from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.services.ai.base import AIProvider, AIProviderStatus, AITextResult

logger = logging.getLogger(__name__)


class LocalProvider(AIProvider):
    """Ollama 本地模型 Provider。"""

    provider_name = "local"

    def is_available(self) -> bool:
        return bool(
            settings.ai_enabled
            and settings.ai_provider == "local"
            and settings.ollama_base_url
            and settings.ollama_model
        )

    def get_model_name(self) -> str:
        return settings.ollama_model

    def get_base_url(self) -> str:
        return settings.ollama_base_url

    def health_check(self) -> AIProviderStatus:
        if not self.is_available():
            return AIProviderStatus(
                configured=False,
                available=False,
                reachable=False,
                provider=self.provider_name,
                model=self.get_model_name(),
                base_url=self.get_base_url(),
                message="Ollama 配置未完成或当前未启用 local Provider。",
            )

        try:
            with httpx.Client(timeout=min(settings.ai_timeout_seconds, 10.0)) as client:
                response = client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
                response.raise_for_status()
                data = response.json()
        except Exception as error:
            logger.warning("Ollama 健康检查失败: %s", error)
            return AIProviderStatus(
                configured=True,
                available=False,
                reachable=False,
                provider=self.provider_name,
                model=self.get_model_name(),
                base_url=self.get_base_url(),
                message="Ollama 服务不可达。",
                error=str(error),
            )

        models = data.get("models") or []
        model_names = {
            str(item.get("name", "")).strip()
            for item in models
            if isinstance(item, dict)
        }
        model_exists = settings.ollama_model in model_names
        if not model_exists:
            return AIProviderStatus(
                configured=True,
                available=False,
                reachable=True,
                provider=self.provider_name,
                model=self.get_model_name(),
                base_url=self.get_base_url(),
                message="Ollama 已连接，但目标模型未拉取。",
                error=f"model '{settings.ollama_model}' not found",
            )

        probe_result = self.generate_text(
            system_prompt="你是健康检查助手。",
            user_prompt="请只回复：OK",
            temperature=0.0,
            max_tokens=48,
        )
        if not probe_result.success:
            return AIProviderStatus(
                configured=True,
                available=False,
                reachable=True,
                provider=self.provider_name,
                model=self.get_model_name(),
                base_url=self.get_base_url(),
                message="Ollama 已连接，但模型未返回有效内容。",
                error=probe_result.error,
            )

        return AIProviderStatus(
            configured=True,
            available=True,
            reachable=True,
            provider=self.provider_name,
            model=self.get_model_name(),
            base_url=self.get_base_url(),
            message="Ollama 已连接，模型可正常生成内容。",
            error="",
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
        if not self.is_available():
            return AITextResult(
                success=False,
                error="local provider unavailable",
                provider=self.provider_name,
            )

        payload = {
            "model": settings.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "keep_alive": settings.ollama_keep_alive,
        }
        if response_format == "json":
            payload["format"] = "json"

        try:
            with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
                response = client.post(
                    f"{settings.ollama_base_url.rstrip('/')}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as error:
            logger.warning("Ollama 文本生成失败: %s", error)
            return AITextResult(
                success=False,
                error=str(error),
                provider=self.provider_name,
            )

        message = data.get("message") or {}
        content = str(message.get("content", "")).strip()
        if not content:
            thinking = str(message.get("thinking", "")).strip()
            if thinking:
                logger.warning("Ollama 返回了推理内容但没有最终答案，当前模型可能为强推理模型。")
                return AITextResult(
                    success=False,
                    error="reasoning-only output; try a non-reasoning model such as qwen2.5:3b or increase max_tokens",
                    provider=self.provider_name,
                )
            logger.warning("Ollama 文本生成返回空内容。")
            return AITextResult(
                success=False,
                error="empty response content",
                provider=self.provider_name,
            )

        return AITextResult(
            success=True,
            text=content,
            provider=self.provider_name,
        )
