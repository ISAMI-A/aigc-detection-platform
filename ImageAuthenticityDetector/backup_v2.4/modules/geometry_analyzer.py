"""
热力图连通域几何特征分析（V2）
========================================
目的：区分"画笔涂鸦圈标注"与"真实篡改区域"。

思路：
- 真实篡改（拼接/复制粘贴）在热力图上呈块状、实心、较饱满的区域
- 画笔圈标注呈细长弧线/曲线，在最小外接矩形内只占少量像素

每个连通域计算以下指标：
  rectangularity  矩形度     = 面积 / 最小外接矩形(MBR)面积    线条低(~0.05-0.2)，块状高(~0.4-0.9)
  solidity        紧致度     = 面积 / 凸包面积                弧线低，实心块高
  extent          延展度     = 面积 / 包围盒面积（=矩形度，用旋转矩形则为MBR）
  elongation      细长度     = MBR 长边 / 短边                线条高(>5)，块状低(<3)
  circularity     圆度       = 4π·面积 / 周长²                 细线低，实心高
"""
import cv2
import numpy as np


def component_geometry(mask, min_area=16):
    """对二值 mask 的每个连通域计算几何特征。

    参数：
        mask: 二值数组（bool 或 0/1 uint8），True 表示篡改候选像素
        min_area: 面积小于该值（像素数）的连通域视为微噪点忽略
    返回：
        list[dict]，每个有效连通域一个：
            {area, rect_w, rect_h, rectangularity, solidity, extent,
             elongation, circularity, bbox, center}
    """
    if mask.dtype != np.uint8:
        mask = (mask > 0).astype(np.uint8)
    mask_u8 = mask * 255 if mask.max() <= 1 else mask

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask_u8, 8)
    geos = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue

        ys, xs = np.where(labels == i)
        # 最小外接矩形（旋转矩形，对弧线更贴合）。
        # 注意：OpenCV 把像素当作"点"处理，minAreaRect 返回的矩形比实际像素
        # 占据面积小（如 30x30 块返回 29x29），导致矩形度>1。
        # 修正：坐标 +0.5，把像素视为 1x1 方块。
        pts = np.column_stack([xs, ys]).astype(np.float32) + 0.5
        rect = cv2.minAreaRect(pts)
        (w, h) = rect[1]
        mbr_area = max(w * h, 1.0)
        rect_w, rect_h = w, h

        # 凸包面积
        hull = cv2.convexHull(pts.astype(np.int32))
        hull_area = max(float(cv2.contourArea(hull)), 1.0)

        # 轮廓周长
        comp = (labels == i).astype(np.uint8)
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        perimeter = float(cv2.arcLength(contours[0], True)) if contours else 1.0

        short_side = min(w, h)
        geos.append({
            "area": area,
            "rect_w": float(w), "rect_h": float(h),
            "rectangularity": float(area / mbr_area),
            "solidity": float(area / hull_area),
            "extent": float(area / mbr_area),
            "elongation": float(max(w, h) / short_side) if short_side > 0 else 0.0,
            "circularity": float(4 * np.pi * area / (perimeter * perimeter)) if perimeter > 0 else 0.0,
            "bbox": (int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]),
                     int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])),
            "center": (float(stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] / 2),
                       float(stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] / 2)),
        })
    return geos


def summarize_geometry(geos):
    """汇总一张图的几何特征统计：
    - n_comp:        有效连通域数量
    - max_area:      最大连通域面积（像素）
    - max_rect:      最大连通域的矩形度
    - max_solidity:  最大连通域的紧致度
    - max_elong:     最大连通域的细长度
    - avg_rect:      有效连通域平均矩形度
    - avg_solidity:  有效连通域平均紧致度
    - line_like:     线状连通域数量（矩形度低 且 紧致度低）
    - block_like:    块状连通域数量（矩形度高 或 紧致度高）
    - solid_ratio:   块状数量 / 有效数量（>0 说明有成片块状区域）
    """
    if not geos:
        return {"n_comp": 0, "max_area": 0, "max_rect": 0.0, "max_solidity": 0.0,
                "max_elong": 0.0, "avg_rect": 0.0, "avg_solidity": 0.0,
                "line_like": 0, "block_like": 0, "solid_ratio": 0.0}

    best = max(geos, key=lambda g: g["area"])
    return {
        "n_comp": len(geos),
        "max_area": best["area"],
        "max_rect": best["rectangularity"],
        "max_solidity": best["solidity"],
        "max_elong": best["elongation"],
        "avg_rect": float(np.mean([g["rectangularity"] for g in geos])),
        "avg_solidity": float(np.mean([g["solidity"] for g in geos])),
    }


def is_line_component(g, rect_thr=0.30, solid_thr=0.55):
    """判断单个连通域是否"线状"（画笔弧线/圈线特征）：
    矩形度低（细长弧线占 MBR 比例小）且 紧致度低（非实心）。
    """
    return g["rectangularity"] < rect_thr and g["solidity"] < solid_thr


def is_brush_annotation(geos, rect_thr=0.30, solid_thr=0.55, min_n=1):
    """判断一张图的热力图是否属于"画笔涂鸦标注"（全部有效区域都是线状）：
    - 存在至少 min_n 个有效连通域
    - 且所有有效连通域都满足线状特征（无任何块状区域）
    """
    if len(geos) < min_n:
        return False
    return all(is_line_component(g, rect_thr, solid_thr) for g in geos)


if __name__ == "__main__":
    # 快速自测：实心块 vs 圆环弧线（模拟画笔圈） vs 细横线
    import numpy as np

    mask = np.zeros((200, 200), dtype=np.uint8)
    mask[20:60, 20:60] = 1           # 实心块（真篡改）
    # 画一个圆环模拟画笔圈（半径60，线宽10）
    yy, xx = np.ogrid[:200, :200]
    d = np.sqrt((xx - 140) ** 2 + (yy - 60) ** 2)
    mask[(d >= 55) & (d <= 65)] = 1
    mask[120:124, 20:160] = 1        # 细横线
    geos = component_geometry(mask)
    for g in sorted(geos, key=lambda x: -x["area"]):
        print({k: (round(v, 3) if isinstance(v, float) else v)
               for k, v in g.items() if k not in ("bbox", "center")})
    print("is_brush_annotation(all):", is_brush_annotation(geos))
