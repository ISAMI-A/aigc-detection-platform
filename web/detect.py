"""
图像篡改检测后端（TruFor V2.4）
========================================
- 复用 ImageAuthenticityDetector 的 V2.4 检测核心（共享代码，不复制，算法更新自动跟随）
- 上传图片 → 临时落盘 → TruFor 批量检测（模型只加载一次）→ 返回判定+指标+base64图 → 用后即删
- 导出 Excel 内存生成直接下载；临时文件可一键清理
- SQLite：当前存检测记录，预留用户/人脸数据表（后续人脸识别 + 管理系统）

由 web/app.py 挂载到 /api 前缀；独立维护本功能相关代码。
"""
import io
import json
import os
import queue
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime

# 定位 web/ 目录并把检测核心（ImageAuthenticityDetector）加入 sys.path
_BASE = os.path.dirname(os.path.abspath(__file__))
_IMG_DIR = os.path.join(os.path.dirname(_BASE), "ImageAuthenticityDetector")
if _IMG_DIR not in sys.path:
    sys.path.insert(0, _IMG_DIR)

import numpy as np
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
import sqlalchemy as sa
from PIL import Image as PILImage

import trufor_pair
from config import TRUFOR_PATH, MAX_IMAGE_SIZE, TEMP_DIR
from modules.image_preprocess import preprocess
from modules.forgery_detector import TruForDetector
from trufor_pair import loc_stats, judge, judge_source, draw_analysis, make_heatmap, level_of

# 统一模型管理器：全局推理串行锁 + 显存记账（多系统模型集中管理）
from model_manager import manager, gpu_free_too_low
from auth_device import get_device_id, get_identity, get_identity_from_img, log_operation

router = APIRouter(prefix="/api", tags=["detect"])

# TruFor 推理为子进程型任务：子进程内加载模型（约 1.6GB），任务结束即释放
TRUFOR_GB = 1.6


def get_detector() -> TruForDetector:
    """TruFor 检测器懒加载单例。

    注意：TruForDetector 对象本身不加载模型（每次 predict_batch 启动独立子进程，
    模型加载发生在子进程内，约 30 秒）；单例复用的价值是统一注册与调度，
    真正的 30 秒加载若要消除，需将 TruFor 改造成常驻推理 worker（专项改造）。
    """
    return manager.get("trufor_detector", lambda: TruForDetector(TRUFOR_PATH), est_gb=0.0)

TMP_ROOT = os.path.join(_BASE, "tmp")          # 临时目录（检测后自动删除，可一键清理）
DATA_DIR = os.path.join(_BASE, "data")         # SQLite 存放
DB_PATH = os.path.join(DATA_DIR, "web.db")
# 游客设备隔离存储：上传原图 / 结果图（按设备子目录，删除记录时联动删文件）
DETECT_UPLOADS_DIR = os.path.join(DATA_DIR, "detect_uploads")
DETECT_RESULTS_DIR = os.path.join(DATA_DIR, "detect_results")
os.makedirs(TMP_ROOT, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DETECT_UPLOADS_DIR, exist_ok=True)
os.makedirs(DETECT_RESULTS_DIR, exist_ok=True)

# 启动时清理上次异常退出（进程被杀/断电）残留的临时目录
for _name in os.listdir(TMP_ROOT):
    _p = os.path.join(TMP_ROOT, _name)
    try:
        if os.path.isdir(_p):
            shutil.rmtree(_p, ignore_errors=True)
        else:
            os.remove(_p)
    except Exception:
        pass


def _cleanup_loop():
    """后台兜底清理：客户端中途断开/异常泄漏的临时目录，超过 30 分钟无写入则删除。
    正常检测路径由 finally 即时删除，此线程只兜底异常场景。
    """
    while True:
        time.sleep(120)
        now = time.time()
        try:
            for name in os.listdir(TMP_ROOT):
                p = os.path.join(TMP_ROOT, name)
                if not os.path.isdir(p):
                    continue
                # 取目录内所有文件的最新写入时间（推理期间 npz/预处理文件会持续刷新）
                mt = os.path.getmtime(p)
                for _r, _ds, _fs in os.walk(p):
                    for _f in _fs:
                        mt = max(mt, os.path.getmtime(os.path.join(_r, _f)))
                if now - mt > 1800:  # 30 分钟无写入
                    shutil.rmtree(p, ignore_errors=True)
                    print(f"[web] 已清理超时残留临时目录: {name}")
        except Exception:
            pass


threading.Thread(target=_cleanup_loop, daemon=True).start()

# 模型加载/检测串行锁：由模型管理器统一提供全局推理锁（与核验等系统互斥，防并发挤爆显存）
DETECT_LOCK = manager.infer

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")

