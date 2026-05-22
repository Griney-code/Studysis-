from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


@dataclass
class AITextResult:
    """统一的文本生成结果。"""

    success: bool
    text: str = ""
    error: str = ""
    provider: str = ""


@dataclass
class AIProviderStatus:
    """Provider 健康状态。"""

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
    """AI Provider 抽象接口。"""

    provider_name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """当前 Provider 是否具备调用配置。"""

    @abstractmethod
    def get_model_name(self) -> str:
        """返回当前模型名。"""

    @abstractmethod
    def get_base_url(self) -> str:
        """返回当前服务地址。"""

    @abstractmethod
    def health_check(self) -> AIProviderStatus:
        """检查 Provider 健康状态。"""

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
        """生成文本。"""
