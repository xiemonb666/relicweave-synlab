"""Scratch analysis: measured facts of the degradation-diversity store (report -> JSON/stdout)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from synlab.degrade.diversity import (  # noqa: E402
    ROLE_DEGRADE_SOURCE,
    ROLE_DEGRADE_VARIANT,
    asset_bytes,
    directory_bytes,
    load_diversity_config,
)
from synlab.storage.store import AssetStore  # noqa: E402

STORE = ROOT / "data" / "a12_degrade" / "store"
store = AssetStore(STORE)
cfg = load_diversity_config()
reports = [json.loads(p.read_text(encoding="utf-8"))
           for p in sorted((STORE / "reports" / "degrade_diversity").glob("*.json"))]
coverage = json.loads((STORE / "reports" / "coverage.json").read_text(encoding="utf-8"))
generation = json.loads(next((STORE / "reports").glob("generation_run_*.json")).read_text(encoding="utf-8"))

variants = store.list_assets(role=ROLE_DEGRADE_VARIANT, limit=10000)
sources = store.list_assets(role=ROLE_DEGRADE_SOURCE, limit=10000)
roles = Counter(a.role for a in store.list_assets(limit=100000))

out: dict = {
    "store": str(STORE),
    "store_bytes": directory_bytes(STORE),
    "roles": dict(sorted(roles.items())),
    "config": {"path": str(cfg.path), "axes": [a.axis_id for a in cfg.axes], "levels": list(cfg.levels)},
    "run": {"run_id": coverage["run_id"], "planned": coverage["planned"],
            "attempted": coverage["attempted"], "accepted": coverage["accepted"],
            "seconds": round(float(coverage["seconds"]), 2),
            "generation_seconds": round(float(generation["seconds"]), 2),
            "degrade_diversity": coverage.get("degrade_diversity")},
    "variant_assets": len(variants),
    "source_assets": len(sources),
    "variant_bytes_total": sum(asset_bytes(store, a) for a in variants),
    "source_bytes_total": sum(asset_bytes(store, a) for a in sources),
    "lineages": [],
}
for report in reports:
    s = report["summary"]
    per_axis = {}
    for axis in report["axes"]:
        per_axis[axis["axis_id"]] = {
            "status": axis["status"], "basis_id": axis["basis_id"],
            "source_asset": axis.get("source_asset_id"),
            "levels": [{"level": l["level"], "status": l["status"],
                        "asset": l.get("asset_id"), "committed": l.get("asset_committed"),
                        "bytes": l.get("bytes"), "seconds": round(float(l.get("seconds") or 0), 3),
                        "identity": l.get("identity"), "realized": l.get("realized"),
                        "source_hash": l.get("source_hash"), "result_hash": l.get("result_hash"),
                        "identity_reference_ok": l.get("identity_reference_ok"),
                        "bytes_unchanged": l.get("bytes_unchanged"),
                        "failure_code": l.get("failure_code"), "na_reason": l.get("na_reason"),
                        "measured": l.get("measured"), "planned": l.get("planned"),
                        "units": l.get("units")}
                       for l in axis["levels"]],
            "seconds": round(float(axis["seconds"]), 3), "bytes": axis["bytes"],
        }
    commit_bytes = sum(l["bytes"] or 0 for axis in report["axes"] for l in axis["levels"])
    out["lineages"].append({
        "lineage_id": report["lineage_id"], "split": report["split"],
        "status": report["status"], "seconds": round(float(report["seconds"]), 2),
        "levels_planned": s["levels_planned"], "levels_ok": s["levels_ok"],
        "levels_identity": s["levels_identity"], "levels_na": s["levels_na"],
        "levels_failed": s["levels_failed"], "variant_assets": s["variant_assets"],
        "identity_reference_ok": s["identity_reference_ok"],
        "identity_bytes_unchanged": s["identity_bytes_unchanged"],
        "basis_shared_per_axis": s["basis_shared_per_axis"],
        "variant_bytes": commit_bytes,
        "sources": report["sources"], "axes": per_axis,
    })

# --- one real 5-level group, per-level realised change --------------------------------------
sample_axes = ["I03", "I01", "I05", "P03", "G05", "X01"]
out["sample_groups"] = {}
for axis_id in sample_axes:
    rows = []
    for lineage in out["lineages"]:
        entry = lineage["axes"].get(axis_id)
        if not entry:
            continue
        for level in entry["levels"]:
            rows.append({"lineage_id": lineage["lineage_id"], "level": level["level"],
                         "status": level["status"], "planned": level["planned"],
                         "measured": level["measured"], "units": level["units"],
                         "realized": level["realized"], "identity": level["identity"],
                         "asset_id": level["asset"], "bytes": level["bytes"],
                         "result_hash": level["result_hash"]})
    out["sample_groups"][axis_id] = rows

REPORT = ROOT / "data" / "a12_reports" / "degrade_diversity_measurements.json"
REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("REPORT", REPORT)
print(json.dumps({k: v for k, v in out.items() if k not in ("sample_groups", "lineages")},
                 ensure_ascii=False, indent=2, default=str))
for lineage in out["lineages"]:
    print("---", lineage["lineage_id"], lineage["status"], "seconds", lineage["seconds"],
          "variant_bytes", lineage["variant_bytes"])
    for axis_id, entry in lineage["axes"].items():
        print(f"   {axis_id:4s} {entry['status']:7s} basis={entry['basis_id'][:10]} "
              f"sec={entry['seconds']:6.2f} bytes={entry['bytes']:>9} "
              f"levels={''.join(str(l['level']) + l['status'][0] for l in entry['levels'])}")
