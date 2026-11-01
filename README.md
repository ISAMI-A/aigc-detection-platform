# AI 检测平台（AIGC Detection）

一个把多种「AI 检测能力」聚合到同一套 Web 界面的平台：图像篡改检测、点位真实性核验、遥感变化核验、人脸识别，外加登录体系、通知中心与系统管理后台。

项目的核心设计目标是：**在单张 8GB 显存的消费级显卡上，让三套 AI 模型稳定共存**（统一模型管理器负责懒加载、推理串行锁、显存预算与空闲卸载）。

## 项目用途

四类业务场景对应四个功能页：

| 功能 | 解决的问题 | 判定方式 |
|---|---|---|
| 图像篡改检测 | 判断一张图片是否被局部编辑/合成过（证据图、公示材料核查） | TruFor V2.4 模型输出 13 项指标并融合判定，结果分「伪造 / 真实 / 不确定」三态 |
| 点位真实性核验 | 判断「整改后照片」与「暗访照片」是否拍自同一场景（防止用别处照片冒充整改） | SuperPoint + LightGlue 特征匹配 + RANSAC 几何校验 |
| 遥感变化核验 | 对比同一地点前后两期卫星图，核查框内是否新增构筑物 / 是否完成整改 | 多模态视觉大模型（OpenAI 兼容接口，可接 DeepSeek / 通义千问 / 本地 Ollama） |
| 人脸识别 | 人脸检索、人员标注入库、人脸登录 | RetinaFace 检测 + ArcFace 512 维特征比对 |

平台还提供：游客免登录试用（数据本设备隔离，30 天无活跃自动清理）、账号注册登录（密码 / 邮箱验证码 / 人脸）、通知中心（公告 / 好友 / 聊天）、管理员后台（用户管理、功能开关、操作日志、数据清理）。

## 技术栈

| 层 | 技术 | 作用 |
|---|---|---|
| 后端 | Python 3.11 + FastAPI + Uvicorn | Web API、子应用挂载、流式检测接口 |
| 前端 | React 19 + Vite + i18next | 单页多标签界面、双语（中/英）、主题切换 |
| 存储 | SQLite（`web.db` / `smart_verify.db` / `rs_verify.db` / `face.db`）+ 本地文件目录 | 记录、账号、日志、聊天、上传与结果图 |
| 检测核心 | TruFor V2.4（`ImageAuthenticityDetector/`） | 篡改检测，子进程隔离推理 |
| 点位核验 | SuperPoint + LightGlue + RANSAC（`ImageVerifier/`） | 同一场景判定 |
| 遥感核验 | 多模态大模型（`Remote_sensing/`，子进程桥接） | 卫星图框内变化分析 |
| 人脸 | RetinaFace + ArcFace（`FaceRecognition/`） | 人脸检测、特征提取与检索 |
| 安全 | PBKDF2 密码哈希、sha256 token、AES-256-GCM 敏感配置加密 | 账号安全与 API Key 落库加密 |

四个算法模块都是**独立可运行的项目**，Web 侧不复制算法代码，只通过进程内导入 / 核心库转发 / 子进程桥接三种方式集成，算法更新后 Web 自动跟随。

## 目录结构

```
AIGC Detection/
├── web/                          # Web 应用（本项目主入口）
│   ├── app.py                    # FastAPI 主入口（挂载三个子应用）
│   ├── auth.py                   # 注册/登录/验证码/改密
│   ├── admin.py                  # 管理员后台接口
│   ├── chat.py                   # 通知中心（公告/好友/聊天）
│   ├── detect.py                 # 图像篡改检测（NDJSON 流式）
│   ├── smart_verify/             # 点位真实性核验子应用（/smart）
│   ├── rs_verify/                # 遥感变化核验子应用（/rsverify）
│   ├── face/                     # 人脸识别子应用（/face）
│   ├── model_manager.py          # 统一模型管理器（显存调度）
│   ├── api_envelope.py           # 统一响应封装 {code,msg,data}
│   ├── .env.example              # 环境变量模板（复制为 .env）
│   └── frontend/                 # React 前端（Vite）
├── ImageAuthenticityDetector/    # TruFor 检测核心（含 CLI）
├── TruFor_V2.4/                  # TruFor 原始算法工程
├── ImageVerifier/                # SuperPoint + LightGlue 核验核心
├── PointVerifier/                # 核验 CLI
├── Remote_sensing/               # 遥感核验核心（含 config.example.yaml）
├── FaceRecognition/              # 人脸识别核心 + 全局人脸库
├── data/                         # 运行时数据（Git 忽略）
└── .venv/                        # 虚拟环境（Git 忽略）
```

