# 映序 · Topic Video Studio

输入主题，批量策划脚本、审核分镜、生成素材并合成视频的本地工作台。

**以后重新打开：** 在左侧选择「项目十一：AI视频生成数据台」，打开项目文件夹并双击 `启动AI视频数据台.cmd`。它会复用已运行的服务，或启动本机后台服务后打开页面。代码、`.env`、任务记录和成片保存在当前目录；使用说明见 `重新打开项目.md`，本地快照位于 `outputs/backups/`，未上传云端。

**GitHub 仓库范围：** 仓库保存源码、前端构建、启动脚本、说明文档与不含密钥的 `.env.example`。实际 `.env`、数据库和生成媒体、`samples/` 本机样例、`outputs/` 验证报告与备份、依赖缓存均不提交。文档中的本机验证样例路径仅适用于原电脑；在新电脑克隆后需按启动说明安装运行环境并填写自己的服务端配置，不会同步原有视频任务和成片。

已新增“模型用量”：按项目、视频及模型/接入点统计供应商实际返回的 Token、图片张数、配音计费字符与音频时长，支持历史记录和 CSV 导出。缺失数据不补零，不推算费用；统计口径见 `USAGE_GUIDE.md`。

2026-10-24 已完成企业工作台风格的页面改版，左下角统一为“AI 视频生产中心”。新增项目搜索、状态筛选、时间排序和列表/卡片切换，统一成片资产库、任务详情和 ComfyUI 配置界面。项目代码、`.env`、数据库及媒体已同步至左侧项目对应的当前目录，旧目录作为保留副本；后续请从当前项目目录运行 `start-local.ps1`。页面改版验证未调用付费模型。

2026-10-23 已使用用户本地配置的火山方舟接入点，完成一条真实5秒竖屏视频的脚本、图片、视频生成与合成下载验证；随后使用MiniMax为同一视频补上真实旁白。无配音示例为 `samples/live-5s.mp4`，有配音示例为 `samples/live-5s-voice.mp4`，详见 `LIVE_VERIFICATION.md` 和 `AUDIO_VERIFICATION.md`。Docker容器联调仍未验证。

**ComfyUI为可选图片生成服务。** 已增加工作流导入、参考图上传、固定种子、连接与节点检查、任务ID恢复。现有Seedream、Seedance和MiniMax官方API路线仍可使用。点击左侧“ComfyUI工作区”查看，配置步骤与验证边界见 `COMFYUI_GUIDE.md`。

## 已实现的范围

- React + TypeScript 页面：项目列表、创建表单、脚本审核与编辑、镜头进度、素材预览、成片库、调用记录、配置状态。
- 每批 1～20 条，每条 5～600 秒，支持 9:16、16:9、1:1；按约 5 秒拆分镜头，支持拼成长片。
- 同主题不同版本采用不同叙事角度；演示策划使用有限模板，真实策划由文本模型完成。
- 人工审核或自动执行；图片重做、视频重做、脚本重写、恢复执行、重新合成。
- 修改口播只使对应音频和成片失效；修改画面提示词只使对应图片、视频和成片失效；保留其他镜头。
- FFmpeg 合成 MP4：统一画幅、24fps、H.264、AAC；按镜头调整时长，过短的视频循环补足，过长裁剪；口播超长会加速以适配镜头，过短补静音。
- 字幕按镜头时间轴显示，不是逐字强制对齐；批量 ZIP 包含 MP4 与 SRT。
- 调用记录保存生成 POST 的实际尝试次数、模型、供应商任务 ID 和返回的 usage。次数包含被明确限流的生成请求，不含状态查询和媒体下载；没有价格信息时不估算金额。

## 两种运行方式

### A. 本机快速体验（不需要 Docker）

环境：Python 3.11+、Node.js 22 LTS 或更高版本。安装依赖需要联网。

在项目目录打开 PowerShell：

```powershell
.\start-local.ps1
```

也可双击 `启动AI视频数据台.cmd`，等待浏览器自动打开。双击入口在后台运行服务，关闭浏览器后服务仍继续运行。

