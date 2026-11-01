"""核验接口：单对核验、批量核验（含进度跟踪）。"""

import json
import os
import torch
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models import Pair, VerificationResult, ImageRecord
from ..scope import scope
from ..services.verifier import SceneVerifier
from ..services.annotation import generate_annotations
from auth_device import get_identity, log_operation
from model_manager import manager, gpu_free_too_low   # 统一模型管理器（全局推理串行锁 + 显存记账）

router = APIRouter()

# 可视化图目录：web/data/smart_visualizations
VIS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "smart_visualizations")


def _load_verifier() -> SceneVerifier:
    """SuperPoint + LightGlue 场景核验器加载器（由模型管理器懒加载单例化）。"""
    # 自动检测 CUDA 可用性，不可用时回退 CPU
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"[核验] 使用设备: {device}")
    return SceneVerifier(device=device, min_inliers=12, min_ratio=0.15)


def get_verifier() -> SceneVerifier:
    """懒加载单例：经模型管理器统一注册/调度（显存约 0.5GB，超预算时按 LRU 卸载；
    核验完成后立即卸载释放 GPU 显存（_unload_verifier），空闲 60s 兜底自动卸载，
    下次核验再自动加载）。"""
    return manager.get("superpoint_lightglue", _load_verifier, est_gb=0.5, idle_timeout=60)


def _unload_verifier():
    """核验完成立即卸载核验模型（释放 GPU 显存；下次核验自动重新加载）。

    必须在 manager.infer 锁内调用（与并发推理互斥），避免推理中被卸载。
    """
    manager.unload("superpoint_lightglue")


# ====== 批量核验进度跟踪 ======
_batch_progress = {}
_batch_lock = Lock()


def get_progress():
    with _batch_lock:
        return dict(_batch_progress)


def set_progress(**kwargs):
    with _batch_lock:
        _batch_progress.update(kwargs)


def clear_progress():
    with _batch_lock:
        _batch_progress.clear()


# ====== 核心核验逻辑（提取为公共函数） ======

def _run_verify(pair: Pair, db: Session) -> dict:
    """对单个配对执行核验，返回结果字典。"""
    left = db.query(ImageRecord).filter(ImageRecord.id == pair.left_image_id).first()
    right = db.query(ImageRecord).filter(ImageRecord.id == pair.right_image_id).first()

    if not left or not right:
        pair.status = "error"
        db.commit()
        return {"pair_id": pair.id, "error": "图片不完整"}

    # 删除旧结果
    db.query(VerificationResult).filter(VerificationResult.pair_id == pair.id).delete()

    verifier = get_verifier()
    out = verifier.verify(left.file_path, right.file_path, save_vis_dir=VIS_DIR)

    ann = {}
    if out.mkpts0 is not None and out.mask is not None:
        ann = generate_annotations(out.mkpts0, out.mkpts1, out.mask)

    vr = VerificationResult(
        pair_id=pair.id,
        device_id=pair.device_id,
        user_id=pair.user_id,
        is_same=out.is_same_scene,
        confidence=out.confidence,
        total_matches=out.total_matches,
        ransac_inliers=out.ransac_inliers,
        inlier_ratio=out.inlier_ratio,
        method=out.method,
        regions_json=json.dumps(ann, ensure_ascii=False) if ann else None,
        vis_path=out.vis_path,
    )
    db.add(vr)
    pair.status = "done"
    db.commit()

    return {
        "pair_id": pair.id,
        "is_same": out.is_same_scene,
        "confidence": out.confidence,
        "total_matches": out.total_matches,
        "inliers": out.ransac_inliers,
        "inlier_ratio": out.inlier_ratio,
        "method": out.method,
        "vis_url": f"/smart/api/visualization/{vr.id}" if out.vis_path else None,
        "result_id": vr.id,
    }


def _process_pair_safe(pair: Pair, db: Session) -> dict:
    """安全的单对核验（带异常捕获）。"""
    pair.status = "running"
    db.commit()
    try:
        return _run_verify(pair, db)
    except Exception as e:
        pair.status = "error"
        db.commit()
        return {"pair_id": pair.id, "error": str(e)}


# ====== API ======

