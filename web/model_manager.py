"""
统一模型管理器：多系统模型集中管理（检测 / 核验 / 未来人脸识别等共用）。

解决的问题：各系统"各管各的模型"，多模型常驻同一进程时内存/显存线性增长。
统一职责：
  1. 懒加载单例 —— get(name, loader, est_gb) 首次调用才加载，之后复用；
  2. 全局串行调度 —— infer() 返回全局推理锁，避免多系统模型并发推理挤爆显存；
  3. 显存预算与 LRU 卸载 —— 超出预算自动卸载最久未用的常驻模型；
  4. 任务记账 —— begin_task/end_task 登记"子进程型"任务（如 TruFor）的显存占用；
  5. 状态查询 —— stats() 供系统设置展示各模型占用。

显存估算（RTX 4060 8GB 实测参考）：
  TruFor（子进程任务型）   ~1.6 GB
  SuperPoint + LightGlue  ~0.5 GB
  RetinaFace + ArcFace    ~1.2 GB（人脸识别，任务型记账：模块内懒加载+空闲300s自动卸载）
默认预算 6GB，多模型叠加仍留有安全余量；预算可在构造时调整。
"""
import subprocess
import threading
import time


DEFAULT_BUDGET_GB = 6.0
# GPU 可用显存低于该值（MB）时阻止启动新的检测/核验任务（防叠加爆显存）
GPU_MIN_FREE_MB = 1500


def gpu_memory() -> dict | None:
    """当前 GPU 显存使用（MB）：优先解析 nvidia-smi（含所有进程如 Ollama），失败回退 torch。"""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"], timeout=5)
        total, used, free = (int(x) for x in out.decode("utf-8").strip().replace(",", " ").split())
        return {"total_mb": total, "used_mb": used, "free_mb": free}
    except Exception:
        try:
            import torch
            if torch.cuda.is_available():
                total = torch.cuda.get_device_properties(0).total_memory // 1024 // 1024
                used = torch.cuda.memory_allocated(0) // 1024 // 1024
                return {"total_mb": total, "used_mb": used, "free_mb": total - used}
        except Exception:
            pass
    return None


def gpu_free_too_low() -> str | None:
    """GPU 可用显存低于阈值时返回阻止提示文案，否则返回 None（供各任务入口检查）。"""
    mem = gpu_memory()
    if mem and mem["free_mb"] < GPU_MIN_FREE_MB:
        return (f"GPU 显存不足（已用 {mem['used_mb'] / 1024:.1f}/{mem['total_mb'] / 1024:.1f} GB），"
                f"请稍等约 1 分钟（模型空闲自动释放）后再试")
    return None


