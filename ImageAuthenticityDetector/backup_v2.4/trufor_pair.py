"""
TruFor 精简版：原图 vs P图 成对检测
========================================
- 只使用 TruFor 模型（其余 AI/Patch/DIRE/噪声 检测全部不加载）
- 生成热力图并直接嵌入 Excel，不单独保存图片文件
- 从原 JSON 报告中挑选有参考价值的字段（篡改等级/EXIF/GPS/编辑软件/综合风险/问题标记）
  合并进表格；其余信息一律丢弃，不生成 JSON
- 输出：单个 Excel（仅此一个文件，TruFor 中间产物自动清理）

用法：
    python trufor_pair.py -dir <图片目录> -o <输出目录>

配对规则：同一目录下 "数字.png" 为原图，"数字p.jpg/png" 为对应 P 图。
"""
import argparse
import io
import logging
import os
import re
import shutil
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

warnings.filterwarnings("ignore")
for _n in ["requests", "urllib3", "huggingface_hub", "diffusers", "filelock", "PIL"]:
    logging.getLogger(_n).setLevel(logging.ERROR)

import cv2
import numpy as np
from PIL import Image as PILImage

from config import (MAX_IMAGE_SIZE, TEMP_DIR, TRUFOR_PATH,
                    THRESHOLD_FORGERY_HIGH, THRESHOLD_FORGERY_MED,
                    FUSE_PEAK, FUSE_AREA, CONF_THRESHOLD, COMP_MIN_AREA,
                    COMP_RATIO, COMP_N_SPOTS, GEOM_RECT, GEOM_SOLID, GEOM_MIN_AREA,
                    GEOM_LOC_THR, GEOM_LINE_RATIO, SUSPECT_LOC_THR, SUSPECT_UP_THR,
                    EDGE_BAND, EDGE_TOUCH_RATIO, EDGE_BAND_RATIO)
from modules.image_preprocess import preprocess
from modules.forgery_detector import TruForDetector
from modules.exif_analyzer import analyze_exif
from modules.geometry_analyzer import component_geometry

# TruFor 判定阈值（可通过环境变量 TRUFOR_THRESHOLD 覆盖，由 run.py 传入）
THRESHOLD = float(os.environ.get("TRUFOR_THRESHOLD", 0.5))


def parse_name(fn):
    """'0p.jpg' -> ('0', True)；'0.png' -> ('0', False)"""
    stem, _ = os.path.splitext(fn)
    if stem.endswith("p"):
        return stem[:-1], True
    return stem, False


