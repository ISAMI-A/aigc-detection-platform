"""登录体系后端（批次3，实现 8.1/8.6 规划）

- 表（web.db）：users / email_codes / tokens
  - users：username 唯一；password PBKDF2 哈希（非可逆 AES）；email 唯一可空；
    role=user|admin；must_change_password；disabled；fail_count/lock_until（登录锁定）
  - email_codes：验证码（purpose=register|login|reset|bind），5 分钟过期，一次性
  - tokens：Bearer token 30 天滑动过期，多设备共存；存 token_hash（sha256）
- 接口：/api/auth/*（register / send_code / login / login_email / forgot /
  change_password / logout / me）；人脸接口远期预留
- SMTP：环境变量 SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_FROM；
  未配置时验证码打印到服务端日志（开发模式），配置后可真实收发
- 后台清理线程：过期验证码 / 过期 token
"""
import hashlib
import hmac
import io
import json
import os
import secrets
import shutil
import smtplib
import sqlite3
import threading
import time
import uuid
import zipfile
from datetime import datetime, timedelta
from email.header import Header
from email.mime.text import MIMEText

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
import sqlalchemy as sa

from auth_device import get_device_id, log_operation

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ============================================================
# SQLite（web.db，与 detect 共用同一文件；WAL 已由 detect 开启）
# ============================================================
_BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_BASE, "data", "web.db")
engine = sa.create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
metadata = sa.MetaData()

_now = lambda: datetime.now().isoformat(timespec="seconds")
_dt = lambda s: datetime.fromisoformat(s) if s else None

users = sa.Table(
    "users", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("username", sa.String(64), unique=True, nullable=False),
    sa.Column("password_hash", sa.String(255), default=""),      # pbkdf2$salt$hash
    sa.Column("email", sa.String(255), nullable=True),           # 唯一可空（未绑为 NULL）
    sa.Column("email_verified", sa.Integer, default=0),
    sa.Column("face_vectors", sa.Text, default=""),              # JSON，远期人脸预留
    sa.Column("role", sa.String(16), default="user"),
    sa.Column("must_change_password", sa.Integer, default=0),    # 1=下次登录强制改密
    sa.Column("disabled", sa.Integer, default=0),                # 1=禁用（admin）
    sa.Column("fail_count", sa.Integer, default=0),              # 连续登录失败次数
    sa.Column("lock_until", sa.String(32), default=""),          # 锁定截止时间
    sa.Column("uid", sa.String(16), unique=True, nullable=True), # 8位纯数字唯一 UID（通知中心搜索用）
    sa.Column("created_at", sa.String(32), default=lambda: _now()),
)

email_codes = sa.Table(
    "email_codes", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("email", sa.String(255), index=True),
    sa.Column("code", sa.String(8)),
    sa.Column("purpose", sa.String(16)),                         # register/login/reset/bind
    sa.Column("ip", sa.String(64), default=""),                  # 发送来源 IP（单 IP 限速）
    sa.Column("expire_at", sa.String(32)),
    sa.Column("used", sa.Integer, default=0),
    sa.Column("created_at", sa.String(32), default=lambda: _now()),
)

tokens = sa.Table(
    "tokens", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("token_hash", sa.String(64), unique=True, index=True),
    sa.Column("user_id", sa.Integer, index=True),
    sa.Column("device_id", sa.String(64), default=""),
    sa.Column("created_at", sa.String(32), default=lambda: _now()),
    sa.Column("expire_at", sa.String(32)),
    sa.Column("last_used_at", sa.String(32)),
)

metadata.create_all(engine)

# 启动幂等迁移：users 表补列（create_all 不给已有表加列）
with engine.connect() as conn:
    cols = {r[1] for r in conn.execute(sa.text("PRAGMA table_info(users)")).fetchall()}
