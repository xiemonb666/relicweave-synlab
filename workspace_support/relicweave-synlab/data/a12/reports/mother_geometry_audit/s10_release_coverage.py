"""Step 10 (read-only): which frozen releases and baselines carry the affected geometry."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
A1 = {f"V{i:02d}" for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 17)}
A2 = {"V06", "V07", "V08", "V09", "V10", "V11", "V16"}

rows = []
for manifest in sorted(REPO.glob("data/a12_exports/**/releases/*/manifest.json")):
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        continue
    lineages = sorted({str(a.get("lineage_id") or "") for a in (data.get("assets") or [])})
    vessels = sorted({lin.split("_")[1] for lin in lineages if len(lin.split("_")) > 2})
    rows.append({
        "release": str(manifest.parent.relative_to(REPO)),
        "manifest_hash": data.get("manifest_hash"),
        "frozen_at": data.get("frozen_at"),
        "scope": data.get("scope"),
        "n_assets": len(data.get("assets") or []),
        "n_lineages": len(lineages),
        "vessels": vessels,
        "affected_A1": sorted(set(vessels) & A1),
        "affected_A2": sorted(set(vessels) & A2),
        "lineages_total": lineages,
    })

baselines = []
for candidate in [REPO / "_baseline_acceptance.json",
                  REPO / "data" / "a12" / "reports" / "_baseline" / "acceptance_summary_before.json"]:
    if candidate.exists():
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception as exc:
            baselines.append({"path": str(candidate.relative_to(REPO)), "error": str(exc)})
            continue
        keys = sorted(payload.keys()) if isinstance(payload, dict) else [f"<{type(payload).__name__}>"]
        baselines.append({"path": str(candidate.relative_to(REPO)), "keys": keys,
                          "size_bytes": candidate.stat().st_size})

out = {"releases": rows, "baselines": baselines}
(HERE / "s10_release_coverage.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

for row in rows:
    print(f"{row['release']}  assets={row['n_assets']:4d} lineages={row['n_lineages']:3d} "
          f"vessels={','.join(row['vessels'])}")
    print(f"    A1={','.join(row['affected_A1']) or '-'}  A2={','.join(row['affected_A2']) or '-'} "
          f"frozen_at={row['frozen_at']}")
print()
for base in baselines:
    print(base)
