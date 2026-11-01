"""功能开关后端拦截（批次5）：纯 ASGI 中间件。

按请求路径前缀判定所属功能（detect/verify/rsverify/face）；
开关关闭时对游客/普通用户返回 1009（403），admin 始终放行（应急恢复）。
豁免：/api/auth/*、/api/admin/*、/api/announcements* 等管理/登录接口不受功能开关影响。
"""
import json
import hashlib
import os
from datetime import datetime
from urllib.parse import urlparse

import sqlalchemy as sa

from admin import get_feature_enabled

# 路径前缀 → 功能名（detect 相关接口前缀较多）
_FEATURE_PREFIX = {
    "detect": ("/api/detect", "/api/export", "/api/params", "/api/cleanup", "/api/models"),
    "verify": ("/smart/api",),
    "rsverify": ("/rsverify/api",),
    "face": ("/face/api",),
}
# 豁免前缀（登录/管理/公告等）
_EXEMPT = ("/api/auth", "/api/admin", "/api/announcements", "/api/health")


def _match_feature(path: str):
    for feature, prefixes in _FEATURE_PREFIX.items():
        if any(path == p or path.startswith(p + "/") for p in prefixes):
            return feature
    return None


def _is_admin(scope) -> bool:
    """解析请求头 Authorization → 是否 admin（feature 关闭时放行）"""
    headers = dict(scope.get("headers") or [])
    auth = headers.get(b"authorization") or b""
    if not auth.startswith(b"Bearer "):
        return False
    token = auth[7:].strip().decode("utf-8", "ignore")
    try:
        _engine = sa.create_engine(
            f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'web.db')}",
            connect_args={"check_same_thread": False})
        th = hashlib.sha256(token.encode()).hexdigest()
        with _engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT u.role FROM tokens t JOIN users u ON u.id=t.user_id "
                "WHERE t.token_hash=:t AND t.expire_at > :now"),
                {"t": th, "now": datetime.now().isoformat(timespec="seconds")}).first()
            return bool(row and row[0] == "admin")
    except Exception:
        return False


class FeatureGateMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        path = urlparse(scope.get("path", "")).path
        if not path.startswith("/api/") and not path.startswith("/smart") and not path.startswith("/rsverify"):
            await self.app(scope, receive, send)
            return
        feature = _match_feature(path)
        if feature and not get_feature_enabled(feature) and not _is_admin(scope):
            body = json.dumps(
                {"code": 1009, "msg": "该功能暂未开放", "data": None},
                ensure_ascii=False).encode("utf-8")
            headers = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ]
            await send({"type": "http.response.start", "status": 403, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
