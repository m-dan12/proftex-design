"""T04: каталог моделей, стоимость в микродолларах, проверка параметров, `GET /api/models`."""

import copy
import json
import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.deps import CurrentUser, current_user
from app.main import app
from app.routers.models import check_params
from app.services import pricing

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SPEC = yaml.safe_load((ROOT / "contracts" / "openapi.yaml").read_text(encoding="utf-8"))

MODEL = {
    "id": "test-model",
    "title": "Тестовая",
    "qualities": ["low", "high"],
    "default_quality": "high",
    "sizes": ["auto", "1024x1024"],
    "output_formats": ["jpeg", "png"],
    "supports_input_fidelity": True,
    "max_n": 3,
    "prices_usd_per_1m_tokens": {"text_in": 5, "image_in": 8, "image_out": 32},
    "fallback_per_image_usd": {"low": Decimal("0.011"), "high": Decimal("0.167")},
}
NO_FIDELITY = {**MODEL, "id": "no-fidelity", "supports_input_fidelity": False}
DATA = {"default_model": "test-model", "models": [MODEL, NO_FIDELITY]}


@pytest.fixture
def catalog() -> pricing.Catalog:
    return pricing.parse_catalog(copy.deepcopy(DATA))


def _broken(**changes) -> dict:
    data = copy.deepcopy(DATA)
    model = data["models"][0]
    for key, value in changes.items():
        if value is None:
            model.pop(key)
        else:
            model[key] = value
    return data


# --- 1. стоимость ---


def test_cost_by_tokens_is_exact(catalog: pricing.Catalog) -> None:
    # 1000 × 5 + 3000 × 8 + 2000 × 32 = 5000 + 24000 + 64000 микродолларов.
    result = pricing.cost("test-model", 1000, 3000, 2000, catalog=catalog)
    assert result == 93000
    assert isinstance(result, int)


def test_cost_without_tokens_uses_fallback(catalog: pricing.Catalog) -> None:
    assert pricing.cost("test-model", None, None, None, quality="low", catalog=catalog) == 11000
    assert pricing.cost("test-model", 0, 0, 0, quality="high", n=3, catalog=catalog) == 501000
    # Без качества — default_quality модели.
    assert pricing.cost("test-model", None, None, None, catalog=catalog) == 167000


def test_cost_rounds_to_micro_usd(catalog: pricing.Catalog) -> None:
    # 1 выходной токен × 32 USD/млн = 32 микродоллара; 1 текстовый × 5 = 5; сумма 37.
    assert pricing.cost("test-model", 1, 0, 1, catalog=catalog) == 37
    data = copy.deepcopy(DATA)
    data["models"][0]["prices_usd_per_1m_tokens"]["image_out"] = Decimal("2.5")
    cheap = pricing.parse_catalog(data)
    # 1 × 2,5 = 2,5 микродоллара → 3 (половина вверх); 3 × 2,5 = 7,5 → 8.
    assert pricing.cost("test-model", 0, 0, 1, catalog=cheap) == 3
    assert pricing.cost("test-model", 0, 0, 3, catalog=cheap) == 8


def test_cost_rejects_negative_tokens(catalog: pricing.Catalog) -> None:
    with pytest.raises(ValueError):
        pricing.cost("test-model", -1, 0, 10, catalog=catalog)


def test_real_models_json_loads() -> None:
    catalog = pricing.load_catalog()
    assert catalog.default_model in catalog.models
    for spec in catalog.models.values():
        assert spec.default_quality in spec.qualities
        assert pricing.cost(spec.id, 1000, 1000, 1000) > 0


# --- 2. проверка параметров → 422 ---

OK = {
    "model": "test-model",
    "quality": "high",
    "size": "1024x1024",
    "output_format": "png",
}


def test_valid_params_pass(catalog: pricing.Catalog) -> None:
    spec = pricing.validate_params(**OK, input_fidelity="high", n=3, catalog=catalog)
    assert spec.id == "test-model"
    pricing.validate_params(**{**OK, "model": "no-fidelity"}, catalog=catalog)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"model": "dall-e-9"}, "Неизвестная модель"),
        ({"quality": "max"}, "Качество"),
        ({"size": "4096x4096"}, "Размер"),
        ({"output_format": "webp"}, "Формат"),
        ({"model": "no-fidelity", "input_fidelity": "high"}, "input_fidelity"),
        ({"input_fidelity": "medium"}, "input_fidelity"),
        ({"n": 4}, "вариантов"),
        ({"n": 0}, "вариантов"),
    ],
)
def test_invalid_params_raise(catalog: pricing.Catalog, change: dict, message: str) -> None:
    with pytest.raises(pricing.ParamError, match=message):
        pricing.validate_params(**{**OK, **change}, catalog=catalog)


