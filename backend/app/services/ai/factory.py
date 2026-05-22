from __future__ import annotations

from app.core.config import settings
from app.services.ai.base import AIProvider
from app.services.ai.cloud_provider import CloudProvider
from app.services.ai.local_provider import LocalProvider
from app.services.ai.null_provider import NullProvider


def get_ai_provider() -> AIProvider:
    """根据配置返回当前 AI Provider。"""
    if not settings.ai_enabled:
        return NullProvider()

    provider_name = settings.ai_provider.strip().lower()
    if provider_name == "local":
        return LocalProvider()
    if provider_name == "cloud":
        return CloudProvider()
    return NullProvider()
