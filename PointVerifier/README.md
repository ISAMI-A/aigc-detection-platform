# 点位真实性核验 · 独立工具包（分发使用说明）

> 本工具用于批量核验「整改图 vs 暗访图」是否为同一地点（乡村整改点位场景）。
> 不依赖任何 Web 服务，拿到即可在命令行独立运行。
> 与 Web 版共用同一套算法（`ImageVerifier` 核心库），判定标准完全一致。
>
> **项目关系**：`ImageVerifier`（算法核心库）+ `PointVerifier`（本 CLI 壳）+ Web 端
> `smart_verify` 共同组成同一个「点位真实性核验系统」，三端共用一套算法（单一来源）。
> 算法原理详见 [ImageVerifier/README.md](../ImageVerifier/README.md)。

## 一、打包内容（分发时给这两个目录）

```
分发包/
├── ImageVerifier/          # 算法核心库（必须与 PointVerifier 同级放置）
│   ├── __init__.py
│   ├── verifier.py         # SuperPoint + LightGlue + RANSAC 场景核验
│   └── parser.py           # 文件名解析（UUID/地点/编号）
└── PointVerifier/
    └── verify.py           # 命令行入口（依赖 ImageVerifier）
```

**注意**：`ImageVerifier` 和 `PointVerifier` 必须放在**同一级目录**（`verify.py` 通过相对路径定位核心库）。

## 二、环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows / Linux / macOS |
| Python | 3.10 或 3.11（推荐 3.11） |
| GPU | 可选。有 NVIDIA GPU 用 `cuda` 更快（约 1 秒/对），无 GPU 用 `cpu`（约 5~10 秒/对） |

## 三、安装步骤（对方机器上执行）

### 1. 创建虚拟环境（建议，避免污染系统 Python）

```powershell
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
# python3 -m venv .venv
# source .venv/bin/activate
```

### 2. 安装 PyTorch（按显卡选择）

```powershell
# NVIDIA GPU + CUDA 11.8（推荐）
pip install torch==2.3.0+cu118 torchvision==0.18.0+cu118 --index-url https://download.pytorch.org/whl/cu118

# 无 GPU（CPU 版，较慢）
# pip install torch torchvision
```

### 3. 安装 LightGlue（GitHub 源码，官方发布版本）

```powershell
pip install git+https://github.com/cvg/LightGlue.git
```

### 4. 安装其余依赖

```powershell
pip install opencv-python numpy pillow openpyxl tqdm
```

> 一条命令装完 2~4 步（GPU 版）：
> `pip install torch==2.3.0+cu118 torchvision==0.18.0+cu118 --index-url https://download.pytorch.org/whl/cu118 && pip install git+https://github.com/cvg/LightGlue.git opencv-python numpy pillow openpyxl tqdm`

## 四、使用方法

```powershell
# 进入 PointVerifier 目录，确保虚拟环境已激活
cd PointVerifier

# 1. 文件名解析配对（推荐，文件名需含 UUID 与「整改图/暗访图」标识）
python verify.py -dir "图片目录" -o output --mode auto

# 2. 数字编号配对（适用 0.png / 0p.jpg 这类命名；缺图自动跳过不串位）
python verify.py -dir "图片目录" -o output --mode sequential

# 3. CPU 运行 / 调整判定阈值
python verify.py -dir "图片目录" --device cpu --min-inliers 12 --min-ratio 0.15
```

### 参数说明

| 参数 | 默认 | 说明 |
|------|------|------|
| `-dir` | 内置测试目录 | 图片目录 |
| `-o` | `output` | 输出目录 |
| `--mode` | `auto` | `auto`=文件名解析配对；`sequential`=数字编号配对 |
| `--device` | `cuda` | `cuda` 或 `cpu` |
| `--min-inliers` | `12` | 最小内点数（12=严格 / 10=适中 / 8=宽松） |
| `--min-ratio` | `0.15` | 最小内点比例（0.15=严格 / 0.10=适中 / 0.05=宽松） |
| `--no-vis` | 关闭 | 不生成匹配可视化图（加快导出） |

### 输出文件

```
output/
├── 核验结果.xlsx     # 判定着色 + 整改图/暗访图/匹配可视化图嵌入
└── vis/*.jpg         # 每对匹配可视化图（连线 = RANSAC 内点）
```

### 文件名规范（`--mode auto` 需要）

```
2020_2_{UUID}_{地点名称}_{序号}_{整改图|暗访图}_{编号}.png
示例：2020_2_7a41c97b-2c85-44c7-a883-c2faefbcd16f_壶东溪_1_整改图_0.png
```

## 五、常见问题

