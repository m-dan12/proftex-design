"""T09: генерации и галереи. Номера тестов — показатели из карточки T09 (docs/TZ.md, раздел 9).

`current_user` подменяется фикстурой `login_as`, настоящий вход (T08) не нужен.
Провайдер подменяется быстрым `FakeProvider`, кроме теста полного цикла на заглушке.
"""

import asyncio
import io
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from PIL import Image

from app import db as dbmod
from app.config import reset_settings
from app.deps import CurrentUser
from app.services import jobs, pricing
from app.services.provider import ProviderError, ProviderResult
from app.services.storage import get_storage

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "contracts" / "openapi.yaml").read_text(encoding="utf-8"))
MODEL = "gpt-image-1"
FORM = {"prompt": "кот в шляпе", "model": MODEL, "quality": "medium", "size": "1024x1024"}
CAP_TEXT = "дневной бюджет сервиса исчерпан, обратитесь к администратору"


def assert_schema(data: Any, name: str) -> None:
    """Ответ соответствует схеме `name` из contracts/openapi.yaml."""
    schema = {"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]}
    errors = list(Draft202012Validator(schema).iter_errors(data))
    assert not errors, [e.message for e in errors]


def picture(fmt: str = "PNG", color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, fmt)
    return buf.getvalue()


class FakeProvider:
    """Быстрый провайдер со счётчиком одновременных запросов."""

    def __init__(
        self,
        *,
        delay: float = 0.0,
        tokens: tuple[int, int, int] = (101, 0, 1000),
        fail: Exception | None = None,
        count: int | None = None,
    ) -> None:
        self.delay = delay
        self.tokens = tokens
        self.fail = fail
        self.count = count
        self.calls: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0
        self.max_running_db = 0

    async def generate(self, **kwargs: Any) -> ProviderResult:
        self.calls.append(kwargs)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            conn = dbmod.connect()
            try:
                running = conn.execute(
                    "SELECT COUNT(*) FROM generations WHERE status = 'running'"
                ).fetchone()[0]
            finally:
                conn.close()
            self.max_running_db = max(self.max_running_db, running)
            await asyncio.sleep(self.delay)
            if self.fail is not None:
                raise self.fail
            fmt = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}[kwargs["output_format"]]
            n = kwargs["n"] if self.count is None else self.count
            images = [picture(fmt, (i * 60, 100, 50)) for i in range(n)]
            return ProviderResult(images, *self.tokens)
        finally:
            self.active -= 1


@pytest.fixture
def gclient(client: TestClient) -> Iterator[TestClient]:
    """Клиент, который в конце дожидается фоновых задач своего цикла событий."""
    yield client

    async def drain() -> None:
        await jobs.get_runner().drain()

    client.portal.call(drain)


@pytest.fixture
def fake(env: pytest.MonkeyPatch) -> FakeProvider:
    provider = FakeProvider()
    env.setattr(jobs, "get_provider", lambda: provider)
    return provider


