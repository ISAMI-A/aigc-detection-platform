"""上传图管理：批量上传（幂等）/ 列表 / 删除（联动物理文件）/ 图片服务。"""
import io
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from PIL import Image as PILImage, ImageOps

from ..database import get_db
from ..models import FaceUpload
from ..scope import scope
from auth_device import get_device_id, get_identity, get_identity_from_img, log_operation

router = APIRouter()

_WEB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(_WEB, "data", "face_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")
MAX_SIDE = 2048   # 落盘最长边（控制内存/显存，RetinaFace 内部还会再缩放）


def _preprocess_and_save(data: bytes, path: str) -> None:
    """上传图规整落盘：EXIF 方向校正 → RGB → 超大缩放（LANCZOS）→ JPEG q95。"""
    img = PILImage.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)          # 手机照片 EXIF 方向丢失的经典坑
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_SIDE:
        s = MAX_SIDE / max(w, h)
        img = img.resize((max(1, int(w * s)), max(1, int(h * s))), PILImage.LANCZOS)
    img.save(path, "JPEG", quality=95)


class IdsPayload(BaseModel):
    ids: list[int]


@router.post("/upload")
async def api_upload(request: Request, files: list[UploadFile] = File(...),
                     db: Session = Depends(get_db)):
    """批量上传（归属当前设备/用户），返回记录。幂等：同归属同名直接复用。"""
    user_id, device_id = get_identity(request)
    up_dir = os.path.join(UPLOAD_DIR, device_id)
    os.makedirs(up_dir, exist_ok=True)
    saved = []
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in IMG_EXT:
            continue
        name = f.filename or ""
        exist = db.query(FaceUpload).filter(
            scope(FaceUpload, user_id, device_id), FaceUpload.filename == name).first()
        if exist:
            saved.append({"id": exist.id, "name": exist.filename,
                          "url": f"/face/api/uploads/{exist.id}/img?dev={exist.device_id}"})
            continue
        stored = f"{uuid.uuid4().hex}.jpg"      # 统一 JPEG（预处理转换）
        path = os.path.join(up_dir, stored)
        try:
            _preprocess_and_save(await f.read(), path)
        except Exception:
            raise HTTPException(400, f"图片无法解码: {name}")
        rec = FaceUpload(device_id=device_id, user_id=user_id, filename=name,
                         stored_name=stored, file_path=path)
        db.add(rec)
        db.commit()
        saved.append({"id": rec.id, "name": name,
                      "url": f"/face/api/uploads/{rec.id}/img?dev={device_id}"})
    log_operation(request, "face.upload", f"{len(saved)} 张图片")
    return {"items": saved}


@router.get("/uploads")
def api_uploads(request: Request, db: Session = Depends(get_db)):
    """上传列表（刷新恢复；status=最新一次识别状态）。"""
    user_id, device_id = get_identity(request)
    rows = db.query(FaceUpload).filter(
        scope(FaceUpload, user_id, device_id)).order_by(FaceUpload.id.desc()).all()
    return {"items": [{
        "id": r.id, "name": r.filename, "status": r.status or "pending",
        "url": f"/face/api/uploads/{r.id}/img?dev={r.device_id}",
        "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else "",
    } for r in rows]}


@router.post("/uploads/delete")
def api_uploads_delete(payload: IdsPayload, request: Request, db: Session = Depends(get_db)):
    """删除上传图（ids 空 = 全部）；联动物理文件与该图识别结果。"""
    from ..models import FaceResult
    user_id, device_id = get_identity(request)
    q = db.query(FaceUpload).filter(scope(FaceUpload, user_id, device_id))
    if payload.ids:
        q = q.filter(FaceUpload.id.in_(payload.ids))
    rows = q.all()
    for r in rows:
        # 联动删除该图识别结果（含人脸缩略图）
        for res in db.query(FaceResult).filter(FaceResult.upload_id == r.id).all():
            if res.thumb_path and os.path.exists(res.thumb_path):
                try:
                    os.remove(res.thumb_path)
                except OSError:
                    pass
            db.delete(res)
        if os.path.exists(r.file_path):
            try:
                os.remove(r.file_path)
            except OSError:
                pass
        db.delete(r)
    db.commit()
    # 空目录清理
    d = os.path.join(UPLOAD_DIR, device_id)
    try:
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
    except OSError:
        pass
    log_operation(request, "face.upload_delete", f"{len(rows)} 张图片")
    return {"deleted": len(rows)}


@router.get("/uploads/{upload_id}/img")
def api_upload_img(upload_id: int, request: Request, db: Session = Depends(get_db)):
    """上传原图服务（<img> 加载；URL 携带 dev/token 校验；登录跨设备可见、游客仅本设备）。"""
    user_id, device_id = get_identity_from_img(request)
    rec = db.query(FaceUpload).filter(
        FaceUpload.id == upload_id, scope(FaceUpload, user_id, device_id)).first()
    if not rec or not os.path.exists(rec.file_path):
        raise HTTPException(404, "图片不存在")
    return FileResponse(rec.file_path, headers={"Cache-Control": "no-store"})
