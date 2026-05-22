"""
Studysis 本地后端启动脚本。

执行方式：
python scripts/start_backend.py
"""

from pathlib import Path
import sys

import uvicorn


CURRENT_FILE = Path(__file__).resolve()
BACKEND_ROOT = CURRENT_FILE.parents[1]

# 保证从 backend 根目录外执行该脚本时，也能正确导入 app 包。
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False
    )
