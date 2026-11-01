"""预设平台配置读写（按用户隔离，数据库存储；api_key AES 加密）。

预设 = 一组完整 LLM 配置（名称 + api/base_url/api_key/模型/参数），
支持增删改查与激活切换；当前生效预设（is_active=1）供 analyze 使用。
批次3 登录体系后：登录用户预设按 user_id（跨设备共享）；游客预设 user_id=NULL + device_id。
"""
import sqlalchemy as sa
from sqlalchemy.orm import Session

from ..models import Preset, User
from .crypto import decrypt, encrypt

# 游客不再用 rs_users：游客预设 user_id=NULL（登录体系后统一，废弃 GUEST_USER_ID=1）
GUEST_USER_ID = None


def _scope(m, user_id, device_id):
    """预设归属过滤：登录（user_id 非空）按 user_id 跨设备共享；游客按 user_id IS NULL + device_id。"""
    if user_id is not None:
        return m.user_id == user_id
    return sa.and_(m.user_id.is_(None), m.device_id == device_id)

# 内置默认预设（提前写进数据库，用户无需手动添加；按 name 查重，已存在不重复插入）
DEFAULT_PRESETS = [
    {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model_name": "deepseek-v4-flash",
    },
    {
        "name": "Qwen",
        "base_url": "https://ws-r94qb6xvlmoz944x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "model_name": "qwen-vl-plus",
    },
    {
        "name": "ChatGPT",
        "base_url": "https://api.openai.com/v1",
        "model_name": "gpt-4o",
    },
]


def ensure_user(db: Session, user_id: int = GUEST_USER_ID) -> int:
    """确保用户存在（游客自动创建），返回 user_id。"""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        db.add(User(id=user_id, username=f"user_{user_id}"))
        db.commit()
    return user_id


def _to_dict(p: Preset) -> dict:
    """预设 → dict（api_key 解密返回，供前端编辑展示）。"""
    return {
        "id": p.id,
        "user_id": p.user_id,
        "name": p.name,
        "api": p.api or "openai",
        "base_url": p.base_url or "",
        "api_key": decrypt(p.api_key or ""),
        "model_name": p.model_name or "",
        "local_model_name": p.local_model_name or "",
        "max_tokens": p.max_tokens or 2000,
        "temperature": p.temperature if p.temperature is not None else 0.2,
        "local_model_path": p.local_model_path or "",
        "local_device": p.local_device or "cuda",
        "is_active": bool(p.is_active),
    }


def list_presets(db: Session, user_id: int = GUEST_USER_ID, device_id: str = "") -> list:
    return [_to_dict(p) for p in db.query(Preset)
            .filter(_scope(Preset, user_id, device_id))
            .order_by(Preset.id).all()]


def get_active(db: Session, user_id: int = GUEST_USER_ID, device_id: str = "") -> dict | None:
    """当前生效预设（is_active=1）；无激活时取该用户该设备第一个。"""
    p = db.query(Preset).filter(
        _scope(Preset, user_id, device_id), Preset.is_active == 1
    ).first() or db.query(Preset).filter(
        _scope(Preset, user_id, device_id)
    ).order_by(Preset.id).first()
    return _to_dict(p) if p else None


def create_preset(db: Session, data: dict, user_id: int = GUEST_USER_ID, device_id: str = "") -> dict:
    """新增预设；同用户同设备同名查重；该用户该设备首个预设自动激活。"""
    name = (data.get("name") or "").strip() or "未命名"
    dup = db.query(Preset).filter(
        _scope(Preset, user_id, device_id), Preset.name == name
    ).first()
    if dup:
        raise ValueError(f"预设「{name}」已存在，请勿重复添加")
    row = Preset(user_id=user_id, device_id=device_id, name=name)
    _apply(row, data)
    db.add(row)
    db.flush()
    if db.query(Preset).filter(
        _scope(Preset, user_id, device_id)
    ).count() == 1:
        row.is_active = 1
    db.commit()
    db.refresh(row)
    return _to_dict(row)


