#!/usr/bin/env python3
"""Export two_layer_tree.json to an integer-only C include file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def condition(feature: str, threshold: float) -> str:
    scalar = {"edge4": "f->edge4", "edge8": "f->edge8", "edge16": "f->edge16",
              "edge32": "f->edge32", "qp": "qp"}
    if feature in scalar:
        return f"{scalar[feature]} <= {threshold:.12g}"
    expressions = {
        "sad32/qstep": ("f->sad32", "f->qstep_q8", 256),
        "sad16/qstep": ("f->sad16", "f->qstep_q8", 256),
        "sad8/qstep": ("f->sad8", "f->qstep_q8", 256),
        "gain32/qstep": ("gain32", "f->qstep_q8", 256),
        "gain8/qstep": ("gain8", "f->qstep_q8", 256),
        "grad/qstep": ("grad", "f->qstep_q8", 256),
        "lap/qstep": ("f->laplacian", "f->qstep_q8", 256),
        "anisotropy/qstep": ("anisotropy", "f->qstep_q8", 256),
        "gain8/sad16": ("gain8", "f->sad16 + 1", 1),
        "gain32/sad32": ("gain32", "f->sad32 + 1", 1),
        "grad/sad8": ("grad", "f->sad8 + 1", 1),
        "lap/grad": ("f->laplacian", "grad + 1", 1),
        "sad8/qstep2": ("f->sad8", "(uint64_t)f->qstep_q8 * f->qstep_q8", 65536),
        "grad/qstep2": ("grad", "(uint64_t)f->qstep_q8 * f->qstep_q8", 65536),
        "lap/qstep2": ("f->laplacian", "(uint64_t)f->qstep_q8 * f->qstep_q8", 65536),
    }
    numerator, denominator, scale = expressions[feature]
    scaled_threshold = int(round(threshold * 1_000_000))
    return (f"(uint64_t)({numerator}) * {scale}000000ULL <= "
            f"{scaled_threshold}ULL * ({denominator})")


def emit(node: dict, depth: int = 1) -> list[str]:
    indent = "    " * depth
    if node["feature"] < 0:
        score = int(round(node["low_probability"] * 100))
        return [f"{indent}return {score}; /* n={node['samples']}, p_low={node['low_probability']:.4f} */"]
    lines = [f"{indent}if ({condition(node['feature_name'], node['threshold'])})"]
    lines += emit(node["left"], depth + 1)
    lines.append(f"{indent}else")
    lines += emit(node["right"], depth + 1)
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = json.loads(args.model.read_text(encoding="utf-8"))
    body = "\n".join(emit(model["tree"]))
    text = f'''/* Generated deterministically by export_two_layer_c.py. */
static uint32_t generated_low_score(const IntraLayerFeaturesC *f, int qp)
{{
    const uint32_t gain32 = f->sad32 > f->sad16 ? f->sad32 - f->sad16 : 0;
    const uint32_t gain8 = f->sad16 > f->sad8 ? f->sad16 - f->sad8 : 0;
    const uint32_t grad = f->grad_h + f->grad_v;
    const uint32_t anisotropy = f->grad_h > f->grad_v ? f->grad_h - f->grad_v : f->grad_v - f->grad_h;
    (void)qp;
{body}
}}
'''
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
