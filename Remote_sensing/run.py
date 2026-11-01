#!/usr/bin/env python3
"""
遥感变化核验 启动器
========================================
在下方"参数配置区"修改输入输出路径，然后直接运行：
    python run.py

也支持命令行覆盖：
    python run.py --scenario detect --before 0t.webp --after 0.webp
"""

import random
import io
import sys
from pathlib import Path

# Windows 下 rich 输出 ▶/✓ 等字符到 gbk 编码流会抛 UnicodeEncodeError；
# 非交互场景（管道/重定向捕获输出）统一强制 UTF-8，保证输出可正常编码与解析
if hasattr(sys.stdout, "buffer") and not sys.stdout.isatty():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer") and not sys.stderr.isatty():
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 确保能导入 core 模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 脚本所在目录（相对路径将基于它解析，从任何位置运行都有效）
SCRIPT_DIR = Path(__file__).resolve().parent

def _resolve(path_str: str) -> Path:
    """相对路径基于脚本目录解析，绝对路径原样返回"""
    p = Path(path_str)
    return p if p.is_absolute() else (SCRIPT_DIR / p)

# ==================== 参数配置区（改这里即可） ====================

# ──────────────── ① 场景选择（三选一） ──────────────────────
#   detect   : 新增构筑物检测（双图对比：旧图 → 新图，检测框内是否出现新增人工构筑物）
#   verify   : 整改核验（双图对比：整改前 → 整改后，核验构筑物是否已拆除/恢复）
#   classify : 单图检测（单张图，输出 大类/具体类别/图像特征描述）
SCENARIO = "classify"

# ──────────────── ② 输出目录 ────────────────────────────────
OUTPUT_DIR  = "data\\output_one1"    # 结果 Excel / 标注图输出目录（目录名不能含冒号 :）
CONFIG_PATH = "./config.yaml"                   # LLM API 配置（模型/地址/Key 都在 config.yaml）

# ──────────────── ③ 运行模式（四选一，互不影响） ─────────────
#   single : 单张/单对识别，用下方 ④ 的图片路径
#   random : 随机批量识别，用下方 ⑤ 的参数（从文件夹随机抽 N 张/对）
#   seq    : 顺序批量识别，用下方 ⑥ 的参数（按编号范围顺序识别 N/Nt）
#   group  : 按组随机批量识别，用下方 ⑦ 的参数（随机抽 N 组，每组 新图N+旧图Nt 都识别）
# 命令行 --batch / --range 可临时覆盖这里的设置。
#RUN_MODE = "group"
RUN_MODE = "single"


# ──────────────── ④ 单张/单对模式参数（RUN_MODE=single 用） ──
# classify 用一张图：
IMAGE_PATH  = "..\\data\\整改前图片_processed\\169.webp"
# detect/verify 用两张图（按场景填对应项）：
BEFORE_PATH = "..\\data\\整改前图片_processed\\2t.webp"
AFTER_PATH  = "..\\data\\整改前图片_processed\\2.webp"

# ──────────────── ⑤ 随机批量参数（RUN_MODE=random 用） ───────
RANDOM_DIR   = "..\\data\\整改前图片_processed"   # 批量图片文件夹（支持相对/绝对路径）
RANDOM_COUNT = 20                                 # 抽取数量：双图=对，单图=张
RANDOM_SEED  = 46                                 # 随机种子：None=每次随机抽；填数字=固定抽同一批（便于换模型对比）

# ──────────────── ⑥ 顺序批量参数（RUN_MODE=seq 用） ──────────
# 按编号顺序识别 N/Nt 成对图片（0、0t、1、1t、2、2t...），不走随机抽样
SEQ_DIR    = "..\\data\\整改前图片_processed"     # 批量图片文件夹（支持相对/绝对路径）
SEQ_RANGE  = "0-20"                               # 编号范围："0-20"=识别 0/0t...20/20t（42张）；"5"=只识别 5/5t（2张）

