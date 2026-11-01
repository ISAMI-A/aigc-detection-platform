"""系统管理（批次5，实现 8.2/8.6）：总览 / 用户管理 / 功能开关 / 系统公告 / 操作日志（仅 admin）。

- 表（web.db）：feature_flags（功能开关）、announcements（系统公告）；operation_logs 由 auth_device 管理
- 接口：/api/admin/*（require_admin 依赖拦截，非 admin 403）
- 功能开关：本模块提供读写；前端隐藏入口由 /api/admin/features 驱动；
  后端拦截由主应用 feature_gate 中间件按路径前缀判定（admin 豁免，游客/普通用户 1009）
"""
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import sqlalchemy as sa

from auth import engine, users, tokens, _get_current_user, _public_user, hash_password, _password_ok, _gen_uid
from auth_device import log_operation

router = APIRouter(prefix="/api/admin", tags=["admin"])

_BASE = os.path.dirname(os.path.abspath(__file__))

metadata = sa.MetaData()

feature_flags = sa.Table(
    "feature_flags", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String(32), unique=True, nullable=False),   # detect/verify/rsverify/face
    sa.Column("enabled", sa.Integer, default=1),
    sa.Column("updated_at", sa.String(32), default=lambda: datetime.now().isoformat(timespec="seconds")),
)

announcements = sa.Table(
    "announcements", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("title", sa.String(200), nullable=False),
    sa.Column("content", sa.Text, default=""),
    sa.Column("enabled", sa.Integer, default=1),
    sa.Column("created_at", sa.String(32), default=lambda: datetime.now().isoformat(timespec="seconds")),
    sa.Column("updated_at", sa.String(32), default=lambda: datetime.now().isoformat(timespec="seconds")),
)

metadata.create_all(engine)

# 功能开关种子（幂等）：默认全部开启
DEFAULT_FEATURES = ("detect", "verify", "rsverify", "face")
with engine.begin() as conn:
    for name in DEFAULT_FEATURES:
        if not conn.execute(sa.select(feature_flags.c.id).where(
                feature_flags.c.name == name)).first():
            conn.execute(feature_flags.insert().values(name=name, enabled=1))


def _now():
    return datetime.now().isoformat(timespec="seconds")


def require_admin(request: Request):
    """依赖：必须为已登录 admin，否则 401/403"""
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, detail={"code": 401, "msg": "未登录或登录已过期"})
    if user["role"] != "admin":
        raise HTTPException(403, detail={"code": 403, "msg": "无管理员权限"})
    return user


def get_feature_enabled(name: str) -> bool:
    """查询功能开关（供 feature_gate 中间件使用）"""
    try:
        with engine.connect() as conn:
            row = conn.execute(sa.select(feature_flags.c.enabled).where(
                feature_flags.c.name == name)).first()
            return bool(row[0]) if row else True
    except Exception:
        return True


class ResetPwdReq(BaseModel):
    password: str | None = None


class FeatureReq(BaseModel):
    enabled: bool


class AnnouncementReq(BaseModel):
    title: str | None = None
    content: str | None = None
    enabled: bool | None = None


# ============================================================
# 总览
# ============================================================
@router.get("/overview")
def overview(request: Request, admin=Depends(require_admin)):
    """仪表盘总览：用户数 / 今日活跃 / 各系统记录数 / 功能开关状态"""
    today = datetime.now().strftime("%Y-%m-%d")
    with engine.connect() as conn:
        user_total = conn.execute(sa.select(sa.func.count()).select_from(users)).scalar() or 0
        today_active = conn.execute(sa.text(
            "SELECT COUNT(DISTINCT user_id) FROM tokens WHERE created_at LIKE :t AND user_id IS NOT NULL"),
            {"t": f"{today}%"}).scalar() or 0

    def _tbl_count(db_file, tables):
        out = {}
        try:
            if not os.path.exists(db_file):
                return {t: 0 for t in tables}
            conn = sqlite3.connect(db_file)
            for t in tables:
                try:
                    out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except Exception:
                    out[t] = 0
            conn.close()
        except Exception:
            out = {t: 0 for t in tables}
        return out

    _base = os.path.dirname(os.path.abspath(__file__))
    detect = _tbl_count(os.path.join(_base, "data", "web.db"),
                        ["detect_uploads", "detect_records"])
    smart = _tbl_count(os.path.join(_base, "data", "smart_verify.db"),
                       ["images", "pairs", "results"])
    rs = _tbl_count(os.path.join(_base, "data", "rs_verify.db"),
                    ["rs_images", "rs_records"])
    feats = {}
    with engine.connect() as conn:
        for row in conn.execute(sa.select(feature_flags.c.name, feature_flags.c.enabled)):
            feats[row[0]] = bool(row[1])
    return {
        "users": user_total, "today_active": today_active,
        "detect": detect, "smart": smart, "rs": rs, "features": feats,
    }


