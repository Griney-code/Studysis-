from __future__ import annotations

import json
from typing import Any


def build_global_outline_system_prompt() -> str:
    return (
        "You are a teaching-video outline assistant. "
        "Read the full transcript blocks, then produce a clean global overview and chapter plan. "
        "Return strict JSON only, with no markdown fences and no extra explanation."
    )


def build_global_outline_user_prompt(payload: dict[str, Any]) -> str:
    schema = {
        "overview_summary": "One or two sentences that summarize the whole lesson.",
        "chapters": [
            {
                "index": 1,
                "title": "Chapter title",
                "start_seconds": 0,
                "end_seconds": 120,
                "focus": "Concepts / Methods / Worked Examples / Review / Orientation",
                "summary": "One sentence describing the chapter focus.",
            }
        ],
        "exam_points": ["Reviewable points for revision or question design"],
    }

    return (
        "Plan a teaching-video chapter structure from the transcript.\n"
        "Requirements:\n"
        "1. Chapters must follow the transcript timeline.\n"
        "2. Keep chapter boundaries within the provided time range.\n"
        "3. Usually keep the lesson within 3 to 8 chapters.\n"
        "4. Titles should sound like human-written study notes, not slogans.\n"
        "5. Exam points should be specific and reviewable.\n\n"
        f"Output JSON schema:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        f"Input payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def build_chapter_analysis_system_prompt() -> str:
    return (
        "You are a teaching-video chapter analysis assistant. "
        "Given one chapter with a transcript slice, produce a concise summary, a useful explanation, and revision points. "
        "Return strict JSON only, with no markdown fences and no extra explanation."
    )


def build_chapter_analysis_user_prompt(payload: dict[str, Any]) -> str:
    schema = {
        "title": "Polished chapter title",
        "summary": "One short sentence for the chapter card.",
        "detail": "Two to four sentences explaining the chapter clearly.",
        "exam_points": ["Two to five reviewable chapter points"],
    }

    return (
        "Write study notes for this teaching-video chapter.\n"
        "Requirements:\n"
        "1. Keep the title natural and specific.\n"
        "2. The summary should be short and card-friendly.\n"
        "3. The detail should clarify concepts, methods, formulas, and example logic when present.\n"
        "4. Exam points must be reviewable and question-oriented.\n"
        "5. Do not simply copy the raw transcript.\n\n"
        f"Output JSON schema:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        f"Input payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def build_visual_chapter_analysis_system_prompt() -> str:
    return (
        "You are a teaching-video OCR and board-recognition assistant. "
        "Use the provided chapter transcript and keyframes together. "
        "Treat the keyframes as a time-ordered sequence of board states instead of isolated screenshots. "
        "Extract visible board writing, formulas, diagram labels, and slide structure conservatively. "
        "Prefer later frames when they contain a more complete board state, and merge repeated content across frames. "
        "Do not invent text that is not visibly present. "
        "Always respond in Simplified Chinese. "
        "Return strict JSON only, with no markdown fences and no extra explanation."
    )


def build_visual_chapter_analysis_user_prompt(payload: dict[str, Any]) -> str:
    schema = {
        "visual_summary": "一句话概括这组关键帧为本章补充了什么板书或图示信息",
        "detail_appendix": "2到4句，解释这些关键帧怎样帮助理解本章，重点补充字幕里没有说清的视觉信息",
        "board_lines": ["按板书原意提取的短句、定义、结论或标题"],
        "formula_lines": ["图中清晰可见的公式、符号关系或 LaTeX 表达式（不含 $ 符号，由系统自动渲染）"],
        "diagram_elements": ["图示中的标签、坐标轴、箭头、变量、结构名称等"],
        "uncertain_parts": ["看不清、只看到一部分、无法确认的内容，明确标注不确定"],
        "exam_points": ["由板书、公式或图示支持的复习考点"],
    }

    return (
        "请对这一章关联的多张关键帧做板书识别和视觉补充。\n"
        "要求：\n"
        "1. 全部使用简体中文输出。\n"
        "2. 重点做 OCR 风格提取：板书行、公式、图示标签、结构名称。\n"
        "3. 多张关键帧要按时间顺序综合，重复内容去重，后面更完整的板书优先。\n"
        "4. 只写图里明确看得出的内容；看不清的部分放进 uncertain_parts，不要脑补。\n"
        "5. 不要机械复述字幕，重点补充字幕里没有、但板书里能看到的信息。\n"
        "6. board_lines 更像板书摘录；detail_appendix 更像学习解释；两者不要混写。\n\n"
        f"输出 JSON 结构：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        f"输入数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
