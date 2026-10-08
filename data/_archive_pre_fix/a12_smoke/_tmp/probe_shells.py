"""How many closed shells does each of the 24 vessel pioneers build?

The per-shell cut (``synlab/fracture/event.py::_cut_both_sides``) only changes behaviour for a
mother whose mesh carries more than one closed shell, so this measurement says exactly which
vessels the fix can touch and which ones keep the previous code path bit for bit.

Writes ``data/a12_smoke/_tmp/shell_census.json``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec
from synlab.fracture.booleans import mesh_shells
from synlab.mothers.api import create_mother
from synlab.pipeline import derive_named_rngs, plan_generation


def main() -> int:
    spec = load_generation_spec("configs/a12/next_experiment.yaml")
    plan = plan_generation(spec)
    first: dict[str, object] = {}
    for lineage in plan.lineages:
        first.setdefault(lineage.vessel_id, lineage)
    rows = []
    for vessel in sorted(first):
        lineage = first[vessel]
        started = time.time()
        rngs = derive_named_rngs(spec.master_seed, lineage.lineage_id)
        mother = create_mother(lineage.vessel_id, lineage.material_id, lineage.params,
                               rngs["shape"], mother_id=lineage.lineage_id)
        shells = mesh_shells(mother.mesh)
        volumes = [float(abs(part.volume)) for part, _ in shells]
        # do the shells overlap volumetrically? (a valid CSG operand needs them not to)
        import numpy as np
        from manifold3d import Manifold, Mesh

        overlaps = []
        for i in range(len(shells)):
            for j in range(i + 1, len(shells)):
                a = Manifold(Mesh(vert_properties=np.asarray(shells[i][0].vertices,
                                                             dtype=np.float32),
                                  tri_verts=np.asarray(shells[i][0].faces, dtype=np.uint32)))
                b = Manifold(Mesh(vert_properties=np.asarray(shells[j][0].vertices,
                                                             dtype=np.float32),
                                  tri_verts=np.asarray(shells[j][0].faces, dtype=np.uint32)))
                overlaps.append(round(float(abs((a ^ b).volume())), 6))
        row = {"vessel_id": vessel, "lineage_id": lineage.lineage_id,
               "mother_faces": int(mother.mesh.faces.shape[0]),
               "shells": len(shells),
               "shell_faces": [int(part.faces.shape[0]) for part, _ in shells],
               "shell_volumes_mm3": [round(v, 3) for v in volumes],
               "pairwise_overlap_mm3": overlaps,
               "watertight": bool(mother.mesh.is_watertight),
               "seconds": round(time.time() - started, 2)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    Path("data/a12_smoke/_tmp/shell_census.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    multi = [r["vessel_id"] for r in rows if r["shells"] > 1]
    print(json.dumps({"vessels": len(rows), "multi_shell": multi,
                      "single_shell": [r["vessel_id"] for r in rows if r["shells"] == 1]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
