"""点位真实性核验子系统（FastAPI 子应用）。

由主应用挂载到 /smart 前缀下，内部路由保持 /api/*，最终访问路径为 /smart/api/*。
独立 SQLite（web/data/smart_verify.db）与存储目录，与检测系统互不干扰。
"""

import os
import shutil
import threading
from datetime import datetime as _dt, timedelta

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text, func

from .database import Base, engine, get_db, SessionLocal
from .models import ImageRecord, Pair, VerificationResult
from .routers import upload, verify, results, export
from .scope import scope
from auth_device import get_device_id, get_identity, get_identity_from_img
from api_envelope import install_errors

# 存储目录：web/data/smart_uploads（上传图）、web/data/smart_visualizations（可视化图）
_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_WEB, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "smart_uploads")
VIS_DIR = os.path.join(DATA_DIR, "smart_visualizations")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(VIS_DIR, exist_ok=True)

# 先创建表
Base.metadata.create_all(bind=engine)


def _migrate_add_device_id():
    """启动迁移：为已存在的表补 device_id / user_id 列与双轨索引（create_all 不会给已有表加列）。"""
    with engine.connect() as conn:
        for tbl in ("images", "pairs", "results"):
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({tbl})")).fetchall()}
            if "device_id" not in cols:
                conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN device_id VARCHAR DEFAULT ''"))
                print(f"[核验] 迁移：{tbl} 表新增 device_id 列")
            # 批次2：登录体系数据层预留 —— user_id（NULL=游客）
            if "user_id" not in cols:
                conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN user_id INTEGER"))
                print(f"[核验] 迁移：{tbl} 表新增 user_id 列")
    # 批次2：双轨查询索引（user_id 优先、无则 device_id，两条独立查询分支）
    with engine.begin() as conn:
        for tbl in ("images", "pairs", "results"):
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_smart_{tbl}_device_created ON {tbl}(device_id, created_at)"))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_smart_{tbl}_user_created ON {tbl}(user_id, created_at)"))


_migrate_add_device_id()


def cleanup_all(device_id: str = "", user_id=None):
    """清空指定数据（批次3：登录按 user_id、游客按 device_id）。

    - 只删除归属记录对应的物理文件（上传图/可视化图），不 rmtree 整个目录
    - 旧数据（device_id 为空串）也会被清掉，避免历史遗留不可见数据残留
    """
    db = SessionLocal()
    try:
        if user_id is not None:
            vr_scope = VerificationResult.user_id == user_id
            pair_scope = Pair.user_id == user_id
            img_scope = ImageRecord.user_id == user_id
        else:
            vr_scope = VerificationResult.device_id == device_id
            pair_scope = Pair.device_id == device_id
            img_scope = ImageRecord.device_id == device_id
        # 1. 收集并删除该归属的可视化图文件
        vrs = db.query(VerificationResult).filter(vr_scope).all()
        for vr in vrs:
            if vr.vis_path and os.path.exists(vr.vis_path):
                try:
                    os.remove(vr.vis_path)
                except OSError:
                    pass
        db.execute(VerificationResult.__table__.delete().where(vr_scope))
        print(f"[核验] 清理 {'用户' + str(user_id) if user_id is not None else '设备 ' + device_id} 的核验结果")

        # 2. 删除该归属的配对
        pairs = db.query(Pair).filter(pair_scope).all()
        db.execute(Pair.__table__.delete().where(pair_scope))
        print(f"[核验] 清理配对 {len(pairs)} 条")

        # 3. 删除该归属的上传图片文件与记录
        images = db.query(ImageRecord).filter(img_scope).all()
        for img in images:
            if os.path.exists(img.file_path):
                try:
                    os.remove(img.file_path)
                except OSError:
                    pass
        db.execute(ImageRecord.__table__.delete().where(img_scope))
        print(f"[核验] 清理上传图片 {len(images)} 张")

        db.commit()
        print("[核验] 清理完成")
    except Exception as e:
        db.rollback()
        print(f"[核验] 清空数据异常: {e}")
    finally:
        db.close()


smart_app = FastAPI(title="点位真实性核验系统")
# 统一接口响应格式：仅注册异常处理（包装中间件由主应用提供，避免双重包装）
install_errors(smart_app)


# ====== 图片 / 可视化服务接口 ======

@smart_app.get("/api/images/list")
def list_images(request: Request, db: Session = Depends(get_db)):
    """返回当前设备已上传图片，按整改图/暗访图分组。"""
    user_id, device_id = get_identity(request)
    images = db.query(ImageRecord).filter(
        scope(ImageRecord, user_id, device_id)
    ).order_by(ImageRecord.id.desc()).all()
    left = []
    right = []
    for img in images:
        entry = {
            "id": img.id,
            "filename": img.filename,
            "stored_name": img.stored_name,
            "uuid": img.uuid,
            "location": img.location_name,
            "photo_num": img.photo_num,
        }
        if img.photo_type == "整改图":
            left.append(entry)
        else:
            right.append(entry)
    return {"left_images": left, "right_images": right}


@smart_app.get("/api/images/{image_id}")
def serve_image(image_id: int, request: Request, db: Session = Depends(get_db)):
    """返回原图文件（<img> 加载，URL 携带 dev/token 校验；登录跨设备可见、游客仅本设备）。"""
    user_id, device_id = get_identity_from_img(request)
    record = db.query(ImageRecord).filter(
        ImageRecord.id == image_id, scope(ImageRecord, user_id, device_id)
    ).first()
    if not record or not os.path.exists(record.file_path):
        raise HTTPException(404, "图片不存在")
    # 禁用缓存：主键可能被 SQLite 复用，防止浏览器显示旧图
    return FileResponse(record.file_path, headers={"Cache-Control": "no-store"})


