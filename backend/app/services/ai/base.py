from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


@dataclass
class AITextResult:
    """Unified text generation result."""

    success: bool
    text: str = ""
    error: str = ""
    provider: str = ""


@dataclass
class AIImageInput:
    """One image passed to a multimodal model."""

    image_url: str
    detail: str = "auto"


@dataclass
class AIProviderStatus:
    """Provider health status."""

    configured: bool
    available: bool
    reachable: bool
    provider: str = "none"
    model: str = ""
    base_url: str = ""
    message: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class AIProvider(ABC):
    """Base provider interface."""

    provider_name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Whether the provider is configured and callable."""

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the active model name."""

    @abstractmethod
    def get_base_url(self) -> str:
        """Return the active service base URL."""

    @abstractmethod
    def health_check(self) -> AIProviderStatus:
        """Run a provider health check."""

    @abstractmethod
    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        response_format: str | None = None,
    ) -> AITextResult:
        """Generate text."""

    def supports_vision(self) -> bool:
        """Whether the provider can accept image inputs."""

        return False

    def generate_multimodal(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        images: list[AIImageInput],
        temperature: float,
        max_tokens: int,
        response_format: str | None = None,
    ) -> AITextResult:
        """Generate text from text plus image evidence."""

        return AITextResult(
            success=False,
            error="vision input unsupported",
            provider=self.provider_name,
        )
