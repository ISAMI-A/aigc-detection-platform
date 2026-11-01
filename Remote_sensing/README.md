# 遥感变化核验工具（Remote Sensing Change Verification）

基于多模态大模型的遥感影像变化核验 CLI 工具。用户输入两张同一地点的卫星图，大模型自动对比分析框内区域的变化情况。
同时支持单图检测（classify）：输入一张带标注框的卫星图，自动识别框内区域的 大类（乱占/乱采/乱堆/乱建/其他问题/无）、具体类别与图像特征描述。

---

## 技术方案详解（简历/汇报素材）

### 1. 系统定位

基于**多模态大模型（VLM）** 的遥感影像变化核验系统：河湖监管场景下，输入
带人工标注框的两期卫星图，自动判定框内区域"新增构筑物（乱占乱建）/ 已拆除恢复 /
四乱分类"，替代人工目视解译。属于"大模型 + 垂直业务"的工程化落地：不训练模型，
核心工作在**提示工程、图像工程、推理可靠性、多平台适配**四个层面。

### 2. 三种分析场景（一套框架复用）

| 场景 | 输入 | 输出 | 典型用途 |
|---|---|---|---|
| detect | 新旧两期图 | 是否新增人工构筑物 | 新增违建发现 |
| verify | 整改前后两期图 | 构筑物是否已拆除/恢复 | 整改核验闭环 |
| classify | 单图 | 大类（乱占/乱采/乱堆/乱建/其他/无）+ 具体类别 + 特征描述 | 四乱巡检分类 |

三场景共用同一套图像编码、API 客户端、JSON 解析与报告管线，仅 prompt 模板不同。

### 3. 提示工程（抑制大模型幻觉的结构化设计）

Prompt 采用**角色设定 → 三步分析法 → 优先级判定规则 → 最终自检**的层级结构：

```
[角色] 你是遥感影像变化检测专家……只依据框内可见证据判断
[三步法] ① 判断影像环境（植被茂密/冬季枯黄/城市/乡村/水岸）
        ② 观察框内目标特征（大小/形状/颜色/阴影/纹理）
        ③ 与基准图对比变化
[判定规则] 优先级从高到低：明显新增人工构筑物 → 原有构筑物仍在 →
          植被自然变化（排除误判）→ 无明显变化
[自检] 结论与依据必须一一对应；依据不足时宁判"无明显变化"，禁止臆测
```

设计要点：

- **环境前置判断**抑制"旧图发黄/季节变化"被误判为新增违建的经典错误；
- **优先级判定**给模型明确的决策顺序，避免倾向性回答；
- **宁枉勿纵反转**（证据不足判"无变化"）符合监管业务"不能冤枉已整改点位"的要求；
- **结论-依据对应**约束输出结构化 JSON，为可解释性打底。

### 4. 图像编码工程（体积/速度/细节三角权衡）

VLM 的图像输入有隐式 token 成本（每图按分辨率切 patch 计费），编码策略直接影响
延迟、成本与识别精度：

| 情况 | 处理 | 理由 |
|---|---|---|
| 小图（<150KB） | 原样发送 | 无压缩损失，成本可控 |
| WebP 格式 | 转 JPEG q95 | 部分平台 API 对 WebP 兼容性差 |
| 大图 | 等比缩放至 1600px + JPEG q85 | 兼顾标注框内小目标细节与 token 成本 |

关键技术决策：缩放阈值取 **1600 而非常见的 1024**——标注框可能只占图像很小区域，
过度缩放会让框内小目标（如单栋违建）低于模型分辨率下限；经实测 1600px 在
q85 压缩下单图约 200~400KB，多数平台 token 成本可接受。

### 5. 推理可靠性工程

#### 5.1 JSON 容错解析（三级降级）