@smart_app.get("/api/visualization/{result_id}")
def serve_visualization(result_id: int, request: Request, db: Session = Depends(get_db)):
    """返回可视化图文件（<img> 加载，URL 携带 dev/token 校验；登录跨设备可见、游客仅本设备）。"""
    user_id, device_id = get_identity_from_img(request)
    vr = db.query(VerificationResult).filter(
        VerificationResult.id == result_id, scope(VerificationResult, user_id, device_id)
    ).first()
    if not vr or not vr.vis_path or not os.path.exists(vr.vis_path):
        raise HTTPException(404, "可视化图不存在")
    # 禁用缓存：主键可能被 SQLite 复用，防止浏览器显示旧图
    return FileResponse(vr.vis_path, headers={"Cache-Control": "no-store"})


@smart_app.delete("/api/images/{image_id}")
def delete_image(image_id: int, request: Request, db: Session = Depends(get_db)):
    """删除单张图片及其关联的配对和结果（仅当前设备）。"""
    user_id, device_id = get_identity(request)
    record = db.query(ImageRecord).filter(
        ImageRecord.id == image_id, scope(ImageRecord, user_id, device_id)
    ).first()
    if not record:
        raise HTTPException(404, "图片不存在")

    # 查找关联的配对（同归属）
    related_pairs = db.query(Pair).filter(
        scope(Pair, user_id, device_id),
        (Pair.left_image_id == image_id) | (Pair.right_image_id == image_id)
    ).all()

    for pair in related_pairs:
        # 删除关联的结果
        vr = db.query(VerificationResult).filter(
            VerificationResult.pair_id == pair.id
        ).first()
        if vr:
            if vr.vis_path and os.path.exists(vr.vis_path):
                try:
                    os.remove(vr.vis_path)
                except OSError:
                    pass
            db.delete(vr)
        db.delete(pair)

    # 删除图片文件
    if os.path.exists(record.file_path):
        try:
            os.remove(record.file_path)
        except OSError:
            pass

    db.delete(record)
    db.commit()
    return {"deleted": image_id}


@smart_app.get("/api/health")
def health():
    return {"status": "ok"}


@smart_app.post("/api/reset")
def reset_all(request: Request):
    """手动重置：清空当前数据（登录清 user_id、游客清 device_id）。"""
    user_id, device_id = get_identity(request)
    cleanup_all(device_id, user_id)
    return {"message": "已清空当前设备数据"}


@smart_app.get("/api/stats")
def stats(request: Request, db: Session = Depends(get_db)):
    """核验数据统计（供系统设置"历史内容清理"展示；仅当前归属）"""
    user_id, device_id = get_identity(request)
    pairs = db.query(Pair).filter(scope(Pair, user_id, device_id)).count()
    done = db.query(Pair).filter(scope(Pair, user_id, device_id), Pair.status == "done").count()
    images = db.query(ImageRecord).filter(scope(ImageRecord, user_id, device_id)).count()
    # 占用大小 = 该归属所有上传图 + 可视化图（按 DB 记录的文件路径累加）
    size = 0
    for img in db.query(ImageRecord).filter(scope(ImageRecord, user_id, device_id)).all():
        try:
            size += os.path.getsize(img.file_path)
        except OSError:
            pass
    for vr in db.query(VerificationResult).filter(scope(VerificationResult, user_id, device_id)).all():
        if vr.vis_path:
            try:
                size += os.path.getsize(vr.vis_path)
            except OSError:
                pass
    return {"pairs": pairs, "done": done, "images": images, "bytes": size}


# 静态文件（可视化图）
smart_app.mount("/static", StaticFiles(directory=str(VIS_DIR)), name="smart_static")

# 注册路由
smart_app.include_router(upload.router, prefix="/api")
smart_app.include_router(verify.router, prefix="/api")
smart_app.include_router(results.router, prefix="/api")
smart_app.include_router(export.router, prefix="/api")


# ====== 游客数据过期清理（防无主设备数据无限堆积） ======
DEVICE_EXPIRE_DAYS = 30


def _expire_old_devices() -> None:
    """删除超过 DEVICE_EXPIRE_DAYS 没有新数据的游客设备（三表最近时间判定）。"""
    cutoff = _dt.now() - timedelta(days=DEVICE_EXPIRE_DAYS)
    db = SessionLocal()
    try:
        ids = set()
        for model in (ImageRecord, Pair, VerificationResult):
            # 批次3：只清游客数据（user_id IS NULL）
            for (did,) in db.query(model.device_id).filter(
                    model.device_id != "", model.user_id.is_(None)).distinct().all():
                ids.add(did)
        for did in ids:
            last = None
            for model, col in ((ImageRecord, ImageRecord.created_at),
                               (Pair, Pair.created_at),
                               (VerificationResult, VerificationResult.created_at)):
                v = db.query(func.max(col)).filter(model.device_id == did).scalar()
                if v and (last is None or v > last):
                    last = v
            if last and last < cutoff:
                cleanup_all(did)
                print(f"[核验] 过期清理游客设备 {did[:8]}...")
    except Exception as e:
        print(f"[核验] 过期设备清理异常: {e}")
    finally:
        db.close()


def _device_expire_loop() -> None:
    """后台守护线程：每 6 小时检查一次过期游客设备。"""
    while True:
        import time
        time.sleep(6 * 3600)
        try:
            _expire_old_devices()
        except Exception:
            pass


threading.Thread(target=_device_expire_loop, daemon=True).start()
