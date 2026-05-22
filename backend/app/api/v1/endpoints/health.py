from fastapi import APIRouter

from app.core.config import settings
from app.services.ai.factory import get_ai_provider

router = APIRouter()


@router.get("")
async def health_check() -> dict:
    """Return backend and AI provider health."""

    provider = get_ai_provider()
    ai_status = provider.health_check().to_dict()
    ai_status["enabled"] = settings.ai_enabled
    ai_status["selected_provider"] = settings.ai_provider

    return {
        "status": "ok",
        "message": "Studysis backend service is healthy",
        "ai": ai_status,
    }
