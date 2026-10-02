"""Census of the roles actually committed per lineage in a store (read-only).

    python tests/a12/integration/role_census.py --store data/a12_campaign/store --lineage LIN0000_V10_M11_PAT15
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.storage.store import AssetStore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--lineage", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    store = AssetStore(args.store)
    per_lineage: dict[str, Counter] = defaultdict(Counter)
    qa: dict[str, Counter] = defaultdict(Counter)
    total = 0
    for asset in store.list_assets(limit=500000):
        total += 1
        lid = getattr(asset, "lineage_id", None) or "<none>"
        per_lineage[lid][asset.role] += 1
        qa[lid][f"{asset.role}:{asset.qa_status}"] += 1

    report = {
        "store": args.store,
        "assets_total": total,
        "lineages": len(per_lineage),
        "global_role_histogram": dict(Counter(
            role for counter in per_lineage.values() for role, n in counter.items()
            for _ in range(n))),
        "per_lineage": {
            lid: {"roles": dict(sorted(counter.items())),
                  "qa": dict(sorted(qa[lid].items()))}
            for lid, counter in sorted(per_lineage.items())
        },
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
