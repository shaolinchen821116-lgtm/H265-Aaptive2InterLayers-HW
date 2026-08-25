#!/usr/bin/env python3
"""Find a QP-dependent multiscale-tree cutoff schedule from completed runs.

This is a zero-encode post-process: for every tested QP it selects one already
encoded cutoff, forms the corresponding four-point RD curves, and ranks all
cutoff schedules by mean/worst BD-rate.  It never selects by sequence, so the
result remains a portable function of QP only.
"""

from __future__ import annotations

import argparse
import csv
import itertools
from pathlib import Path

from analyze_results import bd_rate


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", type=Path, required=True)
    parser.add_argument("--anchor-runs", type=Path, required=True)
    parser.add_argument("--cutoffs", default="30,35,40,45,50")
    parser.add_argument("--qps", default="22,27,32,37")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    cutoffs = [int(x) for x in args.cutoffs.split(",")]
    qps = [int(x) for x in args.qps.split(",")]
    anchor_rows = [r for r in read_csv(args.anchor_runs) if r["mode"] == "hw"]
    anchor = {(r["sequence"], int(r["qp"])): r for r in anchor_rows}
    variants: dict[int, dict[tuple[str, int], dict[str, str]]] = {}
    for cutoff in cutoffs:
        path = args.sweep / f"layer_m8_c{cutoff}_o92" / "runs.csv"
        variants[cutoff] = {
            (r["sequence"], int(r["qp"])): r for r in read_csv(path)
            if r["mode"] == "hw"
        }
    sequences = sorted({key[0] for key in anchor if key[1] in qps} &
                       {key[0] for rows in variants.values() for key in rows
                        if key[1] in qps})

    ranked: list[tuple[float, float, tuple[int, ...], list[float]]] = []
    for schedule in itertools.product(cutoffs, repeat=len(qps)):
        values: list[float] = []
        complete = True
        for sequence in sequences:
            anchor_curve: list[tuple[float, float]] = []
            test_curve: list[tuple[float, float]] = []
            for qp, cutoff in zip(qps, schedule):
                a = anchor.get((sequence, qp))
                t = variants[cutoff].get((sequence, qp))
                if a is None or t is None:
                    complete = False
                    break
                anchor_curve.append((float(a["bitrate_kbps"]), float(a["y_psnr"])))
                test_curve.append((float(t["bitrate_kbps"]), float(t["y_psnr"])))
            if not complete:
                break
            values.append(bd_rate(anchor_curve, test_curve))
        if complete:
            ranked.append((sum(values) / len(values), max(values), schedule, values))

    ranked.sort(key=lambda row: (row[0], row[1]))
    print("rank,mean_bd_rate_pct,worst_bd_rate_pct,schedule," + ",".join(sequences))
    for rank, row in enumerate(ranked[:args.top], 1):
        mean, worst, schedule, values = row
        mapping = ";".join(f"{qp}:{cutoff}" for qp, cutoff in zip(qps, schedule))
        fields = [str(rank), f"{mean:.9f}", f"{worst:.9f}", mapping]
        fields.extend(f"{value:.9f}" for value in values)
        print(",".join(fields))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