- **`No module named 'lightglue'`**：未安装 LightGlue，执行第三步 `pip install git+https://github.com/cvg/LightGlue.git`
- **CUDA 相关报错 / `device` 设为 `cpu`**：显卡驱动过旧或 torch 版本与驱动不匹配，改用 CPU：`--device cpu`
- **中文路径无法读取图片**：工具已内置处理（imdecode/fromfile），请勿改文件名编码
- **`[跳过] 文件名不含 UUID/类型`**：文件命名不含「整改图/暗访图」标识，改用 `--mode sequential` 或按规范重命名
- **配对数量不对**：`sequential` 模式按文件名数字编号配对，缺图只跳过该组；请确认每编号有 2 张图
- **想改默认输入输出目录**：直接编辑 `verify.py` 顶部「默认配置」区块，保存后无需敲命令行直接运行

## 六、二次开发（集成到自己系统）

核心库 `ImageVerifier` 是无 Web 依赖的纯算法包，可直接引用：

```python
import sys
sys.path.insert(0, r"路径\ImageVerifier")
from ImageVerifier import SceneVerifier, parse_filename

verifier = SceneVerifier(device="cuda", min_inliers=12, min_ratio=0.15)
out = verifier.verify("整改图.png", "暗访图.png", save_vis_dir="vis")
print(out.is_same_scene, out.ransac_inliers, out.inlier_ratio)
```

## 七、技术方案详解（简历/汇报素材）

### 7.1 系统定位

面向乡村整改点位的**批量图像取证工具**：自动核验数百对「整改图 vs 暗访图」是否
拍摄于同一地点，输出带可视化证据链的 Excel 报告，替代人工逐对肉眼比对。

### 7.2 算法流水线（四段式证据链）

```
SuperPoint 特征提取 → LightGlue 深度匹配 → RANSAC 几何校验 → 双阈值判定
```

1. **SuperPoint**（自监督局部特征网络，CVPRW 2018）：单前向同时输出关键点与 256 维描述子，
   每图最多 2048 点；对视角/光照变化鲁棒，取代对光照敏感的 SIFT/ORB；
2. **LightGlue**（轻量 Transformer 匹配网络，ICCV 2023）：自注意力 + 交叉注意力逐层精化
   匹配置信度；**关闭自适应深度剪枝**（`depth_confidence=-1`）保证推理结果完全确定可复现；
3. **RANSAC 几何校验**：优先**基础矩阵 F**（极线约束对非平面 3D 场景成立，乡村场景适用）
   → 失败回退**单应矩阵 H**；估计器选 **USAC_MAGSAC**（MAGSAC++，ECCV 2020），
   阈值自适应、抗噪；`confidence=0.99999` + `maxIters=10000` 宁慢勿错；
4. **双阈值判定**：内点数 ≥12 且 内点比例 ≥0.15 才判同一场景——绝对量防弱特征场景
   侥幸通过，相对质防海量误匹配里挑内点，两者互为护栏。

### 7.3 旋转鲁棒性设计（解决 EXIF 方向丢失）

暗访图常因 EXIF Orientation 丢失而横竖颠倒，直接匹配直接失败。方案：
对第二张图分别旋转 **0°/90°/180°/270°** 各跑一遍完整匹配，取 **RANSAC 内点数最多**的
角度为最终结果，并在 method 中标注（如 `Fundamental_rot90`）。特征按"路径@角度"缓存，
同图多配对零重复计算。

### 7.4 自动配对策略（两种模式）

- **auto 文件名解析**：正则从业务命名
  `2020_2_{UUID}_{地点}_{序号}_{整改图|暗访图}_{编号}.png` 提取 UUID/地点/类型/编号，
  按 (UUID, 地点) 分组、组内按编号排序逐位配对，与 Web 版口径完全一致；
- **sequential 数字编号**：`0.png ↔ 0p.jpg` 按文件名数字分组配对，缺图只跳过该组不串位；
- **自然排序**：`re.split(r"(\d+)")` 拆段、数字段按数值比较，避免字符串排序的
  `0,1,10,11,2` 错序。

### 7.5 报告工程

- **Excel 证据报告**（openpyxl）：每行一对，嵌入整改图/暗访图/匹配可视化图三张缩略图，
  判定"是/否"整行绿/红着色，冻结首行、自适应行高、列宽定制，开表即审；
- **可视化连线图**：`cv2.drawMatches` 仅绘制 RANSAC 内点连线（外点不画），
  匹配证据一目了然，供人工复核快速抽查；
- **终端汇总**：tqdm 逐对进度 + 通过率统计。

### 7.6 性能

| 设备 | 单对耗时（含 4 角度匹配） |
|---|---|
| NVIDIA GPU | 约 1 秒/对 |
| CPU | 约 5~10 秒/对 |

### 7.7 工程亮点小结

- 深度特征（学习"像不像"）+ 几何校验（验证"对不对"）两级证据链，判定可解释可复核；
- 算法库/CLI/Web 三端单一算法来源，一处升级三端同步；
- 全链路中文路径兼容（`imdecode/imencode` 方案）、失败路径全枚举不中断批量任务。
