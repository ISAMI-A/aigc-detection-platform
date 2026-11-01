"""admin 人脸库管理：分页/模糊搜索/新增/改名/换照片/批量删除/样本照服务。"""
import os
import shutil
import uuid as _uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import engine
from auth import _get_current_user
from auth_device import log_operation
from model_manager import manager, gpu_free_too_low

router = APIRouter()


class IdsPayload(BaseModel):
    ids: list[int]


class RenameReq(BaseModel):
    record_id: int
    name: str


def _require_admin(request: Request) -> dict:
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, "未登录或登录已过期")
    if user.get("role") != "admin":
        raise HTTPException(403, "无管理员权限")
    return user


def _item(rec: dict) -> dict:
    out = dict(rec)
    out["thumb"] = f"/face/api/library/{rec['id']}/thumb" if rec.get("thumb_path") else ""
    out["bound"] = bool(rec.get("user_id"))
    return out


@router.get("/library")
def api_library_list(request: Request, q: str = "", page: int = 1, size: int = 20,
                     db: Session = Depends(get_db)):
    """人脸库分页列表（模糊搜索 name/person_id/created_by）。"""
    _require_admin(request)
    data = engine.face_db().list_page(q=q, page=page, size=size)
    return {"total": data["total"], "items": [_item(r) for r in data["items"]],
            "persons": engine.face_db().count_persons()}


@router.get("/library/{record_id}/thumb")
def api_library_thumb(record_id: int, request: Request):
    """库样本照服务（全局库数据，登录用户可见；管理页/个人资料共用）。"""
    rec = engine.face_db().get_record(record_id)
    if not rec or not rec["thumb_path"] or not os.path.exists(rec["thumb_path"]):
        raise HTTPException(404, "样本照不存在")
    return FileResponse(rec["thumb_path"], headers={"Cache-Control": "no-store"})


@router.post("/library")
async def api_library_add(request: Request, file: UploadFile = File(...),
                          name: str = Form(...), mode: str = Form("")):
    """admin 新增人员（与人工入库同一查重逻辑：同名补样本/异名 need_confirm）。"""
    _require_admin(request)
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "姓名不能为空")
    data = await file.read()
    if not data:
        raise HTTPException(400, "未收到图片")
    img = engine.decode_image_bytes(data)
    if gpu_free_too_low():
        raise HTTPException(507, gpu_free_too_low())

    with manager.infer:
        emb, det = engine.embed_largest_face(img)
    if emb is None:
        raise HTTPException(400, "未检测到人脸，请更换照片")

    fdb = engine.face_db()
    cands = fdb.search(emb, top_k=1)
    top = cands[0] if cands else None
    th = engine.SIMILARITY_THRESHOLD
    conflict = same_person_id = None
    if top and top["similarity"] >= th:
        if top["name"] != name:
            conflict = top
        else:
            same_person_id = top["person_id"]
    if mode not in ("overwrite", "new") and conflict:
        return {"need_confirm": True, "conflict": {
            "person_id": conflict["person_id"], "name": conflict["name"],
            "similarity": round(conflict["similarity"], 4)}}

    if mode == "overwrite" and (conflict or same_person_id):
        person_id = conflict["person_id"] if conflict else same_person_id
        fdb.rename_person(person_id, name)
    elif same_person_id:
        person_id = same_person_id          # 同名同人 → 直接补样本（无需新建人员）
    else:
        person_id = engine._new_person_id()

    lib_thumb = ""
    try:
        face = engine.crop_face(img, det["bbox"])
        lib_thumb = str(engine.LIB_THUMB_DIR / f"s_{_uuid.uuid4().hex}.jpg")
        engine.save_image(face, lib_thumb)
    except Exception:
        pass
    admin = _get_current_user(request)
    rid = fdb.add_sample(person_id, name, emb, thumb_path=lib_thumb,
                         created_by=f"admin:{admin['username']}", source="admin")
    log_operation(request, "face.library_add", f"{name} ({person_id})")
    return {"status": "ok", "record_id": rid, "person_id": person_id}


@router.post("/library/rename")
def api_library_rename(payload: RenameReq, request: Request):
    """改名（人员级：该 person_id 全部样本同步更新）。"""
    _require_admin(request)
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "姓名不能为空")
    rec = engine.face_db().get_record(payload.record_id)
    if not rec:
        raise HTTPException(404, "记录不存在")
    n = engine.face_db().rename_person(rec["person_id"], name)
    log_operation(request, "face.library_rename", f"{rec['person_id']} → {name}")
    return {"updated": n}


@router.post("/library/photo")
async def api_library_photo(request: Request, record_id: int = Form(...),
                            file: UploadFile = File(...)):
    """更换某样本照片：重新提取特征替换该记录（保留 person_id/绑定/其余样本）。"""
    _require_admin(request)
    fdb = engine.face_db()
    rec = fdb.get_record(record_id)
    if not rec:
        raise HTTPException(404, "记录不存在")
    data = await file.read()
    if not data:
        raise HTTPException(400, "未收到图片")
    img = engine.decode_image_bytes(data)
    if gpu_free_too_low():
        raise HTTPException(507, gpu_free_too_low())

    with manager.infer:
        emb, det = engine.embed_largest_face(img)
    if emb is None:
        raise HTTPException(400, "未检测到人脸，请更换照片")

    lib_thumb = ""
    try:
        face = engine.crop_face(img, det["bbox"])
        lib_thumb = str(engine.LIB_THUMB_DIR / f"s_{_uuid.uuid4().hex}.jpg")
        engine.save_image(face, lib_thumb)
    except Exception:
        pass
    admin = _get_current_user(request)
    # 删旧记录（含旧样本照）→ 以原 person_id 追加新样本
    old_thumb = rec["thumb_path"]
    fdb.delete(record_id)
    rid = fdb.add_sample(rec["person_id"], rec["name"], emb, thumb_path=lib_thumb,
                         user_id=rec["user_id"], created_by=f"admin:{admin['username']}",
                         source=rec["source"] or "admin")
    engine.delete_lib_thumbs([old_thumb] if old_thumb else [])
    log_operation(request, "face.library_photo", f"记录 {record_id} 换照")
    return {"status": "ok", "record_id": rid}


@router.delete("/library")
def api_library_delete(payload: IdsPayload, request: Request):
    """批量删除记录（含样本照文件）。ids 空=无操作。"""
    _require_admin(request)
    if not payload.ids:
        return {"deleted": 0}
    fdb = engine.face_db()
    thumbs = []
    for rid in payload.ids:
        rec = fdb.get_record(rid)
        if rec and rec["thumb_path"]:
            thumbs.append(rec["thumb_path"])
    n = fdb.delete_ids(payload.ids)
    engine.delete_lib_thumbs(thumbs)
    log_operation(request, "face.library_delete", f"{n} 条")
    return {"deleted": n}
