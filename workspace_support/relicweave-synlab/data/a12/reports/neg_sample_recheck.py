"""Item 4: sample >= 30 real negatives and re-check each one twice, independently.

Two checks per sampled pair, neither of which reads the classification under test:

1. **ledger re-derivation** (``synlab.relations.negatives.audit_negative_sample``): rebuild the
   verdict from the raw measured ledger -- the mother identity, the event identity of both
   fragments, and the full interface-patch list of every measured event.  A shared real fracture
   surface would have to appear as an interface patch connecting the two fragments.
2. **geometry re-check** (this script): load both fragments' committed npz meshes and measure
   (a) exact shared vertices, (b) the minimum surface distance and (c) the measured volumetric
   overlap in both directions.  A pair that really shared a fracture surface would share the
   cut-face vertices; a pair that shares *material* (the plan's §2.4 concern about alternative
   events of one mother) shows a positive overlap instead.

Writes ``data/a12/reports/relation_negatives_sample_recheck.json`` after every pair, so a host
kill keeps the finished checks.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from synlab.fracture.fragment import overlap_ratio  # noqa: E402
from synlab.relations.multi_event import library_fragments  # noqa: E402
from synlab.relations.negatives import audit_negative_sample  # noqa: E402
from synlab.schemas.runtime import RELATION_R0, RELATION_R1  # noqa: E402

REPORTS = REPO / "data" / "a12" / "reports"
BASE = REPORTS / "relation_negatives"
MESHES = BASE / "meshes"
OUT = REPORTS / "relation_negatives_sample_recheck.json"
SAMPLE_SIZE = 40
SEED = 20261003

library = json.loads((REPORTS / "relation_negatives_library.json").read_text(encoding="utf-8"))
rows = json.loads((REPORTS / "relation_negatives_rows.json").read_text(encoding="utf-8"))
fragments = library_fragments(library)

# the population is the set a loader can actually use as negatives:
# storage.export writes eligible_as_negative = kind in {R1,R0} and valid and loss_mask
population = [r for r in rows if str(r["kind"]) in (RELATION_R0, RELATION_R1)
              and bool(r.get("valid")) and bool(r.get("loss_mask"))]
population.sort(key=lambda r: (str(r["a"]), str(r["b"])))

report: dict = {"schema": "synlab.neg.relatives_sample_recheck.v1",
                "population": len(population), "sample_size": int(SAMPLE_SIZE), "seed": SEED,
                "population_note": ("export-eligible negatives only: kind in {R1,R0} and valid "
                                    "and loss_mask (synlab/storage/export.py:581)"),
                "ledger": None, "geometry": [], "method": {}, "ok": False}
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

ledger = audit_negative_sample(library, population, sample_size=SAMPLE_SIZE, seed=SEED,
                               kinds=(RELATION_R0, RELATION_R1))
report["ledger"] = {k: v for k, v in ledger.items()
                    if k not in ("checked", "foreign_patch_examples")}
report["ledger"]["checked_pairs"] = [{"a": c["a"], "b": c["b"], "labelled": c["labelled"],
                                      "re_derived": c["re_derived"],
                                      "same_mother": c["same_mother"],
                                      "same_event": c["same_event"],
                                      "is_measured_R2": c["is_measured_R2"],
                                      "shared_patch": c["shared_patch"],
                                      "event_a": c["event_a"], "event_b": c["event_b"],
                                      "ok": c["ok"]} for c in ledger["checked"]]
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def load_mesh(fragment_id: str):
    import trimesh

    path = MESHES / f"mesh_{fragment_id}.npz"
    if not path.exists():
        return None
    payload = np.load(path)
    return trimesh.Trimesh(vertices=np.asarray(payload["vertices"]),
                           faces=np.asarray(payload["faces"]), process=False)


started = time.perf_counter()
for entry in ledger["checked"]:
    a, b = str(entry["a"]), str(entry["b"])
    mesh_a, mesh_b = load_mesh(a), load_mesh(b)
    item = {"a": a, "b": b, "labelled": entry["labelled"], "re_derived_ledger": entry["re_derived"],
            "same_mother": entry["same_mother"], "same_event": entry["same_event"],
            "ledger_shared_patch": bool(entry["shared_patch"]),
            "ledger_is_measured_R2": bool(entry["is_measured_R2"]),
            "mother_a": fragments.get(a, {}).get("mother_id"),
            "mother_b": fragments.get(b, {}).get("mother_id"),
            "event_a": fragments.get(a, {}).get("event_id"),
            "event_b": fragments.get(b, {}).get("event_id")}
    if mesh_a is None or mesh_b is None:
        item.update({"geometry": None, "error": "fragment mesh not present on disk",
                     "not_a_real_adjacency": bool(entry["ok"])})
        report["geometry"].append(item)
        continue
    verts_a = np.asarray(mesh_a.vertices, dtype=np.float64)
    verts_b = np.asarray(mesh_b.vertices, dtype=np.float64)
    quant_a = {tuple(np.round(v, 9)) for v in verts_a}
    quant_b = {tuple(np.round(v, 9)) for v in verts_b}
    shared = len(quant_a & quant_b)
    nearest = float(np.min(mesh_b.nearest.on_surface(verts_a)[1]))
    overlap_ab = float(overlap_ratio(mesh_a, mesh_b, seed=0))
    overlap_ba = float(overlap_ratio(mesh_b, mesh_a, seed=1))
    item["geometry"] = {
        "shared_vertices_exact": int(shared),
        "shared_vertex_ratio_a": float(shared / max(len(quant_a), 1)),
        "min_surface_distance_mm": nearest,
        "overlap_ratio_a_in_b": overlap_ab,
        "overlap_ratio_b_in_a": overlap_ba,
        "max_overlap_ratio": max(overlap_ab, overlap_ba),
        "vertices_a": int(verts_a.shape[0]), "vertices_b": int(verts_b.shape[0]),
    }
    # a real adjacency would have to share the cut face: exact shared vertices (the boolean
    # union tags both sides from one cutter) or a measured interface patch in the ledger.
    item["not_a_real_adjacency"] = bool(not item["ledger_shared_patch"]
                                        and not item["ledger_is_measured_R2"] and shared == 0)
    item["shares_material"] = bool(max(overlap_ab, overlap_ba) > 0.0)
    report["geometry"].append(item)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")

by_basis: dict[str, dict] = {}
for item in report["geometry"]:
    key = ("different_mother" if not item["same_mother"] else
           ("same_event" if item["same_event"] else "same_mother_other_event"))
    bucket = by_basis.setdefault(key, {"pairs": 0, "not_a_real_adjacency": 0,
                                       "shares_material": 0, "max_overlap_ratio": 0.0,
                                       "max_shared_vertices": 0, "examples": []})
    bucket["pairs"] += 1
    bucket["not_a_real_adjacency"] += int(bool(item.get("not_a_real_adjacency")))
    bucket["shares_material"] += int(bool(item.get("shares_material")))
    geometry = item.get("geometry") or {}
    bucket["max_overlap_ratio"] = max(bucket["max_overlap_ratio"],
                                      float(geometry.get("max_overlap_ratio", 0.0)))
    bucket["max_shared_vertices"] = max(bucket["max_shared_vertices"],
                                        int(geometry.get("shared_vertices_exact", 0)))
    if len(bucket["examples"]) < 3:
        bucket["examples"].append({"a": item["a"], "b": item["b"],
                                   "overlap": geometry.get("max_overlap_ratio"),
                                   "shared_vertices": geometry.get("shared_vertices_exact"),
                                   "min_distance_mm": geometry.get("min_surface_distance_mm")})
report["by_basis"] = by_basis
report["method"] = {
    "ledger": ("audit_negative_sample: re-derive the verdict from the measured library "
               "(mother id, event id and the interface-patch list of every event); the "
               "classification under test is never read"),
    "geometry": ("independent second pass on the committed npz meshes: exact shared vertex "
                 "count, minimum surface distance, and trimesh sampled volumetric overlap "
                 "ratio in both directions (synlab.fracture.fragment.overlap_ratio)"),
    "why_it_decides_adjacency": ("two fragments of one real fracture share the cut face, so a "
                                 "real adjacency must show either a ledger interface patch "
                                 "connecting them or the boolean's shared cutter vertices"),
    "population": report["population_note"],
}
report["sampled"] = len(report["geometry"])
report["not_a_real_adjacency"] = sum(1 for i in report["geometry"]
                                     if i.get("not_a_real_adjacency"))
report["shares_material"] = sum(1 for i in report["geometry"] if i.get("shares_material"))
report["ledger_mismatches"] = len(ledger["mismatches"])
report["ok"] = bool(report["sampled"] >= 30 and report["not_a_real_adjacency"] == report["sampled"]
                    and report["ledger_mismatches"] == 0)
report["seconds"] = time.perf_counter() - started
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

print(json.dumps({"population": report["population"], "sampled": report["sampled"],
                  "not_a_real_adjacency": report["not_a_real_adjacency"],
                  "shares_material": report["shares_material"],
                  "ledger_mismatches": report["ledger_mismatches"],
                  "ledger_ok": ledger["ok"], "by_basis": by_basis,
                  "ok": report["ok"], "seconds": report["seconds"]},
                 ensure_ascii=False, indent=2, default=str))
raise SystemExit(0 if report["ok"] else 1)
