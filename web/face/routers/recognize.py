"""人脸识别：批量/单图识别（NDJSON 流式，逐图进度；重测 = 覆盖该图旧结果）。"""
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FaceUpload, FaceResult
from ..scope import scope
from ..services import engine
from auth_device import get_identity, log_operation
from model_manager import manager, gpu_free_too_low

router = APIRouter()

_WEB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
THUMB_DIR = os.path.join(_WEB, "data", "face_thumbs")   # 识别结果人脸缩略图
os.makedirs(THUMB_DIR, exist_ok=True)

# 人脸引擎显存估算（检测+识别两模型，RTX 4060 实测参考）
FACE_GB = 1.2


class RecognizeReq(BaseModel):
    upload_ids: list[int]


def _recognize_one(upload: FaceUpload, db: Session, user_id, device_id) -> dict:
    """识别单张上传图（覆盖旧结果）：写 face_results + 更新 upload.status。

    需在 manager.infer 锁内调用。返回 {upload_id, name, status, face_count}。
    """
    # 删除旧结果（含人脸缩略图）——重测覆盖语义
    for old in db.query(FaceResult).filter(FaceResult.upload_id == upload.id).all():
        if old.thumb_path and os.path.exists(old.thumb_path):
            try:
                os.remove(old.thumb_path)
            except OSError:
                pass
        db.delete(old)
    db.commit()

    img = engine.read_image(upload.file_path)
    faces = engine.recognize_faces(img)      # 面积降序
    if not faces:
        upload.status = "no_face"
        db.commit()
        return {"upload_id": upload.id, "name": upload.filename,
                "status": "no_face", "face_count": 0}

    fdb = engine.face_db()
    for idx, f in enumerate(faces):
        thumb = engine.save_face_crop(img, f["bbox"], THUMB_DIR)
        cands = fdb.search(f["embed"], top_k=5)
        best = cands[0] if cands and cands[0]["similarity"] >= engine.SIMILARITY_THRESHOLD else None
        db.add(FaceResult(
            device_id=device_id, user_id=user_id,
            upload_id=upload.id, upload_name=upload.filename, face_idx=idx,
            bbox_json=json.dumps([int(v) for v in f["bbox"]]),
            det_score=round(f["score"], 4), thumb_path=thumb,
            matched=bool(best), similarity=round(best["similarity"], 4) if best else 0.0,
            matched_name=best["name"] if best else "",
            matched_person=best["person_id"] if best else "",
            candidates_json=json.dumps(
                [{k: c[k] for k in ("id", "person_id", "name", "similarity")} for c in cands]),
            embed_json=json.dumps([round(float(v), 6) for v in f["embed"]]),
        ))
    upload.status = "done"
    db.commit()
    return {"upload_id": upload.id, "name": upload.filename,
            "status": "done", "face_count": len(faces)}


@router.post("/recognize")
def api_recognize(req: RecognizeReq, request: Request, db: Session = Depends(get_db)):
    """批量识别（NDJSON 流式）：逐图推送 progress，done 携带每图汇总。

    一图多脸 → 多条结果行；整图无脸 → 上传列表标 no_face（无结果行）。
    """
    if not req.upload_ids:
        raise HTTPException(400, "未选择图片")
    user_id, device_id = get_identity(request)

    def gen():
        ok = False
        manager.begin_task("facerec", FACE_GB)
        try:
            with manager.infer:
                total = len(req.upload_ids)
                # 首次识别模型懒加载（约 5-10 秒）
                yield json.dumps({"type": "phase", "msg": "模型加载中（首次约 5-10 秒）...", "pct": 2},
                                 ensure_ascii=False) + "\n"
                # 预热加载（不动业务数据）
                engine.face_engine()
                results = []
                for i, uid in enumerate(req.upload_ids):
                    up = db.query(FaceUpload).filter(
                        FaceUpload.id == uid, scope(FaceUpload, user_id, device_id)).first()
                    if not up or not os.path.exists(up.file_path):
                        results.append({"upload_id": uid, "name": "", "status": "error",
                                        "face_count": 0, "error": "图片不存在"})
                    else:
                        try:
                            results.append(_recognize_one(up, db, user_id, device_id))
                        except Exception as e:
                            results.append({"upload_id": uid, "name": up.filename, "status": "error",
                                            "face_count": 0, "error": f"识别失败: {e}"})
                    pct = 5 + round((i + 1) / total * 93, 1)
                    yield json.dumps({"type": "progress", "done": i + 1, "total": total, "pct": pct,
                                      "msg": f"识别中：第 {i + 1}/{total} 张"},
                                     ensure_ascii=False) + "\n"
                ok = True
                yield json.dumps({"type": "done", "results": results}, ensure_ascii=False) + "\n"
        finally:
            manager.end_task("facerec", FACE_GB)
            if ok:
                log_operation(request, "face.recognize", f"{len(req.upload_ids)} 张图片")
        # gen 函数无法直接返回非 200；异常统一由 done 事件承载

    # GPU 显存不足时阻止启动（防叠加爆显存）
    msg = gpu_free_too_low()
    if msg:
        raise HTTPException(507, msg)
    return StreamingResponse(gen(), media_type="application/x-ndjson; charset=utf-8")


@router.get("/stats")
def api_stats(request: Request, db: Session = Depends(get_db)):
    """人脸识别数据统计（供系统设置展示；仅当前归属）。"""
    user_id, device_id = get_identity(request)
    uploads = db.query(FaceUpload).filter(scope(FaceUpload, user_id, device_id)).count()
    results = db.query(FaceResult).filter(scope(FaceResult, user_id, device_id)).count()
    size = 0
    for r in db.query(FaceUpload).filter(scope(FaceUpload, user_id, device_id)).all():
        try:
            size += os.path.getsize(r.file_path)
        except OSError:
            pass
    for r in db.query(FaceResult).filter(scope(FaceResult, user_id, device_id)).all():
        if r.thumb_path:
            try:
                size += os.path.getsize(r.thumb_path)
            except OSError:
                pass
    return {"uploads": uploads, "results": results, "bytes": size}
