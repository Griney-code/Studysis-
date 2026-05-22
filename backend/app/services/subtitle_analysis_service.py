from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from math import ceil
from typing import Any, Callable

from app.core.config import settings
from app.schemas.note import NoteItem, NotesPayload
from app.services.ai.factory import get_ai_provider
from app.services.ai.prompts import (
    build_chapter_analysis_system_prompt,
    build_chapter_analysis_user_prompt,
    build_global_outline_system_prompt,
    build_global_outline_user_prompt,
)

logger = logging.getLogger(__name__)


@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str


@dataclass
class TranscriptBlock:
    index: int
    start: float
    end: float
    text: str


@dataclass
class PlannedChapter:
    index: int
    title: str
    start: float
    end: float
    focus: str
    summary: str


@dataclass
class ChapterAnalysis:
    index: int
    title: str
    start: float
    end: float
    focus: str
    summary: str
    detail: str
    exam_points: list[str]
    transcript: str


class SubtitleAnalysisService:
    _space_re = re.compile(r"\s+")
    _sentence_break_re = re.compile(r"(?<=[。！？!?；;])")
    _low_value_exact = {
        "点赞收藏",
        "点个关注",
        "关注我",
        "我们现在发车",
        "看完这个视频",
        "好",
        "好的",
        "嗯",
        "啊",
        "来",
        "好吧",
    }
    _low_value_substrings = (
        "点赞",
        "关注",
        "收藏",
        "一键三连",
        "记得签到",
        "小姐姐们好",
        "寒假躺",
        "拜个早年",
        "下个视频再见",
        "拜拜",
        "小糖糖",
        "可爱老师",
    )
    _topic_keywords = (
        "向量",
        "坐标",
        "空间",
        "数量场",
        "向量场",
        "梯度",
        "散度",
        "旋度",
        "nabla",
        "纳布拉",
        "方向余弦",
        "模长",
        "卦限",
        "公式",
        "例题",
        "解析几何",
    )
    _focus_values = {"概念定义", "公式方法", "例题讲解", "总结归纳", "知识导览"}
    _title_keyword_map = [
        (("投影",), "向量投影"),
        (("数量积",), "数量积"),
        (("点乘",), "点乘"),
        (("内积",), "向量内积"),
        (("夹角",), "向量夹角"),
        (("垂直",), "垂直判定"),
        (("坐标",), "坐标表示"),
        (("例题",), "例题讲解"),
    ]

    def build_instant_preview_notes(
        self,
        *,
        session: dict[str, Any],
        subtitle_payload: dict[str, Any],
    ) -> NotesPayload:
        page_title = self._normalize_text(session.get("page_title", ""))

        markdown = self._build_markdown(
            page_title=page_title or "Studysis Notes",
            overview="",
            chapters=[],
            exam_points=[],
        )
        return NotesPayload(
            quick_summary="",
            overview_summary="",
            live_summary="",
            structured_notes=[],
            detailed_notes=[],
            exam_points=[],
            markdown=markdown,
            backend_message="正在整理章节内容。",
        )

    def _build_preview_chapter_title(self, chapter: PlannedChapter) -> str:
        title = self._normalize_text(chapter.title)
        title = re.sub(r"^(第\s*\d+\s*[章节讲]|章节\s*\d+[:：]?)", "", title).strip()
        title = title.strip("：:，,。 ")
        if not title:
            title = f"第{chapter.index}章"
        return self._truncate_text(title, 18)

    def _build_preview_chapter_content(self, chapter: PlannedChapter) -> str:
        focus = self._normalize_text(chapter.focus)
        if focus == "概念定义":
            return "正在整理本章核心概念。"
        if focus == "公式方法":
            return "正在整理本章公式与解题方法。"
        if focus == "例题讲解":
            return "正在整理本章例题思路。"
        if "例题" in focus and "公式" in focus:
            return "正在整理本章公式与例题。"
        if "总结" in focus:
            return "正在整理本章重点归纳。"
        return "正在整理本章重点内容。"

    def analyze(
        self,
        *,
        session_id: str,
        session: dict[str, Any],
        subtitle_payload: dict[str, Any],
        progress_callback: Callable[[NotesPayload, dict[str, Any], dict[str, Any]], None] | None = None,
    ) -> tuple[NotesPayload, dict[str, Any], dict[str, Any]] | None:
        tracks = subtitle_payload.get("tracks") or []
        cues = self._load_best_track_cues(tracks)
        if not cues:
            return None

        cleaned_cues = self._clean_cues(cues)
        if not cleaned_cues:
            return None

        transcript_blocks = self._build_transcript_blocks(cleaned_cues)
        if not transcript_blocks:
            return None

        full_transcript = "\n".join(
            f"[{self._format_time(block.start)}-{self._format_time(block.end)}] {block.text}"
            for block in transcript_blocks
        )
        debug_payload = self._build_debug_payload(
            subtitle_payload=subtitle_payload,
            cleaned_cues=cleaned_cues,
            transcript_blocks=transcript_blocks,
            full_transcript=full_transcript,
        )

        outline, outline_meta = self._plan_global_outline(
            session=session,
            cleaned_cues=cleaned_cues,
            transcript_blocks=transcript_blocks,
            subtitle_payload=subtitle_payload,
            debug_payload=debug_payload,
        )
        if not outline:
            return None

        if progress_callback is not None:
            interim_notes = self._build_outline_only_notes(
                session=session,
                overview_summary=outline_meta.get("overview_summary", ""),
                provider_name=outline_meta.get("provider", ""),
            )
            progress_callback(
                interim_notes,
                {
                    "session_id": session_id,
                    "mode": outline_meta.get("mode") or "ai_global_outline",
                    "provider": outline_meta.get("provider", ""),
                    "model": outline_meta.get("model", ""),
                    "ai_used": bool(outline_meta.get("ai_used")),
                    "ai_error": outline_meta.get("ai_error", ""),
                    "track_count": len(tracks),
                    "cleaned_cue_count": len(cleaned_cues),
                    "transcript_block_count": len(transcript_blocks),
                    "chapter_count": len(outline),
                    "subtitle_updated_at": subtitle_payload.get("updated_at", ""),
                    "overview_summary": outline_meta.get("overview_summary", ""),
                    "status": "running",
                    "message": "Overview ready. Chapter analysis is running.",
                    "phase": "outline_ready",
                },
                debug_payload,
            )

        chapter_analyses, chapter_meta = self._analyze_chapters(
            session=session,
            cleaned_cues=cleaned_cues,
            outline=outline,
            overview_summary=outline_meta.get("overview_summary", ""),
            debug_payload=debug_payload,
        )
        notes = self._build_notes(
            session=session,
            overview_summary=outline_meta.get("overview_summary", ""),
            planned_chapters=outline,
            chapter_analyses=chapter_analyses,
            global_exam_points=outline_meta.get("exam_points", []),
            ai_used=outline_meta.get("ai_used", False) or chapter_meta.get("ai_used", False),
            provider_name=outline_meta.get("provider", "") or chapter_meta.get("provider", ""),
        )

        analysis_meta = {
            "session_id": session_id,
            "mode": chapter_meta.get("mode") or outline_meta.get("mode") or "rule",
            "provider": outline_meta.get("provider", ""),
            "model": outline_meta.get("model", ""),
            "ai_used": bool(outline_meta.get("ai_used") or chapter_meta.get("ai_used")),
            "ai_error": chapter_meta.get("ai_error") or outline_meta.get("ai_error", ""),
            "track_count": len(tracks),
            "cleaned_cue_count": len(cleaned_cues),
            "transcript_block_count": len(transcript_blocks),
            "chapter_count": len(outline),
            "subtitle_updated_at": subtitle_payload.get("updated_at", ""),
            "overview_summary": outline_meta.get("overview_summary", ""),
            "phase": "completed",
        }
        return notes, analysis_meta, debug_payload

    def _build_outline_only_notes(
        self,
        *,
        session: dict[str, Any],
        overview_summary: str,
        provider_name: str,
    ) -> NotesPayload:
        quick_summary = self._first_sentence(overview_summary) or overview_summary
        markdown = self._build_markdown(
            page_title=session.get("page_title", ""),
            overview=overview_summary,
            chapters=[],
            exam_points=[],
        )
        return NotesPayload(
            quick_summary=quick_summary,
            overview_summary=overview_summary,
            live_summary="",
            structured_notes=[],
            detailed_notes=[],
            exam_points=[],
            markdown=markdown,
            backend_message="总览已就绪，正在整理章节内容。",
        )

    def _compress_transcript_blocks_for_outline(
        self,
        transcript_blocks: list[TranscriptBlock],
    ) -> list[TranscriptBlock]:
        max_blocks = max(1, int(settings.ai_outline_max_blocks))
        if len(transcript_blocks) <= max_blocks:
            return transcript_blocks

        group_size = max(1, ceil(len(transcript_blocks) / max_blocks))
        merged: list[TranscriptBlock] = []
        merged_index = 1
        for start in range(0, len(transcript_blocks), group_size):
            group = transcript_blocks[start : start + group_size]
            if not group:
                continue
            merged.append(
                TranscriptBlock(
                    index=merged_index,
                    start=group[0].start,
                    end=group[-1].end,
                    text=self._join_transcript_parts([block.text for block in group]),
                )
            )
            merged_index += 1
        return merged

    def _load_best_track_cues(self, tracks: list[dict[str, Any]]) -> list[SubtitleCue]:
        if not tracks:
            return []

        def score(track: dict[str, Any]) -> tuple[int, int, int]:
            lang_key = str(track.get("lang_key", "")).lower()
            lang = str(track.get("lang", "")).lower()
            segments = track.get("segments") or []
            zh_score = 1 if "zh" in lang_key or "cn" in lang_key or "中" in lang else 0
            non_ai_score = 0 if "ai" in lang_key else 1
            return (len(segments), zh_score, non_ai_score)

        best_track = max(tracks, key=score)
        cues: list[SubtitleCue] = []
        for segment in best_track.get("segments") or []:
            text = self._normalize_text(segment.get("content", ""))
            if not text:
                continue
            cues.append(
                SubtitleCue(
                    start=float(segment.get("from_seconds", 0) or 0),
                    end=float(segment.get("to_seconds", 0) or 0),
                    text=text,
                )
            )
        return cues

    def _clean_cues(self, cues: list[SubtitleCue]) -> list[SubtitleCue]:
        cleaned: list[SubtitleCue] = []
        previous_text = ""
        for cue in cues:
            text = self._normalize_text(cue.text).strip("，,。；; ")
            if not text or self._is_low_value_text(text):
                continue
            if cleaned and text == previous_text and cue.start - cleaned[-1].end < 2.0:
                continue
            cleaned.append(SubtitleCue(start=cue.start, end=max(cue.end, cue.start), text=text))
            previous_text = text
        return cleaned

    def _is_low_value_text(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return True
        if normalized in self._low_value_exact:
            return True

        has_topic_keyword = any(keyword in normalized for keyword in self._topic_keywords)
        if any(keyword in normalized for keyword in self._low_value_substrings):
            return not has_topic_keyword

        if (
            len(normalized) <= 18
            and any(normalized.startswith(prefix) for prefix in ("嗨", "哈喽", "大家好", "同学们好"))
            and not has_topic_keyword
        ):
            return True

        if (
            any(phrase in normalized for phrase in ("我们下个视频", "下期见", "下次见"))
            and not has_topic_keyword
        ):
            return True

        return False

    def _build_transcript_blocks(self, cues: list[SubtitleCue]) -> list[TranscriptBlock]:
        blocks: list[TranscriptBlock] = []
        if not cues:
            return blocks

        current_start = cues[0].start
        current_end = cues[0].end
        parts = [cues[0].text]
        block_index = 1

        for cue in cues[1:]:
            candidate_text = " ".join(parts + [cue.text])
            duration = cue.end - current_start
            gap = cue.start - current_end
            should_split = (
                duration >= 18
                or len(candidate_text) >= 180
                or gap >= 1.8
            )
            if should_split:
                blocks.append(
                    TranscriptBlock(
                        index=block_index,
                        start=current_start,
                        end=current_end,
                        text=self._join_transcript_parts(parts),
                    )
                )
                block_index += 1
                current_start = cue.start
                current_end = cue.end
                parts = [cue.text]
                continue

            current_end = cue.end
            parts.append(cue.text)

        blocks.append(
            TranscriptBlock(
                index=block_index,
                start=current_start,
                end=current_end,
                text=self._join_transcript_parts(parts),
            )
        )
        return blocks

    def _plan_global_outline(
        self,
        *,
        session: dict[str, Any],
        cleaned_cues: list[SubtitleCue],
        transcript_blocks: list[TranscriptBlock],
        subtitle_payload: dict[str, Any],
        debug_payload: dict[str, Any],
    ) -> tuple[list[PlannedChapter], dict[str, Any]]:
        provider = get_ai_provider()
        provider_name = getattr(provider, "provider_name", "none")
        model_name = provider.get_model_name() if hasattr(provider, "get_model_name") else ""

        fallback_outline = self._build_rule_outline(transcript_blocks)
        fallback_overview = self._build_fallback_overview(session, fallback_outline)
        fallback_exam_points = self._build_fallback_exam_points(cleaned_cues, fallback_outline)

        if not provider.is_available():
            debug_payload["global_outline"] = {
                "input": {},
                "raw_output": "",
                "parsed_output": {},
                "error": "provider unavailable",
            }
            return fallback_outline, {
                "mode": "rule",
                "provider": provider_name,
                "model": model_name,
                "ai_used": False,
                "ai_error": "provider unavailable",
                "overview_summary": fallback_overview,
                "exam_points": fallback_exam_points,
            }

        outline_blocks = self._compress_transcript_blocks_for_outline(transcript_blocks)

        prompt_payload = {
            "page_title": session.get("page_title", ""),
            "page_description": session.get("page_context", {}).get("description", ""),
            "track_count": subtitle_payload.get("track_count", 0),
            "transcript_blocks": [
                {
                    "index": block.index,
                    "start_seconds": block.start,
                    "end_seconds": block.end,
                    "time_label": f"{self._format_time(block.start)}-{self._format_time(block.end)}",
                    "text": block.text,
                }
                for block in outline_blocks
            ],
        }
        debug_payload["global_outline"] = {
            "input": prompt_payload,
            "raw_output": "",
            "parsed_output": {},
            "error": "",
        }

        result = provider.generate_text(
            system_prompt=build_global_outline_system_prompt(),
            user_prompt=build_global_outline_user_prompt(prompt_payload),
            temperature=settings.ai_temperature,
            max_tokens=settings.ai_max_tokens,
            response_format="json",
        )
        debug_payload["global_outline"]["raw_output"] = result.text if result.success else ""
        debug_payload["global_outline"]["error"] = result.error

        if not result.success:
            logger.warning("AI global outline failed: provider=%s error=%s", provider_name, result.error)
            return fallback_outline, {
                "mode": "rule_fallback",
                "provider": provider_name,
                "model": model_name,
                "ai_used": True,
                "ai_error": result.error,
                "overview_summary": fallback_overview,
                "exam_points": fallback_exam_points,
            }

        parsed = self._parse_json_payload(result.text)
        debug_payload["global_outline"]["parsed_output"] = parsed or {}
        if not parsed:
            return fallback_outline, {
                "mode": "rule_fallback",
                "provider": provider_name,
                "model": model_name,
                "ai_used": True,
                "ai_error": "global outline parse failed",
                "overview_summary": fallback_overview,
                "exam_points": fallback_exam_points,
            }

        chapters = self._normalize_planned_chapters(
            parsed.get("chapters"),
            transcript_blocks=transcript_blocks,
        )
        if not chapters:
            chapters = fallback_outline

        overview_summary = self._normalize_text(parsed.get("overview_summary", "")) or fallback_overview
        exam_points = self._normalize_string_list(parsed.get("exam_points"), limit=8) or fallback_exam_points

        return chapters, {
            "mode": "ai_global_outline",
            "provider": provider_name,
            "model": model_name,
            "ai_used": True,
            "ai_error": "",
            "overview_summary": overview_summary,
            "exam_points": exam_points,
        }

    def _analyze_chapters(
        self,
        *,
        session: dict[str, Any],
        cleaned_cues: list[SubtitleCue],
        outline: list[PlannedChapter],
        overview_summary: str,
        debug_payload: dict[str, Any],
    ) -> tuple[list[ChapterAnalysis], dict[str, Any]]:
        provider = get_ai_provider()
        provider_name = getattr(provider, "provider_name", "none")
        model_name = provider.get_model_name() if hasattr(provider, "get_model_name") else ""

        if not provider.is_available():
            debug_payload["chapter_analysis_runs"] = []
            return [], {
                "mode": "rule",
                "provider": provider_name,
                "model": model_name,
                "ai_used": False,
                "ai_error": "provider unavailable",
            }

        max_workers = max(1, min(int(settings.ai_chapter_parallelism), len(outline)))
        chapter_results_map: dict[int, ChapterAnalysis] = {}
        chapter_debug_map: dict[int, dict[str, Any]] = {}
        had_failure = False

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="studysis-chapter") as executor:
            future_map = {
                executor.submit(
                    self._run_single_chapter_analysis,
                    session=session,
                    cleaned_cues=cleaned_cues,
                    chapter=chapter,
                    overview_summary=overview_summary,
                ): chapter.index
                for chapter in outline
            }

            for future in as_completed(future_map):
                chapter_index = future_map[future]
                try:
                    chapter_result, run_debug, failed = future.result()
                except Exception as error:
                    had_failure = True
                    chapter_result = None
                    run_debug = {
                        "chapter_index": chapter_index,
                        "input": {},
                        "raw_output": "",
                        "parsed_output": {},
                        "error": str(error),
                    }
                else:
                    had_failure = had_failure or failed

                if chapter_result is not None:
                    chapter_results_map[chapter_index] = chapter_result
                chapter_debug_map[chapter_index] = run_debug

        chapter_results = [chapter_results_map[item.index] for item in outline if item.index in chapter_results_map]
        debug_payload["chapter_analysis_runs"] = [
            chapter_debug_map[item.index] for item in outline if item.index in chapter_debug_map
        ]
        return chapter_results, {
            "mode": "ai_chapter_analysis" if not had_failure else "ai_chapter_analysis_fallback",
            "provider": provider_name,
            "model": model_name,
            "ai_used": True,
            "ai_error": "partial chapter analysis fallback" if had_failure else "",
        }

    def _run_single_chapter_analysis(
        self,
        *,
        session: dict[str, Any],
        cleaned_cues: list[SubtitleCue],
        chapter: PlannedChapter,
        overview_summary: str,
    ) -> tuple[ChapterAnalysis | None, dict[str, Any], bool]:
        provider = get_ai_provider()
        chapter_cues = self._slice_cues(cleaned_cues, chapter.start, chapter.end)
        chapter_text = self._join_transcript_parts([cue.text for cue in chapter_cues])
        prompt_payload = {
            "page_title": session.get("page_title", ""),
            "overview_summary": overview_summary,
            "chapter": {
                "index": chapter.index,
                "title": chapter.title,
                "focus": chapter.focus,
                "start_seconds": chapter.start,
                "end_seconds": chapter.end,
                "time_label": f"{self._format_time(chapter.start)}-{self._format_time(chapter.end)}",
                "summary": chapter.summary,
                "transcript": self._truncate_text(chapter_text, 2200),
            },
        }

        result = provider.generate_text(
            system_prompt=build_chapter_analysis_system_prompt(),
            user_prompt=build_chapter_analysis_user_prompt(prompt_payload),
            temperature=settings.ai_temperature,
            max_tokens=settings.ai_max_tokens,
            response_format="json",
        )
        run_debug = {
            "chapter_index": chapter.index,
            "input": prompt_payload,
            "raw_output": result.text if result.success else "",
            "parsed_output": {},
            "error": result.error,
        }

        if not result.success:
            return None, run_debug, True

        parsed = self._parse_json_payload(result.text)
        run_debug["parsed_output"] = parsed or {}
        if not parsed:
            run_debug["error"] = run_debug["error"] or "chapter analysis parse failed"
            return None, run_debug, True

        title = self._normalize_text(parsed.get("title", "")) or chapter.title
        summary = self._normalize_text(parsed.get("summary", "")) or chapter.summary
        detail = self._normalize_text(parsed.get("detail", ""))
        exam_points = self._normalize_string_list(parsed.get("exam_points"), limit=5)
        return (
            ChapterAnalysis(
                index=chapter.index,
                title=title,
                start=chapter.start,
                end=chapter.end,
                focus=chapter.focus,
                summary=summary,
                detail=detail,
                exam_points=exam_points,
                transcript=chapter_text,
            ),
            run_debug,
            False,
        )

    def _build_notes(
        self,
        *,
        session: dict[str, Any],
        overview_summary: str,
        planned_chapters: list[PlannedChapter],
        chapter_analyses: list[ChapterAnalysis],
        global_exam_points: list[str],
        ai_used: bool,
        provider_name: str,
    ) -> NotesPayload:
        quick_summary = self._first_sentence(overview_summary) or overview_summary

        analysis_map = {item.index: item for item in chapter_analyses}
        structured_notes: list[NoteItem] = []
        detailed_notes: list[NoteItem] = []
        seen_titles: set[str] = set()
        all_exam_points: list[str] = list(global_exam_points)

        for chapter in planned_chapters:
            analysis = analysis_map.get(chapter.index) or self._build_fallback_chapter_analysis(chapter, "")
            title = self._dedupe_title(analysis.title or chapter.title, seen_titles, chapter.start)
            seen_titles.add(title)
            summary = self._truncate_text(analysis.summary or chapter.summary, 80)
            structured_notes.append(
                NoteItem(
                    note_id=f"chapter-{chapter.index}",
                    title=title,
                    content=summary,
                    detail=analysis.detail,
                    category=chapter.focus,
                    timestamp=self._format_time(chapter.start),
                    seconds=chapter.start,
                )
            )
            detailed_notes.append(
                NoteItem(
                    note_id=f"chapter-detail-{chapter.index}",
                    title=title,
                    content=summary,
                    detail=analysis.detail,
                    category=chapter.focus,
                    timestamp=self._format_time(chapter.start),
                    seconds=chapter.start,
                )
            )
            all_exam_points.extend(analysis.exam_points)

        exam_point_items = self._build_exam_point_items(
            structured_notes=structured_notes,
            exam_points=self._dedupe_texts(all_exam_points, limit=8),
        )
        markdown = self._build_markdown(
            page_title=session.get("page_title", ""),
            overview=overview_summary,
            chapters=structured_notes,
            exam_points=exam_point_items,
        )

        backend_message = (
            f"已基于官方字幕完成章节整理（provider={provider_name}）。"
            if ai_used
            else "已基于官方字幕完成内容整理。"
        )
        return NotesPayload(
            quick_summary=quick_summary,
            overview_summary=overview_summary,
            live_summary="",
            structured_notes=structured_notes,
            detailed_notes=detailed_notes,
            exam_points=exam_point_items,
            markdown=markdown,
            backend_message=backend_message,
        )

    def _build_rule_outline(self, transcript_blocks: list[TranscriptBlock]) -> list[PlannedChapter]:
        if not transcript_blocks:
            return []

        chunks: list[list[TranscriptBlock]] = []
        current: list[TranscriptBlock] = []
        for block in transcript_blocks:
            if not current:
                current = [block]
                continue
            duration = block.end - current[0].start
            if duration >= 150 or len(current) >= 5:
                chunks.append(current)
                current = [block]
            else:
                current.append(block)
        if current:
            chunks.append(current)

        if len(chunks) >= 2 and chunks[-1][-1].end - chunks[-1][0].start < 30:
            chunks[-2].extend(chunks[-1])
            chunks.pop()

        outline: list[PlannedChapter] = []
        for index, chunk in enumerate(chunks, start=1):
            text = self._join_transcript_parts([block.text for block in chunk])
            title = self._infer_title(text, index)
            outline.append(
                PlannedChapter(
                    index=index,
                    title=title,
                    start=chunk[0].start,
                    end=chunk[-1].end,
                    focus=self._classify_focus(text),
                    summary=self._build_generic_summary(title, self._classify_focus(text)),
                )
            )
        return outline

    def _build_fallback_overview(self, session: dict[str, Any], outline: list[PlannedChapter]) -> str:
        title = self._normalize_text(session.get("page_title", ""))
        title_part = f"本节视频围绕“{title}”展开。" if title else "本节视频围绕当前知识点展开。"
        chapter_titles = "、".join(item.title for item in outline[:3]) if outline else "核心知识点"
        flow_part = f"讲解主线依次覆盖{chapter_titles}。"
        return f"{title_part}{flow_part}整体以知识梳理和题型应用为主。"

    def _build_fallback_exam_points(
        self,
        cleaned_cues: list[SubtitleCue],
        outline: list[PlannedChapter],
    ) -> list[str]:
        points: list[str] = []
        for chapter in outline:
            chapter_text = self._join_transcript_parts([cue.text for cue in self._slice_cues(cleaned_cues, chapter.start, chapter.end)])
            points.extend(self._extract_exam_point_candidates(chapter_text))
        return self._dedupe_texts(points, limit=6)

    def _build_fallback_chapter_analyses(
        self,
        cleaned_cues: list[SubtitleCue],
        outline: list[PlannedChapter],
    ) -> list[ChapterAnalysis]:
        return [
            self._build_fallback_chapter_analysis(
                chapter,
                self._join_transcript_parts([cue.text for cue in self._slice_cues(cleaned_cues, chapter.start, chapter.end)]),
            )
            for chapter in outline
        ]

    def _build_fallback_chapter_analysis(
        self,
        chapter: PlannedChapter,
        chapter_text: str,
    ) -> ChapterAnalysis:
        summary = chapter.summary or self._build_generic_summary(chapter.title, chapter.focus)
        detail = self._build_detail_from_text(chapter_text, chapter.focus)
        exam_points = self._extract_exam_point_candidates(chapter_text)
        if not exam_points:
            exam_points = [self._build_generic_exam_point(chapter.title, chapter.focus)]
        return ChapterAnalysis(
            index=chapter.index,
            title=chapter.title,
            start=chapter.start,
            end=chapter.end,
            focus=chapter.focus,
            summary=summary,
            detail=detail,
            exam_points=self._dedupe_texts(exam_points, limit=5),
            transcript=chapter_text,
        )

    def _normalize_planned_chapters(
        self,
        raw_value: Any,
        *,
        transcript_blocks: list[TranscriptBlock],
    ) -> list[PlannedChapter]:
        if not isinstance(raw_value, list) or not transcript_blocks:
            return []

        min_start = transcript_blocks[0].start
        max_end = transcript_blocks[-1].end
        planned: list[PlannedChapter] = []
        for index, item in enumerate(raw_value, start=1):
            if not isinstance(item, dict):
                continue
            start = self._clamp_float(item.get("start_seconds"), min_start, max_end)
            end = self._clamp_float(item.get("end_seconds"), min_start, max_end)
            if end <= start:
                end = min(max_end, start + 30.0)
            title = self._normalize_text(item.get("title", "")) or f"第 {index} 章"
            focus = self._normalize_focus(item.get("focus", ""))
            summary = self._normalize_text(item.get("summary", "")) or self._build_generic_summary(title, focus)
            planned.append(
                PlannedChapter(
                    index=int(item.get("index", index) or index),
                    title=title,
                    start=start,
                    end=end,
                    focus=focus,
                    summary=summary,
                )
            )

        planned.sort(key=lambda chapter: (chapter.start, chapter.end))
        normalized: list[PlannedChapter] = []
        for index, chapter in enumerate(planned, start=1):
            start = max(min_start, chapter.start)
            if normalized:
                start = max(start, normalized[-1].end)
            end = max(start + 1.0, chapter.end)
            if index < len(planned):
                next_start = planned[index].start
                end = min(end, max(next_start, start + 1.0))
            else:
                end = min(end, max_end)
            normalized.append(
                PlannedChapter(
                    index=index,
                    title=chapter.title,
                    start=start,
                    end=end,
                    focus=chapter.focus,
                    summary=chapter.summary,
                )
            )

        if not normalized:
            return []
        normalized[-1].end = max(normalized[-1].end, max_end)
        return normalized

    def _slice_cues(self, cues: list[SubtitleCue], start: float, end: float) -> list[SubtitleCue]:
        return [
            cue
            for cue in cues
            if not (cue.end < start or cue.start > end)
        ]

    def _build_exam_point_items(
        self,
        *,
        structured_notes: list[NoteItem],
        exam_points: list[str],
    ) -> list[NoteItem]:
        if not structured_notes:
            return []
        items: list[NoteItem] = []
        for index, point in enumerate(exam_points, start=1):
            source_note = structured_notes[min(index - 1, len(structured_notes) - 1)]
            items.append(
                NoteItem(
                    note_id=f"exam-{index}",
                    title=f"考点 {index}",
                    content=point,
                    detail="",
                    category="备考考点",
                    timestamp=source_note.timestamp,
                    seconds=source_note.seconds,
                )
            )
        return items

    def _build_debug_payload(
        self,
        *,
        subtitle_payload: dict[str, Any],
        cleaned_cues: list[SubtitleCue],
        transcript_blocks: list[TranscriptBlock],
        full_transcript: str,
    ) -> dict[str, Any]:
        return {
            "subtitle_updated_at": subtitle_payload.get("updated_at", ""),
            "track_count": subtitle_payload.get("track_count", 0),
            "cleaned_cues": [
                {"start": cue.start, "end": cue.end, "text": cue.text}
                for cue in cleaned_cues
            ],
            "full_transcript_blocks": [
                {
                    "index": block.index,
                    "start": block.start,
                    "end": block.end,
                    "time_label": f"{self._format_time(block.start)}-{self._format_time(block.end)}",
                    "text": block.text,
                }
                for block in transcript_blocks
            ],
            "full_transcript_text": full_transcript,
            "global_outline": {
                "input": {},
                "raw_output": "",
                "parsed_output": {},
                "error": "",
            },
            "chapter_analysis_runs": [],
        }

    def _build_detail_from_text(self, text: str, focus: str) -> str:
        sentences = self._split_sentences(text)
        if not sentences:
            return self._build_generic_summary("本章内容", focus)
        picked = [self._truncate_text(sentence, 72) for sentence in sentences[:3] if sentence]
        if focus == "概念定义":
            picked.append("这一部分更偏向概念理解，适合先建立基本图景，再记公式。")
        elif focus == "公式方法":
            picked.append("这一部分更偏向公式和运算方法，适合结合题目反复练习。")
        elif focus == "例题讲解":
            picked.append("这一部分更偏向例题拆解，复习时要关注每一步为什么这样做。")
        return "\n".join(self._dedupe_texts(picked, limit=4))

    def _extract_exam_point_candidates(self, text: str) -> list[str]:
        sentences = self._split_sentences(text)
        candidates: list[str] = []
        for sentence in sentences:
            normalized = self._normalize_text(sentence)
            if len(normalized) < 8:
                continue
            if any(keyword in normalized for keyword in ("定义", "公式", "性质", "结论", "夹角", "内积", "投影", "坐标", "垂直")):
                candidates.append(self._truncate_text(normalized, 32))
        return self._dedupe_texts(candidates, limit=5)

    def _build_generic_exam_point(self, title: str, focus: str) -> str:
        normalized_title = self._normalize_text(title)
        if "夹角" in normalized_title:
            return "掌握利用点乘或内积求向量夹角的方法。"
        if "投影" in normalized_title:
            return "理解向量投影的几何意义和常见计算方式。"
        if "内积" in normalized_title:
            return "熟练掌握向量内积的定义、性质和坐标计算。"
        if "坐标" in normalized_title:
            return "掌握把向量问题转成坐标分量计算的思路。"
        if focus == "公式方法":
            return "掌握本章核心公式的适用条件和计算步骤。"
        if focus == "例题讲解":
            return "复习时重点关注例题中的解题步骤和思路迁移。"
        return "掌握本章核心概念、公式和典型应用。"

    def _dedupe_title(self, title: str, seen_titles: set[str], start: float) -> str:
        normalized = self._normalize_text(title) or "未命名章节"
        if normalized not in seen_titles:
            return normalized
        return f"{normalized}（{self._format_time(start)}）"

    def _classify_focus(self, text: str) -> str:
        normalized = self._normalize_text(text)
        if any(keyword in normalized for keyword in ("定义", "概念", "是什么", "叫做")):
            return "概念定义"
        if any(keyword in normalized for keyword in ("公式", "性质", "法则", "推导")):
            return "公式方法"
        if any(keyword in normalized for keyword in ("例题", "题目", "求", "计算", "证明")):
            return "例题讲解"
        if any(keyword in normalized for keyword in ("总结", "回顾", "归纳", "结论")):
            return "总结归纳"
        return "知识导览"

    def _normalize_focus(self, value: str) -> str:
        normalized = self._normalize_text(value)
        return normalized if normalized in self._focus_values else "知识导览"

    def _infer_title(self, text: str, index: int) -> str:
        normalized = self._normalize_text(text)
        for keywords, title in self._title_keyword_map:
            if any(keyword in normalized for keyword in keywords):
                return title
        sentences = self._split_sentences(normalized)
        if sentences:
            candidate = self._truncate_text(sentences[0], 16).strip("：:，,。 ")
            if len(candidate) >= 4:
                return candidate
        return f"第 {index} 章"

    def _build_generic_summary(self, title: str, focus: str) -> str:
        normalized_title = self._normalize_text(title)
        if "夹角" in normalized_title:
            return "本章主要讲解如何利用向量关系和点乘公式来求夹角。"
        if "投影" in normalized_title:
            return "本章主要解释向量投影的定义、几何意义以及它和数量积的联系。"
        if "单位向量" in normalized_title:
            return "本章主要复习单位向量、坐标表示和分量展开，为后续计算做准备。"
        if "内积" in normalized_title:
            return "本章主要说明向量内积的定义、性质以及常见计算方法。"
        if "坐标" in normalized_title:
            return "本章主要讲解如何把向量问题转成坐标形式进行计算。"
        if "数量积" in normalized_title or "点乘" in normalized_title:
            return "本章主要梳理数量积与点乘的定义、公式和常见用法。"
        if focus == "例题讲解":
            return "本章主要通过例题演示这一节知识点的具体解法。"
        if focus == "公式方法":
            return "本章主要整理这一节的核心公式、运算规则和使用方法。"
        if focus == "概念定义":
            return "本章主要解释这一节涉及的核心概念和基本定义。"
        return "本章主要围绕这一节的核心知识点做讲解和梳理。"

    def _build_markdown(
        self,
        *,
        page_title: str,
        overview: str,
        chapters: list[NoteItem],
        exam_points: list[NoteItem],
    ) -> str:
        lines = [f"# {page_title or 'Studysis Notes'}", "", "## 速览总结", "", overview, "", "## 结构化笔记", ""]
        for chapter in chapters:
            lines.append(f"### {chapter.title} ({chapter.timestamp})")
            lines.append(chapter.content)
            if chapter.detail:
                lines.append("")
                lines.append(chapter.detail)
            lines.append("")

        lines.extend(["## 备考考点", ""])
        for item in exam_points:
            lines.append(f"- {item.content}")
        lines.append("")
        return "\n".join(lines)

    def _parse_json_payload(self, raw_text: str) -> dict[str, Any] | None:
        text = raw_text.strip()
        if not text:
            return None

        fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _normalize_string_list(self, value: Any, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        output: list[str] = []
        for item in value:
            text = self._normalize_text(item)
            if not text:
                continue
            output.append(text)
            if len(output) >= limit:
                break
        return self._dedupe_texts(output, limit=limit)

    def _split_sentences(self, text: str) -> list[str]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []
        parts = self._sentence_break_re.split(normalized)
        return [part.strip(" ，,") for part in parts if part.strip(" ，,")]

    def _join_transcript_parts(self, parts: list[str]) -> str:
        cleaned = [self._normalize_text(part).strip("，,") for part in parts if self._normalize_text(part)]
        if not cleaned:
            return ""
        return "。".join(cleaned)

    def _first_sentence(self, text: str) -> str:
        sentences = self._split_sentences(text)
        return sentences[0] if sentences else text

    def _dedupe_texts(self, items: list[str], limit: int) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = self._normalize_text(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            output.append(normalized)
            if len(output) >= limit:
                break
        return output

    def _truncate_text(self, text: str, max_length: int) -> str:
        normalized = self._normalize_text(text)
        if len(normalized) <= max_length:
            return normalized
        return f"{normalized[: max_length - 1].rstrip()}…"

    def _normalize_text(self, text: Any) -> str:
        return self._space_re.sub(" ", str(text or "").replace("\u3000", " ")).strip()

    def _clamp_float(self, value: Any, minimum: float, maximum: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = minimum
        return max(minimum, min(maximum, number))

    def _format_time(self, seconds: float) -> str:
        total_seconds = max(0, int(seconds))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        remain_seconds = total_seconds % 60
        if hours:
            return f"{hours:02d}:{minutes:02d}:{remain_seconds:02d}"
        return f"{minutes:02d}:{remain_seconds:02d}"


subtitle_analysis_service = SubtitleAnalysisService()
