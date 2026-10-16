"""Diagnose the V10 fracture boolean: inspect M_minus / M_plus watertightness.

Reproduces the pipeline's fracture stage for one lineage and, instead of only reporting the
refusal, measures *why* the boolean output is not closed:

* per-side face/vertex/edge counts, euler number, winding consistency, volume,
* the connected components of each side (a composite mother splits into several),
* for every component: is_watertight / is_winding_consistent, and the boundary edges
  (edges used by exactly one face) with their lengths and positions.

Usage::

    python data/a12_smoke/_tmp/probe_v10_fracture.py [mother_index]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec
from synlab.fracture.api import fracture_event, make_closed_cutter
from synlab.fracture.booleans import boolean_difference, boolean_intersection, tag_source
from synlab.mothers.api import create_mother
from synlab.pipeline import derive_named_rngs, plan_generation


def component_report(mesh: trimesh.Trimesh, name: str) -> dict:
    parts = mesh.split(only_watertight=False)
    rows = []
    for i, part in enumerate(parts):
        edges = np.asarray(part.edges_unique, dtype=np.int64)
        counts = np.bincount(np.asarray(part.edges_unique_inverse, dtype=np.int64),
                             minlength=edges.shape[0])
        boundary = edges[counts == 1]
        over = edges[counts > 2]
        rows.append({
            "component": i,
            "faces": int(part.faces.shape[0]),
            "vertices": int(part.vertices.shape[0]),
            "watertight": bool(part.is_watertight),
            "winding_consistent": bool(part.is_winding_consistent),
            "volume_mm3": float(abs(part.volume)),
            "euler_number": int(part.euler_number),
            "boundary_edges": int(boundary.shape[0]),
            "boundary_edge_total_len_mm": float(
                np.sum(np.linalg.norm(
                    part.vertices[edges[boundary][:, 0]] - part.vertices[edges[boundary][:, 1]],
                    axis=1))) if boundary.shape[0] else 0.0,
            "nonmanifold_edges": int(over.shape[0]),
            "body_count": int(part.body_count),
        })
    print(f"--- {name}: faces={mesh.faces.shape[0]} volume={abs(mesh.volume):.2f} "
          f"watertight={mesh.is_watertight} winding={mesh.is_winding_consistent} "
          f"components={len(parts)}")
    for row in rows:
        print("   ", json.dumps(row))
    return {"name": name, "faces": int(mesh.faces.shape[0]), "components": rows}


def main() -> int:
    index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    spec = load_generation_spec("configs/a12/next_experiment.yaml")
    plan = plan_generation(spec)
    lineage = next(l for l in plan.lineages if l.mother_index == index)
    rngs = derive_named_rngs(spec.master_seed, lineage.lineage_id)
    mother = create_mother(lineage.vessel_id, lineage.material_id, lineage.params,
                           rngs["shape"], mother_id=lineage.lineage_id)
    print(f"{lineage.lineage_id} vessel={lineage.vessel_id} material={lineage.material_id} "
          f"pattern={lineage.pattern_id}")
    mm = mother.mesh
    print(f"mother: faces={mm.faces.shape[0]} watertight={mm.is_watertight} "
          f"winding={mm.is_winding_consistent} volume={abs(mm.volume):.2f} "
          f"components={len(mm.split(only_watertight=False))}")

    cutter = make_closed_cutter(mother, spec.fracture, rngs["cut"])
    source_mother = tag_source(trimesh.Trimesh(vertices=np.asarray(mm.vertices),
                                               faces=np.asarray(mm.faces), process=False),
                               1.0, "mother")
    source_cutter = tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                               faces=np.asarray(cutter.mesh.faces),
                                               process=False),
                               2.0, "cutter")
    meta = {}
    for label, fn, args in (("M_minus", boolean_intersection, [source_mother, source_cutter]),
                            ("M_plus", boolean_difference, [source_mother, source_cutter])):
        try:
            out = fn(args, label=label)
        except Exception as exc:  # noqa: BLE001 - the probe reports the real failure
            print(f"{label}: boolean raised {type(exc).__name__}: {exc}")
            continue
        meta[label] = component_report(out.mesh, label)
        meta[label]["boolean_meta"] = {k: v for k, v in out.meta.items()
                                       if isinstance(v, (int, float, str, bool))}
    try:
        result = fracture_event(mother, spec.fracture, rngs["cut"], event_id=lineage.event_ids[0])
        print(f"fracture_event OK: fragments={len(result.fragments)}")
    except Exception as exc:  # noqa: BLE001
        print(f"fracture_event FAILED {type(exc).__name__}: {exc}")
        for key in ("code", "message", "measurements"):
            if hasattr(exc, key):
                print(f"   {key}={getattr(exc, key)}")
    Path("data/a12_smoke/_tmp/probe_fracture_out.json").write_text(
        json.dumps(meta, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
