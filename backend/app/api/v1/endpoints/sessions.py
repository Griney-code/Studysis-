from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse

from app.schemas.response import ApiResponse, SessionDetailResponse, SessionListResponse
from app.services.collect_service import collect_service

router = APIRouter()


@router.get("", response_model=ApiResponse[SessionListResponse])
async def list_sessions() -> ApiResponse[SessionListResponse]:
    """Return all stored sessions."""

    data = collect_service.list_sessions()
    return ApiResponse.ok(message="sessions fetched", data=data)


@router.get("/{session_id}", response_model=ApiResponse[SessionDetailResponse])
async def get_session(session_id: str) -> ApiResponse[SessionDetailResponse]:
    """Return one stored session."""

    data = collect_service.get_session_detail(session_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )
    return ApiResponse.ok(message="session fetched", data=data)


@router.get("/{session_id}/debug")
async def get_session_debug(session_id: str) -> dict:
    """Return debug information for one session."""

    data = collect_service.get_session_debug(session_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )
    return {
        "success": True,
        "message": "session debug fetched",
        "data": data,
    }


@router.get("/{session_id}/bootstrap")
async def get_session_bootstrap(session_id: str) -> dict:
    """Return the stored bootstrap snapshot for one session."""

    data = collect_service.get_session_bootstrap(session_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="bootstrap snapshot not found",
        )
    return {
        "success": True,
        "message": "session bootstrap fetched",
        "data": data,
    }


@router.get("/{session_id}/markdown", response_class=PlainTextResponse)
async def export_session_markdown(session_id: str) -> PlainTextResponse:
    """Export one session as Markdown."""

    markdown = collect_service.export_markdown(session_id)
    if markdown is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )
    return PlainTextResponse(content=markdown, media_type="text/markdown; charset=utf-8")
