"""通知中心 · 聊天/好友/公告 子系统（登录用户专属）。

- 身份：仅登录用户可用（游客只读公告走 /api/announcements，见 admin.py）。
  依赖 auth._get_current_user（Bearer header）；图片/zip 下载因 <img>/<a> 无法带
  header，支持 `?token=<明文token>` 鉴权（沿用 B78 思路）。
- 数据表（web.db 主库，与 auth 共用 engine）：
  - chat_requests   好友申请（pending/accepted/declined；同一对未处理唯一）
  - chat_friends    好友关系（双向，规范化 user_a<user_b）
  - chat_conversations  每用户视角会话（owner_id, peer_id；peer_id=0 表示"公告"伪会话）
  - chat_messages   消息（text/image/zip/emoji）；文件落盘 data/chat_files/<user_id>/
- 清理语义：
  - 右键"删除聊天" = 仅删除当前用户视角会话（对方记录保留）
  - 好友列表"删除好友" = 解除关系 + 级联删除该对全部消息与落盘文件（彻底，用户确认）
  - 独立一键清理 = 删除本人全部会话 + 本人全部消息与落盘文件 + 全部好友申请 + 空目录；
    与系统设置"一键清理历史内容"互不影响；保留好友关系
"""
import os
import secrets
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
import sqlalchemy as sa

from auth import engine, users, _get_current_user, _token_hash

router = APIRouter(prefix="/api/chat", tags=["chat"])

_BASE = os.path.dirname(os.path.abspath(__file__))
_CHAT_ROOT = os.path.join(_BASE, "data", "chat_files")

_metadata = sa.MetaData()

chat_requests = sa.Table(
    "chat_requests", _metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("sender_id", sa.Integer, nullable=False, index=True),
    sa.Column("receiver_id", sa.Integer, nullable=False, index=True),
    sa.Column("status", sa.String(16), default="pending"),   # pending/accepted/declined
    sa.Column("created_at", sa.String(32)),
    sa.Column("processed_at", sa.String(32), default=""),
)

chat_friends = sa.Table(
    "chat_friends", _metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_a", sa.Integer, nullable=False),
    sa.Column("user_b", sa.Integer, nullable=False),
    sa.Column("created_at", sa.String(32)),
    sa.UniqueConstraint("user_a", "user_b", name="uq_friend_pair"),
)

chat_conversations = sa.Table(
    "chat_conversations", _metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("owner_id", sa.Integer, nullable=False, index=True),
    sa.Column("peer_id", sa.Integer, nullable=False),         # 好友用户 id；0=公告伪会话
    sa.Column("is_pinned", sa.Integer, default=0),
    sa.Column("unread", sa.Integer, default=0),
    sa.Column("last_msg_at", sa.String(32), default=""),
    sa.Column("created_at", sa.String(32)),
    sa.Column("updated_at", sa.String(32), default=""),
    sa.UniqueConstraint("owner_id", "peer_id", name="uq_conv_owner_peer"),
)

chat_messages = sa.Table(
    "chat_messages", _metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("sender_id", sa.Integer, nullable=False, index=True),
    sa.Column("receiver_id", sa.Integer, nullable=False, index=True),
    sa.Column("msg_type", sa.String(12), default="text"),    # text/image/zip/emoji
    sa.Column("content", sa.Text, default=""),               # 文本/表情 或 文件原始名
    sa.Column("file_path", sa.String(500), default=""),      # 图片/zip 落盘绝对路径
    sa.Column("file_name", sa.String(255), default=""),
    sa.Column("file_size", sa.Integer, default=0),
    sa.Column("is_read", sa.Integer, default=0),
    sa.Column("del_by_sender", sa.Integer, default=0),      # 本人视角删除：发送方清除
    sa.Column("del_by_receiver", sa.Integer, default=0),    # 本人视角删除：接收方清除
    sa.Column("created_at", sa.String(32)),
    sa.Index("ix_msg_conv", "sender_id", "receiver_id"),
)

# 待发附件（两段式发送：先上传排队、点"发送"才落地为消息；仅本人持有，各删各的不影响对方）
chat_pending = sa.Table(
    "chat_pending", _metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Integer, nullable=False, index=True),
    sa.Column("msg_type", sa.String(12), default=""),      # image / zip
    sa.Column("file_path", sa.String(500), default=""),
    sa.Column("file_name", sa.String(255), default=""),
    sa.Column("file_size", sa.Integer, default=0),
    sa.Column("created_at", sa.String(32)),
)

# 公告（与 admin.py 同一物理表，独立 Define 便于本模块查询）
announcements = sa.Table(
    "announcements", _metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("title", sa.String(200), nullable=False),
    sa.Column("content", sa.Text, default=""),
    sa.Column("enabled", sa.Integer, default=1),
    sa.Column("created_at", sa.String(32)),
    sa.Column("updated_at", sa.String(32)),
)

# 公告已读游标（按用户存最新已读公告 id）
ann_read = sa.Table(
    "chat_ann_read", _metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Integer, nullable=False, unique=True),
    sa.Column("last_read_id", sa.Integer, default=0),
)

