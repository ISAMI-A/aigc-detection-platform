#!/usr/bin/env python3
"""
点位真实性核验 · 独立命令行工具（对标 ImageAuthenticityDetector/run.py）

不依赖 Web，直接命令行批量核验"整改图 vs 暗访图"是否为同一地点。
复用独立核心库 ImageVerifier（SceneVerifier + 文件名解析），与 Web 版共用同一套算法、
判定标准完全一致。分发时把 ImageVerifier 目录与本工具一起拷贝即可独立使用。

用法：
    python verify.py                                   # 使用下方默认配置
    python verify.py -dir "图片目录" -o output           # 自定义输入/输出
    python verify.py -dir D:\\点位图 --mode auto         # 文件名解析配对（含"整改图/暗访图"标识）
    python verify.py -dir D:\\测试图 --mode sequential   # 顺序配对（如 0.png ↔ 0p.jpg）
    python verify.py ... --device cuda --min-inliers 12 --min-ratio 0.15

输出：
    output/核验结果.xlsx    Excel 报告（判定/指标 + 整改图/暗访图/可视化图嵌入）
    output/vis/*.jpg        每对匹配可视化图（绿色连线 = RANSAC 内点）

配对逻辑：
    auto        按 (UUID, 地点名称) 分组，组内按编号排序后逐位配对（与 Web 版一致）
    sequential  全部图片按自然排序后相邻两两配对
依赖：已装在本仓库根目录 .venv（torch / lightglue / opencv / openpyxl）。
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# ==================== 默认配置（可直接修改后运行） ====================
# 图片目录（默认：ImageAuthenticityDetector/test_images/testss）
DEFAULT_IMAGE_DIR  = r'd:\Users\沈佳勇\Desktop\AIGC Detection\ImageAuthenticityDetector\test_images\testss'
# 输出目录（Excel + 可视化图写到这里）
DEFAULT_OUTPUT_DIR = r'output'
# 计算设备：'cuda'=GPU(推荐)  'cpu'=CPU(慢)
DEFAULT_DEVICE     = 'cuda'
# 最小内点数：12=严格  10=适中  8=宽松
DEFAULT_MIN_INLIERS = 12
# 内点比例：0.15=严格  0.10=适中  0.05=宽松
DEFAULT_MIN_RATIO   = 0.15
# 是否生成可视化图（--no-vis 关闭）
DEFAULT_SAVE_VIS    = True
# 配对模式：'auto'=文件名解析（含"整改图/暗访图"标识）  'sequential'=自然排序后相邻两两配对（如 0.png ↔ 0p.jpg）
DEFAULT_MODE        = "auto"

# ==================== 复用独立核心库（ImageVerifier） ====================
# 场景核验算法与文件名解析位于独立核心库，Web（web/smart_verify）与本 CLI 共用，
# 算法单一来源。分发时将 ImageVerifier 与本工具一起拷贝即可。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # AIGC Detection/
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ImageVerifier import SceneVerifier, parse_filename   # noqa: E402

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def natural_key(name: str):
    """自然排序：0.png < 0p.jpg < 1.png < ... < 10.png（数字按数值比较）。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def build_pairs(image_dir: str, mode: str = "auto"):
    """按模式构建配对。

    - mode="auto"：按 (UUID, 地点名称) 分组、组内按编号排序后逐位配对（与 Web 版一致）。
    - mode="sequential"：全部图片按自然排序后相邻两两配对（适用 0.png/0p.jpg 这类命名）。

    返回: [(整改图路径, 暗访图路径, uuid, 地点, 编号)]
    """
    files = sorted(os.listdir(image_dir), key=natural_key)
    files = [os.path.join(image_dir, f) for f in files if f.lower().endswith(IMG_EXT)]

    if mode == "sequential":
        # 按文件名数字编号分组配对（0.png ↔ 0p.jpg）；缺图只跳过该组，不产生错位。
        # 无数字编号的文件回退为自然排序后相邻配对。
        groups = defaultdict(list)
        ordered = []
        for path in files:
            m = re.match(r"(\d+)", Path(path).stem)
            (groups[m.group(1)] if m else ordered).append(path)
        pairs = []
        for g in groups.values():
            if len(g) >= 2:
                pairs.append((g[0], g[1], "", Path(g[0]).name, len(pairs)))
                if len(g) > 2:
                    print(f"  [跳过] 编号重复多余图片: {Path(g[2]).name}")
            else:
                print(f"  [跳过] 单张无配对: {Path(g[0]).name}")
        for i in range(0, len(ordered) - 1, 2):
            p1, p2 = ordered[i], ordered[i + 1]
            pairs.append((p1, p2, "", Path(p1).name, len(pairs)))
        if len(ordered) % 2 == 1:
            print(f"  [跳过] 单张无配对: {Path(ordered[-1]).name}")
        return pairs

    # mode == "auto"：文件名解析配对
    images = []
    for path in files:
        info = parse_filename(path)
        if not info:
            print(f"  [跳过] {Path(path).name}: 文件名不含 UUID/类型（需含「整改图」或「暗访图」）")
            continue
        images.append(info)

    zg_map = defaultdict(list)
    af_map = defaultdict(list)
    for info in images:
        key = (info["uuid"], info["location"])
        (zg_map if info["photo_type"] == "整改图" else af_map)[key].append(info)

    pairs = []
    keys = set(zg_map) | set(af_map)
    for key in sorted(keys, key=lambda k: (k[0], k[1] or "")):
        zlist = sorted(zg_map.get(key, []), key=lambda x: int(x["photo_num"] or 0))
        alist = sorted(af_map.get(key, []), key=lambda x: int(x["photo_num"] or 0))
        for i in range(max(len(zlist), len(alist))):
            z = zlist[i] if i < len(zlist) else None
            a = alist[i] if i < len(alist) else None
            if z and a:
                pairs.append((z["path"], a["path"], key[0], key[1] or "未知地点", i))
            elif z and not a:
                print(f"  [跳过] 整改图无对应暗访图: {z['filename']}")
            elif a and not z:
                print(f"  [跳过] 暗访图无对应整改图: {a['filename']}")
    return pairs


