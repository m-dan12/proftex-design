"""Фоновый исполнитель генераций (FR-04, FR-03a, FR-05, NFR-08).

Один запуск формы — одна «пачка» (`batch_id`) из N работ и ровно один запрос к провайдеру
с `n=N`. Пачка ждёт в очереди в статусе `pending`, пока не освободится место в семафоре
на `MAX_PARALLEL` запросов, затем все её работы переходят в `running`, а по ответу —
в `done` или `error`.

Очередь и семафор живут в памяти процесса, поэтому Uvicorn запускается строго
с `--workers 1`. Задачи, прерванные перезапуском, при старте переводит в `error`
`db.recover_interrupted` (NFR-09).

Стоимость запроса и токены делятся между вариантами поровну, остаток микродолларов
(и токенов) достаётся варианту 0, поэтому сумма по вариантам равна стоимости запроса.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import db as dbmod
from app.config import get_settings
from app.services import pricing
from app.services.provider import ImageProvider, ProviderError, ProviderResult, make_provider
from app.services.storage import Storage, get_storage

log = logging.getLogger(__name__)

ERR_INTERNAL = "Внутренняя ошибка сервиса при генерации. Попробуйте ещё раз."
ERR_FEWER = "Провайдер вернул меньше вариантов, чем запрошено."

try:
    MOSCOW: timezone | ZoneInfo = ZoneInfo("Europe/Moscow")
except ZoneInfoNotFoundError:  # в образе без tzdata; Москва с 2014 года живёт в UTC+3
    MOSCOW = timezone(timedelta(hours=3), "MSK")


@dataclass(frozen=True)
class Batch:
    """Что нужно исполнителю, чтобы выполнить пачку вариантов одним запросом."""

    ids: tuple[int, ...]  # по возрастанию variant_idx
    model: str
    prompt: str
    quality: str
    size: str
    input_fidelity: str | None
    output_format: str


# --- провайдер ---


@lru_cache(maxsize=4)
def _provider_for(api_key: str) -> ImageProvider:
    return make_provider(api_key or None, pricing.models_file())


def get_provider() -> ImageProvider:
    """Провайдер по режиму из настроек; тесты подменяют эту функцию."""
    return _provider_for(get_settings().openai_api_key)


# --- деньги ---


def split_evenly(total: int, parts: int) -> list[int]:
    """Поровну на `parts` частей, остаток — первой части; сумма равна `total`."""
    base, rest = divmod(total, parts)
    return [base + rest] + [base] * (parts - 1)


def moscow_day_start_utc(now: datetime | None = None) -> str:
    """Начало текущих суток по Москве в формате `created_at` из базы (UTC)."""
    now = now or datetime.now(UTC)
    local = now.astimezone(MOSCOW)
    start = datetime.combine(local.date(), time(0, 0), tzinfo=MOSCOW)
    return start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def spent_today_micro_usd(conn, now: datetime | None = None) -> int:
    """Сумма расходов всех пользователей за текущие сутки по Москве (FR-18)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_micro_usd), 0) FROM generations WHERE created_at >= ?",
        (moscow_day_start_utc(now),),
    ).fetchone()
    return int(row[0])


def daily_cap_reached(conn, now: datetime | None = None) -> bool:
    """Достигнут ли аварийный потолок `SPEND_CAP_DAILY_USD`; пустой потолок — никогда."""
    cap = get_settings().spend_cap_daily_micro_usd
    if cap is None:
        return False
    return spent_today_micro_usd(conn, now) >= cap


# --- исполнитель ---


class JobRunner:
    """Очередь пачек одного цикла событий с семафором на `max_parallel` запросов."""

    def __init__(self, max_parallel: int) -> None:
        self.loop = asyncio.get_running_loop()
        self.semaphore = asyncio.Semaphore(max_parallel)
        self.tasks: set[asyncio.Task] = set()

    def submit(self, batch: Batch) -> asyncio.Task:
        task = self.loop.create_task(self._run(batch))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def drain(self) -> None:
        """Дождаться всех поставленных пачек (для тестов и аккуратной остановки)."""
        while self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)

    async def _run(self, batch: Batch) -> None:
        try:
            async with self.semaphore:
                await run_batch(batch)
        except Exception:
            log.exception("Пачка %s упала вне обработки ошибок", batch.ids)
            _mark_error(batch.ids, ERR_INTERNAL)


_runner: JobRunner | None = None


