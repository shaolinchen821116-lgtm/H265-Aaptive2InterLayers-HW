#!/usr/bin/env python3
"""Analyze the independent Class A/C/E validation runs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from analyze_results import RESULTS, SEGMENTS, bd_rate, low_probability


HERE = Path(__file__).resolve().parent
OUT = HERE / "validation_report_data_generated"
SEQUENCES = {
    "PeopleOnStreet": ("ClassA", 2560, 1600),
    "Traffic": ("ClassA", 2560, 1600),
    "BasketballDrill": ("ClassC", 832, 480),
    "BQMall": ("ClassC", 832, 480),
    "PartyScene": ("ClassC", 832, 480),
    "RaceHorsesC": ("ClassC", 832, 480),
    "FourPeople": ("ClassE", 1280, 720),
    "Johnny": ("ClassE", 1280, 720),
    "KristenAndSara": ("ClassE", 1280, 720),
    "vidyo1": ("ClassE", 1280, 720),
    "vidyo3": ("ClassE", 1280, 720),
    "vidyo4": ("ClassE", 1280, 720),
}


def load_result(sequence, qp, mode):
    path = RESULTS / sequence / f"QP{qp:02d}" / mode / "result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def compute_bd_rows():
    rows = []
    for sequence, (seq_class, _, _) in SEQUENCES.items():
        for mode in ("low", "adaptive40"):
            for segment, qps in SEGMENTS.items():
                anchor = [(load_result(sequence, qp, "all")["psnr_y"],
                           load_result(sequence, qp, "all")["kbps"]) for qp in qps]
                test = [(load_result(sequence, qp, mode)["psnr_y"],
                         load_result(sequence, qp, mode)["kbps"]) for qp in qps]
                rows.append({"class": seq_class, "sequence": sequence, "mode": mode,
                             "segment": segment, "bd_rate_y_pct": bd_rate(anchor, test)})
    for group in ("ClassA", "ClassC", "ClassE", "A/C/E总体"):
        members = set(SEQUENCES) if group == "A/C/E总体" else {
            sequence for sequence, meta in SEQUENCES.items() if meta[0] == group}
        for mode in ("low", "adaptive40"):
            for segment in SEGMENTS:
                values = [row["bd_rate_y_pct"] for row in rows
                          if row["sequence"] in members and row["mode"] == mode and row["segment"] == segment]
                rows.append({"class": group, "sequence": f"{group}算术平均", "mode": mode,
                             "segment": segment, "bd_rate_y_pct": sum(values) / len(values)})
    return rows


def compute_accuracy_rows():
    rows = []
    aggregates = defaultdict(lambda: defaultdict(int))
    for sequence, (seq_class, width, height) in SEQUENCES.items():
        counts = defaultdict(int)
        for qp in range(10, 52):
            path = RESULTS / sequence / f"QP{qp:02d}" / "all" / "ctu_stats.csv"
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    x, y = int(row["x"]), int(row["y"])
                    if x + 32 > width or y + 32 > height:
                        continue
                    oracle = row["oracle"]
                    prediction = "low" if low_probability(row) >= 40 else "high"
                    counts["all"] += 1
                    counts[f"oracle_{oracle}"] += 1
                    counts[f"selected_{prediction}"] += 1
                    counts["correct"] += oracle == "both" or oracle == prediction
                    if oracle != "both":
                        counts["nonneutral"] += 1
                        counts["nonneutral_correct"] += oracle == prediction
                    if oracle == "low":
                        counts["low_correct"] += prediction == "low"
                    if oracle == "high":
                        counts["high_correct"] += prediction == "high"
        rows.append(format_accuracy(seq_class, sequence, counts))
        for group in (seq_class, "A/C/E总体"):
            for key, value in counts.items():
                aggregates[group][key] += value
    for group in ("ClassA", "ClassC", "ClassE", "A/C/E总体"):
        rows.append(format_accuracy(group, f"{group}加权总体", aggregates[group]))
    return rows


def format_accuracy(seq_class, sequence, c):
    return {
        "class": seq_class, "sequence": sequence, "ctus": c["all"],
        "overall_accuracy_pct": 100 * c["correct"] / c["all"],
        "nonneutral_accuracy_pct": 100 * c["nonneutral_correct"] / c["nonneutral"],
        "low_recall_pct": 100 * c["low_correct"] / c["oracle_low"],
        "high_recall_pct": 100 * c["high_correct"] / c["oracle_high"],
        "selected_low_pct": 100 * c["selected_low"] / c["all"],
        "neutral_pct": 100 * c["oracle_both"] / c["all"],
    }


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    global RESULTS, OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    RESULTS = args.results.resolve()
    OUT = args.output.resolve()
    bd_rows = compute_bd_rows()
    accuracy_rows = compute_accuracy_rows()
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "bd_rate_class_ace.csv", bd_rows)
    write_csv(OUT / "accuracy_class_ace.csv", accuracy_rows)
    (OUT / "validation_class_ace.json").write_text(
        json.dumps({"bd_rate": bd_rows, "accuracy": accuracy_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("BD-rate class averages:")
    for row in bd_rows:
        if row["sequence"].endswith("算术平均"):
            print(f"{row['sequence']:16s} {row['mode']:10s} {row['segment']:22s} {row['bd_rate_y_pct']:+.3f}%")
    print("\nAccuracy:")
    for row in accuracy_rows:
        print(f"{row['sequence']:20s} overall={row['overall_accuracy_pct']:.2f}% "
              f"nonneutral={row['nonneutral_accuracy_pct']:.2f}% selected-low={row['selected_low_pct']:.2f}%")


if __name__ == "__main__":
    main()