def wait_all(client: TestClient, ids: list[int], timeout: float = 15.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while True:
        items = [client.get(f"/api/generations/{gen_id}").json() for gen_id in ids]
        if all(item["status"] in ("done", "error") for item in items):
            return items
        assert time.monotonic() < deadline, [item["status"] for item in items]
        time.sleep(0.05)


def create(client: TestClient, files: list | None = None, **fields: Any) -> Any:
    data = {**FORM, **fields}
    return client.post("/api/generations", data=data, files=files or None)


@pytest.fixture
def done_generation(make_generation: Callable[..., int]) -> Callable[..., int]:
    """Готовая работа с настоящими файлами результата и превью."""

    def factory(user_id: int, **fields: Any) -> int:
        gen_id = make_generation(user_id, **fields)
        storage = get_storage()
        data = picture("JPEG")
        result = storage.save_result(gen_id, data, "jpeg")
        thumb = storage.make_thumb(gen_id, data)
        conn = dbmod.connect()
        with conn:
            conn.execute(
                "UPDATE generations SET result_path = ?, thumb_path = ? WHERE id = ?",
                (result, thumb, gen_id),
            )
        conn.close()
        return gen_id

    return factory


# --- 1. Полный цикл на заглушке ---


def test_1_full_cycle_on_mock(gclient: TestClient, user: CurrentUser, login_as) -> None:
    login_as(user)
    started = time.monotonic()
    response = create(gclient)
    assert response.status_code == 202, response.text
    body = response.json()
    assert_schema(body, "GenerationCreated")
    assert len(body["ids"]) == 1

    pending = gclient.get(f"/api/generations/{body['ids'][0]}").json()
    assert pending["status"] in ("pending", "running")

    [item] = wait_all(gclient, body["ids"], timeout=15)
    assert time.monotonic() - started < 15
    assert item["status"] == "done", item["error"]
    assert_schema(item, "Generation")
    assert item["batch_id"] == body["batch_id"]
    assert item["username"] == user.username
    assert item["finished_at"]
    assert item["output_tokens"] > 0
    expected = pricing.cost(
        MODEL,
        item["input_text_tokens"],
        item["input_image_tokens"],
        item["output_tokens"],
        quality="medium",
    )
    assert item["cost_micro_usd"] == expected > 0

    storage = get_storage()
    gen_id = item["id"]
    assert storage.result_path(gen_id, "jpg").is_file()
    assert storage.thumb_path(gen_id).is_file()

    result = gclient.get(f"/api/generations/{gen_id}/image", params={"kind": "result"})
    assert result.status_code == 200
    assert result.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(result.content)).format == "JPEG"
    thumb = gclient.get(f"/api/generations/{gen_id}/image", params={"kind": "thumb"})
    assert thumb.status_code == 200
    assert thumb.headers["content-type"] == "image/webp"
    download = gclient.get(
        f"/api/generations/{gen_id}/image", params={"kind": "result", "download": "true"}
    )
    assert download.headers["content-disposition"].startswith("attachment")


def test_1_output_format_and_uploaded_reference(
    gclient: TestClient, user: CurrentUser, login_as, fake: FakeProvider
) -> None:
    login_as(user)
    files = [("files", ("ref.png", picture("PNG"), "image/png"))]
    response = create(gclient, files=files, output_format="webp", input_fidelity="low")
    assert response.status_code == 202, response.text
    [item] = wait_all(gclient, response.json()["ids"])
    assert item["status"] == "done"
    assert item["output_format"] == "webp"
    assert item["input_fidelity"] == "low"
    assert item["inputs"] == [{"idx": 0, "filename": "ref.png", "source_generation_id": None}]
    call = fake.calls[0]
    assert call["output_format"] == "webp" and call["input_fidelity"] == "low"
    assert len(call["images"]) == 1 and call["images"][0].startswith(b"\x89PNG")

    image = gclient.get(f"/api/generations/{item['id']}/image", params={"kind": "result"})
    assert image.headers["content-type"] == "image/webp"
    ref = gclient.get(f"/api/generations/{item['id']}/image", params={"kind": "input", "idx": 0})
    assert ref.status_code == 200 and ref.headers["content-type"] == "image/png"
    no_idx = gclient.get(f"/api/generations/{item['id']}/image", params={"kind": "input"})
    assert no_idx.status_code == 422
    missing = gclient.get(
        f"/api/generations/{item['id']}/image", params={"kind": "input", "idx": 5}
    )
    assert missing.status_code == 404


def test_1_input_fidelity_defaults(
    gclient: TestClient, user: CurrentUser, login_as, fake: FakeProvider
) -> None:
    login_as(user)
    files = [("files", ("ref.png", picture("PNG"), "image/png"))]
    with_refs = create(gclient, files=files).json()["ids"]
    without_refs = create(gclient).json()["ids"]
    items = wait_all(gclient, with_refs + without_refs)
    assert items[0]["input_fidelity"] == "high"
    assert items[1]["input_fidelity"] is None


@pytest.mark.parametrize(
    ("fields", "fragment"),
    [
        ({"model": "нет-такой"}, "Неизвестная модель"),
        ({"quality": "ultra"}, "Качество"),
        ({"size": "10x10"}, "Размер"),
        ({"n": "5"}, "Число вариантов"),
        ({"output_format": "gif"}, "Формат"),
        ({"prompt": "x" * 4001}, "4000"),
        ({"prompt": "   "}, "пустым"),
    ],
)
def test_1_invalid_params_422(
    gclient: TestClient, user: CurrentUser, login_as, fake, fields, fragment
) -> None:
    login_as(user)
    response = create(gclient, **fields)
    assert response.status_code == 422
    assert fragment in response.json()["detail"]
    assert_schema(response.json(), "Error")
    assert gclient.get("/api/generations", params={"scope": "mine"}).json()["items"] == []


