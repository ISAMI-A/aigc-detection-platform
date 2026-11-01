"""分析路由：触发 Remote_sensing 分析并保存结果。"""
import datetime
import json
import os
import shutil

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AnalysisRecord, UploadImage
from ..scope import scope
from ..services import presets, runner
from auth_device import get_identity, log_operation
from model_manager import gpu_free_too_low

router = APIRouter(prefix="/api", tags=["rs-analyze"])

_WEB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK_DIR = os.path.join(_WEB, "data", "rs_work")   # CLI 产物（标注图/临时配置），按记录清理


def _cleanup_empty_workdirs():
    """删除 rs_work 下所有空目录（标注图未生成的失败产物/历史遗留，保持目录干净）。"""
    if not os.path.isdir(WORK_DIR):
        return
    for d in os.listdir(WORK_DIR):
        p = os.path.join(WORK_DIR, d)
        if os.path.isdir(p) and d.startswith("rec_"):
            try:
                os.rmdir(p)  # 只删空目录（非空抛 OSError 忽略）
            except OSError:
                pass


class AnalyzeReq(BaseModel):
    before_id: int | None = None
    after_id: int | None = None
    image_id: int | None = None
    scenario: str = "detect"


def _llm_config(db: Session, user_id, device_id: str = "") -> dict:
    """当前归属激活预设的 LLM 配置（api_key 已解密）。"""
    cfg = presets.get_active(db, user_id, device_id) or {}
    return {
        "api": cfg.get("api", "openai"),
        "base_url": cfg.get("base_url", ""),
        "api_key": cfg.get("api_key", ""),
        "model_name": cfg.get("model_name", ""),
        "local_model_name": cfg.get("local_model_name", ""),
        "max_tokens": int(cfg.get("max_tokens", 2000) or 2000),
        "temperature": float(cfg.get("temperature", 0.2) or 0.2),
        "model_path": cfg.get("local_model_path", ""),
        "device": cfg.get("local_device", "cuda"),
    }


def _model_used(cfg: dict) -> str:
    """本次核验实际使用的模型名：本地模型用 local_model_name，云端用 model_name。"""
    if cfg.get("api") == "local":
        return (cfg.get("local_model_name") or "").strip()
    return (cfg.get("model_name") or "").strip()


def _run_analysis(before_path: str, after_path: str, scenario: str, db: Session, user_id, device_id: str = "") -> dict:
    """执行一次分析（子进程调用 CLI），独立工作目录便于按记录清理。

    分析失败/异常时删除本次工作目录，避免失败产物（标注图等）落盘残留。
    """
    work_dir = os.path.join(WORK_DIR, f"rec_{uuid4_hex()}")
    os.makedirs(work_dir, exist_ok=True)
    try:
        out = runner.run_analysis(
            before_path=before_path,
            after_path=after_path,
            scenario=scenario,
            config=_llm_config(db, user_id, device_id),
            work_dir=work_dir,
        )
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(500, f"分析调用失败: {e}")
    if out.get("status") != "ok":
        # 分析失败：清理本次产物目录，不残留
        shutil.rmtree(work_dir, ignore_errors=True)
        return out
    return out


def _run_single_analysis(image_path: str, db: Session, user_id, device_id: str = "") -> dict:
    """执行一次单图检测（classify 四乱核验），独立工作目录便于按记录清理。"""
    work_dir = os.path.join(WORK_DIR, f"rec_{uuid4_hex()}")
    os.makedirs(work_dir, exist_ok=True)
    try:
        out = runner.run_single_analysis(
            image_path=image_path,
            config=_llm_config(db, user_id, device_id),
            work_dir=work_dir,
        )
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(500, f"分析调用失败: {e}")
    if out.get("status") != "ok":
        shutil.rmtree(work_dir, ignore_errors=True)
        return out
    return out


