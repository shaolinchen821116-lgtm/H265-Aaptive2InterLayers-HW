#!/usr/bin/env python3
"""Compute ONLY32 BD-rate and actual selection probabilities."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
EXP = HERE.parent
sys.path.insert(0, str(EXP))
from analyze_results import bd_rate  # noqa: E402


RESULTS = EXP / "results"
OUT = HERE / "report_data"
QPS = [10, 16, 20, 24, 28, 32, 36, 40, 44, 48]
SEGMENTS = {
    "low": [10, 16, 20, 24],
    "mid": [24, 28, 32, 36],
    "high": [36, 40, 44, 48],
    "all10": QPS,
}
SEQUENCES = {
    "BasketballDrive": "ClassB", "BQTerrace": "ClassB", "Cactus": "ClassB",
    "Kimono1": "ClassB", "ParkScene": "ClassB",
    "PeopleOnStreet": "ClassA", "Traffic": "ClassA",
    "BasketballDrill": "ClassC", "BQMall": "ClassC", "PartyScene": "ClassC",
    "RaceHorsesC": "ClassC", "FourPeople": "ClassE", "Johnny": "ClassE",
    "KristenAndSara": "ClassE", "vidyo1": "ClassE", "vidyo3": "ClassE",
    "vidyo4": "ClassE",
}
DIMS = {
    "ClassA": (2560, 1600), "ClassB": (1920, 1080),
    "ClassC": (832, 480), "ClassE": (1280, 720),
}


def result(sequence: str, qp: int, mode: str) -> dict:
    path = RESULTS / sequence / f"QP{qp:02d}" / mode / "result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    global RESULTS, OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    RESULTS = args.results.resolve()
    OUT = args.output.resolve()
    modes = sorted({p.parent.name for p in RESULTS.glob("*/QP*/gate32*/result.json")})
    modes += sorted({p.parent.name for p in RESULTS.glob("*/QP*/cascade32*/result.json")})
    bd_rows, selection_rows = [], []
    for sequence, seq_class in SEQUENCES.items():
        for mode in modes:
            if not all((RESULTS / sequence / f"QP{qp:02d}" / mode / "result.json").exists() for qp in QPS):
                continue
            selected = total = oracle32 = true32 = false32 = 0
            for qp in QPS:
                stats = RESULTS / sequence / f"QP{qp:02d}" / mode / "ctu_stats.csv"
                anchor_stats = RESULTS / sequence / f"QP{qp:02d}" / "all" / "ctu_stats.csv"
                with anchor_stats.open(newline="", encoding="utf-8") as anchor_handle:
                    anchor_by_addr = {int(row["ctu_addr"]): row for row in csv.DictReader(anchor_handle)}
                with stats.open(newline="", encoding="utf-8") as handle:
                    for row in csv.DictReader(handle):
                        width, height = DIMS[seq_class]
                        if int(row["x"]) + 32 > width or int(row["y"]) + 32 > height:
                            continue
                        total += 1
                        is32 = row["selected"] == "only32"
                        anchor_row = anchor_by_addr[int(row["ctu_addr"])]
                        oracle = int(anchor_row["leaf32"]) > 0
                        selected += is32
                        oracle32 += oracle
                        true32 += is32 and oracle
                        false32 += is32 and not oracle
            selection_rows.append({
                "class": seq_class, "sequence": sequence, "mode": mode,
                "ctus_qp_points": total, "selected_only32_pct": 100 * selected / total,
                "anchor_leaf32_pct": 100 * oracle32 / total,
                "selected_precision_pct": 100 * true32 / max(1, selected),
                "false_selected_pct_all": 100 * false32 / total,
            })
            references = [("anchor_all", "all")]
            if mode.startswith("cascade32"):
                references.append(("adaptive40", "adaptive40"))
            for reference_name, reference_mode in references:
                for segment, qps in SEGMENTS.items():
                    anchor = [(result(sequence, q, reference_mode)["psnr_y"], result(sequence, q, reference_mode)["kbps"]) for q in qps]
                    test = [(result(sequence, q, mode)["psnr_y"], result(sequence, q, mode)["kbps"]) for q in qps]
                    bd_rows.append({"class": seq_class, "sequence": sequence, "mode": mode,
                                    "reference": reference_name, "segment": segment,
                                    "bd_rate_y_pct": bd_rate(anchor, test)})

    for rows, value_key in ((bd_rows, "bd_rate_y_pct"), (selection_rows, "selected_only32_pct")):
        groups = defaultdict(list)
        for row in rows:
            suffix = (row["mode"], row.get("reference", ""), row.get("segment", ""))
            groups[(row["class"],) + suffix].append(row[value_key])
            groups[("ALL",) + suffix].append(row[value_key])
        for key, values in sorted(groups.items()):
            if rows is bd_rows:
                rows.append({"class": key[0], "sequence": f"{key[0]}_mean", "mode": key[1],
                             "reference": key[2], "segment": key[3], value_key: sum(values) / len(values)})
            else:
                members = [r for r in selection_rows if r["class"] == key[0] and r["mode"] == key[1]] if key[0] != "ALL" else [r for r in selection_rows if r["mode"] == key[1]]
                weight = sum(r["ctus_qp_points"] for r in members)
                rows.append({"class": key[0], "sequence": f"{key[0]}_weighted", "mode": key[1],
                             "ctus_qp_points": weight,
                             "selected_only32_pct": sum(r["selected_only32_pct"] * r["ctus_qp_points"] for r in members) / weight,
                             "anchor_leaf32_pct": sum(r["anchor_leaf32_pct"] * r["ctus_qp_points"] for r in members) / weight,
                             "selected_precision_pct": sum(r["selected_precision_pct"] * r["ctus_qp_points"] for r in members) / weight,
                             "false_selected_pct_all": sum(r["false_selected_pct_all"] * r["ctus_qp_points"] for r in members) / weight})

    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "only32_bd_rate.csv", bd_rows)
    write_csv(OUT / "only32_selection.csv", selection_rows)
    (OUT / "only32_results.json").write_text(json.dumps(
        {"bd_rate": bd_rows, "selection": selection_rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    for row in bd_rows:
        if row["sequence"].endswith("_mean") and row["segment"] == "all10":
            print(f"{row['sequence']:14s} {row['mode']:12s} vs {row['reference']:10s} BD-rate={row['bd_rate_y_pct']:+.4f}%")
    for row in selection_rows:
        if row["sequence"].endswith("_weighted"):
            print(f"{row['sequence']:14s} {row['mode']:12s} selected={row['selected_only32_pct']:.3f}% precision={row['selected_precision_pct']:.2f}%")


if __name__ == "__main__":
    main()
