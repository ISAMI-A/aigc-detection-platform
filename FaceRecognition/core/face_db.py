# -*- coding: utf-8 -*-
"""
人脸向量库：基于 SQLite 的特征存储与检索。
===============
表结构（v2，web 集成扩展字段，旧库启动时自动迁移补列）：
    faces(id INTEGER PRIMARY KEY AUTOINCREMENT,
          person_id TEXT NOT NULL,      -- 人员唯一标识（如 p_a1b2c3d4e5f6）
          name TEXT NOT NULL,           -- 显示名（同 person_id 各样本一致，改名为人员级）
          embed BLOB NOT NULL,          -- 512 维 float32 向量（np.ndarray.tobytes）
          thumb_path TEXT DEFAULT '',   -- 人脸照落盘路径（bbox 裁剪缩略图）
          user_id INTEGER,              -- 绑定的 web 账号 id（NULL=未绑定；人脸登录用）
          created_by TEXT DEFAULT '',   -- 创建者（如 user:3 / admin / system）
          created_at TEXT DEFAULT '',   -- 创建时间（ISO 字符串）
          source TEXT DEFAULT '')       -- 来源（web-recog / web-profile / admin）

能力：
  - register（覆盖语义）/ add_sample（追加样本，保留旧样本）
  - search：1:N 检索返回 Top-K 候选 + 余弦相似度（含 v2 元数据）
  - verify：1:1 对两条记录做相似度比对
  - v2：分页+模糊查询、人员改名、按记录/人员/账号删除、账号绑定/解绑
"""
import os
import sqlite3
import threading
import uuid
from datetime import datetime

import numpy as np

import config


def new_person_id() -> str:
    """生成新人员唯一标识。"""
    return "p_" + uuid.uuid4().hex[:12]


def _row_to_item(r) -> dict:
    """sqlite Row → 字典（不含 embed 向量本体，避免无谓反序列化）。"""
    return {"id": r["id"], "person_id": r["person_id"], "name": r["name"],
            "thumb_path": r["thumb_path"] or "", "user_id": r["user_id"],
            "created_by": r["created_by"] or "", "created_at": r["created_at"] or "",
            "source": r["source"] or ""}


