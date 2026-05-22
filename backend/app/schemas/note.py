from pydantic import BaseModel, Field


class NoteItem(BaseModel):
    """Simple note item for frontend rendering."""

    note_id: str = Field(default="", description="Stable note ID")
    title: str = Field(default="", description="Title")
    content: str = Field(default="", description="Summary content")
    detail: str = Field(default="", description="Expanded detail")
    category: str = Field(default="章节导览", description="Category")
    timestamp: str = Field(default="00:00", description="Display timestamp")
    seconds: float = Field(default=0, description="Seek position in seconds")


class NotesPayload(BaseModel):
    """Lightweight notes payload returned to the frontend."""

    quick_summary: str = Field(default="", description="Quick summary")
    overview_summary: str = Field(default="", description="Overview summary")
    live_summary: str = Field(default="", description="Live progress summary")
    structured_notes: list[NoteItem] = Field(default_factory=list, description="Structured notes")
    detailed_notes: list[NoteItem] = Field(default_factory=list, description="Detailed notes")
    exam_points: list[NoteItem] = Field(default_factory=list, description="Exam points")
    markdown: str = Field(default="", description="Markdown export text")
    backend_message: str = Field(default="", description="Backend status message")
