"""T10: расходы — «Мои расходы», сводка администратора и CSV."""

import csv
import io
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from openapi_schema_validator import OAS31Validator

from app.deps import CurrentUser, current_user

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "contracts" / "openapi.yaml").read_text(encoding="utf-8"))
MODELS = ("gpt-image-2.5-sunburst", "gpt-image-1", "gpt-image-1-mini")
PERIOD = {"from": "2026-10-01", "to": "2026-10-31"}
MSK = timedelta(hours=3)


def assert_schema(body: object, name: str) -> None:
    schema = {"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]}
    OAS31Validator(schema).validate(body)


def utc(msk_text: str) -> str:
    """Московское время «2026-10-05 23:30» в формате базы (UTC)."""
    moment = datetime.strptime(msk_text, "%Y-%m-%d %H:%M") - MSK
    return moment.replace(tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def as_user(app):
    """Подменить `current_user` (T08 делается параллельно, настоящий вход не нужен)."""

    def switch(who: CurrentUser) -> None:
        app.dependency_overrides[current_user] = lambda: who

    return switch


@pytest.fixture
def dataset(client, make_user, make_generation):
    """3 пользователя, 30 работ; эталон считается независимо от роутера."""
    users = [make_user("anna"), make_user("boris"), make_user("boss", is_admin=True)]
    expected = {
        "total": 0,
        "count": 0,
        "user": defaultdict(int),
        "model": defaultdict(int),
        "day": defaultdict(int),
        "user_count": defaultdict(int),
        "mine": defaultdict(int),
    }
    for i in range(30):
        owner = users[i % 3]
        model = MODELS[i % len(MODELS)]
        status = "error" if i % 7 == 3 else "done"
        cost = 12_345 * (i + 1) + 7
        day = f"2026-10-{1 + i % 9:02d}"
        hour = (i * 5) % 24
        make_generation(
            owner.id,
            model=model,
            status=status,
            # У ошибки стоимость в базе 0; проверяем и случай, если там осталось число.
            cost_micro_usd=cost,
            created_at=utc(f"{day} {hour:02d}:{i % 60:02d}"),
        )
        counted = 0 if status == "error" else cost
        expected["total"] += counted
        expected["count"] += 1
        expected["user"][str(owner.id)] += counted
        expected["user_count"][str(owner.id)] += 1
        expected["model"][model] += counted
        expected["day"][day] += counted
        if owner is users[0]:
            expected["mine"][day] += counted
    # Вне периода — не должно попасть никуда.
    make_generation(users[0].id, cost_micro_usd=999_999, created_at=utc("2026-09-30 23:59"))
    make_generation(users[0].id, cost_micro_usd=999_999, created_at=utc("2026-11-01 00:00"))
    return users, expected


def as_map(rows: list[dict]) -> dict[str, int]:
    return {row["key"]: row["cost_micro_usd"] for row in rows}


# 1, 2, 7
@pytest.mark.parametrize("group", ["user", "model", "day"])
def test_admin_sums_match_reference(client, as_user, dataset, group):
    users, expected = dataset
    as_user(users[2])
    response = client.get("/api/admin/spending", params={**PERIOD, "group": group})
    assert response.status_code == 200, response.text
    body = response.json()
    assert_schema(body, "AdminSpending")
    assert body["total_micro_usd"] == expected["total"]
    assert body["count"] == expected["count"] == 30
    assert as_map(body["rows"]) == dict(expected[group])
    # 2: сумма групп равна итогу, число работ тоже.
    assert sum(r["cost_micro_usd"] for r in body["rows"]) == body["total_micro_usd"]
    assert sum(r["count"] for r in body["rows"]) == body["count"]


def test_admin_labels(client, as_user, dataset):
    users, expected = dataset
    as_user(users[2])
    by_user = client.get("/api/admin/spending", params={**PERIOD, "group": "user"}).json()
    labels = {r["key"]: r["label"] for r in by_user["rows"]}
    assert labels == {str(u.id): u.username for u in users}
    assert {r["key"]: r["count"] for r in by_user["rows"]} == dict(expected["user_count"])
    by_model = client.get("/api/admin/spending", params={**PERIOD, "group": "model"}).json()
    assert {r["key"]: r["label"] for r in by_model["rows"]}["gpt-image-1"] == (
        "GPT Image 1 (запасная)"
    )
    by_day = client.get("/api/admin/spending", params={**PERIOD, "group": "day"}).json()
    keys = [r["key"] for r in by_day["rows"]]
    assert keys == sorted(keys)


# 1, 7
def test_my_spending(client, as_user, dataset):
    users, expected = dataset
    as_user(users[0])
    response = client.get("/api/spending/me", params=PERIOD)
    assert response.status_code == 200, response.text
    body = response.json()
    assert_schema(body, "MySpending")
    assert body["from"] == PERIOD["from"] and body["to"] == PERIOD["to"]
    assert as_map(body["by_day"]) == dict(expected["mine"])
    assert body["total_micro_usd"] == expected["user"][str(users[0].id)]
    assert body["count"] == 10
    assert sum(r["cost_micro_usd"] for r in body["by_model"]) == body["total_micro_usd"]
    assert sum(r["cost_micro_usd"] for r in body["by_day"]) == body["total_micro_usd"]


# 3
def test_error_counts_as_zero(client, as_user, user, make_generation):
    make_generation(
        user.id, status="done", cost_micro_usd=40_000, created_at=utc("2026-10-02 12:00")
    )
    make_generation(user.id, status="error", cost_micro_usd=0, created_at=utc("2026-10-02 12:05"))
    make_generation(
        user.id, status="error", cost_micro_usd=55_555, created_at=utc("2026-10-02 12:10")
    )
    as_user(user)
    body = client.get("/api/spending/me", params=PERIOD).json()
    assert body["total_micro_usd"] == 40_000
    assert body["count"] == 3
    assert body["by_day"] == [
        {"key": "2026-10-02", "label": "2026-10-02", "count": 3, "cost_micro_usd": 40_000}
    ]


# 4
def test_moscow_day_boundary(client, as_user, admin, make_generation):
    # 23:30 по Москве 5 октября — это 20:30 UTC, всё ещё 5 октября; 00:30 — уже 6-е
    # по Москве, хотя в UTC ещё 5-е.
    make_generation(admin.id, cost_micro_usd=100, created_at="2026-10-05T20:30:00Z")
    make_generation(admin.id, cost_micro_usd=20, created_at="2026-10-05T21:30:00Z")
    as_user(admin)
    body = client.get("/api/admin/spending", params={**PERIOD, "group": "day"}).json()
    assert as_map(body["rows"]) == {"2026-10-05": 100, "2026-10-06": 20}
    # Однодневный период берёт московские сутки целиком.
    one_day = client.get("/api/spending/me", params={"from": "2026-10-05", "to": "2026-10-05"})
    assert one_day.json()["total_micro_usd"] == 100
    next_day = client.get("/api/spending/me", params={"from": "2026-10-06", "to": "2026-10-06"})
    assert next_day.json()["total_micro_usd"] == 20


# 5
@pytest.mark.parametrize("path", ["/api/admin/spending", "/api/admin/spending.csv"])
def test_designer_forbidden(client, as_user, user, path):
    as_user(user)
    response = client.get(path, params={**PERIOD, "group": "user"})
    assert response.status_code == 403
    assert isinstance(response.json()["detail"], str)


# 6
@pytest.mark.parametrize("group", ["user", "model", "day"])
def test_csv(client, as_user, dataset, group):
    users, _ = dataset
    as_user(users[2])
    params = {**PERIOD, "group": group}
    data = client.get("/api/admin/spending", params=params).json()
    response = client.get("/api/admin/spending.csv", params=params)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    raw = response.content
    assert raw.startswith(b"\xef\xbb\xbf")
    lines = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
    assert lines[0] == ["key", "label", "count", "cost_usd"]
    assert all(len(line) == 4 for line in lines)
    groups, total = lines[1:-1], lines[-1]
    # Заголовок + строки групп + итоговая строка (контракт: «последняя строка — итог»).
    assert len(groups) == len(data["rows"])
    assert len(lines) == len(data["rows"]) + 2

    def micro(text: str) -> int:
        return int(Decimal(text.replace(",", ".")) * 1_000_000)

    assert [g[0] for g in groups] == [r["key"] for r in data["rows"]]
    assert [micro(g[3]) for g in groups] == [r["cost_micro_usd"] for r in data["rows"]]
    assert sum(micro(g[3]) for g in groups) == data["total_micro_usd"]
    assert micro(total[3]) == data["total_micro_usd"]
    assert int(total[2]) == data["count"]


def test_csv_money_format(client, as_user, admin, make_generation):
    make_generation(admin.id, cost_micro_usd=93_000, created_at=utc("2026-10-02 10:00"))
    make_generation(admin.id, cost_micro_usd=1_500_001, created_at=utc("2026-10-02 11:00"))
    as_user(admin)
    text = client.get("/api/admin/spending.csv", params={**PERIOD, "group": "day"}).content.decode(
        "utf-8-sig"
    )
    assert text.splitlines()[1] == "2026-10-02;2026-10-02;2;1,593001"


# 7: ошибки в формате контракта
@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-10-31", "to": "2026-10-01", "group": "user"},
        {"from": "31.10.2026", "to": "2026-10-31", "group": "user"},
        {"to": "2026-10-31", "group": "user"},
        {**PERIOD, "group": "week"},
        PERIOD,
    ],
)
def test_bad_params_422(client, as_user, admin, params):
    as_user(admin)
    for path in ("/api/admin/spending", "/api/admin/spending.csv"):
        response = client.get(path, params=params)
        assert response.status_code == 422, response.text
        assert_schema(response.json(), "Error")


def test_my_spending_bad_period(client, as_user, user):
    as_user(user)
    response = client.get("/api/spending/me", params={"from": "2026-10-02", "to": "2026-10-01"})
    assert response.status_code == 422
    assert_schema(response.json(), "Error")


def test_empty_period(client, as_user, user):
    as_user(user)
    body = client.get("/api/spending/me", params=PERIOD).json()
    assert_schema(body, "MySpending")
    assert body["total_micro_usd"] == 0 and body["by_day"] == [] and body["by_model"] == []


def test_designer_sees_only_self(client, as_user, dataset):
    users, expected = dataset
    as_user(users[1])
    body = client.get("/api/spending/me", params=PERIOD).json()
    assert body["total_micro_usd"] == expected["user"][str(users[1].id)]
    assert body["count"] == 10
