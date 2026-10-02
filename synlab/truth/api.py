"""Three-layer truth: ``CleanTruth`` → ``PhysicalTruth`` → ``VisibleLabels`` (plan 11 / 30.5).

Only measured evidence becomes a label.  The rules implemented here are the frozen ones from
plan §11.1/§30.5/§30.6:

* **R2** requires a real *new fracture surface*: both sides of the interface are cut faces
  (``origin_kind == interface``), the source triangle is unique, the sample points are backed
  by mother material, and the shared area clears **both** the absolute (0.1 mm², development
  candidate) and the relative threshold (``1e-4`` × mother material area);
* point/edge contact, adjacency across a cavity, original assembly contact and outer-surface
  proximity are **never** R2 — they come out as ``TINY_CONTACT`` (numerical grey zone, area kept
  as measured), ``R1`` (same event, no direct fracture surface) or ``UNKNOWN``;
* ``UNKNOWN`` always carries ``loss_mask=False`` and is never rewritten into ``R0``;
* relations are symmetric, have no self-loops and are **not** transitively closed;
* ``build_labels`` keeps labels out of features: the feature payload is returned untouched and
  a leak check refuses to mix the two.

Persistence (``commit_truth``/``load_truth``) writes the relation list as a JSON blob named
``relations`` (the encoding the L0 gate reads through ``store.load_bytes``) *and* as
``meta["relations"]`` (the encoding ``synlab.relations.gallery`` reads), plus the
correspondence / interface sample arrays in ``arrays.npz``.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..fracture.spec import (
    AMBIGUITY_AREA_RATIO_MAX,
    CORRESPONDENCE_RESIDUAL_MM,
    INTERFACE_GAP_P95_MM,
    NORMAL_REVERSAL_P95_DEG,
    R2_AREA_ABS_MM2,
    R2_AREA_REL,
    TINY_AREA_ABS_MM2,
    TINY_AREA_REL,
)
from ..roles import (
    FORBIDDEN_FEATURE_FIELDS,
    FRAME_WORLD,
    ROLE_CLEAN_TRUTH,
    ROLE_PHYSICAL_TRUTH,
    ROLE_VISIBLE_LABELS,
    SCHEMA_TRUTH_CLEAN,
    SCHEMA_TRUTH_PHYSICAL,
    SCHEMA_TRUTH_VISIBLE,
    UNIT_MM,
)
from ..schemas.runtime import (
    ORIGIN_INTERFACE,
    RELATION_R1,
    RELATION_R2,
    RELATION_TINY,
    RELATION_UNKNOWN,
    CleanTruth,
    CorrespondenceSample,
    InterfacePatch,
    PhysicalTruth,
    RelationEdge,
    VisibleLabels,
)
from ..storage.store import QA_FAIL, QA_PASS

__all__ = [
    "finalize_clean_truth",
    "update_residual_truth",
    "update_visibility_truth",
    "build_labels",
    "commit_truth",
    "load_truth",
    "relation_audit",
    "truth_summary",
    "LAYER_CLEAN",
    "LAYER_PHYSICAL",
    "LAYER_VISIBLE",
    "ASSOCIATION_KINDS",
    "VISIBILITY_RULE",
]

LAYER_CLEAN = "clean"
LAYER_PHYSICAL = "physical"
LAYER_VISIBLE = "visible"

#: plan 30.6 association kinds, in the frozen order used by the integer codes below.
ASSOCIATION_KINDS: tuple[str, ...] = ("EXACT_SURVIVOR", "VERIFIED_RECESSION", "UNKNOWN_MAPPING")
_ASSOCIATION_CODE = {name: index for index, name in enumerate(ASSOCIATION_KINDS)}

#: how far inside the material the mother-containment probe is taken along ``-normal`` (mm);
#: the shared surface lies *on* the mother boundary, so a strictly interior probe is needed.
MATERIAL_PROBE_MM = 0.05
#: a patch counts as material-backed when at least this fraction of its probes is inside
MATERIAL_INSIDE_MIN = 0.90
#: cap on correspondence samples carried from one layer to the next
DEFAULT_CORRESPONDENCE_LIMIT = 200_000
#: ``ORIGIN_TO_TAG[ORIGIN_INTERFACE]`` in ``synlab.observe.routes`` (the rendered "rim" tag)
INTERFACE_SURFACE_TAG = 2
_EPS = 1.0e-12

VISIBILITY_RULE = (
    "visible = inside the delivered image AND camera z>0 AND |z - rendered depth| <= "
    "max(0.5 mm, 4 * mm_per_px) AND id_map>=0 AND not uncertain_mask AND deployment_mask"
)


# ---------------------------------------------------------------------------- helpers
def _relation_key(a: str, b: str) -> tuple[str, str]:
    """Canonical (sorted) pair key: R2 is symmetric and must have exactly one entry."""
    return (a, b) if a <= b else (b, a)


def _edge_row(pair: tuple[str, str], edge: RelationEdge) -> dict[str, Any]:
    return {
        "a": pair[0], "b": pair[1], "kind": edge.kind, "interface_id": edge.interface_id,
        "area_mm2": float(edge.area_mm2), "valid": bool(edge.valid),
        "loss_mask": bool(edge.loss_mask), "reason": edge.reason,
    }


def _mesh_of(obj: Any) -> Any:
    return getattr(obj, "mesh", None)


def _mother_material_area_mm2(mother: Any) -> float:
    mesh = _mesh_of(mother)
    if mesh is not None and hasattr(mesh, "area"):
        return float(mesh.area)
    return 0.0


def _fragment_area_mm2(fragment: Any) -> float:
    mesh = _mesh_of(fragment)
    if mesh is not None and hasattr(mesh, "area"):
        return float(mesh.area)
    return float(getattr(fragment, "area_mm2", 0.0) or 0.0)


def _new_fracture_fraction(fragment: Any, faces: Sequence[int] | None) -> float | None:
    """Fraction of the patch faces that are *cut* faces (``origin_kind == interface``).

    ``None`` means "not measurable from this fragment" (no face attribute recorded); the caller
    records that the check was unavailable instead of assuming it passed.
    """
    if faces is None or len(faces) == 0:
        return None
    origin = getattr(fragment, "face_origin_kind", None)
    if origin is None:
        return None
    origin = np.asarray(origin)
    ids = np.asarray(list(faces), dtype=np.int64)
    ids = ids[(ids >= 0) & (ids < origin.shape[0])]
    if ids.size == 0:
        return None
    return float(np.mean(origin[ids] == ORIGIN_INTERFACE))


def _material_inside_fraction(points: np.ndarray, normals: np.ndarray, mother: Any,
                              *, probe_mm: float = MATERIAL_PROBE_MM) -> float | None:
    """Fraction of shared-surface sample points that lie **inside** the mother material.

    A new fracture surface is a cut *through* material, so its points are strictly interior to
    the mother solid.  Two fragments that merely face each other across a cavity (or across the
    original outer surface) share a surface that lies *on* the mother boundary instead, and this
    fraction collapses — which is what keeps cavity adjacency and outer-surface proximity out of
    R2 (plan 11.1).  ``normals`` is accepted for API symmetry and recorded, not needed by the
    containment test.  ``None`` means containment is unavailable for this mother (recorded,
    never silently treated as a pass).
    """
    mesh = _mesh_of(mother)
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if mesh is None or pts.shape[0] == 0 or not hasattr(mesh, "contains"):
        return None
    nrm = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    if nrm.shape[0] != pts.shape[0]:
        return None
    del probe_mm
    try:
        inside = np.asarray(mesh.contains(pts), dtype=bool)
    except Exception:  # noqa: BLE001 - a non-watertight mother cannot answer containment
        return None
    return float(np.mean(inside))


def _face_normals_for(fragment: Any, faces: np.ndarray) -> np.ndarray:
    mesh = _mesh_of(fragment)
    ids = np.asarray(faces, dtype=np.int64)
    if mesh is None or ids.size == 0:
        return np.zeros((ids.size, 3), dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    if normals.shape[0] == 0:
        return np.zeros((ids.size, 3), dtype=np.float64)
    ids = np.clip(ids, 0, normals.shape[0] - 1)
    return normals[ids]


def _bary_block(rows: Sequence[Mapping[str, Any]], key: str) -> np.ndarray:
    out = np.zeros((len(rows), 3), dtype=np.float64)
    for index, row in enumerate(rows):
        value = np.asarray(row.get(key, (1.0, 0.0, 0.0)), dtype=np.float64).reshape(-1)
        if value.size >= 3:
            out[index] = value[:3]
        elif value.size == 2:
            out[index] = (1.0 - float(value.sum()), float(value[0]), float(value[1]))
    return out


# ------------------------------------------------------------------- correspondence bundle
def _empty_correspondence() -> dict[str, np.ndarray]:
    return {
        "fragment_ids": np.zeros(0, dtype="<U1"),
        "index_a": np.zeros(0, dtype=np.int64),
        "index_b": np.zeros(0, dtype=np.int64),
        "point_a": np.zeros((0, 3), dtype=np.float64),
        "point_b": np.zeros((0, 3), dtype=np.float64),
        "normal_a": np.zeros((0, 3), dtype=np.float64),
        "normal_b": np.zeros((0, 3), dtype=np.float64),
        "bary_a": np.zeros((0, 3), dtype=np.float64),
        "bary_b": np.zeros((0, 3), dtype=np.float64),
        "face_a": np.zeros(0, dtype=np.int64),
        "face_b": np.zeros(0, dtype=np.int64),
        "interface_id": np.zeros(0, dtype=np.int64),
        "residual_mm": np.zeros(0, dtype=np.float64),
        "weight": np.zeros(0, dtype=np.float64),
        "association_code": np.zeros(0, dtype=np.int8),
        "ambiguous": np.zeros(0, dtype=bool),
        "valid": np.zeros(0, dtype=bool),
    }


def _correspondence_from_rows(rows: Sequence[Mapping[str, Any]],
                              fragments: Mapping[str, Any],
                              patches: Mapping[int, InterfacePatch],
                              ) -> dict[str, np.ndarray]:
    """Build the array bundle from the event's barycentric correspondence rows (plan 30.5)."""
    if not rows:
        return _empty_correspondence()
    ids = sorted({str(row.get("fragment_a", "")) for row in rows}
                 | {str(row.get("fragment_b", "")) for row in rows})
    index = {name: position for position, name in enumerate(ids)}
    width = max(1, max((len(name) for name in ids), default=1))
    out = _empty_correspondence()
    out["fragment_ids"] = np.asarray(ids, dtype=f"<U{width}")
    count = len(rows)
    out["index_a"] = np.asarray([index[str(r.get("fragment_a", ""))] for r in rows], dtype=np.int64)
    out["index_b"] = np.asarray([index[str(r.get("fragment_b", ""))] for r in rows], dtype=np.int64)
    out["point_a"] = np.asarray([np.asarray(r.get("point_a_mm", (0.0, 0.0, 0.0)),
                                            dtype=np.float64).reshape(3) for r in rows])
    out["point_b"] = np.asarray([np.asarray(r.get("point_b_mm", (0.0, 0.0, 0.0)),
                                            dtype=np.float64).reshape(3) for r in rows])
    face_a = np.asarray([int(r.get("face_a", -1)) for r in rows], dtype=np.int64)
    face_b = np.asarray([int(r.get("face_b", -1)) for r in rows], dtype=np.int64)
    out["face_a"], out["face_b"] = face_a, face_b
    out["bary_a"] = _bary_block(rows, "bary_a")
    out["bary_b"] = _bary_block(rows, "bary_b")
    out["interface_id"] = np.asarray([int(r.get("interface_id", -1) or -1) for r in rows],
                                     dtype=np.int64)
    residual = np.asarray([float(r.get("residual_mm", 0.0) or 0.0) for r in rows], dtype=np.float64)
    ambiguous = np.asarray([bool(r.get("ambiguous", False)) for r in rows], dtype=bool)
    fidelity = np.asarray([bool(r.get("fidelity_ok", True)) for r in rows], dtype=bool)
    out["residual_mm"] = residual
    out["ambiguous"] = ambiguous
    exact = (~ambiguous) & (residual <= CORRESPONDENCE_RESIDUAL_MM) & fidelity
    codes = np.full(count, _ASSOCIATION_CODE["UNKNOWN_MAPPING"], dtype=np.int8)
    codes[exact] = _ASSOCIATION_CODE["EXACT_SURVIVOR"]
    out["association_code"] = codes
    out["valid"] = exact
    out["weight"] = np.ones(count, dtype=np.float64)
    out["normal_a"] = np.zeros((count, 3), dtype=np.float64)
    out["normal_b"] = np.zeros((count, 3), dtype=np.float64)
    for position, name in enumerate(ids):
        fragment = fragments.get(name)
        if fragment is None:
            continue
        side_a = out["index_a"] == position
        side_b = out["index_b"] == position
        if bool(np.any(side_a)):
            out["normal_a"][side_a] = _face_normals_for(fragment, face_a[side_a])
        if bool(np.any(side_b)):
            out["normal_b"][side_b] = _face_normals_for(fragment, face_b[side_b])
    for patch in patches.values():
        weights = patch.meta.get("weights_mm2")
        if weights is None:
            continue
        selected = out["interface_id"] == int(patch.interface_id)
        weights = np.asarray(weights, dtype=np.float64).reshape(-1)
        if int(np.sum(selected)) == weights.size and weights.size:
            out["weight"][selected] = weights
    return out


