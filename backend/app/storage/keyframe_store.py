from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.config import settings


class KeyframeStore:
    """Persist keyframe images plus a lightweight manifest per session."""

    _mime_extension_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def get(self, session_id: str) -> dict[str, Any] | None:
        path = self._get_manifest_path(session_id)
        if not path.exists():
            return None

        with self._lock:
            return json.loads(path.read_text(encoding="utf-8"))

    def save(
        self,
        session_id: str,
        *,
        page_title: str,
        page_url: str,
        host: str,
        keyframes: list[dict[str, Any]],
        updated_at: str,
    ) -> dict[str, Any]:
        manifest = self.get(session_id) or {
            "session_id": session_id,
            "page_title": page_title,
            "page_url": page_url,
            "host": host,
            "first_written_at": updated_at,
            "updated_at": updated_at,
            "items": [],
        }
        manifest["page_title"] = page_title
        manifest["page_url"] = page_url
        manifest["host"] = host
        manifest["updated_at"] = updated_at

        session_dir = self._get_session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        existing_by_sha = {
            item.get("sha1", ""): item
            for item in manifest.get("items", [])
            if item.get("sha1")
        }

        for keyframe in keyframes:
            saved = self._save_single_keyframe(session_dir=session_dir, keyframe=keyframe)
            if saved is None:
                continue
            existing = existing_by_sha.get(saved["sha1"])
            if existing is not None:
                existing["captured_at_seconds"] = min(
                    float(existing.get("captured_at_seconds", saved["captured_at_seconds"])),
                    saved["captured_at_seconds"],
                )
                existing["time_label"] = existing.get("time_label") or saved["time_label"]
                existing["capture_reason"] = existing.get("capture_reason") or saved["capture_reason"]
                continue
            existing_by_sha[saved["sha1"]] = saved

        manifest["items"] = sorted(
            existing_by_sha.values(),
            key=lambda item: (float(item.get("captured_at_seconds", 0) or 0), item.get("sha1", "")),
        )

        with self._lock:
            self._get_manifest_path(session_id).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return manifest

    def _save_single_keyframe(
        self,
        *,
        session_dir: Path,
        keyframe: dict[str, Any],
    ) -> dict[str, Any] | None:
        data_url = str(keyframe.get("image_data_url", "") or "").strip()
        if not data_url.startswith("data:image/"):
            return None

        try:
            header, encoded = data_url.split(",", 1)
        except ValueError:
            return None

        mime_type = header[5:].split(";", 1)[0].strip().lower()
        if not mime_type.startswith("image/"):
            return None

        try:
            raw_bytes = base64.b64decode(encoded, validate=True)
        except Exception:
            return None

        if not raw_bytes:
            return None

        sha1 = hashlib.sha1(raw_bytes).hexdigest()
        extension = self._mime_extension_map.get(mime_type, ".bin")
        image_path = session_dir / f"{sha1}{extension}"
        if not image_path.exists():
            image_path.write_bytes(raw_bytes)

        return {
            "keyframe_id": sha1,
            "sha1": sha1,
            "captured_at_seconds": float(keyframe.get("captured_at_seconds", 0) or 0),
            "time_label": str(keyframe.get("time_label", "") or ""),
            "capture_reason": str(keyframe.get("capture_reason", "") or ""),
            "mime_type": mime_type,
            "width": int(keyframe.get("width", 0) or 0),
            "height": int(keyframe.get("height", 0) or 0),
            "image_path": str(image_path),
        }

    def _get_manifest_path(self, session_id: str) -> Path:
        return self.base_dir / f"{self._sanitize_session_id(session_id)}.json"

    def _get_session_dir(self, session_id: str) -> Path:
        return self.base_dir / self._sanitize_session_id(session_id)

    def _sanitize_session_id(self, session_id: str) -> str:
        return "".join(char if char.isalnum() or char in "-._" else "_" for char in session_id)


keyframe_store = KeyframeStore(settings.data_dir / "keyframes")
