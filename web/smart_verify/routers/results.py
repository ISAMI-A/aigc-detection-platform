"""查询和修改核验结果。"""

import json
import os

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models import Pair, VerificationResult, ImageRecord
from ..scope import scope
from auth_device import get_identity

router = APIRouter()


class ManualFixRequest(BaseModel):
    is_same: bool | None = None   # True=是 False=否 None=取消人工修正（恢复机器结果）
    note: str = ""


class HumanJudgmentRequest(BaseModel):
    """人工复核判断（不覆盖机器结果）"""
    is_same: bool | None = None   # True=同一场景 False=不同 None=清除判断


@router.get("/results")
def list_results(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    status: str = Query(None),
    db: Session = Depends(get_db),
):
    """
    查询结果列表，支持分页（仅当前设备）。
    """
    user_id, device_id = get_identity(request)
    query = db.query(Pair, VerificationResult).outerjoin(
        VerificationResult, Pair.id == VerificationResult.pair_id
    ).filter(scope(Pair, user_id, device_id))

    pairs = query.order_by(Pair.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    dev = f"?dev={device_id}" if device_id else ""
    for pair, vr in pairs:
        # 图片访问 URL（子应用挂载 /smart；<img> 无法带 header，URL 必须带 dev 校验，B78 约定）
        left_url = f"/smart/api/images/{pair.left_image_id}{dev}" if pair.left_image_id else None
        right_url = f"/smart/api/images/{pair.right_image_id}{dev}" if pair.right_image_id else None
        # 缺失图片的配对
        if pair.status == "missing":
            items.append({
                "pair_id": pair.id,
                "mode": pair.mode,
                "uuid": pair.uuid,
                "location_name": pair.location_name,
                "pair_index": pair.pair_index,
                "left_filename": pair.left_filename,
                "right_filename": pair.right_filename,
                "left_image_id": pair.left_image_id,
                "right_image_id": pair.right_image_id,
                "left_image_url": left_url,
                "right_image_url": right_url,
                "status": "missing",
                "is_same": None,
                "confidence": None,
                "total_matches": None,
                "inliers": None,
                "inlier_ratio": None,
                "dino_similarity": None,
                "manual_override": False,
                "note": "图片缺失",
                "result_id": None,
            })
            continue

        # 最终判定：人工修正优先
        note = "待核验"
        if vr and vr.manual_override:
            final_same = vr.manual_is_same
            final_conf = None
            note = f"人工修正: {vr.manual_note}" if vr.manual_note else "人工修正"
        elif vr:
            final_same = vr.is_same
            final_conf = round(vr.confidence, 4)
            note = ""
        else:
            final_same = None
            final_conf = None

        items.append({
            "pair_id": pair.id,
            "mode": pair.mode,
            "uuid": pair.uuid,
            "location_name": pair.location_name,
            "pair_index": pair.pair_index,
            "left_filename": pair.left_filename,
            "right_filename": pair.right_filename,
            "left_image_id": pair.left_image_id,
            "right_image_id": pair.right_image_id,
            "left_image_url": left_url,
            "right_image_url": right_url,
            "status": pair.status,
            "is_same": final_same,
            "confidence": final_conf,
            "total_matches": vr.total_matches if vr else None,
            "inliers": vr.ransac_inliers if vr else None,
            "inlier_ratio": round(vr.inlier_ratio, 4) if vr and vr.inlier_ratio is not None else None,
            "dino_similarity": None,
            "manual_override": vr.manual_override if vr else False,
            "note": note,
            "result_id": vr.id if vr else None,
            "human_judgment": vr.human_judgment if vr else None,
        })

    total = db.query(Pair).filter(scope(Pair, user_id, device_id)).count()
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/results/{result_id}/detail")
def result_detail(result_id: int, request: Request, db: Session = Depends(get_db)):
    """
    获取单条核验结果详情（含标注坐标），供前端 Canvas 绘制（仅当前设备）。
    """
    user_id, device_id = get_identity(request)
    vr = db.query(VerificationResult).filter(
        VerificationResult.id == result_id, scope(VerificationResult, user_id, device_id)
    ).first()
    if not vr:
        raise HTTPException(404, "结果不存在")

    pair = db.query(Pair).filter(Pair.id == vr.pair_id).first()
    if not pair:
        raise HTTPException(404, "配对不存在")

    left = db.query(ImageRecord).filter(ImageRecord.id == pair.left_image_id).first()
    right = db.query(ImageRecord).filter(ImageRecord.id == pair.right_image_id).first()

    annotations = {}
    if vr.regions_json:
        try:
            annotations = json.loads(vr.regions_json)
        except json.JSONDecodeError:
            annotations = {}

    return {
        "result_id": vr.id,
        "pair_id": vr.pair_id,
        "is_same": vr.is_same,
        "confidence": vr.confidence,
        "total_matches": vr.total_matches,
        "ransac_inliers": vr.ransac_inliers,
        "inlier_ratio": vr.inlier_ratio,
        "method": vr.method,
        "manual_override": vr.manual_override,
        "manual_is_same": vr.manual_is_same,
        "manual_note": vr.manual_note,
        "human_judgment": vr.human_judgment,
        "annotations": annotations,
        # 子应用挂载在 /smart 下，图片 URL 需带前缀 + dev 校验（<img> 无法带 header，B78 约定）
        "left_image_url": f"/smart/api/images/{pair.left_image_id}?dev={device_id}",
        "right_image_url": f"/smart/api/images/{pair.right_image_id}?dev={device_id}",
        "left_filename": pair.left_filename,
        "right_filename": pair.right_filename,
        "left_width": left.width if left else 0,
        "left_height": left.height if left else 0,
        "right_width": right.width if right else 0,
        "right_height": right.height if right else 0,
    }


@router.put("/results/{result_id}/manual")
def manual_fix(result_id: int, req: ManualFixRequest, request: Request, db: Session = Depends(get_db)):
    """
    人工修正某个核验结果（仅当前设备）。
    """
    user_id, device_id = get_identity(request)
    vr = db.query(VerificationResult).filter(
        VerificationResult.id == result_id, scope(VerificationResult, user_id, device_id)
    ).first()
    if not vr:
        raise HTTPException(404, "结果不存在")

    if req.is_same is None:
        # 取消人工修正，恢复机器结果
        vr.manual_override = False
        vr.manual_is_same = None
        vr.manual_note = None
    else:
        vr.manual_override = True
        vr.manual_is_same = req.is_same
        vr.manual_note = req.note
    db.commit()

    return {"result_id": result_id, "manual_override": vr.manual_override,
            "manual_is_same": vr.manual_is_same, "note": vr.manual_note}


@router.put("/results/{result_id}/human-judgment")
def human_judgment(result_id: int, req: HumanJudgmentRequest, request: Request, db: Session = Depends(get_db)):
    """
    人工复核判断（不覆盖机器结果，仅供准确率对比；仅当前设备）。
    is_same=true → 人为判断是同一场景
    is_same=false → 人为判断不是同一场景
    is_same=null  → 清除判断
    """
    user_id, device_id = get_identity(request)
    vr = db.query(VerificationResult).filter(
        VerificationResult.id == result_id, scope(VerificationResult, user_id, device_id)
    ).first()
    if not vr:
        raise HTTPException(404, "结果不存在")

    vr.human_judgment = req.is_same
    db.commit()

    return {"result_id": result_id, "human_judgment": req.is_same}


class DeletePairsRequest(BaseModel):
    """批量删除请求体"""
    pair_ids: list[int]


@router.delete("/pairs/{pair_id}")
def delete_pair(pair_id: int, request: Request, db: Session = Depends(get_db)):
    """
    删除单个配对及其关联结果（仅当前设备）。
    """
    user_id, device_id = get_identity(request)
    pair = db.query(Pair).filter(
        Pair.id == pair_id, scope(Pair, user_id, device_id)
    ).first()
    if not pair:
        raise HTTPException(404, "配对不存在")

    # 删除关联的结果
    vr = db.query(VerificationResult).filter(
        VerificationResult.pair_id == pair_id
    ).first()
    if vr:
        # 删除可视化文件
        if vr.vis_path and os.path.exists(vr.vis_path):
            try:
                os.remove(vr.vis_path)
            except OSError:
                pass
        db.delete(vr)

    db.delete(pair)
    db.commit()
    return {"deleted": pair_id}


@router.post("/pairs/batch-delete")
def delete_pairs_batch(req: DeletePairsRequest, request: Request, db: Session = Depends(get_db)):
    """
    批量删除多个配对及其关联结果（仅当前设备）。
    """
    user_id, device_id = get_identity(request)
    deleted = []
    for pair_id in req.pair_ids:
        pair = db.query(Pair).filter(
            Pair.id == pair_id, scope(Pair, user_id, device_id)
        ).first()
        if not pair:
            continue

        vr = db.query(VerificationResult).filter(
            VerificationResult.pair_id == pair_id
        ).first()
        if vr:
            if vr.vis_path and os.path.exists(vr.vis_path):
                try:
                    os.remove(vr.vis_path)
                except OSError:
                    pass
            db.delete(vr)

        db.delete(pair)
        deleted.append(pair_id)

    db.commit()
    return {"deleted_count": len(deleted), "deleted_ids": deleted}