def test_1_bad_upload_rolls_back(gclient: TestClient, user: CurrentUser, login_as, fake) -> None:
    login_as(user)
    files = [("files", ("fake.png", b"not an image at all", "image/png"))]
    response = create(gclient, files=files, n="2")
    assert response.status_code == 422
    assert "не изображение" in response.json()["detail"]
    assert gclient.get("/api/generations", params={"scope": "mine"}).json()["items"] == []
    assert not list((get_storage().root / "inputs").glob("*/*"))
    assert fake.calls == []


def test_1_too_many_references_422(gclient: TestClient, user: CurrentUser, login_as, fake):
    login_as(user)
    files = [("files", (f"{i}.png", picture("PNG"), "image/png")) for i in range(11)]
    assert create(gclient, files=files).status_code == 422


# --- 1a. N вариантов и деление стоимости ---


def test_1a_three_variants_share_batch_and_cost(
    gclient: TestClient, user: CurrentUser, login_as, fake: FakeProvider
) -> None:
    login_as(user)
    files = [("files", ("ref.jpg", picture("JPEG"), "image/jpeg"))]
    response = create(gclient, files=files, n="3")
    assert response.status_code == 202
    body = response.json()
    assert len(body["ids"]) == 3
    items = wait_all(gclient, body["ids"])

    assert len(fake.calls) == 1 and fake.calls[0]["n"] == 3  # один запрос на пачку
    assert {item["batch_id"] for item in items} == {body["batch_id"]}
    assert [item["variant_idx"] for item in items] == [0, 1, 2]
    assert all(item["status"] == "done" for item in items)

    total = pricing.cost(MODEL, *fake.tokens, quality="medium", n=3)
    costs = [item["cost_micro_usd"] for item in items]
    assert sum(costs) == total
    assert total % 3 != 0  # проверяем именно остаток
    assert costs[1] == costs[2] == total // 3
    assert costs[0] == total // 3 + total % 3
    assert sum(item["input_text_tokens"] for item in items) == fake.tokens[0]
    assert sum(item["output_tokens"] for item in items) == fake.tokens[2]

    # У каждого варианта свой результат и своя копия референсов.
    storage = get_storage()
    for item in items:
        assert storage.result_path(item["id"], "jpg").is_file()
        assert len(item["inputs"]) == 1
        assert storage.find_input(item["id"], 0) is not None


def test_1a_fewer_images_than_requested(
    gclient: TestClient, user: CurrentUser, login_as, fake: FakeProvider
) -> None:
    login_as(user)
    fake.count = 1
    items = wait_all(gclient, create(gclient, n="2").json()["ids"])
    assert [item["status"] for item in items] == ["done", "error"]
    assert items[0]["cost_micro_usd"] == pricing.cost(MODEL, *fake.tokens, quality="medium")
    assert items[1]["cost_micro_usd"] == 0


def test_1a_split_evenly() -> None:
    assert jobs.split_evenly(10, 3) == [4, 3, 3]
    assert jobs.split_evenly(9, 3) == [3, 3, 3]
    assert jobs.split_evenly(0, 4) == [0, 0, 0, 0]
    assert jobs.split_evenly(7, 1) == [7]


# --- 1b. Аварийный дневной потолок ---


def _set_cap(env: pytest.MonkeyPatch, value: str) -> None:
    env.setenv("SPEND_CAP_DAILY_USD", value)
    reset_settings()


def test_1b_cap_reached_429(gclient, user, login_as, fake, env, make_user, make_generation) -> None:
    login_as(user)
    _set_cap(env, "1")
    other = make_user("other")
    make_generation(other.id, cost_micro_usd=600_000, created_at=dbmod.now_iso())
    assert create(gclient).status_code == 202  # 0,6 из 1 — ещё можно
    wait_all(gclient, [g["id"] for g in gclient.get("/api/generations?scope=mine").json()["items"]])

    make_generation(user.id, cost_micro_usd=400_000, created_at=dbmod.now_iso())
    response = create(gclient)
    assert response.status_code == 429
    assert CAP_TEXT in response.json()["detail"].lower()
    assert_schema(response.json(), "Error")


