#!/usr/bin/env python3
"""Compute per-QP deltas and cubic Bjontegaard delta-rate from run_classb.py."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path


def solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve a small dense system with partial-pivot Gaussian elimination."""
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(a[row][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("singular polynomial fit")
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [value / scale for value in a[col]]
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            a[row] = [a[row][j] - factor * a[col][j] for j in range(n + 1)]
    return [a[i][n] for i in range(n)]


def cubic_fit(x: list[float], y: list[float]) -> list[float]:
    if len(x) < 4 or len(x) != len(y):
        raise ValueError("BD-rate requires at least four matched points")
    sums = [sum(value ** power for value in x) for power in range(7)]
    matrix = [[sums[row + col] for col in range(4)] for row in range(4)]
    vector = [sum((xv ** power) * yv for xv, yv in zip(x, y)) for power in range(4)]
    return solve(matrix, vector)


def integral(coeff: list[float], low: float, high: float) -> float:
    return sum(coeff[i] * (high ** (i + 1) - low ** (i + 1)) / (i + 1)
               for i in range(4))


def bd_rate(anchor: list[tuple[float, float]], test: list[tuple[float, float]]) -> float:
    """Return BD-rate %, fitting ln(rate) as a cubic function of Y-PSNR."""
    anchor = sorted(anchor)
    test = sorted(test)
    low = max(anchor[0][0], test[0][0])
    high = min(anchor[-1][0], test[-1][0])
    if high <= low:
        raise ValueError("curves have no overlapping Y-PSNR interval")
    # Normalize the common interval to [-1, 1] before fitting. This represents
    # the same cubic as fitting raw dB values, with much better conditioning.
    middle = (low + high) * 0.5
    scale = (high - low) * 0.5
    normalize = lambda quality: (quality - middle) / scale
    ca = cubic_fit([normalize(p[0]) for p in anchor],
                   [math.log(p[1]) for p in anchor])
    ct = cubic_fit([normalize(p[0]) for p in test],
                   [math.log(p[1]) for p in test])
    mean_delta = (integral(ct, -1.0, 1.0) - integral(ca, -1.0, 1.0)) * 0.5
    return (math.exp(mean_delta) - 1.0) * 100.0


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def f(row: dict[str, str], name: str) -> float:
    return float(row[name])


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="?", type=Path,
                        default=here / "results" / "classb_16f" / "runs.csv")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--anchor-runs", type=Path,
                        help="optional runs.csv supplying reusable baseline rows")
    parser.add_argument("--anchor-mode", default="baseline",
                        help="mode name to import from --anchor-runs as baseline")
    args = parser.parse_args()
    runs_path = args.runs.resolve()
    out_dir = args.output.resolve() if args.output else runs_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = read_rows(runs_path)
    if args.anchor_runs:
        for row in read_rows(args.anchor_runs.resolve()):
            if row.get("mode") == args.anchor_mode:
                imported = dict(row)
                imported["mode"] = "baseline"
                rows.append(imported)

    grouped: dict[str, dict[str, dict[int, dict[str, str]]]] = defaultdict(
        lambda: defaultdict(dict))
    class_by_sequence: dict[str, str] = {}
    for row in rows:
        grouped[row["sequence"]][row["mode"]][int(row["qp"])] = row
        class_by_sequence[row["sequence"]] = row.get("class", "ClassB") or "ClassB"

    point_rows: list[dict[str, object]] = []
    bd_rows: list[dict[str, object]] = []
    search_rows: list[dict[str, object]] = []
    for sequence in sorted(grouped):
        modes = grouped[sequence]
        if "baseline" not in modes or "hw" not in modes:
            continue
        common_qps = sorted(set(modes["baseline"]) & set(modes["hw"]))
        anchor_curve: list[tuple[float, float]] = []
        hw_curve: list[tuple[float, float]] = []
        for qp in common_qps:
            anchor = modes["baseline"][qp]
            hw = modes["hw"][qp]
            arate, hrate = f(anchor, "bitrate_kbps"), f(hw, "bitrate_kbps")
            ay, hy = f(anchor, "y_psnr"), f(hw, "y_psnr")
            anchor_curve.append((ay, arate))
            hw_curve.append((hy, hrate))
            point_rows.append({
                "class": class_by_sequence[sequence],
                "sequence": sequence,
                "qp": qp,
                "anchor_kbps": arate,
                "hw_kbps": hrate,
                "rate_delta_pct": (hrate / arate - 1.0) * 100.0,
                "anchor_y_psnr": ay,
                "hw_y_psnr": hy,
                "y_psnr_delta_db": hy - ay,
                "anchor_fps": f(anchor, "encoder_fps"),
                "hw_fps": f(hw, "encoder_fps"),
                "speed_ratio": f(hw, "encoder_fps") / f(anchor, "encoder_fps"),
            })
        if len(common_qps) >= 4:
            bd_rows.append({
                "class": class_by_sequence[sequence],
                "sequence": sequence,
                "bd_rate_y_psnr_pct": bd_rate(anchor_curve, hw_curve),
                "points": len(common_qps),
                "qp_set": "/".join(str(qp) for qp in common_qps),
            })
        hw_rows = [modes["hw"][qp] for qp in common_qps]
        if hw_rows:
            pu8 = sum(int(float(row["pu8"])) for row in hw_rows)
            pu16 = sum(int(float(row["pu16"])) for row in hw_rows)
            pu32 = sum(int(float(row["pu32"])) for row in hw_rows)
            total_pu = pu8 + pu16 + pu32
            search_rows.append({
                "class": class_by_sequence[sequence],
                "sequence": sequence,
                "pu8_pct": 100.0 * pu8 / total_pu,
                "pu16_pct": 100.0 * pu16 / total_pu,
                "pu32_pct": 100.0 * pu32 / total_pu,
                "pme_candidates_avg": sum(f(row, "pme_candidates_avg") for row in hw_rows) / len(hw_rows),
                "ime_candidates_avg": sum(f(row, "ime_candidates_avg") for row in hw_rows) / len(hw_rows),
                "fme_candidates_avg": sum(f(row, "fme_candidates_avg") for row in hw_rows) / len(hw_rows),
                "pme_zero_pct": sum(f(row, "pme_zero_pct") for row in hw_rows) / len(hw_rows),
                "ime_changed_pct": sum(f(row, "ime_changed_pct") for row in hw_rows) / len(hw_rows),
                "fme_changed_pct": sum(f(row, "fme_changed_pct") for row in hw_rows) / len(hw_rows),
            })

    if bd_rows:
        class_names = sorted({row["class"] for row in bd_rows})
        mean_label = (f"{class_names[0]} arithmetic mean" if len(class_names) == 1
                      else "All-sequence arithmetic mean")
        bd_rows.append({
            "class": "All",
            "sequence": mean_label,
            "bd_rate_y_psnr_pct": sum(float(row["bd_rate_y_psnr_pct"]) for row in bd_rows) / len(bd_rows),
            "points": "-",
            "qp_set": "-",
        })

    def write_csv(path: Path, data: list[dict[str, object]]) -> None:
        if not data:
            return
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)

    write_csv(out_dir / "per_qp_comparison.csv", point_rows)
    write_csv(out_dir / "bd_rate_summary.csv", bd_rows)
    write_csv(out_dir / "hw_search_summary.csv", search_rows)

    class_rows: list[dict[str, object]] = []
    by_class: dict[str, list[float]] = defaultdict(list)
    for row in bd_rows:
        if row.get("class") != "All":
            by_class[str(row["class"])].append(float(row["bd_rate_y_psnr_pct"]))
    for class_name in sorted(by_class):
        values = by_class[class_name]
        class_rows.append({
            "class": class_name,
            "sequence_count": len(values),
            "bd_rate_y_psnr_mean_pct": sum(values) / len(values),
            "worst_sequence_bd_rate_pct": max(values),
        })
    if class_rows:
        all_values = [value for values in by_class.values() for value in values]
        class_rows.append({
            "class": "All classes",
            "sequence_count": len(all_values),
            "bd_rate_y_psnr_mean_pct": sum(all_values) / len(all_values),
            "worst_sequence_bd_rate_pct": max(all_values),
        })
    write_csv(out_dir / "class_bd_rate_summary.csv", class_rows)

    lines = [
        "# Inter HW-HME comparison",
        "",
        "BD-rate uses a cubic fit of ln(bitrate) against luma PSNR over the common quality interval.",
        "",
        "| Sequence | BD-rate (Y-PSNR) | Points | QPs |",
        "|---|---:|---:|---|",
    ]
    for row in bd_rows:
        lines.append(f'| {row["sequence"]} | {float(row["bd_rate_y_psnr_pct"]):+.3f}% | {row["points"]} | {row["qp_set"]} |')
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
