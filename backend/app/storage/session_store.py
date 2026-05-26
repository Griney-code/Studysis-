import json
from copy import deepcopy
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, TypeVar

from app.core.config import settings

T = TypeVar("T")


class SessionStore:
    """Use local JSON files to persist session data."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._locks_guard = Lock()
        self._session_locks: dict[str, RLock] = {}

    def get(self, session_id: str) -> dict[str, Any] | None:
        path = self._get_path(session_id)
        if not path.exists():
            return None

        with self._get_session_lock(session_id):
            return self._read_path(path)

    def save(self, session_id: str, data: dict[str, Any]) -> None:
        path = self._get_path(session_id)
        with self._get_session_lock(session_id):
            self._write_path(path, data)

    def update(
        self,
        session_id: str,
        updater: Callable[[dict[str, Any]], T],
        *,
        create_default: Callable[[], dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any] | None, T | None]:
        path = self._get_path(session_id)
        with self._get_session_lock(session_id):
            current = self._read_path(path) if path.exists() else None
            if current is None:
                if create_default is None:
                    return None, None
                current = create_default()

            working = deepcopy(current)
            result = updater(working)
            self._write_path(path, working)
            return working, result

    def list_all(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for path in sorted(self.base_dir.glob("*.json")):
            with self._get_session_lock(path.stem):
                sessions.append(self._read_path(path))
        return sessions

    def _get_path(self, session_id: str) -> Path:
        safe_id = self._to_safe_id(session_id)
        return self.base_dir / f"{safe_id}.json"

    def _get_session_lock(self, session_id: str) -> RLock:
        safe_id = self._to_safe_id(session_id)
        with self._locks_guard:
            lock = self._session_locks.get(safe_id)
            if lock is None:
                lock = RLock()
                self._session_locks[safe_id] = lock
            return lock

    def _to_safe_id(self, session_id: str) -> str:
        return "".join(char if char.isalnum() or char in "-._" else "_" for char in session_id)

    def _read_path(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_path(self, path: Path, data: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


session_store = SessionStore(settings.data_dir / "sessions")
