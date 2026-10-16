"""Step 1 (read-only): locate the V10 parameter sets actually used by the batch.

Scans the content-addressed asset metadata for mother meshes and prints, per vessel id,
the observed parameter sets plus the recorded ``mother_meta.profile_metrics`` (which is
where ``z_rim`` and ``z_rim_target_mm`` are stored).  Nothing is written outside stdout.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
ASSETS = ROOT / "data" / "a12" / "assets"
OUT = Path(__file__).resolve().parent

wanted = sys.argv[1:] or ["V10", "V09", "V16", "V15", "V17"]


def main() -> int:
    per_vessel: dict[str, list[dict]] = {v: [] for v in wanted}
    seen_ids: Counter = Counter()
    for meta_path in sorted(ASSETS.glob("*/meta.json")):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = payload.get("meta") or {}
        vid = str(meta.get("vessel_id") or "")
        if vid not in per_vessel:
            continue
        seen_ids[vid] += 1
        mother_meta = meta.get("mother_meta") or {}
        per_vessel[vid].append({
            "asset": meta_path.parent.name,
            "mother_id": meta.get("mother_id"),
            "params": meta.get("params") or {},
            "profile_metrics": mother_meta.get("profile_metrics") or {},
            "geometry_hash": payload.get("geometry_hash"),
            "charts": meta.get("chart_summary") or [],
        })

    report = {"assets_scanned": int(sum(seen_ids.values())),
              "per_vessel_counts": dict(seen_ids),
              "records": per_vessel}
    (OUT / "s01_v10_params.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    for vid, rows in per_vessel.items():
        print(f"=== {vid}: {len(rows)} assets")
        uniq: dict[str, list] = {}
        for row in rows:
            key = json.dumps(row["params"], sort_keys=True)
            uniq.setdefault(key, []).append(row)
        print(f"    distinct param sets: {len(uniq)}")
        for key, group in list(uniq.items())[:4]:
            pm = group[0]["profile_metrics"]
            print(f"    params={key}")
            print(f"      n={len(group)} mother_id={group[0]['mother_id']}")
            print(f"      profile_metrics.z_rim={pm.get('z_rim')!r} "
                  f"z_rim_target_mm={pm.get('z_rim_target_mm')!r} "
                  f"z_bottom={pm.get('z_bottom')!r} r_max={pm.get('r_max')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
