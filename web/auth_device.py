"""游客设备标识 + 登录用户双轨解析（供各子系统路由使用）。

- 语义：游客身份 = 本浏览器本缓存（localStorage 的 aigc_device_id）
- 批次3（登录体系）双轨：
  - 请求带有效 `Authorization: Bearer <token>` → 按 user_id（**忽略 X-Device-Id 防伪造**）
  - 无/失效 token → 按 device_id（游客）
  - 已登录请求的 device_id 仍保留返回（登出后回退游客视图，历史游客数据不丢）
- 缺失时返回空串：查询永远匹配不到任何设备数据（相当于空数据），避免意外共享
- 批次5：操作日志（operation_logs）——内存队列 + 后台线程批量写（不阻塞主流程）
"""
import hashlib
import os
import queue
import threading
import time
from datetime import datetime

from fastapi import Request
import sqlalchemy as sa

_BASE = os.path.dirname(os.path.abspath(__file__))
_engine = sa.create_engine(f"sqlite:///{os.path.join(_BASE, 'data', 'web.db')}",
                           connect_args={"check_same_thread": False})


def get_device_id(request: Request) -> str:
    """从请求头取设备标识（游客）；缺失返回空串。"""
    return (request.headers.get("X-Device-Id") or "").strip()


def get_user_id(request: Request):
    """解析 Authorization Bearer token → user_id；无/失效返回 None。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    th = hashlib.sha256(auth[7:].strip().encode()).hexdigest()
    try:
        with _engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT user_id FROM tokens WHERE token_hash=:t AND expire_at > :now"),
                {"t": th, "now": datetime.now().isoformat(timespec="seconds")}).first()
            return row[0] if row else None
    except Exception:
        return None


def get_identity(request: Request):
    """返回 (user_id, device_id) 双轨身份：
    - 有效 token → (user_id, device_id)（device_id 保留，登出回退游客视图用）
    - 无/失效 token → (None, device_id)
    """
    return get_user_id(request), get_device_id(request)


def get_user_id_from_query_or_header(request: Request):
    """query `?token=` 优先（供 <img>/<a> 下载场景），无则走 header Authorization。"""
    tok = (request.query_params.get("token") or "").strip()
    if not tok:
        return get_user_id(request)
    th = hashlib.sha256(tok.encode()).hexdigest()
    try:
        with _engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT user_id FROM tokens WHERE token_hash=:t AND expire_at > :now"),
                {"t": th, "now": datetime.now().isoformat(timespec="seconds")}).first()
            return row[0] if row else None
    except Exception:
        return None


def get_identity_from_img(request: Request):
    """图片/下载类接口专用双轨身份（B135）：<img>/<a> 无法带 header，
    token 与设备标识都从 query 取（`?dev=`/`?token=`），dev 兜底回退请求头。
    - 带有效 ?token= → (user_id, device_id)：登录用户数据归账号，跨设备可见
    - 无 token → (None, device_id)：游客按设备隔离
    """
    user_id = get_user_id_from_query_or_header(request)
    device_id = (request.query_params.get("dev") or get_device_id(request) or "").strip()
    return user_id, device_id


# ============================================================
# 操作日志（批次5）：内存队列 + 后台线程批量写，不阻塞主流程
# ============================================================
_op_queue = queue.Queue(maxsize=1000)
_OP_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    operator_type TEXT,
    operator_id TEXT,
    operator_name TEXT,
    action TEXT,
    target TEXT DEFAULT '',
    result TEXT DEFAULT 'ok',
    ip TEXT DEFAULT '',
    duration_ms INTEGER DEFAULT 0
)
"""
_OP_INDEX_SQL = "CREATE INDEX IF NOT EXISTS ix_oplog_created ON operation_logs(created_at)"


def _init_oplog() -> None:
    with _engine.begin() as conn:
        conn.execute(sa.text(_OP_TABLE_SQL))
        conn.execute(sa.text(_OP_INDEX_SQL))


_init_oplog()


def log_operation(request: Request, action: str, target: str = "",
                  result: str = "ok", duration_ms: int = 0,
                  operator_username: str = None) -> None:
    """记录一条操作日志（入队，立即返回；队列满丢弃最旧一条）。

    operator_username：认证前动作（登录/注册/忘记密码等请求尚未携带 token，
    无法按 token 解析到用户）可显式传入用户名，使操作者显示为用户名而非 device_id。
    """
    try:
        user_id = get_user_id(request)
        if user_id is not None:
            operator_type, operator_id, operator_name = "user", str(user_id), f"user#{user_id}"
            try:
                with _engine.connect() as conn:
                    row = conn.execute(sa.text(
                        "SELECT username FROM users WHERE id=:id"), {"id": user_id}).first()
                if row:
                    operator_name = row[0]
            except Exception:
                pass
        elif operator_username:
            operator_type, operator_id, operator_name = "user", "", operator_username
        else:
            device_id = get_device_id(request)
            operator_type, operator_id, operator_name = "device", device_id, device_id or "?"
        fwd = request.headers.get("X-Forwarded-For", "")
        ip = (fwd.split(",")[0] if fwd else (request.client.host if request.client else "")) or ""
        _op_queue.put({
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "operator_type": operator_type, "operator_id": operator_id,
            "operator_name": operator_name, "action": action,
            "target": target, "result": result, "ip": ip, "duration_ms": int(duration_ms),
        })
    except Exception:
        pass


def _oplog_flush() -> None:
    """把队列中的日志批量写入 SQLite（每 5s 一次）。"""
    while True:
        time.sleep(5)
        try:
            batch = []
            while not _op_queue.empty():
                batch.append(_op_queue.get_nowait())
                if len(batch) >= 200:
                    break
            if not batch:
                continue
            with _engine.begin() as conn:
                conn.execute(sa.text(
                    "INSERT INTO operation_logs (created_at, operator_type, operator_id, operator_name,"
                    " action, target, result, ip, duration_ms) VALUES (:created_at, :operator_type,"
                    " :operator_id, :operator_name, :action, :target, :result, :ip, :duration_ms)"),
                    batch)
        except Exception:
            time.sleep(1)


threading.Thread(target=_oplog_flush, daemon=True).start()