# 公告投递副本（用户个人数据）：admin 发布/启用公告时惰性投递快照到各用户，
# 之后 admin 关闭/删除/编辑公告不影响用户已收到的副本（各存各的，类似聊天记录）
chat_ann_delivered = sa.Table(
    "chat_ann_delivered", _metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Integer, nullable=False, index=True),
    sa.Column("ann_id", sa.Integer, nullable=False),
    sa.Column("title", sa.String(200), default=""),
    sa.Column("content", sa.Text, default=""),
    sa.Column("created_at", sa.String(32)),
    sa.Column("delivered_at", sa.String(32)),
    sa.UniqueConstraint("user_id", "ann_id"),
)

_metadata.create_all(engine)

# 迁移：chat_messages 补"本人视角删除"标记列（create_all 不会给已有表加列；须在 create_all 之后执行）
with engine.begin() as conn:
    _cms_cols = {r[1] for r in conn.execute(sa.text("PRAGMA table_info(chat_messages)"))}
    if "del_by_sender" not in _cms_cols:
        conn.execute(sa.text("ALTER TABLE chat_messages ADD COLUMN del_by_sender INTEGER DEFAULT 0"))
    if "del_by_receiver" not in _cms_cols:
        conn.execute(sa.text("ALTER TABLE chat_messages ADD COLUMN del_by_receiver INTEGER DEFAULT 0"))

_now = lambda: datetime.now().isoformat(timespec="seconds")


# ============================================================
# 工具
# ============================================================
def _req_user(request: Request) -> dict:
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, detail={"code": 401, "msg": "未登录或登录已过期"})
    return user


def _visible_cond(uid: int):
    """用户 uid 可见的消息条件：一条消息只在"我方那一份"未被本人删除时对我可见。
    （我只看 sender==uid 且未被发送方标记删除、或 receiver==uid 且未被接收方标记删除）"""
    return sa.or_(
        sa.and_(chat_messages.c.sender_id == uid, chat_messages.c.del_by_sender == 0),
        sa.and_(chat_messages.c.receiver_id == uid, chat_messages.c.del_by_receiver == 0),
    )


def _user_from_query_token(request: Request) -> dict:
    """图片/zip 下载鉴权：?token= 明文 → user；fallback 走 header"""
    tok = (request.query_params.get("token") or "").strip()
    if tok:
        th = _token_hash(tok)
        with engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT user_id FROM tokens WHERE token_hash=:t AND expire_at > :now"),
                {"t": th, "now": _now()}).first()
            if row:
                u = conn.execute(sa.select(users).where(users.c.id == row[0])).first()
                if u:
                    return dict(u._mapping)
    return _get_current_user(request)


def _conv_id(user_id: int, peer_id: int):
    with engine.connect() as conn:
        row = conn.execute(sa.select(chat_conversations.c.id).where(
            chat_conversations.c.owner_id == user_id,
            chat_conversations.c.peer_id == peer_id)).first()
        return row[0] if row else None


def _touch_conv(db_conn, user_id: int, peer_id: int, bump_unread: bool = False):
    """更新/创建会话行（复用调用方事务内的 db_conn）；bump_unread=True 用于对方收到消息时 unread+1。
    必须在 send_message/send_file 的 `with engine.begin() as conn:` 事务内调用并传入该 conn，
    否则在事务内再开新的 engine.begin() 会产生并行的 SQLite 写连接 → database is locked。"""
    row = db_conn.execute(sa.select(chat_conversations.c.id, chat_conversations.c.unread).where(
        chat_conversations.c.owner_id == user_id,
        chat_conversations.c.peer_id == peer_id)).first()
    now = _now()
    if row:
        if bump_unread:
            db_conn.execute(chat_conversations.update().where(
                chat_conversations.c.id == row[0]).values(
                unread=row[1] + 1, last_msg_at=now, updated_at=now))
        else:
            db_conn.execute(chat_conversations.update().where(
                chat_conversations.c.id == row[0]).values(last_msg_at=now, updated_at=now))
    else:
        db_conn.execute(chat_conversations.insert().values(
            owner_id=user_id, peer_id=peer_id, is_pinned=0,
            unread=1 if bump_unread else 0, last_msg_at=now,
            created_at=now, updated_at=now))


def _is_friend(a: int, b: int) -> bool:
    lo, hi = min(a, b), max(a, b)
    with engine.connect() as conn:
        return conn.execute(sa.select(sa.func.count()).select_from(chat_friends).where(
            chat_friends.c.user_a == lo, chat_friends.c.user_b == hi)).scalar() or 0


def _delete_pair_messages(me: int, p: int) -> None:
    """彻底删除两用户间全部消息 + 落盘文件 + 清理空目录"""
    with engine.connect() as conn:
        rows = conn.execute(sa.select(chat_messages.c.file_path).where(
            sa.or_(sa.and_(chat_messages.c.sender_id == me, chat_messages.c.receiver_id == p),
                   sa.and_(chat_messages.c.sender_id == p, chat_messages.c.receiver_id == me)))).fetchall()
        paths = {r[0] for r in rows if r[0]}
    with engine.begin() as conn:
        conn.execute(chat_messages.delete().where(sa.or_(
            sa.and_(chat_messages.c.sender_id == me, chat_messages.c.receiver_id == p),
            sa.and_(chat_messages.c.sender_id == p, chat_messages.c.receiver_id == me))))
    _remove_files(paths)


def _remove_files(paths) -> None:
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
                d = os.path.dirname(p)
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
        except OSError:
            pass


