# AI 检测平台 · Web 版

基于 TruFor V2.4 检测核心 + SuperPoint/LightGlue 场景核验 + 多模态大模型遥感核验 + RetinaFace/ArcFace 人脸识别的 Web 可视化平台，包含四个功能页 + 登录体系（游客/用户/管理员）：

- **图像篡改检测**：拖拽上传图片/文件夹批量检测，结果三态判定 + 指标 + 三图展示，支持人工修正、备注、导出 Excel；上传图/结果图/记录统一后端存储（游客设备隔离、刷新不丢）
- **点位真实性核验**：整改图 vs 暗访图配对（文件名自动/顺序/选择比对），SuperPoint+LightGlue+RANSAC 判定是否同一场景，支持批量核验进度、人工修正与复核、Excel 导出
- **遥感变化核验**：上传同一地点两张卫星图（自带标注框），多模态大模型对比框内区域（新增构筑物检测 / 整改核验），功能页右上角圆形按钮打开"功能设置"（模型/API 参数可改，api_key 加密落库），支持结果列表、标注图查看、Excel 导出。批量上传：双面板上传 + 缩略图列表（拖拽排序、刷新从后端恢复）、顺序匹配（列表上下顺序两两配对）/选择比对（多选按点击编号 1,2,3 顺序配对）、批量逐对核验进度条、开始按钮自动变"核验选中 (N)"、无匹配不能开始
- **人脸识别**：上传照片/批量上传（拖拽/选文件夹），**一图多脸**逐张抠出人脸（缩略图 + Top-K 候选相似度 + 512 维特征值详情 + 原图人脸框）；**全局人脸库**（所有用户可见，游客除外）支持人工标注入库（自动查重：相似不同名弹窗确认"覆盖=改名+补样本 / 新增=独立人员"）、重测（行内图标 / 一键重测 / 重测选中）、勾选双击行、删除/删除选中、导出 Excel/导出选中；**人脸登录**（登录弹窗第三 tab：上传照片直接登录 + 摄像头实时检测匹配）；**个人资料人脸录入**（绑定账号供人脸登录）；**admin 人脸库管理**（分页/模糊搜索/新增/改名/换照片/批量删除/图片放大）
- **通知中心（聊天/好友/公告）**：登录用户顶栏小铃铛悬浮最新公告与未读红点；通知中心页（左侧会话列表 + 右侧聊窗）支持系统公告、好友聊天（文本/图片/zip/表情）、好友搜索/申请/列表；消息**两段式发送**（选图/文件先落入输入框待发，可点 × 或键盘删除并同步清理后端落盘文件，确认后才发送）；聊天记录**个人视角隔离**（清除自己的不影响对方，双方均删除才物理清理）；admin 系统公告发布后**投递到各用户个人公告副本**（admin 关闭/删除/编辑不影响用户已收到的公告，各存各的）
- **登录体系**：游客免登录可试用全部功能（数据 30 天无活跃自动清理、仅本设备可见）；注册/登录（账号密码 / 邮箱验证码 / 人脸）后数据跨设备随账号共享；个人资料页（账号信息/修改密码/邮箱设置/人脸设置/数据导出）；admin 系统管理（总览仪表盘/用户管理/功能开关/系统公告/操作日志/人脸库/数据管理）；功能开关关闭时游客与普通用户入口隐藏且后端返回 1009（admin 豁免）；预置管理员账号 `admin / Admin@2026`（首次登录需修改初始密码）

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python + FastAPI + uvicorn（多线程，模型推理串行） |
| 前端 | React 18 + Vite（单页多标签），HMR 热更新 |
| 数据库 | SQLite（`data/web.db` 检测记录 + 账号/日志/功能开关/公告/通知中心聊天等 + `data/smart_verify.db` 核验数据 + `data/rs_verify.db` 遥感核验 + `data/face.db` 人脸识别数据）；上传/结果图按游客设备落盘 `data/*_uploads`、`data/detect_results`（B76 起无浏览器缓存，统一后端存储）；聊天文件落盘 `data/chat_files/<user_id>/`（B76 起无浏览器缓存，统一后端存储） |
| 检测核心 | 复用 `../ImageAuthenticityDetector`（V2.4，不复制代码，算法更新自动跟随） |
| 核验模型 | SuperPoint 特征提取 + LightGlue 特征匹配 + RANSAC（懒加载，首次核验加载） |
| 遥感核验 | 复用 `../Remote_sensing`（多模态大模型 CLI，web 通过其 `web_bridge.py` 子进程调用，算法更新自动跟随） |
| 人脸识别 | 复用 `../FaceRecognition`（RetinaFace 检测 + ArcFace 512 维特征，web 进程内直调：全局推理锁 + 懒加载 + 空闲 300s 自动卸载）；**全局人脸库** `FaceRecognition/face_db/faces.db`（模块自治，含 v2 扩展字段/分页/改名/账号绑定，所有用户共享） |
| 登录体系 | PBKDF2 密码哈希 + sha256 token（30 天滑动过期）+ 游客/用户双轨（`X-Device-Id` ↔ `Bearer token`）+ 人脸登录（已录入人脸的账号匹配）；SMTP 发送验证码（未配置时打印后端日志）；sqlite3 SQL 原生 |

## 技术方案详解（简历/汇报素材）

### 1. 整体架构：模块化单体（Modular Monolith）

单进程 FastAPI 应用按业务域组装三个子系统，**逻辑上微服务化（独立数据库/存储/路由前缀），物理上单进程部署**——兼得隔离性与零运维成本：

```
FastAPI 主应用 (app.py, :8000)
├── 纯 ASGI 中间件层：CORS → FeatureGateMiddleware（功能开关拦截）→ Envelope（统一响应包装）
├── 主应用路由：/api/auth（登录）/api/admin（管理）/api/chat（通知中心）/api（检测）
├── mount("/smart", smart_app)      ← 点位核验子应用（独立 smart_verify.db + smart_uploads/）
└── mount("/rsverify", rs_app)      ← 遥感核验子应用（独立 rs_verify.db + rs_uploads/）

算法层（三种集成模式，均不复制代码）：
├── 进程内共享：ImageAuthenticityDetector（sys.path 注入，直接 import 判定核心）
├── 核心库转发：ImageVerifier（smart_verify/services/verifier.py 仅作兼容层 re-export）
└── 子进程桥接：Remote_sensing/web_bridge.py（子进程 + JSON 中转，主进程不加载 VLM 依赖）
```

