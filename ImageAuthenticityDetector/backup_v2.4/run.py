"""
TruFor 检测启动器（通用版）
========================================
在下方"参数配置区"修改默认值即可，命令行参数可覆盖配置区的值。

输入支持（自动识别）：
  - 配对目录：文件名匹配 {数字}.png + {数字}p.jpg 的对比数据
  - 普通目录：任意图片，不做配对，逐张检测
  - 单个图片文件：直接检测
  - 支持递归子目录、.tif/.tiff 格式
  - --max-samples N 随机抽样 N 张

用法（自动使用项目虚拟环境运行，无需手动激活）：
    python run.py                                            # 使用配置区默认参数
    python run.py -dir "任意图片目录" -o output               # 自定义输入/输出
    python run.py -dir "任意图片目录" --max-samples 100       # 随机抽100张
    python run.py -dir D:\\path\\单张图片.jpg                  # 单文件
    python run.py --preset strict                            # 用预设档位
    python run.py --threshold 0.5 --peak 0.7 --area 0.05     # 完全自定义参数

判定规则（多指标融合 + V2 画笔标注降级 + V2.2/V2.3 疑似仲裁）：
    篡改概率 >= 判定阈值 → "是（有篡改痕迹）"，
      但热力图呈线状弧线（画笔圈/涂鸦特征）→ 降级为"否（画笔标注）"：
        a) 常规线状：mask=loc>=0.5&conf>=0.5 最大连通域 矩形度<GEOM_RECT 且紧致度<GEOM_SOLID
        b) 深红线状：mask=loc>=GEOM_LOC_THR（无 conf 限制）最大连通域同样呈线状
    否则 热力图峰值 >= FUSE_PEAK 且 区域占比 >= FUSE_AREA → 疑似候选：
      深红区占比（loc>=SUSPECT_LOC_THR 无conf）>= SUSPECT_UP_THR → 升判"是"；
      < SUSPECT_UP_THR（增强图红色很小/很少）→ 判"否（深红区过小）"（无中间态）
    判"是"后另做边缘误检复核（V2.4）：红色主体完全贴边（直接触及图像边界、与边缘间
      无蓝色间隔）且集中在四周 EDGE_BAND 边缘带内 → 降级"否（边缘误检）"
    否则 → "否"
"""
# ==================== 参数配置区（改这里即可） ====================
# 注意：Windows 绝对路径请用正斜杠 "D:/..." 或原始字符串 r"D:\..."，
#       不要直接写 "D:\..."（\U、\t 等会被 Python 当作转义符导致报错）。
INPUT_DIR = "ImageAuthenticityDetector/test_images/testss"                     # 输入：图片目录 或 单个图片文件（留空则必须命令行 -dir 指定）
OUTPUT_DIR = "output_trufor_testC4"       # 输出目录（Excel 保存位置）
MAX_SAMPLES = 0                    # 随机抽样数量（0=不限制，全量跑；建议大量图片先设 100 试效果）
SEED = 42                          # 随机种子（保证抽样可复现）
PRESET = ""                # 预设档位：balanced 均衡 / strict 严格 / loose 宽松；
                               # 留空 "" 则使用下方自定义阈值
