"""Read-only inventory of an asset store (temporary diagnostic tool)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from synlab.storage.store import AssetStore  # noqa: E402


def main(root: str) -> None:
    store = AssetStore(root)
    rows = store.list_assets(limit=100000)
    by_role: Counter = Counter()
    by_role_qa: Counter = Counter()
    by_split: Counter = Counter()
    by_lineage: Counter = Counter()
    for a in rows:
        by_role[a.role] += 1
        by_role_qa[(a.role, a.qa_status)] += 1
        by_split[(a.split, a.role)] += 1
        by_lineage[a.lineage_id] += 1
    out = {
        "root": str(store.root),
        "assets": len(rows),
        "by_role": dict(by_role),
        "by_role_qa": {f"{k[0]}|{k[1]}": v for k, v in by_role_qa.items()},
        "by_split_role": {f"{k[0]}|{k[1]}": v for k, v in by_split.items()},
        "lineages": len(by_lineage),
        "lineage_sample": {str(k): v for k, v in sorted(
            by_lineage.items(), key=lambda kv: str(kv[0]))[:40]},
        "runs": None,
        "releases": None,
    }
    with store.connect() as conn:
        out["runs"] = [dict(r) for r in conn.execute("SELECT run_id, status, profile, scope FROM runs").fetchall()]
        out["releases"] = [dict(r) for r in conn.execute("SELECT release_id, profile, scope FROM releases").fetchall()]
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/a12")
