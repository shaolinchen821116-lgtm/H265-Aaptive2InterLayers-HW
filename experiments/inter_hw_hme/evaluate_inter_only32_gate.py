#!/usr/bin/env python3
"""Evaluate an exported P-frame CU32-only tree on independent mode-4 logs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from train_inter_only32_gate import FEATURES, Sample, load_samples, metrics, write_csv


def predict_probability(tree: dict[str, object], sample: Sample) -> int:
    node = tree
    while "feature" in node:
        feature = FEATURES.index(str(node["feature"]))
        threshold = int(node["threshold"])
        branch = "left" if sample.values[feature] <= threshold else "right"
        node = node[branch]  # type: ignore[assignment]
    return int(node["probability_only32_integer_pct"])


def class_map(runs_csv: Path) -> dict[str, str]:
    with runs_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        return {row["sequence"]: row.get("class", "Unknown") or "Unknown"
                for row in csv.DictReader(handle) if row.get("mode") == "hw"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="inter_only32_tree.json")
    parser.add_argument("runs", type=Path, help="independent mode-4 runs.csv")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cutoffs", default="89,90,92,94")
    parser.add_argument("--recommended-cutoff", type=int, default=92)
    args = parser.parse_args()

    model_path = args.model.resolve()
    runs_path = args.runs.resolve()
    output = (args.output.resolve() if args.output else runs_path.parent / "only32_eval")
    output.mkdir(parents=True, exist_ok=True)
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if model.get("features") != FEATURES:
        raise ValueError("model feature order does not match this evaluator")
    samples = load_samples(runs_path)
    probabilities = [predict_probability(model["tree"], sample) for sample in samples]
    cutoffs = sorted({int(value) for value in args.cutoffs.split(",") if value.strip()})
    if not cutoffs or min(cutoffs) < 1 or max(cutoffs) > 99:
        parser.error("cutoffs must be in [1, 99]")
    classes = class_map(runs_path)

    threshold_rows: list[dict[str, object]] = []
    for cutoff in cutoffs:
        row: dict[str, object] = {"cutoff": cutoff}
        row.update(metrics(samples, probabilities, cutoff))
        threshold_rows.append(row)
    write_csv(output / "inter_only32_independent_thresholds.csv", threshold_rows)

    def grouped_rows(key_of) -> list[dict[str, object]]:
        groups: dict[str, list[int]] = defaultdict(list)
        for index, sample in enumerate(samples):
            groups[key_of(sample)].append(index)
        rows: list[dict[str, object]] = []
        for name in sorted(groups):
            indices = groups[name]
            row: dict[str, object] = {"name": name, "cutoff": args.recommended_cutoff}
            row.update(metrics([samples[index] for index in indices],
                               [probabilities[index] for index in indices],
                               args.recommended_cutoff))
            rows.append(row)
        overall: dict[str, object] = {"name": "All independent samples",
                                     "cutoff": args.recommended_cutoff}
        overall.update(metrics(samples, probabilities, args.recommended_cutoff))
        rows.append(overall)
        return rows

    sequence_rows = grouped_rows(lambda sample: sample.sequence)
    class_rows = grouped_rows(lambda sample: classes.get(sample.sequence, "Unknown"))
    write_csv(output / "inter_only32_independent_sequences.csv", sequence_rows)
    write_csv(output / "inter_only32_independent_classes.csv", class_rows)

    summary = {
        "model": str(model_path),
        "runs": str(runs_path),
        "cutoff": args.recommended_cutoff,
        "overall": sequence_rows[-1],
        "class_rows": class_rows[:-1],
    }
    (output / "inter_only32_independent_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