# ============================================================
# 用户管理
# ============================================================
def _user_rows(conn, where, limit=None, offset=None):
    q = sa.select(users).where(where).order_by(users.c.id)
    if limit is not None:
        q = q.limit(limit).offset(offset)
    return [dict(r._mapping) for r in conn.execute(q)]


@router.get("/users")
def list_users(request: Request, admin=Depends(require_admin)):
    """用户列表（搜索 username/email 模糊；分页）"""
    q = (request.query_params.get("search") or "").strip()
    page = max(1, int(request.query_params.get("page") or 1))
    size = min(50, max(5, int(request.query_params.get("size") or 10)))
    with engine.connect() as conn:
        if q:
            like = f"%{q}%"
            where = sa.or_(users.c.username.like(like), users.c.email.like(like))
        else:
            where = sa.true()
        total = conn.execute(sa.select(sa.func.count()).select_from(users).where(where)).scalar() or 0
        rows = _user_rows(conn, where, size, (page - 1) * size)
    return {"total": total, "page": page, "size": size,
            "items": [dict(_public_user(r), disabled=r["disabled"], fail_count=r["fail_count"],
                           lock_until=r["lock_until"]) for r in rows]}


class CreateUserReq(BaseModel):
    username: str
    password: str
    email: str = ""
    role: str = "user"


@router.post("/users")
def create_user(payload: CreateUserReq, request: Request, admin=Depends(require_admin)):
    """admin 直接创建用户（复用注册的密码策略校验；创建后可直接登录，无强制改密）"""
    username = payload.username.strip()
    email = payload.email.strip() or None
    role = payload.role if payload.role in ("user", "admin") else "user"
    if not username or not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
        raise HTTPException(400, detail={"code": 400, "msg": "用户名需 3-20 位字母/数字/下划线"})
    if not _password_ok(payload.password, username):
        raise HTTPException(400, detail={"code": 400, "msg": "密码需 8-20 位且含大小写字母与数字，且不能与用户名相同或为弱密码"})
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, detail={"code": 400, "msg": "邮箱格式不正确"})
    with engine.begin() as conn:
        exists = conn.execute(sa.text("SELECT id FROM users WHERE username=:u"), {"u": username}).first()
        if exists:
            raise HTTPException(400, detail={"code": 400, "msg": "用户名已存在"})
        if email:
            dup = conn.execute(sa.text("SELECT id FROM users WHERE email=:e"), {"e": email}).first()
            if dup:
                raise HTTPException(400, detail={"code": 400, "msg": "邮箱已被其他账号使用"})
        ins = conn.execute(users.insert().values(
            username=username, uid=_gen_uid(), email=email,
            password_hash=hash_password(payload.password),
            role=role, disabled=0, must_change_password=0,
            created_at=datetime.now().isoformat(timespec="seconds")))
    log_operation(request, "admin.user_create", f"user#{ins.lastrowid}:{username}")
    return {"id": ins.lastrowid, "username": username, "role": role}


@router.post("/users/{user_id}/toggle")
def toggle_user(user_id: int, request: Request, admin=Depends(require_admin)):
    """禁用/启用用户（禁用后该用户全部 token 失效）；超级管理员不可禁用"""
    if user_id == admin["id"]:
        raise HTTPException(400, detail={"code": 400, "msg": "不能禁用自己"})
    with engine.begin() as conn:
        row = conn.execute(sa.select(users.c.disabled, users.c.username).where(users.c.id == user_id)).first()
        if not row:
            raise HTTPException(404, detail={"code": 404, "msg": "用户不存在"})
        if row._mapping["username"] == "admin":
            raise HTTPException(400, detail={"code": 400, "msg": "超级管理员不可禁用"})
        new_val = 0 if row[0] else 1
        conn.execute(users.update().where(users.c.id == user_id).values(disabled=new_val))
        if new_val:
            conn.execute(tokens.delete().where(tokens.c.user_id == user_id))
    log_operation(request, "admin.user_toggle", f"user#{user_id}:{'禁用' if new_val else '启用'}")
    return {"disabled": new_val}


