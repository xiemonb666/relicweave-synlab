"""Report the truth-layer R2 state of the committed sandbox run (read-only).

Writes ``data/a12/reports/r2_after_fix.json``: per lineage the fragment count, interface count,
relation kinds, the pair-level common fracture area, the ambiguity measurement and the QA checks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from synlab.storage.store import AssetStore  # noqa: E402


def main() -> int:
    store = AssetStore(REPO_ROOT / "data" / "a12" / "store",
                       db_path=REPO_ROOT / "data" / "a12" / "metadata.sqlite")
    rows = []
    for role in ("clean_truth", "physical_truth", "visible_labels"):
        records = sorted(store.list_assets(role=role),
                         key=lambda record: float(getattr(record, "created_at", 0.0) or 0.0))
        if role == "clean_truth":
            # one asset per lineage and run: keep the four newest (the latest generate run)
            newest: dict[str, Any] = {}
            for record in records:
                newest[str(record.lineage_id)] = record
            records = [newest[key] for key in sorted(newest)]
        for record in records:
            meta = dict(record.meta or {})
            qa = dict(record.qa or {})
            entry = {
                "asset_id": record.asset_id,
                "role": role,
                "lineage_id": getattr(record, "lineage_id", None),
                "split": getattr(record, "split", None),
                "mother_id": meta.get("mother_id"),
                "event_id": meta.get("event_id"),
                "qa_status": getattr(record, "qa_status", None),
                "qa_pass": bool(qa.get("pass")),
                "qa": {k: v for k, v in qa.items()
                       if k in ("r2_pairs", "r1_pairs", "tiny_pairs", "unknown_pairs",
                                "relation_count", "interface_patches", "fragments",
                                "r2_area_mm2_total", "r2_area_threshold_mm2",
                                "mother_area_mm2", "ambiguity_area_ratio_max",
                                "ambiguity_area_ratio_total", "correspondence_samples",
                                "failures", "checks", "association_counts",
                                "fragments_present", "fragments_total")},
            }
            if role == "clean_truth":
                entry["fragment_count"] = len(meta.get("fragment_ids") or [])
                entry["interfaces"] = int(meta.get("interface_count", 0) or 0)
                relations = meta.get("relations") or json.loads(
                    meta.get("relations_json", "[]") or "[]")
                entry["relations"] = [
                    {k: row.get(k) for k in ("a", "b", "kind", "area_mm2", "valid",
                                             "loss_mask", "reason", "interface_id")}
                    for row in relations]
                evidence = meta.get("patch_evidence") or {}
                entry["patch_clip_areas_mm2"] = [
                    {"interface_id": key,
                     "measured_area_mm2": row.get("area_mm2"),
                     "event_area_mm2": row.get("event_area_mm2"),
                     "pair_common_area_mm2": row.get("pair_common_area_mm2"),
                     "pair_common_area_source": row.get("pair_common_area_source"),
                     "structural_ok": row.get("structural_ok"),
                     "reason": row.get("reason"),
                     "ambiguity_area_ratio": row.get("ambiguity_area_ratio"),
                     "gap_p95_mm": row.get("gap_p95_mm"),
                     "normal_angle_p95_deg": row.get("normal_angle_p95_deg"),
                     "material_inside_fraction": row.get("material_inside_fraction"),
                     "new_fracture_fraction_first": row.get("new_fracture_fraction_first"),
                     "new_fracture_fraction_second": row.get("new_fracture_fraction_second")}
                    for key, row in sorted(evidence.items(), key=lambda kv: int(kv[0]))]
            rows.append(entry)
    out = {
        "store": str(store.root),
        "clean_truth_assets": sum(1 for r in rows if r["role"] == "clean_truth"),
        "r2_pairs_total": sum(int(r["qa"].get("r2_pairs", 0) or 0)
                              for r in rows if r["role"] == "clean_truth"),
        "r2_clean_truth_assets": sum(1 for r in rows if r["role"] == "clean_truth"
                                     and int(r["qa"].get("r2_pairs", 0) or 0) > 0),
        "rows": rows,
    }
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(f"clean_truth={out['clean_truth_assets']} r2_pairs_total={out['r2_pairs_total']} "
          f"assets_with_r2={out['r2_clean_truth_assets']}")
    for row in rows:
        if row["role"] != "clean_truth":
            continue
        print(f"  {row['lineage_id']} {row['mother_id']} {row['event_id']}: "
              f"r2={row['qa'].get('r2_pairs')} r1={row['qa'].get('r1_pairs')} "
              f"tiny={row['qa'].get('tiny_pairs')} unknown={row['qa'].get('unknown_pairs')} "
              f"area={row['qa'].get('r2_area_mm2_total')} "
              f"thr={row['qa'].get('r2_area_threshold_mm2')} "
              f"amb_max={row['qa'].get('ambiguity_area_ratio_max')} "
              f"pass={row['qa_pass']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
