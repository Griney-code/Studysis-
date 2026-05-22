from fastapi import APIRouter, HTTPException, status

from app.schemas.collect import CollectSegmentRequest
from app.schemas.response import ApiResponse, CollectResponseData
from app.services.collect_service import collect_service

router = APIRouter()


@router.post("/segment", response_model=ApiResponse[CollectResponseData])
async def collect_segment(payload: CollectSegmentRequest) -> ApiResponse[CollectResponseData]:
    """Store one lightweight snapshot from the browser extension."""

    try:
        result = collect_service.handle_segment(payload)
        return ApiResponse.ok(message="segment received", data=result)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