# ============================================================
# 判定参数：默认值 = run.py 配置区校准值；前端设置弹窗可覆盖（临时生效，不写回共享配置）
# ============================================================
PRESETS = {
    "balanced": {"desc": "均衡：检出率与误报率平衡（推荐）", "threshold": 0.30},
    "strict":   {"desc": "严格：降低误报，仅高置信判定",       "threshold": 0.60},
    "loose":    {"desc": "宽松：提高检出率，宁误报不漏报",     "threshold": 0.30},
}
DEFAULT_PARAMS = {
    "preset": "", "threshold": 0.35, "threshold_high": 0.60, "threshold_med": 0.35,
    "fuse_peak": 0.7, "fuse_area": 0.05, "conf_threshold": 0.5,
    "comp_ratio": 0.005, "comp_n_spots": 16,
    "geom_rect": 0.25, "geom_solid": 0.30, "geom_min_area": 200,
    "geom_loc_thr": 0.75, "geom_line_ratio": 0.50,
    "suspect_loc_thr": 0.75, "suspect_up_thr": 0.01,
    "edge_band": 0.10, "edge_touch_ratio": 0.9, "edge_band_ratio": 0.5,
}
# 参数说明（前端 tooltip 显示）
PARAM_DESC = {
    "preset": "预设档位：默认/均衡/严格/宽松；留空则用下方自定义参数",
    "threshold": "篡改判定阈值：篡改概率 >= 该值 → 是",
    "threshold_high": "篡改等级'高'阈值：概率 >= 该值 等级=高",
    "threshold_med": "篡改等级'中'阈值：概率 >= 该值 等级=中",
    "fuse_peak": "疑似仲裁：热力图峰值阈值（概率不达标时进入仲裁）",
    "fuse_area": "疑似仲裁：热力图区域占比阈值（loc 全图均值）",
    "conf_threshold": "置信度阈值：仅作高置信面积参考列，不参与判定",
    "comp_ratio": "散点噪声降级：最大成片占比下限（低于则视为散点）",
    "comp_n_spots": "散点噪声降级：散点数量下限（>= 该值判定为噪声）",
    "geom_rect": "画笔标注a：最大连通域矩形度阈值",
    "geom_solid": "画笔标注a：最大连通域紧致度阈值",
    "geom_min_area": "画笔标注：线状连通域面积下限(px)，防小噪点误触",
    "geom_loc_thr": "画笔标注b：深红线状检测 loc 阈值（无 conf，识别画圈线）",
    "geom_line_ratio": "画笔标注b：深红区线状面积占比阈值（>= 判为画笔线）",
    "suspect_loc_thr": "疑似仲裁：深红区 loc 阈值（无 conf）",
    "suspect_up_thr": "疑似仲裁：深红区占比分界（>= 升判是，< 判不是）",
    "edge_band": "边缘误检：边缘带宽度（图像宽高比例）",
    "edge_touch_ratio": "边缘误检：贴边连通域面积占比阈值（红色直接触及边界）",
    "edge_band_ratio": "边缘误检：边缘带内红色占比阈值（排除覆盖中心的大面积篡改）",
}


def apply_params(p):
    """把前端参数覆盖到 trufor_pair 模块级变量（与 run.py 通用模式一致）"""
    t = float(p.get("threshold", DEFAULT_PARAMS["threshold"]))
    trufor_pair.THRESHOLD = t
    trufor_pair.THRESHOLD_FORGERY_HIGH = float(p.get("threshold_high", 0.60))
    trufor_pair.THRESHOLD_FORGERY_MED = float(p.get("threshold_med", 0.35))
    trufor_pair.FUSE_PEAK = float(p.get("fuse_peak", 0.7))
    trufor_pair.FUSE_AREA = float(p.get("fuse_area", 0.05))
    trufor_pair.CONF_THRESHOLD = float(p.get("conf_threshold", 0.5))
    trufor_pair.COMP_RATIO = float(p.get("comp_ratio", 0.005))
    trufor_pair.COMP_N_SPOTS = int(p.get("comp_n_spots", 16))
    trufor_pair.GEOM_RECT = float(p.get("geom_rect", 0.25))
    trufor_pair.GEOM_SOLID = float(p.get("geom_solid", 0.30))
    trufor_pair.GEOM_MIN_AREA = int(p.get("geom_min_area", 200))
    trufor_pair.GEOM_LOC_THR = float(p.get("geom_loc_thr", 0.75))
    trufor_pair.GEOM_LINE_RATIO = float(p.get("geom_line_ratio", 0.50))
    trufor_pair.SUSPECT_LOC_THR = float(p.get("suspect_loc_thr", 0.75))
    trufor_pair.SUSPECT_UP_THR = float(p.get("suspect_up_thr", 0.01))
    trufor_pair.EDGE_BAND = float(p.get("edge_band", 0.10))
    trufor_pair.EDGE_TOUCH_RATIO = float(p.get("edge_touch_ratio", 0.9))
    trufor_pair.EDGE_BAND_RATIO = float(p.get("edge_band_ratio", 0.5))


# ============================================================
# SQLite（SQLAlchemy）：检测记录表 + 上传图记录表 + 预留用户/人脸表
# ============================================================
engine = sa.create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
# 批次2：开启 WAL（提升并发读写；持久生效，启动时确认一次即可）
with engine.connect() as conn:
    conn.execute(sa.text("PRAGMA journal_mode=WAL"))
metadata = sa.MetaData()

detect_uploads = sa.Table(
    "detect_uploads", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("device_id", sa.String(64), index=True, default=""),   # 归属设备（游客隔离）
    sa.Column("user_id", sa.Integer, nullable=True),  # 归属用户（登录体系预留；NULL=游客，批次2 加列）
    sa.Column("filename", sa.String(255)),        # 原始文件名
    sa.Column("stored_name", sa.String(255)),     # 落盘文件名（uuid.ext）
    sa.Column("file_path", sa.String(500)),       # 绝对路径
    sa.Column("created_at", sa.String(32), default=lambda: datetime.now().isoformat(timespec="seconds")),
)

