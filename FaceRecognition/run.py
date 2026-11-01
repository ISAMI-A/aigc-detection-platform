#!/usr/bin/env python3
"""
人脸识别 启动器（独立 CLI）
========================================
两种用法：
  ① 改顶部"参数配置区"后直接运行（最常）：  python run.py
  ② 命令行子命令覆盖（临时改一次）：         python run.py register --image ... --person ...

子命令：
    register  注册/覆盖某人员           (--image --person [--name])
    verify    1:1 两图是否同一人        (--image --image2 [--threshold])
    identify  1:N 在库中识别图片人脸    (--image [--topk --threshold])
    list      列出向量库全部记录
    delete    删除某人员                (--person)
    demo      批量注册演示（一张图=一人）(--dir)

图片读取兼容中文路径；模型首次调用自动加载到 GPU。
"""
import io
import os
import sys
from pathlib import Path

# Windows 非交互延迟下 rich/中文输出统一强制 UTF-8，避免 gbk 编码崩溃
if hasattr(sys.stdout, "buffer") and not sys.stdout.isatty():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer") and not sys.stderr.isatty():
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 确保能导入 core/ 与 config.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import cv2
import numpy as np

from core.model_manager import get_manager
from core.face_db import default_db
from core.face_engine import cosine_similarity
from config import SIMILARITY_THRESHOLD, IDENTIFY_TOP_K


# ==================== 参数配置区（改这里即可） ====================

# ──────────────── ① 任务选择（六选一） ──────────────────────
#   register : 注册/覆盖某人员（用 ② 的主图片 + ③ 人员信息）
#   verify   : 1:1 验证两张图是否同一人（用 ② 的主图 + 对比图）
#   identify : 1:N 在库中识别图片中全部人脸（用 ② 的主图片）
#   list     : 列出向量库全部记录（无需图片）
#   delete   : 删除某人员（用 ③ 的 person）
#   demo     : 批量注册演示（用 ④ 的图片文件夹，一张图=一人）
TASK = "register"

# ──────────────── ② 图片路径（相对路径基于本脚本目录） ─────
IMAGE_PATH  = "..\\data\\faces\\a.jpg"     # 主图片（register/verify/identify 用）
IMAGE2_PATH = "..\\data\\faces\\b.jpg"     # 对比图（verify 用）

# ──────────────── ③ 人员信息（register/delete 用） ────────
PERSON_ID   = "u001"                       # 人员唯一标识
PERSON_NAME = "张三"                        # 显示名（默认同 person）

# ──────────────── ④ 演示批量（TASK=demo 用） ──────────────
DEMO_DIR    = "..\\data\\faces"            # 图片文件夹（每张图注册为一人，文件名作 person_id）

# ──────────────── ⑤ 推理参数 ──────────────────────────────
SIMILARITY = 0.6                          # 相似度阈值：≥ 该值判定同一人（1:1/1:N 共用）
TOP_K      = 5                             # 1:N 识别返回候选数
# 注：人脸检测置信度阈值不在此设置，统一在 config.py 的 DETECT_THRESHOLD 调整
# ==================================================================


