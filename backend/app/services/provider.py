"""Провайдер изображений: OpenAI Images API или заглушка (FR-05, FR-17, NFR-10).

Оба провайдера реализуют одну асинхронную функцию ``generate``. Без ``OPENAI_API_KEY``
сервис работает с ``MockProvider``, который рисует тестовые картинки и считает фиктивные
токены. Ошибки наружу выходят только как ``ProviderError`` с понятным русским текстом:
без ключа, без исходного ответа OpenAI и без трассировки.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import openai
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

TIMEOUT_S = 300.0  # NFR-10
RETRY_DELAY_S = 2.0
DEFAULT_SIZE = (1024, 1024)  # что даёт size=auto в заглушке

PIL_FORMATS = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}

# Тексты ошибок для пользователя (FR-05). Ключ и ответ OpenAI сюда не попадают.
ERR_MODERATION = "Запрос отклонён модерацией OpenAI. Измените промпт или референсы."
ERR_RATE_LIMIT = "OpenAI ограничил частоту запросов. Повторите через минуту."
ERR_QUOTA = "Исчерпан баланс или месячный лимит OpenAI. Обратитесь к администратору."
ERR_AUTH = "Неверный ключ OpenAI или у ключа нет доступа. Обратитесь к администратору."
ERR_MODEL = "Модель недоступна для этого ключа OpenAI. Выберите другую модель."
ERR_TIMEOUT = "OpenAI не ответил за 5 минут. Попробуйте ещё раз."
ERR_CONNECTION = "Нет связи с OpenAI. Попробуйте ещё раз позже."
ERR_SERVER = "Сервис OpenAI временно недоступен. Попробуйте ещё раз позже."
ERR_BAD_REQUEST = "OpenAI отклонил параметры запроса. Проверьте размер, качество и референсы."
ERR_EMPTY = "OpenAI не вернул изображение. Попробуйте ещё раз."
ERR_UNKNOWN = "Неизвестная ошибка OpenAI. Попробуйте ещё раз позже."

MODERATION_CODES = {"moderation_blocked", "content_policy_violation"}
QUOTA_CODES = {"insufficient_quota", "billing_hard_limit_reached", "billing_not_active"}


class ProviderError(Exception):
    """Генерация не удалась; ``str(err)`` можно показывать пользователю."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ProviderResult:
    images: list[bytes]
    text_in_tokens: int
    image_in_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ModelCaps:
    """Что модель принимает из необязательных параметров (поля из ``models.json``)."""

    supports_input_fidelity: bool = False
    max_n: int = 1
    output_formats: tuple[str, ...] = ()


def load_caps(path: str | Path) -> dict[str, ModelCaps]:
    """Читает из ``models.json`` только то, что нужно провайдеру; проверка файла — в pricing."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        m["id"]: ModelCaps(
            supports_input_fidelity=bool(m.get("supports_input_fidelity", False)),
            max_n=int(m.get("max_n", 1)),
            output_formats=tuple(m.get("output_formats", ())),
        )
        for m in data["models"]
    }


class ImageProvider(Protocol):
    async def generate(
        self,
        model: str,
        prompt: str,
        quality: str,
        size: str,
        images: Sequence[bytes],
        n: int = 1,
        input_fidelity: str | None = None,
        output_format: str = "jpeg",
    ) -> ProviderResult: ...


def parse_size(size: str) -> tuple[int, int]:
    if size == "auto":
        return DEFAULT_SIZE
    width, _, height = size.partition("x")
    return int(width), int(height)


def sniff_image(data: bytes) -> tuple[str, str]:
    """Расширение и MIME по сигнатуре файла (референсы хранятся в исходном формате)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return "png", "image/png"


# --- OpenAI ---------------------------------------------------------------------------


def _translate(err: Exception) -> ProviderError:
    """Ошибка SDK → понятный текст. Сообщение OpenAI не пересказываем: там бывает что угодно."""
    code = getattr(err, "code", None)
    message = str(getattr(err, "message", "") or "").lower()
    if isinstance(err, openai.APITimeoutError):
        return ProviderError(ERR_TIMEOUT)
    if isinstance(err, openai.APIConnectionError):
        return ProviderError(ERR_CONNECTION)
    if code in MODERATION_CODES or "safety system" in message:
        return ProviderError(ERR_MODERATION)
    if code in QUOTA_CODES:
        return ProviderError(ERR_QUOTA)
    if isinstance(err, openai.RateLimitError):
        return ProviderError(ERR_RATE_LIMIT, retryable=True)
    if isinstance(err, openai.AuthenticationError):
        return ProviderError(ERR_AUTH)
    if isinstance(err, openai.PermissionDeniedError | openai.NotFoundError):
        return ProviderError(ERR_MODEL)
    if isinstance(err, openai.APIStatusError) and err.status_code >= 500:
        return ProviderError(ERR_SERVER, retryable=True)
    if isinstance(err, openai.BadRequestError | openai.UnprocessableEntityError):
        return ProviderError(ERR_BAD_REQUEST)
    return ProviderError(ERR_UNKNOWN)


def _usage_tokens(usage: Any) -> tuple[int, int, int]:
    """``usage`` ответа → (текстовые входные, картиночные входные, выходные)."""
    if usage is None:
        return 0, 0, 0
    input_tokens = usage.input_tokens or 0
    details = getattr(usage, "input_tokens_details", None)
    if details is None:
        text_in, image_in = input_tokens, 0
    else:
        text_in, image_in = details.text_tokens or 0, details.image_tokens or 0
    return text_in, image_in, usage.output_tokens or 0


