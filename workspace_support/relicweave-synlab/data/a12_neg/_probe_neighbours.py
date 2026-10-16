"""Probe: why does ``ExportedRelationPool.neighbours`` see only one partner now?"""
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from synlab.qc.loader_probe import ExportedRelationPool  # noqa: E402
from synlab.storage.export import NEGATIVE_KINDS  # noqa: E402

Q = "LIN0101_V16_M12_PAT12_E01-m"
for tag, package in (
        ("base", "data/a12_exports/trainable/next_experiment/training_package"),
        ("negfix", "data/a12_exports/negfix/next_experiment/training_package")):
    frame = pd.read_parquet(Path(package) / "research/relations.parquet")
    rows = frame.to_dict("records")
    pool = ExportedRelationPool(rows, pool_id=tag)
    own = [r for r in rows if str(r["query"]) == Q]
    as_cand = [r for r in rows if str(r["candidate"]) == Q]
    print(f"=== {tag}: rows={len(rows)} rows_as_query={len(own)} rows_as_candidate={len(as_cand)}")
    print("   dtypes valid/loss_mask:", frame["valid"].dtype, frame["loss_mask"].dtype)
    neg = [r for r in own if str(r["kind"]) in NEGATIVE_KINDS and bool(r["valid"])
           and bool(r["loss_mask"])]
    print(f"   legal negatives as query: {len(neg)}")
    print(f"   pool.neighbours(q) size={len(pool.neighbours(Q))} -> "
          f"{sorted(pool.neighbours(Q))[:4]}")
    print(f"   pool.mates(q)          = {sorted(pool.mates(Q))}")
    for r in own[:6]:
        print("    row", r["kind"], r["valid"], r["loss_mask"], "->", str(r["candidate"])[:28],
              "| confirmed:", pool.confirmed(Q, str(r["candidate"])),
              "| reason:", str(r.get("reason"))[:60])
    if neg:
        c = str(neg[0]["candidate"])
        print(f"   first legal negative {c}: confirmed={pool.confirmed(Q, c)} "
              f"relation={pool.relation(Q, c)} in_neighbours={c in pool.neighbours(Q)}")