def _read_image(path: str) -> np.ndarray:
    """读取图片（兼容中文路径），失败抛异常。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"图片不存在: {path}")
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"无法解码图片（可能是损坏或格式不支持）: {path}")
    return img


def _largest_face(engine, img):
    """取图中面积最大的人脸；无脸抛异常。"""
    faces = engine.detect(img)
    if not faces:
        raise RuntimeError("未检测到任何人脸")
    return max(faces, key=lambda f: (f["bbox"][2]-f["bbox"][0]) * (f["bbox"][3]-f["bbox"][1]))


def cmd_register(engine, db, args):
    person = args.person or PERSON_ID
    name = args.name or PERSON_NAME or person
    image = args.image or IMAGE_PATH
    img = _read_image(image)
    face = _largest_face(engine, img)
    emb = engine.embed_face(img, face["kps"])
    rid = db.register(person, name, emb)
    print(f"✓ 已注册 {person}（{name}），记录 id={rid}")
    return 0


def cmd_verify(engine, db, args):
    img1 = _read_image(args.image or IMAGE_PATH)
    img2 = _read_image(args.image2 or IMAGE2_PATH)
    f1 = _largest_face(engine, img1)
    f2 = _largest_face(engine, img2)
    e1 = engine.embed_face(img1, f1["kps"])
    e2 = engine.embed_face(img2, f2["kps"])
    sim = cosine_similarity(e1, e2)
    ok = sim >= args.threshold
    print(f"相似度: {sim:.4f}  阈值: {args.threshold:.2f}")
    print(f"结论: {'同一人 ✓' if ok else '不同人 ✗'}" if sim else "相似度为0（异常）")
    return 0 if ok else 1


def cmd_identify(engine, db, args):
    img = _read_image(args.image or IMAGE_PATH)
    faces = engine.detect(img)
    if not faces:
        print("✗ 图片中未检测到人脸")
        return 1
    for i, face in enumerate(faces, 1):
        emb = engine.embed_face(img, face["kps"])
        cands = db.search(emb, top_k=args.topk)
        best = cands[0] if cands and cands[0]["similarity"] >= args.threshold else None
        x1, y1, x2, y2 = (int(v) for v in face["bbox"])
        print(f"— 人脸{i} @({x1},{y1})-({x2},{y2}) 置信度{face['score']:.2f}")
        if best:
            print(f"   识别为: {best['name']}（{best['person_id']}） 相似度 {best['similarity']:.4f}")
            for c in cands[1:]:
                print(f"   备选: {c['name']}  {c['similarity']:.4f}")
        else:
            print(f"   未匹配到库中人脸（最佳 {cands[0]['similarity']:.4f} < 阈值）" if cands else "   向量库为空")
    return 0


def cmd_list(_engine, db, args):
    rows = db.list_all()
    if not rows:
        print("向量库为空（0 条记录）")
        return 0
    print(f"向量库共 {len(rows)} 条记录:")
    cur_person = None
    for r in rows:
        prefix = "→ " if r["person_id"] != cur_person else "  "
        cur_person = r["person_id"]
        print(f"{prefix}[{r['person_id']}] {r['name']}  (id={r['id']})")
    return 0


def cmd_delete(_engine, db, args):
    person = args.person or PERSON_ID
    n = db.delete_person(person)
    print(f"已删除人员 {person}，共 {n} 条样本" if n else f"未找到人员 {person}")
    return 0


def cmd_demo(engine, db, args):
    """批量注册演示：把指定文件夹内每张图注册为一人（以文件名 stem 为 person_id）。"""
    directory = Path(args.dir or DEMO_DIR)
    if not directory.is_dir():
        print(f"✗ 演示目录不存在: {directory}")
        return 1
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    files = sorted(p for p in directory.iterdir()
                   if p.is_file() and p.suffix.lower() in exts)
    if not files:
        print(f"✗ {directory} 中没有支持的图片")
        return 1
    ok = 0
    for p in files:
        try:
            img = _read_image(str(p))
            face = _largest_face(engine, img)
            emb = engine.embed_face(img, face["kps"])
            db.register(p.stem, p.stem, emb)
            ok += 1
        except Exception as e:
            print(f"✗ {p.name}: {e}")
    print(f"演示注册完成: 成功 {ok}/{len(files)} 人")
    return 0


def main():
    p = argparse.ArgumentParser(description="人脸识别 CLI（改顶部参数配置区，或命令行子命令覆盖）")
    # 不指定子命令时用顶部配置区 TASK；指定则用子命令
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("register", help="注册/覆盖某人员")
    sp.add_argument("--image", "-i", default=None, help=f"图片路径（默认 {IMAGE_PATH}）")
    sp.add_argument("--person", "-p", default=None, help=f"人员标识（默认 {PERSON_ID}）")
    sp.add_argument("--name", "-n", default=None, help=f"显示名（默认 {PERSON_NAME or PERSON_ID}）")

    sp = sub.add_parser("verify", help="1:1 两图是否同一人")
    sp.add_argument("--image", "-i", default=None, help=f"主图（默认 {IMAGE_PATH}）")
    sp.add_argument("--image2", "-j", default=None, help=f"对比图（默认 {IMAGE2_PATH}）")
    sp.add_argument("--threshold", type=float, default=SIMILARITY, help=f"阈值（默认 {SIMILARITY}）")

    sp = sub.add_parser("identify", help="1:N 在库识别图片人脸")
    sp.add_argument("--image", "-i", default=None, help=f"图片路径（默认 {IMAGE_PATH}）")
    sp.add_argument("--topk", type=int, default=TOP_K, help=f"候选数（默认 {TOP_K}）")
    sp.add_argument("--threshold", type=float, default=SIMILARITY, help=f"阈值（默认 {SIMILARITY}）")

    sub.add_parser("list", help="列出向量库记录")
    sp = sub.add_parser("delete", help="删除某人员")
    sp.add_argument("--person", "-p", default=None, help=f"人员标识（默认 {PERSON_ID}）")
    sp = sub.add_parser("demo", help="批量注册演示")
    sp.add_argument("--dir", "-d", default=None, help=f"图片文件夹（默认 {DEMO_DIR}）")

    args = p.parse_args()

    # 无子命令 → 用顶部配置区 TASK；有子命令 → 用命令名
    cmd = args.cmd or TASK

    manager = get_manager()
    db = default_db()
    handlers = {"register": cmd_register, "verify": cmd_verify, "identify": cmd_identify,
                "list": cmd_list, "delete": cmd_delete, "demo": cmd_demo}

    try:
        if cmd not in handlers:
            print(f"✗ 未知命令: {cmd}（可选 {list(handlers)} 或改顶部 TASK）")
            return 1
        engine = manager.acquire()
    except Exception as e:
        print(f"✗ 模型加载失败: {e}")
        return 1

    try:
        return handlers[cmd](engine, db, args)
    except Exception as e:
        print(f"✗ {type(e).__name__}: {e}")
        return 1
    finally:
        # 交互用完即卸，回退还给其他模型（web 集成时由全局 manager 决定驻留）
        manager.release()


if __name__ == "__main__":
    sys.exit(main())