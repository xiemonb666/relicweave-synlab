"""Class-3 root-cause probe: are the "fragments without interface faces" really solid bodies?

It rebuilds the failing lineage's mother with the parameters the batch really used, then
reports, for the mother and for every fracture output component:

  * face count, mesh-component count, volume, watertightness,
  * whether the component is *contained inside* another component (a void boundary),
  * the origin_kind / interface_id histogram,
  * the distance from the component's faces to the nearest interface face of the event
    (a component that really carries no new surface is far from every cut face).

Nothing is written to the store.  Cost: one mother build + one fracture (~20 s).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

from synlab.config import load_generation_spec  # noqa: E402
from synlab.fracture.api import fracture_event  # noqa: E402
from synlab.fracture.fragment import split_components  # noqa: E402
from synlab.mothers.api import create_mother  # noqa: E402
from synlab.schemas.runtime import ORIGIN_INTERFACE, ORIGIN_MOTHER_SURFACE  # noqa: E402
from synlab.seeds import derive_named_rngs  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

LIN = "LIN0004_V10_M06_PAT03"
MOTHER_ASSET = "asset_d6a31345d892ead78e4e"
SPEC = ROOT / "configs" / "a12" / "next_experiment.yaml"


def histogram(values: np.ndarray) -> dict[str, int]:
    values = np.asarray(values)
    uniq, counts = np.unique(values, return_counts=True)
    return {str(int(u)): int(c) for u, c in zip(uniq, counts)}


def component_report(label: str, mesh: trimesh.Trimesh, others: list[trimesh.Trimesh]) -> None:
    print(f"    {label}: faces={len(mesh.faces)} vol={abs(float(mesh.volume)):.1f} "
          f"area={float(mesh.area):.1f} watertight={bool(mesh.is_watertight)} "
          f"winding_ok={bool(mesh.is_winding_consistent)}")
    point = np.asarray(mesh.vertices, dtype=np.float64)[0] + 1e-6 * np.asarray(
        mesh.face_normals[0], dtype=np.float64)
    for index, other in enumerate(others):
        if other is mesh:
            continue
        if not bool(other.is_watertight):
            continue
        try:
            inside = bool(other.contains(point.reshape(1, 3))[0])
        except Exception as exc:  # pragma: no cover - defensive
            print(f"        containment vs #{index} failed: {type(exc).__name__}: {exc}")
            continue
        if inside:
            print(f"        CONTAINED INSIDE component #{index} "
                  f"(faces={len(other.faces)}, vol={abs(float(other.volume)):.1f})")


def main() -> int:
    store = AssetStore(ROOT / "data" / "a12")
    record = store.get_asset(MOTHER_ASSET)
    params = dict(record.meta.get("params") or {})
    vessel = str(record.meta.get("vessel_id"))
    material = str(record.meta.get("material_id"))
    spec = load_generation_spec(SPEC)
    rngs = derive_named_rngs(spec.master_seed, LIN)
    mother = create_mother(vessel, material, params, rngs["shape"], mother_id=LIN)
    print(f"mother {vessel}/{material}: faces={len(mother.mesh.faces)} "
          f"verts={len(mother.mesh.vertices)} watertight={bool(mother.mesh.is_watertight)} "
          f"vol={float(mother.mesh.volume):.1f}")
    print(f"  charts={[(c.name, c.kind, c.x_period_mm) for c in mother.charts]}")
    print(f"  tags={histogram(np.asarray(mother.face_surface_tag))}")
    print("  MOTHER surface-connected components:")
    parts = split_components(mother.mesh)
    meshes = [p.mesh for p in parts]
    for index, part in enumerate(parts):
        component_report(f"#{index}", part.mesh, meshes)
        print(f"        bounds={np.round(np.asarray(part.mesh.bounds), 2).tolist()}")

    event_id = f"{LIN}_E01"
    fracture = fracture_event(mother, spec.fracture, rngs["cut"], event_id=event_id)
    print(f"\nfracture backend={fracture.backend} fragments={len(fracture.fragments)} "
          f"interfaces={len(fracture.interfaces)}")
    interface_centres = []
    for fragment in fracture.fragments:
        origin = np.asarray(fragment.face_origin_kind)
        ids = np.asarray(fragment.face_interface_id)
        if int(np.count_nonzero(origin == ORIGIN_INTERFACE)):
            interface_centres.append(np.asarray(fragment.mesh.triangles_center, dtype=np.float64)[
                origin == ORIGIN_INTERFACE])
    all_centres = np.vstack(interface_centres) if interface_centres else np.zeros((0, 3))
    print(f"  total interface faces across the event: {len(all_centres)}")
    for fragment in fracture.fragments:
        origin = np.asarray(fragment.face_origin_kind)
        ids = np.asarray(fragment.face_interface_id)
        centres = np.asarray(fragment.mesh.triangles_center, dtype=np.float64)
        nearest = float("nan")
        if len(all_centres) and len(centres):
            from scipy.spatial import cKDTree

            nearest = float(cKDTree(all_centres).query(centres, k=1)[0].min())
        print(f"  {fragment.fragment_id:44s} comp={fragment.component_id} "
              f"faces={len(fragment.mesh.faces)} vol={fragment.volume_mm3:.1f} "
              f"tiny={fragment.is_tiny} watertight={bool(fragment.mesh.is_watertight)} "
              f"side={int(np.asarray(fragment.face_side)[0])}")
        print(f"      origin_kind={histogram(origin)} (1=INTERFACE)")
        print(f"      interface_id>=0: {int(np.count_nonzero(ids >= 0))}  "
              f"min_centroid_distance_to_any_interface_face={nearest:.3f} mm")
    picked = max([f for f in fracture.fragments if not f.is_tiny] or list(fracture.fragments),
                 key=lambda f: float(f.volume_mm3))
    print(f"\n  pipeline would pick: {picked.fragment_id} "
          f"(vol={picked.volume_mm3:.1f}, interface faces="
          f"{int(np.count_nonzero(np.asarray(picked.face_origin_kind) == ORIGIN_INTERFACE))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

