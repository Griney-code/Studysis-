from pydantic import BaseModel, ConfigDict, Field


class OfficialSubtitleCue(BaseModel):
    """One subtitle cue from the platform subtitle file."""

    from_seconds: float = Field(default=0, ge=0, description="Cue start time in seconds")
    to_seconds: float = Field(default=0, ge=0, description="Cue end time in seconds")
    content: str = Field(default="", description="Cue text")


class OfficialSubtitleTrack(BaseModel):
    """One official subtitle track."""

    lang: str = Field(default="", description="Display language name")
    lang_key: str = Field(default="", description="Language key")
    track_type: int = Field(default=0, description="Track type, such as official CC or AI subtitle")
    source: str = Field(default="", description="Where this subtitle track was discovered")
    source_url: str = Field(default="", description="Original subtitle URL")
    segments: list[OfficialSubtitleCue] = Field(default_factory=list, description="Subtitle cue list")


class KeyframePayload(BaseModel):
    """One captured keyframe from the video element."""

    captured_at_seconds: float = Field(default=0, ge=0, description="Capture time in seconds")
    time_label: str = Field(default="", description="Display label for the capture time")
    capture_reason: str = Field(default="", description="Why the keyframe was captured")
    image_data_url: str = Field(default="", description="Data URL of the captured image")
    width: int = Field(default=0, ge=0, description="Image width")
    height: int = Field(default=0, ge=0, description="Image height")


class SourceInfo(BaseModel):
    """Lightweight page source information."""

    title: str = Field(default="", description="Page title")
    url: str = Field(default="", description="Page URL")
    host: str = Field(default="", description="Page host")
    description: str = Field(default="", description="Page description")
    page_text: str = Field(default="", description="Merged page text")
    chapter_titles: list[str] = Field(default_factory=list, description="Visible chapter titles")
    visible_texts: list[str] = Field(default_factory=list, description="Important visible texts")
    subtitle_candidates: list[str] = Field(default_factory=list, description="Subtitle-like text snippets")
    official_subtitle_tracks: list[OfficialSubtitleTrack] = Field(
        default_factory=list,
        description="Official subtitle tracks fetched from the platform",
    )
    bilibili_subtitle_debug: dict = Field(
        default_factory=dict,
        description="Debug payload for Bilibili subtitle collection",
    )
    buffered_ranges: list[str] = Field(default_factory=list, description="Loaded video ranges")
    keyframes: list[KeyframePayload] = Field(default_factory=list, description="Captured keyframes")


class CaptureSnapshot(BaseModel):
    """One lightweight snapshot sent by the extension."""

    start_time: float = Field(default=0, ge=0, description="Snapshot start time")
    end_time: float = Field(default=0, ge=0, description="Snapshot end time")
    time_label: str = Field(default="", description="Display label for the time range")
    subtitle_text: str = Field(default="", description="Current subtitle-like text")
    capture_stage: str = Field(default="preview", description="Capture stage name")
    trigger_reason: str = Field(default="", description="Why this snapshot was sent")
    is_preview_only: bool = Field(default=True, description="Whether this is a preview snapshot")
    loaded_until: float = Field(default=0, ge=0, description="Currently loaded video time")
    loaded_fraction: float = Field(default=0, ge=0, le=1, description="Loaded fraction of the video")


class CollectSegmentRequest(BaseModel):
    """Lightweight collection request."""

    session_id: str = Field(min_length=1, description="Frontend session ID")
    source: SourceInfo = Field(description="Page-level source information")
    segment: CaptureSnapshot = Field(description="Lightweight segment snapshot")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "session_id": "studysis-www.bilibili.com-1710000000000",
                "source": {
                    "title": "高等数学课程",
                    "url": "https://www.example.com/video",
                    "host": "www.example.com",
                    "description": "课程简介",
                    "page_text": "标题 简介 章节标题",
                    "chapter_titles": ["第一章", "第二章"],
                    "visible_texts": ["向量场", "坐标系"],
                    "subtitle_candidates": [],
                    "official_subtitle_tracks": [
                        {
                            "lang": "中文",
                            "lang_key": "zh-CN",
                            "source_url": "https://example.com/subtitle.json",
                            "segments": [
                                {
                                    "from_seconds": 0,
                                    "to_seconds": 2.5,
                                    "content": "这里是一条官方字幕",
                                }
                            ],
                        }
                    ],
                    "buffered_ranges": ["00:00 - 05:20"],
                    "keyframes": [
                        {
                            "captured_at_seconds": 125.4,
                            "time_label": "02:05",
                            "capture_reason": "paused",
                            "image_data_url": "data:image/jpeg;base64,...",
                            "width": 960,
                            "height": 540,
                        }
                    ],
                },
                "segment": {
                    "start_time": 0,
                    "end_time": 320,
                    "time_label": "00:00 - 05:20",
                    "subtitle_text": "",
                    "capture_stage": "preview",
                    "trigger_reason": "video-attached",
                    "is_preview_only": True,
                    "loaded_until": 320,
                    "loaded_fraction": 0.2,
                },
            }
        }
    )
