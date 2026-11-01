#!/usr/bin/env python3
"""
遥感图像变化核验 CLI 工具

支持两种任务：
  detect  - 检测框内新增人工构筑物（旧图 vs 新图）
  verify  - 核验整改是否完毕（整改前 vs 整改后）
  classify - 单图检测：识别框内区域的 大类/具体类别/图像特征描述

用法：
  python rs_verify.py detect  --before ./data/0t.webp --after ./data/0.webp
  python rs_verify.py verify  --before ./data/0.webp --after ./data/0t.webp
  python rs_verify.py classify --image ./data/点位测试图/xxx.png
"""

import datetime
import io
import json
import sys
from pathlib import Path

# Windows 下 rich 输出 ▶/✓ 等字符到 gbk 编码流会抛 UnicodeEncodeError；
# 非交互场景（web 子进程捕获输出）统一强制 UTF-8，保证输出可正常编码与解析
if hasattr(sys.stdout, "buffer") and not sys.stdout.isatty():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer") and not sys.stderr.isatty():
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.analyzer import LLMAnalyzer, load_config
from core.reporter import ExcelReporter, SINGLE_COLUMNS
from core.viz import create_annotated_comparison, create_single_annotated

app = typer.Typer(
    help="遥感影像变化核验工具",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()

# 默认配置路径（相对于脚本所在目录）
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.yaml"


def _run_analysis(
    scenario: str,
    before_path: Path,
    after_path: Path,
    output_dir: Path,
    config_path: Path,
    json_out: Path = None,
    skip_excel: bool = False,
):
    """通用分析流程

    skip_excel=True 时跳过 Excel 写入（供 web 桥接使用：web 结果在前端展示并可导出，
    不需要 CLI 侧冗余的 results.xlsx 落盘）。
    """

    # 验证输入
    if not before_path.exists():
        console.print(f"[red]✗ Before 图片不存在: {before_path}[/red]")
        raise typer.Exit(1)
    if not after_path.exists():
        console.print(f"[red]✗ After 图片不存在: {after_path}[/red]")
        raise typer.Exit(1)

    # 加载配置
    cfg = load_config(config_path)
    excel_path = output_dir / "results.xlsx"
    image_dir = output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    # 显示任务信息
    scenario_cn = "新增构筑物检测" if scenario == "detect" else "整改核验"
    console.rule(f"[bold blue]{scenario_cn}任务")

    table = Table(show_header=False, box=None)
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("场景", scenario_cn)
    table.add_row("Before", str(before_path))
    table.add_row("After", str(after_path))
    table.add_row("LLM 模型", cfg["llm"]["openai"]["model_name"])
    table.add_row("输出目录", str(output_dir.absolute()))
    console.print(table)
    console.print()

    # Step 1: LLM 分析
    console.print("[bold]▶ Step 1/3: LLM 分析中...[/bold]")
    analyzer = LLMAnalyzer(config_path)

    with console.status("[bold green]正在调用大模型分析..."):
        if scenario == "detect":
            result = analyzer.analyze_new_construction(str(before_path), str(after_path))
        else:
            result = analyzer.analyze_rectification(str(before_path), str(after_path))

    # 检查 LLM 是否返回错误
    if "error" in result:
        console.print(f"[red]✗ LLM 分析失败: {result['error']}[/red]")
        if "raw_response" in result:
            console.print(f"[yellow]原始响应: {result['raw_response'][:500]}[/yellow]")
        raise typer.Exit(1)

    console.print("[green]✓ LLM 分析完成[/green]")

    # Step 2: 生成标注对比图（仅此一种，落盘供 Excel 嵌入与人工复核）
    console.print("[bold]▶ Step 2/3: 生成标注对比图...[/bold]")

    ann_path = image_dir / f"{before_path.stem}_vs_{after_path.stem}_annotated.png"
    create_annotated_comparison(
        str(before_path), str(after_path), str(ann_path),
        result, scenario,
    )

    console.print(f"[green]✓ 标注对比图已生成: {ann_path}[/green]")

    # Step 3: 写入 Excel（--no-excel 时跳过，web 桥接不需要 CLI 侧 Excel）
    if skip_excel:
        console.print("[dim]▶ 跳过 Excel 写入（--no-excel）[/dim]")
        reporter = None
    else:
        console.print("[bold]▶ Step 3/3: 写入 Excel 报告...[/bold]")
        reporter = ExcelReporter(str(excel_path))
        row = reporter.add_result(
            str(before_path), str(after_path),
            scenario, result, str(ann_path),
            model_name=cfg["llm"]["openai"]["model_name"],
        )
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
        result_table.add_row("当前地物", str(result.get("current_land_type", "N/A")))
        result_table.add_row("整改评分", f"{result.get('rectification_score', 'N/A')}/100")
        result_table.add_row("植被恢复", "是" if result.get("vegetation_restored") else "否")

    result_table.add_row("置信度", str(result.get("confidence", "N/A")))
    result_table.add_row("分析详情", str(result.get("reasoning", ""))[:120] + "...")
    console.print(result_table)

    console.print(f"\n[bold green]全部完成！[/bold green]")
    if reporter:
        console.print(f"  Excel: {reporter.excel_path.absolute()}")
    console.print(f"  标注对比图: {ann_path.absolute()}")

    # 可选：输出结构化 JSON（供 web 等外部程序读取）
    if json_out:
        summary = {
            "scenario": scenario,
            "before_file": Path(before_path).name,
            "after_file": Path(after_path).name,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": cfg["llm"]["openai"]["model_name"],
            "result": result,
            "annotated_image": str(ann_path.absolute()),
            "excel_path": str(reporter.excel_path.absolute()) if reporter else "",
            "conclusion": _conclusion_text(result, scenario),
        }
        json_out = Path(json_out)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        console.print(f"[green]✓ JSON 已输出: {json_out.absolute()}[/green]")


def _conclusion_text(result: dict, scenario: str) -> str:
    """从结果中提取摘要结论（与 Excel 主要结论列一致）"""
    if scenario == "detect":
        if result.get("has_new_construction"):
            return f"存在新增{result.get('construction_type', '构筑物')}"
        return "未发现新增构筑物"
    return result.get("pass_status", result.get("current_land_type", "N/A"))


def _run_single_analysis(
    image_path: Path,
    output_dir: Path,
    config_path: Path,
    json_out: Path = None,
    skip_excel: bool = False,
):
    """单图检测流程（classify 场景）

    skip_excel=True 时跳过 Excel 写入（与双图场景的 --no-excel 行为一致）。
    """

    # 验证输入
    if not image_path.exists():
        console.print(f"[red]✗ 图片不存在: {image_path}[/red]")
        raise typer.Exit(1)

    # 加载配置
    cfg = load_config(config_path)
    excel_path = output_dir / "results_classify.xlsx"
    image_dir = output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    # 显示任务信息
    console.rule("[bold blue]单图检测任务")
    table = Table(show_header=False, box=None)
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("场景", "单图检测")
    table.add_row("图片", str(image_path))
    table.add_row("LLM 模型", cfg["llm"]["openai"]["model_name"])
    table.add_row("输出目录", str(output_dir.absolute()))
    console.print(table)
    console.print()

    # Step 1: LLM 分析
    console.print("[bold]▶ Step 1/3: LLM 分析中...[/bold]")
    analyzer = LLMAnalyzer(config_path)

    with console.status("[bold green]正在调用大模型分析..."):
        result = analyzer.analyze_single(str(image_path))

    if "error" in result:
        console.print(f"[red]✗ LLM 分析失败: {result['error']}[/red]")
        if "raw_response" in result:
            console.print(f"[yellow]原始响应: {result['raw_response'][:500]}[/yellow]")
        raise typer.Exit(1)

    console.print("[green]✓ LLM 分析完成[/green]")

    # Step 2: 生成标注单图（落盘供 Excel 嵌入与人工复核）
    console.print("[bold]▶ Step 2/3: 生成标注单图...[/bold]")

    ann_path = image_dir / f"{image_path.stem}_classified.png"
    create_single_annotated(str(image_path), str(ann_path), result)

    console.print(f"[green]✓ 标注单图已生成: {ann_path}[/green]")

    # Step 3: 写入 Excel（--no-excel 时跳过）
    if skip_excel:
        console.print("[dim]▶ 跳过 Excel 写入（--no-excel）[/dim]")
        reporter = None
    else:
        console.print("[bold]▶ Step 3/3: 写入 Excel 报告...[/bold]")
        reporter = ExcelReporter(str(excel_path), columns=SINGLE_COLUMNS, sheet_name="单图检测")
        row = reporter.add_single_result(
            str(image_path), result, str(ann_path),
            model_name=cfg["llm"]["openai"]["model_name"],
        )
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

    console.print(f"\n[bold green]全部完成！[/bold green]")
    if reporter:
        console.print(f"  Excel: {reporter.excel_path.absolute()}")
    console.print(f"  标注单图: {ann_path.absolute()}")

    # 可选：输出结构化 JSON（供外部程序读取）
    if json_out:
        summary = {
            "scenario": "classify",
            "image_file": Path(image_path).name,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": cfg["llm"]["openai"]["model_name"],
            "result": result,
            "annotated_image": str(ann_path.absolute()),
            "excel_path": str(reporter.excel_path.absolute()) if reporter else "",
            "conclusion": f"{result.get('major_category', 'N/A')} - {result.get('specific_category', 'N/A')}",
        }
        json_out = Path(json_out)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        console.print(f"[green]✓ JSON 已输出: {json_out.absolute()}[/green]")


# ==================== CLI 命令 ====================

@app.command()
def detect(
    before: Path = typer.Option(
        ..., "--before", "-b", help="旧时卫星图（框内无构筑物）", exists=True
    ),
    after: Path = typer.Option(
        ..., "--after", "-a", help="现在卫星图（框内可能有新增构筑物）", exists=True
    ),
    output: Path = typer.Option(
        "./output", "--output", "-o", help="输出目录"
    ),
    config: Path = typer.Option(
        DEFAULT_CONFIG, "--config", "-c", help="配置文件路径"
    ),
    json_out: Path = typer.Option(
        None, "--json-out", help="分析完成后将结构化结果写入该 JSON 文件（供 web 等外部程序读取）"
    ),
    no_excel: bool = typer.Option(
        False, "--no-excel", is_flag=True,
        help="跳过 Excel 报告写入（只输出标注图与结构化结果）"
    ),
):
    """检测框内是否出现新增人工构筑物（旧图 → 新图）"""
    _run_analysis("detect", before, after, output, config, json_out, no_excel)


@app.command()
def verify(
    before: Path = typer.Option(
        ..., "--before", "-b", help="整改前卫星图（框内有构筑物）", exists=True
    ),
    after: Path = typer.Option(
        ..., "--after", "-a", help="整改后卫星图（框内应已恢复绿植/空地）", exists=True
    ),
    output: Path = typer.Option(
        "./output", "--output", "-o", help="输出目录"
    ),
    config: Path = typer.Option(
        DEFAULT_CONFIG, "--config", "-c", help="配置文件路径"
    ),
    json_out: Path = typer.Option(
        None, "--json-out", help="分析完成后将结构化结果写入该 JSON 文件（供 web 等外部程序读取）"
    ),
    no_excel: bool = typer.Option(
        False, "--no-excel", is_flag=True,
        help="跳过 Excel 报告写入（只输出标注图与结构化结果）"
    ),
):
    """核验框内构筑物是否已拆除、恢复绿植/空地（整改前 → 整改后）"""
    _run_analysis("verify", before, after, output, config, json_out, no_excel)


@app.command()
def classify(
    image: Path = typer.Option(
        ..., "--image", "-i", help="待检测卫星图（带人工标注框）", exists=True
    ),
    output: Path = typer.Option(
        "./output", "--output", "-o", help="输出目录"
    ),
    config: Path = typer.Option(
        DEFAULT_CONFIG, "--config", "-c", help="配置文件路径"
    ),
    json_out: Path = typer.Option(
        None, "--json-out", help="分析完成后将结构化结果写入该 JSON 文件（供外部程序读取）"
    ),
    no_excel: bool = typer.Option(
        False, "--no-excel", is_flag=True,
        help="跳过 Excel 报告写入（只输出标注图与结构化结果）"
    ),
):
    """单图检测：识别框内区域的 大类/具体类别/图像特征描述"""
    _run_single_analysis(image, output, config, json_out, no_excel)


if __name__ == "__main__":
    app()
