"""Isolate the boolean cost on the implicit cutter: each CSG call is timed and flushed."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests" / "a12" / "fracture"))
OUT = REPO_ROOT / "data" / "a12_reports" / "implicit"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extent", type=float, default=12.0)
    ap.add_argument("--vessel", default="")
    ap.add_argument("--material", default="M01")
    ap.add_argument("--triangles", type=int, default=60000)
    ap.add_argument("--steps", default="cutter,manifold,intersection,difference")
    args = ap.parse_args()
    steps = set(args.steps.split(","))
    print(f"[start] vessel={args.vessel or 'box'} extent={args.extent} triangles={args.triangles}",
          flush=True)

    import fixtures as fx

    import trimesh

    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    if args.vessel:
        import json as _json

        from synlab.mothers.api import create_mother, load_mother
        from synlab.storage.store import AssetStore

        demo_root = REPO_ROOT / "data" / "a12_demo"
        manifest = _json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
        entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{args.vessel}")
        demo = load_mother(AssetStore(demo_root / "store"), str(entry["asset_id"]))
        mother = create_mother(args.vessel, args.material, dict(demo.params),
                               make_rng(20261001, "imp", "m"), mother_id="bool_probe")
    else:
        mother = fx.box_mother((args.extent,) * 3, mother_id="bool_probe")
    profile = build_material_profile(args.material, default_material_params(args.material),
                                     make_rng(20261001, "imp", "mat"))

    from synlab.fracture.implicit.backend import build_implicit_cutter

    t0 = time.time()
    cutter, field, params, report = build_implicit_cutter(
        mother, material_profile=profile, rng=make_rng(20261001, "imp", "build"),
        event_id="bool_probe", error_budget_mm=0.01,
        options={"max_sheet_triangles": int(args.triangles)})
    print(f"[cutter] {time.time() - t0:.1f}s faces={len(cutter.mesh.faces)} "
          f"watertight={cutter.mesh.is_watertight}", flush=True)

    from synlab.fracture.booleans import boolean_difference, boolean_intersection, tag_source

    source_mother = tag_source(trimesh.Trimesh(vertices=np.asarray(mother.mesh.vertices),
                                               faces=np.asarray(mother.mesh.faces), process=False),
                               1.0, "mother")
    source_cutter = tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                               faces=np.asarray(cutter.mesh.faces), process=False),
                               2.0, "cutter")
    if "manifold" in steps:
        from manifold3d import Manifold

        t0 = time.time()
        m = Manifold(mesh=__import__("manifold3d").Mesh(
            vert_properties=np.asarray(source_cutter.mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(source_cutter.mesh.faces, dtype=np.uint32)))
        print(f"[manifold] {time.time() - t0:.1f}s status={m.status()} "
              f"volume={m.volume():.3f} genus={m.genus()}", flush=True)
    if "intersection" in steps:
        t0 = time.time()
        result = boolean_intersection([source_mother, source_cutter], label="M_minus")
        print(f"[intersection] {time.time() - t0:.1f}s faces={len(result.mesh.faces)} "
              f"volume={abs(float(result.mesh.volume)):.4f} "
              f"watertight={bool(result.mesh.is_watertight)}", flush=True)
    if "difference" in steps:
        t0 = time.time()
        result = boolean_difference([source_mother, source_cutter], label="M_plus")
        print(f"[difference] {time.time() - t0:.1f}s faces={len(result.mesh.faces)} "
              f"volume={abs(float(result.mesh.volume)):.4f} "
              f"watertight={bool(result.mesh.is_watertight)}", flush=True)
    if "resolve" in steps:
        from synlab.fracture.event import _cut_both_sides
        from synlab.fracture.booleans import SourceResolver

        t0 = time.time()
        minus, plus = _cut_both_sides(source_mother, source_cutter)
        print(f"[cut_both] {time.time() - t0:.1f}s minus={minus.n_faces} plus={plus.n_faces}",
              flush=True)
        t0 = time.time()
        resolver = SourceResolver([source_mother, source_cutter], tolerance_mm=1.0e-4)
        for name, side in (("M_minus", minus), ("M_plus", plus)):
            classification = resolver.classify(side, container=cutter.mesh,
                                               container_tolerance_mm=1.0e-4)
            print(f"[resolve:{name}] {time.time() - t0:.1f}s keys={sorted(classification)[:8]}",
                  flush=True)
    if "full" in steps:
        from synlab.fracture.event import run_shared_cut

        t0 = time.time()
        result = run_shared_cut(mother, cutter, event_id="bool_probe",
                                backend="implicit_sheet_cut")
        print(f"[full] {time.time() - t0:.1f}s fragments={len(result.fragments)} "
              f"interfaces={len(result.interfaces)} "
              f"volumes={[round(float(f.volume_mm3), 3) for f in result.fragments]}", flush=True)
    (OUT / "boolean_probe.json").write_text(json.dumps(
        {"faces": int(len(cutter.mesh.faces)), "steps": sorted(steps)}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
