from app.core.config import settings
from app.storage.session_store import SessionStore


subtitle_store = SessionStore(settings.data_dir / "subtitles")
