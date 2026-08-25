#!/usr/bin/env python3
"""Train a hierarchy-cost-rooted hardware CART for P-frame two-layer gating."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import train_inter_multiscale_tree as cart


HYBRID_FEATURES = cart.FEATURES + [
    "cost_prefers_low", "cost_ratio_bin", "cost32_q8pp",
    "cost8_to32_q8pp", "cost_abs_delta_q8pp", "cost8_group_mean_q8pp",
    "cost8_group_range_q8pp", "cost8_group_mad_q8pp",
    "root_mvd_bits", "sqrt_lambda_q8",
]
COST_ROOT_INDEX = len(cart.FEATURES)


def ratio_bin(cost8: int, cost32: int) -> int:
    if cost8 * 4 <= cost32 * 3:
        return 0
    if cost8 * 8 <= cost32 * 7:
        return 1
    if cost8 <= cost32:
        return 2
    if cost8 * 8 <= cost32 * 9:
        return 3
    if cost8 * 4 <= cost32 * 5:
        return 4
    if cost8 * 2 <= cost32 * 3:
        return 5
    return 6


def load_samples(runs_csv: Path) -> tuple[list[cart.Sample], dict[str, int]]:
    with runs_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        runs = list(csv.DictReader(handle))
    samples: list[cart.Sample] = []
    counters = {"ms_records": 0, "cost_records": 0, "valid": 0,
                "invalid": 0, "bad_fields": 0, "unpaired": 0}
    for run in runs:
        if run.get("mode") != "hw":
            continue
        pending: dict[tuple[str, str, str], tuple[tuple[int, ...], int]] = {}
        log = runs_csv.parent / f'{run["sequence"]}_qp{run["qp"]}_hw.log'
        with log.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                p = line.rstrip().split(",")
                if line.startswith("INTERLAYERMS,"):
                    counters["ms_records"] += 1
                    if len(p) != 38:
                        counters["bad_fields"] += 1
                        continue
                    if p[4] != "1":
                        counters["invalid"] += 1
                        continue
                    pending[(p[1], p[2], p[3])] = (
                        tuple(int(v) for v in p[5:34]), int(p[37] == "low"))
                elif line.startswith("INTERLAYERCOST,"):
                    counters["cost_records"] += 1
                    if len(p) != 22:
                        counters["bad_fields"] += 1
                        continue
                    if p[4] != "1":
                        continue
                    key = (p[1], p[2], p[3])
                    base = pending.pop(key, None)
                    if base is None:
                        counters["unpaired"] += 1
                        continue
                    cost32, cost8 = int(p[9]), int(p[16])
                    groups = [int(v) for v in p[11:15]]
                    group_mean = (sum(groups) + 2) >> 2
                    group_mad = (sum(abs(v - group_mean) for v in groups) + 2) >> 2
                    extra = (
                        int(cost8 <= cost32), ratio_bin(cost8, cost32),
                        (cost32 + 2) >> 2, (cost8 + 2) >> 2,
                        (abs(cost8 - cost32) + 2) >> 2, group_mean,
                        max(groups) - min(groups), group_mad,
                        int(p[8]), int(p[6]),
                    )
                    samples.append(cart.Sample(run["sequence"], base[0] + extra,
                                               base[1]))
                    counters["valid"] += 1
        counters["unpaired"] += len(pending)
    if not samples:
        raise RuntimeError("no paired INTERLAYERMS/INTERLAYERCOST samples")
    return samples, counters


def build_cost_root(samples: list[cart.Sample], indices: list[int],
                    max_depth: int, min_leaf: int,
                    low_weight: float) -> cart.Node:
    low_count = sum(samples[i].low for i in indices)
    high_count = len(indices) - low_count
    weighted_low = low_count * low_weight
    node = cart.Node(weighted_low / max(weighted_low + high_count, 1.0),
                     len(indices), low_count, feature=COST_ROOT_INDEX,
                     threshold=0)
    left = [i for i in indices if samples[i].values[COST_ROOT_INDEX] == 0]
    right = [i for i in indices if samples[i].values[COST_ROOT_INDEX] == 1]
    if len(left) < min_leaf or len(right) < min_leaf:
        return cart.build_tree(samples, indices, 0, max_depth,
                               min_leaf, low_weight)
    parent = cart.impurity(weighted_low, high_count)
    left_low = sum(samples[i].low for i in left)
    right_low = low_count - left_low
    score = cart.impurity(left_low * low_weight, len(left) - left_low) + \
            cart.impurity(right_low * low_weight, len(right) - right_low)
    node.gain = parent - score
    node.left = cart.build_tree(samples, left, 1, max_depth,
                                min_leaf, low_weight)
    node.right = cart.build_tree(samples, right, 1, max_depth,
                                 min_leaf, low_weight)
    return node


def write_header(path: Path, node: cart.Node) -> None:
    lines = [
        "/****************************************************************************",
        " * Generated by train_inter_hybrid_cost_tree.py. Do not hand edit.",
        " * Forced root: cost8_to32 <= cost32; child trees learn corrections.",
        " ****************************************************************************/",
        "#ifndef X265_INTER_HYBRID_COST_GATE_MODEL_H",
        "#define X265_INTER_HYBRID_COST_GATE_MODEL_H", "", "#include <stdint.h>", "",
        "static inline uint32_t hwInterHybridCostLowProbability(const uint32_t* f)",
        "{",
    ] + cart.header_lines(node) + ["}", "", "#endif", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-depth", type=int, default=7)
    parser.add_argument("--min-leaf", type=int, default=256)
    parser.add_argument("--low-weight", type=float, default=1.5)
    parser.add_argument("--cutoffs", default="35,40,45,50,55,60,65")
    parser.add_argument("--recommended-cutoff", type=int, default=45)
    parser.add_argument("--cpp-header", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    samples, counters = load_samples(args.runs.resolve())
    cart.FEATURES = HYBRID_FEATURES
    sequences = sorted({s.sequence for s in samples})
    probabilities = [0.0] * len(samples)
    for sequence in sequences:
        train = [i for i, s in enumerate(samples) if s.sequence != sequence]
        test = [i for i, s in enumerate(samples) if s.sequence == sequence]
        tree = build_cost_root(samples, train, args.max_depth,
                               args.min_leaf, args.low_weight)
        for i in test:
            probabilities[i] = cart.predict_probability(tree, samples[i])

    threshold_rows: list[dict[str, object]] = []
    for cutoff in cart.parse_cutoffs(args.cutoffs):
        row: dict[str, object] = {"cutoff": round(cutoff * 100)}
        row.update(cart.metrics(samples, probabilities, cutoff))
        threshold_rows.append(row)
    cart.write_csv(args.output / "inter_hybrid_thresholds_cv.csv", threshold_rows)
    selected = args.recommended_cutoff / 100.0
    sequence_rows: list[dict[str, object]] = []
    for sequence in sequences:
        picked = [i for i, s in enumerate(samples) if s.sequence == sequence]
        row: dict[str, object] = {"sequence": sequence,
                                  "cutoff": args.recommended_cutoff}
        row.update(cart.metrics([samples[i] for i in picked],
                                [probabilities[i] for i in picked], selected))
        sequence_rows.append(row)
    overall: dict[str, object] = {"sequence": "All leave-one-sequence-out",
                                  "cutoff": args.recommended_cutoff}
    overall.update(cart.metrics(samples, probabilities, selected))
    sequence_rows.append(overall)
    cart.write_csv(args.output / "inter_hybrid_sequence_cv.csv", sequence_rows)

    final_tree = build_cost_root(samples, list(range(len(samples))),
                                 args.max_depth, args.min_leaf, args.low_weight)
    counts = [0] * len(HYBRID_FEATURES)
    gains = [0.0] * len(HYBRID_FEATURES)
    cart.split_usage(final_tree, counts, gains)
    usage = [{"feature_index": i, "feature": name,
              "split_count": counts[i], "total_weighted_gini_gain": gains[i]}
             for i, name in enumerate(HYBRID_FEATURES) if counts[i]]
    usage.sort(key=lambda row: float(row["total_weighted_gini_gain"]), reverse=True)
    cart.write_csv(args.output / "inter_hybrid_feature_usage.csv", usage)
    model = {"features": HYBRID_FEATURES, "forced_cost_root": True,
             "max_depth": args.max_depth, "min_leaf": args.min_leaf,
             "low_weight": args.low_weight,
             "recommended_cutoff": args.recommended_cutoff,
             "sample_counters": counters, "loo_metrics": overall,
             "tree": cart.node_to_dict(final_tree)}
    (args.output / "inter_hybrid_tree.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "inter_hybrid_tree.txt").write_text(
        "\n".join(cart.tree_text(final_tree)) + "\n", encoding="utf-8")
    generated = args.output / "inter_hybrid_cost_gate_model.h"
    write_header(generated, final_tree)
    if args.cpp_header:
        write_header(args.cpp_header, final_tree)
    print(json.dumps({"counters": counters, "loo": overall,
                      "top_features": usage[:12]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
