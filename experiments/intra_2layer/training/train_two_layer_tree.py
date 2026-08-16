#!/usr/bin/env python3
"""Train a deterministic, hardware-friendly HIGH(32/16) vs LOW(16/8) CART."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np


@dataclass
class Node:
    samples: int
    low_count: int
    low_probability: float
    feature: int = -1
    threshold: float = 0.0
    left: "Node | None" = None
    right: "Node | None" = None


def load(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    def col(name): return np.asarray([int(row[name]) for row in rows], dtype=np.float64)
    qstep = col("qstep_q8") / 256.0
    sad32, sad16, sad8 = col("sad32"), col("sad16"), col("sad8")
    gain32, gain8 = np.maximum(0, sad32 - sad16), np.maximum(0, sad16 - sad8)
    gh, gv = col("grad_h"), col("grad_v")
    grad, lap, eps = gh + gv, col("laplacian"), 1.0
    names = ["sad32/qstep", "sad16/qstep", "sad8/qstep", "gain32/qstep",
             "gain8/qstep", "grad/qstep", "lap/qstep", "anisotropy/qstep",
             "gain8/sad16", "gain32/sad32", "grad/sad8", "lap/grad",
             "edge4", "edge8", "edge16", "edge32", "qp",
             "sad8/qstep2", "grad/qstep2", "lap/qstep2"]
    x = np.column_stack([sad32/qstep, sad16/qstep, sad8/qstep, gain32/qstep,
                         gain8/qstep, grad/qstep, lap/qstep, abs(gh-gv)/qstep,
                         gain8/(sad16+eps), gain32/(sad32+eps), grad/(sad8+eps),
                         lap/(grad+eps), col("edge4"), col("edge8"), col("edge16"),
                         col("edge32"), col("qp"), sad8/qstep**2, grad/qstep**2,
                         lap/qstep**2])
    oracle = np.asarray([row["oracle"] for row in rows])
    return rows, x, oracle == "low", oracle != "both", names


def build(x, y, idx, depth, max_depth, min_leaf):
    labels = y[idx].astype(np.int64); low = int(labels.sum())
    node = Node(len(idx), low, low / len(idx))
    if depth >= max_depth or len(idx) < 2 * min_leaf or low in (0, len(idx)): return node
    best = None
    for feature in range(x.shape[1]):
        values = x[idx, feature]; order = np.argsort(values, kind="stable")
        sv, sy = values[order], labels[order]
        ln = np.arange(1, len(idx)); rn = len(idx) - ln
        lp = np.cumsum(sy)[:-1]; rp = low - lp
        impurity = lp*(ln-lp)/ln + rp*(rn-rp)/rn
        allowed = (ln >= min_leaf) & (rn >= min_leaf) & (sv[:-1] < sv[1:])
        if not np.any(allowed): continue
        impurity[~allowed] = np.inf; split = int(np.argmin(impurity))
        candidate = (float(impurity[split]), feature, split, order, sv)
        if best is None or candidate[:3] < best[:3]: best = candidate
    if best is None: return node
    _, feature, split, order, sv = best
    node.feature = feature; node.threshold = float((sv[split]+sv[split+1])/2)
    node.left = build(x, y, idx[order[:split+1]], depth+1, max_depth, min_leaf)
    node.right = build(x, y, idx[order[split+1:]], depth+1, max_depth, min_leaf)
    return node


def score(node, x):
    if node.feature < 0: return np.full(len(x), round(node.low_probability*100), dtype=np.int16)
    right=x[:,node.feature]>node.threshold; out=np.empty(len(x),dtype=np.int16)
    out[~right]=score(node.left,x[~right]); out[right]=score(node.right,x[right]); return out


def tree_dict(node, names):
    out=asdict(node); out["feature_name"]=names[node.feature] if node.feature>=0 else None
    if node.left: out["left"]=tree_dict(node.left,names)
    if node.right: out["right"]=tree_dict(node.right,names)
    return out


def evaluate(rows, target, valid, scores, cutoff):
    pred=scores>=cutoff; sequence=np.asarray([r["sequence"] for r in rows])
    result=[]
    for name in ["ALL"]+sorted(set(sequence)):
        mask=valid if name=="ALL" else valid&(sequence==name)
        neutral=(~valid) if name=="ALL" else (~valid)&(sequence==name)
        allmask=np.ones(len(rows),dtype=bool) if name=="ALL" else sequence==name
        result.append({"set":name,"cutoff":cutoff,"nonneutral_rows":int(mask.sum()),
                       "nonneutral_accuracy_pct":100*float(np.mean(pred[mask]==target[mask])),
                       "overall_accuracy_pct":100*float(((pred[mask]==target[mask]).sum()+neutral.sum())/allmask.sum()),
                       "selected_low_pct":100*float(pred[allmask].mean())})
    return result


def main():
    p=argparse.ArgumentParser(); p.add_argument("--train",type=Path,required=True)
    p.add_argument("--validation",type=Path); p.add_argument("--output",type=Path,required=True)
    p.add_argument("--depth",type=int,default=4); p.add_argument("--min-leaf",type=int,default=800)
    p.add_argument("--cutoffs",nargs="+",type=int,default=[30,35,40,45,50]); a=p.parse_args()
    rows,x,y,valid,names=load(a.train); tree=build(x,y,np.flatnonzero(valid),0,a.depth,a.min_leaf)
    a.output.mkdir(parents=True,exist_ok=True)
    model={"task":"LOW(16/8) vs HIGH(32/16)","depth":a.depth,"min_leaf":a.min_leaf,
           "feature_names":names,"tree":tree_dict(tree,names)}
    (a.output/"two_layer_tree.json").write_text(json.dumps(model,indent=2,ensure_ascii=False),encoding="utf-8")
    metrics=[]
    for cutoff in a.cutoffs: metrics += [{"split":"train",**r} for r in evaluate(rows,y,valid,score(tree,x),cutoff)]
    if a.validation and a.validation.exists():
        vr,vx,vy,vvalid,_=load(a.validation)
        for cutoff in a.cutoffs: metrics += [{"split":"validation",**r} for r in evaluate(vr,vy,vvalid,score(tree,vx),cutoff)]
    with (a.output/"classification_metrics.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=list(metrics[0]));w.writeheader();w.writerows(metrics)
    print(json.dumps(model,ensure_ascii=False)[:1000]); print(f"metrics={len(metrics)}")


if __name__=="__main__": main()
