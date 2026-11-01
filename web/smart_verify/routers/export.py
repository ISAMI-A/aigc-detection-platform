"""导出 Excel 核验报告（支持选中导出；原图/对比图/可视化图直接嵌入单元格）。"""

import io
import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage

from ..database import get_db
from ..models import Pair, VerificationResult, ImageRecord
from ..scope import scope
from auth_device import get_identity

router = APIRouter()

IMG_W = 180  # 嵌入图片宽度（px），行高随图自适应


class ExportRequest(BaseModel):
    pair_ids: list[int] | None = None   # None = 导出全部；否则只导出指定配对


@router.post("/export/excel")
def export_excel(req: ExportRequest, request: Request, db: Session = Depends(get_db)):
    """
    导出 Excel 核验报告（仅当前设备）：
    - pair_ids 为空时导出全部配对，否则只导出指定配对（前端已过滤未核验项）
    - 已核验配对：嵌入 整改图原图 + 暗访图原图 + 匹配可视化图（如有）
    - 未核验/缺失配对仅导出文本行（黄色标记"待核验"）
    """
    user_id, device_id = get_identity(request)
    wb = Workbook()
    ws = wb.active
    ws.title = "验证结果"

    headers = [
        "UUID", "地点名称", "配对编号",
        "整改图文件名", "暗访图文件名",
        "是否同一场景", "置信度", "总匹配数", "内点数", "内点比例",
        "备注", "人工复核判断",
        "整改图", "暗访图", "匹配可视化",
    ]

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    # 数据（指定配对或全部；仅当前设备）
    q = db.query(Pair).filter(scope(Pair, user_id, device_id)).order_by(Pair.uuid, Pair.pair_index)
    if req.pair_ids:
        q = q.filter(Pair.id.in_(req.pair_ids))
    pairs = q.all()

    row = 2
    skipped = 0
    for pair in pairs:
        vr = db.query(VerificationResult).filter(VerificationResult.pair_id == pair.id).first()
        left = db.query(ImageRecord).filter(ImageRecord.id == pair.left_image_id).first() if pair.left_image_id else None
        right = db.query(ImageRecord).filter(ImageRecord.id == pair.right_image_id).first() if pair.right_image_id else None

        has_result = vr is not None and pair.status == "done"
        if vr and vr.manual_override:
            is_same = "是" if vr.manual_is_same else "否"
            conf, total, inl, ratio = None, vr.total_matches, vr.ransac_inliers, vr.inlier_ratio
            note = f"人工修正: {vr.manual_note}" if vr.manual_note else "人工修正"
        elif has_result:
            is_same = "是" if vr.is_same else "否"
            conf, total, inl, ratio = round(vr.confidence, 4), vr.total_matches, vr.ransac_inliers, vr.inlier_ratio
            note = ""
        else:
            is_same, conf, total, inl, ratio, note = "待核验", None, None, None, None, "待核验"
            skipped += 1

        human = None
        if vr and vr.human_judgment is not None:
            human = "是" if vr.human_judgment else "否"

        values = [
            pair.uuid[:8] + "..." if pair.uuid else "",
            pair.location_name or "",
            pair.pair_index,
            pair.left_filename or "",
            pair.right_filename or "",
            is_same, conf, total, inl,
            round(ratio, 4) if ratio is not None else None,
            note, human,
        ]

        # 文本列
        max_h = 0
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        # 整行着色
        fill = yellow_fill if is_same == "待核验" else (green_fill if is_same == "是" else red_fill)
        for col in range(1, len(headers) + 1):
            ws.cell(row=row, column=col).fill = fill

        # 图片列（13=整改图, 14=暗访图, 15=可视化）
        img_paths = [left.file_path if left else None, right.file_path if right else None, vr.vis_path if has_result else None]
        for col, p in zip((13, 14, 15), img_paths):
            if not p or not os.path.exists(p):
                continue
            try:
                pil = PILImage.open(p)
                w, h = pil.size
                scale = IMG_W / w if w else 1
                img = XLImage(p)
                img.width, img.height = int(IMG_W), int(h * scale)
                ws.add_image(img, f"{chr(64 + col)}{row}")
                max_h = max(max_h, img.height)
            except Exception as e:
                print(f"[核验] 导出图片失败({col}): {e}")
        if max_h:
            ws.row_dimensions[row].height = int(max_h * 0.75) + 8

        row += 1

    col_widths = [14, 20, 10, 40, 40, 14, 10, 10, 10, 10, 20, 12, IMG_W // 6, IMG_W // 6, IMG_W // 6]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=verification_results.xlsx",
        },
    )
