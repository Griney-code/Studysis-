from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Studysis 在线网课知识视频智能笔记总结系统本地后端服务"
    )

    # 允许浏览器插件直接访问本地后端。
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )

    application.include_router(api_router, prefix=settings.api_v1_prefix)
    application.mount(
        "/media/keyframes",
        StaticFiles(directory=settings.data_dir / "keyframes"),
        name="keyframes",
    )

    @application.get("/", tags=["system"])
    async def root() -> dict:
        """服务根路由，用于快速检查服务状态。"""
        return {
            "message": "Studysis backend is running",
            "version": settings.app_version
        }

    return application


app = create_app()
