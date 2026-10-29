"""T06: хранилище файлов и превью (NFR-04, NFR-07)."""

import asyncio
import io
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi import UploadFile
from PIL import Image

from app.services import storage
from app.services.storage import MAX_FILE_BYTES, Storage, StorageError

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "data")


def upload(data: bytes, name: str = "ref.png") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


def save(store: Storage, gen_id: int, files: list[bytes]):
    return asyncio.run(store.save_inputs(gen_id, [upload(f) for f in files]))


def image_bytes(fmt: str, size=(64, 48), mode="RGB", **params) -> bytes:
    buf = io.BytesIO()
    Image.effect_mandelbrot(size, (-2, -1.5, 1, 1.5), 50).convert(mode).save(buf, fmt, **params)
    return buf.getvalue()


def photo_jpeg(quality: int, orientation: int | None = None) -> bytes:
    """«Фото» с EXIF и GPS, как с телефона."""
    im = Image.radial_gradient("L").resize((1200, 900)).convert("RGB")
    im.paste(Image.effect_noise((600, 450), 40).convert("RGB"), (300, 200))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x0110] = "PhoneModel"  # Model
    if orientation:
        exif[0x0112] = orientation
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (55.0, 45.0, 21.0)
    gps[3] = "E"
    gps[4] = (37.0, 37.0, 4.0)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, exif=exif)
    return buf.getvalue()


# --- 1. проверка по содержимому, а не по расширению ---


def test_exe_renamed_to_png_rejected(store: Storage) -> None:
    exe = b"MZ\x90\x00\x03\x00\x00\x00" + os.urandom(4096)
    with pytest.raises(StorageError) as err:
        asyncio.run(store.save_inputs(1, [upload(exe, "setup.png")]))
    assert err.value.status_code == 422
    assert "не изображение" in err.value.detail
    assert not store.inputs_dir(1).exists()


def test_unsupported_format_rejected(store: Storage) -> None:
    with pytest.raises(StorageError, match="не поддерживается"):
        save(store, 1, [image_bytes("GIF")])