```
直接 json.loads → 失败 → 提取 ```json 代码块再解析 → 再失败 → 正则抓取最外层 {} → 仍失败则记为解析错误
```

失败时附带**诊断信息**（finish_reason / usage / reasoning 长度），可快速定位
"截断（finish_reason=length）"还是"模型输出跑偏"。

#### 5.2 多平台参数适配矩阵

直连 OpenAI 兼容 API 时，各家实现细节差异是隐蔽的坑，统一在客户端层适配：

| 平台 | 特殊参数 | 坑点 |
|---|---|---|
| Kimi (moonshot) | `max_completion_tokens` | 已弃用 `max_tokens` 会报错 |
| Kimi kimi-k2.6 | `thinking: {type: disabled}` | 默认开思考模式，会吃掉 completion 预算 |
| Qwen3 系列 | `enable_thinking=false` / think 参数 | 思考 token 同样占用预算 |
| 通用 | `temperature=0` | 关闭随机性，保证同图判定可复现 |

#### 5.3 网络层稳健性

- **httpx 直连**而非 openai SDK：① 规避 SDK 注入 Authorization 头的代理冲突；
  ② `trust_env=False` 隔离系统代理（内网/科学上网环境误劫持 API 流量）；
  ③ 显式连接/读超时控制，批量任务不悬挂。

### 6. 批量任务工程

- **四种运行模式**：single（单组）/ random（随机抽样）/ seq（区间顺序）/ group（指定编号组），
  适配试点验证、全量普查、复检定位不同工作流；
- **Excel 累积追加报告**：断点续跑不重算，多次运行结果合并到同一报告；
- **标注对比图**：两期影像 + 红框标注 + 结论文字栏合成单图，人工复核一眼定位；
- **失败重试与跳过**：单图失败不中断批任务，失败项单独汇总便于补跑。

### 7. Web 集成（web_bridge 子进程桥接）

Web 后端通过 `web_bridge.py` 以**子进程 + JSON 中转**方式调用本模块：
主 Web 进程不加载 VLM 相关依赖，算法进程崩溃不影响 Web 服务，
结果以标准 JSON 协议回传（状态码 + 结论 + 依据 + 标注图路径）。

---

## 工作流程

```
输入两张卫星图（图片自带人工标注框）
        │
        ▼
  ┌─────────────────┐
  │  场景 A: detect   │  检测框内是否出现新增人工构筑物
  │  场景 B: verify   │  核验构筑物是否已拆除、恢复绿植/空地
  │  场景 C: classify │  单图检测：大类/具体类别/图像特征描述
  └─────────────────┘
        │
        ▼
  多模态大模型分析（OpenAI 兼容 API）
        │
        ▼
  生成输出：
  ├── Excel 汇总表（累积追加，含原图/标注图嵌入）
  ├── 标注对比图（两期影像 + 分析结论）
  └── 终端结构化摘要
```

---

## 技术栈

| 模块 | 库 | 用途 |
|:---|:---|:---|
| CLI 入口 | `argparse` | 命令行参数解析 |
| 终端输出 | `rich` | 彩色进度、表格、面板 |
| LLM 调用 | `openai` SDK | OpenAI 兼容多模态 API |
| 本地模型 | `transformers`（预留） | Qwen2-VL 等本地 VL 模型 |
| 图像处理 | `Pillow` (PIL) | 标注图生成、缩略图 |
| Excel | `openpyxl` | 报告生成、图片嵌入 |
| 配置 | `pyyaml` | YAML 配置读写 |

**安装依赖：**
```bash
pip install openai pillow openpyxl pyyaml rich
```

> 本地模型（可选）：`pip install transformers torch accelerate`

---

## 项目结构

```
Remote_sensing/
├── run.py              # 启动器（推荐入口，顶部配置区改路径即可）
├── rs_verify.py        # CLI 主入口（typer，支持完整命令行参数）
├── web_bridge.py       # Web 集成桥接层（供 web 后端 import，子进程调用 CLI）
├── config.yaml         # LLM API 配置文件
├── requirements.txt    # Python 依赖清单
├── core/
│   ├── __init__.py
│   ├── analyzer.py     # 大模型分析器（API + 本地模型预留）
│   ├── viz.py          # 可视化（标注对比图）
│   └── reporter.py     # Excel 报告生成（累积追加）
├── output/             # 默认输出目录
└── README.md           # 本文档
```

---

## 快速开始

### 1. 配置 API

编辑 `config.yaml`，填入你的 API 信息：

```yaml
llm:
  api: openai
  openai:
    base_url: https://api.openai.com/v1          # API 地址
    api_key: sk-your-api-key-here                # API Key
    model_name: gpt-4o                           # 模型名称
    max_tokens: 2000
    temperature: 0.2