add_cols = {
    "email": "VARCHAR(255)", "email_verified": "INTEGER DEFAULT 0",
    "face_vectors": "TEXT DEFAULT ''", "role": "VARCHAR(16) DEFAULT 'user'",
    "must_change_password": "INTEGER DEFAULT 0", "disabled": "INTEGER DEFAULT 0",
    "fail_count": "INTEGER DEFAULT 0", "lock_until": "VARCHAR(32) DEFAULT ''",
    "password_hash": "VARCHAR(255) DEFAULT ''",
    "uid": "VARCHAR(16) DEFAULT NULL",
}
for col, ddl in add_cols.items():
    if col not in cols:
        with engine.begin() as conn:
            conn.execute(sa.text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
            print(f"[auth] 迁移：users 表新增 {col} 列")


def _gen_uid() -> str:
    """生成唯一的 8 位纯数字 UID（10000000~99999999，重试防碰撞）"""
    for _ in range(20):
        u = str(secrets.randbelow(90000000) + 10000000)
        with engine.connect() as conn:
            if not conn.execute(sa.select(sa.func.count()).select_from(users).where(
                    users.c.uid == u)).scalar():
                return u
    # 极端碰撞：追加随机位保证唯一（不破坏纯数字语义）
    for _ in range(20):
        u = str(secrets.randbelow(90000000) + 10000000) + \
            str(secrets.randbelow(10))
        with engine.connect() as conn:
            if not conn.execute(sa.select(sa.func.count()).select_from(users).where(
                    users.c.uid == u)).scalar():
                return u
    raise RuntimeError("uid 生成失败：无法获得唯一编号")


# ============================================================
# 工具：密码哈希 / token / 邮件
# ============================================================
def hash_password(password: str, salt: str = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             bytes.fromhex(salt), 200_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        return hmac.compare_digest(hash_password(password, salt), stored)
    except Exception:
        return False


# 预置 admin（幂等）：初始密码取环境变量 ADMIN_INIT_PASSWORD，未设置则随机生成并打印，首次登录强制改密
with engine.begin() as conn:
    adm = conn.execute(sa.select(users).where(users.c.username == "admin")).first()
    if not adm:
        _init_pwd = os.environ.get("ADMIN_INIT_PASSWORD", "").strip()
        _generated = not _init_pwd
        if _generated:
            _init_pwd = secrets.token_urlsafe(10) + "Aa1"
        conn.execute(users.insert().values(
            username="admin", uid=_gen_uid(), password_hash=hash_password(_init_pwd),
            role="admin", must_change_password=1,
            created_at=_now()))
        print(f"[auth] 已预置 admin 账号（初始密码：{_init_pwd}"
              f"{'（自动生成）' if _generated else '（来自 ADMIN_INIT_PASSWORD）'}，首次登录强制改密）")

# 存量用户补 UID（幂等：仅补 uid 为空的用户）
with engine.connect() as conn:
    missing = [dict(r._mapping) for r in conn.execute(
        sa.select(users.c.id).where(sa.or_(users.c.uid.is_(None), users.c.uid == ""))).fetchall()]
for u in missing:
    with engine.begin() as conn:
        conn.execute(users.update().where(users.c.id == u["id"]).values(uid=_gen_uid()))
if missing:
    print(f"[auth] 迁移：为 {len(missing)} 个存量用户回填 UID")


def new_token() -> str:
    """生成明文 token（前端持有）；库中只存 sha256 哈希"""
    return secrets.token_hex(32)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


TOKEN_TTL_DAYS = 30
TOKEN_REFRESH_SECONDS = 5 * 60  # last_used_at 超 5 分钟或写操作才刷新（滑动过期）


def create_token(user_id: int, device_id: str, client_ip: str = "") -> str:
    token = new_token()
    now = datetime.now()
    with engine.begin() as conn:
        conn.execute(tokens.insert().values(
            token_hash=_token_hash(token), user_id=user_id, device_id=device_id,
            created_at=now.isoformat(timespec="seconds"),
            expire_at=(now + timedelta(days=TOKEN_TTL_DAYS)).isoformat(timespec="seconds"),
            last_used_at=now.isoformat(timespec="seconds"),
        ))
    return token


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0] if fwd else request.client.host if request.client else "") or ""


# ---------- SMTP（环境变量配置，未配置则验证码打印日志，便于开发验证） ----------
def _load_env_file(path: str = None) -> dict:
    """读取 web/.env 的 KEY=VALUE 键值（SMTP 配置兜底；进程环境变量优先）。

    用途：环境变量只对启动进程的终端生效，换一种方式启动后端（IDE 终端/脚本）
    很容易拿不到；把配置放 .env 后任何方式启动都生效。
    """
    envs = {}
    try:
        p = path or os.path.join(_BASE, ".env")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    envs[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return envs


def _smtp_config() -> dict:
    envs = _load_env_file()
    get = lambda k, d="": os.environ.get(k, envs.get(k, d))
    return {
        "host": get("SMTP_HOST", ""),
        "port": int(get("SMTP_PORT", "465")),
        "user": get("SMTP_USER", ""),
        "password": get("SMTP_PASS", ""),
        "from_addr": get("SMTP_FROM", ""),
        "use_ssl": get("SMTP_SSL", "1") != "0",
    }


def send_code_email(email: str, code: str, purpose: str) -> None:
    """发送验证码邮件；SMTP 未配置时打印到日志（开发模式可读）并返回。"""
    cfg = _smtp_config()
    if not cfg["host"]:
        print(f"[auth] SMTP 未配置：验证码 {code}（purpose={purpose}，email={email}）已输出到日志")
        return
    subject = {"register": "注册验证码", "login": "登录验证码",
               "reset": "重置密码验证码", "bind": "绑定邮箱验证码"}.get(purpose, "验证码")
    body = f"您的验证码是：{code}，5 分钟内有效。请勿泄露给他人。"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = cfg["from_addr"] or cfg["user"]
    msg["To"] = email
    if cfg["use_ssl"]:
        server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=10)
    else:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=10)
    try:
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["from_addr"] or cfg["user"], [email], msg.as_string())
    finally:
        server.quit()


# ============================================================
# 业务辅助
# ============================================================
def _row_dict(u) -> dict:
    """SQLAlchemy Core Row → dict（兼容已传入 dict 的场景）"""
    return dict(u._mapping) if hasattr(u, "_mapping") else u


def _public_user(u) -> dict:
    """用户对外信息（不含哈希）"""
    m = u._mapping if hasattr(u, "_mapping") else u
    return {
        "id": m["id"], "username": m["username"], "uid": m.get("uid") or "",
        "email": m["email"], "email_verified": m["email_verified"],
        "role": m["role"], "must_change_password": m["must_change_password"],
        "created_at": m["created_at"],
    }


def _password_ok(pw: str, username: str) -> bool:
    """密码策略：8-20 位，含大小写+数字；不与用户名相同；非弱密码"""
    if len(pw) < 8 or len(pw) > 20:
        return False
    if not any(c.islower() for c in pw) or not any(c.isupper() for c in pw) or not any(c.isdigit() for c in pw):
        return False
    if username and pw.lower() == username.lower():
        return False
    if pw.lower() in ("123456", "password", "admin123", "qwerty", "abc123", "12345678"):
        return False
    return True


def _gen_code() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def _code_rate_limited(email: str, purpose: str, ip: str) -> int:
    """限速：同 (email,purpose) 60s 内 → 1007；单邮箱单日 10 条 / 单 IP 单日 20 条"""
    now = datetime.now()
    with engine.connect() as conn:
        last = conn.execute(sa.select(email_codes.c.created_at).where(
            email_codes.c.email == email, email_codes.c.purpose == purpose,
        ).order_by(email_codes.c.id.desc()).limit(1)).first()
        if last and last[0] and (now - _dt(last[0])).total_seconds() < 60:
            return 1007
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
        email_cnt = conn.execute(sa.select(sa.func.count()).where(
            email_codes.c.email == email, email_codes.c.created_at >= day0)).scalar() or 0
        if email_cnt >= 10:
            return 1007
        ip_cnt = conn.execute(sa.select(sa.func.count()).where(
            email_codes.c.ip == ip, email_codes.c.created_at >= day0)).scalar() or 0
        if ip_cnt >= 20:
            return 1007
    return 0


