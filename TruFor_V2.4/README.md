# TruFor 图片篡改检测工具（V2.4 发布版）

基于 **TruFor（CVPR 2023）** 的图片篡改检测工具：

- 输入任意图片或目录（相对/绝对路径），自动识别配对模式或通用单图模式
- 多级后处理管线可开关：画笔标注降级 / 边缘误检降级 / 散点噪声 / 深红区升判
- 多种输出格式可选：**终端文本 / JSON / Excel（含/不含图）/ 图片落盘**

---

## 项目结构

```
TruFor_V2.4/
├── run.py                   # 主入口（通用单图 + 配对对比自动识别）
├── trufor_pair.py           # 判定核心引擎（judge/loc_stats/热力图/分析图/Excel）
├── calibrate.py             # 网格搜索校准脚本（终端用户无用可删除）
├── config.py                # 全局配置
├── requirements.txt         # Python 依赖
├── README.md                # 本说明
├── modules/
│   ├── forgery_detector.py  # TruFor 子进程推理
│   ├── image_preprocess.py  # 图片预处理
│   ├── exif_analyzer.py     # EXIF 元数据分析
│   └── geometry_analyzer.py # 连通域几何特征
└── trufor/                  # TruFor 模型源码 + 权重（~268MB）
```

---

## 环境准备

> **注意：本项目不包含 `.venv` 虚拟环境，所有依赖需要自行配置安装。**

```powershell
# 1. 安装 Python 3.9+（推荐 3.11）

# 2. 创建虚拟环境（在项目目录内）
cd TruFor_V2.4
python -m venv .venv
.venv\Scripts\activate

# 3. 安装 PyTorch（有 NVIDIA 显卡，CUDA 11.8）
pip install torch==2.3.0+cu118 torchvision==0.18.0+cu118 --index-url https://download.pytorch.org/whl/cu118

# 无独显 / 仅 CPU：
# pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 4. 安装其他依赖
pip install -r requirements.txt
```

> 若 `.venv` 建在项目目录内，`run.py` 会自动查找并使用，无需手动激活。

---

## 配置说明（`run.py` 顶部）

所有配置在 `run.py` 开头，分为四个区，修改后保存即可生效：

### 检测功能开关（不建议关闭，影响识别准确率）

```python
ENABLE_BRUSH_DETECTION = True   # 画笔标注降级检测
ENABLE_EDGE_DETECTION = True    # V2.4 边缘误检降级检测
ENABLE_SPOT_DETECTION = True    # 散点噪声降级检测
ENABLE_SUSPECT_UPGRADE = True   # 深红区疑似升判
```

### 输出模式开关

```python
OUTPUT_TERMINAL = True   # 终端文本输出（始终输出进度+结果摘要）
OUTPUT_JSON = False      # 输出 JSON 文件
OUTPUT_EXCEL = True      # 输出 Excel 表格
SAVE_IMAGES = False      # 图片落盘（热力图/分析图保存为独立 PNG）
```
模型检测过程中产生缓存已设置即用即删，不会有临时文件落盘，无需手动清理。

### Excel 图片嵌入开关（`OUTPUT_EXCEL=True` 时生效）

```python
ENABLE_ORIGINAL_IMAGE = True  # Excel 中嵌入"原图/P图"列
ENABLE_HEATMAP = True         # Excel 中嵌入"热力图"列
ENABLE_ANALYSIS_IMAGE = True  # Excel 中嵌入"分析图"列
```

### 常用输出组合

| 场景 | OUTPUT_JSON | OUTPUT_EXCEL | SAVE_IMAGES | 图片开关 |
|:---|:---|:---|:---|:---|
| 仅终端文本 | False | False | False | - |
| 终端 + JSON | True | False | False | - |
| Excel 全量（含所有图） | False | True | False | 全 True |
| Excel 去掉分析图 | False | True | False | `ENABLE_ANALYSIS_IMAGE=False` |
| Excel 去掉热力图 | False | True | False | `ENABLE_HEATMAP=False` |
| Excel 去掉原图 | False | True | False | `ENABLE_ORIGINAL_IMAGE=False` |
| Excel 仅文本（无任何图） | False | True | False | 全 False |
| 图片落盘 | 任意 | 任意 | **True** | - |

### 参数配置区

