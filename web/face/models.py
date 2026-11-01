"""人脸识别子系统数据模型。

- face_uploads：上传图记录（按 device_id/user_id 双轨归属）
- face_results：识别结果（一行 = 一张人脸；一图多脸多行）
  embed_json 冗余存 512 维特征，人工入库直接复用（免二次推理）
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime

from .database import Base


class FaceUpload(Base):
    """上传图记录"""
    __tablename__ = "face_uploads"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True, default="")   # 归属设备（游客隔离；登录后双轨 user_id）
    user_id = Column(Integer, nullable=True)             # 归属用户（NULL=游客）
    filename = Column(String, nullable=False)            # 原始文件名
    stored_name = Column(String, nullable=False)         # 存储文件名 (uuid.ext)
    file_path = Column(String, nullable=False)           # 绝对路径
    status = Column(String, default="pending")           # pending / done / no_face / error（最新一次识别状态）
    created_at = Column(DateTime, default=datetime.now)


class FaceResult(Base):
    """识别结果（一行 = 一张人脸）"""
    __tablename__ = "face_results"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True, default="")
    user_id = Column(Integer, nullable=True)

    upload_id = Column(Integer, index=True)              # 所属上传图
    upload_name = Column(String, default="")             # 上传图文件名（冗余，列表展示用）
    face_idx = Column(Integer, default=0)                # 图内第几张脸（按面积降序）

    # 检测信息
    bbox_json = Column(Text, default="")                 # {x1,y1,x2,y2}
    det_score = Column(Float, default=0.0)               # 检测置信度
    thumb_path = Column(String, default="")              # 人脸裁剪缩略图路径

    # 识别结果
    matched = Column(Boolean, default=False)             # 是否命中人脸库
    similarity = Column(Float, default=0.0)              # 最佳匹配相似度
    matched_name = Column(String, default="")            # 命中姓名（人工修正后同步更新）
    matched_person = Column(String, default="")          # 命中 person_id
    candidates_json = Column(Text, default="")           # Top-K 候选 JSON

    # 人工修正 / 入库
    manual_name = Column(String, default="")             # 人工输入姓名（修正展示）
    manual_by = Column(String, default="")               # 修正者（user:3）
    embed_json = Column(Text, default="")                # 512 维特征 JSON（人工入库复用，免重推理）

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
