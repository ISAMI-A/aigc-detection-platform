"""ImageVerifier：点位真实性核验核心库（独立、无 Web 依赖）。

SceneVerifier（SuperPoint + LightGlue + RANSAC 场景判定）与文件名解析，
被 Web（web/smart_verify）与命令行工具（PointVerifier/verify.py）共同引用，
算法单一来源。分发时带上本包 + 依赖即可独立使用。

依赖：torch / lightglue / opencv-python / numpy / Pillow
"""

from .verifier import SceneVerifier, VerifyOutput
from .parser import parse_filename

__all__ = ["SceneVerifier", "VerifyOutput", "parse_filename"]
__version__ = "1.0.0"