detect_records = sa.Table(
    "detect_records", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("device_id", sa.String(64), index=True, default=""),   # 归属设备（游客隔离）
    sa.Column("user_id", sa.Integer, nullable=True),  # 归属用户（登录体系预留；NULL=游客，批次2 加列）
    sa.Column("created_at", sa.String(32), default=lambda: datetime.now().isoformat(timespec="seconds")),
    sa.Column("file", sa.String(255)),
    sa.Column("jud", sa.String(50)),           # 模型原始判定
    sa.Column("jud_simple", sa.String(8)),     # 简判：是/不是/疑似
    sa.Column("manual_jud", sa.String(50)),    # 人工修正判定
    sa.Column("note", sa.Text, default=""),    # 人工备注
    sa.Column("score", sa.Float),
    sa.Column("level", sa.String(8)),
    sa.Column("area", sa.Float),
    sa.Column("peak", sa.Float),
    sa.Column("conf", sa.Float),
    sa.Column("src", sa.String(50)),
    sa.Column("param", sa.String(500), default=""),  # 判定参数快照
    sa.Column("orig_path", sa.String(500), default=""),    # 原图落盘路径
    sa.Column("heat_path", sa.String(500), default=""),    # 热力图落盘路径
    sa.Column("analysis_path", sa.String(500), default=""),# 分析图落盘路径
    sa.Column("thumb_path", sa.String(500), default=""),   # 缩略图落盘路径
)
# 预留（后续人脸识别/用户管理系统）
# users / faces / face_features 表在 FaceRecognition 模块化后添加

metadata.create_all(engine)


def _migrate_detect_tables():
    """启动迁移：为已存在的表补列 + 索引（create_all 不会给已有表加列/建索引）。"""
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(sa.text("PRAGMA table_info(detect_records)")).fetchall()}
    add = {
        "device_id": "VARCHAR(64) DEFAULT ''",
        "jud_simple": "VARCHAR(8) DEFAULT ''",
        "param": "VARCHAR(500) DEFAULT ''",
        "orig_path": "VARCHAR(500) DEFAULT ''",
        "heat_path": "VARCHAR(500) DEFAULT ''",
        "analysis_path": "VARCHAR(500) DEFAULT ''",
        "thumb_path": "VARCHAR(500) DEFAULT ''",
    }
    for col, ddl in add.items():
        if col not in cols:
            with engine.begin() as conn:
                conn.execute(sa.text(f"ALTER TABLE detect_records ADD COLUMN {col} {ddl}"))
                print(f"[web] 迁移：detect_records 表新增 {col} 列")
    # 批次2：登录体系数据层预留 —— detect_uploads / detect_records 补 user_id（NULL=游客）
    for tbl in ("detect_uploads", "detect_records"):
        with engine.connect() as conn:
            cols = {r[1] for r in conn.execute(sa.text(f"PRAGMA table_info({tbl})")).fetchall()}
        if "user_id" not in cols:
            with engine.begin() as conn:
                conn.execute(sa.text(f"ALTER TABLE {tbl} ADD COLUMN user_id INTEGER"))
                print(f"[web] 迁移：{tbl} 表新增 user_id 列")
    # 批次2：双轨查询索引（user_id 优先、无则 device_id，两条独立查询分支）
    with engine.begin() as conn:
        for tbl in ("detect_records", "detect_uploads"):
            conn.execute(sa.text(
                f"CREATE INDEX IF NOT EXISTS ix_{tbl}_device_created ON {tbl}(device_id, created_at)"))
            conn.execute(sa.text(
                f"CREATE INDEX IF NOT EXISTS ix_{tbl}_user_created ON {tbl}(user_id, created_at)"))


_migrate_detect_tables()


# ============================================================
# 接口
# ============================================================
@router.get("/params")
def api_params():
    """返回默认参数、预设档位、参数说明（前端设置弹窗用）"""
    return {"defaults": DEFAULT_PARAMS, "presets": PRESETS, "desc": PARAM_DESC}


def _b64(arr):
    """RGB ndarray → data URL base64"""
    import base64
    buf = io.BytesIO()
    PILImage.fromarray(arr).save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _save_b64(file_path: str, b64: str) -> None:
    """base64 dataURL → 落盘（结果图持久化，删除记录时联动删）。"""
    if not b64:
        return
    try:
        raw = b64.split(",", 1)[1] if "," in b64 else b64
        data = __import__("base64").b64decode(raw)
        with open(file_path, "wb") as f:
            f.write(data)
    except Exception as e:
        print(f"[web] 结果图落盘失败({file_path}): {e}")