脚本会优先检查现有服务，避免重复启动；未运行时检查项目自己的 `.venv`，缺少依赖才联网安装，必要时构建前端，然后打开 `http://127.0.0.1:8000`。通过 PowerShell 前台启动的服务可以在对应终端按 Ctrl+C 停止。

如果系统策略禁止脚本，可在本次进程中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
```

本机方式使用 SQLite 和进程内单线程任务执行器。任务与检查点保存在数据库中，重启后会恢复排队任务；运行中任务等待租约过期（默认120秒）后恢复。本机启动脚本强制 `EXECUTION_MODE=local`。

FFmpeg 优先使用 `FFMPEG_PATH`，其次查找系统 FFmpeg，最后使用 imageio-ffmpeg 安装包内附带的可执行文件；一般无需另装。Windows 默认使用微软雅黑，其他平台可以配置 `FONT_PATH`。

### B. PostgreSQL + Redis + Celery（Docker Compose）

安装并启动 Docker Desktop，在项目根目录执行：

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

也可运行 `.\start-docker.ps1`。访问同一个地址 `http://127.0.0.1:8000`。

容器包含 API、Celery Worker、Celery Beat、PostgreSQL、Redis。Beat 每10秒扫描数据库任务表，把待执行与租约过期任务送到队列；数据库原子领取防止重复执行。默认单 Worker 并发为1，先保证串行可控。Compose 内数据库和 Redis 不向宿主机暴露端口。

```powershell
docker compose logs -f api worker beat
docker compose down
```

`down` 保留数据卷。不要使用 `down -v`，除非确定要删除数据。SQLite 本机数据与 Docker 数据卷相互独立，不会自动迁移。

## 从主题到成片

1. 点“新建视频项目”，输入主题、数量、时长、比例、风格及补充要求。
2. 第一次选择“演示模式”，保持脚本审核开启。
3. 等待“待审核”，点“审核 / 编辑脚本”。可以修改标题、口播、运镜及每个镜头时长，总时长需保持一致。
4. 保存后点“确认并生成”。页面显示每个镜头的图片、视频状态。
5. 完成后预览、单条下载，或在批次全部完成后点“批量下载”。成片库也可预览下载。
6. 需要修改时，只重做相关镜头，最后点“重新合成”或“确认并生成”。

**演示模式说明：** 图片为程序绘制的概念画面，视频为这些画面的缓慢缩放，均带 DEMO 标识；脚本来自演示模板。勾选配音时为演示提示音，不是口播。它用于检查工程闭环，不能代表真实模型的生成质量。

## 接入真实模型

复制 `.env.example` 到 `.env`，在服务端填写以下值后重启：

```dotenv
ARK_API_KEY=你的火山方舟密钥
TEXT_MODEL=你账号已开通的文本模型ID或推理接入点
SEEDREAM_MODEL=你账号已开通的Seedream模型ID
SEEDANCE_MODEL=你账号已开通的Seedance模型ID
MINIMAX_API_KEY=你的MiniMax密钥
MINIMAX_MODEL=你账号已开通的语音模型ID
MINIMAX_VOICE=你有权使用的音色ID
```

不使用配音时，无需配置 MiniMax。模型版本故意不预填，避免使用不存在或账号无权限的版本。`TEXT_MODEL` 要支持常规 Chat Completions 文本输出；模型成功响应但脚本结构错误时，会以单独账本记录进行至多一次纠错。仍不合规时中止，不伪造或补空镜头。网络错误、HTTP失败或受理状态不明时不会启动格式纠错调用。

`SEEDREAM_SIZE`、`SEEDANCE_RESOLUTION`、`SEEDANCE_CLIP_SECONDS` 应按所选模型文档设置。默认 Seedream 2K、Seedance 720p和5秒镜头；这不意味着所有版本都支持这些参数。真实成片默认短边720px，可用 `OUTPUT_SHORT_EDGE` 调整；演示竖屏为360×640，以缩短本地验证时间。

Seedance 使用分镜 PNG 的 base64 data URL 作为输入，不要求本机文件向公网开放。图片结果立即下载并规范为 PNG，视频成功后立即下载，避免供应商临时链接过期。

