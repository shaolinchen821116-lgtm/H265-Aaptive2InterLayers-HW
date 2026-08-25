#!/usr/bin/env python3
"""Analyze the frozen hierarchical IME cost-only gate from mode-7 logs."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def metrics(rows: list[dict[str, object]]) -> dict[str, object]:
    tp = tn = fp = fn = 0
    ratio_sum = 0.0
    for row in rows:
        low = row["oracle"] == "low"
        pred = row["selected"] == "low"
        tp += int(low and pred)
        fn += int(low and not pred)
        fp += int(not low and pred)
        tn += int(not low and not pred)
        ratio_sum += float(row["cost8"]) / max(float(row["cost32"]), 1.0)
    count = max(len(rows), 1)
    low_count = max(tp + fn, 1)
    high_count = max(tn + fp, 1)
    return {
        "samples": len(rows),
        "oracle_low_pct": 100.0 * (tp + fn) / count,
        "selected_low_pct": 100.0 * (tp + fp) / count,
        "accuracy_pct": 100.0 * (tp + tn) / count,
        "balanced_accuracy_pct": 50.0 * (tp / low_count + tn / high_count),
        "low_recall_pct": 100.0 * tp / low_count,
        "false_high_pct_of_low": 100.0 * fn / low_count,
        "false_low_pct_of_high": 100.0 * fp / high_count,
        "mean_cost8_over_cost32": ratio_sum / count,
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.runs.open("r", newline="", encoding="utf-8-sig") as handle:
        runs = list(csv.DictReader(handle))
    rows: list[dict[str, object]] = []
    bad = invalid = records = 0
    for run in runs:
        if run.get("mode") != "hw":
            continue
        log = args.runs.parent / f'{run["sequence"]}_qp{run["qp"]}_hw.log'
        with log.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.startswith("INTERLAYERCOST,"):
                    continue
                records += 1
                p = line.rstrip().split(",")
                if len(p) != 22:
                    bad += 1
                    continue
                if p[4] != "1":
                    invalid += 1
                    continue
                rows.append({"sequence": run["sequence"], "qp": int(p[5]),
                             "lambda_q8": int(p[6]), "cost32": int(p[9]),
                             "cost8": int(p[16]), "selected": p[17],
                             "oracle": p[21]})
    grouped: dict[tuple[str, object], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["sequence"]), row["qp"])].append(row)
        grouped[(str(row["sequence"]), "All")].append(row)
    output: list[dict[str, object]] = []
    for key in sorted(grouped, key=lambda item: (item[0], str(item[1]))):
        result: dict[str, object] = {"sequence": key[0], "qp": key[1]}
        result.update(metrics(grouped[key]))
        output.append(result)
    overall: dict[str, object] = {"sequence": "All", "qp": "All"}
    overall.update(metrics(rows))
    output.append(overall)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    print({"records": records, "valid": len(rows), "invalid": invalid,
           "bad_fields": bad, "overall": overall})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
