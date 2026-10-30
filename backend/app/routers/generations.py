"""Генерации и галереи (T09): создание, список, карточка, `shared`, удаление, картинки.

Права (FR-10, NFR-05): свою работу видит автор, общую — все, любую — администратор.
Чужая приватная работа для остальных не существует: карточка и картинки отвечают 404.
Менять `shared` и удалять может только автор или администратор (иначе 403).
"""

import asyncio
import shutil
import sqlite3
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, StrictBool

from app import db as dbmod
from app.deps import CurrentUser, current_user
from app.routers.models import check_params
from app.services import jobs
from app.services.storage import MAX_FILES, StorageError, get_storage

router = APIRouter()

MAX_PROMPT = 4000
PAGE_MAX = 50
CAP_REACHED = "Дневной бюджет сервиса исчерпан, обратитесь к администратору"
MEDIA_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

_SELECT = "SELECT g.*, u.username FROM generations g JOIN users u ON u.id = g.user_id"


# --- общее ---


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Работа не найдена")


def _can_see(row: sqlite3.Row, user: CurrentUser) -> bool:
    return user.is_admin or row["user_id"] == user.id or bool(row["shared"])


def _can_edit(row: sqlite3.Row, user: CurrentUser) -> bool:
    return user.is_admin or row["user_id"] == user.id


def _load_visible(conn: sqlite3.Connection, gen_id: int, user: CurrentUser) -> sqlite3.Row:
    row = conn.execute(f"{_SELECT} WHERE g.id = ?", (gen_id,)).fetchone()
    if row is None or not _can_see(row, user):
        raise _not_found()
    return row


def _inputs_by_id(conn: sqlite3.Connection, ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {gen_id: [] for gen_id in ids}
    if not ids:
        return result
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        "SELECT generation_id, idx, filename, source_generation_id FROM generation_inputs"
        f" WHERE generation_id IN ({marks}) ORDER BY generation_id, idx",
        tuple(ids),
    )
    for row in rows:
        result[row["generation_id"]].append(
            {
                "idx": row["idx"],
                "filename": row["filename"],
                "source_generation_id": row["source_generation_id"],
            }
        )
    return result


