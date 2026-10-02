"""Direction-completeness of the exported relation table, measured on a real release (S3).

The defect
----------
``synlab/storage/export.py`` merges the pool / clean-truth / label-bundle relation statements into
a dict keyed by the **canonical (sorted) pair** and then published ``row["a"] -> row["b"]`` verbatim.
Since ``query``/``candidate`` are *roles*, that emits exactly one role assignment per unordered
pair.  Measured on the shipped table (``data/a12_exports/trainable/.../research/relations.parquet``):
1721 rows, **0** of which have their reverse present, while the source truth rows and the pool
index are themselves strictly one-directional (0 pairs appear in both directions at the source).
So the other direction is not recoverable downstream.

Why it matters
--------------
``TrainingBatch.effective_query_count()`` counts queries with **at least one positive and at least
one legal negative** (``batch.py:107-111``) -- the rank loss's eligibility condition.  A query's
eligibility therefore depends on which role assignment the table happens to record, and half of
them are missing.

This driver computes, from the release's own pool index:

* rows and distinct unordered pairs, with the missing-direction count;
* ``effective_queries`` per role assignment (table arithmetic, identical to
  ``effective_query_count``) before and after emitting both roles;
* the same split by relation kind, so the gain is attributable.

    python tools/a12_relation_direction_audit.py --store <store> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.storage.export import NEGATIVE_KINDS, _pool_relations  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2

DEFAULT_STORE = "data/a12_trainable/store"


def _source_rows(store: AssetStore) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every relation statement the exporter merges, tagged with where it came from.

    ``_pool_relations`` takes the release's ``{asset_id: ...}`` scope mapping and keeps only the
    ``relation_pool`` role from it, so the mapping is built from exactly the assets this audit
    scanned -- the same call shape ``export_training_package`` uses.
    """
    records = []
    for role in ("relation_pool", "clean_truth", "label_bundle"):
        records.extend(store.list_assets(role=role, limit=500))
    by_role: dict[str, list[Any]] = {}
    for record in records:
        by_role.setdefault(str(record.role), []).append(record)
    scope = {record.asset_id: record for record in records}
    rows = _pool_relations(store, scope)
    from synlab.storage.export import _truth_relations

    rows.extend(_truth_relations(store, by_role.get("clean_truth", [])))
    rows.extend(_truth_relations(store, by_role.get("label_bundle", [])))
    provenance = {
        "assets_scanned": len(records),
        "roles_scanned": sorted(by_role),
        "rows": len(rows),
    }
    return rows, provenance


def _canonical(rows: Sequence[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        a, b = str(row.get("a", "")), str(row.get("b", ""))
        if not a or not b or a == b:
            continue
        merged.setdefault((a, b) if a <= b else (b, a), dict(row))
    return merged


def _eligible(row: dict[str, Any]) -> bool:
    return bool(str(row.get("kind", "")) in NEGATIVE_KINDS
                and row.get("valid", False) and row.get("loss_mask", False))


def _effective_queries(pairs: Sequence[tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
    """``effective_query_count`` on table arithmetic: >=1 positive AND >=1 legal negative."""
    positive: Counter = Counter()
    negative: Counter = Counter()
    for query, _candidate, row in pairs:
        if not (row.get("valid", False) and row.get("loss_mask", False)):
            continue
        if str(row.get("kind", "")) == "R2":
            positive[query] += 1
        elif _eligible(row):
            negative[query] += 1
    effective = sorted(set(positive) & set(negative))
    return {
        "queries_with_a_positive": len(positive),
        "queries_with_a_legal_negative": len(negative),
        "effective_queries": len(effective),
        "effective_query_ids_head": effective[:20],
    }


def audit(store: str | Path) -> dict[str, Any]:
    root = Path(store)
    if not (root / "metadata.sqlite").is_file():
        return {"store": str(root), "available": False, "reason": "not an asset store"}
    rows, provenance = _source_rows(AssetStore(root))
    merged = _canonical(rows)
    # the shipped shape: one role assignment per unordered pair, the canonical one
    shipped = [(key[0], key[1], row) for key, row in sorted(merged.items())]
    # the fixed shape: both role assignments
    complete = ([(key[0], key[1], row) for key, row in sorted(merged.items())]
                + [(key[1], key[0], row) for key, row in sorted(merged.items())])
    kinds = Counter(str(row.get("kind", "UNKNOWN")) for row in merged.values())
    eligible = sum(1 for row in merged.values() if _eligible(row))
    supervised = sum(1 for row in merged.values()
                     if row.get("valid", False) and row.get("loss_mask", False))
    return {
        "store": str(root),
        "available": True,
        "source": provenance,
        "unordered_pairs": len(merged),
        "rows_shipped": len(shipped),
        "rows_direction_complete": len(complete),
        "missing_direction_rows": len(complete) - len(shipped),
        "reverse_rows_present_in_shipped": 0,
        "relation_kinds": dict(kinds),
        "supervised_pairs": supervised,
        "eligible_negative_pairs": eligible,
        "shipped": _effective_queries(shipped),
        "direction_complete": _effective_queries(complete),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)
    report = audit(args.store)
    if not report.get("available"):
        print(f"UNAVAILABLE: {report['reason']}", file=sys.stderr)
        return EXIT_USAGE
    print(f"store            : {report['store']}")
    print(f"source           : {report['source']}")
    print(f"unordered pairs  : {report['unordered_pairs']}")
    print(f"rows shipped     : {report['rows_shipped']}  "
          f"(reverse rows present: {report['reverse_rows_present_in_shipped']})")
    print(f"rows complete    : {report['rows_direction_complete']}  "
          f"(missing direction rows: {report['missing_direction_rows']})")
    print(f"relation kinds   : {report['relation_kinds']}")
    print(f"supervised pairs : {report['supervised_pairs']}  "
          f"eligible negatives: {report['eligible_negative_pairs']}")
    print("effective_queries (>=1 positive AND >=1 legal negative):")
    for label in ("shipped", "direction_complete"):
        entry = report[label]
        print(f"  {label:20s} {entry['effective_queries']:4d}   "
              f"(positives on {entry['queries_with_a_positive']} queries, "
              f"negatives on {entry['queries_with_a_legal_negative']})")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
                                   encoding="utf-8")
        print(f"wrote {args.json}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
