"""
大模型分析器
支持 OpenAI 兼容 API 和本地模型（预留接口）
"""

import base64
import io
import json
import re
import time
from pathlib import Path
from typing import Optional

import yaml


def load_config(config_path: str | Path = "config.yaml") -> dict:
    """加载 YAML 配置文件"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# 发送给大模型的图片压缩参数（体积和速度的关键）
# 1600：遥感图常见 1595px 边长，缩到 1024 会丢失红框内小目标细节导致误判（见踩坑日志 #8）
MAX_IMAGE_SIZE = 1600   # 最长边像素（超过则等比缩小）
JPEG_QUALITY = 85       # JPEG 压缩质量（webp 转换例外，见 _encode_image）


def _encode_image(image_path: str | Path) -> str:
    """
    将图片编码为 base64 data URL。
    - 小图（<150KB）且非 webp → 原样发送，避免转码膨胀
    - webp 一律转高质量 JPEG（quality=95，本地 Ollama/llama.cpp 后端对 webp 的
      base64 解码支持不佳，会报 "Failed to load image or audio file"；webp→JPEG
      只能做有损转换，95 为视觉无损，兼顾体积与保真）
    - 大图 → 等比缩放到 MAX_IMAGE_SIZE 并转 JPEG 压缩，减小上传体积、加快模型推理
    """
    import os

    from PIL import Image

    ext = Path(image_path).suffix.lower().lstrip(".")

    # 小图且非 webp：原样发送（WebP/PNG 压缩率高的图，转 JPEG 反而变大）
    if ext != "webp" and os.path.getsize(image_path) < 150 * 1024:
        with open(image_path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        mime = f"image/{ext}" if ext else "image/png"
        return f"data:{mime};base64,{data}"

    # 大图或 webp：等比缩放 + JPEG 压缩（webp 用高质量保真，其余按 JPEG_QUALITY）
    img = Image.open(image_path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > MAX_IMAGE_SIZE:
        scale = MAX_IMAGE_SIZE / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    quality = 95 if ext == "webp" else JPEG_QUALITY
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    data = base64.b64encode(buf.getvalue()).decode()
    img.close()

    return f"data:image/jpeg;base64,{data}"


class LLMAnalyzer:
    """大模型分析器"""

    def __init__(self, config_path: str | Path = "config.yaml"):
        cfg = load_config(config_path)
        self.llm_cfg = cfg["llm"]
        self.api_type = self.llm_cfg["api"]

        if self.api_type == "openai":
            import httpx

            openai_cfg = self.llm_cfg["openai"]
            # 禁用 httpx 环境代理（trust_env=False）：本机 Ollama（localhost）与国内 API 直连，
            # 避免系统 HTTP_PROXY 把 localhost 请求也走代理导致连接失败
            self._http = httpx.Client(trust_env=False, timeout=600)
            self.base_url = openai_cfg["base_url"].rstrip("/")
            self.api_key = openai_cfg.get("api_key", "")
            self.model_name = openai_cfg["model_name"]
            # Kimi API 用 max_completion_tokens（max_tokens 已弃用，传了会 400）
            self.max_tokens = openai_cfg.get("max_tokens")
            self.max_completion_tokens = openai_cfg.get("max_completion_tokens")
            # temperature：Kimi k2.6 固定值不可改（传错会 400），不配则不传
            self.temperature = openai_cfg.get("temperature")
            # qwen3 系列（qwen3-vl/qwen3.5 等）默认开启思考模式，回答会被吞进 reasoning、
            # content 为空 → 需显式传 think=false；其他模型可不配置（不传该参数）
            self.think = openai_cfg.get("think")
            # Kimi k2.6 默认开启思考，reasoning_tokens 会吃光 max_completion_tokens
            # → content 为空；需传 {"type": "disabled"} 关闭思考
            self.thinking = openai_cfg.get("thinking")
        elif self.api_type == "local":
            self._init_local()
        else:
            raise ValueError(f"不支持的 API 类型: {self.api_type}")

    def _init_local(self):
        """初始化本地模型（预留接口）"""
        local_cfg = self.llm_cfg["local"]
        self.model_path = local_cfg["model_path"]
        self.device = local_cfg.get("device", "cuda")
        self.max_new_tokens = local_cfg.get("max_new_tokens", 2048)
        self.model = None
        self.processor = None

    # ==================== 场景 A: 新增构筑物检测 ====================

    def analyze_new_construction(self, old_path: str, new_path: str) -> dict:
        """
        检测框内是否出现新增人工构筑物
        old: 旧时卫星图
        new: 现在卫星图
        """
        prompt = """你是一位遥感影像解译专家。下面两张图分别是同一地点的【前期影像】和【后期影像】。

