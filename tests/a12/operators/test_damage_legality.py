"""Physical-damage legality (``damage_semantics = subset_v2``) -- regression tests.

The A09 defect was: a P03 level-1 result was audited ``QA_FAIL`` with
``DAMAGED_NOT_SUBSET_OF_CLEAN + NON_POSITIVE_VOLUME + NOT_WATERTIGHT``.  Measured root causes,
each locked by one test below:

1. two coincidence *pairs* of opposite-winding triangles with exactly 0.0 mm3 were registered as
   DEBRIS components (``NON_POSITIVE_VOLUME``);
2. the accepted body carried 6 boundary edges forming 2 loops of 50 nm / 23 nm, and
   ``trimesh.repair.fill_holes`` repairs none of them in trimesh 5.1.0 (``NOT_WATERTIGHT``);
3. the subset check used Open3D's approximate signed distance, whose noise floor measured on the
   clean mesh *against itself* is 0.0161 mm / 0.275 % of samples -- a level-0 identity result
   (the component **is** the clean mesh object) failed it, i.e. the criterion was unsatisfiable
   as instrumented.

No tolerance is relaxed by these tests: they assert the shipped thresholds and exact relations.
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from synlab.physical.api import (
    DAMAGE_SEMANTICS,
    MAX_PINHOLE_DIAGONAL_MM,
    apply_damage,
    assemble_damage_bodies,
    audit_physical,
    close_numerical_pinholes,
    register_components,
    subset_outside_stats,
)
from synlab.physical.recipe import DamageRecipe
from synlab.schemas.runtime import PhysicalResult


def cube(extents: float = 20.0) -> trimesh.Trimesh:
    return trimesh.creation.box(extents=(extents, extents, extents))


def nanometre_open_triangle(origin: np.ndarray, size_mm: float = 1e-6) -> trimesh.Trimesh:
    """A single 1 nm triangle: 3 edges used once, bounding box ~1 nm (engine pinhole shape)."""
    vertices = np.asarray(origin, dtype=np.float64) + size_mm * np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    return trimesh.Trimesh(vertices=vertices, faces=np.array([[0, 1, 2]], dtype=np.int64),
                           process=False)


def coincident_zero_volume_pair(origin: np.ndarray, size_mm: float = 1e-5) -> trimesh.Trimesh:
    """Two coincident, oppositely wound triangles: watertight, exactly 0.0 mm3 (engine debris)."""
    vertices = np.asarray(origin, dtype=np.float64) + size_mm * np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    faces = np.array([[0, 1, 2], [0, 2, 1]], dtype=np.int64)
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def cube_with_nanometre_hole(solid: trimesh.Trimesh, size_mm: float = 1e-6
                             ) -> tuple[trimesh.Trimesh, tuple[int, int, int]]:
    """Carve a ``size_mm``-sized triangular hole into one face of ``solid``.

    The face (A, B, C) is replaced by the triangulation of the same triangle *minus* the
    nanometre triangle (P0, P1, P2) inside it, so the body stays a single positive-volume solid
    whose only defect is one boundary loop of three sub-micron edges -- the shape the manifold
    boolean left behind on the L0 P03 body.  Returns the mesh and the hole's vertex indices.
    """
    faces = np.asarray(solid.faces, dtype=np.int64)
    vertices = np.asarray(solid.vertices, dtype=np.float64).copy()
    a, b, c = (int(v) for v in faces[0])
    A, B, C = vertices[[a, b, c]]
    normal = np.cross(B - A, C - A)
    normal /= max(float(np.linalg.norm(normal)), 1e-12)
    e1 = (B - A) / max(float(np.linalg.norm(B - A)), 1e-12)
    e2 = np.cross(normal, e1)
    centroid = (A + B + C) / 3.0
    base = len(vertices)
    p0, p1, p2 = base, base + 1, base + 2
    vertices = np.vstack([vertices, centroid[None, :],
                          (centroid + size_mm * e1)[None, :],
                          (centroid + size_mm * e2)[None, :]])
    patch = np.array([[a, b, p1], [a, p1, p0], [b, c, p2],
                      [b, p2, p1], [c, a, p0], [c, p0, p2]], dtype=np.int64)
    return (trimesh.Trimesh(vertices=vertices, faces=np.vstack([faces[1:], patch]), process=False),
            (p0, p1, p2))


# --------------------------------------------------------------------------------------
# 1. materiality: a body with no measurable volume is not a component
# --------------------------------------------------------------------------------------
def test_zero_volume_engine_debris_is_not_registered_as_a_component():
    solid = cube()
    debris_a = coincident_zero_volume_pair(np.array([30.0, 0.0, 0.0]))
    debris_b = coincident_zero_volume_pair(np.array([0.0, 30.0, 0.0]))
    assert float(abs(debris_a.volume)) == 0.0 and float(abs(debris_b.volume)) == 0.0

    components, representative_map, ledger = register_components(
        [solid, debris_a, debris_b], clean_fragment_id="F_probe",
        source_volume_mm3=float(abs(solid.volume)))

    assert len(components) == 1, [c.component_id for c in components]
    assert ledger["component_count"] == 1
    assert ledger["raw_connected_bodies"] == 3
    assert ledger["non_material_body_count"] == 2
    assert ledger["non_material_body_volume_mm3"] == 0.0
    assert ledger["material_floor_mm3"] > 0.0
    assert ledger["material_floor_overridden"] is False
    assert ledger["conservation_ok"] is True
    assert representative_map["F_probe"] == components[0].component_id


def test_all_debris_still_keeps_the_largest_body_so_the_failure_stays_visible():
    """If nothing is material the result must not become empty (fail visibly, never silently)."""
    tiny = coincident_zero_volume_pair(np.array([0.0, 0.0, 0.0]))
    components, _representative, ledger = register_components(
        [tiny], clean_fragment_id="F_probe", source_volume_mm3=1.0)
    assert len(components) == 1
    assert ledger["material_floor_overridden"] is True


# --------------------------------------------------------------------------------------
# 2. closure: nanometre loops are filled with proof, real holes are left alone
# --------------------------------------------------------------------------------------
def test_close_numerical_pinholes_fills_a_nanometre_loop_without_changing_volume():
    solid = cube()
    hole = nanometre_open_triangle(np.array([0.0, 0.0, 10.0]))
    damaged = trimesh.util.concatenate([solid, hole])
    assert damaged.is_watertight is False
    volume_before = float(abs(damaged.volume))

    closed, report = close_numerical_pinholes(damaged)

    assert report["applied"] is True
    assert report["faces_added"] == 1
    assert report["boundary"]["loops"] == 1
    assert closed.is_watertight is True
    assert closed.is_winding_consistent is True
    assert float(abs(closed.volume)) == pytest.approx(volume_before, abs=1e-9)
    assert len(closed.faces) == len(damaged.faces) + 1


def test_close_numerical_pinholes_refuses_a_hole_larger_than_the_pinhole_scale():
    solid = cube()
    holed = solid.copy()
    holed.update_faces(np.arange(1, len(solid.faces)))     # remove one whole face: a real hole
    holed.remove_unreferenced_vertices()
    assert holed.is_watertight is False

    unchanged, report = close_numerical_pinholes(holed)

    assert report["applied"] is False
    assert unchanged is holed                              # the operator output is not touched
    assert len(unchanged.faces) == len(holed.faces)
    assert report["loops"][0]["fillable"] is False
    assert report["loops"][0]["diagonal_mm"] > MAX_PINHOLE_DIAGONAL_MM


def test_assemble_damage_bodies_drops_debris_then_closes_the_material_body():
    """The measured order: pinholes close only once the coincident zero-volume pair is gone."""
    solid = cube()
    body, (p0, p1, p2) = cube_with_nanometre_hole(solid)
    # the engine's leftover pair shares the hole's vertices (measured on the L0 P03 body)
    faces = np.vstack([np.asarray(body.faces, dtype=np.int64),
                       np.array([[p0, p1, p2], [p0, p2, p1]], dtype=np.int64)])
    raw = trimesh.Trimesh(vertices=np.asarray(body.vertices, dtype=np.float64), faces=faces,
                          process=False)

    # patching first is measured to fail: the pair already uses those edges twice
    unchanged, refused = close_numerical_pinholes(raw)
    assert refused["applied"] is False
    assert unchanged is raw

    bodies, record = assemble_damage_bodies(raw, source_volume_mm3=float(abs(solid.volume)))

    assert record["connected_bodies"] >= 2
    assert record["material_bodies"] == 1
    assert record["non_material_bodies"] >= 1
    assert record["non_material_volume_mm3"] < 1e-9
    assert record["watertight_bodies"] == 1
    assert len(bodies) == 1
    assert bodies[0].is_watertight is True
    # the delivered body keeps the source's material volume (only debris was dropped)
    assert float(abs(bodies[0].volume)) == pytest.approx(float(abs(solid.volume)), rel=1e-9)


# --------------------------------------------------------------------------------------
# 3. the subset instrument: exact float64, tolerance unchanged
# --------------------------------------------------------------------------------------
def test_subset_instrument_is_exact_on_a_body_measured_against_itself():
    solid = cube()
    stats = subset_outside_stats(solid, solid, n_samples=1200, tol_mm=1e-3, seed=0)
    assert stats["outside_points"] == 0
    assert stats["outside_fraction"] == 0.0
    assert stats["max_outside_mm"] < 1e-6
    assert "exact" in stats["instrument"]
    # the superseded instrument is still reported beside the exact one
    assert "approx_open3d" in stats


def test_audit_passes_for_an_identity_result_whose_component_is_the_clean_mesh():
    """The decisive control: this FAILED before the instrument swap (max outside 0.0087 mm)."""
    solid = cube()
    recipe = DamageRecipe(axis_id="P03", variant="smooth_recession_field", level=0,
                          recipe_id="P03_identity", params={"depth_mm": 0.05})
    fragment = type("Fragment", (), {"mesh": solid, "fragment_id": "F_identity",
                                     "meta": {}, "volume_mm3": float(abs(solid.volume))})()
    clean_truth = type("Clean", (), {"mother_id": "M", "event_id": "E", "version": 1})()

    result = apply_damage(clean_truth, fragment, recipe, None)

    assert result.components[0].mesh is solid
    assert result.meta["damage_semantics"] == DAMAGE_SEMANTICS
    audit = audit_physical(result, solid)
    assert audit["status"] == "PASS", audit["failure_codes"]
    assert audit["checks"]["damaged_subset_clean"]["pass"] is True
    assert audit["checks"]["damaged_subset_clean"]["outside_points"] == 0
    assert audit["no_auto_repair"]["geometry_hashes_unchanged"] is True


def test_audit_still_fails_a_body_that_pokes_out_of_the_clean_body():
    """A real subset violation must still be caught (the check was not loosened)."""
    clean = cube()
    protruding = cube()
    protruding.apply_translation((0.0, 0.0, 3.0))            # 3 mm outside the clean body
    result = PhysicalResult(
        mother_id="M", clean_ref="M:E:v1", event_id="E", recipe_id="P03:probe:L1", version=1,
        components=register_components([protruding], clean_fragment_id="F_probe",
                                       source_volume_mm3=float(abs(clean.volume)))[0],
        lost_volume_mm3=0.0, lost_volume_ratio=0.0, representative_map={},
        qa={"ledger": {}, "result_geometry_hash": "sha256:probe"},
        meta={"declared": {"axis_id": "P03", "variant": "probe", "level": 1,
                           "touches_geometry": True},
              "axis_id": "P03", "variant": "probe", "level": 1, "geometry_changed": True,
              "ledger": {}, "measured": {"depth_mm": 0.05},
              "damage_semantics": DAMAGE_SEMANTICS})

    audit = audit_physical(result, clean)

    assert "DAMAGED_NOT_SUBSET_OF_CLEAN" in audit["failure_codes"]
    check = audit["checks"]["damaged_subset_clean"]
    assert check["pass"] is False
    assert check["max_outside_mm"] > 1.0