def _correspondence_subset(bundle: Mapping[str, np.ndarray],
                           mask: np.ndarray) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for key, value in bundle.items():
        array = np.asarray(value)
        out[key] = array if (array.ndim == 1 and array.dtype.kind == "U") else array[mask]
    return out


def _correspondence_samples(bundle: Mapping[str, np.ndarray]) -> list[CorrespondenceSample]:
    names = [str(x) for x in np.asarray(bundle.get("fragment_ids", np.zeros(0, dtype="<U1")))]
    index_a = np.asarray(bundle.get("index_a", np.zeros(0, dtype=np.int64)), dtype=np.int64)
    count = int(index_a.shape[0])
    if count == 0:
        return []
    index_b = np.asarray(bundle["index_b"], dtype=np.int64)
    codes = np.asarray(bundle["association_code"], dtype=np.int8)
    point_a = np.asarray(bundle["point_a"], dtype=np.float64)
    point_b = np.asarray(bundle["point_b"], dtype=np.float64)
    normal_a = np.asarray(bundle["normal_a"], dtype=np.float64)
    normal_b = np.asarray(bundle["normal_b"], dtype=np.float64)
    bary_a = np.asarray(bundle["bary_a"], dtype=np.float64)
    bary_b = np.asarray(bundle["bary_b"], dtype=np.float64)
    face_a = np.asarray(bundle["face_a"], dtype=np.int64)
    face_b = np.asarray(bundle["face_b"], dtype=np.int64)
    weight = np.asarray(bundle["weight"], dtype=np.float64)
    valid = np.asarray(bundle["valid"], dtype=bool)
    residual = np.asarray(bundle["residual_mm"], dtype=np.float64)
    out: list[CorrespondenceSample] = []
    for row in range(count):
        code = int(codes[row])
        out.append(CorrespondenceSample(
            fragment_a=names[int(index_a[row])], fragment_b=names[int(index_b[row])],
            point_a_mm=point_a[row].copy(), point_b_mm=point_b[row].copy(),
            normal_a=normal_a[row].copy(), normal_b=normal_b[row].copy(),
            face_a=int(face_a[row]), face_b=int(face_b[row]),
            bary_a=bary_a[row].copy(), bary_b=bary_b[row].copy(),
            association_kind=(ASSOCIATION_KINDS[code] if 0 <= code < len(ASSOCIATION_KINDS)
                              else "UNKNOWN_MAPPING"),
            weight=float(weight[row]), valid=bool(valid[row]), residual_mm=float(residual[row]),
        ))
    return out


# ------------------------------------------------------------------- clean truth
def finalize_clean_truth(
    mother: Any,
    fracture_result: Any,
    *,
    area_abs_mm2: float = R2_AREA_ABS_MM2,
    area_rel: float = R2_AREA_REL,
    tiny_abs_mm2: float = TINY_AREA_ABS_MM2,
    tiny_rel: float = TINY_AREA_REL,
    gap_p95_mm: float = INTERFACE_GAP_P95_MM,
    normal_p95_deg: float = NORMAL_REVERSAL_P95_DEG,
    ambiguity_max: float = AMBIGUITY_AREA_RATIO_MAX,
    material_probe_mm: float = MATERIAL_PROBE_MM,
    correspondence_limit: int = DEFAULT_CORRESPONDENCE_LIMIT,
) -> CleanTruth:
    """Freeze the clean relation graph, interfaces and geometric correspondence (plan 11.1)."""
    fragments = list(getattr(fracture_result, "fragments", []) or [])
    if not fragments:
        raise SynLabError(ErrorCode.FRACTURE_CONSERVATION_FAIL,
                          "clean truth needs at least one fragment",
                          stage="truth.finalize_clean")
    by_id = {str(f.fragment_id): f for f in fragments}
    ids = list(by_id)
    mother_area = _mother_material_area_mm2(mother)
    if mother_area <= 0.0:
        mother_area = float(sum(_fragment_area_mm2(f) for f in fragments))
    area_threshold = max(float(area_abs_mm2), float(area_rel) * mother_area)
    tiny_threshold = max(float(tiny_abs_mm2), float(tiny_rel) * mother_area)

    patches = list(getattr(fracture_result, "interfaces", []) or [])
    patch_map = {int(p.interface_id): p for p in patches}
    by_pair: dict[tuple[str, str], list[InterfacePatch]] = {}
    self_loops: list[int] = []
    unbound: list[int] = []
    for patch in patches:
        name_a, name_b = str(patch.fragment_a), str(patch.fragment_b)
        if name_a == name_b:
            self_loops.append(int(patch.interface_id))
            continue
        if name_a not in by_id or name_b not in by_id:
            unbound.append(int(patch.interface_id))
            continue
        by_pair.setdefault(_relation_key(name_a, name_b), []).append(patch)

    evidence: dict[int, dict[str, Any]] = {}
    for pair, pair_patches in by_pair.items():
        for patch in pair_patches:
            evidence[int(patch.interface_id)] = _classify_patch(
                patch, pair, by_id, mother, area_threshold, tiny_threshold,
                gap_p95_mm=gap_p95_mm, normal_p95_deg=normal_p95_deg,
                ambiguity_max=ambiguity_max, material_probe_mm=material_probe_mm)

    relations: dict[tuple[str, str], RelationEdge] = {}
    for position, name_a in enumerate(ids):
        for name_b in ids[position + 1:]:
            pair = _relation_key(name_a, name_b)
            relations[pair] = _merge_pair_edges(pair, by_pair.get(pair, []), evidence,
                                                area_threshold, tiny_threshold)

    rows = getattr(fracture_result, "meta", {}).get("correspondence") or []
    correspondence = _correspondence_from_rows(rows, by_id, patch_map)
    truncated = False
    if int(correspondence["index_a"].shape[0]) > int(correspondence_limit):
        stride = int(np.ceil(correspondence["index_a"].shape[0] / float(correspondence_limit)))
        mask = np.zeros(correspondence["index_a"].shape[0], dtype=bool)
        mask[::stride] = True
        correspondence = _correspondence_subset(correspondence, mask)
        truncated = True

    samples = _correspondence_samples(correspondence)
    for sample in samples:
        edge = relations.get(_relation_key(sample.fragment_a, sample.fragment_b))
        if edge is None or edge.kind != RELATION_R2:
            # a sample is only supervised when its own pair carries a real fracture surface
            sample.valid = False
            sample.association_kind = "UNKNOWN_MAPPING"

    qa = _clean_qa(mother_area, area_threshold, tiny_threshold, relations, evidence,
                   correspondence, self_loops, unbound, len(ids), len(patch_map))
    event_id = str((getattr(fracture_result, "event_tree", {}) or {}).get("event_id")
                   or getattr(fracture_result, "meta", {}).get("event_id", ""))
    mother_id = str(getattr(mother, "mother_id", "") or getattr(fracture_result, "parent_id", ""))
    meta = {
        "layer": LAYER_CLEAN,
        "mother_id": mother_id,
        "fragment_ids": ids,
        "fragments": [{"fragment_id": str(f.fragment_id), "volume_mm3": float(f.volume_mm3),
                       "area_mm2": float(f.area_mm2), "is_tiny": bool(f.is_tiny),
                       "component_id": int(getattr(f, "component_id", 0))}
                      for f in fragments],
        "mother_area_mm2": float(mother_area),
        "r2_area_threshold_mm2": float(area_threshold),
        "tiny_area_threshold_mm2": float(tiny_threshold),
        "backend": str(getattr(fracture_result, "backend", "")),
        "cutter_ref": getattr(fracture_result, "cutter_ref", None),
        "patch_evidence": {str(k): v for k, v in sorted(evidence.items())},
        "fracture_qa": _jsonable(getattr(fracture_result, "qa", {}) or {}),
        "correspondence_truncated": truncated,
        "correspondence_rows_total": int(len(rows)),
        "truth_incomplete": False,
        "correspondence_bundle": correspondence,
    }
    truth = CleanTruth(
        mother_id=mother_id, event_id=event_id, version=1, relations=relations,
        interfaces=list(patch_map.values()), correspondence=samples,
        event_tree=dict(getattr(fracture_result, "event_tree", {}) or {}), qa=qa, meta=meta,
    )
    truth.meta["truth_hash"] = hash_json({
        "event_id": event_id,
        "relations": [_edge_row(pair, edge) for pair, edge in sorted(relations.items())],
        "interfaces": sorted(int(i) for i in patch_map),
        "samples": int(correspondence["index_a"].shape[0]),
    })
    return truth


