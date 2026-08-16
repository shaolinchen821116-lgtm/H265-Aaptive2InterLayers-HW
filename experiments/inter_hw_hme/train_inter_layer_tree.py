#!/usr/bin/env python3
"""Fit a tiny hardware-friendly CART from INTERLAYERSTAT records."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


STAT_RE = re.compile(
    r"^INTERLAYERSTAT,(\d+),(\d+),(\d+),(-?\d+),(\d+),(\d+),(\d+),"
    r"(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(high|low)$"
)
FEATURES = ["qp", "ime_sad_q8", "refine_l1", "mvd_qpel_l1",
            "mv_fullpel_l1", "pme_activity", "ime_boundary"]


@dataclass
class Sample:
    sequence: str
    values: tuple[int, ...]
    low: int


@dataclass
class Node:
    probability_low: float
    samples: int
    feature: int = -1
    threshold: int = 0
    left: "Node | None" = None
    right: "Node | None" = None


def load_samples(runs_csv: Path) -> list[Sample]:
    with runs_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        runs = list(csv.DictReader(handle))
    samples: list[Sample] = []
    for run in runs:
        if run.get("mode") != "hw":
            continue
        log = runs_csv.parent / f'{run["sequence"]}_qp{run["qp"]}_hw.log'
        with log.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = STAT_RE.match(line.rstrip())
                if not match:
                    continue
                fields = [int(value) for value in match.groups()[:-1]]
                _, _, _, qp, sad, refine, mvd, mv, activity, boundary, _, _, _ = fields
                samples.append(Sample(
                    run["sequence"],
                    (qp, sad, refine, mvd, mv, activity, boundary),
                    int(match.group(14) == "low"),
                ))
    if not samples:
        raise RuntimeError("no INTERLAYERSTAT records found")
    return samples


def impurity(low: float, high: float) -> float:
    total = low + high
    if total <= 0:
        return 0.0
    p = low / total
    return total * 2.0 * p * (1.0 - p)


def build_tree(samples: list[Sample], indices: list[int], depth: int,
               max_depth: int, min_leaf: int, low_weight: float) -> Node:
    low_count = sum(samples[index].low for index in indices)
    high_count = len(indices) - low_count
    weighted_low = low_count * low_weight
    node = Node(weighted_low / max(weighted_low + high_count, 1.0), len(indices))
    if depth >= max_depth or len(indices) < min_leaf * 2 or low_count == 0 or high_count == 0:
        return node

    best: tuple[float, int, int] | None = None
    for feature in range(len(FEATURES)):
        ordered = sorted(indices, key=lambda index: samples[index].values[feature])
        left_low = 0
        left_high = 0
        total_low = low_count
        total_high = high_count
        for position in range(len(ordered) - 1):
            label = samples[ordered[position]].low
            left_low += label
            left_high += 1 - label
            left_n = position + 1
            right_n = len(ordered) - left_n
            if left_n < min_leaf or right_n < min_leaf:
                continue
            value = samples[ordered[position]].values[feature]
            next_value = samples[ordered[position + 1]].values[feature]
            if value == next_value:
                continue
            right_low = total_low - left_low
            right_high = total_high - left_high
            score = impurity(left_low * low_weight, left_high) + \
                    impurity(right_low * low_weight, right_high)
            threshold = (value + next_value) // 2
            if best is None or score < best[0]:
                best = (score, feature, threshold)
    if best is None:
        return node

    _, feature, threshold = best
    left_indices = [index for index in indices
                    if samples[index].values[feature] <= threshold]
    right_indices = [index for index in indices
                     if samples[index].values[feature] > threshold]
    node.feature = feature
    node.threshold = threshold
    node.left = build_tree(samples, left_indices, depth + 1, max_depth,
                           min_leaf, low_weight)
    node.right = build_tree(samples, right_indices, depth + 1, max_depth,
                            min_leaf, low_weight)
    return node


def predict_probability(node: Node, sample: Sample) -> float:
    while node.feature >= 0:
        node = node.left if sample.values[node.feature] <= node.threshold else node.right  # type: ignore[assignment]
    return node.probability_low


def metrics(samples: list[Sample], probabilities: list[float], cutoff: float) -> dict[str, float]:
    tp = tn = fp = fn = 0
    for sample, probability in zip(samples, probabilities):
        pred = probability >= cutoff
        if sample.low and pred:
            tp += 1
        elif sample.low:
            fn += 1
        elif pred:
            fp += 1
        else:
            tn += 1
    return {
        "samples": len(samples),
        "oracle_low_pct": 100.0 * (tp + fn) / len(samples),
        "selected_low_pct": 100.0 * (tp + fp) / len(samples),
        "accuracy_pct": 100.0 * (tp + tn) / len(samples),
        "false_high_pct_of_low": 100.0 * fn / max(tp + fn, 1),
        "false_low_pct_of_high": 100.0 * fp / max(tn + fp, 1),
    }


def node_to_dict(node: Node) -> dict[str, object]:
    result: dict[str, object] = {
        "samples": node.samples,
        "probability_low": round(node.probability_low, 8),
    }
    if node.feature >= 0:
        result.update({
            "feature": FEATURES[node.feature],
            "threshold": node.threshold,
            "left": node_to_dict(node.left),  # type: ignore[arg-type]
            "right": node_to_dict(node.right),  # type: ignore[arg-type]
        })
    return result


def tree_text(node: Node, indent: str = "") -> list[str]:
    if node.feature < 0:
        return [f"{indent}return {round(node.probability_low * 100)};  // n={node.samples}"]
    lines = [f"{indent}if ({FEATURES[node.feature]} <= {node.threshold})"]
    lines += tree_text(node.left, indent + "    ")  # type: ignore[arg-type]
    lines.append(f"{indent}else")
    lines += tree_text(node.right, indent + "    ")  # type: ignore[arg-type]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--min-leaf", type=int, default=256)
    parser.add_argument("--low-weight", type=float, default=3.0)
    parser.add_argument("--cutoff", type=float, default=0.5)
    args = parser.parse_args()
    output = args.output or args.runs.resolve().parent
    output.mkdir(parents=True, exist_ok=True)
    samples = load_samples(args.runs.resolve())

    probabilities = [0.0] * len(samples)
    for sequence in sorted({sample.sequence for sample in samples}):
        train_indices = [index for index, sample in enumerate(samples)
                         if sample.sequence != sequence]
        test_indices = [index for index, sample in enumerate(samples)
                        if sample.sequence == sequence]
        tree = build_tree(samples, train_indices, 0, args.max_depth,
                          args.min_leaf, args.low_weight)
        for index in test_indices:
            probabilities[index] = predict_probability(tree, samples[index])

    rows: list[dict[str, object]] = []
    for sequence in sorted({sample.sequence for sample in samples}):
        selected = [(sample, probability) for sample, probability in zip(samples, probabilities)
                    if sample.sequence == sequence]
        row = {"sequence": sequence}
        row.update(metrics([item[0] for item in selected],
                           [item[1] for item in selected], args.cutoff))
        rows.append(row)
    overall = {"sequence": "All leave-one-sequence-out"}
    overall.update(metrics(samples, probabilities, args.cutoff))
    rows.append(overall)
    with (output / "inter_layer_cv.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    final_tree = build_tree(samples, list(range(len(samples))), 0,
                            args.max_depth, args.min_leaf, args.low_weight)
    model = {
        "features": FEATURES,
        "max_depth": args.max_depth,
        "min_leaf": args.min_leaf,
        "low_weight": args.low_weight,
        "cutoff": args.cutoff,
        "sample_count": len(samples),
        "tree": node_to_dict(final_tree),
    }
    (output / "inter_layer_tree.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "inter_layer_tree.txt").write_text(
        "\n".join(tree_text(final_tree)) + "\n", encoding="utf-8")
    print(json.dumps(overall, ensure_ascii=False, indent=2))
    print("\n".join(tree_text(final_tree)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
