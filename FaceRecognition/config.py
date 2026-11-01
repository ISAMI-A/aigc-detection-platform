"""
人脸识别系统配置
===============
用法：
    from config import FACE_DB_PATH, SIMILARITY_THRESHOLD, ...
"""
import os

# 项目根目录（AIGC Detection/）
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据与模型路径
_FACE_MODULE = os.path.dirname(os.path.abspath(__file__))
WEIGHTS_DIR = os.path.join(_FACE_MODULE, "weights_root")      # 检测/识别模型权重
FACE_DB_PATH = os.path.join(_FACE_MODULE, "face_db", "faces.db")  # 人脸向量库（SQLite）
DATA_DIR = os.path.join(_PROJECT, "data")                     # 人脸数据

# 相似度阈值（余弦相似度 ≥ 该值 判定同一个人）
SIMILARITY_THRESHOLD = 0.45      # 1:1 验证阈值（越高越严格）
IDENTIFY_TOP_K = 5               # 1:N 识别返回 Top-K

# 模型设置
DETECT_MODEL = "retinaface_resnet50"    # facexlib 检测模型（resnet50 版精度更高，抑制复杂背景过度检测）
RECOG_MODEL = "arcface"                 # facexlib 识别模型（ir_se50）
DEVICE = "cuda"                              # 实际可用性由引擎启动时检测，不可用自动回退 cpu
DETECT_THRESHOLD = 0.5                  # 检测置信度阈值（低于该值忽略）
USE_ORIGIN_SIZE = False                 # True 用原图分辨率检测（更准但更慢）

# 候选框后处理过滤（抑制复杂背景/模糊图的过度检测，为置信度过滤兜底）
MIN_FACE_SIZE = 20                      # 人脸框短边最小像素（更小视为误检，跳过）
MIN_KPS_CHECK = True                    # 是否校验 5 点关键点几何结构（眼-鼻-嘴三角）
KPS_ASPECT = (0.2, 1.8)                  # 关键点结构判定：双眼间距/框高的最小与最大容忍比例
NMS_IOU = 0.30                            # 重叠框合并阈值：IoU>该值且更低置信度的候选剔除
MODEL_IDLE_TIMEOUT = 300.0              # 模型空闲多少秒自动卸载释放显存（0=常驻）
MODEL_EST_GB = 1.2                      # 人脸检测+识别两模型估算显存占用（GB）

# 预处理
FACE_CROP_SIZE = (112, 112)      # ArcFace 对齐后裁剪尺寸
ARC_FACE_DST = None              # 由 face_engine 用标准 5 点模板填充