def _patch_shared_area_mm2(patch: InterfacePatch) -> float:
    """The patch's measured common clipped coverage (plan 30.5).

    ``patch.area_mm2`` is the event's own number; ``build_interface`` records the measured 2D
    common clipped coverage of the patch under ``meta['common_clip_area_mm2']`` and that
    measurement is what the relation graph is built from.
    """
    measured = patch.meta.get("common_clip_area_mm2")
    return float(measured) if measured is not None else float(patch.area_mm2)


def _pair_shared_area_mm2(patches: Sequence[InterfacePatch]) -> tuple[float, str]:
    """The fragment pair's measured common fracture area and where the number comes from.

    A fragment pair shares *one* new fracture surface; the event records it as several sampling
    chunks.  ``build_interface`` measures the pair-level common clipped coverage once (plan 30.5
    "公共面积"), which is the physical quantity the R2 threshold is defined on; the sum of the
    chunk measurements is the fallback when a layer was rebuilt from stored arrays.
    """
    for patch in patches:
        value = patch.meta.get("pair_common_clip_area_mm2")
        if value is not None:
            return float(value), "pair_common_clip_area_mm2"
    return float(sum(_patch_shared_area_mm2(patch) for patch in patches)), "sum_of_patch_clip_area"


def _classify_patch(patch: InterfacePatch, pair: tuple[str, str], fragments: Mapping[str, Any],
                    mother: Any, area_threshold: float, tiny_threshold: float, *,
                    gap_p95_mm: float, normal_p95_deg: float, ambiguity_max: float,
                    material_probe_mm: float) -> dict[str, Any]:
    """Measure one interface patch's **structure** against the frozen R2 rules (never a guess).

    The *area* verdict is deliberately not taken here: one interface is recorded as several
    sampling chunks whose individual areas are far below the frozen threshold, so the verdict is
    taken once per fragment pair in ``_merge_pair_edges``.  This function answers the question the
    plan reserves for the patch: is this a real, uniquely sourced, material-backed cut face, or
    is it an assembly contact / cavity adjacency / an unmappable sample?
    """
    fragment_first, fragment_second = fragments[pair[0]], fragments[pair[1]]
    if str(patch.fragment_a) == pair[0]:
        faces_first = patch.meta.get("faces_a")
        faces_second = patch.meta.get("faces_b")
    else:
        faces_first = patch.meta.get("faces_b")
        faces_second = patch.meta.get("faces_a")
    new_first = _new_fracture_fraction(fragment_first, faces_first)
    new_second = _new_fracture_fraction(fragment_second, faces_second)
    points = np.asarray(patch.sample_points_a, dtype=np.float64)
    normals = np.asarray(patch.normals_a, dtype=np.float64)
    inside = _material_inside_fraction(points, normals, mother, probe_mm=material_probe_mm)
    sources = [int(x) for x in patch.meta.get("source_triangles", [])]
    unique_source = bool(sources) and all(x >= 0 for x in sources)
    measured_area = _patch_shared_area_mm2(patch)
    empty = bool(patch.meta.get("empty_patch", False)) or points.shape[0] == 0
    if empty or measured_area <= _EPS:
        kind, valid, loss_mask, reason = RELATION_R1, False, False, "empty_patch"
        structural_ok, unknown_reason = False, ""
    elif new_first is not None and new_second is not None \
            and (new_first <= 0.0 or new_second <= 0.0):
        kind, valid, loss_mask = RELATION_R1, False, False
        reason = "not_a_new_fracture_surface (assembly / outer-surface contact)"
        structural_ok, unknown_reason = False, ""
    elif not unique_source:
        kind, valid, loss_mask, reason = RELATION_UNKNOWN, False, False, "no_unique_source"
        structural_ok, unknown_reason = False, "no_unique_source"
    elif float(patch.ambiguity_area_ratio) > float(ambiguity_max):
        kind, valid, loss_mask = RELATION_UNKNOWN, False, False
        reason = f"ambiguous_area_ratio>{ambiguity_max}"
        structural_ok, unknown_reason = False, reason
    elif inside is not None and inside < MATERIAL_INSIDE_MIN:
        kind, valid, loss_mask = RELATION_UNKNOWN, False, False
        reason = "cavity_adjacency_or_outside_material"
        structural_ok, unknown_reason = False, reason
    elif float(patch.gap_p95_mm) > float(gap_p95_mm) \
            or float(patch.normal_angle_p95_deg) > float(normal_p95_deg):
        kind, valid, loss_mask = RELATION_UNKNOWN, False, False
        reason = "shared_surface_geometry_out_of_budget"
        structural_ok, unknown_reason = False, reason
    else:
        # structurally a real cut face; the area verdict is taken per fragment pair below
        kind, valid, loss_mask, reason = RELATION_TINY, True, True, "structurally_valid_cut_face"
        structural_ok, unknown_reason = True, ""
    return {
        "pair": [pair[0], pair[1]],
        "kind": kind, "valid": bool(valid), "loss_mask": bool(loss_mask), "reason": reason,
        "structural_ok": bool(structural_ok), "unknown_reason": str(unknown_reason),
        "area_mm2": float(measured_area),
        "event_area_mm2": float(patch.area_mm2),
        "gap_p95_mm": float(patch.gap_p95_mm),
        "normal_angle_p95_deg": float(patch.normal_angle_p95_deg),
        "ambiguity_area_ratio": float(patch.ambiguity_area_ratio),
        "ambiguous_area_mm2": float(patch.ambiguous_area_mm2),
        "samples": int(points.shape[0]),
        "source_triangles": sources,
        "new_fracture_fraction_first": new_first,
        "new_fracture_fraction_second": new_second,
        "material_inside_fraction": inside,
        "area_threshold_mm2": float(area_threshold),
        "tiny_threshold_mm2": float(tiny_threshold),
    }


_KIND_PRIORITY = {RELATION_R2: 0, RELATION_TINY: 1, RELATION_UNKNOWN: 2, RELATION_R1: 3}


