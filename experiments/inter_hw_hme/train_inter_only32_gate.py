#!/usr/bin/env python3
"""Train and export a conservative integer CART for P-frame CU32-only gating.

The input is the ``runs.csv`` produced by ``run_classb.py`` with
``--hw-hme-inter-layers 4``.  Every INTERLAYERSTAT line is one CU32 sample.
The positive label is ``leaf32 == 1`` in the complete 32/16/8 RDO result,
which means that the entire CTU selected CU32 and did not recurse.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path


STAT_RE = re.compile(
    r"^INTERLAYERSTAT,(\d+),(\d+),(\d+),(-?\d+),(\d+),(\d+),(\d+),"
    r"(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(high|low)$"
)
FEATURES = ["qp", "ime_sad_q8", "refine_l1", "mvd_qpel_l1",
            "mv_fullpel_l1", "pme_activity", "ime_boundary"]
CPP_NAMES = ["qp", "imeSadQ8", "refineL1", "mvdQPelL1",
             "mvFullPelL1", "pmeActivity", "imeBoundary"]


@dataclass(frozen=True)
class Sample:
    sequence: str
    values: tuple[int, ...]
    only32: int


@dataclass
class Node:
    probability_only32: float
    samples: int
    positives: int
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
        if not log.is_file():
            raise FileNotFoundError(log)
        with log.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = STAT_RE.match(line.rstrip())
                if not match:
                    continue
                fields = [int(value) for value in match.groups()[:-1]]
                _, _, _, qp, sad, refine, mvd, mv, activity, boundary, leaf32, _, _ = fields
                samples.append(Sample(
                    run["sequence"],
                    (qp, sad, refine, mvd, mv, activity, boundary),
                    int(leaf32 > 0),
                ))
    if not samples:
        raise RuntimeError("no INTERLAYERSTAT records found")
    return samples


def impurity(positive: float, negative: float) -> float:
    total = positive + negative
    if total <= 0:
        return 0.0
    probability = positive / total
    return total * 2.0 * probability * (1.0 - probability)


def build_tree(samples: list[Sample], indices: list[int], depth: int,
               max_depth: int, min_leaf: int,
               positive_weight: float) -> Node:
    positive_count = sum(samples[index].only32 for index in indices)
    negative_count = len(indices) - positive_count
    weighted_positive = positive_count * positive_weight
    node = Node(weighted_positive / max(weighted_positive + negative_count, 1.0),
                len(indices), positive_count)
    if (depth >= max_depth or len(indices) < min_leaf * 2 or
            positive_count == 0 or negative_count == 0):
        return node

    best: tuple[float, int, int] | None = None
    for feature in range(len(FEATURES)):
        ordered = sorted(indices, key=lambda index: samples[index].values[feature])
        left_positive = 0
        left_negative = 0
        for position in range(len(ordered) - 1):
            label = samples[ordered[position]].only32
            left_positive += label
            left_negative += 1 - label
            left_count = position + 1
            right_count = len(ordered) - left_count
            if left_count < min_leaf or right_count < min_leaf:
                continue
            value = samples[ordered[position]].values[feature]
            next_value = samples[ordered[position + 1]].values[feature]
            if value == next_value:
                continue
            right_positive = positive_count - left_positive
            right_negative = negative_count - left_negative
            score = (impurity(left_positive * positive_weight, left_negative) +
                     impurity(right_positive * positive_weight, right_negative))
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
                           min_leaf, positive_weight)
    node.right = build_tree(samples, right_indices, depth + 1, max_depth,
                            min_leaf, positive_weight)
    return node


def predict_probability(node: Node, sample: Sample) -> int:
    while node.feature >= 0:
        node = node.left if sample.values[node.feature] <= node.threshold else node.right  # type: ignore[assignment]
    return int(node.probability_only32 * 100.0 + 0.5)


def metrics(samples: list[Sample], probabilities: list[int], cutoff: int) -> dict[str, float | int]:
    true_positive = true_negative = false_positive = false_negative = 0
    for sample, probability in zip(samples, probabilities):
        predicted = probability >= cutoff
        if sample.only32 and predicted:
            true_positive += 1
        elif sample.only32:
            false_negative += 1
        elif predicted:
            false_positive += 1
        else:
            true_negative += 1
    selected = true_positive + false_positive
    positives = true_positive + false_negative
    return {
        "samples": len(samples),
        "oracle_only32_pct": 100.0 * positives / max(len(samples), 1),
        "selected_only32_pct": 100.0 * selected / max(len(samples), 1),
        "accuracy_pct": 100.0 * (true_positive + true_negative) / max(len(samples), 1),
        "precision_pct": 100.0 * true_positive / max(selected, 1),
        "recall_pct": 100.0 * true_positive / max(positives, 1),
        "false_gate_pct": 100.0 * false_positive / max(len(samples), 1),
        "tp": true_positive,
        "tn": true_negative,
        "fp": false_positive,
        "fn": false_negative,
    }


def node_to_dict(node: Node) -> dict[str, object]:
    result: dict[str, object] = {
        "samples": node.samples,
        "positives": node.positives,
        "probability_only32": round(node.probability_only32, 8),
        "probability_only32_integer_pct": int(node.probability_only32 * 100.0 + 0.5),
    }
    if node.feature >= 0:
        result.update({
            "feature": FEATURES[node.feature],
            "threshold": node.threshold,
            "left": node_to_dict(node.left),  # type: ignore[arg-type]
            "right": node_to_dict(node.right),  # type: ignore[arg-type]
        })
    return result


def tree_lines(node: Node, names: list[str], indent: str = "") -> list[str]:
    if node.feature < 0:
        probability = int(node.probability_only32 * 100.0 + 0.5)
        return [f"{indent}return {probability};  // n={node.samples}, positive={node.positives}"]
    lines = [f"{indent}if ({names[node.feature]} <= {node.threshold})"]
    lines += tree_lines(node.left, names, indent + "    ")  # type: ignore[arg-type]
    lines.append(f"{indent}else")
    lines += tree_lines(node.right, names, indent + "    ")  # type: ignore[arg-type]
    return lines


def write_header(path: Path, tree: Node, metadata: dict[str, object]) -> None:
    lines = [
        "/*****************************************************************************",
        " * Generated by train_inter_only32_gate.py. Do not edit the tree by hand.",
        f" * Samples: {metadata['sample_count']}; depth: {metadata['max_depth']};",
        f" * min leaf: {metadata['min_leaf']}; positive weight: {metadata['positive_weight']}.",
        " ****************************************************************************/",
        "#ifndef X265_INTER_ONLY32_GATE_MODEL_H",
        "#define X265_INTER_ONLY32_GATE_MODEL_H",
        "",
        "namespace X265_NS {",
        "",
        "static inline uint32_t hwInterOnly32ModelProbability(",
        "    int qp, uint32_t imeSadQ8, uint32_t refineL1,",
        "    uint32_t mvdQPelL1, uint32_t mvFullPelL1,",
        "    uint32_t pmeActivity, uint32_t imeBoundary)",
        "{",
    ]
    lines += tree_lines(tree, CPP_NAMES, "    ")
    lines += [
        "}",
        "",
        "}",
        "",
        "#endif // X265_INTER_ONLY32_GATE_MODEL_H",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_portable_c_header(path: Path, tree: Node, metadata: dict[str, object]) -> None:
    lines = [
        "/*****************************************************************************",
        " * Generated by train_inter_only32_gate.py. Do not edit the tree by hand.",
        f" * Samples: {metadata['sample_count']}; depth: {metadata['max_depth']};",
        f" * min leaf: {metadata['min_leaf']}; positive weight: {metadata['positive_weight']}.",
        " ****************************************************************************/",
        "#ifndef HW_HME_INTER_ONLY32_GATE_MODEL_H",
        "#define HW_HME_INTER_ONLY32_GATE_MODEL_H",
        "",
        "#include <stdint.h>",
        "",
        "static uint32_t hw_hme_inter_only32_model_probability(",
        "    int qp, uint32_t ime_sad_q8, uint32_t refine_l1,",
        "    uint32_t mvd_qpel_l1, uint32_t mv_fullpel_l1,",
        "    uint32_t pme_activity, uint32_t ime_boundary)",
        "{",
    ]
    lines += tree_lines(tree,
                        ["qp", "ime_sad_q8", "refine_l1", "mvd_qpel_l1",
                         "mv_fullpel_l1", "pme_activity", "ime_boundary"],
                        "    ")
    lines += [
        "}",
        "",
        "#endif /* HW_HME_INTER_ONLY32_GATE_MODEL_H */",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_cutoffs(text: str) -> list[int]:
    cutoffs = sorted({int(value.strip()) for value in text.split(",") if value.strip()})
    if not cutoffs or cutoffs[0] < 1 or cutoffs[-1] > 99:
        raise ValueError("cutoffs must be integers in [1, 99]")
    return cutoffs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, help="mode-4 collection runs.csv")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--min-leaf", type=int, default=512)
    parser.add_argument("--positive-weight", type=float, default=1.0)
    parser.add_argument("--cutoffs", default="50,60,70,80,85,90,92,94,95,96,97,98,99")
    parser.add_argument("--recommended-cutoff", type=int, default=96)
    parser.add_argument("--cpp-header", type=Path,
                        help="optional path for the generated x265 C++ model header")
    parser.add_argument("--portable-header", type=Path,
                        help="optional path for a generated ISO C99 model header")
    args = parser.parse_args()
    output = args.output or args.runs.resolve().parent
    output.mkdir(parents=True, exist_ok=True)
    cutoffs = parse_cutoffs(args.cutoffs)
    if args.recommended_cutoff not in range(1, 100):
        parser.error("recommended cutoff must be in [1, 99]")

    samples = load_samples(args.runs.resolve())
    sequences = sorted({sample.sequence for sample in samples})
    probabilities = [0] * len(samples)
    for sequence in sequences:
        train_indices = [index for index, sample in enumerate(samples)
                         if sample.sequence != sequence]
        test_indices = [index for index, sample in enumerate(samples)
                        if sample.sequence == sequence]
        tree = build_tree(samples, train_indices, 0, args.max_depth,
                          args.min_leaf, args.positive_weight)
        for index in test_indices:
            probabilities[index] = predict_probability(tree, samples[index])

    threshold_rows: list[dict[str, object]] = []
    for cutoff in cutoffs:
        row: dict[str, object] = {"cutoff": cutoff}
        row.update(metrics(samples, probabilities, cutoff))
        threshold_rows.append(row)
    write_csv(output / "inter_only32_thresholds_cv.csv", threshold_rows)

    sequence_rows: list[dict[str, object]] = []
    for sequence in sequences:
        selected = [(sample, probability) for sample, probability in zip(samples, probabilities)
                    if sample.sequence == sequence]
        row: dict[str, object] = {"sequence": sequence,
                                 "cutoff": args.recommended_cutoff}
        row.update(metrics([item[0] for item in selected],
                           [item[1] for item in selected],
                           args.recommended_cutoff))
        sequence_rows.append(row)
    overall: dict[str, object] = {"sequence": "All leave-one-sequence-out",
                                  "cutoff": args.recommended_cutoff}
    overall.update(metrics(samples, probabilities, args.recommended_cutoff))
    sequence_rows.append(overall)
    write_csv(output / "inter_only32_sequence_cv.csv", sequence_rows)

    final_tree = build_tree(samples, list(range(len(samples))), 0,
                            args.max_depth, args.min_leaf,
                            args.positive_weight)
    metadata: dict[str, object] = {
        "features": FEATURES,
        "label": "leaf32 > 0 in complete 32/16/8 RDO",
        "sample_count": len(samples),
        "sequence_count": len(sequences),
        "max_depth": args.max_depth,
        "min_leaf": args.min_leaf,
        "positive_weight": args.positive_weight,
        "recommended_cutoff": args.recommended_cutoff,
        "cross_validation": "leave-one-sequence-out",
        "recommended_cutoff_cv": overall,
        "tree": node_to_dict(final_tree),
    }
    (output / "inter_only32_tree.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "inter_only32_tree.txt").write_text(
        "\n".join(tree_lines(final_tree, FEATURES)) + "\n", encoding="utf-8")
    write_header(output / "inter_only32_gate_model.h", final_tree, metadata)
    if args.cpp_header:
        write_header(args.cpp_header.resolve(), final_tree, metadata)
    write_portable_c_header(output / "inter_only32_gate_model_c.h", final_tree, metadata)
    if args.portable_header:
        write_portable_c_header(args.portable_header.resolve(), final_tree, metadata)
    print(json.dumps(overall, ensure_ascii=False, indent=2))
    print(f"Wrote model and validation files to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