# ──────────────── ⑦ 按组随机批量参数（RUN_MODE=group 用） ────
# 随机抽取若干组编号，每组 新图N + 旧图Nt 两张都识别（如抽到 0、6、24 组 → 识别 0/0t、6/6t、24/24t）
GROUP_DIR   = "..\\data\\整改前图片_processed"   # 批量图片文件夹（支持相对/绝对路径）
GROUP_COUNT = 8                                   # 随机抽取的组数（每组通常 2 张：N 与 Nt）
GROUP_SEED  = 51                                  # 随机种子：None=每次随机；填数字=固定抽同一批（便于换模型对比）

# ──────────────── ⑧ 精简 Excel（classify 单图检测用） ──────
#   False : 完整表格（序号/文件名/场景/模型/时间/大类/具体类别/图像特征描述/标注图）
#   True  : 精简表格 5 列（序号/大类/具体类别/图像特征描述/原图），图片用原图不缩放，
#           输出到 results_classify_simple.xlsx（与原表格独立，不混列）
SIMPLE_EXCEL = True
# ==================================================================

SUPPORTED_EXT = {".webp", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def _list_images(directory: Path):
    """收集文件夹内所有支持的图片文件，按文件名排序（classify 批量用）。"""
    files = [f for f in directory.iterdir()
             if f.is_file() and f.suffix.lower() in SUPPORTED_EXT]
    return sorted(files, key=lambda f: f.name)


def _parse_number_range(s: str):
    """解析编号范围参数："0-20" → (0,20)；"5" → (5,5)；非法返回 None。"""
    s = s.strip()
    if not s:
        return None
    parts = s.split("-")
    if len(parts) == 1 and parts[0].isdigit():
        n = int(parts[0])
        return (n, n)
    if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
        a, b = int(parts[0]), int(parts[1])
        return (min(a, b), max(a, b))
    return None


def _list_by_number_range(directory: Path, num_range: tuple):
    """按编号范围收集图片（classify 顺序批量用）。

    文件名规则：N（新图）与 Nt（旧图）成对，如 0/0t、1/1t。
    返回 [start, end] 区间内的全部图片，按 (编号, 新图在前旧图在后) 顺序排列，
    即 0、0t、1、1t、2、2t ...
    """
    start, end = num_range
    items = []
    for f in directory.iterdir():
        if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXT:
            continue
        stem = f.stem
        if stem.isdigit():
            n, is_t = int(stem), False
        elif stem.endswith("t") and stem[:-1].isdigit():
            n, is_t = int(stem[:-1]), True
        else:
            continue
        if start <= n <= end:
            items.append((n, is_t, f))
    items.sort(key=lambda x: (x[0], x[1]))
    return [f for _, _, f in items]


def _list_groups(directory: Path) -> list:
    """收集文件夹内的编号组（按组随机批量用）。

    按文件名编号分组：0/0t 属编号 0，6/6t 属编号 6；组内新图 N 在前、旧图 Nt 在后。
    返回 [(编号, [该编号的图片路径...]), ...]，按编号升序。
    """
    groups: dict = {}
    for f in directory.iterdir():
        if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXT:
            continue
        stem = f.stem
        if stem.isdigit():
            n = int(stem)
        elif stem.endswith("t") and stem[:-1].isdigit():
            n = int(stem[:-1])
        else:
            continue
        groups.setdefault(n, []).append(f)
    for paths in groups.values():
        paths.sort(key=lambda p: (p.stem.endswith("t"), p.name))  # N 在前，Nt 在后
    return sorted(groups.items())


def _match_pairs(directory: Path, scenario: str, count: int, random_sample: bool = False):
    """在文件夹中按数字匹配图片对（0/0t 开始向上递增）。

    规则：文件名 "Nt"（旧图/整改前）与 "N"（新图/整改后）为一对；
    detect 顺序 before=Nt → after=N；verify 顺序 before=N → after=Nt。
    random_sample=True 时从全部对中随机抽取 count 对（无放回），否则按数字顺序取前 count 对。
    返回 [(before_path, after_path), ...]。
    """
    nums = {}
    for f in directory.iterdir():
        if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXT:
            continue
        stem = f.stem
        if stem.endswith("t") and stem[:-1].isdigit():
            nums.setdefault(int(stem[:-1]), {})["t"] = f
        elif stem.isdigit():
            nums.setdefault(int(stem), {})["n"] = f
    pairs = []
    for n in sorted(nums):
        d = nums[n]
        if "n" in d and "t" in d:
            if scenario == "verify":
                pairs.append((d["n"], d["t"]))
            else:
                pairs.append((d["t"], d["n"]))
    if random_sample:
        random.shuffle(pairs)
    return pairs[:count]


def _run_single(scenario: str, before: Path, after: Path,
                output_dir: Path, config: Path) -> bool:
    """执行单对分析：LLM 分析 → 标注对比图 → Excel 追加 → 终端摘要。成功返回 True。"""
    from core.analyzer import LLMAnalyzer, load_config
    from core.reporter import ExcelReporter
    from core.viz import create_annotated_comparison
    from rich.console import Console
    from rich.table import Table

    console = Console()

    if not before.exists():
        console.print(f"[red]✗ Before 图片不存在: {before}[/red]")
        return False
    if not after.exists():
        console.print(f"[red]✗ After 图片不存在: {after}[/red]")
        return False
    if not config.exists():
        console.print(f"[red]✗ 配置文件不存在: {config}[/red]")
        return False

    cfg = load_config(config)
    excel_path = output_dir / "results.xlsx"
    image_dir = output_dir / "images"
    try:
        image_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        console.print(f"[red]✗ 无法创建输出目录 {image_dir}: {e}[/red]")
        console.print("[yellow]提示：Windows 目录名不能包含 \\ / : * ? \" < > | 等字符，请修改 OUTPUT_DIR（例如模型名 qwen3-vl:4b 中的冒号换成 -）[/yellow]")
        return False

    # 显示任务信息
    scenario_cn = "新增构筑物检测" if scenario == "detect" else "整改核验"
    console.rule(f"[bold blue]{scenario_cn}任务")
    info = Table(show_header=False, box=None)
    info.add_column(style="cyan"); info.add_column()
    info.add_row("场景", scenario_cn)
    info.add_row("Before", str(before))
    info.add_row("After", str(after))
    info.add_row("LLM 模型", cfg["llm"]["openai"]["model_name"])
    info.add_row("输出目录", str(output_dir.absolute()))
    console.print(info)
    console.print()

    # Step 1: LLM 分析
    console.print("[bold]▶ Step 1/3: LLM 分析中...[/bold]")
    analyzer = LLMAnalyzer(config)
    with console.status("[bold green]正在调用大模型分析..."):
        if scenario == "detect":
            result = analyzer.analyze_new_construction(str(before), str(after))
        else:
            result = analyzer.analyze_rectification(str(before), str(after))

    if "error" in result:
        console.print(f"[red]✗ LLM 分析失败: {result['error']}[/red]")
        raw = result.get("raw_response", "")
        if raw and raw.strip():
            # 输出响应首尾片段，帮助判断是空响应还是截断/格式错误
            head = raw[:150].strip().replace("\n", " ")
            tail = raw[-100:].strip().replace("\n", " ")
            console.print(f"[yellow]响应片段: {head}…{tail}[/yellow]")
        else:
            console.print("[yellow]原始响应: 空（模型未生成内容）[/yellow]")
        # 失败也在 Excel 记录一行（文件名 + 原因），便于批量后排查哪几对失败
        try:
            reporter = ExcelReporter(str(excel_path))
            reporter.add_failed(str(before), str(after), scenario, result.get("error", "识别失败"),
                                model_name=cfg["llm"]["openai"]["model_name"])
        except Exception:
            pass
        return False

    console.print("[green]✓ LLM 分析完成[/green]")

    # Step 2: 生成标注对比图（仅此一种，落盘供 Excel 嵌入与人工复核）
    console.print("[bold]▶ Step 2/3: 生成标注对比图...[/bold]")
    ann_path = image_dir / f"{before.stem}_vs_{after.stem}_annotated.png"
    create_annotated_comparison(str(before), str(after), str(ann_path), result, scenario)
    console.print(f"[green]✓ 标注对比图已生成: {ann_path}[/green]")

    # Step 3: 写入 Excel（累积追加）
    console.print("[bold]▶ Step 3/3: 写入 Excel 报告...[/bold]")
    reporter = ExcelReporter(str(excel_path))
    row = reporter.add_result(str(before), str(after), scenario, result, str(ann_path),
                              model_name=cfg["llm"]["openai"]["model_name"])
    console.print(f"[green]✓ 已追加到 {reporter.excel_path} (第 {row} 行)[/green]")

    # 输出摘要
    console.print()
    result_table = Table(title="分析结果摘要", show_header=True)
    result_table.add_column("项目", style="cyan")
    result_table.add_column("结果", style="green")
    if scenario == "detect":
        has_new = result.get("has_new_construction", False)
        result_table.add_row("结论", "存在新增构筑物" if has_new else "未发现新增构筑物")
        result_table.add_row("构筑物类型", str(result.get("construction_type", "N/A")))
    else:
        result_table.add_row("通过状态", str(result.get("pass_status", "N/A")))
        result_table.add_row("整改评分", f"{result.get('rectification_score', 'N/A')}/100")
        result_table.add_row("植被恢复", "是" if result.get("vegetation_restored") else "否")
    result_table.add_row("置信度", str(result.get("confidence", "N/A")))
    result_table.add_row("分析详情", str(result.get("reasoning", ""))[:120] + "...")
    console.print(result_table)
    console.print(f"[bold green]全部完成！[/bold green]")
    console.print(f"  Excel: {reporter.excel_path.absolute()}")
    console.print(f"  标注对比图: {ann_path.absolute()}")
    return True


def _run_single_classify(image: Path, output_dir: Path, config: Path) -> bool:
    """执行单张图分类检测：LLM 分析 → 标注单图 → Excel 追加 → 终端摘要。成功返回 True。"""
    from core.analyzer import LLMAnalyzer, load_config
    from core.reporter import ExcelReporter, SINGLE_COLUMNS, SIMPLE_SINGLE_COLUMNS
    from core.viz import create_single_annotated
    from rich.console import Console
    from rich.table import Table

    console = Console()

    if not image.exists():
        console.print(f"[red]✗ 图片不存在: {image}[/red]")
        return False
    if not config.exists():
        console.print(f"[red]✗ 配置文件不存在: {config}[/red]")
        return False

    cfg = load_config(config)
    # 精简表格（SIMPLE_EXCEL）输出独立文件，避免与原完整表格混列
    excel_path = output_dir / ("results_classify_simple.xlsx" if SIMPLE_EXCEL else "results_classify.xlsx")
    image_dir = output_dir / "images"
    try:
        image_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        console.print(f"[red]✗ 无法创建输出目录 {image_dir}: {e}[/red]")
        return False

    # 显示任务信息
    console.rule("[bold blue]单图检测任务")
    info = Table(show_header=False, box=None)
    info.add_column(style="cyan"); info.add_column()
    info.add_row("场景", "单图检测")
    info.add_row("图片", str(image))
    info.add_row("LLM 模型", cfg["llm"]["openai"]["model_name"])
    info.add_row("输出目录", str(output_dir.absolute()))
    console.print(info)
    console.print()

    # Step 1: LLM 分析
    console.print("[bold]▶ Step 1/3: LLM 分析中...[/bold]")
    analyzer = LLMAnalyzer(config)
    with console.status("[bold green]正在调用大模型分析..."):
        result = analyzer.analyze_single(str(image))

    if "error" in result:
        console.print(f"[red]✗ LLM 分析失败: {result['error']}[/red]")
        diag = result.get("diagnostics")
        if diag:
            console.print(f"[yellow]诊断: {diag}[/yellow]")
        raw = result.get("raw_response", "")
        if raw and raw.strip():
            head = raw[:150].strip().replace("\n", " ")
            tail = raw[-100:].strip().replace("\n", " ")
            console.print(f"[yellow]响应片段: {head}…{tail}[/yellow]")
        else:
            console.print("[yellow]原始响应: 空（模型未生成内容）[/yellow]")
        # 失败也在 Excel 记录一行，便于批量后排查
        try:
            if SIMPLE_EXCEL:
                reporter = ExcelReporter(str(excel_path), columns=SIMPLE_SINGLE_COLUMNS, sheet_name="单图检测")
                reporter.add_single_failed_simple(str(image), result.get("error", "识别失败"),
                                                  model_name=cfg["llm"]["openai"]["model_name"])
            else:
                reporter = ExcelReporter(str(excel_path), columns=SINGLE_COLUMNS, sheet_name="单图检测")
                reporter.add_single_failed(str(image), result.get("error", "识别失败"),
                                           model_name=cfg["llm"]["openai"]["model_name"])
        except Exception:
            pass
        return False

    console.print("[green]✓ LLM 分析完成[/green]")

    # Step 2: 生成标注单图（落盘供 Excel 嵌入与人工复核）
    console.print("[bold]▶ Step 2/3: 生成标注单图...[/bold]")
    ann_path = image_dir / f"{image.stem}_classified.png"
    create_single_annotated(str(image), str(ann_path), result)
    console.print(f"[green]✓ 标注单图已生成: {ann_path}[/green]")

    # Step 3: 写入 Excel（累积追加）
    console.print("[bold]▶ Step 3/3: 写入 Excel 报告...[/bold]")
    if SIMPLE_EXCEL:
        reporter = ExcelReporter(str(excel_path), columns=SIMPLE_SINGLE_COLUMNS, sheet_name="单图检测")
        row = reporter.add_single_result_simple(str(image), result,
                                                model_name=cfg["llm"]["openai"]["model_name"])
    else:
        reporter = ExcelReporter(str(excel_path), columns=SINGLE_COLUMNS, sheet_name="单图检测")
        row = reporter.add_single_result(str(image), result, str(ann_path),
                                         model_name=cfg["llm"]["openai"]["model_name"])
    console.print(f"[green]✓ 已追加到 {reporter.excel_path} (第 {row} 行)[/green]")

    # 输出摘要
    console.print()
    result_table = Table(title="分析结果摘要", show_header=True)
    result_table.add_column("项目", style="cyan")
    result_table.add_column("结果", style="green")
    result_table.add_row("大类", str(result.get("major_category", "N/A")))
    result_table.add_row("具体类别", str(result.get("specific_category", "N/A")))
    result_table.add_row("图像特征描述", str(result.get("feature_description", "")))
    console.print(result_table)
    console.print(f"[bold green]全部完成！[/bold green]")
    console.print(f"  Excel: {reporter.excel_path.absolute()}")
    console.print(f"  标注单图: {ann_path.absolute()}")
    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="遥感变化核验启动器")
    parser.add_argument("--scenario", default=SCENARIO, choices=["detect", "verify", "classify"],
                        help="任务场景 (默认: 配置区 SCENARIO)")
    parser.add_argument("--before", "-b", default=None,
                        help="Before 图片路径 (默认: 配置区 BEFORE_PATH)")
    parser.add_argument("--after", "-a", default=None,
                        help="After 图片路径 (默认: 配置区 AFTER_PATH)")
    parser.add_argument("--image", "-i", default=None,
                        help="单图检测图片路径 (classify 用, 默认: 配置区 IMAGE_PATH)")
    parser.add_argument("--output", "-o", default=None,
                        help="输出目录 (默认: 配置区 OUTPUT_DIR)")
    parser.add_argument("--config", "-c", default=None,
                        help="配置文件路径 (默认: 配置区 CONFIG_PATH)")
    parser.add_argument("--batch", action="store_true",
                        help="强制随机批量模式（默认跟随配置区 RUN_MODE）")
    parser.add_argument("--count", type=int, default=None,
                        help="批量数量：random=张/对，group=组（默认: 配置区 RANDOM_COUNT / GROUP_COUNT）")
    parser.add_argument("--range", default=None,
                        help="强制顺序批量模式：按编号范围识别，如 0-20 识别 0/0t...20/20t；"
                             "单个编号如 5 只识别 5/5t（默认跟随配置区 RUN_MODE/SEQ_RANGE）")
    parser.add_argument("--dir", default=None,
                        help="批量图片文件夹 (默认: 配置区 RANDOM_DIR / SEQ_DIR)")
    args = parser.parse_args()

    scenario   = args.scenario
    output_dir = _resolve(args.output) if args.output else _resolve(OUTPUT_DIR)
    config     = _resolve(args.config) if args.config else _resolve(CONFIG_PATH)

    # 运行模式：命令行 --batch / --range 优先，否则用配置区 RUN_MODE
    if args.range:
        run_mode = "seq"
    elif args.batch:
        run_mode = "random"
    else:
        run_mode = RUN_MODE

    # ==================== 顺序批量（RUN_MODE=seq） ====================
    if run_mode == "seq":
        if scenario != "classify":
            print("✗ 顺序批量仅支持 classify 场景（按 N/Nt 编号逐张识别）")
            return
        range_arg = args.range if args.range is not None else (SEQ_RANGE.strip() or None)
        nr = _parse_number_range(range_arg) if range_arg else None
        if nr is None:
            print(f"✗ 无法解析顺序批量范围: {range_arg}（格式如 0-20 或 5）")
            return
        batch_dir = _resolve(args.dir) if args.dir else _resolve(SEQ_DIR)
        if not batch_dir.exists():
            print(f"✗ 批量文件夹不存在: {batch_dir}")
            return
        images = _list_by_number_range(batch_dir, nr)
        if not images:
            print(f"✗ 在 {batch_dir} 中未找到编号范围 {range_arg} 的图片")
            return
        print(f"顺序批量：编号范围 {range_arg}，共 {len(images)} 张图，开始逐张检测...")
        ok = fail = 0
        failures = []
        for i, image in enumerate(images, 1):
            print(f"\n========== [第 {i}/{len(images)} 张] ==========")
            if _run_single_classify(image, output_dir, config):
                ok += 1
            else:
                fail += 1
                failures.append(image.name)
        print(f"\n[bold]顺序批量完成：成功 {ok} 张，失败 {fail} 张[/bold]")
        if failures:
            print("失败清单（详细原因见 Excel 的\"识别失败\"行）：")
            for n in failures:
                print(f"  ✗ {n}")
        return

    # ==================== 随机批量（RUN_MODE=random） ====================
    if run_mode == "random":
        batch_dir = _resolve(args.dir) if args.dir else _resolve(RANDOM_DIR)
        if not batch_dir.exists():
            print(f"✗ 批量文件夹不存在: {batch_dir}")
            return
        # 配置了随机种子则先固定随机序列，保证每次抽到的对一致（便于对比不同模型识别差异）
        if RANDOM_SEED is not None:
            random.seed(RANDOM_SEED)

        if scenario == "classify":
            images = _list_images(batch_dir)
            if not images:
                print(f"✗ 在 {batch_dir} 中未找到支持的图片文件")
                return
            random.shuffle(images)
            count = args.count if args.count is not None else RANDOM_COUNT
            images = images[:count]
            seed_note = f"，随机种子={RANDOM_SEED}" if RANDOM_SEED is not None else "（随机抽样）"
            print(f"随机批量：共 {len(images)} 张图（要求 {count} 张{seed_note}），开始逐张检测...")
            ok = fail = 0
            failures = []
            for i, image in enumerate(images, 1):
                print(f"\n========== [第 {i}/{len(images)} 张] ==========")
                if _run_single_classify(image, output_dir, config):
                    ok += 1
                else:
                    fail += 1
                    failures.append(image.name)
            print(f"\n[bold]随机批量完成：成功 {ok} 张，失败 {fail} 张[/bold]")
            if failures:
                print("失败清单（详细原因见 Excel 的\"识别失败\"行）：")
                for n in failures:
                    print(f"  ✗ {n}")
            return

        count = args.count if args.count is not None else RANDOM_COUNT
        pairs = _match_pairs(batch_dir, scenario, count, random_sample=True)
        if not pairs:
            print(f"✗ 在 {batch_dir} 中未匹配到图片对（需要 0t/0, 1t/1 ... 数字配对）")
            return
        seed_note = f"，随机种子={RANDOM_SEED}" if RANDOM_SEED is not None else "（随机抽样）"
        print(f"随机批量：共匹配 {len(pairs)} 对（要求 {count} 对{seed_note}），开始逐对检测...")
        ok = fail = 0
        failures = []
        for i, (before, after) in enumerate(pairs, 1):
            print(f"\n========== [第 {i}/{len(pairs)} 对] ==========")
            if _run_single(scenario, before, after, output_dir, config):
                ok += 1
            else:
                fail += 1
                failures.append((before.name, after.name))
        print(f"\n[bold]随机批量完成：成功 {ok} 对，失败 {fail} 对[/bold]")
        if failures:
            print("失败清单（详细原因见 Excel 的\"识别失败\"行）：")
            for b, a in failures:
                print(f"  ✗ {b} ↔ {a}")
        return

    # ==================== 按组随机批量（RUN_MODE=group） ====================
    if run_mode == "group":
        if scenario != "classify":
            print("✗ 按组随机批量仅支持 classify 场景（每组 N/Nt 两张逐张识别）")
            return
        batch_dir = _resolve(args.dir) if args.dir else _resolve(GROUP_DIR)
        if not batch_dir.exists():
            print(f"✗ 批量文件夹不存在: {batch_dir}")
            return
        group_count = args.count if args.count is not None else GROUP_COUNT
        seed = GROUP_SEED
        if seed is not None:
            random.seed(seed)
        groups = _list_groups(batch_dir)
        if not groups:
            print(f"✗ 在 {batch_dir} 中未找到 N/Nt 编号图片")
            return
        random.shuffle(groups)
        picked = groups[:group_count]
        seed_note = f"，随机种子={seed}" if seed is not None else "（随机抽样）"
        total = sum(len(paths) for _, paths in picked)
        print(f"按组随机批量：共 {len(groups)} 组，随机抽取 {len(picked)} 组{seed_note}，共 {total} 张图，开始逐张检测...")
        ok = fail = 0
        failures = []
        idx = 0
        for n, paths in picked:
            for p in paths:
                idx += 1
                print(f"\n========== [第 {idx}/{total} 张] 组 {n} ==========")
                if _run_single_classify(p, output_dir, config):
                    ok += 1
                else:
                    fail += 1
                    failures.append(p.name)
        print(f"\n[bold]按组随机批量完成：成功 {ok} 张，失败 {fail} 张[/bold]")
        if failures:
            print("失败清单（详细原因见 Excel 的\"识别失败\"行）：")
            for fname in failures:
                print(f"  ✗ {fname}")
        return

    # ==================== 单张/单对（RUN_MODE=single） ====================
    if scenario == "classify":
        image = _resolve(args.image) if args.image else _resolve(IMAGE_PATH)
        if not image.exists():
            print(f"✗ 图片不存在: {image}")
            return
        _run_single_classify(image, output_dir, config)
        return

    before = _resolve(args.before) if args.before else _resolve(BEFORE_PATH)
    after  = _resolve(args.after)  if args.after  else _resolve(AFTER_PATH)
    if not before.exists():
        print(f"✗ Before 图片不存在: {before}")
        return
    if not after.exists():
        print(f"✗ After 图片不存在: {after}")
        return
    _run_single(scenario, before, after, output_dir, config)


if __name__ == "__main__":
    main()