def _to_api(row: sqlite3.Row, inputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Строка базы → схема `Generation` из контракта."""
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "parent_id": row["parent_id"],
        "batch_id": row["batch_id"],
        "variant_idx": row["variant_idx"],
        "model": row["model"],
        "quality": row["quality"],
        "size": row["size"],
        "input_fidelity": row["input_fidelity"],
        "output_format": row["output_format"],
        "prompt": row["prompt"],
        "status": row["status"],
        "error": row["error"],
        "shared": bool(row["shared"]),
        "input_text_tokens": row["input_text_tokens"],
        "input_image_tokens": row["input_image_tokens"],
        "output_tokens": row["output_tokens"],
        "cost_micro_usd": row["cost_micro_usd"],
        "inputs": inputs,
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


def _one(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    return _to_api(row, _inputs_by_id(conn, [row["id"]])[row["id"]])


# --- создание ---


def _check_sources(
    conn: sqlite3.Connection, source_ids: list[int], user: CurrentUser
) -> list[sqlite3.Row]:
    """Прошлые работы как референсы: видимые пользователю и уже готовые."""
    rows = []
    for source_id in source_ids:
        row = conn.execute("SELECT * FROM generations WHERE id = ?", (source_id,)).fetchone()
        if row is None or not _can_see(row, user):
            raise HTTPException(status_code=404, detail=f"Работа-референс №{source_id} не найдена")
        if row["status"] != "done" or not row["result_path"]:
            raise HTTPException(
                status_code=422, detail=f"Работа-референс №{source_id} ещё не готова"
            )
        rows.append(row)
    return rows


def _insert_batch(
    conn: sqlite3.Connection, user: CurrentUser, batch_id: str, n: int, fields: dict[str, Any]
) -> list[int]:
    ids = []
    with conn:
        for idx in range(n):
            row = {**fields, "user_id": user.id, "batch_id": batch_id, "variant_idx": idx}
            columns = ", ".join(row)
            marks = ", ".join("?" * len(row))
            cursor = conn.execute(
                f"INSERT INTO generations ({columns}) VALUES ({marks})", tuple(row.values())
            )
            ids.append(cursor.lastrowid)
    return ids


@router.post("/generations", status_code=202)
async def create_generation(
    user: CurrentUser = Depends(current_user),
    prompt: str = Form(...),
    model: str = Form(...),
    quality: str = Form(...),
    size: str = Form(...),
    n: int = Form(1),
    input_fidelity: str | None = Form(None),
    output_format: str = Form("jpeg"),
    shared: bool = Form(True),
    parent_id: int | None = Form(None),
    source_ids: list[int] = Form([]),
    files: list[UploadFile] = File([]),
) -> JSONResponse:
    with dbmod.session() as conn:
        if not prompt.strip():
            raise HTTPException(status_code=422, detail="Промпт не может быть пустым")
        if len(prompt) > MAX_PROMPT:
            raise HTTPException(
                status_code=422, detail=f"Промпт длиннее {MAX_PROMPT} символов: {len(prompt)}"
            )
        source_ids = list(dict.fromkeys(source_ids))
        if len(files) + len(source_ids) > MAX_FILES:
            raise HTTPException(
                status_code=422, detail=f"Референсов можно не больше {MAX_FILES} вместе с работами"
            )
        has_refs = bool(files or source_ids)
        spec = check_params(
            model=model,
            quality=quality,
            size=size,
            output_format=output_format,
            input_fidelity=input_fidelity if has_refs else None,
            n=n,
        )
        # Точность к референсам имеет смысл только при референсах; по умолчанию high (FR-03).
        fidelity = (input_fidelity or "high") if has_refs and spec.supports_input_fidelity else None
        if parent_id is not None and parent_id not in source_ids:
            raise HTTPException(status_code=422, detail="parent_id должен быть среди source_ids")
        sources = _check_sources(conn, source_ids, user)

        if jobs.daily_cap_reached(conn):
            raise HTTPException(status_code=429, detail=CAP_REACHED)

        batch_id = uuid.uuid4().hex
        fields = {
            "parent_id": parent_id,
            "model": spec.id,
            "quality": quality,
            "size": size,
            "input_fidelity": fidelity,
            "output_format": output_format,
            "prompt": prompt,
            "shared": int(shared),
            "status": "pending",
        }
        ids = _insert_batch(conn, user, batch_id, n, fields)
        storage = get_storage()
        try:
            saved = await storage.save_inputs(ids[0], files)
            refs = [(item.path, files[item.idx].filename, None) for item in saved]
            for source in sources:
                item = await asyncio.to_thread(
                    storage.save_input_file, ids[0], len(refs), storage.path(source["result_path"])
                )
                refs.append((item.path, None, source["id"]))
            # У каждого варианта своя копия референсов: удаление одного не ломает остальные.
            with conn:
                for gen_id in ids:
                    for idx, (path, filename, source_id) in enumerate(refs):
                        if gen_id != ids[0]:
                            src = storage.path(path)
                            dest = storage.input_path(gen_id, idx, src.suffix[1:])
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(src, dest)
                            path = storage.rel(dest)
                        conn.execute(
                            "INSERT INTO generation_inputs"
                            " (generation_id, idx, path, source_generation_id, filename)"
                            " VALUES (?, ?, ?, ?, ?)",
                            (gen_id, idx, path, source_id, filename),
                        )
        except BaseException as exc:
            _drop(conn, ids)
            if isinstance(exc, StorageError):
                raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
            raise

        jobs.submit(
            jobs.Batch(
                ids=tuple(ids),
                model=spec.id,
                prompt=prompt,
                quality=quality,
                size=size,
                input_fidelity=fidelity,
                output_format=output_format,
            )
        )
        return JSONResponse(status_code=202, content={"batch_id": batch_id, "ids": ids})


def _drop(conn: sqlite3.Connection, ids: list[int]) -> None:
    """Откат неудачного создания: строки и файлы пачки."""
    storage = get_storage()
    for gen_id in ids:
        storage.delete_generation(gen_id)
    marks = ",".join("?" * len(ids))
    with conn:
        conn.execute(f"DELETE FROM generations WHERE id IN ({marks})", tuple(ids))


# --- список и карточка ---


@router.get("/generations")
def list_generations(
    user: CurrentUser = Depends(current_user),
    scope: Literal["mine", "shared"] = Query(...),
    cursor: str | None = Query(None),
    limit: int = Query(PAGE_MAX, ge=1, le=PAGE_MAX),
    author_id: int | None = Query(None),
) -> dict[str, Any]:
    with dbmod.session() as conn:
        where: list[str] = []
        args: list[Any] = []
        if scope == "mine":
            where.append("g.user_id = ?")
            args.append(user.id)
        else:
            # «Общая» — готовые работы, видимые всем.
            where.append("g.shared = 1 AND g.status = 'done'")
            if author_id is not None:
                where.append("g.user_id = ?")
                args.append(author_id)
        if cursor:
            if not cursor.isdigit() or int(cursor) < 1:
                raise HTTPException(status_code=422, detail="Неверный курсор")
            where.append("g.id < ?")
            args.append(int(cursor))
        rows = conn.execute(
            f"{_SELECT} WHERE {' AND '.join(where)} ORDER BY g.id DESC LIMIT ?",
            (*args, limit + 1),
        ).fetchall()
        page = rows[:limit]
        inputs = _inputs_by_id(conn, [row["id"] for row in page])
        return {
            "items": [_to_api(row, inputs[row["id"]]) for row in page],
            "next_cursor": str(page[-1]["id"]) if len(rows) > limit else None,
        }


@router.get("/generations/{id}")
def get_generation(
    id: int,
    user: CurrentUser = Depends(current_user),
) -> dict[str, Any]:
    with dbmod.session() as conn:
        return _one(conn, _load_visible(conn, id, user))


class GenerationPatch(BaseModel):
    shared: StrictBool


@router.patch("/generations/{id}")
def update_generation(
    id: int,
    body: GenerationPatch,
    user: CurrentUser = Depends(current_user),
) -> dict[str, Any]:
    with dbmod.session() as conn:
        row = _load_visible(conn, id, user)
        if not _can_edit(row, user):
            raise HTTPException(status_code=403, detail="Менять видимость может только автор")
        with conn:
            conn.execute("UPDATE generations SET shared = ? WHERE id = ?", (int(body.shared), id))
        return _one(conn, _load_visible(conn, id, user))


@router.delete("/generations/{id}", status_code=204)
def delete_generation(
    id: int,
    user: CurrentUser = Depends(current_user),
) -> Response:
    with dbmod.session() as conn:
        row = _load_visible(conn, id, user)
        if not _can_edit(row, user):
            raise HTTPException(status_code=403, detail="Удалить работу может только автор")
        if row["status"] in ("pending", "running"):
            raise HTTPException(status_code=409, detail="Работа ещё выполняется, удалить нельзя")
        with conn:
            conn.execute("DELETE FROM generations WHERE id = ?", (id,))
        get_storage().delete_generation(id)
        return Response(status_code=204)


# --- картинки ---


@router.get("/generations/{id}/image")
def get_generation_image(
    id: int,
    user: CurrentUser = Depends(current_user),
    kind: Literal["result", "thumb", "input"] = Query(...),
    idx: int | None = Query(None, ge=0, le=MAX_FILES - 1),
    download: bool = Query(False),
) -> FileResponse:
    with dbmod.session() as conn:
        row = _load_visible(conn, id, user)
        if kind == "input":
            if idx is None:
                raise HTTPException(status_code=422, detail="Для kind=input нужен idx")
            found = conn.execute(
                "SELECT path FROM generation_inputs WHERE generation_id = ? AND idx = ?", (id, idx)
            ).fetchone()
            rel = found["path"] if found else None
        else:
            rel = row["result_path"] if kind == "result" else row["thumb_path"]
        if not rel:
            raise HTTPException(status_code=404, detail="Файла нет")
        path = get_storage().path(rel)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Файла нет")
        ext = path.suffix[1:].lower()
        filename = (
            f"generation-{id}.{ext}" if kind != "input" else f"generation-{id}-ref{idx}.{ext}"
        )
        return FileResponse(
            path,
            media_type=MEDIA_TYPES.get(ext, "application/octet-stream"),
            filename=filename,
            content_disposition_type="attachment" if download else "inline",
        )
