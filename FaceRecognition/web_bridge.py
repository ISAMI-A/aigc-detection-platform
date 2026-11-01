# -*- coding: utf-8 -*-
"""
人脸识别 · Web 桥接层（骨架）
========================================
供 web 后端以子进程方式调用本模块，返回结构化 JSON。与 Remote_sensing/web_bridge.py
同一设计思路：web 只 import 本文件，不复制算法代码；算法更新后 web 自动跟随。

用法（web 后端）：
    import sys
    sys.path.insert(0, r"<FaceRecognition 绝对路径>")
    from web_bridge import FaceRecognizer

    fr = FaceRecognizer(dir=r"<FaceRecognition 绝对路径>")
    fr.register(person="u001", name="张三", image="...")   -> {status, record_id}
    fr.verify(image="a.jpg", image2="b.jpg")               -> {status, similarity, same}
    fr.identify(image="q.jpg")                             -> {status, faces:[{person,name,similarity}]}

设计说明：本骨架为"进程内直调"接口（供演示/预留）。正式 web 集成建议走
Remote_sensing 的子进程 + JSON 中转模式（避免模型多进程各占一份显存），届时在本文件
扩展为 subprocess 封装。当前保留最简可用形态，web 接入阶段再填充。
"""
import os
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import cv2
import numpy as np

from core.model_manager import get_manager
from core.face_db import default_db
from core.face_engine import cosine_similarity
from config import SIMILARITY_THRESHOLD


class FaceRecognizer:
    """人脸识别桥接（进程内直调）。"""

    def __init__(self, dir: str | Path = None):
        self.dir = Path(dir) if dir else _DIR

    # ==================== 内部工具 ====================
    @staticmethod
    def _read(path: str) -> np.ndarray:
        if not os.path.exists(path):
            raise FileNotFoundError(f"图片不存在: {path}")
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"无法解码图片: {path}")
        return img

    def _largest(self, engine, img):
        faces = engine.detect(img)
        if not faces:
            raise RuntimeError("未检测到人脸")
        return max(faces, key=lambda f: (f["bbox"][2]-f["bbox"][0]) * (f["bbox"][3]-f["bbox"][1]))

    # ==================== 公共接口 ====================
    def register(self, person: str, image: str, name: str = None,
                 threshold: float = SIMILARITY_THRESHOLD, **meta) -> dict:
        try:
            engine = get_manager().acquire()
            img = self._read(image)
            face = self._largest(engine, img)
            emb = engine.embed_face(img, face["kps"])
            rid = default_db().register(person, name or person, emb, **meta)
            return {"status": "ok", "record_id": rid, "person": person, "name": name or person}
        except Exception as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    def embed_image(self, image: str) -> dict:
        """提取图中最大人脸的 512 维特征（web 人工入库前查重用）。
        返回 {status, embed(list), bbox, score}；无人脸 status=no_face。"""
        try:
            engine = get_manager().acquire()
            img = self._read(image)
            face = self._largest(engine, img)
            emb = engine.embed_face(img, face["kps"])
            x1, y1, x2, y2 = (int(v) for v in face["bbox"])
            return {"status": "ok", "embed": emb.tolist(), "score": round(face["score"], 4),
                    "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2}}
        except RuntimeError as e:
            return {"status": "no_face", "error": str(e)}
        except Exception as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    def verify(self, image: str, image2: str,
               threshold: float = SIMILARITY_THRESHOLD) -> dict:
        try:
            engine = get_manager().acquire()
            img1 = self._read(image)
            img2 = self._read(image2)
            e1 = engine.embed_face(img1, self._largest(engine, img1)["kps"])
            e2 = engine.embed_face(img2, self._largest(engine, img2)["kps"])
            sim = cosine_similarity(e1, e2)
            return {"status": "ok", "similarity": round(sim, 4),
                    "same": bool(sim >= threshold), "threshold": threshold}
        except Exception as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    def identify(self, image: str, top_k: int = 5,
                 threshold: float = SIMILARITY_THRESHOLD) -> dict:
        try:
            engine = get_manager().acquire()
            db = default_db()
            img = self._read(image)
            faces = engine.detect(img)
            dets = []
            for face in faces:
                emb = engine.embed_face(img, face["kps"])
                cands = db.search(emb, top_k=top_k)
                best = cands[0] if cands and cands[0]["similarity"] >= threshold else None
                x1, y1, x2, y2 = (int(v) for v in face["bbox"])
                dets.append({
                    "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                    "score": round(face["score"], 4),
                    "matched": best,
                    "candidates": cands,
                })
            return {"status": "ok", "face_count": len(dets), "faces": dets}
        except Exception as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}