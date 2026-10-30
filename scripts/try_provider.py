"""Ручная проверка провайдера с настоящим ключом OpenAI (запуск — в S-17).

Ключ берётся только из переменной окружения и никуда не печатается. Каждый запуск
стоит денег: по умолчанию одна картинка низкого качества.

    cd backend
    OPENAI_API_KEY=... python ../scripts/try_provider.py "кот в шляпе"
    OPENAI_API_KEY=... python ../scripts/try_provider.py "сделай фон синим" \\
        --ref a.jpg --ref b.png --model gpt-image-2.5-sunburst --quality high --format png

Без ключа скрипт работает с заглушкой (удобно проверить сам скрипт).
Картинки сохраняются в текущую папку как try_provider_<n>.<формат>, токены
печатаются по трём видам для сверки с Usage в кабинете OpenAI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.provider import ProviderError, make_provider  # noqa: E402

MODELS = ROOT / "models.json"


def main() -> int:
    default_model = json.loads(MODELS.read_text(encoding="utf-8"))["default_model"]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prompt")
    parser.add_argument("--model", default=default_model)
    parser.add_argument("--quality", default="low")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--format", default="jpeg", choices=["jpeg", "png", "webp"])
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--fidelity", choices=["low", "high"], default=None)
    parser.add_argument("--ref", action="append", default=[], help="файл-референс, до 10")
    args = parser.parse_args()

    key = os.environ.get("OPENAI_API_KEY")
    provider = make_provider(key, MODELS)
    print(f"режим: {'openai' if key else 'mock'}, модель: {args.model}")
    refs = [Path(p).read_bytes() for p in args.ref]
    try:
        result = asyncio.run(
            provider.generate(
                args.model,
                args.prompt,
                args.quality,
                args.size,
                refs,
                args.n,
                args.fidelity,
                args.format,
            )
        )
    except ProviderError as err:
        print(f"ошибка: {err}", file=sys.stderr)
        return 1
    for idx, data in enumerate(result.images, 1):
        name = f"try_provider_{idx}.{args.format}"
        Path(name).write_bytes(data)
        print(f"сохранено: {name} ({len(data)} байт)")
    print(
        f"токены: текст на входе {result.text_in_tokens}, "
        f"картинки на входе {result.image_in_tokens}, на выходе {result.output_tokens}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
