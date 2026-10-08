"""Diagnose the L0 integration failures (role census, QA denominator, PhysicalPack result).

Not part of the export fix: this only measures the L0/SANDBOX chain so the remaining
integration failures can be described from evidence instead of guesswork.  Since the
PhysicalPack gained a ``physical_result`` asset (plan 4.1), the census also dumps that
asset's real measured fields, so the run can be checked without re-reading the store by hand.

Usage:  python data/a12/reports/l0_role_census.py [--config configs/a12/sandbox.yaml]
                                                 [--out data/a12/reports/l0_role_census.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.pipeline import run_generation  # noqa: E402
from synlab.roles import FORBIDDEN_FEATURE_FIELDS, ROLE_FEATURE_BUNDLE, ROLE_PHYSICAL_RESULT  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def _physical_results(store: AssetStore, limit: int = 10) -> list[dict]:
    out = []
    for asset in store.list_assets(role=ROLE_PHYSICAL_RESULT, limit=limit):
        meta = dict(asset.meta or {})
        audit = dict(meta.get("qa") or {})
        out.append({
            "asset_id": asset.asset_id, "qa_status": asset.qa_status,
            "schema": asset.schema, "unit": asset.unit, "frame": asset.frame,
            "ancestry": list(asset.ancestry or []),
            "recipe_id": meta.get("recipe_id"), "axis_id": meta.get("axis_id"),
            "variant": meta.get("variant"), "level": meta.get("level"),
            "revision": meta.get("revision"),
            "lost_volume_mm3": meta.get("lost_volume_mm3"),
            "lost_volume_ratio": meta.get("lost_volume_ratio"),
            "representative_map": meta.get("representative_map"),
            "components": meta.get("components"),
            "source_asset_id": meta.get("source_asset_id"),
            "source_hash": meta.get("source_hash"),
            "source_geometry_hash": meta.get("source_geometry_hash"),
            "measurement": meta.get("measurement"),
            "audit_status": audit.get("status"),
            "audit_failure_codes": audit.get("failure_codes"),
            "payload_arrays": sorted(store.load_arrays(asset.asset_id)),
        })
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(Path("configs") / "a12" / "sandbox.yaml"))
    parser.add_argument("--out", default=str(Path("data") / "a12" / "reports" / "l0_role_census.json"))
    args = parser.parse_args(argv)

    root = Path(tempfile.mkdtemp(prefix="l0_census_")) / "store"
    spec = load_generation_spec(REPO_ROOT / args.config)
    spec.storage.root = str(root)
    report = run_generation(spec, store_root=root, max_mothers=1)
    store = AssetStore(root)

    roles = Counter(asset.role for asset in store.list_assets(limit=100000))
    qa = Counter(asset.qa_status for asset in store.list_assets(limit=100000))
    features = []
    for asset in store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=100):
        leaked = sorted(set(asset.meta or {}) & FORBIDDEN_FEATURE_FIELDS)
        features.append({"asset_id": asset.asset_id, "qa": asset.qa_status,
                         "forbidden_meta": leaked,
                         "feature_fields": sorted((asset.meta or {}).get("feature_fields") or [])})
    non_pass = sorted(f"{a.qa_status} {a.asset_id} ({a.role})"
                      for a in store.list_assets(limit=100000) if a.qa_status != "QA_PASS")

    out = {
        "config": args.config,
        "store": str(root),
        "run_id": report.get("run_id"),
        "accepted": report.get("accepted"),
        "attempted": report.get("attempted"),
        "roles": dict(sorted(roles.items())),
        "qa": dict(sorted(qa.items())),
        "has_physical_result": int(roles.get("physical_result", 0)),
        "has_physical_truth": int(roles.get("physical_truth", 0)),
        "physical_results": _physical_results(store),
        "non_pass_assets": non_pass,
        "features": features,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