def get_runner() -> JobRunner:
    """Исполнитель текущего цикла событий (вызывать из асинхронного кода).

    В тестах у каждого клиента свой цикл событий, поэтому исполнитель пересоздаётся.
    """
    global _runner
    loop = asyncio.get_running_loop()
    if _runner is None or _runner.loop is not loop:
        _runner = JobRunner(get_settings().max_parallel)
    return _runner


def submit(batch: Batch) -> asyncio.Task:
    return get_runner().submit(batch)


# --- одна пачка ---


async def run_batch(batch: Batch, storage: Storage | None = None) -> None:
    """Выполнить пачку: `running` → запрос к провайдеру → результаты или ошибка."""
    storage = storage or get_storage()
    if not _mark_running(batch.ids):
        return  # работы удалены до старта
    try:
        images = await asyncio.to_thread(_read_inputs, storage, batch.ids[0])
        result = await get_provider().generate(
            model=batch.model,
            prompt=batch.prompt,
            quality=batch.quality,
            size=batch.size,
            images=images,
            n=len(batch.ids),
            input_fidelity=batch.input_fidelity,
            output_format=batch.output_format,
        )
    except ProviderError as err:
        _mark_error(batch.ids, err.message)
        return
    except Exception:
        log.exception("Ошибка провайдера в пачке %s", batch.ids)
        _mark_error(batch.ids, ERR_INTERNAL)
        return
    try:
        await asyncio.to_thread(_save_results, storage, batch, result)
    except Exception:
        log.exception("Не удалось сохранить результат пачки %s", batch.ids)
        _mark_error(batch.ids, ERR_INTERNAL)


def _read_inputs(storage: Storage, gen_id: int) -> list[bytes]:
    return [path.read_bytes() for path in storage.list_inputs(gen_id)]


def _mark_running(ids: Sequence[int]) -> bool:
    marks = ",".join("?" * len(ids))
    with dbmod.session() as conn:
        cursor = conn.execute(
            f"UPDATE generations SET status = 'running' WHERE id IN ({marks})"
            " AND status = 'pending'",
            tuple(ids),
        )
    return cursor.rowcount > 0


def _mark_error(ids: Sequence[int], message: str) -> None:
    """Ошибка: стоимость и токены 0, текст для пользователя (FR-05)."""
    marks = ",".join("?" * len(ids))
    with dbmod.session() as conn:
        conn.execute(
            "UPDATE generations SET status = 'error', error = ?, cost_micro_usd = 0,"
            " input_text_tokens = 0, input_image_tokens = 0, output_tokens = 0,"
            f" finished_at = ? WHERE id IN ({marks}) AND status IN ('pending', 'running')",
            (message, dbmod.now_iso(), *ids),
        )


def _save_results(storage: Storage, batch: Batch, result: ProviderResult) -> None:
    pictures = result.images[: len(batch.ids)]
    if not pictures:
        _mark_error(batch.ids, ERR_FEWER)
        return
    done_ids = batch.ids[: len(pictures)]
    total = pricing.cost(
        batch.model,
        result.text_in_tokens,
        result.image_in_tokens,
        result.output_tokens,
        quality=batch.quality,
        n=len(pictures),
    )
    parts = len(pictures)
    costs = split_evenly(total, parts)
    text_in = split_evenly(result.text_in_tokens, parts)
    image_in = split_evenly(result.image_in_tokens, parts)
    output = split_evenly(result.output_tokens, parts)

    saved = []
    for gen_id, data in zip(done_ids, pictures, strict=True):
        result_path = storage.save_result(gen_id, data, batch.output_format)
        thumb_path = storage.make_thumb(gen_id, data)
        saved.append((gen_id, result_path, thumb_path))

    finished = dbmod.now_iso()
    with dbmod.session() as conn:
        for i, (gen_id, result_path, thumb_path) in enumerate(saved):
            conn.execute(
                "UPDATE generations SET status = 'done', error = NULL, result_path = ?,"
                " thumb_path = ?, input_text_tokens = ?, input_image_tokens = ?,"
                " output_tokens = ?, cost_micro_usd = ?, finished_at = ? WHERE id = ?",
                (
                    result_path,
                    thumb_path,
                    text_in[i],
                    image_in[i],
                    output[i],
                    costs[i],
                    finished,
                    gen_id,
                ),
            )
    missing = batch.ids[len(pictures) :]
    if missing:
        _mark_error(missing, ERR_FEWER)