# ============================================================
# 好友搜索 / 申请 / 列表
# ============================================================
_ALLOWED_IMG = (".jpg", ".jpeg", ".png", ".gif", ".webp")
_MAX_FILE = 50 * 1024 * 1024  # 单文件 50MB


@router.get("/search")
def search_users(request: Request):
    """按 username / uid 模糊搜索用户（排除自己，仅登录）"""
    me = _req_user(request)
    q = (request.query_params.get("q") or "").strip()
    if not q:
        return {"items": []}
    like = f"%{q}%"
    with engine.connect() as conn:
        rows = conn.execute(sa.select(users).where(
            users.c.id != me["id"],
            sa.or_(users.c.username.like(like), users.c.uid.like(like)),
            users.c.disabled == 0).limit(20)).fetchall()
    return {"items": [_public(r) for r in rows]}


def _public(u) -> dict:
    m = u._mapping if hasattr(u, "_mapping") else u
    return {"id": m["id"], "username": m["username"], "uid": m.get("uid") or ""}


@router.post("/request")
def send_request(payload: dict, request: Request):
    """发送好友申请（对方同意后互为好友；同对未处理申请幂等）"""
    me = _req_user(request)
    peer = int(payload.get("receiver_id") or 0)
    if peer <= 0 or peer == me["id"]:
        raise HTTPException(400, detail={"code": 400, "msg": "不能向自己发送好友申请"})
    with engine.connect() as conn:
        if not conn.execute(sa.select(users.c.id).where(users.c.id == peer)).first():
            raise HTTPException(404, detail={"code": 404, "msg": "用户不存在"})
    if _is_friend(me["id"], peer):
        raise HTTPException(400, detail={"code": 400, "msg": "你们已是好友"})
    now = _now()
    with engine.begin() as conn:
        dup = conn.execute(sa.select(chat_requests.c.id).where(
            sa.or_(sa.and_(chat_requests.c.sender_id == me["id"], chat_requests.c.receiver_id == peer),
                   sa.and_(chat_requests.c.sender_id == peer, chat_requests.c.receiver_id == me["id"])),
            chat_requests.c.status == "pending")).first()
        if dup:
            raise HTTPException(400, detail={"code": 400, "msg": "已有待处理的好友申请"})
        conn.execute(chat_requests.insert().values(
            sender_id=me["id"], receiver_id=peer, status="pending",
            created_at=now))
    return {"ok": True}


@router.get("/requests")
def list_requests(request: Request):
    """好友申请列表：收到的（可同意/拒绝）+ 发送的（状态展示），带 dir 方向标记"""
    me = _req_user(request)
    with engine.connect() as conn:
        inc = conn.execute(sa.select(chat_requests, users.c.username, users.c.uid).join(
            users, users.c.id == chat_requests.c.sender_id
        ).where(chat_requests.c.receiver_id == me["id"])).fetchall()
        out = conn.execute(sa.select(chat_requests, users.c.username, users.c.uid).join(
            users, users.c.id == chat_requests.c.receiver_id
        ).where(chat_requests.c.sender_id == me["id"])).fetchall()
    items = []
    for r in inc:
        m = dict(r._mapping)
        items.append({"id": m["id"], "peer_id": m["sender_id"], "username": m["username"],
                      "uid": m["uid"], "created_at": m["created_at"], "status": m["status"],
                      "dir": "in"})
    for r in out:
        m = dict(r._mapping)
        items.append({"id": m["id"], "peer_id": m["receiver_id"], "username": m["username"],
                      "uid": m["uid"], "created_at": m["created_at"], "status": m["status"],
                      "dir": "out"})
    # 排序：待处理优先，同状态内时间倒序
    items.sort(key=lambda x: (0 if x["status"] == "pending" else 1, x["created_at"] or ""),
               reverse=True)
    return {"items": items}


@router.post("/request/{rid}/handle")
def handle_request(rid: int, payload: dict, request: Request):
    """同意/拒绝好友申请（仅接收者可操作）"""
    me = _req_user(request)
    action = (payload.get("action") or "").strip()
    if action not in ("accept", "decline"):
        raise HTTPException(400, detail={"code": 400, "msg": "action 必须为 accept 或 decline"})
    with engine.begin() as conn:
        row = conn.execute(sa.select(chat_requests).where(chat_requests.c.id == rid)).first()
        if not row:
            raise HTTPException(404, detail={"code": 404, "msg": "申请不存在"})
        m = dict(row._mapping)
        if m["receiver_id"] != me["id"]:
            raise HTTPException(403, detail={"code": 403, "msg": "无权处理该申请"})
        if m["status"] != "pending":
            raise HTTPException(400, detail={"code": 400, "msg": "该申请已处理"})
        now = _now()
        if action == "accept":
            a, b = min(m["sender_id"], m["receiver_id"]), max(m["sender_id"], m["receiver_id"])
            conn.execute(chat_friends.insert().values(user_a=a, user_b=b, created_at=now))
            conn.execute(chat_requests.update().where(chat_requests.c.id == rid).values(
                status="accepted", processed_at=now))
        else:
            conn.execute(chat_requests.update().where(chat_requests.c.id == rid).values(
                status="declined", processed_at=now))
    return {"ok": True}