def update_preset(db: Session, preset_id: int, data: dict, user_id: int = GUEST_USER_ID, device_id: str = "") -> dict:
    """更新预设（参数与 api_key 独立保存，不影响其他预设/其他用户/其他设备）。"""
    row = _get_owned(db, preset_id, user_id, device_id)
    if not row:
        raise ValueError(f"预设不存在: {preset_id}")
    _apply(row, data)
    db.commit()
    db.refresh(row)
    return _to_dict(row)


def delete_preset(db: Session, preset_id: int, user_id: int = GUEST_USER_ID, device_id: str = ""):
    """删除预设；若删除的是激活预设，自动激活该用户该设备剩余第一个。"""
    row = _get_owned(db, preset_id, user_id, device_id)
    if not row:
        return
    was_active = row.is_active == 1
    db.delete(row)
    db.commit()
    if was_active:
        first = db.query(Preset).filter(
            _scope(Preset, user_id, device_id)
        ).order_by(Preset.id).first()
        if first:
            first.is_active = 1
            db.commit()


def activate_preset(db: Session, preset_id: int, user_id: int = GUEST_USER_ID, device_id: str = "") -> dict:
    """激活指定预设（该用户该设备其余全部置为未激活）。"""
    db.query(Preset).filter(
        _scope(Preset, user_id, device_id)
    ).update({Preset.is_active: 0})
    row = _get_owned(db, preset_id, user_id, device_id)
    if not row:
        raise ValueError(f"预设不存在: {preset_id}")
    row.is_active = 1
    db.commit()
    return _to_dict(row)


def ensure_default_presets(db: Session, user_id: int = GUEST_USER_ID, device_id: str = ""):
    """写入内置默认预设（DeepSeek/Qwen/ChatGPT），按 name 查重：已存在的公司名不再重复添加。"""
    existing = {p.name for p in db.query(Preset).filter(
        _scope(Preset, user_id, device_id)).all()}
    for d in DEFAULT_PRESETS:
        if d["name"] in existing:
            continue
        db.add(Preset(
            user_id=user_id, device_id=device_id, name=d["name"], api="openai",
            base_url=d["base_url"], model_name=d["model_name"],
            max_tokens=2000, temperature=0.2,
        ))
    db.commit()


def reconcile_presets(db: Session, user_id: int = GUEST_USER_ID, device_id: str = ""):
    """合并重复预设（幂等）。

    1) 旧迁移预设（如"云端 API（迁移）"）若命中内置默认预设 URL → 改名为默认名
    2) 同用户同设备同名预设只保留一个（优先保留激活/带 key 的），避免重复按钮
    """
    # 1) 旧迁移预设改名（命中默认预设 URL 的）
    for p in db.query(Preset).filter(
        _scope(Preset, user_id, device_id)
    ).all():
        for d in DEFAULT_PRESETS:
            if p.name != d["name"] and (p.base_url or "").rstrip("/") == d["base_url"].rstrip("/"):
                p.name = d["name"]
                break
    db.commit()
    # 2) 同名去重：保留 active 或带 key 的，删除另一个
    seen = {}
    for p in db.query(Preset).filter(
        _scope(Preset, user_id, device_id)
    ).order_by(Preset.id).all():
        if p.name not in seen:
            seen[p.name] = p
            continue
        keep, drop = seen[p.name], p
        if (drop.is_active and not keep.is_active) or (drop.api_key and not keep.api_key):
            keep, drop = drop, keep
        seen[p.name] = keep
        db.delete(drop)
    db.commit()


def _get_owned(db: Session, preset_id: int, user_id: int, device_id: str = ""):
    return db.query(Preset).filter(
        Preset.id == preset_id, _scope(Preset, user_id, device_id)
    ).first()


def _apply(row: Preset, data: dict):
    """把合法字段写入 ORM（api_key 加密存储）。"""
    for k in ("name", "api", "base_url", "model_name", "local_model_name", "local_model_path", "local_device"):
        if data.get(k) is not None:
            setattr(row, k, str(data[k]).strip())
    if data.get("api_key") is not None:
        row.api_key = encrypt(str(data["api_key"]).strip())
    if data.get("max_tokens") is not None:
        try:
            row.max_tokens = int(data["max_tokens"])
        except (TypeError, ValueError):
            pass
    if data.get("temperature") is not None:
        try:
            row.temperature = float(data["temperature"])
        except (TypeError, ValueError):
            pass
