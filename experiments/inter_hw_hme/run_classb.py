#!/usr/bin/env python3
"""Run matched Class-B baseline and hardware-HME x265 experiments."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path


HW_STATS_RE = re.compile(
    r"HW-HME summary: PU8=(\d+) PU16=(\d+) PU32=(\d+); "
    r"avg candidates PME=([0-9.]+) IME=([0-9.]+) FME=([0-9.]+); "
    r"PME-zero=([0-9.]+)% IME-changed=([0-9.]+)% FME-changed=([0-9.]+)%"
)
LAYER_STATS_RE = re.compile(
    r"HW-inter-layer summary: high2=(\d+) low2=(\d+) only32=(\d+) "
    r"high=([0-9.]+)% one=([0-9.]+)%; "
    r"leaf32=(\d+) leaf16=(\d+) leaf8=(\d+); avg-IME-SAD-Q8=([0-9.]+) "
    r"avg-refine=([0-9.]+) boundary=([0-9.]+)% avg-only32-prob=([0-9.]+)"
)

FIELDS = [
    "class", "sequence", "mode", "qp", "frames", "fps", "bitrate_kbps",
    "y_psnr", "u_psnr", "v_psnr", "global_psnr", "elapsed_s",
    "encoder_fps", "bitstream_bytes", "pu8", "pu16", "pu32",
    "pme_candidates_avg", "ime_candidates_avg", "fme_candidates_avg",
    "pme_zero_pct", "ime_changed_pct", "fme_changed_pct", "returncode",
    "layer_high2", "layer_low2", "layer_only32", "layer_high_pct",
    "layer_only32_pct", "layer_leaf32",
    "layer_leaf16", "layer_leaf8", "layer_ime_sad_q8",
    "layer_refine_avg", "layer_boundary_pct", "layer_only32_prob_avg",
]


def parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"name", "path", "width", "height", "fps"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"invalid manifest: {path}")
    return rows


def read_x265_csv(path: Path) -> dict[str, str]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RuntimeError(f"x265 CSV has no data row: {path}")
    return {key.strip(): value for key, value in rows[-1].items() if key is not None}


def number(row: dict[str, str], key: str) -> float:
    value = row.get(key, "").strip()
    if not value or value == "-":
        return float("nan")
    return float(value)


def make_command(encoder: Path, seq: dict[str, str], mode: str, qp: int,
                 frames: int, bitstream: Path, csv_path: Path,
                 pme_cost_mode: int, pme_rate_scale: int,
                 pme_texture: str, pme_attractor: int,
                 layer_mode: int, layer_sad: int,
                 layer_slope: int, layer_refine: int,
                 layer_cutoff: int, only32_cutoff: int) -> list[str]:
    command = [
        str(encoder),
        "--input", seq["path"],
        "--input-res", f'{seq["width"]}x{seq["height"]}',
        "--fps", seq["fps"],
        "--frames", str(frames),
        "--preset", "medium",
        "--tune", "zerolatency",
        "--qp", str(qp),
        "--ctu", "32",
        "--min-cu-size", "8",
        "--no-rect",
        "--no-amp",
        "--max-tu-size", "32",
        "--tu-inter-depth", "1",
        "--bframes", "0",
        "--ref", "1",
        "--no-weightp",
        "--no-weightb",
        "--keyint", "250",
        "--min-keyint", "250",
        "--no-scenecut",
        "--frame-threads", "1",
        "--no-early-skip",
        "--rskip", "0",
        "--limit-refs", "0",
        "--psnr",
        "--csv", str(csv_path),
        "--csv-log-level", "0",
    ]
    if mode == "hw":
        command += [
            "--hw-hme",
            "--hw-hme-pme-range", "32,28",
            "--hw-hme-ime-range", "12,12",
            "--hw-hme-pme-sad-shift", "3",
            "--hw-hme-pme-cost-mode", str(pme_cost_mode),
            "--hw-hme-pme-rate-scale", str(pme_rate_scale),
            "--hw-hme-pme-texture", pme_texture,
            "--hw-hme-pme-attractor", str(pme_attractor),
            "--hw-hme-inter-layers", str(layer_mode),
            "--hw-hme-layer-sad", str(layer_sad),
            "--hw-hme-layer-sad-slope", str(layer_slope),
            "--hw-hme-layer-refine", str(layer_refine),
            "--hw-hme-layer-cutoff", str(layer_cutoff),
            "--hw-hme-only32-cutoff", str(only32_cutoff),
            "--hw-hme-stats",
        ]
    command += ["-o", str(bitstream)]
    return command


def run_one(encoder: Path, seq: dict[str, str], mode: str, qp: int,
            frames: int, out_dir: Path, force: bool, pme_cost_mode: int,
            pme_rate_scale: int, pme_texture: str,
            pme_attractor: int, layer_mode: int, layer_sad: int,
            layer_slope: int, layer_refine: int,
            layer_cutoff: int, only32_cutoff: int) -> dict[str, object]:
    stem = f'{seq["name"]}_qp{qp}_{mode}'
    bitstream = out_dir / f"{stem}.hevc"
    csv_path = out_dir / f"{stem}.csv"
    log_path = out_dir / f"{stem}.log"
    json_path = out_dir / f"{stem}.json"
    if json_path.exists() and not force:
        return json.loads(json_path.read_text(encoding="utf-8"))

    for old in (bitstream, csv_path, log_path, json_path):
        if old.exists():
            old.unlink()

    command = make_command(encoder, seq, mode, qp, frames, bitstream, csv_path,
                           pme_cost_mode, pme_rate_scale, pme_texture,
                           pme_attractor, layer_mode, layer_sad,
                           layer_slope, layer_refine, layer_cutoff,
                           only32_cutoff)
    print(f'[{seq["name"]}] mode={mode} qp={qp} frames={frames}', flush=True)
    started = time.perf_counter()
    completed = subprocess.run(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace")
    wall_s = time.perf_counter() - started
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"encoder failed ({completed.returncode}); see {log_path}")

    xrow = read_x265_csv(csv_path)
    stats = HW_STATS_RE.search(completed.stdout)
    layer_stats = LAYER_STATS_RE.search(completed.stdout)
    result: dict[str, object] = {
        "class": seq.get("class", "ClassB"),
        "sequence": seq["name"],
        "mode": mode,
        "qp": qp,
        "frames": frames,
        "fps": float(seq["fps"]),
        "bitrate_kbps": number(xrow, "Bitrate"),
        "y_psnr": number(xrow, "Y PSNR"),
        "u_psnr": number(xrow, "U PSNR"),
        "v_psnr": number(xrow, "V PSNR"),
        "global_psnr": number(xrow, "Global PSNR"),
        "elapsed_s": number(xrow, "Elapsed Time"),
        "encoder_fps": number(xrow, "FPS"),
        "bitstream_bytes": bitstream.stat().st_size,
        "pu8": 0,
        "pu16": 0,
        "pu32": 0,
        "pme_candidates_avg": 0.0,
        "ime_candidates_avg": 0.0,
        "fme_candidates_avg": 0.0,
        "pme_zero_pct": 0.0,
        "ime_changed_pct": 0.0,
        "fme_changed_pct": 0.0,
        "returncode": completed.returncode,
        "layer_high2": 0,
        "layer_low2": 0,
        "layer_only32": 0,
        "layer_high_pct": 0.0,
        "layer_only32_pct": 0.0,
        "layer_leaf32": 0,
        "layer_leaf16": 0,
        "layer_leaf8": 0,
        "layer_ime_sad_q8": 0.0,
        "layer_refine_avg": 0.0,
        "layer_boundary_pct": 0.0,
        "layer_only32_prob_avg": 0.0,
        "wall_s": round(wall_s, 3),
        "command": command,
    }
    if stats:
        values = stats.groups()
        result.update({
            "pu8": int(values[0]),
            "pu16": int(values[1]),
            "pu32": int(values[2]),
            "pme_candidates_avg": float(values[3]),
            "ime_candidates_avg": float(values[4]),
            "fme_candidates_avg": float(values[5]),
            "pme_zero_pct": float(values[6]),
            "ime_changed_pct": float(values[7]),
            "fme_changed_pct": float(values[8]),
        })
    if layer_stats:
        values = layer_stats.groups()
        result.update({
            "layer_high2": int(values[0]),
            "layer_low2": int(values[1]),
            "layer_only32": int(values[2]),
            "layer_high_pct": float(values[3]),
            "layer_only32_pct": float(values[4]),
            "layer_leaf32": int(values[5]),
            "layer_leaf16": int(values[6]),
            "layer_leaf8": int(values[7]),
            "layer_ime_sad_q8": float(values[8]),
            "layer_refine_avg": float(values[9]),
            "layer_boundary_pct": float(values[10]),
            "layer_only32_prob_avg": float(values[11]),
        })
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def write_summary(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path,
                        default=root / "build" / "inter-hw-ninja" / "x265.exe")
    parser.add_argument("--manifest", type=Path, default=here / "sequence_manifest.csv")
    parser.add_argument("--output", type=Path, default=here / "results" / "classb_16f")
    parser.add_argument("--qps", default="22,27,32,37")
    parser.add_argument("--frames", type=int, default=16)
    parser.add_argument("--modes", default="baseline,hw")
    parser.add_argument("--sequences", default="all",
                        help="comma-separated manifest names, or all")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--pme-cost-mode", type=int, choices=(0, 1), default=1)
    parser.add_argument("--pme-rate-scale", type=int, default=256)
    parser.add_argument("--pme-texture", default="8,24")
    parser.add_argument("--pme-attractor", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--layer-mode", type=int, choices=range(10), default=0)
    parser.add_argument("--layer-sad", type=int, default=2048)
    parser.add_argument("--layer-slope", type=int, default=64)
    parser.add_argument("--layer-refine", type=int, default=8)
    parser.add_argument("--layer-cutoff", type=int, default=50)
    parser.add_argument("--only32-cutoff", type=int, default=92)
    args = parser.parse_args()

    encoder = args.encoder.resolve()
    if not encoder.is_file():
        parser.error(f"encoder not found: {encoder}")
    sequences = read_manifest(args.manifest.resolve())
    if args.sequences.lower() != "all":
        selected = {item.strip() for item in args.sequences.split(",") if item.strip()}
        sequences = [seq for seq in sequences if seq["name"] in selected]
        missing = selected - {seq["name"] for seq in sequences}
        if missing:
            parser.error(f"unknown sequence(s): {', '.join(sorted(missing))}")

    modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    if any(mode not in {"baseline", "hw"} for mode in modes):
        parser.error("modes must contain only baseline and/or hw")
    qps = parse_int_list(args.qps)
    if len(qps) < 1:
        parser.error("at least one QP is required")

    args.output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for seq in sequences:
        if not Path(seq["path"]).is_file():
            raise FileNotFoundError(seq["path"])
        for mode in modes:
            for qp in qps:
                rows.append(run_one(encoder, seq, mode, qp, args.frames,
                                    args.output, args.force, args.pme_cost_mode,
                                    args.pme_rate_scale, args.pme_texture,
                                    args.pme_attractor, args.layer_mode,
                                    args.layer_sad, args.layer_slope,
                                    args.layer_refine, args.layer_cutoff,
                                    args.only32_cutoff))
                write_summary(args.output / "runs.csv", rows)
    print(f"Wrote {args.output / 'runs.csv'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
