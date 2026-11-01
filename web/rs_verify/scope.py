"""rs_verify 双轨归属过滤（批次3 登录体系）

- 登录用户（user_id 非空）→ 按 user_id 过滤（数据归账号，跨设备可见）
- 游客（user_id 为空）→ 按 user_id IS NULL + device_id 过滤
"""
import sqlalchemy as sa
from typing import Any


def scope(m: Any, user_id, device_id):
    """生成归属过滤条件：登录按 user_id、游客按 user_id IS NULL + device_id"""
    if user_id is not None:
        return m.user_id == user_id
    return sa.and_(m.user_id.is_(None), m.device_id == device_id)
