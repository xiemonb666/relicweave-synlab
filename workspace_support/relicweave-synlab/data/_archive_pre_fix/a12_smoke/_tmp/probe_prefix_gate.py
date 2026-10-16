"""Pre-fix fracture gate: would the *whole-body* boolean have closed both sides?

The per-shell cut only changes the code path for a mother with more than one closed shell, so
this probe reconstructs exactly what the previous ``run_shared_cut`` did for those vessels --
one Manifold intersection/difference over the whole body -- and reports the gate the pipeline
applies (``side.mesh.is_watertight``).  A vessel that fails here is a vessel the pre-fix chain
refused with ``FRACTURE_CONSERVATION_FAIL`` before it ever reached the observation stage.

Usage::

    python data/a12_smoke/_tmp/probe_prefix_gate.py            # the 6 multi-shell vessels
    python data/a12_smoke/_tmp/probe_prefix_gate.py 0 15       # explicit mother indices
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec
from synlab.fracture import booleans as B
from synlab.fracture.api import make_closed_cutter
from synlab.mothers.api import create_mother
from synlab.pipeline import derive_named_rngs, plan_generation

#: vessels whose mother mesh carries more than one closed shell (data/a12_smoke/_tmp/shell_census.json)
MULTI_SHELL = ("V05", "V10", "V15", "V16", "V17", "V24")


def edge_use(mesh: trimesh.Trimesh) -> tuple[int, int]:
    edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    counts = np.bincount(np.asarray(mesh.edges_unique_inverse, dtype=np.int64),
                         minlength=edges.shape[0])
    return int(np.sum(counts == 1)), int(np.sum(counts > 2))


def main() -> int:
    spec = load_generation_spec("configs/a12/next_experiment.yaml")
    plan = plan_generation(spec)
    first: dict[str, object] = {}
    for lineage in plan.lineages:
        first.setdefault(lineage.vessel_id, lineage)
    if len(sys.argv) > 1:
        wanted = {int(x) for x in sys.argv[1:]}
        pick = [l for l in plan.lineages if l.mother_index in wanted]
    else:
        pick = [first[v] for v in MULTI_SHELL]
    rows = []
    for lineage in pick:
        started = time.time()
        rngs = derive_named_rngs(spec.master_seed, lineage.lineage_id)
        mother = create_mother(lineage.vessel_id, lineage.material_id, lineage.params,
                               rngs["shape"], mother_id=lineage.lineage_id)
        cutter = make_closed_cutter(mother, spec.fracture, rngs["cut"])
        source_mother = B.tag_source(trimesh.Trimesh(vertices=np.asarray(mother.mesh.vertices),
                                                     faces=np.asarray(mother.mesh.faces),
                                                     process=False), 1.0, "mother")
        source_cutter = B.tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                                     faces=np.asarray(cutter.mesh.faces),
                                                     process=False), 2.0, "cutter")
        sides = {}
        for label, fn in (("M_minus", B.boolean_intersection), ("M_plus", B.boolean_difference)):
            out = fn([source_mother, source_cutter], label=label)
            boundary, over = edge_use(out.mesh)
            sides[label] = {"faces": int(out.n_faces), "watertight": bool(out.mesh.is_watertight),
                            "boundary_edges": boundary, "nonmanifold_edges": over,
                            "components": len(out.mesh.split(only_watertight=False))}
        would_refuse = not all(sides[k]["watertight"] for k in sides)
        row = {"vessel_id": lineage.vessel_id, "lineage_id": lineage.lineage_id,
               "mother_shells": len(B.mesh_shells(mother.mesh)),
               "pre_fix_gate": "FRACTURE_CONSERVATION_FAIL" if would_refuse else "passes",
               "sides": sides, "seconds": round(time.time() - started, 2)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    Path("data/a12_smoke/_tmp/prefix_gate.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    refused = [r["vessel_id"] for r in rows if r["pre_fix_gate"] != "passes"]
    print(json.dumps({"checked": len(rows), "refused_before_fix": refused,
                      "passed_before_fix": [r["vessel_id"] for r in rows
                                            if r["pre_fix_gate"] == "passes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
