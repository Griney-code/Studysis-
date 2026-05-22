from app.core.config import settings
from app.storage.session_store import SessionStore


analysis_debug_store = SessionStore(settings.data_dir / "analysis_debug")
