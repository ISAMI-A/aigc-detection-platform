# ImageVerifier · 点位真实性核验核心算法库

> **项目关系说明**：本库与 `PointVerifier`（命令行分发工具）、Web 端（`web/smart_verify` 智能核验页）
> 共同组成**同一个项目——「点位真实性核验系统」**：
>
> | 组成部分 | 角色 | 说明 |
> |---|---|---|
> | **ImageVerifier（本库）** | 算法核心库 | 场景核验算法 + 文件名解析，无任何 Web 依赖 |
> | **PointVerifier** | CLI 分发壳 | 面向无 Web 环境的批量命令行工具，`import` 本库 |
> | **Web 端 smart_verify** | 在线版 | Web 后端同样 `import` 本库 |
>
> 三端**共用同一套算法与判定标准（算法单一来源）**，算法升级一处修改、三端同步生效。

## 一、解决的业务问题与技术挑战

乡村整改点位场景下，需要批量核验「整改图 vs 暗访图」是否拍摄于**同一地点**，替代人工逐对肉眼比对。

核心技术挑战：

| 挑战 | 具体表现 |
|---|---|
| 同地不同拍 | 同一地点两次拍摄：视角、光照、季节、设备均不同，像素级差异极大，无法用直方图/哈希等全局相似度方法 |
| 拍摄方向随机 | 手机 EXIF 方向信息可能丢失，图像存在 90°/180°/270° 旋转，直接匹配直接失败 |
| 需要可解释证据 | 判定结果必须附带匹配点连线可视化与量化指标，供人工复核，不能是黑盒打分 |

## 二、技术架构总览

```
输入图对（整改图 p1, 暗访图 p2）
   │
   ▼ ① 预处理
   │    LANCZOS 等比缩放（最长边 ≤1024）→ [0,1] 归一化 → HWC→CHW 张量 → GPU
   │
   ▼ ② 特征提取（SuperPoint，自监督关键点检测 + 256 维描述子）
   │    每图最多 2048 个关键点
   │    特征缓存：`path@rot{angle}` 为 key（CPU 存储，按需上 GPU，跨配对复用）
   │
   ▼ ③ 特征匹配（LightGlue 轻量 Transformer 匹配网络）
   │    关闭自适应深度/广度剪枝，保证结果确定性
   │
   ▼ ④ 几何校验（RANSAC · USAC_MAGSAC）
   │    优先基础矩阵 F（对非平面 3D 场景成立）→ 失败回退单应矩阵 H（≥4 点）
   │
   ▼ ⑤ 多角度择优（旋转鲁棒性）
   │    对 p2 尝试 0°/90°/180°/270° 四个旋转角各跑一遍 ②~④，取 RANSAC 内点数最多的结果
   │
   ▼ ⑥ 双阈值判定
   │    内点数 ≥ min_inliers 且 内点比例 ≥ min_ratio → 判定同一场景
   │
   └─▶ 输出 VerifyOutput
        判定 + 置信度 + 匹配点坐标 + 内点掩码 + 可视化连线图
```

## 三、核心算法详解

### 3.1 特征提取：SuperPoint（CVPRW 2018）

采用 Magic Leap 的 **SuperPoint** 自监督局部特征网络，单次前向传播同时输出关键点位置与描述子：

- **原理**：通过 Homographic Adaptation（随机单应变换 + 图像增强）生成自监督训练信号，
  无需人工标注即可学习跨视角/光照稳定的特征点；
- **网络结构**：共享卷积骨干 + 双头输出——检测头（像素级关键点 softmax 分类，带亚像素精度）
  与描述子头（256 维双曲正切空间向量）；
- **参数选择**：`max_num_keypoints=2048`，在乡村场景的纹理丰富度下平衡召回率与计算量；
- **选型理由**：相比传统 SIFT/ORB，SuperPoint 对光照变化和视角变化鲁棒性显著更强、
  GPU 推理速度快一个量级，且与 LightGlue 天然配套（官方联合训练权重）。

