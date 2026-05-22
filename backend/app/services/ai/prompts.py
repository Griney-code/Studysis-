from __future__ import annotations

import json
from typing import Any


def build_global_outline_system_prompt() -> str:
    return (
        "你是一个教学视频内容规划助手。"
        "你会先通读整段字幕，再给出全局导览和章节划分。"
        "请严格输出 JSON，不要输出 markdown，不要解释，不要补充多余文字。"
        "标题要自然、像人写的讲义标题，不能口号化，不能重复。"
    )


def build_global_outline_user_prompt(payload: dict[str, Any]) -> str:
    schema = {
        "overview_summary": "1到3句，概括整节视频的核心主线",
        "chapters": [
            {
                "index": 1,
                "title": "章节标题",
                "start_seconds": 0,
                "end_seconds": 120,
                "focus": "概念定义/公式方法/例题讲解/总结归纳",
                "summary": "一句话概括这一章讲什么",
            }
        ],
        "exam_points": ["整节视频层面的3到8条备考考点"],
    }

    return (
        "请根据下面的整段字幕转录，为教学视频规划章节结构。\n"
        "要求：\n"
        "1. 章节必须按时间顺序排列。\n"
        "2. start_seconds 和 end_seconds 要落在给定字幕时间范围内。\n"
        "3. 不要切得过碎，通常控制在 3 到 8 章。\n"
        "4. 标题要能体现内容递进，不要重复。\n"
        "5. summary 只写一句，简洁清楚。\n"
        "6. exam_points 要能用于复习和出题，不要写空话。\n\n"
        f"输出 JSON 结构：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        f"输入数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def build_chapter_analysis_system_prompt() -> str:
    return (
        "你是一个教学视频章节分析助手。"
        "你会针对某一个已经确定边界的章节，生成简洁摘要、详细讲解和备考考点。"
        "请严格输出 JSON，不要输出 markdown，不要解释。"
        "语言要自然、具体、去 AI 味，避免空话套话。"
    )


def build_chapter_analysis_user_prompt(payload: dict[str, Any]) -> str:
    schema = {
        "title": "润色后的章节标题",
        "summary": "1到2句，适合章卡片展示",
        "detail": "3到6句，对本章进行具体讲解",
        "exam_points": ["2到5条本章备考考点"],
    }

    return (
        "请根据下面的章节字幕内容，生成这个章节的学习笔记。\n"
        "要求：\n"
        "1. 保持标题自然，不要重复整节视频标题。\n"
        "2. summary 要短，适合卡片概览。\n"
        "3. detail 要把定义、公式、方法、例题逻辑讲清楚。\n"
        "4. exam_points 要是能复习、能命题的知识点。\n"
        "5. 不要直接大段复述原字幕。\n\n"
        f"输出 JSON 结构：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        f"输入数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
