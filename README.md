# Studysis

Studysis 是一个面向 B 站学习视频的本地优先学习总结工具。

当前仓库包含两部分：

- `backend/`：FastAPI 后端，负责会话存储、字幕落盘、异步分析、关键帧静态资源和 Markdown 导出
- `chrome-extension/`：Chrome 扩展，负责页面接入、官方字幕抓取、关键帧采集和侧边栏展示

## 当前实现概览

当前版本已经收敛成“轻前端采集 + 后端异步分析 + 单 session 串行写入”的模式：

1. 打开 B 站学习视频页面后，扩展会尽早收集页面信息与官方字幕轨道。
2. 扩展在少量关键事件上发送快照，而不是高频轮询重传。
3. 后端先快速返回预览态结果，保证侧边栏尽快有反馈。
4. 真正的分析在后台异步执行，前端通过轮询会话详情获取增量结果。
5. 同一个 `session` 的分析写入是串行收敛的，旧版本结果不会覆盖新版本。

## 当前多模态模式

项目现在支持“双模型模式”：

- 文本总结模型：`CLOUD_API_MODEL`
- 视觉关键帧模型：`CLOUD_VISION_API_MODEL`

如果你当前使用智谱云，常见配置就是：

```env
AI_ENABLED=true
AI_PROVIDER=cloud
CLOUD_API_MODEL=glm-5.1
CLOUD_VISION_API_MODEL=glm-5v-turbo
```

其中：

- `glm-5.1` 负责总览、章节详解、考点总结
- `glm-5v-turbo` 负责关键帧理解、板书识别、公式/图示补充

## 当前分析与更新策略

当前笔记更新不是“每次暂停都全量重做”，而是分成两层：

- 首次正式生成：
  - 产出高质量 `overview summary`
  - 产出完整章节详解
  - 产出 `exam points`
- 后续增量刷新：
  - 优先复用既有章节文本
  - 只对章节补充板书、公式、图示等视觉信息

当前有一条明确策略：

- `quick_summary`
- `overview_summary`
- `exam_points`

在第一次正式完成后会被冻结，后面不应该再随着新的暂停/关键帧反复改写。

章节区则是增量补全的，后续更新主要集中在：

- `structured_notes`
- `detailed_notes`

## 关键帧采集规则

扩展当前只在少量事件上尝试截取关键帧：

- `video-attached`
- `playback-start`
- `seeked`
- `paused`

并且还有几层限制：

- 单个 session 最多发送 8 张关键帧
- 同一触发类型按 10 秒时间桶去重
- 除 `seeked` 外，默认至少间隔 20 秒才再截一张

这意味着当前视觉增强质量很依赖实际播放过程中的暂停、跳转和播放位置。如果某一章节附近没有采到合适关键帧，该章节就可能没有稳定的板书识别结果。

## 当前运行链路

1. 扩展向 `POST /api/v1/collect/segment` 发送轻量快照。
2. 后端保存：
   - `data/sessions/`
   - `data/bootstrap/`
   - `data/subtitles/`
   - `data/subtitles_debug/`
   - `data/keyframes/`
3. 后端立即返回预览态或处理中结果。
4. 后端后台执行：
   - 字幕清洗
   - 转写块构建
   - 全局总览生成
   - 首轮章节文本分析或复用既有章节文本
   - 关键帧视觉增强
   - Markdown 拼装
5. 前端持续轮询 `GET /api/v1/sessions/{session_id}` 并刷新界面。

## 当前限制

目前多模态部分仍然有一个现实限制：视觉增强效果强依赖“采到的关键帧是否刚好落在对应章节附近”。如果只有开头 `00:00` 左右的截图，后续章节即使文字分析正常，也可能缺少有用的板书补充。

## 仓库结构

```text
studysis/
|- backend/
|  |- app/
|  |- scripts/
|  |- .env.example
|  |- requirements.txt
|  `- README.md
|- chrome-extension/
|  |- assets/
|  |- manifest.json
|  |- background.js
|  |- content.js
|  |- page-hook.js
|  |- sidepanel.html
|  |- sidepanel.css
|  |- sidepanel.js
|  `- README.md
|- environment.yml
`- .gitignore
```

## 快速开始

### 1. 创建环境

如果你使用 Conda：

```bash
conda env create -f environment.yml
conda activate studysis
```

或者手动安装后端依赖：

```bash
cd backend
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2. 配置后端

```bash
cd backend
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

如果你只想测试采集链路，可保持：

```env
AI_ENABLED=false
AI_PROVIDER=none
```

如果你要启用当前推荐的云端双模型模式，可配置：

```env
AI_ENABLED=true
AI_PROVIDER=cloud
CLOUD_API_BASE_URL=你的接口地址
CLOUD_API_KEY=你的密钥
CLOUD_API_MODEL=glm-5.1
CLOUD_VISION_API_MODEL=glm-5v-turbo
```

### 3. 启动后端

```bash
cd backend
python scripts/start_backend.py
```

默认地址：

- `http://127.0.0.1:8000`
- `http://127.0.0.1:8000/docs`

### 4. 加载 Chrome 扩展

1. 打开 `chrome://extensions/`
2. 开启开发者模式
3. 点击“加载已解压的扩展程序”
4. 选择 `chrome-extension/` 目录

### 5. 跑一次完整流程

1. 打开一个 B 站学习视频页面
2. 打开 Studysis 侧边栏
3. 等待官方字幕抓取与后台分析
4. 如需排查结果，可查看 `backend/data/` 下的落盘文件

## 本地数据目录

以下目录默认是本地开发与调试数据，不应提交到 Git：

- `backend/data/sessions/`
- `backend/data/bootstrap/`
- `backend/data/subtitles/`
- `backend/data/subtitles_debug/`
- `backend/data/keyframes/`
- `backend/data/analysis_debug/`
- `backend/exports/`

它们主要用于定位：

- 扩展采到了什么
- 官方字幕是否拿到
- 关键帧是否成功落盘
- 分析请求和结果是否版本一致
- 模型输入输出到底是什么

## 主要接口

- `GET /api/v1/health`
- `POST /api/v1/collect/segment`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions/{session_id}/debug`
- `GET /api/v1/sessions/{session_id}/bootstrap`
- `GET /api/v1/sessions/{session_id}/markdown`
- `GET /media/keyframes/{session_id}/{filename}`

## 子目录文档

- 后端说明：[backend/README.md](./backend/README.md)
- 扩展说明：[chrome-extension/README.md](./chrome-extension/README.md)