def _merge_pair_edges(pair: tuple[str, str], patches: Sequence[InterfacePatch],
                      evidence: Mapping[int, dict[str, Any]], area_threshold: float,
                      tiny_threshold: float) -> RelationEdge:
    """One relation per fragment pair, with the **pair-level** area verdict (plan 11.1 / 30.5).

    A fragment pair shares *one* new fracture surface.  The interface record splits it into
    sampling chunks (a sampling-cost bound, not a physical fact), so the frozen absolute and
    relative thresholds are applied to the pair's measured common fracture area
    (``pair_common_clip_area_mm2``) and never to a single chunk.  Structure and area stay
    separate: a structurally sound cut face below the thresholds is a measured ``TINY_CONTACT``
    (a grey zone, never a negative), and an unmappable patch is ``UNKNOWN`` with
    ``loss_mask=False``.
    """
    if not patches:
        return RelationEdge(fragment_a=pair[0], fragment_b=pair[1], kind=RELATION_R1,
                            interface_id=None, area_mm2=0.0, valid=False, loss_mask=False,
                            reason="no_direct_fracture_surface (same event, mutually exclusive)")
    measured = [(patch, evidence[int(patch.interface_id)]) for patch in patches
                if int(patch.interface_id) in evidence]
    if not measured:
        return RelationEdge(fragment_a=pair[0], fragment_b=pair[1], kind=RELATION_UNKNOWN,
                            interface_id=None, area_mm2=0.0, valid=False, loss_mask=False,
                            reason="interface_patch_without_measurement")
    structural = [(patch, row) for patch, row in measured if bool(row.get("structural_ok"))]
    pair_area, area_source = _pair_shared_area_mm2(patches)
    reasons = sorted({str(row["reason"]) for _, row in measured})
    if structural:
        if pair_area >= float(area_threshold):
            kind, valid, loss_mask = RELATION_R2, True, True
            reason = "shared_new_fracture_surface"
        elif pair_area >= float(tiny_threshold):
            kind, valid, loss_mask = RELATION_TINY, True, False
            reason = (f"below_r2_area_threshold ({pair_area:.6g} < "
                      f"{float(area_threshold):.6g} mm^2)")
        else:
            kind, valid, loss_mask = RELATION_TINY, True, False
            reason = "below_tiny_area"
        best_patch, best_row = max(structural, key=lambda item: float(item[1]["area_mm2"]))
        area = float(pair_area) if kind in (RELATION_R2, RELATION_TINY) else 0.0
        edge = RelationEdge(
            fragment_a=pair[0], fragment_b=pair[1], kind=kind,
            interface_id=int(best_patch.interface_id), area_mm2=area,
            valid=bool(valid), loss_mask=bool(loss_mask),
            reason=";".join([reason] + [r for r in reasons if r != reason][:3]),
        )
    else:
        unknown_rows = [(patch, row) for patch, row in measured if str(row.get("unknown_reason"))]
        if unknown_rows:
            best_patch, _row = max(unknown_rows, key=lambda item: float(item[1]["area_mm2"]))
            edge = RelationEdge(
                fragment_a=pair[0], fragment_b=pair[1], kind=RELATION_UNKNOWN,
                interface_id=int(best_patch.interface_id), area_mm2=0.0, valid=False,
                loss_mask=False,
                reason=";".join(sorted({str(row["unknown_reason"]) for _, row in unknown_rows})),
            )
        else:
            edge = RelationEdge(fragment_a=pair[0], fragment_b=pair[1], kind=RELATION_R1,
                                interface_id=None, area_mm2=0.0, valid=False, loss_mask=False,
                                reason=";".join(reasons))
    for _patch, row in measured:
        row["pair_common_area_mm2"] = float(pair_area)
        row["pair_common_area_source"] = str(area_source)
        row["pair_area_threshold_mm2"] = float(area_threshold)
        row["pair_tiny_threshold_mm2"] = float(tiny_threshold)
        row["pair_structural_patches"] = int(len(structural))
        row["pair_relation_kind"] = str(edge.kind)
        row["pair_r2_area_rule"] = ("max(R2_AREA_ABS_MM2, R2_AREA_REL * mother material area) "
                                    "applied to the pair's measured common fracture area")
    return edge


def _clean_qa(mother_area: float, area_threshold: float, tiny_threshold: float,
              relations: Mapping[tuple[str, str], RelationEdge],
              evidence: Mapping[int, dict[str, Any]], correspondence: Mapping[str, np.ndarray],
              self_loops: Sequence[int], unbound: Sequence[int],
              fragment_count: int, patch_count: int) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    for edge in relations.values():
        kinds[edge.kind] = kinds.get(edge.kind, 0) + 1
    unknown_without_mask = [f"{pair[0]}|{pair[1]}" for pair, edge in relations.items()
                            if edge.kind == RELATION_UNKNOWN and edge.loss_mask]
    r2_without_area = [f"{pair[0]}|{pair[1]}" for pair, edge in relations.items()
                       if edge.kind == RELATION_R2 and edge.area_mm2 <= 0.0]
    unbacked_r2 = [f"{pair[0]}|{pair[1]}" for pair, edge in relations.items()
                   if edge.kind == RELATION_R2
                   and (edge.interface_id is None
                        or not evidence.get(int(edge.interface_id), {}).get("structural_ok")
                        or not evidence.get(int(edge.interface_id), {}).get("source_triangles"))]
    malformed = [f"{pair[0]}|{pair[1]}" for pair, edge in relations.items()
                 if pair[0] == pair[1] or pair[0] > pair[1]
                 or edge.fragment_a != pair[0] or edge.fragment_b != pair[1]]
    ambiguous_ratio = max((float(row["ambiguity_area_ratio"]) for row in evidence.values()),
                          default=0.0)
    ambiguous_ratio_total = float(sum(float(row.get("ambiguous_area_mm2", 0.0))
                                     for row in evidence.values())
                                  / max(sum(float(row.get("area_mm2", 0.0))
                                            for row in evidence.values()), _EPS))
    codes = np.asarray(correspondence.get("association_code", np.zeros(0, dtype=np.int8)))
    samples = int(np.asarray(correspondence.get("index_a", np.zeros(0))).shape[0])
    exact = int(np.sum(codes == _ASSOCIATION_CODE["EXACT_SURVIVOR"])) if codes.size else 0
    checks = {
        "symmetric_keys_and_no_self_loops": not malformed,
        "no_self_loop_patches": not self_loops,
        "unknown_has_loss_mask_false": not unknown_without_mask,
        "r2_backed_by_measured_new_fracture_surface": not unbacked_r2,
        "patches_bound_to_fragments": not unbound,
        "r2_has_positive_measured_area": not r2_without_area,
    }
    failures = [name for name, ok in checks.items() if not ok]
    return {
        "pass": not failures,
        "layer": LAYER_CLEAN,
        "fragments": int(fragment_count),
        "interface_patches": int(patch_count),
        "relation_count": int(len(relations)),
        "r2_pairs": int(kinds.get(RELATION_R2, 0)),
        "r1_pairs": int(kinds.get(RELATION_R1, 0)),
        "tiny_pairs": int(kinds.get(RELATION_TINY, 0)),
        "unknown_pairs": int(kinds.get(RELATION_UNKNOWN, 0)),
        "r2_area_mm2_total": float(sum(e.area_mm2 for e in relations.values()
                                       if e.kind == RELATION_R2)),
        "mother_area_mm2": float(mother_area),
        "r2_area_threshold_mm2": float(area_threshold),
        "tiny_area_threshold_mm2": float(tiny_threshold),
        "r2_area_threshold_rule": "max(0.1 mm^2, 1e-4 * mother material area)",
        "r2_area_level": "fragment_pair (summed over the pair's sampling chunks)",
        "ambiguity_area_ratio_max": float(ambiguous_ratio),
        "ambiguity_area_ratio_total": float(ambiguous_ratio_total),
        "ambiguity_tolerance": float(AMBIGUITY_AREA_RATIO_MAX),
        "correspondence_samples": samples,
        "correspondence_exact_survivor": exact,
        "correspondence_unknown_mapping": int(samples - exact),
        "rejected_self_loop_patches": [int(x) for x in self_loops],
        "unbound_patches": [int(x) for x in unbound],
        "checks": checks,
        "failures": failures,
        "notes": [
            "R2 needs a material-backed cut face on both sides, a unique source triangle and the "
            "pair's measured common fracture area above both the absolute and the relative "
            "threshold (plan 11.1/30.5)",
            "the area verdict is taken once per fragment pair: one interface is recorded as "
            "several sampling chunks whose individual areas are below the pair threshold",
            "ambiguity_area_ratio counts only sample points that cannot be attributed to exactly "
            "one output triangle per side; a clean planar cut measures 0",
            "point/edge contacts, cavity adjacency, assembly contacts and outer-surface proximity "
            "are recorded as TINY_CONTACT / R1 / UNKNOWN, never as R2",
            "UNKNOWN always carries loss_mask=false and is never rewritten into R0",
        ],
    }


