#!/usr/bin/env python3
"""Train a hardware-friendly P-frame high2/low2 tree from multi-scale IME logs.

Input is ``runs.csv`` produced with ``--hw-hme-inter-layers 7``.  Each valid
``INTERLAYERMS`` record contains 29 integer features aggregated from one CU32,
four CU16, and sixteen CU8 PME/IME probes.  The label is the complete 32/16/8
RDO result: any selected CU8 is LOW, otherwise HIGH.

The implementation intentionally has no third-party dependencies so it can be
reproduced on a clean Python installation.  It exports JSON, a readable tree,
cross-validation CSV files, and the exact C/C++ integer inference header used
by x265 mode 8.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path


FEATURES = [
    "qp", "sad32_q8", "refine32_l1", "mvd32_qpel_l1",
    "mv32_fullpel_l1", "activity32", "boundary32",
    "sad16_mean_q8", "sad16_range_q8", "sad16_mad_q8",
    "sad8_mean_q8", "sad8_range_q8", "sad8_mad_q8",
    "sad_gain32_to16_q8", "sad_gain16_to8_q8",
    "sad_gain16_to8_max_q8", "mv16_root_mean_l1",
    "mv16_root_max_l1", "mv16_span_l1", "mv8_parent_mean_l1",
    "mv8_parent_max_l1", "mv8_root_mean_l1", "mv8_root_max_l1",
    "mv8_span_l1", "activity16_mean", "activity16_range",
    "activity8_mean", "activity8_range", "boundary_count",
]


@dataclass(slots=True)
class Sample:
    sequence: str
    values: tuple[int, ...]
    low: int


@dataclass
class Node:
    probability_low: float
    samples: int
    low_samples: int
    feature: int = -1
    threshold: int = 0
    gain: float = 0.0
    left: "Node | None" = None
    right: "Node | None" = None


def load_samples(runs_csv: Path) -> tuple[list[Sample], dict[str, int]]:
    with runs_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        runs = list(csv.DictReader(handle))
    samples: list[Sample] = []
    counters = {"records": 0, "valid": 0, "invalid": 0, "bad_fields": 0}
    for run in runs:
        if run.get("mode") != "hw":
            continue
        log = runs_csv.parent / f'{run["sequence"]}_qp{run["qp"]}_hw.log'
        with log.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.startswith("INTERLAYERMS,"):
                    continue
                counters["records"] += 1
                parts = line.rstrip().split(",")
                if len(parts) != 38:
                    counters["bad_fields"] += 1
                    continue
                if int(parts[4]) == 0:
                    counters["invalid"] += 1
                    continue
                values = tuple(int(value) for value in parts[5:34])
                if len(values) != len(FEATURES):
                    counters["bad_fields"] += 1
                    continue
                samples.append(Sample(run["sequence"], values,
                                      int(parts[37] == "low")))
                counters["valid"] += 1
    if not samples:
        raise RuntimeError("no valid INTERLAYERMS records found")
    return samples, counters


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
    parent_score = impurity(weighted_low, high_count)
    node = Node(weighted_low / max(weighted_low + high_count, 1.0),
                len(indices), low_count)
    if (depth >= max_depth or len(indices) < min_leaf * 2 or
            not low_count or not high_count):
        return node

    best: tuple[float, int, int] | None = None
    for feature in range(len(FEATURES)):
        ordered = sorted(indices, key=lambda index, f=feature: samples[index].values[f])
        left_low = 0
        left_high = 0
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
            right_low = low_count - left_low
            right_high = high_count - left_high
            score = impurity(left_low * low_weight, left_high) + \
                    impurity(right_low * low_weight, right_high)
            threshold = (value + next_value) // 2
            candidate = (score, feature, threshold)
            if best is None or candidate < best:
                best = candidate
    if best is None or best[0] >= parent_score:
        return node

    score, feature, threshold = best
    left_indices = [index for index in indices
                    if samples[index].values[feature] <= threshold]
    right_indices = [index for index in indices
                     if samples[index].values[feature] > threshold]
    node.feature = feature
    node.threshold = threshold
    node.gain = parent_score - score
    node.left = build_tree(samples, left_indices, depth + 1, max_depth,
                           min_leaf, low_weight)
    node.right = build_tree(samples, right_indices, depth + 1, max_depth,
                            min_leaf, low_weight)
    return node


def predict_probability(node: Node, sample: Sample) -> float:
    while node.feature >= 0:
        node = node.left if sample.values[node.feature] <= node.threshold else node.right  # type: ignore[assignment]
    return node.probability_low


def metrics(samples: list[Sample], probabilities: list[float], cutoff: float) -> dict[str, float | int]:
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
    count = max(len(samples), 1)
    low_count = max(tp + fn, 1)
    high_count = max(tn + fp, 1)
    return {
        "samples": len(samples),
        "oracle_low_pct": 100.0 * (tp + fn) / count,
        "selected_low_pct": 100.0 * (tp + fp) / count,
        "accuracy_pct": 100.0 * (tp + tn) / count,
        "balanced_accuracy_pct": 50.0 * (tp / low_count + tn / high_count),
        "low_recall_pct": 100.0 * tp / low_count,
        "low_precision_pct": 100.0 * tp / max(tp + fp, 1),
        "false_high_pct_of_low": 100.0 * fn / low_count,
        "false_low_pct_of_high": 100.0 * fp / high_count,
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
    }


def node_to_dict(node: Node) -> dict[str, object]:
    result: dict[str, object] = {
        "samples": node.samples,
        "low_samples": node.low_samples,
        "probability_low": round(node.probability_low, 8),
    }
    if node.feature >= 0:
        result.update({
            "feature": FEATURES[node.feature],
            "feature_index": node.feature,
            "threshold": node.threshold,
            "gain": round(node.gain, 6),
            "left": node_to_dict(node.left),  # type: ignore[arg-type]
            "right": node_to_dict(node.right),  # type: ignore[arg-type]
        })
    return result


def tree_text(node: Node, indent: str = "") -> list[str]:
    if node.feature < 0:
        return [f"{indent}return {round(node.probability_low * 100)};  // n={node.samples}, low={node.low_samples}"]
    lines = [f"{indent}if ({FEATURES[node.feature]} <= {node.threshold})"]
    lines += tree_text(node.left, indent + "    ")  # type: ignore[arg-type]
    lines.append(f"{indent}else")
    lines += tree_text(node.right, indent + "    ")  # type: ignore[arg-type]
    return lines


def header_lines(node: Node, indent: str = "    ") -> list[str]:
    if node.feature < 0:
        return [f"{indent}return {round(node.probability_low * 100)}u;"]
    lines = [f"{indent}if (f[{node.feature}] <= {node.threshold}u)"]
    lines += header_lines(node.left, indent + "    ")  # type: ignore[arg-type]
    lines.append(f"{indent}else")
    lines += header_lines(node.right, indent + "    ")  # type: ignore[arg-type]
    return lines


def write_header(path: Path, node: Node) -> None:
    body = [
        "/****************************************************************************",
        " * Generated by train_inter_multiscale_tree.py. Do not hand edit.",
        " * Input: 1xCU32 + 4xCU16 + 16xCU8 integer PME/IME aggregates.",
        " ****************************************************************************/",
        "#ifndef X265_INTER_MULTISCALE_GATE_MODEL_H",
        "#define X265_INTER_MULTISCALE_GATE_MODEL_H",
        "",
        "#include <stdint.h>",
        "",
        "static inline uint32_t hwInterMultiscaleLowProbability(const uint32_t* f)",
        "{",
    ]
    body += header_lines(node)
    body += ["}", "", "#endif", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body), encoding="utf-8")


def split_usage(node: Node, counts: list[int], gains: list[float]) -> None:
    if node.feature < 0:
        return
    counts[node.feature] += 1
    gains[node.feature] += node.gain
    split_usage(node.left, counts, gains)  # type: ignore[arg-type]
    split_usage(node.right, counts, gains)  # type: ignore[arg-type]


def parse_cutoffs(text: str) -> list[float]:
    values = [float(item.strip()) for item in text.split(",") if item.strip()]
    return [value / 100.0 if value > 1.0 else value for value in values]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--min-leaf", type=int, default=512)
    parser.add_argument("--low-weight", type=float, default=1.0)
    parser.add_argument("--cutoffs", default="30,35,40,45,50,55,60,65,70")
    parser.add_argument("--recommended-cutoff", type=int, default=50)
    parser.add_argument("--cpp-header", type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    samples, counters = load_samples(args.runs.resolve())
    sequences = sorted({sample.sequence for sample in samples})
    probabilities = [0.0] * len(samples)
    for sequence in sequences:
        train_indices = [i for i, sample in enumerate(samples)
                         if sample.sequence != sequence]
        test_indices = [i for i, sample in enumerate(samples)
                        if sample.sequence == sequence]
        tree = build_tree(samples, train_indices, 0, args.max_depth,
                          args.min_leaf, args.low_weight)
        for index in test_indices:
            probabilities[index] = predict_probability(tree, samples[index])

    cutoff_rows: list[dict[str, object]] = []
    for cutoff in parse_cutoffs(args.cutoffs):
        row: dict[str, object] = {"cutoff": round(cutoff * 100)}
        row.update(metrics(samples, probabilities, cutoff))
        cutoff_rows.append(row)
    write_csv(args.output / "inter_multiscale_thresholds_cv.csv", cutoff_rows)

    selected_cutoff = args.recommended_cutoff / 100.0
    sequence_rows: list[dict[str, object]] = []
    for sequence in sequences:
        picked = [i for i, sample in enumerate(samples) if sample.sequence == sequence]
        row: dict[str, object] = {"sequence": sequence,
                                  "cutoff": args.recommended_cutoff}
        row.update(metrics([samples[i] for i in picked],
                           [probabilities[i] for i in picked], selected_cutoff))
        sequence_rows.append(row)
    overall: dict[str, object] = {"sequence": "All leave-one-sequence-out",
                                  "cutoff": args.recommended_cutoff}
    overall.update(metrics(samples, probabilities, selected_cutoff))
    sequence_rows.append(overall)
    write_csv(args.output / "inter_multiscale_sequence_cv.csv", sequence_rows)

    final_tree = build_tree(samples, list(range(len(samples))), 0,
                            args.max_depth, args.min_leaf, args.low_weight)
    counts = [0] * len(FEATURES)
    gains = [0.0] * len(FEATURES)
    split_usage(final_tree, counts, gains)
    importance_rows = [
        {"feature_index": i, "feature": feature, "split_count": counts[i],
         "total_weighted_gini_gain": gains[i]}
        for i, feature in enumerate(FEATURES) if counts[i]
    ]
    importance_rows.sort(key=lambda row: float(row["total_weighted_gini_gain"]),
                         reverse=True)
    write_csv(args.output / "inter_multiscale_feature_usage.csv", importance_rows)

    model = {
        "features": FEATURES,
        "max_depth": args.max_depth,
        "min_leaf": args.min_leaf,
        "low_weight": args.low_weight,
        "recommended_cutoff": args.recommended_cutoff,
        "sample_counters": counters,
        "sample_count": len(samples),
        "sequence_count": len(sequences),
        "loo_metrics": overall,
        "tree": node_to_dict(final_tree),
    }
    (args.output / "inter_multiscale_tree.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "inter_multiscale_tree.txt").write_text(
        "\n".join(tree_text(final_tree)) + "\n", encoding="utf-8")
    generated = args.output / "inter_multiscale_gate_model.h"
    write_header(generated, final_tree)
    if args.cpp_header:
        write_header(args.cpp_header, final_tree)

    print(json.dumps({"counters": counters, "loo": overall,
                      "top_features": importance_rows[:10]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
