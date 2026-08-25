#!/usr/bin/env python3
"""Evaluate one frozen multiscale CART model on independently collected logs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from train_inter_multiscale_tree import FEATURES, load_samples, metrics


def predict(tree: dict[str, object], values: tuple[int, ...]) -> float:
    node = tree
    while "feature_index" in node:
        index = int(node["feature_index"])
        threshold = int(node["threshold"])
        node = node["left"] if values[index] <= threshold else node["right"]  # type: ignore[assignment]
    return float(node["probability_low"])


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--cutoff", type=int, default=45)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    model = json.loads(args.model.read_text(encoding="utf-8"))
    if model["features"] != FEATURES:
        raise RuntimeError("model feature order does not match the evaluator")
    samples, counters = load_samples(args.runs.resolve())
    probabilities = [predict(model["tree"], sample.values) for sample in samples]
    rows: list[dict[str, object]] = []
    for sequence in sorted({sample.sequence for sample in samples}):
        picked = [i for i, sample in enumerate(samples) if sample.sequence == sequence]
        row: dict[str, object] = {"sequence": sequence, "cutoff": args.cutoff}
        row.update(metrics([samples[i] for i in picked],
                           [probabilities[i] for i in picked],
                           args.cutoff / 100.0))
        rows.append(row)
    overall: dict[str, object] = {"sequence": "All independent sequences",
                                  "cutoff": args.cutoff}
    overall.update(metrics(samples, probabilities, args.cutoff / 100.0))
    rows.append(overall)
    write_csv(args.output, rows)
    print(json.dumps({"counters": counters, "overall": overall},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