def test_router_turns_param_error_into_422() -> None:
    probe = FastAPI()

    @probe.post("/probe")
    def handler(model: str, quality: str, n: int = 1) -> dict:
        spec = check_params(model=model, quality=quality, size="auto", output_format="png", n=n)
        return {"model": spec.id}

    client = TestClient(probe)
    real = pricing.get_catalog().default_model
    assert client.post("/probe", params={"model": real, "quality": "low"}).status_code == 200
    for params in (
        {"model": "dall-e-9", "quality": "low"},
        {"model": real, "quality": "ultra"},
        {"model": real, "quality": "low", "n": 99},
    ):
        response = client.post("/probe", params=params)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)


# --- 3. повреждённый models.json ---


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (_broken(id=None), "«id»"),
        (
            _broken(prices_usd_per_1m_tokens={"text_in": -1, "image_in": 8, "image_out": 32}),
            "отриц",
        ),
        (_broken(fallback_per_image_usd={"low": Decimal("-0.01"), "high": 1}), "отриц"),
        (_broken(prices_usd_per_1m_tokens={"text_in": 5, "image_in": 8}), "image_out"),
        (
            _broken(prices_usd_per_1m_tokens={"text_in": "5", "image_in": 8, "image_out": 32}),
            "числом",
        ),
        (_broken(fallback_per_image_usd={"low": 1}), "high"),
        (_broken(default_quality="ultra"), "default_quality"),
        (_broken(output_formats=["gif"]), "форматы"),
        (_broken(max_n=5), "max_n"),
        (_broken(supports_input_fidelity="yes"), "supports_input_fidelity"),
        (_broken(sizes=[]), "sizes"),
        ({**DATA, "default_model": "nope"}, "default_model"),
        ({**DATA, "models": [MODEL, MODEL]}, "дважды"),
        ({"default_model": "x", "models": []}, "models"),
    ],
)
def test_broken_catalog_is_rejected(data: dict, message: str) -> None:
    with pytest.raises(pricing.ModelsConfigError, match=message) as info:
        pricing.parse_catalog(data)
    assert str(info.value).startswith("models.json")


def test_unreadable_files(tmp_path: Path) -> None:
    with pytest.raises(pricing.ModelsConfigError, match="не читается"):
        pricing.load_catalog(tmp_path / "missing.json")
    bad = tmp_path / "models.json"
    bad.write_text("{oops", encoding="utf-8")
    with pytest.raises(pricing.ModelsConfigError, match="не JSON"):
        pricing.load_catalog(bad)


def _start_app(models_file: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "MODELS_FILE": str(models_file)}
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_app_does_not_start_with_broken_models_json(tmp_path: Path) -> None:
    data = json.loads((ROOT / "models.json").read_text(encoding="utf-8"))
    del data["models"][0]["id"]
    bad = tmp_path / "models.json"
    bad.write_text(json.dumps(data), encoding="utf-8")

    result = _start_app(bad)
    assert result.returncode != 0
    assert "ModelsConfigError" in result.stderr
    assert "поле «id» обязательно" in result.stderr


def test_app_starts_with_valid_models_json() -> None:
    result = _start_app(ROOT / "models.json")
    assert result.returncode == 0, result.stderr


# --- 4. GET /api/models по контракту ---


def _response_schema() -> Draft202012Validator:
    schema = SPEC["paths"]["/api/models"]["get"]["responses"]["200"]["content"]
    schema = schema["application/json"]["schema"]
    return Draft202012Validator({**schema, "components": SPEC["components"]})


@pytest.fixture
def client():
    app.dependency_overrides[current_user] = lambda: CurrentUser(1, "designer", False)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_models_endpoint_matches_contract(client: TestClient, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.get("/api/models")
    assert response.status_code == 200
    body = response.json()
    errors = [error.message for error in _response_schema().iter_errors(body)]
    assert errors == []

    catalog = pricing.get_catalog()
    assert body["mode"] == "mock"
    assert body["default_model"] == catalog.default_model
    assert [model["id"] for model in body["models"]] == list(catalog.models)
    for model in body["models"]:
        assert "prices_usd_per_1m_tokens" not in model
        assert all(isinstance(v, int) for v in model["fallback_per_image_micro_usd"].values())


def test_models_endpoint_mode_openai(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert client.get("/api/models").json()["mode"] == "openai"


def test_models_endpoint_requires_login() -> None:
    def no_session() -> CurrentUser:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Нужен вход")

    app.dependency_overrides[current_user] = no_session
    try:
        assert TestClient(app).get("/api/models").status_code == 401
    finally:
        app.dependency_overrides.clear()


# --- 5. цены только в models.json ---


def test_no_prices_in_code() -> None:
    price = re.compile(r"(?<![\d.])(5|8|32)\.0(?!\d)")
    hits = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in (BACKEND / "app").rglob("*.py")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if price.search(line)
    ]
    assert hits == []
