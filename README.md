# Studysis

Studysis 是一个面向 B 站学习视频的本地优先总结工具。

当前仓库包含两部分：

- 一个 FastAPI 后端：负责会话存储、官方字幕落盘、异步分析与导出
- 一个 Chrome 扩展：负责页面接入、字幕抓取与侧边栏展示

当前分析链路以官方字幕为核心，再在后台进行模型增强。

## 当前状态

这个项目已经不再是早期那种“浏览器高频轮询、前后端高频写盘”的重型原型，而是收敛成了更清晰的一版：

1. 打开 B 站学习视频页面
2. 扩展尽早收集页面信息，并尝试抓取官方字幕
3. 后端保存：
   - 会话快照
   - bootstrap 元数据
   - 官方字幕
   - 字幕调试数据
   - 分析调试数据
4. 后端先快速返回适合前端加载态的占位结果
5. 后台异步执行真实分析：
   - 字幕净化
   - 转写块构建
   - 全局总览生成
   - 分章节分析
   - 备考考点提炼
6. 侧边栏持续轮询会话详情，并在结果完成后刷新展示

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

## 当前能力

- 优先抓取 B 站官方字幕，并在本地保留调试数据
- 异步分析，保证侧边栏先响应、后补全
- 先出总览，再逐步补齐章节卡片
- 支持多种模型提供方：
  - `none`
  - 本地 Ollama
  - 兼容 OpenAI 接口的第三方模型
- 可通过会话调试接口查看整条数据链路
- 支持导出 Markdown

## 快速开始

### 1. 创建环境

如果你使用 Conda：

```bash
conda env create -f environment.yml
conda activate studysis
```

如果你手动安装依赖：

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

如果你使用 Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

然后编辑 `backend/.env`：

- 如果你只想先测试抓取与存储，可保持 `AI_ENABLED=false`
- 如果你想使用本地模型，可设置 `AI_PROVIDER=local`
- 如果你想使用第三方模型，可设置 `AI_PROVIDER=cloud`

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
4. 如有需要，查看 `backend/data/` 下的落盘文件

## 后端数据落盘

以下目录都是本地开发数据，默认已被 Git 忽略：

- `backend/data/sessions/`
- `backend/data/bootstrap/`
- `backend/data/subtitles/`
- `backend/data/subtitles_debug/`
- `backend/data/analysis_debug/`
- `backend/exports/`

这些文件在开发时很有价值，因为它们可以帮助你定位：

- 扩展到底抓到了什么
- 是否成功拿到官方字幕
- 原始字幕列表长什么样
- 净化后的分析文本是什么
- 每一步分析给模型喂了什么、模型回了什么

## 主要接口

- `GET /api/v1/health`
- `POST /api/v1/collect/segment`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions/{session_id}/debug`
- `GET /api/v1/sessions/{session_id}/bootstrap`
- `GET /api/v1/sessions/{session_id}/markdown`

## 上传仓库前注意

- 不要提交 `backend/.env`
- 不要提交 `backend/data/` 下的本地调试数据
- 不要提交本地产生的导出文件
- 如果后续准备公开发布扩展，请重新审查 `manifest.json` 里的权限范围

## 子目录文档

- 后端说明：[backend/README.md](./backend/README.md)
- 扩展说明：[chrome-extension/README.md](./chrome-extension/README.md)
