from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings
from app.services.ai.base import AIProvider, AIProviderStatus, AITextResult

logger = logging.getLogger(__name__)


class CloudProvider(AIProvider):
    """OpenAI-compatible third-party chat completions provider."""

    provider_name = "cloud"

    def is_available(self) -> bool:
        return bool(
            settings.ai_enabled
            and settings.ai_provider == "cloud"
            and settings.cloud_api_base_url
            and settings.cloud_api_key
            and settings.cloud_api_model
        )

    def get_model_name(self) -> str:
        return settings.cloud_api_model

    def get_base_url(self) -> str:
        return settings.cloud_api_base_url

    def health_check(self) -> AIProviderStatus:
        if not self.is_available():
            return AIProviderStatus(
                configured=False,
                available=False,
                reachable=False,
                provider=self.provider_name,
                model=self.get_model_name(),
                base_url=self.get_base_url(),
                message="Cloud provider is not fully configured or not enabled.",
            )

        payload, headers, url = self._build_request(
            system_prompt="You are a health check assistant.",
            user_prompt="Reply with OK only.",
            temperature=0.0,
            max_tokens=8,
        )

        try:
            with httpx.Client(timeout=min(settings.ai_timeout_seconds, 15.0)) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            logger.warning("Cloud provider health check failed with HTTP %s", status_code)
            return AIProviderStatus(
                configured=True,
                available=False,
                reachable=True,
                provider=self.provider_name,
                model=self.get_model_name(),
                base_url=self.get_base_url(),
                message=f"Cloud provider reachable, but request failed with HTTP {status_code}.",
                error=str(error),
            )
        except Exception as error:
            logger.warning("Cloud provider health check failed: %s", error)
            return AIProviderStatus(
                configured=True,
                available=False,
                reachable=False,
                provider=self.provider_name,
                model=self.get_model_name(),
                base_url=self.get_base_url(),
                message="Cloud provider is unreachable.",
                error=str(error),
            )

        content = self._extract_content(data)
        if not content:
            logger.warning(
                "Cloud provider health check returned empty content. raw_response=%s",
                self._stringify_debug_payload(data),
            )

        return AIProviderStatus(
            configured=True,
            available=bool(content),
            reachable=True,
            provider=self.provider_name,
            model=self.get_model_name(),
            base_url=self.get_base_url(),
            message=(
                "Cloud provider connected and returned content."
                if content
                else "Cloud provider responded, but content was empty."
            ),
            error="" if content else "empty response content",
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
                error="cloud provider unavailable",
                provider=self.provider_name,
            )

        payload, headers, url = self._build_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

        try:
            with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as error:
            logger.warning("Cloud provider text generation failed: %s", error)
            return AITextResult(
                success=False,
                error=str(error),
                provider=self.provider_name,
            )

        content = self._extract_content(data)
        if not content:
            logger.warning(
                "Cloud provider returned empty content. raw_response=%s",
                self._stringify_debug_payload(data),
            )
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

    def _build_request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        response_format: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str], str]:
        base_url = settings.cloud_api_base_url.rstrip("/")
        path = settings.cloud_api_path.strip() or "/chat/completions"
        if not path.startswith("/"):
            path = f"/{path}"

        payload: dict[str, Any] = {
            "model": settings.cloud_api_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        if settings.cloud_thinking_type:
            payload["thinking"] = {
                "type": settings.cloud_thinking_type,
            }
            if settings.cloud_clear_thinking:
                payload["thinking"]["clear_thinking"] = True

        headers = {
            "Authorization": f"Bearer {settings.cloud_api_key}",
            "Content-Type": "application/json",
        }
        return payload, headers, f"{base_url}{path}"

    def _extract_content(self, data: dict[str, Any]) -> str:
        output_text = data.get("output_text", "")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        choices = data.get("choices") or []
        if not choices:
            return ""

        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        message = first_choice.get("message") or {}
        content = message.get("content", "")

        if isinstance(content, str):
            normalized = content.strip()
            if normalized:
                return normalized
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text", "")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
                    continue
                nested_content = item.get("content", "")
                if isinstance(nested_content, str) and nested_content.strip():
                    parts.append(nested_content.strip())
            normalized = "\n".join(part for part in parts if part).strip()
            if normalized:
                return normalized

        choice_text = first_choice.get("text", "")
        if isinstance(choice_text, str) and choice_text.strip():
            return choice_text.strip()

        reasoning_content = message.get("reasoning_content", "")
        if isinstance(reasoning_content, str) and reasoning_content.strip():
            return reasoning_content.strip()

        return str(content).strip()

    def _stringify_debug_payload(self, data: dict[str, Any]) -> str:
        try:
            raw = json.dumps(data, ensure_ascii=False)
        except Exception:
            raw = str(data)
        return raw[:4000]
