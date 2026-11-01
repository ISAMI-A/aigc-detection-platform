"""场景核验引擎（独立核心库，Web 与 CLI 共用）。

复用 verify_pairs.py 中 GeometryMatcher 的 SP+LG+RANSAC 逻辑，
但返回更丰富的匹配细节（关键点坐标、内点掩码），供前端 Canvas 标注使用。

支持多角度旋转匹配（0°/90°/180°/270°），自动选取内点数最多的结果。
"""

import os
import cv2
import numpy as np
import torch
from PIL import Image
from dataclasses import dataclass
from typing import Optional

from lightglue import LightGlue, SuperPoint
from lightglue.utils import rbd


@dataclass
class VerifyOutput:
    """核验输出"""
    is_same_scene: bool
    confidence: float
    total_matches: int
    ransac_inliers: int
    inlier_ratio: float
    method: str
    vis_path: Optional[str] = None
    mkpts0: Optional[np.ndarray] = None   # 图1匹配点坐标
    mkpts1: Optional[np.ndarray] = None   # 图2匹配点坐标
    mask: Optional[np.ndarray] = None     # RANSAC 内点掩码
    best_angle: int = 0                   # 最佳匹配角度（0/90/180/270）


class SceneVerifier:
    """场景核验器，沿用 verify_pairs.py 的 SP+LG+RANSAC 策略。"""

    def __init__(self, device='cuda', max_size=1024,
                 min_inliers=12, min_ratio=0.15):
        self.device = torch.device(device)
        self.max_size = max_size
        self.min_inliers = min_inliers
        self.min_ratio = min_ratio

        print("[核验] 加载 SuperPoint + LightGlue ...")
        self.extractor = SuperPoint(max_num_keypoints=2048).eval().to(self.device)
        self.matcher = LightGlue(
            features='superpoint',
            depth_confidence=-1,
            breadth_confidence=-1,
        ).eval().to(self.device)
        self.feat_cache = {}

    def _load(self, path: str, angle: int = 0) -> torch.Tensor:
        """加载图片，支持旋转（0/90/180/270 度）。"""
        img = Image.open(path).convert('RGB')
        if angle == 90:
            img = img.transpose(Image.Transpose.ROTATE_90)
        elif angle == 180:
            img = img.transpose(Image.Transpose.ROTATE_180)
        elif angle == 270:
            img = img.transpose(Image.Transpose.ROTATE_270)
        w, h = img.size
        scale = self.max_size / max(w, h)
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        arr = np.array(img).astype(np.float32) / 255.0
        return torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(self.device)

    def _get_feats(self, path: str, angle: int = 0) -> dict:
        cache_key = f"{path}@rot{angle}"
        if cache_key not in self.feat_cache:
            t = self._load(path, angle)
            with torch.no_grad():
                f = self.extractor.extract(t)
            self.feat_cache[cache_key] = {k: v.cpu() for k, v in f.items()}
        return {k: v.to(self.device) for k, v in self.feat_cache[cache_key].items()}

    def _verify_pair(self, p1: str, p2: str, angle: int = 0,
                     save_vis_dir=None) -> Optional[VerifyOutput]:
        """
        在指定旋转角度下验证两张图片。
        返回 None 表示匹配点太少（total_matches < 8）。
        """
        f0 = self._get_feats(p1, 0)
        f1 = self._get_feats(p2, angle)

        with torch.no_grad():
            m01 = self.matcher({'image0': f0, 'image1': f1})

        f0 = rbd(f0)
        f1 = rbd(f1)
        m01 = rbd(m01)

        kpts0 = f0['keypoints'].cpu().numpy()
        kpts1 = f1['keypoints'].cpu().numpy()
        matches = m01['matches'].cpu().numpy()

        total_matches = len(matches)
        mk0 = kpts0[matches[:, 0]]
        mk1 = kpts1[matches[:, 1]]

        # 匹配点太少时跳过 RANSAC，避免 OpenCV 断言错误
        if total_matches < 8:
            return None

        # 优先 Fundamental Matrix（乡村非平面场景更适用）
        F, mask = cv2.findFundamentalMat(
            mk0, mk1, cv2.USAC_MAGSAC, 5.0,
            confidence=0.99999, maxIters=10000
        )
        if F is not None and mask is not None and mask.sum() >= self.min_inliers:
            inl = int(mask.sum())
            ratio = inl / total_matches
            is_same = ratio >= self.min_ratio
            method = "Fundamental"
        elif total_matches >= 4:
            # 回退 Homography（至少需要 4 个点）
            H, mask = cv2.findHomography(mk0, mk1, cv2.USAC_MAGSAC, 5.0)
            if H is not None and mask is not None:
                inl = int(mask.sum())
                ratio = inl / total_matches
                is_same = inl >= self.min_inliers and ratio >= self.min_ratio
                method = "Homography"
            else:
                inl, ratio, is_same, method, mask = 0, 0.0, False, "RANSAC_Fail", None
        else:
            return None

        # 置信度：内点数的归一化分数
        conf = min(inl / 30.0, 1.0) if inl > 0 else 0.0

        # 可视化图
        vis_path = None
        if save_vis_dir and mk0 is not None and len(mk0) > 0 and mask is not None:
            try:
                vis_path = self._save_visualization(p1, p2, mk0, mk1, mask, save_vis_dir, angle)
            except Exception as e:
                print(f"[可视化] 保存失败: {e}")

        return VerifyOutput(
            is_same, conf, total_matches, inl, ratio, method,
            vis_path, mk0, mk1, mask, best_angle=angle,
        )

    def verify(self, p1: str, p2: str, save_vis_dir=None) -> VerifyOutput:
        """
        验证两张图片是否为同一场景（自动尝试 0/90/180/270° 取最佳结果）。

        返回: VerifyOutput，包含判定结果和匹配细节。
        """
        best = None
        for angle in [0, 90, 180, 270]:
            out = self._verify_pair(p1, p2, angle, save_vis_dir)
            if out is None:
                continue
            if best is None or out.ransac_inliers > best.ransac_inliers:
                best = out

        if best is not None:
            # 标记旋转角度
            if best.best_angle != 0:
                best.method = f"{best.method}_rot{best.best_angle}"
            return best

        # 所有角度都失败（匹配点太少）
        return VerifyOutput(
            is_same_scene=False, confidence=0.0,
            total_matches=0, ransac_inliers=0, inlier_ratio=0.0,
            method="TooFewMatches", best_angle=0,
        )

    def _save_visualization(self, p1, p2, mk0, mk1, mask, save_vis_dir, angle=0):
        os.makedirs(save_vis_dir, exist_ok=True)
        # cv2.imread 不支持中文路径，改用 np.fromfile + imdecode 读取
        im0 = cv2.imdecode(np.fromfile(p1, dtype=np.uint8), cv2.IMREAD_COLOR)
        im1 = cv2.imdecode(np.fromfile(p2, dtype=np.uint8), cv2.IMREAD_COLOR)
        if im0 is None or im1 is None:
            return None

        h0, w0 = im0.shape[:2]
        h1, w1 = im1.shape[:2]
        scale = self.max_size / max(im0.shape[:2])
        if scale < 1.0:
            im0 = cv2.resize(im0, (int(w0 * scale), int(h0 * scale)))
            im1 = cv2.resize(im1, (int(w1 * scale), int(h1 * scale)))

        idx = mask.ravel().astype(bool)
        pts0 = mk0[idx]
        pts1 = mk1[idx]
        kp0 = [cv2.KeyPoint(float(x[0]), float(x[1]), 1) for x in pts0]
        kp1 = [cv2.KeyPoint(float(x[0]), float(x[1]), 1) for x in pts1]
        dm = [cv2.DMatch(i, i, 0) for i in range(len(pts0))]
        vis = cv2.drawMatches(
            im0, kp0, im1, kp1, dm, None,
            flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS
        )

        fname = f"vis_{os.path.basename(p1)}_{os.path.basename(p2)}.jpg"
        out_path = os.path.join(save_vis_dir, fname)
        # cv2.imwrite 不支持中文路径，改用 imencode + tofile 写入
        cv2.imencode('.jpg', vis)[1].tofile(out_path)
        return out_path