def _detect_stream(items, p, device_id, user_id=None):
    """流式检测生成器：按 NDJSON 逐行推送进度/结果事件
    items: [(原始文件名, 落盘文件路径)]（上传图已在 detect_uploads 持久化）；
    结果图落盘 detect_results/<device_id>/ 并写 detect_records，返回记录 id 与图片 URL。
    事件：{"type": phase|progress|done, ...}
    """
    preset = p.get("preset", "")
    if preset in PRESETS:
        merged = dict(DEFAULT_PARAMS)
        merged.update({k: v for k, v in PRESETS[preset].items() if k != "desc"})
        merged.update(p)  # 显式传的高级参数优先
        p = merged

    def ev(obj):
        return json.dumps(obj, ensure_ascii=False) + "\n"

    with DETECT_LOCK:
        manager.begin_task("trufor", TRUFOR_GB)
        try:
            apply_params(p)
            session = os.path.join(TMP_ROOT, uuid.uuid4().hex)
            batch_dir = os.path.join(session, "batch")
            out_dir = os.path.join(session, "out")
            try:
                os.makedirs(batch_dir)
                # 1. 校验上传图（已落盘于 detect_uploads，直接引用路径）
                saved = []
                for orig_name, fp in items:
                    ext = os.path.splitext(orig_name or "")[1].lower()
                    if ext not in IMG_EXT or not fp or not os.path.exists(fp):
                        continue
                    saved.append((os.path.basename(orig_name or f"未命名{ext}"), fp))
                if not saved:
                    yield ev({"type": "done", "results": [{"file": "", "error": "没有有效的图片文件（支持 jpg/png/webp/bmp/tif）"}]})
                    return

                # 2. 预处理（统一尺寸/格式）
                yield ev({"type": "phase", "msg": "预处理图片...", "pct": 3})
                plan = []
                for orig_name, fp in saved:
                    try:
                        name = os.path.basename(preprocess(fp, MAX_IMAGE_SIZE, batch_dir))
                        plan.append((orig_name, fp, name))
                    except Exception as e:
                        plan.append((orig_name, fp, None))  # 预处理失败标记

                # 3. TruFor 批量推理（每次检测启动一个子进程、模型在子进程内只加载一次；tqdm 进度实时转发；失败自动重试一次）
                yield ev({"type": "phase", "msg": "模型加载中（首次约30秒）...", "pct": 5})
                q = queue.Queue()

                def on_progress(cur, total):
                    if cur <= 0:
                        return  # 过滤 tqdm 初始的 0/N
                    q.put({"type": "progress", "done": cur, "total": total,
                           "msg": f"推理中：第 {cur}/{total} 张"})

                def worker():
                    try:
                        trufor = get_detector()
                        results = trufor.predict_batch(batch_dir, out_dir, on_progress=on_progress)
                        q.put({"type": "_results", "data": results})
                    except Exception as e:
                        print(f"[web] 首次推理失败({e})，自动重试...")
                        try:
                            results = trufor.predict_batch(batch_dir, out_dir, on_progress=on_progress)
                            q.put({"type": "_results", "data": results})
                        except Exception as e2:
                            q.put({"type": "_error", "msg": str(e2)})

                t = threading.Thread(target=worker, daemon=True)
                t.start()
                results = None
                while results is None:
                    msg = q.get()
                    if msg["type"] == "_results":
                        results = msg["data"]
                    elif msg["type"] == "_error":
                        yield ev({"type": "done", "results": [{"file": "", "error": f"推理失败：{msg['msg']}"}]})
                        return
                    else:
                        # 推理进度映射：5% 起 80% 区间
                        msg["pct"] = 10 + round(msg["done"] / msg["total"] * 80, 1)
                        yield ev(msg)

                # 4. 逐张计算判定/指标/图像（结果图落盘 + 写记录）
                yield ev({"type": "phase", "msg": "生成结果图片...", "pct": 93})
                res_dir = os.path.join(DETECT_RESULTS_DIR, device_id)
                os.makedirs(res_dir, exist_ok=True)
                out = []
                for orig_name, fp, name in plan:
                    if name is None or name not in results:
                        out.append({"file": orig_name, "error": "预处理或推理失败"})
                        continue
                    score, loc, conf_map = results[name]
                    st = loc_stats(loc, conf_map)
                    jud = judge(score, st)
                    jud_simple = ("是" if jud and jud.startswith("是") else
                                  "不是" if jud and jud.startswith("否") else "疑似")
                    src = judge_source(jud, st, score)
                    orig_arr = np.array(PILImage.open(fp).convert("RGB"))
                    # 列表缩略图（小）
                    thumb = PILImage.fromarray(orig_arr); thumb.thumbnail((160, 160))
                    heat = make_heatmap(loc)
                    ana = draw_analysis(orig_arr, loc) if loc is not None else None
                    rid = uuid.uuid4().hex
                    # 落盘结果图（删除记录时联动删文件 → 无落盘）
                    orig_p = os.path.join(res_dir, f"{rid}_orig.jpg")
                    heat_p = os.path.join(res_dir, f"{rid}_heat.jpg")
                    ana_p = os.path.join(res_dir, f"{rid}_analysis.jpg") if ana is not None else ""
                    thumb_p = os.path.join(res_dir, f"{rid}_thumb.jpg")
                    _save_b64(orig_p, _b64(orig_arr))
                    _save_b64(heat_p, _b64(heat))
                    if ana is not None:
                        _save_b64(ana_p, _b64(ana))
                    _save_b64(thumb_p, _b64(np.array(thumb)))
                    # 写记录（登录用户归属 user_id；device_id 保留供登出回退与图片校验）
                    with engine.begin() as conn:
                        ins = conn.execute(detect_records.insert().values(
                            device_id=device_id, user_id=user_id, file=orig_name, jud=jud, jud_simple=jud_simple,
                            manual_jud="", note="", score=round(float(score), 4) if score is not None else None,
                            level=level_of(score) if score is not None else "",
                            area=round(st["area"], 4) if st else None,
                            peak=round(st["peak"], 4) if st else None,
                            conf=round(float(conf_map.mean()), 4) if conf_map is not None else None,
                            src=src or "", param=json.dumps(p, ensure_ascii=False),
                            orig_path=orig_p, heat_path=heat_p, analysis_path=ana_p, thumb_path=thumb_p,
                        ))
                        record_id = ins.lastrowid
                    out.append({
                        "record_id": record_id,
                        "file": orig_name,
                        "jud": jud, "jud_simple": jud_simple,
                        "src": src or "",
                        "score": round(float(score), 4) if score is not None else None,
                        "level": level_of(score) if score is not None else "",
                        "area": round(st["area"], 4) if st else None,
                        "peak": round(st["peak"], 4) if st else None,
                        "conf": round(float(conf_map.mean()), 4) if conf_map is not None else None,
                        # 图片由浏览器 <img> 直接加载（无法带请求头），URL 上携带 dev 供后端校验
                        "thumb": f"/api/detect/results/{record_id}/img/thumb?dev={device_id}",
                        "heat": f"/api/detect/results/{record_id}/img/heat?dev={device_id}",
                        "analysis": f"/api/detect/results/{record_id}/img/analysis?dev={device_id}",
                        "orig": f"/api/detect/results/{record_id}/img/orig?dev={device_id}",
                    })
                yield ev({"type": "done", "results": out})
            finally:
                # 用后即删。若客户端中断（关页面/刷新）时推理子进程仍在写文件，
                # Windows 下 rmtree(ignore_errors=True) 会静默删不干净：
                # 先删一次，再等推理线程结束释放句柄后补删，确保不残留。
                shutil.rmtree(session, ignore_errors=True)
                if "t" in locals():
                    t.join(timeout=300)
                    shutil.rmtree(session, ignore_errors=True)
        finally:
            manager.end_task("trufor", TRUFOR_GB)