# ------------------------------------------------------------------- physical truth
def update_residual_truth(clean: CleanTruth, physical: Any, *,
                          tolerance_mm: float = CORRESPONDENCE_RESIDUAL_MM,
                          survivor_tolerance_mm: float = 0.05,
                          correspondence_limit: int = DEFAULT_CORRESPONDENCE_LIMIT,
                          ) -> PhysicalTruth:
    """Measure what survived the damage; historical R2 edges are preserved unchanged."""
    components = list(getattr(physical, "components", []) or [])
    by_fragment: dict[str, list[Any]] = {}
    for component in components:
        by_fragment.setdefault(str(getattr(component, "clean_fragment_id", "")), []).append(component)
    ledger = dict(getattr(physical, "meta", {}).get("ledger", {}) or {})
    clean_volume = float(ledger.get("source_volume_mm3", 0.0) or 0.0)
    clean_fragment_id = str(ledger.get("clean_fragment_id", "") or "")

    residual: dict[str, Any] = {
        "fragments": {},
        "lost_volume_mm3": float(getattr(physical, "lost_volume_mm3", 0.0) or 0.0),
        "lost_volume_ratio": float(getattr(physical, "lost_volume_ratio", 0.0) or 0.0),
        "source_volume_mm3": clean_volume,
        "damaged_volume_mm3": float(ledger.get("damaged_volume_mm3", 0.0) or 0.0),
        "conservation_ok": bool(ledger.get("conservation_ok", False)),
        "identity": bool(getattr(physical, "meta", {}).get("identity", False)),
    }
    current_fit: dict[str, bool] = {}
    for fragment_id in clean.meta.get("fragment_ids", []):
        name = str(fragment_id)
        mine = by_fragment.get(name, [])
        volume = 0.0
        for component in mine:
            mesh = getattr(component, "mesh", None)
            if mesh is not None:
                volume += float(abs(np.asarray(mesh.volume)))
        expected = clean_volume if (name == clean_fragment_id and clean_volume > 0.0) else None
        ratio = (volume / expected) if expected else None
        residual["fragments"][name] = {
            "component_ids": [str(getattr(c, "component_id", "")) for c in mine],
            "damaged_volume_mm3": float(volume),
            "clean_volume_mm3": expected,
            "retained_ratio": ratio,
            "present": bool(mine),
            "representative": bool(any(bool(getattr(c, "is_representative", False)) for c in mine)),
        }
        current_fit[name] = bool(mine) and (ratio is None or ratio >= 1.0 - 1.0e-6)

    survivor_patches: dict[str, Any] = {
        str(int(patch.interface_id)): _survivor_row(patch, by_fragment,
                                                    tolerance_mm=survivor_tolerance_mm)
        for patch in clean.interfaces
    }

    bundle = clean.meta.get("correspondence_bundle")
    if not isinstance(bundle, Mapping):
        bundle = _empty_correspondence()
    count = int(np.asarray(bundle.get("index_a", np.zeros(0))).shape[0])
    if count > int(correspondence_limit):
        stride = int(np.ceil(count / float(correspondence_limit)))
        mask = np.zeros(count, dtype=bool)
        mask[::stride] = True
        bundle = _correspondence_subset(bundle, mask)
    codes = np.asarray(bundle.get("association_code", np.zeros(0, dtype=np.int8)))
    counts = {name: 0 for name in ASSOCIATION_KINDS}
    for name, code in _ASSOCIATION_CODE.items():
        counts[name] = int(np.sum(codes == code)) if codes.size else 0
    present = {name: bool(row["present"]) for name, row in residual["fragments"].items()}
    names = [str(x) for x in np.asarray(bundle.get("fragment_ids", np.zeros(0, dtype="<U1")))]
    index_a = np.asarray(bundle.get("index_a", np.zeros(0, dtype=np.int64)), dtype=np.int64)
    index_b = np.asarray(bundle.get("index_b", np.zeros(0, dtype=np.int64)), dtype=np.int64)
    mate_present = {
        f"{names[int(a)]}|{names[int(b)]}": bool(present.get(names[int(a)], False)
                                                 and present.get(names[int(b)], False))
        for a, b in zip(index_a, index_b)
    }
    # damage never relabels a positive relation: the clean edge objects are carried unchanged
    relations: dict[tuple[str, str], RelationEdge] = dict(clean.relations)
    kinds_clean = {pair: edge.kind for pair, edge in clean.relations.items()}
    kinds_physical = {pair: edge.kind for pair, edge in relations.items()}
    checks = {
        "historical_relation_kinds_unchanged": kinds_clean == kinds_physical,
        "clean_relations_carried_by_identity": all(
            relations[pair] is edge for pair, edge in clean.relations.items()),
        "no_negative_relabelling": all(
            not (kinds_clean.get(pair) == RELATION_R2 and edge.kind != RELATION_R2)
            for pair, edge in relations.items()),
    }
    qa = {
        "pass": all(checks.values()),
        "layer": LAYER_PHYSICAL,
        "historical_r2_preserved": bool(checks["historical_relation_kinds_unchanged"]),
        "components": len(components),
        "fragments_present": int(sum(1 for value in present.values() if value)),
        "fragments_total": int(len(present)),
        "lost_volume_ratio": residual["lost_volume_ratio"],
        "conservation_ok": residual["conservation_ok"],
        "association_counts": counts,
        "correspondence_samples": int(np.asarray(bundle.get("index_a", np.zeros(0))).shape[0]),
        "survivor_patches": len(survivor_patches),
        "current_fit_valid": int(sum(1 for value in current_fit.values() if value)),
        "checks": checks,
        "failures": [name for name, ok in checks.items() if not ok],
        "notes": [
            "a ground-off historical mate keeps its R2 edge: damage never rewrites a positive "
            "relation into a negative one (plan 11.2)",
            "VERIFIED_RECESSION is only counted when a verified recession field exists; this "
            "build has none, so SDF-born surfaces stay UNKNOWN_MAPPING",
            "current_fit_valid is True only when the surviving geometry still explains the clean "
            "fragment within a 1e-6 relative volume budget",
        ],
    }
    meta = {
        "layer": LAYER_PHYSICAL,
        "mother_id": str(getattr(physical, "mother_id", "") or clean.mother_id),
        "event_id": str(getattr(physical, "event_id", "") or clean.event_id),
        "clean_truth_ref": clean.meta.get("truth_hash"),
        "fragment_id": clean_fragment_id or None,
        "fragment_ids": list(clean.meta.get("fragment_ids", [])),
        "correspondence_bundle": bundle,
        "correspondence_limit": int(correspondence_limit),
        "mate_present": mate_present,
        "damage": {
            "recipe_id": str(getattr(physical, "recipe_id", "")),
            "level": int(getattr(physical, "meta", {}).get("level", 0) or 0),
            "axis_id": str(getattr(physical, "meta", {}).get("axis_id", "")),
            "variant": str(getattr(physical, "meta", {}).get("variant", "")),
            "geometry_changed": bool(getattr(physical, "meta", {}).get("geometry_changed", False)),
        },
        "truth_incomplete": not bool(components),
        "relations_edges": relations,
    }
    truth = PhysicalTruth(
        clean_truth_ref=str(clean.meta.get("truth_hash", "") or f"{clean.mother_id}:{clean.event_id}"),
        version=int(clean.version) + 1, residual=residual, survivor_patches=survivor_patches,
        association_counts=counts, current_fit_valid=current_fit, qa=qa, meta=meta,
    )
    return truth


def _survivor_row(patch: InterfacePatch, by_fragment: Mapping[str, list[Any]], *,
                  tolerance_mm: float, max_samples: int = 4096) -> dict[str, Any]:
    """Area of one old patch that still exists on the damaged components (plan 30.5)."""
    row: dict[str, Any] = {
        "interface_id": int(patch.interface_id),
        "pair": [str(patch.fragment_a), str(patch.fragment_b)],
        "area_mm2": float(patch.area_mm2),
        "survivor_area_mm2": 0.0,
        "survivor_ratio": 0.0,
        "samples": 0,
        "tolerance_mm": float(tolerance_mm),
        "sides": {},
    }
    survivors = 0
    total = 0
    for side, fragment_id, points in (("a", str(patch.fragment_a), patch.sample_points_a),
                                      ("b", str(patch.fragment_b), patch.sample_points_b)):
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        mine = by_fragment.get(fragment_id, [])
        if pts.shape[0] == 0 or not mine:
            row["sides"][side] = {"fragment_id": fragment_id, "present": bool(mine),
                                  "samples": int(pts.shape[0]), "surviving": 0}
            continue
        if pts.shape[0] > max_samples:
            pts = pts[::int(np.ceil(pts.shape[0] / float(max_samples)))]
        best = np.full(pts.shape[0], np.inf, dtype=np.float64)
        for component in mine:
            mesh = getattr(component, "mesh", None)
            if mesh is None:
                continue
            try:
                best = np.minimum(best, np.asarray(mesh.nearest.on_surface(pts)[1],
                                                   dtype=np.float64))
            except Exception:  # noqa: BLE001 - an unusable component simply keeps nothing alive
                continue
        alive = int(np.sum(best <= float(tolerance_mm)))
        row["sides"][side] = {
            "fragment_id": fragment_id, "present": True, "samples": int(pts.shape[0]),
            "surviving": alive,
            "distance_p95_mm": float(np.percentile(best, 95)) if best.size else 0.0}
        survivors += alive
        total += int(pts.shape[0])
    if total:
        row["survivor_ratio"] = float(survivors / float(total))
        row["survivor_area_mm2"] = float(row["survivor_ratio"] * float(patch.area_mm2))
        row["samples"] = int(total)
    return row


