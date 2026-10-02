"""Debug: why is the morphology cutter not watertight?  Dump the edge-use histogram."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests" / "a12" / "fracture"))

import numpy as np  # noqa: E402


def box_mother(extents=(14.0, 14.0, 14.0)):
    try:
        import fixtures as fx

        return fx.box_mother(extents)
    except Exception:  # noqa: BLE001
        import trimesh

        from synlab.schemas.runtime import Chart, MotherGeometry

        mesh = trimesh.creation.box(extents=list(extents))
        chart = Chart(name="default", surface_tags=("outer_wall",), kind="triplanar",
                      u_periodic=False, x_period_mm=None, area_mm2=float(mesh.area),
                      to_uv=lambda points: np.asarray(points, dtype=np.float64)[:, :2])
        return MotherGeometry(
            mesh=mesh, face_surface_tag=np.zeros(len(mesh.faces), dtype=np.int32),
            surface_tag_names={0: "outer_wall"}, charts=[chart], vessel_id="V_BOX",
            material_id="M_FIX", params={"extents": list(extents)}, mother_id="box14",
            meta={"fixture": True})


def main() -> int:
    from synlab.errors import SynLabError
    from synlab.fracture.api import _default_basis
    from synlab.fracture.morphology import build_morphology_cutter, prepare_morphology
    from synlab.fracture.spec import FractureSpec
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    import fixtures  # noqa: F401  (kept for parity with the test fixture)
    mother = box_mother((14.0, 14.0, 14.0))
    profile = build_material_profile("M01", default_material_params("M01"),
                                     make_rng(20261001, "morphology_test", "materials", "M01"))
    rng = make_rng(20261001, "morphology_test", "fracture", "FIX14", "M01")
    basis = _default_basis(mother, rng, FractureSpec())
    out: dict = {}
    try:
        prepared = prepare_morphology(mother, material_profile=profile, rng=rng, basis=basis,
                                      event_id="dbg", error_budget_mm=0.01, max_cells=400_000)
        cutter, field, params, report = build_morphology_cutter(
            mother, rng=rng, prepared=prepared, basis=basis, event_id="dbg",
            error_budget_mm=0.01, max_cells=400_000)
        out["status"] = "OK"
        out["triangles"] = int(cutter.triangles)
        out["cells"] = int(report.get("cells", 0))
    except SynLabError as exc:
        out["status"] = "SYNLAB_ERROR"
        out["code"] = exc.code.value
        out["stage"] = exc.stage
        out["message"] = str(exc)
        out["measurements"] = {k: (v if not isinstance(v, np.ndarray) else v.tolist())
                               for k, v in (exc.measurements or {}).items()}
    except BaseException as exc:  # noqa: BLE001
        out["status"] = "ERROR"
        out["message"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc()[-2000:]
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