```

支持所有 OpenAI 兼容 API（GPT-4o、DeepSeek-V3、通义千问-VL 等）。

### 2. 运行

**方式一：启动器（推荐）**

编辑 `run.py` 顶部配置区，然后直接运行：

```bash
python run.py
```

**方式二：CLI 命令**

```bash
# 场景A：新增构筑物检测
python rs_verify.py detect -b 旧图.webp -a 新图.webp

# 场景B：整改核验
python rs_verify.py verify -b 整改前.webp -a 整改后.webp

# 场景C：单图检测（大类/具体类别/图像特征描述）
python rs_verify.py classify -i 单图.png

# 指定输出目录
python rs_verify.py detect -b 0t.webp -a 0.webp -o ./my_results/

# 指定配置文件
python rs_verify.py detect -b 0t.webp -a 0.webp -c ./other_config.yaml
```

---

## 配置说明

### `run.py` 配置区（第 26-43 行）

| 参数 | 默认值 | 说明 |
|:---|:---|:---|
| `SCENARIO` | `detect` | 任务场景：`detect` / `verify` / `classify` |
| `BEFORE_PATH` | `..\data\...\2t.webp` | Before 图片路径（单对模式用） |
| `AFTER_PATH` | `..\data\...\2.webp` | After 图片路径（单对模式用） |
| `IMAGE_PATH` | `..\data\点位测试图\0.png` | 单图检测图片路径（classify 单张模式用） |
| `OUTPUT_DIR` | `data\output_test_Remotesensing` | 输出目录 |
| `CONFIG_PATH` | `./config.yaml` | LLM 配置文件路径 |
| `BATCH_MODE` | `True` | `True`=批量模式 / `False`=单对模式 |
| `BATCH_COUNT` | `50` | 批量检测数量（单位：对），预设 50 对 |
| `BATCH_DIR` | `..\data\点位测试图` | 批量图片文件夹（留空则用 BEFORE_PATH/IMAGE_PATH 所在目录；classify 时收集文件夹内所有图片逐张检测） |

路径支持相对路径和绝对路径。

### 批量匹配规则

文件夹内按文件名数字自动配对：`0t` ↔ `0`、`1t` ↔ `1` ……（`t` 后缀为旧图/整改前）。
- `detect` 顺序：before=`Nt` → after=`N`
- `verify` 顺序：before=`N` → after=`Nt`

批量模式从全部匹配对中**随机抽取** `BATCH_COUNT` 对（无放回），每次只发送一对图，逐对循环检测，所有对结果累积追加到同一个 `results.xlsx`。

命令行也可覆盖批量参数：
```bash
python run.py --batch --count 100 --dir "../data/整改前图片_processed"
python run.py --batch --count 50 --scenario verify
```

### `config.yaml` 配置项

| 参数 | 默认值 | 说明 |
|:---|:---|:---|
| `llm.api` | `openai` | API 类型：`openai`（兼容 API）、`local`（本地模型，预留） |
| `llm.openai.base_url` | `https://api.openai.com/v1` | API 地址 |
| `llm.openai.api_key` | — | API Key（必填） |
| `llm.openai.model_name` | `gpt-4o` | 模型名称 |
| `llm.openai.temperature` | `0.2` | 生成温度（越低越确定） |
| `llm.openai.max_tokens` | `2000` | 最大输出 token |

---

## 输出说明

### Excel 汇总表

运行后生成 `output/results.xlsx`，每次运行**累积追加**一行：