def test_1b_yesterday_not_counted(gclient, user, login_as, fake, env, make_generation) -> None:
    login_as(user)
    _set_cap(env, "1")
    yesterday_msk = "2000-01-01T00:00:00Z"
    make_generation(user.id, cost_micro_usd=5_000_000, created_at=yesterday_msk)
    assert create(gclient).status_code == 202


def test_1b_empty_cap_means_no_limit(gclient, user, login_as, fake, env, make_generation) -> None:
    login_as(user)
    _set_cap(env, "")
    make_generation(user.id, cost_micro_usd=10**12, created_at=dbmod.now_iso())
    assert create(gclient).status_code == 202


def test_1b_moscow_day_boundary(db: sqlite3.Connection, make_user, make_generation) -> None:
    # 22:30 UTC 30 октября = 01:30 31 октября по Москве: сутки начались в 21:00 UTC.
    now = datetime(2026, 10, 30, 22, 30, tzinfo=UTC)
    assert jobs.moscow_day_start_utc(now) == "2026-10-30T21:00:00Z"
    assert jobs.moscow_day_start_utc(datetime(2026, 10, 30, 20, 0, tzinfo=UTC)) == (
        "2026-10-29T21:00:00Z"
    )
    who = make_user()
    make_generation(who.id, cost_micro_usd=7, created_at="2026-10-30T20:59:59Z")
    make_generation(who.id, cost_micro_usd=5, created_at="2026-10-30T21:00:00Z")
    assert jobs.spent_today_micro_usd(db, now) == 5


# --- 2. Не больше MAX_PARALLEL одновременно ---


def test_2_six_requests_at_most_four_running(
    gclient: TestClient, user: CurrentUser, login_as, fake: FakeProvider
) -> None:
    login_as(user)
    fake.delay = 0.4
    ids = []
    for _ in range(6):
        response = create(gclient)
        assert response.status_code == 202
        ids += response.json()["ids"]
    statuses = [gclient.get(f"/api/generations/{i}").json()["status"] for i in ids]
    assert statuses.count("running") <= 4

    items = wait_all(gclient, ids)
    assert all(item["status"] == "done" for item in items)
    assert fake.max_active == 4  # очередь реально работает параллельно, но не шире 4
    assert fake.max_running_db <= 4


def test_2_max_parallel_from_env(gclient, user, login_as, fake, env) -> None:
    env.setenv("MAX_PARALLEL", "2")
    reset_settings()
    login_as(user)
    fake.delay = 0.2
    ids = [create(gclient).json()["ids"][0] for _ in range(4)]
    wait_all(gclient, ids)
    assert fake.max_active == 2


# --- 3. Ошибка провайдера ---


def test_3_provider_error(gclient, user, login_as, fake: FakeProvider) -> None:
    login_as(user)
    fake.fail = ProviderError("Запрос отклонён модерацией OpenAI. Измените промпт.")
    items = wait_all(gclient, create(gclient, n="2").json()["ids"])
    for item in items:
        assert item["status"] == "error"
        assert item["cost_micro_usd"] == 0
        assert item["error"] == "Запрос отклонён модерацией OpenAI. Измените промпт."
        assert item["finished_at"]
        assert_schema(item, "Generation")
    result = gclient.get(f"/api/generations/{items[0]['id']}/image", params={"kind": "result"})
    assert result.status_code == 404


def test_3_unexpected_error_is_hidden(gclient, user, login_as, fake: FakeProvider) -> None:
    login_as(user)
    fake.fail = RuntimeError("sk-secret внутренняя трассировка")
    [item] = wait_all(gclient, create(gclient).json()["ids"])
    assert item["status"] == "error"
    assert item["error"] == jobs.ERR_INTERNAL
    assert item["cost_micro_usd"] == 0


# --- 4. Референсы из галереи и parent_id ---


def test_4_foreign_private_source_rejected(
    gclient, user, login_as, fake, make_user, done_generation
) -> None:
    other = make_user("other")
    private = done_generation(other.id, shared=0)
    login_as(user)
    response = create(gclient, source_ids=[str(private)])
    assert response.status_code == 404
    assert_schema(response.json(), "Error")
    missing = create(gclient, source_ids=["99999"])
    assert missing.status_code == 404
    assert fake.calls == []


