"""Shared vessel assembly pipeline (plan 7.1 / 7.2).

Every vessel builder prepares one or more watertight *parts* (body, foot, handle, ear,
spout, lid, ...), each carrying its own face tags, and then calls :func:`build_vessel`.
The pipeline is identical for all 24 registry entries:

1. boolean-union the parts with Manifold (or concatenate them when the plan requires
   independent pre-break components, e.g. a lid);
2. recover face tags and component ids by nearest pre-boolean triangle;
3. apply the low-amplitude non-axisymmetric warp to the *assembled* solid, so inner and
   outer walls move together and the thickness stays a measured quantity;
4. freeze the charts and the QA bookkeeping.

Boolean kernels do not preserve face provenance, so tag recovery is explicit here and its
ambiguity is reported (``ambiguous_area_mm2``) rather than assumed to be zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np
import trimesh

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import Chart
from .geometry import LabelledPolyline, ShellProfile, sections_for_chord_error
from .solids import boolean_union, concatenate, health
from .tagging import (TAG_NAMES, attach_face_semantics, inherit_components, inherit_tags,
                      tag_by_polyline, tag_index)
from .warp import WarpSpec, apply_warp


@dataclass
class Part:
    """One closed solid entering the assembly, with its own face tags."""

    mesh: trimesh.Trimesh
    tags: np.ndarray
    component_id: int = 0
    name: str = "body"
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tags = np.asarray(self.tags, dtype=np.int32)
        if self.tags.shape[0] != len(self.mesh.faces):
            raise SynLabError(ErrorCode.MOTHER_INVALID,
                              f"part {self.name!r}: {self.tags.shape[0]} tags for "
                              f"{len(self.mesh.faces)} faces",
                              stage="mothers.assembly")


@dataclass
class VesselAssembly:
    mesh: trimesh.Trimesh
    surface_tag: np.ndarray
    component_id: np.ndarray
    charts: list[Chart]
    meta: dict[str, Any]
    requires_cavity: bool
    cavity_probe_points: np.ndarray


def constant_tags(mesh: trimesh.Trimesh, name: str) -> np.ndarray:
    return np.full(len(mesh.faces), tag_index(name), dtype=np.int32)


def revolve_body(profile: ShellProfile, *, chord_tol_mm: float | None = None,
                 min_sections: int = 48, max_sections: int = 256,
                 sections: int | None = None) -> Part:
    """Revolve a thick profile and tag the faces from the labelled construction poly-line.

    ``chord_tol_mm`` defaults to a fraction of the profile radius: the plan's acceptance is a
    chord error (step 5), and a fixed 0.06 mm on a 150 mm radius keeps a needlessly dense mesh,
    which turns the complete self-intersection scan into an all-pairs comparison.
    """
    tolerance = float(chord_tol_mm) if chord_tol_mm is not None else max(
        0.06, 0.004 * float(profile.r_max))
    if sections is None:
        sections = sections_for_chord_error(profile.r_max, tolerance,
                                            minimum=min_sections, maximum=max_sections)
    mesh = trimesh.creation.revolve(profile.closed, sections=int(sections))
    mesh, cleanup_report = _cleanup(mesh)
    if not mesh.is_watertight:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "revolved body is not watertight",
                          stage="mothers.assembly.revolve",
                          measurements={"faces": int(len(mesh.faces)), "sections": int(sections)})
    tags, report = tag_by_polyline(mesh, profile.polyline, mode="revolve")
    report["sections"] = int(sections)
    report["chord_tol_mm"] = tolerance
    report["cleanup"] = cleanup_report
    report["profile_region_area_mm2"] = {}
    return Part(mesh=mesh, tags=tags, component_id=0, name="body", meta=report)


def _cleanup(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    from .solids import cleanup

    return cleanup(mesh)


def build_vessel(parts: Sequence[Part], *, union: bool = True,
                 warp: WarpSpec | None = None,
                 charts_fn: Callable[[trimesh.Trimesh, np.ndarray, dict[str, Any]],
                                     list[Chart]] | None = None,
                 construct: dict[str, Any] | None = None,
                 meta: dict[str, Any] | None = None,
                 requires_cavity: bool = False,
                 cavity_probe_points: np.ndarray | None = None,
                 design_thickness: tuple[float, float] = (float("nan"), float("nan")),
                 min_wall_mm: float = 0.8,
                 max_wall_mm: float = float("inf"),
                 ambiguity_mm: float = 0.35,
                 stage: str = "mothers.assembly") -> VesselAssembly:
    if not parts:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "assembly needs at least one part",
                          stage=stage)
    for part in parts:
        if not part.mesh.is_watertight:
            raise SynLabError(ErrorCode.MOTHER_INVALID,
                              f"part {part.name!r} is not watertight before assembly",
                              stage=stage,
                              measurements={"faces": int(len(part.mesh.faces))})
    assembly_meta: dict[str, Any] = {
        "parts": [{"name": p.name, "component_id": int(p.component_id),
                   "faces": int(len(p.mesh.faces)), "volume_mm3": float(p.mesh.volume)}
                  for p in parts],
        "boolean": "manifold_union" if union else "none (independent pre-break components)",
    }
    if union and len(parts) > 1:
        source = concatenate([p.mesh for p in parts])
        source_tags = np.concatenate([p.tags for p in parts])
        source_comp = np.concatenate([np.full(len(p.mesh.faces), p.component_id, dtype=np.int32)
                                      for p in parts])
        mesh = boolean_union([p.mesh for p in parts])
        tags, tag_report = inherit_tags(mesh, source, source_tags, ambiguity_mm=ambiguity_mm)
        comp = inherit_components(mesh, source, source_comp)
        assembly_meta["tag_inheritance"] = tag_report
    else:
        mesh = concatenate([p.mesh for p in parts])
        tags = np.concatenate([p.tags for p in parts])
        comp = np.concatenate([np.full(len(p.mesh.faces), p.component_id, dtype=np.int32)
                               for p in parts])
        assembly_meta["tag_inheritance"] = {"mode": "direct concatenation (no boolean)"}
    pre_warp_health = health(mesh)
    if warp is not None:
        assembly_meta["warp"] = apply_warp(mesh, warp)
    else:
        assembly_meta["warp"] = {"applied": False, "mode": "identity"}
    mesh.metadata = dict(mesh.metadata or {})
    attach_face_semantics(mesh, surface_tag=tags, component_id=comp)

    extra_meta: dict[str, Any] = dict(meta or {})
    construct_spec = dict(construct or {})
    if charts_fn is not None:
        charts = charts_fn(mesh, tags, construct_spec)
    else:
        charts = []
    if not charts:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "vessel build produced no charts",
                          stage=stage)
    probes = np.asarray(cavity_probe_points if cavity_probe_points is not None
                        else np.zeros((0, 3)), dtype=np.float64).reshape(-1, 3)
    final_meta: dict[str, Any] = {
        **extra_meta,
        "construct": construct_spec,
        "assembly": assembly_meta,
        "pre_warp_health": {k: v for k, v in pre_warp_health.items() if k != "bounds_mm"},
        "requires_cavity": bool(requires_cavity),
        "cavity_probe_points_mm": probes.tolist(),
        "design_thickness_min_mm": float(design_thickness[0]),
        "design_thickness_max_mm": float(design_thickness[1]),
        "min_wall_mm": float(min_wall_mm),
        "max_wall_mm": float(max_wall_mm),
        "surface_tag_names": {int(k): v for k, v in TAG_NAMES.items()},
    }
    return VesselAssembly(mesh=mesh, surface_tag=np.asarray(tags, dtype=np.int32),
                          component_id=np.asarray(comp, dtype=np.int32), charts=charts,
                          meta=final_meta, requires_cavity=bool(requires_cavity),
                          cavity_probe_points=probes)


def cavity_probe_points(profile: ShellProfile, *, count: int = 6,
                        lateral_fraction: float = 0.35,
                        theta_rad: float = 0.7,
                        margin_mm: float = 2.5) -> np.ndarray:
    """Probe points that are provably inside the open cavity of a revolved shell (mm).

    A foot ring or a dished base makes the inner surface *multi-valued in r*: the inner
    floor rises from the wall towards the axis, so a probe placed from a single-valued
    radius table lands inside the material and fails a mother that is in fact hollow.

    The inner surface is therefore treated as a function ``z_floor(r)`` (the highest inner
    point in each radial bin) and every probe is placed at ``z = z_floor(r) + 2.5 mm``,
    strictly above the floor and strictly below the rim.  Points where that leaves no
    clearance are dropped; ``audit_mother`` still verifies them with an inside/outside
    test on the assembled (possibly warped, possibly boolean-joined) solid.
    """
    r_in = np.asarray(profile.r_in, dtype=np.float64)
    z_in = np.asarray(profile.z_in, dtype=np.float64)
    if r_in.size == 0:
        return np.zeros((0, 3), dtype=np.float64)
    r_max = float(np.max(r_in))
    margin = float(min(margin_mm, 0.3 * r_max))
    floor = _inner_floor_table(r_in, z_in)
    z_hi = float(profile.z_rim) - 0.25 * float(profile.thickness_min_mm)
    ring_count = int(max(count, 1))
    out: list[list[float]] = []
    for ring in range(1, ring_count + 1):
        radial = r_max * float(lateral_fraction) * float(ring) / float(ring_count)
        radial = max(radial, 0.25 * profile.thickness_min_mm)
        if radial > r_max - margin:
            radial = max(r_max - margin, 0.25 * profile.thickness_min_mm)
        z = float(np.interp(radial, floor[:, 0], floor[:, 1])) + margin
        if not np.isfinite(z) or z >= z_hi:
            continue
        out.append([radial * np.cos(theta_rad), radial * np.sin(theta_rad), z])
    return np.asarray(out, dtype=np.float64).reshape(-1, 3)


def _inner_floor_table(r_in: np.ndarray, z_in: np.ndarray, *, bins: int = 48) -> np.ndarray:
    """``(K,2)`` table of the cavity floor ``z_floor(r)``: the highest inner point per bin."""
    order = np.argsort(r_in, kind="stable")
    r_sorted = np.asarray(r_in, dtype=np.float64)[order]
    z_sorted = np.asarray(z_in, dtype=np.float64)[order]
    edges = np.linspace(0.0, float(r_sorted[-1]), int(max(bins, 4)) + 1)
    rows: list[list[float]] = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        sel = (r_sorted >= lo) & (r_sorted <= hi)
        if not np.any(sel):
            continue
        rows.append([0.5 * (lo + hi), float(np.max(z_sorted[sel]))])
    if not rows:
        return np.column_stack([[0.0], [float(np.max(z_in))]])
    table = np.asarray(rows, dtype=np.float64)
    # The floor may drop towards the wall, but only gradually: a sharper drop than
    # ``floor_safety`` of the axial floor is not trusted, so a probe can never end up below
    # the true floor near the base.  The result is still a real, z-varying probe band.
    floor_safety = 0.7
    peak = float(np.max(table[:, 1]))
    max_drop = 0.0
    for i in range(len(table)):
        max_drop = max(max_drop, peak - float(table[i, 1]))
        table[i, 1] = peak - floor_safety * max_drop
    return table


def profile_chart_payload(profile: ShellProfile) -> np.ndarray:
    """(P,3) ``[r, z, s]`` table used by the revolve chart and its store round-trip."""
    return np.column_stack([profile.polyline.points[:, 0], profile.polyline.points[:, 1],
                            profile.polyline.s_mm])


def profile_polyline_for_chart(profile: ShellProfile) -> LabelledPolyline:
    return profile.polyline
