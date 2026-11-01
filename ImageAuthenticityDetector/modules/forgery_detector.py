import os
import re
import sys
import subprocess
import numpy as np


def _run_streamed(cmd, cwd, on_progress=None):
    """运行子进程并实时转发输出（支持 TruFor 内部的 tqdm 进度条显示）。
    on_progress(cur, total)：解析子进程 tqdm 输出（第 cur/total 张），实时回调，可选。
    """
    # 强制子进程 UTF-8 输出（中文 Windows 默认 GBK，会导致中文路径/进度条乱码）
    # 并抑制 timm 等第三方库的警告刷屏
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONWARNINGS"] = "ignore"
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=0, text=True, encoding="utf-8", errors="replace",
    )
    # 逐块读取并原样转发到主进程终端（\r 进度条可正常渲染）
    # 用 os.read 而非 stdout.read：read(n) 会等缓冲攒满才返回，导致 tqdm 多次更新被合并、
    # 进度事件跳变；os.read 每次取管道内当前可用数据，可逐张上报
    prog_re = re.compile(r"(\d+)\s*/\s*(\d+)")
    buf = ""
    last_cur = -1
    fd = proc.stdout.fileno()
    while True:
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        text = chunk.decode("utf-8", errors="replace")
        sys.stdout.write(text)
        sys.stdout.flush()
        if on_progress:
            # 进度行可能被 chunk 截断，保留末尾缓冲再解析
            buf += text
            if len(buf) > 8192:
                buf = buf[-8192:]
            best = None
            for m in prog_re.finditer(buf):
                c, t = int(m.group(1)), int(m.group(2))
                if t > 0 and c <= t and (best is None or c > best[0]):
                    best = (c, t)
            if best and best[0] != last_cur:
                # 同一块内可能跳过中间值（如 1/5 → 3/5），逐个补报
                for c in range(last_cur + 1, best[0] + 1):
                    on_progress(c, best[1])
                last_cur = best[0]
    proc.wait()
    return proc.returncode


class TruForDetector:
    def __init__(self, trufor_path: str = "./trufor"):
        self.trufor_path = trufor_path
        self.test_script = os.path.join(trufor_path, "test_docker/src/trufor_test.py")
        self.work_dir = os.path.join(trufor_path, "test_docker/src")
        # 使用当前虚拟环境的 Python，而非系统 Python
        self.python_exe = sys.executable

        if not os.path.exists(self.test_script):
            raise FileNotFoundError(
                f"TruFor not found at {trufor_path}. "
                "Run: git clone https://github.com/grip-unina/TruFor.git ./trufor"
            )

    def predict(self, image_path: str, output_dir: str):
        os.makedirs(output_dir, exist_ok=True)

        cmd = [
            self.python_exe, self.test_script,
            "-gpu", "0",
            "-in", image_path,
            "-out", output_dir
        ]
        code = _run_streamed(cmd, self.work_dir)
        if code != 0:
            raise RuntimeError(f"TruFor 运行失败 (exit {code})，详情见上方输出")

        # TruFor 路径 bug：os.path.join 遇到 "\" 开头的路径会重置为盘符根目录
        # 导致 npz 被错误保存到 D:\xxx.jpg.npz
        # 修复：检查 D:\ 根目录的 npz 文件，移到正确位置
        filename_with_ext = os.path.basename(image_path)
        expected_name = filename_with_ext + ".npz"
        correct_path = os.path.join(output_dir, expected_name)

        # 检查正确位置
        if os.path.exists(correct_path):
            npz_path = correct_path
        else:
            # 检查 D:\ 下是否有散落的同名文件
            stray_path = os.path.join("D:\\", expected_name)
            if os.path.exists(stray_path):
                import shutil
                shutil.move(stray_path, correct_path)
                npz_path = correct_path
            else:
                raise FileNotFoundError(
                    f"TruFor output not found.\n"
                    f"  expected: {correct_path}\n"
                    f"  stray: {stray_path}"
                )

        data = np.load(npz_path)
        score = float(data["score"])
        loc_map = data["map"]
        conf_map = data["conf"]
        # 关闭 npz 文件句柄，否则无法删除
        data.close()

        # 读取完成后删除 npz 中间文件，只保留最终产物（mask.png + report.json）
        os.remove(npz_path)

        return score, loc_map, conf_map

    def predict_batch(self, input_dir: str, output_dir: str, on_progress=None) -> dict:
        """批量检测目录下所有图片：子进程只启动一次、模型只加载一次。
        on_progress(cur, total)：tqdm 实时进度回调（推理完成张数/总数），可选。
        返回 {文件名: (score, loc_map, conf_map)}。
        """
        os.makedirs(output_dir, exist_ok=True)

        cmd = [
            self.python_exe, self.test_script,
            "-gpu", "0",
            "-in", input_dir,
            "-out", output_dir
        ]
        code = _run_streamed(cmd, self.work_dir, on_progress=on_progress)
        if code != 0:
            raise RuntimeError(f"TruFor 批量运行失败 (exit {code})，详情见上方输出")

        results = {}
        for f in sorted(os.listdir(input_dir)):
            if not f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                continue
            expected = f + ".npz"
            npz_path = os.path.join(output_dir, expected)
            # 兼容路径 bug：npz 被错误保存到 D:\ 根目录时移回正确位置
            if not os.path.exists(npz_path):
                stray_path = os.path.join("D:\\", expected)
                if os.path.exists(stray_path):
                    import shutil
                    shutil.move(stray_path, npz_path)
            if not os.path.exists(npz_path):
                print(f"  [跳过] {f}: TruFor 未生成结果（推理失败）")
                continue
            data = np.load(npz_path)
            score = float(data["score"])
            loc_map = data["map"]
            conf_map = data["conf"]
            data.close()
            os.remove(npz_path)
            results[f] = (score, loc_map, conf_map)
        return results