def _issue_token_for(user_row, request: Request) -> dict:
    u = _row_dict(user_row)
    return {"token": create_token(u["id"], (request.headers.get("X-Device-Id") or "").strip()),
            "user": _public_user(u)}


def _get_current_user(request: Request):
    """从 Authorization: Bearer <token> 解析当前用户；无效返回 None"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    th = _token_hash(auth[7:].strip())
    with engine.connect() as conn:
        tok = conn.execute(sa.select(tokens).where(tokens.c.token_hash == th)).first()
        if not tok:
            return None
        if _dt(tok._mapping["expire_at"]) and _dt(tok._mapping["expire_at"]) < datetime.now():
            return None
        user = conn.execute(sa.select(users).where(users.c.id == tok._mapping["user_id"])).first()
        if not user or user._mapping["disabled"]:
            return None
    return _row_dict(user)


def _touch_token(request: Request, is_write: bool = False) -> None:
    """滑动过期：last_used_at 超 5 分钟或写操作才刷新 expire_at"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return
    th = _token_hash(auth[7:].strip())
    now = datetime.now()
    with engine.begin() as conn:
        tok = conn.execute(sa.select(tokens).where(tokens.c.token_hash == th)).first()
        if not tok:
            return
        last = tok._mapping["last_used_at"]
        need = is_write
        if not need and last:
            try:
                need = (now - _dt(last)).total_seconds() >= TOKEN_REFRESH_SECONDS
            except Exception:
                need = True
        if need:
            conn.execute(tokens.update().where(tokens.c.token_hash == th).values(
                last_used_at=now.isoformat(timespec="seconds"),
                expire_at=(now + timedelta(days=TOKEN_TTL_DAYS)).isoformat(timespec="seconds"),
            ))


# ============================================================
# 接口
# ============================================================
@router.post("/register")
def api_register(payload: dict, request: Request):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    email = (payload.get("email") or "").strip() or None
    code = (payload.get("code") or "").strip()
    if not username or not password:
        raise HTTPException(400, detail={"code": 400, "msg": "用户名和密码不能为空"})
    if not _password_ok(password, username):
        raise HTTPException(400, detail={"code": 400, "msg": "密码需 8-20 位且含大小写字母与数字，且不能与用户名相同或为弱密码"})
    with engine.connect() as conn:
        if conn.execute(sa.select(users).where(users.c.username == username)).first():
            raise HTTPException(400, detail={"code": 1002, "msg": "用户名已存在"})
        if email:
            if conn.execute(sa.select(users).where(users.c.email == email)).first():
                raise HTTPException(400, detail={"code": 1003, "msg": "邮箱已被使用"})
            if not _verify_code(email, code, "register"):
                raise HTTPException(400, detail={"code": 1001, "msg": "验证码错误或已过期"})
    with engine.begin() as conn:
        ins = conn.execute(users.insert().values(
            username=username, uid=_gen_uid(), password_hash=hash_password(password),
            email=email, email_verified=1 if email else 0, created_at=_now()))
        row = conn.execute(sa.select(users).where(users.c.id == ins.lastrowid)).first()
    log_operation(request, "auth.register", f"user#{row._mapping['id']}:{username}",
                   operator_username=username)
    return _issue_token_for(row, request)


@router.post("/send_code")
def api_send_code(payload: dict, request: Request):
    email = (payload.get("email") or "").strip()
    purpose = (payload.get("purpose") or "").strip()
    if not email or purpose not in ("register", "login", "reset", "bind"):
        raise HTTPException(400, detail={"code": 400, "msg": "参数错误：email 与 purpose 必填"})
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, detail={"code": 400, "msg": "邮箱格式不正确"})
    ip = _client_ip(request)
    if (limited := _code_rate_limited(email, purpose, ip)) == 1007:
        raise HTTPException(429, detail={"code": 1007, "msg": "验证码发送太频繁，请稍后再试"})
    code = _gen_code()
    expire = (datetime.now() + timedelta(minutes=5)).isoformat(timespec="seconds")
    with engine.begin() as conn:
        conn.execute(email_codes.insert().values(
            email=email, code=code, purpose=purpose, ip=ip,
            expire_at=expire, created_at=_now()))
    try:
        send_code_email(email, code, purpose)
    except Exception as e:
        print(f"[auth] 邮件发送失败: {e}")
        raise HTTPException(500, detail={"code": 500, "msg": "邮件发送失败，请稍后再试"})
    return {"message": "验证码已发送"}


def _verify_code(email: str, code: str, purpose: str) -> bool:
    """校验验证码（一次性）：匹配且未过期且 purpose 一致"""
    with engine.begin() as conn:
        row = conn.execute(sa.select(email_codes).where(
            email_codes.c.email == email, email_codes.c.purpose == purpose,
            email_codes.c.used == 0,
        ).order_by(email_codes.c.id.desc()).limit(1)).first()
        if not row:
            return False
        if _dt(row._mapping["expire_at"]) and _dt(row._mapping["expire_at"]) < datetime.now():
            return False
        if not hmac.compare_digest(row._mapping["code"], code):
            return False
        conn.execute(email_codes.update().where(email_codes.c.id == row._mapping["id"]).values(used=1))
    return True