@router.post("/analyze")
def analyze(req: AnalyzeReq, request: Request, db: Session = Depends(get_db)):
    """分析图片（阻塞，LLM 调用约 30-60s；仅当前设备）。
    detect/verify 为双图核验，classify（四乱核验）为单图检测。
    """
    if req.scenario not in ("detect", "verify", "classify"):
        raise HTTPException(400, "scenario 必须为 detect / verify / classify")
    # GPU 显存不足时阻止启动（如点位核验模型/其他占用未释放），避免叠加爆显存
    msg = gpu_free_too_low()
    if msg:
        raise HTTPException(507, msg)

    user_id, device_id = get_identity(request)

    # 四乱核验：单图检测
    if req.scenario == "classify":
        if not req.image_id:
            raise HTTPException(400, "四乱核验需要 image_id")
        img = db.query(UploadImage).filter(
            UploadImage.id == req.image_id, scope(UploadImage, user_id, device_id)
        ).first()
        if not img or not os.path.exists(img.file_path):
            raise HTTPException(404, "图片不存在或已丢失，请重新上传")
        out = _run_single_analysis(img.file_path, db, user_id, device_id)
        if out.get("status") != "ok":
            raise HTTPException(502, out.get("error", "分析失败"))
        result = out.get("result", {})
        record = AnalysisRecord(
            device_id=device_id,
            user_id=user_id,
            scenario="classify",
            before_file=img.filename,
            after_file="",
            before_path=img.file_path,
            after_path="",
            result_json=json.dumps(result, ensure_ascii=False),
            model_used=out.get("model") or _model_used(_llm_config(db, user_id, device_id)),
            conclusion=out.get("conclusion", ""),
            confidence="",
            annotated_image=out.get("annotated_image", ""),
            excel_path=out.get("excel_path", ""),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        log_operation(request, "rs.analyze", f"record#{record.id}")
        _cleanup_empty_workdirs()
        return record_to_dict(record)

    # detect/verify：双图核验
    before = db.query(UploadImage).filter(
        UploadImage.id == req.before_id, scope(UploadImage, user_id, device_id)
    ).first()
    after = db.query(UploadImage).filter(
        UploadImage.id == req.after_id, scope(UploadImage, user_id, device_id)
    ).first()
    if not before or not after:
        raise HTTPException(404, "图片不存在，请重新上传")
    if not os.path.exists(before.file_path) or not os.path.exists(after.file_path):
        raise HTTPException(404, "图片文件已丢失，请重新上传")

    out = _run_analysis(before.file_path, after.file_path, req.scenario, db, user_id, device_id)

    if out.get("status") != "ok":
        raise HTTPException(502, out.get("error", "分析失败"))

    result = out.get("result", {})
    annotated = out.get("annotated_image", "")
    # 标注图默认存 CLI 工作目录；复制到 uploads 可稳定保留（记录清理时连同工作目录删除）
    record = AnalysisRecord(
        device_id=device_id,
        user_id=user_id,
        scenario=req.scenario,
        before_file=before.filename,
        after_file=after.filename,
        before_path=before.file_path,
        after_path=after.file_path,
        result_json=json.dumps(result, ensure_ascii=False),
        model_used=out.get("model") or _model_used(_llm_config(db, user_id, device_id)),
        conclusion=out.get("conclusion", ""),
        confidence=str(result.get("confidence", "")) if result.get("confidence") is not None else "",
        annotated_image=annotated,
        excel_path=out.get("excel_path", ""),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    log_operation(request, "rs.analyze", f"record#{record.id}")
    _cleanup_empty_workdirs()
    return record_to_dict(record)


@router.post("/analyze/{record_id}/rerun")
def rerun_analysis(record_id: int, request: Request, db: Session = Depends(get_db)):
    """重新核验单条结果：用原图重新分析并覆盖该记录（结果列表操作列"重新核验"；仅当前设备）。"""
    user_id, device_id = get_identity(request)
    rec = db.query(AnalysisRecord).filter(
        AnalysisRecord.id == record_id, scope(AnalysisRecord, user_id, device_id)
    ).first()
    if not rec:
        raise HTTPException(404, "记录不存在")
    old_ann = rec.annotated_image or ""
    old_dir = os.path.dirname(old_ann) if old_ann else ""

    if rec.scenario == "classify":
        if not os.path.exists(rec.before_path):
            raise HTTPException(404, "原图文件已丢失，无法重新核验")
        out = _run_single_analysis(rec.before_path, db, user_id, device_id)
    else:
        if not os.path.exists(rec.before_path) or not os.path.exists(rec.after_path):
            raise HTTPException(404, "原图文件已丢失，无法重新核验")
        out = _run_analysis(rec.before_path, rec.after_path, rec.scenario or "detect", db, user_id, device_id)
    if out.get("status") != "ok":
        raise HTTPException(502, out.get("error", "分析失败"))

    result = out.get("result", {})
    rec.result_json = json.dumps(result, ensure_ascii=False)
    rec.model_used = out.get("model") or _model_used(_llm_config(db, user_id, device_id))
    rec.conclusion = out.get("conclusion", "")
    rec.confidence = str(result.get("confidence", "")) if result.get("confidence") is not None else ""
    rec.annotated_image = out.get("annotated_image", "")
    rec.created_at = datetime.datetime.now()
    db.commit()
    db.refresh(rec)

    # 旧 CLI 产物目录（旧标注图）不再被引用则删除，避免重复落盘
    if old_dir and old_dir != os.path.dirname(rec.annotated_image or ""):
        shutil.rmtree(old_dir, ignore_errors=True)

    # 清理残留的空 rec_ 工作目录（覆盖失败/历史遗留的产物目录）
    _cleanup_empty_workdirs()

    return record_to_dict(rec)


def record_to_dict(r: AnalysisRecord) -> dict:
    return {
        "id": r.id,
        "scenario": r.scenario,
        "before_file": r.before_file,
        "after_file": r.after_file,
        "result": json.loads(r.result_json or "{}"),
        "model_used": r.model_used or "",
        "conclusion": r.conclusion,
        "confidence": r.confidence,
        "annotated_image": r.annotated_image,
        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
    }


def uuid4_hex():
    import uuid
    return uuid.uuid4().hex
