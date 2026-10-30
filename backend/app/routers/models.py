"""`GET /api/models`: модели, качества, размеры, форматы и запасные цены из `models.json`.

Каталог читается при импорте модуля: если `models.json` повреждён, приложение
не стартует, а в логе остаётся понятная ошибка `ModelsConfigError`.
"""

import os

from fastapi import APIRouter, Depends, HTTPException

from app.deps import CurrentUser, current_user
from app.services import pricing

router = APIRouter()

pricing.get_catalog()


def mode() -> str:
    """Режим из FR-17: без `OPENAI_API_KEY` — заглушка."""
    return "openai" if os.environ.get("OPENAI_API_KEY", "").strip() else "mock"


def check_params(**params) -> pricing.ModelSpec:
    """`pricing.validate_params`, но ошибка параметров превращается в 422 для роутеров."""
    try:
        return pricing.validate_params(**params)
    except pricing.ParamError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc


@router.get("/models")
def list_models(user: CurrentUser = Depends(current_user)) -> dict:
    catalog = pricing.get_catalog()
    return {
        "mode": mode(),
        "default_model": catalog.default_model,
        "models": [spec.public() for spec in catalog.models.values()],
    }
