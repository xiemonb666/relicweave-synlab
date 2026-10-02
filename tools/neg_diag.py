#!/usr/bin/env python
"""Diagnostic probe: why does the frozen loader route refuse the exported negatives?

Reads one training package with numpy/pandas only and reports, for the **first** pair the
frozen ``pool=`` route refuses:

* every exported row that mentions the query or the candidate (both directions),
* what ``qc.loader_probe.ExportedRelationPool.neighbours(query)`` really returns,
* whether *every* legal negative of that query is inside that return value,
* and the query's own true R2 mates (``pool.mates``).

Nothing is written except the report; the point is to separate the two candidate causes:

(a) the candidate is a *real* R2 mate of the query (a true leak in the negative table), or
(b) ``ExportedRelationPool.neighbours()`` returns the confirmed R1/R0 set while
    ``training.batch`` reads it as the historical-R2 set (a semantic mismatch of the reader).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.qc.loader_probe import ExportedRelationPool  # noqa: E402
from synlab.storage.export import NEGATIVE_KINDS, TrainingPackage  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    package = TrainingPackage(args.package)
    relations = list(package.relations())
    queries = list(package.queries())
    pool = ExportedRelationPool(relations, pool_id="diag")

    ids = [str(r.get("query_id", "")).split("::", 1)[-1] for r in queries]
    ids = [i for i in dict.fromkeys(ids) if i]
    for row in relations:
        for key in ("query", "candidate"):
            value = str(row.get(key, ""))
            if value and value not in ids:
                ids.append(value)

    report: dict = {
        "schema": "synlab.neg_diag.v1",
        "package": str(args.package),
        "relations": len(relations),
        "queries": len(queries),
        "fragment_ids": len(ids),
        "kind_histogram": pool.kind_histogram(),
        "r2_closure": pool.r2_closure(),
    }

    rows_by_pair: dict[tuple[str, str], list[dict]] = {}
    for row in relations:
        a, b = str(row.get("query", "")), str(row.get("candidate", ""))
        key = (a, b) if a <= b else (b, a)
        rows_by_pair.setdefault(key, []).append({
            "query": a, "candidate": b, "kind": row.get("kind"),
            "valid": bool(row.get("valid", False)),
            "loss_mask": bool(row.get("loss_mask", False)),
            "eligible_as_negative": bool(row.get("eligible_as_negative", False)),
            "has_observation": bool(row.get("has_observation", False)),
        })

    # legal negatives exactly as qc.loader_probe._batch_rows splits them
    legal: dict[str, list[str]] = {}
    for row in relations:
        q, c = str(row.get("query", "")), str(row.get("candidate", ""))
        if not q or not c or q == c:
            continue
        if str(row.get("kind")) in NEGATIVE_KINDS and bool(row.get("valid", False)) \
                and bool(row.get("loss_mask", False)):
            legal.setdefault(q, []).append(c)

    flagged = {}
    for q, cands in legal.items():
        nb = pool.neighbours(q)
        flagged[q] = {
            "legal_negatives": len(cands),
            "inside_neighbours": sum(1 for c in cands if c in nb),
            "neighbours_size": len(nb),
            "true_r2_mates": sorted(pool.mates(q)),
        }
    report["legal_negative_rows_per_query"] = {k: len(v) for k, v in sorted(legal.items())}
    report["flagged_by_pool_neighbours"] = flagged
    report["every_legal_negative_is_a_pool_neighbour"] = all(
        entry["legal_negatives"] == entry["inside_neighbours"] for entry in flagged.values())
    report["queries_with_legal_negatives"] = len(flagged)

    # the first refusal the frozen route produces, with its rows
    first = None
    for q in sorted(legal):
        nb = pool.neighbours(q)
        for c in sorted(legal[q]):
            if c in nb:
                first = (q, c)
                break
        if first:
            break
    if first:
        q, c = first
        report["first_refusal"] = {
            "query": q, "candidate": c,
            "candidate_is_pool_neighbour": c in pool.neighbours(q),
            "candidate_is_true_r2_mate_of_query": c in pool.mates(q),
            "query_true_r2_mates": sorted(pool.mates(q)),
            "candidate_true_r2_mates": sorted(pool.mates(c)),
            "rows_mentioning_the_pair": rows_by_pair.get((q, c) if q <= c else (c, q), []),
            "candidate_rows_as_query": rows_by_pair.get((c, q) if c <= q else (q, c), []),
        }
        # candidate's own rows in the table, whatever the direction
        own = [r for r in relations
               if str(r.get("query")) == c or str(r.get("candidate")) == c]
        kinds = pd.Series([str(r.get("kind")) for r in own]).value_counts().to_dict()
        report["first_refusal"]["candidate_row_kinds"] = {str(k): int(v) for k, v in kinds.items()}

    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
