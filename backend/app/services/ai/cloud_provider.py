from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings
from app.services.ai.base import AIImageInput, AIProvider, AIProviderStatus, AITextResult

logger = logging.getLogger(__name__)


class CloudProvider(AIProvider):
    """OpenAI-compatible third-party chat completions provider."""

    provider_name = "cloud"

    def __init__(self, *, model_name: str | None = None, vision_enabled: bool = False) -> None:
        self._model_name_override = (model_name or "").strip()
        self._vision_enabled = vision_enabled

    def is_available(self) -> bool:
        return bool(
            settings.ai_enabled
            and settings.ai_provider == "cloud"
            and settings.cloud_api_base_url
            and settings.cloud_api_key
            and self.get_model_name()
        )

    def get_model_name(self) -> str:
        return self._model_name_override or settings.cloud_api_model

    def get_base_url(self) -> str:
        return settings.cloud_api_base_url

    def supports_vision(self) -> bool:
        return self._vision_enabled and self.is_available()

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

        payload, headers, url = self._build_text_request(
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

        payload, headers, url = self._build_text_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return self._post_request(payload=payload, headers=headers, url=url)

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
        if not self.supports_vision():
            return AITextResult(
                success=False,
                error="cloud vision provider unavailable",
                provider=self.provider_name,
            )

        payload, headers, url = self._build_multimodal_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            images=images,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return self._post_request(payload=payload, headers=headers, url=url)

    def _post_request(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
        url: str,
    ) -> AITextResult:
        try:
            data = self._post_json_with_retry(
                payload=payload,
                headers=headers,
                url=url,
            )
        except Exception as error:
            logger.warning("Cloud provider request failed: %s", error)
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

    def _post_json_with_retry(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
        url: str,
    ) -> dict[str, Any]:
        timeouts = self._build_timeout_schedule(payload)
        last_error: Exception | None = None

        for timeout_seconds in timeouts:
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    return response.json()
            except httpx.ReadTimeout as error:
                last_error = error
                logger.warning(
                    "Cloud provider read timeout after %.1fs, retrying if possible.",
                    timeout_seconds,
                )
                continue

        if last_error is not None:
            raise last_error

        base_timeout = max(settings.ai_timeout_seconds, 15.0)
        with httpx.Client(timeout=base_timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    def _build_timeout_schedule(self, payload: dict[str, Any]) -> list[float]:
        base_timeout = max(settings.ai_timeout_seconds, 15.0)
        if self._payload_has_images(payload):
            first_timeout = max(base_timeout, 50.0)
            second_timeout = max(first_timeout + 30.0, base_timeout * 2.4)
            return [first_timeout, second_timeout]

        return [base_timeout, max(base_timeout + 20.0, base_timeout * 1.8)]

    def _payload_has_images(self, payload: dict[str, Any]) -> bool:
        messages = payload.get("messages") or []
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    return True
        return False

    def _build_text_request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        response_format: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str], str]:
        payload = self._build_base_payload(
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        payload["messages"] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return payload, self._build_headers(), self._build_url()

    def _build_multimodal_request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        images: list[AIImageInput],
        temperature: float,
        max_tokens: int,
        response_format: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str], str]:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for image in images:
            if not image.image_url:
                continue
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image.image_url,
                        "detail": image.detail,
                    },
                }
            )

        payload = self._build_base_payload(
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        payload["messages"] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]
        return payload, self._build_headers(), self._build_url()

    def _build_base_payload(
        self,
        *,
        temperature: float,
        max_tokens: int,
        response_format: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.get_model_name(),
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
        return payload

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.cloud_api_key}",
            "Content-Type": "application/json",
        }

    def _build_url(self) -> str:
        base_url = settings.cloud_api_base_url.rstrip("/")
        path = settings.cloud_api_path.strip() or "/chat/completions"
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{base_url}{path}"

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
