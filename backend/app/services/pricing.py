"""Каталог моделей из `models.json` и расчёт стоимости генерации.

Все цены живут только в `models.json` (FR-15) и меняются перезапуском без пересборки.
Деньги считаются целыми микродолларами: цены читаются как `Decimal` и переводятся
в целые «микродоллары за 1 млн токенов», поэтому плавающая запятая в расчёт не попадает.

Путь к файлу берётся из `MODELS_FILE`, по умолчанию — `models.json` в корне репозитория.
"""

import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_MODELS_FILE = Path(__file__).resolve().parents[3] / "models.json"

MICRO = 1_000_000  # микродолларов в долларе
TOKENS_PER_PRICE = 1_000_000  # цены в models.json — за 1 млн токенов
MAX_N = 4  # потолок вариантов из контракта
OUTPUT_FORMATS = ("jpeg", "png", "webp")
INPUT_FIDELITIES = ("low", "high")
TOKEN_KINDS = ("text_in", "image_in", "image_out")


class ModelsConfigError(RuntimeError):
    """`models.json` не читается или не проходит проверку; сервис не должен стартовать."""


class ParamError(ValueError):
    """Недопустимые параметры генерации. Роутеры отвечают на неё 422 с `detail`."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class ModelSpec:
    id: str
    title: str
    qualities: tuple[str, ...]
    default_quality: str
    sizes: tuple[str, ...]
    output_formats: tuple[str, ...]
    supports_input_fidelity: bool
    max_n: int
    # Микродолларов за 1 млн токенов, по видам токенов из TOKEN_KINDS.
    price_micro_per_1m: dict[str, int]
    # Микродолларов за одну картинку, по качеству.
    fallback_per_image_micro: dict[str, int]

    def public(self) -> dict[str, Any]:
        """Описание модели по схеме `ModelInfo` из контракта."""
        return {
            "id": self.id,
            "title": self.title,
            "qualities": list(self.qualities),
            "default_quality": self.default_quality,
            "sizes": list(self.sizes),
            "output_formats": list(self.output_formats),
            "supports_input_fidelity": self.supports_input_fidelity,
            "max_n": self.max_n,
            "fallback_per_image_micro_usd": dict(self.fallback_per_image_micro),
        }


@dataclass(frozen=True)
class Catalog:
    default_model: str
    models: dict[str, ModelSpec]

    def get(self, model_id: str) -> ModelSpec:
        spec = self.models.get(model_id)
        if spec is None:
            raise ParamError(f"Неизвестная модель: {model_id}")
        return spec


# --- загрузка и проверка models.json ---


def _fail(where: str, message: str) -> ModelsConfigError:
    return ModelsConfigError(f"models.json, {where}: {message}")


def _str(raw: dict, key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail(where, f"поле «{key}» обязательно и должно быть непустой строкой")
    return value


def _str_list(raw: dict, key: str, where: str) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise _fail(where, f"поле «{key}» обязательно и должно быть непустым списком")
    if not all(isinstance(item, str) and item for item in value):
        raise _fail(where, f"в «{key}» допустимы только непустые строки")
    if len(set(value)) != len(value):
        raise _fail(where, f"в «{key}» есть повторы")
    return tuple(value)


def _micro(value: Any, where: str, field: str) -> int:
    """USD (число из JSON) → целые микродоллары, без потери точности."""
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise _fail(where, f"цена «{field}» должна быть числом")
    try:
        amount = Decimal(value) * MICRO
    except InvalidOperation as exc:
        raise _fail(where, f"цена «{field}» не число") from exc
    if not amount.is_finite():
        raise _fail(where, f"цена «{field}» не число")
    if amount < 0:
        raise _fail(where, f"цена «{field}» отрицательная: {value}")
    if amount != amount.to_integral_value():
        raise _fail(where, f"цена «{field}» точнее микродоллара: {value}")
    return int(amount)


def _price_table(raw: dict, key: str, keys: tuple[str, ...], where: str) -> dict[str, int]:
    table = raw.get(key)
    if not isinstance(table, dict):
        raise _fail(where, f"поле «{key}» обязательно и должно быть объектом")
    if set(table) != set(keys):
        raise _fail(where, f"в «{key}» нужны ровно ключи {', '.join(keys)}")
    return {name: _micro(table[name], where, f"{key}.{name}") for name in keys}


def _parse_model(raw: Any, index: int) -> ModelSpec:
    where = f"модель №{index + 1}"
    if not isinstance(raw, dict):
        raise _fail(where, "ожидается объект")
    model_id = _str(raw, "id", where)
    where = f"модель «{model_id}»"

    qualities = _str_list(raw, "qualities", where)
    default_quality = _str(raw, "default_quality", where)
    if default_quality not in qualities:
        raise _fail(where, f"default_quality «{default_quality}» нет в qualities")

    output_formats = _str_list(raw, "output_formats", where)
    unknown = [fmt for fmt in output_formats if fmt not in OUTPUT_FORMATS]
    if unknown:
        raise _fail(where, f"неизвестные форматы {unknown}, допустимы {list(OUTPUT_FORMATS)}")

    fidelity = raw.get("supports_input_fidelity")
    if not isinstance(fidelity, bool):
        raise _fail(where, "поле «supports_input_fidelity» обязательно, true или false")

    max_n = raw.get("max_n")
    if isinstance(max_n, bool) or not isinstance(max_n, int) or not 1 <= max_n <= MAX_N:
        raise _fail(where, f"поле «max_n» обязательно, целое от 1 до {MAX_N}")

    return ModelSpec(
        id=model_id,
        title=_str(raw, "title", where),
        qualities=qualities,
        default_quality=default_quality,
        sizes=_str_list(raw, "sizes", where),
        output_formats=output_formats,
        supports_input_fidelity=fidelity,
        max_n=max_n,
        price_micro_per_1m=_price_table(raw, "prices_usd_per_1m_tokens", TOKEN_KINDS, where),
        fallback_per_image_micro=_price_table(raw, "fallback_per_image_usd", qualities, where),
    )


def parse_catalog(data: Any) -> Catalog:
    """Проверить содержимое `models.json` (числа — `Decimal`) и собрать каталог."""
    if not isinstance(data, dict):
        raise ModelsConfigError("models.json: ожидается объект верхнего уровня")
    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ModelsConfigError("models.json: поле «models» должно быть непустым списком")

    models: dict[str, ModelSpec] = {}
    for index, raw in enumerate(raw_models):
        spec = _parse_model(raw, index)
        if spec.id in models:
            raise ModelsConfigError(f"models.json: модель «{spec.id}» описана дважды")
        models[spec.id] = spec

    default_model = data.get("default_model")
    if default_model not in models:
        raise ModelsConfigError(
            f"models.json: default_model «{default_model}» нет в списке моделей"
        )
    return Catalog(default_model=default_model, models=models)


def models_file() -> Path:
    return Path(os.environ.get("MODELS_FILE") or DEFAULT_MODELS_FILE)


def load_catalog(path: Path | None = None) -> Catalog:
    """Прочитать и проверить `models.json`; при любой ошибке — `ModelsConfigError`."""
    path = path or models_file()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ModelsConfigError(f"models.json не читается ({path}): {exc}") from exc
    try:
        data = json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise ModelsConfigError(f"models.json ({path}) — не JSON: {exc}") from exc
    return parse_catalog(data)


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    """Каталог процесса: читается один раз, новая версия файла — после перезапуска."""
    return load_catalog()


# --- проверка параметров и стоимость ---


def validate_params(
    model: str,
    quality: str,
    size: str,
    output_format: str,
    input_fidelity: str | None = None,
    n: int = 1,
    catalog: Catalog | None = None,
) -> ModelSpec:
    """Проверить параметры генерации по `models.json`; при ошибке — `ParamError`."""
    spec = (catalog or get_catalog()).get(model)
    if quality not in spec.qualities:
        raise ParamError(f"Качество «{quality}» недоступно для {spec.id}")
    if size not in spec.sizes:
        raise ParamError(f"Размер «{size}» недоступен для {spec.id}")
    if output_format not in spec.output_formats:
        raise ParamError(f"Формат «{output_format}» недоступен для {spec.id}")
    if input_fidelity is not None:
        if not spec.supports_input_fidelity:
            raise ParamError(f"Модель {spec.id} не поддерживает input_fidelity")
        if input_fidelity not in INPUT_FIDELITIES:
            raise ParamError(f"input_fidelity может быть только {', '.join(INPUT_FIDELITIES)}")
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= spec.max_n:
        raise ParamError(f"Число вариантов для {spec.id} — от 1 до {spec.max_n}")
    return spec


def cost(
    model: str,
    text_in_tokens: int | None,
    image_in_tokens: int | None,
    output_tokens: int | None,
    *,
    quality: str | None = None,
    n: int = 1,
    catalog: Catalog | None = None,
) -> int:
    """Стоимость одного запроса к API в целых микродолларах.

    По токенам: сумма токенов × цена за 1 млн, округление до микродоллара (половина — вверх).
    Если API не вернул выходные токены (`None` или 0), считается запасная цена
    за картинку для `quality` (по умолчанию — `default_quality` модели), умноженная на `n`.
    """
    spec = (catalog or get_catalog()).get(model)
    if not output_tokens:
        quality = quality or spec.default_quality
        if quality not in spec.fallback_per_image_micro:
            raise ParamError(f"Качество «{quality}» недоступно для {spec.id}")
        return spec.fallback_per_image_micro[quality] * n

    tokens = {
        "text_in": text_in_tokens or 0,
        "image_in": image_in_tokens or 0,
        "image_out": output_tokens,
    }
    if any(value < 0 for value in tokens.values()):
        raise ValueError("Число токенов не может быть отрицательным")
    scaled = sum(tokens[kind] * spec.price_micro_per_1m[kind] for kind in TOKEN_KINDS)
    return (scaled + TOKENS_PER_PRICE // 2) // TOKENS_PER_PRICE
