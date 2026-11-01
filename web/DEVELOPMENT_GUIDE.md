# AIGC Detection · Web 开发辅助文档

> 合并自 `ADD_NEW_SYSTEM.md` + `BUGS_NOTES.md`，新增 i18n / 主题 / 全局清理等基础设施说明。
> 后续新增功能页、修复 bug、扩展全局能力时，本文档同步更新。

## 速读指引（新对话/新任务先看这里）

- **要做新功能页** → 直接看 [二、新增一个系统（操作模板）](#二新增一个系统操作模板) 的步骤清单
- **要改遥感核验（rsverify）** → 先看 [3.6 遥感核验子系统关键约定](#36-遥感核验子系统rsverify关键约定)，理解 web↔CLI 配置链路与本地模型设计
- **遇到怪问题（改代码没生效 / 编码报错 / 图片打不开）** → 查 [4.8 高频避坑速查](#48-高频避坑速查症状-根因-解法)，大多是踩过的坑
- **开发新功能 / 新子系统 / 改 bug 之前** → 先看 [高频复发问题加权表](#高频复发问题加权表开发前必看)（本文档第一章前）。它把历史 B 系列按根因主题归并并统计**复发次数权重**，次数越大的越要规避（删除清理残留 / 刷新恢复 / 组件风格 / 图片 URL / 连接锁 / 未重启 / 导出 / i18n 八大高频主题 + 通用自检清单）
- **记新坑** → 在 [五、历史 Bug 记录](#五历史-bug-记录按模块) 按模块追加 `B{n}`，并在 [六、更新日志](#六更新日志) 加一行；**若新坑属于[高频复发问题加权表](#高频复发问题加权表开发前必看)里的主题，把新 `B{n}` 并回对应行（含代表 Bug 列），并让该行的次数权重如实 +1，让权重随时间真实增长**
- **本文档约定**：所有界面文字走 i18n（`t()`）；样式用 `var(--c-*)` 变量；提示用 toast、破坏性操作用确认弹窗、耗时操作用进度条；禁止浏览器 `alert/confirm`

---

## 高频复发问题加权表（开发前必看）

> 下表把历史 Bug（B{n}）按**根因主题**归并，`次数` = 该主题在历史记录中作为真问题出现的次数（一个 bug 可能同时踩多个主题，会重复计）。**次数越大 = 反复越多次 = 越要重点避免**。开发新功能、新增子系统或改 bug 前，先看对应主题的"规避规矩"。

| 优先级 | 高频主题 | 次数 | 代表 Bug | 一句话根因 | 开发前必守的规避规矩 |
|:---:|---------|:---:|---------|-----------|--------------------|
| 🔴🔴 | **删除/清空后落盘文件或空文件夹残留** | **8** | B79 B55 B57 B99 B102 B103 B104 B123 | 删除只清了 DB 记录或主文件，落盘文件/空目录没同步删；各删除入口没共用同一个清理函数；或"先删文件再找目录"顺序颠倒 | ①删除必须**三连清**：DB 记录 + 落盘文件 + 空目录（文件删后 `os.rmdir`/`rmtree`）②一个子系统的**所有删除入口（单条/批量/级联/一键清理）复用同一个文件清理函数**③**先定位目录再删文件**（别先删文件导致找不到 rec_ 目录）④级联删除（删记录连带删被引用文件） |
| 🔴🔴 | **页面刷新后内容丢失/错乱/残留** | **8** | B66 B80 B82 B92 B93 B97 B124 B22 | 前端把数据存内存/本地，刷新后不从后端恢复；localStorage 记忆的"选中会话/场景"未校验仍存在；用户数据归属（游客/登录）切换未迁移；同 URL 图片被浏览器缓存显示旧图 | ①刷新后页面内容**一律从后端重新拉取恢复**，不依赖 memory/localStorage 当数据源②localStorage 恢复选中值**必须先校验目标仍存在于列表**，否则保持空③登录体系：游客数据须迁移到 username 下，否则登录后查空④`<img>` URL 带 `?dev=` 后要追加 `&t=时间戳` 防同 URL 缓存（B97） |
| 🔴🔴 | **前端组件风格/主题/原生控件未统一** | **8** | B40 B42 B65 B84 B90 B106 B108 B109 | 新控件裸用浏览器默认样式；原生控件（date/select/number）无法随主题；新增页面漏补 CSS/图标风格不一致 | ①任何新控件走 `--c-*` 主题变量 + 圆角 + 阴影 + `color-scheme`②原生 date/select/number 弹出面板无法定制的一律**自实现组件**（DateTimePicker/LocalModelDropdown）③number 输入隐藏原生 spinner④新页面必须同步补 index.css + zh/en 翻译⑤图标统一**单色线条 SVG**（`stroke=currentColor`），禁彩色 emoji⑥带 `tabIndex` 的可删项点击要手动 `focus()` 才能收到键盘事件（B123） |
| 🔴 | **图片/资源 URL 打不开（404）** | **6** | B3 B58 B78 B93 B97 B100 | `<img>` 不能带自定义头 → 图片接口必须走 URL 带 `?dev=`；URL 已含 `?` 再拼参数要用 `&` 不是 `?`；子应用漏配 vite proxy；鉴权文件用 `?token=` | ①凡 `<img>` 加载的图片接口，URL 必须带 `?dev=`（B78）②URL 已含 `?` 时追加参数一律 `&`（B93）③同一 `?dev=` URL 用作 `<img>` 要拼 `&t=` 防缓存（B97）④新增子应用在 vite 代理登记自己前缀（B3） |
| 🔴 | **SQLAlchemy 连接/Row/事务/锁** | **5** | B86 B87 B88 B110 B120 | `with engine.begin()` 块外复用已关闭 conn；`Row` 不能 `row["col"]`；事务块内再 `engine.begin()` 抢写锁（database is locked）；`Column default` 覆盖显式 None | ①`with engine.begin()/connect()` 块结束后 conn 已关闭，块外不可再 execute（B86/B110）②`Row` 列访问用 `r._mapping["col"]`（B87）③同一事务内**复用事务里的 conn**，勿块内再 `engine.begin()`（B120 锁）④需"默认 NULL"的列 default 显式写 `None`（B88） |
| 🔴 | **改后端 .py 后未重启 / 8000 端口旧进程 → 修复无效** | **5** | B54 B57 B93 B104 B122 | 启动方式无 `--reload`，改完不重启跑的是旧代码 → 修复"看似无效"（多因 8000 被旧进程占用）；新增路由不重启同样 404 | ①改完任何后端 `.py` **必须重启后端**②重启前 `Get-NetTCPConnection 8000` 核对进程启动时间**晚于**源码 `LastWriteTime`，否则先结束旧进程③新增路由必须重启④验收用 `Invoke-RestMethod /openapi.json` 核对路由已加载（B122） |
| 🟠 | **导入/导出 Excel** | **5** | B6 B20 B72 B101 | 导出 GET 全量/参数类型错；中文文件名直接写 header（latin-1 爆错）；结果加了新列导出表头没同步；不同场景复用通用表头 | ①导出一律 POST + body + 等待条 + 嵌图（B6）②中文文件名按 RFC 5987 `filename*=UTF-8''` 编码（B20）③后端结果表加列后导出**表头/Excel 列必须同步**（B72/B101）④不同场景用独立表头常量（classify 分开，B101） |
| 🟠 | **i18n 键名/插值未同步** | **4** | B67 B77 B94 B106 | 改了 t() 引用键名但翻译文件没同步 → 显示键名；插值用 `{n}` 而非 `{{n}}` → 显示字面；新功能页漏配 i18n 命名空间 | ①加/改 i18n 键时**同一步**改 zh + en②插值语法用**双大括号** `{{n}}`（B67）③t() 传参键名与翻译键一致（B77）④新增功能页必须同步建 i18n 命名空间（B106）⑤删键前先 grep 确认无引用 |

**次级关注（同样要规避但次数较低）**：浏览器 `alert/confirm` 违反交互约定（B8 B105——提示用 toast、破坏性操作用组件内确认弹窗）；子进程/rich 输出 gbk 编码报错（B52 B54——非 tty `PYTHONIOENCODING=utf-8` + `io.TextIOWrapper` 替换 stdout/stderr）；前端请求必须走统一 `request()` 解包 `{code,msg,data}`（B89，禁止直接 fetch）；显存/模型管理（B74 B75——常驻懒加载单例 + 空闲自动卸载 + GPU 入口检测）；UI 细节（B121——数字 `X && JSX` 当 X=0 会渲染 "0"，须 `!!X`）。

**通用"改一处查四处"自检（防高频坑复现）**：
- 新增/改**按钮/弹窗/表格/输入控件** → 查「风格主题」「i18n」
- 改**删除/清空/清理** → 查「删除落盘残留 + 复用同一清理函数」
- 改**返回图片/文件 URL** → 查「dev/&/代理」
- 改**前端恢复/刷新数据** → 查「从后端恢复 + localStorage 校验」
- 改**后端 .py** → 查「重启 + 端口进程核对」
- 给**导出**加字段 → 查「表头/Excel 列同步」
- 新增**前端 API 调用** → 查「request() + query 参数数字归一化边界」
- 一个请求里**多次写** → 查「复用同一事务 conn」

---

## 一、项目架构速览

```
AIGC Detection/
├── web/                          # FastAPI 后端 + React 前端
│   ├── app.py                    # 主入口：挂载子应用、路由、CORS
│   ├── model_manager.py          # 全局模型管理器（显存调度 + 推理锁）
│   ├── detect.py                 # 图像篡改检测（TruFor 子进程）
│   ├── smart_verify/             # 点位真实性核验（FastAPI 子应用）
│   │   ├── app.py                #   子应用组装
│   │   ├── database.py           #   独立 SQLite（data/smart_verify.db）
│   │   ├── models.py             #   ORM 模型
│   │   ├── services/             #   → 核心算法见 ../../ImageVerifier/
│   │   └── routers/              #   上传 / 配对 / 核验 / 结果 / 导出
│   ├── rs_verify/                # 遥感变化核验（FastAPI 子应用，挂载 /rsverify）
│   │   ├── app.py                #   子应用组装；启动时 _migrate：加列/迁移/默认预设写库
│   │   ├── database.py           #   独立 SQLite（data/rs_verify.db）
│   │   ├── models.py             #   ORM：rs_images(上传图) / rs_records(结果) / rs_users / rs_presets(预设) / rs_models(模型列表) / rs_settings(旧迁移用)
│   │   ├── services/             #   runner(调 web_bridge) / presets(预设 CRUD+AES) / crypto / excel / models
│   │   ├── routers/              #   upload / analyze(含 rerun) / results(删除三连清) / settings(预设+手动刷新本地模型) / export
│   │   └── （算法在 ../../Remote_sensing/，web_bridge.py 子进程调用，算法更新自动跟随）
│   ├── ImageVerifier/            # 核验算法核心库（独立可分发）
│   ├── PointVerifier/            # 核验 CLI（独立运行）
│   └── frontend/                 # React + Vite
│       └── src/
│           ├── i18n/             # 国际化（zh-CN / en）
│           ├── api/              # 按功能分文件（detectApi / smartApi / rsApi / db）
│           ├── components/
│           │   ├── common/       #   App / Home / SystemSettings
│           │   ├── detect/       #   图像篡改检测页
│           │   ├── verify/       #   点位核验页
│           │   └── rsverify/     #   遥感核验页（RsVerify + 设置弹窗）
│           └── theme.js          # 主题持久化与切换
├── Remote_sensing/               # 遥感核验算法（独立可分发 CLI，web 子进程调用）
└── .venv/                        # 项目根虚拟环境
```

---

## 二、新增一个系统（操作模板）

> 目标：新增功能页（如人脸识别）时按此模板执行，不会漏步骤。

### 0. 前置规划（最重要，先想清楚）

- **模型**：占多少显存？常驻（进程内）还是子进程任务型？→ 接入 `model_manager.py`（见第三章），并在 `model_manager.py` 顶部注释的显存估算表中登记
- **存储**：独立 SQLite 文件（`data/<system>.db`）与独立上传/产物目录，**不要**与检测/核验系统混用
- **资源 URL**：接口返回的相对路径统一带自身前缀（如 `/face/api/...`），前端经 vite proxy 转发
- **交互**：提示用 toast、破坏性操作用确认弹窗、耗时操作用进度条
- **必避的坑（新系统最容易踩）**：① 表结构变更要写进启动迁移（`create_all` 不会给已存在表加列）；② 子进程/rich 输出要处理 gbk 编码（非 tty 强制 UTF-8）；③ 图片/文件资源必须走本系统自己的服务接口（不要复用其他子系统的 URL）；④ 所有慢请求（拉模型列表等）不要放高频接口里，用手动按钮+缓存；⑤ 界面文案全部走 i18n，插值用 `{{n}}`；⑥ 验证前先确认 8000 端口没有被旧进程占用

### 1. 后端三步（web/ 下）

#### 1.1 建目录（FastAPI 子应用包）

```
web/<system>/                  # 如 web/face/
├── __init__.py
├── database.py                # 独立 engine → data/<system>.db（参考 smart_verify/database.py）
├── models.py                  # 数据模型（SQLAlchemy）
├── services/                  # 业务/算法（模型懒加载走 model_manager）
├── routers/                   # 接口：upload / verify / results / export...
└── app.py                     # 组装子应用（复制 smart_verify/app.py 结构）
```

#### 1.2 挂载前缀（web/app.py）

```python
from <system>.app import <system>_app
app.mount("/<system>", <system>_app)
```

资源 URL 规则：子应用内路由保留 `/api/*`，实际访问路径为 `/<system>/api/*`；
返回给前端的图片/资源 URL 写成相对路径 `/<system>/api/...`。

#### 1.3 安装依赖

```powershell
# 根目录虚拟环境
.venv\Scripts\python.exe -m pip install <包名>
```

### 2. 前端四步（web/frontend/src/ 下）

#### 2.1 建组件目录

```
src/components/<system>/       # 如 components/face/
├── <System>Verify.jsx         # 主页面
└── ...                         # 子组件
```

#### 2.2 写 API 文件

```
src/api/<system>Api.js         # 复制 smartApi.js 结构，BASE = "/<system>/api"
```

#### 2.3 注册路由 + 首页卡片

在 `App.jsx` 的 `TAB_META` 增加条目；在 `Home.jsx` 的 `FEATURES` 数组增加卡片（含 `i18nKey` / `descKey` / `detailKey`），对应翻译键加入 `src/i18n/zh-CN.json` 和 `en.json`。

#### 2.4 i18n 国际化（必须）

所有界面可见文字必须走 `useTranslation()` + `t()`，禁止硬编码中文。详见第四章。

#### 2.5 vite 代理（web/frontend/vite.config.js）

```js
server: {
  proxy: {
    "/<system>": { target: "http://127.0.0.1:8000", changeOrigin: true },
  },
}
```

### 3. 收尾检查清单

- [ ] `npm run build` 通过
- [ ] 后端启动无报错，`/<system>/api/health` 返回 ok
- [ ] 上传 → 处理 → 导出 全链路通过（含同名幂等查重）
- [ ] 删除操作有确认弹窗、耗时操作有进度/等待条、提示用 toast
- [ ] 所有界面文字已接入 i18n（`t('xxx.yyy')`）
- [ ] 新增的 model_manager 显存估算已登记
- [ ] **数据管理清空接口已同步**：新表/新落盘目录已纳入 admin.py `_TABLES`（或独立 `_CHAT_TABLES` 等）的 `clear_files`/`clear_config`/`clear_all` 三类清空，并核对 `_data_stats` 统计口径（B115 约定）
- [ ] 更新本文档（如有新坑或新规范）

---

## 三、全局基础设施（所有页面共享）

### 3.1 模型管理器（model_manager.py）

单例 `manager`，统一调度多系统的 GPU 显存，避免并发挤爆显存。

```python
from model_manager import manager

# 常驻模型（懒加载单例，超预算自动 LRU 卸载）
def get_model():
    return manager.get("<system>_<model>", loader, est_gb=0.5)

# 推理时加全局串行锁（与检测/核验互斥）
with manager.infer:
    model = get_model()
    result = model.predict(...)

# 子进程任务型（如 TruFor）：任务期间记账
manager.begin_task("<system>", 1.6)
try:
    ...  # 启动子进程推理
finally:
    manager.end_task("<system>", 1.6)
```

显存预算默认 6GB（RTX 4060 8GB），在 `model_manager.py` 构造处调整。
状态查询：`GET /api/models`。

### 3.2 主题系统（theme.js）

- 浅色 / 深色 + 8 色主色色板，全局 CSS 变量（`--c-*`）
- `loadTheme()` / `saveTheme()` / `applyTheme()` → `localStorage` 持久化
- 任何页面样式**禁止写死色值**，一律用 `var(--c-*)` 变量
- 组件样式加功能前缀（如 `.smart-*`、`.detect-*`）

### 3.3 i18n 国际化（src/i18n/）

#### 架构

| 文件 | 说明 |
|------|------|
| `src/i18n/index.js` | i18next 初始化，从 localStorage 恢复语言偏好，默认 `zh-CN` |
| `src/i18n/zh-CN.json` | 中文简体翻译（key = 中文值，便于维护） |
| `src/i18n/en.json` | 英文翻译 |

#### 命名空间规范

按功能/页面分层，命名空间前缀：

| 命名空间 | 对应页面/组件 |
|----------|--------------|
| `common` | 通用（确认/取消/删除/加载中/即将上线） |
| `home` | 首页卡片（标题/描述/详情） |
| `settings` | 系统设置 |
| `detect` | 图像篡改检测 |
| `verify` | 点位真实性核验 |
| `rsverify` | 遥感变化核验（含功能设置弹窗文案） |
| `upload` | 上传面板 |
| `resultTable` | 结果表格 |
| `imageCompare` | 详情弹窗 |

#### 组件中使用

```jsx
import { useTranslation } from 'react-i18next';

export default function MyComponent() {
  const { t } = useTranslation();

  return (
    <div>
      <h1>{t('myPage.title')}</h1>
      <button>{t('common.confirm')}</button>
      <p>{t('myPage.stats', { count: 5 })}</p>  {/* 插值 */}
    </div>
  );
}
```

#### 新增语言

1. 在 `src/i18n/` 下新增 `xx.json`（复制 `en.json` 翻译）
2. 在 `index.js` 的 `resources` 中注册
3. 在 `SystemSettings.jsx` 的 `langOptions` 中增加按钮

### 3.4 全局清理（SystemSettings）

收口在系统设置 → 历史内容清理，各功能模块的统计数据通过以下方式汇总：

- **图像篡改检测**（浏览器 IndexedDB 缓存）：`cacheUsage()` → `{ bytes, items }`
- **点位核验**（后端统计数据）：`smartApi.stats()` → `{ pairs, done, images, bytes }`
- **遥感核验**（后端统计数据）：`rsApi.stats()` → `{ records, bytes }`；清理调 `rsApi.reset()`（后端删 rs_uploads/rs_work 全目录 + 清 rs_verify.db 记录）

各功能页面通过 `window.dispatchEvent` 响应清理事件：
- `"cache-cleared"` → 检测页清空界面
- `"smart-verify-cleared"` → 核验页清空界面
- `"rsverify-cleared"` → 遥感核验页清空界面 + 清 IndexedDB 上传缓存（`rs_upload_cache`）+ 双面板 reset

### 3.5 语言切换（SystemSettings）

语言切换器在系统设置中（外观主题下方），两个按钮切换 `zh-CN` / `en`。
切换后 `i18n.changeLanguage(lang)` 即时生效，同时 `saveLang()` 持久化到 localStorage。

### 3.6 遥感核验子系统（rsverify）关键约定

> 改遥感相关代码前必读。该子系统与 Remote_sensing 强耦合，很多坑跨两侧。

#### 配置链路（web → CLI，必须理解）

```
前端功能设置（数据库 rs_presets 激活预设）→ analyze._llm_config()
  → runner.run_analysis() → RemoteAnalyzer.analyze()
    → 生成临时 config.yaml（web_bridge._write_config，JSON 即 YAML 子集）
    → 子进程 python rs_verify.py <scenario> --before --after --output --json-out --no-excel --config <临时配置>
    → CLI core/analyzer.LLMAnalyzer 调用大模型 → json_out 中转结构化结果
```

- **CLI 与 web 共用同一份 analyzer**（`Remote_sensing/core/analyzer.py`）：修 analyzer（webp 转码、重试、代理等）两边同时生效
- 子进程固定 `--no-excel`：web 结果在前端展示并自行导出，rs_work 只留标注图
- 中转 JSON / 临时配置放系统临时目录、用完即删；不碰 Remote_sensing/config.yaml（web 通过参数覆盖）
- **config.yaml 与 web 设置的关系**：web 预设是"用户配置"（数据库）；本地模型（api=local）参数自动读 config.yaml（地址/Key/超长），前端只填模型名

#### 本地模型（api=local）设计

- 语义：**api=local 也走 openai 通道**，`base_url` 指向本机 Ollama（`http://localhost:11434/v1`），由 `web_bridge._resolve_local_config` 从 config.yaml 读取
- 模型名存预设的**独立字段 `local_model_name`**（与云端 `model_name` 互不干扰，rs_presets 迁移加列）
- 本地模型列表：`GET /rsverify/api/local/models` 手动拉取 Ollama `/v1/models`（前端"从服务器获取模型"按钮触发），**不写数据库**，前端 localStorage 缓存（`rsverify_local_models`）；不要在 get_settings 里实时拉取（会拖慢设置页 2s+）
- 8GB 显存甜点位：`qwen2.5vl:7b`（Q4 ~5GB，稳定）；`qwen3-vl:4b` 空响应率 50-70%，不可用（B60/B61/B70）

#### 失败处理策略（两侧不一致，留意）

- **CLI 批量（run.py）**：失败写 Excel"识别失败"行（`reporter.add_failed`）+ 终端失败清单；`_call_llm` 默认**不重试**（retries=0）
- **web 端**：失败 → 子进程 exit 1 → 502 → 前端 toast"核验失败" + **不落库**（结果表/导出都没有失败行）+ 清理本次上传图与 work_dir

#### 其他约定

- run.py 批量抽样用 `RANDOM_SEED` 固定（换模型对比同一批识别差异）；Windows 目录名不能含 `:`（WinError 123），OUTPUT_DIR 按模型名分目录时冒号换 `-`
- 图片发 LLM：webp 一律转 JPEG（Ollama 无法解码 webp base64）；httpx 客户端 `trust_env=False`（系统 HTTP_PROXY 会拦截 localhost）
- 删除记录"三连清"：DB 记录 + 标注图/CLI 工作目录 + 不再被引用的上传图（`results.py`）

---

## 四、前端开发规范（避免重复踩坑）

### 4.1 交互约定

| 场景 | 方式 | 说明 |
|------|------|------|
| 成功/信息提示 | 组件内 toast | 3 秒自动消失，success/error/warn 三态 |
| 破坏性操作确认 | 组件内 confirm 弹窗 | 删除/清空等不可逆操作 |
| 耗时操作 | loading 态 + 进度条 | 导出/批量核验等 |
| 禁止 | 浏览器 `alert`/`confirm` | 永远不用 |

### 4.2 父子组件联动

- 子组件状态变化必须通过回调上报（`onXxxChanged`），父组件用 state 驱动 UI
- **禁止用 ref 读子组件状态计算父组件按钮可用态**（ref 不触发重渲染）
- 状态上报统一放 `useEffect`（避免 setState-in-render 警告）

### 4.3 HTML5 拖拽排序

缺一不可三要素：
1. `draggable` 属性设置
2. `dragstart` 中 `e.dataTransfer.setData(...)`（部分浏览器不设置则不进入拖拽）
3. `dragover` 中 `e.preventDefault()`（不阻止默认则 drop 不触发）

### 4.4 列表组件

- 缩略图列（hover 放大用**固定中央预览**，不要撑出滚动条；滚动条统一装饰）
- 行级勾选：**仅双击行切换**（再次双击取消），双击范围排除勾选列与操作列；勾选列复选框可直接点击（真实 `onChange` 驱动，不用 `readOnly`+冒泡，避免双击时 click×2+dblclick 三连 toggle 状态错乱）
- 列表禁用文本复制：`.smart-table` 加 `user-select:none`（防双击误触复制，影响勾选判断）
- 状态标签（多态颜色，用 `--c-*` 变量）
- 空态提示（如"暂无配对（先上传图片并生成配对）"）
- 批量操作入口（未勾选时默认"全部"，有勾选时"选中 N"）
- 顺序匹配模式上传列表支持**拖拽排序**；选择比对模式多选时显示**点击顺序编号徽标**（1,2,3...），按编号顺序一一配对

### 4.5 异步操作

- 所有耗时操作（导出/批量处理）提供 loading 态或进度条
- 文件导出用 POST（便于带选择条件）
- 按钮防重复点击（`disabled={busy}` + "处理中..."文案）

### 4.6 幂等与查重

- 上传/提交前必须查重（同名文件、已配对）
- 结果类操作前检查状态（未完成项跳过并说明原因）
- 幂等查重前后端双保险——前端拦截同名输入，后端兜底

### 4.7 i18n

- 所有界面可见文字走 `t()`，禁硬编码
- 变量文本用插值：`t('key', { n, msg })`；**插值语法是双大括号 `{{n}}`**，写 `{n}` 会原样显示
- 新功能页同步添加 `zh-CN.json` + `en.json` 翻译键（JSON 字符串里的引号要转义，文案尽量不带英文引号）

### 4.8 高频避坑速查（症状 → 根因 → 解法）

> 按"先现象、再排查"组织，改代码前先过一遍；命中的大多在第五章有对应 B 编号详情。

| 症状 | 根因 | 解法 |
|------|------|------|
| 改了代码但行为没变 | **8000 端口被旧后端进程占用**（最常踩的坑） | `Get-NetTCPConnection -LocalPort 8000` 找占用进程 taskkill 后重启（start.ps1 会自动清理）；前后端都要确认是新代码 |
| 设置页/保存卡"加载中"几秒 | 后端接口里实时请求慢服务（如 Ollama `/v1/models`） | 慢请求改手动按钮触发 + 前端缓存；不要放在 get_settings 等高频接口（B64） |
| 子进程报 UnicodeEncodeError（gbk 无法编码 ▶/✓） | rich 输出在 Windows gbk 控制台 | 子进程入口非 tty 时强制 UTF-8（`io.TextIOWrapper`，在 import rich 前）；web_bridge 子进程 env 加 `PYTHONIOENCODING=utf-8`（B52/B54） |
| 本地 Ollama 报 400 "Failed to load image or audio file" | webp base64 后端无法解码 | `_encode_image` 对 webp 一律转 JPEG（B59） |
| 本地 Ollama/内网 API 连接超时/崩溃 | 环境变量 HTTP_PROXY 拦截 localhost | httpx 客户端 `trust_env=False` |
| 图片 hover 放大时页面闪烁 | img 本体 `position:fixed` 触发 hover 循环 | 独立预览层 `.thumb-zoom` + CSS 变量 `::after`（B56） |
| 列表复制/双击勾选冲突 | 双击选中文字触发复制 | 列表 `user-select:none`；行级勾选仅双击（排除勾选列/操作列）（B41/B42） |
| 数字输入框调节按钮 hover 全白 | 浏览器原生 spinner 暗色主题未适配 | CSS 隐藏 `-webkit-inner/outer-spin-button`（B68） |
| 本地模型名和云端模型名串了 | 共用预设 model_name 字段 | 用独立字段 `local_model_name`（B63） |
| 新表加列后查询报"no such column" | SQLAlchemy `create_all` 不给已存在表加列 | app.py `_migrate` 显式 `ALTER TABLE ... ADD COLUMN`（幂等判断列是否存在） |
| 数据库越堆越多/清不干净 | 删除记录只删 DB 行、文件残留 | 删除"三连清"：DB 记录 + 标注图/工作目录 + 孤儿上传图；清空全部时 rmtree 重建目录（B57） |
| 批量抽样的对每次不一样，无法对比模型 | 抽样无种子 | `random.seed(RANDOM_SEED)`（run.py 配置区，B71） |
| Windows 目录/文件名含 `:` 等报 WinError 123 | 模型名带冒号直接拼路径 | 目录名里冒号换 `-`；创建目录加友好 try/except（B71） |
| 上传图片核验后预览图消失 | 图片 URL 服务串用（smart 的接口给遥感用） | 各子系统自己的图片服务 + `imageUrlFn`（B58） |
| 导出 Excel 中文文件名 500 | header 直接写中文抛 latin-1 编码错 | `filename*=UTF-8''{quote(name)}`（B20） |
| 下拉/开关联动状态残留 | 切换模式未清 state | 用 effect 监听模式变化清空相关 state（B50） |
| 验证码一直打印"SMTP 未配置"、收不到邮件 | SMTP 只配了 User 级环境变量，后端由 IDE/已运行程序派生的终端启动 → 读不到新环境变量（环境变量不跨已运行进程继承） | 配置写入 `web/.env`（auth.py `_load_env_file` 启动自动读取，进程环境变量优先），任何方式启动都生效；`.env` 含授权码勿提交仓库 |

---

## 五、历史 Bug 记录（按模块）

### 5.1 点位核验（verify）

| 编号 | 问题 | 根因 | 修复 |
|------|------|------|------|
| B1 | 上传后按钮响应慢 | ref 读子组件状态不触发重渲染 | 改为 `onFilesChanged` 回调 + state |
| B2 | 拖拽排序失效 | `dragover` 未 `preventDefault` + `<img>` 抢占事件 | 三要素修复 |
| B3 | 详情弹窗图片/Canvas 不显示 | 资源 URL 无代理 → 404 | vite proxy `/smart` |
| B4 | 人工复核结果不同步列表 | 列表判定逻辑未处理 `human_judgment` | 多级判定优先级 |
| B5 | 刷新结果无反馈 | 无 loading + toast | 加态 + 提示 |
| B6 | 导出传参 422 / 无等待条 / 无图 | GET 全量 + 参数类型错误 | POST + body + 嵌图 + 进度 |
| B7 | 重复上传/配对 | 无查重逻辑 | 文件名查重 + 确认删旧 |
| B8 | 浏览器 alert | 未用组件 toast | 统一 toast + 确认弹窗 |
| B9 | 列表无缩略图 | 未实现 | 加图片列 + 双击勾选 |
| B13 | 重复配对确认后未删旧 | `deleteOld` 逻辑丢失 | 确认回调中真实执行删旧→重建 |
| B14 | 单击勾选框无效 | `stopPropagation` 阻断冒泡 | 去掉阻断 |
| B15 | 人工修正/复核重复 | 两个卡片功能重叠 | 合并为一个人工修正卡片 |
| B16 | 未勾选无法批量删除 | 按钮禁用 | 无选中=全部，加确认弹窗 |
| B17 | 核验按钮不醒目/重复 | 两个按钮并存 | 合并为一个橙色按钮 |

### 5.2 全局 / 系统设置

| 编号 | 问题 | 根因 | 修复 |
|------|------|------|------|
| B10 | 清理未覆盖核验数据 | 入口分散 | 收口到系统设置 + 事件联动 |
| B12 | setState-in-render 警告 | updater 内调副作用 | 移到 useEffect |
| B18 | 核验数据单独删除按钮 | 与全局清理并存 | 移除单独按钮，统一入口 |
| B19 | 上传面板缺清空 | 未实现 | 加清空/清除选中按钮 |
| B77 | 系统设置"图像篡改检测"占用显示字面 `{{results}}`/`{{uploads}}` | 文案键名改 `{{results}}`/`{{uploads}}`，但 `t('settings.cacheUsage', {...})` 仍传 `items`，键名不匹配 → i18next 找不到值保留字面（`{{mb}}` 匹配所以正常） | SystemSettings.jsx 插值改传 `results`/`uploads`；usage 初始 state 同步为 `{bytes, results, uploads}` |
| B78 | 设备隔离后图片缩略图 404（图像篡改上传后缩略图消失；点位/遥感图片同理） | B76 后图片接口按 `X-Device-Id` header 过滤，但浏览器 `<img>` 直接加载图片 URL **无法携带自定义请求头** → device_id 为空串查不到记录 → 404 | 图片 URL 携带 `?dev={device_id}`：后端图片接口 `request.query_params.get("dev") or get_device_id(request)` 优先取 query；detect 后端生成 URL 拼 dev；前端 `smartApi.imageUrl/visUrl`、`rsApi.imageUrl/uploadImageUrl` 拼 dev。**约定：凡 `<img>` 加载的图片接口，URL 必须带 dev 参数** |
| B79 | 删除上传/结果后残留空设备文件夹（`detect_uploads/<device_id>/` 等） | `api_uploads_delete`/`api_result_delete` 只删文件与 DB 记录，不清理空目录 | 新增 `_rmdir_if_empty`（目录为空则 `os.rmdir`），两个删除接口调用；清理逻辑同 `_save_b64` 风格局部封装 |
| B80 | 遥感上传面板显示浏览器历史缓存的旧文件（还没上传却有文件） | B76 统一后端存储后，上传面板仍用旧的 IndexedDB 草稿缓存（`rs_upload_cache`，Blob 存本地，刷新恢复）且未按设备隔离 | 移除 IndexedDB 草稿缓存（RsVerify.jsx 删 rsCache* 系列 + 面板 onLocalCache/onLocalDelete），改为与点位核验一致：后端新增 `GET /rsverify/api/images/list`（当前设备已上传图片）+ `rsApi.getUploadedImages()`，页面加载 `restoreImages` 从后端恢复；清空面板只删后端。**体验变化：未上传的本地草稿刷新不再保留** |
| B82 | 图像篡改上传列表：选中行识别后状态始终显示"待检测"；已检测文件刷新后又被当作待检测重复检测；上传相同文件名图片产生重复记录 | 前端恢复上传列表时硬编码 `status: "待检测"`（`done` 状态未从后端恢复）；`POST /api/detect/upload` 无同名幂等 | 后端 `GET /api/detect/uploads` 计算 `done` 标记（查本设备 detect_records.file 集合，文件名命中即已检测）；前端恢复时 `status: it.done ? "完成" : "待检测"`（startDetect 只挑"待检测/失败"，已完成自动跳过）；上传接口按 (device_id, filename) 查重，已存在直接返回已有记录不重复落盘 |
| B83 | 图像篡改上传列表仍可无限添加同名文件（B82 后端幂等后：重复上传返回已有 id，但前端 `setUploads` 直接 append 不去重，列表中重复显示） | 前端 `addUploads` 合并列表时未按 id 去重 | `addUploads` 先按当前列表 id 集合过滤后端返回项（重复的跳过），updater 内再按 id 兜底去重；有重复时**右下角 toast** 提示 `detect.dupSkipped`（组件内轻提示 3s 自动消失，不用浏览器 alert 打断） |
| B84 | 上传列表表头勾选框显示浏览器默认蓝白色（未同步主题） | 全局 checkbox 装饰只覆盖了数据行 `.detect .check-cell` 与结果表表头 `.detect .result-table th`，漏了上传列表表头 `.detect .upload-table th` | index.css 补 `.detect .upload-table th input[type="checkbox"]`（17px + `accent-color: var(--c-primary)`），与结果表表头一致 |
| B85 | 统一响应格式中间件不生效（所有 JSON 响应未被包装成 {code,msg,data}） | 用 Starlette `BaseHTTPMiddleware` 实现包装，但**新版 Starlette 会把下游响应包装成内部 `_StreamingResponse`**（继承 StreamingResponse）→ `isinstance(response, StreamingResponse)` 全部误判为流式直接跳过，且 `.body` 属性不存在 | 改用**纯 ASGI 中间件**（send 拦截：按 content-type 判断，application/json 响应缓冲后包装为 {code:0,msg,data}，非 JSON 的流式/图片/下载透传；包装时过滤 content-type/content-length 头防重复）；另注册 404（StarletteHTTPException）与未捕获 500 的异常 handler 统一包装，避免 404 被当成功返回 |
| B86 | 注册接口 500（`sqlalchemy.exc.ResourceClosedError: This Connection is closed`） | `with engine.begin() as conn:` 块结束后 conn 已自动关闭，块外仍 `conn.execute(...)` 查刚插入的 row | row 查询移入 `with engine.begin()` 块内（`ins.lastrowid` 后紧跟 SELECT 该行） |
| B87 | 注册/登录接口 500（`TypeError: tuple indices must be integers or slices, not str`） | SQLAlchemy Core 2.0 `Row` 不支持字符串索引 `row["col"]`（须 `row._mapping["col"]`），auth.py 新增代码多处直接 `user["id"]`/`user["password_hash"]` | 新增 `_row_dict()` 辅助（`dict(u._mapping)`，兼容已传 dict），`_public_user`/`_issue_token_for`/`_get_current_user`/api_login/api_login_email/api_forgot 统一先转 dict 再索引；`_check_lock`/`_record_login_fail` 同步改 dict 访问 |
| B88 | 游客 rs 预设被写入 user_id=1（应 NULL；导致迁移检查残留、登录后误归属） | rs_verify/models.py `user_id = Column(Integer, default=1)`：SQLAlchemy 对**显式传 None 也应用 Python 端 default** → 游客 `Preset(user_id=None, ...)` 落库变成 1 | models.py rs_presets/rs_models 两处 `user_id` default 改 `None`；`_migrate` 启动时 `UPDATE rs_presets/rs_models SET user_id=NULL WHERE user_id=1` 清理存量（幂等） |
| B89 | 批次5 三处前端功能失效：①个人资料"数据导出"统计数字不显示 ②功能开关关闭后游客标签未隐藏/首页可打开 ③登录用户公告横幅不显示 | ① 后端 `export._stats` 返回嵌套 `{表名:{count,bytes}}`，前端按平铺 `r.s.count` 取 → undefined ②③ App.jsx 用原生 `fetch` 拉 `/api/features`、`/api/announcements`，未走统一 `request()` 解包 `{code,msg,data}` → 拿到的是整体对象，`features['detect']` 恒 undefined、`d.items` 恒空 | ① Profile.jsx ExportSection 增加 `sum()` 把嵌套表聚合为单系统 {count,bytes} ②③ App.jsx 改用统一 `request()`（自动解包 data）。**约定：前端所有后端请求必须走 `request()`（自动解包），不要直接 fetch** |
| B90 | 批次5.2 前端装饰遗漏三处：①操作日志时间筛选用原生 `<input type=datetime-local>`，弹出的日历面板纯白、无圆角阴影、不随主题（浏览器 shadow DOM 无法 CSS 定制）②日志表格窄屏时溢出范围框 ③分页"页码"输入框纯白无边框圆角（`.admin-jump` 未设背景/边框） | ① 原生 datetime-local 面板由浏览器渲染，无法定制 ② `.admin-table` 无横向滚动容器 ③ `.admin-jump` 只设了尺寸没设背景/边框 | ① 新增自定义 `DateTimePicker.jsx`（月历弹层 + 时/分 select + 清空，弹层用 `--c-*`/`border-radius`/`--shadow-*` 全主题化；已替换操作日志 from/to）② 管理页三张表格套 `.admin-table-scroll`（`overflow-x:auto` + 表 `min-width:720px`）③ `.admin-jump` 补背景/边框/圆角/focus，下拉 select 补 `color-scheme` 明暗。**约定（前端装饰规范）：任何新增按钮/弹窗/表格/输入控件都必须走 `--c-*` 主题变量 + 圆角 + 阴影 + 明暗（color-scheme），原生控件（date/datetime/time/select 弹出面板）无法定制的一律自实现组件，禁止裸用** |
| B91 | 操作日志中普通用户登录/注册的"操作者"显示为 device_id（如 `31dc746d-...`）而非用户名 | 登录/注册/忘记密码请求发生在认证**之前**，请求尚未携带有效 `Authorization: Bearer <token>`，`log_operation` 经 `get_user_id()` 解析不到 user_id 后回退到 `get_device_id()`（游客语义），把 device_id 记为操作者 | `log_operation` 增加 `operator_username` 参数，优先级：有效 token 解析到的用户名 > 显式传入的用户名 > device_id；auth.py 在 register/login/login_email/forgot 四处认证前动作显式传 `operator_username`；历史旧记录不自动回填（如需可一次性 SQL 按 target 里 `user#N:username` 回填） |

### 5.3 遥感变化核验（rsverify）

| 编号 | 问题 | 根因 | 修复 |
|------|------|------|------|
| B20 | 导出 Excel 500 | `Content-Disposition` 直接写中文文件名，latin-1 编码 header 抛 UnicodeEncodeError | 按 RFC 5987 `filename*=UTF-8''{quote(name)}` 编码 |
| B21 | 表格内删除按钮误触批量删除 | 单行删除复用了批量删除 handler（选中集为空=删除全部） | 拆分独立 `handleDeleteOne`（调 DELETE /results/{id}） |
| B22 | 设置弹窗表单被重置（模型列表/Key 丢失） | 加载 effect 依赖父组件内联 `onNotify/onClose`，fetch 成功后父组件重渲染 → effect 重跑 getSettings 覆盖表单 | effect 改为仅挂载执行一次（`[]` + eslint-disable） |
| B23 | 预设模型用模型名作按钮文本、Qwen URL 错误 | 预设常量设计不当 | 预设按钮改公司名（DeepSeek/Qwen/ChatGPT/自定义），Qwen 用实际 MaaS URL；点击预设填充、自定义清空 |
| B24 | 设置无配置状态回显 | 未实现 | 弹窗顶部加"当前配置状态"只读行（API 类型·模型·主机） |
| B25 | 模型名称无法快速选择 | 仅手写输入 | 增加"从 API 获取模型"（后端代理 `GET {base_url}/models`）+ datalist 下拉 + "全部模型"浏览面板；模型持久化到 `rs_models` 表（新增补入、过时删除，全局共享）；并入 Remote_sensing `COMMON_MODELS` 静态兜底 |
| B29 | 平台 key 串台 | 切换预设保留全局 key，未配置平台显示他人 key | 预设平台重构为数据库存储（rs_presets）：各预设独立保存参数与 key、点击激活切换、核验用激活预设；删除旧 localStorage 记忆方案 |
| B30 | 预设写死代码 | PRESETS 常量写死 | 预设按钮/参数全部从数据库读取；"自定义"改为"添加模型"表单（名称+参数入库） |
| B31 | 模型列表混用（DS 显示 Qwen 模型） | rs_models 全局一张表 | 模型按 base_url 隔离（(name,base_url) 联合唯一），各平台只显示自己获取的模型 |
| B32 | 全部模型面板装不下/重叠 | 面板无固定高度、列表未限高 | 面板固定 height:min(70vh,540px) + flex 布局，列表 flex:1 + overflow-y:auto |
| B33 | 模型下拉重复（key 警告/计数+1） | 合并当前模型名与列表时未去重 | loadSettings/selectPreset/fetchModels 三处统一 `new Set` 去重；搜索框 flex:none 防拉伸 |
| B34 | 预设全局共享，无用户维度 | 预设表无 user_id | 新增 rs_users（游客 id=1）+ rs_presets/rs_models 加 user_id；所有接口按当前用户隔离（预留登录）；analyze 用当前用户激活预设 |
| B35 | 预设需手动添加、易重复 | 无默认预设/无查重 | 内置默认预设（DeepSeek/Qwen/ChatGPT）启动写库（按 name 查重）；添加同名预设后端 400 拦截；reconcile 合并旧迁移重复预设 |
| B36 | 本地/云端切换不完整 | 本地模式仍显示部分表单 | API 类型切换置顶：本地模式仅提示无内容；云端模式显示预设区+配置表单（保存/重置） |
| B37 | 多预设撑爆弹窗 | 预设区无高度限制 | .rs-preset-scroll max-height:132px + overflow-y:auto，超出滚轮查看 |
| B26 | 本地模型模式显示配置输入 | 本地配置应由服务器写死 | 移除 local_model_path/local_device 前端编辑，仅显示提示；保存不提交该字段 |
| B27 | 模型接口获取失败时无提示 | 未处理 | toast 提示错误（401 未提供 key 等） |
| B28 | 遥感核验 CLI 缺 typer 依赖 | 项目根 .venv 未安装 Remote_sensing 依赖 | 安装 `typer`（openai/PIL/openpyxl/yaml/rich 已具备） |
| B38 | 全局清理没清掉遥感数据 | SystemSettings 未接入 rs_verify | 新增 `rsApi.stats()/reset()` + 系统设置"遥感变化核验"统计区 + `rsverify-cleared` 事件联动页面清空（含 IndexedDB 上传缓存） |
| B39 | rs_work 落盘 results.xlsx / _rs_web_result.json | CLI 默认写 Excel + 中转 JSON 放工作目录 | CLI 加 `--no-excel`（web 桥接固定传参）；中转 JSON/临时配置改放系统临时目录、读取后即删；rs_work 仅保留标注图（web 前端展示用），web 结果在前端展示并自行导出 |
| B40 | 结果列表 hover 图片放大撑出滚动条且滚动条无装饰 | hover 放大为行内绝对定位，超出表格 | hover 预览改为 `position:fixed` 固定中央（不撑滚动条）；滚动条统一装饰（webkit 滚动条样式） |
| B41 | 结果列表勾选框无法勾选 | 勾选列靠行 onClick 冒泡 + readOnly 复选框；双击时 click×2+dblclick 三连 toggle 状态错乱 | 行级仅保留双击勾选（排除勾选列/操作列），复选框改真实 `onChange`；上传列表同步（去掉缩略图/文件名单击 toggle，双击项勾选、排除勾选框列与删除列） |
| B42 | 结果列表复制文本误触双击判断 | 双击选中文字触发复制 | `.smart-table` 加 `user-select:none` |
| B43 | 场景列"新增构筑物检测"换行 | 列宽不足 | `.rs-table .cell-scenario { white-space: nowrap }` + 加宽列 |
| B44 | 遥感无批量能力 | 仅单对分析 | 双面板上传 + 顺序匹配/选择比对（多选编号 1,2,3 按编号配对）+ 批量逐对核验循环 + 进度条 + 开始按钮自动变"核验选中 (N)" + 无匹配禁用；上传列表 IndexedDB 缓存刷新不丢 |
| B45 | 上传列表顺序编号徽标显示在图片上遮挡缩略图 | `.thumb-order` 绝对定位在图片容器右上角 | 编号徽标移到勾选框前（`flex-shrink:0` 行内徽标），移除图片容器 `position:relative` |
| B46 | 功能设置点击保存后取消/重置/保存三按钮闪烁 | `save()` 成功后调用 `loadSettings()` 重建 form 对象，整窗重渲染 | 保存成功改为轻量刷新：仅更新 presets/activeId/commonModels/modelOptions，保留当前表单值 |
| B47 | 遥感页上传面板"清空/清除选中"无效、"已选 N 张"常驻显示（未勾选也显示） | 遥感页未传 `onClearFiles`（面板文件全为本地）导致清空无操作；计数恒用文件总数 | `handleClear` 支持父组件未接管时本地直接清理（revoke blob + onLocalDelete + 移除）；面板头部按模式区分：选择比对且有勾选时显示"清除选中/已选 N"，否则显示"清空/共 N 张"（新增 `upload.total` 文案） |
| B48 | 未配置 Key 的预设也能进入检测流程，全失败仍显示"完成（0 对）" | doAnalyze 无配置校验；结束 toast 恒为 success | 开始前 `getSettings()` 校验激活预设（云端模式要求 base_url/model_name/api_key 非空，缺失即 error 提示并中止）；全对失败时改 error 提示"全部未完成，请检查模型配置或网络" |
| B49 | 系统设置一键清理后核验统计显示"无（后端未连接或为空）"，再次进入恢复 | clearAll 里 `setVerify(null)/setRs(null)` 置空导致误导显示 | 清理后不再置 null，改为重新 `refreshVerifyStats()/refreshRsStats()` 拉取（清空后应为 0 条） |
| B50 | 选择比对勾选后切回顺序匹配，高亮/编号残留 | 切换模式未清除 selected/selOrder | UploadPanel 用 effect 监听 `showCheckbox`：变 false 时清空全部选中/编号状态 |
| B51 | 上传列表拖动文件时窗口抖动 | drop-line 占位 div（`margin:2px 0`）随拖拽插入/移除改变布局高度 | drop-line 改绝对定位（`position:absolute` + `.before`/`.after` 定位到项顶部/底部），不占文档流 |
| B52 | 遥感核验报 UnicodeEncodeError（gbk 无法编码 '▶'） | rich 输出 ▶/✓ 时子进程 stdout 为 Windows gbk 控制台编码 | web_bridge 子进程 `env` 注入 `PYTHONIOENCODING=utf-8`，rich 输出可正常捕获解析 |
| B53 | 顺序匹配页核验按钮也显示"核验选中"；重复点击核验重复落盘 | 按钮文案恒用 selectedPairCount 判断；doAnalyze 每对都重新 upload+analyze | 按钮文案仅选择比对模式显示"核验选中 (N)"，顺序匹配固定"开始核验"；doAnalyze 按 (scenario+前后文件名) 跳过已核验对；新增 `POST /analyze/{record_id}/rerun` 重新核验接口（用原图重分析并覆盖记录、清理旧产物目录）+ 结果表操作列"重新核验"按钮；上传面板本身已有同名查重 |
| B54 | rich 输出 gbk 编码报错（'▶' 无法编码）持续出现 | 仅设子进程 `PYTHONIOENCODING` 不够；且 8000 端口被旧进程占用导致新代码未生效 | rs_verify.py 非交互场景强制 UTF-8（`io.TextIOWrapper` 替换 stdout/stderr，在 import rich 前）；排查遗留 python 进程并重启后端使修复生效 |
| B55 | 核验失败也落盘 rs_uploads（上传图）与 rs_work | 上传成功但 analyze 失败时未清理；_run_analysis 失败未删工作目录 | 前端 analyze 失败时调用新增 `DELETE /images/{id}` 清理本次已上传图片（后端校验未被记录引用才可删）；后端 _run_analysis 分析失败/异常时删除本次 work_dir |
| B56 | 结果表缩略图 hover 时页面持续闪烁（闪现放大图） | `.thumb-cell img:hover` 把 img 本体 `position:fixed` 到屏幕中央，鼠标离开原位置触发 hover 解除 → img 归位再触发 → 无限闪烁 | 改为独立预览层：img 包 `.thumb-zoom`（inline-block 不动），hover 时 `::after` 用 CSS 变量 `--zoom-src` 固定屏幕中央显示放大图；遥感/点位核验结果表同步改造 |
| B57 | 清空结果/清空上传列表后 rs_uploads、rs_work 文件夹未真正清除 | 删除记录仅删标注图，上传图片文件保留（原设计"可复用"）；面板清空只清本地缓存；且 8000 端口曾被旧后端进程占用导致修复代码未生效 | 后端：删除记录时 `_remove_orphan_upload_image` 清理不再被引用的上传图片；batch-delete ids 空（清空全部）时整体 rmtree 重建 rs_uploads/rs_work 并清空 rs_images；前端：上传成功后回写面板图片 id，清空面板时调用 DELETE /images/{id} 删除服务器文件 + 清 IndexedDB 缓存；排查遗留后端进程并重启 |
| B58 | 遥感页上传图片开始核验后预览图消失（结果正常） | 上一轮回写面板图片 id 时，共享 UploadPanel 的 markUploaded 用默认 `smartApi.imageUrl`（/smart/api/images/{id}）作缩略图 URL，遥感图片在该服务 404 | 新增后端 `GET /rsverify/api/uploads/{image_id}` 返回上传原图；遥感页给 UploadPanel 传 `imageUrlFn={rsApi.uploadImageUrl}`，核验后缩略图切到遥感自身的上传原图服务 |
| B59 | 本地 Ollama（qwen3-vl 等）调用报 400 "Failed to load image or audio file" | `_encode_image` 对小图（<150KB）原样发送 webp base64，Ollama/llama.cpp 后端无法解码 webp | `_encode_image` 改为 webp 一律转 JPEG（其余小图仍原样发送），CLI 与 web 共用此函数同时生效 |
| B60 | 本地 4B 模型批量核验时大量"JSON 解析失败"（空响应，实测 50% 失败率） | qwen3-vl:4b 对复杂遥感 prompt 生成不稳定，偶发返回空内容；_call_llm 无重试 | `_call_llm` 加失败自动重试（默认 1 次、间隔 3s，解析失败才重试）；失败原因细分（空响应/输出不完整）；失败对写入 Excel"识别失败"行 + 批量结束打印失败清单 |
| B61 | 换 qwen2.5vl:7b 后批量 10/10 全部成功 | qwen3-vl:4b 空响应率 50-70%（多批次验证），4B 视觉模型对该任务不可用 | 8GB 显存甜点位为 Q4 量化 7B 视觉模型（qwen2.5vl:7b ~5GB），成熟稳定，置信度 0.95、reasoning 清晰 |
| B62 | API 类型"本地模型（预留）"不可用 | 本地模式仅有提示，无真实配置 | 本地模型改为真实可用：web_bridge `_resolve_local_config` 在 api=local 时从 Remote_sensing/config.yaml 读取 base_url/api_key/max_tokens/temperature（与 CLI 一致），前端只填模型名即可切换（走 OpenAI 兼容通道连本机 Ollama）；移除预设平台里的"Ollama 本地"预设方案 |
| B63 | 本地模型名与云端模型名绑一起（切换 API 类型时两页内容一致更新） | 两者共用预设的 model_name 字段 | rs_presets 新增独立 `local_model_name` 字段（app.py 启动自动 ALTER 加列），本地/云端模型名各自独立保存、互不影响；web_bridge 本地解析改读 local_model_name |
| B64 | 打开功能设置/点击保存都要等约 2s"加载中" | get_settings 每次实时请求 Ollama `/v1/models`（跑模型时响应慢），打开与保存后刷新都会触发 | get_settings 不再拉取本地模型；新增 `GET /rsverify/api/local/models` 手动刷新接口（超时 2s，失败兜底 config 默认模型名）；前端"从服务器获取模型"按钮点击才加载 |
| B65 | 本地模型下拉展开状态无圆角/阴影 | 用原生 select，展开列表由浏览器渲染无法美化 | 自定义 LocalModelDropdown 组件（复用全局 .smart-dropdown 样式：圆角阴影、fixed 定位、点击外部/滚动关闭、选中高亮、空列表可点击触发获取），主设置面板与"添加模型"表单共用 |
| B66 | 获取的本地模型列表刷新页面后消失 | 列表只存组件 state | localStorage 缓存（`rsverify_local_models`），刷新/重开设置直接显示；点"从服务器获取模型"可强制刷新覆盖缓存 |
| B67 | 文案插值显示字面 "{n}" 未替换 | i18next 插值语法为双大括号 `{{n}}`，新键误用单括号 `{n}` | 新增翻译键统一用 `{{n}}`（localModelCount 等） |
| B68 | max_tokens/temperature 数字输入框原生调节按钮 hover 全白 | 浏览器默认 spinner 样式在暗色主题下破坏统一风格 | CSS 隐藏 number 原生调节按钮（`-webkit-inner/outer-spin-button` + `-moz-appearance:textfield`），手动输入 |
| B69 | 本地模型获取成功 toast 误显示"已同步到数据库" | 误复用云端 fetchModelsDone 文案；实际本地模型列表不落库（仅内存展示） | 本地获取成功不再弹 toast（数量显示在下拉下方），失败保留 error 提示；明确本地模型列表不写数据库、无越堆越多问题 |
| B70 | 本地 4B 模型失败重试浪费时间（重试也失败） | B60 设置的重试对不稳定模型无效，且用户无感知 | `_call_llm` 默认重试次数 1→0（取消重试）：空响应/解析失败直接返回，CLI 记入 Excel 失败行并继续下一对；web 端失败即 toast + 不落库 |
| B71 | 批量检测每次随机抽对不一致，无法对比模型差异 | run.py 批量抽样无种子 | run.py 配置区新增 `RANDOM_SEED`（None=随机；填数字则每次抽到的对固定，便于换模型对比同一批识别差异）；另外修复 OUTPUT_DIR 含冒号导致 WinError 123（Windows 目录名非法），目录创建加友好提示 |
| B72 | 结果不知道是哪 个模型识别的 | 结果未记录模型名 | web：rs_records 新增 `model_used` 列（启动自动迁移），analyze/rerun 写入（CLI json_out 带回实际模型名 `model`，兜底按 api 取 local_model_name/model_name），结果表新增"使用模型"列 + 导出 Excel 新增"模型"列；CLI：reporter.py 的 COLUMNS 加"模型"列（add_result/add_failed 传 model_name），rs_verify.py / run.py 从 config.yaml 取模型名写入每条结果 |
| B73 | 上传两侧图片放反，需手动逐个调整 | 双面板无一键互换 | 双栏间隙加大，中间放圆形交换按钮：UploadPanel 暴露 `replaceFiles(list)`；点击时两侧文件互换 + 动画（按钮旋转 180°，两面板先向对方滑出淡出、换完数据后滑回淡入，CSS transition .25s） |
| B74 | 点位核验跑一次后 GPU 显存常驻 3.2GB | SuperPoint+LightGlue 经 model_manager 懒加载单例"常驻复用"，仅超预算才 LRU 卸载；占用远低于 6GB 预算 → 永不卸载，直到 web 进程退出 | model_manager 新增**空闲自动卸载**（后台守护线程 + `get(..., idle_timeout)`，默认 0=常驻兼容旧调用）；点位核验模型：核验**完成即卸载**（单对/批量/选中三个端点在 `manager.infer` 锁内结束后 `manager.unload`，批量跑完再卸、不逐对重载；下次核验自动重新加载）+ 60s 空闲兜底；`_release_gpu` 增强（extractor/matcher 子对象 to cpu + del + gc + empty_cache）；TruFor 为子进程型任务本就跑完即释放 |
| B75 | 显存切换过快叠加易爆显存；且无法得知当前 GPU 占用 | 无 GPU 占用检测接口与任务入口防护；点位核验/检测/Ollama 占用叠加无感知 | model_manager 新增 `gpu_memory()`（nvidia-smi 解析、回退 torch）与 `gpu_free_too_low()`（可用 <1.5GB 返回阻止文案）；检测 / 点位核验（单对/批量/选中） / 遥感核验入口检查，显存不足抛 507 阻止并提示"稍等约 1 分钟（模型空闲自动释放）"；`GET /api/models` 返回实际 GPU 显存（含外部进程如 Ollama）；系统设置新增"GPU 显存占用"实时展示（5s 轮询 + 进度条 + 常驻模型标签）；说明：TruFor 为子进程型任务本就跑完即释放（模型在子进程内），无需 idle 配置 |
| B92 | 登录用户保存的 API Key / 模型配置 / 模型列表重启后全部丢失（回退为空配置） | B88 修复时在 `_migrate` 中加了**无条件** `UPDATE rs_presets/rs_models SET user_id=NULL WHERE user_id=1`（当时 user_id=1 是旧游客幽灵账号）；登录体系上线后 user_id=1 变为真实登录用户，每次重启该语句将登录用户全部预设与模型列表重置为游客归属（user_id=NULL），登录后 `_scope` 按 user_id 过滤查不到 → 看到空配置 | ① `app.py _migrate` 删除无条件重置语句（B88 旧数据已清理完毕，default=None 后新游客不再误写 user_id=1）；② `settings.py _ensure_device` 新增 `_migrate_guest_data`：登录用户访问时将该设备（device_id 匹配）的游客记录（user_id=NULL）迁移回登录用户名下（幂等），恢复被误重置的数据，后经 `reconcile_presets` 同名去重保留带 key 的预设 |
| B93 | 点位真实性核验上传文件列表刷新页面后消失（遥感核验此前已修复但有 URL 双 `?` 导致缩略图 404） | ① SmartVerify.jsx 两个 UploadPanel 未传 `onUploadFile`/`imageUrlFn`，文件选择后仅本地 blob 不落盘，刷新后后端无记录 → 列表空 ② smart_verify 后端 `/upload-single` 路由新增后后端未重启 → 404 ③ UploadPanel `restoreImages`/`addRawFiles`/`markUploaded` 三处缩略图 URL 用 `?t=` 追加时间戳，但 `imageUrl(id)` 已含 `?dev=xxx`，导致双 `?` → 后端 `dev` 参数解析错误返回 404，缩略图加载失败 | ① SmartVerify.jsx 两个 UploadPanel 补 `imageUrlFn={smartApi.imageUrl}` + `onUploadFile` 回调（整改图/暗访图分别调 `smartApi.uploadSingle`）② `doGeneratePairs` 改为直接用已上传文件 id 配对，不再二次批量上传 ③ 重启后端加载 smart_verify `/upload-single` 路由 ④ UploadPanel 三处 `?t=` 改 `&t=`（因 imageUrl 已含 `?dev=`） |
| B94 | 管理页清空操作改造后 i18n 键名未同步——清空按钮显示 i18n 键名而非文案 | 后端 admin.py 清空操作从两级（clear_guests/clear_users）改为三级（clear_files/clear_config/clear_all）时，AdminPage.jsx 和 adminApi.js 同步更新了引用键名（dataClearFiles/dataClearConfig），但 i18n 文件翻译条目未同步重命名，仍为旧键名（dataClearGuests/dataClearUsers） | zh-CN.json 和 en.json 将 `dataClearGuests`/`dataClearUsers` 及其 `Desc` 替换为 `dataClearFiles`/`dataClearConfig` 及其 `Desc`，文案更新为三级清理语义；**约定：前端 i18n 引用键名修改后必须同步检查翻译文件是否包含对应键** |
| B95 | 遥感核验结果表格无数据时不显示（仅空态文字），无法预览表头结构 | 结果区整体被 `filteredRecords.length > 0 && (...)` 包裹，无记录时表格（含表头）整体隐藏 | RsVerify.jsx 结果区改为常驻渲染：批量操作按钮在无记录时 `disabled`，表格常驻显示，tbody 空数据时渲染 `colSpan=10` 空态行；SmartVerify.jsx 的 ResultTable 同样取消 `pairResults.length > 0 &&` 包裹（ResultTable 内部已有空态行），点位核验结果表常驻显示 |
| B96 | 遥感核验四乱场景上传图片在切换场景后丢失（其他场景空、返回四乱也空、刷新后列表空但后端文件还在） | `rs_verify/routers/upload.py` 的 `/upload-single` 的 `scenario` 参数未标 `Form(...)`，FastAPI 把它当 **query 参数**，而前端把 scenario 放 FormData body → 后端恒收默认值 "detect" → 所有图片全存成 detect 场景，classify 查询恒空；另 RsVerify `restoreUploads` 切换场景时未先清空旧面板，`restoreImages` 累加导致跨场景残留 | ① `upload-single` 的 `scenario` 改 `Form("detect")`（与 `/upload` 一致）；② `app.py _migrate` 存量修正：`position='single'` 且 scenario='detect' 的记录归位到 `classify`（四乱是唯一用 single 的场景，幂等）；③ `restoreUploads` 先 `reset()` 三个面板再恢复当前场景列表 |
| B97 | 图像篡改检测上传列表清除后再上传，缩略图仍显示上一次的图（刷新后才恢复） | SQLite 无 AUTOINCREMENT 时删除记录后新插入**复用被删的 rowid** → 新图 URL 与旧图完全相同，浏览器 `<img>` 更新 src 为相同值不重新加载 → 显示旧图 | Detect.jsx 上传列表缩略图 URL 拼时间戳 `${it.url}&t=${Date.now()}`（fetchUploads 恢复与 addUploads 新增两处），强制浏览器重新请求（与 B93 修 smart/rs 缩略图同法）；**约定：任何 `?dev=` 图片 URL 用于 `<img>` 时，需拼时间戳防同 URL 缓存** |
| B98 | 图像篡改检测检测成功但前端结果列表为空（后端记录在、detect_results 目录有文件；系统设置统计"0 项结果"但占用 0.2MB） | 检测记录 `user_id=None`（游客归属），用户随后登录（user_id=1）→ `api_results`/`api_stats` 按 `user_id==1` 过滤查不到游客记录；detect/smart 缺 rs_verify B92 那样的"登录时游客数据迁移" | detect.py 新增 `_migrate_guest_data(device_id, user_id)`（登录用户访问时把该设备 `user_id IS NULL AND device_id=:d` 的记录 UPDATE 到用户名下，幂等），`api_results`/`api_uploads`/`api_stats`/`api_result_clear` 登录态开头调用；重启后端后游客历史检测/上传自动归入登录用户 |
| B99 | 系统设置一键清理清不掉 detect_results/<device> 设备文件夹（但统计能扫到 0.2MB 占用） | `api_result_clear` 登录用户走 `_clear_user_data(user_id)`：只删 `user_id==1` 的记录文件、**不删设备目录**（原注释"设备上可能还有游客数据"），而记录是游客归属 → 登录用户删不到记录也不删目录，文件夹残留 | ① B98 迁移后游客记录先归 user_id 再清 ② `api_result_clear` 登录用户清空后 `shutil.rmtree` 当前设备目录（DETECT_RESULTS_DIR/DETECT_UPLOADS_DIR/<device>，迁移后该设备数据已全部删除） |
| B100 | 点位真实性核验结果表缩略图不显示、ImageCompare 弹窗图片也不显示 | smart_verify `results.py` 返回的 `left_image_url/right_image_url` 不带 dev；`serve_image` 用 `?dev` 或 header 校验，`<img>` 无法带 header → dev 空 → 404（违反 B78 约定）；前端 ResultTable `thumb()`/ImageCompare 又用 `?t=` 拼时间戳与 `?dev=` 双问号冲突 | 后端 results.py 列表与 detail 两处 URL 均带 `?dev={device_id}`；前端 ResultTable `thumb()` 与 ImageCompare 的 `?t=` 改 `&t=`（URL 已含 `?dev=`） |
| B101 | 遥感核验四项问题：①四乱导出用通用表格 ②classify 结果图弹窗标题显示"标注对比图" ③重新核验无进度反馈 ④重新核验后空 rec_ 目录残留 | ① `services/excel.py` 单一 HEADERS 12 列，未区分 classify ② 弹窗标题恒用 `colAnnotated` ③ `handleRerun` 直接 await 无 loading ④ rerun 只删旧标注图目录，历史/失败遗留的空 rec_ 目录不清理 | ① excel.py 新增 CLASSIFY_HEADERS（序号/文件名/场景/模型/时间/大类/具体类别/特征描述/标注图，参考 CLI SINGLE_COLUMNS），记录全为 classify 时用之 ② RsVerify 弹窗标题 `isClassify ? colResult : colAnnotated` ③ handleRerun 加 `rerunning` 态 + indeterminate 进度弹窗 + i18n `rerunning` 键 ④ rerun 结尾调 `app._cleanup_empty_workdirs()` 清理空 rec_ 目录 |
| B102 | 遥感页结果列表"清空全部"连带删除了上传图片（UploadImage 记录+文件），留下空文件夹；结果列表应只清结果，不碰上传文件 | `results.py batch_delete` 在删完 AnalysisRecord 后，还做了两件事：①每条记录调 `_remove_orphan_upload_image` 删关联上传图 ②兜底循环删所有未被引用的上传图（`for img in UploadImage...`），导致上传图片的 DB 记录与文件被一起清空，且无空目录清理 | ① `batch_delete` 移除 `_remove_orphan_upload_image` 调用与兜底循环，只删 `AnalysisRecord`+标注图/CLI 产物 ② `delete_result`（单条删除）同步移除 `_remove_orphan_upload_image` ③ `batch_delete` 末尾追加 `_cleanup_empty_workdirs()` 清理残留空目录 ④ 从 `analyze.py` 导入 `_cleanup_empty_workdirs` |
| B103 | 四乱场景结果列表清空时，图片（标注图）删了但 rec_xxx 空文件夹残留 | `_delete_record_files` 先 `os.remove` 删除标注图，再用 `os.walk(WORK_DIR)` 按文件名 `os.path.exists` 查找 rec_ 目录——**文件已删，查找恒为 False → rec_dir 为 None → 目录残留**（顺序颠倒的经典坑） | `_delete_record_files` 改为**先定位再删除**：标注图路径 `os.path.dirname` 以 `rec_` 开头时直接用该目录（标注图通常就在 rec_xxx 内）；否则兼容旧数据按文件名遍历查找；定位后再删标注图、最后 `shutil.rmtree` 整个 rec_dir（非空也能删）；`batch_delete` 末尾 `_cleanup_empty_workdirs()` 保留作兜底 |
| B104 | 四乱核验后清空上传文件列表，后端文件删不掉（只清了前端）；另修 bug 后未重启后端导致 B103 未生效（单条删除仍残留空目录） | `delete_image` 有"图片被结果记录引用时 400 拒绝"保护 → 核验后图片必被引用 → 前端 `handleClearUploads` 循环调 `deleteImage` 全部 400，`catch(_) {}` 静默忽略 → 后端文件永远删不掉 | ① `delete_image` 改为**级联删除**：删除引用该图片的全部结果记录（`_delete_record_files` 连带标注图+rec_ 目录），再删上传图片文件与记录，不再 400 ② 前端 `handleClearUploads` 末尾 `loadResults(true)` 静默刷新结果列表（级联删了结果需同步）③ **排查同类**：rs_verify 所有删除入口（单条/批量/级联/cleanup_all）均复用 `_delete_record_files`，rerun 先取 old_dir 再更新顺序正确；smart_verify/detect 按记录字段直删文件无此坑 ④ 教训：**改完 rs_verify 后端代码必须重启后端再让用户测试** |
| B105 | 通知中心新页面 3 处破坏性操作（删除好友/删除聊天/一键清理）直接用了浏览器 `window.confirm`（违反 B8 约定） | 初版 NotificationCenter.jsx 图省事用原生 confirm | 改为组件内确认弹窗：新增 `confirmBox` state + `.modal.notify-confirm` 弹窗（标题 common.confirm、文案、取消/确定按钮 danger 红色），删除好友/删除聊天/一键清理三个入口统一复用 |
| B106 | 通知中心新增功能未配 i18n 与主题样式（`.notify-*/.bell-*` 样式与 notifiy 命名空间初始均为 0）→ 页面无样式且可见文案显示 i18n 键名 | 新功能页开发时只写了 JSX，漏补 CSS 与翻译 | 补齐 index.css 的 notify/bell/chat/zip/emoji 主题样式（全部走 `--c-*`/`--shadow-*` 变量，复用 .btn/.modal 通用类）；zh-CN.json/en.json 增补 notify 命名空间（与代码 t("notify.*") 键一一对应）；**约定：新增功能页必须同步补 index.css + zh/en 翻译，否则无样式/显键名** |
| B107 | 聊天窗对方消息头像显示字面 "?"（`avatarText("")`），聊天窗头部 UID 拼接逻辑有误（`msgs[0]?.receiver_id===meId?" ":""` 恒输出 "ID: " 前缀） | 初版 MessageBubble 对方头像与聊天头 UID 渲染逻辑未完善 | 对方消息头像改固定 "👤" 占位；聊天窗头部改传 `uid={activeItem?.peer_uid || ""}`，有值才渲染 `ID:{uid}`，无值留空 |
| B108 | 通知中心 UI 打磨四连：①小铃铛 hover 浮层鼠标刚下移即消失、无法移到弹窗上 ②小铃铛/添加好友/好友列表/清理用彩色 emoji 不协调，用户要"纯净文本风" ③顶栏铃铛与头像基线错位（.user-area 为 inline 基线对齐）④无任何会话/公告时左侧只剩"暂无会话"，看不到系统公告入口 | ①popup 绝对定位在 trigger 边界框外，从按钮滑向弹窗的间隙触发 `mouseleave` 关闭 ②图标直接写了 emoji ③user-area 未设 flex ④conversations 返回空时前端不兜底 | ①hover 加 180ms 延迟关闭 + 弹窗自身 `onMouseEnter` 保持（scheduleClose/keepOpen），鼠标可顺畅移入弹窗 ②铃铛/添加好友(user-plus)/好友列表(users)/清理(trash-2)全靠换为**单色线条 SVG**（feather 线性图标，`stroke=currentColor` 跟随主题文字色，非彩色图）③`.user-area` 改 `display:flex;align-items:center;gap:6px`、`.bell-btn` 加 `color:var(--c-text-2)` 实现铃铛与头像垂直居中对齐 ④`refreshConvs` 兜底 `unshift` 一个 peer_id=0 系统公告项，左侧永远有公告入口（即使无会话/公告/接口异常）|
| B109 | ①用户管理页历史要求未落实：仍显示"禁用"（应"封禁"）、表格未居中、管理员开关还挤在操作列（应下移到角色列并加"设置为管理员："前缀）②通知中心公告页仍是居中普通气泡、公告图标仍用彩色📢、时间嵌套在气泡内 | ①管理页多轮需求未收敛到最终态 ②公告页初版用 `chat-bubble.notice` 居中样式 | ①「禁用」→「封禁」（zh 封禁/已封禁；en Ban/Banned）；`.admin-table th,td` 改 `text-align:center; vertical-align:middle` 全表居中；管理员开关从操作列移到角色列身份文本下、前置 `admin.setAdminLabel("设置为管理员：")` label，超级管理员开关 disabled（title superLocked）保留 ②公告页重做：左侧顶到头大头像 + 右侧带左侧小尖角气泡（`.ann-*`，标题+内容，时间 `.ann-time` 脱离气泡置于气泡下方浅色），所有公告图标（公告行/公告页头部/公告条）改单色喇叭 SVG（`AnnIcon`，lucide megaphone 线性，currentColor 跟随主题） |

### 5.4 通知中心 / 聊天（chat）

| 编号 | 问题 | 根因 | 修复 |
|------|------|------|------|
| B110 | `/api/chat/conversations` 全部 500（系统公告栏不显示、聊天不可用；前端兜底后只显示公告栏反而掩盖了故障） | `list_conversations` 的会话 `rows` 查询在 `with engine.connect() as conn:` 块内，但公告摘要（`_notice_brief`）/已读游标（`_get_last_read_id`）/待处理申请数（`_pending_count`）在**块外**复用已关闭的 `conn` → `sqlalchemy.exc.ResourceClosedError`（B86 同类坑） | 将上述三处查询与排序/组装返回整体收进 `with engine.connect()` 块内，块内完成全部连读返回；**改完后端需重启生效** |
| B111 | 游客未登录时悬停铃铛不展开弹窗，且游客看不到最新公告 | BellMenu `onMouseEnter` 以 `auth.isLoggedIn` 为门槛拦截游客；游客分支只渲染登录引导，不展示公告 | ①移除游客门槛，游客同样可悬停展开 ②游客态新增 useEffect 拉公开 `/api/announcements` 展示最新公告，下方保留登录引导 |
| B119 | 聊天窗头部（`notify-chat-head`）无法显示对方头像和名称（从好友列表进入新会话，或进入尚无会话记录的会话时，头部名称/ID 为空） | `ChatWindow` 的名称/头像取自 `activeItem?.peer_name`，而 `activeItem = convs.find(c => c.peer_id === activePeer)` 仅在**左侧会话列表**里有该好友时才非空；从好友列表（`openChatWith`）或外部跳转进入**尚无消息的会话**时 `convs` 里无此行 → `activeItem` 为 `undefined` → `name=""`/`uid=""`，头部空白；后端 `/api/chat/messages` 仅返回消息不返回对方资料，前端无从兜底 | 后端 `get_messages` 返回新增 `peer_name`/`peer_uid`（查 `users` 表填充对方资料）；前端新增 `peerMeta` state，`loadMessages` 写入，切换会话时重置，`ChatWindow` 名称/ID 改为 `activeItem?.peer_name || peerMeta?.name`（列表里优先走实时 `convs`，新建会话回落消息接口）。**改完后端需重启生效** |
| B120 | 发送消息报 `sqlite3.OperationalError: database is locked`，内容发送不出去 | `_touch_conv` 自带 `with engine.begin() as conn:`，而 `send_message`/`send_file` 已在 `with engine.begin()` 事务内调用它 → 事务内再开 `engine.begin()` 取得**第二个写连接**，与外层未提交事务并行抢 SQLite 写锁（WAL 下写写仍需独占），首条 `INSERT INTO chat_conversations` 即被阻塞超时报锁 | `_touch_conv` 改为接收调用方 `db_conn` 参数**复用外层事务连接**，不再自开事务；两处调用点补传 `conn`。教训：事务块内必须复用事务里的 `conn`，勿再 `engine.begin()`（同库并行写连接 → 锁冲突） |
| B121 | 会话列表行名称末尾多显示一个 "0" | `{it.is_pinned && ...}` 中 `is_pinned` 是**数字**（0/1），0 为假值但 React 会把 `0 &&` 表达式的值 `0` **当成文本渲染**，于是未置顶的会话都会在 ID 后面多个 "0" | 改为 `{!!it.is_pinned && ...}` 强制转布尔。同类检查：本文件其余 `X && JSX`（badge()/长度取反/boolean state/字符串/比较表达式均安全），仅此一处数字条件 |
| B122 | ①用户清除个人聊天记录后，对方聊天记录也被清除（互相干扰）②小铃铛与通知中心的通知/未读刷新不同步（一快一慢）③发送图片/文件"上传即发出"，无法先预览待发 | ①聊天记录清除原为**物理删除整行**，双方共用同一数据行，一方清除即同时影响另一方视角；且**后端进程（16:31 启动）早于最新 `chat.py`（16:54 修改）**，跑的是旧代码，新逻辑未加载 → 修复"看似无效" ②铃铛 5s 轮询、通知中心操作即刻刷新，两端刷新时机不一致 ③发送附件没有"待发"缓冲，选完即落地消息 | ①后端数据隔离：`chat_messages` 增 `del_by_sender`/`del_by_receiver`，`_visible_cond(uid)` 只返回**本人视角未删**消息；`clear_chat` 只把本人发送的标记 `del_by_sender=1`、收到的标记 `del_by_receiver=1`，**仅当双方都标记才物理删除并回收文件**（对方视角不受影响）；`delete_conversation` 只删本人视角会话。**改后重启后端**加载最新代码（见下方"教训"）②两段式发送：新增 `chat_pending` 表 + `upload_pending`/`delete_pending`/`send_pending` 接口，`delete_pending` 删记录的同时删落盘文件、仅本人持有互不影响；`send_pending` 批量落地为消息 ③前端全局同步：`chatApi` 定义 `CHAT_REFRESH` 事件，`BellMenu` 与 `NotificationCenter` 在发送/已读/清理/好友变更后**广播并互听**，未读红点实时一致，5s 轮询兜底 | **教训（重要）**：改完后端 `.py` 必须重启后端（启动器无 `--reload`）；改前先核对 `Get-NetTCPConnection 8000` 的进程启动时间 是否**晚于**源码最后修改时间（`LastWriteTime`），否则跑的是旧代码、修复木有真正生效——本次"清除聊天互相影响"反复复现即因 8000 被 16:31 的旧进程占用，而代码 16:54 才改 |
| B123 | 待发附件删除未彻底清理后端落盘（表现：点 × / 键盘 Delete 删掉前端缩略图，但 `chat_files/<uid>/pending/` 里文件残留） | 前端删除待发项只 `setPending(filter)` 清了本地队列，未调用后端删除接口，落盘文件成孤儿 | 前端 `removePending(idx)`：先释放 preview 的 `URL.revokeObjectURL`，再 `await chatApi.deletePending(p.id)`（后端 `delete_pending` 删 `chat_pending` 记录 + `_remove_files([path])` 删落盘文件）；键盘 Delete/Backspace 与 × 按钮共用该删除函数，且只删**本人**待发项（`WHERE id AND user_id=当前用户`），不影响对方。**增强：待发附件条嵌入输入框内**（新增 `.notify-chatbox` 外壳，附件条 `.notify-pending` + `.notify-textarea` 同一个带边框输入框；textarea 去独立边框、透明背景、外壳 `:focus-within` 高亮）——**坑：带 `tabIndex` 的 div 点击后并不会自动获得焦点**，若不在 `onClick` 里 `currentTarget.focus()`，`onKeyDown` 收不到键盘事件 → 表现为"只能点 × 删"，故附件项 `onClick` 手动 `focus()`+记 `selIdx` 后，Delete/Backspace 才真正删除；`textarea` 的 `onClick` 清 `selIdx` 防止打字误删附件。**补充：图片待发项仅显示缩略图（文件名只放标题 title），zip 项显示 `Z`+文件名；键盘删除双路径**——①附件项获焦时 Delete/Backspace 删该项 ②焦点在 `textarea` 时 `onKeyDown` 也支持：有选中附件（`selIdx>=0`）按 Delete/Backspace 删选中、`textarea` 为空时按 Backspace 删最后一个附件，避免"只能点 ×" |
| B124 | ①清空聊天记录后右侧聊天框仍显示（左侧会话列表已空、只剩系统公告，右侧却残留聊天窗）②聊天窗头部显示"自己跟自己聊天"（显示当前登录用户自己的名字/ID） | ①`activePeer` 从 localStorage（`notify_active_peer`）恢复，`doClearChat` 只 `setActivePeer(null)` 但**未清 localStorage**；刷新页面后挂载时无条件恢复旧值（指向已被清空/删除的会话），而渲染条件 `activePeer > 0` **不校验该 peer 是否仍存在于会话列表** → 右侧残留聊天窗 ②残留的 peer 恰好等于当前用户自己的 ID，且后端 `get_messages` **未防护 `peer == me["id"]`**（`send_message`/`send_file`/`send_pending` 都有"非法接收者"防护，唯独它没有）→ 消息接口返回自己的资料，聊天窗头部显示自己 | ①前端挂载恢复校验：`refreshConvs` 改为返回列表，挂载时**先拉会话列表再恢复** `notify_active_peer`，仅当该 peer 仍存在于列表（或 0 公告/-1 申请）才 `setActivePeer`，否则保持 null → 清空/删除后刷新不再残留聊天窗 ②`doClearChat` 清空时 `localStorage.removeItem("notify_active_peer")` ③后端 `get_messages` 增加 `if peer <= 0 or peer == me["id"]: return {"items": [], "ts": _now()}`，杜绝任何路径产生"自己跟自己聊天"。**改后端需重启**（本次 PID 22240→25816） |
| B125 | ①好友申请处理后左侧"好友申请"红点不消失（需刷新页面）②小铃铛收到新消息但通知中心页面不同步（需刷新页面才出现） | ①`doHandleReq` 处理申请后只 `setReqOpen(true)` 刷新右侧申请面板，**未刷新 `pending` 计数**（`refreshConvs` 里的 `setPending(d.pending_requests)`）→ 红点不消失 ②通知中心**无全局轮询**：只在挂载时拉一次会话列表、选中会话时 `pollActive` 轮询**当前会话**；未选中会话时列表不再刷新，新消息不出现；且小铃铛 5s 轮询 `summary` 收到新消息后**只 setSum 不广播**，通知中心无从感知 | ①`doHandleReq` 处理后补 `refreshConvs()`（更新红点计数）+ 广播 `CHAT_REFRESH`（同步小铃铛 pending）②通知中心新增**全局 5s 轮询 `refreshConvs`**（无论是否选中会话都刷新列表未读/申请数）③通知中心**监听 `CHAT_REFRESH`**：收到后 `refreshConvs()` + 若 `activePeer>0` 则 `loadMessages(n)`（用不广播的 `loadMessages` 而非 `pollActive`，**避免自身广播→监听→再广播死循环**）④小铃铛 `loadSum` 在未读/申请**增加**时广播 `CHAT_REFRESH`（减少/已读不广播，同样防循环）。纯前端 HMR 生效 |
| B126 | admin 关闭/删除公告后，用户端已收到的公告也消失（用户期望：公告像聊天记录一样存个人数据，各存各的，不受 admin 影响） | 公告是**全局共享表**（`announcements`），所有接口（通知中心公告页 `get_notices`、铃铛 `_notice_brief`、顶部 banner）都实时查 `enabled == 1`，`chat_ann_read` 只存"已读游标"而非副本 → admin 关闭（enabled=0）即全局撤回 | 改为**公告投递模型**：新增 `chat_ann_delivered` 表（user_id/ann_id/title/content/created_at/delivered_at，`UNIQUE(user_id,ann_id)`）存用户个人副本；`_ensure_ann_delivered` **惰性投递**——用户拉公告时把当前 `enabled=1` 且未投递的公告快照写入副本（已关闭/删除的不再投递→新用户看不到；已投递副本不受 admin 后续关闭/删除/编辑影响）；`get_notices`/`_notice_brief` 改查用户副本；`clear_chat` 清空本人副本；admin.py `_CHAT_TABLES` 加 `chat_ann_delivered`。**坑：惰性投递需写库，但 `conversations`/`summary` 用只读 `engine.connect()`** → `_notice_brief` 内部用独立 `engine.begin()` 写事务再查，避免把整个接口改成写事务（B120 锁教训）。**迁移**：首次投递（副本为空）时重置 `ann_read` 游标（旧版 last_read 存 announcements.id，语义已变为 delivered.id）。改后端已重启（PID 28304→15708） |
| B127 | 好友申请界面只能看到"收到的请求"，看不到自己"发送的请求"及状态（等待对方同意/已添加/添加失败） | `/api/chat/requests` 只查 `receiver_id == me["id"]`（收到的），未返回发送的 | 后端 `list_requests` 同时查收到的（`receiver_id==me`，对方是 sender）与发送的（`sender_id==me`，对方是 receiver），每项带 `dir: "in"/"out"` 方向；排序待处理优先、同状态时间倒序。前端 `RequestsPanel` 分组展示：**收到的申请**（pending 显示同意/拒绝按钮，已处理显示"已同意/已拒绝"）+ **发送的申请**（pending 显示"等待对方同意"、accepted 显示"已添加"、declined 显示"添加失败"）；i18n 新增 `receivedReqs/sentReqs/waiting/added/failed` 键（zh/en）；CSS 新增 `.req-group-title`/`.req-status.req-wait`。`doAddFriend` 发送申请后补广播 `CHAT_REFRESH`（对方铃铛 pending 及时更新）。改后端已重启 |
| B128 | 通知中心会话列表与聊天框宽度固定（300px）无法调节；页面/面板缩小时布局不优化（工具栏不换行、会话行次要信息不隐藏、名字溢出） | `.notify-panel` 固定 `width:300px` 无拖拽；无窄屏适配（无容器查询/媒体查询）；`.notify-row-name` 内名字是裸文本节点，flex 下无法单独 ellipsis 截断 | ①**拖拽调节宽度**：`.notify-panel` 与 `.notify-main` 之间插入 `.notify-resizer` 手柄，JS `startResize`（mousedown 记录起点→mousemove 改宽→mouseup 解绑并持久化），宽度 clamp `[200,480]`，存 `localStorage("notify_panel_w")`，挂载恢复；`.notify-panel` 加 `min-width:200px`（**保留头像可见**）/`max-width:480px` ②**窄面板适配**：`.notify-panel` 加 `container-type:inline-size`，`@container (max-width:260px)` 时工具栏 `flex-wrap:wrap`（搜索框占一行、按钮换行）、会话行隐藏 `.notify-row-uid`/`.notify-pin`/`.notify-row-summary`（保留头像+名字）③**名字截断**：`{it.peer_name}` 包 `<span class="notify-row-name-text">` + `min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap` ⑤会话列表 `.notify-list`/消息区 `.notify-msgs` 已有 `overflow-y:auto` 滚动。纯前端 HMR 生效 |

### 5.5 人脸识别 / 功能开关（facerec）

| 编号 | 问题 | 根因 | 修复 |
|------|------|------|------|
| B129 | `FaceRecognition/core/face_engine.py` 报 `ImportError: attempted relative import beyond top-level package` | FaceRecognition 的 `core` 包被当**顶层包**导入（`run.py` `sys.path.insert` 目录后 `from core.xxx import`），其内部却用 `from .. import config`（两层相对导入，预期指向 core 的父包 config），而顶层导入下 core 无父包 → 导入失败 | core 包内引用顶层 `config.py` 一律改**顶层绝对导入** `import config`（目录已在 sys.path），仅保留同级相对导入 `from .xxx import ...`；`face_db.default_db()` 里 `from .. import config` 同理。教训：**被当作顶层包直接导入的包，内部不得用 `from ..` 引用其父包模块** |
| B130 | `FaceRecognition/run.py list` 报 `TypeError: cmd_list() takes 2 positional arguments but 3 were given` | `run.py` 用统一分发 `fn(engine, db, args)` 调用所有子命令，但 `cmd_list`/`cmd_delete` 不需要 engine、形参只写了 2 个，比分发协议少一个位置参数 | 所有子命令签名与分发协议对齐：`cmd_list(_engine, db, args)`、`cmd_delete(_engine, db, args)`（不用的参数用 `_engine` 命名列明）。教训：**统一分发 `fn(engine, db, args)` 下，全部子命令签名必须一致，不用引擎的也必须占位** |
| B131 | 管理员关闭"人脸识别"功能开关后，普通用户/游客首页仍能看到"人脸识别"卡片（点开提示"该功能尚未上线"）；且后端 feature_gate 未拦截人脸接口。**后续抽查补充**：关闭**其他功能**（如遥感核验）后其卡片同样仍显示、点进无反应 | ①前端 `Home.jsx` 的功能卡片 `enabled` 是**硬编码**，全部未接入 `/api/features` 拉取的开关状态 + admin 豁免（首轮只修了 `face` 一张，漏了 detect/verify/rsverify 三张 → 关闭时它们 `canView`/`canUse` 恒真，卡片仍在且点了 `openTab` 因开关关闭而 return 无反应）；`App.jsx` 顶部标签 `TAB_META` 走 `features[...] !== false || isAdmin` 正确过滤（B89 修复过），但首页卡片 Home 此前未接开关，且**同类功能卡片必须一起修，不能只改被报告的那张** ②后端 `feature_gate.py` `_FEATURE_PREFIX` 未登记 face（`_FEATURE_PREFIX` 缺 `face` 前缀，注释"face 暂无接口"），没有人脸接口前缀拦截 | ①前端：`App.jsx` 把 `features={features} isAdmin={isAdmin}` 传给 `<Home .../>`；`Home.jsx` 全部 4 张卡片统一走开关——`FEATURES` 每项加 `feature`（开关名，face 另加 `ready:false`），`canView(f)=features[f.feature]!==false || isAdmin`（关闭且非 admin → 隐藏），`canUse(f)=f.ready!==false && (isAdmin||features[f.feature]!==false)`（可进入判定，face 恒不可进）；列表为空（全部关闭）显示 `common.noFeature` 空态 ②后端：`_FEATURE_PREFIX` 登记 `"face": ("/face/api",)`（与 verify=`/smart/api`、rsverify=`/rsverify/api` 挂载前缀规范一致，face 未来挂 `app.mount("/face", ...)`）。教训：**新增/修复功能卡片显隐，全部卡片必须由 `/api/features` 开关 + admin 豁免驱动，不得硬编码 enabled；修复涉及同类多张卡片时必须一并检查，不能只改被报告的一张**；新增功能系统需同步登记 feature_gate 前缀 |
| B132 | 人脸识别人工入库：库中已有**同名同人**（同 person_id 多样本）时再次录入/人工标注，本应"补样本"却**新建了一个 person_id**——同一人在库里出现两条人员记录，1:N 检索可能分散命中、admin 库管理出现重复人员 | 入库查重分支只处理两种情况：`conflict`（相似且不同名 → need_confirm）与 `mode=overwrite`（改名+补样本）；**漏了"相似且同名"分支**——该情况 `conflict=None`、`same_person_id` 有值，但 mode 为空时直接落到 `else: person_id = new_person_id()`（新建人员），同名同人被误当陌生人 | 三处入库入口（`face/routers/results.py` manual_save、`auth_face.py` profile_face_save、`library.py` library_add）统一补分支：`elif same_person_id: person_id = same_person_id`（同名同人 → 直接补样本，无需确认/新建）。教训：**查重分支必须覆盖"相似+同名"（同人补样本）这第三种状态**，只有"相似+异名"才需要用户确认——三分支：异名确认/同名补样本/无相似新建；同段逻辑复制到多处时，修复必须全部同步（漏一处即复发） |
| B133 | 人脸识别导出 Excel：接口直接 500 崩溃（`UnicodeEncodeError: 'latin-1' codec can't encode characters`），前端报"导出失败" | `FileResponse(out, filename=中文名)` → starlette `init_headers` 把 Content-Disposition 头按 **latin-1** 编码，中文字节超出 0-255 直接抛异常 | 与 auth.py 备份下载同方案：不用 `filename=` 参数，改手工构造 RFC 5987 头 `Content-Disposition: attachment; filename=face_results.xlsx; filename*=UTF-8''{quote(中文名)}`（ASCII 兜底名 + UTF-8 编码真实名，浏览器优先取后者）。教训：**任何含中文文件名的下载响应，Content-Disposition 必须走 `filename*=UTF-8''` + urllib.parse.quote**，FileResponse 的 `filename=` 参数遇非 latin-1 字符必崩 |
| B135 | 首页点击"人脸识别"卡片无反应，跳转不到对应页面（点其它功能正常） | `Home.jsx` 的功能卡片 `id` 与 `App.jsx` `TAB_META` 键名**不一致**：TAB_META 注册键是 `facerec`（`{ title:"人脸识别", comp: FaceRec, feature:"face" }`），但 Home 人脸卡片 `id` 是 `"face"`；点击走 `onTry(id)`→`openTab("face")`→`TAB_META["face"]` 为 undefined→第187行 `if(!meta) return;` **静默返回、不跳转**。该功能后端 `web/face/app.py`（挂载 /face，12 路由）+ 前端 `FaceRec.jsx`/`faceApi.js` 早已完整可用，唯独入口键名脱节导致游客/用户从首页进不去 | `Home.jsx` 人脸卡片 `id: "face"` → `"facerec"`，与 `TAB_META.facerec` 对齐；顺带移除过时 `ready` 判定与"face 未接 web"注释（页面早已存在）。教训：**Home 卡片 `id` 必须与 `App.jsx` `TAB_META` 键名严格一致**，否则 `openTab` 因找不到 meta 静默失败（无报错、难排查）；对照 checklist：新增功能页在 TAB_META 注册后，必须同步核对 Home 卡片 id / onTry 目标，确保键名唯一且匹配；预留占位时的旧 id 与正式 id 冲突是高发坑（B131 曾用 face 作开关名、TAB_META 用 facerec 作键名，两个命名空间易混） |
| B136 | 登录用户跨设备（换浏览器 / 预览环境）看自己的**核验图、遥感标注图、检测图、人脸图**全部 404（控制台刷 `/smart/api/images/{id}`、`/detect/results/{id}/img/...` 等），而列表、结果数据都能正常看到 | 登录体系（批次3 scope 双轨：登录按 `user_id`、游客按 `device_id`）落地后，所有供 `<img>` 加载的**图片服务接口仍用「?dev= 设备单轨」校验**，且 `<img>` 无法携带 Authorization 头 → 后端识别不了访问者是否已登录。smart/rs 图片 URL 用「当前请求者 device」→ 登录跨设备时 device 与记录 `device_id` 不匹配→404；detect/face 图片 URL 虽用「记录自身 device」侥幸能匹配，但机制与列表的 scope 双轨不一致，登录态下依旧不可靠 | ①后端 `auth_device` 新增 `get_identity_from_img()`：token/device 均从 query 取（`?token=` 解析登录 user 回退 header、`?dev=` 兜底游客 device），全部图片接口改为"它 + scope 双轨"——smart `serve_image`/`serve_visualization`、rs `serve_annotated`/`serve_upload`、face `api_upload_img`、detect `api_upload_img`/`api_result_img`（共 7 处）②前端 `api/index.js` 新增统一 `imgUrl()`：登录态在图片 URL 追加 `?token=明文`（沿用 chat `?token=` 模式，B78 思路），游客无 token 原样返回；`smartApi.imageUrl/visUrl`、`rsApi.imageUrl/uploadImageUrl` 及所有用**后端返回裸 URL** 渲染的组件（ResultTable/ImageCompare/FaceRec/Detect 的上传缩略图、结果缩略图、详情图）统一走 `imgUrl()` 签名。教训：**`<img>`/`<a>` 无法带请求头，身份标识只能靠 query 传**（B78 用 `?dev=`、本次更进一步用 `?token=`）；凡供 `<img>` 用的图片服务接口，登录体系落地时必须同步支持 query token 并按 scope 双轨过滤；前端显示后端图片一律走统一 `imgUrl()`，严禁直接用后端裸 URL（漏一处即复发 404） |

---

## 六、更新日志

| 日期 | 更新内容 |
|------|----------|
| 2026-08 | **修复 B136（登录跨设备看所有业务图 404）**——登录体系落地后，供 `<img>` 加载的图片服务接口仍用 `?dev=` 设备单轨校验，而 `<img>` 无法带 Authorization header，导致登录用户换浏览器/预览环境看自己的核验/遥感/检测/人脸图全部 404。①后端 `auth_device` 新增 `get_identity_from_img()`（token/device 均从 query 取，`?token=` 解析登录 user、`?dev=` 兜底游客 device），smart/rs/face/detect 共 7 个图片服务接口全部改为"它 + scope 双轨"②前端 `api/index.js` 新增统一 `imgUrl()`（登录在图片 URL 追加 `?token=`，游客原样返回），`smartApi`/`rsApi` 的图片 URL 及 ResultTable/ImageCompare/FaceRec/Detect 所有后端返回 URL 渲染点统一走 `imgUrl()`。**改后端需重启生效（8000 端口须是新进程）、前端 HMR 生效**。后续新增图片类功能注意：`<img>` 无 header → 统一用 `imgUrl()` + 后端图片接口支持 query token |
| 2026-08 | **人脸检测过度检测修复已同步生效到 web（溢出根源：FaceRecognition/B132）**——用户"单张糊脸图被识别出一堆(9个)错人脸"根因是 RetinaFace mobile0.25 对复杂背景/低质量图假阳多、且缺失框级过滤。模块层修复：①检测模型 `mobile0.25`→`retinaface_resnet50`（同一 facexlib、零依赖，`FaceRecognition/weights_root` 新增 `detection_Resnet50_Final.pth`≈109MB，D 盘）②`face_engine` 新增 `_pass_filter`+`_kps_is_face`（最小人脸尺寸 `MIN_FACE_SIZE=20` + 5 点关键点几何校验 `KPS_ASPECT=(0.2,1.8)`）③新增贪心 NMS `_nms`（`NMS_IOU=0.30` 合并同一张脸的多尺度偏移变体框）。**web 端是桥接层（`web/face/services/engine.py` → 直调 `FaceRecognition/core` 同一个 config/face_engine），因此本修复无需改 web 代码即自动生效**。已用项目虚拟环境重启后端(8000)并走 web 真实识别接口实测：同一误检图 web 端 `face_count` 9→**1**；临时设备数据已清。显存：`FACE_GB=1.2` 估算暂未改（resnet50 增幅有限 + 空闲 300s 自动卸载兜底），若遇显存不足可调至 1.5。**注意**：面部识别算法 bug 权威记录在 `FaceRecognition/DEVELOPMENT_GUIDE.md`（引擎历史（B129~B132））；两文档 B 编号体系（尤其 B131/B132）曾双轨维护出现**同编号不同义**错位，建议后续统一并入 web 全局编号再索引 |
| 2026-08 | **修复 B135（首页人脸识别卡片点不动）**：`Home.jsx` 人脸卡片 `id:"face"` 与 `App.jsx` `TAB_META` 键名 `facerec` 不一致 → `openTab("face")` 找不到 meta 静默 return，首页从入口进不去（后端 `/face` 12 路由 + FaceRec 页面早已完整）。改 Home 卡片 id→`facerec` 对齐，移除过时 `ready` 判定。教训：Home 卡片 id 必须与 TAB_META 键名严格一致，预留占位旧 id 与正式 id 冲突是高发坑。前端已 `vite build` 通过；后端未改动、无需重启 |
| 2026-08 | **修复 B134（数据管理页第 4 张统计卡无名称）**：人脸库集成后 `_data_stats` 返回 4 个子系统，前端 `AdminPage.jsx` 的 `sysNames` 映射漏登 face → 出现一张无名称、只显示"0 用户记录 0 游客记录"的卡片；补 `face: t("home.faceTitle")` 一行修复。纯前端改动（HMR 生效，无需重启后端）。教训：后端新增子系统后，前端遍历渲染的键→名称映射表必须同步登记 |
| 2026-08 | **人脸识别 web 集成上线（第四功能页 /face）**——①模块层：`FaceRecognition/core/face_db.py` v2 表结构扩展（thumb_path/user_id/created_by/created_at/source + 启动自动迁移补列 + 分页/模糊搜索/人员级改名/账号绑定/批量删除）；`web_bridge.py` register 支持元数据、新增 embed_image ②后端：`web/face/` 子应用（挂载 /face；独立 face.db 两表：face_uploads/face_results 一行=一张脸，embed_json 冗余特征免二次推理；`services/engine.py` 桥接——**sys.modules config 置换导入**解决与 ImageAuthenticityDetector 的顶层 config.py 同名冲突 + web 全局推理锁 + 模块懒加载/空闲 300s 卸载 + 任务记账 1.2GB）；NDJSON 流式识别（一图多脸）；人工入库查重三分支（异名确认/同名补样本/无相似新建，B132）；人脸登录（照片+摄像头帧，仅匹配已绑定账号子集）；admin 人脸库管理 ③前端：FaceRec 主页（上传列表/结果列表/详情含 512 维特征与 Top-K 候选/人工入库冲突确认/重测/导出）、AuthModal 人脸登录 tab（FaceLoginPanel：照片+摄像头扫描动画）、Profile 人脸录入、AdminPage 人脸库 tab、i18n 双语、CSS face 前缀 ④全局集成：admin 三类清空（占用级清文件/配置级清人脸库全量/全清兜底）、auth 备份 ZIP 含 face.json、游客 30 天清理、SystemSettings 统计与一键清理、Home 卡片激活（ready:false 移除）、vite proxy /face ⑤修复 B132（同名同人误建新人员）、B133（导出中文文件名 latin-1 崩溃）。TestClient 冒烟 27/27 通过、vite build 通过 |
| 2026-08 | **修复 B131（补充抽查）**：此前只修了 `Home.jsx` 的 face 一张卡片；本次把 detect/verify/rsverify 三张卡片一并接入功能开关——`canView`=关闭且非 admin 即隐藏、`canUse`=开关开启才可进入，全部功能统一由 `/api/features` + admin 豁免驱动显隐，并加 `common.noFeature` 空态（全部关闭时友好提示，zh/en 双语）。`feature_gate.py` 已登记 face 前缀。经验：修复涉及同类多张卡片必须一并检查。前端已验证 `vite build` 成功；**改后端需重启生效** |
| 2026-08 | **文档增强：新增『高频复发问题加权表』（开发前必看）**——把历史 B 系列（B1~B128）按**根因主题**归并统计**复发次数权重**，置于文档第一章之前：🔴🔴 删除/清空后落盘或空目录残留(8)、页面刷新后内容丢失/残留(8)、前端组件风格/主题/原生控件未统一(8)；🔴 图片/资源 URL 404(6)、SQLAlchemy 连接/Row/事务/锁(5)、改后端未重启/8000 旧进程(5)、导入导出 Excel(5)；🟠 i18n 键名/插值未同步(4)。每个主题含"一句话根因 + 开发前必守规避规矩"，另附次级关注清单与通用"改一处查四处"自检。同步在速读指引加入口；开发遵循"次数权重越大越要避免" |
| 2026-08 | **通知中心宽度可拖拽调节 + 窄屏布局优化（B128，纯前端 HMR）**——①会话列表与聊天框之间加 `.notify-resizer` 拖拽手柄（JS mousedown/mousemove/mouseup），宽度 clamp `[200,480]` 并持久化 `localStorage("notify_panel_w")`，面板 `min-width:200px` 保留头像可见 ②`.notify-panel` 加 `container-type:inline-size`，`@container (max-width:260px)` 时工具栏换行（搜索框占一行）、会话行隐藏 UID/置顶/摘要（保留头像+名字）③名字包 `.notify-row-name-text` span 加 ellipsis 截断 ④会话列表/消息区已有纵向滚动 |
| 2026-08 | **公告投递模型（B126，改后端已重启 PID 15708）+ 好友申请双向展示（B127，改后端已重启）**——①公告改为"用户个人副本"：新增 `chat_ann_delivered` 表，`_ensure_ann_delivered` 惰性投递当前启用公告到用户副本，admin 关闭/删除/编辑不再影响用户已收到的公告（各存各的）；`get_notices`/`_notice_brief` 改查副本，`clear_chat` 清空本人副本，admin.py 清理配置纳入新表；惰性投递用独立 `engine.begin()` 写事务避免 B120 锁；首次投递重置 `ann_read` 游标迁移旧数据 ②好友申请面板分组展示：后端 `/api/chat/requests` 同时返回收到的（`dir:in`）+发送的（`dir:out`），前端"收到的申请"（同意/拒绝/已同意/已拒绝）+"发送的申请"（等待对方同意/已添加/添加失败）；i18n 新增 5 键、CSS 新增分组样式；`doAddFriend` 补广播 `CHAT_REFRESH` 同步对方铃铛 |
| 2026-08 | **好友申请红点不消失 + 通知中心不同步新消息修复（B125，纯前端 HMR）**——①`doHandleReq` 处理申请后补 `refreshConvs()`（更新 pending 红点计数）+ 广播 `CHAT_REFRESH` ②通知中心新增**全局 5s 轮询 `refreshConvs`**（无论是否选中会话都刷新列表未读/申请数，新消息无需手动刷新页面）③通知中心**监听 `CHAT_REFRESH`**：收到后 `refreshConvs()` + 若 `activePeer>0` 则 `loadMessages(n)`（用不广播的 `loadMessages` 而非 `pollActive`，避免自身广播→监听→再广播死循环）④小铃铛 `loadSum` 在未读/申请**增加**时广播 `CHAT_REFRESH`（减少/已读不广播，同样防循环） |
| 2026-08 | **清空聊天记录后右侧残留聊天窗 + "自己跟自己聊天"修复（B124，改后端已重启）**——①**前端挂载恢复校验**：`refreshConvs` 改为返回列表，挂载时先拉会话列表再恢复 `notify_active_peer`，仅当该 peer 仍存在于列表（或 0 公告/-1 申请）才选中，否则保持 null → 清空/删除聊天后刷新页面不再残留右侧聊天窗 ②**清空联动清 localStorage**：`doClearChat` 清空聊天记录时 `localStorage.removeItem("notify_active_peer")` ③**后端自我防护**：`get_messages` 增加 `peer == me["id"]` 时返回空（`send_message`/`send_file`/`send_pending` 本就有"非法接收者"防护，唯独它漏了），杜绝任何路径产生"自己跟自己聊天"。后端已重启（PID 22240→25816）加载生效，前端 HMR 自动生效 |
| 2026-08 | **首页遥感核验文案同步（纯前端 i18n）**：`home.rsDesc`/`home.rsDetail` 更新为与实际功能一致——删除过时的"本地模型（预留）"（本地 Ollama 模型已支持）、补充缺失的**单图四乱核验**场景（乱占/乱采/乱堆/乱建）、加上批量核验/结果重新核验能力；中英文同步 |
| 2026-08 | **聊天记录数据隔离 + 两段式附件发送 + 通知实时同步（B122/B123，改后端需重启）**——①**数据隔离**：`chat_messages` 增 `del_by_sender`/`del_by_receiver`，`clear_chat` 只标记**本人视角**删除（清空聊天不再物理删整行，对方视角保留），仅当**双方都标记**才物理删除并回收落盘文件；`_visible_cond(uid)` 保证本人只能看到本人视角未删的消息；`delete_conversation` 依旧只删本人视角会话 → **一方清除聊天不影响另一方** ②**两段式发送**：新增 `chat_pending` 表 + `upload_pending`/`delete_pending`/`send_pending`（图片/zip 先上传到本人待发区排队预览，点发送才批量落地为消息）；`delete_pending` 删记录 + 删落盘文件，仅删本人待发项、不影响对方；前端 `ChatWindow` 待发条支持 × 与键盘 Delete/Backspace 删除、多附件排队、可选中项 ③**通知实时同步**：`chatApi` 定义 `CHAT_REFRESH` 全局事件，`BellMenu`（铃铛）与 `NotificationCenter` 在发送/已读已读状态变更清零/清理/好友变更后**广播并互听**，未读红点与通知两端即时一致，5s 轮询兜底 ④**★★后端重启校验**：本次"清除聊天互相影响"反复复现的根因是 8000 端口被 **16:31 启动的旧后端**占用（早于 `chat.py` 16:54 修改），跑的是旧代码（物理删除），最新隔离逻辑木有真正加载。已结束旧进程(PID 31508)并按项目规范用 `.venv\Scripts\python.exe -u app.py`（cwd=web/）重启，`openapi.json` 已确认含 `/api/chat/clear`、`/api/chat/pending/upload`、`/api/chat/messages`。**教训**：后端无 `--reload`，凡改 `.py` 必须先确认 8000 进程启动时间晚于源码修改时间，否则会因旧进程误判"修复无效"；新增后端逻辑验收时可用 `Invoke-RestMethod /openapi.json` 核对路由是否已加载 |
| 2026-08 | **聊天窗气泡/头像/表情面板三项前端打磨**（纯前端 HMR）：①**消息时间独立于气泡**——`MessageBubble` 把 `.chat-time` 从 `.chat-bubble` 内移出，改为 `.chat-body`（flex column 包裹气泡+时间）下的独立行，置于气泡底部（己方右对齐、对方左对齐，由 `.chat-msg.own .chat-body` 控制）；原居中态 `.notify-msgs` 无影响 ②**己方头像补齐**——原来 `own ? "" : "👤"` 己方头像恒为空，改为 `own ? avatarText(username)` 显示自己用户名首字母 ③**表情面板**：加 `.emoji-mask`（fixed 全屏，`.emoji-panel` 上方，点击任意空白关闭）；`.emoji-panel` 加 `max-height:220px; overflow-y:auto` 防内容溢出（装不下时滚动） |
| 2026-08 | **修复会话列表名称末尾多出 "0"（B121）**——纯前端 HMR：`{it.is_pinned && <span>置顶</span>}` 中 `is_pinned` 是数字（未置顶=0），React 把 `0 &&` 表达式的 `0` 当文本渲染 → 未置顶会话 ID 后都多个 "0"；改为 `{!!it.is_pinned && ...}`。教训：**数字类型**的 `X && JSX` 当 X=0 时会渲染出 "0"，须 `!!X` 转布尔 |
| 2026-08 | **修复发送消息 `database is locked`（B120）**——后端 chat.py，改需重启：`_touch_conv` 原先自带 `with engine.begin() as conn:`，而 `send_message`/`send_file` 已在 `with engine.begin()` 事务内调用它 → 事务内再开一个新 `engine.begin()` 拿到**第二个写连接**，与外层未提交事务并行抢 SQLite 写锁，首条插入 `chat_conversations` 即报 `sqlite3.OperationalError: database is locked`（内容发送不出去）。修复：`_touch_conv` 改为接收调用方 `db_conn` 参数、**复用外层事务连接**，不再自开事务；两处调用点补传 `conn`。**教训**：SQLAlchemy 中同一**事务**内要复用一个连接，使用事务上下文里的 `conn`，切勿在事务块内再 `engine.begin()`（会造成同库并行写连接 → 锁冲突） |
| 2026-08 | **修复聊天窗头部不显示对方头像和名称（B119）＋工具条按钮图标化**——①**头部**（后端 `chat.py get_messages` 改需重启 + 前端）：`activeItem` 依赖左侧会话列表，从好友列表进入尚无会话记录的会话时缺失 → 头部名称/ID 空白；后端 `/api/chat/messages` 返回补 `peer_name`/`peer_uid`，前端新增 `peerMeta` 兜底 ②**工具条**（纯前端 HMR）：输入栏文件/图片/表情按钮统一为**单色线条图标**（回形针/图片/笑脸，lucide 线性、`stroke=currentColor`，遵循 B108 线条图标约定）；`.tool-btn` 改 `width:32px; inline-flex 居中、hover 变色`；发送按钮 `.notify-send` 由 `align-self:flex-end` 改 `center` **垂直居中**（原先贴底） |
| 2026-08 | **修复"好友列表暂无好友 + 好友申请已处理即消失"（B118）**——①**好友列表 500**（后端 chat.py `list_friends`，改需重启）：`conn.execute(sa.select(...)).where(...)` 把 `.where()` **误接到 `CursorResult`（execute 返回值）上**（`select().where()` 才是合法写法）→ 报 `AttributeError: 'CursorResult' object has no attribute 'where'`，`GET /api/chat/friends` 500，前端弹窗 catch 后显示"暂无好友"（掩盖了真实故障）；修复为 `conn.execute(sa.select(...).where(...)).fetchall()`。**同类检查**：grep 全项目 `execute(...).where`，其余 `.where()` 均挂在 select/update/delete 表达式上，仅此一处中招 ②**申请已处理即消失**（后端 `list_requests` + 前端 `RequestsPanel`）：原 `list_requests` 只查 `status=="pending"`，同意/拒绝后刷新列表就看不到了；改为返回**全部**申请（待处理在前、已处理在后，带 `status` 字段）；前端按 `status` 渲染——`pending` 显示"同意/拒绝"按钮、`accepted/declined` 显示静态文本"已同意/已拒绝"（新增 i18n 键 `notify.accepted`/`notify.declined`，zh/en）+ `.req-status` 样式。**教训**：SQLAlchemy 写法 `select(...)` 的链式 `.where()` 必须接在**查询表达式**上，不得接在 `execute()` 的结果对象上；列表数据准备就绪后，前端弹窗空态多为接口 500 被 catch 吞掉所致 |
| 2026-08 | **修复"其他用户看不到公告 + 好友申请面板空显示"（B117）**——①**公告**（后端 chat.py `get_notices`，改需重启）：原逻辑按 `announcements.created_at >= 用户注册时间` 过滤，新注册用户注册时间晚于早期已启用公告 → 永远看不到历史启用公告（实测 test 用户看不到 test 的公告），且与横幅/会话栏 `_notice_brief`（只看 `enabled=1`）语义不一致；改为返回**全部** `enabled=1` 公告，不按注册时间过滤 ②**好友申请面板空**（前端 NotificationCenter.jsx）：B112 把入口改为常驻按钮（`setActivePeer(-1)`），但 `RequestsPanel` 的数据加载 `useEffect` 仍依赖旧 `reqOpen` 内部开关（仅在 `reqOpen` 变 true 时 `load()`），而"好友申请"按钮只设 activePeer 不设 reqOpen → **数据永不拉取**，面板恒空（角标 pending 数却正常，来自 conversations/summary），用户看到"角标1但详情空"；修复：面板仅在 activePeer===-1 时渲染，故改`useEffect(() => load(), [])` **挂载即加载**，并保留 `reqOpen` 变化二次刷新（accept/decline 后仍能刷新）③**同类检查**：公告横幅/会话栏用 `_notice_brief` await 全局 enabled，无注册时间过滤已一致；FriendList/AddFriend 为弹窗自管理数据无此坑。**教训**：入口从弹窗/开关改为面板式常驻时，子组件数据加载必须改"挂载即加载"，勿沿用旧的开关 prop 触发 |
| 2026-08 | **修复通知中心消息接口 500（B116）：`peer=[object Object]`**——前端：NotificationCenter 在 `notify-open` 外部事件/`activePeer` state 被污染成对象时，会把**整个对象拼进 URL**（`GET /api/chat/messages?peer=[object Object]`），后端 `int(peer)` 抛 `ValueError` 500 刷屏。修复：新增 `normPeer()`（仅接受整数会话 id：0公告/-1申请/>0好友），在 `loadMessages`/`pollActive`/`loadEarlier` 三个请求入口 + `notify-open` 事件 `setActivePeer` + 选中会话 effect 共五处做数字归一化，保证 state 与 URL 只含整数，对象被污染时直接跳过请求；后端 `get_messages` 对 `peer/before_id/limit` 三个 query 参数包 `try/except (TypeError,ValueError)`，非法值按空列表返回而非抛 500（query 属系统边界）。**同类检查**：chat 其余 peer 接口（setPin/delete_conversation/mark_unread）均用路径参数 `peer_id: int`，FastAPI 自动强转，对象传入得 422 不 500、不污染数据，无需改。**教训**：凡从前端 state 拿值拼 query 的接口，请求前需数字归一化，勿直接 `request.query_params.get(...)` 强转 |
| 2026-08 | **数据管理页三类清空操作补上「通知中心」子系统（B115）＋新增长期约定**——**后端**，改后需重启生效：后台核查发现三个清空接口原先只覆盖 detect/smart/rs 三库的 `_TABLES`/`_BUSINESS_TABLES`，**漏掉了后加的通知中心（chat）** → 新增独立常量 `_CHAT_TABLES`（`chat_requests`/`chat_friends`/`chat_conversations`/`chat_messages["file_path"]`/`chat_ann_read`，均在主库 web.db `/data/chat_files/` 落盘）与 `_CHAT_DB`，三个接口各补一行：`clear_files`（清空占用数据/只删文件）→ `_purge_files_only(_CHAT_DB,_CHAT_TABLES,"1=1")`；`clear_config`（清空配置数据/删DB+文件、保留账号）与 `clear_all`（清空全部/连同账号）→ `_purge(_CHAT_DB,_CHAT_TABLES,"1=1")`；`_CHAT_TABLES` **独立定义而非并入 `_TABLES`/`_BUSINESS_TABLES`**，避免 `_data_stats` 统计把聊天记录算进"图像篡改检测"项。**★长期约定（新增子系统必须同步清空）：** 新增功能/子系统时，只要会产生 DB 表或落盘文件，就必须同步把新表/新文件目录纳入数据管理页的「清空占用数据 / 清空配置数据 / 清空全部数据」三类清空接口（逐一核对三个接口，并确认 `_data_stats` 统计口径）。凡 new 出表/目录而未同步清空，即属漏删 bug（本次 B115）。此核对点已列入 [二、新增一个系统（操作模板）](#二新增一个系统操作模板) 的 checklist |
| 2026-08 | **数据管理页统计口径优化（B114）**——纯前端，HMR 生效：①卡片大数字改为 `s.user + s.guest`（各系统数据库业务记录总条数），直观反映"该系统有多少数据"，与下方清空操作对应；②副标题去掉不再需要的"设备 N"（`admin.dataDevices` 键删除，zh/en）；③按钮上方标题"清空操作"→"清理数据"（`admin.dataOps` zh"清理数据"、en"Clear Data"），语义更清晰 |
| 2026-08 | **顶栏公告横幅图标统一（B113）**——纯前端，HMR 自动生效、无需重启后端：顶栏 `announce-banner` 公告横幅（登录用户最新公告条 + 游客"登录查看公告"提示条）的图标由彩色 📢 emoji 统一为**单色线条喇叭 SVG**（`AnnounceIcon`，lucide megaphone 线性、`stroke=currentColor`，与通知中心 `AnnIcon`/铃铛公告图标同风格）；`.announce-bell` 样式由 `font-size:13px`（emoji）改为 `inline-flex` 垂直居中承载 SVG，颜色沿用父级主题色 |
| 2026-08 | **通知中心（B112）：好友申请入口由消息框改为常驻小按钮**——纯前端，HMR 自动生效、无需重启后端：①通知中心左侧工具栏在"添加好友"/"好友列表"按钮右侧新增**好友申请常驻小按钮**（复用 `notify-tool-btn` 风格，**单色线条 user-check SVG**（lucide 线性、`stroke=currentColor`，与 UserPlusIcon/UsersIcon 全局线条风格一致，非彩色 emoji），未读申请数角标用 `.notify-req-badge`，选中申请面板时 `.active` 高亮），常驻显示于列表顶部，不再依赖"有无待处理申请/是否在铃铛中点过" ②移除原列表顶部"好友申请"消息会话框（原 `.notify-row.req-entry`：它只在有申请时经由铃铛频现、且占用会话列表一整行），避免与真实会话混排 ③申请面板头部右侧"完成"按钮删除（无多余出口，面板本身可点其它会话切走），连带清理 `notify.done` 键与 `onEnter` prop ④清理 i18n 死键 `notify.reqEntryHint`（zh/en）、`notify.done`（zh/en），以及 CSS `.req-entry`/`.notify-avatar.req`/`.notify-req-emoji` 死样式 |
| 2026-08 | **通知中心/管理页/统计 细节完善**——①通知中心左侧好友申请入口去条件化、**常驻显示**于列表顶部（无待处理仍显示，仅有申请数时带角标）；占位气泡💬换单色线条 message-circle SVG ②用户管理页角色列 `.admin-role-ctrl` 加 `flex-wrap`，页面缩小时"设置为管理员："标签与开关**独立换行**不再乱排；封禁用户时操作列按钮由"启用"改为"解封"（新键 `admin.unban`/`unbanOk`，zh/en）③数据管理统计口径明确并修复：`_data_stats` 的游客设备数由"各表 `COUNT(DISTINCT device_id)` 求和"（同一设备跨多表**重复计**）改为**跨该库业务表取并集去重**；卡片副标题由"用户/游客/设备"改为"用户记录/游客记录/设备"（前端 `admin.dataUsers`/`dataGuests` 文案，避免"用户3"被误读为3个人）④弹窗头部 `.modal-head` 改 `position:sticky;top:0;background:var(--c-card)`，系统设置等滚动弹窗缩小时头部悬浮、关闭/设置按钮不随内容划走；修改后端 `.py` 后**重启后端**使 admin 接口生效，前端 HMR |
| 2026-08 | **修复 B110/B111 + 通知中心进阶**——①后端：`/api/chat/conversations` 因 `with engine.connect()` 块外复用已关闭 conn 抛 `ResourceClosedError` 全 500（系统公告栏/聊天不可用，前端兜底后只剩公告栏掩盖故障）；将公告摘要/已读游标/待处理申请等查询收进 with 块修复（B86 同类），**改后端需重启生效** ②游客未登录现可悬停铃铛展开弹窗并看到最新公告（拉公开 `/api/announcements`），下方保留登录引导 ③铃铛浮层内公告图标由彩色📢统一为单色喇叭 SVG（与通知中心 AnnIcon 一致）④通知中心会话列表顶部新增**好友申请独立入口**固定栏（带未读申请数 badge，点击进申请面板）⑤`refreshConvs` 请求失败也兜底保留系统公告栏 ⑥通知中心左侧搜索框加单色放大镜图标 ⑦顶栏用户下拉菜单各项加单色线条图标（角色/卫星[遥感管理]/齿轮[系统设置]/关机[退出]），`.menu-item` 改 flex 图标+文字对齐 |
| 2026-08 | **用户管理页 & 公告页 UI 修正（B109）**——纯前端，HMR 生效无需重启后端：①「禁用」→「封禁」（zh 封禁/已封禁，en Ban/Banned）；`.admin-table th,td` 全表居中（text-align:center）；管理员开关移到角色列身份文本下并前置「设置为管理员：」label（新键 `admin.setAdminLabel`），超级管理员开关 disabled 保留 ②公告页由居中气泡改为**左侧顶到头大头像 + 右侧带左侧小尖角气泡**（标题+内容，时间 `.ann-time` 脱离气泡置下方浅色）；所有公告图标改单色喇叭 SVG（`AnnIcon`，currentColor 跟随主题） |
| 2026-08 | **通知中心 UI 打磨（B108）**——全前端改动，Vite HMR 自动生效无需重启后端：①小铃铛 hover 浮层改为 180ms 延迟关闭 + 弹窗内 `onMouseEnter` 保持，修复"鼠标刚下移弹窗即消失"；②小铃铛/添加好友(user-plus)/好友列表(users)/一键清理(trash-2) 图标由彩色 emoji 全换为**单色线条 SVG**（feather 线性、`stroke=currentColor` 跟随主题文字色，非彩色图）；③`.user-area` 改 `flex align-items:center` + `.bell-btn` 补色，铃铛与头像垂直对齐；④`refreshConvs` 兜底 `unshift` 系统公告项，左侧永远有"系统公告"入口（即使无会话/公告/接口异常）|
| 2026-08 | **新增「通知中心」子系统（登录专属）：聊天 + 好友 + 公告**——后端新增 `web/chat.py` 挂载 `/api/chat`（表 chat_requests/chat_friends/chat_conversations/chat_messages/chat_ann_read，共用主 web.db 引擎）：好友搜索（username/8位uid）/申请/同意拒绝/好友列表/删除好友（级联彻底删该对消息+落盘文件）；会话置顶/删除聊天（仅删本人视角，对方保留）/标记未读/未读计数；消息 text/image/zip/emoji，**文本落库 + 文件落盘**（`data/chat_files/<uid>/<peer>/`，路径与元信息落库；清理=删库记录+删文件+删空目录，彻底），图片/zip 下载走 `?token=` 鉴权（B78 思路，`<img>/<a>` 无法带 header）；公告页=注册至今全部启用公告 + 按用户已读游标判未读（关闭顶栏公告后仍可在通知查看）；独立一键清理（删会话+消息+落盘文件+空目录、保留好友关系、与系统设置清理互不影响）；uid：注册生成 8 位纯数字 UID + 存量回填，`/me` 返回 uid。前端：`chatApi.js`（含 chatFileUrl ?token=）、`BellMenu.jsx`（顶栏小铃铛 hover 浮层：最新公告+最近会话+待处理好友申请+底部进入按钮；未读红点 1→99+；5s 轮询）、`NotificationCenter.jsx`（左侧微信式会话列表[公告+有聊天记录的好友]+搜索/添加好友/好友列表+右键置顶/删除聊天/标记未读；右侧公告页/好友申请/聊天窗 7:3[消息区:输入区，菜单栏 zip上传/图片上传/表情]；localStorage 保留选中会话刷新不丢；图片缩略图点击放大+下载、zip 文件框 Z 图标 3:7 分割+下载）、App.jsx 集成（notify 标签+铃铛+notify-open 事件）、Profile 显示 uid、i18n notify 命名空间（zh/en）、index.css notify 主题样式；修复 B105-B107 |
| 2026-08 | **用户管理：管理员角色改开关 + 引入超级管理员**——① 操作列"设为管理员"按钮改为开关按钮（复用 `.switch` 样式）：开=管理员、关=普通用户，点击直接调 `setRole` 切换，支持解除管理员身份（原来 admin 用户无解除入口）② 预置 `admin` 账号身份显示为"超级管理员"（前端按 `username==='admin'` 判定，DB role 不加新值），其开关 disabled（title 提示不可变更）③ 后端同类防护：`set_role`/`toggle_user`/`delete_user` 均拒绝操作超级管理员（username=='admin' → 400，防系统失管）④ i18n：新增 `profile.roleSuper`/`admin.removeAdmin`/`admin.roleOk`/`admin.superLocked`（zh/en），删除不再引用的 `admin.setAdminOk`；重启后端生效 |
| 2026-08 | **修复 B104：四乱核验后清空上传列表后端文件删不掉 + B103 未生效**——① `delete_image` 原有"被结果引用 400 拒绝"保护，核验后图片必被引用，前端循环删除全 400 被静默忽略；改为级联删除：删引用该图片的全部结果记录（连带标注图+rec_ 目录）再删图片文件与记录 ② 前端 `handleClearUploads` 末尾静默刷新结果列表 ③ 排查同类：rs_verify 所有删除入口复用 `_delete_record_files`（B103 修复自动覆盖）、rerun 顺序正确、smart_verify/detect 无此坑 ④ 重启后端使 B103/B104 生效 |
| 2026-08 | **修复 B103：四乱清空结果残留 rec_ 空文件夹**——`_delete_record_files` 先删标注图再按文件名遍历查找 rec_ 目录，文件已删导致查找恒 False、目录残留（顺序颠倒）；改为**先定位再删除**：标注图 `os.path.dirname` 以 `rec_` 开头直接用该目录，否则兼容旧数据遍历查找，定位后再删标注图并 `shutil.rmtree` 整个 rec_dir（非空也能删）；`batch_delete` 末尾 `_cleanup_empty_workdirs()` 保留作兜底 |
| 2026-08 | **修复 B102：遥感页结果列表"清空全部"连带删除上传图片**——`results.py batch_delete` 在删完 AnalysisRecord 后额外调用了 `_remove_orphan_upload_image` 与兜底循环删未引用上传图，导致上传图片的 DB 记录与文件被一起清空并残留空目录；修复：`batch_delete` 与 `delete_result` 移除 `_remove_orphan_upload_image` 调用及兜底循环，只删结果（AnalysisRecord+标注图/CLI 产物），不碰上传图片；`batch_delete` 末尾追加 `_cleanup_empty_workdirs()` 清理残留空目录 |
| 2026-08 | **Remote_sensing CLI：run.py 新增⑧精简 Excel 开关（SIMPLE_EXCEL）**——`SIMPLE_EXCEL=True` 时 classify 单图检测结果输出到 `results_classify_simple.xlsx`，仅 5 列（序号/大类/具体类别/图像特征描述/原图），原图**缩放后**嵌入（最大边 480px、保持纵横比、webp 经 PIL 转 PNG，reporter.py 的 `SIMPLE_SINGLE_COLUMNS`/`_embed_image_original`/`add_single_result_simple`/`add_single_failed_simple`）；**列宽按内容优化**（序号 8/大类 16/具体类别 18/特征描述 60/原图 40），**行高按缩放后图片高度自适应**（px×0.75+8pt，图片完整落在单元格内，不再原始分辨率撑满表格）；失败行写"识别失败"占位、行高 30；与原表格独立不混列；已修复既有 results_classify_simple.xlsx（16 张图片全部重采样缩放到 ≤480px）；注意：openpyxl load_workbook 后直接改 img.width/height 不写进 drawing extent，必须重建 workbook 重新 add_image |
| 2026-08 | **修复 B98-B101：登录态游客数据迁移 + 一键清理删空目录 + 点位图片 dev + 遥感四乱导出/弹窗/重核验**——①B98/B99：detect.py 新增 `_migrate_guest_data`（登录用户访问时把该设备游客记录归入 user_id，幂等），`api_results`/`api_uploads`/`api_stats`/`api_result_clear` 登录态调用；清空后 `rmtree` 当前设备目录，解决"检测结果列表为空 + 一键清理清不掉文件夹" ②B100：smart_verify results.py 列表与 detail 的图片 URL 补 `?dev=`，前端 ResultTable/ImageCompare `?t=` 改 `&t=`，点位核验缩略图与弹窗图片恢复显示 ③B101：rs 四乱导出改用独立表头（序号/文件名/大类/具体类别/图像特征描述/标注图）；classify 结果图弹窗标题改"结果图"；重新核验加 indeterminate 进度弹窗 + `rerunning` i18n；rerun 后清理空 rec_ 目录 ④结果表空态文本移除（遥感/点位无数据时表格空着不显示提示） |
| 2026-08 | **管理页清空操作改造为三级清理 + 公告启用开关移至操作列 + 四乱场景表头改造 + 场景选择持久化**——① 后端 admin.py 新增 `_BUSINESS_TABLES`（排除 rs_presets/rs_models 配置表）+ `_purge_files_only` 函数，替换旧接口为 `clear_files`（只删落盘文件不删 DB）/ `clear_config`（删 DB 业务数据+文件，保留配置表和用户账号）/ `clear_all`（删全部业务数据+文件+普通用户账号，保留 admin）；前端 AdminPage.jsx/adminApi.js 适配；i18n 修复 B94（键名从 dataClearGuests/Users 改为 dataClearFiles/Config）② 公告启用开关从编辑表单移至公告列表操作列（直接调 updateAnnouncement 切换 enabled），移除状态列，表格内容居中（`.admin-ann-table` 类）③ RsVerify.jsx 四乱场景表头改造：classify 场景用结果图/大类/具体类别列 + 详情弹窗，其他场景保持原表头 ④ RsVerify.jsx 场景选择用 localStorage 持久化，刷新页面保持上次选中的场景 |
| 2026-08 | **邮箱设置页两态化 + 更换邮箱先验证旧邮箱 + 验证码提示文案修正**——①修复"验证码已发送（SMTP 未配置时见服务端日志）"误导文案（SMTP 已启用）：`auth.codeSent` 改为"验证码已发送，请查收邮箱（注意垃圾箱）"（zh/en）②邮箱设置页（Profile EmailSection）重构为状态驱动：未绑定 →"绑定邮箱"表单；已绑定 → 显示当前邮箱 + 说明 + "更换邮箱"按钮，不再永远显示表单 ③更换邮箱采用两步验证（用户确认）：新增后端 `POST /api/auth/verify_old_email`（校验旧邮箱收到的 purpose=bind 验证码，一次性），前端更换流程 = 验证旧邮箱（向旧邮箱发码）→ 输入新邮箱 + 新邮箱验证码 → 确认更换；绑定/更换成功后 `auth.refresh()` 经 userEmail 变化自动回到已绑定视图；新增 i18n 键（currentEmail/changeEmail/oldEmail* /verifyAndNext/confirmChange 等 zh/en）；新增 `.profile-email-line`/`.profile-btns` 样式（走主题变量） |
| 2026-08 | **SMTP 发信配置改为 `web/.env` 文件读取**——解决"验证码一直打印 SMTP 未配置"：SMTP 此前只依赖进程环境变量，而 User 级环境变量对 IDE/已运行程序派生的终端不生效，自行启动后端时读不到导致仍打印日志；auth.py 新增 `_load_env_file()`（启动自动读取 `web/.env` 的 KEY=VALUE，进程环境变量优先、.env 兜底），已用**不带任何环境变量**方式启动后端实测验证码真实发送成功；README 更新配置说明；`.env` 含 SMTP 授权码属敏感文件勿提交仓库；已同步 4.8 速查表 |
| 2026-08 | **批次5.8：操作日志操作者显示用户名（B91）**——修复普通用户登录/注册后操作日志"操作者"列显示 device_id（如 `31dc746d-...`）而非用户名：根因是登录/注册/忘记密码请求发生在认证前、尚未携带 token，`log_operation` 只能回退到 device_id；`log_operation` 新增 `operator_username` 参数（优先级：有效 token 解析用户名 > 显式传入 > device_id），auth.py 的 register/login/login_email/forgot 四处认证前动作显式传用户名；验证：新注册+登录后日志 `operator_name` 正确显示用户名（带 token 的请求仍按用户名解析）；历史旧记录不自动回填（可一次性 SQL 回填） |
| 2026-08 | **B92：登录用户 API Key/模型配置重启丢失修复**——根因：B88 修复时在 `_migrate` 中加了无条件 `UPDATE rs_presets/rs_models SET user_id=NULL WHERE user_id=1`（当时 user_id=1 是旧游客幽灵账号），登录体系上线后 user_id=1 变为真实登录用户，每次重启该语句将登录用户全部预设与模型列表重置为游客归属，登录后 `_scope` 按 user_id 过滤查不到；修复：① `app.py _migrate` 删除无条件重置语句 ② `settings.py _ensure_device` 新增 `_migrate_guest_data`，登录用户访问时将该设备的游客记录迁移回用户名下（幂等），经 `reconcile_presets` 同名去重保留带 key 的预设 |
| 2026-08 | **批次5.7：admin 直接创建用户**——后端新增 `POST /api/admin/users`（复用注册的 `_password_ok` 密码策略 + `hash_password`；用户名 3-20 位字母数字下划线、重名/邮箱重复/弱密码/非法用户名校验；可指定 role=user/admin；`must_change_password=0` 创建后可直接登录，与"重置密码"（强制改密）语义区分）；前端用户管理工具栏右侧新增"新建用户"按钮（弹窗：用户名/密码/确认密码/邮箱选填/角色下拉，密码框带显示切换，表单走主题变量）；验证：`_t_batch57.py` 9 项全 PASS（创建/重名/弱密码/非法名/admin 角色/邮箱重复/直接登录/非 admin 403） |
| 2026-08 | **批次5.6：移除"导出我的数据"按钮**——个人资料"数据导出"页移除无用的 JSON 摘要导出（`doExport` 与按钮、i18n `export/exported` 键）；三系统记录数与占用大小统计保留展示；后端 `GET /api/auth/export` 接口保留（供统计展示），README 描述更新为"我的数据统计"；备份/导入 ZIP 流程不变 |
| 2026-08 | **批次5.5：公告表单底行 + 标签持久化修复 + 数据管理统计排版**——①公告新建表单底行改为一行：带"启用"文字的开关（`.switch-text`，knob 固定右侧、状态用背景色区分）+ 确认/取消按钮（`min-width:88px` 等宽、`gap:10px` 留间隙，不再紧贴）②**修复标签栏刷新丢失**：原 `shouldHide` effect 会把无权限标签（profile/admin）从 tabs **移除并保存**，刷新时登录态未就绪导致标签被删后无法恢复 → 改为 `loadTabState` 不再按权限过滤、删除移除 effect，改由渲染层 `visibleTabs` 按当前权限过滤（标签保留在 tabs，登录态恢复后自动重新显示，activeId 无效时回退 home）③数据管理统计卡片"用户/游客/设备"由单行堆叠改为换行显示（系统名一行 + 三项竖排小字）；更新日志同步 |
| 2026-08 | **批次5.4：操作日志工具栏与公告表单细化**——①修复日历弹层"确定"按钮显示为 `common.ok` 原文（zh/en 均缺 `common.ok` 键，已补 zh=确定/en=OK，按钮补 `.btn` 样式不再白底）②开始/结束时间输入框尺寸与动作/操作者对齐（min-width 180px 统一）③操作日志工具栏重排：第一行仅四个筛选输入，第二行"每页条数 + 重置/搜索/清空日志"按钮（重置 = 一键清空全部搜索条件回第一页），不再随页面大小乱排 ④公告内容文本框 `resize: vertical`（禁止横向拉出范围框）⑤公告"启用"由 checkbox 改为开关按钮（复用 `.switch` 功能开关样式） |
| 2026-08 | **批次5.3：前端装饰统一修复（B90）**——①操作日志时间筛选由原生 `datetime-local` 替换为自定义 `DateTimePicker.jsx`（月历弹层 + 时/分下拉 + 清空按钮，弹层圆角/阴影/明暗全走 `--c-*`/`--shadow-*` 主题变量）②系统管理三张表格（用户/公告/日志）套 `.admin-table-scroll` 横向滚动容器（窄屏不溢出，表 `min-width:720px`）③分页"页码"输入框补背景/边框/圆角/focus 装饰、下拉 select 补 `color-scheme` 明暗；并立**前端装饰规范**（见 B90）：任何新增控件必须主题化，原生无法定制的控件一律自实现组件 |
| 2026-08 | **批次5.2：admin 数据管理**——新增 `GET /api/admin/data`（统计：用户数 + 三系统用户/游客记录数与游客设备数）与三个清空接口：`POST /api/admin/data/clear_guests`（清全部游客数据+文件）、`clear_users`（清全部用户数据+文件、账号保留）、`clear_all`（一键清空全部业务数据+普通用户账号+日志，仅保留当前 admin 与公告/开关等管理配置）；`_purge()` 按条件删三库指定表记录并联动删除物理文件（路径去重、删后清理空目录）；前端系统管理新增"数据管理"模块（统计卡片 + 三个清空按钮，危险操作需输入"确认清空"文案才能执行，全部清空按钮红色标记）；验证：`_t_batch52.py` 15 项 PASS（统计/三种清空/文件联动删除/账号保留/保留 admin）+ 浏览器回归（页面渲染/弹窗禁用逻辑） |
| 2026-08 | **批次5.1：体验优化与数据备份恢复**——①密码输入框（登录/注册/忘记/改密/重置）统一加"显示/隐藏"切换（新增 `PasswordInput.jsx`，默认隐藏）②个人资料"数据导出"升级为完整备份：新增 `GET /api/auth/backup`（一个 ZIP = meta.json + detect/smart/rs.json + files/ 全部图片，文件路径列改写为 zip 内相对路径）+ `POST /api/auth/restore`（解压导入，合并追加到当前账号、图片落盘到本设备目录、smart/rs 关联 id 映射重建，无效 zip/超 300MB 拒绝），前端三按钮（导出 ZIP / 导入备份 / 导出 JSON 摘要）+ 说明文案 ③系统公告：勾选框 UI 错位修复（checkbox 被 `input{width:100%}` 撑满）、保存/删除后派发 `announce-changed` 事件热更新顶栏横幅、关闭状态改为**仅内存不持久化**（刷新后公告重现）④操作日志：支持时间范围 from~to、每页条数 10/20/50、页码跳转、`DELETE /api/admin/logs` 手动清空（清空动作记一条新日志）、时间列改为日期/时间两行显示（修复在"8-"后换行）⑤个人资料注册时间改为日期+时间分开显示；验证：`_t_batch51.py` 14 项全 PASS（backup zip 结构/restore 恢复含图片落盘/无效 zip 400/时间范围/每页/清空）+ 浏览器 8 步回归全 PASS |
| 2026-08 | **批次6：游客引导收尾（8.5 定稿落地）**——游客态存在启用公告时显示"📢 系统公告：登录后可查看"浅色细条（点击弹登录框，不展示全文）；登录用户展示最新启用公告横幅（可关闭）；退出登录时右下角全局 toast 轻提示"已退出登录，本设备已切换为游客视图"（3s 自动消失，遵守 B8 不用 alert）；至此 8.5 游客策略全部落地（游客保留全部功能 + 引导横幅可关闭刷新不重现 + 公告登录后查看 + 数据 30 天过期清理 B81 保持）；验证：浏览器 8 步回归全 PASS（游客无公告→admin 建公告→登出 toast→游客提示细条可点击→注册登录见公告全文→登出回游客→三功能页全量回归 Console 干净） |
| 2026-08 | **批次5：admin 系统管理 + 全局日志**——后端新增 `web/admin.py`（`/api/admin/*` 仅 admin：总览 overview（用户数/今日活跃/三系统记录数/开关状态）、用户管理（列表搜索分页/禁用启用/重置密码(下次登录强制改密)/角色调整/删除用户联动清理三系统数据+操作日志脱敏）、功能开关（detect/verify/rsverify/face，`/api/admin/features`）、系统公告 CRUD（公开展示 `/api/announcements` + `/api/features`））；`auth_device.py` 增加 operation_logs（内存队列 max1000 + 后台线程批量写，auth/detect/smart/rs 关键接口接入 auth.*/detect.*/verify.*/rs.*/admin.* 动作点，90 天自动清理）；新增 `feature_gate.py` 纯 ASGI 中间件按路径前缀拦截（开关关闭时游客/普通用户 403+1009，admin 豁免，OPTIONS/管理接口放行）；前端新增 `api/adminApi.js` + `components/admin/AdminPage.jsx`（左侧菜单：总览/用户管理/功能开关/系统公告/操作日志，组件内确认/输入弹窗不用浏览器 confirm/prompt），App.jsx 集成（admin 标签仅管理员可见、顶栏下拉"系统管理"入口、登录用户公告横幅、功能开关关闭时非 admin 隐藏标签）；修复 B89；验证：`_t_batch5.py` 20 项全 PASS + 浏览器 10 步回归（3 处缺陷修复后复验通过） |
| 2026-08 | **批次4.1：个人资料页改版 + 游客系统设置入口**——Profile 改为左侧菜单栏（头像+用户名 + 账号信息/修改密码/邮箱设置/人脸设置/数据导出）+ 右侧内容区（默认账号信息）；数据导出页展示三系统记录数与占用大小（后端 `export` 扩展为返回 count+bytes，按文件路径去重统计）；顶栏游客态恢复"客 未登录"下拉布局（含个人资料[引导登录]/系统设置入口），登录态下拉含"系统管理"（admin）与退出登录 |
| 2026-08 | **批次4：登录体系前端（登录弹窗/顶栏用户区/个人资料页）**——后端补 `POST /api/auth/bind_email`（绑定/更换邮箱，purpose=bind 验证码，验证码一次性）与 `GET /api/auth/export`（导出我的数据：账号信息 + detect/smart/rs 三系统记录摘要 JSON，不含操作日志）；前端：`request()` 扩展（自动携带 Authorization、401 且曾登录时派发 `auth-expired` 事件）；新增 `api/authApi.js`、`auth/AuthContext.jsx`（user/isLoggedIn/isAdmin + auth-changed 事件 + 登录弹窗状态）；`AuthModal`（登录/注册/忘记密码/强制改密四模式，登录方式三 tab：账号密码/邮箱验证码/人脸[远期禁用占位]，注册用户名密码必选+邮箱可选+协议勾选，must_change_password=1 时登录后自动切改密框不关闭）；`Profile` 个人资料页（账号信息/修改密码/绑邮箱/人脸占位/导出我的数据/退出登录）；`App.jsx` 整合（顶栏用户区登录态、游客引导横幅可关闭且刷新不重现、profile 标签仅登录可见、auth-changed 刷新当前页数据、auth-expired 回退游客）；i18n 新增 auth/profile 命名空间（zh/en）；验证：`_t_batch4.py` 后端 12 项接口全 PASS + 浏览器端到端 10/10（注册自动登录/登出回游客/admin 首登强制改密拦截/三功能页回归） |
| 2026-08 | **批次3：登录体系后端**——新增 `web/auth.py`（users/email_codes/tokens 表；注册/登录/邮箱验证码登录/忘记密码/改密/登出/me；PBKDF2 密码哈希 + token 存 sha256 + 30 天滑动过期（5 分钟或写操作刷新）；限速/锁定/强密码策略；SMTP 发送验证码（未配置时打印日志）；后台清理线程；预置 admin/Admin@2026 首登强制改密）；新增 `web/auth_device.py` 双轨身份解析（Bearer token→user_id **忽略 X-Device-Id 防伪造**；无/失效 token→device_id；游客 user_id=None）；detect/smart/rs 三系统查询全部双轨化（scope() 辅助：登录按 user_id 跨设备共享、游客按 `user_id IS NULL AND device_id`，SQL 不写 OR 走索引）；rs 游客预设/模型 user_id=1→NULL 迁移；登录"清除数据"按 user_id、游客按 device_id；修复 B86/B87/B88；验证：`_t_auth.py` 端到端 24 项全 PASS（注册/me/登录/错密/归属/跨设备/游客隔离/登出/admin/rs 预设/迁移/三系统 health）+ 浏览器三页面回归正常 |
| 2026-08 | **批次2：数据库迁移（登录体系数据层预留）**——三平台 7 张数据表（detect_uploads/detect_records、images/pairs/results、rs_images/rs_records）新增 `user_id` 列（INTEGER NULL=游客，与 device_id 并存）+ `(device_id, created_at)` / `(user_id, created_at)` 双轨索引（迁移幂等：PRAGMA 判断列存在再 ALTER + CREATE INDEX IF NOT EXISTS）；三库开启 WAL（PRAGMA journal_mode=WAL，持久生效）；rs_presets/rs_models 的 user_id=1 游客语义迁移推迟到批次 3（与查询逻辑改造同步，避免游客查不到预设）；验证：7 表列/索引/WAL 全通过、三系统接口正常 |
| 2026-08 | **批次1：接口统一响应格式 {code,msg,data}**——后端新增 `api_envelope.py`（纯 ASGI 中间件包装 JSON 响应 + 404/500 异常处理；流式 NDJSON / 图片 / Excel 下载透传不包装），主应用 `install`、smart/rs 子应用 `install_errors`；前端新增 `src/api/index.js` `request()` 统一封装（自动带 X-Device-Id、解包 data、code≠0 抛 Error(msg)），detectApi/smartApi/rsApi 统一走它；浏览器回归三页面正常、同名幂等与前端去重不受影响（B85） |
| 2026-08 | 修复 B84：上传列表表头勾选框显示浏览器默认蓝白色 → index.css 补 `.detect .upload-table th input[type="checkbox"]`（17px + `accent-color: var(--c-primary)`），与结果表表头/数据行 checkbox 装饰一致 |
| 2026-08 | 修复 B83：图像篡改上传列表仍可无限添加同名文件（B82 后端幂等后重复上传返回已有 id，但前端 append 不去重导致列表重复）→ `addUploads` 按 id 去重合并（闭包过滤 + updater 兜底），重复文件跳过并以**右下角 toast** 提示 `detect.dupSkipped`（新增组件内轻提示机制，3s 自动消失，不用浏览器 alert）；新增 i18n 键（zh/en） |
| 2026-08 | 修复 B82：图像篡改上传列表状态不恢复（识别后刷新仍显示"待检测"导致重复检测）+ 上传无去重 → 后端 `GET /api/detect/uploads` 返回 `done` 标记（按本设备 detect_records.file 集合判定）；前端恢复列表 `status: it.done ? "完成" : "待检测"`（startDetect 自动跳过已完成）；`POST /api/detect/upload` 按 (device_id, filename) 幂等查重，重复上传返回已有记录不重复落盘 |
| 2026-08 | B81：游客数据 30 天过期清理（detect/smart_verify/rs_verify 各自后台守护线程，每 6h 按设备最近 created_at 判定，超期调各自 cleanup 联动删文件与目录）；删除废弃 `frontend/src/api/db.js`（检测 IndexedDB 缓存已全部走后端）；文档第七章清理为"已完成"摘要并新增"八、后续规划" |
| 2026-08 | 修复 B80：遥感上传面板显示浏览器历史缓存的旧文件（未上传却有文件）→ 移除 IndexedDB 草稿缓存（rs_upload_cache），改为与点位核验一致：新增后端 `GET /rsverify/api/images/list`（当前设备已上传图片）+ `rsApi.getUploadedImages()`，页面加载 `restoreImages` 从后端恢复；**未上传的本地草稿刷新不再保留**（体验变化） |
| 2026-08 | 修复 B79：删除上传/结果后残留空设备文件夹（detect_uploads/或 detect_results/ 下 `<device_id>/`）→ 新增 `_rmdir_if_empty`，删除后目录为空则 rmdir（上传删除与结果删除接口均调用） |
| 2026-08 | 修复 B78：设备隔离后图片 404（`<img>` 无法带 X-Device-Id 头）→ 图片 URL 携带 `?dev={device_id}`，后端图片接口优先取 query dev；detect 后端生成 URL 拼 dev，前端 smartApi/rsApi 的 imageUrl/visUrl/uploadImageUrl 拼 dev；另：图像篡改上传/结果列表双击行勾选（排除勾选列/操作列） |
| 2026-08 | 修复 B77：系统设置篡改检测占用显示字面 `{{results}}`/`{{uploads}}`（i18n 文案键名改了但 t() 仍传 items，键不匹配不替换）→ 插值改传 results/uploads + usage 初始 state 同步 |
| 2026-08 | B76：游客设备隔离（三平台统一后端存储 + X-Device-Id 隔离）。前端 deviceId.js（localStorage `aigc_device_id`）三 API 模块带头；点位/遥感表加 device_id + 迁移 + 全部路由按设备过滤（游客"清除所有"只清本设备）；图像篡改从 IndexedDB 迁后端（detect_uploads/detect_results 落盘 + detect_records 扩展 + 上传/结果/删除/清空/统计接口，删除联动删文件无落盘）；遥感预设/模型按 (user,device) 隔离（云端 API 私有，本地模型能力全局共享，get_settings 首次访问自动建默认预设）；系统设置占用/清除改为"当前设备"；旧数据已清空；注意：SQLAlchemy Core Row 需 `r._mapping["col"]`（`r["col"]` 报 tuple 索引错）、PRAGMA 列名取 `r[1]`、迁移用 `engine.connect()`（2.0 无 `engine.execute`） |
| 2026-08 | B75：GPU 显存占用检测 + 任务入口防爆（model_manager 新增 gpu_memory/gpu_free_too_low，检测/点位核验/遥感核验入口显存<1.5GB 抛 507 阻止；/api/models 返回实际显存；系统设置新增 GPU 显存实时展示 5s 轮询；说明 TruFor 为子进程型任务跑完即释放） |
| 2026-08 | B74：点位核验模型（SuperPoint+LightGlue）GPU 显存常驻 3.2GB → model_manager 新增空闲自动卸载（后台守护线程 + `get(..., idle_timeout)`）；点位核验核验完立即卸载（单对/批量/选中端点锁内 unload，批量跑完再卸不逐对重载）+ 60s 兜底；`_release_gpu` 增强 del+gc+empty_cache |
| 2026-08 | B72-B73：结果/导出记录"使用模型"（web rs_records 加 model_used 列+迁移，analyze/rerun 写入，结果表与导出 Excel 加"模型"列；CLI reporter 的 Excel 加"模型"列，rs_verify/run 从 config.yaml 写入每条）；遥感页双栏加宽 + 中间圆形一键交换按钮（UploadPanel 暴露 replaceFiles，交换动画：按钮旋转 + 面板滑出淡出/滑回淡入） |
| 2026-08 | B62-B71：web 端本地模型落地（API 类型"本地模型"真实可用，参数自动读 config.yaml 只填模型名）；local_model_name 与云端 model_name 拆分独立（rs_presets 迁移加列）；设置页"加载中"2s 根除（get_settings 不再实时拉 Ollama，改"从服务器获取模型"手动按钮 + GET /rsverify/api/local/models）；本地模型下拉自定义美化（复用 .smart-dropdown 圆角阴影）；获取列表 localStorage 缓存刷新不丢；i18n 插值 {{n}} 语法纠正；number 输入框隐藏原生调节按钮；本地获取成功提示不再误导"已同步到数据库"（本地列表不落库）；取消 LLM 失败重试（retries 1→0，失败直接记录继续下一对）；run.py 新增 RANDOM_SEED 固定抽样 + OUTPUT_DIR 冒号 WinError 123 防护 |
| 2026-08 | B60-B61：本地 4B 模型（qwen3-vl:4b）空响应失败 50-70% → 失败自动重试 1 次 + 失败原因细分 + Excel 记录失败行 + 批量失败清单；换 qwen2.5vl:7b 后批量 10/10 成功（8GB 显存甜点位） |
| 2026-08 | 修复 B59：本地 Ollama 调用 400（webp 无法解码）→ `_encode_image` 对 webp 强制转 JPEG；支持本地 Ollama（OpenAI 兼容 /v1）配置方式 |
| 2026-08 | 修复 B58：遥感页核验后上传预览图消失（markUploaded 误用 smart 图片服务）→ 新增 /rsverify/api/uploads/{image_id} 上传原图接口 + 遥感页传 imageUrlFn |
| 2026-08 | 修复 B57：清空结果/清空上传列表真正删除 rs_uploads 图片与 rs_work 目录（后端删除记录时清理孤儿上传图、清空全部时 rmtree 重建目录 + 清 rs_images；前端上传后回写面板 id、清空面板调 DELETE /images/{id}）；排查 8000 端口旧进程占用 |
| 2026-08 | 修复 B56：结果表缩略图 hover 持续闪烁（img 本体 fixed 导致 hover 反复触发）→ 独立预览层（.thumb-zoom + CSS 变量 ::after），遥感/点位核验同步 |
| 2026-08 | 修复 B54-B55：rich gbk 编码报错根除（rs_verify.py 非 tty 强制 UTF-8；并排查 8000 端口旧进程占用导致新代码未生效）；核验失败落盘清理（前端失败调 DELETE /images/{id} 清已上传图、后端 _run_analysis 失败删 work_dir；新增删除上传图片接口） |
| 2026-08 | 修复 B50-B53：切换模式清除勾选残留；拖动文件窗口抖动（drop-line 绝对定位）；rich 输出 gbk 编码报错（子进程 PYTHONIOENCODING=utf-8）；顺序匹配按钮文案恒"开始核验" + 重复点击跳过已核验对 + 结果表操作列新增"重新核验"（后端 /analyze/{id}/rerun 覆盖记录并清理旧产物） |
| 2026-08 | 修复 B45-B49：上传列表编号徽标移到勾选框前；功能设置保存按钮闪烁（轻量刷新不重建表单）；遥感页清空按钮失效与"已选 N"常驻显示（清空支持本地直清 + 面板按模式显示"清空/共 N 张"）；未配置 Key 预设仍能进入检测且全失败显示"完成(0对)"（开始前校验配置 + 全失败 error 提示）；系统设置一键清理后统计误显示"后端未连接"（清理后重新拉取统计） |
| 2026-08 | 遥感页批量升级：双面板上传 + 缩略图列表（拖拽排序/IndexedDB 缓存刷新不丢）、顺序匹配/选择比对（多选点击编号 1,2,3 按编号配对）、批量逐对核验 + 进度条、开始按钮自动变"核验选中 (N)"、无匹配禁用；点位核验"单点比对"同步为"选择比对"（按编号顺序配对）；结果列表双击行勾选（排除勾选/操作列）+ 禁复制 + hover 预览固定中央不撑滚动条 + 场景列不换行；系统设置全局清理接入遥感核验（stats/reset + rsverify-cleared 事件）；CLI `--no-excel` + web_bridge 中转文件移临时目录（rs_work 仅留标注图）；Remote_sensing/run.py 批量检测（数字对匹配、BATCH_COUNT 预设 50 对、逐对循环）；记录 B38-B44 |
| 2026-08 | 遥感变化核验（rsverify）功能页集成：FastAPI 子应用挂载 /rsverify + Remote_sensing web_bridge 子进程调用（算法更新自动跟随）；前端功能页 + 右上角"功能设置"弹窗（预设平台/联网获取模型列表/api_key AES 加密落库/配置状态回显）；记录 B20-B28 踩坑 |
| 2026-08 | 合并 ADD_NEW_SYSTEM + BUGS_NOTES；新增 i18n 国际化、主题系统、语言切换、全局清理等基础设施文档 |
| 2026-08 | 首次拆分（ADD_NEW_SYSTEM.md + BUGS_NOTES.md） |