| 参数 | 默认值 | 说明 |
|---|---|---|
| `THRESHOLD` | 0.35 | 篡改判定阈值：概率≥该值 → "是" |
| `THRESHOLD_HIGH` | 0.60 | 篡改等级"高"阈值 |
| `THRESHOLD_MED` | 0.35 | 篡改等级"中"阈值 |
| `FUSE_PEAK` | 0.70 | 融合判定：热力图峰值阈值 |
| `FUSE_AREA` | 0.05 | 融合判定：热力图区域占比阈值 |
| `COMP_RATIO` | 0.005 | 散点噪声：最大成片占比下限 |
| `COMP_N_SPOTS` | 16 | 散点数量下限 |
| `GEOM_RECT` | 0.25 | 画笔降级a：矩形度阈值 |
| `GEOM_SOLID` | 0.30 | 画笔降级a：紧致度阈值 |
| `GEOM_MIN_AREA` | 200 | 画笔降级：面积下限（px） |
| `GEOM_LOC_THR` | 0.75 | 画笔降级b：深红线状 loc 阈值 |
| `GEOM_LINE_RATIO` | 0.50 | 画笔降级b：线状面积占比阈值 |
| `SUSPECT_LOC_THR` | 0.75 | 疑似仲裁：深红区 loc 阈值 |
| `SUSPECT_UP_THR` | 0.01 | 疑似仲裁：深红区占比分界 |
| `EDGE_BAND` | 0.10 | 边缘误检：边缘带宽度 |
| `EDGE_TOUCH_RATIO` | 0.90 | 边缘误检：贴边占比阈值 |
| `EDGE_BAND_RATIO` | 0.50 | 边缘误检：边缘带红色占比 |
| `MAX_SAMPLES` | 0 | 随机抽样数量（0=全量） |

---

## 使用方法

```powershell
# 配对目录（数字.png + 数字p.jpg）
python run.py -dir "配对图片目录"

# 单张图片
python run.py -dir "任意图片.jpg"

# 目录批量（递归子目录，不做配对）
python run.py -dir "图片目录" -o output_trufor

# 随机抽样
python run.py -dir "图片目录" --max-samples 100

# 命令行覆盖阈值
python run.py --threshold 0.5 --peak 0.7 --area 0.05
```

---

## 判定规则

```
篡改概率 >= THRESHOLD → "是（有篡改痕迹）"
  → [画笔标注降级] 热力图呈线状弧线 → "否（画笔标注）"
  → [边缘误检降级] 红色完全贴边 → "否（边缘误检）"
否则 峰值>=FUSE_PEAK 且 面积>=FUSE_AREA → 疑似候选：
  → [散点噪声降级] 无成片 → "否（散点噪声）"
  → [深红区升判] 深红区占比达标 → "是"
  → [深红区过小] → "否（深红区过小）"
否则 → "否"
```

其中 `[ ... ]` 为可开关的后处理阶段（参见检测功能开关）。

---

## 输出说明

### Excel 报告（配对模式）

| 列 | 内容 |
|---|---|
| 文件名 | 配对编号 |
| P图/原图 | 原图缩略图（可关闭） |
| 热力图×2 | TruFor JET 热力图（可关闭） |
| 判定结果×2 | P图/原图篡改判定 |
| 分析图×2 | 深红区叠加+轮廓+线状框（可关闭） |
| 判定来源 | 一轮/二轮说明 |
| 篡改概率/等级/区域/峰值/置信度 | 数值指标 |
| 综合风险 | HIGH / MEDIUM / LOW |
| 问题标记 | 自动备注 |

### JSON 输出结构

```json
[
  {
    "base": "0",
    "p_file": "0p.jpg",
    "orig_file": "0.png",
    "judgment_p": "是（有篡改痕迹）",
    "judgment_o": "否",
    "score_p": 0.8523,
    "score_o": 0.1234,
    "level_p": "高",
    "level_o": "低",
    "area_p": 0.053,
    "peak_p": 0.89,
    "source_p": "二轮:深红升判",
    "risk": "HIGH",
    "flags": ["P图篡改概率高"]
  }
]
```

### 图片落盘（`SAVE_IMAGES=True`）

```
output/images/
├── 0_p_heatmap.png      # P图热力图
├── 0_o_heatmap.png      # 原图热力图
├── 0_p_analysis.png     # P图分析图
├── 0_o_analysis.png     # 原图分析图
└── ...
```

---

## 常见问题

**Q: 支持哪些格式？**
A: JPG、JPEG、PNG、BMP、WebP、TIF、TIFF。

**Q: 没有 `.venv` 怎么运行？**
A: 按上方"环境准备"章节自行创建虚拟环境并安装依赖。`run.py` 会自动查找 `.venv/Scripts/python.exe`，创建在项目目录下即可。

**Q: 检测结果是否 100% 准确？**
A: 不保证。建议作为辅助参考，重要场景需人工复核。

**Q: 如何仅看文本结果不产生文件？**
A: 设置 `OUTPUT_JSON=False`、`OUTPUT_EXCEL=False`、`SAVE_IMAGES=False`，结果仅在终端输出。