def _check_lock(user) -> None:
    if user["disabled"]:
        raise HTTPException(403, detail={"code": 1006, "msg": "账号已被禁用"})
    lock = user["lock_until"]
    if lock and _dt(lock) and _dt(lock) > datetime.now():
        raise HTTPException(403, detail={"code": 1008, "msg": "多次尝试失败，请稍后再试"})


def _record_login_fail(user, ok: bool) -> None:
    now = datetime.now()
    with engine.begin() as conn:
        if ok:
            conn.execute(users.update().where(users.c.id == user["id"]).values(fail_count=0, lock_until=""))
        else:
            fail = user["fail_count"] + 1
            lock_until = (now + timedelta(minutes=15)).isoformat(timespec="seconds") if fail >= 5 else ""
            conn.execute(users.update().where(users.c.id == user["id"]).values(
                fail_count=fail, lock_until=lock_until))


@router.post("/login")
def api_login(payload: dict, request: Request):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    with engine.connect() as conn:
        user = _row_dict(conn.execute(sa.select(users).where(users.c.username == username)).first())
        if not user:
            raise HTTPException(400, detail={"code": 1004, "msg": "用户名或密码错误"})
    _check_lock(user)
    if not verify_password(password, user["password_hash"]):
        _record_login_fail(user, False)
        log_operation(request, "auth.login", f"user#{user['id']}:{username}", result="fail")
        raise HTTPException(400, detail={"code": 1005, "msg": "用户名或密码错误"})
    _record_login_fail(user, True)
    log_operation(request, "auth.login", f"user#{user['id']}:{username}",
                  operator_username=username)
    return _issue_token_for(user, request)


@router.post("/login_email")
def api_login_email(payload: dict, request: Request):
    email = (payload.get("email") or "").strip()
    code = (payload.get("code") or "").strip()
    with engine.connect() as conn:
        user = _row_dict(conn.execute(sa.select(users).where(users.c.email == email)).first())
        if not user:
            raise HTTPException(400, detail={"code": 1004, "msg": "该邮箱未注册"})
    _check_lock(user)
    if not _verify_code(email, code, "login"):
        raise HTTPException(400, detail={"code": 1001, "msg": "验证码错误或已过期"})
    log_operation(request, "auth.login_email", f"user#{user['id']}:{user['username']}",
                  operator_username=user["username"])
    return _issue_token_for(user, request)


@router.post("/forgot")
def api_forgot(payload: dict, request: Request):
    """邮箱验证码重置密码（purpose=reset）"""
    email = (payload.get("email") or "").strip()
    code = (payload.get("code") or "").strip()
    new_password = payload.get("new_password") or ""
    with engine.connect() as conn:
        user = _row_dict(conn.execute(sa.select(users).where(users.c.email == email)).first())
        if not user:
            raise HTTPException(400, detail={"code": 1004, "msg": "该邮箱未注册"})
    _check_lock(user)
    if not _verify_code(email, code, "reset"):
        raise HTTPException(400, detail={"code": 1001, "msg": "验证码错误或已过期"})
    if not _password_ok(new_password, user["username"]):
        raise HTTPException(400, detail={"code": 400, "msg": "密码需 8-20 位且含大小写字母与数字"})
    with engine.begin() as conn:
        conn.execute(users.update().where(users.c.id == user["id"]).values(
            password_hash=hash_password(new_password), must_change_password=0))
        conn.execute(tokens.delete().where(tokens.c.user_id == user["id"]))  # 全部 token 失效
    log_operation(request, "auth.forgot", f"user#{user['id']}:{user['username']}",
                  operator_username=user["username"])
    return {"message": "密码已重置，请重新登录"}


@router.post("/change_password")
def api_change_password(payload: dict, request: Request):
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, detail={"code": 401, "msg": "未登录或登录已过期"})
    old = payload.get("old_password") or ""
    new = payload.get("new_password") or ""
    if not verify_password(old, user["password_hash"]):
        # 旧密码错误不计入登录锁定（避免想改密码却被锁）
        raise HTTPException(400, detail={"code": 400, "msg": "旧密码错误"})
    if not _password_ok(new, user["username"]):
        raise HTTPException(400, detail={"code": 400, "msg": "密码需 8-20 位且含大小写字母与数字"})
    with engine.begin() as conn:
        conn.execute(users.update().where(users.c.id == user["id"]).values(
            password_hash=hash_password(new), must_change_password=0))
        # 全部 token 失效（含当前，强制重新登录）
        conn.execute(tokens.delete().where(tokens.c.user_id == user["id"]))
    log_operation(request, "auth.change_password", f"user#{user['id']}:{user['username']}")
    return {"message": "密码已修改，请重新登录"}


@router.post("/logout")
def api_logout(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        log_operation(request, "auth.logout", "")  # 先记日志再删 token（否则解析不到操作者）
        th = _token_hash(auth[7:].strip())
        with engine.begin() as conn:
            conn.execute(tokens.delete().where(tokens.c.token_hash == th))  # 仅当前设备
    return {"message": "已退出登录"}


@router.get("/me")
def api_me(request: Request):
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, detail={"code": 401, "msg": "未登录或登录已过期"})
    return {"user": _public_user(user)}


@router.post("/bind_email")
def api_bind_email(payload: dict, request: Request):
    """绑定/更换邮箱（个人资料页）：需登录 + purpose=bind 验证码"""
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, detail={"code": 401, "msg": "未登录或登录已过期"})
    email = (payload.get("email") or "").strip()
    code = (payload.get("code") or "").strip()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, detail={"code": 400, "msg": "邮箱格式不正确"})
    with engine.connect() as conn:
        dup = conn.execute(sa.select(users.c.id).where(
            users.c.email == email, users.c.id != user["id"])).first()
    if dup:
        raise HTTPException(400, detail={"code": 1003, "msg": "邮箱已被使用"})
    if not _verify_code(email, code, "bind"):
        raise HTTPException(400, detail={"code": 1001, "msg": "验证码错误或已过期"})
    with engine.begin() as conn:
        conn.execute(users.update().where(users.c.id == user["id"]).values(
            email=email, email_verified=1))
    log_operation(request, "auth.bind_email", f"user#{user['id']}:{email}")
    return {"message": "邮箱已绑定"}