def export_excel(pairs, results, output_dir, save_vis):
    """导出核验结果 Excel（判定着色 + 整改图/暗访图/可视化图嵌入）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.drawing.image import Image as XLImage
    from PIL import Image as PILImage

    wb = Workbook()
    ws = wb.active
    ws.title = "核验结果"

    headers = ["UUID", "地点", "编号", "整改图", "暗访图",
               "是否同一场景", "置信度", "总匹配数", "内点数", "内点比例", "方法",
               "整改图", "暗访图", "匹配可视化"]
    green = PatternFill("solid", start_color="C6EFCE", end_color="C6EFCE")
    red = PatternFill("solid", start_color="FFC7CE", end_color="FFC7CE")
    hdr_fill = PatternFill("solid", start_color="4472C4", end_color="4472C4")
    border = Border(*[Side(style="thin")] * 4)

    for c, h in enumerate(headers, 1):
        cell = ws.cell(1, c, h)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = border

    row = 2
    for (p1, p2, uuid, loc, idx), r in zip(pairs, results):
        same = r["is_same"]
        text = "是" if same else "否"
        values = [uuid[:8] + "...", loc, idx, Path(p1).name, Path(p2).name,
                  text, round(r["confidence"], 4), r["total_matches"], r["inliers"],
                  round(r["ratio"], 4), r["method"]]
        for c, v in enumerate(values, 1):
            cell = ws.cell(row, c, v)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border
        fill = green if same else red
        for c in range(1, len(headers) + 1):
            ws.cell(row, c).fill = fill

        imgs = [p1, p2, r.get("vis") if save_vis else None]
        max_h = 0
        for col, p in zip((12, 13, 14), imgs):
            if not p or not os.path.exists(p):
                continue
            try:
                w, h = PILImage.open(p).size
                scale = 180 / w if w else 1
                xl = XLImage(p)
                xl.width, xl.height = 180, int(h * scale)
                ws.add_image(xl, f"{chr(64 + col)}{row}")
                max_h = max(max_h, xl.height)
            except Exception as e:
                print(f"  [导出] 嵌图失败({col}): {e}")
        if max_h:
            ws.row_dimensions[row].height = int(max_h * 0.75) + 8
        row += 1

    for i, w in enumerate([14, 18, 8, 36, 36, 12, 10, 10, 10, 10, 16, 30, 30, 30], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"

    out = os.path.join(output_dir, "核验结果.xlsx")
    wb.save(out)
    return out


def main():
    parser = argparse.ArgumentParser(description="点位真实性核验（独立命令行版）")
    parser.add_argument("-dir", "--input-dir", default=DEFAULT_IMAGE_DIR, help="图片目录")
    parser.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")
    parser.add_argument("--mode", default=DEFAULT_MODE, choices=["auto", "sequential"],
                        help="配对模式：auto=文件名解析（含整改图/暗访图标识）；sequential=自然排序后相邻配对（如 0.png↔0p.jpg）")
    parser.add_argument("--device", default=DEFAULT_DEVICE, choices=["cuda", "cpu"], help="计算设备")
    parser.add_argument("--min-inliers", type=int, default=DEFAULT_MIN_INLIERS, help="最小内点数")
    parser.add_argument("--min-ratio", type=float, default=DEFAULT_MIN_RATIO, help="最小内点比例")
    parser.add_argument("--no-vis", action="store_true", help="不生成可视化图")
    args = parser.parse_args()
    save_vis = not args.no_vis

    if not os.path.isdir(args.input_dir):
        print(f"图片目录不存在: {args.input_dir}")
        sys.exit(1)
    os.makedirs(args.output_dir, exist_ok=True)
    vis_dir = os.path.join(args.output_dir, "vis") if save_vis else None
    if vis_dir:
        os.makedirs(vis_dir, exist_ok=True)

    print("▶ 点位真实性核验启动")
    print(f"  ▶ 输入: {args.input_dir}")
    print(f"  ▶ 输出: {args.output_dir}")
    print(f"  ▶ 配对模式: {args.mode}  设备: {args.device}  内点阈值: {args.min_inliers}  内点比例: {args.min_ratio}")

    pairs = build_pairs(args.input_dir, args.mode)
    if not pairs:
        print("未找到可配对的图片（文件名需含 UUID 与「整改图/暗访图」标识）")
        sys.exit(0)
    print(f"  ▶ 检测到 {len(pairs)} 对配对")

    verifier = SceneVerifier(device=args.device,
                             min_inliers=args.min_inliers, min_ratio=args.min_ratio)
    results = []
    from tqdm import tqdm
    for i, (p1, p2, uuid, loc, idx) in enumerate(tqdm(pairs, desc="核验", unit="对"), 1):
        out = verifier.verify(p1, p2, save_vis_dir=vis_dir)
        r = {
            "is_same": out.is_same_scene, "confidence": out.confidence,
            "total_matches": out.total_matches, "inliers": out.ransac_inliers,
            "ratio": out.inlier_ratio, "method": out.method, "vis": out.vis_path,
        }
        results.append(r)
        tag = "✓ 同一场景" if r["is_same"] else ("✗ 不同场景" if r["inliers"] > 0 else "✗ 匹配点过少")
        print(f"[{i}/{len(pairs)}] {Path(p1).name} ↔ {Path(p2).name}  "
              f"判定:{tag}  内点:{r['inliers']}/{r['total_matches']}  比例:{r['ratio']:.3f}  方法:{r['method']}")

    # 终端汇总
    same_n = sum(1 for r in results if r["is_same"])
    rate = same_n / len(results) * 100 if results else 0
    print("─" * 60)
    print(f"📊 汇总: {same_n}/{len(results)} 对同一场景，通过率 {rate:.1f}%")

    # Excel 导出
    xlsx = export_excel(pairs, results, args.output_dir, save_vis)
    print(f"📊 Excel: {xlsx}")
    if vis_dir:
        print(f"📊 可视化: {vis_dir}")
    print("完成")


if __name__ == "__main__":
    main()
