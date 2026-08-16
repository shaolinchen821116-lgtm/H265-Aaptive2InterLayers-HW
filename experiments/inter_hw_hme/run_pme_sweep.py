#!/usr/bin/env python3
"""Sweep hardware-PME cost/weight/attractor settings and reuse saved anchors."""

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
    parser.add_argument("--output", type=Path,
                        default=here / "results" / "pme_sweep")
    parser.add_argument("--sequences", default="BasketballDrive,Kimono1,RaceHorses,BQTerrace")
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--qps", default="22,27,32,37")
    parser.add_argument("--texture", default="8,24")
    parser.add_argument(
        "--variants", default="1:0:1,1:64:1,1:128:1,1:256:1,1:128:2",
        help="comma-separated cost_mode:rate_scale_q8:attractor triples")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    details: list[dict[str, object]] = []
    for item in args.variants.split(","):
        mode, scale, attractor = (int(value) for value in item.split(":"))
        tag = f"m{mode}_s{scale}_a{attractor}"
        out_dir = args.output / tag
        command = [
            sys.executable, str(here / "run_classb.py"),
            "--encoder", str(args.encoder.resolve()),
            "--manifest", str(args.manifest.resolve()),
            "--sequences", args.sequences,
            "--frames", str(args.frames),
            "--qps", args.qps,
            "--modes", "hw",
            "--output", str(out_dir),
            "--pme-cost-mode", str(mode),
            "--pme-rate-scale", str(scale),
            "--pme-texture", args.texture,
            "--pme-attractor", str(attractor),
        ]
        if args.force:
            command.append("--force")
        subprocess.run(command, check=True)
        subprocess.run([
            sys.executable, str(here / "analyze_results.py"),
            str(out_dir / "runs.csv"),
            "--anchor-runs", str(args.anchor_runs.resolve()),
        ], check=True)
        for row in read_csv(out_dir / "bd_rate_summary.csv"):
            if row["class"] == "All":
                continue
            details.append({
                "variant": tag,
                "cost_mode": mode,
                "rate_scale_q8": scale,
                "attractor": attractor,
                "class": row["class"],
                "sequence": row["sequence"],
                "bd_rate_y_psnr_pct": float(row["bd_rate_y_psnr_pct"]),
            })

    write_csv(args.output / "pme_sweep_detail.csv", details)
    summaries: list[dict[str, object]] = []
    for tag in sorted({str(row["variant"]) for row in details}):
        selected = [row for row in details if row["variant"] == tag]
        values = [float(row["bd_rate_y_psnr_pct"]) for row in selected]
        worst = max(selected, key=lambda row: float(row["bd_rate_y_psnr_pct"]))
        summaries.append({
            "variant": tag,
            "sequence_count": len(values),
            "mean_bd_rate_pct": sum(values) / len(values),
            "worst_sequence": worst["sequence"],
            "worst_bd_rate_pct": worst["bd_rate_y_psnr_pct"],
        })
    write_csv(args.output / "pme_sweep_summary.csv", summaries)
    print(f"Wrote {args.output / 'pme_sweep_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