@router.get("/friends")
def list_friends(request: Request):
    """好友列表：每行含对方 id/username/uid"""
    me = _req_user(request)
    with engine.connect() as conn:
        rows = conn.execute(sa.select(chat_friends.c.user_a, chat_friends.c.user_b).where(
            sa.or_(chat_friends.c.user_a == me["id"], chat_friends.c.user_b == me["id"]))).fetchall()
        ids = []
        for r in rows:
            a, b = r[0], r[1]
            ids.append(b if a == me["id"] else a)
        out = []
        if ids:
            for u in conn.execute(sa.select(users).where(users.c.id.in_(ids))):
                um = u._mapping
                out.append({"id": um["id"], "username": um["username"], "uid": um.get("uid") or ""})
    return {"items": out}


@router.delete("/friend/{friend_id}")
def delete_friend(friend_id: int, request: Request):
    """删除好友：解除关系 + 级联删除该对全部消息与落盘文件（彻底，前端已确认）"""
    me = _req_user(request)
    if friend_id == me["id"]:
        raise HTTPException(400, detail={"code": 400, "msg": "不能删除自己"})
    with engine.begin() as conn:
        a, b = min(me["id"], friend_id), max(me["id"], friend_id)
        cur = conn.execute(sa.select(chat_friends.c.id).where(
            chat_friends.c.user_a == a, chat_friends.c.user_b == b)).first()
        if not cur:
            raise HTTPException(404, detail={"code": 404, "msg": "你们不是好友"})
        conn.execute(chat_friends.delete().where(chat_friends.c.id == cur[0]))
        conn.execute(chat_conversations.delete().where(sa.and_(
            chat_conversations.c.owner_id == me["id"],
            chat_conversations.c.peer_id == friend_id)))
    _delete_pair_messages(me["id"], friend_id)
    return {"ok": True}


# ============================================================
# 会话 / 消息
# ============================================================
@router.get("/conversations")
def list_conversations(request: Request):
    """会话列表（含公告伪会话）：置顶优先，含 last_msg 摘要与 unread"""
    me = _req_user(request)
    with engine.connect() as conn:
        rows = conn.execute(sa.select(chat_conversations).where(
            chat_conversations.c.owner_id == me["id"])).fetchall()
        convs = [dict(r._mapping) for r in rows]
        peer_ids = [c["peer_id"] for c in convs if c["peer_id"] != 0]
        uname = {}
        if peer_ids:
            for u in conn.execute(sa.select(users).where(users.c.id.in_(peer_ids))):
                um = u._mapping
                uname[um["id"]] = {"username": um["username"], "uid": um.get("uid") or ""}
        # 每条会话最近一条消息
        last_map = {}
        for c in convs:
            m = conn.execute(sa.select(chat_messages).where(
                sa.and_(chat_messages.c.sender_id.in_((me["id"], c["peer_id"])),
                        chat_messages.c.receiver_id.in_((me["id"], c["peer_id"])),
                        _visible_cond(me["id"]))
            ).order_by(chat_messages.c.id.desc()).limit(1)).first()
            if m:
                mm = dict(m._mapping)
                last_map[c["id"]] = _msg_summary(mm)
        # 公告未读 & 公告伪会话（头像/摘要由前端渲染）
        ann_rows = _notice_brief(conn, me["id"])
        last_read = _get_last_read_id(conn, me["id"])
        notices_unread = any(a["id"] > last_read for a in ann_rows)

        items = []
        items.append({"peer_id": 0, "peer_name": "系统公告", "peer_uid": "",
                      "is_pinned": True, "unread": 1 if notices_unread else 0,
                      "last_msg_at": (ann_rows[0]["created_at"] if ann_rows else ""),
                      "last_msg": {"type": "text",
                                   "content": (ann_rows[0]["title"] if ann_rows else "")}})
        for c in convs:
            if c["peer_id"] == 0:
                continue
            p = uname.get(c["peer_id"], {})
            items.append({"peer_id": c["peer_id"], "peer_name": p.get("username", "?"),
                          "peer_uid": p.get("uid", ""),
                          "is_pinned": c["is_pinned"], "unread": c["unread"],
                          "last_msg_at": c["last_msg_at"],
                          "last_msg": last_map.get(c["id"], {})})
        # 稳定排序：先按最近消息新→旧，再按类别（公告0/置顶1/普通2）——同类别内保持时间倒序
        items.sort(key=lambda x: x.get("last_msg_at") or "", reverse=True)
        items.sort(key=lambda x: 0 if x["peer_id"] == 0
                   else (1 if x["is_pinned"] else 2))
        return {"items": items, "pending_requests": _pending_count(conn, me["id"])}


def _ensure_ann_delivered(conn, user_id: int):
    """惰性投递：把当前 enabled=1 且用户尚未收到的公告快照写入个人副本。
    已关闭/删除的公告不再投递（新用户看不到）；已投递的副本不受 admin 后续关闭/删除/编辑影响。
    首次投递（含旧版迁移）时重置已读游标——旧版 last_read 存 announcements.id，语义已变为 delivered.id。"""
    existing = conn.execute(sa.select(sa.func.count()).select_from(chat_ann_delivered).where(
        chat_ann_delivered.c.user_id == user_id)).scalar()
    if existing == 0:
        conn.execute(ann_read.delete().where(ann_read.c.user_id == user_id))
    rows = conn.execute(sa.select(announcements.c.id, announcements.c.title,
                                  announcements.c.content, announcements.c.created_at)
                        .where(announcements.c.enabled == 1)).fetchall()
    if not rows:
        return
    have = {r[0] for r in conn.execute(
        sa.select(chat_ann_delivered.c.ann_id).where(chat_ann_delivered.c.user_id == user_id))}
    now = _now()
    for r in rows:
        if r[0] not in have:
            conn.execute(chat_ann_delivered.insert().values(
                user_id=user_id, ann_id=r[0], title=r[1], content=r[2],
                created_at=r[3], delivered_at=now))


