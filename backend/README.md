# Studysis 后端

## 概述

后端是一个 FastAPI 服务，负责接收浏览器快照、保存官方字幕与关键帧、异步执行分析，并向前端提供会话查询、调试和导出能力。

当前职责包括：

- 接收来自扩展的 `collect/segment` 请求
- 持久化 `session`、`bootstrap`、字幕、关键帧和调试数据
- 在后台执行文本分析与视觉增强
- 对同一个 `session` 做串行写入与版本保护
- 提供会话详情、调试、Markdown 和关键帧静态资源接口

## 当前运行模式

后端当前不是“请求到达后立刻完整分析并同步返回”，而是两段式：

1. 收到快照后先快速返回预览态结果。
2. 真正的分析在后台异步执行。
3. 前端通过轮询 `GET /api/v1/sessions/{session_id}` 获取进度和结果。

这样做的目标是：

- 前端先有反馈
- 后端可增量补齐章节和板书信息
- 避免播放过程中频繁阻塞式调用 AI

## 当前分析链路

一次正式分析大致分为：

1. 读取最佳官方字幕轨道
2. 清洗字幕 cue
3. 构建 transcript blocks
4. 生成全局总览与考试考点
5. 生成章节划分与章节详解
6. 用关键帧做章节视觉增强
7. 生成最终 Markdown

其中多模态是“双模型分工”：

- 文本模型：负责总览、章节详解、考点总结
- 视觉模型：负责关键帧理解、板书识别、公式/图示补充

## 当前笔记更新策略

当前系统已经改成“首次高质量章节详解 + 后续只增量补板书”的思路。

第一次正式完成后，以下部分会被冻结，不应在后续暂停或补帧时反复变化：

- `quick_summary`
- `overview_summary`
- `exam_points`

后续如果字幕未变化、只是关键帧变化，则主要更新章节区：

- `structured_notes`
- `detailed_notes`

这部分逻辑主要在 [collect_service.py](/E:/code/studysis/backend/app/services/collect_service.py) 的 `_merge_frozen_note_sections` 和 [subtitle_analysis_service.py](/E:/code/studysis/backend/app/services/subtitle_analysis_service.py) 的章节复用逻辑中。

## 异步与版本收敛

当前异步链路有几层保护：

- 单个 `session` 同时只跑一个分析任务
- 如果运行中又收到了新字幕或新关键帧，会登记一次 rerun
- 当前任务结束后会自动按最新数据再跑一轮
- 分析结果写回时会检查 `request_version`
- 旧版本分析结果不会覆盖新版本 session

这可以避免：

- 多个后台任务交叉覆盖
- 先完成的旧结果把后完成的新结果刷掉
- 前端看到章节内容来回跳变

## 关键帧与视觉增强

后端会把扩展上传的关键帧保存到：

- `data/keyframes/{session_id}/`

并通过以下静态路径暴露：

- `GET /media/keyframes/{session_id}/{filename}`

章节视觉增强时，当前策略是：

- 优先挑选章节时间窗口内的关键帧
- 允许极少量向前回退的兜底帧
- 同一轮分析尽量避免同一张图被多个章节复用

如果某一章节附近没有采到合适图片，该章节可能只有文本详解，没有板书识别结果。

## 目录结构

```text
backend/
|- app/
|  |- api/
|  |- core/
|  |- schemas/
|  |- services/
|  |  |- ai/
|  |  |- collect_service.py
|  |  `- subtitle_analysis_service.py
|  |- storage/
|  `- main.py
|- data/
|- exports/
|- scripts/
|- .env.example
|- requirements.txt
|- requirements-dev.txt
`- README.md
```

## 主要接口

- `GET /api/v1/health`
- `POST /api/v1/collect/segment`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions/{session_id}/debug`
- `GET /api/v1/sessions/{session_id}/bootstrap`
- `GET /api/v1/sessions/{session_id}/markdown`
- `GET /media/keyframes/{session_id}/{filename}`

## 数据目录

运行时会生成以下本地目录：

- `data/sessions/`
- `data/bootstrap/`
- `data/subtitles/`
- `data/subtitles_debug/`
- `data/keyframes/`
- `data/analysis_debug/`
- `exports/`

这些目录主要用于本地开发和调试，默认不应提交到 Git。

## 环境变量

请参考 [`.env.example`](./.env.example)。

当前和多模态最相关的配置有：

- 基础开关：
  - `AI_ENABLED`
  - `AI_PROVIDER`
- 文本模型：
  - `CLOUD_API_BASE_URL`
  - `CLOUD_API_KEY`
  - `CLOUD_API_MODEL`
- 视觉模型：
  - `CLOUD_VISION_API_MODEL`
- 文本分析参数：
  - `AI_TIMEOUT_SECONDS`
  - `AI_TEMPERATURE`
  - `AI_MAX_TOKENS`
  - `AI_OUTLINE_MAX_BLOCKS`
  - `AI_CHAPTER_PARALLELISM`
  - `AI_ENABLE_TEXT_CHAPTER_ANALYSIS`
- 视觉分析参数：
  - `AI_VISION_MAX_TOKENS`
  - `AI_VISION_TEMPERATURE`
  - `AI_VISION_IMAGES_PER_CHAPTER`
  - `AI_VISION_MAX_CHAPTERS`

当前代码里的默认值已经偏轻量化，核心目的是先保证能稳定跑出结果：

```env
AI_OUTLINE_MAX_BLOCKS=48
AI_CHAPTER_PARALLELISM=1
AI_ENABLE_TEXT_CHAPTER_ANALYSIS=true
AI_VISION_MAX_TOKENS=320
AI_VISION_IMAGES_PER_CHAPTER=1
AI_VISION_MAX_CHAPTERS=0
```

其中：

- `AI_ENABLE_TEXT_CHAPTER_ANALYSIS=true` 表示首次正式分析仍然会产出较完整的章节文本
- `AI_VISION_IMAGES_PER_CHAPTER=1` 表示每章默认只送 1 张图，降低视觉调用负担
- `AI_VISION_MAX_CHAPTERS=0` 当前表示不额外限制章节数

## 推荐云端双模型配置

```env
AI_ENABLED=true
AI_PROVIDER=cloud

CLOUD_API_BASE_URL=你的接口地址
CLOUD_API_KEY=你的密钥
CLOUD_API_PATH=/chat/completions

CLOUD_API_MODEL=glm-5.1
CLOUD_VISION_API_MODEL=glm-5v-turbo

AI_TIMEOUT_SECONDS=30
AI_OUTLINE_MAX_BLOCKS=48
AI_CHAPTER_PARALLELISM=1
AI_ENABLE_TEXT_CHAPTER_ANALYSIS=true
AI_VISION_MAX_TOKENS=320
AI_VISION_IMAGES_PER_CHAPTER=1
AI_VISION_MAX_CHAPTERS=0
```

## 调试建议

如果前端结果异常，优先对照以下目录排查：

- `data/bootstrap/`：看前端到底上传了哪些页面信息
- `data/subtitles/`：看官方字幕是否真的存在
- `data/keyframes/`：看是否真的采到了对应章节图片
- `data/analysis_debug/`：看文本分析、视觉分析、章节选择和错误信息
- `data/sessions/`：看最终写回 session 的 notes 和 analysis 状态