THRESHOLD = 0.35               # 自定义篡改判定阈值（PRESET 留空时生效；balanced 档已用校准值 0.35）
THRESHOLD_HIGH = 0.60          # 自定义"高"阈值
THRESHOLD_MED = 0.35           # 自定义"中"阈值
FUSE_PEAK = 0.7                # 多指标融合判定：热力图篡改峰值阈值（篡改概率不达标时；校准值 0.7）
FUSE_AREA = 0.05               # 多指标融合判定：热力图篡改面积占比阈值（loc 全图均值）
CONF_THRESHOLD = 0.5           # 置信度阈值：仅作"高置信面积"参考列输出，不参与判定
COMP_RATIO = 0.005             # 最大成片占比下限：疑似时若最大成片<该值 且 散点数>=COMP_N_SPOTS → 降级"否"（校准值 0.005）
COMP_N_SPOTS = 16               # 散点数量下限：无成片且连通域数>=该值 → 判定为散点噪声降级
GEOM_RECT = 0.25                # V2 画笔标注降级a：常规线状最大连通域矩形度阈值
GEOM_SOLID = 0.30               # V2 画笔标注降级a：常规线状最大连通域紧致度阈值
GEOM_MIN_AREA = 200             # V2 画笔标注降级：最大连通域面积下限（px），防止小噪点触发降级
GEOM_LOC_THR = 0.75             # V2 画笔标注降级b：深红线状检测 loc 阈值（无 conf，识别画圈线）
GEOM_LINE_RATIO = 0.50          # V2 画笔标注降级b：深红区"线状面积占比"阈值（>=该值判为画笔线）
SUSPECT_LOC_THR = 0.75          # V2.2/V2.3 疑似仲裁：深红区 loc 阈值（无 conf）
SUSPECT_UP_THR = 0.01           # V2.2/V2.3 疑似仲裁：深红区占比分界（>=升判"是"；<判"否（深红区过小）"）
EDGE_BAND = 0.10                # V2.4 边缘误检：边缘带宽度（图像宽高的比例）
EDGE_TOUCH_RATIO = 0.9          # V2.4 边缘误检：贴边连通域面积占比阈值（红色直接触及边界，无蓝色间隔）
EDGE_BAND_RATIO = 0.5           # V2.4 边缘误检：边缘带内红色占比阈值（排除覆盖中心的大面积篡改）

# THRESHOLD = 0.30                   # 篡改判定阈值：概率>=该值 判定'有篡改痕迹'
# THRESHOLD_HIGH = 0.60              # 篡改等级"高"阈值
# THRESHOLD_MED = 0.35               # 篡改等级"中"阈值
# FUSE_PEAK = 0.90                   # 融合判定：热力图篡改峰值阈值
# FUSE_AREA = 0.02                   # 融合判定：热力图篡改区域占比阈值（loc 全图均值）
# CONF_THRESHOLD = 0.5               # 置信度阈值：仅作"高置信面积"参考列输出，不参与判定
# COMP_RATIO = 0.005                 # 最大成片占比下限：过滤散点噪声
# COMP_N_SPOTS = 16                  # 散点数量下限：无成片且连通域数>=该值 → 判定为散点噪声降级

# ==================================================================

import argparse
import io
import os
import random
import shutil
import subprocess
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_BASE)
VENV_PY = os.path.join(_PROJECT, ".venv", "Scripts", "python.exe")

# 图片扩展名（通用模式递归收集用）
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")

# 预设档位：
#   threshold 判定阈值 —— 篡改概率>=该值 判定"是（有篡改痕迹）"
#   high 高阈值       —— 篡改概率>=该值 篡改等级"高"、综合风险 HIGH
#   med  中阈值       —— 篡改概率>=该值 篡改等级"中"、综合风险 MEDIUM
PRESETS = {
    "balanced": {
        # CASIA2 200-sample 5折CV校准：F1=0.818±0.064
        "threshold": 0.30, "high": 0.60, "med": 0.35,
        "desc": "均衡：检出率与误报率平衡（默认推荐，CASIA2校准）",
    },
    "strict": {
        "threshold": 0.6, "high": 0.75, "med": 0.50,
        "desc": "严格：降低误报，仅在高置信时判定为P图",
    },
    "loose": {
        "threshold": 0.3, "high": 0.50, "med": 0.30,
        "desc": "宽松：提高检出率，宁可误报也不漏报",
    },
}


def resolve_path(p):
    """相对路径统一基于项目根目录解析（与运行位置无关）；绝对路径原样返回"""
    if os.path.isabs(p):
        return p
    return os.path.abspath(os.path.join(_PROJECT, p))


