#!/usr/bin/env python3
"""Collect one-frame full-RDO CTU labels and source-only features from x265.

The x265 research build must print lines beginning with INTRA2STAT.  This
script is path-neutral: all content information comes from a manifest CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


STAT_HEADER_V1 = [
    "mode", "ctu_addr", "x", "y", "qp", "selected", "oracle",
    "leaf32", "leaf16", "leaf8", "sad32", "sad16", "sad8",
    "grad_h", "grad_v", "laplacian", "edge4", "edge8", "edge16",
    "edge32", "qstep_q8", "high_cost_q8", "low_cost_q8", "rd_cost",
]
STAT_HEADER_V2 = STAT_HEADER_V1 + ["only32_score"]


def qp_list(text: str) -> list[int]:
    if ":" in text:
        lo, hi = map(int, text.split(":"))
        return list(range(lo, hi + 1))
    return [int(x) for x in text.split(",")]


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"sequence", "class", "path", "width", "height", "fps", "split"}
    if not rows or not required.issubset(rows[0]):
        raise SystemExit(f"manifest must contain: {', '.join(sorted(required))}")
    for row in rows:
        if row["split"] not in ("train", "validation", "test"):
            raise SystemExit(f"invalid split for {row['sequence']}: {row['split']}")
    return rows


def parse_metrics(stderr: str) -> dict:
    pattern = re.compile(
        r"frame I:\s+1, Avg QP:([0-9.]+)\s+kb/s:\s*([0-9.]+)\s+"
        r"PSNR Mean: Y:([0-9.]+) U:([0-9.]+) V:([0-9.]+)\s+"
        r"SSIM Mean:\s*([0-9.]+)")
    match = pattern.search(stderr)
    if not match:
        raise RuntimeError("cannot parse x265 frame I metrics")
    return dict(actual_qp=float(match[1]), kbps=float(match[2]),
                psnr_y=float(match[3]), psnr_u=float(match[4]),
                psnr_v=float(match[5]), ssim_y=float(match[6]))


def extract_stats(stderr: str, output: Path) -> int:
    rows = []
    for line in stderr.splitlines():
        pos = line.find("INTRA2STAT,")
        if pos >= 0:
            rows.append(line[pos + 11:].split(","))
    if not rows:
        raise RuntimeError("x265 emitted no INTRA2STAT rows")
    header = STAT_HEADER_V2 if len(rows[0]) == len(STAT_HEADER_V2) else STAT_HEADER_V1
    if any(len(row) != len(header) for row in rows):
        raise RuntimeError("inconsistent INTRA2STAT field count")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return len(rows)


def command_for(x265: Path, item: dict[str, str], qp: int, bitstream: Path) -> list[str]:
    return [
        str(x265), "--input", item["path"],
        "--input-res", f"{item['width']}x{item['height']}", "--fps", item["fps"],
        "--frames", "1", "--preset", "medium", "--tune", "zerolatency",
        "--ref", "1", "--keyint", "1", "--min-keyint", "1",
        "--ctu", "32", "--min-cu-size", "8", "--max-tu-size", "32",
        "--tu-intra-depth", "1", "--qp", str(qp), "--ipratio", "1.0",
        "--aq-mode", "0", "--no-cutree", "--no-psy", "--no-tskip",
        "--no-tskip-fast", "--frame-threads", "1", "--no-wpp", "--pools", "1",
        "--psnr", "--ssim", "--log-level", "info", "--output", str(bitstream),
    ]


def run_one(x265: Path, root: Path, item: dict[str, str], qp: int,
            force: bool, dry_run: bool) -> dict:
    run_dir = root / item["sequence"] / f"QP{qp:02d}" / "all"
    result_path = run_dir / "result.json"
    stats_path = run_dir / "ctu_stats.csv"
    if result_path.exists() and stats_path.exists() and not force:
        return json.loads(result_path.read_text(encoding="utf-8"))
    bitstream = run_dir / "frame0.265"
    command = command_for(x265, item, qp, bitstream)
    if dry_run:
        return {"sequence": item["sequence"], "qp": qp,
                "command": subprocess.list2cmdline(command)}
    if not Path(item["path"]).exists():
        raise FileNotFoundError(item["path"])
    run_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["X265_INTRA_LAYER_MODE"] = "all"
    env["X265_INTRA_LAYER_STATS"] = "1"
    started = time.perf_counter()
    process = subprocess.run(command, capture_output=True, text=True, env=env)
    if process.returncode:
        (run_dir / "stderr.log").write_text(process.stderr, encoding="utf-8")
        raise RuntimeError(f"x265 failed: {item['sequence']} QP{qp}")
    count = extract_stats(process.stderr, stats_path)
    result = {"sequence": item["sequence"], "class": item["class"],
              "split": item["split"], "qp": qp, "mode": "all",
              "width": int(item["width"]), "height": int(item["height"]),
              "fps": float(item["fps"]), "source": item["path"],
              "ctu_stats": count, "wall_seconds": time.perf_counter() - started,
              **parse_metrics(process.stderr)}
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--x265", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qps", default="10:51", help="inclusive range 10:51 or comma list")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    manifest, qps = read_manifest(args.manifest), qp_list(args.qps)
    if not args.dry_run and not args.x265.exists():
        raise SystemExit(f"missing x265: {args.x265}")
    tasks = [(args.x265, args.output, item, qp, args.force, args.dry_run)
             for item in manifest for qp in qps]
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_one, *task) for task in tasks]
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            print(json.dumps(row, ensure_ascii=False))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "collection_summary.json").write_text(
        json.dumps(sorted(results, key=lambda r: (r["sequence"], r["qp"])),
                   indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
