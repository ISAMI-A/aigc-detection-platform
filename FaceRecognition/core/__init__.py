"""
FaceRecognition.core：人脸识别引擎 + 向量库 + 模型管理。

对外统一入口：
    from core.face_engine import FaceEngine, cosine_similarity
    from core.face_db import FaceDB, default_db
    from core.model_manager import get_manager
"""
from .face_engine import FaceEngine, cosine_similarity
from .face_db import FaceDB, default_db
from .model_manager import get_manager

__all__ = ["FaceEngine", "cosine_similarity", "FaceDB", "default_db", "get_manager"]