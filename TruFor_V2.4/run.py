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
    python run.py --threshold 0.5 --peak 0.7 --area 0.05     # 完全自定义参数

判定规则：
    篡改概率 >= 判定阈值 → "是（有篡改痕迹）"
    否则 热力图峰值>=FUSE_PEAK 且 区域占比>=FUSE_AREA → 进入疑似仲裁
    其余 → "否"
    判"是"后可经下级检测修正（画笔标注/边缘误检/散点噪声降级，可通过下方开关控制）

检测流程（仅 TruFor 模型推理，其余后处理均可按需开关）：
    TruFor推理 → 基础概率判定 → [画笔标注降级] → [边缘误检降级]
              → [融合判定] → [散点噪声降级] → [深红区升判]
              → 生成分析图/热力图 → Excel输出
    其中 [...] 为可选阶段，由下方功能开关控制。
"""
# ==================== 检测功能开关（不建议关闭，影响识别准确率） ====================
ENABLE_BRUSH_DETECTION = True   # 画笔标注降级检测（深红线状+常规线状，关闭跳过 deep_red_stats）
ENABLE_EDGE_DETECTION = True    # V2.4 边缘误检降级检测（关闭跳过边缘连通域分析）
ENABLE_SPOT_DETECTION = True    # 散点噪声降级检测（关闭不降级散点噪声）
ENABLE_SUSPECT_UPGRADE = True   # 深红区疑似升判（V2.2/V2.3，关闭不升判，疑似直接判否）

# ==================== 输出模式开关 ====================
OUTPUT_TERMINAL = True   # 终端文本输出（始终输出进度+结果摘要）
OUTPUT_JSON = False      # 输出 JSON 文件（保存到输出目录）
OUTPUT_EXCEL = True      # 输出 Excel 表格
SAVE_IMAGES = False      # 图片落盘（热力图 / 分析图保存为独立 PNG 文件）

# ==================== Excel 图片嵌入开关（OUTPUT_EXCEL=True 时生效） ====================
ENABLE_ORIGINAL_IMAGE = True  # Excel 中嵌入"原图/P图"列
ENABLE_HEATMAP = True         # Excel 中嵌入"热力图"列
ENABLE_ANALYSIS_IMAGE = True  # Excel 中嵌入"分析图"列

# ==================== 参数配置区 ====================
# 注意：Windows 绝对路径请用正斜杠 "D:/..." 或原始字符串 r"D:\..."，
#       不要直接写 "D:\..."（\U、\t 等会被 Python 当作转义符导致报错）。
INPUT_DIR = ""                     # 输入：图片目录 或 单个图片文件（留空则必须命令行 -dir 指定，如 -dir D:/图片目录）
OUTPUT_DIR = "./output"            # 输出目录（Excel 保存位置）
MAX_SAMPLES = 0                    # 随机抽样数量（0=不限制，全量跑；建议大量图片先设 100 试效果）
SEED = 42                          # 随机种子（保证抽样可复现）
THRESHOLD = 0.35                   # 篡改判定阈值：概率>=该值 → 判定"有篡改痕迹"（校准值 0.35）
THRESHOLD_HIGH = 0.60              # 篡改等级"高"阈值：概率>=该值 → 等级"高"
THRESHOLD_MED = 0.35               # 篡改等级"中"阈值：概率>=该值 → 等级"中"（低于此=低）
FUSE_PEAK = 0.7                    # 融合判定：热力图篡改峰值阈值（概率不达标时，校准值 0.7）
FUSE_AREA = 0.05                   # 融合判定：热力图篡改面积占比阈值（loc 全图均值）
CONF_THRESHOLD = 0.5               # 置信度阈值：仅作"高置信面积"参考列输出，不参与判定
COMP_RATIO = 0.005                 # 最大成片占比下限：疑似时若最大成片<该值 且 散点数>=COMP_N_SPOTS → 降级"否"
COMP_N_SPOTS = 16                  # 散点数量下限：无成片且连通域数>=该值 → 判定为散点噪声
GEOM_RECT = 0.25                   # 画笔标注降级a：常规线状最大连通域矩形度阈值
GEOM_SOLID = 0.30                  # 画笔标注降级a：常规线状最大连通域紧致度阈值
GEOM_MIN_AREA = 200                # 画笔标注降级：最大连通域面积下限（px）
GEOM_LOC_THR = 0.75                # 画笔标注降级b：深红线状检测 loc 阈值（无 conf）
GEOM_LINE_RATIO = 0.50             # 画笔标注降级b：深红区"线状面积占比"阈值
SUSPECT_LOC_THR = 0.75             # 疑似仲裁：深红区 loc 阈值（无 conf）
SUSPECT_UP_THR = 0.01              # 疑似仲裁：深红区占比分界（>=升判"是"；<判"否（深红区过小）"）
EDGE_BAND = 0.10                   # 边缘误检：边缘带宽度（图像宽高的比例）
EDGE_TOUCH_RATIO = 0.9             # 边缘误检：贴边连通域面积占比阈值
EDGE_BAND_RATIO = 0.5              # 边缘误检：边缘带内红色占比阈值

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
# 虚拟环境优先找脚本所在目录（发布版单目录使用，.venv 建在项目内），
# 找不到再找上级目录（兼容工作区根目录统一建 .venv 的用法）
VENV_PY = os.path.join(_BASE, ".venv", "Scripts", "python.exe")
if not os.path.exists(VENV_PY):
    VENV_PY = os.path.join(_PROJECT, ".venv", "Scripts", "python.exe")

# 图片扩展名（通用模式递归收集用）
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


def resolve_path(p):
    """相对路径统一基于当前运行目录解析；绝对路径原样返回"""
    if os.path.isabs(p):
        return p
    return os.path.abspath(os.path.join(os.getcwd(), p))


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
    parser.add_argument("--threshold", type=float,
                        help="篡改判定阈值：概率>=该值判定'有篡改痕迹'；调高更严格(误报↓漏报↑)，调低更宽松(漏报↓误报↑)")
    parser.add_argument("--high", type=float,
                        help="篡改等级'高'阈值：概率>=该值 等级'高'/风险HIGH")
    parser.add_argument("--med", type=float,
                        help="篡改等级'中'阈值：概率>=该值 等级'中'/风险MEDIUM")
    parser.add_argument("--peak", type=float, default=None,
                        help="融合判定：热力图篡改峰值阈值（默认: 配置区 FUSE_PEAK）")
    parser.add_argument("--area", type=float, default=None,
                        help="融合判定：热力图篡改区域占比阈值（默认: 配置区 FUSE_AREA）")
    parser.add_argument("--conf", type=float, default=None,
                        help="置信度阈值：只统计 loc>=0.5 且 conf>=该值 的像素（默认配置区 CONF_THRESHOLD）")
    parser.add_argument("--comp-ratio", type=float, default=None,
                        help="最大成片占比阈值：过滤散点噪声（默认配置区 COMP_RATIO）")
    args = parser.parse_args()

    if not args.dir:
        print("请通过配置区 INPUT_DIR 或命令行 -dir 指定输入路径")
        return

    # 阈值解析：直接使用配置区值，命令行参数可覆盖
    threshold = args.threshold if args.threshold is not None else THRESHOLD
    high = args.high if args.high is not None else THRESHOLD_HIGH
    med = args.med if args.med is not None else THRESHOLD_MED
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
    print(f"  ▶ 判定阈值: {threshold}  (高≥{high} / 中≥{med})")
    print(f"  ▶ 融合判定: 峰值≥{peak}  面积≥{area}")
    # 输出模式
    modes = []
    if OUTPUT_TERMINAL: modes.append("终端")
    if OUTPUT_JSON: modes.append("JSON")
    if OUTPUT_EXCEL:
        img_parts = []
        if ENABLE_ORIGINAL_IMAGE: img_parts.append("原图")
        if ENABLE_HEATMAP: img_parts.append("热力图")
        if ENABLE_ANALYSIS_IMAGE: img_parts.append("分析图")
        img_str = "+".join(img_parts) if img_parts else "仅文本"
        modes.append(f"Excel({img_str})")
    print(f"  ▶ 输出模式: {' | '.join(modes)}" + ("  图片落盘: ✓" if SAVE_IMAGES else ""))
    print(f"  ▶ 检测开关: 画笔标注{'✓' if ENABLE_BRUSH_DETECTION else '✗'}  边缘误检{'✓' if ENABLE_EDGE_DETECTION else '✗'}  "
          f"散点降级{'✓' if ENABLE_SPOT_DETECTION else '✗'}  深红升判{'✓' if ENABLE_SUSPECT_UPGRADE else '✗'}")

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
        # ===== 配对模式：调用 trufor_pair.py 子进程（模型只加载一次，逐组进度输出） =====
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
        # 功能开关
        env["TRUFOR_BRUSH"] = str(ENABLE_BRUSH_DETECTION)
        env["TRUFOR_EDGE"] = str(ENABLE_EDGE_DETECTION)
        env["TRUFOR_SPOT"] = str(ENABLE_SPOT_DETECTION)
        env["TRUFOR_SUSPECT"] = str(ENABLE_SUSPECT_UPGRADE)
        # 输出模式开关
        env["TRUFOR_OUT_JSON"] = str(OUTPUT_JSON)
        env["TRUFOR_OUT_EXCEL"] = str(OUTPUT_EXCEL)
        env["TRUFOR_SAVE_IMG"] = str(SAVE_IMAGES)
        env["TRUFOR_ORIG_IMG"] = str(ENABLE_ORIGINAL_IMAGE)
        env["TRUFOR_HEATMAP"] = str(ENABLE_HEATMAP)
        env["TRUFOR_ANA_IMG"] = str(ENABLE_ANALYSIS_IMAGE)

        script = os.path.join(_BASE, "trufor_pair.py")
        code = subprocess.call([sys.executable, "-u", script,
                                "-dir", img_input, "-o", out_dir], env=env)
        sys.exit(code)
    else:
        # ===== 通用模式：内联单图批量检测（不做原图/P图配对） =====
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
    import trufor_pair
    from trufor_pair import loc_stats, make_heatmap, level_of, judge, judge_source, draw_analysis

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
    # 功能开关
    trufor_pair.ENABLE_BRUSH_DETECTION = ENABLE_BRUSH_DETECTION
    trufor_pair.ENABLE_EDGE_DETECTION = ENABLE_EDGE_DETECTION
    trufor_pair.ENABLE_SPOT_DETECTION = ENABLE_SPOT_DETECTION
    trufor_pair.ENABLE_SUSPECT_UPGRADE = ENABLE_SUSPECT_UPGRADE
    # 输出模式开关
    trufor_pair.OUTPUT_JSON = OUTPUT_JSON
    trufor_pair.OUTPUT_EXCEL = OUTPUT_EXCEL
    trufor_pair.SAVE_IMAGES = SAVE_IMAGES
    trufor_pair.ENABLE_ORIGINAL_IMAGE = ENABLE_ORIGINAL_IMAGE
    trufor_pair.ENABLE_HEATMAP = ENABLE_HEATMAP
    trufor_pair.ENABLE_ANALYSIS_IMAGE = ENABLE_ANALYSIS_IMAGE

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

        # 分析图（深红区+膨胀轮廓+线状框）与判定来源
        ana = (draw_analysis(np.array(PILImage.open(fp).convert("RGB")), loc)
               if ENABLE_ANALYSIS_IMAGE and loc is not None else None)
        src = judge_source(jud, st, score)

        hm = make_heatmap(loc) if ENABLE_HEATMAP and loc is not None else None

        data.append({
            "file": os.path.basename(fp), "path": fp,
            "score": float(score) if score is not None else None,
            "jud": jud, "src": src,
            "hm": hm, "ana": ana,
            "peak": st["peak"] if st else None,
            "area": st["area"] if st else None,
            "conf": float(conf_map.mean()) if conf_map is not None else None,
        })

    shutil.rmtree(tmp_dir, ignore_errors=True)
    shutil.rmtree(batch_dir, ignore_errors=True)

    if not data:
        print("无有效检测结果")
        return

    # ===== 输出阶段 =====
    if OUTPUT_JSON:
        import json as _json
        records = []
        for d in data:
            records.append({
                "file": d["file"],
                "judgment": jud_simple(d["jud"]),
                "judgment_full": d["jud"],
                "source": d["src"],
                "score": round(d["score"], 4) if d["score"] is not None else None,
                "level": level_of(d["score"]) if d["score"] is not None else None,
                "area": round(d["area"], 4) if d["area"] is not None else None,
                "peak": round(d["peak"], 4) if d["peak"] is not None else None,
                "confidence": round(d["conf"], 4) if d["conf"] is not None else None,
            })
        path = os.path.join(out_dir, "TruFor检测结果.json")
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(records, f, ensure_ascii=False, indent=2)
        print(f"📄 JSON: {path}")

    if OUTPUT_EXCEL:
        build_universal_xlsx(data, out_dir)

    if SAVE_IMAGES:
        from trufor_pair import save_image_disk
        img_dir = os.path.join(out_dir, "images")
        for d in data:
            if d["hm"] is not None:
                save_image_disk(d["hm"], os.path.join(img_dir, f"{d['file']}_heatmap.png"))
            if d["ana"] is not None:
                save_image_disk(d["ana"], os.path.join(img_dir, f"{d['file']}_analysis.png"))
        print(f"🖼 图片已落盘: {img_dir}")

    outputs = []
    if OUTPUT_EXCEL: outputs.append(f"Excel: {out_dir}/TruFor检测结果.xlsx")
    if OUTPUT_JSON: outputs.append(f"JSON: {out_dir}/TruFor检测结果.json")
    if SAVE_IMAGES: outputs.append(f"Images: {out_dir}/images/")
    if outputs:
        print(f"\n完成：{', '.join(outputs)}")
    else:
        print("\n完成（仅终端输出）")


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


def jud_simple(jud):
    """纯净三态判定：是 / 不是 / 疑似（其他情况兜底显示疑似）"""
    if jud is None:
        return "疑似"
    if jud.startswith("是"):
        return "是"
    if jud.startswith("否"):
        return "不是"
    return "疑似"


def build_universal_xlsx(data, out_dir):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from trufor_pair import level_of, save_workbook_retry

    wb = Workbook()
    ws = wb.active
    ws.title = "TruFor检测结果"

    headers = [
        "文件名", "判定结果",
        "原图", "热力图", "分析图", "判定来源",
        "篡改概率", "篡改等级", "篡改区域占比", "篡改峰值", "置信度",
    ]
    hdr_font = Font(bold=True, size=11)
    hdr_fill = PatternFill("solid", fgColor="D9E1F2")
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = hdr_font; c.fill = hdr_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for idx, d in enumerate(data, 2):
        center = Alignment(horizontal="center", vertical="center")

        ws.cell(row=idx, column=1, value=d["file"]).alignment = center
        ws.cell(row=idx, column=2, value=jud_simple(d["jud"])).alignment = center
        if d["path"] and ENABLE_ORIGINAL_IMAGE:
            try:
                import numpy as np
                from PIL import Image as PILImage
                thumb = np.array(PILImage.open(d["path"]).convert("RGB"))
                embed_thumb(ws, thumb, f"C{idx}")
            except Exception:
                pass
        if d["hm"] is not None and ENABLE_HEATMAP:
            embed_thumb(ws, d["hm"], f"D{idx}")
        if d["ana"] is not None and ENABLE_ANALYSIS_IMAGE:
            embed_thumb(ws, d["ana"], f"E{idx}")
        ws.cell(row=idx, column=6, value=d["src"] or "").alignment = center

        if d["score"] is not None:
            ws.cell(row=idx, column=7, value=round(d["score"], 4)).alignment = center
            ws.cell(row=idx, column=8, value=level_of(d["score"])).alignment = center
        if d["area"] is not None:
            ws.cell(row=idx, column=9, value=round(d["area"], 4)).alignment = center
        if d["peak"] is not None:
            ws.cell(row=idx, column=10, value=round(d["peak"], 4)).alignment = center
        if d["conf"] is not None:
            ws.cell(row=idx, column=11, value=round(d["conf"], 4)).alignment = center

        ws.row_dimensions[idx].height = 150

    widths = {
        "A": 28, "B": 10,
        "C": 44, "D": 44, "E": 44, "F": 22,
        "G": 10, "H": 9, "I": 12, "J": 10, "K": 10,
    }
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    path = os.path.join(out_dir, "TruFor检测结果.xlsx")
    path = save_workbook_retry(wb, path)
    print(f"📊 Excel: {path}")


if __name__ == "__main__":
    main()
