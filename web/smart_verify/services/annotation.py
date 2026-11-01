"""
基于 RANSAC 内点生成区域框和特征点标注。

对匹配内点做 DBSCAN 聚类，每个簇生成一个区域框，
每个内点作为一个特征点（红色圆点）。
"""

import cv2
import numpy as np
from sklearn.cluster import DBSCAN
from typing import Dict


def generate_annotations(
    mkpts0: np.ndarray,
    mkpts1: np.ndarray,
    mask: np.ndarray,
    eps: float = 30.0,
    min_samples: int = 3
) -> Dict:
    """
    输入: mkpts0[N,2], mkpts1[N,2], mask[N,1] (RANSAC 内点掩码)
    输出: 两张图各自的区域框和特征点坐标
    """
    if mask is None:
        return {
            'img1_regions': [], 'img1_keypoints': [],
            'img2_regions': [], 'img2_keypoints': [],
            'match_count': 0
        }

    inlier_idx = mask.ravel().astype(bool)
    pts0 = mkpts0[inlier_idx]
    pts1 = mkpts1[inlier_idx]

    if len(pts0) == 0:
        return {
            'img1_regions': [], 'img1_keypoints': [],
            'img2_regions': [], 'img2_keypoints': [],
            'match_count': 0
        }

    # DBSCAN 聚类（仅在图1上聚类，图2对应点同步分组）
    clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(pts0)
    labels = clustering.labels_

    regions0, regions1 = [], []

    for label in set(labels):
        if label == -1:
            continue       # 噪声点不生成区域框

        idx = (labels == label)
        c0 = pts0[idx]
        c1 = pts1[idx]

        # 图1区域框
        x0, y0, w0, h0 = cv2.boundingRect(c0.astype(np.float32))
        regions0.append({
            'x': int(x0), 'y': int(y0),
            'w': int(w0), 'h': int(h0),
            'point_count': int(idx.sum())
        })

        # 图2区域框
        x1, y1, w1, h1 = cv2.boundingRect(c1.astype(np.float32))
        regions1.append({
            'x': int(x1), 'y': int(y1),
            'w': int(w1), 'h': int(h1),
            'point_count': int(idx.sum())
        })

    return {
        'img1_regions': regions0,
        'img1_keypoints': pts0.tolist(),
        'img2_regions': regions1,
        'img2_keypoints': pts1.tolist(),
        'match_count': len(pts0)
    }