- 每个子系统**独立 SQLite + 独立落盘目录**，互不干扰、单独可清空（admin 三类清空接口按此口径核对）；
- 子应用挂载方式为 ASGI `mount`，异常处理各自注册（避免父应用中间件双重包装响应）。

### 2. 后端技术细节

#### 2.1 统一响应封套（api_envelope.py · 纯 ASGI 中间件）

所有 JSON 接口统一包装为 `{code:0, msg:"", data:...}`，实现上的三个关键决策：

- **不用 `BaseHTTPMiddleware`**：新版 Starlette 会把下游响应包装成 `_StreamingResponse` 并缓冲，导致流式响应无法透传——改写**纯 ASGI 协议层中间件**，在 `send` 通道上按 `content-type` 分流：非 JSON（NDJSON 流/图片/Excel 下载）直接透传，JSON 才缓冲拼装后包装；
- **幂等防双重包装**：包装前检测 body 是否已含 `code/msg/data` 三键（异常处理器或业务侧主动返回的结构），避免子应用被父应用重复包一层；
- **业务码透传**：`HTTPException(detail={"code":1002, "msg":"..."})` 时保留业务码（如功能开关 1009），否则降级用 HTTP 状态码。

#### 2.2 身份双轨与设备隔离（auth_device.py）

游客（免登录试用）与登录用户双轨身份，解析优先级：

```
Authorization: Bearer <token> 有效 → user_id（此时忽略 X-Device-Id，防登录态伪造他人设备数据）
  ↓ 无/失效
X-Device-Id（游客设备标识，前端 localStorage 生成）→ device_id 隔离
```

- token 落库存 **sha256 哈希**（泄露库文件也无法还原 token），30 天滑动过期；
- 关键兼容设计：`<img>` 标签无法携带自定义请求头 → 所有图片 URL 统一拼 `?dev={device_id}` 查询参数，后端图片路由双通道取身份（header 或 query）；
- 登出后回退本机游客视图（device_id 全程保留），历史游客数据不丢、不与账号数据合并。

#### 2.3 统一模型管理器（model_manager.py · 多系统 GPU 资源调度）

单卡 8GB 环境下三个 AI 系统共存的显存治理方案：

| 机制 | 实现 |
|---|---|
| 懒加载单例 | `manager.get(name, loader, est_gb)` 首次调用才加载，进程内复用 |
| 全局推理串行锁 | `with manager.infer:` 三系统推理互斥，防并发挤爆显存 |
| 显存预算 + LRU 卸载 | 常驻模型 + 子进程任务记账合计超 6GB 预算时，按最久未用卸载 |
| 空闲自动卸载 | 后台 reaper 线程每 10s 扫描，超时未用模型自动释放（SP+LG 核验完即卸载 + 60s 兜底） |
| 任务记账 | TruFor 等子进程型任务 begin/end_task 登记，与常驻模型统一纳入预算 |
| 入口防御 | nvidia-smi 实测 GPU 可用 <1.5GB 时直接拒绝新任务（能感知 Ollama 等第三方进程占用，torch 查询做不到） |

#### 2.4 NDJSON 流式检测（detect.py）

批量检测 30 秒级长任务的双向流式方案：

- **事件协议**：`{"type":"phase", pct}`（阶段切换）→ `{"type":"progress", done, total}`（逐张推理进度）→ `{"type":"done", results}`（最终结果），每行一个 JSON 以 `\n` 分隔；
- **子进程进度转发**：推理在子进程执行，进度经 `queue.Queue` 回传，由生成器 `yield` 推流；百分比做分段映射（预处理 3% / 模型加载 5% / 推理 10→90% / 生成结果 93% / 完成 100%），进度条全程平滑无跳变；
- **Windows 句柄兜底**：客户端中途断开时推理子进程仍在写文件，`rmtree(ignore_errors=True)` 会静默删不干净——`finally` 中先删一次、再 `join` 推理线程（最长 300s）释放句柄后补删，确保临时目录零残留；
- 后台线程每 2 分钟扫描 30 分钟无写入的残留目录兜底（断电/进程被杀场景）。

#### 2.5 非阻塞操作日志（auth_device.py）

`log_operation()` 只做入队（队列满丢最旧），后台线程每 5s 批量 flush（单批最多 200 条 executemany），关键接口打点不增加请求延迟；90 天自动清理。

#### 2.6 敏感配置加密（rs_verify/services/crypto.py）

遥感核验的多平台 api_key 落库加密：**AES-256-GCM**（密钥由环境变量经 SHA-256 派生，随机 12 字节 nonce，`base64(nonce+ciphertext)` 存储）——认证加密同时保证机密性与防篡改。

#### 2.7 上传幂等与数据生命周期

- 同设备同名上传幂等（服务端已有直接复用记录，不重复落盘）；
- 游客数据 30 天无活跃自动清理（各子系统独立守护线程）；
- 删除记录联动物理文件与空目录；admin 三类清空接口（游客/用户/全部）按统一口径核对每个子系统的新表与新目录。

### 3. 前端技术细节

#### 3.1 统一请求层（api/index.js）

所有接口走单一 `request()` 封装，收敛横切逻辑：

- 自动注入 `X-Device-Id`（游客）与 `Authorization: Bearer`（登录）双头；
- `{code,msg,data}` 自动解包返回 `data`，`code!=0` 抛业务 Error——**上层组件永远拿到干净数据，不感知包装协议**；
- **401 事件化**：token 失效时派发全局 `auth-expired` 事件（AuthContext 监听统一清理登录态），而非在每个调用点重复处理；
- 非 JSON 响应（流式/二进制）原样返回 Response，流式与下载零特殊处理成本。

#### 3.2 NDJSON 流式消费（detectApi.js）

`fetch` + `ReadableStream.getReader()` + `TextDecoder` 增量解码，**缓冲区按 `\n` 切分**（半个 JSON 行缓存到下一块拼接，处理 TCP 分包边界），逐行 `JSON.parse` 回调 `onProgress` 驱动进度条，`done` 事件携带最终结果——检测全程实时反馈，无轮询。

#### 3.3 登录态全局状态（AuthContext）

