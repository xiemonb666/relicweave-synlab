"""Analytic mother fixtures for the fracture / truth / relations tests.

``synlab.mothers.api.create_mother`` is being built in parallel.  These fixtures are the
documented fallback: a closed box (in two resolutions) and a thin-walled bowl with a real
wall thickness and an inner cavity.  They are *not* a re-implementation of the mother
generator - they exist so the fracture contract can be tested without it, and every test
records which source it used.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import trimesh

from synlab.schemas.runtime import Chart, MotherGeometry

OUTER_WALL = 0
INNER_WALL = 1
RIM = 2
BASE = 3
ATTACHMENT = 4

TAG_NAMES = {OUTER_WALL: "outer_wall", INNER_WALL: "inner_wall", RIM: "rim", BASE: "base",
             ATTACHMENT: "attachment"}


def _wrap(mesh: trimesh.Trimesh, *, mother_id: str, vessel_id: str, material_id: str,
          params: dict[str, Any], tag_of_face: np.ndarray) -> MotherGeometry:
    mesh = trimesh.Trimesh(vertices=np.asarray(mesh.vertices, dtype=np.float64),
                           faces=np.asarray(mesh.faces, dtype=np.int64), process=False)
    chart = Chart(
        name="default", surface_tags=tuple(sorted(TAG_NAMES)), kind="triplanar",
        u_periodic=False, x_period_mm=None, area_mm2=float(mesh.area),
        to_uv=lambda points: np.asarray(points, dtype=np.float64)[:, :2],
    )
    return MotherGeometry(
        mesh=mesh,
        face_surface_tag=np.asarray(tag_of_face, dtype=np.int32),
        surface_tag_names=dict(TAG_NAMES),
        charts=[chart],
        vessel_id=vessel_id,
        material_id=material_id,
        params=dict(params),
        mother_id=mother_id,
        meta={"fixture": True},
    )


def mother_from_mesh(mesh: trimesh.Trimesh, *, mother_id: str = "fixture",
                     vessel_id: str = "V_FIX", material_id: str = "M_FIX",
                     params: dict[str, Any] | None = None,
                     tag_of_face: np.ndarray | None = None) -> MotherGeometry:
    if tag_of_face is None:
        tag_of_face = np.zeros(len(mesh.faces), dtype=np.int32)
    return _wrap(mesh, mother_id=mother_id, vessel_id=vessel_id, material_id=material_id,
                 params=params or {}, tag_of_face=np.asarray(tag_of_face))


def box_mother(extents: tuple[float, float, float] = (20.0, 20.0, 20.0), *,
               mother_id: str = "box20", material_id: str = "M_FIX",
               center: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> MotherGeometry:
    """Axis-aligned closed box; every face is tagged ``outer_wall``."""
    mesh = trimesh.creation.box(extents=list(extents))
    mesh.apply_translation(np.asarray(center, dtype=np.float64))
    tag = np.full(len(mesh.faces), OUTER_WALL, dtype=np.int32)
    normal = np.asarray(mesh.face_normals, dtype=np.float64)
    tag[np.abs(normal[:, 2]) > 0.5] = BASE
    return mother_from_mesh(mesh, mother_id=mother_id, vessel_id="V_BOX",
                            material_id=material_id, params={"extents": list(extents),
                                                             "fixture": "box"},
                            tag_of_face=tag)


def thin_bowl_mother(*, outer_radius_mm: float = 12.0, height_mm: float = 16.0,
                     wall_mm: float = 1.2, base_thickness_mm: float = 2.0,
                     sections: int = 48, mother_id: str = "bowl_thin",
                     material_id: str = "M_FIX") -> MotherGeometry:
    """Thin-walled open bowl (outer shell minus an inner cavity), watertight."""
    outer = trimesh.creation.cone(radius=outer_radius_mm, height=height_mm, sections=sections)
    outer.apply_translation([0.0, 0.0, height_mm / 2.0])
    outer = _cap_cone(outer, outer_radius_mm, height_mm)
    inner_radius = outer_radius_mm - wall_mm
    inner_height = height_mm - base_thickness_mm
    inner = trimesh.creation.cone(radius=inner_radius, height=inner_height, sections=sections)
    inner.apply_translation([0.0, 0.0, base_thickness_mm + inner_height / 2.0])
    inner = _cap_cone(inner, inner_radius, inner_height)
    inner.apply_translation([0.0, 0.0, 0.4])  # cut the cavity open through the rim
    shell = trimesh.boolean.difference([outer, inner], engine="manifold")
    if not bool(shell.is_watertight):
        raise RuntimeError("thin_bowl_mother fixture is not watertight")
    tag = np.full(len(shell.faces), OUTER_WALL, dtype=np.int32)
    normals = np.asarray(shell.face_normals, dtype=np.float64)
    centers = np.asarray(shell.triangles_center, dtype=np.float64)
    radial = np.hypot(centers[:, 0], centers[:, 1])
    facing_out = (normals[:, 0] * centers[:, 0] + normals[:, 1] * centers[:, 1]) > 0
    tag[(radial > 1e-6) & (~facing_out)] = INNER_WALL
    tag[np.abs(normals[:, 2] - 1.0) < 1e-6] = RIM
    tag[np.abs(normals[:, 2] + 1.0) < 1e-6] = BASE
    return mother_from_mesh(shell, mother_id=mother_id, vessel_id="V_BOWL",
                            material_id=material_id,
                            params={"outer_radius_mm": outer_radius_mm,
                                    "height_mm": height_mm, "wall_mm": wall_mm,
                                    "base_thickness_mm": base_thickness_mm,
                                    "fixture": "thin_bowl"},
                            tag_of_face=tag)


def _cap_cone(cone: trimesh.Trimesh, radius: float, height: float) -> trimesh.Trimesh:
    """Close a trimesh cone along +Z (its base sits at z = 0 in local coordinates)."""
    from trimesh.creation import triangulate_polygon
    from shapely.geometry import Point

    disc = Point(0.0, 0.0).buffer(radius, resolution=32)
    vertices, faces = triangulate_polygon(disc)
    cap = trimesh.Trimesh(vertices=np.column_stack([vertices[:, 0], vertices[:, 1],
                                                    np.full(vertices.shape[0], height)]),
                          faces=faces, process=False)
    cap.fix_normals()
    return trimesh.util.concatenate([cone, cap])


def two_block_mother(extents: tuple[float, float, float] = (20.0, 20.0, 20.0), *,
                     mother_id: str = "box20") -> tuple[MotherGeometry, np.ndarray, np.ndarray]:
    """Box plus the analytic plane that splits it in two equal halves along +X."""
    mother = box_mother(extents, mother_id=mother_id)
    point = np.array([0.0, 0.0, 0.0])
    normal = np.array([1.0, 0.0, 0.0])
    return mother, point, normal


def try_real_mother(vessel_id: str = "V01", material_id: str = "M01", seed: int = 7
                    ) -> tuple[MotherGeometry | None, str]:
    """Use the real mother generator when it is available; report which source was used."""
    try:
        from synlab.mothers.api import create_mother  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on parallel development
        return None, f"synlab.mothers.api unavailable ({type(exc).__name__}: {exc})"
    try:
        from synlab.seeds import make_rng

        mother = create_mother(vessel_id, material_id, {}, make_rng(seed, "shape"),
                               mother_id=f"{vessel_id}-{material_id}-{seed}")
        return mother, "synlab.mothers.api.create_mother"
    except Exception as exc:  # pragma: no cover
        return None, f"create_mother failed ({type(exc).__name__}: {exc})"