图片中已有人工标注的矩形框（通常为红色或黄色），指出了需要核查的范围。请**只关注框内区域**进行分析。

你的任务是判断：框内区域是否出现了**新增的人工构筑物**？

人工构筑物包括：建筑物、厂房、硬化地面、大棚、围墙、道路等人工建造物。
不包括：自然植被变化、季节性色彩差异、裸地、阴影变化。

请仔细对比框内区域的前后变化，以 JSON 格式输出：
{
    "has_new_construction": true/false,
    "construction_type": "建筑物/厂房/硬化地面/大棚/围墙/道路/其他/无",
    "confidence": 0.0-1.0,
    "area_change_percent": "框内变化区域占比估算，如 15%",
    "needs_manual_review": true/false,
    "reasoning": "详细分析理由，描述具体看到了什么变化"
}

注意事项：
1. 只分析框内区域，忽略框外内容
2. 如果框内只有植被、裸地或阴影变化，判定为 false
3. 置信度应根据变化明显程度合理评估
4. 如果两张图的框内区域看起来完全一样，判定为 false"""

        return self._call_llm(prompt, [old_path, new_path])

    # ==================== 场景 B: 整改核验 ====================

    def analyze_rectification(self, before_path: str, after_path: str) -> dict:
        """
        核验整改区域构筑物是否拆除、是否恢复绿植/空地
        before: 整改前卫星图（有构筑物）
        after:  整改后卫星图（应已拆除）
        """
        prompt = """你是一位遥感整改核验专家。下面两张图分别是同一地点的【整改前】和【整改后】影像。

图片中已有人工标注的矩形框（通常为红色或黄色），指出了需要核查的范围。请**只关注框内区域**进行分析。

你的任务是判断：
1. 框内原有的人工构筑物是否已被拆除？

请仔细对比框内区域前后变化，以 JSON 格式输出：
{
    "is_fully_removed": true/false,
    "current_land_type": "绿地/裸地/仍有残留/其他建设/无法判断",
    "vegetation_restored": true/false,
    "rectification_score": 0-100,
    "pass_status": "通过/需整改/需现场复核",
    "suggestion": "整改建议（仅当未完全拆除时给出）",
    "confidence": 0.0-1.0,
    "reasoning": "详细分析理由"
}

注意事项：
1. 只分析框内区域，忽略框外内容
2. **判定核心：只要框内原有的人工构筑物已被完全拆除，就判定为整改完成（pass_status="通过"）。**
   植被是否恢复属于锦上添花，不算整改未完成，不要因此判为"需整改"，可在 reasoning/suggestion 中作为建议提出。
3. pass_status: "通过"=构筑物已完全拆除；"需整改"=构筑物未拆除或仍有明显残留；
   "需现场复核"=从影像无法确定是否拆除
4. rectification_score: 0=完全未整改（构筑物原样保留）, 100=构筑物已拆且恢复绿植/空地；
   已拆除但未恢复植被的评分仍可较高（如 70-90），分数仅供参考"""

        return self._call_llm(prompt, [before_path, after_path])

    # ==================== 场景 C: 单图分类检测 ====================

    def analyze_single(self, image_path: str) -> dict:
        """
        单图检测：识别红框内目标的视觉特征，判定是否符合四乱/其他问题
        image: 单张卫星图（带人工红色标注框）
        """
        prompt = """你是一名遥感影像解译专家。请分析输入的卫星遥感影像，判断红色矩形框内是否存在“四乱”问题。

【核心要求】
只分析红色矩形框内目标，同时参考整图环境判断目标与河流、湖泊、水面的关系。
忽略荧光绿色标记、文字、红框本身，不要把红框边界当成目标边界。
不要因为“看不清具体是什么”就判定为无；只要存在明确人工制造物特征，就判为乱建。

【第一步：判断整图环境】
先观察整图：
1. 判断水域位置：河流、湖泊、水面、河岸。
2. 判断红框位于：水面、河岸、湖边、内陆。
3. 判断整图是否明显发灰、发黄、褪色、低饱和。
   如果整图整体偏黄/灰，红框内的黄绿色、米黄色、土黄色可能只是旧卫星图的自然地表颜色，不能仅凭黄色判人工目标。