def _notice_brief(conn, user_id: int):
    # 惰性投递用独立写事务（调用方多为只读 connect()，不能直接写）
    with engine.begin() as w:
        _ensure_ann_delivered(w, user_id)
    return [dict(r._mapping) for r in conn.execute(
        sa.select(chat_ann_delivered).where(chat_ann_delivered.c.user_id == user_id)
        .order_by(chat_ann_delivered.c.id.desc())).fetchall()]


def _get_last_read_id(conn, user_id: int) -> int:
    row = conn.execute(sa.select(ann_read.c.last_read_id).where(
        ann_read.c.user_id == user_id)).first()
    return row[0] if row else 0


def _pending_count(conn, user_id: int) -> int:
    return conn.execute(sa.select(sa.func.count()).select_from(chat_requests).where(
        chat_requests.c.receiver_id == user_id,
        chat_requests.c.status == "pending")).scalar() or 0


def _msg_summary(m: dict) -> dict:
    t = m.get("msg_type") or "text"
    if t == "image":
        return {"type": "image", "content": "[图片]"}
    if t == "zip":
        return {"type": "zip", "content": m.get("file_name") or "[文件]"}
    return {"type": t, "content": m.get("content") or ""}


@router.post("/conversation/{peer_id}/pin")
def set_pin(peer_id: int, payload: dict, request: Request):
    me = _req_user(request)
    val = 1 if payload.get("pinned") else 0
    with engine.begin() as conn:
        cid = conn.execute(sa.select(chat_conversations.c.id).where(
            chat_conversations.c.owner_id == me["id"],
            chat_conversations.c.peer_id == peer_id)).first()
        if cid:
            conn.execute(chat_conversations.update().where(
                chat_conversations.c.id == cid[0]).values(is_pinned=val))
    return {"ok": True}


@router.delete("/conversation/{peer_id}")
def delete_conversation(peer_id: int, request: Request):
    """右键删除聊天：仅删除当前用户视角会话（对方记录保留）"""
    me = _req_user(request)
    with engine.begin() as conn:
        conn.execute(chat_conversations.delete().where(sa.and_(
            chat_conversations.c.owner_id == me["id"],
            chat_conversations.c.peer_id == peer_id)))
    return {"ok": True}


@router.post("/conversation/{peer_id}/unread")
def mark_unread(peer_id: int, request: Request):
    me = _req_user(request)
    with engine.begin() as conn:
        cid = conn.execute(sa.select(chat_conversations.c.id).where(
            chat_conversations.c.owner_id == me["id"],
            chat_conversations.c.peer_id == peer_id)).first()
        if cid:
            conn.execute(chat_conversations.update().where(
                chat_conversations.c.id == cid[0]).values(unread=1))
    return {"ok": True}


@router.get("/messages")
def get_messages(request: Request):
    """分页拉取与某好友消息（desc，before_id 向前翻页）。返回后标记对方消息已读并清零会话未读"""
    me = _req_user(request)
    # peer 来自 query 属系统边界：非法值（如对象/非数字）按空处理，勿抛 500 刷屏
    try:
        peer = int(request.query_params.get("peer") or 0)
        before = int(request.query_params.get("before_id") or 0)
        limit = min(50, max(1, int(request.query_params.get("limit") or 20)))
    except (TypeError, ValueError):
        return {"items": [], "ts": _now()}
    if peer <= 0 or peer == me["id"]:
        # 非法 peer（含自己）：返回空，避免"自己跟自己聊天"的会话/头部资料
        return {"items": [], "ts": _now()}
    with engine.begin() as conn:
        cond = sa.and_(sa.or_(
            sa.and_(chat_messages.c.sender_id == me["id"], chat_messages.c.receiver_id == peer),
            sa.and_(chat_messages.c.sender_id == peer, chat_messages.c.receiver_id == me["id"])),
            _visible_cond(me["id"]))
        if before:
            cond = sa.and_(cond, chat_messages.c.id < before)
        rows = conn.execute(sa.select(chat_messages).where(cond)
                            .order_by(chat_messages.c.id.desc()).limit(limit)).fetchall()
        items = [dict(r._mapping) for r in reversed(rows)]
        # 标记对方发来的消息已读 + 清零会话未读
        cid = conn.execute(sa.select(chat_conversations.c.id).where(
            chat_conversations.c.owner_id == me["id"],
            chat_conversations.c.peer_id == peer)).first()
        if cid:
            conn.execute(chat_conversations.update().where(
                chat_conversations.c.id == cid[0]).values(unread=0))
        conn.execute(chat_messages.update().where(sa.and_(
            chat_messages.c.sender_id == peer,
            chat_messages.c.receiver_id == me["id"],
            chat_messages.c.is_read == 0)).values(is_read=1))
        # 对方资料（聊天窗头部用）：新建会话即使尚不在会话列表，也能正确显示名称/ID
        pname, puid = "", ""
        prow = conn.execute(sa.select(users).where(users.c.id == peer)).first()
        if prow:
            pm = prow._mapping
            pname = pm.get("username") or ""
            puid = pm.get("uid") or ""
    return {"items": items, "ts": _now(), "peer_name": pname, "peer_uid": puid}