@router.post("/verify_old_email")
def api_verify_old_email(payload: dict, request: Request):
    """更换邮箱第一步：校验旧邮箱收到的验证码（确认本人操作，purpose=bind 复用）"""
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, detail={"code": 401, "msg": "未登录或登录已过期"})
    if not user["email"]:
        raise HTTPException(400, detail={"code": 400, "msg": "当前账号未绑定邮箱"})
    code = (payload.get("code") or "").strip()
    if not code:
        raise HTTPException(400, detail={"code": 400, "msg": "请填写旧邮箱验证码"})
    if not _verify_code(user["email"], code, "bind"):
        raise HTTPException(400, detail={"code": 1001, "msg": "验证码错误或已过期"})
    return {"message": "旧邮箱验证通过"}


@router.get("/export")
def api_export(request: Request):
    """导出我的数据（个人资料页）：账号信息 + 三系统记录数与占用大小摘要 JSON（不含操作日志）"""
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, detail={"code": 401, "msg": "未登录或登录已过期"})
    uid = user["id"]

    def _stats(db_file: str, tables: dict) -> dict:
        """tables: {表名: [文件路径列...]} → {表名: {count, bytes}}；多列文件路径去重后累计大小"""
        out = {}
        try:
            conn = sqlite3.connect(db_file)
        except Exception:
            return {t: {"count": 0, "bytes": 0} for t in tables}
        for t, cols in tables.items():
            try:
                rows = conn.execute(
                    f"SELECT {', '.join(cols)} FROM {t} WHERE user_id = ?", (uid,)).fetchall()
            except Exception:
                out[t] = {"count": 0, "bytes": 0}
                continue
            seen, total = set(), 0
            for row in rows:
                for p in row:
                    if p and p not in seen:
                        seen.add(p)
                        try:
                            total += os.path.getsize(p)
                        except OSError:
                            pass
            out[t] = {"count": len(rows), "bytes": total}
        conn.close()
        return out

    return {
        "user": _public_user(user),
        "detect": _stats(DB_PATH, {"detect_uploads": ["file_path"]}),
        "smart": _stats(os.path.join(_BASE, "data", "smart_verify.db"),
                        {"images": ["file_path"]}),
        "rs": _stats(os.path.join(_BASE, "data", "rs_verify.db"),
                     {"rs_images": ["file_path"], "rs_records": ["annotated_image"]}),
        "face": _stats(os.path.join(_BASE, "data", "face.db"),
                       {"face_uploads": ["file_path"], "face_results": ["thumb_path"]}),
        "exported_at": _now(),
    }


# ============================================================
# 备份 / 恢复（批次5.1）：一个 zip 文件 = 全部数据（JSON 元数据 + 图片文件）
# 导出：GET /api/auth/backup → zip；导入：POST /api/auth/restore（multipart）→ 合并追加
# ============================================================
def _pack_presets(db_file: str, uid: int, include_sensitive: bool) -> list:
    """导出当前用户 LLM 预设配置（rs_presets，无文件列）。不含敏感时 api_key 置空。"""
    out = []
    if not os.path.exists(db_file):
        return out
    conn = sqlite3.connect(db_file)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(rs_presets)")]
    for row in conn.execute("SELECT * FROM rs_presets WHERE user_id=?", (uid,)):
        d = dict(zip(cols, row))
        if not include_sensitive:
            d["api_key"] = ""
        out.append(d)
    conn.close()
    return out


def _build_backup_zip(uid: int, username: str, include_sensitive: bool = False) -> bytes:
    """导出当前用户三系统数据为 zip：meta.json + detect/smart/rs.json + files/（图片文件）"""
    buf = io.BytesIO()
    zf = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    try:
        zf.writestr("meta.json", json.dumps({
            "app": "AIGC-Detection", "username": username,
            "backup_id": uuid.uuid4().hex, "exported_at": _now(),
        }, ensure_ascii=False))

        def _pack_table(db_file, table, file_cols, folder):
            """导出某表：文件路径列改为 zip 内相对路径（files/<folder>/<id>-<col>-<basename>），并打包文件"""
            out = []
            if not os.path.exists(db_file):
                return out
            conn = sqlite3.connect(db_file)
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            for row in conn.execute(f"SELECT * FROM {table} WHERE user_id=?", (uid,)):
                d = dict(zip(cols, row))
                rid = d["id"]
                for col in file_cols:
                    p = d.get(col)
                    if p and os.path.exists(p):
                        rel = f"files/{folder}/{rid}-{col}-{os.path.basename(p)}"
                        zf.write(p, rel)
                        d[col] = rel
                    else:
                        d[col] = None
                out.append(d)
            conn.close()
            return out

        web_db = os.path.join(_BASE, "data", "web.db")
        det = {
            "uploads": _pack_table(web_db, "detect_uploads", ["file_path"], "detect_uploads"),
            "records": _pack_table(web_db, "detect_records",
                                   ["orig_path", "heat_path", "analysis_path", "thumb_path"],
                                   "detect_results"),
        }
        zf.writestr("detect.json", json.dumps(det, ensure_ascii=False))

        smart_db = os.path.join(_BASE, "data", "smart_verify.db")
        smart = {
            "images": _pack_table(smart_db, "images", ["file_path"], "smart_uploads"),
            "pairs": _pack_table(smart_db, "pairs", [], ""),
            "results": _pack_table(smart_db, "results", ["vis_path"], "smart_visualizations"),
        }
        zf.writestr("smart.json", json.dumps(smart, ensure_ascii=False))

        rs_db = os.path.join(_BASE, "data", "rs_verify.db")
        # 说明：rs_records 的 before_path/after_path 与 rs_images.file_path 同源，仅随 images 打包一次，
        # 故此处不再把 before/after 列入文件列（避免 zip 体积翻倍）；恢复时按文件名反查后端实例。
        rs = {
            "images": _pack_table(rs_db, "rs_images", ["file_path"], "rs_uploads"),
            "records": _pack_table(rs_db, "rs_records",
                                   ["annotated_image", "excel_path"], "rs_work"),
        }
        zf.writestr("rs.json", json.dumps(rs, ensure_ascii=False))

        # LLM 预设配置（rs_presets）：include_sensitive=False 时 api_key 置空，恢复后需重新填写
        zf.writestr("rs_config.json", json.dumps(
            _pack_presets(rs_db, uid, bool(include_sensitive)), ensure_ascii=False))

        # 人脸识别（face.db）：上传图 + 识别结果（人脸缩略图；不含全局人脸库——库为全局共享配置）
        face_db = os.path.join(_BASE, "data", "face.db")
        face = {
            "uploads": _pack_table(face_db, "face_uploads", ["file_path"], "face_uploads"),
            "results": _pack_table(face_db, "face_results", ["thumb_path"], "face_thumbs"),
        }
        zf.writestr("face.json", json.dumps(face, ensure_ascii=False))
    finally:
        zf.close()
    return buf.getvalue()