| 列 | 内容 |
|:---|:---|
| 序号 | 自增编号 |
| Before / After 文件名 | 原图文件名 |
| 场景 | 新增构筑物检测 / 整改核验 |
| 检测时间 | 时间戳 |
| 主要结论 | 摘要（如"存在新增建筑物"） |
| 置信度 | 0.0-1.0 |
| 详细分析 | LLM 分析推理全文 |
| 整改评分 / 通过状态 | 仅 verify 模式 |
| 构筑物类型 | 仅 detect 模式 |
| 原图 Before / After | 缩略图嵌入 |
| 对比图 | 标注对比图嵌入 |

单图检测（classify）另生成 `results_classify.xlsx`（独立文件，与双图结果不混用）：

| 列 | 内容 |
|:---|:---|
| 序号 | 自增编号 |
| 文件名 | 原图文件名 |
| 场景 | 单图检测 |
| 模型 | 使用的 LLM 模型 |
| 检测时间 | 时间戳 |
| 大类 | 乱占/乱采/乱堆/乱建/其他问题/无 |
| 具体类别 | 对应大类的关键词（如垃圾堆放、植被） |
| 图像特征描述 | LLM 输出的图像特征描述（不超过 100 字） |
| 标注图 | 带文字描述的单图标注图嵌入 |

标注图同时落盘到 `images/` 目录（供放大查看），Excel 中嵌入缩略图。

### 标注对比图

`output/images/` 下生成一张带结论的标注对比图（两期影像并列 + 底部 LLM 分析结论，用于人工复核）：

- `{before}_vs_{after}_annotated.png`

---

## 两种场景说明

### detect — 新增构筑物检测

```
旧时卫星图（框内无构筑物） → 现在卫星图（框内可能有新增构筑物）
```

大模型判断框内是否出现了新增的人工构筑物（建筑物、厂房、硬化地面、大棚、围墙、道路等）。

### verify — 整改核验

```
整改前卫星图（框内有构筑物） → 整改后卫星图（框内应已恢复绿植/空地）
```

大模型判断构筑物是否已拆除、拆除区域是否恢复为绿地或空地，给出整改评分（0-100）。

### classify — 单图检测

```
单张卫星图（框内可能有四乱问题） → 大类/具体类别/图像特征描述
```

大模型直接对**原图**分析（不再裁剪红框放大，避免注意力被放大图带偏；webp 自动转高质量 JPEG 发给本地模型），识别框内目标、客观描述其颜色/形状等视觉特征，再判定是否符合四乱问题或其他违法违规行为，按 6 大类输出：

| 大类 | 说明 |
|:---|:---|
| 乱占 | 非法占用水域滩地等占用行为（具体类别由模型自行判断） |
| 乱采 | 非法采砂等 |
| 乱堆 | 在河湖管理范围内堆放、倾倒废弃物、物料等 |
| 乱建 | 河道内/河滩上违建房屋、大棚、围堤、码头等人工构筑物 |
| 其他问题 | 其他违法违规问题 |
| 无 | 植被、裸地等无四乱问题 |

> 具体类别（`specific_category`）不再预置枚举，由大模型根据图像特征自由判断描述；`feature_description` 为客观特征描述，用于人工复核模型识别能力。

---

## 设计规范

### 架构原则

- **接口预留**：`analyzer.py` 中 API 和本地模型共用同一接口，切换只需改配置项 `llm.api`
- **累积输出**：Excel 累积追加而非覆盖，适合批量处理场景
- **自包含**：图片嵌入 Excel，不依赖外部文件链接
- **静默保存**：分析结论自动写入，无需手动确认

### 大模型调用规范

- 图片以 base64 data URL 编码传入，支持 png/jpg/webp
- Prompt 明确要求只分析框内区域
- LLM 输出要求 JSON 格式，带 fallback 正则提取
- Temperature 设为 0.2，降低随机性保证一致性

### 兼容性

- 支持 OpenAI 兼容 API（GPT-4o、DeepSeek-V3、通义千问-VL、本地 Ollama 等）
- 图片格式：PNG、JPG、WebP、BMP
- Excel 兼容 Microsoft Excel 和 WPS

---

## 批量处理

