#!/usr/bin/env python3
"""Run reproducible one-frame Class B intra-layer experiments."""

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


HERE = Path(__file__).resolve().parent

SEQUENCES = {
    "BasketballDrive": ("ClassB", "BasketballDrive_1920x1080_50.yuv", 1920, 1080, 50),
    "BQTerrace": ("ClassB", "BQTerrace_1920x1080_60.yuv", 1920, 1080, 60),
    "Cactus": ("ClassB", "Cactus_1920x1080_50.yuv", 1920, 1080, 50),
    "Kimono1": ("ClassB", "Kimono1_1920x1080_24.yuv", 1920, 1080, 24),
    "ParkScene": ("ClassB", "ParkScene_1920x1080_24.yuv", 1920, 1080, 24),
    "PeopleOnStreet": ("ClassA", "PeopleOnStreet_2560x1600_30_crop.yuv", 2560, 1600, 30),
    "Traffic": ("ClassA", "Traffic_2560x1600_30_crop.yuv", 2560, 1600, 30),
    "BasketballDrill": ("ClassC", "BasketballDrill_832x480_50.yuv", 832, 480, 50),
    "BQMall": ("ClassC", "BQMall_832x480_60.yuv", 832, 480, 60),
    "PartyScene": ("ClassC", "PartyScene_832x480_50.yuv", 832, 480, 50),
    "RaceHorsesC": ("ClassC", "RaceHorses_832x480_30.yuv", 832, 480, 30),
    "FourPeople": ("ClassE", "FourPeople_1280x720_60.yuv", 1280, 720, 60),
    "Johnny": ("ClassE", "Johnny_1280x720_60.yuv", 1280, 720, 60),
    "KristenAndSara": ("ClassE", "KristenAndSara_1280x720_60.yuv", 1280, 720, 60),
    "vidyo1": ("ClassE", "vidyo1_1280x720_60.yuv", 1280, 720, 60),
    "vidyo3": ("ClassE", "vidyo3_1280x720_60.yuv", 1280, 720, 60),
    "vidyo4": ("ClassE", "vidyo4_1280x720_60.yuv", 1280, 720, 60),
}

STAT_HEADER = [
    "mode", "ctu_addr", "x", "y", "qp", "selected", "oracle",
    "leaf32", "leaf16", "leaf8", "sad32", "sad16", "sad8",
    "grad_h", "grad_v", "laplacian", "edge4", "edge8", "edge16",
    "edge32", "qstep_q8", "high_cost_q8", "low_cost_q8", "rd_cost", "only32_score",
]


def parse_metrics(stderr: str) -> dict:
    pattern = re.compile(
        r"frame I:\s+1, Avg QP:([0-9.]+)\s+kb/s:\s*([0-9.]+)\s+"
        r"PSNR Mean: Y:([0-9.]+) U:([0-9.]+) V:([0-9.]+)\s+"
        r"SSIM Mean:\s*([0-9.]+)"
    )
    match = pattern.search(stderr)
    if not match:
        raise RuntimeError("Unable to parse x265 frame metrics")
    return {
        "actual_qp": float(match.group(1)),
        "kbps": float(match.group(2)),
        "psnr_y": float(match.group(3)),
        "psnr_u": float(match.group(4)),
        "psnr_v": float(match.group(5)),
        "ssim_y": float(match.group(6)),
    }


def write_stats(stderr: str, path: Path) -> int:
    rows = []
    for line in stderr.splitlines():
        marker = line.find("INTRA2STAT,")
        if marker >= 0:
            values = line[marker + len("INTRA2STAT,"):].split(",")
            if len(values) != len(STAT_HEADER):
                raise RuntimeError(f"Unexpected INTRA2STAT field count: {len(values)}")
            rows.append(values)

    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(STAT_HEADER)
            writer.writerows(rows)
    return len(rows)


