from fastapi import APIRouter

from app.api.v1.endpoints import collect, health, sessions

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(collect.router, prefix="/collect", tags=["collect"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
