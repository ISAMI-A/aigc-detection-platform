"""功能页面设置路由（前端功能页右上角圆形按钮打开）。

预设平台配置存数据库（rs_presets，非写死代码），支持增删改查与激活切换；
模型名称由用户手动输入，保存到预设的 model_name 字段。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import presets as presets_svc
from ..services import runner
from auth_device import get_identity

router = APIRouter(prefix="/api", tags=["rs-settings"])


def _migrate_guest_data(db: Session, user_id: int, device_id: str) -> None:
    """登录时将该设备的游客数据迁移到登录用户名下（幂等，B92 修复）。

    B88 的 _migrate 曾每次启动将 user_id=1 重置为 NULL，导致登录用户保存的
    API Key / 模型配置全部回退为游客归属，登录后查不到。
    此函数在登录用户访问时，把该设备的游客记录（user_id=NULL）迁移回用户名下。
    """
    from ..models import Preset
    moved = 0
    for p in db.query(Preset).filter(
        Preset.user_id.is_(None), Preset.device_id == device_id
    ).all():
        p.user_id = user_id
        moved += 1
    if moved:
        db.commit()


def _ensure_device(db: Session, user_id, device_id: str) -> None:
    """确保当前归属的默认预设存在 + 登录时迁移游客数据。"""
    if user_id is None and not device_id:
        return
    if user_id is not None and device_id:
        _migrate_guest_data(db, user_id, device_id)
    presets_svc.ensure_default_presets(db, user_id, device_id)
    presets_svc.reconcile_presets(db, user_id, device_id)


class PresetPayload(BaseModel):
    id: int | None = None            # 有 id=更新，无 id=新增
    name: str | None = None
    api: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    local_model_name: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    local_model_path: str | None = None
    local_device: str | None = None


class SettingsPayload(BaseModel):
    api: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    local_model_name: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    local_model_path: str | None = None
    local_device: str | None = None


# ==================== 预设平台（数据库存储，按用户隔离） ====================

@router.get("/presets")
def get_presets(request: Request, db: Session = Depends(get_db)):
    """预设列表 + 当前激活预设 id（仅当前设备）。"""
    user_id, device_id = get_identity(request)
    _ensure_device(db, user_id, device_id)
    presets = presets_svc.list_presets(db, user_id, device_id)
    active = presets_svc.get_active(db, user_id, device_id)
    return {"presets": presets, "active_id": active["id"] if active else None}


@router.post("/presets")
def create_preset(payload: PresetPayload, request: Request, db: Session = Depends(get_db)):
    """新增预设（同设备同名查重；首个自动激活）。"""
    user_id, device_id = get_identity(request)
    data = payload.model_dump(exclude_none=True)
    data.pop("id", None)
    try:
        return presets_svc.create_preset(db, data, user_id, device_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/presets/{preset_id}")
def update_preset(preset_id: int, payload: PresetPayload, request: Request, db: Session = Depends(get_db)):
    """更新预设（独立保存，不影响其他预设/其他设备）。"""
    user_id, device_id = get_identity(request)
    data = payload.model_dump(exclude_none=True)
    data.pop("id", None)
    try:
        return presets_svc.update_preset(db, preset_id, data, user_id, device_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: int, request: Request, db: Session = Depends(get_db)):
    """删除预设（删除激活预设后自动激活该设备第一个）。"""
    presets_svc.delete_preset(db, preset_id, *get_identity(request))
    return {"deleted": preset_id}


@router.post("/presets/{preset_id}/activate")
def activate_preset(preset_id: int, request: Request, db: Session = Depends(get_db)):
    """激活预设（核验分析使用当前设备激活预设）。"""
    try:
        return presets_svc.activate_preset(db, preset_id, *get_identity(request))
    except ValueError as e:
        raise HTTPException(404, str(e))


# ==================== 设置（当前激活预设 + 模型） ====================

@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db)):
    """当前设备激活预设完整配置 + 预设列表 + 静态兜底模型名。"""
    user_id, device_id = get_identity(request)
    _ensure_device(db, user_id, device_id)
    active = presets_svc.get_active(db, user_id, device_id) or {}
    return {
        "preset": active,
        "presets": presets_svc.list_presets(db, user_id, device_id),
        "common_models": runner.load_common_models(),
    }


@router.post("/settings")
def save_settings(payload: SettingsPayload, request: Request, db: Session = Depends(get_db)):
    """更新当前设备激活预设（api_key 加密落库，不影响其他预设/设备）。"""
    user_id, device_id = get_identity(request)
    active = presets_svc.get_active(db, user_id, device_id)
    if not active:
        raise HTTPException(400, "尚无预设，请先添加模型")
    data = payload.model_dump(exclude_none=True)
    return presets_svc.update_preset(db, active["id"], data, user_id, device_id)


@router.get("/local/models")
def get_local_models():
    """手动刷新本地 Ollama 已安装模型列表（功能设置"本地模型"页点击按钮才调用，
    避免打开设置/保存时每次都实时请求 Ollama 拖慢页面）。"""
    return {"models": runner.load_local_models()}
