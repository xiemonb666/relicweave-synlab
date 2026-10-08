"""Step 9 (read-only): how much frozen data carries the affected geometry.

Counts the mother-bearing records in the content-addressed stores by vessel id and lists the
release manifests, so the migration section of the report can name concrete artefacts instead
of saying "everything".
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
ROOTS = [REPO / "data" / "a12", REPO / "data" / "a12_exports", REPO / "data" / "a12_demo"]
NECK = {"V06", "V07", "V08", "V09", "V10", "V11", "V16"}
WALL = {f"V{i:02d}" for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 17)}

counts: Counter = Counter()
lineages: dict[str, set] = defaultdict(set)
per_root: dict[str, Counter] = defaultdict(Counter)
releases: list[dict] = []

for root in ROOTS:
    if not root.exists():
        continue
    for meta_path in root.glob("**/assets/*/meta.json"):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = payload.get("meta") or {}
        vid = str(meta.get("vessel_id") or "")
        if not vid:
            continue
        counts[vid] += 1
        per_root[str(root.relative_to(REPO))][vid] += 1
        if meta.get("mother_id"):
            lineages[vid].add(str(meta["mother_id"]))
    for manifest in list(root.glob("releases/*/manifest.json")) + \
            list(root.glob("**/releases/*/manifest.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        releases.append({
            "path": str(manifest.parent.relative_to(REPO)),
            "release_id": data.get("release_id") or manifest.parent.name,
            "assets": len(data.get("assets") or data.get("asset_ids") or []),
            "keys": sorted(data.keys())[:14],
        })

summary = {
    "asset_records_by_vessel": dict(sorted(counts.items())),
    "distinct_mother_ids_by_vessel": {k: len(v) for k, v in sorted(lineages.items())},
    "per_root": {k: dict(sorted(v.items())) for k, v in per_root.items()},
    "affected_asset_records": {
        "neck_family_A2": {v: counts.get(v, 0) for v in sorted(NECK)},
        "wall_points_A1": {v: counts.get(v, 0) for v in sorted(WALL)},
        "A1_total": sum(counts.get(v, 0) for v in WALL),
        "A2_total": sum(counts.get(v, 0) for v in NECK),
        "total_asset_records": sum(counts.values()),
    },
    "releases": releases,
}
(HERE / "s09_frozen_inventory.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

print("asset records by vessel:", json.dumps(summary["asset_records_by_vessel"]))
print("A1 total:", summary["affected_asset_records"]["A1_total"],
      "A2 total:", summary["affected_asset_records"]["A2_total"],
      "of", summary["affected_asset_records"]["total_asset_records"])
print("roots:", json.dumps(summary["per_root"]))
print("releases:", len(releases))
for rel in releases[:20]:
    print("  ", rel["path"], rel["assets"], "assets")
