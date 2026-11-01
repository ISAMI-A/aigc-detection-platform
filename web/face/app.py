"""人脸识别子系统（FastAPI 子应用）。

由主应用挂载到 /face 前缀下，内部路由保持 /api/*，最终访问路径为 /face/api/*。
独立 SQLite（web/data/face.db）与存储目录（face_uploads/face_thumbs）；
人脸库（faces.db + thumbs/）在 FaceRecognition 模块内，全局共享。
"""

import os
import threading
from datetime import datetime as _dt, timedelta

from fastapi import FastAPI, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import Base, engine, get_db, SessionLocal
from .models import FaceUpload, FaceResult
from .routers import upload, recognize, results, library, auth_face
from .scope import scope
from .services import engine as face_engine_svc
from auth_device import get_identity
from api_envelope import install_errors

# 存储目录：web/data/face_uploads（上传图）、web/data/face_thumbs（识别结果人脸图）
_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_WEB, "data")
os.makedirs(os.path.join(DATA_DIR, "face_uploads"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "face_thumbs"), exist_ok=True)

# 先创建表
Base.metadata.create_all(bind=engine)

# 启动迁移：为已存在的表补 device_id/user_id 列（create_all 不会给已有表加列）
with engine.connect() as conn:
    from sqlalchemy import text
    for tbl in ("face_uploads", "face_results"):
        cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({tbl})")).fetchall()}
        if "device_id" not in cols:
            conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN device_id VARCHAR DEFAULT ''"))
        if "user_id" not in cols:
            conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN user_id INTEGER"))
with engine.begin() as conn:
    for tbl in ("face_uploads", "face_results"):
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_face_{tbl}_device ON {tbl}(device_id, created_at)"))
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_face_{tbl}_user ON {tbl}(user_id, created_at)"))


def cleanup_all(device_id: str = "", user_id=None):
    """清空指定归属的识别数据（登录按 user_id、游客按 device_id；联动物理文件）。

    供 /api/reset 与 admin 清空接口、游客过期清理调用；不动全局人脸库。
    """
    db = SessionLocal()
    try:
        if user_id is not None:
            r_scope, u_scope = FaceResult.user_id == user_id, FaceUpload.user_id == user_id
        else:
            r_scope, u_scope = FaceResult.device_id == device_id, FaceUpload.device_id == device_id
        for r in db.query(FaceResult).filter(r_scope).all():
            if r.thumb_path and os.path.exists(r.thumb_path):
                try:
                    os.remove(r.thumb_path)
                except OSError:
                    pass
        db.query(FaceResult).filter(r_scope).delete(synchronize_session=False)
        for u in db.query(FaceUpload).filter(u_scope).all():
            if os.path.exists(u.file_path):
                try:
                    os.remove(u.file_path)
                except OSError:
                    pass
        db.query(FaceUpload).filter(u_scope).delete(synchronize_session=False)
        db.commit()
        print(f"[人脸] 清理 {'用户 ' + str(user_id) if user_id is not None else '设备 ' + device_id} 的识别数据")
    except Exception as e:
        db.rollback()
        print(f"[人脸] 清空数据异常: {e}")
    finally:
        db.close()


def cleanup_library() -> int:
    """清空全局人脸库（faces.db 全部记录 + 样本照目录）。

    admin「清空配置数据 / 清空全部数据」调用（B 口径：人脸库属配置级数据）。
    返回删除的记录条数。
    """
    try:
        import shutil
        from .services import engine
        fdb = engine.face_db()
        n = fdb.clear()
        if os.path.isdir(engine.LIB_THUMB_DIR):
            shutil.rmtree(engine.LIB_THUMB_DIR, ignore_errors=True)
        print(f"[人脸] 已清空全局人脸库（{n} 条记录）")
        return n
    except Exception as e:
        print(f"[人脸] 清空人脸库异常: {e}")
        return 0


face_app = FastAPI(title="人脸识别系统")
install_errors(face_app)


@face_app.get("/api/health")
def health():
    return {"status": "ok"}


@face_app.post("/api/reset")
def reset_all(request: Request):
    """手动重置：清空当前归属识别数据（上传图+结果；不动人脸库）。"""
    user_id, device_id = get_identity(request)
    cleanup_all(device_id, user_id)
    return {"message": "已清空当前识别数据"}


@face_app.get("/api/stats")
def stats(request: Request, db: Session = Depends(get_db)):
    """人脸识别数据统计（系统设置展示；仅当前归属 + 全局人脸库概况）。"""
    user_id, device_id = get_identity(request)
    uploads = db.query(FaceUpload).filter(scope(FaceUpload, user_id, device_id)).count()
    results = db.query(FaceResult).filter(scope(FaceResult, user_id, device_id)).count()
    try:
        fdb = face_engine_svc.face_db()
        lib = {"records": fdb.count(), "persons": fdb.count_persons()}
    except Exception:
        lib = {"records": 0, "persons": 0}
    return {"uploads": uploads, "results": results, "library": lib}


# 注册路由
face_app.include_router(upload.router, prefix="/api")
face_app.include_router(recognize.router, prefix="/api")
face_app.include_router(results.router, prefix="/api")
face_app.include_router(library.router, prefix="/api")
face_app.include_router(auth_face.router, prefix="/api")


# ====== 游客数据过期清理（30 天无活跃，与 detect/smart/rs 同口径） ======
DEVICE_EXPIRE_DAYS = 30


def _expire_old_devices() -> None:
    cutoff = _dt.now() - timedelta(days=DEVICE_EXPIRE_DAYS)
    db = SessionLocal()
    try:
        ids = set()
        for model in (FaceUpload, FaceResult):
            for (did,) in db.query(model.device_id).filter(
                    model.device_id != "", model.user_id.is_(None)).distinct().all():
                ids.add(did)
        for did in ids:
            last = None
            for model, col in ((FaceUpload, FaceUpload.created_at),
                               (FaceResult, FaceResult.created_at)):
                v = db.query(func.max(col)).filter(model.device_id == did).scalar()
                if v and (last is None or v > last):
                    last = v
            if last and last < cutoff:
                cleanup_all(did)
                print(f"[人脸] 过期清理游客设备 {did[:8]}...")
    except Exception as e:
        print(f"[人脸] 过期设备清理异常: {e}")
    finally:
        db.close()


def _device_expire_loop() -> None:
    import time
    while True:
        time.sleep(6 * 3600)
        try:
            _expire_old_devices()
        except Exception:
            pass


threading.Thread(target=_device_expire_loop, daemon=True).start()
