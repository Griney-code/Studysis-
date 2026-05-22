import json
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.config import settings


class SessionStore:
    """使用本地 JSON 文件保存会话数据。"""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def get(self, session_id: str) -> dict[str, Any] | None:
        """读取指定会话。"""
        path = self._get_path(session_id)
        if not path.exists():
            return None

        with self._lock:
            return json.loads(path.read_text(encoding="utf-8"))

    def save(self, session_id: str, data: dict[str, Any]) -> None:
        """写入指定会话。"""
        path = self._get_path(session_id)

        with self._lock:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

    def list_all(self) -> list[dict[str, Any]]:
        """读取所有会话。"""
        sessions: list[dict[str, Any]] = []
        for path in sorted(self.base_dir.glob("*.json")):
            with self._lock:
                sessions.append(json.loads(path.read_text(encoding="utf-8")))
        return sessions

    def _get_path(self, session_id: str) -> Path:
        safe_id = "".join(char if char.isalnum() or char in "-._" else "_" for char in session_id)
        return self.base_dir / f"{safe_id}.json"


session_store = SessionStore(settings.data_dir / "sessions")