@router.post("/users/{user_id}/reset_password")
def reset_password(user_id: int, payload: ResetPwdReq, request: Request, admin=Depends(require_admin)):
    """重置用户密码（可指定或随机生成；全部 token 失效；下次登录强制改密）"""
    new_pwd = (payload.password or "").strip() or (secrets.token_urlsafe(8) + "Aa1")
    with engine.begin() as conn:
        row = conn.execute(sa.select(users.c.username).where(users.c.id == user_id)).first()
        if not row:
            raise HTTPException(404, detail={"code": 404, "msg": "用户不存在"})
        conn.execute(users.update().where(users.c.id == user_id).values(
            password_hash=hash_password(new_pwd), must_change_password=1))
        conn.execute(tokens.delete().where(tokens.c.user_id == user_id))
    log_operation(request, "admin.reset_password", f"user#{user_id}:{row[0]}")
    return {"message": "密码已重置，下次登录需修改密码", "password": new_pwd}


@router.post("/users/{user_id}/role")
def set_role(user_id: int, role: str, request: Request, admin=Depends(require_admin)):
    """调整用户角色（user/admin）。

    超级管理员（预置 admin 账号）身份不可变更，防止系统失管。
    """
    if role not in ("user", "admin"):
        raise HTTPException(400, detail={"code": 400, "msg": "角色必须为 user 或 admin"})
    with engine.begin() as conn:
        row = conn.execute(sa.select(users.c.username).where(users.c.id == user_id)).first()
        if not row:
            raise HTTPException(404, detail={"code": 404, "msg": "用户不存在"})
        if row[0] == "admin":
            raise HTTPException(400, detail={"code": 400, "msg": "超级管理员身份不可变更"})
        conn.execute(users.update().where(users.c.id == user_id).values(role=role))
    log_operation(request, "admin.set_role", f"user#{user_id}:{row[0]}→{role}")
    return {"role": role}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, admin=Depends(require_admin)):
    """删除用户（物理删除）：联动清理三系统数据与文件；操作日志保留但 operator_name 脱敏；超级管理员不可删除"""
    if user_id == admin["id"]:
        raise HTTPException(400, detail={"code": 400, "msg": "不能删除自己"})
    with engine.begin() as conn:
        row = conn.execute(sa.select(users.c.username).where(users.c.id == user_id)).first()
        if not row:
            raise HTTPException(404, detail={"code": 404, "msg": "用户不存在"})
        if row[0] == "admin":
            raise HTTPException(400, detail={"code": 400, "msg": "超级管理员不可删除"})
        conn.execute(users.delete().where(users.c.id == user_id))
        conn.execute(tokens.delete().where(tokens.c.user_id == user_id))
        # 操作日志脱敏（保留审计留痕）
        conn.execute(sa.text("UPDATE operation_logs SET operator_name='已注销用户' WHERE operator_id=:id"),
                     {"id": str(user_id)})
    # 联动清理三系统该用户数据（图片文件/结果记录）
    from detect import _clear_user_data as _detect_clear
    from smart_verify.app import cleanup_all as _smart_clear
    from rs_verify.app import cleanup_all as _rs_clear
    _detect_clear(user_id)
    _smart_clear("", user_id)
    _rs_clear("", user_id)
    log_operation(request, "admin.delete_user", f"user#{user_id}:{row[0]}")
    return {"deleted": user_id}


# ============================================================
# 功能开关
# ============================================================
@router.get("/features")
def get_features(request: Request, admin=Depends(require_admin)):
    with engine.connect() as conn:
        items = [{"name": r[0], "enabled": bool(r[1])}
                 for r in conn.execute(sa.select(feature_flags.c.name, feature_flags.c.enabled))]
    return {"features": items}


@router.put("/features/{name}")
def set_feature(name: str, payload: FeatureReq, request: Request, admin=Depends(require_admin)):
    if name not in DEFAULT_FEATURES:
        raise HTTPException(400, detail={"code": 400, "msg": "未知功能开关"})
    enabled = 1 if payload.enabled else 0
    with engine.begin() as conn:
        conn.execute(feature_flags.update().where(feature_flags.c.name == name).values(
            enabled=enabled, updated_at=_now()))
    log_operation(request, "admin.set_feature", f"{name}:{'开' if enabled else '关'}")
    return {"name": name, "enabled": bool(enabled)}


# ============================================================
# 系统公告（CRUD 仅 admin；全局展示走 /api/announcements）
# ============================================================
@router.get("/announcements")
def list_announcements(request: Request, admin=Depends(require_admin)):
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(
            sa.select(announcements).order_by(announcements.c.id.desc()))]
    return {"items": rows}


