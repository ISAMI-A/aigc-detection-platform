"""
Excel 报告生成器
支持累积追加到汇总表格
"""

import datetime
import io
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XlImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


# 表格样式
HEADER_FONT = Font(name="微软雅黑", bold=True, size=11, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
CELL_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
TEXT_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=True)
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

# 列定义
COLUMNS = [
    ("序号", 6),
    ("Before 文件名", 28),
    ("After 文件名", 28),
    ("场景", 16),
    ("模型", 18),
    ("检测时间", 20),
    ("主要结论", 28),
    ("置信度", 10),
    ("详细分析", 50),
    ("整改评分", 10),
    ("通过状态", 12),
    ("构筑物类型", 16),
    ("原图 Before", 48),
    ("原图 After", 48),
    ("对比图", 48),
]

# 单图检测（classify）专用列：嵌入原图 + 模型列
SINGLE_COLUMNS = [
    ("序号", 6),
    ("文件名", 30),
    ("场景", 12),
    ("模型", 18),
    ("检测时间", 20),
    ("大类", 14),
    ("具体类别", 20),
    ("图像特征描述", 50),
    ("标注图", 48),
]

# 单图检测精简列（run.py 开关 SIMPLE_EXCEL=True 时使用）：5 列，图片用原图（缩放后嵌入）
# 列宽按内容优化：文本列加宽（特征描述最长），原图列给图片让位
SIMPLE_SINGLE_COLUMNS = [
    ("序号", 8),
    ("大类", 16),
    ("具体类别", 18),
    ("图像特征描述", 60),
    ("原图", 40),
]

# 精简表格嵌入图片的最大边长（px），与样例 结果.xlsx（481x458）接近，避免原图撑满表格
SIMPLE_IMG_MAX_SIDE = 480