def test_4_shared_source_and_parent_id(
    gclient, user, login_as, fake, make_user, done_generation
) -> None:
    other = make_user("other")
    shared = done_generation(other.id, shared=1)
    own_private = done_generation(user.id, shared=0)
    login_as(user)
    files = [("files", ("up.webp", picture("WEBP"), "image/webp"))]
    response = create(
        gclient,
        files=files,
        source_ids=[str(shared), str(own_private)],
        parent_id=str(shared),
    )
    assert response.status_code == 202, response.text
    [item] = wait_all(gclient, response.json()["ids"])
    assert item["status"] == "done"
    assert item["parent_id"] == shared
    assert item["inputs"] == [
        {"idx": 0, "filename": "up.webp", "source_generation_id": None},
        {"idx": 1, "filename": None, "source_generation_id": shared},
        {"idx": 2, "filename": None, "source_generation_id": own_private},
    ]
    assert len(fake.calls[0]["images"]) == 3
    ref = gclient.get(f"/api/generations/{item['id']}/image", params={"kind": "input", "idx": 1})
    assert ref.status_code == 200


def test_4_parent_must_be_in_sources(gclient, user, login_as, fake, done_generation) -> None:
    own = done_generation(user.id)
    login_as(user)
    response = create(gclient, parent_id=str(own))
    assert response.status_code == 422
    assert "source_ids" in response.json()["detail"]


def test_4_unfinished_source_rejected(gclient, user, login_as, fake, make_generation) -> None:
    pending = make_generation(user.id, status="error")
    login_as(user)
    assert create(gclient, source_ids=[str(pending)]).status_code == 422


# --- 5. Права на просмотр (NFR-05) ---


def test_5_foreign_private_is_404_admin_sees(
    gclient, user, admin, login_as, make_user, done_generation
) -> None:
    other = make_user("other")
    private = done_generation(other.id, shared=0)
    public = done_generation(other.id, shared=1)

    login_as(user)
    assert gclient.get(f"/api/generations/{private}").status_code == 404
    for kind in ("result", "thumb"):
        url = f"/api/generations/{private}/image"
        assert gclient.get(url, params={"kind": kind}).status_code == 404
    assert gclient.get(f"/api/generations/{public}").status_code == 200
    assert gclient.get(f"/api/generations/{public}/image?kind=thumb").status_code == 200
    assert gclient.get("/api/generations/424242").status_code == 404

    login_as(admin)
    card = gclient.get(f"/api/generations/{private}")
    assert card.status_code == 200
    assert_schema(card.json(), "Generation")
    assert gclient.get(f"/api/generations/{private}/image?kind=result").status_code == 200

    login_as(other)
    assert gclient.get(f"/api/generations/{private}").status_code == 200


def test_5_missing_file_404(gclient, user, login_as, make_generation) -> None:
    gen_id = make_generation(user.id, result_path="results/999.jpg")
    login_as(user)
    assert gclient.get(f"/api/generations/{gen_id}/image?kind=result").status_code == 404
    assert gclient.get(f"/api/generations/{gen_id}/image?kind=thumb").status_code == 404


# --- 6. Флаг «Видна всем» ---


def test_6_new_generation_shared_by_default(gclient, user, login_as, fake) -> None:
    login_as(user)
    [item] = wait_all(gclient, create(gclient).json()["ids"])
    assert item["shared"] is True
    [private] = wait_all(gclient, create(gclient, shared="false").json()["ids"])
    assert private["shared"] is False


def test_6_patch_shared_rights(gclient, user, admin, login_as, make_user, make_generation) -> None:
    other = make_user("other")
    gen_id = make_generation(other.id, shared=1)

    login_as(user)
    response = gclient.patch(f"/api/generations/{gen_id}", json={"shared": False})
    assert response.status_code == 403
    assert_schema(response.json(), "Error")

    login_as(other)
    response = gclient.patch(f"/api/generations/{gen_id}", json={"shared": False})
    assert response.status_code == 200
    assert response.json()["shared"] is False
    assert_schema(response.json(), "Generation")

    login_as(user)  # теперь работа приватная: для чужого её нет
    assert gclient.patch(f"/api/generations/{gen_id}", json={"shared": True}).status_code == 404

    login_as(admin)
    response = gclient.patch(f"/api/generations/{gen_id}", json={"shared": True})
    assert response.status_code == 200 and response.json()["shared"] is True
    assert gclient.patch(f"/api/generations/{gen_id}", json={}).status_code == 422
    assert gclient.patch(f"/api/generations/{gen_id}", json={"shared": "yes"}).status_code == 422