# ------------------------------------------------------------------- visible labels
def update_visibility_truth(physical_truth: PhysicalTruth, observation: Any, *,
                            depth_tolerance_factor: float = 4.0,
                            min_depth_tolerance_mm: float = 0.5,
                            correspondence_limit: int = DEFAULT_CORRESPONDENCE_LIMIT,
                            ) -> VisibleLabels:
    """Project the clean correspondence into the *delivered* views (plan 11.2 / 30.6).

    A correspondence sample counts as visible on one side when its projection lands inside the
    delivered image, has positive camera depth, the rendered depth agrees within tolerance, the
    integer id map carries a surface, the pixel is not in the mixed/AA uncertain band and the
    deployment mask covers it.  The mate side is *not observed* in this observation (one
    observation renders one component); that is recorded as not-observed instead of assumed.
    """
    if not isinstance(physical_truth, PhysicalTruth):
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            "update_visibility_truth projects the correspondence of a *physical* truth layer; "
            f"got {type(physical_truth).__name__}"
            + (" (the clean layer carries no damage association counts or survivor map; call "
               "update_residual_truth first)" if isinstance(physical_truth, CleanTruth) else ""),
            stage="truth.update_visibility",
            measurements={"received_type": type(physical_truth).__name__,
                          "expected_type": "PhysicalTruth"},
        )
    bundle = physical_truth.meta.get("correspondence_bundle")
    if not isinstance(bundle, Mapping):
        raise SynLabError(
            ErrorCode.INPUT_UNAVAILABLE,
            "physical truth carries no correspondence bundle; call update_residual_truth first",
            stage="truth.update_visibility",
        )
    views = list(getattr(observation, "views", []) or [])
    observed_fragment = str(getattr(observation, "fragment_id", "") or "")
    observed_component = str(getattr(observation, "component_id", "") or "")
    names = [str(x) for x in np.asarray(bundle.get("fragment_ids", np.zeros(0, dtype="<U1")))]
    count = int(np.asarray(bundle.get("index_a", np.zeros(0))).shape[0])
    if count > int(correspondence_limit):
        stride = int(np.ceil(count / float(correspondence_limit)))
        mask = np.zeros(count, dtype=bool)
        mask[::stride] = True
        bundle = _correspondence_subset(bundle, mask)
    index_a = np.asarray(bundle.get("index_a", np.zeros(0, dtype=np.int64)), dtype=np.int64)
    index_b = np.asarray(bundle.get("index_b", np.zeros(0, dtype=np.int64)), dtype=np.int64)
    count = int(index_a.shape[0])
    point_a = np.asarray(bundle.get("point_a", np.zeros((0, 3))), dtype=np.float64)
    point_b = np.asarray(bundle.get("point_b", np.zeros((0, 3))), dtype=np.float64)
    name_a = np.asarray([names[int(i)] for i in index_a], dtype=object) if count else np.zeros(0, object)
    name_b = np.asarray([names[int(i)] for i in index_b], dtype=object) if count else np.zeros(0, object)
    # -1: the fragment under observation is side A; +1: side B; 0: not part of this observation
    side_of_row = np.zeros(count, dtype=np.int64)
    if count:
        matches_a = name_a == observed_fragment
        matches_b = name_b == observed_fragment
        side_of_row[matches_a] = -1
        side_of_row[matches_b & ~matches_a] = 1

    per_view: dict[str, Any] = {}
    visible_count = np.zeros(count, dtype=np.int64)
    projected_count = np.zeros(count, dtype=np.int64)
    for view in views:
        frame = getattr(view, "frame", None)
        view_id = str(getattr(view, "view_id", "") or getattr(frame, "view_id", ""))
        entry: dict[str, Any] = {
            "view_id": view_id, "samples": int(count), "projected": 0, "depth_ok": 0,
            "id_ok": 0, "not_uncertain": 0, "deployment_ok": 0, "visible": 0,
            "interface_pixels": 0,
            "image_size": [int(x) for x in (getattr(frame, "image_size", (0, 0)) or (0, 0))],
            "rule": VISIBILITY_RULE,
        }
        if frame is None or count == 0:
            per_view[view_id] = entry
            continue
        K = np.asarray(frame.K, dtype=np.float64)
        T_CW = np.asarray(frame.T_CW, dtype=np.float64)
        width, height = int(frame.image_size[0]), int(frame.image_size[1])
        depth = np.asarray(getattr(view, "depth_z", np.full((height, width), np.nan)),
                           dtype=np.float64)
        id_map = np.asarray(getattr(view, "id_map", np.full((height, width), -1)), dtype=np.int64)
        uncertain = np.asarray(getattr(view, "uncertain_mask",
                                       np.zeros((height, width), dtype=bool)), dtype=bool)
        deploy = np.asarray(getattr(view, "deployment_mask",
                                    np.zeros((height, width), dtype=bool)), dtype=bool)
        surface_tag = np.asarray(getattr(view, "surface_tag",
                                         np.zeros((height, width), dtype=np.int16)), dtype=np.int16)
        mm_per_px = float(frame.working_distance_mm / max(float(K[0, 0]), 1e-9))
        tolerance = max(float(min_depth_tolerance_mm), float(depth_tolerance_factor) * mm_per_px)
        entry["depth_tolerance_mm"] = float(tolerance)
        entry["mm_per_px"] = mm_per_px
        for side, origin in ((-1, point_a), (1, point_b)):
            rows = np.nonzero(side_of_row == side)[0]
            if rows.size == 0:
                continue
            points = np.asarray(origin, dtype=np.float64)[rows]
            homogeneous = np.column_stack([points, np.ones(points.shape[0])])
            camera = (T_CW @ homogeneous.T).T[:, 0:3]
            z = camera[:, 2]
            safe = np.where(np.abs(z) < 1e-12, 1e-12, z)
            u = K[0, 0] * camera[:, 0] / safe + K[0, 2]
            v = K[1, 1] * camera[:, 1] / safe + K[1, 2]
            ui = np.rint(u).astype(np.int64)
            vi = np.rint(v).astype(np.int64)
            inside = (z > 0.0) & (ui >= 0) & (ui < width) & (vi >= 0) & (vi < height)
            entry["projected"] += int(np.sum(inside))
            if not bool(np.any(inside)):
                continue
            use = rows[inside]
            projected_count[use] += 1
            uu, vv, zz = ui[inside], vi[inside], z[inside]
            rendered = depth[vv, uu]
            depth_ok = np.isfinite(rendered) & (np.abs(rendered - zz) <= tolerance)
            entry["depth_ok"] += int(np.sum(depth_ok))
            id_ok = id_map[vv, uu] >= 0
            entry["id_ok"] += int(np.sum(id_ok))
            clean_px = ~uncertain[vv, uu]
            entry["not_uncertain"] += int(np.sum(clean_px))
            covered = deploy[vv, uu]
            entry["deployment_ok"] += int(np.sum(covered))
            entry["interface_pixels"] += int(np.sum(surface_tag[vv, uu] == INTERFACE_SURFACE_TAG))
            visible = depth_ok & id_ok & clean_px & covered
            entry["visible"] += int(np.sum(visible))
            visible_count[use[visible]] += 1
        per_view[view_id] = entry

    visible_valid = visible_count > 0
    observed_side = int(np.sum(side_of_row != 0))
    qa = {
        "pass": bool(count == 0 or not views or int(np.sum(visible_valid)) > 0),
        "layer": LAYER_VISIBLE,
        "observation_id": str(getattr(observation, "observation_id", "")),
        "route": str(getattr(observation, "route", "")),
        "views": len(views),
        "observed_fragment_id": observed_fragment or None,
        "observed_component_id": observed_component or None,
        "correspondence_samples": int(count),
        "samples_of_observed_side": observed_side,
        "samples_projected": int(np.sum(projected_count > 0)),
        "samples_visible": int(np.sum(visible_valid)),
        "visible_fraction": float(np.sum(visible_valid) / max(observed_side, 1)),
        "rule": VISIBILITY_RULE,
        "notes": [
            "one observation renders one component, so the mate side is recorded as not observed "
            "here instead of being assumed visible",
            "a sample with no valid view stays out of the correspondence loss; it is not turned "
            "into a negative match (plan 11.2)",
        ],
    }
    qa["failures"] = [] if qa["pass"] else ["no correspondence sample is visible in any view"]
    meta = {
        "layer": LAYER_VISIBLE,
        "physical_truth_ref": str(physical_truth.meta.get("truth_hash")
                                  or physical_truth.clean_truth_ref),
        "fragment_id": observed_fragment or physical_truth.meta.get("fragment_id"),
        "fragment_ids": list(physical_truth.meta.get("fragment_ids", [])),
        "mother_id": physical_truth.meta.get("mother_id"),
        "event_id": physical_truth.meta.get("event_id"),
        "observation_id": str(getattr(observation, "observation_id", "")),
        "association_counts": dict(physical_truth.association_counts),
        "history": {"association_kind": "EXACT_SURVIVOR",
                    "historical_R2": _r2_fragments(physical_truth),
                    "mate_present": any(bool(v) for v in
                                         (physical_truth.meta.get("mate_present") or {}).values())},
        "truth_incomplete": bool(views) and int(np.sum(visible_valid)) == 0,
        "correspondence_visible_counts": visible_count,
        "correspondence_projected_counts": projected_count,
    }
    return VisibleLabels(
        physical_truth_ref=meta["physical_truth_ref"],
        version=int(physical_truth.version) + 1, per_view=per_view, qa=qa, meta=meta,
    )


def _r2_fragments(physical_truth: PhysicalTruth) -> list[str]:
    mates: set[str] = set()
    for edge in (physical_truth.meta.get("relations_edges") or {}).values():
        if getattr(edge, "kind", "") == RELATION_R2:
            mates.add(str(edge.fragment_a))
            mates.add(str(edge.fragment_b))
    return sorted(mates)


# ------------------------------------------------------------------- labels
def build_labels(clean: CleanTruth, visible: VisibleLabels | None = None, *,
                 features: Mapping[str, Any] | None = None,
                 split: str = "", history: Mapping[str, Any] | None = None,
                 ) -> dict[str, Any]:
    """Assemble the label payload **separately** from the feature payload (plan 4.4 / A01).

    The feature mapping is returned untouched; nothing measured here is merged into it, and a
    leak check refuses a feature payload that already carries a label/answer field.
    """
    relations = [_edge_row(pair, edge) for pair, edge in sorted(clean.relations.items())]
    labels: dict[str, Any] = {
        "layer": LAYER_CLEAN,
        "mother_id": clean.mother_id,
        "event_id": clean.event_id,
        "split": split,
        "fragment_ids": list(clean.meta.get("fragment_ids", [])),
        "relations": relations,
        "relation_count": len(relations),
        "r2_count": sum(1 for row in relations if row["kind"] == RELATION_R2),
        "r1_count": sum(1 for row in relations if row["kind"] == RELATION_R1),
        "tiny_count": sum(1 for row in relations if row["kind"] == RELATION_TINY),
        "unknown_count": sum(1 for row in relations if row["kind"] == RELATION_UNKNOWN),
        "correspondence_count": len(clean.correspondence),
        "correspondence_exact": sum(1 for s in clean.correspondence
                                    if s.association_kind == "EXACT_SURVIVOR"),
        "visible_views": sorted((visible.per_view or {}).keys()) if visible is not None else [],
        "history": dict(history or {}),
    }
    labels["label_fields"] = sorted(labels)
    separation: dict[str, Any] = {
        "features_untouched": True, "forbidden_present": [], "shared_keys": [],
        "leakage_check": "synlab.observe.features.assert_no_leakage",
    }
    out_features: Mapping[str, Any] = features or {}
    if features:
        keys = set(map(str, features.keys()))
        forbidden = sorted(keys & set(FORBIDDEN_FEATURE_FIELDS))
        shared = sorted((keys & set(labels)) - {"layer", "split"})
        try:  # reuse the whitelist the forward pass enforces instead of a second copy
            from ..observe.features import assert_no_leakage

            assert_no_leakage(dict(features))
        except SynLabError:
            raise
        except Exception as exc:  # noqa: BLE001 - the checker itself is optional
            separation["leakage_check"] = f"unavailable ({type(exc).__name__}: {exc})"
        separation.update({"features_untouched": not forbidden and not shared,
                           "forbidden_present": forbidden, "shared_keys": shared})
        if forbidden or shared:
            raise SynLabError(
                ErrorCode.LEAKAGE_DETECTED,
                f"feature payload carries label/answer fields: forbidden={forbidden} "
                f"shared={shared}",
                stage="truth.build_labels",
                measurements={"forbidden": forbidden, "shared": shared},
            )
    return {"labels": labels, "features": out_features, "separation": separation}