class ExcelReporter:
    """Excel 报告生成器"""

    def __init__(self, excel_path: str | Path, columns: list = None, sheet_name: str = "检测结果"):
        self.excel_path = Path(excel_path)
        self.columns = columns or COLUMNS
        self.sheet_name = sheet_name
        self.image_dir = self.excel_path.parent / "images"
        self.image_dir.mkdir(parents=True, exist_ok=True)

    def _get_or_create_workbook(self) -> Workbook:
        """获取或创建 Excel 工作簿（损坏文件自动重建）"""
        if self.excel_path.exists():
            try:
                return load_workbook(self.excel_path)
            except Exception:
                # 文件损坏（如保存中断）→ 删除重建
                self.excel_path.unlink(missing_ok=True)

        wb = Workbook()
        ws = wb.active
        ws.title = self.sheet_name
        self._write_header(ws)
        return wb

    def _write_header(self, ws):
        """写入表头"""
        for col_idx, (name, width) in enumerate(self.columns, 1):
            cell = ws.cell(row=1, column=col_idx, value=name)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = HEADER_ALIGN
            cell.border = THIN_BORDER
            ws.column_dimensions[get_column_letter(col_idx)].width = width

    def _resize_image_for_excel(self, image_path: Path, max_size: int = 340) -> Path:
        """
        将图片转成 PNG 缩略图（openpyxl 不支持 webp 等格式，统一转 PNG）。
        输出到 Excel 同目录下的 .xl_thumbs 缓存目录。
        """
        from PIL import Image as PilImage

        thumb_dir = self.excel_path.parent / ".xl_thumbs"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        resized_path = thumb_dir / f"{image_path.stem}.png"
        if resized_path.exists():
            return resized_path

        img = PilImage.open(image_path).convert("RGB")
        w, h = img.size
        scale = max_size / max(w, h)
        if scale < 1:
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, PilImage.LANCZOS)
        img.save(resized_path, "PNG")
        img.close()
        return resized_path

    def add_result(
        self,
        before_path: str | Path,
        after_path: str | Path,
        scenario: str,
        result: dict,
        comparison_image: str | Path | None = None,
        model_name: str = "",
    ) -> int:
        """
        追加一条检测结果到 Excel。
        返回行号。
        """
        wb = self._get_or_create_workbook()
        ws = wb["检测结果"]

        # 找到下一个空行
        row = ws.max_row + 1
        seq = row - 1  # 序号（-1 因为第1行是表头）

        # 场景中文名
        scenario_cn = "新增构筑物检测" if scenario == "detect" else "整改核验"

        # 写入文本数据
        data = [
            seq,
            Path(before_path).name,
            Path(after_path).name,
            scenario_cn,
            model_name,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            self._get_conclusion(result, scenario),
            result.get("confidence", "N/A"),
            result.get("reasoning", result.get("raw_response", "")),
            result.get("rectification_score", "N/A") if scenario == "verify" else "N/A",
            result.get("pass_status", "N/A") if scenario == "verify" else "N/A",
            result.get("construction_type", "N/A") if scenario == "detect" else "N/A",
        ]

        for col_idx, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.border = THIN_BORDER
            if col_idx in (7, 9):  # 主要结论/详细分析 文本列左对齐
                cell.alignment = TEXT_ALIGN
            else:
                cell.alignment = CELL_ALIGN

        # 设置行高（为图片留空间）
        ws.row_dimensions[row].height = 320

        # 嵌入原图 Before（列13）
        self._embed_image(ws, row, 13, before_path)
        # 嵌入原图 After（列14）
        self._embed_image(ws, row, 14, after_path)
        # 嵌入对比图（列15）
        if comparison_image and Path(comparison_image).exists():
            self._embed_image(ws, row, 15, comparison_image)

        # 保存（文件被占用时自动换名重试）
        path = self._save_with_retry(wb)

        # 图片已固化进 Excel，清理临时缩略图缓存（避免累积）
        import shutil
        shutil.rmtree(path.parent / ".xl_thumbs", ignore_errors=True)

        return row

    def add_single_result(
        self,
        image_path: str | Path,
        result: dict,
        annotated_image: str | Path = None,
        model_name: str = "",
    ) -> int:
        """
        追加一条单图检测结果到 Excel（classify 场景）。
        annotated_image 为带文字描述的标注图；嵌入 Excel 后由调用方决定是否删除原文件。
        返回行号。
        """
        wb = self._get_or_create_workbook()
        ws = wb[self.sheet_name]

        row = ws.max_row + 1
        seq = row - 1

        data = [
            seq,
            Path(image_path).name,
            "单图检测",
            model_name,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            result.get("major_category", "N/A"),
            result.get("specific_category", "N/A"),
            result.get("feature_description", result.get("raw_response", "")),
        ]

        for col_idx, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.border = THIN_BORDER
            cell.alignment = TEXT_ALIGN if col_idx == 8 else CELL_ALIGN

        # 设置行高（为图片留空间）
        ws.row_dimensions[row].height = 320

        # 嵌入标注图（最后一列）；无标注图时退回嵌入原图
        embed_path = annotated_image if annotated_image and Path(annotated_image).exists() else image_path
        self._embed_image(ws, row, len(self.columns), embed_path)

        path = self._save_with_retry(wb)

        import shutil
        shutil.rmtree(path.parent / ".xl_thumbs", ignore_errors=True)

        return row

    def add_single_failed(
        self,
        image_path: str | Path,
        reason: str,
        model_name: str = "",
    ) -> int:
        """
        追加一条单图检测失败记录到 Excel（标记哪张图失败及原因，便于批量后排查）。
        返回行号。
        """
        wb = self._get_or_create_workbook()
        ws = wb[self.sheet_name]

        row = ws.max_row + 1
        seq = row - 1

        data = [
            seq,
            Path(image_path).name,
            "单图检测",
            model_name,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "识别失败",
            "N/A",
            reason,
        ]

        for col_idx, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.border = THIN_BORDER
            cell.alignment = TEXT_ALIGN if col_idx == 8 else CELL_ALIGN

        ws.row_dimensions[row].height = 30

        path = self._save_with_retry(wb)

        import shutil
        shutil.rmtree(path.parent / ".xl_thumbs", ignore_errors=True)

        return row

    def add_failed(
        self,
        before_path: str | Path,
        after_path: str | Path,
        scenario: str,
        reason: str,
        model_name: str = "",
    ) -> int:
        """
        追加一条识别失败记录到 Excel（标记哪一对失败及原因，便于批量后排查）。
        返回行号。
        """
        wb = self._get_or_create_workbook()
        ws = wb["检测结果"]

        row = ws.max_row + 1
        seq = row - 1
        scenario_cn = "新增构筑物检测" if scenario == "detect" else "整改核验"

        data = [
            seq,
            Path(before_path).name,
            Path(after_path).name,
            scenario_cn,
            model_name,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "识别失败",
            "N/A",
            reason,
            "N/A", "N/A", "N/A",
        ]

        for col_idx, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.border = THIN_BORDER
            cell.alignment = TEXT_ALIGN if col_idx in (7, 9) else CELL_ALIGN

        ws.row_dimensions[row].height = 30

        path = self._save_with_retry(wb)

        import shutil
        shutil.rmtree(path.parent / ".xl_thumbs", ignore_errors=True)

        return row

    def _save_with_retry(self, wb) -> Path:
        """
        保存 Excel 工作簿；若目标文件被占用（PermissionError，如正被 Excel/WPS 打开），
        自动在文件名末尾追加序号重试：results.xlsx → results_1.xlsx → results_2.xlsx ...
        返回实际保存的路径（self.excel_path 同步更新）。
        """
        base = self.excel_path
        target = base
        n = 1
        while True:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                wb.save(target)
                self.excel_path = target
                return target
            except PermissionError:
                # 被占用 → 换名：stem_1.xlsx, stem_2.xlsx ...
                target = base.with_name(f"{base.stem}_{n}{base.suffix}")
                n += 1

    def _embed_image(self, ws, row: int, col: int, image_path: str | Path):
        """在指定单元格嵌入图片缩略图"""
        image_path = Path(image_path)
        if not image_path.exists():
            return

        try:
            thumb = self._resize_image_for_excel(image_path)
            xl_img = XlImage(str(thumb))
            # 缩放到单元格合适大小
            xl_img.width = 340
            xl_img.height = min(xl_img.height, 280)
            cell_ref = f"{get_column_letter(col)}{row}"
            ws.add_image(xl_img, cell_ref)
        except Exception as e:
            ws.cell(row=row, column=col, value=f"[图片加载失败: {e}]")

    def _embed_image_original(self, ws, row: int, col: int, image_path: str | Path):
        """在指定单元格嵌入原图（缩放到最大边 SIMPLE_IMG_MAX_SIDE px，保持纵横比）。

        精简表格（SIMPLE_EXCEL）用：原图缩放后嵌入，行高按缩放后图片高度自动适配
        （96dpi: 1px ≈ 0.75pt，加 8pt 边距），保证图片完整显示在单元格内。
        """
        image_path = Path(image_path)
        if not image_path.exists():
            return
        try:
            from PIL import Image as PilImage
            img = PilImage.open(image_path).convert("RGB")
            w, h = img.size
            scale = min(1.0, SIMPLE_IMG_MAX_SIDE / max(w, h))
            if scale < 1.0:
                img = img.resize((int(w * scale), int(h * scale)), PilImage.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            xl_img = XlImage(buf)  # 缩放后的尺寸
            cell_ref = f"{get_column_letter(col)}{row}"
            ws.add_image(xl_img, cell_ref)
            ws.row_dimensions[row].height = round(img.height * 0.75) + 8
        except Exception as e:
            ws.cell(row=row, column=col, value=f"[原图加载失败: {e}]")

    def add_single_result_simple(self, image_path: str | Path, result: dict, model_name: str = "") -> int:
        """追加一条单图检测结果到精简 Excel（5 列：序号/大类/具体类别/图像特征描述/原图）。

        原图缩放后嵌入第 5 列，行高由 _embed_image_original 按缩放后图片高度自适应。
        """
        wb = self._get_or_create_workbook()
        ws = wb[self.sheet_name]

        row = ws.max_row + 1
        seq = row - 1

        data = [
            seq,
            result.get("major_category", "N/A"),
            result.get("specific_category", "N/A"),
            result.get("feature_description", result.get("raw_response", "")),
        ]
        for col_idx, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.border = THIN_BORDER
            cell.alignment = TEXT_ALIGN if col_idx == 4 else CELL_ALIGN

        # 嵌入原图（第 5 列，缩放后嵌入；行高随图片高度自适应）
        self._embed_image_original(ws, row, 5, image_path)

        path = self._save_with_retry(wb)

        import shutil
        shutil.rmtree(path.parent / ".xl_thumbs", ignore_errors=True)

        return row

    def add_single_failed_simple(self, image_path: str | Path, reason: str, model_name: str = "") -> int:
        """追加一条单图检测失败记录到精简 Excel（失败原因 + 原图）。"""
        wb = self._get_or_create_workbook()
        ws = wb[self.sheet_name]

        row = ws.max_row + 1
        seq = row - 1

        data = [seq, "识别失败", "N/A", reason]
        for col_idx, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.border = THIN_BORDER
            cell.alignment = TEXT_ALIGN if col_idx == 4 else CELL_ALIGN

        ws.row_dimensions[row].height = 30

        path = self._save_with_retry(wb)

        import shutil
        shutil.rmtree(path.parent / ".xl_thumbs", ignore_errors=True)

        return row

    @staticmethod
    def _get_conclusion(result: dict, scenario: str) -> str:
        """从结果中提取摘要结论"""
        if scenario == "detect":
            if result.get("has_new_construction"):
                return f"存在新增{result.get('construction_type', '构筑物')}"
            return "未发现新增构筑物"
        else:
            return result.get("pass_status", result.get("current_land_type", "N/A"))
