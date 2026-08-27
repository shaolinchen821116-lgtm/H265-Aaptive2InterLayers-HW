#!/usr/bin/env python3
"""Train a corrected-sum-cost-rooted CART for P-frame two-layer gating.

The first decision is whether sum(J8[0..15]) plus five split bits is no
greater than J32 plus one split bit. Child CARTs then correct that estimate
using integer texture, SAD-gain, and MV-consistency features.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import train_inter_multiscale_tree as cart


EXTRA_FEATURES = [
    "sum_cost_prefers_low", "sum_cost_ratio_bin", "cost32_q8pp",
    "sum_cost8_q8pp", "sum_cost_abs_delta_q8pp",
    "sum_group_mean_q8pp", "sum_group_range_q8pp", "sum_group_mad_q8pp",
    "min4_cost8_q8pp", "min4_optimism_q8pp", "sqrt_lambda_q8",
]
FEATURES = cart.FEATURES + EXTRA_FEATURES
COST_ROOT_INDEX = len(cart.FEATURES)


def ratio_bin(cost8: int, cost32: int) -> int:
    for index, (left, right) in enumerate(((3, 4), (7, 8), (1, 1),
                                           (9, 8), (5, 4), (3, 2))):
        if cost8 * right <= cost32 * left:
            return index
    return 6


def load_samples(runs_csv: Path) -> tuple[list[cart.Sample], dict[str, int]]:
    with runs_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        runs = list(csv.DictReader(handle))
    samples: list[cart.Sample] = []
    counters = {"ms_records": 0, "sum_records": 0, "valid": 0,
                "invalid": 0, "bad_fields": 0, "unpaired": 0}
    for run in runs:
        if run.get("mode") != "hw":
            continue
        pending: dict[tuple[str, str, str], tuple[tuple[int, ...], int]] = {}
        log = runs_csv.parent / f'{run["sequence"]}_qp{run["qp"]}_hw.log'
        with log.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                fields = line.rstrip().split(",")
                if line.startswith("INTERLAYERMS,"):
                    counters["ms_records"] += 1
                    if len(fields) != 38:
                        counters["bad_fields"] += 1
                        continue
                    if fields[4] != "1":
                        counters["invalid"] += 1
                        continue
                    pending[(fields[1], fields[2], fields[3])] = (
                        tuple(int(v) for v in fields[5:34]),
                        int(fields[37] == "low"))
                elif line.startswith("INTERLAYERCOSTSUM,"):
                    counters["sum_records"] += 1
                    if len(fields) != 19:
                        counters["bad_fields"] += 1
                        continue
                    if fields[4] != "1":
                        continue
                    key = (fields[1], fields[2], fields[3])
                    base = pending.pop(key, None)
                    if base is None:
                        counters["unpaired"] += 1
                        continue
                    cost32 = int(fields[7])
                    groups = [int(v) for v in fields[8:12]]
                    sum_cost = int(fields[12])
                    min4_cost = int(fields[13])
                    group_mean = (sum(groups) + 2) >> 2
                    group_mad = (sum(abs(v - group_mean) for v in groups) + 2) >> 2
                    extra = (
                        int(sum_cost <= cost32), ratio_bin(sum_cost, cost32),
                        (cost32 + 2) >> 2, (sum_cost + 2) >> 2,
                        (abs(sum_cost - cost32) + 2) >> 2, group_mean,
                        max(groups) - min(groups), group_mad,
                        (min4_cost + 2) >> 2,
                        (max(sum_cost - min4_cost, 0) + 2) >> 2,
                        int(fields[6]),
                    )
                    samples.append(cart.Sample(run["sequence"], base[0] + extra,
                                               base[1]))
                    counters["valid"] += 1
        counters["unpaired"] += len(pending)
    if not samples:
        raise RuntimeError("no paired INTERLAYERMS/INTERLAYERCOSTSUM samples")
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
    left_low = sum(samples[i].low for i in left)
    right_low = low_count - left_low
    node.gain = cart.impurity(weighted_low, high_count) - (
        cart.impurity(left_low * low_weight, len(left) - left_low) +
        cart.impurity(right_low * low_weight, len(right) - right_low))
    node.left = cart.build_tree(samples, left, 1, max_depth,
                                min_leaf, low_weight)
    node.right = cart.build_tree(samples, right, 1, max_depth,
                                 min_leaf, low_weight)
    return node


def write_header(path: Path, node: cart.Node) -> None:
    lines = [
        "/****************************************************************************",
        " * Generated by train_inter_sum_cost_tree.py. Do not hand edit.",
        " * Forced root: sum(J8[0..15])+split <= J32+split.",
        " ****************************************************************************/",
        "#ifndef X265_INTER_SUM_COST_GATE_MODEL_H",
        "#define X265_INTER_SUM_COST_GATE_MODEL_H", "", "#include <stdint.h>", "",
        "static inline uint32_t hwInterSumCostLowProbability(const uint32_t* f)",
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
    parser.add_argument("--recommended-cutoff", type=int, default=50)
    parser.add_argument("--sample-stride", type=int, default=4,
                        help="deterministic CTU subsampling stride for CART fitting")
    parser.add_argument("--cpp-header", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    samples, counters = load_samples(args.runs.resolve())
    if args.sample_stride < 1:
        parser.error("sample stride must be at least one")
    if args.sample_stride > 1:
        total_valid = len(samples)
        samples = [sample for index, sample in enumerate(samples)
                   if index % args.sample_stride == 0]
        counters["fit_stride"] = args.sample_stride
        counters["fit_samples"] = len(samples)
        counters["all_valid_samples"] = total_valid
    cart.FEATURES = FEATURES
    sequences = sorted({sample.sequence for sample in samples})

    pure_probabilities = [float(s.values[COST_ROOT_INDEX]) for s in samples]
    pure = cart.metrics(samples, pure_probabilities, 0.5)

    probabilities = [0.0] * len(samples)
    for sequence in sequences:
        train = [i for i, sample in enumerate(samples) if sample.sequence != sequence]
        test = [i for i, sample in enumerate(samples) if sample.sequence == sequence]
        tree = build_cost_root(samples, train, args.max_depth,
                               args.min_leaf, args.low_weight)
        for i in test:
            probabilities[i] = cart.predict_probability(tree, samples[i])

    threshold_rows = []
    for cutoff in cart.parse_cutoffs(args.cutoffs):
        row: dict[str, object] = {"cutoff": round(cutoff * 100)}
        row.update(cart.metrics(samples, probabilities, cutoff))
        threshold_rows.append(row)
    cart.write_csv(args.output / "inter_sum_cost_thresholds_cv.csv", threshold_rows)

    selected = args.recommended_cutoff / 100.0
    sequence_rows = []
    for sequence in sequences:
        picked = [i for i, sample in enumerate(samples) if sample.sequence == sequence]
        row: dict[str, object] = {"sequence": sequence,
                                  "cutoff": args.recommended_cutoff}
        row.update(cart.metrics([samples[i] for i in picked],
                                [probabilities[i] for i in picked], selected))
        sequence_rows.append(row)
    overall: dict[str, object] = {"sequence": "All leave-one-sequence-out",
                                  "cutoff": args.recommended_cutoff}
    overall.update(cart.metrics(samples, probabilities, selected))
    sequence_rows.append(overall)
    cart.write_csv(args.output / "inter_sum_cost_sequence_cv.csv", sequence_rows)

    final_tree = build_cost_root(samples, list(range(len(samples))),
                                 args.max_depth, args.min_leaf, args.low_weight)
    counts = [0] * len(FEATURES)
    gains = [0.0] * len(FEATURES)
    cart.split_usage(final_tree, counts, gains)
    usage = [{"feature_index": i, "feature": name, "split_count": counts[i],
              "total_weighted_gini_gain": gains[i]}
             for i, name in enumerate(FEATURES) if counts[i]]
    usage.sort(key=lambda row: float(row["total_weighted_gini_gain"]), reverse=True)
    cart.write_csv(args.output / "inter_sum_cost_feature_usage.csv", usage)
    model = {"features": FEATURES, "forced_sum_cost_root": True,
             "max_depth": args.max_depth, "min_leaf": args.min_leaf,
             "low_weight": args.low_weight,
             "sample_stride": args.sample_stride,
             "recommended_cutoff": args.recommended_cutoff,
             "sample_counters": counters, "pure_sum_cost_metrics": pure,
             "loo_metrics": overall, "tree": cart.node_to_dict(final_tree)}
    (args.output / "inter_sum_cost_tree.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "inter_sum_cost_tree.txt").write_text(
        "\n".join(cart.tree_text(final_tree)) + "\n", encoding="utf-8")
    generated = args.output / "inter_sum_cost_gate_model.h"
    write_header(generated, final_tree)
    if args.cpp_header:
        write_header(args.cpp_header, final_tree)
    print(json.dumps({"counters": counters, "pure_sum": pure,
                      "loo": overall, "top_features": usage[:12]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