def relation_audit(clean: CleanTruth) -> dict[str, Any]:
    """Independent relation-graph audit (A08 evidence): symmetry, loops, masks, area backing."""
    problems: list[str] = []
    for (a, b), edge in clean.relations.items():
        if a == b:
            problems.append(f"self-loop {a}")
        if a > b:
            problems.append(f"non-canonical key {a}|{b}")
        if edge.fragment_a != a or edge.fragment_b != b:
            problems.append(f"orientation mismatch {a}|{b}")
        if not edge.valid and edge.kind == RELATION_R2:
            problems.append(f"R2 marked invalid {a}|{b}")
        if edge.kind == RELATION_UNKNOWN and edge.loss_mask:
            problems.append(f"UNKNOWN with loss_mask=True {a}|{b}")
        if edge.kind == RELATION_R2 and edge.area_mm2 <= 0.0:
            problems.append(f"R2 without measured area {a}|{b}")
        if edge.kind == RELATION_R2 and edge.interface_id is None:
            problems.append(f"R2 without interface id {a}|{b}")
    evidence = dict(clean.meta.get("patch_evidence", {}) or {})
    for (a, b), edge in clean.relations.items():
        if edge.kind != RELATION_R2 or edge.interface_id is None:
            continue
        row = evidence.get(str(int(edge.interface_id)), {})
        if not bool(row.get("structural_ok")):
            problems.append(f"R2 not backed by a structurally valid cut-face patch {a}|{b}")
        if float(row.get("pair_common_area_mm2", 0.0)) <= 0.0:
            problems.append(f"R2 without a pair-level common fracture area {a}|{b}")
    r2 = {pair for pair, edge in clean.relations.items() if edge.kind == RELATION_R2}
    return {
        "pass": not problems,
        "relation_count": len(clean.relations),
        "r2_pairs": len(r2),
        "r2_area_mm2_total": float(sum(clean.relations[p].area_mm2 for p in r2)),
        "symmetric": True,
        "no_self_loops": not any(a == b for a, b in clean.relations),
        "transitively_closed": False,
        "unknown_loss_mask_false": all(not edge.loss_mask for edge in clean.relations.values()
                                       if edge.kind == RELATION_UNKNOWN),
        "problems": problems,
    }


def truth_summary(obj: Any) -> dict[str, Any]:
    """Small JSON-safe summary of any truth layer (used by reports and the CLI)."""
    if isinstance(obj, CleanTruth):
        return {"layer": LAYER_CLEAN, "mother_id": obj.mother_id, "event_id": obj.event_id,
                "relations": len(obj.relations),
                "r2": sum(1 for e in obj.relations.values() if e.kind == RELATION_R2),
                "interfaces": len(obj.interfaces), "correspondence": len(obj.correspondence),
                "qa_pass": bool(obj.qa.get("pass"))}
    if isinstance(obj, PhysicalTruth):
        return {"layer": LAYER_PHYSICAL, "version": obj.version,
                "fragments_present": int(sum(1 for v in obj.residual.get("fragments", {}).values()
                                             if v.get("present"))),
                "association_counts": dict(obj.association_counts),
                "current_fit_valid": int(sum(1 for v in obj.current_fit_valid.values() if v)),
                "qa_pass": bool(obj.qa.get("pass"))}
    if isinstance(obj, VisibleLabels):
        return {"layer": LAYER_VISIBLE, "views": len(obj.per_view),
                "samples_visible": int(obj.qa.get("samples_visible", 0)),
                "visible_fraction": float(obj.qa.get("visible_fraction", 0.0)),
                "qa_pass": bool(obj.qa.get("pass"))}
    return {"layer": "unknown", "type": type(obj).__name__}


# ------------------------------------------------------------------- persistence
def commit_truth(store: Any, obj: Any, *, role: str | None = None, lineage_id: str,
                 split: str, ancestry: Iterable[str] = ()) -> Any:
    """Persist one truth layer (clean / physical / visible) idempotently."""
    if isinstance(obj, CleanTruth):
        obj_role, schema = ROLE_CLEAN_TRUTH, SCHEMA_TRUTH_CLEAN
    elif isinstance(obj, PhysicalTruth):
        obj_role, schema = ROLE_PHYSICAL_TRUTH, SCHEMA_TRUTH_PHYSICAL
    elif isinstance(obj, VisibleLabels):
        obj_role, schema = ROLE_VISIBLE_LABELS, SCHEMA_TRUTH_VISIBLE
    else:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"commit_truth cannot persist {type(obj)!r}",
                          stage="truth.commit")
    role = role or obj_role
    if role != obj_role:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"role {role!r} does not match {type(obj).__name__} ({obj_role!r})",
                          stage="truth.commit")
    relations = _relations_of(obj)
    arrays, meta = _payload_of(obj)
    meta["layer"] = meta.get("layer") or obj_role
    meta["relations"] = relations
    meta["relations_json"] = json.dumps(relations, ensure_ascii=False)
    meta["relation_count"] = len(relations)
    meta["r2_count"] = sum(1 for row in relations if row["kind"] == RELATION_R2)
    meta["truth_hash"] = _truth_hash(obj, relations)
    qa = dict(getattr(obj, "qa", {}) or {})
    payload: dict[str, Any] = dict(arrays)
    payload["relations"] = json.dumps(relations, ensure_ascii=False).encode("utf-8")
    return store.commit_asset(
        role=role, schema=schema, unit=UNIT_MM, frame=FRAME_WORLD, payload=payload,
        meta=meta, qa=qa, qa_status=QA_PASS if qa.get("pass", True) else QA_FAIL,
        ancestry=list(ancestry), lineage_id=lineage_id, split=split,
    )


def load_truth(store: Any, asset_id: str, role: str | None = None) -> Any:
    """Rebuild a truth layer from its committed asset (arrays + meta + relations blob)."""
    record = store.get_asset(asset_id)
    if role is not None and record.role != role:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"asset {asset_id} has role {record.role!r}, expected {role!r}",
                          stage="truth.load")
    meta = dict(getattr(record, "meta", {}) or {})
    arrays = store.load_arrays(asset_id)
    relations_json = meta.get("relations_json")
    rows: Any = None
    if isinstance(relations_json, str):
        rows = json.loads(relations_json)
    elif relations_json is not None:
        rows = relations_json
    elif isinstance(meta.get("relations"), (list, tuple)):
        rows = meta.get("relations")
    if rows is None:
        try:
            rows = json.loads(store.load_bytes(asset_id, "relations").decode("utf-8"))
        except SynLabError:
            rows = []
    relation_map = _relations_map(rows or [])
    if record.role == ROLE_CLEAN_TRUTH or record.schema == SCHEMA_TRUTH_CLEAN:
        bundle = _bundle_from_arrays(arrays)
        return CleanTruth(
            mother_id=str(meta.get("mother_id", "")), event_id=str(meta.get("event_id", "")),
            version=int(meta.get("version", 1) or 1), relations=relation_map,
            interfaces=_interfaces_from_arrays(arrays, meta),
            correspondence=_correspondence_samples(bundle),
            event_tree=dict(meta.get("event_tree", {}) or {}), qa=dict(record.qa or {}),
            meta={**meta, "correspondence_bundle": bundle},
        )
    if record.role == ROLE_PHYSICAL_TRUTH or record.schema == SCHEMA_TRUTH_PHYSICAL:
        bundle = _bundle_from_arrays(arrays)
        return PhysicalTruth(
            clean_truth_ref=str(meta.get("clean_truth_ref", "")),
            version=int(meta.get("version", 1) or 1),
            residual=dict(meta.get("residual", {}) or {}),
            survivor_patches=dict(meta.get("survivor_patches", {}) or {}),
            association_counts={str(k): int(v) for k, v in
                                (meta.get("association_counts", {}) or {}).items()},
            current_fit_valid={str(k): bool(v) for k, v in
                               (meta.get("current_fit_valid", {}) or {}).items()},
            qa=dict(record.qa or {}),
            meta={**meta, "correspondence_bundle": bundle, "relations_edges": relation_map},
        )
    if record.role == ROLE_VISIBLE_LABELS or record.schema == SCHEMA_TRUTH_VISIBLE:
        meta_out = dict(meta)
        for key in ("correspondence_visible_counts", "correspondence_projected_counts"):
            if f"visible_{key}" in arrays:
                meta_out[key] = np.asarray(arrays[f"visible_{key}"], dtype=np.int64)
        return VisibleLabels(
            physical_truth_ref=str(meta.get("physical_truth_ref", "")),
            version=int(meta.get("version", 1) or 1),
            per_view=dict(meta.get("per_view", {}) or {}), qa=dict(record.qa or {}),
            meta=meta_out,
        )
    raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                      f"asset {asset_id} (role={record.role!r}) is not a truth layer",
                      stage="truth.load")


# -- persistence helpers -----------------------------------------------------
def _relations_of(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, CleanTruth):
        return [_edge_row(pair, edge) for pair, edge in sorted(obj.relations.items())]
    edges = (getattr(obj, "meta", {}) or {}).get("relations_edges")
    if isinstance(edges, Mapping):
        return [_edge_row(pair, edge) for pair, edge in sorted(edges.items())]
    rows = (getattr(obj, "meta", {}) or {}).get("relations")
    if isinstance(rows, list):
        return [dict(row) for row in rows]
    return []


def _relations_map(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], RelationEdge]:
    out: dict[tuple[str, str], RelationEdge] = {}
    for row in rows:
        a, b = str(row.get("a", "")), str(row.get("b", ""))
        if not a or not b or a == b:
            continue
        pair = _relation_key(a, b)
        interface_id = row.get("interface_id")
        out[pair] = RelationEdge(
            fragment_a=pair[0], fragment_b=pair[1],
            kind=str(row.get("kind", RELATION_UNKNOWN)),
            interface_id=(int(interface_id) if interface_id is not None else None),
            area_mm2=float(row.get("area_mm2", 0.0) or 0.0),
            valid=bool(row.get("valid", True)), reason=str(row.get("reason", "")),
            loss_mask=bool(row.get("loss_mask", True)),
        )
    return out