def _send(db_conn, sender: int, receiver: int, msg_type: str, content: str = "",
          file_path: str = "", file_name: str = "", file_size: int = 0) -> int:
    now = _now()
    db_conn.execute(chat_messages.insert().values(
        sender_id=sender, receiver_id=receiver, msg_type=msg_type, content=content,
        file_path=file_path, file_name=file_name, file_size=file_size,
        is_read=0, created_at=now))
    return now


@router.post("/send")
def send_message(payload: dict, request: Request):
    """发送文本/表情消息"""
    me = _req_user(request)
    peer = int(payload.get("peer_id") or 0)
    mtype = (payload.get("msg_type") or "text").strip()
    content = (payload.get("content") or "").strip()
    if peer <= 0 or peer == me["id"]:
        raise HTTPException(400, detail={"code": 400, "msg": "非法接收者"})
    if mtype not in ("text", "emoji"):
        raise HTTPException(400, detail={"code": 400, "msg": "非法消息类型"})
    if not content:
        raise HTTPException(400, detail={"code": 400, "msg": "内容不能为空"})
    if len(content) > 2000:
        raise HTTPException(400, detail={"code": 400, "msg": "消息内容过长"})
    if not _is_friend(me["id"], peer):
        raise HTTPException(400, detail={"code": 400, "msg": "仅好友之间可发送消息"})
    with engine.begin() as conn:
        _send(conn, me["id"], peer, mtype, content)
        _touch_conv(conn, me["id"], peer, bump_unread=False)
        _touch_conv(conn, peer, me["id"], bump_unread=True)
    return {"ok": True}


@router.post("/send_file")
async def send_file(request: Request, peer_id: int = Form(0), file: UploadFile = File(...)):
    """发送图片/zip（参数走 Form；登录、好友校验）"""
    me = _req_user(request)
    peer = int(peer_id or 0)
    if peer <= 0 or peer == me["id"]:
        raise HTTPException(400, detail={"code": 400, "msg": "非法接收者"})
    if not _is_friend(me["id"], peer):
        raise HTTPException(400, detail={"code": 400, "msg": "仅好友之间可发送消息"})
    fname = file.filename or ""
    ext = os.path.splitext(fname)[1].lower()
    if ext == ".zip":
        mtype = "zip"
    elif ext in _ALLOWED_IMG:
        mtype = "image"
    else:
        raise HTTPException(400, detail={"code": 400, "msg": "仅支持图片或 zip 文件"})
    data = await file.read()
    if len(data) > _MAX_FILE:
        raise HTTPException(400, detail={"code": 400, "msg": "文件过大（上限 50MB）"})
    u_dir = os.path.join(_CHAT_ROOT, str(me["id"]), str(peer))
    os.makedirs(u_dir, exist_ok=True)
    stored = f"{secrets.token_hex(8)}{ext}"
    dst = os.path.join(u_dir, stored)
    with open(dst, "wb") as f:
        f.write(data)
    now = _now()
    with engine.begin() as conn:
        conn.execute(chat_messages.insert().values(
            sender_id=me["id"], receiver_id=peer, msg_type=mtype,
            content=fname, file_path=dst, file_name=fname, file_size=len(data),
            is_read=0, created_at=now))
        _touch_conv(conn, me["id"], peer, bump_unread=False)
        _touch_conv(conn, peer, me["id"], bump_unread=True)
    return {"ok": True}


@router.post("/pending/upload")
async def upload_pending(request: Request, file: UploadFile = File(...)):
    """两段式发送·第 1 步：上传附件到本人待发区（不产生消息），返回 pending id 供前端排队展示。
    仅本人持有的待发文件，后续删除/发送互不影响对方。"""
    me = _req_user(request)
    fname = file.filename or ""
    ext = os.path.splitext(fname)[1].lower()
    if ext == ".zip":
        mtype = "zip"
    elif ext in _ALLOWED_IMG:
        mtype = "image"
    else:
        raise HTTPException(400, detail={"code": 400, "msg": "仅支持图片或 zip 文件"})
    data = await file.read()
    if len(data) > _MAX_FILE:
        raise HTTPException(400, detail={"code": 400, "msg": "文件过大（上限 50MB）"})
    pdir = os.path.join(_CHAT_ROOT, str(me["id"]), "pending")
    os.makedirs(pdir, exist_ok=True)
    stored = f"{secrets.token_hex(8)}{ext}"
    dst = os.path.join(pdir, stored)
    with open(dst, "wb") as f:
        f.write(data)
    with engine.begin() as conn:
        res = conn.execute(chat_pending.insert().values(
            user_id=me["id"], msg_type=mtype, file_path=dst,
            file_name=fname, file_size=len(data), created_at=_now()))
        pid = res.inserted_primary_key[0]
    return {"ok": True, "id": pid, "msg_type": mtype,
            "file_name": fname, "file_size": len(data)}


