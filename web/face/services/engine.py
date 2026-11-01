"""人脸引擎桥接层：web 子应用 → FaceRecognition 模块（进程内直调）。

关键设计：
1. **import 隔离**：FaceRecognition 与 ImageAuthenticityDetector 都有顶层 config.py，
   同进程共存时 sys.modules["config"] 会串。导入 face 模块前临时置换/恢复 sys.modules，
   并把 FaceRecognition 目录插到 sys.path[0]（face 的 core.* 内部 `import config`
   按路径优先级取到正确的 config）。
2. **推理调度**：web 全局推理锁 manager.infer（与检测/核验互斥）+ 模块自身
   FaceModelManager.acquire（懒加载 + 300s 空闲自动卸载）；显存以任务型记账
   （begin/end_task，1.2GB，TruFor 同模式）。
3. 人脸裁剪：bbox 外扩 25% 裁剪 + 缩放最长边 224px（结果缩略图/库样本照共用）。
"""
import os
import sys
import threading
from pathlib import Path

import numpy as np

# web 根目录与模块目录
_WEB = Path(__file__).resolve().parents[2]          # web/
_FACE_DIR = _WEB.parent / "FaceRecognition"        # AIGC Detection/FaceRecognition

# 识别阈值（导入模块后从 face config 读取，默认同模块配置）
SIMILARITY_THRESHOLD = 0.45

# 模块导入状态（一次性，线程安全）
_import_lock = threading.Lock()
_imported = False
_face_mgr = None          # FaceRecognition FaceModelManager 单例
_face_db_cls = None       # FaceDB 类
_new_person_id = None     # new_person_id 函数
_cosine_similarity = None

# 库样本照目录（人脸库自治数据，随 faces.db 存放于模块目录）
LIB_THUMB_DIR = _FACE_DIR / "face_db" / "thumbs"


def _ensure_face_modules():
    """导入 FaceRecognition 模块（处理 config 名冲突，一次性）。"""
    global _imported, _face_mgr, _face_db_cls, _new_person_id, _cosine_similarity, SIMILARITY_THRESHOLD
    if _imported:
        return
    with _import_lock:
        if _imported:
            return
        if not _FACE_DIR.exists():
            raise RuntimeError(f"FaceRecognition 模块不存在: {_FACE_DIR}")
        # 置换 sys.modules["config"]：face 的 core.* 必须绑定 FaceRecognition 的 config
        saved = sys.modules.get("config")
        try:
            if saved is not None:
                del sys.modules["config"]
            p = str(_FACE_DIR)
            if p in sys.path:
                sys.path.remove(p)
            sys.path.insert(0, p)
            from core.model_manager import get_manager as _gm
            from core.face_db import FaceDB, new_person_id, default_db
            from core.face_engine import cosine_similarity
            import config as _face_config
            _face_mgr = _gm()
            _face_db_cls = FaceDB
            _new_person_id = new_person_id
            _cosine_similarity = cosine_similarity
            SIMILARITY_THRESHOLD = float(getattr(_face_config, "SIMILARITY_THRESHOLD", 0.45))
            # 触发一次 default_db 实例化（建表/迁移在导入期完成）
            default_db()
        finally:
            # 恢复原 config（detect.py 依赖 ImageAuthenticityDetector 的 config；
            # face 各模块已绑定自己的 config 对象，不受恢复影响）
            if saved is not None:
                sys.modules["config"] = saved
            elif "config" in sys.modules and sys.modules["config"].__file__ and \
                    not sys.modules["config"].__file__.startswith(str(_FACE_DIR)):
                pass  # 保留非 face 的既有缓存（异常路径兜底）
        _imported = True


def face_db():
    """人脸库（faces.db，模块管理；每次新连接，内部有写锁）。"""
    _ensure_face_modules()
    from core.face_db import default_db
    return default_db()


def face_engine():
    """获取已加载的人脸引擎（内部懒加载；需在推理锁内调用）。"""
    _ensure_face_modules()
    return _face_mgr.acquire()


# ============================================================
# 图像工具
# ============================================================

def read_image(path: str) -> np.ndarray:
    """读取图片（中文路径兼容：np.fromfile + imdecode）。"""
    import cv2
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"无法解码图片: {path}")
    return img


