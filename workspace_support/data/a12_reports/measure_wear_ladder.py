"""Real wear/aging ladder measured on real bodies of the A12 library.

Run (from ``relicweave-synlab``)::

    .venv\\Scripts\\python.exe ..\\data\\a12_reports\\measure_wear_ladder.py

Writes ``data/a12_reports/a12_wear_ladder.json`` (structured report), the worn bodies into the new
library ``data/a12_wear/store`` and nothing else.

What is measured, per body and per level:
  * applied wear depth (mm) — max / mean / p95, per mechanism, on the produced geometry;
  * contact area (mm^2 and %) and lost volume (mm^3 and % of the body);
  * glaze-loss area ratio and the exposed-substrate volume;
  * cross-section depth by region (rim / base / outer / fracture) so a *spatial* model can be
    distinguished from a global noise field;
  * the soil/patina layer means (image domain, kept separate from the geometry);
  * level-0 identity: same object, same content hash, ``bytes_unchanged``;
  * legality: watertight, positive volume, ``damaged ⊆ clean`` at 1e-3 mm (the shipped A09
    tolerance, never relaxed).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import traceback
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2] / "relicweave-synlab"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from synlab.degrade import wear as W  # noqa: E402
from synlab.degrade.specs import capture_rig_spec, material_wear_traits  # noqa: E402
from synlab.degrade.wear import WearModel, apply_wear  # noqa: E402
from synlab.roles import (  # noqa: E402
    ROLE_PHYSICAL_COMPONENT,
    SCHEMA_PHYSICAL,
    UNIT_MM,
    FRAME_WORLD,
)
from synlab.storage.store import AssetStore  # noqa: E402

OUT = Path(__file__).resolve().parent
WEAR_STORE = Path(__file__).resolve().parents[1] / "a12_wear" / "store"
SOURCE_STORE = REPO / "data" / "a12_trainable" / "store"

#: (asset_id, role, note) — real bodies of the A12 library, one shell-like fragment family and one
#: mother body, so the report never depends on a single geometry.
TARGETS = (
    ("asset_ed22e8fa5ca88685dc59", "fragment_mesh",
     "real fragment LIN0004_V10_M06_PAT03 (3223 verts, 6442 faces, 296.6 cm3)"),
    ("asset_3fdd1dba75a33e40e25d", "fragment_mesh",
     "real fragment LIN0004_V10_M06_PAT03 sibling (3378 verts, 6758 faces)"),
    ("asset_273affb5604f796375f8", "mother_mesh",
     "real mother LIN0000_V10_M11_PAT15 (3973 verts, 7936 faces, 334x334x271 mm)"),
)


def digest(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def main() -> int:
    started = time.time()
    store = AssetStore(SOURCE_STORE)
    by_id = {}
    for role in ("fragment_mesh", "mother_mesh"):
        for record in store.list_assets(role=role, limit=200):
            by_id[record.asset_id] = (record, role)
    wear_store = AssetStore(WEAR_STORE)
    rig = capture_rig_spec()

    report: dict = {
        "schema": "a12.wear_ladder.v1",
        "generated_by": "data/a12_reports/measure_wear_ladder.py",
        "model": {
            "mechanisms": ["rim_wear", "base_abrasion", "glaze_loss", "edge_chip", "microcrack",
                           "soil_layer"],
            "level_ladder": list(W.WearLevels.INTENSITY),
            "level_parameter_kind": "fraction of the physically derived maximum (not millimetres)",
            "drivers": {
                "wall_thickness_mm": "measured per vertex by an inward ray cast (no nominal value)",
                "curvature_per_mm": "signed mean curvature from the cotangent one-ring",
                "glaze_thickness_mm": "material fraction * measured wall, clamped to the measured "
                                      "L01/L03 layer interval 0.469-1.173 mm",
                "porosity_hardness_toughness": "material catalogue, CANDIDATE (see provenance)",
            },
            "provenance": WearModel().provenance(),
        },
        "spec_candidates": rig.candidates(),
        "targets": [],
    }

    for asset_id, role, note in TARGETS:
        entry: dict = {"asset_id": asset_id, "role": role, "note": note, "levels": {}}
        record, _ = by_id[asset_id]
        body = store.load_mesh(asset_id)
        # material id: the mother/fragment record carries it in meta; when the role's meta does not
        # (fragment_mesh records of some lineages), the lineage id encodes it as ..._M<nn>_...
        material = str((record.meta or {}).get("material_id") or "")
        if not material:
            lineage = str(getattr(record, "lineage_id", "") or "")
            match = re.search(r"_M(\d{2})_", lineage)
            material = f"M{match.group(1)}" if match else "M12"
            entry["material_id_source"] = f"lineage_id {lineage!r} (record meta carries none)"
        else:
            entry["material_id_source"] = "record meta"
        entry["material_id"] = material
        entry["source"] = {
            "lineage_id": getattr(record, "lineage_id", None),
            "n_vertices": int(len(body.vertices)), "n_faces": int(len(body.faces)),
            "volume_mm3": float(abs(body.volume)), "area_mm2": float(body.area),
            "watertight": bool(body.is_watertight),
            "extent_mm": [float(v) for v in (body.bounds[1] - body.bounds[0])],
            "vertices_sha256": digest(np.asarray(body.vertices, dtype=np.float64)),
            "faces_sha256": digest(np.asarray(body.faces, dtype=np.int64)),
            "bytes_unchanged": True,
        }
        entry["material_traits"] = material_wear_traits(material).as_dict()
        model = WearModel(material_id=material)
        for level in (0, 1, 2, 3, 4):
            t0 = time.time()
            row: dict = {"level": level}
            try:
                result = apply_wear(body, level, model=model)
            except Exception as exc:  # noqa: BLE001 - reported, never hidden
                row["status"] = "ERROR"
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["traceback"] = traceback.format_exc().splitlines()[-4:]
                entry["levels"][str(level)] = row
                continue
            if level == 0:
                row.update({
                    "status": "IDENTITY",
                    "identity_same_object": bool(result.mesh is body),
                    "result_bytes_unchanged": bool(digest(np.asarray(result.mesh.vertices,
                                                                    dtype=np.float64))
                                                   == entry["source"]["vertices_sha256"]),
                    "measured": {},
                    "seconds": round(time.time() - t0, 2),
                })
                entry["levels"]["0"] = row
                continue
            legal = W.legality_report(body, result.mesh, n_samples=1200, seed=0)
            measured = dict(result.field.measured)
            row.update({
                "status": "MEASURED",
                "measured": {k: float(v) for k, v in measured.items()},
                "units": dict(result.field.units),
                "legality": legal,
                "soil_layer_means": {k: float(np.mean(v)) for k, v in result.field.soil.items()},
                "soil_layer_is_image_domain": True,
                "guard": result.info["wall_guard"],
                "bands": result.info["bands"],
                "drivers": {k: v for k, v in result.info["drivers"].items()
                            if isinstance(v, (int, float, str, type(None)))},
                "layer": {k: v for k, v in result.layer.items() if k != "clamp_provenance"},
                "seconds": round(time.time() - t0, 2),
            })
            asset = wear_store.commit_asset(
                role=ROLE_PHYSICAL_COMPONENT, schema=SCHEMA_PHYSICAL, unit=UNIT_MM,
                frame=FRAME_WORLD,
                payload={"vertices": np.asarray(result.mesh.vertices, dtype=np.float64),
                         "faces": np.asarray(result.mesh.faces, dtype=np.int64),
                         "wear_depth_per_vertex_mm": np.asarray(result.field.applied_mm,
                                                                dtype=np.float64),
                         "wear_depth_per_face_mm": np.asarray(result.field.face_depth_mm,
                                                              dtype=np.float64),
                         "glaze_loss_mask": np.asarray(result.field.glaze_loss, dtype=np.uint8),
                         **{f"soil_{k}": np.asarray(v, dtype=np.float64)
                            for k, v in result.field.soil.items()}},
                meta={"axis_id": "WEAR", "variant": "aged_surface", "level": level,
                      "material_id": material, "source_asset_id": asset_id,
                      "mechanisms": list(result.mechanisms),
                      "intensity": result.intensity,
                      "measured": row["measured"], "units": row["units"],
                      "planned": {"level_ladder": list(W.WearLevels.INTENSITY)},
                      "spec_candidates_ref": "a12_wear_ladder.json:spec_candidates"},
                qa={"status": "PASS" if legal["damaged_subset_clean"] and legal["watertight"]
                    else "FAIL", **{k: legal[k] for k in
                                    ("watertight", "positive_volume", "damaged_subset_clean",
                                     "subset_outside_points", "subset_max_outside_mm",
                                     "tolerance_mm")}},
                lineage_id=getattr(record, "lineage_id", None), split="train",
            )
            row["asset_id"] = asset.asset_id
            row["seconds"] = round(time.time() - t0, 2)
            entry["levels"][str(level)] = row
        report["targets"].append(entry)

    report["seconds_total"] = round(time.time() - started, 2)
    (OUT / "a12_wear_ladder.json").write_text(json.dumps(report, indent=1, default=str),
                                              encoding="utf-8")
    print("wrote", OUT / "a12_wear_ladder.json", "in", report["seconds_total"], "s")
    for entry in report["targets"]:
        print("==", entry["asset_id"], entry["material_id"])
        for level, row in sorted(entry["levels"].items()):
            if row.get("status") == "IDENTITY":
                print("   L0 identity same_object=%s bytes_unchanged=%s"
                      % (row["identity_same_object"], row["result_bytes_unchanged"]))
                continue
            if row.get("status") != "MEASURED":
                print("   L%s %s %s" % (level, row.get("status"), row.get("error")))
                continue
            m, lg = row["measured"], row["legality"]
            print("   L%s depth=%.4f mm lost=%.2f mm3 (%.3f%%) contact=%.1f%% glaze_area=%.4f "
                  "| wt=%s sub=%s out=%d max=%.3g"
                  % (level, m["max_applied_depth_mm"], m["lost_volume_mm3"],
                     100 * m["lost_volume_fraction"], 100 * m["contact_area_fraction"],
                     m["glaze_lost_area_ratio"], lg["watertight"],
                     lg["damaged_subset_clean"], lg["subset_outside_points"],
                     lg["subset_max_outside_mm"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