【第二步：判断红框内目标】

重点寻找以下特征：

A. 明确自然地表
- 植被、森林、绿地
- 裸地、泥地、沙地、滩地
- 普通水面
- 自然岸线
- 与周围环境颜色、纹理基本一致
→ 判“无”。

B. 明确人工制造物
只要看到以下任意明显特征，就判“乱建”：
- 白色或彩色高亮人工色块，与周围明显反差
- 房屋、厂房、棚屋、帐篷等规则建筑轮廓
- 规则矩形、平行直线、硬质边界
- 硬化地面、水泥地
- 明显人工道路
- 成排、规则排列的设施
- 配电箱、临时设施等人工物
- 明显桥梁结构
→ 无法确定具体名称时，specific_category直接写“人工构筑物”。

注意：
如果只是旧图造成的浅灰、浅黄、米黄色自然地表，且没有明显高亮人工色块、规则建筑或硬质边界，不得判乱建。

C. 道路
只有同时满足以下特征才判断为道路：
- 明显细长、连续的线状结构；
- 颜色或纹理与周围明显不同；
- 具有较稳定的宽度和人工线性特征。
如果只是自然裸地、河滩或旧图偏黄，不判道路。

D. 桥梁
桥梁判定必须有明确证据：
- 能看到桥墩/桥台；或
- 能看到桥面与两岸道路连续连接；或
- 能看到明显桥面、护栏等通行结构。
- 能看到跨水域/河道的细长线状物，大概率判桥梁。
- 红框内有一细长白色人工物体，位于水域中，与周围绿色水体和深色植被形成强烈反差。该物体呈规则矩形，边界硬质，表面平整，无自然纹理。大概率判桥梁。

E. 渔业工具
如果目标位于水面，表现为：
- 正方形块状、网状；
- 固定在水面；
→ 可判为渔业工具，属于“乱建”。

F. 乱堆
如果红框内存在明显人为堆放的垃圾、废料、建筑废弃物等，且与周围环境明显不同：
在图中表现大部分情况为圆形、不规则裸露地；
→ 判“乱堆”。

G. 乱占
如果红框内明显属于人为开垦、耕地、菜地等，并且存在明显耕作边界或规则农田特征：
→ 判“乱占”。

H. 乱采
如果红框位于河湖岸边或水域管辖范围内，出现明显采砂形成的圆形、不规则裸露地、砂坑或明显采挖痕迹：
→ 判“乱采”。
普通自然裸地、河滩、沙地不能仅凭颜色判乱采。

【第三步：最终分类】

按照以下优先级判断：

1. 明确人为堆放物 → 乱堆
2. 明确人为开垦/耕地 → 乱占
3. 明确采砂/采挖痕迹 → 乱采
4. 明确人工建筑、道路、硬化地、桥梁、渔业工具等 → 乱建
5. 明确自然地表 → 无
6. 无法确认具体人工类型，但能确认存在人工制造物 → 乱建
7. 完全无法确认且没有明确人工特征 → 无

【重要判定原则】
- 自然颜色 ≠ 人工。
- 浅黄色、土黄色、米黄色 ≠ 道路或采砂，尤其是整图发黄的旧图。
- 红框不是目标边界，不要根据红框形状判断目标。
- 不要臆测桥梁、道路、建筑。
- 看到明确人工特征时，即使无法确定具体名称，也判“乱建”。
- 看到纯自然地表时，判“无”。
- 不要把“可能、疑似、看起来像”作为最终结论。

【输出要求】
只输出JSON，不要输出任何解释、分析过程或Markdown。

{
  "major_category": "乱占/乱采/乱堆/乱建/其他问题/无",
  "specific_category": "简短具体类别，例如：裸地、绿地、河岸、道路、桥梁、渔业工具、房屋、厂房、工地、人工构筑物、耕地、采砂、堆弃物",
  "feature_description": "控制在100字以下。客观描述红框内目标的颜色、形状、纹理、数量、面积占比、分布，并说明最终判定依据。"
}

