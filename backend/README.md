# Studysis 后端

## 概述

后端是一个 FastAPI 服务，面向 B 站学习视频总结场景，负责接收浏览器快照、保存官方字幕、异步执行分析，并提供会话查询、调试与导出接口。

当前职责包括：

- 接收来自 Chrome 扩展的快照上传
- 持久化会话状态与 bootstrap 元数据
- 保存官方字幕轨道与字幕调试数据
- 在后台异步执行字幕分析
- 提供会话详情、调试、bootstrap、Markdown 导出等接口
- 支持 `none`、`local`、`cloud` 三种模型提供方

## 安装

```bash
cd backend
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## 启动

```bash
cd backend
python scripts/start_backend.py
```

默认地址：

- `http://127.0.0.1:8000`
- `http://127.0.0.1:8000/docs`

## 运行流程

1. 扩展调用 `POST /api/v1/collect/segment`
2. 后端标准化页面元数据与片段数据
3. 如果快照里带有官方字幕轨道，则保存到 `backend/data/subtitles/`
4. 字幕调试信息保存到 `backend/data/subtitles_debug/`
5. bootstrap 快照更新到 `backend/data/bootstrap/`
6. 后端先快速返回适合前端加载态的结果
7. 真正的字幕分析在后台异步执行
8. 分析调试数据保存到 `backend/data/analysis_debug/`

## 当前分析链路

当前分析以官方字幕为中心，面向 B 站学习视频，大致分为：

1. 字幕净化
2. 转写块构建
3. 全局总览生成
4. 分章节分析
5. 备考考点提炼
6. Markdown 拼装

前端展示策略是先出总览，再补章节卡片。

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

## 数据目录

运行时会生成以下本地目录：

- `data/sessions/`
- `data/bootstrap/`
- `data/subtitles/`
- `data/subtitles_debug/`
- `data/analysis_debug/`
- `exports/`

这些目录默认都不应提交到 Git，主要用于本地开发和调试。

## 主要接口

- `GET /api/v1/health`
- `POST /api/v1/collect/segment`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions/{session_id}/debug`
- `GET /api/v1/sessions/{session_id}/bootstrap`
- `GET /api/v1/sessions/{session_id}/markdown`

## 环境变量

请参考 [`.env.example`](./.env.example)。

重点配置包括：

- 服务基础配置：`HOST`、`PORT`、`API_V1_PREFIX`
- 分析配置：`AI_TIMEOUT_SECONDS`、`AI_TEMPERATURE`、`AI_MAX_TOKENS`
- 总览与章节并发配置：`AI_OUTLINE_MAX_BLOCKS`、`AI_CHAPTER_PARALLELISM`
- 本地模型配置：`OLLAMA_*`
- 第三方模型配置：`CLOUD_API_*`

## 模型提供方模式

### 关闭模型能力

```env
AI_ENABLED=false
AI_PROVIDER=none
```

### 使用本地 Ollama

```env
AI_ENABLED=true
AI_PROVIDER=local
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_KEEP_ALIVE=15m
```

### 使用兼容 OpenAI 接口的第三方模型

```env
AI_ENABLED=true
AI_PROVIDER=cloud
CLOUD_API_BASE_URL=https://your-api-host/v1
CLOUD_API_KEY=your_api_key
CLOUD_API_MODEL=your_model_name
CLOUD_API_PATH=/chat/completions
```