- token 存 localStorage，刷新页面经 `/me` 恢复会话；`ready` 标志防止恢复期闪现"未登录"UI；
- `auth-changed` / `auth-expired` 两个全局 CustomEvent 构成轻量事件总线——登录/登出/失效时各功能页监听刷新自身数据，无需引入状态管理库。

#### 3.4 主题系统（theme.js + CSS 变量）

- 全部颜色收敛为 `--c-*` CSS 变量，浅色 `:root` 默认 / 深色 `[data-theme="dark"]` 覆盖，**组件零颜色硬编码**；
- 自定义主色：深色模式用 CSS `color-mix()` 自动联动衍生色；浅色模式 JS 按 `mixHex` 算法重算 11 个衍生变量（hover/soft/border/row/ring/渐变端）——换主色即刻全局一致，无图片资源需替换。

#### 3.5 体验优化清单

| 优化点 | 设计动机 |
|---|---|
| 双击行切换勾选（排除勾选/操作列）+ 列表 `user-select:none` | 批量操作高频场景，双击误触文本选区的经典痛点 |
| toast（3s 自动消失）+ 组件内确认弹窗，**禁用浏览器 alert/confirm** | 视觉与主题统一，不被浏览器原生样式打断 |
| 耗时操作必有等待条/进度反馈（检测流式、核验进度轮询、导出等待） | 30s 级长任务不可黑盒 |
| 核验批量"开始按钮自动变核验选中(N)、无匹配禁用开始" | 状态即提示，杜绝无效点击后报错 |
| 遥感缩略图拖拽排序 + 刷新从后端恢复 | 顺序即配对语义，刷新不丢编排 |
| 铃铛/通知中心经 `CHAT_REFRESH` 全局事件同步未读 | 任意入口已读后全站红点即时一致 |
| 聊天两段式发送（选图先入待发区，可删可改，确认才发） | 误选文件可撤回，同步清理后端落盘 |
| i18n 双语（zh-CN/en）命名空间化，插值键与 t() 参数严格对齐 | 面向汇报/演示场景 |

#### 3.6 样式作用域约定

三系统样式分别限定 `.detect` / `.smart-*` / `.rs-*` 前缀，通用组件保持全局——多子系统共存于一个 SPA 互不污染。

### 4. 数据传输与存储设计

| 主题 | 方案 |
|---|---|
| 库分离 | web.db（检测+账号+日志+聊天）/ smart_verify.db / rs_verify.db 三库独立，故障域隔离、单独可清空 |
| 前后端通信 | 前端一律相对路径，开发环境 Vite 代理 `/api` `/smart` `/rsverify` → 8000（生产同源部署零改动） |
| 长任务反馈 | 检测用 **NDJSON 服务端推送**（单向进度，免轮询）；核验批量用**进度轮询**（后台任务+可取消）——按任务形态选型 |
| 图片传输 | URL 相对路径 + `?dev=` 身份参数（img 标签无法带头的兼容方案）；结果图按需 kind 参数取 orig/heat/analysis/thumb |
| 导出下载 | Excel 内存生成经 blob 下载，不经磁盘中转 |
| 备份恢复 | 全量数据导出 ZIP（meta.json + 三系统 JSON + files/），恢复合并追加、图片落本设备目录 |

### 5. 三大算法能力的集成方式

| 系统 | 算法 | 集成模式 | 要点 |
|---|---|---|---|
| 图像篡改检测 | TruFor V2.4（13 指标融合判定） | **进程内共享**：sys.path 注入直接 import 判定核心；**推理子进程**隔离 | 判定规则与 CLI 同源；模型子进程内加载，任务结束即释放显存 |
| 点位真实性核验 | SuperPoint+LightGlue+RANSAC | **核心库转发**：ImageVerifier 单一算法来源，web 侧仅兼容层 | Web/CLI 三端同算法同阈值；核验完即卸载 + 空闲兜底 |
| 遥感变化核验 | 多模态大模型（DeepSeek/Qwen/GPT 等） | **子进程桥接**：web_bridge + JSON 中转 | 主进程零 VLM 依赖；用户自配 api_key AES 加密落库；多平台参数适配矩阵在 CLI 层统一处理 |

三系统推理共享全局串行锁与显存预算——**单卡 8GB 上三个 AI 系统稳定共存**是本平台最核心的工程约束与设计成果。

### 6. 简历亮点速览

- **架构**：模块化单体设计，三 AI 子系统独立库/存储/路由，ASGI 中间件层实现统一响应封套与功能开关拦截
- **资源治理**：统一模型管理器（懒加载 + LRU 卸载 + 空闲回收 + 推理串行锁 + 显存记账），单卡 8GB 稳定跑三模型
- **实时性**：NDJSON 双向流式（服务端逐行推送 + 前端 ReadableStream 增量解析），30s 级任务全程进度可视
- **安全**：PBKDF2 密码哈希、sha256 token 滑动过期、AES-256-GCM 敏感配置加密、游客/用户双轨身份防伪造
- **性能**：非阻塞操作日志（队列+批量写）、上传幂等、临时文件三重清理兜底
- **前端工程**：统一请求层自动解包、事件总线登录态、CSS 变量主题系统（自定义主色实时衍生）、i18n 双语

## 目录结构（按功能分组）

