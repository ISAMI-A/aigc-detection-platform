"""
人脸识别模型管理：懒加载单例 + 空闲自动卸载。
===============
参照 web/model_manager.py 思路，但只服务本模块单个 FaceEngine（检测+识别一体），
因此简化为一对 load/unload 的持有者，后台线程负责空闲超时自动卸载释放显存。
"""
import threading
import time

import config
from .face_engine import FaceEngine


class FaceModelManager:
    """持有单个 FaceEngine，首次使用加载，空闲超过阈值自动卸载。"""

    def __init__(self, engine: FaceEngine = None, idle_timeout: float = None):
        self._engine = engine or FaceEngine()
        self._idle_timeout = config.MODEL_IDLE_TIMEOUT if idle_timeout is None else idle_timeout
        self._infer_lock = threading.Lock()     # 全局推理串行锁（防多线程并发挤爆显存）
        self._last_use = time.time()            # 最近一次 acquire 的活跃时间
        self._stop = threading.Event()
        if self._idle_timeout and self._idle_timeout > 0:
            self._thread = threading.Thread(
                target=self._idle_reaper, name="face-idle-reaper", daemon=True)
            self._thread.start()

    @property
    def engine(self) -> FaceEngine:
        return self._engine

    @property
    def infer_lock(self) -> threading.Lock:
        return self._infer_lock

    def acquire(self) -> FaceEngine:
        """获取已加载的引擎（带推理锁，上层用 `with manager.infer_lock:` 包住推理）。"""
        with self._infer_lock:
            self._last_use = time.time()
            self._engine.load()
            return self._engine

    def _idle_reaper(self):
        """后台线程：距最近一次 acquire 超过 idle_timeout 且已加载时，自动卸载释放显存。"""
        while not self._stop.wait(5.0):
            with self._infer_lock:
                if self._engine.loaded and time.time() - self._last_use >= self._idle_timeout:
                    print(f"[人脸] 空闲 {self._idle_timeout:.0f}s 未使用，自动卸载模型")
                    self._engine.unload()

    def release(self):
        """显式卸载引擎并停掉守护线程（进程退出时调用）。"""
        self._stop.set()
        with self._infer_lock:
            self._engine.unload()

    def stats(self) -> dict:
        return {
            "loaded": self._engine.loaded,
            "device": self._engine._device,
            "idle_timeout_s": self._idle_timeout,
        }


# 进程内全局单例
_manager = None
_manager_lock = threading.Lock()


def get_manager() -> FaceModelManager:
    """获取全局模型管理器（进程内单例）。"""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = FaceModelManager()
        return _manager