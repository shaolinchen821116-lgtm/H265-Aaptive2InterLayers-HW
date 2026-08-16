#!/usr/bin/env python3
"""Run portable-C ONLY32 score/decision verification over all formal runs."""

from __future__ import annotations

import argparse
import csv
import subprocess
from pathlib import Path

from train_only32_gate import CLASS_BY_SEQUENCE


HERE = Path(__file__).resolve().parent
EXP = HERE.parent
QPS = [10, 16, 20, 24, 28, 32, 36, 40, 44, 48]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    with args.manifest.resolve().open(newline="", encoding="utf-8-sig") as handle:
        manifest = {row["sequence"]: row for row in csv.DictReader(handle)}
    total = 0
    for sequence in CLASS_BY_SEQUENCE:
        row = manifest[sequence]
        width, height = int(row["width"]), int(row["height"])
        expected = (width // 32) * (height // 32)
        for qp in QPS:
            stats = args.results.resolve() / sequence / f"QP{qp:02d}" / "gate3294" / "ctu_stats.csv"
            command = [str(args.exe.resolve()), row["path"], str(width), str(height), str(qp),
                       str(stats), str(expected)]
            process = subprocess.run(command, capture_output=True, text=True)
            if process.returncode:
                raise RuntimeError(f"{sequence} QP{qp}: {process.stdout} {process.stderr}")
            total += expected
        print(f"verified {sequence}: {expected * len(QPS)} CTU decisions")
    print(f"TOTAL_ONLY32_VERIFIED_CTUS={total} MISMATCHES=0")


if __name__ == "__main__":
    main()
