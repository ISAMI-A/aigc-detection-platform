"""遥感变化核验子系统（FastAPI 子应用）。

由主应用挂载到 /rsverify 前缀下，内部路由保持 /api/*，最终访问路径为 /rsverify/api/*。
独立 SQLite（web/data/rs_verify.db）与存储目录，与检测/核验系统互不干扰。
算法能力通过 Remote_sensing/web_bridge.py 子进程调用，Remote_sensing 更新后自动跟随。
"""
import os
import threading
from datetime import datetime as _dt, timedelta

from fastapi import FastAPI, Request

from .database import Base, engine, SessionLocal
from .models import AnalysisRecord, UploadImage
from .routers import analyze, export, results, settings, upload
from auth_device import get_device_id, get_identity, log_operation
from api_envelope import install_errors

# 存储目录：web/data/rs_uploads（上传图）、web/data/rs_work（CLI 产物）
_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_WEB, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "rs_uploads")
WORK_DIR = os.path.join(DATA_DIR, "rs_work")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)


def _migrate(engine):
    """数据库结构迁移 + 用户维度初始化（幂等，启动时执行）。

    - rs_presets：无 user_id 时加列（默认游客 1）；无 device_id 时加列（默认空串）
    - rs_images / rs_records：无 device_id 时加列（默认空串）
    - rs_images：无 scenario 时加列（默认 detect，按场景隔离上传图片）
    - rs_users：建表 + 确保游客用户存在
    - 内置默认预设（DeepSeek/Qwen/ChatGPT）写入数据库（按 name 查重）
    - 废弃表 rs_models / rs_settings 启动时自动删除
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "rs_presets" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("rs_presets")}
        if "user_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE rs_presets ADD COLUMN user_id INTEGER DEFAULT 1"))
        if "device_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE rs_presets ADD COLUMN device_id VARCHAR(64) DEFAULT ''"))
        if "local_model_name" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE rs_presets ADD COLUMN local_model_name VARCHAR(255) DEFAULT ''"))
    if "rs_records" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("rs_records")}
        if "model_used" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE rs_records ADD COLUMN model_used VARCHAR(255) DEFAULT ''"))
        if "device_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE rs_records ADD COLUMN device_id VARCHAR(64) DEFAULT ''"))
    if "rs_images" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("rs_images")}
        if "device_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE rs_images ADD COLUMN device_id VARCHAR(64) DEFAULT ''"))
        if "scenario" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE rs_images ADD COLUMN scenario VARCHAR(20) DEFAULT 'detect'"))
        # 存量修正：position=single 的记录此前因 B96（scenario 未收 Form）全存成 detect，
        # 四乱场景是唯一用 single 的，按 position 归位到 classify（幂等：条件已精确）
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE rs_images SET scenario='classify' WHERE position='single' AND scenario='detect'"))

    # 建全部表（rs_users / 其余）
    Base.metadata.create_all(bind=engine)

    # 批次2：登录体系数据层预留 —— rs_images / rs_records 补 user_id（NULL=游客）+ 双轨查询索引
    with engine.begin() as conn:
        for tbl in ("rs_images", "rs_records"):
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({tbl})")).fetchall()}
            if "user_id" not in cols:
                conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN user_id INTEGER"))
                print(f"[遥感核验] 迁移：{tbl} 表新增 user_id 列")
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_rs_{tbl}_device_created ON {tbl}(device_id, created_at)"))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_rs_{tbl}_user_created ON {tbl}(user_id, created_at)"))

    # 废弃表清理：rs_models（已删除"从API获取模型"功能）、rs_settings（已由 rs_presets 取代）
    with engine.begin() as conn:
        for tbl in ("rs_models", "rs_models_old", "rs_settings"):
            if insp.has_table(tbl):
                conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))

    # 批次3：B88 旧数据清理已在前序迁移中完成（default=None 后新游客预设不再误写 user_id=1）；
    # 登录体系后 user_id=1 为真实登录用户，无条件重置为 NULL 会导致登录用户配置每次重启丢失（B92）。


_migrate(engine)


def cleanup_all(device_id: str = "", user_id=None):
    """清空指定数据（批次3：登录按 user_id、游客按 device_id）。

    只删除归属记录对应的物理文件（上传图/标注图/工作目录），不 rmtree 整个目录。
    """
    db = SessionLocal()
    try:
        if user_id is not None:
            rec_scope = AnalysisRecord.user_id == user_id
            img_scope = UploadImage.user_id == user_id
        else:
            rec_scope = AnalysisRecord.device_id == device_id
            img_scope = UploadImage.device_id == device_id
        records = db.query(AnalysisRecord).filter(rec_scope).all()
        for r in records:
            results._delete_record_files(r)
            db.delete(r)
            db.flush()
            results._remove_orphan_upload_image(db, r.before_path)
            results._remove_orphan_upload_image(db, r.after_path)
        # 未被记录引用的本归属上传图一并删除
        for img in db.query(UploadImage).filter(img_scope).all():
            if os.path.exists(img.file_path):
                try:
                    os.remove(img.file_path)
                except OSError:
                    pass
            db.delete(img)
        db.commit()
        # 清理残留的空工作目录（标注图已删但 rec_xxx 目录可能残留）
        _cleanup_empty_workdirs()
        print(f"[遥感核验] {'用户 ' + str(user_id) if user_id is not None else '设备 ' + device_id} 数据已清空")
    except Exception as e:
        db.rollback()
        print(f"[遥感核验] 清空异常: {e}")
    finally:
        db.close()


def _cleanup_empty_workdirs():
    """删除 rs_work 下所有空目录（rec_xxx 工作目录内容已由 _delete_record_files 删除）。"""
    from .routers.results import WORK_DIR
    if not os.path.isdir(WORK_DIR):
        return
    for d in os.listdir(WORK_DIR):
        p = os.path.join(WORK_DIR, d)
        if os.path.isdir(p) and d.startswith("rec_"):
            try:
                os.rmdir(p)  # 只删空目录
            except OSError:
                pass


rs_app = FastAPI(title="遥感变化核验系统")
# 统一接口响应格式：仅注册异常处理（包装中间件由主应用提供，避免双重包装）
install_errors(rs_app)


@rs_app.get("/api/health")
def health():
    return {"status": "ok"}


@rs_app.post("/api/reset")
def reset_all(request: Request):
    user_id, device_id = get_identity(request)
    cleanup_all(device_id, user_id)
    log_operation(request, "rs.clear", "")
    return {"message": "已清空当前设备数据"}


rs_app.include_router(upload.router)
rs_app.include_router(analyze.router)
rs_app.include_router(results.router)
rs_app.include_router(settings.router)
rs_app.include_router(export.router)


# ====== 游客数据过期清理（防无主设备数据无限堆积） ======
DEVICE_EXPIRE_DAYS = 30


def _expire_old_devices() -> None:
    """删除超过 DEVICE_EXPIRE_DAYS 没有新数据的游客设备（rs_images/rs_records 最近时间判定）。"""
    from sqlalchemy import func
    cutoff = _dt.now() - timedelta(days=DEVICE_EXPIRE_DAYS)
    db = SessionLocal()
    try:
        ids = set()
        for model in (UploadImage, AnalysisRecord):
            # 批次3：只清游客数据（user_id IS NULL）
            for (did,) in db.query(model.device_id).filter(
                    model.device_id != "", model.user_id.is_(None)).distinct().all():
                ids.add(did)
        for did in ids:
            last = None
            for model, col in ((UploadImage, UploadImage.created_at),
                               (AnalysisRecord, AnalysisRecord.created_at)):
                v = db.query(func.max(col)).filter(model.device_id == did).scalar()
                if v and (last is None or v > last):
                    last = v
            if last and last < cutoff:
                cleanup_all(did)
                print(f"[遥感核验] 过期清理游客设备 {did[:8]}...")
    except Exception as e:
        print(f"[遥感核验] 过期设备清理异常: {e}")
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
