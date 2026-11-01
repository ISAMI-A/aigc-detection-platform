"""遥感变化核验 · 分析运行器（调用 Remote_sensing 的 web_bridge）。

Remote_sensing 独立项目（web/../Remote_sensing），web 只通过 sys.path 引用其 web_bridge.py，
算法更新后 web 自动跟随。本文件不复制任何算法代码。
"""
import os
import sys
from pathlib import Path

# Remote_sensing 目录：web/rs_verify/services/runner.py → ../../..  = web → 上上级为项目根，join Remote_sensing
_SERVICES = Path(__file__).resolve().parent          # web/rs_verify/services
_RS_DIR = _SERVICES.parents[2] / "Remote_sensing"    # AIGC Detection/Remote_sensing

if str(_RS_DIR) not in sys.path:
    sys.path.insert(0, str(_RS_DIR))

from web_bridge import RemoteAnalyzer  # noqa: E402


def run_analysis(before_path: str, after_path: str, scenario: str,
                 config: dict, work_dir: str) -> dict:
    """调用 Remote_sensing 分析一对图片（阻塞）。

    返回 RemoteAnalyzer.analyze 的结构化结果（status=ok 含 result/annotated_image 等）。
    """
    analyzer = RemoteAnalyzer(rs_dir=str(_RS_DIR))
    return analyzer.analyze(
        before=before_path,
        after=after_path,
        scenario=scenario,
        config=config,
        work_dir=work_dir,
    )


def run_single_analysis(image_path: str, config: dict, work_dir: str) -> dict:
    """调用 Remote_sensing 单图检测（四乱核验 classify 场景，阻塞）。

    返回 RemoteAnalyzer.analyze_single 的结构化结果。
    """
    analyzer = RemoteAnalyzer(rs_dir=str(_RS_DIR))
    return analyzer.analyze_single(
        image=image_path,
        config=config,
        work_dir=work_dir,
    )


def load_default_config() -> dict:
    """读取 Remote_sensing/config.yaml 当前配置（设置页初始默认值）。"""
    try:
        return RemoteAnalyzer.load_default_config()
    except Exception:
        return {}


def load_common_models() -> list:
    """Remote_sensing 常见模型静态列表（web 设置页模型下拉兜底，更新自动跟随）。"""
    try:
        return RemoteAnalyzer.load_common_models()
    except Exception:
        return []


def load_local_models() -> list:
    """本地 Ollama 已安装模型列表（全局，不按用户/设备隔离）。

    固定请求 Ollama 原生 /api/tags 接口（不读 Remote_sensing/config.yaml 的 base_url，
    避免云端配置覆盖后误拉云端模型列表）。Ollama 未启动/拉取失败时回退到
    config.yaml 的 model_name（至少保证当前默认模型可选）。
    """
    try:
        import httpx
        with httpx.Client(timeout=2, trust_env=False) as client:
            r = client.get(os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") + "/api/tags")
            r.raise_for_status()
        fetched = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
        if fetched:
            return fetched
    except Exception:
        pass
    try:
        return [RemoteAnalyzer.load_default_config()["model_name"]]
    except Exception:
        return []
