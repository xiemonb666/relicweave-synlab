"""Throw-away reproduction probe for S2 (the 1120 unused mate-present rows).

Reads an exported package, classifies its relation rows with the rule of
``synlab.relations.mate_absent`` and prints what enters a loss today.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.relations.mate_absent import (  # noqa: E402
    CLASS_MATE_PRESENT,
    CLASS_ORDINARY_NEGATIVE,
    CLASS_POSITIVE,
    class_count_table,
    r2_mates,
    row_class,
)
from synlab.storage.export import TrainingPackage  # noqa: E402


def main() -> int:
    pkg = Path(sys.argv[1])
    package = TrainingPackage(pkg)
    relations = [dict(r) for r in package.relations()]
    rows = [{"query": str(r.get("query", "")), "candidate": str(r.get("candidate", "")),
             "kind": str(r.get("kind", "")), "valid": bool(r.get("valid", False)),
             "loss_mask": bool(r.get("loss_mask", False)),
             "area_mm2": float(r.get("area_mm2") or 0.0),
             "reason": str(r.get("reason", "") or ""),
             "eligible_as_negative": bool(r.get("eligible_as_negative", False))}
            for r in relations]
    mates = r2_mates(rows)
    classes = [row_class(r, mates) for r in rows]
    table = class_count_table(rows)
    hist: dict[str, int] = {}
    for k in classes:
        hist[k] = hist.get(k, 0) + 1
    print("package:", pkg)
    print("rows:", len(rows))
    print("kind histogram:", json.dumps(
        {k: sum(1 for r in rows if r["kind"] == k) for k in sorted({r["kind"] for r in rows})}))
    print("class histogram:", json.dumps(hist, indent=2))
    print("eligible_as_negative true:", sum(1 for r in rows if r["eligible_as_negative"]))
    print("loss_mask true:", sum(1 for r in rows if r["loss_mask"]))
    print("fragments:", table["fragments_with_mate"], "with mate;",
          table["fragments_mate_absent"], "mate absent")
    # which mate-present rows have a mate-present QUERY (requirement 4)?
    q_ok = [r for r, k in zip(rows, classes)
            if k == CLASS_MATE_PRESENT and mates.get(r["query"])]
    q_no = [r for r, k in zip(rows, classes)
            if k == CLASS_MATE_PRESENT and not mates.get(r["query"])]
    print("CLASS_MATE_PRESENT with mate-present query:", len(q_ok),
          "| with mate-absent query:", len(q_no))
    print("distinct queries in the qualified set:", len({r["query"] for r in q_ok}))
    print("distinct candidates in the qualified set:", len({r["candidate"] for r in q_ok}))
    per_q: dict[str, int] = {}
    for r in q_ok:
        per_q[r["query"]] = per_q.get(r["query"], 0) + 1
    print("per-query counts:", json.dumps(dict(sorted(per_q.items())), indent=2))
    # queries that are ALSO trainable under the ordinary rule (pos + >=1 legal neg)
    pos_q = {r["query"] for r, k in zip(rows, classes) if k == CLASS_POSITIVE}
    ord_q = {r["query"] for r, k in zip(rows, classes) if k == CLASS_ORDINARY_NEGATIVE}
    print("queries with positive:", len(pos_q), "| with ordinary negative:", len(ord_q))
    print("queries trainable (pos & ord-neg) AND with hard negatives:",
          sorted(pos_q & ord_q & set(per_q)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