def main():
    # 自动切换到项目虚拟环境运行（若当前解释器不是 .venv 的 python）
    if os.path.exists(VENV_PY) and os.path.abspath(sys.executable) != os.path.abspath(VENV_PY):
        code = subprocess.call([VENV_PY, os.path.abspath(__file__)] + sys.argv[1:], cwd=_BASE)
        sys.exit(code)

    parser = argparse.ArgumentParser(
        description="TruFor 检测启动器（输入支持目录/单文件，自动识别配对/通用模式）")
    parser.add_argument("-dir", default=INPUT_DIR,
                        help="图片目录 或 单个图片文件（默认: %(default)s）")
    parser.add_argument("-o", default=OUTPUT_DIR, help="输出目录（默认: %(default)s）")
    parser.add_argument("--max-samples", type=int, default=MAX_SAMPLES,
                        help=f"随机抽样数量（默认: {MAX_SAMPLES}，0=全量跑；通用模式生效）")
    parser.add_argument("--seed", type=int, default=SEED,
                        help=f"随机种子（默认: {SEED}）")
    parser.add_argument("--preset", choices=list(PRESETS),
                        help="预设档位: balanced均衡 / strict严格 / loose宽松")
    parser.add_argument("--threshold", type=float,
                        help="篡改判定阈值：概率>=该值判定'有篡改痕迹'；调高更严格(误报↓漏报↑)，调低更宽松(漏报↓误报↑)")
    parser.add_argument("--high", type=float,
                        help="篡改等级'高'阈值：概率>=该值 等级'高'/风险HIGH")
    parser.add_argument("--med", type=float,
                        help="篡改等级'中'阈值：概率>=该值 等级'中'/风险MEDIUM")
    parser.add_argument("--peak", type=float, default=None,
                        help="融合判定：热力图篡改峰值阈值（默认: %(default)s，配置区 FUSE_PEAK）")
    parser.add_argument("--area", type=float, default=None,
                        help="融合判定：热力图篡改区域占比阈值（默认: %(default)s，配置区 FUSE_AREA）")
    parser.add_argument("--conf", type=float, default=None,
                        help="置信度阈值：只统计 loc>=0.5 且 conf>=该值 的像素（默认配置区 CONF_THRESHOLD）")
    parser.add_argument("--comp-ratio", type=float, default=None,
                        help="最大成片占比阈值：过滤散点噪声（默认配置区 COMP_RATIO）")
    args = parser.parse_args()

    if not args.dir:
        print("请通过配置区 INPUT_DIR 或命令行 -dir 指定输入路径")
        return

    # 档位与阈值解析：命令行 --preset > 配置区 PRESET > 配置区自定义阈值
    if args.preset and args.preset in PRESETS:
        preset = PRESETS[args.preset]
        threshold, high, med = preset["threshold"], preset["high"], preset["med"]
    elif PRESET in PRESETS:
        preset = PRESETS[PRESET]
        threshold, high, med = preset["threshold"], preset["high"], preset["med"]
    else:
        preset = {"desc": "自定义"}
        threshold, high, med = THRESHOLD, THRESHOLD_HIGH, THRESHOLD_MED
    # 命令行单独参数覆盖
    if args.threshold is not None:
        threshold = args.threshold
    if args.high is not None:
        high = args.high
    if args.med is not None:
        med = args.med
    peak = args.peak if args.peak is not None else FUSE_PEAK
    area = args.area if args.area is not None else FUSE_AREA
    conf_thr = args.conf if args.conf is not None else CONF_THRESHOLD
    comp_ratio = args.comp_ratio if args.comp_ratio is not None else COMP_RATIO

    # 相对路径基于项目根目录解析，绝对路径原样
    img_input = resolve_path(args.dir)
    out_dir = resolve_path(args.o)

    print("▶ TruFor 检测启动")
    print(f"  ▶ 输入: {img_input}" + ("（目录）" if os.path.isdir(img_input) else "（单文件）" if os.path.exists(img_input) else "（不存在！）"))
    print(f"  ▶ 输出: {out_dir}")
    print(f"  ▶ 预设档位: {preset['desc']}")
    print(f"  ▶ 判定阈值: {threshold} —— 篡改概率≥该值 判定'有篡改痕迹'")
    print(f"  ▶ 融合判定: 峰值≥{peak}  面积≥{area}  最大成片<{comp_ratio}且散点≥{COMP_N_SPOTS}→降级")
    print(f"  ▶ 画笔标注降级: 常规线状(矩形度<{GEOM_RECT} 紧致度<{GEOM_SOLID} 面积≥{GEOM_MIN_AREA}) 或 深红线状(loc≥{GEOM_LOC_THR} 无conf, 线状占比≥{GEOM_LINE_RATIO}) → 判'否（画笔标注）'")
    print(f"  ▶ 疑似仲裁: loc≥{SUSPECT_LOC_THR}(无conf)深红区占比≥{SUSPECT_UP_THR} → 升判'是'；<{SUSPECT_UP_THR} → 判'否（深红区过小）'")
    print(f"  ▶ 边缘误检降级: 判'是'时 贴边占比≥{EDGE_TOUCH_RATIO}且边缘带红色占比≥{EDGE_BAND_RATIO}(带宽{EDGE_BAND}) → 判'否（边缘误检）'")

    # ─── 模式检测 ───
    # 单文件 → 通用模式；目录 → 先尝试配对，无真正配对则通用模式
    # "真正配对"需同时有原图({num}.png)和P图({num}p.jpg)，单侧不算
    is_paired = False
    if os.path.isdir(img_input):
        from trufor_pair import collect_pairs
        pairs = collect_pairs(img_input)
        # 只统计两侧都有的真正配对
        real_pairs = {b: p for b, p in pairs.items() if p["orig"] and p["p"]}
        is_paired = len(real_pairs) > 0
        if is_paired:
            print(f"  ▶ 模式: 配对对比（检测到 {len(real_pairs)} 对）")
        else:
            print(f"  ▶ 模式: 通用单图检测（{'目录有图但无完整配对' if pairs else '未检测到配对'}）")
    else:
        print(f"  ▶ 模式: 通用单图检测（单文件）")

    if is_paired:
        # ===== 配对模式：调用 trufor_pair.py 子进程（原有逻辑） =====
        env = os.environ.copy()
        env["TRUFOR_THRESHOLD"] = str(threshold)
        env["TRUFOR_HIGH"] = str(high)
        env["TRUFOR_MED"] = str(med)
        env["TRUFOR_PEAK"] = str(peak)
        env["TRUFOR_AREA"] = str(area)
        env["TRUFOR_CONF"] = str(conf_thr)
        env["TRUFOR_COMP_RATIO"] = str(comp_ratio)
        env["TRUFOR_COMP_SPOTS"] = str(COMP_N_SPOTS)
        env["TRUFOR_GEOM_RECT"] = str(GEOM_RECT)
        env["TRUFOR_GEOM_SOLID"] = str(GEOM_SOLID)
        env["TRUFOR_GEOM_MIN_AREA"] = str(GEOM_MIN_AREA)
        env["TRUFOR_GEOM_LOC_THR"] = str(GEOM_LOC_THR)
        env["TRUFOR_GEOM_LINE_RATIO"] = str(GEOM_LINE_RATIO)
        env["TRUFOR_SUSPECT_LOC_THR"] = str(SUSPECT_LOC_THR)
        env["TRUFOR_SUSPECT_UP_THR"] = str(SUSPECT_UP_THR)
        env["TRUFOR_EDGE_BAND"] = str(EDGE_BAND)
        env["TRUFOR_EDGE_TOUCH_RATIO"] = str(EDGE_TOUCH_RATIO)
        env["TRUFOR_EDGE_BAND_RATIO"] = str(EDGE_BAND_RATIO)

        script = os.path.join(_BASE, "trufor_pair.py")
        code = subprocess.call([sys.executable, "-u", script,
                                "-dir", img_input, "-o", out_dir], env=env)
        sys.exit(code)
    else:
        # ===== 通用模式：内联单图批量检测 =====
        run_universal(
            img_input, out_dir,
            threshold=threshold, high=high, med=med,
            peak=peak, area=area, conf_thr=conf_thr,
            comp_ratio=comp_ratio, comp_spots=COMP_N_SPOTS,
            max_samples=args.max_samples, seed=args.seed,
        )


