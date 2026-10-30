"""Файлы работ в DATA_DIR: входные референсы, результаты и превью (T06).

Схема на диске:
    inputs/{id}/{idx}.{ext}   референсы в исходном формате, без EXIF
    results/{id}.{ext}        результат генерации
    thumbs/{id}.webp          превью, длинная сторона 400 px

Пути строятся только из целых id, поэтому выйти за DATA_DIR нельзя.
Загрузки пишутся на диск потоком и проверяются по одному файлу (NFR-04).
"""

import asyncio
import inspect
import io
import os
import shutil
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageOps

MAX_FILES = 10
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_SIDE = 4096
MAX_PIXELS = MAX_SIDE * MAX_SIDE
THUMB_SIDE = 400
THUMB_MAX_BYTES = 60 * 1024
JPEG_QUALITY = 95
CHUNK = 1024 * 1024
ORIENTATION = 0x0112  # тег EXIF с поворотом снимка

# Защита от «бомб»: Pillow сам ругается на картинки больше этого порога.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

# Формат Pillow → расширение на диске.
EXT = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
# output_format из models.json → расширение результата.
RESULT_EXT = {"png": "png", "jpeg": "jpg", "webp": "webp"}


class StorageError(Exception):
    """Ошибка загрузки с русским текстом; роутер отдаёт её как {"detail": ...}."""

    def __init__(self, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class Upload(Protocol):
    """То, что умеет UploadFile из FastAPI: имя и чтение кусками."""

    filename: str | None

    def read(self, size: int = -1): ...


@dataclass(frozen=True)
class SavedInput:
    idx: int
    path: str  # относительно DATA_DIR
    format: str  # png | jpeg | webp
    width: int
    height: int
    size: int


def _id(value: object) -> int:
    # bool — подкласс int, но id им быть не может.
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"id должен быть целым числом, получено {type(value).__name__}")
    if value < 0:
        raise ValueError("id не может быть отрицательным")
    return value


