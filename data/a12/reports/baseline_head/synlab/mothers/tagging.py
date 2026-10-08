"""Face-level surface semantics (plan 7.1 step 7, contract in ``docs/a12/interfaces.md``).

The frozen vocabulary lives in ``synlab.schemas.runtime.SurfaceTag``; this module fixes the
integer encoding used by ``MotherGeometry.face_surface_tag`` and provides the two tagging
routes used by the vessel builders:

* ``tag_by_polyline`` - project each face centroid onto the *labelled construction
  poly-line* (the very curve the body was revolved/extruded from), which is exact away
  from region junctions;
* ``inherit_tags``   - carry tags and pre-break component ids across a Manifold boolean by
  nearest-neighbour lookup on the pre-boolean triangles, because booleans do not preserve
  face provenance.  The lookup ambiguity area is measured and reported, never hidden.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from ..errors import ErrorCode, SynLabError
from .geometry import LabelledPolyline

#: Authoritative integer encoding of ``synlab.schemas.runtime.SurfaceTag``.
TAG_ORDER: tuple[str, ...] = (
    "outer_wall", "inner_wall", "rim", "foot", "base", "attachment", "interface",
)
TAG_INDEX: dict[str, int] = {name: i for i, name in enumerate(TAG_ORDER)}
TAG_NAMES: dict[int, str] = {i: name for i, name in enumerate(TAG_ORDER)}
#: 0 is reserved for "unassigned"; production faces never keep this value.
TAG_UNASSIGNED = -1


def tag_index(name: str) -> int:
    try:
        return TAG_INDEX[name]
    except KeyError as exc:  # pragma: no cover - guarded by the enum import
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown surface tag {name!r}",
                          stage="mothers.tagging") from exc


def tag_indices(names: Sequence[str]) -> tuple[int, ...]:
    return tuple(tag_index(n) for n in names)


def tag_area_report(mesh: trimesh.Trimesh, tags: np.ndarray) -> dict[str, float]:
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    out: dict[str, float] = {}
    for value in np.unique(tags):
        name = TAG_NAMES.get(int(value), f"tag_{int(value)}")
        out[name] = float(areas[tags == value].sum())
    return out


def tag_by_polyline(mesh: trimesh.Trimesh, polyline: LabelledPolyline, *,
                    mode: str = "revolve") -> tuple[np.ndarray, dict[str, Any]]:
    """Assign ``surface_tag`` indices by projecting face centroids onto ``polyline``."""
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    if mode == "revolve":
        rz = np.column_stack([np.hypot(centroids[:, 0], centroids[:, 1]), centroids[:, 2]])
    elif mode in ("planar", "extrude"):
        rz = centroids[:, :2]
    elif mode == "sweep":
        rz = np.column_stack([np.hypot(centroids[:, 0], centroids[:, 1]), centroids[:, 2]])
    else:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown tagging mode {mode!r}",
                          stage="mothers.tagging")
    _, dist, seg = polyline.project(rz)
    labels = polyline.labels[seg]
    tags = np.array([tag_index(str(lab)) for lab in labels], dtype=np.int32)
    report = {
        "mode": mode,
        "max_projection_distance_mm": float(np.max(dist)) if dist.size else 0.0,
        "mean_projection_distance_mm": float(np.mean(dist)) if dist.size else 0.0,
        "tag_area_mm2": tag_area_report(mesh, tags),
        "tag_rule": "nearest labelled construction segment (parametric, not guessed)",
    }
    return tags, report


def inherit_tags(target: trimesh.Trimesh, source: trimesh.Trimesh, source_tags: np.ndarray,
                 *, ambiguity_mm: float = 0.35) -> tuple[np.ndarray, dict[str, Any]]:
    """Carry face tags across a boolean by nearest pre-boolean triangle.

    Manifold booleans rebuild triangles, so provenance is recovered by matching each
    result centroid to the closest source triangle.  The area of faces whose two nearest
    source triangles disagree (typically the junction ring) is reported as ambiguity.
    """
    src_c = np.asarray(source.triangles_center, dtype=np.float64)
    if len(src_c) == 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "cannot inherit tags from an empty mesh",
                          stage="mothers.tagging")
    tree = cKDTree(src_c)
    tgt_c = np.asarray(target.triangles_center, dtype=np.float64)
    k = 2 if len(src_c) > 1 else 1
    dist, idx = tree.query(tgt_c, k=k)
    if k == 1:
        dist = dist[:, None]
        idx = idx[:, None]
    tags = np.asarray(source_tags, dtype=np.int32)[idx[:, 0]]
    ambiguous = (idx[:, 1] >= 0) & (np.asarray(source_tags, dtype=np.int32)[idx[:, 1]] != tags) \
        & (dist[:, 1] - dist[:, 0] <= ambiguity_mm)
    areas = np.asarray(target.area_faces, dtype=np.float64)
    report = {
        "matched_faces": int(len(tgt_c)),
        "mean_distance_mm": float(dist[:, 0].mean()),
        "p99_distance_mm": float(np.percentile(dist[:, 0], 99)),
        "ambiguous_faces": int(ambiguous.sum()),
        "ambiguous_area_mm2": float(areas[ambiguous].sum()),
        "ambiguity_mm": float(ambiguity_mm),
        "total_area_mm2": float(areas.sum()),
        "tag_area_mm2": tag_area_report(target, tags),
    }
    return tags, report


def component_ids_from_parts(parts: Sequence[trimesh.Trimesh]) -> np.ndarray:
    out = []
    for cid, part in enumerate(parts):
        out.append(np.full(len(part.faces), cid, dtype=np.int32))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.int32)


def inherit_components(target: trimesh.Trimesh, source: trimesh.Trimesh,
                       source_components: np.ndarray) -> np.ndarray:
    tree = cKDTree(np.asarray(source.triangles_center, dtype=np.float64))
    _, idx = tree.query(np.asarray(target.triangles_center, dtype=np.float64), k=1)
    return np.asarray(source_components, dtype=np.int32)[idx]


def merge_tag_reports(*reports: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for report in reports:
        for key, value in report.items():
            if key not in merged:
                merged[key] = value
    return merged


def attach_face_semantics(mesh: trimesh.Trimesh, *,
                          surface_tag: np.ndarray,
                          component_id: np.ndarray | None = None) -> trimesh.Trimesh:
    """Write tags into ``mesh.metadata['face_attr_arrays']`` (mesh_io contract)."""
    from ..storage.mesh_io import with_face_attrs

    tag = np.asarray(surface_tag, dtype=np.int32)
    if tag.shape[0] != len(mesh.faces):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"surface_tag length {tag.shape[0]} != faces {len(mesh.faces)}",
                          stage="mothers.tagging")
    attrs: dict[str, np.ndarray] = {
        "surface_tag": tag,
        "source_triangle": np.arange(len(mesh.faces), dtype=np.int32),
    }
    if component_id is not None:
        comp = np.asarray(component_id, dtype=np.int32)
        if comp.shape[0] != len(mesh.faces):
            raise SynLabError(ErrorCode.MOTHER_INVALID,
                              "component_id length mismatch", stage="mothers.tagging")
        attrs["component_id"] = comp
    return with_face_attrs(mesh, **attrs)
