from __future__ import annotations

from app.core.config import settings
from app.services.ai.base import AIProvider
from app.services.ai.cloud_provider import CloudProvider
from app.services.ai.local_provider import LocalProvider
from app.services.ai.null_provider import NullProvider


def get_ai_provider() -> AIProvider:
    """Backward-compatible alias for the text provider."""

    return get_text_ai_provider()


def get_text_ai_provider() -> AIProvider:
    """Return the configured text provider."""

    if not settings.ai_enabled:
        return NullProvider()

    provider_name = settings.ai_provider.strip().lower()
    if provider_name == "local":
        return LocalProvider()
    if provider_name == "cloud":
        return CloudProvider(model_name=settings.cloud_api_model, vision_enabled=False)
    return NullProvider()


def get_vision_ai_provider() -> AIProvider:
    """Return the configured vision provider."""

    if not settings.ai_enabled:
        return NullProvider()

    provider_name = settings.ai_provider.strip().lower()
    if provider_name != "cloud":
        return NullProvider()
    if not settings.cloud_vision_api_model.strip():
        return NullProvider()
    return CloudProvider(model_name=settings.cloud_vision_api_model, vision_enabled=True)