class ModelManager:
    def __init__(self, budget_gb: float = DEFAULT_BUDGET_GB):
        self._budget_gb = budget_gb
        self._meta_lock = threading.RLock()        # 元数据锁（注册表/记账）
        self._infer_lock = threading.Lock()        # 全局推理串行锁
        self._models = {}                          # name -> {model, est_gb, last_used, idle_timeout}
        self._tasks = {}                           # 子进程任务记账: name -> est_gb
        # 空闲自动卸载守护线程：定期回收超过 idle_timeout 未使用的模型（释放 GPU 显存）
        self._reaper_interval = 10.0               # 扫描间隔（秒）
        self._reaper_stop = threading.Event()
        self._reaper = threading.Thread(target=self._reaper_loop, name="model-idle-reaper", daemon=True)
        self._reaper.start()

    def _reaper_loop(self):
        """后台回收：last_used 距今超过 idle_timeout（>0）的模型自动卸载。"""
        while not self._reaper_stop.is_set():
            self._reaper_stop.wait(self._reaper_interval)
            if self._reaper_stop.is_set():
                break
            now = time.time()
            with self._meta_lock:
                expired = [n for n, m in self._models.items()
                           if m.get("idle_timeout", 0) > 0 and now - m["last_used"] >= m["idle_timeout"]]
                for name in expired:
                    m = self._models.pop(name)
                    print(f"[模型管理] 空闲 {m['idle_timeout']:.0f}s 未使用，自动卸载模型: {name}")
                    self._release_gpu(m["model"])

    # ================= 常驻模型（懒加载单例 + LRU 卸载 + 空闲自动卸载） =================
    def get(self, name: str, loader, est_gb: float = 1.0, idle_timeout: float = 0.0):
        """获取模型：未加载则调用 loader() 加载；返回可复用的模型实例。

        idle_timeout > 0 时，模型空闲超过该秒数会被后台线程自动卸载（释放 GPU 显存），
        下次使用再自动加载；0 = 常驻不自动卸载。
        """
        with self._meta_lock:
            if name not in self._models:
                self._evict_if_needed(est_gb)
                print(f"[模型管理] 加载模型: {name}（约 {est_gb} GB，空闲 {idle_timeout:.0f}s 自动卸载）")
                self._models[name] = {
                    "model": loader(), "est_gb": est_gb,
                    "last_used": time.time(), "idle_timeout": idle_timeout,
                }
            self._models[name]["last_used"] = time.time()
            return self._models[name]["model"]

    def _evict_if_needed(self, need_gb: float):
        """当前占用 + need_gb 超预算时，按 LRU 卸载常驻模型并释放 GPU 显存。"""
        total = self._used_gb()
        if total + need_gb <= self._budget_gb:
            return
        names = sorted(self._models, key=lambda n: self._models[n]["last_used"])
        for name in names:
            if total + need_gb <= self._budget_gb:
                break
            m = self._models.pop(name)
            total -= m["est_gb"]
            print(f"[模型管理] 显存超预算（已用 {total + need_gb:.1f}/{self._budget_gb}GB），卸载模型: {name}")
            self._release_gpu(m["model"])

    @staticmethod
    def _release_gpu(model):
        """尽力释放模型占用的 GPU 显存（失败不阻塞）。

        处理两类模型：有 .to() 的 nn.Module（移回 CPU）；无 .to() 的组合对象
        （如 SceneVerifier 内部含 extractor/matcher）通过删除对象 + gc + empty_cache 释放。
        """
        try:
            import gc
            import torch
            for sub in (getattr(model, "extractor", None), getattr(model, "matcher", None),
                        getattr(model, "model", None)):
                try:
                    if sub is not None and hasattr(sub, "to") and hasattr(sub, "eval"):
                        sub.to("cpu")
                except Exception:
                    pass
            if hasattr(model, "to") and hasattr(model, "eval"):
                model.to("cpu")
            del model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def unload(self, name: str):
        """显式卸载指定模型。"""
        with self._meta_lock:
            if name in self._models:
                self._release_gpu(self._models.pop(name)["model"])
                print(f"[模型管理] 已卸载模型: {name}")

    def unload_all(self):
        """卸载全部常驻模型。"""
        with self._meta_lock:
            for name in list(self._models):
                self.unload(name)

    # ================= 子进程型任务记账（如 TruFor） =================
    def begin_task(self, name: str, est_gb: float):
        """子进程任务开始（如 TruFor 推理子进程）时登记显存占用。"""
        with self._meta_lock:
            self._tasks[name] = self._tasks.get(name, 0.0) + est_gb

    def end_task(self, name: str, est_gb: float):
        """子进程任务结束时释放记账。"""
        with self._meta_lock:
            cur = self._tasks.get(name, 0.0)
            self._tasks[name] = max(0.0, cur - est_gb)
            if self._tasks[name] == 0:
                self._tasks.pop(name, None)

    # ================= 全局串行调度 =================
    @property
    def infer(self) -> threading.Lock:
        """全局推理锁：多系统推理互斥，防止并发挤爆显存。用法：with manager.infer: ..."""
        return self._infer_lock

    # ================= 状态查询 =================
    def _used_gb(self) -> float:
        return sum(m["est_gb"] for m in self._models.values()) + sum(self._tasks.values())

    def stats(self) -> dict:
        """模型占用状态（供系统设置/调试展示）。"""
        with self._meta_lock:
            return {
                "budget_gb": self._budget_gb,
                "used_gb": round(self._used_gb(), 2),
                "gpu": gpu_memory(),
                "models": sorted(
                    [{"name": n, "est_gb": m["est_gb"], "type": "常驻"} for n, m in self._models.items()],
                    key=lambda x: -x["est_gb"]),
                "tasks": sorted(
                    [{"name": n, "est_gb": g, "type": "子进程"} for n, g in self._tasks.items()],
                    key=lambda x: -x["est_gb"]),
            }


# 全局单例（进程内共享）
manager = ModelManager()
