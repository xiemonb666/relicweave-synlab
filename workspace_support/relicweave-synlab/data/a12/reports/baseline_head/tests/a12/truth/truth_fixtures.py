"""Hand-computable fracture/truth fixtures: 2/3/4-block events with known relations.

These fixtures are *analytic*: axis-aligned boxes cut along planes, so every shared area,
normal and relation kind can be computed by hand (plan A08: "手工已知2/3/4块 fixture 全R2
完全匹配").  They do not use the fracture backend at all — they feed ``synlab.truth.api``
directly, which is what makes them an independent check of the relation rules.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.schemas.runtime import (  # noqa: E402
    ORIGIN_AMBIGUOUS,
    ORIGIN_INTERFACE,
    ORIGIN_MOTHER_SURFACE,
    FractureResult,
    Fragment,
    InterfacePatch,
)

CUT = ORIGIN_INTERFACE        # 1: origin_kind code for a cut (new fracture) face
BODY = ORIGIN_MOTHER_SURFACE  # 0: origin_kind code for the original mother surface


@dataclass
class Block:
    """One box-shaped fragment of a hand-built event."""

    fragment_id: str
    bounds: tuple[float, float, float, float, float, float]  # x0,x1,y0,y1,z0,z1
    side: int = 1


@dataclass
class _Event:
    """Minimal stand-in for ``FractureResult`` (only the fields truth reads)."""

    fragments: list[Fragment]
    interfaces: list[InterfacePatch]
    event_tree: dict[str, Any]
    debris: list[Fragment]
    parent_id: str
    backend: str
    qa: dict[str, Any]
    cutter_ref: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def _box(bounds: tuple[float, float, float, float, float, float]) -> trimesh.Trimesh:
    x0, x1, y0, y1, z0, z1 = bounds
    mesh = trimesh.creation.box(extents=[x1 - x0, y1 - y0, z1 - z0])
    mesh.apply_translation([(x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0])
    return mesh


def _mother_of(blocks: list[Block]) -> Any:
    """The mother solid of a block event: the union of the blocks (CSG, real material).

    A shared *cut* plane is interior to this solid, while a face that merely faces a cavity or
    the open air stays on its boundary — which is exactly what the truth rules test.
    """

    class _Mother:
        def __init__(self, mesh: trimesh.Trimesh) -> None:
            self.mesh = mesh
            self.mother_id = "fixture_mother"

    parts = [_box(block.bounds) for block in blocks]
    try:
        mesh = trimesh.boolean.union(parts, engine="manifold")
    except BaseException:  # noqa: BLE001 - fall back to a concatenation (still closed shells)
        mesh = trimesh.util.concatenate(parts)
    return _Mother(trimesh.Trimesh(vertices=np.asarray(mesh.vertices, dtype=np.float64),
                                   faces=np.asarray(mesh.faces, dtype=np.int64), process=False))


def _fragment(block: Block, cut_planes: list[float], *, axis: int = 0) -> Fragment:
    mesh = _box(block.bounds)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    centres = np.asarray(mesh.triangles_center, dtype=np.float64)
    origin = np.full(len(mesh.faces), BODY, dtype=np.uint8)
    for plane in cut_planes:
        on_plane = np.abs(centres[:, axis] - plane) < 1.0e-9
        origin[on_plane] = CUT
    source = np.arange(len(mesh.faces), dtype=np.int32)
    return Fragment(
        fragment_id=block.fragment_id, mesh=mesh, volume_mm3=float(abs(mesh.volume)),
        area_mm2=float(mesh.area), face_origin_kind=origin, face_source_tri=source,
        face_interface_id=np.full(len(mesh.faces), -1, dtype=np.int32),
        face_side=np.full(len(mesh.faces), int(block.side), dtype=np.int8), component_id=0,
        is_tiny=False, parent_id="fixture_event",
        meta={"mesh_hash": block.fragment_id},
    )


def _patch(interface_id: int, first: Fragment, second: Fragment, plane: float, *,
           area: float, normal_sign: float = 1.0, ambiguous: bool = False,
           gap_mm: float = 0.0, normal_angle_deg: float = 0.0,
           sample_margin: float = 6.0, n: int = 8, origin_kind: int = CUT,
           source_triangles: list[int] | None = None,
           inward_axis: int = 0) -> InterfacePatch:
    """A planar interface patch on ``x = plane`` between two axis-aligned blocks."""
    grid = np.linspace(-10.0 + sample_margin, 10.0 - sample_margin, n)
    yy, zz = np.meshgrid(grid, grid, indexing="ij")
    points = np.column_stack([np.full(yy.size, plane), yy.reshape(-1), zz.reshape(-1)])
    normal_a = np.zeros_like(points)
    normal_a[:, inward_axis] = float(normal_sign)
    normal_b = -normal_a
    faces_a = np.nonzero(np.asarray(first.face_origin_kind) == origin_kind)[0]
    faces_b = np.nonzero(np.asarray(second.face_origin_kind) == origin_kind)[0]
    return InterfacePatch(
        interface_id=interface_id, fragment_a=first.fragment_id, fragment_b=second.fragment_id,
        area_mm2=float(area), sample_points_a=points, sample_points_b=points.copy(),
        normals_a=normal_a, normals_b=normal_b, gap_p95_mm=float(gap_mm),
        normal_angle_p95_deg=float(normal_angle_deg),
        ambiguity_area_ratio=(1.0 if ambiguous else 0.0),
        ambiguous_area_mm2=(float(area) if ambiguous else 0.0),
        meta={"source_triangles": list(source_triangles if source_triangles is not None else [0]),
              "faces_a": [int(x) for x in faces_a], "faces_b": [int(x) for x in faces_b],
              "weights_mm2": np.full(points.shape[0], float(area) / points.shape[0]),
              "empty_patch": False},
    )


def two_block_event(*, plane: float = 0.0, area: float = 400.0) -> tuple[Any, _Event]:
    """Two 20×20×10 blocks sharing the plane ``x = plane``: exactly one R2 relation."""
    blocks = [Block("A", (plane - 10.0, plane, -10.0, 10.0, -10.0, 10.0), side=-1),
              Block("B", (plane, plane + 10.0, -10.0, 10.0, -10.0, 10.0), side=+1)]
    fragments = [_fragment(block, [plane]) for block in blocks]
    patch = _patch(0, fragments[0], fragments[1], plane, area=area)
    return _mother_of(blocks), _Event(fragments=fragments, interfaces=[patch],
                                      event_tree={"event_id": "fixture_E01"},
                                      debris=[], parent_id="fixture_mother", backend="fixture",
                                      qa={"passed": True})


def three_block_event() -> tuple[Any, _Event]:
    """Three blocks in a row (A|B|C): R2 between neighbours, R1 between the outer two."""
    blocks = [Block("A", (-30.0, -10.0, -10.0, 10.0, -10.0, 10.0), side=-1),
              Block("B", (-10.0, 10.0, -10.0, 10.0, -10.0, 10.0), side=-1),
              Block("C", (10.0, 30.0, -10.0, 10.0, -10.0, 10.0), side=+1)]
    fragments = [_fragment(block, [-10.0, 10.0]) for block in blocks]
    patches = [_patch(0, fragments[0], fragments[1], -10.0, area=400.0),
               _patch(1, fragments[1], fragments[2], 10.0, area=400.0)]
    return _mother_of(blocks), _Event(fragments=fragments, interfaces=patches,
                                      event_tree={"event_id": "fixture_E02"},
                                      debris=[], parent_id="fixture_mother", backend="fixture",
                                      qa={"passed": True})


def four_block_event() -> tuple[Any, _Event]:
    """Four blocks: a 2×2 grid, three cut planes, R2 only across real shared faces."""
    blocks = [Block("A", (-20.0, 0.0, -20.0, 0.0, -10.0, 10.0), side=-1),
              Block("B", (0.0, 20.0, -20.0, 0.0, -10.0, 10.0), side=-1),
              Block("C", (-20.0, 0.0, 0.0, 20.0, -10.0, 10.0), side=+1),
              Block("D", (0.0, 20.0, 0.0, 20.0, -10.0, 10.0), side=+1)]
    fragments = [_fragment(block, [0.0]) for block in blocks]
    patches = [
        _patch(0, fragments[0], fragments[1], 0.0, area=400.0),      # A|B
        _patch(1, fragments[2], fragments[3], 0.0, area=400.0),      # C|D
    ]
    patches.append(_y_patch(2, fragments[0], fragments[2], 0.0, area=400.0,
                            x_range=(-18.0, -2.0)))                  # A|C
    patches.append(_y_patch(3, fragments[1], fragments[3], 0.0, area=400.0,
                            x_range=(2.0, 18.0)))                    # B|D
    return _mother_of(blocks), _Event(fragments=fragments, interfaces=patches,
                                      event_tree={"event_id": "fixture_E03"},
                                      debris=[], parent_id="fixture_mother", backend="fixture",
                                      qa={"passed": True})


def _y_patch(interface_id: int, first: Fragment, second: Fragment, plane: float, *,
             area: float, x_range: tuple[float, float]) -> InterfacePatch:
    """A patch on ``y = plane`` that stays strictly inside ``x_range`` (both blocks)."""
    grid_x = np.linspace(float(x_range[0]), float(x_range[1]), 8)
    grid_z = np.linspace(-8.0, 8.0, 8)
    xx, zz = np.meshgrid(grid_x, grid_z, indexing="ij")
    points = np.column_stack([xx.reshape(-1), np.full(xx.size, plane), zz.reshape(-1)])
    normal_a = np.zeros_like(points)
    normal_a[:, 1] = 1.0
    faces_a = np.nonzero(np.asarray(first.face_origin_kind) == CUT)[0]
    faces_b = np.nonzero(np.asarray(second.face_origin_kind) == CUT)[0]
    return InterfacePatch(
        interface_id=interface_id, fragment_a=first.fragment_id, fragment_b=second.fragment_id,
        area_mm2=float(area), sample_points_a=points, sample_points_b=points.copy(),
        normals_a=normal_a, normals_b=-normal_a, gap_p95_mm=0.0, normal_angle_p95_deg=0.0,
        ambiguity_area_ratio=0.0, ambiguous_area_mm2=0.0,
        meta={"source_triangles": [0], "faces_a": [int(x) for x in faces_a],
              "faces_b": [int(x) for x in faces_b],
              "weights_mm2": np.full(points.shape[0], float(area) / points.shape[0]),
              "empty_patch": False},
    )


def cavity_adjacency_event() -> tuple[Any, _Event]:
    """Two blocks facing each other across an air gap: the shared surface is *not* interior.

    The patch has a measured area but its faces lie on the boundary of the real material (they
    face the cavity), so plan 11.1 forbids R2: the relation must come out UNKNOWN with
    ``loss_mask=False``.
    """
    blocks = [Block("A", (-20.0, -12.0, -10.0, 10.0, -10.0, 10.0), side=-1),
              Block("B", (12.0, 20.0, -10.0, 10.0, -10.0, 10.0), side=+1)]
    fragments = [_fragment(block, []) for block in blocks]
    patch = _patch(0, fragments[0], fragments[1], -12.0, area=400.0)
    # the interface is on the *outer* faces of A/B, which no mother material backs
    return _mother_of(blocks), _Event(fragments=fragments, interfaces=[patch],
                                      event_tree={"event_id": "fixture_E04"}, debris=[],
                                      parent_id="fixture_mother", backend="fixture",
                                      qa={"passed": True})


def assembly_contact_event() -> tuple[Any, _Event]:
    """Two blocks touching along their original (non-cut) surfaces: never R2."""
    blocks = [Block("A", (-20.0, 0.0, -10.0, 10.0, -10.0, 10.0), side=-1),
              Block("B", (0.0, 20.0, -10.0, 10.0, -10.0, 10.0), side=+1)]
    fragments = [_fragment(block, []) for block in blocks]  # no cut faces at all
    patch = _patch(0, fragments[0], fragments[1], 0.0, area=400.0, origin_kind=BODY)
    return _mother_of(blocks), _Event(fragments=fragments, interfaces=[patch],
                                      event_tree={"event_id": "fixture_E05"}, debris=[],
                                      parent_id="fixture_mother", backend="fixture",
                                      qa={"passed": True})


def point_contact_event() -> tuple[Any, _Event]:
    """Two blocks whose shared area sits in the numerical grey zone: TINY_CONTACT."""
    blocks = [Block("A", (-20.0, 0.0, -10.0, 10.0, -10.0, 10.0), side=-1),
              Block("B", (0.0, 20.0, -10.0, 10.0, -10.0, 10.0), side=+1)]
    fragments = [_fragment(block, [0.0]) for block in blocks]
    patch = _patch(0, fragments[0], fragments[1], 0.0, area=0.02)
    return _mother_of(blocks), _Event(fragments=fragments, interfaces=[patch],
                                      event_tree={"event_id": "fixture_E06"}, debris=[],
                                      parent_id="fixture_mother", backend="fixture",
                                      qa={"passed": True})


def ambiguous_event() -> tuple[Any, _Event]:
    """A patch with genuine area but no unique source: UNKNOWN, ``loss_mask=False``."""
    blocks = [Block("A", (-20.0, 0.0, -10.0, 10.0, -10.0, 10.0), side=-1),
              Block("B", (0.0, 20.0, -10.0, 10.0, -10.0, 10.0), side=+1)]
    fragments = [_fragment(block, [0.0]) for block in blocks]
    patch = _patch(0, fragments[0], fragments[1], 0.0, area=400.0, ambiguous=True,
                   source_triangles=[])
    return _mother_of(blocks), _Event(fragments=fragments, interfaces=[patch],
                                      event_tree={"event_id": "fixture_E07"}, debris=[],
                                      parent_id="fixture_mother", backend="fixture",
                                      qa={"passed": True})


def correspondence_rows(first: Fragment, second: Fragment, plane: float, *,
                        n: int = 12, residual_mm: float = 0.0,
                        ambiguous: bool = False) -> list[dict[str, Any]]:
    """Barycentric correspondence rows on the shared plane (as ``event.py`` emits them)."""
    grid = np.linspace(-8.0, 8.0, n)
    rows: list[dict[str, Any]] = []
    for y in grid:
        for z in grid:
            point = np.array([plane, float(y), float(z)])
            rows.append({
                "interface_id": 0, "fragment_a": first.fragment_id,
                "fragment_b": second.fragment_id, "point_a_mm": point.copy(),
                "point_b_mm": point.copy(), "face_a": 0, "face_b": 0,
                "bary_a": np.array([1.0, 0.0, 0.0]), "bary_b": np.array([1.0, 0.0, 0.0]),
                "source_tri": 0, "ambiguous": bool(ambiguous), "residual_mm": float(residual_mm),
            })
    return rows


def event_with_correspondence(*, residual_mm: float = 0.0,
                              ambiguous: bool = False) -> tuple[Any, _Event]:
    mother, event = two_block_event()
    event.meta["correspondence"] = correspondence_rows(event.fragments[0], event.fragments[1],
                                                       0.0, residual_mm=residual_mm,
                                                       ambiguous=ambiguous)
    return mother, event


__all__ = [
    "Block", "CUT", "BODY", "two_block_event", "three_block_event", "four_block_event",
    "cavity_adjacency_event", "assembly_contact_event", "point_contact_event",
    "ambiguous_event", "correspondence_rows", "event_with_correspondence",
]
