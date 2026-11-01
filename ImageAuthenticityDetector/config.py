"""全局配置（仅保留 TruFor 检测所需）"""
import os

# 项目根目录（config.py 所在目录）
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# TruFor 模型路径（相对于项目根目录）
TRUFOR_PATH = os.path.join(_BASE_DIR, "trufor")

# 预处理
MAX_IMAGE_SIZE = 2048
TEMP_DIR = os.path.join(_BASE_DIR, "temp")

# TruFor 篡改等级阈值（微调参数就在这里改，或通过环境变量 TRUFOR_HIGH / TRUFOR_MED 覆盖）
THRESHOLD_FORGERY_HIGH = float(os.environ.get("TRUFOR_HIGH", 0.60))  # 篡改等级"高"阈值
THRESHOLD_FORGERY_MED = float(os.environ.get("TRUFOR_MED", 0.35))    # 篡改等级"中"阈值

# 多指标融合判定参数：篡改概率未达阈值时，若热力图同时满足以下两个条件，判为"疑似篡改"
FUSE_PEAK = float(os.environ.get("TRUFOR_PEAK", 0.8))   # 篡改峰值阈值（热力图最红区域的像素概率）
FUSE_AREA = float(os.environ.get("TRUFOR_AREA", 0.05))  # 篡改面积占比阈值（loc_map 全图均值）

# 连通域散点噪声降级：疑似条件满足但 最大成片占比 < COMP_RATIO 且 有效连通域数 >= COMP_N_SPOTS
# → 判定为散点红点（噪声）而非成片篡改，降级为"否"
COMP_RATIO = float(os.environ.get("TRUFOR_COMP_RATIO", 0.01))  # 最大成片占比下限（低于则认为无成片篡改）
COMP_N_SPOTS = int(os.environ.get("TRUFOR_COMP_SPOTS", 16))    # 散点数量下限（达到则认为全是小点）

# 置信度加权：定位图 loc>=0.5 且 置信度图 conf>=该值 的像素计为"高置信篡改区域"
# （仅作参考列输出，不参与判定；参与判定的指标是 FUSE_PEAK / FUSE_AREA / 连通域）
CONF_THRESHOLD = float(os.environ.get("TRUFOR_CONF", 0.5))
# 连通域分析：面积小于该值（像素数）的连通域视为微噪点忽略（散点块通常 16~64px）
COMP_MIN_AREA = 16

# V2 几何降级（画笔涂鸦圈标注识别）：
# 篡改概率达标（判"是"）时，若热力图满足以下画笔标注特征 → 降级为"否（画笔标注）"：
#   a) 常规线状（mask=loc>=0.5 & conf>=0.5）：最大连通域矩形度<GEOM_RECT 且紧致度<GEOM_SOLID 且面积>=GEOM_MIN_AREA
#   b) 深红线状（mask=loc>=GEOM_LOC_THR，无 conf 限制）：画圈线在热力图上呈深红弧线，
#      但模型对画笔线的置信度 conf 偏低（<0.5），会被 conf 条件滤掉；用高 loc 阈值单独提取
# 校准值来自 testss 全量扫描：a) 命中 0/8/10；b) loc>=0.75 命中 8/11；组合零误报
GEOM_RECT = float(os.environ.get("TRUFOR_GEOM_RECT", 0.25))          # a) 最大连通域矩形度阈值
GEOM_SOLID = float(os.environ.get("TRUFOR_GEOM_SOLID", 0.30))        # a) 最大连通域紧致度阈值
GEOM_MIN_AREA = int(os.environ.get("TRUFOR_GEOM_MIN_AREA", 200))     # a) 最大连通域面积下限（px）
GEOM_LOC_THR = float(os.environ.get("TRUFOR_GEOM_LOC_THR", 0.75))    # b) 深红线状检测 loc 阈值（无 conf）
GEOM_LINE_RATIO = float(os.environ.get("TRUFOR_GEOM_LINE_RATIO", 0.5))  # b) 深红区"线状面积占比"阈值（>=该值判为画笔线）

# V2.2/V2.3 疑似仲裁（深红区占比判据）：
# 热力图满足疑似候选（peak>=FUSE_PEAK 且 area>=FUSE_AREA）时，按 loc>=SUSPECT_LOC_THR（无 conf）
# 的深红区占比二分：
#   - 占比 >= SUSPECT_UP_THR → 升判"是（有篡改痕迹）"（V2.2，真篡改痕迹明显）
#   - 占比 <  SUSPECT_UP_THR → 判"否（深红区过小）"（V2.3，增强图红色区域很小/很少，
#     视为模型未检测出显著篡改，宁缺毋滥，不再保留模棱两可的"疑似"态）
# 依据：真篡改图深红区占比高（testss 升判图 = 1.3%~10.3%），原图误报与未检出（3/4/6/6p）<1%。
# 校准值 0.01 → V2.2 准确率 86.8%（79.2% 升上）；V2.3 消灭疑似中间态，6p 漏判为接受代价。
SUSPECT_LOC_THR = float(os.environ.get("TRUFOR_SUSPECT_LOC_THR", 0.75))  # 疑似仲裁：深红区 loc 阈值（无 conf）
SUSPECT_UP_THR = float(os.environ.get("TRUFOR_SUSPECT_UP_THR", 0.01))    # 疑似仲裁：深红区占比分界（>=升判是，<判否）

# V2.4 边缘误检降级（模型对部分原图的误检特征）：
# 篡改概率达标（判"是"）时，若红色区域(loc>=0.5)主体"完全贴边"——红色直接触及图像边界、
# 红色与边缘之间没有任何蓝色间隔（如 testss 2/13 原图：右边缘整条竖带/竖条）——
# 判定为模型边缘误检，降级"否（边缘误检）"。
# 双条件（缺一不可，避免误伤真篡改）：
#   a) 贴边面积占比：触及图像边界的连通域面积 / 红色总面积 >= EDGE_TOUCH_RATIO
#      （2p 真篡改的红色虽靠近边缘但与边界间有蓝色间隔，贴边占比≈0，天然排除）
#   b) 边缘带红色占比：红色像素落在四周 EDGE_BAND 宽度边缘带内的比例 >= EDGE_BAND_RATIO
#      （排除 1p/10p 等贴边大块却覆盖画面中心的大面积真篡改）
# 校准：testss 22 张判"是"中仅 2/13 命中，其余 20 张（含真篡改 1p/2p/10p/12p/19p）零误伤。
EDGE_BAND = float(os.environ.get("TRUFOR_EDGE_BAND", 0.10))            # 边缘带宽度（图像宽高的比例）
EDGE_TOUCH_RATIO = float(os.environ.get("TRUFOR_EDGE_TOUCH_RATIO", 0.9))  # a) 贴边连通域面积占比阈值
EDGE_BAND_RATIO = float(os.environ.get("TRUFOR_EDGE_BAND_RATIO", 0.5))    # b) 边缘带红色占比阈值