@router.post("/announcements")
def create_announcement(payload: AnnouncementReq, request: Request, admin=Depends(require_admin)):
    title = (payload.title or "").strip()
    content = (payload.content or "").strip()
    if not title:
        raise HTTPException(400, detail={"code": 400, "msg": "公告标题不能为空"})
    now = _now()
    with engine.begin() as conn:
        ins = conn.execute(announcements.insert().values(
            title=title, content=content,
            enabled=1 if (payload.enabled is None or payload.enabled) else 0,
            created_at=now, updated_at=now))
        new_id = ins.lastrowid
    log_operation(request, "admin.announcement_create", f"id#{new_id}:{title}")
    return {"id": new_id}


@router.put("/announcements/{ann_id}")
def update_announcement(ann_id: int, payload: AnnouncementReq, request: Request, admin=Depends(require_admin)):
    with engine.begin() as conn:
        if not conn.execute(sa.select(announcements.c.id).where(
                announcements.c.id == ann_id)).first():
            raise HTTPException(404, detail={"code": 404, "msg": "公告不存在"})
        vals = {"updated_at": _now()}
        if payload.title is not None:
            vals["title"] = payload.title.strip()
        if payload.content is not None:
            vals["content"] = payload.content.strip()
        if payload.enabled is not None:
            vals["enabled"] = 1 if payload.enabled else 0
        conn.execute(announcements.update().where(announcements.c.id == ann_id).values(**vals))
    log_operation(request, "admin.announcement_update", f"id#{ann_id}")
    return {"updated": ann_id}


@router.delete("/announcements/{ann_id}")
def delete_announcement(ann_id: int, request: Request, admin=Depends(require_admin)):
    with engine.begin() as conn:
        conn.execute(announcements.delete().where(announcements.c.id == ann_id))
    log_operation(request, "admin.announcement_delete", f"id#{ann_id}")
    return {"deleted": ann_id}


# 全局可见（登录用户）的公告列表（enabled=1）——公开前缀 /api/announcements，供所有用户拉取
public_router = APIRouter(prefix="/api", tags=["announcement"])


@public_router.get("/announcements")
def public_announcements(request: Request):
    with engine.connect() as conn:
        rows = [{"id": r[0], "title": r[1], "content": r[2], "created_at": r[4]}
                for r in conn.execute(sa.select(
                    announcements.c.id, announcements.c.title, announcements.c.content,
                    announcements.c.enabled, announcements.c.created_at).where(
                    announcements.c.enabled == 1).order_by(announcements.c.id.desc()))]
    return {"items": rows}


@public_router.get("/features")
def public_features(request: Request):
    """功能开关状态（公开，供前端隐藏入口）"""
    with engine.connect() as conn:
        return {r[0]: bool(r[1]) for r in conn.execute(
            sa.select(feature_flags.c.name, feature_flags.c.enabled))}


# ============================================================
# 操作日志
# ============================================================
@router.get("/logs")
def list_logs(request: Request, admin=Depends(require_admin)):
    """操作日志（分页 + 筛选：动作 / 操作者 / 时间范围 from~to）"""
    action = (request.query_params.get("action") or "").strip()
    operator = (request.query_params.get("operator") or "").strip()
    from_ts = (request.query_params.get("from") or "").strip()
    to_ts = (request.query_params.get("to") or "").strip()
    page = max(1, int(request.query_params.get("page") or 1))
    size = min(100, max(5, int(request.query_params.get("size") or 20)))
    conds = ["1=1"]
    params = {}
    if action:
        conds.append("action LIKE :a")
        params["a"] = f"%{action}%"
    if operator:
        conds.append("(operator_name LIKE :o OR operator_id LIKE :o)")
        params["o"] = f"%{operator}%"
    if from_ts:
        conds.append("created_at >= :f")
        params["f"] = from_ts
    if to_ts:
        conds.append("created_at <= :t")
        params["t"] = to_ts
    where = " AND ".join(conds)
    with engine.connect() as conn:
        total = conn.execute(sa.text(
            f"SELECT COUNT(*) FROM operation_logs WHERE {where}"), params).scalar() or 0
        rows = [dict(r._mapping) for r in conn.execute(sa.text(
            f"SELECT * FROM operation_logs WHERE {where} ORDER BY id DESC LIMIT :lim OFFSET :off"),
            {**params, "lim": size, "off": (page - 1) * size})]
    return {"total": total, "page": page, "size": size, "items": rows}


