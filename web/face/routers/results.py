"""识别结果：列表 / 详情 / 人工标注入库（含查重二次确认）/ 删除 / Excel 导出。"""
import json
import os
import shutil
import uuid as _uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FaceResult, FaceUpload
from ..scope import scope
from ..services import engine
from auth_device import get_identity, log_operation

router = APIRouter()

_WEB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class IdsPayload(BaseModel):
    ids: list[int]


class ManualSaveReq(BaseModel):
    result_id: int
    name: str
    mode: str = ""          # ""=先查重 / "overwrite"=覆盖（改名+补样本）/ "new"=新增人员


def _row_to_result(r: FaceResult) -> dict:
    """结果行 → 前端对象（图片 URL 携带记录自身 device_id，B78 约定）。"""
    dev = r.device_id
    return {
        "id": r.id, "upload_id": r.upload_id, "upload_name": r.upload_name,
        "face_idx": r.face_idx, "bbox": json.loads(r.bbox_json or "[]"),
        "det_score": r.det_score,
        "matched": bool(r.matched), "similarity": r.similarity,
        "matched_name": r.matched_name or "", "matched_person": r.matched_person or "",
        "manual_name": r.manual_name or "", "manual_by": r.manual_by or "",
        "thumb": f"/face/api/results/{r.id}/thumb?dev={dev}",
        "orig": f"/face/api/uploads/{r.upload_id}/img?dev={dev}",
        "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else "",
    }


@router.get("/results")
def api_results(request: Request, db: Session = Depends(get_db)):
    """当前归属全部识别结果（一行=一张脸）。"""
    user_id, device_id = get_identity(request)
    rows = db.query(FaceResult).filter(
        scope(FaceResult, user_id, device_id)).order_by(FaceResult.id.desc()).all()
    return {"items": [_row_to_result(r) for r in rows]}


@router.get("/results/{result_id}/detail")
def api_result_detail(result_id: int, request: Request, db: Session = Depends(get_db)):
    """详情：检测参数 + Top-K 候选 + 512 维特征（模型检测的特征值参数）。"""
    user_id, device_id = get_identity(request)
    r = db.query(FaceResult).filter(
        FaceResult.id == result_id, scope(FaceResult, user_id, device_id)).first()
    if not r:
        raise HTTPException(404, "结果不存在")
    out = _row_to_result(r)
    out["candidates"] = json.loads(r.candidates_json or "[]")
    out["embed"] = json.loads(r.embed_json or "[]")
    out["threshold"] = engine.SIMILARITY_THRESHOLD
    return out


@router.get("/results/{result_id}/thumb")
def api_result_thumb(result_id: int, request: Request, db: Session = Depends(get_db)):
    """人脸裁剪缩略图服务。"""
    r = db.query(FaceResult).filter(FaceResult.id == result_id).first()
    if not r or not r.thumb_path or not os.path.exists(r.thumb_path):
        raise HTTPException(404, "图片不存在")
    return FileResponse(r.thumb_path, headers={"Cache-Control": "no-store"})


@router.post("/results/manual_save")
def api_manual_save(payload: ManualSaveReq, request: Request, db: Session = Depends(get_db)):
    """人工标注入库：输入姓名写入全局人脸库，并更新该行识别结果。

    流程（登录用户；游客 403）：
    - mode=""：先查重。命中"相似但不同名"人员 → 返回 need_confirm（前端弹窗
      覆盖=改姓名+补样本 / 新增=独立人员）；同名或无相似 → 直接入库。
    - mode=overwrite：改该人员姓名 + 当前脸追加为样本。
    - mode=new：当前脸作为独立新人员入库。
    """
    user_id, device_id = get_identity(request)
    if user_id is None:
        raise HTTPException(403, "游客无法人工录入人脸库，请先登录")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "姓名不能为空")

    r = db.query(FaceResult).filter(
        FaceResult.id == payload.result_id, scope(FaceResult, user_id, device_id)).first()
    if not r:
        raise HTTPException(404, "结果不存在")
    if not r.embed_json:
        raise HTTPException(400, "该结果缺少特征数据，无法入库")

    import numpy as np
    emb = np.array(json.loads(r.embed_json), dtype=np.float32)

    # 查重：相似且不同名 → 冲突（需前端确认）；相似且同名 → 同人补样本（无需确认）
    fdb = engine.face_db()
    cands = fdb.search(emb, top_k=1)
    top = cands[0] if cands else None
    th = engine.SIMILARITY_THRESHOLD
    conflict = None
    same_person_id = None
    if top and top["similarity"] >= th:
        if top["name"] != name:
            conflict = {"person_id": top["person_id"], "name": top["name"],
                        "similarity": round(top["similarity"], 4), "user_id": top["user_id"]}
        else:
            same_person_id = top["person_id"]

    if payload.mode not in ("overwrite", "new") and conflict:
        return {"need_confirm": True, "conflict": conflict}

    if payload.mode == "overwrite" and (conflict or same_person_id):
        person_id = conflict["person_id"] if conflict else same_person_id
        fdb.rename_person(person_id, name)
    elif same_person_id:
        person_id = same_person_id          # 同名同人 → 直接补样本（无需新建人员）
    else:
        person_id = engine._new_person_id()

    # 库样本照：复用结果人脸缩略图 → 复制到人脸库 thumbs（库数据自治，不随结果清理）
    lib_thumb = ""
    if r.thumb_path and os.path.exists(r.thumb_path):
        lib_thumb = str(engine.LIB_THUMB_DIR / f"s_{_uuid.uuid4().hex}.jpg")
        os.makedirs(engine.LIB_THUMB_DIR, exist_ok=True)
        shutil.copy(r.thumb_path, lib_thumb)

    fdb.add_sample(person_id, name, emb, thumb_path=lib_thumb,
                   created_by=f"user:{user_id}", source="web-recog")

    # 更新该行结果为人工修正后的姓名
    r.matched = True
    r.matched_name = name
    r.matched_person = person_id
    r.similarity = 1.0
    r.manual_name = name
    r.manual_by = f"user:{user_id}"
    db.commit()
    log_operation(request, "face.manual_save", f"{name} ({person_id})")
    return {"status": "ok", "person_id": person_id, "name": name}