### 3.2 特征匹配：LightGlue（ICCV 2023）

采用轻量级 Transformer 匹配网络 **LightGlue**（SuperGlue 的后继者）：

- **原理**：交替执行自注意力（同图内点关系建模）与交叉注意力（跨图特征交互），
  逐层精化匹配置信度，可微分、端到端；
- **工程决策**：`depth_confidence=-1, breadth_confidence=-1` **关闭自适应深度剪枝机制**
  （原设计用于动态跳层提速），换取**推理结果完全确定性**——同一输入永远同一输出，
  满足核验类业务"结果可复现"的要求；
- **选型理由**：计算量与显存占用约为 SuperGlue 的一半，精度持平；
  `features='superpoint'` 直接加载与 SuperPoint 联合训练的配套权重，免去自训成本。

### 3.3 几何校验：RANSAC（USAC_MAGSAC 变体）

匹配点中不可避免混入误匹配，用随机抽样一致性（RANSAC）从匹配点对中估计几何模型并分离内点/外点：

- **优先基础矩阵 F**（`cv2.findFundamentalMat`）：F 矩阵的极线约束对**一般非平面 3D 场景**成立，
  乡村场景（树木、房屋、地形）恰恰是非平面的，因此优先 F；
- **回退单应矩阵 H**（`cv2.findHomography`）：当 F 求解失败或内点不足时回退
  （H 假设平面场景或纯旋转，仅需 4 点即可求解）；
- **鲁棒估计器选 USAC_MAGSAC**（`cv2.USAC_MAGSAC`）：OpenCV 内置的 MAGSAC++（ECCV 2020）变体，
  采用阈值自适应的边缘化采样一致性，对噪声内阈值不敏感，显著优于朴素 RANSAC 与 LMEDS；
- **参数**：重投影阈值 5.0px、`confidence=0.99999`（置信度上限拉满）、`maxIters=10000`
  （高迭代上限），宁慢勿错；
- **防御性设计**：总匹配数 < 8 时跳过 RANSAC（F 矩阵最少需 8 点），直接返回"匹配点过少"，
  避免 OpenCV 断言错误。

### 3.4 多角度旋转匹配（旋转鲁棒性）

针对暗访图 EXIF Orientation 丢失导致的横竖颠倒问题：

- 固定 p1 为 0°，对 p2 分别旋转 **0°/90°/180°/270°**（PIL `Transpose` 无损旋转）后各执行一次完整匹配；
- 取 **RANSAC 内点数最多**的角度作为最终结果，并在 `method` 字段标注
  （如 `Fundamental_rot90`），旋转命中即说明原图方向颠倒；
- 四个角度的特征各自缓存（`path@rot90` 等独立 key），同一张图被多个配对引用时不重复提特征。

### 3.5 双阈值判定与置信度

```
判定同一场景 ⟺ RANSAC 内点数 ≥ min_inliers（绝对量） 且 内点比例 = 内点数/总匹配数 ≥ min_ratio（相对质）
置信度 confidence = min(内点数 / 30, 1.0)   # 30 个内点即满置信，饱和式归一化
```

双阈值设计的意义：**绝对量防"弱特征场景侥幸通过"**（匹配总量少时比例容易虚高），
**相对质防"海量误匹配里挑内点"**（匹配总量大时绝对量容易虚高），两者同时达标才判定同场景。

阈值三档预设（CLI 可调）：

| 档位 | min_inliers | min_ratio | 适用 |
|---|---|---|---|
| 严格 | 12 | 0.15 | 误判代价高的场景 |
| 适中 | 10 | 0.10 | 常规 |
| 宽松 | 8 | 0.05 | 光照/季节差异极大的老图对比 |

## 四、预处理与后处理

### 预处理（`_load`）

1. PIL 打开并转 RGB；
2. 按指定角度旋转（多角度匹配用）；
3. 最长边超过 1024 时 **LANCZOS 等比缩放**（控制显存与推理耗时，LANCZOS 在缩小时
   抗混叠能力优于 BILINEAR，利于保留高频角点）；
