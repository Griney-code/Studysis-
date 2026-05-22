from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

from app.schemas.note import NotesPayload

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard API response envelope."""

    success: bool = Field(description="Whether the request succeeded")
    message: str = Field(default="", description="Response message")
    data: Optional[T] = Field(default=None, description="Response payload")

    @classmethod
    def ok(cls, message: str, data: Optional[T] = None) -> "ApiResponse[T]":
        return cls(success=True, message=message, data=data)


class SegmentStoredData(BaseModel):
    """Stored snapshot summary returned after collection."""

    start_time: float
    end_time: float
    time_label: str
    subtitle_text: str = ""
    effective_text: str = ""
    text_source: str = "unknown"
    subtitle_source: str = "none"
    capture_stage: str = "preview"
    trigger_reason: str = ""


class CollectResponseData(BaseModel):
    """Response payload for the collection endpoint."""

    session_id: str
    received_segment: SegmentStoredData
    notes: NotesPayload
    analysis_status: str = "idle"
    analysis_message: str = ""


class SessionSummaryItem(BaseModel):
    """One item in the session list."""

    session_id: str
    page_title: str
    page_url: str
    host: str
    segment_count: int
    latest_time_label: str
    updated_at: str


class SessionListResponse(BaseModel):
    """Session list payload."""

    sessions: list[SessionSummaryItem] = Field(default_factory=list)
    total: int = 0


class StoredSegmentRecord(BaseModel):
    """One stored lightweight snapshot inside a session."""

    start_time: float
    end_time: float
    time_label: str
    subtitle_text: str = ""
    effective_text: str = ""
    text_source: str = "unknown"
    subtitle_source: str = "none"
    capture_stage: str = "preview"
    trigger_reason: str = ""
    is_preview_only: bool = True
    loaded_until: float = 0
    loaded_fraction: float = 0


class SessionDetailResponse(BaseModel):
    """Full stored session payload."""

    session_id: str
    page_title: str
    page_url: str
    host: str
    segment_count: int
    notes: NotesPayload
    analysis_status: str = "idle"
    analysis_message: str = ""
    segments: list[StoredSegmentRecord] = Field(default_factory=list)
    created_at: str
    updated_at: str
