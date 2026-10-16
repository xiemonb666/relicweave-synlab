"""Solid construction wrappers around trimesh / manifold3d (plan 2.4 [R1][R15]).

Every function here is a thin adapter over a reused kernel:

* ``trimesh.creation.revolve``      - surfaces of revolution from a closed half-profile
* ``trimesh.creation.extrude_polygon`` / ``sweep_polygon`` - extrusions and swept tubes
* ``trimesh.boolean.{union,difference,intersection}`` with ``engine="manifold"``
* ``manifold3d.Manifold``           - validity status, genus, ray casting

Nothing in this module invents kernel geometry; it only enforces the project contract
(watertight, outward-oriented, millimetre, face-attribute preserving).
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np
import trimesh
from shapely.geometry import Polygon

from ..errors import ErrorCode, SynLabError

MANIFOLD_ENGINE = "manifold"


def to_manifold(mesh: trimesh.Trimesh):
    """Convert to ``manifold3d.Manifold``; raises when the mesh is not a solid."""
    import manifold3d

    md = manifold3d.Manifold(manifold3d.Mesh(
        np.ascontiguousarray(np.asarray(mesh.vertices, dtype=np.float32)),
        np.ascontiguousarray(np.asarray(mesh.faces, dtype=np.uint32)),
    ))
    status = md.status()
    if str(status) != "Error.NoError" or md.is_empty():
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"manifold rejected the mesh: {status}",
                          stage="mothers.solids.to_manifold",
                          measurements={"faces": int(len(mesh.faces)),
                                        "watertight": bool(mesh.is_watertight)})
    return md


def manifold_status(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """Honest manifold report (used by ``audit_mother`` and by the PoC)."""
    import manifold3d

    md = manifold3d.Manifold(manifold3d.Mesh(
        np.ascontiguousarray(np.asarray(mesh.vertices, dtype=np.float32)),
        np.ascontiguousarray(np.asarray(mesh.faces, dtype=np.uint32)),
    ))
    status = str(md.status())
    return {
        "status": status,
        "ok": status == "Error.NoError" and not md.is_empty(),
        "volume_mm3": float(md.volume()),
        "genus": int(md.genus()),
        "triangles": int(md.num_tri()),
    }


def cleanup(mesh: trimesh.Trimesh, *, merge_tol: float = 1e-8) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    """Drop exactly degenerate faces and unreferenced vertices, reporting the change.

    ``merge_vertices`` is only run on a mesh that is *not* already watertight.  On a closed
    solid it fuses the duplicate vertices that two coincident sub-solids contribute along a
    shared face, which turns the shared triangle pairs into non-manifold edges and destroys
    the watertightness the kernel just produced.  The merge is a repair step, never a
    refinement of an already valid solid - and losing watertightness here is reported instead
    of being silently passed on.
    """
    before = {"faces": int(len(mesh.faces)), "vertices": int(len(mesh.vertices)),
              "watertight": bool(mesh.is_watertight)}
    out = mesh.copy()
    merged = False
    if merge_tol > 0 and not before["watertight"]:
        out.merge_vertices()
        merged = True
    areas = np.asarray(out.area_faces, dtype=np.float64)
    bad = np.nonzero(areas <= 1e-12)[0]
    removed = int(bad.size)
    if removed:
        keep = np.setdiff1d(np.arange(len(out.faces)), bad, assume_unique=False)
        out.update_faces(keep)
    out.remove_unreferenced_vertices()
    after_watertight = bool(out.is_watertight)
    recovered = False
    if removed and before["watertight"] and not after_watertight:
        # Dropping exactly degenerate faces can open the mesh when a cutter crossed a surface
        # tangentially.  The repair is to weld the coincident vertices the kernel emitted at
        # that junction and drop the resulting slivers, which closes the loop again; the
        # result is re-checked below and a failure is still reported.
        welded = out.copy()
        welded.merge_vertices()
        areas2 = np.asarray(welded.area_faces, dtype=np.float64)
        welded.update_faces(welded.nondegenerate_faces())
        welded.remove_unreferenced_vertices()
        if bool(welded.is_watertight):
            out = welded
            after_watertight = True
            recovered = True
    report = {
        "faces_before": before["faces"],
        "vertices_before": before["vertices"],
        "watertight_before": before["watertight"],
        "merged_vertices": merged,
        "degenerate_faces_removed": removed,
        "degenerate_faces_recovery": recovered,
        "faces_after": int(len(out.faces)),
        "vertices_after": int(len(out.vertices)),
        "watertight_after": after_watertight,
    }
    if before["watertight"] and not after_watertight:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            "cleanup destroyed the watertightness of a closed solid (kernel regression)",
            stage="mothers.solids.cleanup",
            measurements=report,
        )
    return out, report


def combine_solids(meshes: Sequence[trimesh.Trimesh], *,
                   stage: str = "mothers.solids.combine") -> trimesh.Trimesh:
    """Union closed solids, falling back to a plain concatenation of disjoint bodies.

    Sub-solids that only *touch* (a lid skirt lapping a mouth, two rims meeting exactly) make
    the Manifold union produce a non-manifold junction.  Both operands are valid closed solids
    in that case, so the honest fallback is to keep them as separate bodies of one mesh - which
    is what the plan wants for independent pre-break components - instead of failing the
    mother.  The chosen route is returned in the mesh metadata.
    """
    if not meshes:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "combine_solids needs at least one mesh",
                          stage=stage)
    if len(meshes) == 1:
        return meshes[0]
    try:
        out = _boolean("union", list(meshes))
        out.metadata = dict(out.metadata or {})
        out.metadata["combine_route"] = "manifold_union"
        return out
    except SynLabError as exc:
        for mesh in meshes:
            if not mesh.is_watertight or float(mesh.volume) <= 0:
                raise
        out = concatenate(meshes)
        out.metadata = dict(out.metadata or {})
        out.metadata["combine_route"] = "concatenate (union rejected touching solids)"
        out.metadata["union_error"] = str(exc)
        return out


def _require(condition: bool, message: str, *, stage: str, measurements: dict[str, Any] | None = None) -> None:
    if not condition:
        raise SynLabError(ErrorCode.MOTHER_INVALID, message, stage=stage,
                          measurements=measurements or {})


def revolve_profile(closed_profile: np.ndarray, *, sections: int,
                    stage: str = "mothers.solids.revolve") -> trimesh.Trimesh:
    """Revolve a closed ``(r, z)`` half-profile into a watertight thick body."""
    prof = np.asarray(closed_profile, dtype=np.float64)
    _require(prof.ndim == 2 and prof.shape[1] == 2 and len(prof) >= 4,
             "revolve needs a closed (P,2) profile", stage=stage,
             measurements={"shape": list(prof.shape)})
    mesh = trimesh.creation.revolve(prof, sections=int(sections))
    mesh, _ = cleanup(mesh)
    _require(mesh.is_watertight, "revolved body is not watertight", stage=stage,
             measurements={"faces": int(len(mesh.faces)), "sections": int(sections)})
    _require(mesh.volume > 0, "revolved body has non-positive volume", stage=stage,
             measurements={"volume_mm3": float(mesh.volume)})
    return mesh


def extrude_polygon_solid(polygon: Polygon, height: float, *,
                          transform: np.ndarray | None = None,
                          stage: str = "mothers.solids.extrude") -> trimesh.Trimesh:
    """Extrude a (possibly holed) shapely polygon into a watertight prism."""
    _require(isinstance(polygon, Polygon) and polygon.is_valid and not polygon.is_empty,
             "extrude needs a valid non-empty shapely Polygon", stage=stage)
    _require(abs(float(height)) > 1e-6, "extrude height must be non-zero", stage=stage)
    mesh = trimesh.creation.extrude_polygon(polygon, height=float(abs(height)), transform=transform)
    mesh, _ = cleanup(mesh)
    _require(mesh.is_watertight, "extruded body is not watertight", stage=stage,
             measurements={"faces": int(len(mesh.faces)), "holes": int(len(polygon.interiors))})
    return mesh


def sweep_tube(polygon: Polygon, path: np.ndarray, *, cap: bool = True,
               stage: str = "mothers.solids.sweep") -> trimesh.Trimesh:
    """Sweep a (possibly holed) cross-section along a 3D path into a closed tube.

    A holed cross-section keeps an internal channel: that is how a thick spout keeps its
    bore (plan 7.2) instead of being a solid rod.
    """
    _require(isinstance(polygon, Polygon) and polygon.is_valid and not polygon.is_empty,
             "sweep needs a valid non-empty shapely Polygon", stage=stage)
    path = np.asarray(path, dtype=np.float64)
    _require(path.ndim == 2 and path.shape[1] == 3 and len(path) >= 3,
             "sweep path needs (K,3) with K>=3", stage=stage,
             measurements={"shape": list(path.shape)})
    mesh = trimesh.creation.sweep_polygon(polygon, path, cap=cap)
    mesh, _ = cleanup(mesh)
    _require(mesh.is_watertight, "swept body is not watertight (cap or path self-intersection)",
             stage=stage, measurements={"faces": int(len(mesh.faces)), "cap": bool(cap)})
    return mesh


def _boolean(op: str, meshes: Sequence[trimesh.Trimesh]) -> trimesh.Trimesh:
    if len(meshes) < 2:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"boolean {op} needs >=2 operands",
                          stage="mothers.solids.boolean")
    fn = {"union": trimesh.boolean.union,
          "difference": trimesh.boolean.difference,
          "intersection": trimesh.boolean.intersection}[op]
    try:
        out = fn(list(meshes), engine=MANIFOLD_ENGINE)
    except Exception as exc:  # pragma: no cover - kernel failure is reported, not hidden
        raise SynLabError(ErrorCode.DEPENDENCY_CAPABILITY_MISSING,
                          f"manifold boolean {op} failed: {type(exc).__name__}: {exc}",
                          stage="mothers.solids.boolean") from exc
    if out is None or len(out.faces) == 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"manifold boolean {op} produced an empty result",
                          stage="mothers.solids.boolean",
                          measurements={"operands": [int(len(m.faces)) for m in meshes]})
    out, _ = cleanup(out)
    return out


def boolean_union(meshes: Iterable[trimesh.Trimesh]) -> trimesh.Trimesh:
    return _boolean("union", list(meshes))


def boolean_difference(meshes: Iterable[trimesh.Trimesh]) -> trimesh.Trimesh:
    return _boolean("difference", list(meshes))


def boolean_intersection(meshes: Iterable[trimesh.Trimesh]) -> trimesh.Trimesh:
    return _boolean("intersection", list(meshes))


def concatenate(meshes: Sequence[trimesh.Trimesh]) -> trimesh.Trimesh:
    """Concatenate disjoint solids (used for pre-break components such as a lid)."""
    if not meshes:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "cannot concatenate zero meshes",
                          stage="mothers.solids.concatenate")
    out = trimesh.util.concatenate([m.copy() for m in meshes])
    out.metadata = {}
    return out


def face_centroids_and_normals(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(mesh.triangles_center, dtype=np.float64), \
        np.asarray(mesh.face_normals, dtype=np.float64)


def health(mesh: trimesh.Trimesh) -> dict[str, Any]:
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    return {
        "faces": int(len(mesh.faces)),
        "vertices": int(len(mesh.vertices)),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "volume_mm3": float(mesh.volume),
        "area_mm2": float(mesh.area),
        "bodies": int(mesh.body_count),
        "degenerate_faces": int(np.sum(areas <= 1e-12)),
        "euler_number": int(mesh.euler_number),
        "bounds_mm": np.asarray(mesh.bounds, dtype=np.float64),
    }
