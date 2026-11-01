"""
人脸识别引擎：RetinaFace 检测/对齐 + ArcFace 特征提取。
===============
设计要点：
  - 模型懒加载：首次调用才加载到 GPU，避免 import 即占用显存
  - 空闲自动卸载：由依赖它的 model_manager 管理，本类只提供 load/unload
  - 输出统一：detect 返回规范化的 bbox + 5 点关键点；embed 返回 512 维 L2 归一化向量
"""
import os
import numpy as np
import torch

import config


# ArcFace 标准 5 点对齐模板（[左眼, 右眼, 鼻尖, 左嘴角, 右嘴角]）
_ARC_FACE_DST = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
     [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


def _kps_is_face(kps: np.ndarray, box) -> bool:
    """关键点几何校验：判断 5 点排列是否像真实人脸（眼-鼻-嘴三角）。

    RetinaFace 对花束/阴影/纹理等误检框，也会输出一组"关键点"，
    但其几何结构通常错乱，不满足"两眼大致水平 + 鼻尖居中偏下 +
    双嘴角更下"的人脸关系。该校验用于把这些结构性误检框剔除。
    """
    x1, y1, x2, y2 = box
    h = y2 - y1
    if h <= 0:
        return False
    (lx, ly), (rx, ry) = kps[0], kps[1]        # 左右眼
    (nx, ny) = kps[2]                          # 鼻尖
    (mlx, mly), (mrx, mry) = kps[3], kps[4]    # 左右嘴角
    eye_d = max(float(np.hypot(rx - lx, ry - ly)), 1e-6)
    # ① 两眼应大致水平
    if abs(ly - ry) > 0.5 * eye_d:
        return False
    # ② 鼻尖应在双眼下方，且横向居中
    if ny <= max(ly, ry) or abs(nx - (lx + rx) / 2) > 1.0 * eye_d:
        return False
    # ③ 双嘴角应在鼻尖之下（纵向有下降）
    if min(mly, mry) <= ny:
        return False
    # ④ 两嘴角间距不宜异常（与眼距同量级即可）
    mouth_d = float(np.hypot(mrx - mlx, mry - mly))
    if mouth_d < 0.3 * eye_d:
        return False
    # ⑤ 眼间距相对框高须在合理区间（过小=框内不可能有人脸眼鼻结构）
    lo, hi = config.KPS_ASPECT
    if not (lo <= eye_d / h <= hi):
        return False
    return True


def _bbox_iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    sa = (ax2 - ax1) * (ay2 - ay1)
    sb = (bx2 - bx1) * (by2 - by1)
    return inter / (sa + sb - inter + 1e-9)


def _nms(faces, iou_thr: float) -> list:
    """贪心非极大值抑制：按置信度降序，剔除与已保留框 IoU 过高的候选。

    抑制同一目标的多余重叠检测框（RetinaFace 在清晰大脸上常输出
    若干偏移变体框），保留最高置信度者。
    """
    keep = []
    for f in sorted(faces, key=lambda x: -x["score"]):
        if all(_bbox_iou(f["bbox"], k["bbox"]) <= iou_thr for k in keep):
            keep.append(f)
    return keep


class FaceEngine:
    """RetinaFace + ArcFace 人脸识别引擎（懒加载，进程内单例复用）。"""

    def __init__(self, device: str = None):
        self._device = device or config.DEVICE
        # 实际设备探测：CUDA 不可用时回退 CPU
        try:
            if self._device == "cuda" and not torch.cuda.is_available():
                self._device = "cpu"
        except Exception:
            self._device = "cpu"
        self._det = None    # 检测模型
        self._rec = None    # 识别模型
        # 权重目录：facexlib 找不到权重时自动下载到这里，需先建好
        os.makedirs(config.WEIGHTS_DIR, exist_ok=True)

    # ==================== 模型加载/卸载 ====================
    @property
    def loaded(self) -> bool:
        return self._det is not None and self._rec is not None

    def load(self):
        """加载检测 + 识别模型到指定设备（幂等）。"""
        if self.loaded:
            return
        from facexlib.detection import init_detection_model
        from facexlib.recognition import init_recognition_model
        self._det = init_detection_model(
            config.DETECT_MODEL, half=False, device=self._device,
            model_rootpath=config.WEIGHTS_DIR)
        self._rec = init_recognition_model(
            config.RECOG_MODEL, half=False, device=self._device,
            model_rootpath=config.WEIGHTS_DIR)
        self._det.eval()
        self._rec.eval()

    def unload(self):
        """卸载模型并释放 GPU 显存（幂等）。"""
        for ref in ("_det", "_rec"):
            m = getattr(self, ref, None)
            if m is not None:
                for sub in (getattr(m, "body", None),):
                    try:
                        if sub is not None and hasattr(sub, "to"):
                            sub.to("cpu")
                        elif sub is None and hasattr(m, "to"):
                            m.to("cpu")
                    except Exception:
                        pass
                try:
                    if hasattr(m, "to"):
                        m.to("cpu")
                except Exception:
                    pass
            setattr(self, ref, None)
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ==================== 检测 ====================
    def _pass_filter(self, face: dict) -> bool:
        """候选框后处理过滤：最小人脸尺寸 + 关键点几何校验。

        作用：在置信度过滤之外兜底，抑制复杂背景/低质量图上
        RetinaFace 的过度检测（花束/阴影/纹理常被误认为人脸）。
        """
        x1, y1, x2, y2 = face["bbox"]
        w, h = x2 - x1, y2 - y1
        if w < config.MIN_FACE_SIZE or h < config.MIN_FACE_SIZE:
            return False
        if config.MIN_KPS_CHECK and not _kps_is_face(face["kps"], face["bbox"]):
            return False
        return True

    def detect(self, img_bgr: np.ndarray):
        """检测图像中的所有人脸。

        参数:
            img_bgr: BGR 图像（cv2.imread / imdecode 结果）
        返回:
            list[dict]: 每人脸 {bbox:[x1,y1,x2,y2], kps:[[x,y]×5], score:float}
            未检测到返回空列表。候选框须通过置信度、最小尺寸与关键点结构过滤。
        """
        if img_bgr is None or img_bgr.size == 0:
            return []
        self.load()
        with torch.no_grad():
            dets = self._det.detect_faces(
                img_bgr, conf_threshold=config.DETECT_THRESHOLD,
                use_origin_size=config.USE_ORIGIN_SIZE)
        faces = []
        for row in dets:
            face = {"bbox": [float(v) for v in row[0:4]],
                    "score": float(row[4])}
            face["kps"] = np.array(row[5:15], dtype=np.float32).reshape(5, 2)
            if not self._pass_filter(face):
                continue
            faces.append(face)
        return _nms(faces, config.NMS_IOU)

    # ==================== 特征提取 ====================
    def _align_face(self, img_bgr: np.ndarray, kps: np.ndarray):
        """按 5 点关键点把正脸对齐裁剪成 112x112 ArcFace 输入。

        注意：必须传 _ARC_FACE_DST.copy()。facexlib 的 matlab_cp2tform.findSimilarity
        内部会对 reference_pts 第一列做原地翻转（xyR = xy 浅引用 bug），若直接传全局
        常量会导致模板被污染、对齐结果奇偶交替（同图两次 embed 特征不一致）。
        """
        from facexlib.detection.align_trans import warp_and_crop_face
        return warp_and_crop_face(
            img_bgr, kps, _ARC_FACE_DST.copy(),
            crop_size=config.FACE_CROP_SIZE, align_type="similarity")

    def embed_face(self, img_bgr: np.ndarray, kps: np.ndarray) -> np.ndarray:
        """提取单张已检测人脸的对齐 512 维特征向量。

        参数:
            img_bgr: BGR 图像
            kps:     5 点关键点 [[x,y]×5]
        返回:
            np.ndarray shape (512,) float32，已 L2 归一化
        """
        self.load()
        face = self._align_face(img_bgr, kps)
        rgb = cv2_bgr_to_rgb(face)
        x = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(self._device)
        with torch.no_grad():
            feats = self._rec(x)
        emb = feats[0].cpu().numpy()
        n = np.linalg.norm(emb)
        return emb / n if n > 0 else emb

    def embed(self, img_bgr: np.ndarray):
        """提取图像中最大的一个（或全部）人脸的 512 维特征。

        参数:
            img_bgr: BGR 图像
        返回:
            list[dict]: 每项 {bbox, score, kps, embed}
        """
        faces = self.detect(img_bgr)
        if not faces:
            return []
        out = []
        for face in faces:
            face["embed"] = self.embed_face(img_bgr, face["kps"])
            out.append(face)
        return out


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度（输入为 L2 归一化向量则等价于点积）。"""
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def cv2_bgr_to_rgb(face: np.ndarray) -> np.ndarray:
    """对齐后的人脸做 ArcFace 预归一化（BGR→RGB、/255、[-1,1]，返回 CHW float32）。"""
    import cv2
    rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return (rgb - 0.5) / 0.5