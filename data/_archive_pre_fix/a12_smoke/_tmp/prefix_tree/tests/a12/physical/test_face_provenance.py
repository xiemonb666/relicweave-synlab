"""Face-level provenance of a damaged body (``synlab.physical.api``).

Fixtures only: a tagged box stands in for the clean fragment, so every class boundary can be
checked by hand.  The published measurements on real assets are in
``docs/a12/fracture_surface_signal.md`` and ``data/a12/reports/fracture_surface_signal/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.physical.api import (  # noqa: E402
    ORIGIN_COLOCATION_MAX_MM,
    ORIGIN_COLOCATION_MIN_MM,
    ORIGIN_PROVENANCE_VERSION,
    apply_damage,
    attach_face_provenance,
    classify_face_origin,
    origin_colocation_tolerance_mm,
)
from synlab.physical.recipe import DamageRecipe  # noqa: E402
from synlab.schemas.runtime import (  # noqa: E402
    ORIGIN_AMBIGUOUS,
    ORIGIN_INTERFACE,
    ORIGIN_MOTHER_SURFACE,
    PhysicalComponent,
    PhysicalResult,
)
from synlab.storage.mesh_io import face_attrs, mesh_arrays, with_face_attrs  # noqa: E402

BOX = (20.0, 20.0, 10.0)


def tagged_box(interface_faces: int = 4) -> tuple[trimesh.Trimesh, np.ndarray, np.ndarray]:
    """A 20x20x10 box whose first ``interface_faces`` faces carry the interface channel."""
    mesh = trimesh.creation.box(extents=list(BOX))
    n = len(mesh.faces)
    origin = np.zeros(n, dtype=np.uint8)
    origin[:interface_faces] = ORIGIN_INTERFACE
    interface_id = np.full(n, -1, dtype=np.int32)
    interface_id[:interface_faces] = 0
    with_face_attrs(mesh, origin_kind=origin, interface_id=interface_id)
    return mesh, origin, interface_id


def parallel_offset(mesh: trimesh.Trimesh, face: int, offset_mm: float) -> np.ndarray:
    """One triangle parallel to ``face``, displaced by ``offset_mm`` along its own normal."""
    vertices = np.asarray(mesh.vertices, dtype=np.float64)[np.asarray(mesh.faces)[face]]
    normal = np.asarray(mesh.face_normals, dtype=np.float64)[face]
    return np.asarray(vertices - float(offset_mm) * normal[None, :])


def with_extra_triangle(mesh: trimesh.Trimesh, triangle: np.ndarray) -> trimesh.Trimesh:
    vertices = np.vstack([np.asarray(mesh.vertices, dtype=np.float64),
                          np.asarray(triangle, dtype=np.float64)])
    faces = np.vstack([np.asarray(mesh.faces, dtype=np.int64),
                       np.asarray([[len(mesh.vertices), len(mesh.vertices) + 1,
                                    len(mesh.vertices) + 2]], dtype=np.int64)])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


# ------------------------------------------------------------------ the tolerance rule
def test_colocation_tolerance_is_cell_plus_recession_and_bounded() -> None:
    assert origin_colocation_tolerance_mm(spacing_mm=None) == pytest.approx(
        ORIGIN_COLOCATION_MIN_MM)
    assert origin_colocation_tolerance_mm(spacing_mm=0.5,
                                          realized_recession_mm=0.05) == pytest.approx(0.35)
    # a thin wall caps the tolerance at half of it, so a face cannot map across the wall
    assert origin_colocation_tolerance_mm(spacing_mm=1.0, min_wall_mm=0.4) == pytest.approx(0.2)
    # and it never grows past the declared maximum
    assert origin_colocation_tolerance_mm(spacing_mm=10.0,
                                          realized_recession_mm=5.0) == pytest.approx(
        ORIGIN_COLOCATION_MAX_MM)


# ------------------------------------------------------------------ the three classes
def test_a_copy_of_the_source_keeps_its_own_channels() -> None:
    clean, origin, interface_id = tagged_box()
    damaged = trimesh.Trimesh(vertices=clean.vertices.copy(), faces=clean.faces.copy(),
                              process=False)
    classes, ids, report = classify_face_origin(
        damaged, clean, origin=origin, interface_id=interface_id,
        roi_ids=np.flatnonzero(origin == ORIGIN_INTERFACE), tol_mm=1e-6, roi_tol_mm=1.0)
    assert report["mapped_fraction"] == pytest.approx(1.0)
    assert np.array_equal(classes, origin)
    assert np.array_equal(ids, interface_id)
    assert report["classes"][str(ORIGIN_AMBIGUOUS)] == 0
    assert report["version"] == ORIGIN_PROVENANCE_VERSION


def test_a_new_face_in_the_declared_roi_band_is_an_interface_face() -> None:
    clean, origin, interface_id = tagged_box()
    roi = np.flatnonzero(origin == ORIGIN_INTERFACE)
    damaged = with_extra_triangle(clean, parallel_offset(clean, int(roi[0]), 0.2))
    classes, ids, report = classify_face_origin(
        damaged, clean, origin=origin, interface_id=interface_id, roi_ids=roi,
        tol_mm=0.05, roi_tol_mm=0.5)
    assert classes[-1] == ORIGIN_INTERFACE
    assert ids[-1] == 0
    assert report["born_in_declared_roi"] == 1
    # the same face without a declared ROI band is *not* claimed as an interface face
    classes2, _ids2, report2 = classify_face_origin(
        damaged, clean, origin=origin, interface_id=interface_id, roi_ids=roi,
        tol_mm=0.05, roi_tol_mm=0.0)
    assert classes2[-1] == ORIGIN_AMBIGUOUS
    assert report2["classes"][str(ORIGIN_AMBIGUOUS)] == 1
    assert report2["ambiguous_reasons"]["new_face_outside_declared_roi_band"] == 1


def test_a_face_crossing_the_source_surface_is_not_mapped() -> None:
    clean, origin, interface_id = tagged_box()
    face = int(np.flatnonzero(origin == ORIGIN_MOTHER_SURFACE)[0])
    centre = np.asarray(clean.triangles_center, dtype=np.float64)[face]
    # a sliver standing perpendicular to the wall, with its centroid exactly on the wall
    triangle = np.asarray([centre + [0.0, 0.0, 2.0], centre + [2.0, 0.0, -1.0],
                           centre + [-2.0, 0.0, -1.0]])
    damaged = with_extra_triangle(clean, triangle)
    classes, _ids, report = classify_face_origin(
        damaged, clean, origin=origin, interface_id=interface_id,
        roi_ids=np.flatnonzero(origin == ORIGIN_INTERFACE), tol_mm=1.0, roi_tol_mm=0.0)
    assert classes[-1] == ORIGIN_AMBIGUOUS
    assert report["mapped_to_clean_face"] == len(clean.faces)
    assert report["distance_mm"]["mapped_max"] <= 1.0


def test_a_clean_channel_of_the_wrong_length_claims_nothing() -> None:
    clean, origin, interface_id = tagged_box()
    classes, ids, report = classify_face_origin(
        clean, clean, origin=origin[:-1], interface_id=interface_id, tol_mm=1.0, roi_tol_mm=1.0)
    assert np.all(classes == ORIGIN_AMBIGUOUS)
    assert np.all(ids == -1)
    assert "failure" in report
    assert report["classes"][str(ORIGIN_AMBIGUOUS)] == len(clean.faces)


# ------------------------------------------------------------------ attach + persistence
def _physical_result(mesh: trimesh.Trimesh, **meta: object) -> PhysicalResult:
    component = PhysicalComponent(
        component_id="F1#c0", clean_fragment_id="F1", mesh=mesh,
        volume_mm3=float(abs(mesh.volume)), is_representative=True, status="CORE",
        survivor_patch_ref=None, meta={"is_contamination": bool(meta.pop("contamination", False))})
    return PhysicalResult(
        mother_id="M", clean_ref="M:E1:v1", event_id="E1", recipe_id="P03:depth_mm:L1", version=1,
        components=[component], lost_volume_mm3=0.0, lost_volume_ratio=0.0,
        representative_map={"F1": "F1#c0"}, physical_truth=None,
        qa={"status": "PASS"},
        meta={"identity": False, "axis_id": "P03", "variant": "smooth_recession_field", "level": 1,
              "geometry_changed": True,
              "declared": {"axis_id": "P03", "variant": "smooth_recession_field", "level": 1,
                           "params": {"depth_mm": 0.05}, "roi": {"kind": "interface"}},
              "measured": {"realized_max_recession_mm": 0.2, "min_thickness_mm": 5.0},
              "ledger": {}, **meta})


def test_attach_face_provenance_writes_both_channels() -> None:
    clean, _origin, _ids = tagged_box()
    roi_face = 0
    damaged = with_extra_triangle(clean, parallel_offset(clean, roi_face, 0.2))
    result = _physical_result(damaged)
    fragment = type("Frag", (), {"mesh": clean, "fragment_id": "F1"})()
    report = attach_face_provenance(result, clean_mesh=clean, fragment=fragment, spacing_mm=0.5,
                                   halo_mm=3.0)
    component = result.components[0]
    attrs = face_attrs(component.mesh)
    assert set(attrs) >= {"origin_kind", "interface_id"}
    assert attrs["origin_kind"].shape[0] == len(component.mesh.faces)
    assert attrs["interface_id"].shape[0] == len(component.mesh.faces)
    assert attrs["origin_kind"][-1] == ORIGIN_INTERFACE
    assert report["totals"][str(ORIGIN_INTERFACE)] == int(
        np.count_nonzero(attrs["origin_kind"] == ORIGIN_INTERFACE))
    assert report["totals"][str(ORIGIN_INTERFACE)] > 0
    assert report["roi"]["roi_kind"] == "interface"
    # floor 0.05 + half of the declared 0.5 mm cell + the measured 0.2 mm recession
    assert report["tol_mm"] == pytest.approx(0.5)
    # the committed payload names the channels exactly as the census expects them
    arrays = mesh_arrays(component.mesh)
    assert "face__origin_kind" in arrays and "face__interface_id" in arrays
    counts = np.bincount(np.asarray(arrays["face__origin_kind"], dtype=np.int64))
    assert int(counts[ORIGIN_INTERFACE]) > 0


def test_a_contamination_body_is_never_mapped_onto_the_surface_it_covers() -> None:
    clean, _origin, _ids = tagged_box()
    shell = trimesh.Trimesh(vertices=clean.vertices.copy(), faces=clean.faces.copy(),
                            process=False)   # perfectly co-located with the clean surface
    result = _physical_result(shell, contamination=True)
    fragment = type("Frag", (), {"mesh": clean, "fragment_id": "F1"})()
    report = attach_face_provenance(result, clean_mesh=clean, fragment=fragment, spacing_mm=0.5,
                                   halo_mm=3.0)
    entry = report["components"]["F1#c0"]
    assert entry["class"] == "CONTAMINATION_UNMAPPED"
    assert np.all(face_attrs(result.components[0].mesh)["origin_kind"] == ORIGIN_AMBIGUOUS)
    assert report["totals"][str(ORIGIN_MOTHER_SURFACE)] == 0
    assert report["totals"][str(ORIGIN_AMBIGUOUS)] == len(shell.faces)


def test_level_zero_records_that_it_attached_nothing() -> None:
    clean, origin, interface_id = tagged_box()
    fragment = type("Frag", (), {"mesh": clean, "fragment_id": "F1"})()
    result = apply_damage(None, fragment, DamageRecipe(axis_id="P03", level=0, variant="depth_mm"))
    assert result.meta["face_provenance"]["attached"] is False
    assert result.qa["face_provenance"]["attached"] is False
    assert result.components[0].mesh is clean        # the identity contract: same object
    # the source's own channels are returned byte-identical, not replaced by anything
    assert np.array_equal(np.asarray(face_attrs(clean)["origin_kind"]), origin)
    assert np.array_equal(np.asarray(face_attrs(clean)["interface_id"]), interface_id)
    assert result.meta["geometry_changed"] is False
