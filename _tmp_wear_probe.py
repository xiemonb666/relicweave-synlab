"""Scratch smoke probe for synlab.degrade.wear on a REAL mother body (temporary)."""
from __future__ import annotations

import sys
import time

sys.path.insert(0, r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")

from synlab.storage.store import AssetStore  # noqa: E402
from synlab.degrade.wear import WearModel, apply_wear, legality_report, local_thickness  # noqa: E402

STORE = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\data\a12_trainable\store"


def main() -> None:
    store = AssetStore(STORE)
    rows = store.list_assets(role="mother_mesh", limit=6)
    for record in rows:
        body = store.load_mesh(record.asset_id)
        print("==", record.asset_id, record.lineage_id,
              "material", (record.meta or {}).get("material_id"),
              "faces", len(body.faces), "verts", len(body.vertices),
              "watertight", body.is_watertight, "volume %.2f" % body.volume,
              "extent", [round(float(v), 2) for v in (body.bounds[1] - body.bounds[0])])
        if not body.is_watertight or body.volume <= 0:
            continue
        if len(body.vertices) > 20000:
            continue
        t0 = time.time()
        thick = local_thickness(body)
        print("   thickness median %.4f p05 %.4f min %.4f max %.4f missing %d (%.1fs)"
              % (thick["median_mm"], thick["p05_mm"], thick["min_mm"], thick["max_mm"],
                 thick["missing"], time.time() - t0))
        model = WearModel(material_id=str((record.meta or {}).get("material_id", "M03")))
        for level in (0, 1, 2, 3, 4):
            t0 = time.time()
            try:
                result = apply_wear(body, level, model=model)
            except Exception as exc:  # noqa: BLE001
                print("   L%d ERROR %s: %s" % (level, type(exc).__name__, exc))
                continue
            if level == 0:
                print("   L0 identity (mesh is source object):", result.mesh is body)
                continue
            m = result.field.measured
            print("   L%d maxdepth %.4f mm  contact %.2f mm2 (%.3f%%)  lost %.4f mm3  "
                  "glaze_area %.4f  wt %s vol+ %s faces %d->%d (%.1fs)"
                  % (level, m["max_applied_depth_mm"], m["contact_area_mm2"],
                     100 * m["contact_area_fraction"], m["lost_volume_mm3"],
                     m["glaze_lost_area_ratio"], m["watertight"], m["positive_volume"],
                     int(m["face_count_before"]), int(m["face_count_after"]), time.time() - t0))
            if level == 4:
                legal = legality_report(body, result.mesh, n_samples=800)
                print("      legality:", {k: legal[k] for k in
                                          ("watertight", "positive_volume",
                                           "damaged_subset_clean", "subset_outside_points",
                                           "subset_max_outside_mm")})
                print("      bands:", {k: v for k, v in result.info["bands"].items()})
                print("      drivers:", {k: (round(v, 6) if isinstance(v, float) else v)
                                         for k, v in result.info["drivers"].items()
                                         if not isinstance(v, dict)})
        break


if __name__ == "__main__":
    main()