class DetectReq(BaseModel):
    upload_ids: list[int]
    params: dict = {}


@router.post("/detect")
async def api_detect(req: DetectReq, request: Request):
    """批量检测（流式）：upload_ids 指向当前设备已上传的落盘图片。
    临时预处理 → TruFor 推理 → 判定+指标+结果图落盘+写记录 → 清理临时文件。
    """
    if not req.upload_ids:
        raise HTTPException(400, "未选择图片")
    # GPU 显存不足时阻止启动（如 Ollama 仍在占用未释放），避免叠加爆显存
    msg = gpu_free_too_low()
    if msg:
        raise HTTPException(507, msg)
    user_id, device_id = get_identity(request)
    with engine.connect() as conn:
        filt = (detect_uploads.c.user_id == user_id if user_id is not None
                else detect_uploads.c.device_id == device_id)
        rows = conn.execute(
            sa.select(detect_uploads).where(
                detect_uploads.c.id.in_(req.upload_ids),
                filt,
            )
        ).fetchall()
    items = [(r._mapping["filename"], r._mapping["file_path"]) for r in rows]
    if not items:
        raise HTTPException(400, "所选图片不存在或不属于当前设备")
    log_operation(request, "detect.run", f"{len(items)} 张图片")
    return StreamingResponse(_detect_stream(items, req.params or {}, device_id, user_id),
                             media_type="application/x-ndjson; charset=utf-8")


# ============================================================
# 游客设备隔离：上传图 / 结果记录 CRUD（删除联动物理文件 → 无落盘）
# ============================================================

class IdsPayload(BaseModel):
    ids: list[int]


class ResultUpdatePayload(BaseModel):
    record_id: int
    manual_jud: str = ""
    note: str = ""


def _row_to_result(r, device_id: str) -> dict:
    """detect_records 行 → 前端结果对象（图片为 URL，携带 dev 供 <img> 校验；
    dev 用记录自身 device_id（登录用户跨设备也能加载，B78 约定））"""
    dev = r._mapping["device_id"] or device_id
    return {
        "record_id": r._mapping["id"],
        "file": r._mapping["file"],
        "jud": r._mapping["jud"],
        "jud_simple": r._mapping["jud_simple"] or (r._mapping["jud"] or ""),
        "manual_jud": r._mapping["manual_jud"] or "",
        "note": r._mapping["note"] or "",
        "src": r._mapping["src"] or "",
        "score": r._mapping["score"],
        "level": r._mapping["level"] or "",
        "area": r._mapping["area"],
        "peak": r._mapping["peak"],
        "conf": r._mapping["conf"],
        "param": r._mapping["param"] or "",
        "created_at": r._mapping["created_at"],
        "thumb": f"/api/detect/results/{r._mapping['id']}/img/thumb?dev={dev}",
        "heat": f"/api/detect/results/{r._mapping['id']}/img/heat?dev={dev}",
        "analysis": f"/api/detect/results/{r._mapping['id']}/img/analysis?dev={dev}",
        "orig": f"/api/detect/results/{r._mapping['id']}/img/orig?dev={dev}",
    }


@router.post("/detect/upload")
async def api_upload(request: Request = None, files: list[UploadFile] = File(...)):
    """上传图片落盘（归属当前设备），返回记录（供上传列表恢复/检测引用）。

    幂等：同设备同名文件已存在时直接返回已有记录，不重复落盘（避免重复文件/相同文件名）。
    """
    user_id, device_id = get_identity(request)
    up_dir = os.path.join(DETECT_UPLOADS_DIR, device_id)
    os.makedirs(up_dir, exist_ok=True)
    saved = []
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in IMG_EXT:
            continue
        name = f.filename or ""
        # 同归属同名查重（登录按 user_id、游客按 device_id）：已存在直接复用，不重复落盘
        with engine.connect() as conn:
            filt = (detect_uploads.c.user_id == user_id if user_id is not None
                    else detect_uploads.c.device_id == device_id)
            exist = conn.execute(sa.select(detect_uploads).where(
                filt, detect_uploads.c.filename == name,
            )).first()
        if exist:
            saved.append({"id": exist._mapping["id"], "name": exist._mapping["filename"],
                          "url": f"/api/detect/uploads/{exist._mapping['id']}/img?dev={exist._mapping['device_id']}"})
            continue
        stored = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(up_dir, stored)
        data = await f.read()
        with open(path, "wb") as fh:
            fh.write(data)
        with engine.begin() as conn:
            ins = conn.execute(detect_uploads.insert().values(
                device_id=device_id, user_id=user_id, filename=name, stored_name=stored, file_path=path))
            up_id = ins.lastrowid
        saved.append({"id": up_id, "name": name,
                      "url": f"/api/detect/uploads/{up_id}/img?dev={device_id}"})
    log_operation(request, "detect.upload", f"{len(saved)} 张图片")
    return {"items": saved}