def test_truncated_image_rejected(store: Storage) -> None:
    data = image_bytes("PNG", size=(512, 512))
    with pytest.raises(StorageError, match="повреждён"):
        save(store, 1, [data[: len(data) // 2]])


# --- 2. размер и количество ---


def test_21mb_file_rejected(store: Storage) -> None:
    big = image_bytes("PNG") + b"\0" * (21 * 1024 * 1024)
    with pytest.raises(StorageError) as err:
        save(store, 1, [image_bytes("PNG"), big])
    assert err.value.status_code == 413
    assert "больше 20 МБ" in err.value.detail
    # Первый файл тоже убран: работа не создаётся наполовину.
    assert not store.inputs_dir(1).exists()


def test_eleven_files_rejected(store: Storage) -> None:
    with pytest.raises(StorageError) as err:
        save(store, 1, [image_bytes("PNG")] * 11)
    assert err.value.status_code == 422
    assert "не больше 10 файлов" in err.value.detail
    assert not store.inputs_dir(1).exists()


def test_ten_files_accepted_in_original_formats(store: Storage) -> None:
    files = [image_bytes(fmt) for fmt in ("PNG", "JPEG", "WEBP")] * 3 + [image_bytes("PNG")]
    saved = save(store, 7, files)
    assert [s.idx for s in saved] == list(range(10))
    assert [s.format for s in saved[:3]] == ["png", "jpeg", "webp"]
    assert [p.name for p in store.list_inputs(7)][:3] == ["0.png", "1.jpg", "2.webp"]
    assert saved[1].path == "inputs/7/1.jpg"
    assert store.find_input(7, 2) == store.root / "inputs/7/2.webp"


def test_long_side_over_4096_rejected(store: Storage) -> None:
    with pytest.raises(StorageError, match="4096"):
        save(store, 1, [image_bytes("PNG", size=(4097, 8), mode="L")])


# --- 3. метаданные снимаются, формат сохраняется ---


@pytest.mark.parametrize("quality", [75, 90, 95])
def test_jpeg_exif_and_gps_stripped(store: Storage, quality: int) -> None:
    original = photo_jpeg(quality)
    with Image.open(io.BytesIO(original)) as im:
        assert im.getexif().get_ifd(0x8825)  # исходник действительно с GPS

    saved = save(store, 3, [original])[0]
    path = store.path(saved.path)
    assert path.suffix == ".jpg"
    with Image.open(path) as im:
        assert im.format == "JPEG"
        assert len(im.getexif()) == 0
        assert not im.getexif().get_ifd(0x8825)
        assert "exif" not in im.info
    assert path.stat().st_size <= len(original) * 1.2
    assert b"PhoneMaker" not in path.read_bytes()


def test_exif_rotation_applied_before_stripping(store: Storage) -> None:
    # Orientation 6: снимок надо повернуть на 90°, ширина и высота меняются местами.
    saved = save(store, 3, [photo_jpeg(90, orientation=6)])[0]
    assert (saved.width, saved.height) == (900, 1200)
    with Image.open(store.path(saved.path)) as im:
        assert im.size == (900, 1200)
        assert len(im.getexif()) == 0


def test_png_and_webp_metadata_stripped(store: Storage) -> None:
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    png = image_bytes("PNG", exif=exif)
    webp = image_bytes("WEBP", exif=exif)
    for saved in save(store, 4, [png, webp]):
        data = store.path(saved.path).read_bytes()
        assert b"PhoneMaker" not in data
        with Image.open(io.BytesIO(data)) as im:
            assert len(im.getexif()) == 0


# --- 3a. защита от «бомб» и память ---


def test_pixel_bomb_rejected_before_decoding(store: Storage, monkeypatch) -> None:
    buf = io.BytesIO()
    Image.new("1", (20000, 20000)).save(buf, "PNG")
    bomb = buf.getvalue()
    assert len(bomb) < MAX_FILE_BYTES

    def no_decode(self):
        raise AssertionError("пиксели не должны декодироваться")

    monkeypatch.setattr(Image.Image, "load", no_decode)
    with pytest.raises(StorageError) as err:
        save(store, 1, [bomb])
    assert err.value.status_code == 422
    assert "4096" in err.value.detail


def test_ten_files_of_20mb_stay_under_1gb(tmp_path: Path) -> None:
    # Отдельный процесс, чтобы пиковая память не смешивалась с остальными тестами.
    script = textwrap.dedent(
        """
        import asyncio, os, resource, sys
        from pathlib import Path
        from fastapi import UploadFile
        from PIL import Image
        from app.services.storage import MAX_FILE_BYTES, Storage

        root = Path(sys.argv[1])
        src = root / "big.png"
        # Шум не сжимается: PNG 4096x1700 RGB весит почти ровно 20 МБ.
        Image.frombytes("RGB", (4096, 1700), os.urandom(4096 * 1700 * 3)).save(
            src, "PNG", compress_level=0
        )
        assert 19 * 1024 * 1024 < src.stat().st_size <= MAX_FILE_BYTES

        async def main():
            files = [src.open("rb") for _ in range(10)]
            try:
                ups = [UploadFile(file=f, filename="big.png") for f in files]
                return await Storage(root / "data").save_inputs(1, ups)
            finally:
                for f in files:
                    f.close()

        saved = asyncio.run(main())
        assert len(saved) == 10
        print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, out.stderr
    peak_kb = int(out.stdout.strip().splitlines()[-1])
    print(f"пик памяти {peak_kb // 1024} МБ")
    assert peak_kb < 1024 * 1024, f"пик памяти {peak_kb // 1024} МБ"


# --- 4. превью ---


@pytest.mark.parametrize("kind", ["photo", "noise"])
def test_thumb_from_png_1024x1536(store: Storage, kind: str) -> None:
    if kind == "noise":
        # Худший случай для сжатия.
        im = Image.frombytes("RGB", (1024, 1536), os.urandom(1024 * 1536 * 3))
    else:
        im = Image.open(io.BytesIO(photo_jpeg(95))).resize((1024, 1536))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    store.save_result(5, buf.getvalue(), "png")

    rel = store.make_thumb(5)
    assert rel == "thumbs/5.webp"
    path = store.path(rel)
    assert path.stat().st_size <= 60 * 1024
    with Image.open(path) as thumb:
        assert thumb.format == "WEBP"
        assert max(thumb.size) == 400
        assert thumb.size == (267, 400)


def test_thumb_keeps_transparency(store: Storage) -> None:
    im = Image.new("RGBA", (800, 600), (255, 0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    store.make_thumb(6, buf.getvalue())
    with Image.open(store.thumb_path(6)) as thumb:
        assert thumb.mode == "RGBA"
        assert thumb.size == (400, 300)


@pytest.mark.parametrize(("fmt", "ext"), [("png", "png"), ("jpeg", "jpg"), ("webp", "webp")])
def test_save_result_paths(store: Storage, fmt: str, ext: str) -> None:
    rel = store.save_result(12, image_bytes(fmt.upper()), fmt)
    assert rel == f"results/12.{ext}"
    assert store.find_result(12) == store.root / rel


# --- 5. пути только из целых id ---


@pytest.mark.parametrize("bad", ["../etc", "1/../../x", "5", 1.0, True, None])
def test_paths_accept_only_int_ids(store: Storage, bad) -> None:
    calls = [
        lambda: store.inputs_dir(bad),
        lambda: store.input_path(1, bad, "png"),
        lambda: store.result_path(bad, "png"),
        lambda: store.thumb_path(bad),
        lambda: store.find_result(bad),
        lambda: store.delete_generation(bad),
        lambda: store.make_thumb(bad, b""),
        lambda: asyncio.run(store.save_inputs(bad, [])),
    ]
    for call in calls:
        with pytest.raises(TypeError):
            call()


def test_negative_id_and_foreign_extension_rejected(store: Storage) -> None:
    with pytest.raises(ValueError):
        store.result_path(-1, "png")
    with pytest.raises(ValueError):
        store.result_path(1, "png/../../x")
    with pytest.raises(ValueError):
        store.save_result(1, b"x", "../../evil")


def test_db_path_cannot_escape_data_dir(store: Storage) -> None:
    with pytest.raises(ValueError):
        store.path("../../etc/passwd")
    with pytest.raises(ValueError):
        store.path("/etc/passwd")
    assert store.path("results/1.png") == store.root / "results" / "1.png"


def test_all_paths_inside_data_dir(store: Storage) -> None:
    for path in (
        store.inputs_dir(10**12),
        store.input_path(10**12, 9, "webp"),
        store.result_path(0, "jpg"),
        store.thumb_path(42),
    ):
        assert path.resolve().is_relative_to(store.root)


# --- 6. удаление ---


def test_delete_generation_removes_everything(store: Storage) -> None:
    save(store, 8, [image_bytes("PNG"), image_bytes("JPEG")])
    store.save_result(8, image_bytes("PNG", size=(1024, 1024)), "png")
    store.make_thumb(8)
    # Соседняя работа не должна пострадать.
    save(store, 80, [image_bytes("PNG")])
    store.save_result(80, image_bytes("PNG"), "png")

    store.delete_generation(8)

    assert store.find_result(8) is None
    assert not store.thumb_path(8).exists()
    assert not store.inputs_dir(8).exists()
    assert store.find_result(80) is not None
    assert store.list_inputs(80)
    store.delete_generation(8)  # повторное удаление не падает


def test_input_from_existing_file(store: Storage, tmp_path: Path) -> None:
    rel = store.save_result(20, photo_jpeg(90), "jpeg")
    saved = store.save_input_file(21, 0, store.path(rel))
    assert saved.path == "inputs/21/0.jpg"
    assert not list(store.inputs_dir(21).glob("*.part"))


def test_get_storage_uses_data_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert storage.get_storage().root == tmp_path.resolve()