@router.delete("/pending/{pid}")
def delete_pending(pid: int, request: Request):
    """两段式发送·删除本人某个待发附件：删记录 + 删落盘文件（仅本人可删，不影响对方）"""
    me = _req_user(request)
    path = None
    with engine.begin() as conn:
        row = conn.execute(sa.select(chat_pending.c.file_path).where(
            sa.and_(chat_pending.c.id == pid, chat_pending.c.user_id == me["id"]))).first()
        if row:
            path = row[0]
            conn.execute(chat_pending.delete().where(chat_pending.c.id == pid))
    if path:
        _remove_files([path])
    return {"ok": True}


@router.post("/pending/send")
def send_pending(payload: dict, request: Request):
    """两段式发送·第 2 步：把本人待发区的一组附件正式发出（落地为消息 + 触达会话），并清空对应待发记录"""
    me = _req_user(request)
    uid = me["id"]
    peer = int(payload.get("peer_id") or 0)
    ids = [int(x) for x in (payload.get("ids") or [])]
    if peer <= 0 or peer == uid:
        raise HTTPException(400, detail={"code": 400, "msg": "非法接收者"})
    if not ids:
        raise HTTPException(400, detail={"code": 400, "msg": "没有待发附件"})
    if not _is_friend(uid, peer):
        raise HTTPException(400, detail={"code": 400, "msg": "仅好友之间可发送消息"})
    now = _now()
    with engine.begin() as conn:
        rows = conn.execute(sa.select(chat_pending).where(
            sa.and_(chat_pending.c.user_id == uid, chat_pending.c.id.in_(ids)))).fetchall()
        pend = [dict(r._mapping) for r in rows]
        for p in pend:
            conn.execute(chat_messages.insert().values(
                sender_id=uid, receiver_id=peer, msg_type=p["msg_type"],
                content=p["file_name"], file_path=p["file_path"],
                file_name=p["file_name"], file_size=p["file_size"],
                is_read=0, created_at=now))
        if pend:
            conn.execute(chat_pending.delete().where(
                sa.and_(chat_pending.c.user_id == uid, chat_pending.c.id.in_(ids))))
        _touch_conv(conn, uid, peer, bump_unread=False)
        _touch_conv(conn, peer, uid, bump_unread=True)
    return {"ok": True, "count": len(pend)}


@router.get("/file/{msg_id}")
def get_file(msg_id: int, request: Request):
    """下载/预览图片、zip（?token= 鉴权；仅涉事双方可见）"""
    from fastapi.responses import FileResponse
    user = _user_from_query_token(request)
    if not user:
        raise HTTPException(401, detail={"code": 401, "msg": "未登录或登录已过期"})
    with engine.connect() as conn:
        row = conn.execute(sa.select(chat_messages).where(
            chat_messages.c.id == msg_id)).first()
        if not row:
            raise HTTPException(404, detail={"code": 404, "msg": "文件不存在"})
        m = dict(row._mapping)
    if m["sender_id"] != user["id"] and m["receiver_id"] != user["id"]:
        raise HTTPException(403, detail={"code": 403, "msg": "无权访问该文件"})
    if not m["file_path"] or not os.path.exists(m["file_path"]):
        raise HTTPException(404, detail={"code": 404, "msg": "文件已不存（可能已被清理）"})
    fname = m["file_name"] or os.path.basename(m["file_path"])
    return FileResponse(m["file_path"], filename=fname, media_type="application/octet-stream")


# ============================================================
# 公告
# ============================================================
@router.get("/notices")
def get_notices(request: Request):
    """用户个人公告副本（时间升序）+ 已读游标。
    惰性投递当前启用公告到个人副本；已投递副本不受 admin 关闭/删除/编辑影响（各存各的）。"""
    me = _req_user(request)
    with engine.begin() as conn:
        _ensure_ann_delivered(conn, me["id"])
        rows = [dict(r._mapping) for r in conn.execute(
            sa.select(chat_ann_delivered).where(chat_ann_delivered.c.user_id == me["id"])
            .order_by(chat_ann_delivered.c.id.asc())).fetchall()]
        last_read = _get_last_read_id(conn, me["id"])
    return {"items": rows, "last_read": last_read}


@router.post("/notices/read")
def mark_notices_read(payload: dict, request: Request):
    me = _req_user(request)
    ann_id = int(payload.get("ann_id") or 0)
    with engine.begin() as conn:
        row = conn.execute(sa.select(ann_read.c.id, ann_read.c.last_read_id).where(
            ann_read.c.user_id == me["id"])).first()
        if row:
            conn.execute(ann_read.update().where(ann_read.c.id == row[0]).values(
                last_read_id=max(row[1], ann_id)))
        else:
            conn.execute(ann_read.insert().values(user_id=me["id"], last_read_id=ann_id))
    return {"ok": True}