@router.get("/detect/uploads")
def api_uploads(request: Request):
    """当前设备上传列表（刷新后恢复；done=该文件是否已有检测结果）。"""
    user_id, device_id = get_identity(request)
    if user_id is not None:
        _migrate_guest_data(device_id, user_id)
    with engine.connect() as conn:
        filt = (detect_uploads.c.user_id == user_id if user_id is not None
                else detect_uploads.c.device_id == device_id)
        rows = conn.execute(sa.select(detect_uploads).where(
            filt).order_by(detect_uploads.c.id.desc())).fetchall()
        done_filt = (detect_records.c.user_id == user_id if user_id is not None
                     else detect_records.c.device_id == device_id)
        done_files = {r[0] for r in conn.execute(
            sa.select(detect_records.c.file).where(done_filt)).fetchall()}
    return {"items": [{
        "id": r._mapping["id"], "name": r._mapping["filename"],
        "url": f"/api/detect/uploads/{r._mapping['id']}/img?dev={r._mapping['device_id']}",
        "done": r._mapping["filename"] in done_files,
    } for r in rows]}


def _rmdir_if_empty(path: str) -> None:
    """设备目录为空时删除（避免删光文件后残留空文件夹）。"""
    try:
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
    except OSError:
        pass


@router.post("/detect/uploads/delete")
def api_uploads_delete(payload: IdsPayload, request: Request):
    """删除上传图片（联动物理文件，无落盘；空设备目录一并清理）。"""
    user_id, device_id = get_identity(request)
    filt = (detect_uploads.c.user_id == user_id if user_id is not None
            else detect_uploads.c.device_id == device_id)
    with engine.begin() as conn:
        rows = conn.execute(sa.select(detect_uploads).where(
            detect_uploads.c.id.in_(payload.ids), filt)).fetchall()
        for r in rows:
            if os.path.exists(r._mapping["file_path"]):
                try:
                    os.remove(r._mapping["file_path"])
                except OSError:
                    pass
        conn.execute(detect_uploads.delete().where(
            detect_uploads.c.id.in_(payload.ids), filt))
    _rmdir_if_empty(os.path.join(DETECT_UPLOADS_DIR, device_id))
    log_operation(request, "detect.delete_uploads", f"{len(rows)} 张")
    return {"deleted": len(rows)}


@router.get("/detect/uploads/{upload_id}/img")
def api_upload_img(upload_id: int, request: Request):
    """上传原图预览（<img> 加载，URL 携带 dev/token 校验；登录跨设备可见、游客仅本设备）。"""
    user_id, device_id = get_identity_from_img(request)
    filt = (detect_uploads.c.user_id == user_id if user_id is not None
            else detect_uploads.c.device_id == device_id)
    with engine.connect() as conn:
        r = conn.execute(sa.select(detect_uploads).where(
            detect_uploads.c.id == upload_id, filt)).fetchone()
    if not r or not os.path.exists(r._mapping["file_path"]):
        raise HTTPException(404, "图片不存在")
    return FileResponse(r._mapping["file_path"], headers={"Cache-Control": "no-store"})


@router.get("/detect/results")
def api_results(request: Request):
    """当前设备结果列表（新→旧）。"""
    user_id, device_id = get_identity(request)
    if user_id is not None:
        _migrate_guest_data(device_id, user_id)
    filt = (detect_records.c.user_id == user_id if user_id is not None
            else detect_records.c.device_id == device_id)
    with engine.connect() as conn:
        rows = conn.execute(sa.select(detect_records).where(
            filt).order_by(detect_records.c.id.desc())).fetchall()
    return {"items": [_row_to_result(r, device_id) for r in rows]}


