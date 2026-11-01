from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime
from datetime import datetime
from .database import Base


class ImageRecord(Base):
    """图片元数据"""
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True, default="")   # 归属设备（游客隔离；登录后双轨 user_id）
    user_id = Column(Integer, nullable=True)             # 归属用户（登录体系预留；NULL=游客，批次2 加列）
    filename = Column(String, nullable=False)          # 原始文件名
    stored_name = Column(String, nullable=False)       # 存储文件名 (uuid.ext)
    file_path = Column(String, nullable=False)         # 绝对路径
    uuid = Column(String, index=True)                  # 从文件名解析的 UUID
    location_name = Column(String)                     # 地点名称
    photo_type = Column(String)                        # 整改图 / 暗访图
    photo_num = Column(Integer, default=0)             # 图片编号
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


class Pair(Base):
    """配对关系（三种模式都会生成）"""
    __tablename__ = "pairs"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True, default="")   # 归属设备（游客隔离；登录后双轨 user_id）
    user_id = Column(Integer, nullable=True)             # 归属用户（登录体系预留；NULL=游客，批次2 加列）
    mode = Column(String, default="auto")              # auto / sequential / manual
    uuid = Column(String, index=True)                  # 自动配对时记录的 UUID
    location_name = Column(String)                     # 地点名称
    pair_index = Column(Integer, default=0)            # 配对编号
    left_image_id = Column(Integer, nullable=True)
    right_image_id = Column(Integer, nullable=True)
    left_filename = Column(String)
    right_filename = Column(String)
    status = Column(String, default="pending")         # pending / running / done / error / missing
    created_at = Column(DateTime, default=datetime.now)


class VerificationResult(Base):
    """核验结果"""
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, index=True)
    pair_id = Column(Integer, index=True)
    device_id = Column(String, index=True, default="")   # 归属设备（游客隔离；登录后双轨 user_id）
    user_id = Column(Integer, nullable=True)             # 归属用户（登录体系预留；NULL=游客，批次2 加列）

    # 算法结果
    is_same = Column(Boolean)
    confidence = Column(Float)
    total_matches = Column(Integer)
    ransac_inliers = Column(Integer)
    inlier_ratio = Column(Float)
    method = Column(String)
    regions_json = Column(Text)           # 区域框坐标 JSON
    keypoints_json = Column(Text)         # 特征点坐标 JSON
    vis_path = Column(String)

    # 人工修正
    manual_override = Column(Boolean, default=False)
    manual_is_same = Column(Boolean, nullable=True)
    manual_note = Column(String, default="")

    # 人工复核判断（不覆盖机器结果，用于准确率对比）
    human_judgment = Column(Boolean, nullable=True)   # True=同一场景 False=不同 None=未判断

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