# ============================================================
# 概览（铃铛红点/浮层） + 独立一键清理
# ============================================================
@router.get("/summary")
def summary(request: Request):
    """铃铛浮层/未读：公告未读 + 最近公告 + 最近会话 + 待处理申请数"""
    me = _req_user(request)
    with engine.connect() as conn:
        ann_rows = _notice_brief(conn, me["id"])
        last_read = _get_last_read_id(conn, me["id"])
        notices_unread = any(a["id"] > last_read for a in ann_rows)
        pending = _pending_count(conn, me["id"])
        # 最近会话（top 4，含公告）
        convs = [dict(r._mapping) for r in conn.execute(
            sa.select(chat_conversations).where(chat_conversations.c.owner_id == me["id"])
            .order_by(chat_conversations.c.last_msg_at.desc())).fetchall()]
        peer_ids = [c["peer_id"] for c in convs if c["peer_id"] != 0]
        uname = {}
        if peer_ids:
            for u in conn.execute(sa.select(users).where(users.c.id.in_(peer_ids))):
                um = u._mapping
                uname[um["id"]] = um["username"]
        recent = []
        if ann_rows:
            recent.append({"peer_id": 0, "name": "系统公告",
                           "summary": ann_rows[0]["title"], "unread": 1 if notices_unread else 0})
        for c in convs[:6]:
            if c["peer_id"] == 0:
                continue
            m = conn.execute(sa.select(chat_messages).where(
                sa.and_(chat_messages.c.sender_id.in_((me["id"], c["peer_id"])),
                        chat_messages.c.receiver_id.in_((me["id"], c["peer_id"])),
                        _visible_cond(me["id"]))
            ).order_by(chat_messages.c.id.desc()).limit(1)).first()
            summ = _msg_summary(dict(m._mapping))["content"] if m else ""
            recent.append({"peer_id": c["peer_id"], "name": uname.get(c["peer_id"], "?"),
                           "summary": summ, "unread": c["unread"]})
    total_unread = sum(x["unread"] for x in recent)
    return {"notices_unread": notices_unread, "pending": pending,
            "total_unread": total_unread, "recent": recent,
            "latest_announce": ann_rows[0] if ann_rows else None}


@router.get("/stats")
def chat_stats(request: Request):
    """聊天占用统计（会话/消息/文件 MB）——独立于系统设置统计"""
    me = _req_user(request)
    uid = me["id"]
    with engine.connect() as conn:
        msgs = conn.execute(sa.text(
            "SELECT COUNT(*) FROM chat_messages WHERE sender_id=:u OR receiver_id=:u"),
            {"u": uid}).scalar() or 0
        bytes_ = conn.execute(sa.text(
            "SELECT COALESCE(SUM(file_size),0) FROM chat_messages"
            " WHERE (sender_id=:u OR receiver_id=:u) AND file_size>0"),
            {"u": uid}).scalar() or 0
        convs = conn.execute(sa.text(
            "SELECT COUNT(*) FROM chat_conversations WHERE owner_id=:u"),
            {"u": uid}).scalar() or 0
    return {"conversations": convs, "messages": msgs,
            "bytes": int(bytes_ or 0),
            "mb": round((bytes_ or 0) / 1024 / 1024, 2)}


@router.post("/clear")
def clear_chat(request: Request):
    """独立一键清理：仅清理**本人视角**——把本人发出的消息标记"发送方已删"、本人收到的标记"接收方已删"，
    对方视角不受影响（对方那份仍在）。
    仅当消息被**双方都标记删除**时才物理删除该行并回收落盘文件（此时无人需要它）。
    同时清空本人会话、本人好友申请、本人公告已读游标，并清理本人 chat_files 空目录。保留好友关系。"""
    me = _req_user(request)
    uid = me["id"]
    with engine.begin() as conn:
        # 先标记本人视角删除（本方那一份）
        conn.execute(chat_messages.update().where(
            sa.and_(chat_messages.c.sender_id == uid, chat_messages.c.del_by_sender == 0)
        ).values(del_by_sender=1))
        conn.execute(chat_messages.update().where(
            sa.and_(chat_messages.c.receiver_id == uid, chat_messages.c.del_by_receiver == 0)
        ).values(del_by_receiver=1))
        # 双方都已删除的消息：物理删除并回收文件
        rows = conn.execute(sa.select(chat_messages.c.file_path).where(
            sa.and_(chat_messages.c.del_by_sender == 1, chat_messages.c.del_by_receiver == 1)
        )).fetchall()
        paths = {r[0] for r in rows if r[0]}
        conn.execute(chat_messages.delete().where(
            sa.and_(chat_messages.c.del_by_sender == 1, chat_messages.c.del_by_receiver == 1)))
        conn.execute(chat_conversations.delete().where(
            chat_conversations.c.owner_id == uid))
        conn.execute(chat_requests.delete().where(sa.or_(
            chat_requests.c.sender_id == uid, chat_requests.c.receiver_id == uid)))
        conn.execute(ann_read.delete().where(ann_read.c.user_id == uid))
        conn.execute(chat_ann_delivered.delete().where(chat_ann_delivered.c.user_id == uid))
        # 清空本人待发附件（未发送草稿，仅本人持有）
        for r in conn.execute(sa.select(chat_pending.c.file_path).where(
                chat_pending.c.user_id == uid)):
            _pp = r[0]
            if _pp:
                paths.add(_pp)
        conn.execute(chat_pending.delete().where(chat_pending.c.user_id == uid))
    _remove_files(paths)
    # 清理本人 chat_files 目录下空目录
    me_dir = os.path.join(_CHAT_ROOT, str(uid))
    if os.path.isdir(me_dir):
        for sub in os.listdir(me_dir):
            p = os.path.join(me_dir, sub)
            if os.path.isdir(p) and not os.listdir(p):
                try:
                    os.rmdir(p)
                except OSError:
                    pass
        if not os.listdir(me_dir):
            try:
                os.rmdir(me_dir)
            except OSError:
                pass
    return {"ok": True}