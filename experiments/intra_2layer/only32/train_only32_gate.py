#!/usr/bin/env python3
"""Train and inspect a hardware-friendly ONLY32 confidence tree.

The model uses Class B anchor CTUs for fitting and reports Class A/C/E as an
independent validation set.  It never reads reconstructed pixels, prediction
modes, neighboring decisions, or encoder state; the inputs are the same
source-luma features and QP used by the two-layer selector.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np


EXP = Path(__file__).resolve().parents[1]
RESULTS = EXP / "results"
OUT = Path(__file__).resolve().parent / "model"

CLASS_BY_SEQUENCE = {
    "BasketballDrive": "ClassB", "BQTerrace": "ClassB", "Cactus": "ClassB",
    "Kimono1": "ClassB", "ParkScene": "ClassB",
    "PeopleOnStreet": "ClassA", "Traffic": "ClassA",
    "BasketballDrill": "ClassC", "BQMall": "ClassC", "PartyScene": "ClassC",
    "RaceHorsesC": "ClassC",
    "FourPeople": "ClassE", "Johnny": "ClassE", "KristenAndSara": "ClassE",
    "vidyo1": "ClassE", "vidyo3": "ClassE", "vidyo4": "ClassE",
}


@dataclass
class Node:
    samples: int
    positives: int
    probability: float
    feature: int = -1
    threshold: float = 0.0
    left: "Node | None" = None
    right: "Node | None" = None


def load_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(RESULTS.glob("*/QP*/all/ctu_stats.csv")):
        sequence = path.parts[-4]
        if sequence not in CLASS_BY_SEQUENCE:
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                # The selector API requires a complete 32x32 block.  Anchor
                # boundary CTUs that are forced to split are not trainable
                # layer decisions and are deliberately excluded.
                width = {"ClassA": 2560, "ClassB": 1920, "ClassC": 832,
                         "ClassE": 1280}[CLASS_BY_SEQUENCE[sequence]]
                height = {"ClassA": 1600, "ClassB": 1080, "ClassC": 480,
                          "ClassE": 720}[CLASS_BY_SEQUENCE[sequence]]
                if int(row["x"]) + 32 > width or int(row["y"]) + 32 > height:
                    continue
                row["sequence"] = sequence
                row["class"] = CLASS_BY_SEQUENCE[sequence]
                rows.append(row)
    return rows


def columns(rows: list[dict[str, str]]):
    def col(name: str) -> np.ndarray:
        return np.asarray([int(r[name]) for r in rows], dtype=np.float64)

    qstep = col("qstep_q8") / 256.0
    sad32, sad16, sad8 = col("sad32"), col("sad16"), col("sad8")
    gain32 = np.maximum(0.0, sad32 - sad16)
    gain8 = np.maximum(0.0, sad16 - sad8)
    grad_h, grad_v = col("grad_h"), col("grad_v")
    grad = grad_h + grad_v
    lap = col("laplacian")
    eps = 1.0
    names = [
        "sad32/qstep", "sad16/qstep", "sad8/qstep",
        "gain32/qstep", "gain8/qstep", "grad/qstep", "lap/qstep",
        "anisotropy/qstep", "gain8/sad16", "gain32/sad32",
        "grad/sad8", "lap/grad", "edge4", "edge8", "edge16", "edge32",
        "qp", "sad32/qstep2", "sad16/qstep2", "sad8/qstep2",
        "grad/qstep2", "lap/qstep2",
    ]
    x = np.column_stack([
        sad32 / qstep, sad16 / qstep, sad8 / qstep,
        gain32 / qstep, gain8 / qstep, grad / qstep, lap / qstep,
        np.abs(grad_h - grad_v) / qstep,
        gain8 / (sad16 + eps), gain32 / (sad32 + eps),
        grad / (sad8 + eps), lap / (grad + eps),
        col("edge4"), col("edge8"), col("edge16"), col("edge32"), col("qp"),
        sad32 / (qstep * qstep), sad16 / (qstep * qstep),
        sad8 / (qstep * qstep), grad / (qstep * qstep), lap / (qstep * qstep),
    ])
    # A complete root CTU has leaf32=1 exactly when full RDO retained 32x32.
    y = col("leaf32") > 0
    return x, y, names


def build_tree(x: np.ndarray, y: np.ndarray, idx: np.ndarray, depth: int,
               max_depth: int, min_leaf: int) -> Node:
    positives = int(y[idx].sum())
    node = Node(len(idx), positives, positives / len(idx))
    if depth >= max_depth or len(idx) < 2 * min_leaf or positives in (0, len(idx)):
        return node

    labels = y[idx].astype(np.int64)
    best = None
    for feature in range(x.shape[1]):
        values = x[idx, feature]
        order = np.argsort(values, kind="stable")
        sv, sy = values[order], labels[order]
        left_n = np.arange(1, len(idx), dtype=np.int64)
        right_n = len(idx) - left_n
        left_pos = np.cumsum(sy)[:-1]
        right_pos = positives - left_pos
        # Weighted Gini; constant factor two is omitted.
        impurity = (left_pos * (left_n - left_pos) / left_n +
                    right_pos * (right_n - right_pos) / right_n)
        valid = ((left_n >= min_leaf) & (right_n >= min_leaf) &
                 (sv[:-1] < sv[1:]))
        if not np.any(valid):
            continue
        impurity[~valid] = np.inf
        split = int(np.argmin(impurity))
        candidate = (float(impurity[split]), feature, split, order, sv)
        if best is None or candidate[:3] < best[:3]:
            best = candidate

    if best is None:
        return node
    _, feature, split, order, sv = best
    node.feature = feature
    node.threshold = float((sv[split] + sv[split + 1]) * 0.5)
    node.left = build_tree(x, y, idx[order[:split + 1]], depth + 1,
                           max_depth, min_leaf)
    node.right = build_tree(x, y, idx[order[split + 1:]], depth + 1,
                            max_depth, min_leaf)
    return node


def score_tree(node: Node, x: np.ndarray) -> np.ndarray:
    if node.feature < 0:
        return np.full(len(x), int(round(node.probability * 100)), dtype=np.int16)
    right = x[:, node.feature] > node.threshold
    score = np.empty(len(x), dtype=np.int16)
    score[~right] = score_tree(node.left, x[~right])
    score[right] = score_tree(node.right, x[right])
    return score


def node_dict(node: Node, names: list[str]) -> dict:
    result = asdict(node)
    result["feature_name"] = names[node.feature] if node.feature >= 0 else None
    if node.left is not None:
        result["left"] = node_dict(node.left, names)
    if node.right is not None:
        result["right"] = node_dict(node.right, names)
    return result


def metrics(y: np.ndarray, score: np.ndarray, mask: np.ndarray, cutoff: int) -> dict:
    pred = score >= cutoff
    chosen = pred & mask
    tp = int((chosen & y).sum())
    fp = int((chosen & ~y).sum())
    positives = int((mask & y).sum())
    return {
        "rows": int(mask.sum()),
        "anchor_only32": positives / int(mask.sum()),
        "cutoff": cutoff,
        "selected_only32": int(chosen.sum()) / int(mask.sum()),
        "precision": tp / max(1, tp + fp),
        "recall": tp / max(1, positives),
        "false_positive_rate_all": fp / int(mask.sum()),
        "tp": tp, "fp": fp,
    }


def main() -> None:
    global RESULTS, OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--min-leaf", type=int, default=500)
    parser.add_argument("--cutoffs", nargs="+", type=int,
                        default=[80, 85, 90, 92, 94, 95, 96, 97, 98, 99, 100])
    args = parser.parse_args()
    RESULTS = args.results.resolve()
    OUT = args.output.resolve()

    rows = load_rows()
    x, y, names = columns(rows)
    classes = np.asarray([r["class"] for r in rows])
    sequences = np.asarray([r["sequence"] for r in rows])
    train = classes == "ClassB"
    valid = classes != "ClassB"
    tree = build_tree(x, y, np.flatnonzero(train), 0, args.depth, args.min_leaf)
    score = score_tree(tree, x)

    OUT.mkdir(parents=True, exist_ok=True)
    model = {
        "task": "ONLY32 vs fallback",
        "inputs": "original 32x32 8-bit luma and QP only",
        "train_classes": ["ClassB"],
        "validation_classes": ["ClassA", "ClassC", "ClassE"],
        "depth": args.depth,
        "min_leaf": args.min_leaf,
        "feature_names": names,
        "tree": node_dict(tree, names),
    }
    (OUT / "only32_tree.json").write_text(
        json.dumps(model, indent=2, ensure_ascii=False), encoding="utf-8")

    output_rows = []
    masks = [("train_ClassB", train), ("validation_ACE", valid)]
    masks += [(name, sequences == name) for name in sorted(set(sequences))]
    for cutoff in args.cutoffs:
        for name, mask in masks:
            output_rows.append({"set": name, **metrics(y, score, mask, cutoff)})
    with (OUT / "threshold_metrics.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"rows={len(rows)} train={train.sum()} validation={valid.sum()}")
    print(f"anchor ONLY32 train={y[train].mean()*100:.2f}% validation={y[valid].mean()*100:.2f}%")
    for cutoff in args.cutoffs:
        tr = metrics(y, score, train, cutoff)
        va = metrics(y, score, valid, cutoff)
        print(f"cutoff={cutoff:3d} "
              f"train selected={tr['selected_only32']*100:6.2f}% precision={tr['precision']*100:6.2f}% "
              f"ACE selected={va['selected_only32']*100:6.2f}% precision={va['precision']*100:6.2f}% "
              f"ACE FP/all={va['false_positive_rate_all']*100:6.3f}%")


if __name__ == "__main__":
    main()