def _extract_file(zf: zipfile.ZipFile, rel, dst_dir):
    """从 zip 提取文件到目标目录，返回绝对路径；缺失返回 None"""
    if not rel or rel not in zf.namelist():
        return None
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(rel))
    with zf.open(rel) as src, open(dst, "wb") as out:
        shutil.copyfileobj(src, out)
    return dst


@router.get("/backup")
def api_backup(request: Request, include_sensitive: bool = False):
    """导出完整备份（zip：全部数据 + 图片），可在任意设备/账号导入恢复。
    include_sensitive=True 时连同 LLM 预设的 API Key 一并打包；否则 api_key 置空（恢复后需重填）。"""
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, detail={"code": 401, "msg": "未登录或登录已过期"})
    data = _build_backup_zip(user["id"], user["username"], include_sensitive)
    total = len(data)
    over = total > 283 * 1024 * 1024  # 略低于导入侧 300MB 上限，提前预警
    log_operation(request, "auth.backup",
                  f"user#{user['id']}:{user['username']}(敏感={'含' if include_sensitive else '不含'}"
                  + (f", {total // 1024 // 1024}MB, 超导入上限→可能无法导入回本系统" if over else ""))
    fn = f"backup-{user['username']}-{datetime.now().strftime('%Y%m%d')}.zip"
    from urllib.parse import quote
    headers = {"Content-Disposition": f"attachment; filename=backup.zip; filename*=UTF-8''{quote(fn)}"}
    if over:
        headers["X-Backup-Warning"] = "exceeds_import_limit"
    return StreamingResponse(
        iter([data]), media_type="application/zip", headers=headers)


