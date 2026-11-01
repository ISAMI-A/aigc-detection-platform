"""导出路由：全量/选中记录导出 Excel（嵌入图片；按游客设备隔离）。"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AnalysisRecord
from ..scope import scope
from ..services.excel import build_excel
from auth_device import get_identity

router = APIRouter(prefix="/api", tags=["rs-export"])


class ExportReq(BaseModel):
    ids: list[int] | None = None  # 为空=全部


@router.post("/export/excel")
def export_excel(payload: ExportReq, request: Request, db: Session = Depends(get_db)):
    """导出 Excel（POST，带选择条件；ids 为空导出当前设备全部）。"""
    user_id, device_id = get_identity(request)
    q = db.query(AnalysisRecord).filter(scope(AnalysisRecord, user_id, device_id))
    if payload.ids:
        records = q.filter(AnalysisRecord.id.in_(payload.ids)).all()
    else:
        records = q.all()
    buf = build_excel(records)
    filename = "遥感核验结果.xlsx"
    # 中文文件名需按 RFC 5987 编码，否则 latin-1 header 会抛异常
    encoded = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=rs_results.xlsx; filename*=UTF-8''{encoded}"},
    )
