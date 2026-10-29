"""T05: провайдер изображений. Сеть в этих тестах запрещена (критерий 5)."""

import asyncio
import io
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest
from PIL import Image

from app.services import provider as prov
from app.services.provider import (
    MockProvider,
    ModelCaps,
    OpenAIProvider,
    ProviderError,
    ProviderResult,
    load_caps,
    make_provider,
)

MODELS_JSON = Path(__file__).resolve().parents[2] / "models.json"
FAKE_KEY = "sk-test-" + "x" * 40
CAPS = {
    "full": ModelCaps(supports_input_fidelity=True, max_n=4, output_formats=("jpeg", "png")),
    "bare": ModelCaps(),
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("сеть в тестах запрещена")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def run(coro):
    return asyncio.run(coro)


def png(width=8, height=8, fmt="PNG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(out, format=fmt)
    return out.getvalue()


def response(count=1, usage=True, details=True):
    import base64

    data = [SimpleNamespace(b64_json=base64.b64encode(png()).decode()) for _ in range(count)]
    if not usage:
        return SimpleNamespace(data=data, usage=None)
    input_details = SimpleNamespace(text_tokens=40, image_tokens=600) if details else None
    return SimpleNamespace(
        data=data,
        usage=SimpleNamespace(
            input_tokens=640, input_tokens_details=input_details, output_tokens=4160
        ),
    )


class FakeImages:
    """Подменённый ``client.images``: отдаёт ответы или бросает ошибки по очереди."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes) or [response()]
        self.calls: list[tuple[str, dict]] = []

    async def _next(self, method, kwargs):
        self.calls.append((method, kwargs))
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def generate(self, **kwargs):
        return await self._next("generate", kwargs)

    async def edit(self, **kwargs):
        return await self._next("edit", kwargs)


def provider_with(*outcomes):
    images = FakeImages(*outcomes)
    sleeps: list[float] = []

    async def sleep(seconds):
        sleeps.append(seconds)

    client = SimpleNamespace(images=images)
    return OpenAIProvider(caps=CAPS, client=client, sleep=sleep), images, sleeps


def status_error(cls, status, code=None, message="boom"):
    request = SimpleNamespace(method="POST", url="https://api.openai.com/v1/images/edits")
    resp = SimpleNamespace(status_code=status, headers={}, request=request)
    body = {"message": message, "code": code, "type": "x", "param": None}
    return cls(message, response=resp, body=body)


def rate_limit():
    return status_error(openai.RateLimitError, 429, code="rate_limit_exceeded")


# --- 0. Сеть действительно закрыта ---------------------------------------------------


def test_sockets_are_blocked():
    with pytest.raises(RuntimeError, match="запрещена"):
        socket.create_connection(("api.openai.com", 443))


# --- 1. Заглушка ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "fmt", "expected_size", "pil"),
    [
        ("auto", "jpeg", (1024, 1024), "JPEG"),
        ("1536x1024", "png", (1536, 1024), "PNG"),
        ("1024x1536", "webp", (1024, 1536), "WEBP"),
    ],
)
def test_mock_size_and_format(size, fmt, expected_size, pil):
    result = run(MockProvider(delay=(0, 0)).generate("m", "кот", "high", size, [], 1, None, fmt))
    assert len(result.images) == 1
    picture = Image.open(io.BytesIO(result.images[0]))
    assert picture.size == expected_size
    assert picture.format == pil


def test_mock_n_variants_and_tokens():
    result = run(
        MockProvider(delay=(0, 0)).generate("m", "кот в шляпе", "low", "auto", [png()], n=3)
    )
    assert isinstance(result, ProviderResult)
    assert len(result.images) == 3
    assert len(set(result.images)) == 3  # варианты различаются
    assert result.text_in_tokens > 0
    assert result.image_in_tokens > 0
    assert result.output_tokens > 0


def test_mock_delay_in_range(monkeypatch):
    waited = []

    async def fake_sleep(seconds):
        waited.append(seconds)

    monkeypatch.setattr(prov.asyncio, "sleep", fake_sleep)
    for _ in range(20):
        run(MockProvider().generate("m", "p", "low", "1024x1024", []))
    assert all(2 <= s <= 5 for s in waited)


# --- 2. Выбор метода, параметры, usage ------------------------------------------------


def test_generate_without_references():
    p, images, _ = provider_with(response(count=2))
    result = run(p.generate("full", "кот", "high", "1024x1024", [], 2, "high", "png"))
    [(method, kwargs)] = images.calls
    assert method == "generate"
    assert kwargs["n"] == 2
    assert kwargs["output_format"] == "png"
    assert "input_fidelity" not in kwargs  # у generate такого параметра нет
    assert kwargs["timeout"] == 300
    assert len(result.images) == 2
    assert Image.open(io.BytesIO(result.images[0])).format == "PNG"


def test_edit_with_n_references():
    refs = [png(), png(fmt="JPEG"), png(fmt="WEBP")]
    p, images, _ = provider_with(response())
    result = run(p.generate("full", "кот", "high", "auto", refs, 1, "high", "jpeg"))
    [(method, kwargs)] = images.calls
    assert method == "edit"
    assert [f[0] for f in kwargs["image"]] == ["ref0.png", "ref1.jpg", "ref2.webp"]
    assert [f[1] for f in kwargs["image"]] == refs
    assert [f[2] for f in kwargs["image"]] == ["image/png", "image/jpeg", "image/webp"]
    assert kwargs["input_fidelity"] == "high"
    assert "n" not in kwargs  # n=1 — значение по умолчанию
    assert (result.text_in_tokens, result.image_in_tokens, result.output_tokens) == (
        40,
        600,
        4160,
    )


def test_unsupported_params_not_sent():
    p, images, _ = provider_with(response())
    run(p.generate("bare", "кот", "low", "auto", [png()], 3, "high", "webp"))
    [(_, kwargs)] = images.calls
    assert not {"n", "input_fidelity", "output_format"} & kwargs.keys()


def test_usage_without_details_and_without_usage():
    p, _, _ = provider_with(response(details=False))
    result = run(p.generate("full", "кот", "low", "auto", []))
    assert (result.text_in_tokens, result.image_in_tokens, result.output_tokens) == (640, 0, 4160)

    p, _, _ = provider_with(response(usage=False))
    result = run(p.generate("full", "кот", "low", "auto", []))
    assert (result.text_in_tokens, result.image_in_tokens, result.output_tokens) == (0, 0, 0)


def test_empty_response_is_error():
    p, _, _ = provider_with(SimpleNamespace(data=[], usage=None))
    with pytest.raises(ProviderError, match="не вернул"):
        run(p.generate("full", "кот", "low", "auto", []))


# --- 3. Ошибки → понятный текст ------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (rate_limit(), prov.ERR_RATE_LIMIT),
        (status_error(openai.RateLimitError, 429, "insufficient_quota"), prov.ERR_QUOTA),
        (status_error(openai.BadRequestError, 400, "moderation_blocked"), prov.ERR_MODERATION),
        (
            status_error(
                openai.BadRequestError, 400, None, "Your request was rejected by the safety system"
            ),
            prov.ERR_MODERATION,
        ),
        (status_error(openai.AuthenticationError, 401, "invalid_api_key"), prov.ERR_AUTH),
        (status_error(openai.NotFoundError, 404, "model_not_found"), prov.ERR_MODEL),
        (status_error(openai.PermissionDeniedError, 403), prov.ERR_MODEL),
        (status_error(openai.InternalServerError, 503), prov.ERR_SERVER),
        (status_error(openai.BadRequestError, 400, "invalid_value"), prov.ERR_BAD_REQUEST),
        (openai.APITimeoutError(request=SimpleNamespace()), prov.ERR_TIMEOUT),
        (openai.APIConnectionError(request=SimpleNamespace()), prov.ERR_CONNECTION),
    ],
)
def test_errors_translated(error, expected, caplog):
    # Ключ в тексте ошибки OpenAI не должен дойти до пользователя или логов.
    error.message = f"Incorrect API key provided: {FAKE_KEY}. {error.message}"
    error.args = (error.message,)
    p, _, _ = provider_with(error)
    with pytest.raises(ProviderError) as info:
        run(p.generate("full", "кот", "low", "auto", []))
    text = str(info.value)
    assert text == expected
    assert any("а" <= ch <= "я" for ch in text.lower())
    assert FAKE_KEY not in text
    assert "Traceback" not in text
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__
    assert FAKE_KEY not in caplog.text


# --- 4. Повторы ----------------------------------------------------------------------


def test_one_retry_on_429_then_success():
    p, images, sleeps = provider_with(rate_limit(), response())
    result = run(p.generate("full", "кот", "low", "auto", []))
    assert len(images.calls) == 2
    assert sleeps == [prov.RETRY_DELAY_S]
    assert len(result.images) == 1


def test_two_429_in_a_row_fail():
    p, images, _ = provider_with(rate_limit(), rate_limit(), response())
    with pytest.raises(ProviderError, match="частоту"):
        run(p.generate("full", "кот", "low", "auto", []))
    assert len(images.calls) == 2


def test_retry_on_5xx():
    p, images, _ = provider_with(status_error(openai.InternalServerError, 500), response())
    run(p.generate("full", "кот", "low", "auto", [png()]))
    assert [m for m, _ in images.calls] == ["edit", "edit"]


@pytest.mark.parametrize(
    "error",
    [
        status_error(openai.RateLimitError, 429, "insufficient_quota"),
        status_error(openai.BadRequestError, 400, "moderation_blocked"),
        status_error(openai.AuthenticationError, 401),
    ],
)
def test_no_retry_on_final_errors(error):
    p, images, _ = provider_with(error, response())
    with pytest.raises(ProviderError):
        run(p.generate("full", "кот", "low", "auto", []))
    assert len(images.calls) == 1


# --- Режим и models.json -------------------------------------------------------------


def test_make_provider_mode():
    assert isinstance(make_provider(None), MockProvider)
    assert isinstance(make_provider(""), MockProvider)
    real = make_provider(FAKE_KEY, MODELS_JSON)
    assert isinstance(real, OpenAIProvider)
    assert real._client.max_retries == 0  # повторы — только свои, ровно один
    assert real._client.timeout == 300


def test_load_caps_from_models_json():
    caps = load_caps(MODELS_JSON)
    models = json.loads(MODELS_JSON.read_text(encoding="utf-8"))["models"]
    assert set(caps) == {m["id"] for m in models}
    for m in models:
        assert caps[m["id"]].supports_input_fidelity == m["supports_input_fidelity"]
        assert caps[m["id"]].max_n == m["max_n"]
        assert set(caps[m["id"]].output_formats) == set(m["output_formats"])
