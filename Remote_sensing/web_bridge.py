#!/usr/bin/env python3
"""
遥感变化核验 · Web 桥接层
========================================
供 web 后端（web/rs_verify/）调用的服务层入口。

设计目标：
  - Remote_sensing 项目更新后，web 功能自动跟随（web 只 import 本模块，不复制算法代码）
  - 打包分发 Remote_sensing 时排除 web 相关内容，本模块随源码一起分发（仅小体积封装）
  - 不修改 Remote_sensing/config.yaml：web 侧通过参数传入自定义配置，由本层生成临时配置文件

用法（web 后端）：
  import sys
  sys.path.insert(0, r"<Remote_sensing 绝对路径>")
  from web_bridge import RemoteAnalyzer

  analyzer = RemoteAnalyzer(rs_dir=r"<Remote_sensing 绝对路径>")
  result = analyzer.analyze(before="...", after="...", scenario="detect",
                            config={"api": "openai", "base_url": "...", "api_key": "...",
                                    "model_name": "...", "max_tokens": 2000, "temperature": 0.2},
                            work_dir=r"<web 输出目录>")
  # result = {status, scenario, before_file, after_file, result: {...}, annotated_image, ...}
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# 默认项目根目录（本文件所在目录）
_RS_DIR = Path(__file__).resolve().parent

# 常见 OpenAI 兼容模型（静态兜底列表，供 web 功能设置页下拉选择；可自行增删，
# Remote_sensing 更新此列表后，web 侧自动跟随）
COMMON_MODELS = [
    # OpenAI
    "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4",
    # DeepSeek
    "deepseek-chat", "deepseek-reasoner", "deepseek-v3",
    # 通义千问（阿里云 MaaS / DashScope）
    "qwen-max", "qwen-plus", "qwen-turbo",
    "qwen-vl-max", "qwen-vl-plus", "qwen3.7-plus",
    "qwen3-vl-8b-instruct", "qwen3-vl-plus", "qwen3-vl-flash",
    # 智谱 GLM
    "glm-4", "glm-4v", "glm-5",
    # Kimi
    "moonshot-v1-8k",
]


class RemoteAnalyzer:
    """遥感变化核验分析器（子进程调用 CLI）"""

    def __init__(self, rs_dir: str | Path = None):
        self.rs_dir = Path(rs_dir) if rs_dir else _RS_DIR
        self.cli = self.rs_dir / "rs_verify.py"
        if not self.cli.exists():
            raise FileNotFoundError(f"未找到 rs_verify.py: {self.cli}")

    # ==================== 公共入口 ====================

    def analyze(
        self,
        before: str | Path,
        after: str | Path,
        scenario: str = "detect",
        config: dict = None,
        work_dir: str | Path = None,
        timeout: int = 600,
    ) -> dict:
        """
        分析一对遥感图（阻塞直到完成）。

        参数:
            before:  旧时/整改前 图片路径
            after:   现在/整改后 图片路径
            scenario: detect（新增构筑物检测）或 verify（整改核验）
            config:   覆盖的 LLM 配置（dict，可选；不传则用 Remote_sensing/config.yaml 默认值）
            work_dir: 输出目录（Excel/标注图/临时配置），默认用系统临时目录
            timeout:  子进程超时（秒），默认 600

        返回:
            {status: "ok"|"error", ...}（成功时包含 result/annotated_image 等）
        """
        scenario = scenario if scenario in ("detect", "verify") else "detect"
        before = Path(before)
        after = Path(after)
        if not before.exists():
            return {"status": "error", "error": f"Before 图片不存在: {before}"}
        if not after.exists():
            return {"status": "error", "error": f"After 图片不存在: {after}"}

        work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="rs_web_"))
        work_dir.mkdir(parents=True, exist_ok=True)

        # 临时目录：中转 JSON 与临时配置文件放这里，分析完即删，不残留到 work_dir
        tmp_dir = Path(tempfile.mkdtemp(prefix="rs_web_tmp_"))

        # 生成临时配置文件（若传了 config），用完即删；不碰 Remote_sensing/config.yaml
        config_path = None
        if config:
            config = self._resolve_local_config(config)
            config_path = tmp_dir / "_rs_web_config.yaml"
            self._write_config(config_path, config)

        # 结构化结果输出文件（子进程通信中转，读取后删除）
        json_out = tmp_dir / "_rs_web_result.json"

        cmd = [
            sys.executable, str(self.cli), scenario,
            "--before", str(before),
            "--after", str(after),
            "--output", str(work_dir),
            "--json-out", str(json_out),
            "--no-excel",   # web 端结果在前端展示并可导出，不需要 CLI 侧冗余 Excel 落盘
        ]
        if config_path:
            cmd += ["--config", str(config_path)]

        try:
            # 子进程设置 UTF-8 IO 编码：rich 输出（如 ▶/✓）在 Windows gbk 控制台下会抛
            # UnicodeEncodeError，强制 utf-8 后输出可被正常捕获解析
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace", env=env,
            )
        except subprocess.TimeoutExpired:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return {"status": "error", "error": f"分析超时（>{timeout}s）"}

        try:
            # 读取结构化结果
            if json_out.exists():
                try:
                    with open(json_out, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["status"] = "ok"
                    data["exit_code"] = proc.returncode
                    return data
                except Exception as e:
                    return {
                        "status": "error",
                        "error": f"JSON 结果解析失败: {e}",
                        "exit_code": proc.returncode,
                        "stderr": proc.stderr[-2000:] if proc.stderr else "",
                    }

            # 分析失败：CLI 输出到 stderr/stdout
            msg = (proc.stderr or proc.stdout or "").strip()
            return {
                "status": "error",
                "error": f"分析失败（exit={proc.returncode}）: {msg[-2000:]}",
                "exit_code": proc.returncode,
            }
        finally:
            # 删除临时配置与中转 JSON（不落盘敏感 key）
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def analyze_single(
        self,
        image: str | Path,
        config: dict = None,
        work_dir: str | Path = None,
        timeout: int = 600,
    ) -> dict:
        """
        单图检测（四乱核验）：调用 CLI classify 命令（阻塞直到完成）。

        参数:
            image:    待检测卫星图路径（带人工标注框）
            config:   覆盖的 LLM 配置（dict，可选）
            work_dir: 输出目录（标注图/临时配置），默认用系统临时目录
            timeout:  子进程超时（秒），默认 600

        返回:
            {status, scenario:"classify", image_file, result:{major_category,...},
             annotated_image, model, conclusion, ...}
        """
        image = Path(image)
        if not image.exists():
            return {"status": "error", "error": f"图片不存在: {image}"}

        work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="rs_web_"))
        work_dir.mkdir(parents=True, exist_ok=True)

        tmp_dir = Path(tempfile.mkdtemp(prefix="rs_web_tmp_"))
        config_path = None
        if config:
            config = self._resolve_local_config(config)
            config_path = tmp_dir / "_rs_web_config.yaml"
            self._write_config(config_path, config)

        json_out = tmp_dir / "_rs_web_result.json"

        cmd = [
            sys.executable, str(self.cli), "classify",
            "--image", str(image),
            "--output", str(work_dir),
            "--json-out", str(json_out),
            "--no-excel",
        ]
        if config_path:
            cmd += ["--config", str(config_path)]

        try:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace", env=env,
            )
        except subprocess.TimeoutExpired:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return {"status": "error", "error": f"分析超时（>{timeout}s）"}

        try:
            if json_out.exists():
                try:
                    with open(json_out, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["status"] = "ok"
                    data["exit_code"] = proc.returncode
                    return data
                except Exception as e:
                    return {
                        "status": "error",
                        "error": f"JSON 结果解析失败: {e}",
                        "exit_code": proc.returncode,
                        "stderr": proc.stderr[-2000:] if proc.stderr else "",
                    }
            msg = (proc.stderr or proc.stdout or "").strip()
            return {
                "status": "error",
                "error": f"分析失败（exit={proc.returncode}）: {msg[-2000:]}",
                "exit_code": proc.returncode,
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ==================== 配置 ====================

    def _resolve_local_config(self, config: dict) -> dict:
        """本地模型配置解析：api=local 时走 OpenAI 兼容通道连本机 Ollama。

        地址/Key/超长等参数全部取自 Remote_sensing/config.yaml（与 CLI 一致），
        用户在前端只需填写 model_name 即可切换本地模型。
        """
        if config.get("api") != "local":
            return config
        try:
            from core.analyzer import load_config
            o = load_config(self.rs_dir / "config.yaml").get("llm", {}).get("openai", {})
        except Exception:
            o = {}
        return {
            "api": "openai",
            "base_url": o.get("base_url", "http://localhost:11434/v1"),
            "api_key": o.get("api_key", "ollama"),
            "model_name": (config.get("local_model_name") or "").strip() or o.get("model_name", ""),
            "max_tokens": o.get("max_tokens", 2000),
            "temperature": o.get("temperature", 0.2),
        }

    @staticmethod
    def _write_config(path: Path, config: dict):
        """把 dict 配置写为 yaml（与 Remote_sensing/config.yaml 的 llm 结构一致）"""
        llm = {
            "llm": {
                "api": config.get("api", "openai"),
                "openai": {
                    "base_url": config.get("base_url", "https://api.openai.com/v1"),
                    "api_key": config.get("api_key", ""),
                    "model_name": config.get("model_name", "gpt-4o"),
                    "max_tokens": int(config.get("max_tokens", 2000)),
                    "temperature": float(config.get("temperature", 0.2)),
                },
                "local": {
                    "model_path": config.get("model_path", "./models/Qwen2-VL-7B"),
                    "device": config.get("device", "cuda"),
                    "max_new_tokens": int(config.get("max_new_tokens", 2048)),
                },
            }
        }
        # JSON 是 YAML 子集，直接写入即可被 yaml.safe_load 解析
        with open(path, "w", encoding="utf-8") as f:
            json.dump(llm, f, ensure_ascii=False, indent=2)

    @staticmethod
    def load_default_config(config_path: str | Path = None) -> dict:
        """读取 Remote_sensing/config.yaml 当前配置（默认值，供 web 设置页初始展示）"""
        from core.analyzer import load_config
        cfg = load_config(config_path) if config_path else load_config(_RS_DIR / "config.yaml")
        llm = cfg.get("llm", {})
        o = llm.get("openai", {})
        l = llm.get("local", {})
        return {
            "api": llm.get("api", "openai"),
            "base_url": o.get("base_url", ""),
            "model_name": o.get("model_name", ""),
            "max_tokens": o.get("max_tokens", 2000),
            "temperature": o.get("temperature", 0.2),
            "local_model_path": l.get("model_path", ""),
            "local_device": l.get("device", "cuda"),
        }

    @staticmethod
    def load_common_models(config_path: str | Path = None) -> list:
        """常见模型静态列表（兜底，供 web 设置页下拉选择）。

        返回 COMMON_MODELS 并合并 config.yaml 当前 model_name（去重、置前）。
        """
        models = list(COMMON_MODELS)
        try:
            cur = RemoteAnalyzer.load_default_config(config_path).get("model_name", "")
            if cur and cur not in models:
                models.insert(0, cur)
        except Exception:
            pass
        return models