@router.post("/results/delete")
def api_results_delete(payload: IdsPayload, request: Request, db: Session = Depends(get_db)):
    """删除结果（ids 空=全部；联动物理缩略图文件）。"""
    user_id, device_id = get_identity(request)
    q = db.query(FaceResult).filter(scope(FaceResult, user_id, device_id))
    if payload.ids:
        q = q.filter(FaceResult.id.in_(payload.ids))
    rows = q.all()
    for r in rows:
        if r.thumb_path and os.path.exists(r.thumb_path):
            try:
                os.remove(r.thumb_path)
            except OSError:
                pass
        db.delete(r)
    db.commit()
    log_operation(request, "face.result_delete", f"{len(rows)} 条")
    return {"deleted": len(rows)}


@router.post("/export")
def api_export(payload: IdsPayload, request: Request, db: Session = Depends(get_db)):
    """导出 Excel：每行嵌人脸缩略图+原图缩略图+姓名/相似度/状态/人工修正/时间。"""
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from PIL import Image as PILImage

    user_id, device_id = get_identity(request)
    q = db.query(FaceResult).filter(scope(FaceResult, user_id, device_id))
    if payload.ids:
        q = q.filter(FaceResult.id.in_(payload.ids))
    rows = q.order_by(FaceResult.id).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "人脸识别结果"
    headers = ["编号", "上传文件", "人脸图", "原图缩略", "识别结果", "姓名",
               "相似度", "检测置信度", "人工修正", "录入时间"]
    ws.append(headers)
    head_fill = PatternFill("solid", fgColor="1a66ff")
    for c in range(1, len(headers) + 1):
        cell = ws.cell(1, c)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center")
    for i, h in enumerate(headers):
        ws.column_dimensions[get_column_letter(i + 1)].width = \
            10 if i in (0,) else (22 if i in (1,) else (14 if i in (4, 5) else 12))

    ok_fill = PatternFill("solid", fgColor="E8F5E9")
    bad_fill = PatternFill("solid", fgColor="FFEBEE")
    for idx, r in enumerate(rows):
        row_excel = idx + 2
        name = r.manual_name or r.matched_name
        ws.cell(row_excel, 1, r.id)
        ws.cell(row_excel, 2, r.upload_name or "")
        ws.cell(row_excel, 5, "识别成功" if r.matched else "识别失败（库中不存在）")
        ws.cell(row_excel, 6, name or "")
        ws.cell(row_excel, 7, round(r.similarity, 4) if r.similarity else "")
        ws.cell(row_excel, 8, r.det_score if r.det_score else "")
        ws.cell(row_excel, 9, r.manual_name or "")
        ws.cell(row_excel, 10, r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "")
        fill = ok_fill if r.matched else bad_fill
        for c in range(1, len(headers) + 1):
            ws.cell(row_excel, c).fill = fill
            ws.cell(row_excel, c).alignment = Alignment(vertical="center")
        # 嵌图（人脸缩略图 / 原图缩略）
        for col, path in ((3, r.thumb_path),):
            if path and os.path.exists(path):
                try:
                    img = XLImage(path)
                    img.width, img.height = 64, 64
                    ws.add_image(img, f"{get_column_letter(col)}{row_excel}")
                except Exception:
                    pass
        up = db.query(FaceUpload).filter(FaceUpload.id == r.upload_id).first()
        if up and os.path.exists(up.file_path):
            try:
                thumb_tmp = os.path.join(_WEB, "data", "face_thumbs", f"exp_{_uuid.uuid4().hex}.jpg")
                im = PILImage.open(up.file_path)
                im.thumbnail((160, 160))
                im.convert("RGB").save(thumb_tmp, "JPEG", quality=85)
                img = XLImage(thumb_tmp)
                img.width, img.height = 64, 64
                ws.add_image(img, f"D{row_excel}")
                # openpyxl 嵌入后删除临时文件（图片数据已被复制进 xlsx）
            except Exception:
                pass
        ws.row_dimensions[row_excel].height = 52

    ws.freeze_panes = "A2"
    out = os.path.join(_WEB, "data", f"人脸识别结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    wb.save(out)
    # 临时缩略图清理（xlsx 已嵌入图片数据）
    for f in os.listdir(os.path.dirname(out)):
        if f.startswith("exp_") and f.endswith(".jpg"):
            try:
                os.remove(os.path.join(os.path.dirname(out), f))
            except OSError:
                pass
    log_operation(request, "face.export", f"{len(rows)} 条")
    # 中文文件名走 RFC 5987（filename*），否则 starlette 以 latin-1 编码 header 会崩
    from urllib.parse import quote
    fn = os.path.basename(out)
    return FileResponse(out, headers={
        "Content-Disposition": f"attachment; filename=face_results.xlsx; filename*=UTF-8''{quote(fn)}"})