```
web/
├── app.py                    # 主入口：CORS + 功能开关中间件 + 统一响应格式 + 挂载 /api/auth、/api/admin、/api（检测）+ /smart（核验）+ /rsverify（遥感）+ uvicorn 启动
├── api_envelope.py           # 统一响应格式 {code,msg,data}（纯 ASGI 中间件 + 404/500 异常包装；流式/图片/下载透传）
├── auth.py                   # 登录体系后端：users/email_codes/tokens 表 + 注册/登录(密码·邮箱码)/验证码/忘记密码/改密/登出/me/绑定邮箱/导出数据 + SMTP 发送
├── chat.py                    # 通知中心后端：聊天（text/image/zip/emoji）/好友/好友申请/公告投递，挂载 /api/chat（web.db 主库，文件落盘 data/chat_files/）
├── auth_device.py            # 游客/用户双轨身份解析 + 操作日志（operation_logs 队列+后台批量写）
├── admin.py                  # 系统管理（admin）：总览 / 用户管理 / 功能开关 / 系统公告 CRUD / 操作日志 + 公开公告·功能开关接口
├── feature_gate.py           # 功能开关后端拦截（纯 ASGI 中间件：关闭时非 admin 返回 1009）
├── detect.py                 # 图像篡改检测后端（上传/检测流/结果/导出/清理 + SQLite，挂载 /api）
├── model_manager.py          # 全局模型管理器（GPU 显存记账 + 全局推理锁 + 空闲自动卸载）
├── smart_verify/             # 点位真实性核验子应用（独立数据库/存储，挂载 /smart）
│   ├── app.py                #   子应用组装（图片服务/重置/静态）
│   ├── database.py           #   独立 SQLite（data/smart_verify.db）
│   ├── models.py             #   数据模型（ImageRecord / Pair / VerificationResult）
│   ├── routers/              #   upload / verify / results / export
│   └── services/             #   verifier（SP+LG+RANSAC）/ annotation / parser
├── rs_verify/                # 遥感变化核验子应用（独立数据库/存储，挂载 /rsverify）
│   ├── app.py                #   子应用组装（health/reset/路由注册 + 启动迁移）
│   ├── database.py           #   独立 SQLite（data/rs_verify.db）
│   ├── models.py             #   数据模型（UploadImage / AnalysisRecord / rs_users / rs_presets / rs_models）
│   ├── routers/              #   upload / analyze / results / settings / export
│   └── services/             #   runner（调用 Remote_sensing/web_bridge）/ presets（预设 CRUD+AES）/ crypto / excel / models
├── face/                     # 人脸识别子应用（独立数据库/存储，挂载 /face）
│   ├── app.py                #   子应用组装（health/reset/stats + 游客 30 天清理 + cleanup_library 供 admin 清空）
│   ├── database.py           #   独立 SQLite（data/face.db）
│   ├── models.py             #   数据模型（FaceUpload 上传 / FaceResult 结果，一行=一张脸）
│   ├── scope.py              #   双轨归属过滤（同 smart_verify）
│   ├── services/engine.py    #   FaceRecognition 模块桥接（config 名冲突置换导入 + 推理锁 + 人脸裁剪）
│   └── routers/              #   upload / recognize（NDJSON 流式）/ results（人工入库+导出）/ library（admin）/ auth_face（登录+录入）
├── start.ps1                 # 一键启动器（自动释放端口、起后端+前端、Ctrl+C 停止）
├── README.md                 # 本文件
├── DEVELOPMENT_GUIDE.md      # 开发辅助文档（架构约定/新增系统模板/历史 Bug 记录/后续规划）
├── data/                     # SQLite：web.db（检测+账号+日志）+ smart_verify.db（核验）+ rs_verify.db（遥感）
│   ├── detect_uploads/       #   检测上传原图（按设备子目录，删除记录联动删）
│   ├── detect_results/       #   检测结果图（热力/分析/缩略图，删除记录联动删）
│   ├── smart_uploads/        #   核验上传图片（持久保留，重置时清空）
│   ├── smart_visualizations/ #   核验可视化图（持久保留，重置时清空）
│   ├── rs_uploads/           #   遥感核验上传图片
│   ├── rs_work/              #   遥感核验 CLI 产物（仅标注对比图，按记录清理；Excel/中转 JSON 已不落盘）
│   ├── face_uploads/         #   人脸识别上传图（按设备子目录，删除记录联动删）
│   ├── face_thumbs/          #   人脸识别结果人脸裁剪图（删除结果联动删）
│   └── chat_files/           #   通知中心聊天文件（按 user_id 子目录：图片/zip；发送时落盘，删除/双向删除时清理）
├── tmp/                      # 检测临时目录（用后即删，异常残留由后台线程/启动时自动清理）
└── frontend/                 # 前端（React + Vite）
    ├── index.html            # 页面入口（浏览器标签标题：AI 检测平台）
    └── src/
        ├── main.jsx          # 入口（启动时应用主题）
        ├── index.css         # 全局样式 + 主题变量（:root 浅色 / [data-theme=dark] 深色）
        ├── theme.js          # 主题：深浅色 + 主色（localStorage 持久化）
        ├── i18n/             # 国际化：index.js + zh-CN.json / en.json（含 auth/profile/admin 命名空间）
        ├── api/              # 接口封装（按功能分文件，统一走 index.js request()）
        │   ├── index.js      #   request() 统一封装：自动带 X-Device-Id + Authorization、解包 {code,msg,data}
        │   ├── deviceId.js   #   游客设备 id（localStorage `aigc_device_id`，请求头 X-Device-Id）
        │   ├── detectApi.js  #   检测接口（上传/列表/流式检测/结果/导出/统计）
        │   ├── smartApi.js   #   核验接口（上传/配对/核验/进度/导出）
        │   ├── rsApi.js      #   遥感核验接口（上传/分析/结果/设置/模型列表/导出）
        │   ├── faceApi.js    #   人脸识别接口（上传/流式识别/结果/人工入库/人脸登录/录入/库管理/导出）
        │   ├── authApi.js    #   登录体系接口（注册/登录/验证码/改密/me/绑邮箱/导出数据）
        │   ├── adminApi.js   #   系统管理接口（总览/用户/开关/公告/日志）
        │   └── chatApi.js    #   通知中心接口（好友/请求/会话/消息/待发/公告/摘要）+ 文件 URL + CHAT_REFRESH 全局刷新事件
        ├── auth/             # AuthContext.jsx（登录态全局状态 + auth-changed/auth-expired 事件 + 登录弹窗开关）
        └── components/
            ├── common/       # App（标签页系统+登录态整合）/ Home（功能选择器）/ Dropdown / SystemSettings / AuthModal（登录·注册·改密·人脸登录弹窗）/ FaceLoginPanel（人脸登录：照片+摄像头）/ BellMenu（顶栏小铃铛）/ NotificationCenter（通知中心页：会话列表+聊窗）
            ├── profile/      # Profile（个人资料页：左侧菜单 + 账号/改密/邮箱/人脸/数据导出）
            ├── admin/        # AdminPage（系统管理页：总览/用户/开关/公告/日志）
            ├── detect/       # Detect（检测页）/ SettingsModal（参数弹窗）
            ├── verify/       # SmartVerify（核验页）/ UploadPanel / ResultTable / ImageCompare
            ├── face/         # FaceRec（人脸识别页：上传列表+结果列表+详情+人工入库+冲突确认）
            └── rsverify/     # RsVerify（遥感核验页，含上传/场景/结果 + 设置弹窗）
```

## 启动方式

