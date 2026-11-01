"""
图片上传与配对。

支持三种配对模式：
  - auto: 文件名自动配对（按 UUID + 地点名称）
  - sequential: 按左栏/右栏顺序一一配对
  - manual: 手动勾选配对
"""

import os
import shutil
import uuid as uuid_lib
from pathlib import Path
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from PIL import Image

from ..database import get_db
from ..models import ImageRecord, Pair
from ..services.parser import parse_filename
from ..scope import scope
from auth_device import get_identity, log_operation

router = APIRouter()

# 上传目录：web/data/smart_uploads（独立于检测系统临时目录）
_WEB = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = _WEB / "data" / "smart_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {'.png', '.jpg', '.jpeg', '.webp'}


class PairRequest(BaseModel):
    """配对请求体"""
    left_ids: list[int]
    right_ids: list[int]


def _save_file(file: UploadFile, photo_type: str, device_id: str, user_id, db: Session) -> ImageRecord:
    """保存单个上传文件到磁盘并写入数据库（记录归属设备/用户）。

    幂等：若服务器已存在同名文件（无论整改图/暗访图），直接返回已存在记录，
    不再重复落盘，避免资源管理器出现冗余文件。
    """
    ext = os.path.splitext(file.filename or "image.png")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的文件格式: {ext}")

    # 同名查重（登录按 user_id、游客按 device_id）：已有记录直接复用（前端会据返回记录刷新面板状态）
    existing = db.query(ImageRecord).filter(
        ImageRecord.filename == file.filename,
        scope(ImageRecord, user_id, device_id),
    ).first()
    if existing:
        print(f"[核验] 文件已存在，跳过落盘: {file.filename} (id={existing.id})")
        return existing

    # 保存到 uploads 目录
    stored_name = f"{uuid_lib.uuid4().hex}{ext}"
    save_path = UPLOAD_DIR / stored_name
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 获取图片尺寸
    try:
        img = Image.open(save_path)
        width, height = img.size
    except Exception:
        width, height = 0, 0

    # 解析文件名
    parsed = parse_filename(file.filename or "")
    photo_num = 0
    if parsed:
        try:
            photo_num = int(parsed['photo_num'])
        except (ValueError, TypeError):
            photo_num = 0

    record = ImageRecord(
        device_id=device_id,
        user_id=user_id,
        filename=file.filename or stored_name,
        stored_name=stored_name,
        file_path=str(save_path),
        uuid=parsed['uuid'] if parsed else None,
        location_name=parsed['location'] if parsed else None,
        photo_type=photo_type,
        photo_num=photo_num,
        width=width,
        height=height,
    )
    db.add(record)
    db.flush()
    return record


