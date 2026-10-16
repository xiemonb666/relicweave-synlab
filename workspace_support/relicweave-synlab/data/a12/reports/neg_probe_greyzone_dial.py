"""Probe: can a real grey-zone (TINY_CONTACT) cut be produced under the frozen audit?

For mother 0 of the relation-negative library, dial the cut plane at several target
cross-section areas inside the frozen grey band ``[tiny_threshold, r2_threshold)`` and run
the real ``fracture_event``.  Records, per target, the measured pair common clip area, the
pair-level verdict of ``finalize_clean_truth`` and the boolean ``overlap_ratio`` even when
``audit_fracture`` refuses the event.  Writes after every attempt so a host kill keeps the
evidence.

Read-only w.r.t. the repository; writes only ``data/a12/reports/_neg_greyzone_probe.json``.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from synlab.fracture.api import audit_fracture, fracture_event  # noqa: E402
from synlab.fracture.booleans import mesh_hash  # noqa: E402
from synlab.fracture.fragment import overlap_ratio  # noqa: E402
from synlab.fracture.spec import (  # noqa: E402
    BACKEND_PLANE, R2_AREA_ABS_MM2, R2_AREA_REL, TINY_AREA_ABS_MM2, TINY_AREA_REL,
    FractureSpec,
)
from synlab.mothers.api import create_mother  # noqa: E402
from synlab.relations.multi_event import _section_area_mm2  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.truth.api import finalize_clean_truth  # noqa: E402

OUT = REPO / "data" / "a12" / "reports" / "_neg_greyzone_probe.json"
PLAN = json.loads((REPO / "data" / "a12_exports" / "relation_negatives"
                   / "library_plan.json").read_text(encoding="utf-8"))
MASTER_SEED = int(PLAN["master_seed"])
MOTHER = PLAN["mothers"][0]

result: dict = {"schema": "synlab.neg.greyzone_probe.v1", "mother": MOTHER["lineage_id"],
                "master_seed": MASTER_SEED, "attempts": [], "ok": False}


def flush() -> None:
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")


mother = create_mother(MOTHER["vessel_id"], MOTHER["material_id"], MOTHER["params"],
                       make_rng(MASTER_SEED, MOTHER["lineage_id"], "shape"),
                       mother_id=MOTHER["lineage_id"])
area = float(getattr(mother, "area_mm2", 0.0))
high = max(R2_AREA_ABS_MM2, R2_AREA_REL * area)
low = max(TINY_AREA_ABS_MM2, TINY_AREA_REL * area)
result["thresholds"] = {"r2_area_threshold_mm2": high, "tiny_area_threshold_mm2": low,
                        "mother_area_mm2": area, "mother_faces": int(len(mother.mesh.faces))}
flush()

# a fixed, mostly horizontal normal: it slices the body through its axis, which keeps the
# boolean well conditioned; only the offset (hence the target area) varies here.
normal = np.array([1.0, 0.0, 0.0])
targets = [0.95 * high, 0.90 * high, 0.75 * high, 0.50 * high,
           float(np.sqrt(low * high)), 0.30 * high, 0.10 * high]
for index, target in enumerate(targets):
    entry: dict = {"index": index, "target_area_mm2": float(target),
                   "frac_of_r2_threshold": float(target / high)}
    result["attempts"].append(entry)
    t0 = time.perf_counter()
    try:
        points = np.asarray(mother.mesh.vertices, dtype=np.float64)
        centre = points.mean(axis=0)
        projections = (points - centre) @ normal
        lo_o = float(np.min(projections)) + 1e-6
        hi_o = float(np.max(projections)) - 1e-6
        best_offset, best_area = hi_o, 0.0
        for _ in range(28):
            middle = 0.5 * (lo_o + hi_o)
            measured = _section_area_mm2(mother.mesh, normal, centre + normal * middle)
            if abs(measured - target) < abs(best_area - target):
                best_offset, best_area = middle, measured
            if measured > target:
                hi_o = middle
            else:
                lo_o = middle
            if abs(measured - target) <= max(1e-9, 0.02 * target):
                best_offset, best_area = middle, measured
                break
        entry["dialed_section_area_mm2"] = float(best_area)
        spec = FractureSpec(backend=BACKEND_PLANE, error_budget_mm=0.01,
                            target_rms_mm=0.16,
                            plane_point=(centre + normal * best_offset),
                            plane_normal=normal)
        rng = make_rng(MASTER_SEED, MOTHER["lineage_id"], "cut",
                       f"{MOTHER['lineage_id']}_E03", index)
        event_id = f"{MOTHER['lineage_id']}_GZ{index:02d}"
        fracture = fracture_event(mother, spec, rng, event_id=event_id)
        entry["fragment_ids"] = [f.fragment_id for f in fracture.fragments]
        entry["fragment_volumes_mm3"] = [float(f.volume_mm3) for f in fracture.fragments]
        entry["mesh_hashes"] = [mesh_hash(f.mesh) for f in fracture.fragments]
        # the audit's own worst-pair overlap, measured even when the audit refuses
        minus = [f for f in fracture.fragments if f.face_side.size and int(f.face_side[0]) < 0]
        plus = [f for f in fracture.fragments if f.face_side.size and int(f.face_side[0]) > 0]
        worst, per_pair = 0.0, []
        for frag_a in minus[:4]:
            for frag_b in plus[:4]:
                value = overlap_ratio(frag_a.mesh, frag_b.mesh, seed=0)
                per_pair.append({"a": frag_a.fragment_id, "b": frag_b.fragment_id,
                                 "overlap_ratio": value})
                worst = max(worst, value)
        entry["overlap_ratio_worst"] = float(worst)
        entry["overlap_pairs"] = per_pair
        try:
            audit = audit_fracture(fracture, mother)
            entry["audit_ok"] = bool(audit.get("ok", True))
            entry["audit_overlap_ratio"] = float(audit.get("overlap_ratio", -1.0))
        except Exception as exc:  # noqa: BLE001 - refusal is the measurement
            entry["audit_ok"] = False
            entry["audit_error"] = f"{type(exc).__name__}: {exc}"
        clean = finalize_clean_truth(mother, fracture)
        entry["relations"] = [
            {"a": a, "b": b, "kind": str(edge.kind), "area_mm2": float(edge.area_mm2),
             "valid": bool(edge.valid), "loss_mask": bool(edge.loss_mask),
             "reason": str(edge.reason)[:160]}
            for (a, b), edge in clean.relations.items()]
        entry["patch_areas_mm2"] = [
            {"interface_id": int(p.interface_id), "fragment_a": str(p.fragment_a),
             "fragment_b": str(p.fragment_b), "area_mm2": float(p.area_mm2),
             "pair_common_clip_area_mm2": (p.meta or {}).get("pair_common_clip_area_mm2"),
             "patch_kind": (clean.meta.get("patch_evidence", {}).get(int(p.interface_id), {})
                            or {}).get("kind")}
            for p in clean.interfaces]
        entry["ok"] = True
        entry["grey_zone_reached"] = any(r["kind"] == "TINY_CONTACT" for r in entry["relations"])
    except Exception as exc:  # noqa: BLE001 - a refused attempt is a recorded outcome
        entry["ok"] = False
        entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["error_code"] = str(getattr(getattr(exc, "code", None), "value", ""))
        entry["traceback_tail"] = traceback.format_exc().strip().splitlines()[-3:]
    entry["seconds"] = time.perf_counter() - t0
    flush()

result["ok"] = any(a.get("grey_zone_reached") for a in result["attempts"])
flush()
print(json.dumps({k: v for k, v in result.items() if k != "attempts"}, ensure_ascii=False))
for entry in result["attempts"]:
    print(json.dumps({k: v for k, v in entry.items()
                      if k not in ("overlap_pairs", "traceback_tail")}, ensure_ascii=False))