class OpenAIProvider:
    """``images.generate`` без референсов, ``images.edit`` с референсами."""

    def __init__(
        self,
        api_key: str | None = None,
        caps: Mapping[str, ModelCaps] | None = None,
        *,
        client: Any = None,
        retry_delay: float = RETRY_DELAY_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if client is None:
            # Повторы SDK выключены: ровно один свой повтор на 429 и 5xx (NFR-10).
            client = openai.AsyncOpenAI(api_key=api_key, timeout=TIMEOUT_S, max_retries=0)
        self._client = client
        self._caps = dict(caps or {})
        self._retry_delay = retry_delay
        self._sleep = sleep

    def _params(
        self,
        model: str,
        prompt: str,
        quality: str,
        size: str,
        n: int,
        input_fidelity: str | None,
        output_format: str,
        edit: bool,
    ) -> dict[str, Any]:
        caps = self._caps.get(model, ModelCaps())
        params: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "quality": quality,
            "size": size,
            "timeout": TIMEOUT_S,
        }
        if n > 1 and caps.max_n > 1:
            params["n"] = min(n, caps.max_n)
        if output_format in caps.output_formats:
            params["output_format"] = output_format
        if edit and input_fidelity and caps.supports_input_fidelity:
            params["input_fidelity"] = input_fidelity
        return params

    async def _call(self, edit: bool, params: dict[str, Any], images: Sequence[bytes]) -> Any:
        if not edit:
            return await self._client.images.generate(**params)
        files = []
        for idx, data in enumerate(images):
            ext, mime = sniff_image(data)
            files.append((f"ref{idx}.{ext}", data, mime))
        return await self._client.images.edit(image=files, **params)

    async def generate(
        self,
        model: str,
        prompt: str,
        quality: str,
        size: str,
        images: Sequence[bytes],
        n: int = 1,
        input_fidelity: str | None = None,
        output_format: str = "jpeg",
    ) -> ProviderResult:
        edit = bool(images)
        params = self._params(model, prompt, quality, size, n, input_fidelity, output_format, edit)
        for attempt in (1, 2):
            try:
                response = await self._call(edit, params, images)
                break
            except openai.OpenAIError as err:
                failure = _translate(err)
                log.warning(
                    "OpenAI %s: попытка %d, %s, status=%s code=%s",
                    "edit" if edit else "generate",
                    attempt,
                    type(err).__name__,
                    getattr(err, "status_code", None),
                    getattr(err, "code", None),
                )
                if failure.retryable and attempt == 1:
                    await self._sleep(self._retry_delay)
                    continue
                raise failure from None

        result = [base64.b64decode(item.b64_json) for item in response.data or () if item.b64_json]
        if not result:
            raise ProviderError(ERR_EMPTY)
        text_in, image_in, output = _usage_tokens(getattr(response, "usage", None))
        return ProviderResult(result, text_in, image_in, output)


# --- Заглушка -------------------------------------------------------------------------


class MockProvider:
    """Тестовый режим (FR-17): картинки нужного размера и формата, фиктивные токены."""

    def __init__(self, delay: tuple[float, float] = (2.0, 5.0)) -> None:
        self._delay = delay

    async def generate(
        self,
        model: str,
        prompt: str,
        quality: str,
        size: str,
        images: Sequence[bytes],
        n: int = 1,
        input_fidelity: str | None = None,
        output_format: str = "jpeg",
    ) -> ProviderResult:
        await asyncio.sleep(random.uniform(*self._delay))
        width, height = parse_size(size)
        pil_format = PIL_FORMATS.get(output_format, "JPEG")
        pictures = [
            _draw(prompt, idx, n, model, quality, width, height, pil_format) for idx in range(n)
        ]
        text_in = max(1, len(prompt) // 4)
        image_in = 85 + 765 * len(images)
        output = n * (width * height // 1024)
        return ProviderResult(pictures, text_in, image_in, output)


def _draw(
    prompt: str, idx: int, n: int, model: str, quality: str, width: int, height: int, fmt: str
) -> bytes:
    seed = hashlib.sha256(f"{prompt}|{idx}".encode()).digest()
    background = (seed[0], seed[1], seed[2])
    ink = (255, 255, 255) if sum(background) < 384 else (0, 0, 0)
    picture = Image.new("RGB", (width, height), background)
    pen = ImageDraw.Draw(picture)
    font = ImageFont.load_default(size=max(16, width // 24))
    lines = ["ТЕСТОВЫЙ РЕЖИМ / MOCK", f"{model} · {quality}", f"вариант {idx + 1} из {n}"]
    lines.append(prompt[:60])
    for row, text in enumerate(lines):
        pen.text((width // 16, height // 8 + row * width // 14), text, fill=ink, font=font)
    pen.rectangle((0, 0, width - 1, height - 1), outline=ink, width=max(2, width // 128))
    out = io.BytesIO()
    picture.save(out, format=fmt)
    return out.getvalue()


def make_provider(
    api_key: str | None, models_path: str | Path | None = None
) -> OpenAIProvider | MockProvider:
    """Режим по наличию ключа: с ключом — OpenAI, без ключа — заглушка."""
    if not api_key:
        return MockProvider()
    caps = load_caps(models_path) if models_path else {}
    return OpenAIProvider(api_key, caps)
