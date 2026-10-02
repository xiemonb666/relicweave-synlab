"""Which semantic generation does each committed asset belong to? (S5)

The marker lives in the committed asset metadata, so the question is answerable with SQL over
``<store>/metadata.sqlite`` -- and this driver is that query, in a form a reader can run.

What it reports per store
-------------------------
``by_role``
    asset count per role, split into ``current`` / ``legacy`` / ``missing`` for
    ``mask_semantics``.  ``missing`` means the key does not exist at all, which is how the
    pre-marker generation is recognised (``docs/a12/data_semantics_versions.md`` §3) -- it is
    never silently counted as current.
``gate``
    the ``semantics.mask_semantics`` verdict the data-quality gate computes, so the report and the
    gate cannot disagree.
``visible_labels``
    the role S5 was about: it is derived from the delivered mask channels, and it used to be
    committed with no marker at all.

    python tools/a12_mask_semantics_census.py [--store <store> ...] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.qc.data_quality import (  # noqa: E402
    CURRENT_GENERATION,
    DATA_SEMANTICS_ROLES,
    LEGACY_GENERATION,
    MARKER_FREE_ROLES,
    check_store,
)

EXIT_OK = 0
EXIT_USAGE = 2

MARKER = "mask_semantics"

DEFAULT_STORES = (
    "data/a12_trainable/store",
    "data/a12_campaign/store",
    "data/a12_exports/closed_loop/store",
    "data/a12_demo/store",
)


def _marker_in(meta: dict[str, Any]) -> str | None:
    """``mask_semantics`` anywhere in the metadata object (top level or nested)."""
    stack = [meta]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key == MARKER and value is not None:
                    return str(value)
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(item for item in node if isinstance(item, (dict, list)))
    return None


def census(store: str | Path) -> dict[str, Any]:
    """Per-role generation census of one store, plus the gate's own verdict."""
    root = Path(store)
    db = root / "metadata.sqlite"
    if not db.is_file():
        return {"store": str(root), "available": False,
                "reason": f"no {db.name} (not an asset store)"}
    current = str(CURRENT_GENERATION[MARKER])
    legacy = str(LEGACY_GENERATION[MARKER])
    by_role: dict[str, Counter] = defaultdict(Counter)
    values: Counter = Counter()
    connection = sqlite3.connect(str(db))
    connection.row_factory = sqlite3.Row
    try:
        rows = list(connection.execute("select asset_id, role, meta_json from assets"))
    finally:
        connection.close()
    for row in rows:
        try:
            meta = json.loads(row["meta_json"])
        except (TypeError, ValueError):
            meta = {}
        value = _marker_in(meta) if isinstance(meta, dict) else None
        values[value or "<missing>"] += 1
        bucket = ("current" if value == current else
                  "legacy" if value == legacy else
                  "missing" if value is None else "other")
        by_role[str(row["role"])][bucket] += 1
        by_role[str(row["role"])]["total"] += 1
    gate = None
    for check in (check_store(root).get("checks") or []):
        if str(check.get("id")) == f"semantics.{MARKER}":
            gate = {"status": check.get("status"), "hits": check.get("hits"),
                    "denominator": check.get("denominator"), "detail": check.get("detail")}
    visible = by_role.get("visible_labels", Counter())
    return {
        "store": str(root),
        "available": True,
        "assets": len(rows),
        "current_value": current,
        "legacy_value": legacy,
        "value_histogram": {str(key): int(count) for key, count in values.items()},
        "by_role": {role: {key: int(count) for key, count in counter.items()}
                    for role, counter in sorted(by_role.items())},
        "marked_roles": sorted(DATA_SEMANTICS_ROLES),
        "marker_free_roles": sorted(MARKER_FREE_ROLES),
        "visible_labels": {key: int(count) for key, count in visible.items()},
        "visible_labels_carries_marker": bool(visible.get("current") or visible.get("legacy")),
        "gate": gate,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", action="append", default=None,
                        help="asset store root (repeatable); defaults to the shipped stores")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    stores = args.store if args.store else [
        path for path in DEFAULT_STORES if (REPO_ROOT / path).is_dir()]
    if not stores:
        print("no store to census", file=sys.stderr)
        return EXIT_USAGE
    reports = [census(store) for store in stores]
    for report in reports:
        print(f"store: {report['store']}")
        if not report.get("available"):
            print(f"  UNAVAILABLE: {report['reason']}")
            continue
        print(f"  assets {report['assets']}  values {report['value_histogram']}")
        print(f"  current  = {report['current_value']}")
        print(f"  legacy   = {report['legacy_value']}")
        roles = report["by_role"]
        for role in report["marked_roles"]:
            entry = roles.get(role)
            if entry:
                print(f"    {role:18s} total={entry.get('total', 0):4d} "
                      f"current={entry.get('current', 0):4d} "
                      f"legacy={entry.get('legacy', 0):4d} "
                      f"missing={entry.get('missing', 0):4d}")
        vis = report["visible_labels"]
        print(f"    visible_labels     total={vis.get('total', 0):4d} "
              f"current={vis.get('current', 0):4d} legacy={vis.get('legacy', 0):4d} "
              f"missing={vis.get('missing', 0):4d}  -> "
              f"carries marker: {report['visible_labels_carries_marker']}")
        if report["gate"]:
            print(f"    gate semantics.{MARKER}: {report['gate']['status']} "
                  f"({report['gate']['hits']}/{report['gate']['denominator']})")
    output = {"reports": reports,
              "query": (f"select role, "
                        f"json_extract(meta_json, '$.{MARKER}') as generation, count(*) "
                        f"from assets group by 1, 2 "
                        f"-- '<missing>' = the pre-marker generation, never assumed current")}
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(output, ensure_ascii=False, indent=2,
                                              sort_keys=True), encoding="utf-8")
        print(f"wrote {args.json}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
