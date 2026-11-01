"""face 双轨归属过滤（与 smart_verify/scope.py 同思路）

- 登录用户（user_id 非空）→ 按 user_id 过滤（数据归账号，跨设备可见）
- 游客（user_id 为空）→ 按 device_id 过滤
"""
from typing import Any


def scope(m: Any, user_id, device_id):
    """生成 ORM 归属过滤条件：登录按 user_id、游客按 device_id"""
    return m.user_id == user_id if user_id is not None else m.device_id == device_id
