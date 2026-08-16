#!/usr/bin/env python3
"""Compute BD-rate and anchor-RDO agreement for the intra two-layer study."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "work"
REPORT = HERE / "report_data_generated"

SEGMENTS = {
    "低QP段(10,16,20,24)": [10, 16, 20, 24],
    "中QP段(24,28,32,36)": [24, 28, 32, 36],
    "高QP段(36,40,44,48)": [36, 40, 44, 48],
    "全部10点": [10, 16, 20, 24, 28, 32, 36, 40, 44, 48],
}


def load_results():
    data = {}
    for path in RESULTS.glob("*/QP*/*/result.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        data[(row["sequence"], int(row["qp"]), row["mode"])] = row
    return data


def bd_rate(anchor, test):
    """Cubic Bjontegaard delta-rate using natural log(rate) versus Y-PSNR."""
    a_quality = [float(p[0]) for p in anchor]
    a_lograte = [math.log(float(p[1])) for p in anchor]
    t_quality = [float(p[0]) for p in test]
    t_lograte = [math.log(float(p[1])) for p in test]
    lo = max(min(a_quality), min(t_quality))
    hi = min(max(a_quality), max(t_quality))
    if hi <= lo:
        return math.nan
    degree = min(3, len(anchor) - 1, len(test) - 1)
    center = (lo + hi) * 0.5
    pa = polynomial_fit([x - center for x in a_quality], a_lograte, degree)
    pt = polynomial_fit([x - center for x in t_quality], t_lograte, degree)
    zlo, zhi = lo - center, hi - center
    delta = ((polynomial_integral(pt, zhi) - polynomial_integral(pt, zlo)) -
             (polynomial_integral(pa, zhi) - polynomial_integral(pa, zlo))) / (hi - lo)
    return (math.exp(delta) - 1.0) * 100.0


def polynomial_fit(x, y, degree):
    """Small least-squares fit using centered normal equations and pivoting."""
    size = degree + 1
    matrix = [[sum(value ** (row + col) for value in x) for col in range(size)]
              for row in range(size)]
    rhs = [sum(target * value ** row for value, target in zip(x, y))
           for row in range(size)]
    for pivot in range(size):
        best = max(range(pivot, size), key=lambda row: abs(matrix[row][pivot]))
        matrix[pivot], matrix[best] = matrix[best], matrix[pivot]
        rhs[pivot], rhs[best] = rhs[best], rhs[pivot]
        scale = matrix[pivot][pivot]
        for col in range(pivot, size):
            matrix[pivot][col] /= scale
        rhs[pivot] /= scale
        for row in range(size):
            if row == pivot:
                continue
            factor = matrix[row][pivot]
            for col in range(pivot, size):
                matrix[row][col] -= factor * matrix[pivot][col]
            rhs[row] -= factor * rhs[pivot]
    return rhs


def polynomial_integral(coefficients, x):
    return sum(coefficient * x ** (power + 1) / (power + 1)
               for power, coefficient in enumerate(coefficients))


def low_probability(row):
    sad16 = int(row["sad16"])
    sad8 = int(row["sad8"])
    sad32 = int(row["sad32"])
    qstep_q8 = int(row["qstep_q8"])
    edge4 = int(row["edge4"])
    edge16 = int(row["edge16"])
    edge32 = int(row["edge32"])
    lap = int(row["laplacian"])
    grad = int(row["grad_h"]) + int(row["grad_v"])
    sad16_q8 = sad16 << 8
    sad8_q8 = sad8 << 8

    if sad16_q8 <= 175 * qstep_q8:
        if edge32 <= 4:
            if sad8_q8 <= 84 * qstep_q8:
                return 1 if sad8_q8 <= 59 * qstep_q8 else 6
            return 5 if edge16 <= 5 else 29
        if sad16_q8 <= 92 * qstep_q8:
            return 7 if sad16_q8 <= 68 * qstep_q8 else 25
        return 63 if edge4 <= 1182 else 43
    if edge32 == 0:
        if (lap << 8) <= 1177 * qstep_q8:
            return 15 if grad * 1000 <= 1175 * sad8 else 37
        return 24 if lap * 1000 <= 1098 * grad else 70
    if edge32 <= 36:
        return 90 if edge4 <= 1086 else 63
    gain32 = max(0, sad32 - sad16)
    return 86 if (gain32 << 8) <= 108 * qstep_q8 else 96


def accuracy_rows(cutoff):
    totals = defaultdict(lambda: defaultdict(int))
    for path in RESULTS.glob("*/QP*/all/ctu_stats.csv"):
        sequence = path.parts[-4]
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if int(row["y"]) >= 1056:
                    continue
                oracle = row["oracle"]
                prediction = "low" if low_probability(row) >= cutoff else "high"
                count = totals[sequence]
                count["all"] += 1
                count[f"oracle_{oracle}"] += 1
                count[f"selected_{prediction}"] += 1
                if oracle == "both" or oracle == prediction:
                    count["correct"] += 1
                if oracle != "both":
                    count["nonneutral"] += 1
                    count["nonneutral_correct"] += oracle == prediction
                if oracle == "low":
                    count["low_correct"] += prediction == "low"
                if oracle == "high":
                    count["high_correct"] += prediction == "high"
    rows = []
    for sequence, c in sorted(totals.items()):
        rows.append({
            "sequence": sequence,
            "cutoff": cutoff,
            "ctus": c["all"],
            "overall_accuracy_pct": 100.0 * c["correct"] / c["all"],
            "nonneutral_accuracy_pct": 100.0 * c["nonneutral_correct"] / c["nonneutral"],
            "low_recall_pct": 100.0 * c["low_correct"] / c["oracle_low"],
            "high_recall_pct": 100.0 * c["high_correct"] / c["oracle_high"],
            "selected_low_pct": 100.0 * c["selected_low"] / c["all"],
            "neutral_pct": 100.0 * c["oracle_both"] / c["all"],
        })
    return rows


def main():
    global RESULTS, REPORT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args()
    RESULTS = args.results.resolve()
    REPORT = args.output.resolve()
    data = load_results()
    sequences = sorted({key[0] for key in data})
    modes = ["high", "low", "adaptive15", "adaptive20", "adaptive25",
             "adaptive30", "adaptive35", "adaptive40", "adaptive50"]
    bd_rows = []
    for sequence in sequences:
        for mode in modes:
            for segment, qps in SEGMENTS.items():
                try:
                    # Use x265's reported coded-picture bitrate.  The on-disk
                    # one-frame stream also contains fixed VPS/SPS/PPS overhead,
                    # which would artificially dilute BD-rate at high QP.
                    anchor = [(data[(sequence, qp, "all")]["psnr_y"],
                               data[(sequence, qp, "all")]["kbps"]) for qp in qps]
                    test = [(data[(sequence, qp, mode)]["psnr_y"],
                             data[(sequence, qp, mode)]["kbps"]) for qp in qps]
                except KeyError:
                    continue
                bd_rows.append({
                    "sequence": sequence,
                    "mode": mode,
                    "segment": segment,
                    "bd_rate_y_pct": bd_rate(anchor, test),
                })

    for mode in modes:
        for segment in SEGMENTS:
            values = [r["bd_rate_y_pct"] for r in bd_rows
                      if r["mode"] == mode and r["segment"] == segment]
            if values:
                bd_rows.append({
                    "sequence": "五序列算术平均",
                    "mode": mode,
                    "segment": segment,
                    "bd_rate_y_pct": sum(values) / len(values),
                })

    accuracy = []
    for cutoff in (15, 20, 25, 30, 35, 40, 50):
        accuracy.extend(accuracy_rows(cutoff))
    for cutoff in (15, 20, 25, 30, 35, 40, 50):
        fold = [r for r in accuracy if r["cutoff"] == cutoff]
        weight = sum(r["ctus"] for r in fold)
        accuracy.append({
            "sequence": "五序列加权总体",
            "cutoff": cutoff,
            "ctus": weight,
            **{key: sum(r[key] * r["ctus"] for r in fold) / weight
               for key in ("overall_accuracy_pct", "nonneutral_accuracy_pct",
                           "low_recall_pct", "high_recall_pct", "selected_low_pct", "neutral_pct")},
        })

    REPORT.mkdir(parents=True, exist_ok=True)
    with (REPORT / "bd_rate.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(bd_rows[0]))
        writer.writeheader()
        writer.writerows(bd_rows)
    with (REPORT / "accuracy.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(accuracy[0]))
        writer.writeheader()
        writer.writerows(accuracy)
    (REPORT / "analysis.json").write_text(
        json.dumps({"bd_rate": bd_rows, "accuracy": accuracy}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Average BD-rate versus anchor (Y-PSNR):")
    for mode in modes:
        values = [r for r in bd_rows if r["sequence"] == "五序列算术平均" and r["mode"] == mode]
        if values:
            print(mode, " | ".join(f"{r['segment']}={r['bd_rate_y_pct']:+.3f}%" for r in values))
    print("\nAggregate classification accuracy:")
    for row in accuracy:
        if row["sequence"] == "五序列加权总体":
            print(f"cutoff={row['cutoff']:2d} overall={row['overall_accuracy_pct']:.2f}% "
                  f"nonneutral={row['nonneutral_accuracy_pct']:.2f}% "
                  f"low-recall={row['low_recall_pct']:.2f}% high-recall={row['high_recall_pct']:.2f}% "
                  f"selected-low={row['selected_low_pct']:.2f}%")


if __name__ == "__main__":
    main()