```powershell
cd web
./start.ps1
```

- 自动：清理占用端口 → 启动后端（FastAPI @ 8000）→ 启动前端（Vite @ 5173）
- 浏览器访问 http://localhost:5173
- 按 Ctrl+C 停止全部服务
- **预置管理员**：`admin / Admin@2026`（首次登录会强制修改初始密码；普通用户可在登录弹窗"注 册"自助注册）

> 提示：如需真实发送邮箱验证码，在 `web/.env` 配置 `SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_FROM/SMTP_SSL`（`.env` 文件后端启动时自动读取，也可用进程环境变量覆盖，二者都不配置时验证码打印到后端控制台，便于开发联调）。`.env` 含 SMTP 授权码，属敏感文件，勿提交到代码仓库。

## 后端接口

### 登录体系（`/api/auth/*`）

| 接口 | 说明 |
|------|------|
| `POST /api/auth/register` | 注册（用户名/密码必填，邮箱可选；密码 8-20 位含大小写+数字；自动登录返回 token） |
| `POST /api/auth/login` | 账号密码登录（错密 5 次锁 5 分钟；返回 token + user） |
| `POST /api/auth/login_email` | 邮箱验证码登录（验证码来自 `send_code` purpose=login） |
| `POST /api/auth/send_code` | 发送验证码（body `{email, purpose}`，purpose=register/login/reset/bind；60s 限速；SMTP 未配置时打印后端日志） |
| `POST /api/auth/forgot` | 忘记密码重置（邮箱验证码 + 新密码；全部 token 失效） |
| `POST /api/auth/change_password` | 修改密码（旧密码校验；全部 token 失效，需重新登录） |
| `POST /api/auth/logout` | 退出登录（删除当前 token） |
| `GET /api/auth/me` | 当前登录用户信息（含 email_verified / role / must_change_password） |
| `POST /api/auth/bind_email` | 绑定/更换邮箱（purpose=bind 验证码，验证码一次性） |
| `POST /api/auth/verify_old_email` | 更换邮箱第一步：校验旧邮箱验证码（确认本人操作，purpose=bind 复用） |
| `GET /api/auth/export` | 我的数据统计（账号信息 + 三系统记录数与占用大小，供个人资料页统计展示） |
| `GET /api/auth/backup` | 导出完整备份 ZIP（meta.json + detect/smart/rs.json 全部记录 + files/ 全部图片），可导入恢复 |
| `POST /api/auth/restore` | 从备份 ZIP 恢复（multipart `file`；合并追加到当前账号，图片落盘本设备目录，无效 ZIP/超 300MB 拒绝） |

### 系统管理（`/api/admin/*`，仅 admin；非 admin 401/403）

| 接口 | 说明 |
|------|------|
| `GET /api/admin/overview` | 总览：用户数 / 今日活跃 / 三系统记录数 / 功能开关状态 |
| `GET /api/admin/users` | 用户列表（`?search=&page=&size=`） |
| `POST /api/admin/users` | 新建用户（body `{username, password, email?, role?}`；复用密码策略校验；创建后可直接登录） |
| `POST /api/admin/users/{id}/toggle` | 禁用/启用用户（禁用时该用户全部 token 失效） |
| `POST /api/admin/users/{id}/reset_password` | 重置密码（body `{password}`；下次登录强制改密） |
| `POST /api/admin/users/{id}/role?role=` | 调整角色（user/admin） |
| `DELETE /api/admin/users/{id}` | 删除用户（联动清理三系统数据与文件；操作日志脱敏） |
| `GET /api/admin/features` + `PUT /api/admin/features/{name}` | 功能开关（detect/verify/rsverify/face）读 / 改 |
| `GET/POST /api/admin/announcements` + `PUT/DELETE /{id}` | 系统公告 CRUD |
| `GET /api/admin/logs` | 操作日志（`?action=&operator=&from=&to=&page=&size=`；90 天自动清理） |
| `DELETE /api/admin/logs` | 手动清空全部操作日志（清空动作本身记录一条新日志） |
| `GET /api/admin/data` | 数据管理统计（用户数 + 三系统用户/游客记录数与游客设备数） |
| `POST /api/admin/data/clear_guests` | 清空全部游客数据（记录+文件+聊天子系统；账号不受影响） |
| `POST /api/admin/data/clear_users` | 清空全部用户数据（记录+文件+聊天子系统；账号保留） |
| `POST /api/admin/data/clear_all` | 一键清空全部业务数据（记录+文件+聊天子系统+普通用户账号+日志；仅保留当前 admin） |

### 公开（`/api/*`，无需登录）

| 接口 | 说明 |
|------|------|
| `GET /api/announcements` | 启用中的系统公告（登录用户顶栏横幅 / 游客"登录后可查看"提示） |
| `GET /api/features` | 功能开关状态（前端隐藏入口） |

### 通知中心·聊天（`/api/chat/*`，仅登录用户）

| 接口 | 说明 |
|------|------|
| `GET /api/chat/search?q=` | 好友搜索（用户名/8 位 UID，仅返回已存在用户） |
| `POST /api/chat/request` | 发送好友申请（body `{receiver_id}`；同一对待处理唯一） |
| `GET /api/chat/requests` | 好友申请列表：收到的（`dir:in`，可同意/拒绝）+ 发送的（`dir:out`，状态展示：等待对方同意/已添加/添加失败） |
| `POST /api/chat/request/{rid}/handle` | 处理好友申请（body `{action}` = accept/decline） |
| `GET /api/chat/friends` | 好友列表 |
| `DELETE /api/chat/friend/{id}` | 删除好友（解除关系 + 级联删除该对消息与落盘文件，彻底） |
| `GET /api/chat/conversations` | 会话列表（含公告伪会话、未读、申请数、最近消息摘要） |
| `POST /api/chat/conversation/{peer}/pin` | 置顶/取消置顶会话 |
| `DELETE /api/chat/conversation/{peer}` | 删除会话（仅本人视角，对方记录保留） |
| `POST /api/chat/conversation/{peer}/unread` | 标记会话未读 |
| `GET /api/chat/messages?peer=` | 消息列表（按本人视角过滤已删除；peer=0 为公告伪会话） |
| `POST /api/chat/send` | 发送文本/表情 |
| `POST /api/chat/send_file` | 直接发送图片/zip（multipart） |
| `POST /api/chat/pending/upload` | **两段式**：上传到待发区（队列预览，不直接发送） |
| `DELETE /api/chat/pending/{pid}` | **两段式**：删除待发附件（同步清理后端落盘文件，仅本人） |
| `POST /api/chat/pending/send` | **两段式**：批量把待发附件发送为消息 |
| `GET /api/chat/file/{msg_id}` | 聊天文件（图片预览/zip 下载，`?token=` 供 img/a 访问） |
| `GET /api/chat/notices` | 用户个人公告副本（惰性投递当前启用公告）+ 已读游标 |
| `POST /api/chat/notices/read` | 公告已读（推进本人已读游标） |
| `GET /api/chat/summary` | 铃铛摘要（公告未读 + 会话未读 + 待处理申请 + 最近会话） |
| `POST /api/chat/clear` | 一键清理本人全部聊天（会话/消息/落盘文件/好友申请/公告副本；保留好友关系） |
| `GET /api/chat/stats` | 聊天数据统计（会话/消息数/占用，供系统设置展示） |