def run_one(sequence: str, qp: int, mode: str, stats: bool, force: bool,
            encoder: Path, yuv_root: Path, out_root: Path) -> dict:
    sequence_class, file_name, width, height, fps = SEQUENCES[sequence]
    source = yuv_root / sequence_class / file_name
    run_dir = out_root / sequence / f"QP{qp:02d}" / mode
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "result.json"
    bitstream = run_dir / "frame0.265"
    stats_path = run_dir / "ctu_stats.csv"

    if json_path.exists() and not force:
        return json.loads(json_path.read_text(encoding="utf-8"))

    command = [
        str(encoder),
        "--input", str(source),
        "--input-res", f"{width}x{height}",
        "--fps", str(fps),
        "--frames", "1",
        "--preset", "medium",
        "--tune", "zerolatency",
        "--ref", "1",
        "--keyint", "1",
        "--min-keyint", "1",
        "--ctu", "32",
        "--min-cu-size", "8",
        "--max-tu-size", "32",
        "--tu-intra-depth", "1",
        "--qp", str(qp),
        "--ipratio", "1.0",
        "--aq-mode", "0",
        "--no-cutree",
        "--no-psy",
        "--no-tskip",
        "--no-tskip-fast",
        "--frame-threads", "1",
        "--no-wpp",
        "--pools", "1",
        "--psnr",
        "--ssim",
        "--log-level", "info",
        "--output", str(bitstream),
    ]

    env = os.environ.copy()
    adaptive_match = re.fullmatch(r"adaptive(\d+)?", mode)
    only32_match = re.fullmatch(r"(gate32|cascade32)(\d+)?", mode)
    env["X265_INTRA_LAYER_MODE"] = "adaptive" if adaptive_match else (only32_match.group(1) if only32_match else mode)
    if adaptive_match and adaptive_match.group(1):
        env["X265_INTRA_LAYER_CUTOFF"] = adaptive_match.group(1)
    if only32_match and only32_match.group(2):
        env["X265_INTRA_ONLY32_CUTOFF"] = only32_match.group(2)
    env["X265_INTRA_LAYER_STATS"] = "1" if stats else "0"

    started = time.perf_counter()
    process = subprocess.run(command, capture_output=True, text=True, env=env)
    elapsed = time.perf_counter() - started
    if process.returncode:
        (run_dir / "stderr.log").write_text(process.stderr, encoding="utf-8")
        raise RuntimeError(f"x265 failed for {sequence} QP{qp} {mode}: {process.returncode}")

    metrics = parse_metrics(process.stderr)
    stat_count = write_stats(process.stderr, stats_path) if stats else 0
    result = {
        "sequence": sequence,
        "class": sequence_class,
        "source": str(source),
        "width": width,
        "height": height,
        "fps": fps,
        "qp": qp,
        "mode": mode,
        "bytes": bitstream.stat().st_size,
        "bits_per_frame": bitstream.stat().st_size * 8,
        "wall_seconds": elapsed,
        "ctu_stats": stat_count,
        **metrics,
    }
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def write_summary(results: list[dict], out_root: Path) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    results = sorted(results, key=lambda r: (r["sequence"], r["qp"], r["mode"]))
    (out_root / "summary.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if not results:
        return
    with (out_root / "summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--yuv-root", type=Path, required=True,
                        help="directory containing ClassA/ClassB/ClassC/ClassE")
    parser.add_argument("--output", type=Path, default=HERE / "work")
    parser.add_argument("--sequences", nargs="+", choices=SEQUENCES, default=list(SEQUENCES))
    parser.add_argument("--qps", nargs="+", type=int, default=[32])
    parser.add_argument("--modes", nargs="+", default=["all"],
                        help="all/high/low/adaptive/only32, adaptiveNN, gate32NN, or cascade32NN")
    parser.add_argument("--stats-modes", nargs="*", default=["all"])
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    encoder = args.encoder.resolve()
    yuv_root = args.yuv_root.resolve()
    out_root = args.output.resolve()
    if not encoder.is_file():
        raise SystemExit(f"Missing research encoder: {encoder}")
    if not yuv_root.is_dir():
        raise SystemExit(f"Missing YUV root: {yuv_root}")

    invalid_modes = [m for m in args.modes if m not in ("all", "high", "low", "adaptive")
                     and m not in ("only32", "gate32", "cascade32")
                     and not re.fullmatch(r"adaptive\d+", m)
                     and not re.fullmatch(r"(gate32|cascade32)\d+", m)]
    if invalid_modes:
        raise SystemExit(f"Invalid modes: {', '.join(invalid_modes)}")

    tasks = [
        (sequence, qp, mode, mode in args.stats_modes, args.force,
         encoder, yuv_root, out_root)
        for sequence in args.sequences
        for qp in args.qps
        for mode in args.modes
    ]
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_one, *task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            result = future.result()
            results.append(result)
            print(
                f"done {result['sequence']} QP{result['qp']} {result['mode']} "
                f"{result['bits_per_frame']} bits PSNR-Y {result['psnr_y']:.3f} "
                f"stats={result['ctu_stats']}"
            )
    write_summary(results, out_root)


if __name__ == "__main__":
    main()