@router.post("/upload")
async def upload_files(
    request: Request,
    left_files: list[UploadFile] = File(default=[]),
    right_files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    """
    批量上传整改图和暗访图，保存到磁盘和数据库（归属当前设备）。

    - left_files: 整改图
    - right_files: 暗访图
    - 返回已保存的图片记录列表
    """
    user_id, device_id = get_identity(request)
    left_records = []
    right_records = []

    for f in left_files:
        try:
            rec = _save_file(f, "整改图", device_id, user_id, db)
            left_records.append(rec)
        except Exception as e:
            raise HTTPException(400, f"整改图 {f.filename} 上传失败: {e}")

    for f in right_files:
        try:
            rec = _save_file(f, "暗访图", device_id, user_id, db)
            right_records.append(rec)
        except Exception as e:
            raise HTTPException(400, f"暗访图 {f.filename} 上传失败: {e}")

    db.commit()
    log_operation(request, "verify.upload", f"{len(left_records) + len(right_records)} 张")

    return {
        "message": "上传成功",
        "left_count": len(left_records),
        "right_count": len(right_records),
        "left_images": [
            {"id": r.id, "filename": r.filename, "stored_name": r.stored_name,
             "uuid": r.uuid, "location": r.location_name, "photo_num": r.photo_num}
            for r in left_records
        ],
        "right_images": [
            {"id": r.id, "filename": r.filename, "stored_name": r.stored_name,
             "uuid": r.uuid, "location": r.location_name, "photo_num": r.photo_num}
            for r in right_records
        ],
    }


@router.post("/upload-single")
async def upload_single(
    request: Request,
    image: UploadFile = File(...),
    photo_type: str = "整改图",
    db: Session = Depends(get_db),
):
    """上传单张图片（支持指定 photo_type: 整改图/暗访图），返回一条记录。

    上传即落盘：选文件后立即调用，刷新页面可从后端恢复列表。
    """
    user_id, device_id = get_identity(request)
    if photo_type not in ("整改图", "暗访图"):
        photo_type = "整改图"
    try:
        rec = _save_file(image, photo_type, device_id, user_id, db)
        db.commit()
        log_operation(request, "verify.upload", f"single #{rec.id}")
        return {"image": {"id": rec.id, "filename": rec.filename}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"上传失败: {e}")


@router.post("/pair/auto")
def pair_auto(
    req: PairRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    文件名自动配对：按 UUID + 地点名称 + photo_num 匹配（仅当前设备图片）。
    """
    user_id, device_id = get_identity(request)
    left_images = db.query(ImageRecord).filter(
        ImageRecord.id.in_(req.left_ids), ImageRecord.photo_type == "整改图",
        scope(ImageRecord, user_id, device_id),
    ).all()
    right_images = db.query(ImageRecord).filter(
        ImageRecord.id.in_(req.right_ids), ImageRecord.photo_type == "暗访图",
        scope(ImageRecord, user_id, device_id),
    ).all()

    # 按 (uuid, location_name) 分组
    zg_map = defaultdict(list)
    for r in left_images:
        key = (r.uuid, r.location_name)
        zg_map[key].append(r)

    af_map = defaultdict(list)
    for r in right_images:
        key = (r.uuid, r.location_name)
        af_map[key].append(r)

    all_keys = set(list(zg_map.keys()) + list(af_map.keys()))
    pairs_created = []

    for key in sorted(all_keys):
        zlist = sorted(zg_map.get(key, []), key=lambda x: x.photo_num)
        alist = sorted(af_map.get(key, []), key=lambda x: x.photo_num)
        max_n = max(len(zlist), len(alist))

        for i in range(max_n):
            z = zlist[i] if i < len(zlist) else None
            a = alist[i] if i < len(alist) else None
            if z and a:
                pair = Pair(
                    device_id=device_id,
                    user_id=user_id,
                    mode="auto",
                    uuid=key[0],
                    location_name=key[1],
                    pair_index=i,
                    left_image_id=z.id,
                    right_image_id=a.id,
                    left_filename=z.filename,
                    right_filename=a.filename,
                    status="pending",
                )
            elif z and not a:
                pair = Pair(
                    device_id=device_id,
                    user_id=user_id,
                    mode="auto",
                    uuid=key[0],
                    location_name=key[1],
                    pair_index=i,
                    left_image_id=z.id,
                    right_image_id=None,
                    left_filename=z.filename,
                    right_filename="[缺失对应暗访图]",
                    status="missing",
                )
            elif not z and a:
                pair = Pair(
                    device_id=device_id,
                    user_id=user_id,
                    mode="auto",
                    uuid=key[0],
                    location_name=key[1],
                    pair_index=i,
                    left_image_id=None,
                    right_image_id=a.id,
                    left_filename="[缺失对应整改图]",
                    right_filename=a.filename,
                    status="missing",
                )
            else:
                continue
            db.add(pair)
            db.flush()
            pairs_created.append({
                "pair_id": pair.id,
                "uuid": key[0],
                "location": key[1],
                "index": i,
                "left": pair.left_filename or "",
                "right": pair.right_filename or "",
                "missing": pair.status == "missing",
            })

    db.commit()
    return {"pairs_created": len(pairs_created), "pairs": pairs_created}


@router.post("/pair/sequential")
def pair_sequential(
    req: PairRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    顺序配对：左栏第 N 张 ↔ 右栏第 N 张（仅当前设备图片）。
    """
    user_id, device_id = get_identity(request)
    left_images = db.query(ImageRecord).filter(
        ImageRecord.id.in_(req.left_ids), scope(ImageRecord, user_id, device_id)
    ).order_by(ImageRecord.id).all()
    right_images = db.query(ImageRecord).filter(
        ImageRecord.id.in_(req.right_ids), scope(ImageRecord, user_id, device_id)
    ).order_by(ImageRecord.id).all()

    max_n = max(len(left_images), len(right_images))
    pairs_created = []

    for i in range(max_n):
        z = left_images[i] if i < len(left_images) else None
        a = right_images[i] if i < len(right_images) else None
        if z and a:
            pair = Pair(
                device_id=device_id,
                user_id=user_id,
                mode="sequential",
                pair_index=i,
                left_image_id=z.id,
                right_image_id=a.id,
                left_filename=z.filename,
                right_filename=a.filename,
                status="pending",
            )
        elif z and not a:
            pair = Pair(
                device_id=device_id,
                user_id=user_id,
                mode="sequential",
                pair_index=i,
                left_image_id=z.id,
                right_image_id=None,
                left_filename=z.filename,
                right_filename="[缺失对应暗访图]",
                status="missing",
            )
        elif not z and a:
            pair = Pair(
                device_id=device_id,
                user_id=user_id,
                mode="sequential",
                pair_index=i,
                left_image_id=None,
                right_image_id=a.id,
                left_filename="[缺失对应整改图]",
                right_filename=a.filename,
                status="missing",
            )
        else:
            continue
        db.add(pair)
        db.flush()
        pairs_created.append({
            "pair_id": pair.id,
            "index": i,
            "left": pair.left_filename or "",
            "right": pair.right_filename or "",
        })

    db.commit()
    return {"pairs_created": len(pairs_created), "pairs": pairs_created}


@router.post("/pair/manual")
def pair_manual(
    req: PairRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    单点比对：左栏勾选 N 张，右栏勾选 N 张，按选择顺序一一配对（仅当前设备图片）。

    left_ids 和 right_ids 数量必须一致。
    """
    if len(req.left_ids) != len(req.right_ids):
        raise HTTPException(400, "左右栏选择的图片数量不一致")

    if len(req.left_ids) == 0:
        raise HTTPException(400, "请至少选择一对图片")

    user_id, device_id = get_identity(request)
    left_images = db.query(ImageRecord).filter(
        ImageRecord.id.in_(req.left_ids), scope(ImageRecord, user_id, device_id)
    ).all()
    right_images = db.query(ImageRecord).filter(
        ImageRecord.id.in_(req.right_ids), scope(ImageRecord, user_id, device_id)
    ).all()

    left_map = {r.id: r for r in left_images}
    right_map = {r.id: r for r in right_images}

    pairs_created = []

    for i in range(len(req.left_ids)):
        z = left_map.get(req.left_ids[i])
        a = right_map.get(req.right_ids[i])
        if not z or not a:
            continue

        pair = Pair(
            device_id=device_id,
            user_id=user_id,
            mode="manual",
            pair_index=i,
            left_image_id=z.id,
            right_image_id=a.id,
            left_filename=z.filename,
            right_filename=a.filename,
            status="pending",
        )
        db.add(pair)
        db.flush()
        pairs_created.append({
            "pair_id": pair.id,
            "index": i,
            "left": z.filename,
            "right": a.filename,
        })

    db.commit()
    return {"pairs_created": len(pairs_created), "pairs": pairs_created}
