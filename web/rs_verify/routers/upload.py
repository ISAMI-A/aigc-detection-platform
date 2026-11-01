"""上传路由：保存图片到 web/data/rs_uploads/，按场景隔离。"""
import os
import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Form
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import UploadImage
from auth_device import get_identity, log_operation

router = APIRouter(prefix="/api", tags=["rs-upload"])

# 上传目录：web/data/rs_uploads
_WEB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(_WEB, "data", "rs_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


@router.post("/upload")
def upload(
    request: Request,
    before: UploadFile = File(..., description="Before 图片（旧时/整改前）"),
    after: UploadFile = File(..., description="After 图片（现在/整改后）"),
    scenario: str = Form("detect"),
    db: Session = Depends(get_db),
):
    """上传一对图片，返回两条记录（before_id / after_id；归属当前设备/场景）。"""
    user_id, device_id = get_identity(request)
    files = {"before": before, "after": after}
    saved = {}
    for pos, f in files.items():
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(400, f"不支持的格式: {ext or '未知'}")
        stored = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(UPLOAD_DIR, stored)
        with open(path, "wb") as out:
            shutil.copyfileobj(f.file, out)
        rec = UploadImage(
            device_id=device_id,
            user_id=user_id,
            filename=f.filename or stored,
            stored_name=stored,
            file_path=path,
            position=pos,
            scenario=scenario,
        )
        db.add(rec)
        db.flush()
        saved[pos] = {"id": rec.id, "filename": rec.filename}
    db.commit()
    log_operation(request, "rs.upload", f"before#{saved['before']['id']}, after#{saved['after']['id']}")
    return {"before": saved["before"], "after": saved["after"]}


@router.post("/upload-single")
def upload_single(
    request: Request,
    image: UploadFile = File(..., description="待上传图片"),
    position: str = "single",
    scenario: str = Form("detect"),
    db: Session = Depends(get_db),
):
    """上传单张图片（支持 before/after/single position），按场景隔离。"""
    if position not in ("before", "after", "single"):
        position = "single"
    user_id, device_id = get_identity(request)
    ext = os.path.splitext(image.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的格式: {ext or '未知'}")
    stored = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, stored)
    with open(path, "wb") as out:
        shutil.copyfileobj(image.file, out)
    rec = UploadImage(
        device_id=device_id,
        user_id=user_id,
        filename=image.filename or stored,
        stored_name=stored,
        file_path=path,
        position=position,
        scenario=scenario,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    log_operation(request, "rs.upload", f"{position}#{rec.id}")
    return {"image": {"id": rec.id, "filename": rec.filename}}
