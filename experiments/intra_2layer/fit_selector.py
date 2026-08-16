#!/usr/bin/env python3
"""Explore hardware-friendly layer classifiers from anchor CTU statistics."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "experiment" / "intra_2layer" / "results"


def load_rows():
    rows = []
    for path in RESULTS.glob("*/QP*/all/ctu_stats.csv"):
        sequence = path.parts[-4]
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row["sequence"] = sequence
                rows.append(row)
    return rows


def best_threshold(score, target, valid):
    values = score[valid]
    labels = target[valid]
    order = np.argsort(values)
    values = values[order]
    labels = labels[order]
    # Prediction is LOW(1) when score > threshold.
    low_total = labels.sum()
    high_total = len(labels) - low_total
    prefix_low = np.cumsum(labels)
    prefix_high = np.cumsum(1 - labels)
    correct = prefix_high + (low_total - prefix_low)
    index = int(np.argmax(correct))
    threshold = float(values[index])
    return threshold, float(correct[index] / len(labels))


def evaluate(score, target, valid, threshold):
    pred = score > threshold
    return float(np.mean(pred[valid] == target[valid]))


@dataclass
class Node:
    prediction: bool
    samples: int
    low_fraction: float
    feature: int = -1
    threshold: float = 0.0
    left: "Node | None" = None
    right: "Node | None" = None


def build_tree(x, y, indices, depth, max_depth, min_leaf):
    labels = y[indices].astype(np.int64)
    low_count = int(labels.sum())
    node = Node(low_count * 2 >= len(indices), len(indices), low_count / len(indices))
    if depth >= max_depth or len(indices) < 2 * min_leaf or low_count == 0 or low_count == len(indices):
        return node

    best = None
    total_low = low_count
    n = len(indices)
    for feature in range(x.shape[1]):
        values = x[indices, feature]
        order = np.argsort(values, kind="stable")
        sorted_values = values[order]
        sorted_labels = labels[order]
        prefix_low = np.cumsum(sorted_labels)[:-1]
        left_n = np.arange(1, n, dtype=np.int64)
        right_n = n - left_n
        right_low = total_low - prefix_low
        # Weighted Gini impurity, with the factor of two omitted.
        impurity = (prefix_low * (left_n - prefix_low) / left_n +
                    right_low * (right_n - right_low) / right_n)
        allowed = ((left_n >= min_leaf) & (right_n >= min_leaf) &
                   (sorted_values[:-1] < sorted_values[1:]))
        if not np.any(allowed):
            continue
        impurity[~allowed] = np.inf
        split = int(np.argmin(impurity))
        candidate = (float(impurity[split]), feature, split, order, sorted_values)
        if best is None or candidate[:3] < best[:3]:
            best = candidate

    if best is None:
        return node
    _, feature, split, order, sorted_values = best
    node.feature = feature
    node.threshold = float((sorted_values[split] + sorted_values[split + 1]) * 0.5)
    node.left = build_tree(x, y, indices[order[:split + 1]], depth + 1, max_depth, min_leaf)
    node.right = build_tree(x, y, indices[order[split + 1:]], depth + 1, max_depth, min_leaf)
    return node


def predict_tree(node, x, max_depth=None, depth=0):
    if node.feature < 0 or (max_depth is not None and depth >= max_depth):
        return np.full(len(x), node.prediction, dtype=np.bool_)
    right = x[:, node.feature] > node.threshold
    result = np.empty(len(x), dtype=np.bool_)
    result[~right] = predict_tree(node.left, x[~right], max_depth, depth + 1)
    result[right] = predict_tree(node.right, x[right], max_depth, depth + 1)
    return result


def print_tree(node, feature_names, depth=0, max_depth=None):
    indent = "  " * depth
    leaf_text = "LOW" if node.prediction else "HIGH"
    if node.feature < 0 or (max_depth is not None and depth >= max_depth):
        print(f"{indent}return {leaf_text};  // n={node.samples}, low={node.low_fraction:.3f}")
        return
    print(f"{indent}if ({feature_names[node.feature]} <= {node.threshold:.6g}) {{")
    print_tree(node.left, feature_names, depth + 1, max_depth)
    print(f"{indent}}} else {{")
    print_tree(node.right, feature_names, depth + 1, max_depth)
    print(f"{indent}}}  // n={node.samples}, low={node.low_fraction:.3f}")


def main():
    rows = load_rows()
    if not rows:
        raise SystemExit("No anchor CTU statistics found")

    def col(name):
        return np.asarray([int(row[name]) for row in rows], dtype=np.float64)

    sequence = np.asarray([row["sequence"] for row in rows])
    oracle = np.asarray([row["oracle"] for row in rows])
    valid = oracle != "both"
    target = oracle == "low"
    qstep_q8 = col("qstep_q8")
    qstep = qstep_q8 / 256.0
    sad32, sad16, sad8 = col("sad32"), col("sad16"), col("sad8")
    gain32 = np.maximum(0, sad32 - sad16)
    gain8 = np.maximum(0, sad16 - sad8)
    grad = col("grad_h") + col("grad_v")
    lap = col("laplacian")
    grad_h, grad_v = col("grad_h"), col("grad_v")
    qp = col("qp")

    print(f"rows={len(rows)} nonneutral={valid.sum()} neutral={(~valid).sum()}")
    print(f"nonneutral LOW={target[valid].sum()} HIGH={(~target[valid]).sum()}")

    candidates = {
        "gain8/qstep": gain8 / qstep,
        "grad/qstep": grad / qstep,
        "lap/qstep": lap / qstep,
        "(gain8+grad/4)/qstep": (gain8 + grad / 4) / qstep,
        "(gain8+lap/4)/qstep": (gain8 + lap / 4) / qstep,
        "(gain8+grad/4+lap/8)/qstep": (gain8 + grad / 4 + lap / 8) / qstep,
        "sad8/qstep": sad8 / qstep,
        "gain8/(qstep^2)": gain8 / (qstep * qstep),
        "gain8/qstep+gain32/(4*qstep)": (gain8 + gain32 / 4) / qstep,
    }

    best = None
    for name, score in candidates.items():
        threshold, accuracy = best_threshold(score, target, valid)
        record = (accuracy, name, threshold)
        if best is None or record > best:
            best = record
        print(f"{name:42s} threshold={threshold:10.3f} train={accuracy*100:6.2f}%")

    print("\nleave-one-sequence-out for best scalar candidates")
    for name, score in candidates.items():
        fold_acc = []
        for held_out in sorted(set(sequence)):
            train = valid & (sequence != held_out)
            test = valid & (sequence == held_out)
            threshold, _ = best_threshold(score, target, train)
            fold_acc.append(evaluate(score, target, test, threshold))
        print(f"{name:42s} mean={np.mean(fold_acc)*100:6.2f}% min={np.min(fold_acc)*100:6.2f}%")

    # Every feature below is implementable with additions, absolute differences,
    # integer multiplies and comparisons.  Division is only used while fitting;
    # the generated C++ compares numerator*scale with threshold*denominator.
    feature_names = [
        "sad32/qstep", "sad16/qstep", "sad8/qstep",
        "gain32/qstep", "gain8/qstep", "grad/qstep", "lap/qstep",
        "anisotropy/qstep", "gain8/sad16", "gain32/sad32",
        "grad/sad8", "lap/grad", "edge4", "edge8", "edge16", "edge32",
        "qp", "sad8/qstep2", "grad/qstep2", "lap/qstep2",
    ]
    eps = 1.0
    features = np.column_stack([
        sad32 / qstep, sad16 / qstep, sad8 / qstep,
        gain32 / qstep, gain8 / qstep, grad / qstep, lap / qstep,
        np.abs(grad_h - grad_v) / qstep,
        gain8 / (sad16 + eps), gain32 / (sad32 + eps),
        grad / (sad8 + eps), lap / (grad + eps),
        col("edge4"), col("edge8"), col("edge16"), col("edge32"), qp,
        sad8 / (qstep * qstep), grad / (qstep * qstep), lap / (qstep * qstep),
    ])

    # The last CTU row is only 24 pixels high in 1080p.  Its mandatory boundary
    # split is not a genuine 32/16/8 layer decision, so exclude it from fitting.
    interior = col("y") < 1056
    tree_valid = valid & interior
    train_indices = np.flatnonzero(tree_valid)
    print(f"\ninteger-friendly CART: train rows={len(train_indices)} (partial bottom CTUs excluded)")
    tree = build_tree(features, target, train_indices, 0, 7, 800)
    for depth in range(1, 8):
        pred = predict_tree(tree, features[tree_valid], max_depth=depth)
        nonneutral_accuracy = np.mean(pred == target[tree_valid])
        overall_accuracy = ((pred == target[tree_valid]).sum() + ((~valid) & interior).sum()) / interior.sum()
        print(f"depth={depth} nonneutral={nonneutral_accuracy*100:6.2f}% overall-with-neutral={overall_accuracy*100:6.2f}%")

    print("\nleave-one-sequence-out CART depth=5")
    for held_out in sorted(set(sequence)):
        train_mask = tree_valid & (sequence != held_out)
        test_mask = tree_valid & (sequence == held_out)
        fold_tree = build_tree(features, target, np.flatnonzero(train_mask), 0, 5, 600)
        pred = predict_tree(fold_tree, features[test_mask])
        nonneutral_accuracy = np.mean(pred == target[test_mask])
        neutral_test = ((~valid) & interior & (sequence == held_out)).sum()
        all_test = (interior & (sequence == held_out)).sum()
        overall_accuracy = ((pred == target[test_mask]).sum() + neutral_test) / all_test
        print(f"{held_out:20s} nonneutral={nonneutral_accuracy*100:6.2f}% overall={overall_accuracy*100:6.2f}%")

    print("\ndepth-4 tree (portable candidate):")
    print_tree(tree, feature_names, max_depth=4)


if __name__ == "__main__":
    main()
