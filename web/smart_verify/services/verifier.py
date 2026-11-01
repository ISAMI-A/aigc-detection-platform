"""兼容层：SceneVerifier 已抽取到独立核心库 ImageVerifier（Web 与 CLI 共用）。

保留本文件仅为兼容旧 import（`from ..services.verifier import SceneVerifier`），
算法实现见 ImageVerifier/verifier.py，单点维护。
"""

import os
import sys

# services → smart_verify → web → AIGC Detection（核心库所在目录）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ImageVerifier.verifier import SceneVerifier, VerifyOutput  # noqa: E402,F401