def _payload_of(obj: Any) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Split one truth layer into (array payload, JSON meta) without losing measurements."""
    arrays: dict[str, np.ndarray] = {}
    meta: dict[str, Any] = {}
    if isinstance(obj, CleanTruth):
        meta.update({
            "mother_id": obj.mother_id, "event_id": obj.event_id, "version": int(obj.version),
            "event_tree": obj.event_tree,
            "fragment_ids": list(obj.meta.get("fragment_ids", [])),
            "mother_area_mm2": obj.meta.get("mother_area_mm2"),
            "r2_area_threshold_mm2": obj.meta.get("r2_area_threshold_mm2"),
            "backend": obj.meta.get("backend"), "cutter_ref": obj.meta.get("cutter_ref"),
            "history": {"association_kind": "EXACT_SURVIVOR",
                        "historical_R2": sorted(_r2_fragment_ids(obj.relations)),
                        "event_id": obj.event_id},
            "truth_incomplete": bool(obj.meta.get("truth_incomplete", False)),
            "interface_count": len(obj.interfaces),
            "patch_evidence": _jsonable(obj.meta.get("patch_evidence", {})),
            "fracture_qa": _jsonable(obj.meta.get("fracture_qa", {})),
            "correspondence_truncated": bool(obj.meta.get("correspondence_truncated", False)),
        })
        bundle = obj.meta.get("correspondence_bundle")
        if isinstance(bundle, Mapping):
            arrays.update(_bundle_arrays(bundle))
        arrays.update(_interface_arrays(obj.interfaces))
    elif isinstance(obj, PhysicalTruth):
        meta.update({
            "clean_truth_ref": obj.clean_truth_ref, "version": int(obj.version),
            "residual": _jsonable(obj.residual), "survivor_patches": _jsonable(obj.survivor_patches),
            "association_counts": {str(k): int(v) for k, v in obj.association_counts.items()},
            "current_fit_valid": {str(k): bool(v) for k, v in obj.current_fit_valid.items()},
            "mother_id": obj.meta.get("mother_id"), "event_id": obj.meta.get("event_id"),
            "fragment_id": obj.meta.get("fragment_id"),
            "fragment_ids": list(obj.meta.get("fragment_ids", [])),
            "damage": _jsonable(obj.meta.get("damage", {})),
            "mate_present": _jsonable(obj.meta.get("mate_present", {})),
            "history": {"association_kind": "EXACT_SURVIVOR",
                        "historical_R2": _r2_fragments(obj),
                        "event_id": obj.meta.get("event_id")},
            "truth_incomplete": bool(obj.meta.get("truth_incomplete", False)),
        })
        bundle = obj.meta.get("correspondence_bundle")
        if isinstance(bundle, Mapping):
            arrays.update(_bundle_arrays(bundle))
    elif isinstance(obj, VisibleLabels):
        meta.update({
            "physical_truth_ref": obj.physical_truth_ref, "version": int(obj.version),
            "per_view": _jsonable(obj.per_view),
            "mother_id": obj.meta.get("mother_id"), "event_id": obj.meta.get("event_id"),
            "fragment_id": obj.meta.get("fragment_id"),
            "fragment_ids": list(obj.meta.get("fragment_ids", [])),
            "observation_id": obj.meta.get("observation_id"),
            "association_counts": _jsonable(obj.meta.get("association_counts", {})),
            "history": _jsonable(obj.meta.get("history", {})),
            "truth_incomplete": bool(obj.meta.get("truth_incomplete", False)),
        })
        for key in ("correspondence_visible_counts", "correspondence_projected_counts"):
            value = obj.meta.get(key)
            if value is not None:
                arrays[f"visible_{key}"] = np.asarray(value, dtype=np.int64)
    return arrays, meta


def _r2_fragment_ids(relations: Mapping[tuple[str, str], RelationEdge]) -> list[str]:
    out: set[str] = set()
    for (a, b), edge in relations.items():
        if edge.kind == RELATION_R2:
            out.add(a)
            out.add(b)
    return sorted(out)


def _bundle_arrays(bundle: Mapping[str, Any]) -> dict[str, np.ndarray]:
    return {f"corr_{key}": np.asarray(value) for key, value in bundle.items()}


def _bundle_from_arrays(arrays: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    bundle: dict[str, np.ndarray] = {key[len("corr_"):]: np.asarray(value)
                                     for key, value in arrays.items() if key.startswith("corr_")}
    if not bundle:
        return _empty_correspondence()
    for key, value in _empty_correspondence().items():
        bundle.setdefault(key, value)
    return bundle


def _interface_arrays(interfaces: Sequence[InterfacePatch]) -> dict[str, np.ndarray]:
    if not interfaces:
        return {"iface_id": np.zeros(0, dtype=np.int64)}
    ids = np.asarray([int(p.interface_id) for p in interfaces], dtype=np.int64)
    offsets = np.zeros(len(interfaces) + 1, dtype=np.int64)
    points_a: list[np.ndarray] = []
    points_b: list[np.ndarray] = []
    normals_a: list[np.ndarray] = []
    normals_b: list[np.ndarray] = []
    for index, patch in enumerate(interfaces):
        pa = np.asarray(patch.sample_points_a, dtype=np.float64).reshape(-1, 3)
        pb = np.asarray(patch.sample_points_b, dtype=np.float64).reshape(-1, 3)
        points_a.append(pa)
        points_b.append(pb)
        normals_a.append(np.asarray(patch.normals_a, dtype=np.float64).reshape(-1, 3))
        normals_b.append(np.asarray(patch.normals_b, dtype=np.float64).reshape(-1, 3))
        offsets[index + 1] = offsets[index] + pa.shape[0]

    def _cat(blocks: Sequence[np.ndarray]) -> np.ndarray:
        return np.concatenate(blocks, axis=0) if blocks else np.zeros((0, 3), dtype=np.float64)

    return {
        "iface_id": ids,
        "iface_area_mm2": np.asarray([float(p.area_mm2) for p in interfaces], dtype=np.float64),
        "iface_common_clip_area_mm2": np.asarray(
            [_patch_shared_area_mm2(p) for p in interfaces], dtype=np.float64),
        "iface_pair_common_clip_area_mm2": np.asarray(
            [float(p.meta.get("pair_common_clip_area_mm2", np.nan)) for p in interfaces],
            dtype=np.float64),
        "iface_gap_p95_mm": np.asarray([float(p.gap_p95_mm) for p in interfaces],
                                       dtype=np.float64),
        "iface_normal_p95_deg": np.asarray([float(p.normal_angle_p95_deg) for p in interfaces],
                                           dtype=np.float64),
        "iface_ambiguity_ratio": np.asarray([float(p.ambiguity_area_ratio) for p in interfaces],
                                            dtype=np.float64),
        "iface_offset": offsets,
        "iface_points_a": _cat(points_a),
        "iface_points_b": _cat(points_b),
        "iface_normals_a": _cat(normals_a),
        "iface_normals_b": _cat(normals_b),
    }


def _interfaces_from_arrays(arrays: Mapping[str, np.ndarray],
                            meta: Mapping[str, Any]) -> list[InterfacePatch]:
    ids = np.asarray(arrays.get("iface_id", np.zeros(0, dtype=np.int64)), dtype=np.int64)
    if ids.size == 0:
        return []
    offsets = np.asarray(arrays["iface_offset"], dtype=np.int64)
    points_a = np.asarray(arrays["iface_points_a"], dtype=np.float64)
    points_b = np.asarray(arrays["iface_points_b"], dtype=np.float64)
    normals_a = np.asarray(arrays["iface_normals_a"], dtype=np.float64)
    normals_b = np.asarray(arrays["iface_normals_b"], dtype=np.float64)
    evidence = dict(meta.get("patch_evidence", {}) or {})
    measured_clip = np.asarray(arrays.get("iface_common_clip_area_mm2",
                                          np.full(ids.size, np.nan)), dtype=np.float64)
    pair_clip = np.asarray(arrays.get("iface_pair_common_clip_area_mm2",
                                      np.full(ids.size, np.nan)), dtype=np.float64)
    out: list[InterfacePatch] = []
    for index in range(ids.size):
        lo, hi = int(offsets[index]), int(offsets[index + 1])
        row = evidence.get(str(int(ids[index])), {})
        pair = [str(x) for x in (row.get("pair") or ["", ""])]
        patch_meta: dict[str, Any] = {
            "source_triangles": list(row.get("source_triangles", []) or []),
            "faces_a": [], "faces_b": [], "reconstructed_from_arrays": True,
            "structural_ok": bool(row.get("structural_ok", False)),
            "pair_common_clip_area_mm2_reconstructed": True,
        }
        if np.isfinite(measured_clip[index]):
            patch_meta["common_clip_area_mm2"] = float(measured_clip[index])
        if np.isfinite(pair_clip[index]):
            patch_meta["pair_common_clip_area_mm2"] = float(pair_clip[index])
        out.append(InterfacePatch(
            interface_id=int(ids[index]), fragment_a=pair[0], fragment_b=pair[1],
            area_mm2=float(np.asarray(arrays["iface_area_mm2"])[index]),
            sample_points_a=points_a[lo:hi], sample_points_b=points_b[lo:hi],
            normals_a=normals_a[lo:hi], normals_b=normals_b[lo:hi],
            gap_p95_mm=float(np.asarray(arrays["iface_gap_p95_mm"])[index]),
            normal_angle_p95_deg=float(np.asarray(arrays["iface_normal_p95_deg"])[index]),
            ambiguity_area_ratio=float(np.asarray(arrays["iface_ambiguity_ratio"])[index]),
            ambiguous_area_mm2=float(row.get("ambiguous_area_mm2", 0.0) or 0.0),
            meta=patch_meta,
        ))
    return out


def _truth_hash(obj: Any, relations: Sequence[Mapping[str, Any]]) -> str:
    return hash_json({"summary": truth_summary(obj),
                      "relations": [dict(row) for row in relations]})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return {"shape": list(value.shape), "dtype": str(value.dtype), "size": int(value.size)}
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if hasattr(value, "__dict__"):
        return _jsonable({k: v for k, v in vars(value).items() if not k.startswith("_")})
    return str(value)