### 检测（`/api/*`）

| 接口 | 说明 |
|------|------|
| `GET /api/params` | 默认参数 / 预设档位 / 参数说明（检测参数弹窗） |
| `POST /api/detect/upload` | 批量上传图片（multipart；按设备+文件名幂等，同名复用已有记录，不重复落盘） |
| `GET /api/detect/uploads` | 当前设备上传列表（含 `done`=是否已检测；刷新恢复不丢） |
| `POST /api/detect/uploads/delete` | 删除上传项（`{ids}` 空=全部，联动删文件与空目录） |
| `GET /api/detect/uploads/{id}/img` | 上传原图（`?dev=` 游客设备参数，B78） |
| `POST /api/detect` | 批量检测（**NDJSON 流式**：先推 `phase`/`progress` 进度事件，最后 `done` 携带结果） |
| `GET /api/detect/results` | 当前设备检测结果列表 |
| `POST /api/detect/results/update` | 人工修正判定 / 备注 |
| `POST /api/detect/results/delete` | 删除结果（联动删结果图文件） |
| `POST /api/detect/results/clear` | 一键清空当前设备全部结果 |
| `GET /api/detect/results/{id}/img/{kind}` | 结果图（kind=`orig`/`heat`/`analysis`/`thumb`，`?dev=`） |
| `GET /api/detect/stats` | 检测数据统计（结果/上传/占用，供系统设置展示） |
| `POST /api/export` | 导出 Excel（brief=列表内容+2图；detail=详情全部指标+3图，含表格美化） |
| `POST /api/cleanup` | 一键清理后端遗留临时文件 |
| `GET /api/models` | 统一模型管理器占用状态（各模型显存/任务记账/GPU 实际占用，供系统设置展示） |

### 核验（`/smart/api/*`）

| 接口 | 说明 |
|------|------|
| `POST /smart/api/upload` | 批量上传整改图/暗访图（同名幂等：服务器已有同名文件直接复用，不重复落盘） |
| `POST /smart/api/pair/{auto\|sequential\|manual}` | 三种配对模式 |
| `POST /smart/api/verify/single/{pair_id}` | 单对核验 |
| `POST /smart/api/verify/batch` \| `/selected` | 批量 / 选中核验（进度轮询 `GET /verify/progress`） |
| `GET /smart/api/results` + `/results/{id}/detail` | 结果列表 / 详情（含标注坐标） |
| `PUT /smart/api/results/{id}/manual` \| `/human-judgment` | 人工修正 / 人工复核判断 |
| `GET /smart/api/images/{id}` \| `/visualization/{id}` | 原图 / 可视化图 |
| `POST /smart/api/export/excel` | 导出核验结果 Excel（body `{pair_ids}`，空=全部；嵌原图/对比图/可视化图） |
| `POST /smart/api/reset` | 重置（清空所有核验数据） |
| `GET /smart/api/stats` | 核验数据统计（配对/图片/占用，供系统设置展示） |

### 遥感核验（`/rsverify/api/*`）

| 接口 | 说明 |
|------|------|
| `POST /rsverify/api/upload` | 上传一对图片（`before`/`after` 两个文件字段） |
| `POST /rsverify/api/analyze` | 触发分析（body `{before_id, after_id, scenario}`，阻塞约 30-60s，子进程调 Remote_sensing CLI；CLI 以 `--no-excel` 跳过 Excel 落盘，标注图留在 rs_work） |
| `GET /rsverify/api/results` + `/results/{id}` | 结果列表（新→旧）/ 单条详情 |
| `GET /rsverify/api/images/{id}` | 标注对比图 |
| `DELETE /rsverify/api/results/{id}` + `POST /results/batch-delete` | 删除单条 / 批量删除（`{ids}` 空=全部） |
| `GET /rsverify/api/settings` + `POST /settings` | 当前激活预设配置 + 预设列表 + 该预设地址已获取的模型（隔离）；POST 更新激活预设（api_key AES 加密落库，各预设独立保存） |
| `GET /rsverify/api/presets` + `POST /presets` | 预设平台列表（按当前用户）/ 新增预设（同名查重；首个自动激活） |
| `POST /rsverify/api/presets/{id}` + `DELETE /presets/{id}` + `POST /presets/{id}/activate` | 更新 / 删除（删激活预设自动激活第一个）/ 激活预设（核验用当前激活预设） |
| `POST /rsverify/api/models/list` | 通过 base_url 联网获取模型列表并**按 base_url 隔离同步**（新增补入、上游已无的删除）；返回该地址模型 + 静态兜底 |
| `POST /rsverify/api/export/excel` | 导出 Excel（body `{ids}`，空=全部；嵌入标注图） |
| `GET /rsverify/api/health` + `POST /api/reset` | 健康检查 / 清空所有遥感核验数据（上传图/标注图/记录，供系统设置全局清理调用） |
| `GET /rsverify/api/stats` | 遥感核验数据统计（记录数/占用 MB，供系统设置展示） |

### 人脸识别（`/face/api/*`）

