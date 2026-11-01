"""人脸登录 + 个人资料人脸录入。

- POST /api/login_face：上传照片/摄像头帧识别 → 匹配已绑定账号的人脸 → 签发 token
- GET/POST/DELETE /api/profile_face：个人资料页人脸录入状态 / 录入（查重+绑定）/ 删除
"""
import base64
import json
import os
import shutil
import uuid as _uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import engine
from auth import create_token, engine as auth_engine, users, _public_user
from auth_device import get_identity, get_device_id, log_operation
from model_manager import manager, gpu_free_too_low

router = APIRouter()


class LoginFaceReq(BaseModel):
    image: str = ""        # base64（dataURL 或裸 base64），摄像头帧用


def _match_bound_user(emb) -> tuple[dict | None, float]:
    """在"已绑定账号"的人脸子集中匹配：返回 (候选记录, 相似度) 或 (None, 0)。"""
    cands = engine.face_db().search(emb, top_k=5)
    for c in cands:
        if c["user_id"] and c["similarity"] >= engine.SIMILARITY_THRESHOLD:
            return c, c["similarity"]
    return None, 0.0


@router.post("/login_face")
async def api_login_face(request: Request, file: UploadFile = File(None)):
    """人脸登录：照片（multipart）或摄像头帧（JSON base64，走 /login_face_frame）。

    仅匹配已录入人脸且已绑定账号的用户；命中即签发 30 天 token（与密码登录同轨）。
    """
    if gpu_free_too_low():
        raise HTTPException(507, gpu_free_too_low())
    data = await file.read() if file else b""
    if not data:
        raise HTTPException(400, "未收到图片")
    img = engine.decode_image_bytes(data)

    matched_user = None
    with manager.infer:
        emb, _det = engine.embed_largest_face(img)
    if emb is None:
        return {"matched": False, "reason": "未检测到人脸，请换一张清晰的正脸照片"}
    cand, sim = _match_bound_user(emb)
    if cand is None:
        return {"matched": False, "reason": "未匹配到已录入人脸的账号，请先在个人资料中录入人脸"}

    import sqlalchemy as sa
    with auth_engine.connect() as conn:
        row = conn.execute(sa.select(users).where(users.c.id == cand["user_id"])).first()
    if not row or row._mapping["disabled"]:
        return {"matched": False, "reason": "账号不可用"}
    token = create_token(row._mapping["id"], get_device_id(request))
    log_operation(request, "face.login", row._mapping["username"])
    return {"matched": True, "token": token, "user": _public_user(row)}


@router.post("/login_face_frame")
async def api_login_face_frame(payload: LoginFaceReq, request: Request):
    """摄像头帧人脸登录（JSON base64；前端 canvas.toDataURL 截帧）。"""
    b64 = (payload.image or "").strip()
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        data = base64.b64decode(b64)
    except Exception:
        raise HTTPException(400, "图片数据无效")
    if not data:
        raise HTTPException(400, "未收到图片")
    img = engine.decode_image_bytes(data)
    if gpu_free_too_low():
        raise HTTPException(507, gpu_free_too_low())

    with manager.infer:
        emb, _det = engine.embed_largest_face(img)
    if emb is None:
        return {"matched": False, "reason": "未检测到人脸"}
    cand, sim = _match_bound_user(emb)
    if cand is None:
        return {"matched": False, "reason": "未匹配到已录入人脸的账号"}

    import sqlalchemy as sa
    with auth_engine.connect() as conn:
        row = conn.execute(sa.select(users).where(users.c.id == cand["user_id"])).first()
    if not row or row._mapping["disabled"]:
        return {"matched": False, "reason": "账号不可用"}
    token = create_token(row._mapping["id"], get_device_id(request))
    log_operation(request, "face.login", row._mapping["username"])
    return {"matched": True, "token": token, "user": _public_user(row)}


# ============================================================
# 个人资料 · 人脸录入
# ============================================================

class ProfileSaveReq(BaseModel):
    name: str
    mode: str = ""


@router.get("/profile_face")
def api_profile_face(request: Request, db: Session = Depends(get_db)):
    """我的录入状态：已绑定人脸（姓名/样本数/样本照）或未录入。"""
    user_id, _ = get_identity(request)
    if user_id is None:
        raise HTTPException(401, "请先登录")
    recs = engine.face_db().find_by_user(user_id)
    if not recs:
        return {"bound": False, "name": "", "samples": [], "count": 0}
    return {"bound": True, "name": recs[0]["name"],
            "samples": [{"id": r["id"], "created_at": r["created_at"],
                         "thumb": f"/face/api/library/{r['id']}/thumb"}
                        for r in recs],
            "count": len(recs)}


@router.post("/profile_face")
async def api_profile_face_save(request: Request, file: UploadFile = File(...),
                                name: str = Form(...), mode: str = Form("")):
    """录入/更新我的人脸（登录用户）：提取最大脸 → 查重（同名补样本/异名需确认）→ 入库并绑定账号。"""
    user_id, _ = get_identity(request)
    if user_id is None:
        raise HTTPException(401, "请先登录")
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
        raise HTTPException(400, "未检测到人脸，请换一张清晰的正脸照片")

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

    if mode not in ("overwrite", "new") and conflict:
        # 该人脸已绑定其他账号 → 直接拒绝（不能覆盖他人绑定）
        if conflict["user_id"] and conflict["user_id"] != user_id:
            raise HTTPException(409, f"该人脸已绑定账号「{conflict['name']}」，无法覆盖录入")
        return {"need_confirm": True, "conflict": conflict}

    if mode == "overwrite" and (conflict or same_person_id):
        person_id = conflict["person_id"] if conflict else same_person_id
        fdb.rename_person(person_id, name)
    elif same_person_id:
        person_id = same_person_id          # 同名同人 → 直接补样本（无需新建人员）
    else:
        person_id = engine._new_person_id()

    # 库样本照：从原图裁剪落盘到人脸库 thumbs
    lib_thumb = ""
    try:
        face = engine.crop_face(img, det["bbox"])
        lib_thumb = str(engine.LIB_THUMB_DIR / f"s_{_uuid.uuid4().hex}.jpg")
        engine.save_image(face, lib_thumb)
    except Exception:
        pass

    fdb.add_sample(person_id, name, emb, thumb_path=lib_thumb,
                   created_by=f"user:{user_id}", source="web-profile")
    fdb.bind_user(person_id, user_id)
    log_operation(request, "face.profile_save", f"{name} ({person_id})")
    return {"status": "ok", "person_id": person_id, "name": name}


@router.delete("/profile_face")
def api_profile_face_delete(request: Request):
    """删除我的人脸录入：解绑账号 + 删除库中该人员全部样本（含样本照文件）。"""
    user_id, _ = get_identity(request)
    if user_id is None:
        raise HTTPException(401, "请先登录")
    fdb = engine.face_db()
    recs = fdb.find_by_user(user_id)
    if not recs:
        return {"deleted": 0}
    person_id = recs[0]["person_id"]
    thumbs = [r["thumb_path"] for r in recs if r["thumb_path"]]
    fdb.unbind_user(user_id)
    n = fdb.delete_person(person_id)
    engine.delete_lib_thumbs(thumbs)
    log_operation(request, "face.profile_delete", f"{person_id} 共 {n} 样本")
    return {"deleted": n}
