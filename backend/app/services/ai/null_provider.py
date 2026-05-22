from __future__ import annotations

from app.services.ai.base import AIProvider, AIProviderStatus, AITextResult


class NullProvider(AIProvider):
    """空 Provider，用于未启用 AI 的情况。"""

    provider_name = "none"

    def is_available(self) -> bool:
        return False

    def get_model_name(self) -> str:
        return ""

    def get_base_url(self) -> str:
        return ""

    def health_check(self) -> AIProviderStatus:
        return AIProviderStatus(
            configured=False,
            available=False,
            reachable=False,
            provider=self.provider_name,
            message="AI 未启用或未选择可用 Provider。",
        )

    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        response_format: str | None = None,
    ) -> AITextResult:
        return AITextResult(
            success=False,
            error="ai disabled",
            provider=self.provider_name,
        )
