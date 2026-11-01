"""
可视化模块
生成标注对比图，用于 Excel 嵌入和人工复核
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _get_font(size: int = 24) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """获取字体，优先使用系统中文字体"""
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",      # 黑体
        "C:/Windows/Fonts/simsun.ttc",      # 宋体
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def create_annotated_comparison(
    before_path: str | Path,
    after_path: str | Path,
    output_path: str | Path,
    result: dict,
    scenario: str,
    max_width: int = 1600,
) -> Path:
    """
    生成带标注的对比图，在底部添加分析结论文字。
    """
    img_before = Image.open(before_path).convert("RGB")
    img_after = Image.open(after_path).convert("RGB")

    target_w = min(max_width // 2, img_before.width, img_after.width)
    scale = min(target_w / img_before.width, target_w / img_after.width)
    new_w = int(img_before.width * scale)
    new_h_b = int(img_before.height * scale)
    new_h_a = int(img_after.height * scale)

    img_before = img_before.resize((new_w, new_h_b), Image.LANCZOS)
    img_after = img_after.resize((new_w, new_h_a), Image.LANCZOS)

    # 底部信息栏高度
    info_height = 120
    label_height = 36
    content_h = max(new_h_b, new_h_a)
    canvas_w = new_w * 2 + 4
    canvas_h = content_h + label_height + info_height

    canvas = Image.new("RGB", (canvas_w, canvas_h), (30, 30, 30))
    draw = ImageDraw.Draw(canvas)
    font = _get_font(18)
    font_small = _get_font(14)

    # 标签
    if scenario == "detect":
        lb, la = "旧时影像 (Before)", "现在影像 (After)"
    else:
        lb, la = "整改前 (Before)", "整改后 (After)"

    draw.rectangle([0, 0, new_w, label_height], fill=(50, 50, 50))
    bbox = draw.textbbox((0, 0), lb, font=font)
    draw.text(((new_w - (bbox[2] - bbox[0])) // 2, (label_height - (bbox[3] - bbox[1])) // 2), lb, fill=(255, 255, 255), font=font)

    draw.rectangle([new_w + 4, 0, canvas_w, label_height], fill=(50, 50, 50))
    bbox = draw.textbbox((0, 0), la, font=font)
    draw.text((new_w + 4 + (new_w - (bbox[2] - bbox[0])) // 2, (label_height - (bbox[3] - bbox[1])) // 2), la, fill=(255, 255, 255), font=font)

    canvas.paste(img_before, (0, label_height))
    canvas.paste(img_after, (new_w + 4, label_height))
    draw.line([(new_w + 2, label_height), (new_w + 2, content_h)], fill=(80, 80, 80), width=1)

    # 底部信息栏
    info_y = content_h + label_height
    draw.rectangle([0, info_y, canvas_w, canvas_h], fill=(20, 20, 20))

    # 提取结论
    conclusion = result.get("reasoning", result.get("raw_response", "暂无分析结论"))
    if len(conclusion) > 200:
        conclusion = conclusion[:200] + "..."

    lines = [
        f"场景: {'新增构筑物检测' if scenario == 'detect' else '整改核验'}",
        f"置信度: {result.get('confidence', 'N/A')}",
        f"结论: {conclusion}",
    ]

    y_offset = info_y + 8
    for line in lines:
        draw.text((10, y_offset), line, fill=(200, 200, 200), font=font_small)
        y_offset += 22

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")

    img_before.close()
    img_after.close()
    canvas.close()

    return output_path


def create_single_annotated(
    image_path: str | Path,
    output_path: str | Path,
    result: dict,
    max_width: int = 1200,
) -> Path:
    """
    生成带标注的单图（单图检测用）：单张影像 + 底部分类结论栏。
    """
    img = Image.open(image_path).convert("RGB")
    scale = min(max_width / img.width, 1.0)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    label_height = 36
    info_height = 110
    canvas_w = new_w
    canvas_h = new_h + label_height + info_height

    canvas = Image.new("RGB", (canvas_w, canvas_h), (30, 30, 30))
    draw = ImageDraw.Draw(canvas)
    font = _get_font(18)
    font_small = _get_font(14)

    # 顶部标签
    label = "待核查影像"
    draw.rectangle([0, 0, canvas_w, label_height], fill=(50, 50, 50))
    bbox = draw.textbbox((0, 0), label, font=font)
    draw.text(((canvas_w - (bbox[2] - bbox[0])) // 2, (label_height - (bbox[3] - bbox[1])) // 2),
              label, fill=(255, 255, 255), font=font)

    canvas.paste(img, (0, label_height))

    # 底部信息栏
    info_y = new_h + label_height
    draw.rectangle([0, info_y, canvas_w, canvas_h], fill=(20, 20, 20))
    lines = [
        f"大类: {result.get('major_category', 'N/A')}",
        f"具体类别: {result.get('specific_category', 'N/A')}",
        f"特征描述: {result.get('feature_description', 'N/A')}",
    ]
    y_offset = info_y + 8
    for line in lines:
        draw.text((10, y_offset), line, fill=(200, 200, 200), font=font_small)
        y_offset += 22

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")

    img.close()
    canvas.close()

    return output_path
