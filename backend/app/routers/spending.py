"""Расходы: «Мои расходы» и сводка администратора с выгрузкой в CSV (FR-13, FR-14).

Деньги считаются целыми микродолларами. Работы со `status=error` входят в число
работ, но в сумму — как 0. Дни считаются по Europe/Moscow: период `from`…`to`
включает оба дня целиком по московскому времени, а время в базе хранится в UTC.
"""

import csv
import io
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.db import get_db
from app.deps import CurrentUser, current_user, require_admin
from app.services import pricing

router = APIRouter()

GROUPS = ("user", "model", "day")
DB_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MICRO = 1_000_000


def _moscow() -> tzinfo:
    """Europe/Moscow; без базы часовых поясов в образе — постоянное UTC+3 (переходов нет с 2014)."""
    try:
        return ZoneInfo("Europe/Moscow")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=3), "MSK")


MSK = _moscow()


@dataclass
class Bucket:
    key: str
    label: str
    count: int = 0
    cost_micro_usd: int = 0

    def add(self, cost: int) -> None:
        self.count += 1
        self.cost_micro_usd += cost

    def public(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "count": self.count,
            "cost_micro_usd": self.cost_micro_usd,
        }


@dataclass(frozen=True)
class Row:
    user_id: int
    username: str
    model: str
    day: str
    cost: int


# --- период и строки из базы ---


def _parse_date(value: str | None, name: str) -> date:
    if not value:
        raise HTTPException(status_code=422, detail=f"Параметр {name} обязателен")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"Параметр {name}: нужна дата в формате ГГГГ-ММ-ДД"
        ) from exc


def _period(from_: str | None, to: str | None) -> tuple[date, date]:
    start, end = _parse_date(from_, "from"), _parse_date(to, "to")
    if start > end:
        raise HTTPException(status_code=422, detail="Начало периода позже конца")
    return start, end


def _utc_bound(day: date) -> str:
    """Начало московского дня `day` в формате времени базы."""
    return datetime.combine(day, time(), MSK).astimezone(UTC).strftime(DB_TIME_FORMAT)


def _msk_day(created_at: str) -> str:
    moment = datetime.strptime(created_at, DB_TIME_FORMAT).replace(tzinfo=UTC)
    return moment.astimezone(MSK).date().isoformat()


def _rows(db: sqlite3.Connection, start: date, end: date, user_id: int | None = None) -> list[Row]:
    sql = (
        "SELECT g.user_id, u.username, g.model, g.created_at,"
        " CASE WHEN g.status = 'error' THEN 0 ELSE g.cost_micro_usd END AS cost"
        " FROM generations g JOIN users u ON u.id = g.user_id"
        " WHERE g.created_at >= ? AND g.created_at < ?"
    )
    params: list = [_utc_bound(start), _utc_bound(end + timedelta(days=1))]
    if user_id is not None:
        sql += " AND g.user_id = ?"
        params.append(user_id)
    return [
        Row(r["user_id"], r["username"], r["model"], _msk_day(r["created_at"]), r["cost"])
        for r in db.execute(sql, params)
    ]


# --- группировка ---


def _model_title(model_id: str) -> str:
    spec = pricing.get_catalog().models.get(model_id)
    return spec.title if spec else model_id


def _group(rows: Iterable[Row], group: str) -> list[dict]:
    buckets: dict[str, Bucket] = {}
    for row in rows:
        if group == "user":
            key, label = str(row.user_id), row.username
        elif group == "model":
            key, label = row.model, _model_title(row.model)
        else:
            key = label = row.day
        bucket = buckets.get(key)
        if bucket is None:
            bucket = buckets[key] = Bucket(key, label)
        bucket.add(row.cost)
    if group == "day":
        ordered = sorted(buckets.values(), key=lambda b: b.key)
    else:
        # Сначала самые дорогие, при равенстве — по подписи.
        ordered = sorted(buckets.values(), key=lambda b: (-b.cost_micro_usd, b.label, b.key))
    return [b.public() for b in ordered]


def _check_group(group: str | None) -> str:
    if group not in GROUPS:
        raise HTTPException(
            status_code=422, detail="Параметр group: допустимы значения user, model, day"
        )
    return group


def _admin_summary(
    db: sqlite3.Connection, from_: str | None, to: str | None, group: str | None
) -> dict:
    group = _check_group(group)
    start, end = _period(from_, to)
    rows = _rows(db, start, end)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "group": group,
        "total_micro_usd": sum(r.cost for r in rows),
        "count": len(rows),
        "rows": _group(rows, group),
    }


def _usd(micro: int) -> str:
    """Микродоллары в доллары с запятой, чтобы русский Excel прочитал число: 93000 → 0,093000."""
    return f"{micro // MICRO},{micro % MICRO:06d}"


# --- маршруты ---
# Параметры объявлены необязательными, чтобы на их отсутствие отвечать 422
# в формате контракта `{"detail": "..."}`, а не списком ошибок FastAPI.


@router.get("/spending/me")
def get_my_spending(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    user: CurrentUser = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    start, end = _period(from_, to)
    rows = _rows(db, start, end, user_id=user.id)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "total_micro_usd": sum(r.cost for r in rows),
        "count": len(rows),
        "by_day": _group(rows, "day"),
        "by_model": _group(rows, "model"),
    }


@router.get("/admin/spending")
def get_admin_spending(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    group: str | None = Query(None),
    admin: CurrentUser = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    return _admin_summary(db, from_, to, group)


@router.get("/admin/spending.csv")
def get_admin_spending_csv(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    group: str | None = Query(None),
    admin: CurrentUser = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    summary = _admin_summary(db, from_, to, group)
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(["key", "label", "count", "cost_usd"])
    for row in summary["rows"]:
        writer.writerow([row["key"], row["label"], row["count"], _usd(row["cost_micro_usd"])])
    writer.writerow(["total", "Итого", summary["count"], _usd(summary["total_micro_usd"])])
    filename = f"spending_{summary['group']}_{summary['from']}_{summary['to']}.csv"
    return Response(
        content="﻿" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
