#!/usr/bin/env python3
"""Run forced/adaptive P-frame CU-layer variants and summarize RD/speed."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path,
                        default=root / "build" / "inter-hw-ninja" / "x265.exe")
    parser.add_argument("--manifest", type=Path,
                        default=here / "sequence_manifest_abce.csv")
    parser.add_argument("--anchor-runs", type=Path, required=True)
    parser.add_argument("--anchor-mode", default="hw")
    parser.add_argument("--output", type=Path,
                        default=here / "results" / "inter_layer_sweep")
    parser.add_argument("--sequences", default="all")
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--qps", default="22,27,32,37")
    parser.add_argument("--variants", default="1:50,2:50,3:40,3:50,3:60",
                        help="comma-separated layer_mode:probability_cutoff pairs")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    detail: list[dict[str, object]] = []
    summary: list[dict[str, object]] = []
    for item in args.variants.split(","):
        mode, cutoff = (int(value) for value in item.split(":"))
        tag = f"layer_m{mode}_c{cutoff}"
        out_dir = args.output / tag
        command = [
            sys.executable, str(here / "run_classb.py"),
            "--encoder", str(args.encoder.resolve()),
            "--manifest", str(args.manifest.resolve()),
            "--sequences", args.sequences,
            "--frames", str(args.frames), "--qps", args.qps,
            "--modes", "hw", "--output", str(out_dir),
            "--pme-cost-mode", "1", "--pme-rate-scale", "256",
            "--pme-texture", "8,24", "--pme-attractor", "1",
            "--layer-mode", str(mode), "--layer-cutoff", str(cutoff),
        ]
        if args.force:
            command.append("--force")
        subprocess.run(command, check=True)
        subprocess.run([
            sys.executable, str(here / "analyze_results.py"),
            str(out_dir / "runs.csv"),
            "--anchor-runs", str(args.anchor_runs.resolve()),
            "--anchor-mode", args.anchor_mode,
        ], check=True)

        bd_rows = [row for row in read_csv(out_dir / "bd_rate_summary.csv")
                   if row["class"] != "All"]
        point_rows = read_csv(out_dir / "per_qp_comparison.csv")
        run_rows = read_csv(out_dir / "runs.csv")
        for row in bd_rows:
            sequence = row["sequence"]
            seq_runs = [item for item in run_rows if item["sequence"] == sequence]
            seq_points = [item for item in point_rows if item["sequence"] == sequence]
            seq_high = sum(int(float(item.get("layer_high2", 0) or 0)) for item in seq_runs)
            seq_low = sum(int(float(item.get("layer_low2", 0) or 0)) for item in seq_runs)
            detail.append({
                "variant": tag,
                "class": row["class"],
                "sequence": sequence,
                "bd_rate_y_psnr_pct": float(row["bd_rate_y_psnr_pct"]),
                "mean_speed_ratio": sum(float(item["speed_ratio"]) for item in seq_points) / len(seq_points),
                "selected_high_pct": 100.0 * seq_high / max(seq_high + seq_low, 1),
                "selected_low_pct": 100.0 * seq_low / max(seq_high + seq_low, 1),
            })
        bd_values = [float(row["bd_rate_y_psnr_pct"]) for row in bd_rows]
        speed_values = [float(row["speed_ratio"]) for row in point_rows]
        high = sum(int(float(row.get("layer_high2", 0) or 0)) for row in run_rows)
        low = sum(int(float(row.get("layer_low2", 0) or 0)) for row in run_rows)
        worst = max(bd_rows, key=lambda row: float(row["bd_rate_y_psnr_pct"]))
        summary.append({
            "variant": tag,
            "sequence_count": len(bd_values),
            "mean_bd_rate_pct": sum(bd_values) / len(bd_values),
            "worst_sequence": worst["sequence"],
            "worst_bd_rate_pct": float(worst["bd_rate_y_psnr_pct"]),
            "mean_speed_ratio": sum(speed_values) / len(speed_values),
            "selected_high_pct": 100.0 * high / max(high + low, 1),
            "selected_low_pct": 100.0 * low / max(high + low, 1),
        })

    write_csv(args.output / "inter_layer_sweep_detail.csv", detail)
    write_csv(args.output / "inter_layer_sweep_summary.csv", summary)
    print(f"Wrote {args.output / 'inter_layer_sweep_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