def run_universal(img_path, out_dir, threshold, high, med, peak, area,
                  conf_thr, comp_ratio, comp_spots, max_samples=0, seed=42):
    """通用单图检测：不依赖配对，逐张检测并输出简化 Excel"""
    import cv2
    import numpy as np
    from PIL import Image as PILImage

    from config import TRUFOR_PATH, TEMP_DIR, MAX_IMAGE_SIZE
    from modules.image_preprocess import preprocess
    from modules.forgery_detector import TruForDetector
    from modules.exif_analyzer import analyze_exif
    import trufor_pair
    from trufor_pair import loc_stats, make_heatmap, level_of, judge

    # 覆盖 trufor_pair 的模块级全局阈值
    trufor_pair.THRESHOLD = threshold
    trufor_pair.FUSE_PEAK = peak
    trufor_pair.FUSE_AREA = area
    trufor_pair.CONF_THRESHOLD = conf_thr
    trufor_pair.COMP_RATIO = comp_ratio
    trufor_pair.COMP_N_SPOTS = comp_spots
    trufor_pair.THRESHOLD_FORGERY_HIGH = high
    trufor_pair.THRESHOLD_FORGERY_MED = med
    trufor_pair.GEOM_RECT = GEOM_RECT
    trufor_pair.GEOM_SOLID = GEOM_SOLID
    trufor_pair.GEOM_MIN_AREA = GEOM_MIN_AREA
    trufor_pair.GEOM_LOC_THR = GEOM_LOC_THR
    trufor_pair.GEOM_LINE_RATIO = GEOM_LINE_RATIO
    trufor_pair.SUSPECT_LOC_THR = SUSPECT_LOC_THR
    trufor_pair.SUSPECT_UP_THR = SUSPECT_UP_THR
    trufor_pair.EDGE_BAND = EDGE_BAND
    trufor_pair.EDGE_TOUCH_RATIO = EDGE_TOUCH_RATIO
    trufor_pair.EDGE_BAND_RATIO = EDGE_BAND_RATIO

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

    # 收集图片
    if os.path.isfile(img_path):
        files = [img_path]
    else:
        files = []
        for root, _, filenames in os.walk(img_path):
            for fn in filenames:
                if fn.lower().endswith(IMG_EXT):
                    files.append(os.path.join(root, fn))
    print(f"  检测到 {len(files)} 张图片")

    if not files:
        print("未找到图片文件")
        return

    # 随机抽样
    if max_samples > 0 and max_samples < len(files):
        random.seed(seed)
        files = random.sample(files, max_samples)
        print(f"  随机抽样 {len(files)} 张（seed={seed}）")

    # 预处理
    batch_dir = os.path.join(TEMP_DIR, "run_batch")
    os.makedirs(batch_dir, exist_ok=True)
    plan = []
    total = len(files)
    for idx, fp in enumerate(files, 1):
        try:
            name = os.path.basename(preprocess(fp, MAX_IMAGE_SIZE, batch_dir))
            plan.append((fp, name))
            print(f"\r    ⌛ 预处理 {idx}/{total}...", end="", flush=True)
        except Exception as e:
            print(f"\n    ✗ {os.path.basename(fp)}: 预处理失败 - {e}")
    print()

    if not plan:
        print("全部图片预处理失败，无结果")
        shutil.rmtree(batch_dir, ignore_errors=True)
        return

    # TruFor 批量检测
    tmp_dir = os.path.join(TEMP_DIR, "run_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    print(f"  共 {len(plan)} 张图片，开始 TruFor 批量检测（模型只加载一次）...")
    trufor = TruForDetector(TRUFOR_PATH)
    try:
        results = trufor.predict_batch(batch_dir, tmp_dir)
    except Exception as e:
        print(f"  ⚠ 首次检测失败({e})，自动重试...")
        results = trufor.predict_batch(batch_dir, tmp_dir)

    # 预判
    pre = {}
    for name, (score, loc, conf_map) in results.items():
        st = loc_stats(loc, conf_map) if (loc is not None and conf_map is not None) else None
        pre[name] = (judge(score, st), st, score, loc, conf_map)

    # 收集数据
    data = []
    for i, (fp, name) in enumerate(plan, 1):
        if name not in results:
            print(f"  [{i}/{len(plan)}] {os.path.basename(fp)} ✗ 未生成结果")
            continue
        jud, st, score, loc, conf_map = pre[name]
        info = f"概率={score:.3f}" if score is not None else "无结果"
        print(f"  [{i}/{len(plan)}] {os.path.basename(fp)} {info} → {jud}")

        sw = analyze_exif(fp).get("software") or ""
        size_str = fmt_str = ""
        try:
            with PILImage.open(fp) as im:
                size_str = f"{im.size[0]}x{im.size[1]}"
                fmt_str = im.format or ""
        except Exception:
            pass

        flags = []
        if sw:
            flags.append(f"编辑软件: {sw}")
        if jud and jud.startswith("是"):
            flags.append("篡改概率高")
        elif jud and jud == "否（散点噪声）":
            flags.append("热力图呈散点状，已按噪声降级")
        elif jud and jud == "否（边缘误检）":
            flags.append("热力图红色完全贴边（边缘误检特征），已降级")
        elif jud and jud == "否（深红区过小）":
            flags.append("热力图深红区过小，已按非篡改降级")
        elif jud and jud == "否（画笔标注）":
            flags.append("热力图呈线状弧线（画笔圈/涂鸦特征），已降级")

        data.append({
            "file": os.path.basename(fp), "path": fp,
            "score": float(score) if score is not None else None,
            "jud": jud,
            "hm": make_heatmap(loc) if loc is not None else None,
            "peak": st["peak"] if st else None,
            "area": st["area"] if st else None,
            "conf_area": st["conf_area"] if st else None,
            "max_comp": st["max_comp"] if st else None,
            "n_comp": st["n_comp"] if st else None,
            "conf": float(conf_map.mean()) if conf_map is not None else None,
            "size": size_str, "fmt": fmt_str,
            "software": sw, "flags": flags,
        })

    shutil.rmtree(tmp_dir, ignore_errors=True)
    shutil.rmtree(batch_dir, ignore_errors=True)

    if not data:
        print("无有效检测结果")
        return

    build_universal_xlsx(data, out_dir, threshold, peak, area, comp_ratio, comp_spots, high, med, conf_thr)
    print(f"\n完成：{out_dir}/TruFor检测结果.xlsx")


def embed_thumb(ws, img_array, cell, max_w=250, max_h=180):
    """把图片数组缩略后嵌入 Excel 单元格"""
    from PIL import Image as PILImage
    thumb = PILImage.fromarray(img_array)
    thumb.thumbnail((max_w, max_h))
    buf = io.BytesIO()
    thumb.save(buf, format="PNG")
    buf.seek(0)
    from openpyxl.drawing.image import Image as XLImage
    ws.add_image(XLImage(buf), cell)


def build_universal_xlsx(data, out_dir, threshold, peak, area, comp_ratio, comp_spots, high, med, conf_thr):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from trufor_pair import level_of, save_workbook_retry

    wb = Workbook()
    ws = wb.active
    ws.title = "TruFor检测结果"

    headers = [
        "文件名", "缩略图", "热力图",
        "篡改概率", "篡改等级", "篡改判定",
        "区域占比", "峰值", "高置信面积", "最大成片", "散点数", "置信度",
        "综合风险", "问题标记",
        "尺寸", "格式", "编辑软件", "备注"
    ]
    hdr_font = Font(bold=True, size=11)
    hdr_fill = PatternFill("solid", fgColor="D9E1F2")
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = hdr_font; c.fill = hdr_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for idx, d in enumerate(data, 2):
        center = Alignment(horizontal="center", vertical="center")
        wrap = Alignment(wrap_text=True, vertical="center")

        ws.cell(row=idx, column=1, value=d["file"]).alignment = center
        if d["path"]:
            try:
                import numpy as np
                from PIL import Image as PILImage
                thumb = np.array(PILImage.open(d["path"]).convert("RGB"))
                embed_thumb(ws, thumb, f"B{idx}")
            except Exception:
                pass
        if d["hm"] is not None:
            embed_thumb(ws, d["hm"], f"C{idx}")

        if d["score"] is not None:
            ws.cell(row=idx, column=4, value=round(d["score"], 4)).alignment = center
            ws.cell(row=idx, column=5, value=level_of(d["score"])).alignment = center
        ws.cell(row=idx, column=6, value=d["jud"] or "").alignment = center
        if d["area"] is not None:
            ws.cell(row=idx, column=7, value=round(d["area"], 4)).alignment = center
        if d["peak"] is not None:
            ws.cell(row=idx, column=8, value=round(d["peak"], 4)).alignment = center
        if d["conf_area"] is not None:
            ws.cell(row=idx, column=9, value=round(d["conf_area"], 4)).alignment = center
        if d["max_comp"] is not None:
            ws.cell(row=idx, column=10, value=round(d["max_comp"], 4)).alignment = center
        if d["n_comp"] is not None:
            ws.cell(row=idx, column=11, value=d["n_comp"]).alignment = center
        if d["conf"] is not None:
            ws.cell(row=idx, column=12, value=round(d["conf"], 4)).alignment = center

        # 综合风险
        def _risk(j):
            if j is None: return "LOW"
            if j.startswith("是"): return "HIGH"
            if j.startswith("疑似"): return "MEDIUM"
            return "LOW"
        ws.cell(row=idx, column=13, value=_risk(d["jud"])).alignment = center
        ws.cell(row=idx, column=14, value="；".join(d["flags"])).alignment = wrap
        ws.cell(row=idx, column=15, value=d["size"]).alignment = center
        ws.cell(row=idx, column=16, value=d["fmt"]).alignment = center
        ws.cell(row=idx, column=17, value=d["software"]).alignment = center

        jud = d["jud"]
        notes = []
        if jud and jud.startswith("是"):
            notes.append("判定有篡改痕迹")
        elif jud and jud == "否（散点噪声）":
            notes.append("热力图呈散点状已降级，但仍可能有细微篡改（如局部擦除）")
        elif jud and jud == "否（边缘误检）":
            notes.append("热力图红色完全贴边（与边缘间无蓝色间隔），已按模型边缘误检降级")
        elif jud and jud == "否（深红区过小）":
            notes.append("热力图深红区过小（红色区域很小/很少），模型未检测出显著篡改，已判否")
        elif jud and jud == "否（画笔标注）":
            notes.append("热力图呈线状弧线，符合画笔圈/涂鸦标注特征，已按非篡改降级")
        else:
            notes.append("未检测到显著篡改痕迹")
        ws.cell(row=idx, column=18, value="；".join(notes)).alignment = wrap

        ws.row_dimensions[idx].height = 150

    widths = {
        "A": 28, "B": 35, "C": 35,
        "D": 10, "E": 8, "F": 24,
        "G": 10, "H": 10, "I": 10, "J": 10, "K": 8, "L": 10,
        "M": 10, "N": 30,
        "O": 12, "P": 8, "Q": 16, "R": 40
    }
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    # 参数信息行
    ws.insert_rows(1)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    param_info = (
        f"判定参数: THRESHOLD={threshold}, PEAK={peak}, AREA={area}, "
        f"COMP_RATIO={comp_ratio}, COMP_N_SPOTS={comp_spots}, "
        f"HIGH={high}, MED={med}, CONF={conf_thr}, "
        f"GEOM_RECT={GEOM_RECT}, GEOM_SOLID={GEOM_SOLID}, GEOM_MIN_AREA={GEOM_MIN_AREA}, "
        f"GEOM_LOC_THR={GEOM_LOC_THR}(无conf深红), GEOM_LINE_RATIO={GEOM_LINE_RATIO}, "
        f"SUSPECT仲裁: loc≥{SUSPECT_LOC_THR}(无conf)占比≥{SUSPECT_UP_THR}升判是, <{SUSPECT_UP_THR}判否, "
        f"EDGE误检: 贴边占比≥{EDGE_TOUCH_RATIO}且边缘带占比≥{EDGE_BAND_RATIO}(带宽{EDGE_BAND})"
    )
    ws.cell(row=1, column=1, value=param_info).font = Font(italic=True, size=10, color="666666")

    path = os.path.join(out_dir, "TruFor检测结果.xlsx")
    path = save_workbook_retry(wb, path)
    print(f"📊 Excel: {path}")


if __name__ == "__main__":
    main()
