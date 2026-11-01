"""遥感变化核验子系统数据模型。"""
import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from .database import Base


class UploadImage(Base):
    """上传的图片（Before/After），按场景隔离（detect/verify/classify）"""
    __tablename__ = "rs_images"

    id = Column(Integer, primary_key=True)
    device_id = Column(String(64), default="")          # 归属设备（游客隔离；登录后双轨 user_id）
    user_id = Column(Integer, nullable=True)            # 归属用户（登录体系预留；NULL=游客，批次2 加列）
    filename = Column(String(255), nullable=False)      # 原始文件名
    stored_name = Column(String(255), nullable=False)   # 落盘文件名（uuid 前缀）
    file_path = Column(String(500), nullable=False)     # 绝对路径
    position = Column(String(10), default="before")     # before / after / single
    scenario = Column(String(20), default="detect")     # 上传场景：detect / verify / classify
    created_at = Column(DateTime, default=datetime.datetime.now)


class AnalysisRecord(Base):
    """一次分析结果"""
    __tablename__ = "rs_records"

    id = Column(Integer, primary_key=True)
    device_id = Column(String(64), default="")          # 归属设备（游客隔离；登录后双轨 user_id）
    user_id = Column(Integer, nullable=True)            # 归属用户（登录体系预留；NULL=游客，批次2 加列）
    scenario = Column(String(20), default="detect")     # detect / verify
    before_file = Column(String(255))                   # Before 文件名
    after_file = Column(String(255))                    # After 文件名
    before_path = Column(String(500))                   # Before 绝对路径
    after_path = Column(String(500))                    # After 绝对路径
    result_json = Column(Text)                          # LLM 结构化结果
    model_used = Column(String(255), default="")        # 本次核验实际使用的模型名
    conclusion = Column(String(500))                    # 摘要结论
    confidence = Column(String(20))                     # 置信度文本
    annotated_image = Column(String(500))               # 标注图绝对路径
    excel_path = Column(String(500))                    # CLI 生成的 Excel（可选）
    created_at = Column(DateTime, default=datetime.datetime.now)


class User(Base):
    """平台用户（当前无登录：默认游客 id=1；预留后续登录体系）"""
    __tablename__ = "rs_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.now)


class Preset(Base):
    """预设平台配置（按用户隔离，数据库存储，非写死代码）。

    预设 = 一组完整 LLM 配置（名称 + api/base_url/api_key/模型/参数），
    用户可添加多个、自由切换；is_active=1 的预设为当前生效配置（analyze 使用）。
    user_id 关联 rs_users：预设仅对当前用户生效（游客=独立用户）。
    """
    __tablename__ = "rs_presets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, default=None)        # 归属用户（NULL=游客；登录后按 user_id 跨设备共享）
    device_id = Column(String(64), default="")     # 归属设备（游客=浏览器标识；登录后按账号 user_id）
    name = Column(String(64), nullable=False)          # 预设名称（用户自定义）
    api = Column(String(10), default="openai")         # openai / local
    base_url = Column(String(500), default="")         # OpenAI 兼容 API 地址
    api_key = Column(Text, default="")                 # AES 加密存储
    model_name = Column(String(255), default="")
    local_model_name = Column(String(255), default="")   # 本地模型名（与云端 model_name 独立，互不影响）
    max_tokens = Column(Integer, default=2000)
    temperature = Column(Float, default=0.2)
    local_model_path = Column(String(500), default="")
    local_device = Column(String(20), default="cuda")
    is_active = Column(Integer, default=0)             # 1=当前生效
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now,
                        onupdate=datetime.datetime.now)
