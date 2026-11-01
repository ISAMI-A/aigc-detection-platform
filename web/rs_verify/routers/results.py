"""结果路由：列表 / 详情 / 删除 / 清空 / 图片服务（按游客设备隔离）。"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AnalysisRecord, UploadImage
from ..scope import scope
from .analyze import record_to_dict, _cleanup_empty_workdirs
from auth_device import get_device_id, get_identity, get_identity_from_img

router = APIRouter(prefix="/api", tags=["rs-results"])

_WEB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK_DIR = os.path.join(_WEB, "data", "rs_work")


@router.delete("/images/{image_id}")
def delete_image(image_id: int, request: Request, db: Session = Depends(get_db)):
    """删除上传图片（仅当前设备）。

    图片被结果记录引用时不再 400 拒绝，而是级联删除引用它的结果记录
    （连带标注图与 rec_ 工作目录）——否则核验后清空上传列表时后端
    文件永远删不掉（前端静默忽略 400，只剩本地列表被清）。
    """
    user_id, device_id = get_identity(request)
    img = db.query(UploadImage).filter(
        UploadImage.id == image_id, scope(UploadImage, user_id, device_id)
    ).first()
    if not img:
        raise HTTPException(404, "图片不存在")
    # 级联删除引用该图片的结果记录（标注图 + rec_ 工作目录）
    for r in db.query(AnalysisRecord).filter(or_(
        AnalysisRecord.before_path == img.file_path,
        AnalysisRecord.after_path == img.file_path,
    )).all():
        _delete_record_files(r)
        db.delete(r)
    db.flush()
    if os.path.exists(img.file_path):
        try:
            os.remove(img.file_path)
        except OSError:
            pass
    db.delete(img)
    db.commit()
    return {"deleted": image_id}


@router.get("/results")
def list_results(request: Request, db: Session = Depends(get_db)):
    """分析结果列表（新→旧；仅当前设备）。"""
    user_id, device_id = get_identity(request)
    records = db.query(AnalysisRecord).filter(
        scope(AnalysisRecord, user_id, device_id)
    ).order_by(AnalysisRecord.id.desc()).all()
    return {"records": [record_to_dict(r) for r in records]}


@router.get("/results/{record_id}")
def get_result(record_id: int, request: Request, db: Session = Depends(get_db)):
    user_id, device_id = get_identity(request)
    r = db.query(AnalysisRecord).filter(
        AnalysisRecord.id == record_id, scope(AnalysisRecord, user_id, device_id)
    ).first()
    if not r:
        raise HTTPException(404, "记录不存在")
    return record_to_dict(r)


@router.get("/images/list")
def list_uploaded_images(request: Request, scenario: str = "", db: Session = Depends(get_db)):
    """当前设备当前场景已上传图片列表（场景隔离，上传面板刷新后恢复）。

    不传 scenario 返回所有场景（兼容旧版前端）。
    """
    user_id, device_id = get_identity(request)
    q = db.query(UploadImage).filter(scope(UploadImage, user_id, device_id))
    if scenario:
        q = q.filter(UploadImage.scenario == scenario)
    imgs = q.order_by(UploadImage.id.desc()).all()
    return {"items": [{
        "id": i.id, "filename": i.filename, "position": i.position,
    } for i in imgs]}


@router.get("/images/{record_id}")
def serve_annotated(record_id: int, request: Request, db: Session = Depends(get_db)):
    """返回标注对比图（<img> 加载，URL 携带 dev/token 校验；登录跨设备可见、游客仅本设备）。"""
    user_id, device_id = get_identity_from_img(request)
    r = db.query(AnalysisRecord).filter(
        AnalysisRecord.id == record_id, scope(AnalysisRecord, user_id, device_id)
    ).first()
    if not r or not r.annotated_image or not os.path.exists(r.annotated_image):
        raise HTTPException(404, "标注图不存在")
    return FileResponse(r.annotated_image, headers={"Cache-Control": "no-store"})


@router.get("/uploads/{image_id}")
def serve_upload(image_id: int, request: Request, db: Session = Depends(get_db)):
    """返回上传原图（上传面板缩略图核验后切换为服务器图用；<img> 加载，URL 携带 dev/token 校验）。"""
    user_id, device_id = get_identity_from_img(request)
    img = db.query(UploadImage).filter(
        UploadImage.id == image_id, scope(UploadImage, user_id, device_id)
    ).first()
    if not img or not os.path.exists(img.file_path):
        raise HTTPException(404, "上传图片不存在")
    return FileResponse(img.file_path, headers={"Cache-Control": "no-store"})


@router.delete("/results/{record_id}")
def delete_result(record_id: int, request: Request, db: Session = Depends(get_db)):
    """删除单条分析记录及标注图/CLI 产物，不删上传图片。"""
    user_id, device_id = get_identity(request)
    r = db.query(AnalysisRecord).filter(
        AnalysisRecord.id == record_id, scope(AnalysisRecord, user_id, device_id)
    ).first()
    if not r:
        raise HTTPException(404, "记录不存在")
    _delete_record_files(r)
    db.delete(r)
    db.commit()
    return {"deleted": record_id}


@router.post("/results/batch-delete")
def batch_delete(payload: dict, request: Request, db: Session = Depends(get_db)):
    """批量删除分析记录（仅当前设备）：只删结果与标注图/CLI 产物，不删上传图片。"""
    user_id, device_id = get_identity(request)
    ids = payload.get("ids") or []
    q = db.query(AnalysisRecord).filter(scope(AnalysisRecord, user_id, device_id))
    if ids:
        records = q.filter(AnalysisRecord.id.in_(ids)).all()
    else:
        records = q.all()
    for r in records:
        _delete_record_files(r)
        db.delete(r)
        db.flush()
    # 清理残留的空工作目录（标注图已删但 rec_xxx 目录可能残留）
    _cleanup_empty_workdirs()
    db.commit()
    return {"deleted": len(records)}


def _remove_orphan_upload_image(db: Session, file_path: str):
    """图片文件不再被任何分析记录引用时，删除文件与 UploadImage 记录。"""
    if not file_path:
        return
    used = db.query(AnalysisRecord).filter(or_(
        AnalysisRecord.before_path == file_path,
        AnalysisRecord.after_path == file_path,
    )).count()
    if used == 0:
        img = db.query(UploadImage).filter(UploadImage.file_path == file_path).first()
        if img:
            if os.path.exists(img.file_path):
                try:
                    os.remove(img.file_path)
                except OSError:
                    pass
            db.delete(img)


def _delete_record_files(r: AnalysisRecord):
    """删除标注图与 CLI 工作目录（Excel/临时文件）。

    注意顺序：必须先定位 rec_ 工作目录再删标注图——若先删文件，
    后续按文件名遍历就找不到目录，导致 rec_ 空文件夹残留。
    """
    rec_dir = None
    if r.annotated_image:
        # 标注图通常直接位于 rec_xxx 工作目录内，优先用路径定位
        d = os.path.dirname(r.annotated_image)
        if os.path.basename(d).startswith("rec_"):
            rec_dir = d
        else:
            # 兼容旧数据：按文件名在工作目录树中查找
            base = os.path.basename(r.annotated_image)
            for _r, _ds, _fs in os.walk(WORK_DIR):
                for sub in _ds:
                    p = os.path.join(_r, sub)
                    if os.path.exists(os.path.join(p, base)):
                        rec_dir = p
                        break
                if rec_dir:
                    break
    if r.annotated_image and os.path.exists(r.annotated_image):
        try:
            os.remove(r.annotated_image)
        except OSError:
            pass
    if rec_dir and os.path.isdir(rec_dir):
        import shutil
        shutil.rmtree(rec_dir, ignore_errors=True)


@router.get("/stats")
def stats(request: Request, db: Session = Depends(get_db)):
    """数据统计（供系统设置展示；仅当前设备）。"""
    user_id, device_id = get_identity(request)
    records = db.query(AnalysisRecord).filter(
        scope(AnalysisRecord, user_id, device_id)).count()
    # 占用大小 = 该设备上传图 + 标注图（按 DB 记录的文件路径累加）
    size = 0
    for img in db.query(UploadImage).filter(scope(UploadImage, user_id, device_id)).all():
        try:
            size += os.path.getsize(img.file_path)
        except OSError:
            pass
    for r in db.query(AnalysisRecord).filter(scope(AnalysisRecord, user_id, device_id)).all():
        if r.annotated_image:
            try:
                size += os.path.getsize(r.annotated_image)
            except OSError:
                pass
    return {"records": records, "bytes": size}