class FaceDB:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()      # SQLite 写串行锁（防并发写锁冲突）
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._create_table()

    # ==================== 底层 ====================
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_table(self):
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS faces ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " person_id TEXT NOT NULL,"
                " name TEXT NOT NULL,"
                " embed BLOB NOT NULL,"
                " thumb_path TEXT DEFAULT '',"
                " user_id INTEGER,"
                " created_by TEXT DEFAULT '',"
                " created_at TEXT DEFAULT '',"
                " source TEXT DEFAULT '')")
            # v2 迁移：旧表（仅 id/person_id/name/embed）自动补列
            cols = {r[1] for r in conn.execute("PRAGMA table_info(faces)")}
            for name, decl in [("thumb_path", "TEXT DEFAULT ''"),
                               ("user_id", "INTEGER"),
                               ("created_by", "TEXT DEFAULT ''"),
                               ("created_at", "TEXT DEFAULT ''"),
                               ("source", "TEXT DEFAULT ''")]:
                if name not in cols:
                    conn.execute(f"ALTER TABLE faces ADD COLUMN {name} {decl}")
            conn.commit()

    # ==================== 写入 ====================
    def register(self, person_id: str, name: str, embed: np.ndarray,
                 thumb_path: str = "", user_id: int = None,
                 created_by: str = "", source: str = "") -> int:
        """注册某人脸特征入库。person_id 已存在则覆盖（多张样本用同一 person_id 追加即可，
        覆盖语义是"删除该 id 旧样本后插入"，避免同 id 残留历史特征）。返回记录 id。"""
        embed = self._check_embed(embed)
        with self._lock:
            # person_id 已存在则先清旧样本（覆盖注册）
            with self._conn() as conn:
                conn.execute("DELETE FROM faces WHERE person_id=?", (person_id,))
                cur = conn.execute(
                    "INSERT INTO faces(person_id,name,embed,thumb_path,user_id,created_by,created_at,source)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (person_id, name, embed.tobytes(), thumb_path, user_id,
                     created_by, datetime.now().isoformat(timespec="seconds"), source))
                conn.commit()
                return cur.lastrowid

    def add_sample(self, person_id: str, name: str, embed: np.ndarray,
                   thumb_path: str = "", user_id: int = None,
                   created_by: str = "", source: str = "") -> int:
        """追加一条特征（同一 person_id 保留多条样本，供 1:N 多数累积）。返回记录 id。"""
        embed = self._check_embed(embed)
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    "INSERT INTO faces(person_id,name,embed,thumb_path,user_id,created_by,created_at,source)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (person_id, name, embed.tobytes(), thumb_path, user_id,
                     created_by, datetime.now().isoformat(timespec="seconds"), source))
                conn.commit()
                return cur.lastrowid

    @staticmethod
    def _check_embed(embed: np.ndarray) -> np.ndarray:
        embed = np.asarray(embed, dtype=np.float32)
        if embed.ndim != 1 or embed.shape[0] != 512:
            raise ValueError(f"embed 需为 512 维向量，实际 {embed.shape}")
        return embed

    def delete(self, record_id: int) -> bool:
        """删除指定记录 id，返回是否删除成功。"""
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute("DELETE FROM faces WHERE id=?", (record_id,))
                conn.commit()
                return cur.rowcount > 0

    def delete_ids(self, record_ids: list[int]) -> int:
        """批量删除记录，返回删除条数。"""
        ids = [int(i) for i in record_ids if i is not None]
        if not ids:
            return 0
        with self._lock:
            with self._conn() as conn:
                ph = ",".join("?" * len(ids))
                cur = conn.execute(f"DELETE FROM faces WHERE id IN ({ph})", ids)
                conn.commit()
                return cur.rowcount

    def delete_person(self, person_id: str) -> int:
        """删除某人员全部样本，返回删除条数。"""
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute("DELETE FROM faces WHERE person_id=?", (person_id,))
                conn.commit()
                return cur.rowcount

    def clear(self) -> int:
        """清空全部记录（admin 清空配置数据用），返回删除条数。样本照文件由调用方清理。"""
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute("DELETE FROM faces")
                conn.commit()
                return cur.rowcount

    def rename_person(self, person_id: str, new_name: str) -> int:
        """人员级改名（该 person_id 全部样本同步更新），返回更新条数。"""
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    "UPDATE faces SET name=? WHERE person_id=?", (new_name, person_id))
                conn.commit()
                return cur.rowcount

    # ==================== 账号绑定（人脸登录） ====================
    def bind_user(self, person_id: str, user_id: int) -> int:
        """把人员绑定到 web 账号（该人员全部样本置 user_id，且先解绑该账号旧人员）。"""
        with self._lock:
            with self._conn() as conn:
                conn.execute("UPDATE faces SET user_id=NULL WHERE user_id=?", (user_id,))
                cur = conn.execute(
                    "UPDATE faces SET user_id=? WHERE person_id=?", (user_id, person_id))
                conn.commit()
                return cur.rowcount

    def unbind_user(self, user_id: int) -> int:
        """解绑账号的人脸（保留库记录，仅清 user_id），返回解绑条数。"""
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute("UPDATE faces SET user_id=NULL WHERE user_id=?", (user_id,))
                conn.commit()
                return cur.rowcount

    # ==================== 查询 ====================
    def _all_vectors(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT id,person_id,name,embed FROM faces").fetchall()
        return [{"id": r["id"], "person_id": r["person_id"], "name": r["name"],
                 "embed": np.frombuffer(r["embed"], dtype=np.float32)} for r in rows]

    def search(self, embed: np.ndarray, top_k: int = 5) -> list[dict]:
        """1:N 全库检索，返回按相似度降序的 Top-K 候选。
        每项: {id, person_id, name, similarity, thumb_path, user_id}"""
        query = np.asarray(embed, dtype=np.float32)
        if query.ndim == 2:
            query = query[0]
        qn = float(np.linalg.norm(query))
        if qn == 0:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id,person_id,name,embed,thumb_path,user_id FROM faces").fetchall()
        results = []
        for r in rows:
            e = np.frombuffer(r["embed"], dtype=np.float32)
            sim = float(np.dot(query, e) / (qn * float(np.linalg.norm(e))))
            results.append({"id": r["id"], "person_id": r["person_id"], "name": r["name"],
                            "similarity": sim, "thumb_path": r["thumb_path"] or "",
                            "user_id": r["user_id"]})
        results.sort(key=lambda r: r["similarity"], reverse=True)
        return results[:top_k]

    def verify(self, embed_a: np.ndarray, embed_b: np.ndarray) -> float:
        """1:1 两向量相似度（余弦）。"""
        a = np.asarray(embed_a, dtype=np.float32)
        b = np.asarray(embed_b, dtype=np.float32)
        na = float(np.linalg.norm(a))
        nb = float(np.linalg.norm(b))
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    def list_all(self) -> list[dict]:
        """列出全部记录（不含向量，仅元数据）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id,person_id,name FROM faces ORDER BY person_id,id").fetchall()
        return [{"id": r["id"], "person_id": r["person_id"], "name": r["name"]} for r in rows]

    def list_page(self, q: str = "", page: int = 1, size: int = 20) -> dict:
        """分页 + 模糊搜索（name / person_id / created_by，大小写不敏感）。
        返回 {total, items}；items 不含向量。"""
        q = (q or "").strip()
        where, args = "", []
        if q:
            where = "WHERE name LIKE ? OR person_id LIKE ? OR created_by LIKE ?"
            like = f"%{q}%"
            args = [like, like, like]
        with self._conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM faces {where}", args).fetchone()["c"]
            rows = conn.execute(
                f"SELECT id,person_id,name,thumb_path,user_id,created_by,created_at,source"
                f" FROM faces {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                args + [int(size), (max(1, int(page)) - 1) * int(size)]).fetchall()
        return {"total": total, "items": [_row_to_item(r) for r in rows]}

    def get_record(self, record_id: int) -> dict | None:
        """单条记录元数据（不含向量）。"""
        with self._conn() as conn:
            r = conn.execute(
                "SELECT id,person_id,name,thumb_path,user_id,created_by,created_at,source"
                " FROM faces WHERE id=?", (int(record_id),)).fetchone()
        return _row_to_item(r) if r else None

    def get_embed(self, record_id: int) -> np.ndarray | None:
        """单条记录的 512 维向量。"""
        with self._conn() as conn:
            r = conn.execute("SELECT embed FROM faces WHERE id=?", (int(record_id),)).fetchone()
        return np.frombuffer(r["embed"], dtype=np.float32) if r else None

    def records_by_person(self, person_id: str) -> list[dict]:
        """某人员全部样本元数据。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id,person_id,name,thumb_path,user_id,created_by,created_at,source"
                " FROM faces WHERE person_id=? ORDER BY id", (person_id,)).fetchall()
        return [_row_to_item(r) for r in rows]

    def find_by_user(self, user_id: int) -> list[dict]:
        """账号已绑定的人脸样本（人脸登录/个人资料用）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id,person_id,name,thumb_path,user_id,created_by,created_at,source"
                " FROM faces WHERE user_id=? ORDER BY id", (int(user_id),)).fetchall()
        return [_row_to_item(r) for r in rows]

    def count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM faces").fetchone()
            return int(row["c"])

    def count_persons(self) -> int:
        """人员数（person_id 去重）。"""
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(DISTINCT person_id) AS c FROM faces").fetchone()
            return int(row["c"])


def default_db() -> FaceDB:
    """基于配置的全局默认向量库（进程内复用）。"""
    return FaceDB(config.FACE_DB_PATH)