| 接口 | 说明 |
|------|------|
| `POST /face/api/upload` | 批量上传（multipart；按归属+文件名幂等；EXIF 方向校正 + 超大缩放 ≤2048 + 统一 JPEG） |
| `GET /face/api/uploads` | 上传列表（status=pending/done/no_face/error，刷新恢复） |
| `POST /face/api/uploads/delete` | 删除上传图（`{ids}` 空=全部，联动删识别结果与文件） |
| `GET /face/api/uploads/{id}/img` | 上传原图（`?dev=` 设备校验） |
| `POST /face/api/recognize` | 批量识别（**NDJSON 流式**：phase/progress 逐图进度 → done；一图多脸多结果行；重测=覆盖旧结果） |
| `GET /face/api/results` | 结果列表（一行=一张脸：人脸缩略图/姓名/相似度/状态/人工修正标记） |
| `GET /face/api/results/{id}/detail` | 详情（bbox/检测置信度/Top-K 候选相似度/512 维特征向量/阈值） |
| `GET /face/api/results/{id}/thumb` | 人脸裁剪缩略图 |
| `POST /face/api/results/manual_save` | 人工标注入库（登录用户；查重：相似不同名返回 `{need_confirm, conflict}`，mode=overwrite 改名+补样本 / new 独立人员 / 同名直接补样本；同步更新该行结果） |
| `POST /face/api/results/delete` | 删除结果（`{ids}` 空=全部，联动删缩略图文件） |
| `POST /face/api/export` | 导出 Excel（`{ids}` 空=全部；嵌人脸缩略图+原图缩略+姓名/相似度/状态/人工修正/时间） |
| `POST /face/api/login_face` | 人脸登录（multipart 照片；匹配已绑定账号的人脸 → 签发 token） |
| `POST /face/api/login_face_frame` | 人脸登录（JSON base64 摄像头帧） |
| `GET /face/api/profile_face` | 我的人脸录入状态（绑定姓名/样本照/样本数） |
| `POST /face/api/profile_face` | 录入/更新人脸（multipart file+name+mode；查重同 manual_save；已绑定他人账号则 409 拒绝；入库后绑定本人账号） |
| `DELETE /face/api/profile_face` | 删除录入（解绑账号 + 删除库中该人员全部样本与样本照） |
| `GET /face/api/library` + `POST` | admin 人脸库分页列表（`?q=&page=&size=` 模糊搜索 name/person_id/created_by）/ 新增人员（查重同上） |
| `GET /face/api/library/{id}/thumb` | 库样本照服务 |
| `POST /face/api/library/rename` | 人员级改名（该 person_id 全部样本同步更新） |
| `POST /face/api/library/photo` | 更换某样本照片（重新提取特征替换该记录，保留 person_id/绑定） |
| `DELETE /face/api/library` | 批量删除记录（`{ids}`，联动删样本照） |
| `GET /face/api/stats` + `POST /face/api/reset` + `GET /face/api/health` | 统计（上传/结果/人脸库概况）/ 清空当前归属识别数据（不动人脸库）/ 健康检查 |

### 检测流程

上传图持久化 `data/detect_uploads/<device>/`（B76，刷新恢复）→ 检测时预处理到 `tmp/<session>/` → 子进程加载 TruFor 模型（约 30 秒，仅一次）→ 批量推理（tqdm 进度实时解析转发）→ 逐张判定/生成图落盘 `data/detect_results/<device>/` 并写 `detect_records` → 临时目录用后即删。

### 数据存储