@router.post("/restore")
async def api_restore(request: Request, file: UploadFile = File(...)):
    """从备份 zip 恢复数据到当前账号（合并追加，不删除现有数据；图片落盘到本设备目录）"""
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, detail={"code": 401, "msg": "未登录或登录已过期"})
    uid, device_id = user["id"], get_device_id(request)
    data = await file.read()
    if len(data) > 300 * 1024 * 1024:
        raise HTTPException(400, detail={"code": 400, "msg": "备份文件过大（上限 300MB）"})
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        raise HTTPException(400, detail={"code": 400, "msg": "无效的备份文件"})
    with zf:
        names = zf.namelist()
        if "detect.json" not in names or "meta.json" not in names:
            raise HTTPException(400, detail={"code": 400, "msg": "无效的备份文件"})
        # 备份归属校验：meta.json 的 username 必须与当前登录账号一致，防止误导入他人数据
        try:
            meta = json.loads(zf.read("meta.json"))
        except Exception:
            meta = {}
        if meta.get("username") and meta.get("username") != user["username"]:
            raise HTTPException(400, detail={"code": 400, "msg": "备份归属账号不匹配，无法导入到当前账号"})
        # 幂等：同一备份文件（backup_id）已导入过该账号则整体跳过，防止重复导入数据翻倍
        backup_id = meta.get("backup_id")
        if backup_id:
            try:
                _lg = sqlite3.connect(DB_PATH)
                try:
                    _lg.execute("CREATE TABLE IF NOT EXISTS restore_logs ("
                                "backup_id TEXT PRIMARY KEY, user_id INTEGER, restored_at TEXT)")
                    _dup = _lg.execute("SELECT 1 FROM restore_logs WHERE backup_id=? AND user_id=?",
                                       (backup_id, uid)).fetchone()
                finally:
                    _lg.close()
            except Exception:
                _dup = None
            if _dup:
                raise HTTPException(400, detail={"code": 400,
                                                 "msg": "检测到该备份已在本账号导入过，已跳过（避免重复数据）"})
        det = json.loads(zf.read("detect.json"))
        smart = json.loads(zf.read("smart.json")) if "smart.json" in names else None
        rs = json.loads(zf.read("rs.json")) if "rs.json" in names else None
        face = json.loads(zf.read("face.json")) if "face.json" in names else None

        # ---- detect（web.db）----
        up_dir = os.path.join(_BASE, "data", "detect_uploads", device_id)
        res_dir = os.path.join(_BASE, "data", "detect_results", device_id)
        with engine.begin() as conn:
            for u in det.get("uploads", []):
                dst = _extract_file(zf, u.get("file_path"), up_dir)
                conn.execute(sa.text(
                    "INSERT INTO detect_uploads (device_id, user_id, filename, stored_name,"
                    " file_path, created_at) VALUES (:d,:u,:f,:s,:p,:c)"),
                    {"d": device_id, "u": uid, "f": u.get("filename") or "",
                     "s": u.get("stored_name") or (os.path.basename(dst) if dst else ""),
                     "p": dst, "c": u.get("created_at") or _now()})
            for r in det.get("records", []):
                paths = {k: _extract_file(zf, r.get(k), res_dir)
                         for k in ("orig_path", "heat_path", "analysis_path", "thumb_path")}
                conn.execute(sa.text(
                    "INSERT INTO detect_records (device_id, user_id, created_at, file, jud, jud_simple,"
                    " manual_jud, note, score, level, area, peak, conf, src, param,"
                    " orig_path, heat_path, analysis_path, thumb_path)"
                    " VALUES (:d,:u,:c,:f,:j,:js,:mj,:n,:sc,:lv,:ar,:pk,:cf,:sr,:pa,:o,:h,:an,:t)"),
                    {"d": device_id, "u": uid, "c": r.get("created_at") or _now(),
                     "f": r.get("file") or "", "j": r.get("jud") or "",
                     "js": r.get("jud_simple") or "", "mj": r.get("manual_jud") or "",
                     "n": r.get("note") or "", "sc": r.get("score"), "lv": r.get("level") or "",
                     "ar": r.get("area"), "pk": r.get("peak"), "cf": r.get("conf"),
                     "sr": r.get("src") or "", "pa": r.get("param") or "",
                     "o": paths["orig_path"], "h": paths["heat_path"],
                     "an": paths["analysis_path"], "t": paths["thumb_path"]})

        # ---- smart（smart_verify.db）----
        if smart:
            s_conn = sqlite3.connect(os.path.join(_BASE, "data", "smart_verify.db"))
            try:
                img_map = {}
                s_upload = os.path.join(_BASE, "data", "smart_uploads", device_id)
                for im in smart.get("images", []):
                    dst = _extract_file(zf, im.get("file_path"), s_upload)
                    cur = s_conn.execute(
                        "INSERT INTO images (device_id, user_id, filename, stored_name, file_path,"
                        " uuid, location_name, photo_type, photo_num, width, height, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (device_id, uid, im.get("filename") or "",
                         im.get("stored_name") or (os.path.basename(dst) if dst else ""),
                         dst, im.get("uuid"), im.get("location_name"), im.get("photo_type"),
                         im.get("photo_num") or 0, im.get("width") or 0, im.get("height") or 0,
                         im.get("created_at")))
                    img_map[im["id"]] = cur.lastrowid
                pair_map = {}
                for p in smart.get("pairs", []):
                    cur = s_conn.execute(
                        "INSERT INTO pairs (device_id, user_id, mode, uuid, location_name,"
                        " pair_index, left_image_id, right_image_id, left_filename,"
                        " right_filename, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (device_id, uid, p.get("mode") or "auto", p.get("uuid"),
                         p.get("location_name"), p.get("pair_index") or 0,
                         img_map.get(p.get("left_image_id")), img_map.get(p.get("right_image_id")),
                         p.get("left_filename"), p.get("right_filename"),
                         p.get("status") or "pending", p.get("created_at")))
                    pair_map[p["id"]] = cur.lastrowid
                s_vis = os.path.join(_BASE, "data", "smart_visualizations", device_id)
                for r in smart.get("results", []):
                    vis = _extract_file(zf, r.get("vis_path"), s_vis)
                    s_conn.execute(
                        "INSERT INTO results (pair_id, device_id, user_id, is_same, confidence,"
                        " total_matches, ransac_inliers, inlier_ratio, method, regions_json,"
                        " keypoints_json, vis_path, manual_override, manual_is_same, manual_note,"
                        " human_judgment, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pair_map.get(r.get("pair_id")), device_id, uid, r.get("is_same"),
                         r.get("confidence"), r.get("total_matches"), r.get("ransac_inliers"),
                         r.get("inlier_ratio"), r.get("method"), r.get("regions_json"),
                         r.get("keypoints_json"), vis, r.get("manual_override") or 0,
                         r.get("manual_is_same"), r.get("manual_note") or "",
                         r.get("human_judgment"), r.get("created_at"), r.get("updated_at")))
                s_conn.commit()
            finally:
                s_conn.close()

        # ---- rs（rs_verify.db）----
        if rs:
            r_conn = sqlite3.connect(os.path.join(_BASE, "data", "rs_verify.db"))
            try:
                r_img_map = {}
                r_upload = os.path.join(_BASE, "data", "rs_uploads", device_id)
                # 上传图 filename → 恢复后绝对路径，供 records 的 before/after 反查引用（恢复关联）
                img_by_name = {}
                for im in rs.get("images", []):
                    dst = _extract_file(zf, im.get("file_path"), r_upload)
                    cur = r_conn.execute(
                        "INSERT INTO rs_images (device_id, user_id, filename, stored_name,"
                        " file_path, position, scenario, created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (device_id, uid, im.get("filename") or "",
                         im.get("stored_name") or (os.path.basename(dst) if dst else ""),
                         dst, im.get("position") or "before",
                         im.get("scenario")
                         or ("classify" if (im.get("position") or "") == "single" else "detect"),
                         im.get("created_at")))
                    r_img_map[im["id"]] = cur.lastrowid
                    img_by_name[im.get("filename")] = dst
                r_work = os.path.join(_BASE, "data", "rs_work", device_id)
                for rec in rs.get("records", []):
                    # 恢复 before/after：优先按文件名关联到已恢复的上传图（同源文件），
                    # 无匹配时才从 zip 内单独提取（兼容旧备份直接把 before/after 打进 rs_work）
                    bpath = img_by_name.get(rec.get("before_file")) \
                        or _extract_file(zf, rec.get("before_path"), r_upload)
                    apath = img_by_name.get(rec.get("after_file")) \
                        or _extract_file(zf, rec.get("after_path"), r_upload)
                    # 标注图落盘到每记录独立的 rec_<随机> 子目录（满足 rec_ 目录约定，
                    # 避免平铺在 rs_work/<device_id>/ 被误删；uuid 目录名保证恢复多记录互不冲突）
                    rec_dir = os.path.join(r_work, f"rec_{uuid.uuid4().hex[:8]}")
                    ann = _extract_file(zf, rec.get("annotated_image"), rec_dir) if rec.get("annotated_image") else None
                    excel = _extract_file(zf, rec.get("excel_path"), r_work) if rec.get("excel_path") else None
                    r_conn.execute(
                        "INSERT INTO rs_records (device_id, user_id, scenario, before_file,"
                        " after_file, before_path, after_path, result_json, model_used,"
                        " conclusion, confidence, annotated_image, excel_path, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (device_id, uid, rec.get("scenario") or "detect", rec.get("before_file"),
                         rec.get("after_file"), bpath, apath,
                         rec.get("result_json"), rec.get("model_used") or "",
                         rec.get("conclusion"), rec.get("confidence"), ann,
                         excel, rec.get("created_at")))
                r_conn.commit()
            finally:
                r_conn.close()

        # ---- 恢复 LLM 预设（rs_presets，独立于 rs 业务数据）：同名去重 ----
        if "rs_config.json" in names:
            _rc = sqlite3.connect(os.path.join(_BASE, "data", "rs_verify.db"))
            try:
                for p in json.loads(zf.read("rs_config.json")):
                    try:
                        dup = _rc.execute(
                            "SELECT 1 FROM rs_presets WHERE user_id=? AND name=?",
                            (uid, p.get("name"))).fetchone()
                    except Exception:
                        dup = None
                    if dup:
                        continue
                    _rc.execute(
                        "INSERT INTO rs_presets (user_id, device_id, name, api, base_url,"
                        " api_key, model_name, local_model_name, max_tokens, temperature,"
                        " local_model_path, local_device, is_active, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (uid, "", p.get("name"),
                         p.get("api") or "openai", p.get("base_url") or "",
                         p.get("api_key") or "", p.get("model_name") or "",
                         p.get("local_model_name") or "",
                         p.get("max_tokens") or 2000, p.get("temperature"),
                         p.get("local_model_path") or "",
                         p.get("local_device") or "cuda", 0, p.get("created_at")))
                _rc.commit()
            finally:
                _rc.close()

        # ---- face（face.db）：上传图 + 识别结果（人脸缩略图）；恢复后可继续识别/重测 ----
        if face:
            f_conn = sqlite3.connect(os.path.join(_BASE, "data", "face.db"))
            try:
                f_up_map = {}
                f_upload = os.path.join(_BASE, "data", "face_uploads", device_id)
                for u in face.get("uploads", []):
                    dst = _extract_file(zf, u.get("file_path"), f_upload)
                    cur = f_conn.execute(
                        "INSERT INTO face_uploads (device_id, user_id, filename, stored_name,"
                        " file_path, status, created_at) VALUES (?,?,?,?,?,?,?)",
                        (device_id, uid, u.get("filename") or "",
                         u.get("stored_name") or (os.path.basename(dst) if dst else ""),
                         dst, u.get("status") or "pending", u.get("created_at")))
                    f_up_map[u["id"]] = cur.lastrowid
                f_thumb = os.path.join(_BASE, "data", "face_thumbs", device_id)
                for r in face.get("results", []):
                    thumb = _extract_file(zf, r.get("thumb_path"), f_thumb)
                    f_conn.execute(
                        "INSERT INTO face_results (device_id, user_id, upload_id, upload_name,"
                        " face_idx, bbox_json, det_score, thumb_path, matched, similarity,"
                        " matched_name, matched_person, candidates_json, manual_name, manual_by,"
                        " embed_json, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (device_id, uid, f_up_map.get(r.get("upload_id")),
                         r.get("upload_name") or "", r.get("face_idx") or 0,
                         r.get("bbox_json") or "", r.get("det_score") or 0, thumb,
                         1 if r.get("matched") else 0, r.get("similarity") or 0,
                         r.get("matched_name") or "", r.get("matched_person") or "",
                         r.get("candidates_json") or "", r.get("manual_name") or "",
                         r.get("manual_by") or "", r.get("embed_json") or "",
                         r.get("created_at"), r.get("updated_at")))
                f_conn.commit()
            finally:
                f_conn.close()

        # 记录本次备份成功恢复（幂等去重依据）；若中途异常则未记录，允许修正后重试
        if backup_id:
            try:
                _lg = sqlite3.connect(DB_PATH)
                try:
                    _lg.execute("CREATE TABLE IF NOT EXISTS restore_logs ("
                                "backup_id TEXT PRIMARY KEY, user_id INTEGER, restored_at TEXT)")
                    _lg.execute("INSERT OR IGNORE INTO restore_logs (backup_id, user_id, restored_at)"
                                " VALUES (?,?,?)", (backup_id, uid, _now()))
                    _lg.commit()
                finally:
                    _lg.close()
            except Exception:
                pass

    log_operation(request, "auth.restore", f"user#{uid}:{user['username']}")
    return {"message": "备份已恢复（合并到当前账号）"}


# ============================================================
# 后台清理线程：过期验证码 / 过期 token
# ============================================================
def _cleanup_loop():
    while True:
        time.sleep(10 * 60)
        try:
            now = datetime.now().isoformat(timespec="seconds")
            with engine.begin() as conn:
                conn.execute(email_codes.delete().where(email_codes.c.expire_at < now))
                conn.execute(tokens.delete().where(tokens.c.expire_at < now))
        except Exception:
            pass


threading.Thread(target=_cleanup_loop, daemon=True).start()