4. 像素归一化到 [0,1]（`float32 / 255`），HWC→CHW、升维为 batch 维张量上 GPU。

### 后处理（输出增强）

- **可视化连线图**（`_save_visualization`）：`cv2.drawMatches` 绘制两图并排 +
  仅 RANSAC 内点的绿色连线（`mask.ravel()` 掩码过滤），外点不画，图面干净、证据聚焦；
- **结构化证据输出**：`VerifyOutput` 除判定外还携带匹配点坐标数组（`mkpts0/mkpts1`）与
  内点掩码（`mask`），供 Web 前端在原图上做 Canvas 交互式标注（放大、悬浮查看单点对应关系）。

## 五、工程化设计与亮点

| 设计点 | 说明 |
|---|---|
| 算法单一来源 | 库与 CLI、Web 三端共用；算法迭代只改一处 |
| 特征缓存 | `feat_cache` 以 `路径@旋转角` 为 key；特征提完即 `.cpu()` 存储避免常驻显存，匹配时按需 `.to(device)` |
| 中文路径兼容 | `cv2.imread/imwrite` 不支持中文路径 → 读用 `np.fromfile + imdecode`、写用 `imencode + tofile`，全流程中文目录可用 |
| 无损输入 | 预处理在内存中完成，不落盘、不改原图 |
| 失败降级完整 | TooFewMatches / RANSAC_Fail / Homography 回退，每种失败路径都有明确 method 标识，不会抛裸异常中断批量任务 |

## 六、对外接口

```python
from ImageVerifier import SceneVerifier, VerifyOutput, parse_filename

# 场景核验器
verifier = SceneVerifier(
    device="cuda",        # 'cuda' / 'cpu'
    max_size=1024,        # 预处理最长边
    min_inliers=12,       # 绝对内点数阈值
    min_ratio=0.15,       # 内点比例阈值
)

out = verifier.verify("整改图.png", "暗访图.png", save_vis_dir="vis/")
out.is_same_scene   # bool  是否同一场景
out.confidence      # float 置信度 [0,1]
out.total_matches   # int   LightGlue 总匹配数
out.ransac_inliers  # int   RANSAC 内点数
out.inlier_ratio    # float 内点比例
out.method          # str   'Fundamental' / 'Homography' / '..._rot90' / 'TooFewMatches'
out.mkpts0/mkpts1   # ndarray 匹配点坐标（前端 Canvas 标注用）
out.mask            # ndarray RANSAC 内点掩码
out.best_angle      # int   最佳旋转角 0/90/180/270
out.vis_path        # str   可视化图路径（可选生成）

# 文件名解析（配对用）
info = parse_filename("2020_2_{UUID}_{地点}_{序号}_{整改图|暗访图}_{编号}.png")
# → {'uuid', 'location', 'idx', 'photo_type', 'photo_num', 'path', 'filename'}
```

## 七、性能指标

| 设备 | 单对耗时（含 4 角度匹配） |
|---|---|
| NVIDIA GPU（CUDA） | 约 1 秒/对 |
| CPU | 约 5~10 秒/对 |

模型加载约数秒（一次性），特征缓存命中后同图复检接近零成本。

## 八、踩坑记录

| 问题 | 根因 | 解决 |
|---|---|---|
| 中文路径图片读取返回 None | OpenCV 底层用 C 标准 IO，Windows 下不支持非 ASCII 路径 | `np.fromfile + cv2.imdecode` 读、`imencode + tofile` 写 |
| 显存随批量大涨 | 特征张量缓存常驻 GPU | 缓存统一存 CPU，匹配瞬间按需搬移 GPU |
| 匹配数不足时 RANSAC 崩溃 | `findFundamentalMat` 最少需 8 点，点数不足触发断言 | 总匹配 < 8 直接返回 TooFewMatches，跳过几何校验 |
