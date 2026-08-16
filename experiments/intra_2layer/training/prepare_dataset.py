#!/usr/bin/env python3
"""Validate CTU CSVs and produce canonical train/validation datasets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


REQUIRED = [
    "mode", "ctu_addr", "x", "y", "qp", "oracle", "leaf32", "leaf16", "leaf8",
    "sad32", "sad16", "sad8", "grad_h", "grad_v", "laplacian", "edge4",
    "edge8", "edge16", "edge32", "qstep_q8", "rd_cost",
]
OUTPUT = ["sequence", "class", "split", "width", "height"] + REQUIRED


def manifest(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return {row["sequence"]: row for row in csv.DictReader(handle)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--stats-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    meta = manifest(args.manifest)
    args.output.mkdir(parents=True, exist_ok=True)
    handles, writers, hashes = {}, {}, {}
    for split in ("train", "validation", "test"):
        path = args.output / f"{split}.csv"
        handle = path.open("w", newline="", encoding="utf-8")
        handles[split] = handle
        writers[split] = csv.DictWriter(handle, fieldnames=OUTPUT)
        writers[split].writeheader()

    counts = Counter()
    try:
        for path in sorted(args.stats_root.glob("*/QP*/all/ctu_stats.csv")):
            sequence = path.parts[-4]
            if sequence not in meta:
                continue
            m = meta[sequence]
            width, height = int(m["width"]), int(m["height"])
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                missing = [name for name in REQUIRED if name not in (reader.fieldnames or [])]
                if missing:
                    raise RuntimeError(f"{path}: missing {missing}")
                seen_addr = set()
                for row in reader:
                    key = (int(row["qp"]), int(row["ctu_addr"]))
                    if key in seen_addr:
                        raise RuntimeError(f"{path}: duplicate {key}")
                    seen_addr.add(key)
                    counts["raw"] += 1
                    if int(row["x"]) + 32 > width or int(row["y"]) + 32 > height:
                        counts["partial_excluded"] += 1
                        continue
                    oracle = "high" if int(row["leaf32"]) else ("low" if int(row["leaf8"]) else "both")
                    if oracle != row["oracle"]:
                        raise RuntimeError(f"{path}: inconsistent oracle at {key}")
                    out = {"sequence": sequence, "class": m["class"], "split": m["split"],
                           "width": width, "height": height}
                    out.update({name: row[name] for name in REQUIRED})
                    writers[m["split"]].writerow(out)
                    counts[f"written_{m['split']}"] += 1
                    counts[f"oracle_{oracle}"] += 1
    finally:
        for handle in handles.values():
            handle.close()
    for split in handles:
        path = args.output / f"{split}.csv"
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {"schema_version": 1, "columns": OUTPUT, "counts": dict(counts),
              "sha256": hashes,
              "label_rule": "leaf32>0 => high; else leaf8>0 => low; else both",
              "boundary_rule": "exclude x+32>width or y+32>height"}
    (args.output / "dataset_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
