from app.core.config import settings
from app.storage.session_store import SessionStore


bootstrap_store = SessionStore(settings.data_dir / "bootstrap")