创建新项目时选择“真实模式”。现有演示项目不会切换或混入真实素材。配置状态页面只显示模型名称和缺失项，不返回密钥。

### 已核对的官方协议（2026-10-23）

- [方舟 Chat Completions](https://docs.volcengine.com/docs/ark/sdk-v1-v2?lang=en)：文本脚本。
- [Seedream 图片 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=en)：`POST /images/generations`。
- [Seedance 创建任务](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh)：`POST /contents/generations/tasks`。
- [Seedance 查询任务](https://docs.volcengine.com/docs/ark/get-video-generation-task-api?lang=zh)：`GET /contents/generations/tasks/{id}`。
- [MiniMax 同步语音](https://platform.minimax.cn/docs/api-reference/speech-t2a-http)：`POST /v1/t2a_v2`，非流式 hex 音频。

官方协议核对不等于账号真实调用验证；需要密钥、模型权限与余额。万相只预留明确报“尚未实现”的适配器接口，没有假装可用。

## 故障恢复与费用边界

- 生成请求先写入调用账本，再发 HTTP 请求，成功响应持久化后才处理素材。相同步骤复用已经成功的调用结果。
- 有任务 ID 的 Seedance 请求，在轮询超时、下载失败或进程重启后复用原 ID。点“恢复执行”继续查询。
- 明确 HTTP 429 最多尝试3次，有全局请求间隔和退避；GET 查询与下载最多尝试3次。Celery 模式通过 Redis 限制跨进程的请求间隔。
- POST 超时、5xx、连接中断或结果格式不完整，视为“受理状态不确定”，**不自动重发**。这包括“供应商已受理但响应尚未写入数据库就崩溃”的情况。
- 在“调用记录”中核对供应商控制台。视频生成可以绑定原任务 ID，然后点“恢复执行”；只有确认未受理时才解锁重试。同步图片、文本、语音接口无法通用自动找回已接受但丢失的响应，必须人工核实，不承诺全局 exactly-once。
- “重做”是显式创建新调用，会产生新费用；已有远端任务不会自动取消，等待超时应优先恢复执行。未解决的不确定提交会阻止脚本编辑与重新生成。
- 若已生成结果的临时 URL 过期而本地尚未下载，需要人工处理或显式重做；系统不会悄悄重新计费。

## 代码结构

```text
backend/app/main.py       API、脚本编辑、下载与前端静态服务
backend/app/pipeline.py   分镜流水线、检查点、任务领取与恢复
backend/app/providers.py  文本、Seedream、Seedance、MiniMax、万相扩展接口
backend/app/media.py      演示媒体、字幕渲染、音画处理、FFmpeg合成
backend/app/db.py         SQLAlchemy数据模型
backend/app/worker.py     Celery Worker和Beat调度
backend/app/storage.py    存储接口及本地实现
frontend/src/            React页面与样式
backend/tests/           集成与可靠性测试
data/                    运行产生的数据库和媒体（不要提交到版本库）
```

存储保留 `Storage` 协议，但目前仅实现本地存储；对象存储适配、上传下载以及签名URL仍需后续实现。长视频目前按顺序生成，支持至10分钟，没有实现自动配乐、跨镜头语义质量检测、口型同步或精细剪辑时间线。角色一致性依赖提示词与模型能力，第一版没有独立角色参考库。

## 开发与测试

后端在项目根目录启动：

```powershell
$env:PYTHONPATH = "$PWD/backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端开发可在 `frontend` 执行 `pnpm install`、`pnpm dev`，然后访问5173端口；Vite代理 API 和媒体到8000。发布构建运行 `pnpm build`。预编译的 `frontend/dist` 已包含在本次交付里。

测试在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

测试使用临时数据库与临时媒体目录，不调用真实供应商，不污染用户项目。查看 `VERIFICATION.md` 了解本次实际验证结果。

## 使用边界

当前是面向本机单用户的可运行第一版，没有登录、多租户隔离、计费系统、文件清理策略或公网部署加固。默认只监听127.0.0.1。不要直接把当前端口暴露到公网。企业部署还需要身份认证、权限与配额、审计、备份、监控和迁移管理。没有实现自动发布到社交平台。