def decode_image_bytes(data: bytes) -> np.ndarray:
    """解码图片二进制（上传/摄像头帧）。"""
    import cv2
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码图片数据")
    return img


def crop_face(img: np.ndarray, bbox: list, margin: float = 0.25, max_side: int = 224) -> np.ndarray:
    """按 bbox 外扩裁剪人脸（越界截断），等比缩放到最长边 max_side。"""
    import cv2
    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    x1 = max(0, int(x1 - bw * margin))
    y1 = max(0, int(y1 - bh * margin))
    x2 = min(w, int(x2 + bw * margin))
    y2 = min(h, int(y2 + bh * margin))
    if x2 <= x1 or y2 <= y1:
        return img
    face = img[y1:y2, x1:x2]
    fh, fw = face.shape[:2]
    side = max(fh, fw)
    if side > max_side:
        scale = max_side / side
        face = cv2.resize(face, (max(1, int(fw * scale)), max(1, int(fh * scale))))
    return face


def save_image(img: np.ndarray, path: str) -> str:
    """保存图片（中文路径兼容：imencode + tofile）。"""
    import cv2
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ext = os.path.splitext(path)[1] or ".jpg"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise ValueError(f"图片编码失败: {path}")
    buf.tofile(path)
    return path


def save_face_crop(img: np.ndarray, bbox: list, dir_path: str, prefix: str = "f") -> str:
    """裁剪并落盘人脸图，返回绝对路径（uuid 文件名）。"""
    import uuid as _uuid
    face = crop_face(img, bbox)
    return save_image(face, os.path.join(dir_path, f"{prefix}_{_uuid.uuid4().hex}.jpg"))


# ============================================================
# 推理入口（统一走 web 全局推理锁 + 模块锁）
# ============================================================

def recognize_faces(img: np.ndarray) -> list[dict]:
    """检测 + 提取图中全部人脸特征。

    返回每脸: {bbox:[x1,y1,x2,y2], score, kps, embed(np.ndarray 512)}
    按面积降序（主要人物在前）。需在 manager.infer 锁内调用（推理锁互斥）。
    """
    _ensure_face_modules()
    engine = _face_mgr.acquire()   # 模块锁内懒加载
    faces = engine.detect(img)
    out = []
    for face in faces:
        emb = engine.embed_face(img, face["kps"])
        out.append({"bbox": [float(v) for v in face["bbox"]],
                    "score": float(face["score"]), "kps": face["kps"], "embed": emb})
    out.sort(key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]),
             reverse=True)
    return out


def embed_largest_face(img: np.ndarray) -> tuple[np.ndarray, dict] | tuple[None, None]:
    """提取最大人脸特征（人脸登录/个人资料录入用）。

    返回 (embed, det)；无人脸返回 (None, None)。
    """
    _ensure_face_modules()
    engine = _face_mgr.acquire()
    faces = engine.detect(img)
    if not faces:
        return None, None
    face = max(faces, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
    emb = engine.embed_face(img, face["kps"])
    return emb, {"bbox": [float(v) for v in face["bbox"]], "score": float(face["score"])}


# ============================================================
# 人脸库便捷操作
# ============================================================

def search_face(embed, top_k: int = 5) -> list[dict]:
    """人脸库 1:N 检索（不走推理，纯库查询）。"""
    return face_db().search(embed, top_k=top_k)


def duplicate_check(embed, new_name: str, threshold: float = None) -> dict | None:
    """入库查重：命中同名人员返回 None；命中相似但不同名人员返回冲突信息。"""
    threshold = SIMILARITY_THRESHOLD if threshold is None else threshold
    cands = face_db().search(embed, top_k=1)
    if not cands:
        return None
    top = cands[0]
    if top["similarity"] < threshold:
        return None
    if top["name"] == new_name:
        return None   # 同名同人 → 视为补样本，无需确认
    return {"person_id": top["person_id"], "name": top["name"],
            "similarity": round(top["similarity"], 4), "user_id": top["user_id"],
            "record_id": top["id"]}


def lib_thumb_path(record_id: int) -> str:
    """库样本照标准路径（faces.db 同目录 thumbs/）。"""
    return str(LIB_THUMB_DIR / f"{record_id}.jpg")


def delete_lib_thumbs(paths: list[str]) -> None:
    """删除库样本照文件（不存在忽略）。"""
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass
