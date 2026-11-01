"""
TruFor 阈值校准脚本
========================================
用已知篡改的测试集（P图=篡改正样本，原图=干净负样本）做网格搜索，
自动选出使 F1 / 精确率 / 召回率最优的判定参数组合。

用法：
    python calibrate.py -dir test_images/testss          # 首次运行自动检测并保存指标缓存
    python calibrate.py -dir test_images/testss --force-collect  # 强制重新检测
    python calibrate.py -dir test_images/testss --split 0.7 --seed 123  # 自定义划分比例和随机种子

流程：
    全部数据 → 随机按比例分成训练集 + 测试集（按 label 分层）
    → 训练集上网格搜索最优参数 → 测试集上评估泛化指标

检测本身耗时与 trufor_pair.py 相同（一次模型加载），指标缓存后再次运行秒出结果。
"""
import argparse
import hashlib
import json
import os
import random
import shutil
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TRUFOR_PATH, TEMP_DIR, MAX_IMAGE_SIZE
from modules.image_preprocess import preprocess
from modules.forgery_detector import TruForDetector
from trufor_pair import loc_stats, parse_name
import trufor_pair  # 动态覆盖 judge 使用的全局阈值


IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


def collect_metrics(img_dir, cache_path, max_samples=0):
    """跑一次批量检测，收集每张图的指标与真值（P图=1，原图=0），缓存为 JSON。

    支持两种目录结构：
    1. Au/ + Tp/ 子目录（CASIA2 格式）—— 自动识别，Au=原图，Tp=P图
    2. 扁平目录 + parse_name()（testss 格式）—— {num}.png=原图，{num}p.jpg=P图

    max_samples: 每类最多抽样数量（0=不限制），超出时随机抽取
    """
    if os.path.exists(cache_path):
        print(f"使用缓存指标: {cache_path}")
        return json.load(open(cache_path, encoding="utf-8"))

    batch_dir = os.path.join(TEMP_DIR, "calibrate_batch")
    tmp_dir = os.path.join(TEMP_DIR, "calibrate_tmp")
    os.makedirs(batch_dir, exist_ok=True)
    os.makedirs(tmp_dir, exist_ok=True)

    # 检测目录结构：是否有 Au/ + Tp/ 子目录
    au_dir = os.path.join(img_dir, "Au")
    tp_dir = os.path.join(img_dir, "Tp")
    casia2_mode = os.path.isdir(au_dir) and os.path.isdir(tp_dir)

    if casia2_mode:
        # === CASIA2 格式：按目录名判断 label ===
        def _list_files(d, label, label_name):
            files = []
            for f in sorted(os.listdir(d)):
                if f.lower().endswith(IMG_EXT):
                    files.append((os.path.join(d, f), label, label_name))
            return files

        all_files = _list_files(au_dir, 0, "原图") + _list_files(tp_dir, 1, "P图")
    else:
        # === 扁平目录：按文件名 parse_name 判断 label ===
        all_files = []
        for f in sorted(os.listdir(img_dir)):
            if f.lower().endswith(IMG_EXT):
                _, is_p = parse_name(f)
                label = 1 if is_p else 0
                all_files.append((os.path.join(img_dir, f), label, "P图" if is_p else "原图"))

    n_au = sum(1 for _, l, _ in all_files if l == 0)
    n_tp = sum(1 for _, l, _ in all_files if l == 1)
    print(f"检测到 {n_au} 张原图 + {n_tp} 张P图（{'CASIA2 子目录' if casia2_mode else '扁平目录'}模式）")

    # 抽样（按类别均衡）
    if max_samples > 0:
        random.seed(42)
        au_files = [(p, l, ln) for p, l, ln in all_files if l == 0]
        tp_files = [(p, l, ln) for p, l, ln in all_files if l == 1]
        n_au_sample = min(len(au_files), max_samples // 2)
        n_tp_sample = min(len(tp_files), max_samples - n_au_sample)
        au_files = random.sample(au_files, n_au_sample) if n_au_sample < len(au_files) else au_files
        tp_files = random.sample(tp_files, n_tp_sample) if n_tp_sample < len(tp_files) else tp_files
        all_files = au_files + tp_files
        random.shuffle(all_files)
        print(f"随机抽样后: {len(au_files)} 原图 + {len(tp_files)} P图 = {len(all_files)} 张（max_samples={max_samples}）")

    # 预处理
    names = []
    for p, label, label_name in all_files:
        try:
            n = os.path.basename(preprocess(p, MAX_IMAGE_SIZE, batch_dir))
            names.append((n, p, label, label_name))
        except Exception as e:
            print(f"  跳过 {os.path.basename(p)}: {e}")

    print(f"共 {len(names)} 张图预处理完成，开始 TruFor 批量检测（模型只加载一次）...")
    trufor = TruForDetector(TRUFOR_PATH)
    results = trufor.predict_batch(batch_dir, tmp_dir)

    metrics = []
    for n, p, label, label_name in names:
        if n not in results:
            print(f"  [跳过] {os.path.basename(p)}: 未生成结果")
            continue
        score, loc, conf = results[n]
        st = loc_stats(loc, conf)
        metrics.append({
            "file": os.path.basename(p),
            "label": label,
            "score": float(score),
            "peak": st["peak"], "area": st["area"],
            "conf_area": st["conf_area"], "max_comp": st["max_comp"],
            "n_comp": st["n_comp"],
        })

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1)
    print(f"指标已缓存: {cache_path}")

    # 清理预处理临时文件（避免堆积）
    shutil.rmtree(batch_dir, ignore_errors=True)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return metrics


def evaluate(metrics, threshold, fuse_peak, fuse_area, comp_ratio, comp_spots):
    """用指定参数跑一遍判定，返回混淆矩阵与精确率/召回率/F1"""
    # 覆盖 judge 使用的模块级全局阈值
    trufor_pair.THRESHOLD = threshold
    trufor_pair.FUSE_PEAK = fuse_peak
    trufor_pair.FUSE_AREA = fuse_area
    trufor_pair.COMP_RATIO = comp_ratio
    trufor_pair.COMP_N_SPOTS = comp_spots

    tp = fp = fn = tn = 0
    for m in metrics:
        st = {"peak": m["peak"], "area": m["area"], "conf_area": m["conf_area"],
              "max_comp": m["max_comp"], "n_comp": m["n_comp"]}
        jud = trufor_pair.judge(m["score"], st)
        pred = 1 if (jud and jud.startswith(("是", "疑似"))) else 0
        if pred == 1 and m["label"] == 1:
            tp += 1
        elif pred == 1 and m["label"] == 0:
            fp += 1
        elif pred == 0 and m["label"] == 1:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1}


def search_best(train_metrics):
    """在给定训练集上做网格搜索，返回 (最佳参数元组, 训练集评估结果)"""
    best = None
    for thr in [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        for pk in [0.70, 0.80, 0.90]:
            for ar in [0.02, 0.05, 0.08, 0.10, 0.15]:
                for cr in [0.005, 0.01, 0.02, 0.04]:
                    for sp in [8, 16, 24]:
                        r = evaluate(train_metrics, thr, pk, ar, cr, sp)
                        key = (round(r["f1"], 4), round(r["precision"], 4), round(r["recall"], 4))
                        if best is None or key > best[0]:
                            best = (key, (thr, pk, ar, cr, sp), r)
    return best


def cross_validate(metrics, k=5, seed=42):
    """K 折分层交叉验证：返回每折的结果列表 [(params, train_r, test_r), ...]"""
    random.seed(seed)
    pos = [m for m in metrics if m["label"] == 1]
    neg = [m for m in metrics if m["label"] == 0]
    random.shuffle(pos)
    random.shuffle(neg)

    # 按比例分层切分 K 折
    pos_chunks = [[] for _ in range(k)]
    neg_chunks = [[] for _ in range(k)]
    for i, m in enumerate(pos):
        pos_chunks[i % k].append(m)
    for i, m in enumerate(neg):
        neg_chunks[i % k].append(m)

    fold_results = []
    print(f"\n{'='*60}")
    print(f"  {k} 折交叉验证（{len(pos)}P + {len(neg)}原 = {len(metrics)} 张, seed={seed}）")
    print(f"{'='*60}")

    for fold in range(k):
        # 第 fold 份做测试集，其余做训练集
        test_pos = pos_chunks[fold]
        test_neg = neg_chunks[fold]
        train_pos = [m for i in range(k) if i != fold for m in pos_chunks[i]]
        train_neg = [m for i in range(k) if i != fold for m in neg_chunks[i]]
        train_set = train_pos + train_neg
        test_set = test_pos + test_neg
        random.shuffle(train_set)
        random.shuffle(test_set)

        best = search_best(train_set)
        (_f1, _prec, _rec), params, r_train = best
        r_test = evaluate(test_set, *params)

        fold_results.append((params, r_train, r_test))
        print(f"  第{fold+1}折: 训练={len(train_set)}(P{len(train_pos)}/原{len(train_neg)}) "
              f"测试={len(test_set)}(P{len(test_pos)}/原{len(test_neg)}) | "
              f"参数{params} | "
              f"测试 F1={r_test['f1']:.3f} P={r_test['precision']:.3f} R={r_test['recall']:.3f}")

    return fold_results


def main():
    parser = argparse.ArgumentParser(description="TruFor 阈值校准：网格搜索最优判定参数")
    parser.add_argument("-dir", default="test_images/testss",
                        help="图片目录（P图=篡改正样本，原图=干净负样本）")
    parser.add_argument("-cache", default=None,
                        help="指标缓存文件路径（默认自动按输入目录生成: temp/calibrate_<hash>.json）")
    parser.add_argument("--force-collect", action="store_true",
                        help="强制重新检测收集指标（忽略已有缓存）")
    parser.add_argument("--split", type=float, default=0.8,
                        help="训练集占比（默认 0.8，剩余 0.2 做测试集）")
    parser.add_argument("--seed", type=int, default=42,
                        help="随机种子（默认 42，保证结果可复现）")
    parser.add_argument("--cv", type=int, default=0,
                        help="K 折交叉验证（如 --cv 5，启用后忽略 --split，按 K 折轮转评估）")
    parser.add_argument("--max-samples", type=int, default=0,
                        help="最大检测图片数（0=不限制，按原图/P图均衡抽样；大数据集建议先抽 200 试跑）")
    args = parser.parse_args()

    img_dir = os.path.abspath(args.dir)
    if not os.path.isdir(img_dir):
        print(f"目录不存在: {img_dir}")
        return

    # 自动按输入目录生成缓存文件名（不同目录用不同缓存，杜绝混用）
    cache = args.cache
    if cache is None:
        dir_hash = hashlib.md5(img_dir.encode()).hexdigest()[:8]
        cache = os.path.join(TEMP_DIR, f"calibrate_{dir_hash}.json")

    if args.force_collect and os.path.exists(cache):
        os.remove(cache)

    metrics = collect_metrics(img_dir, cache, args.max_samples)
    if not metrics:
        print("未收集到任何指标")
        return

    if args.cv:
        # ===== K 折交叉验证模式 =====
        fold_results = cross_validate(metrics, k=args.cv, seed=args.seed)

        test_f1s = [r_test["f1"] for _, _, r_test in fold_results]
        test_precs = [r_test["precision"] for _, _, r_test in fold_results]
        test_recs = [r_test["recall"] for _, _, r_test in fold_results]

        print(f"\n{'='*60}")
        print(f"  交叉验证汇总（{args.cv} 折）")
        print(f"{'='*60}")
        print(f"  测试 F1:  均值={statistics.mean(test_f1s):.3f}  "
              f"中位数={statistics.median(test_f1s):.3f}  "
              f"标准差={statistics.stdev(test_f1s):.3f}  "
              f"范围=[{min(test_f1s):.3f}, {max(test_f1s):.3f}]")
        print(f"  测试 Precision: 均值={statistics.mean(test_precs):.3f}  "
              f"中位数={statistics.median(test_precs):.3f}")
        print(f"  测试 Recall:    均值={statistics.mean(test_recs):.3f}  "
              f"中位数={statistics.median(test_recs):.3f}")

        # 统计各折选出的参数（投票选出最常用组合）
        from collections import Counter
        param_counts = Counter(params for params, _, _ in fold_results)
        print(f"\n  各折选出的参数（按出现次数）：")
        for params, count in param_counts.most_common():
            f1s = [r_test["f1"] for p, _, r_test in fold_results if p == params]
            avg_f1 = statistics.mean(f1s) if len(f1s) > 1 else f1s[0]
            print(f"    {params}: {count}折选中, 平均测试F1={avg_f1:.3f}")
        print("\n将以上参数填到 run.py 顶部配置区即可（或命令行 --threshold/--peak/--area/--comp-ratio）。")
        return

    # ===== 单次划分模式（默认） =====
    # 分层划分：按 label 分别 shuffle，保证 train/test 中 P图/原图 比例一致
    random.seed(args.seed)
    pos = [m for m in metrics if m["label"] == 1]
    neg = [m for m in metrics if m["label"] == 0]
    random.shuffle(pos)
    random.shuffle(neg)
    n_pos_train = max(1, int(len(pos) * args.split))
    n_neg_train = max(1, int(len(neg) * args.split))
    train = pos[:n_pos_train] + neg[:n_neg_train]
    test = pos[n_pos_train:] + neg[n_neg_train:]
    random.shuffle(train)
    random.shuffle(test)
    print(f"数据划分: 训练集 {len(train)} 张（P={len(pos[:n_pos_train])}, 原={len(neg[:n_neg_train])}）"
          f" | 测试集 {len(test)} 张（P={len(pos[n_pos_train:])}, 原={len(neg[n_neg_train:])}）"
          f"  seed={args.seed}")

    # 当前默认参数基线（与 run.py balanced 档一致）—— 仅在训练集上计算
    cur_train = evaluate(train, 0.35, 0.7, 0.05, 0.005, 16)
    cur_test = evaluate(test, 0.35, 0.7, 0.05, 0.005, 16)
    print(f"\n=== 当前默认参数 (THRESHOLD=0.35, PEAK=0.7, AREA=0.05, COMP=0.005, SPOTS=16) ===")
    print(f"  训练集: 精确率={cur_train['precision']:.3f}  召回率={cur_train['recall']:.3f}  "
          f"F1={cur_train['f1']:.3f}  TP={cur_train['tp']} FP={cur_train['fp']} FN={cur_train['fn']} TN={cur_train['tn']}")
    print(f"  测试集: 精确率={cur_test['precision']:.3f}  召回率={cur_test['recall']:.3f}  "
          f"F1={cur_test['f1']:.3f}  TP={cur_test['tp']} FP={cur_test['fp']} FN={cur_test['fn']} TN={cur_test['tn']}")

    # 网格搜索（优先 F1，其次精确率）—— 仅在训练集上搜索
    best = search_best(train)

    (f1, prec, rec), (thr, pk, ar, cr, sp), r_train = best
    print(f"\n=== 最优参数（训练集上按 F1 搜索）===")
    print(f"  THRESHOLD={thr}  FUSE_PEAK={pk}  FUSE_AREA={ar}  COMP_RATIO={cr}  COMP_N_SPOTS={sp}")
    print(f"  训练集: 精确率={prec:.3f}  召回率={rec:.3f}  F1={f1:.3f}"
          f"  TP={r_train['tp']} FP={r_train['fp']} FN={r_train['fn']} TN={r_train['tn']}")

    # 测试集评估（泛化能力的诚实估计）
    r_test = evaluate(test, thr, pk, ar, cr, sp)
    print(f"  测试集: 精确率={r_test['precision']:.3f}  召回率={r_test['recall']:.3f}  "
          f"F1={r_test['f1']:.3f}"
          f"  TP={r_test['tp']} FP={r_test['fp']} FN={r_test['fn']} TN={r_test['tn']}")
    print(f"  ← 测试集 F1={r_test['f1']:.3f} 是对真实泛化能力的估计，训练集 F1={f1:.3f} 仅供参考")

    print("\n将以上参数填到 run.py 顶部配置区即可（或命令行 --threshold/--peak/--area/--comp-ratio）。")


if __name__ == "__main__":
    main()