`run.py` 已内置批量模式（`BATCH_MODE = True`）：自动匹配文件夹内数字图片对，**每次只发送一对图**，逐对循环检测，全部结果累积追加到同一个 `results.xlsx`。

```bash
# 直接用配置区的参数批量检测（默认 50 对）
python run.py

# 命令行覆盖数量与文件夹
python run.py --batch --count 221 --dir "../data/整改前图片_processed"
```

或直接调用 CLI（保留 `--no-excel` 可跳过 Excel 落盘）：
```bash
python rs_verify.py detect -b 0t.webp -a 0.webp -o ./batch_output
```

classify 批量（文件夹内所有图片逐张检测）：
```bash
python run.py --scenario classify --batch --count 50 --dir "../data/点位测试图"
python rs_verify.py classify -i 单图.png -o ./single_output
```

---

## 打包分发（给其他人）

本项目独立可分发，**不附带 web 项目内容**。打包内容：

```
Remote_sensing/           ← 整个目录压缩分发即可
├── run.py / rs_verify.py
├── web_bridge.py
├── config.yaml           ← 空 api_key 模板（见下）
├── requirements.txt
├── core/
├── README.md
└── 计划.md（可选）
```

**分发前处理：**
1. `config.yaml` 中的 `api_key` 清空为 `sk-your-api-key-here`（或让接收方自行填写）
2. 删除运行产物：`output/`、`data/`、`__pycache__/`、`*.pyc`

**接收方安装：**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py   # 先改 run.py 顶部路径 + config.yaml 的 api_key
```

**依赖说明**：LLM 调用走 OpenAI 兼容 API（网络请求），本工具自身**不需要 GPU**；仅当使用本地模型（`llm.api: local`）时才需额外安装 transformers + torch。

---

## Web 集成（web 平台调用）

`web_bridge.py` 是桥接层：**web 后端只 import 本模块**，内部通过子进程调用 `rs_verify.py` CLI。Remote_sensing 算法更新后，web 无需改动即可自动跟随。

**调用约定：**
```python
import sys
sys.path.insert(0, r"<Remote_sensing 绝对路径>")
from web_bridge import RemoteAnalyzer

analyzer = RemoteAnalyzer(rs_dir=r"<Remote_sensing 绝对路径>")
result = analyzer.analyze(
    before="旧图路径", after="新图路径",
    scenario="detect",          # 或 "verify"
    config={                    # 可选：覆盖 LLM 配置（不传则用 config.yaml 默认）
        "api": "openai",
        "base_url": "...",
        "api_key": "...",       # web 侧解密后的 key
        "model_name": "...",
    },
    work_dir=r"<web 输出目录>",
)
```

**要点：**
- **不修改 `config.yaml`**：web 传入自定义配置时，`web_bridge` 生成临时配置文件（含解密后的 api_key），子进程调用结束后**立即删除**
- **不落盘冗余产物**：中转 JSON 与临时配置放系统临时目录、读取后即删；CLI 以 `--no-excel` 跳过 Excel 写入（web 结果在前端展示并自行导出，无需 CLI 侧 results.xlsx）；`work_dir` 只保留标注对比图（web 前端展示用）
- 分析完成返回结构化 JSON：`result.result`（LLM 结论）、`result.annotated_image`（标注图）、`result.conclusion`（摘要）
- CLI 侧新增 `--json-out` 参数支持结构化输出、`--no-excel` 跳过 Excel，web 版本直接使用

**版本更新约定**：Remote_sensing 发布新版本 → 替换 `web/../Remote_sensing` 目录（或更新子模块引用）→ web 功能自动跟随新逻辑。

**模型列表（web 功能设置页）**：web 通过后端代理请求 `GET {base_url}/models`（OpenAI 兼容标准端点）联网获取模型名称列表，**按 base_url 隔离持久化**（各平台只显示自己获取的模型）；`COMMON_MODELS` 静态兜底列表（本文件 `web_bridge.py` 顶部，可自行增删，更新后 web 自动跟随）供"添加模型"表单选择。