class Storage:
    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.root = Path(data_dir).resolve()

    # --- пути ---

    def _abs(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("путь вне DATA_DIR")
        return path

    def inputs_dir(self, gen_id: int) -> Path:
        return self.root / "inputs" / str(_id(gen_id))

    def input_path(self, gen_id: int, idx: int, ext: str) -> Path:
        return self.inputs_dir(gen_id) / f"{_id(idx)}.{_ext(ext)}"

    def result_path(self, gen_id: int, ext: str) -> Path:
        return self.root / "results" / f"{_id(gen_id)}.{_ext(ext)}"

    def thumb_path(self, gen_id: int) -> Path:
        return self.root / "thumbs" / f"{_id(gen_id)}.webp"

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def find_result(self, gen_id: int) -> Path | None:
        return _first(self.root / "results", f"{_id(gen_id)}.*")

    def find_input(self, gen_id: int, idx: int) -> Path | None:
        return _first(self.inputs_dir(gen_id), f"{_id(idx)}.*")

    def list_inputs(self, gen_id: int) -> list[Path]:
        folder = self.inputs_dir(gen_id)
        if not folder.is_dir():
            return []
        files = [p for p in folder.iterdir() if p.is_file() and p.stem.isdigit()]
        return sorted(files, key=lambda p: int(p.stem))

    # --- входные файлы ---

    async def save_inputs(self, gen_id: int, uploads: Sequence[Upload]) -> list[SavedInput]:
        """Сохраняет референсы работы. При любой ошибке папка работы удаляется целиком."""
        check_count(len(uploads))
        folder = self.inputs_dir(gen_id)
        folder.mkdir(parents=True, exist_ok=True)
        saved = []
        try:
            for idx, upload in enumerate(uploads):
                part = folder / f"{idx}.part"
                await _stream_to(upload, part)
                saved.append(await asyncio.to_thread(self._finalize_input, gen_id, idx, part))
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return saved

    def save_input_file(self, gen_id: int, idx: int, src: Path) -> SavedInput:
        """Референс из уже лежащего на диске файла (например, результат прошлой работы)."""
        folder = self.inputs_dir(gen_id)
        folder.mkdir(parents=True, exist_ok=True)
        part = folder / f"{_id(idx)}.part"
        shutil.copyfile(src, part)
        return self._finalize_input(gen_id, idx, part)

    def _finalize_input(self, gen_id: int, idx: int, part: Path) -> SavedInput:
        try:
            name = f"файл {idx + 1}"
            if part.stat().st_size > MAX_FILE_BYTES:
                raise StorageError(f"{name}: больше 20 МБ", 413)
            data, fmt, width, height = _clean_image(part, name)
            dest = self.input_path(gen_id, idx, EXT[fmt])
            tmp = dest.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
        finally:
            part.unlink(missing_ok=True)
        return SavedInput(idx, self.rel(dest), fmt.lower(), width, height, len(data))

    # --- результат и превью ---

    def save_result(self, gen_id: int, data: bytes, output_format: str) -> str:
        """Записывает результат и возвращает путь относительно DATA_DIR."""
        dest = self.result_path(gen_id, RESULT_EXT.get(output_format, output_format))
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        return self.rel(dest)

    def make_thumb(self, gen_id: int, source: bytes | Path | None = None) -> str:
        """Превью WebP: длинная сторона 400 px, не больше 60 КБ."""
        dest = self.thumb_path(gen_id)
        if source is None:
            source = self.find_result(gen_id)
            if source is None:
                raise FileNotFoundError(f"нет результата работы {gen_id}")
        src = io.BytesIO(source) if isinstance(source, bytes) else source
        with Image.open(src) as im:
            im.draft("RGB", (THUMB_SIDE, THUMB_SIDE))
            im = ImageOps.exif_transpose(im)
            im.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
            im = im.convert("RGBA" if _has_alpha(im) else "RGB")
            data = _webp_under(im, THUMB_MAX_BYTES)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        return self.rel(dest)

    def path(self, rel: str) -> Path:
        """Абсолютный путь по значению из базы (result_path, thumb_path)."""
        return self._abs(rel)

    # --- удаление ---

    def delete_generation(self, gen_id: int) -> None:
        """Стирает результат, превью и входные файлы работы."""
        gen_id = _id(gen_id)
        for path in (self.root / "results").glob(f"{gen_id}.*"):
            path.unlink(missing_ok=True)
        self.thumb_path(gen_id).unlink(missing_ok=True)
        shutil.rmtree(self.inputs_dir(gen_id), ignore_errors=True)


def check_count(count: int) -> None:
    if count > MAX_FILES:
        raise StorageError(f"Можно приложить не больше {MAX_FILES} файлов, выбрано {count}")


def _ext(ext: str) -> str:
    if ext not in EXT.values():
        raise ValueError(f"недопустимое расширение: {ext!r}")
    return ext


def _first(folder: Path, pattern: str) -> Path | None:
    if not folder.is_dir():
        return None
    found = sorted(p for p in folder.glob(pattern) if p.suffix[1:] in EXT.values())
    return found[0] if found else None


async def _stream_to(upload: Upload, dest: Path) -> None:
    """Пишет загрузку на диск кусками по 1 МБ; больше 20 МБ — сразу отказ."""
    written = 0
    with dest.open("wb") as out:
        while True:
            chunk = upload.read(CHUNK)
            if inspect.isawaitable(chunk):
                chunk = await chunk
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_FILE_BYTES:
                name = upload.filename or "файл"
                raise StorageError(f"{name}: больше 20 МБ", 413)
            out.write(chunk)


def _clean_image(path: Path, name: str) -> tuple[bytes, str, int, int]:
    """Проверяет картинку и пересохраняет её в том же формате без EXIF и GPS."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            im = Image.open(path)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise StorageError(f"{name}: слишком большое изображение, максимум 4096×4096") from None
    except Exception:
        raise StorageError(f"{name}: не изображение (нужен PNG, JPEG или WebP)") from None
    with im:
        fmt = im.format
        if fmt not in EXT:
            raise StorageError(f"{name}: формат {fmt} не поддерживается, нужен PNG, JPEG или WebP")
        # Размер берём из заголовка: до декодирования пикселей.
        width, height = im.size
        if max(width, height) > MAX_SIDE or width * height > MAX_PIXELS:
            raise StorageError(
                f"{name}: {width}×{height} px, длинная сторона должна быть не больше {MAX_SIDE}"
            )
        try:
            im.load()
        except Exception:
            raise StorageError(f"{name}: файл повреждён, не удалось прочитать картинку") from None
        original = path.stat().st_size
        icc = im.info.get("icc_profile")
        rotated = im.getexif().get(ORIENTATION, 1) != 1
        # Поворот из EXIF применяем к пикселям, иначе после снятия EXIF фото «ляжет набок».
        upright = ImageOps.exif_transpose(im) if rotated else im
        out = _encode(upright, fmt, icc)
        if fmt == "JPEG" and not rotated and len(out) > original * 1.2:
            # Исходник сжат сильнее, чем q95: сохраняем с его же таблицами квантования,
            # чтобы файл не раздувался и не терял качество при повторном сжатии.
            out = _encode(im, fmt, icc, keep=True)
        return out, fmt, upright.width, upright.height


def _encode(im: Image.Image, fmt: str, icc: bytes | None, *, keep: bool = False) -> bytes:
    buf = io.BytesIO()
    params: dict = {}
    if icc:
        params["icc_profile"] = icc
    if fmt == "JPEG":
        if keep:
            params.update(quality="keep", subsampling="keep", qtables="keep")
        else:
            params.update(quality=JPEG_QUALITY, optimize=True)
            if im.mode not in ("RGB", "L", "CMYK"):
                im = im.convert("RGB")
    elif fmt == "PNG":
        params.update(optimize=False, compress_level=6)
    elif fmt == "WEBP":
        params.update(quality=JPEG_QUALITY)
    # exif и pnginfo не передаём: метаданные (EXIF, GPS, текстовые блоки) не попадают в файл.
    im.save(buf, fmt, **params)
    return buf.getvalue()


def _has_alpha(im: Image.Image) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)


def _webp_under(im: Image.Image, limit: int) -> bytes:
    data = b""
    for quality in (80, 70, 60, 50, 40, 30):
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=quality, method=6)
        data = buf.getvalue()
        if len(data) <= limit:
            break
    return data


_default: Storage | None = None


def get_storage() -> Storage:
    """Хранилище по DATA_DIR из окружения; для Depends в роутерах."""
    global _default
    root = Path(os.environ.get("DATA_DIR", "data")).resolve()
    if _default is None or _default.root != root:
        _default = Storage(root)
    return _default