@router.post("/verify/single/{pair_id}")
def verify_single(pair_id: int, request: Request, db: Session = Depends(get_db)):
    """核验单个配对（不论当前状态，先重置再核验；仅当前设备）。"""
    msg = gpu_free_too_low()
    if msg:
        raise HTTPException(507, msg)
    user_id, device_id = get_identity(request)
    pair = db.query(Pair).filter(
        Pair.id == pair_id, scope(Pair, user_id, device_id)
    ).first()
    if not pair:
        raise HTTPException(404, "配对不存在")
    if pair.left_image_id is None or pair.right_image_id is None:
        raise HTTPException(400, "配对图片不完整，无法核验")
    # 不论当前状态（pending/running/error/done），先重置为 pending 再核验
    pair.status = "pending"
    db.commit()
    # 全局推理串行锁：与检测（TruFor）等其他系统互斥，防并发挤爆显存
    with manager.infer:
        result = _process_pair_safe(pair, db)
        _unload_verifier()   # 单对核验完立即卸载模型，释放 GPU 显存
    return result


@router.get("/verify/progress")
def verify_progress():
    """获取当前批量核验进度。"""
    p = get_progress()
    if not p:
        return {"running": False}
    return {
        "running": True,
        "total": p.get("total", 0),
        "processed": p.get("processed", 0),
        "current": p.get("current", ""),
    }


@router.post("/verify/batch")
def verify_batch(request: Request, db: Session = Depends(get_db)):
    """
    批量核验当前设备所有 pending 和 error 状态的配对（带进度跟踪）。
    """
    msg = gpu_free_too_low()
    if msg:
        raise HTTPException(507, msg)
    user_id, device_id = get_identity(request)
    pairs = db.query(Pair).filter(
        scope(Pair, user_id, device_id),
        Pair.status.in_(["pending", "error", "running"]),
        Pair.left_image_id.isnot(None),
        Pair.right_image_id.isnot(None),
    ).all()

    if not pairs:
        return {"processed": 0, "results": [], "message": "没有待核验的配对"}
    log_operation(request, "verify.run", f"{len(pairs)} 对")

    # 先将 running 状态的配对重置为 pending，避免重复并发问题
    for p in pairs:
        if p.status == "running":
            p.status = "pending"
    db.commit()

    total = len(pairs)
    set_progress(total=total, processed=0, current="准备中...")
    results = []

    # 全局推理串行锁：批量核验与检测（TruFor）等其他系统互斥，防并发挤爆显存
    with manager.infer:
        for i, pair in enumerate(pairs):
            try:
                set_progress(processed=i, current=pair.left_filename or f"第{i+1}对")
                r = _process_pair_safe(pair, db)
                results.append(r)
            except Exception as e:
                results.append({"pair_id": pair.id, "error": str(e)})
        _unload_verifier()   # 批量跑完立即卸载模型，释放 GPU 显存

    missing_count = db.query(Pair).filter(Pair.status == "missing").count()
    set_progress(total=total, processed=total, current="完成")

    # 延迟清除进度，让前端有时间读取
    import threading
    threading.Timer(3.0, clear_progress).start()

    return {
        "processed": len(results),
        "results": results,
        "missing_count": missing_count,
    }


class SelectedVerifyRequest(BaseModel):
    pair_ids: list[int]


@router.post("/verify/selected")
def verify_selected(req: SelectedVerifyRequest, request: Request, db: Session = Depends(get_db)):
    """
    按勾选的配对核验（pending 和 error 都处理；仅当前设备）。
    """
    msg = gpu_free_too_low()
    if msg:
        raise HTTPException(507, msg)
    if not req.pair_ids:
        return {"processed": 0, "results": [], "message": "未选择配对"}

    user_id, device_id = get_identity(request)
    pairs = db.query(Pair).filter(
        Pair.id.in_(req.pair_ids),
        scope(Pair, user_id, device_id),
        Pair.status.in_(["pending", "error", "running"]),
        Pair.left_image_id.isnot(None),
        Pair.right_image_id.isnot(None),
    ).all()

    if not pairs:
        return {"processed": 0, "results": [], "message": "所选配对无法核验"}

    # 先将 running 状态的配对重置为 pending
    for p in pairs:
        if p.status == "running":
            p.status = "pending"
    db.commit()

    total = len(pairs)
    set_progress(total=total, processed=0, current="准备中...")
    results = []

    # 全局推理串行锁：批量核验与检测（TruFor）等其他系统互斥，防并发挤爆显存
    with manager.infer:
        for i, pair in enumerate(pairs):
            try:
                set_progress(processed=i, current=pair.left_filename or f"第{i+1}对")
                r = _process_pair_safe(pair, db)
                results.append(r)
            except Exception as e:
                results.append({"pair_id": pair.id, "error": str(e)})
        _unload_verifier()   # 批量跑完立即卸载模型，释放 GPU 显存

    set_progress(total=total, processed=total, current="完成")
    import threading
    threading.Timer(3.0, clear_progress).start()

    return {"processed": len(results), "results": results}
