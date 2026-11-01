"""Excel 导出（web 侧独立实现，嵌入原图 + 标注图）。

与 Remote_sensing 的 reporter.py 逻辑一致但独立维护，web 前端调用。
"""
import io
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XlImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FONT = Font(name="微软雅黑", bold=True, size=11, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
CELL_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin"),
)

HEADERS = [
    ("序号", 6), ("场景", 14), ("模型", 20), ("Before 文件名", 26), ("After 文件名", 26),
    ("主要结论", 30), ("置信度", 10), ("详细分析", 50), ("检测时间", 20),
    ("原图 Before", 40), ("原图 After", 40), ("标注对比图", 40),
]

# 四乱核验（classify）专用列：参考 Remote_sensing/core/reporter.py 的 SINGLE_COLUMNS
CLASSIFY_HEADERS = [
    ("序号", 6), ("文件名", 30), ("场景", 12), ("模型", 18), ("检测时间", 20),
    ("大类", 14), ("具体类别", 20), ("图像特征描述", 50), ("标注图", 48),
]

SCENARIO_CN = {"detect": "新增构筑物检测", "verify": "整改核验", "classify": "四乱现象核验"}


def _thumb(image_path: str, max_size: int = 300) -> io.BytesIO:
    """图片转 PNG 缩略图（webp 等格式统一转 PNG，openpyxl 才能嵌入）"""
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    scale = max_size / max(w, h)
    if scale < 1:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img.close()
    buf.seek(0)
    return buf


def build_excel(records: list) -> io.BytesIO:
    """records: AnalysisRecord 列表，返回 Excel 字节流。

    全部为四乱核验（classify）时用独立表头（序号/文件名/大类/具体类别/图像特征描述/标注图），
    其余场景用通用表头（Before/After 双图 + 结论/置信度）。
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "遥感核验结果"

    is_classify = bool(records) and all(r.scenario == "classify" for r in records)
    headers = CLASSIFY_HEADERS if is_classify else HEADERS

    for col, (name, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col)].width = width

    for idx, r in enumerate(records, 2):
        import json
        try:
            result = json.loads(r.result_json or "{}")
        except Exception:
            result = {}
        created = r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else ""

        if is_classify:
            # 四乱：单图文件名 + 大类/具体类别/特征描述 + 标注图
            values = [
                idx - 1, r.before_file or "", SCENARIO_CN.get(r.scenario, r.scenario),
                r.model_used or "", created,
                result.get("major_category", ""), result.get("specific_category", ""),
                result.get("feature_description", ""),
            ]
            embed_cols = [(9, r.annotated_image or r.before_path)]
        else:
            reasoning = str(result.get("feature_description", "")) if r.scenario == "classify" else str(result.get("reasoning", ""))
            values = [
                idx - 1, SCENARIO_CN.get(r.scenario, r.scenario),
                r.model_used or "",
                r.before_file, r.after_file,
                r.conclusion or "", r.confidence or "",
                reasoning, created,
            ]
            embed_cols = [(10, r.before_path), (11, r.after_path), (12, r.annotated_image)]

        for col, v in enumerate(values, 1):
            cell = ws.cell(row=idx, column=col, value=v)
            cell.alignment = CELL_ALIGN
            cell.border = THIN_BORDER

        ws.row_dimensions[idx].height = 300

        # 嵌入图片（classify: 标注图一列；其他: 原图 Before/After + 标注图）
        for col, path in embed_cols:
            if not path or not Path(path).exists():
                continue
            try:
                xl = XlImage(_thumb(path))
                xl.width = 300
                xl.height = min(xl.height, 260)
                ws.add_image(xl, f"{get_column_letter(col)}{idx}")
            except Exception:
                pass

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