【最终自检】
输出前检查：
1. 有明确人工制造物 → major_category不能是“无”。
2. 纯自然地表 → major_category必须是“无”。
3. 道路、桥梁、房屋、硬化地面、渔业工具等人工设施 → major_category为“乱建”。
4. feature_description的最终结论必须与major_category一致。
5. 不确定具体人工类型但确认是人工物 → “乱建 + 人工构筑物”。
6. 只输出合法JSON。"""

        return self._call_llm(prompt, [image_path], retries=1)

    # ==================== LLM 调用 ====================

    def _call_llm(self, prompt: str, image_paths: list[str], retries: int = 0) -> dict:
        """通用 LLM 调用入口（默认不重试，失败直接交由上层在表格中记录识别失败）"""
        last = None
        for attempt in range(retries + 1):
            if self.api_type == "openai":
                last = self._call_openai(prompt, image_paths)
            elif self.api_type == "local":
                last = self._call_local(prompt, image_paths)
            else:
                return {"error": f"不支持的 API 类型: {self.api_type}"}
            if "error" not in last:
                return last
            if attempt < retries:
                time.sleep(3)
        return last

    def _call_openai(self, prompt: str, image_paths: list[str]) -> dict:
        """调用 OpenAI 兼容 API（httpx 直连，绕开 openai SDK 的 Authorization 头）。

        背景：Ollama 本地用占位 api_key（如 "ollama"），SDK 会带上
        `Authorization: Bearer ollama` 头，实测该头会导致部分本地模型
        （qwen3-vl:8b 等）返回空响应；httpx 不带 auth 头则正常。因此
        api_key 为占位值时省略 Authorization 头，真实云端 API 正常带。
        """
        content = [{"type": "text", "text": prompt}]
        for item in image_paths:
            # 支持 data URL（如红框裁剪图）与本地图片路径混合传入
            url = item if isinstance(item, str) and item.startswith("data:") else _encode_image(item)
            content.append({
                "type": "image_url",
                "image_url": {"url": url},
            })

        body = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content}],
        }
        # temperature：Kimi k2.6 固定值不可改，未配置时不传
        if self.temperature is not None:
            body["temperature"] = self.temperature
        # Kimi API 用 max_completion_tokens，标准 OpenAI 兼容 API 用 max_tokens
        if self.max_completion_tokens is not None:
            body["max_completion_tokens"] = self.max_completion_tokens
        elif self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if self.think is not None:
            body["think"] = self.think
        if self.thinking is not None:
            body["thinking"] = self.thinking
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "ollama":
            headers["Authorization"] = f"Bearer {self.api_key}"

        resp = self._http.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        raw = msg.get("content") or ""
        result = self._parse_json(raw)
        if "error" in result:
            # 失败时附加诊断信息（finish/usage/reasoning 长度），便于排查
            # 空响应/JSON 截断多半是 qwen3 思考内容吃光了 max_tokens
            result["diagnostics"] = {
                "finish_reason": choice.get("finish_reason"),
                "usage": data.get("usage", {}),
                "reasoning_len": len(msg.get("reasoning") or ""),
                "reasoning_head": (msg.get("reasoning") or "")[:200],
            }
            result["raw_response"] = raw or ""
        return result

    def _call_local(self, prompt: str, image_paths: list[str]) -> dict:
        """调用本地模型（预留接口）"""
        if self.model is None:
            return {"error": "本地模型未加载，请先下载模型权重并配置 model_path"}

        try:
            from transformers import Qwen2VLForConditionalGeneration, AutoProcessor

            messages = [{
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }]
            for path in image_paths:
                messages[0]["content"].append({"type": "image", "image": path})

            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.processor(
                text=[text], images=[], padding=True, return_tensors="pt"
            ).to(self.device)

            generated_ids = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens)
            response = self.processor.batch_decode(
                generated_ids, skip_special_tokens=True
            )[0]

            return self._parse_json(response)
        except ImportError:
            return {"error": "本地模型依赖未安装，请 pip install transformers"}

    @staticmethod
    def _parse_json(text: str) -> dict:
        """从 LLM 输出中提取 JSON；失败时区分空响应 / 输出不完整，便于诊断"""
        if not text or not text.strip():
            return {"error": "模型返回空响应", "raw_response": text or ""}

        try:
            # 尝试直接解析
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 块
        for pattern in [
            r"```json\s*([\s\S]*?)\s*```",
            r"```\s*([\s\S]*?)\s*```",
            r"\{[\s\S]*\}",
        ]:
            match = re.search(pattern, text)
            if match:
                try:
                    return json.loads(match.group(1))
                except (json.JSONDecodeError, IndexError):
                    continue

        return {"error": "JSON 解析失败（输出不完整或格式错误）", "raw_response": text}