@router.post("/detect/results/update")
def api_result_update(payload: ResultUpdatePayload, request: Request):
    """人工修正判定 / 备注（仅当前设备）。"""
    user_id, device_id = get_identity(request)
    filt = (detect_records.c.user_id == user_id if user_id is not None
            else detect_records.c.device_id == device_id)
    with engine.begin() as conn:
        r = conn.execute(sa.select(detect_records.c.id).where(
            detect_records.c.id == payload.record_id, filt)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")
        conn.execute(detect_records.update().where(detect_records.c.id == payload.record_id).values(
            manual_jud=payload.manual_jud, note=payload.note))
    return {"ok": True}


@router.post("/detect/results/delete")
def api_result_delete(payload: IdsPayload, request: Request):
    """删除结果记录并联动删除落盘图片（无落盘）。"""
    user_id, device_id = get_identity(request)
    filt = (detect_records.c.user_id == user_id if user_id is not None
            else detect_records.c.device_id == device_id)
    with engine.begin() as conn:
        rows = conn.execute(sa.select(detect_records).where(
            detect_records.c.id.in_(payload.ids), filt)).fetchall()
        for r in rows:
            for k in ("orig_path", "heat_path", "analysis_path", "thumb_path"):
                p = r._mapping[k]
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        conn.execute(detect_records.delete().where(
            detect_records.c.id.in_(payload.ids), filt))
    _rmdir_if_empty(os.path.join(DETECT_RESULTS_DIR, device_id))
    log_operation(request, "detect.delete_results", f"{len(rows)} 条")
    return {"deleted": len(rows)}


def _clear_device_data(device_id: str) -> None:
    """清空指定设备全部结果与上传图（联动删除文件与设备目录；供接口与过期清理共用）。"""
    with engine.begin() as conn:
        for t, keys in ((detect_records, ("orig_path", "heat_path", "analysis_path", "thumb_path")),
                        (detect_uploads, ("file_path",))):
            rows = conn.execute(sa.select(t).where(t.c.device_id == device_id)).fetchall()
            for r in rows:
                for k in keys:
                    p = r._mapping[k]
                    if p and os.path.exists(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
            conn.execute(t.delete().where(t.c.device_id == device_id))
    # 清理设备目录
    shutil.rmtree(os.path.join(DETECT_RESULTS_DIR, device_id), ignore_errors=True)
    shutil.rmtree(os.path.join(DETECT_UPLOADS_DIR, device_id), ignore_errors=True)


def _clear_user_data(user_id: int) -> None:
    """清空指定登录用户的全部结果与上传图（批次3：删除记录引用的文件，不动设备目录——设备上可能还有游客数据）。"""
    with engine.begin() as conn:
        for t, keys in ((detect_records, ("orig_path", "heat_path", "analysis_path", "thumb_path")),
                        (detect_uploads, ("file_path",))):
            rows = conn.execute(sa.select(t).where(t.c.user_id == user_id)).fetchall()
            for r in rows:
                for k in keys:
                    p = r._mapping[k]
                    if p and os.path.exists(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
            conn.execute(t.delete().where(t.c.user_id == user_id))


def _migrate_guest_data(device_id: str, user_id: int) -> None:
    """登录用户访问时，把该设备的游客记录迁移到用户名下（幂等；与 rs_verify B92 同法）。

    设备标识是浏览器级的：同一浏览器先游客后登录，历史检测/上传记录 user_id=NULL 属于该设备，
    登录后按 user_id 过滤查不到（列表空、统计 0 项、清不掉）→ 迁移后可见可清理。
    """
    if not device_id or user_id is None:
        return
    with engine.begin() as conn:
        for t in (detect_records, detect_uploads):
            conn.execute(sa.text(
                f"UPDATE {t.name} SET user_id=:u WHERE user_id IS NULL AND device_id=:d"),
                {"u": user_id, "d": device_id})


@router.post("/detect/results/clear")
def api_result_clear(request: Request):
    """清空当前设备全部结果与上传图（联动删除文件与设备目录）；登录用户先迁移本设备游客数据再清。"""
    user_id, device_id = get_identity(request)
    if user_id is not None:
        _migrate_guest_data(device_id, user_id)
        _clear_user_data(user_id)
        # 迁移后该设备数据已全部删除，设备目录（detect_results/detect_uploads/<device>）整体清理
        shutil.rmtree(os.path.join(DETECT_RESULTS_DIR, device_id), ignore_errors=True)
        shutil.rmtree(os.path.join(DETECT_UPLOADS_DIR, device_id), ignore_errors=True)
    else:
        _clear_device_data(device_id)
    log_operation(request, "detect.clear", "")
    return {"cleared": True}


# 游客数据过期清理：超 DEVICE_EXPIRE_DAYS 无活跃的游客设备数据自动删除（防无主数据无限堆积）
DEVICE_EXPIRE_DAYS = 30


def _expire_old_devices() -> None:
    """删除超过 30 天没有新数据的游客设备（detect_records/detect_uploads 最近时间判定）。"""
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=DEVICE_EXPIRE_DAYS)
    with engine.connect() as conn:
        rows = conn.execute(sa.text(
            "SELECT device_id, MAX(created_at) AS last_at FROM ("
            " SELECT device_id, created_at FROM detect_records WHERE user_id IS NULL"
            " UNION ALL"
            " SELECT device_id, created_at FROM detect_uploads WHERE user_id IS NULL"
            ") WHERE device_id <> '' GROUP BY device_id"
        )).fetchall()
    for r in rows:
        device_id, last = r[0], r[1]
        try:
            if datetime.fromisoformat(last) < cutoff:
                _clear_device_data(device_id)
                print(f"[web] 过期清理游客设备 {device_id[:8]}...")
        except (ValueError, TypeError):
            continue


def _device_expire_loop() -> None:
    """后台守护线程：每 6 小时检查一次过期游客设备。"""
    while True:
        time.sleep(6 * 3600)
        try:
            _expire_old_devices()
        except Exception as e:
            print(f"[web] 过期设备清理异常: {e}")


threading.Thread(target=_device_expire_loop, daemon=True).start()


@router.get("/detect/results/{record_id}/img/{kind}")
def api_result_img(record_id: int, kind: str, request: Request):
    """结果图服务（orig/heat/analysis/thumb；<img> 加载，URL 携带 dev/token 校验）。"""
    user_id, device_id = get_identity_from_img(request)
    filt = (detect_records.c.user_id == user_id if user_id is not None
            else detect_records.c.device_id == device_id)
    with engine.connect() as conn:
        r = conn.execute(sa.select(detect_records).where(
            detect_records.c.id == record_id, filt)).fetchone()
    if not r:
        raise HTTPException(404, "记录不存在")
    key = {"orig": "orig_path", "heat": "heat_path",
           "analysis": "analysis_path", "thumb": "thumb_path"}.get(kind)
    if not key:
        raise HTTPException(400, "未知图片类型")
    p = r._mapping[key]
    if not p or not os.path.exists(p):
        raise HTTPException(404, "图片不存在")
    return FileResponse(p, headers={"Cache-Control": "no-store"})


@router.get("/detect/stats")
def api_stats(request: Request):
    """当前设备占用统计（供系统设置"历史内容清理"展示）。"""
    user_id, device_id = get_identity(request)
    if user_id is not None:
        _migrate_guest_data(device_id, user_id)
    filt_r = (detect_records.c.user_id == user_id if user_id is not None
              else detect_records.c.device_id == device_id)
    filt_u = (detect_uploads.c.user_id == user_id if user_id is not None
              else detect_uploads.c.device_id == device_id)
    with engine.connect() as conn:
        results = len(conn.execute(sa.select(detect_records.c.id).where(filt_r)).fetchall())
        uploads = len(conn.execute(sa.select(detect_uploads.c.id).where(filt_u)).fetchall())
    size = 0
    for d in (os.path.join(DETECT_RESULTS_DIR, device_id), os.path.join(DETECT_UPLOADS_DIR, device_id)):
        if not os.path.isdir(d):
            continue
        for _r, _ds, _fs in os.walk(d):
            for _f in _fs:
                try:
                    size += os.path.getsize(os.path.join(_r, _f))
                except OSError:
                    pass
    return {"results": results, "uploads": uploads, "bytes": size}


class ExportPayload(BaseModel):
    mode: str = "brief"    # brief=简介 / detail=详细
    rows: list = []


@router.post("/export")
def api_export(payload: ExportPayload, request: Request):
    """导出 Excel（内存生成直接下载，不落盘）。
    brief=简要：列表内容（文件名/判定 + 原图/热力图两张图）；
    detail=详细：详情弹窗全部（所有指标 + 原图/热力图/分析图三张图）。
    美化：表头蓝底白字、细边框、判定结果按值着色、行列宽高随内容调整。
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.drawing.image import Image as XLImage
    import base64

    brief = payload.mode != "detail"
    wb = Workbook()
    ws = wb.active
    ws.title = "TruFor检测结果"

    if brief:
        headers = ["文件名", "判定结果", "原图", "热力图"]
        keys = ["file", "jud"]
        img_cols, img_keys = "CD", ("orig", "heat")
        col_widths = {"A": 32, "B": 12, "C": 26, "D": 26}
    else:
        headers = ["文件名", "判定结果", "模型原始判定", "判定来源", "篡改概率", "篡改等级",
                   "篡改区域占比", "篡改峰值", "置信度", "判定参数", "备注",
                   "原图", "热力图", "分析图"]
        keys = ["file", "jud", "jud_orig", "src", "score", "level", "area", "peak", "conf", "param", "note"]
        img_cols, img_keys = "LMN", ("orig", "heat", "analysis")
        col_widths = {"A": 32, "B": 12, "C": 24, "D": 26, "E": 10, "F": 10,
                      "G": 12, "H": 10, "I": 10, "J": 30, "K": 30, "L": 26, "M": 26, "N": 26}

    # 样式
    thin = Side(style="thin", color="C8D3E8")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    hdr_font = Font(bold=True, size=11, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="4472C4")
    jud_fills = {
        "是":   PatternFill("solid", fgColor="FDEAEA"),
        "不是": PatternFill("solid", fgColor="E6F7E6"),
        "疑似": PatternFill("solid", fgColor="FDF3D8"),
    }
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = hdr_font; c.fill = hdr_fill; c.border = border
        c.alignment = Alignment(horizontal="center", vertical="center")

    for i, row in enumerate(payload.rows, 2):
        for col, k in enumerate(keys, 1):
            v = row.get(k)
            c = ws.cell(row=i, column=col, value=v if v is not None else "")
            c.font = Font(size=11); c.border = border
            if col == 2:  # 判定结果列按值着色
                fill = jud_fills.get(str(v))
                if fill:
                    c.fill = fill
                c.alignment = Alignment(horizontal="center")
        # 图片：按 200px 宽等比缩放插入，行高随图自适应
        max_h = 0
        for col, key in zip(img_cols, img_keys):
            b64 = row.get(key)
            if not b64:
                continue
            try:
                raw = b64.split(",", 1)[1] if "," in b64 else b64
                data = base64.b64decode(raw)
                pil = PILImage.open(io.BytesIO(data))
                w, h = pil.size
                scale = 200 / w if w else 1
                img = XLImage(io.BytesIO(data))
                img.width = int(200)
                img.height = int(h * scale)
                ws.add_image(img, f"{col}{i}")
                max_h = max(max_h, img.height)
            except Exception as e:
                print(f"[web] 导出图片失败({key}): {e}")
        if max_h:
            ws.row_dimensions[i].height = int(max_h * 0.75) + 8
    for col, w in col_widths.items():
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from urllib.parse import quote
    log_operation(request, "detect.export", f"{len(payload.rows or [])} 条")
    fn = "TruFor检测结果.xlsx"
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename=\"TruFor_result.xlsx\"; filename*=UTF-8''{quote(fn)}"})


@router.post("/cleanup")
def api_cleanup():
    """一键清理历史临时文件（残留目录）"""
    n = 0
    for entry in os.listdir(TMP_ROOT):
        p = os.path.join(TMP_ROOT, entry)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
                n += 1
        except Exception:
            pass
    return {"cleaned": n}
