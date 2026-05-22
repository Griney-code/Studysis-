from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Any

from app.schemas.collect import CollectSegmentRequest, SourceInfo
from app.schemas.note import NotesPayload
from app.schemas.response import (
    CollectResponseData,
    SegmentStoredData,
    SessionDetailResponse,
    SessionListResponse,
    SessionSummaryItem,
    StoredSegmentRecord,
)
from app.storage.bootstrap_store import bootstrap_store
from app.storage.session_store import session_store
from app.storage.subtitle_store import subtitle_store
from app.storage.subtitle_debug_store import subtitle_debug_store
from app.storage.analysis_debug_store import analysis_debug_store
from app.services.subtitle_analysis_service import subtitle_analysis_service

logger = logging.getLogger(__name__)


class CollectService:
    """Lightweight collection service skeleton."""

    _max_segments = 12

    def __init__(self) -> None:
        self._analysis_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="studysis-analysis",
        )
        self._analysis_lock = Lock()
        self._analysis_futures: dict[str, Future[Any]] = {}

    def handle_segment(self, payload: CollectSegmentRequest) -> CollectResponseData:
        self._validate_segment_time(payload)

        now = self._now()
        session = session_store.get(payload.session_id) or self._create_empty_session(payload, now)
        session["page_title"] = payload.source.title or session.get("page_title", "")
        session["page_url"] = payload.source.url or session.get("page_url", "")
        session["host"] = payload.source.host or session.get("host", "")
        session["updated_at"] = now

        source_context = self._extract_source_context(payload.source)
        self._merge_source_context(session, source_context, now)
        self._save_official_subtitles(
            session_id=payload.session_id,
            session=session,
            source_context=source_context,
            now=now,
        )
        self._save_subtitle_debug(
            session_id=payload.session_id,
            session=session,
            source_context=source_context,
            now=now,
        )

        segment_record = self._build_segment_record(payload)
        self._append_segment(session, segment_record)
        session["progress"] = self._build_progress_snapshot(session, segment_record)
        notes, should_enqueue_analysis = self._resolve_notes_async(
            session_id=payload.session_id,
            session=session,
        )
        session["notes"] = notes.model_dump()

        session_store.save(payload.session_id, session)
        if should_enqueue_analysis:
            self._enqueue_analysis(payload.session_id)
        self._save_bootstrap_snapshot(
            session=session,
            session_id=payload.session_id,
            segment_record=segment_record,
            now=now,
        )

        return CollectResponseData(
            session_id=payload.session_id,
            received_segment=SegmentStoredData(
                start_time=segment_record["start_time"],
                end_time=segment_record["end_time"],
                time_label=segment_record["time_label"],
                subtitle_text=segment_record["subtitle_text"],
                effective_text=segment_record["effective_text"],
                text_source=segment_record["text_source"],
                subtitle_source=segment_record["subtitle_source"],
                capture_stage=segment_record["capture_stage"],
                trigger_reason=segment_record["trigger_reason"],
            ),
            notes=NotesPayload.model_validate(session["notes"]),
            analysis_status=session.get("analysis", {}).get("status", "idle"),
            analysis_message=session.get("analysis", {}).get("message", ""),
        )

    def list_sessions(self) -> SessionListResponse:
        sessions = session_store.list_all()
        items = [
            SessionSummaryItem(
                session_id=item["session_id"],
                page_title=item.get("page_title", ""),
                page_url=item.get("page_url", ""),
                host=item.get("host", ""),
                segment_count=len(item.get("segments", [])),
                latest_time_label=item.get("segments", [{}])[-1].get("time_label", "") if item.get("segments") else "",
                updated_at=item.get("updated_at", ""),
            )
            for item in sessions
        ]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return SessionListResponse(sessions=items, total=len(items))

    def get_session_detail(self, session_id: str) -> SessionDetailResponse | None:
        session = session_store.get(session_id)
        if session is None:
            return None

        return SessionDetailResponse(
            session_id=session["session_id"],
            page_title=session.get("page_title", ""),
            page_url=session.get("page_url", ""),
            host=session.get("host", ""),
            segment_count=len(session.get("segments", [])),
            notes=NotesPayload.model_validate(session.get("notes", {})),
            analysis_status=session.get("analysis", {}).get("status", "idle"),
            analysis_message=session.get("analysis", {}).get("message", ""),
            segments=[
                StoredSegmentRecord(
                    start_time=item.get("start_time", 0),
                    end_time=item.get("end_time", 0),
                    time_label=item.get("time_label", ""),
                    subtitle_text=item.get("subtitle_text", ""),
                    effective_text=item.get("effective_text", ""),
                    text_source=item.get("text_source", "unknown"),
                    subtitle_source=item.get("subtitle_source", "none"),
                    capture_stage=item.get("capture_stage", "preview"),
                    trigger_reason=item.get("trigger_reason", ""),
                    is_preview_only=item.get("is_preview_only", True),
                    loaded_until=item.get("loaded_until", 0),
                    loaded_fraction=item.get("loaded_fraction", 0),
                )
                for item in session.get("segments", [])
            ],
            created_at=session.get("created_at", ""),
            updated_at=session.get("updated_at", ""),
        )

    def get_session_debug(self, session_id: str) -> dict[str, Any] | None:
        session = session_store.get(session_id)
        if session is None:
            return None

        session_file = session_store._get_path(session_id)
        bootstrap_file = bootstrap_store._get_path(session_id)
        subtitle_file = subtitle_store._get_path(session_id)
        subtitle_debug_file = subtitle_debug_store._get_path(session_id)
        analysis_debug_file = analysis_debug_store._get_path(session_id)

        return {
            "session_id": session.get("session_id", session_id),
            "mode": "lightweight",
            "page_title": session.get("page_title", ""),
            "page_url": session.get("page_url", ""),
            "host": session.get("host", ""),
            "session_file": str(session_file),
            "bootstrap_file": str(bootstrap_file),
            "subtitle_file": str(subtitle_file),
            "subtitle_debug_file": str(subtitle_debug_file),
            "analysis_debug_file": str(analysis_debug_file),
            "artifact_exists": {
                "session_file": session_file.exists(),
                "bootstrap_file": bootstrap_file.exists(),
                "subtitle_file": subtitle_file.exists(),
                "subtitle_debug_file": subtitle_debug_file.exists(),
                "analysis_debug_file": analysis_debug_file.exists(),
            },
            "stats": {
                "total_segments": len(session.get("segments", [])),
                "preview_segments": sum(1 for item in session.get("segments", []) if item.get("is_preview_only")),
                "formal_segments": sum(1 for item in session.get("segments", []) if not item.get("is_preview_only")),
            },
            "page_context": session.get("page_context", {}),
            "progress": session.get("progress", {}),
            "analysis": session.get("analysis", {}),
            "segments_preview": session.get("segments", [])[-6:],
            "notes": session.get("notes", {}),
        }

    def get_session_bootstrap(self, session_id: str) -> dict[str, Any] | None:
        snapshot = bootstrap_store.get(session_id)
        if snapshot is not None:
            return snapshot

        session = session_store.get(session_id)
        if session is None:
            return None

        fallback_segment = (session.get("segments") or [{}])[0]
        snapshot = self._build_bootstrap_snapshot(
            session=session,
            session_id=session_id,
            segment_record=fallback_segment,
            now=session.get("updated_at") or session.get("created_at") or self._now(),
            existing={},
        )
        bootstrap_store.save(session_id, snapshot)
        return snapshot

    def export_markdown(self, session_id: str) -> str | None:
        session = session_store.get(session_id)
        if session is None:
            return None

        notes = NotesPayload.model_validate(session.get("notes", {}))
        if notes.markdown:
            return notes.markdown

        return "\n".join(
            [
                f"# {session.get('page_title', 'Studysis Session')}",
                "",
                f"- Page URL: {session.get('page_url', '')}",
                "",
                notes.backend_message or "No backend message available.",
                "",
            ]
        )

    def _create_empty_session(self, payload: CollectSegmentRequest, now: str) -> dict[str, Any]:
        return {
            "session_id": payload.session_id,
            "page_title": payload.source.title,
            "page_url": payload.source.url,
            "host": payload.source.host,
            "created_at": now,
            "updated_at": now,
            "segments": [],
            "notes": self._build_placeholder_notes().model_dump(),
            "page_context": {
                "title": payload.source.title,
                "description": "",
                "page_text": "",
                "chapter_titles": [],
                "visible_texts": [],
                "subtitle_candidates": [],
                "official_subtitle_summary": [],
                "official_subtitle_track_count": 0,
                "subtitle_debug_available": False,
                "buffered_ranges": [],
                "combined_text": "",
                "updated_at": now,
            },
            "progress": {
                "loaded_until": 0.0,
                "loaded_fraction": 0.0,
                "last_capture_stage": "preview",
            },
            "analysis": {
                "status": "idle",
                "message": "",
            },
        }

    def _extract_source_context(self, source: SourceInfo) -> dict[str, Any]:
        title = self._clean_text(source.title)
        description = self._clean_text(source.description)
        page_text = self._clean_text(source.page_text)
        chapter_titles = self._dedupe_items(source.chapter_titles, 8)
        visible_texts = self._dedupe_items(source.visible_texts, 8)
        subtitle_candidates = self._dedupe_items(source.subtitle_candidates, 12)
        official_tracks = self._normalize_official_subtitle_tracks(source)
        subtitle_debug = self._normalize_subtitle_debug(source.bilibili_subtitle_debug)
        official_subtitle_summary = [
            {
                "lang": track["lang"],
                "lang_key": track["lang_key"],
                "track_type": track["track_type"],
                "source": track["source"],
                "segment_count": len(track["segments"]),
            }
            for track in official_tracks
        ]
        official_subtitle_preview = self._build_official_subtitle_preview(official_tracks, 24)
        subtitle_candidates = self._dedupe_items(
            [*subtitle_candidates, *official_subtitle_preview],
            24,
        )
        buffered_ranges = self._dedupe_items(source.buffered_ranges, 6)

        combined_text = self._clean_text(
            " ".join(
                [title, description, page_text, *chapter_titles, *visible_texts, *subtitle_candidates]
            )
        )

        return {
            "title": title,
            "description": description,
            "page_text": page_text,
            "chapter_titles": chapter_titles,
            "visible_texts": visible_texts,
            "subtitle_candidates": subtitle_candidates,
            "official_subtitle_tracks": official_tracks,
            "official_subtitle_summary": official_subtitle_summary,
            "subtitle_debug": subtitle_debug,
            "buffered_ranges": buffered_ranges,
            "combined_text": combined_text,
        }

    def _merge_source_context(self, session: dict[str, Any], source_context: dict[str, Any], now: str) -> None:
        page_context = session.get("page_context", {})
        page_context["title"] = source_context.get("title") or page_context.get("title", "")
        page_context["description"] = source_context.get("description") or page_context.get("description", "")
        page_context["page_text"] = source_context.get("page_text") or page_context.get("page_text", "")
        page_context["chapter_titles"] = self._dedupe_items(
            [*page_context.get("chapter_titles", []), *source_context.get("chapter_titles", [])],
            8,
        )
        page_context["visible_texts"] = self._dedupe_items(
            [*page_context.get("visible_texts", []), *source_context.get("visible_texts", [])],
            8,
        )
        page_context["subtitle_candidates"] = self._dedupe_items(
            [*page_context.get("subtitle_candidates", []), *source_context.get("subtitle_candidates", [])],
            24,
        )
        existing_summary = page_context.get("official_subtitle_summary", [])
        page_context["official_subtitle_summary"] = (
            source_context.get("official_subtitle_summary") or existing_summary
        )
        page_context["official_subtitle_track_count"] = len(
            source_context.get("official_subtitle_tracks", [])
        ) or page_context.get("official_subtitle_track_count", 0)
        page_context["subtitle_debug_available"] = bool(source_context.get("subtitle_debug"))
        page_context["buffered_ranges"] = self._dedupe_items(
            [*page_context.get("buffered_ranges", []), *source_context.get("buffered_ranges", [])],
            6,
        )
        page_context["combined_text"] = source_context.get("combined_text") or page_context.get("combined_text", "")
        page_context["updated_at"] = now
        session["page_context"] = page_context

    def _build_segment_record(self, payload: CollectSegmentRequest) -> dict[str, Any]:
        subtitle_text = self._clean_text(payload.segment.subtitle_text)
        return {
            "start_time": float(payload.segment.start_time),
            "end_time": float(payload.segment.end_time),
            "time_label": payload.segment.time_label or self._format_range(payload.segment.start_time, payload.segment.end_time),
            "subtitle_text": subtitle_text,
            "effective_text": subtitle_text,
            "text_source": "subtitle" if subtitle_text else "unknown",
            "subtitle_source": "page_subtitle" if subtitle_text else "none",
            "capture_stage": payload.segment.capture_stage or "preview",
            "trigger_reason": payload.segment.trigger_reason or "",
            "is_preview_only": bool(payload.segment.is_preview_only),
            "loaded_until": float(payload.segment.loaded_until or 0),
            "loaded_fraction": float(payload.segment.loaded_fraction or 0),
        }

    def _append_segment(self, session: dict[str, Any], segment_record: dict[str, Any]) -> None:
        segments = session.get("segments", [])
        if segments and segments[-1].get("time_label") == segment_record["time_label"]:
            segments[-1] = segment_record
        else:
            segments.append(segment_record)
        session["segments"] = segments[-self._max_segments :]

    def _build_progress_snapshot(self, session: dict[str, Any], segment_record: dict[str, Any]) -> dict[str, Any]:
        previous = session.get("progress", {})
        return {
            "loaded_until": max(
                float(previous.get("loaded_until", 0) or 0),
                float(segment_record.get("loaded_until", 0) or 0),
                float(segment_record.get("end_time", 0) or 0),
            ),
            "loaded_fraction": max(
                float(previous.get("loaded_fraction", 0) or 0),
                float(segment_record.get("loaded_fraction", 0) or 0),
            ),
            "last_capture_stage": segment_record.get("capture_stage", "preview"),
        }

    def _build_placeholder_notes(self) -> NotesPayload:
        return NotesPayload(
            quick_summary="",
            overview_summary="",
            live_summary="",
            structured_notes=[],
            detailed_notes=[],
            exam_points=[],
            markdown="",
            backend_message="当前为轻量重构骨架，旧的高频采集、自动转写和自动分析逻辑已移除。",
        )

    def _resolve_notes_async(
        self,
        *,
        session_id: str,
        session: dict[str, Any],
    ) -> tuple[NotesPayload, bool]:
        existing_notes = NotesPayload.model_validate(session.get("notes", {}))
        subtitle_payload = subtitle_store.get(session_id)
        if subtitle_payload is None:
            session["analysis"] = {
                **session.get("analysis", {}),
                "status": "idle",
                "message": "No official subtitles available yet.",
            }
            notes = existing_notes if self._notes_have_content(existing_notes) else self._build_placeholder_notes()
            return notes, False

        subtitle_updated_at = self._clean_text(subtitle_payload.get("updated_at", ""))
        analysis_meta = session.get("analysis", {})
        provider_signature = self._get_current_provider_signature()
        analysis_debug_exists = analysis_debug_store._get_path(session_id).exists()
        notes_ready = self._notes_have_content(existing_notes)
        analysis_up_to_date = (
            analysis_meta.get("status") == "completed"
            and analysis_meta.get("subtitle_updated_at") == subtitle_updated_at
            and analysis_meta.get("provider_signature") == provider_signature
            and analysis_debug_exists
            and notes_ready
        )
        if analysis_up_to_date:
            return existing_notes, False

        if (
            analysis_meta.get("status") in {"pending", "running"}
            and analysis_meta.get("subtitle_updated_at") == subtitle_updated_at
            and analysis_meta.get("provider_signature") == provider_signature
        ):
            return self._build_processing_notes(existing_notes), False

        instant_preview_notes = subtitle_analysis_service.build_instant_preview_notes(
            session=session,
            subtitle_payload=subtitle_payload,
        )
        session["analysis"] = {
            **analysis_meta,
            "status": "pending",
            "message": "Instant preview ready. Full analysis queued in background.",
            "provider_signature": provider_signature,
            "subtitle_updated_at": subtitle_updated_at,
            "requested_at": self._now(),
            "started_at": analysis_meta.get("started_at", ""),
            "completed_at": "",
            "ai_error": "",
            "phase": "preview_ready",
        }
        return instant_preview_notes, True

    def _build_processing_notes(self, existing_notes: NotesPayload) -> NotesPayload:
        if self._notes_have_content(existing_notes):
            return existing_notes.model_copy(
                update={
                    "backend_message": "Refreshing analysis in background.",
                }
            )

        return NotesPayload(
            quick_summary="",
            overview_summary="",
            live_summary="",
            structured_notes=[],
            detailed_notes=[],
            exam_points=[],
            markdown="",
            backend_message="Generating summary from official subtitles in background.",
        )

    def _enqueue_analysis(self, session_id: str) -> None:
        with self._analysis_lock:
            current_future = self._analysis_futures.get(session_id)
            if current_future is not None and not current_future.done():
                return
            self._analysis_futures[session_id] = self._analysis_executor.submit(
                self._run_analysis_job,
                session_id,
            )

    def _run_analysis_job(self, session_id: str) -> None:
        try:
            session = session_store.get(session_id)
            subtitle_payload = subtitle_store.get(session_id)
            if session is None or subtitle_payload is None:
                self._mark_analysis_failed(session_id, "Missing session or subtitle payload.")
                return

            analysis_meta = session.get("analysis", {})
            self._update_session_analysis_state(
                session_id,
                {
                    **analysis_meta,
                    "status": "running",
                    "message": "Preparing transcript and generating overview.",
                    "started_at": self._now(),
                },
            )

            analysis_result = subtitle_analysis_service.analyze(
                session_id=session_id,
                session=session,
                subtitle_payload=subtitle_payload,
                progress_callback=lambda notes, analysis_details, analysis_debug: self._save_analysis_progress(
                    session_id=session_id,
                    notes=notes,
                    analysis_details=analysis_details,
                    analysis_debug=analysis_debug,
                ),
            )
            if analysis_result is None:
                self._mark_analysis_failed(session_id, "Analysis produced no usable result.")
                return

            notes, analysis_details, analysis_debug = analysis_result
            current_session = session_store.get(session_id)
            if current_session is None:
                return

            previous_analysis = current_session.get("analysis", {})
            analysis_details["provider_signature"] = previous_analysis.get(
                "provider_signature",
                self._get_current_provider_signature(),
            )
            analysis_details["status"] = "completed"
            analysis_details["message"] = "Analysis completed."
            analysis_details["requested_at"] = previous_analysis.get("requested_at", "")
            analysis_details["started_at"] = previous_analysis.get("started_at", "")
            analysis_details["completed_at"] = self._now()
            current_session["analysis"] = analysis_details
            current_session["notes"] = notes.model_dump()
            current_session["updated_at"] = self._now()
            session_store.save(session_id, current_session)
            self._save_analysis_debug(
                session_id=session_id,
                session=current_session,
                analysis_details=analysis_details,
                analysis_debug=analysis_debug,
            )
        except Exception as error:
            logger.exception("Async subtitle analysis failed for session %s", session_id)
            self._mark_analysis_failed(session_id, str(error))
        finally:
            with self._analysis_lock:
                self._analysis_futures.pop(session_id, None)

    def _mark_analysis_failed(self, session_id: str, error_message: str) -> None:
        session = session_store.get(session_id)
        if session is None:
            return

        analysis_meta = session.get("analysis", {})
        analysis_meta.update(
            {
                "status": "failed",
                "message": "Analysis failed.",
                "completed_at": self._now(),
                "ai_error": error_message,
            }
        )
        session["analysis"] = analysis_meta

        notes = NotesPayload.model_validate(session.get("notes", {}))
        session["notes"] = notes.model_copy(
            update={
                "backend_message": f"Background analysis failed: {error_message}",
            }
        ).model_dump()
        session["updated_at"] = self._now()
        session_store.save(session_id, session)

    def _update_session_analysis_state(
        self,
        session_id: str,
        analysis_meta: dict[str, Any],
    ) -> None:
        session = session_store.get(session_id)
        if session is None:
            return
        session["analysis"] = analysis_meta
        session["updated_at"] = self._now()
        session_store.save(session_id, session)

    def _save_analysis_progress(
        self,
        *,
        session_id: str,
        notes: NotesPayload,
        analysis_details: dict[str, Any],
        analysis_debug: dict[str, Any],
    ) -> None:
        session = session_store.get(session_id)
        if session is None:
            return

        previous_analysis = session.get("analysis", {})
        merged_analysis = {
            **previous_analysis,
            **analysis_details,
            "provider_signature": previous_analysis.get(
                "provider_signature",
                self._get_current_provider_signature(),
            ),
            "requested_at": previous_analysis.get("requested_at", ""),
            "started_at": previous_analysis.get("started_at", "") or self._now(),
            "completed_at": "",
            "status": "running",
        }
        session["analysis"] = merged_analysis
        session["notes"] = notes.model_dump()
        session["updated_at"] = self._now()
        session_store.save(session_id, session)
        self._save_analysis_debug(
            session_id=session_id,
            session=session,
            analysis_details=merged_analysis,
            analysis_debug=analysis_debug,
        )

    def _save_analysis_debug(
        self,
        *,
        session_id: str,
        session: dict[str, Any],
        analysis_details: dict[str, Any],
        analysis_debug: dict[str, Any],
    ) -> None:
        analysis_debug_store.save(
            session_id,
            {
                "session_id": session_id,
                "page_title": session.get("page_title", ""),
                "page_url": session.get("page_url", ""),
                "host": session.get("host", ""),
                "updated_at": self._now(),
                "analysis": analysis_details,
                "debug": analysis_debug,
            },
        )

    def _notes_have_content(self, notes: NotesPayload) -> bool:
        return bool(
            notes.quick_summary
            or notes.overview_summary
            or notes.structured_notes
            or notes.exam_points
        )

    def _get_current_provider_signature(self) -> str:
        from app.services.ai.factory import get_ai_provider

        provider = get_ai_provider()
        provider_name = getattr(provider, "provider_name", "none")
        model_name = provider.get_model_name() if hasattr(provider, "get_model_name") else ""
        return f"{provider_name}:{model_name}:{int(bool(provider.is_available()))}"

    def _save_bootstrap_snapshot(
        self,
        *,
        session: dict[str, Any],
        session_id: str,
        segment_record: dict[str, Any],
        now: str,
    ) -> None:
        existing = bootstrap_store.get(session_id) or {}
        snapshot = self._build_bootstrap_snapshot(
            session=session,
            session_id=session_id,
            segment_record=segment_record,
            now=now,
            existing=existing,
        )
        bootstrap_store.save(session_id, snapshot)

    def _build_bootstrap_snapshot(
        self,
        *,
        session: dict[str, Any],
        session_id: str,
        segment_record: dict[str, Any],
        now: str,
        existing: dict[str, Any],
    ) -> dict[str, Any]:
        page_context = session.get("page_context", {})
        initial_capture = existing.get("initial_capture") or {
            "capture_stage": segment_record.get("capture_stage", ""),
            "trigger_reason": segment_record.get("trigger_reason", ""),
            "time_label": segment_record.get("time_label", ""),
            "start_time": float(segment_record.get("start_time", 0) or 0),
            "end_time": float(segment_record.get("end_time", 0) or 0),
        }

        latest_capture = {
            "capture_stage": segment_record.get("capture_stage", ""),
            "trigger_reason": segment_record.get("trigger_reason", ""),
            "time_label": segment_record.get("time_label", ""),
            "start_time": float(segment_record.get("start_time", 0) or 0),
            "end_time": float(segment_record.get("end_time", 0) or 0),
            "loaded_until": float(segment_record.get("loaded_until", 0) or 0),
            "loaded_fraction": float(segment_record.get("loaded_fraction", 0) or 0),
        }

        return {
            "session_id": session_id,
            "snapshot_type": "lightweight_bootstrap",
            "mode": "lightweight",
            "first_written_at": existing.get("first_written_at") or now,
            "updated_at": now,
            "page": {
                "title": session.get("page_title", ""),
                "url": session.get("page_url", ""),
                "host": session.get("host", ""),
                "description": page_context.get("description", ""),
                "page_text": page_context.get("page_text", ""),
                "chapter_titles": page_context.get("chapter_titles", []),
                "visible_texts": page_context.get("visible_texts", []),
                "buffered_ranges": page_context.get("buffered_ranges", []),
            },
            "reliable_sources": {
                "title": page_context.get("title", ""),
                "description": page_context.get("description", ""),
                "chapter_titles": page_context.get("chapter_titles", []),
                "visible_texts": page_context.get("visible_texts", []),
                "subtitle_candidates": page_context.get("subtitle_candidates", []),
                "official_subtitle_summary": page_context.get("official_subtitle_summary", []),
                "combined_text": page_context.get("combined_text", ""),
            },
            "artifacts": {
                "official_subtitle_file": (
                    str(subtitle_store._get_path(session_id))
                    if page_context.get("official_subtitle_track_count", 0) > 0
                    else ""
                ),
                "subtitle_debug_file": (
                    str(subtitle_debug_store._get_path(session_id))
                    if page_context.get("subtitle_debug_available")
                    else ""
                ),
                "analysis_debug_file": (
                    str(analysis_debug_store._get_path(session_id))
                    if session.get("analysis")
                    else ""
                ),
            },
            "capture_policy": {
                "high_frequency_polling": False,
                "subtitle_resource_fetching": False,
                "screenshot_capture": False,
                "audio_recording": False,
                "auto_analysis": True,
            },
            "initial_capture": initial_capture,
            "latest_capture": latest_capture,
        }

    def _save_official_subtitles(
        self,
        *,
        session_id: str,
        session: dict[str, Any],
        source_context: dict[str, Any],
        now: str,
    ) -> None:
        tracks = source_context.get("official_subtitle_tracks", [])
        if not tracks:
            return

        subtitle_store.save(
            session_id,
            {
                "session_id": session_id,
                "page_title": session.get("page_title", ""),
                "page_url": session.get("page_url", ""),
                "host": session.get("host", ""),
                "updated_at": now,
                "track_count": len(tracks),
                "tracks": tracks,
            },
        )

    def _save_subtitle_debug(
        self,
        *,
        session_id: str,
        session: dict[str, Any],
        source_context: dict[str, Any],
        now: str,
    ) -> None:
        subtitle_debug = source_context.get("subtitle_debug")
        if not subtitle_debug:
            return

        subtitle_debug_store.save(
            session_id,
            {
                "session_id": session_id,
                "page_title": session.get("page_title", ""),
                "page_url": session.get("page_url", ""),
                "host": session.get("host", ""),
                "updated_at": now,
                "debug": subtitle_debug,
            },
        )

    def _normalize_official_subtitle_tracks(self, source: SourceInfo) -> list[dict[str, Any]]:
        normalized_tracks: list[dict[str, Any]] = []

        for track in source.official_subtitle_tracks:
            segments: list[dict[str, Any]] = []
            for cue in track.segments:
                content = self._clean_text(cue.content)
                if not content:
                    continue
                segments.append(
                    {
                        "from_seconds": float(cue.from_seconds),
                        "to_seconds": float(cue.to_seconds),
                        "content": content,
                    }
                )

            if not segments:
                continue

            normalized_tracks.append(
                {
                    "lang": self._clean_text(track.lang),
                    "lang_key": self._clean_text(track.lang_key),
                    "track_type": int(track.track_type or 0),
                    "source": self._clean_text(track.source),
                    "source_url": self._clean_text(track.source_url),
                    "segments": segments,
                }
            )

        return normalized_tracks

    def _normalize_subtitle_debug(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        normalized = {
            "collector": self._clean_text(payload.get("collector", "")),
            "page_url": self._clean_text(payload.get("page_url", "")),
            "last_reason": self._clean_text(payload.get("last_reason", "")),
            "last_stage": self._clean_text(payload.get("last_stage", "")),
            "identifiers": payload.get("identifiers", {}),
            "player_tracks_raw": payload.get("player_tracks_raw", []),
            "api_attempts": payload.get("api_attempts", []),
            "final_track_list": payload.get("final_track_list", []),
            "fetched_bodies": payload.get("fetched_bodies", []),
            "errors": payload.get("errors", []),
            "updated_at": self._clean_text(payload.get("updated_at", "")),
        }
        return normalized

    def _build_official_subtitle_preview(
        self,
        tracks: list[dict[str, Any]],
        limit: int,
    ) -> list[str]:
        preview: list[str] = []
        for track in tracks:
            for cue in track.get("segments", []):
                text = self._clean_text(cue.get("content", ""))
                if not text:
                    continue
                preview.append(text)
                if len(preview) >= limit:
                    return preview
        return preview

    def _dedupe_items(self, items: list[str], limit: int) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = self._clean_text(item)
            if not text or text in seen:
                continue
            seen.add(text)
            output.append(text)
            if len(output) >= limit:
                break
        return output

    def _clean_text(self, text: str) -> str:
        return " ".join(str(text or "").replace("\u3000", " ").split()).strip()

    def _validate_segment_time(self, payload: CollectSegmentRequest) -> None:
        if payload.segment.end_time < payload.segment.start_time:
            raise ValueError("segment.end_time cannot be smaller than segment.start_time")

    def _format_range(self, start_time: float, end_time: float) -> str:
        return f"{self._format_seconds(start_time)} - {self._format_seconds(end_time)}"

    def _format_seconds(self, seconds: float) -> str:
        total_seconds = max(0, int(seconds))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        remain_seconds = total_seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{remain_seconds:02d}"
        return f"{minutes:02d}:{remain_seconds:02d}"

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")


collect_service = CollectService()