@router.delete("/logs")
def clear_logs(request: Request, admin=Depends(require_admin)):
    """手动清空全部操作日志（清空动作本身会记入一条新日志）"""
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM operation_logs"))
    log_operation(request, "admin.logs_clear", "")
    return {"cleared": True}


# ============================================================
# 数据管理（批次5.2）：统计 + 清空游客数据 / 清空用户数据 / 清空全部（保留当前 admin）
# ============================================================
_DB_FILES = {
    "detect": os.path.join(_BASE, "data", "web.db"),
    "smart": os.path.join(_BASE, "data", "smart_verify.db"),
    "rs": os.path.join(_BASE, "data", "rs_verify.db"),
    "face": os.path.join(_BASE, "data", "face.db"),
}

# 表 → 需删除的物理文件列（其余列仅删记录；无文件列表照样清记录）
_TABLES = {
    "detect": {
        "detect_uploads": ["file_path"],
        "detect_records": ["orig_path", "heat_path", "analysis_path", "thumb_path"],
    },
    "smart": {
        "images": ["file_path"],
        "pairs": [],
        "results": ["vis_path"],
    },
    "rs": {
        "rs_images": ["file_path"],
        "rs_records": ["annotated_image", "before_path", "after_path"],
        "rs_presets": [],
        "rs_models": [],
    },
    "face": {
        "face_uploads": ["file_path"],
        "face_results": ["thumb_path"],
    },
}

# 业务表（排除 rs_presets/rs_models 配置表，清空配置数据时不删配置）
# 注：全局人脸库（FaceRecognition/face_db/faces.db）为配置级数据，
# 在 clear_config / clear_all 中显式调用 face.app.cleanup_library() 清空
_BUSINESS_TABLES = {
    "detect": _TABLES["detect"],
    "smart": _TABLES["smart"],
    "rs": {k: v for k, v in _TABLES["rs"].items() if k not in ("rs_presets", "rs_models")},
    "face": _TABLES["face"],
}

# 通知中心(chat)业务表：均位于主库 web.db（同 detect），落盘文件 data/chat_files/。
# 独立定义而非并入上面 _TABLES/_BUSINESS_TABLES，避免 _data_stats/统计把聊天记录算进"图像篡改检测"。
_CHAT_DB = _DB_FILES["detect"]
_CHAT_TABLES = {
    "chat_requests": [],
    "chat_friends": [],
    "chat_conversations": [],
    "chat_messages": ["file_path"],
    "chat_pending": ["file_path"],
    "chat_ann_read": [],
    "chat_ann_delivered": [],
}


def _purge(db_file: str, tables: dict, cond: str) -> int:
    """按条件删除某库指定表记录，并联动删除物理文件（路径去重；删后清理空目录）。返回删除文件数"""
    files = []
    conn = sqlite3.connect(db_file)
    try:
        for t, cols in tables.items():
            try:
                if cols:
                    for row in conn.execute(f"SELECT {', '.join(cols)} FROM {t} WHERE {cond}"):
                        for p in row:
                            if p and os.path.exists(p):
                                files.append(p)
                conn.execute(f"DELETE FROM {t} WHERE {cond}")
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()
    seen = set()
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        try:
            os.remove(f)
            d = os.path.dirname(f)
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass
    return len(seen)


def _purge_files_only(db_file: str, tables: dict, cond: str) -> int:
    """只删物理文件，不删DB记录（清空占用数据用）"""
    files = []
    conn = sqlite3.connect(db_file)
    try:
        for t, cols in tables.items():
            try:
                if cols:
                    for row in conn.execute(f"SELECT {', '.join(cols)} FROM {t} WHERE {cond}"):
                        for p in row:
                            if p and os.path.exists(p):
                                files.append(p)
            except Exception:
                pass
    finally:
        conn.close()
    seen = set()
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        try:
            os.remove(f)
            d = os.path.dirname(f)
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass
    return len(seen)