> 各模块更细的设计说明见 `web/README.md`、`web/DEVELOPMENT_GUIDE.md`、各子模块自身 README。

## 环境要求

- Windows 10/11（其余系统需手动执行等价命令）
- Python 3.11
- Node.js 18+
- NVIDIA GPU（推荐 8GB 及以上显存；无 GPU 时人脸/核验速度会明显下降）
- 如需本地大模型：安装 Ollama 并拉取视觉模型（可选）

## 快速开始

### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r ImageAuthenticityDetector\requirements.txt
pip install -r Remote_sensing\requirements.txt
pip install fastapi uvicorn python-multipart httpx cryptography
```

> 各算法模块的依赖见各自目录下的 `requirements.txt`；PyTorch 请按官方显卡版本指引安装。

### 2. 准备配置

```powershell
# 后端环境变量
Copy-Item web\.env.example web\.env
# 按需填写 SMTP 账号（邮箱验证码）、RS_CRYPTO_KEY、ADMIN_INIT_PASSWORD 等

# 遥感核验的大模型配置
Copy-Item Remote_sensing\config.example.yaml Remote_sensing\config.yaml
# 填写 base_url / api_key / model_name
```

模型权重不随仓库提供：TruFor 权重放在 `ImageAuthenticityDetector/`（或 `TruFor_V2.4/`）对应权重目录，人脸权重放在 `FaceRecognition/weights_root/`。具体路径见各模块 README 与 `config.py`。

### 3. 启动

```powershell
# 后端（默认 http://127.0.0.1:8000）
.\.venv\Scripts\python.exe web\app.py

# 前端（另开终端）
cd web\frontend
npm install
npm run dev          # 默认 http://localhost:5173
```

前端通过 Vite 代理把 `/api`、`/smart`、`/rsverify`、`/face` 转发到后端，因此前后端端口变化时只需改配置，不改代码。

### 4. 首次登录

首次启动会自动创建管理员账号 `admin`：

- 若设置了 `ADMIN_INIT_PASSWORD`，则使用该密码；
- 未设置时脚本随机生成密码并打印在后端控制台（形如 `[auth] 已预置 admin 账号（初始密码：…）`）。

无论哪种方式，**首次登录都会强制修改密码**。

## 配置项（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `WEB_HOST` | `127.0.0.1` | 后端监听地址 |
| `WEB_PORT` | `8000` | 后端监听端口 |
| `WEB_BACKEND_URL` | `http://127.0.0.1:8000` | 前端 Vite 代理目标 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` | 空 | 邮箱验证码发信；未配置时验证码打印到后端日志 |
| `RS_CRYPTO_KEY` | 内置默认值 | 遥感核验 API Key 的落库加密密钥；**中途更换会导致旧数据无法解密** |
| `ADMIN_INIT_PASSWORD` | 空（随机生成） | 首次预置 admin 的初始密码 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | 本地 Ollama 服务地址 |

敏感文件均已被 `.gitignore` 忽略：`web/.env`、`Remote_sensing/config.yaml`。仓库中只保留 `.example` 模板。

## 项目完成度与已知限制

**已完成**

- 四个功能页全流程可用（上传 → 处理 → 结果展示 → 人工修正 → 导出 Excel）
- 游客 / 用户 / 管理员三级体系，功能开关、操作日志、数据清理、数据导出与恢复
- 检测结果 NDJSON 流式推送、批量核验进度、显存统一调度（单卡 8GB 三模型共存）

**已知限制**

- 模型权重、人脸库数据不随仓库提供，需自行准备；缺少权重时对应功能不可用
- 后端为开发模式运行（`uvicorn` 单进程、CORS 放开），未提供生产部署（Docker / Nginx / HTTPS）方案
- 存储使用 SQLite + 本地文件目录，不支持多机横向扩展
- 遥感核验依赖外部大模型服务，需要自备 API Key；接口有调用费用与限流风险
- 篡改检测在低分辨率、强压缩、二次截图等场景下误判率会上升，结果只作辅助参考，最终结论需人工复核

## 常见问题

**Q：改了后端 `.py` 不生效？**
`web/app.py` 未开启 `--reload`，改完必须重启后端，并确认 8000 端口没有残留旧进程。

**Q：后端启动报端口占用？**
设置 `WEB_PORT` 换端口，同时把前端的 `WEB_BACKEND_URL` 改成对应地址。

**Q：页面图片 404？**
检查 Vite 代理是否启动、后端是否运行；图片接口依赖 `?dev=` 查询参数，直接复制 URL 访问时需带上该参数。

**Q：人脸识别首次调用很慢？**
模型为懒加载，首次推理需加载权重；空闲 300 秒后会自动卸载释放显存。