- **SQLite**：`data/web.db` 检测表 `detect_uploads`（上传图记录）+ `detect_records`（检测结果：判定指标/参数快照/原图·热力·分析·缩略图落盘路径）+ 账号表 `users`（PBKDF2 密码哈希/邮箱/角色/禁用/首登强制改密）+ `email_codes`（验证码：purpose 区分 register/login/reset/bind、60s 限速、10 分钟过期、一次性）+ `tokens`（sha256 token、30 天滑动过期）+ `operation_logs`（操作日志，90 天自动清理）+ `feature_flags`（功能开关）+ `announcements`（系统公告源表）+ 通知中心聊天表 `chat_requests`（好友申请）/`chat_friends`（好友关系）/`chat_conversations`（会话，每用户视角）/`chat_messages`（消息，含本人视角删除标记）/`chat_pending`（待发附件）/`chat_ann_read`（公告已读游标）/`chat_ann_delivered`（用户个人公告副本）；`data/smart_verify.db` 核验三表（images/pairs/results）；`data/rs_verify.db` 遥感核验（rs_users 用户/rs_images/rs_records/**rs_presets** 预设平台按 user_id 隔离、内置默认预设 DeepSeek/Qwen/ChatGPT 自动写库查重/**rs_models** 模型按 user+base_url 隔离/api_key AES 加密）；`data/face.db` 人脸识别两表（face_uploads 上传/face_results 结果，一行=一张脸，embed_json 冗余存 512 维特征供人工入库免二次推理）；**全局人脸库** `FaceRecognition/face_db/faces.db`（模块自治：person_id/name/embed 512 维向量/thumb_path 样本照/user_id 账号绑定/created_by/created_at/source，v2 启动自动迁移补列；样本照落盘 `FaceRecognition/face_db/thumbs/`）
- **游客设备隔离（B76）+ 登录双轨（批次3）**：三平台数据表带 `device_id`（游客）+ `user_id`（登录，NULL=游客）；接口鉴权优先级 `Authorization: Bearer token` → user_id（**忽略 X-Device-Id 防伪造**），无/失效 token → `X-Device-Id` 设备隔离；`<img>` 加载的图片 URL 必须带 `?dev={device_id}`（浏览器 img 无法携带自定义头，B78 约定）；登录用户数据跨设备共享、登出后回退本机游客视图（游客数据互不合并）
- **无浏览器缓存**：B76 起检测/核验/遥感数据统一后端存储；IndexedDB 缓存已全部移除（遥感上传草稿缓存 B80、检测 db.js B81 均删除）

## 维护要点

- **算法升级**：直接更新 `../ImageAuthenticityDetector`，Web 无需改代码（`sys.path` 共享）
- **遥感核验算法**：更新 `../Remote_sensing` 目录即可自动跟随（web 仅通过 `rs_verify/services/runner.py` 引用其 `web_bridge.py`，子进程调用 CLI，不复制算法代码）；web 传入自定义 LLM 配置时由 web_bridge 生成临时配置、子进程结束即删，**不修改 Remote_sensing/config.yaml**；CLI 以 `--no-excel` 跳过 Excel 落盘，中转 JSON/临时配置放系统临时目录读取后即删，`rs_work` 仅保留标注图（web 结果在前端展示并自行导出）
- **模型管理**：统一由 `web/model_manager.py` 调度（全局单例）——TruFor 为**子进程任务型**（每次检测由 worker 线程启动子进程，模型在子进程内加载约 30 秒、单次批量仅加载一次，任务结束即释放显存）；SuperPoint/LightGlue 为**常驻懒加载单例**（约 0.5GB，核验完立即卸载 + 60s 空闲兜底，B74）。全局推理锁 `manager.infer` 保证多系统推理串行互斥（防并发挤爆显存），显存超预算自动按 LRU 卸载，入口有 GPU 可用显存检测（<1.5GB 抛 507 阻止，B75），占用状态可查 `GET /api/models`
- **核验算法核心库**：`../ImageVerifier`（独立、无 Web 依赖），Web 与命令行工具 [PointVerifier/verify.py](../PointVerifier/verify.py) 共用同一套 SceneVerifier 与文件名解析（`web/smart_verify/services/*` 为兼容层），算法单点维护；分发时携带该目录即可独立使用
- **检测串行**：`DETECT_LOCK = manager.infer`，与核验等系统共用同一把全局推理锁
- **临时文件**：正常路径 `finally` 即时删除；客户端中断泄漏由后台线程（30 分钟无写入）和启动时清理兜底
- **前端作用域**：通用组件/样式保持全局；检测页装饰样式限定 `.detect` 前缀；核验页样式限定 `.smart-*` 前缀；遥感核验页样式限定 `.rs-*` 前缀，避免互相污染
- **主题**：全部颜色走 `--c-*` CSS 变量，浅色为默认值（与原界面一致），深色由 `[data-theme="dark"]` 覆盖，主色可在系统设置中更换
- **交互约定**：提示用页面内 toast（3s 自动消失），破坏性操作用组件内确认弹窗，**禁止浏览器 alert/confirm**；耗时操作（导出/批量）必须有等待条或进度反馈；结果/上传列表**双击行切换勾选**（排除勾选列与操作列），列表禁用文本复制（`user-select:none`，避免双击误触发复制）
- **前后端分离**：前端 API/图片一律相对路径，开发环境由 `vite.config.js` 代理 `/smart`、`/rsverify` → 8000；后端资源 URL 返回相对路径
- **游客设备隔离**：三平台接口自动带 `X-Device-Id` 头（前端 `api/deviceId.js`）；`<img>` 无法带自定义头 → 图片 URL 一律拼 `?dev={device_id}`；游客数据 30 天无活跃自动清理（detect/smart/rs/face 各自后台守护线程，B81）
- **人脸识别（face）**：`web/face/` 子应用挂载 `/face`；算法层**进程内直调** `../FaceRecognition`（`face/services/engine.py` 桥接——sys.path 注入 + **config 名冲突置换导入**（与 ImageAuthenticityDetector 的顶层 config.py 同名共存，导入前临时置换 sys.modules、导入后恢复）+ web 全局推理锁 `manager.infer` + 模块自身懒加载/空闲 300s 自动卸载 + 任务型记账 1.2GB）；识别走 NDJSON 流式（同检测）；**全局人脸库** faces.db 在模块内（所有用户共享，游客只读不能人工入库）；admin 三类清空口径：占用级清 face 上传/缩略图文件、**配置级清人脸库全量**（faces.db + 样本照，`face.app.cleanup_library`）、全清兜底；人脸登录仅匹配"已绑定账号"的人脸子集（`face_db.find_by_user`），token 签发与密码登录同轨；人工入库查重三分支：相似不同名 → need_confirm（覆盖=改名+补样本/新增=独立人员）、**同名同人 → 直接补样本**、无相似 → 新人员
- **登录体系**：账号体系集中 `web/auth.py`（users/tokens/email_codes，PBKDF2 密码哈希，token 存 sha256 + 30 天滑动过期）；身份解析统一走 `auth_device.get_identity`（token 优先、忽略 X-Device-Id 防伪造）；验证码未配置 SMTP 时打印后端日志（开发联调用），配置后真实发送；邮箱验证码 60s 限速 / 10 分钟过期 / 一次性；admin 初始账号 `admin/Admin@2026` 首登强制改密（admin 可重置他人密码）
- **功能开关（批次5）**：`feature_gate.py` 按路径前缀拦截（detect/verify/rsverify/face，face 前缀 `/face/api`，见 B131），关闭时非 admin 返回 403+1009，admin 豁免；前端经 `GET /api/features` 隐藏入口（顶部标签 `TAB_META` 与首页 `Home.jsx` 卡片均由开关 + admin 豁免驱动显隐，不得硬编码 enabled，见 B131）；开关状态由 admin 系统管理页维护
- **操作日志**：`auth_device.log_operation(request, action, target, result, duration_ms)` 非阻塞入队 + 后台线程批量写（90 天自动清理）；auth/detect/smart/rs/admin 关键接口已接入
- **通知中心·聊天（批次扩展）**：仅登录用户（游客只读公告走 `/api/announcements`）；清空语义分三层——右键"删除聊天"= 仅删当前用户视角会话（对方保留）、删除好友 = 级联彻底删该对消息与文件、一键清理 = 删本人全部会话/消息/文件/申请/公告副本（**保留好友关系**），与系统设置"一键清空"互不影响；**消息个人视角隔离**：`chat_messages` 带 `del_by_sender`/`del_by_receiver` 标记，仅双方均删才物理清理落盘（见 B122）；**两段式发送**：图片/文件先入 `chat_pending` 待发区（可键盘/×删除并同步清后端文件），确认发送才落盘为消息；**公告投递模型**：个人副本 `chat_ann_delivered`（announcements 源表启用时惰性投递快照），admin 关闭/删除/编辑不影响用户已收到的公告（见 B126）；前端铃铛/通知中心未读经 `CHAT_REFRESH` 事件全局同步；聊天子系统已纳入 admin 三类清空接口（见 B115）
- **开发辅助文档**：见 [DEVELOPMENT_GUIDE.md](./DEVELOPMENT_GUIDE.md)（架构约定 / 新增系统模板 / **高频复发问题加权表**（把历史 B 系列按根因主题归并并统计复发次数权重，次数越大越要避免）/ 高频避坑速查 / 历史 Bug 记录 B1~B135 / 更新日志），开发前必读；新坑按模块登记 `B{n}`，若属加权表已有主题则并回对应行并让次数权重 +1