def _data_stats() -> dict:
    """用户总数 / 三系统记录数（user=登录用户记录、guest=游客记录，均为该库各业务表记录合计）/ 游客设备去重数"""
    with engine.connect() as conn:
        users_total = conn.execute(sa.select(sa.func.count()).select_from(users)).scalar() or 0
    guests = {}
    for key, db_file in _DB_FILES.items():
        if not os.path.exists(db_file):
            guests[key] = {"devices": 0, "user": 0, "guest": 0}
            continue
        conn = sqlite3.connect(db_file)
        user_rows = guest_rows = 0
        guest_devices = set()
        for t in _TABLES[key]:
            try:
                # 记录数：同一用户/游客可有多条记录，故为"记录数"而非人数
                user_rows += conn.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE user_id IS NOT NULL").fetchone()[0]
                guest_rows += conn.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE user_id IS NULL").fetchone()[0]
                # 游客设备数：跨该库全部表取并集去重，避免同一设备在多表重复计数
                for d in conn.execute(
                        f"SELECT DISTINCT device_id FROM {t} WHERE user_id IS NULL").fetchall():
                    if d[0]:
                        guest_devices.add(d[0])
            except Exception:
                pass
        conn.close()
        guests[key] = {"devices": len(guest_devices), "user": user_rows, "guest": guest_rows}
    return {"users": users_total, "systems": guests}


@router.get("/data")
def data_stats(request: Request, admin=Depends(require_admin)):
    return _data_stats()


@router.post("/data/clear_files")
def clear_files(request: Request, admin=Depends(require_admin)):
    """清空占用数据：只删落盘文件（包括用户/游客/admin），不删DB记录"""
    total = 0
    for key, tables in _TABLES.items():
        total += _purge_files_only(_DB_FILES[key], tables, "1=1")
    # 通知中心(chat)：同样只删聊天落盘文件（data/chat_files/）
    total += _purge_files_only(_CHAT_DB, _CHAT_TABLES, "1=1")
    log_operation(request, "admin.data_clear_files", f"{total} 文件")
    return {"cleared": "files", "files": total}


@router.post("/data/clear_config")
def clear_config_data(request: Request, admin=Depends(require_admin)):
    """清空配置数据：删DB业务数据+文件（不含 rs_presets/rs_models 配置表），保留用户/游客账号；
    全局人脸库（faces.db + 样本照）一并清空（配置级数据，B 口径）"""
    total = 0
    for key, tables in _BUSINESS_TABLES.items():
        total += _purge(_DB_FILES[key], tables, "1=1")
    # 通知中心(chat)：聊天记录/好友/申请/已读游标一并清（保留账号不动，账号由 users 管理）
    total += _purge(_CHAT_DB, _CHAT_TABLES, "1=1")
    # 全局人脸库：faces.db 全部记录 + 样本照目录
    from face.app import cleanup_library as _face_lib_clear
    _face_lib_clear()
    log_operation(request, "admin.data_clear_config", f"{total} 文件")
    return {"cleared": "config", "files": total}


@router.post("/data/clear_all")
def clear_all_data(request: Request, admin=Depends(require_admin)):
    """清空全部数据：DB全部记录+文件+普通用户账号，保留 admin 配置和本身；
    全局人脸库一并彻底清空"""
    total = 0
    admin_id = admin["id"]
    for key, tables in _BUSINESS_TABLES.items():
        total += _purge(_DB_FILES[key], tables, "1=1")
    # 通知中心(chat)：聊天记录/好友/申请/已读游标 + 落盘文件，随账号一并彻底清除
    total += _purge(_CHAT_DB, _CHAT_TABLES, "1=1")
    # rs 配置表：删除非 admin 的记录（保留 admin 的预设/模型配置）
    cfg_cond = f"user_id IS NULL OR user_id != {admin_id}"
    _purge(_DB_FILES["rs"], {"rs_presets": [], "rs_models": []}, cfg_cond)
    # 全局人脸库：faces.db 全部记录 + 样本照目录（含 admin 录入的人脸）
    from face.app import cleanup_library as _face_lib_clear
    _face_lib_clear()
    with engine.begin() as conn:
        conn.execute(users.delete().where(users.c.id != admin_id))
        conn.execute(tokens.delete().where(tokens.c.user_id != admin_id))
        conn.execute(sa.text("DELETE FROM email_codes"))
        conn.execute(sa.text("DELETE FROM operation_logs"))
    log_operation(request, "admin.data_clear_all", f"{total} 文件")
    return {"cleared": "all", "files": total, "kept": admin["username"]}


# ============================================================
# 后台清理线程：90 天前操作日志
# ============================================================
def _log_cleanup_loop():
    while True:
        time.sleep(6 * 3600)
        try:
            cutoff = (datetime.now() - timedelta(days=90)).isoformat(timespec="seconds")
            with engine.begin() as conn:
                conn.execute(sa.text(
                    "DELETE FROM operation_logs WHERE created_at < :c"), {"c": cutoff})
        except Exception:
            pass


threading.Thread(target=_log_cleanup_loop, daemon=True).start()