# --- 7. Пагинация ---


def test_7_pagination_120(gclient, user, login_as, make_user, make_generation) -> None:
    other = make_user("other")
    mine = [make_generation(user.id, shared=i % 2) for i in range(120)]
    make_generation(other.id, shared=0)
    login_as(user)

    seen: list[int] = []
    cursor = None
    pages = []
    while True:
        params = {"scope": "mine", **({"cursor": cursor} if cursor else {})}
        response = gclient.get("/api/generations", params=params)
        assert response.status_code == 200
        body = response.json()
        assert_schema(body, "GenerationList")
        pages.append(len(body["items"]))
        seen += [item["id"] for item in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == [50, 50, 20]
    assert seen == sorted(mine, reverse=True)  # от новых к старым, без дублей и пропусков

    small = gclient.get("/api/generations", params={"scope": "mine", "limit": 7}).json()
    assert len(small["items"]) == 7 and small["next_cursor"] == str(small["items"][-1]["id"])
    assert gclient.get("/api/generations?scope=mine&limit=51").status_code == 422
    assert gclient.get("/api/generations?scope=mine&cursor=abc").status_code == 422
    assert gclient.get("/api/generations?scope=all").status_code == 422


def test_7_shared_scope_and_author_filter(
    gclient, user, login_as, make_user, make_generation
) -> None:
    other = make_user("other")
    a = make_generation(user.id, shared=1)
    make_generation(user.id, shared=0)
    b = make_generation(other.id, shared=1)
    make_generation(other.id, shared=0)
    make_generation(other.id, shared=1, status="error")
    login_as(user)

    body = gclient.get("/api/generations", params={"scope": "shared"}).json()
    assert [item["id"] for item in body["items"]] == [b, a]
    assert body["next_cursor"] is None
    by_author = gclient.get("/api/generations", params={"scope": "shared", "author_id": other.id})
    assert [item["id"] for item in by_author.json()["items"]] == [b]
    assert by_author.json()["items"][0]["username"] == "other"


# --- Удаление (FR-11) ---


def test_delete_rights_and_files(
    gclient, user, admin, login_as, make_user, done_generation, make_generation
) -> None:
    other = make_user("other")
    own = done_generation(user.id)
    foreign = done_generation(other.id, shared=1)
    running = make_generation(user.id, status="running")
    storage = get_storage()

    login_as(user)
    assert gclient.delete(f"/api/generations/{foreign}").status_code == 403
    assert gclient.delete(f"/api/generations/{running}").status_code == 409
    assert gclient.delete(f"/api/generations/{own}").status_code == 204
    assert gclient.get(f"/api/generations/{own}").status_code == 404
    assert storage.find_result(own) is None
    assert not storage.thumb_path(own).exists()

    login_as(admin)
    assert gclient.delete(f"/api/generations/{foreign}").status_code == 204
    assert gclient.delete(f"/api/generations/{foreign}").status_code == 404


def test_delete_variant_keeps_sibling_inputs(gclient, user, login_as, fake) -> None:
    login_as(user)
    files = [("files", ("ref.png", picture("PNG"), "image/png"))]
    first, second = wait_all(gclient, create(gclient, files=files, n="2").json()["ids"])
    assert gclient.delete(f"/api/generations/{first['id']}").status_code == 204
    ref = gclient.get(f"/api/generations/{second['id']}/image", params={"kind": "input", "idx": 0})
    assert ref.status_code == 200


# --- NFR-09: прерванные задачи после перезапуска ---


def test_nfr09_restart_marks_interrupted(app, user, make_generation) -> None:
    pending = make_generation(user.id, status="pending")
    running = make_generation(user.id, status="running")
    with TestClient(app):
        pass
    conn = dbmod.connect()
    rows = conn.execute(
        "SELECT status, error, cost_micro_usd FROM generations WHERE id IN (?, ?)",
        (pending, running),
    ).fetchall()
    conn.close()
    assert [tuple(row) for row in rows] == [("error", dbmod.INTERRUPTED_ERROR, 0)] * 2