def natural_key(s):
    """自然排序键：数字段按数值比较（0,1,2,...,10,11,...），避免字符串排序的 0,1,10,11..."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", s)]


def collect_pairs(img_dir):
    """收集所有图片并按编号配对；返回 {base: {"orig":路径|None, "p":路径|None}}。
    不成对的（只有原图或只有P图）也保留，单独检测。按自然顺序（0,1,2,...）排列。"""
    pairs = {}
    for f in sorted(os.listdir(img_dir)):
        if not f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
            continue
        base, is_p = parse_name(f)
        full = os.path.join(img_dir, f)
        pairs.setdefault(base, {"orig": None, "p": None})
        if is_p:
            pairs[base]["p"] = full
        else:
            pairs[base]["orig"] = full
    return {base: pairs[base] for base in sorted(pairs, key=natural_key)}


def make_heatmap(loc_map):
    """TruFor loc_map(0-1 float) → JET 热力图 RGB ndarray"""
    gray = np.clip(loc_map * 255, 0, 255).astype(np.uint8)
    bgr = cv2.applyColorMap(gray, cv2.COLORMAP_JET)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def draw_analysis(img, loc):
    """画笔检测分析图（供表格/可视化）：
    深红区(loc>=GEOM_LOC_THR 无conf)半透明红叠加 + 膨胀9px轮廓(青色细线) + 线状连通域框(绿色)。
    img: RGB ndarray（原图）；loc: 预处理后的定位图。
    """
    h_l, w_l = loc.shape
    ih, iw = img.shape[:2]
    sx, sy = iw / w_l, ih / h_l

    mask = (loc >= GEOM_LOC_THR).astype(np.uint8)
    over = img.copy()
    m = cv2.resize(mask, (iw, ih), interpolation=cv2.INTER_NEAREST).astype(bool)
    red = np.zeros_like(img)
    red[m] = (255, 0, 0)
    over = cv2.addWeighted(over, 0.65, red, 0.55, 0)

    dil = cv2.dilate(mask, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        c2 = cnt.astype(np.float32)
        c2[:, 0, 0] *= sx
        c2[:, 0, 1] *= sy
        cv2.polylines(over, [c2.astype(np.int32)], True, (0, 255, 255), 1)

    geos = component_geometry(mask)
    for g in geos:
        if g["rectangularity"] < GEOM_RECT and g["solidity"] < GEOM_SOLID and g["area"] >= GEOM_MIN_AREA:
            x, y, bw, bh = g["bbox"]
            cv2.rectangle(over, (int(x * sx), int(y * sy)),
                          (int((x + bw) * sx), int((y + bh) * sy)), (0, 255, 0), 2)
    return over


def judge_source(jud, st, score):
    """判定来源说明：区分一轮（基础判定）与二轮（画笔标注复核/疑似升判）"""
    if jud is None:
        return ""
    if jud == "否（画笔标注）":
        if st:
            a = (st["max_rect"] < GEOM_RECT and st["max_solid"] < GEOM_SOLID
                 and st["max_area"] >= GEOM_MIN_AREA)
            b = st["deep_ratio"] >= GEOM_LINE_RATIO
            if a and b:
                return "二轮:常规线状+深红线状"
            if a:
                return "二轮:常规线状"
            return "二轮:深红线状"
        return "二轮"
    if jud == "否（边缘误检）":
        return "二轮:边缘误检"
    if jud == "是（有篡改痕迹）":
        # 疑似升判：score 未达阈值但深红区占比达标（V2.2）
        if st is not None and score is not None and score < THRESHOLD:
            return "二轮:深红升判"
        return "一轮:概率达标"
    if jud == "否（深红区过小）":
        return "一轮:深红区过小"
    if jud == "否（散点噪声）":
        return "一轮:散点降级"
    return "一轮:概率低"


def deep_red_stats(loc):
    """深红线状检测（画笔圈线提取）：
    画圈线在热力图上呈深红弧线（loc 高），但模型对画笔线的置信度 conf 偏低（<0.5），
    会被常规 mask 的 conf 条件滤掉。这里单独用高 loc 阈值（无 conf 限制）提取深红区，
    统计其中"线状"连通域（矩形度<GEOM_RECT 且紧致度<GEOM_SOLID 且面积>=GEOM_MIN_AREA）
    的面积占比：画圈线的深红区以细长弧线为主 → 占比高；真篡改块状 → 占比接近 0。
    返回 (线状面积占比, 深红区总面积)。
    """
    mask = (loc >= GEOM_LOC_THR).astype(np.uint8)
    geos = component_geometry(mask, min_area=COMP_MIN_AREA)
    total = sum(g["area"] for g in geos)
    if total == 0:
        return 0.0, 0
    line_area = sum(g["area"] for g in geos
                    if g["rectangularity"] < GEOM_RECT and g["solidity"] < GEOM_SOLID
                    and g["area"] >= GEOM_MIN_AREA)
    return line_area / total, total


def loc_stats(loc, conf):
    """定位图增强统计（置信度加权 + 连通域分析 + 几何特征）：
    - peak:      篡改峰值（全图最大值）
    - area:      篡改面积占比（全图均值，兼容旧指标）
    - conf_area: 高置信篡改面积占比（loc>=0.5 且 conf>=CONF_THRESHOLD 的像素比例，
                 只统计"又红又有把握"的区域，过滤模型犹豫区域）
    - max_comp:  最大连通域面积占比（归一化到图面积，区分成片篡改与散点噪声）
    - n_comp:    有效连通域数量（面积>=COMP_MIN_AREA 的成片区域个数）
    - max_rect / max_solid / max_area: 最大连通域的几何特征（V2 画笔标注识别用）——
      红色画笔圈/涂鸦在热力图上呈细长弧线，最小外接矩形内像素占比低（矩形度小）、
      非实心（紧致度小）；真篡改块通常矩形度/紧致度较高。
    """
    h, w = loc.shape
    tot = h * w
    peak = float(loc.max())
    area = float(loc.mean())
    mask = (loc >= 0.5) & (conf >= CONF_THRESHOLD)
    conf_area = float(mask.mean())
    # 连通域分析：成片红色(真篡改) vs 散点红点(噪声)
    n, _, stats, _ = cv2.connectedComponentsWithStats((mask * 255).astype(np.uint8), 8)
    if n <= 1:
        max_comp, n_comp = 0.0, 0
    else:
        areas = stats[1:, cv2.CC_STAT_AREA]
        areas = areas[areas >= COMP_MIN_AREA]
        max_comp = float(areas.max() / tot) if len(areas) else 0.0
        n_comp = int(len(areas))
    # V2 几何特征：最大连通域的矩形度/紧致度/面积（mask=loc>=0.5 & conf>=0.5）
    geos = component_geometry(mask, min_area=COMP_MIN_AREA)
    if geos:
        best = max(geos, key=lambda g: g["area"])
        max_rect, max_solid, max_area = (best["rectangularity"], best["solidity"], best["area"])
    else:
        max_rect = max_solid = 0.0
        max_area = 0
    # V2 深红线状特征（mask=loc>=GEOM_LOC_THR，无 conf）：识别画圈线（线状面积占比）
    deep_ratio, deep_total = deep_red_stats(loc)
    # V2.2 疑似升判特征：深红区（loc>=SUSPECT_LOC_THR 无 conf）占比
    loc75 = float((loc >= SUSPECT_LOC_THR).mean())
    # V2.4 边缘误检特征（mask=loc>=0.5）：红色是否"完全贴边"（直接触及图像边界，无蓝色间隔）
    mask50 = (loc >= 0.5)
    red_total = int(mask50.sum())
    if red_total > 0:
        hh, ww = mask50.shape
        by0, by1 = int(hh * EDGE_BAND), int(hh * (1 - EDGE_BAND))
        bx0, bx1 = int(ww * EDGE_BAND), int(ww * (1 - EDGE_BAND))
        edge_red = red_total - int(mask50[by0:by1, bx0:bx1].sum())
        edge_band_ratio = edge_red / red_total
        # 贴边连通域：bbox 触及图像边界（红色到达边缘 = 与边缘之间无蓝色间隔）
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask50.astype(np.uint8), 8)
        touch = 0
        if n > 1:
            for s in stats[1:]:
                x, y, bw, bh, a = s
                if x <= 1 or y <= 1 or x + bw >= ww - 1 or y + bh >= hh - 1:
                    touch += int(a)
        touch_ratio = touch / red_total
    else:
        edge_band_ratio, touch_ratio = 0.0, 0.0
    return {"peak": peak, "area": area, "conf_area": conf_area,
            "max_comp": max_comp, "n_comp": n_comp,
            "max_rect": max_rect, "max_solid": max_solid, "max_area": max_area,
            "deep_ratio": deep_ratio, "deep_total": deep_total, "loc75": loc75,
            "touch_ratio": touch_ratio, "edge_band_ratio": edge_band_ratio}


def level_of(prob):
    """篡改等级：高/中/低（对齐 JSON 报告 tampering.level）"""
    if prob >= THRESHOLD_FORGERY_HIGH:
        return "高"
    if prob >= THRESHOLD_FORGERY_MED:
        return "中"
    return "低"


def judge(score, st):
    """多指标融合判定（三级 + V2 画笔标注降级）：
    - 篡改概率 >= 判定阈值 → "是（有篡改痕迹）"，
      但若满足画笔标注特征 → 降级为"否（画笔标注）"：
        a) 常规线状（mask=loc>=0.5&conf>=0.5 最大连通域矩形度<GEOM_RECT 且紧致度<GEOM_SOLID 且面积>=GEOM_MIN_AREA）
        b) 深红线状（mask=loc>=GEOM_LOC_THR 无 conf，深红区"线状面积占比">=GEOM_LINE_RATIO）
      或满足边缘误检特征（V2.4：贴边面积占比>=EDGE_TOUCH_RATIO 且 边缘带红色占比>=EDGE_BAND_RATIO）
        → 红色主体完全贴边（直接触及图像边界、与边缘间无蓝色间隔）且集中在边缘带，
          判定为模型边缘误检，降级为"否（边缘误检）"
    - 否则 峰值>=FUSE_PEAK 且 面积占比>=FUSE_AREA（loc 全图均值）→ 疑似候选：
        - 但若 最大成片占比 < COMP_RATIO 且 有效连通域数 >= COMP_N_SPOTS
          → 判定为散点红点（噪声）而非成片篡改，降级为"否（散点噪声）"
        - 若 深红区占比 >= SUSPECT_UP_THR（V2.2 疑似升判，loc>=SUSPECT_LOC_THR 无 conf）
          → 升判"是（有篡改痕迹）"
        - 否则 深红区占比 < SUSPECT_UP_THR（增强图红色区域很小/很少）
          → 降级为"否（深红区过小）"（V2.3：模型未检测出显著篡改，宁缺毋滥）
    - 否则 → "否"
    score 为 None（未检测该图）时返回 None。
    """
    if score is None:
        return None
    if score >= THRESHOLD:
        if st is not None:
            a_line = (st["max_rect"] < GEOM_RECT and st["max_solid"] < GEOM_SOLID
                      and st["max_area"] >= GEOM_MIN_AREA)
            b_line = st["deep_ratio"] >= GEOM_LINE_RATIO
            if a_line or b_line:
                return "否（画笔标注）"
            # V2.4 边缘误检降级：红色主体完全贴边（直接触及图像边界、无蓝色间隔）
            # 且红色集中在四周边缘带内 → 模型边缘误检（如 testss 2/13 原图右边缘竖带）
            if (st["touch_ratio"] >= EDGE_TOUCH_RATIO
                    and st["edge_band_ratio"] >= EDGE_BAND_RATIO):
                return "否（边缘误检）"
        return "是（有篡改痕迹）"
    if st is not None and st["peak"] >= FUSE_PEAK and st["area"] >= FUSE_AREA:
        if st["max_comp"] < COMP_RATIO and st["n_comp"] >= COMP_N_SPOTS:
            return "否（散点噪声）"
        if st["loc75"] >= SUSPECT_UP_THR:
            return "是（有篡改痕迹）"
        return "否（深红区过小）"
    return "否"


def risk_of_jud(jud):
    """判定结果 → 综合风险"""
    if jud is None:
        return "LOW"
    if jud.startswith("是"):
        return "HIGH"
    if jud.startswith("疑似"):
        return "MEDIUM"
    return "LOW"


def embed_image(ws, img_array, cell, max_w=300, max_h=200):
    """把图片数组缩略后嵌入 Excel 单元格"""
    thumb = PILImage.fromarray(img_array)
    thumb.thumbnail((max_w, max_h))
    buf = io.BytesIO()
    thumb.save(buf, format="PNG")
    buf.seek(0)
    from openpyxl.drawing.image import Image as XLImage
    ws.add_image(XLImage(buf), cell)


def main():
    parser = argparse.ArgumentParser(description="TruFor 精简版：原图 vs P图 成对检测")
    parser.add_argument("-dir", required=True,
                        help="图片目录（数字.png=原图，数字p.jpg=对应P图）或单个图片文件（绝对/相对路径均可）")
    parser.add_argument("-o", default="./output_trufor", help="输出目录")
    args = parser.parse_args()

    img_dir = os.path.abspath(args.dir)
    out_dir = os.path.abspath(args.o)
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

    # TruFor 中间产物（mask.png/report.json）统一放子目录，结束时整体删除，只留 Excel
    tmp_dir = os.path.join(out_dir, "_trufor_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    # 单个图片文件：直接单独检测；目录：按 数字.png=原图 / 数字p.jpg=P图 配对
    if os.path.isfile(img_dir):
        fname = os.path.basename(img_dir)
        base, is_p = parse_name(fname)
        pair = {"orig": img_dir if not is_p else None,
                "p": img_dir if is_p else None}
        pairs = {base: pair}
        print(f"单文件模式：{fname}（{'P图' if is_p else '原图'}）")
    else:
        pairs = collect_pairs(img_dir)
    if not pairs:
        print("未找到图片（需要 数字.png 原图 + 数字p.jpg P图）")
        return

    # 预处理所有图片，统一放到 batch 目录（TruFor 一次批量检测，模型只加载一次）
    batch_dir = os.path.join(TEMP_DIR, "trufor_batch")
    os.makedirs(batch_dir, exist_ok=True)
    plan = []  # (base, pair, 预处理后的P图文件名|None, 预处理后的原图文件名|None)
    total = len(pairs)
    for idx, (base, pair) in enumerate(pairs.items(), 1):
        try:
            p_name = o_name = None
            if pair["p"]:
                p_name = os.path.basename(preprocess(pair["p"], MAX_IMAGE_SIZE, batch_dir))
            if pair["orig"]:
                o_name = os.path.basename(preprocess(pair["orig"], MAX_IMAGE_SIZE, batch_dir))
            plan.append((base, pair, p_name, o_name))
            print(f"\r  ⌛ 预处理 {idx}/{total}（{base}）...", end="", flush=True)
        except Exception as e:
            print(f"\n  ✗ {base}: 预处理失败 - {e}")
    print()
    if not plan:
        print("全部图片预处理失败，无结果")
        return

    print(f"共 {len(plan)} 组图片，开始 TruFor 批量检测（模型只加载一次）...")
    trufor = TruForDetector(TRUFOR_PATH)
    # 批量失败时自动重试一次（首次启动偶发失败兜底）
    try:
        results = trufor.predict_batch(batch_dir, tmp_dir)
    except Exception as e:
        print(f"⚠ 首次批量检测失败({e})，自动重试...")
        results = trufor.predict_batch(batch_dir, tmp_dir)

    # ===== 预判：先算每张图的初步判定（供统计循环复用，避免重复计算 loc_stats） =====
    pre = {}  # name -> (jud, st)
    for name, (score, loc, conf) in results.items():
        st = loc_stats(loc, conf) if (loc is not None and conf is not None) else None
        pre[name] = (judge(score, st), st)

    data = []
    for i, (base, pair, p_name, o_name) in enumerate(plan, 1):
        fp_p = fp_o = None
        loc_p = loc_o = None
        conf_p = conf_o = None
        if p_name and p_name in results:
            fp_p, loc_p, conf_p = results[p_name]
        if o_name and o_name in results:
            fp_o, loc_o, conf_o = results[o_name]
        if fp_p is None and fp_o is None:
            print(f"[{i}/{len(plan)}] {base} ✗ TruFor 未生成结果")
            continue

        # 图片信息
        size_o = size_p = ""
        ofmt = ""
        if pair["orig"]:
            with PILImage.open(pair["orig"]) as im:
                size_o = f"{im.size[0]}x{im.size[1]}"
                ofmt = im.format
        if pair["p"]:
            with PILImage.open(pair["p"]) as im:
                size_p = f"{im.size[0]}x{im.size[1]}"
        # 编辑软件取自 P 图（PS 等痕迹多出现在 P 图），P 图没有再看原图
        software = (analyze_exif(pair["p"]).get("software") if pair["p"] else None) \
            or (analyze_exif(pair["orig"]).get("software") if pair["orig"] else None) or ""

        # 判定与统计复用预判结果（第一轮已算，避免重复计算 loc_stats）
        jud_p, st_p = pre.get(p_name, (None, None)) if p_name else (None, None)
        jud_o, st_o = pre.get(o_name, (None, None)) if o_name else (None, None)

        # 分析图（深红区+膨胀轮廓+线状框）与判定来源
        ana_p = (draw_analysis(np.array(PILImage.open(pair["p"]).convert("RGB")), loc_p)
                 if loc_p is not None and pair["p"] else None)
        ana_o = (draw_analysis(np.array(PILImage.open(pair["orig"]).convert("RGB")), loc_o)
                 if loc_o is not None and pair["orig"] else None)
        src_p = judge_source(jud_p, st_p, fp_p)
        src_o = judge_source(jud_o, st_o, fp_o)

        # 问题标记
        flags = []
        if software:
            flags.append(f"检测到编辑软件: {software}")
        if jud_p == "是（有篡改痕迹）":
            flags.append("P图篡改概率高")
        elif jud_p == "否（边缘误检）":
            flags.append("P图热力图红色完全贴边（边缘误检特征），已降级")
        elif jud_p == "否（深红区过小）":
            flags.append("P图热力图深红区过小，已按非篡改降级")
        elif jud_p == "否（散点噪声）":
            flags.append("P图热力图呈散点状，已按噪声降级")
        elif jud_p == "否（画笔标注）":
            flags.append("P图热力图呈线状弧线（画笔圈/涂鸦特征），已降级")
        if jud_o == "是（有篡改痕迹）":
            flags.append("原图也判异常")
        elif jud_o == "否（边缘误检）":
            flags.append("原图热力图红色完全贴边（边缘误检特征），已降级")
        elif jud_o == "否（深红区过小）":
            flags.append("原图热力图深红区过小，已按非篡改降级")
        elif jud_o == "否（散点噪声）":
            flags.append("原图热力图呈散点状，已按噪声降级")
        elif jud_o == "否（画笔标注）":
            flags.append("原图热力图呈线状弧线（画笔圈/涂鸦特征），已降级")

        info = f"P图:{fp_p:.3f}" if fp_p is not None else "P图:无"
        info += f" 原图:{fp_o:.3f}" if fp_o is not None else " 原图:无"
        print(f"[{i}/{len(plan)}] {base} {info}")

        data.append({
            "base": base, "p_path": pair["p"], "orig_path": pair["orig"],
            "fp_p": fp_p, "fp_o": fp_o,
            "jud_p": jud_p, "jud_o": jud_o,
            "hm_p": make_heatmap(loc_p) if loc_p is not None else None,
            "hm_o": make_heatmap(loc_o) if loc_o is not None else None,
            "ana_p": ana_p, "ana_o": ana_o, "src_p": src_p, "src_o": src_o,
            "area_p": st_p["area"] if st_p else None, "area_o": st_o["area"] if st_o else None,
            "peak_p": st_p["peak"] if st_p else None, "peak_o": st_o["peak"] if st_o else None,
            "conf_area_p": st_p["conf_area"] if st_p else None,
            "conf_area_o": st_o["conf_area"] if st_o else None,
            "max_comp_p": st_p["max_comp"] if st_p else None,
            "max_comp_o": st_o["max_comp"] if st_o else None,
            "n_comp_p": st_p["n_comp"] if st_p else None,
            "n_comp_o": st_o["n_comp"] if st_o else None,
            "conf_p": float(conf_p.mean()) if conf_p is not None else None,
            "conf_o": float(conf_o.mean()) if conf_o is not None else None,
            "size_o": size_o, "size_p": size_p, "fmt": ofmt,
            "software": software,
            "flags": flags,
        })

    # 生成 Excel
    build_xlsx(data, out_dir)

    # 清理中间产物与预处理临时文件
    shutil.rmtree(tmp_dir, ignore_errors=True)
    shutil.rmtree(batch_dir, ignore_errors=True)
    print(f"\n完成：{out_dir}/TruFor检测结果.xlsx")


def save_workbook_retry(wb, path):
    """保存 Excel；文件被占用（PermissionError）时自动改名重试（名1、名2...），
    避免推理白跑。返回实际保存的文件路径。"""
    attempt = 0
    while True:
        try:
            wb.save(path)
            return path
        except PermissionError:
            attempt += 1
            stem, ext = os.path.splitext(path)
            path = f"{stem}{attempt}{ext}"


def build_xlsx(data, out_dir):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "TruFor检测结果"

    headers = [
        "文件名", "P图", "原图", "热力图(P图)", "热力图(原图)",
        "篡改判定(P图)", "篡改判定(原图)",
        "分析图(P图)", "分析图(原图)", "判定来源(P图)", "判定来源(原图)",
        "篡改概率(P图)", "篡改等级(P图)", "篡改区域占比(P图)", "篡改峰值(P图)", "高置信面积(P图)", "最大成片(P图)", "置信度(P图)",
        "篡改概率(原图)", "篡改等级(原图)", "篡改区域占比(原图)", "篡改峰值(原图)", "高置信面积(原图)", "最大成片(原图)", "置信度(原图)",
        "综合风险", "问题标记",
        "尺寸(原图)", "尺寸(P图)", "格式", "编辑软件", "备注"
    ]
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill("solid", fgColor="D9E1F2")
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for idx, d in enumerate(data, 2):
        row = idx
        jud_p = d["jud_p"]
        jud_o = d["jud_o"]

        # 自动备注
        notes = []
        if jud_p is not None and jud_o is not None:
            if jud_p.startswith("是") and d["fp_p"] > d["fp_o"] + 0.1:
                notes.append("P图篡改概率显著高于原图，疑似P图")
            elif jud_p.startswith("是"):
                notes.append("P图判定有篡改痕迹")
            elif jud_p == "否（边缘误检）":
                notes.append("P图热力图红色完全贴边（与边缘间无蓝色间隔），已按模型边缘误检降级")
            elif jud_p == "否（深红区过小）":
                notes.append("P图热力图深红区过小（红色区域很小/很少），已按非篡改降级")
            elif jud_p == "否（散点噪声）":
                notes.append("P图热力图呈散点状，已按噪声降级")
            elif jud_p == "否（画笔标注）":
                notes.append("P图热力图呈线状弧线，符合画笔圈/涂鸦标注特征，已按非篡改降级")
            else:
                notes.append("P图篡改概率低（可能为隐蔽擦除或调色/裁剪）")
            if jud_o.startswith("是"):
                notes.append("原图也判异常（水面/平滑场景可能误报，建议人工复核）")
            elif jud_o == "否（边缘误检）":
                notes.append("原图热力图红色完全贴边（与边缘间无蓝色间隔），已按模型边缘误检降级")
            elif jud_o == "否（深红区过小）":
                notes.append("原图热力图深红区过小（红色区域很小/很少），已按非篡改降级")
            elif jud_o == "否（散点噪声）":
                notes.append("原图热力图呈散点状，已按噪声降级")
            elif jud_o == "否（画笔标注）":
                notes.append("原图热力图呈线状弧线，符合画笔圈/涂鸦标注特征，已按非篡改降级")
        elif jud_p is None and jud_o is not None:
            notes.append("无对应P图，单独检测原图")
            if jud_o.startswith("是"):
                notes.append("原图判异常（水面/平滑场景可能误报，建议人工复核）")
            elif jud_o == "否（边缘误检）":
                notes.append("原图热力图红色完全贴边（与边缘间无蓝色间隔），已按模型边缘误检降级")
            elif jud_o == "否（深红区过小）":
                notes.append("原图热力图深红区过小（红色区域很小/很少），已按非篡改降级")
            elif jud_o == "否（散点噪声）":
                notes.append("原图热力图呈散点状，已按噪声降级")
            elif jud_o == "否（画笔标注）":
                notes.append("原图热力图呈线状弧线，符合画笔圈/涂鸦标注特征，已按非篡改降级")
        elif jud_o is None and jud_p is not None:
            notes.append("无对应原图，单独检测P图")
            if jud_p.startswith("是"):
                notes.append("P图判定有篡改痕迹")
            elif jud_p == "否（边缘误检）":
                notes.append("P图热力图红色完全贴边（与边缘间无蓝色间隔），已按模型边缘误检降级")
            elif jud_p == "否（深红区过小）":
                notes.append("P图热力图深红区过小（红色区域很小/很少），已按非篡改降级")
            elif jud_p == "否（散点噪声）":
                notes.append("P图热力图呈散点状，已按噪声降级")
            elif jud_p == "否（画笔标注）":
                notes.append("P图热力图呈线状弧线，符合画笔圈/涂鸦标注特征，已按非篡改降级")
        note = "；".join(notes) if notes else ""

        center = Alignment(horizontal="center", vertical="center")
        ws.cell(row=row, column=1, value=d["base"]).alignment = center
        # 判定结果（单独检测时对应列留空）
        if jud_p is not None:
            ws.cell(row=row, column=6, value=jud_p).alignment = center
        if jud_o is not None:
            ws.cell(row=row, column=7, value=jud_o).alignment = center
        # 判定来源（一轮/二轮说明）
        ws.cell(row=row, column=10, value=d["src_p"]).alignment = center
        ws.cell(row=row, column=11, value=d["src_o"]).alignment = center
        # P图参数指标
        if d["fp_p"] is not None:
            ws.cell(row=row, column=12, value=round(d["fp_p"], 4)).alignment = center
            ws.cell(row=row, column=13, value=level_of(d["fp_p"])).alignment = center
            ws.cell(row=row, column=14, value=round(d["area_p"], 4)).alignment = center
            ws.cell(row=row, column=15, value=round(d["peak_p"], 4)).alignment = center
            ws.cell(row=row, column=16, value=round(d["conf_area_p"], 4)).alignment = center
            ws.cell(row=row, column=17, value=round(d["max_comp_p"], 4)).alignment = center
            ws.cell(row=row, column=18, value=round(d["conf_p"], 4)).alignment = center
        # 原图参数指标
        if d["fp_o"] is not None:
            ws.cell(row=row, column=19, value=round(d["fp_o"], 4)).alignment = center
            ws.cell(row=row, column=20, value=level_of(d["fp_o"])).alignment = center
            ws.cell(row=row, column=21, value=round(d["area_o"], 4)).alignment = center
            ws.cell(row=row, column=22, value=round(d["peak_o"], 4)).alignment = center
            ws.cell(row=row, column=23, value=round(d["conf_area_o"], 4)).alignment = center
            ws.cell(row=row, column=24, value=round(d["max_comp_o"], 4)).alignment = center
            ws.cell(row=row, column=25, value=round(d["conf_o"], 4)).alignment = center
        # 综合风险：优先按 P 图判定，P 图缺失时按原图
        ref_jud = jud_p if jud_p is not None else jud_o
        ws.cell(row=row, column=26, value=risk_of_jud(ref_jud)).alignment = center
        ws.cell(row=row, column=27, value="；".join(d["flags"])).alignment = Alignment(wrap_text=True, vertical="center")
        ws.cell(row=row, column=28, value=d["size_o"]).alignment = center
        ws.cell(row=row, column=29, value=d["size_p"]).alignment = center
        ws.cell(row=row, column=30, value=d["fmt"]).alignment = center
        ws.cell(row=row, column=31, value=d["software"]).alignment = center
        ws.cell(row=row, column=32, value=note).alignment = Alignment(wrap_text=True, vertical="center")

        # 嵌入缩略图（P图/原图/热力图×2/分析图×2，缺失的不嵌入）
        if d["p_path"]:
            embed_image(ws, np.array(PILImage.open(d["p_path"]).convert("RGB")), f"B{row}")
        if d["orig_path"]:
            embed_image(ws, np.array(PILImage.open(d["orig_path"]).convert("RGB")), f"C{row}")
        if d["hm_p"] is not None:
            embed_image(ws, d["hm_p"], f"D{row}")
        if d["hm_o"] is not None:
            embed_image(ws, d["hm_o"], f"E{row}")
        if d["ana_p"] is not None:
            embed_image(ws, d["ana_p"], f"H{row}")
        if d["ana_o"] is not None:
            embed_image(ws, d["ana_o"], f"I{row}")

        ws.row_dimensions[row].height = 150

    widths = {"A": 8, "B": 44, "C": 44, "D": 44, "E": 44,
              "F": 15, "G": 15, "H": 44, "I": 44, "J": 22, "K": 22,
              "L": 11, "M": 10, "N": 12, "O": 10, "P": 11, "Q": 11, "R": 10,
              "S": 11, "T": 10, "U": 12, "V": 10, "W": 11, "X": 11, "Y": 10,
              "Z": 10, "AA": 28,
              "AB": 11, "AC": 11, "AD": 7, "AE": 18, "AF": 40}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    path = os.path.join(out_dir, "TruFor检测结果.xlsx")
    path = save_workbook_retry(wb, path)
    print(f"📊 Excel: {path}")


if __name__ == "__main__":
    main()
