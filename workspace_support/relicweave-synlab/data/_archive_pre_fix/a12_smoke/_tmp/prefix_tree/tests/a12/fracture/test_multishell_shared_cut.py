"""A mother made of several interpenetrating shells must still be cut into closed solids.

Failure this pins (measured, ``data/a12/reports/synthesis_functional_survey.json``):
``LIN0000_V10_M11_PAT15`` answered ``FRACTURE_CONSERVATION_FAIL`` -- "M_minus is not watertight
after the boolean (faces=7466)" -- in 2.7 s.  V10 is assembled from three *independent* closed
shells (body + lid dome + lid collar, ``build_vessel(union=False)``) whose overlaps are the
design ("a real volumetric lap, not a point contact"), so the body is not one valid CSG operand:
the winding number of a mesh whose shells interpenetrate is undefined where they overlap, and
Manifold returned a mesh that is geometrically closed but topologically open (M_minus: 69 edges
used by four faces, M_plus: 124).  The same cut done one shell at a time is closed, has the same
volume to 1e-5 mm^3, and leaves a single-shell mother bit for bit unchanged.

The tests below use a synthetic two-shell assembly (two overlapping boxes) because it reproduces
the defect exactly in under a second, plus one real-geometry assertion on the same V10 lineage
the batch failed on.
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from synlab.fracture import booleans as B
from synlab.fracture.api import fracture_event, make_closed_cutter
from synlab.fracture.event import _cut_both_sides
from synlab.fracture.fragment import audit_fracture_result
from synlab.fracture.spec import FractureSpec

PLANE_SPEC = FractureSpec(backend="plane_shared_cut", error_budget_mm=0.01)


class _FakeMother:
    """A minimal mother: ``run_shared_cut``/``audit_fracture_result`` need mesh + id only."""

    def __init__(self, mesh: trimesh.Trimesh, mother_id: str = "synthetic") -> None:
        self.mesh = mesh
        self.mother_id = mother_id


def _edge_use(mesh: trimesh.Trimesh) -> tuple[int, int]:
    edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    counts = np.bincount(np.asarray(mesh.edges_unique_inverse, dtype=np.int64),
                         minlength=edges.shape[0])
    return int(np.sum(counts == 1)), int(np.sum(counts > 2))


def _interpenetrating_pair() -> trimesh.Trimesh:
    """Two boxes overlapping by 9 mm along x, with no pair of coplanar walls.

    Different extents are deliberate: two boxes of *equal* size put four pairs of walls exactly
    coplanar, and the source resolver then reports the whole overlap as ambiguous (measured 35 %
    ambiguous area on equal boxes), which is a property of the test geometry, not of the cut.
    """
    box_a = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
    box_b = trimesh.creation.box(extents=[14.0, 14.0, 14.0])
    box_b.apply_translation([8.0, 0.0, 0.0])
    return trimesh.util.concatenate([box_a, box_b])


def _tagged(mesh: trimesh.Trimesh, mesh_id: float = 1.0) -> B.SourceMesh:
    return B.tag_source(trimesh.Trimesh(vertices=np.asarray(mesh.vertices),
                                        faces=np.asarray(mesh.faces), process=False),
                        mesh_id, "mother")


def _triangle_keys(mesh: trimesh.Trimesh) -> list[tuple[float, ...]]:
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    return sorted(tuple(np.round(np.sort(tri, axis=0).reshape(-1), 6)) for tri in triangles)


def test_mesh_shells_returns_each_part_with_its_parent_face_ids():
    parent = _interpenetrating_pair()
    shells = B.mesh_shells(parent)
    assert len(shells) == 2
    seen: list[int] = []
    for part, ids in shells:
        assert part.is_watertight
        assert part.faces.shape[0] == ids.shape[0]
        # the shell's triangles really are the parent's triangles at those ids: without this the
        # per-shell boolean would report provenance ids that point at another shell's surface
        reference = trimesh.Trimesh(vertices=np.asarray(parent.vertices),
                                    faces=np.asarray(parent.faces)[ids], process=False)
        assert _triangle_keys(part) == _triangle_keys(reference)
        seen.extend(int(i) for i in ids)
    assert sorted(seen) == list(range(np.asarray(parent.faces).shape[0]))


def test_concatenated_result_keeps_every_channel_aligned():
    parent = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
    source = _tagged(parent)
    cutter_box = trimesh.creation.box(extents=[40.0, 40.0, 40.0])
    cutter_box.apply_translation([20.0, 0.0, 0.0])   # half-space x >= 0: both sides non-empty
    cutter = B.tag_source(trimesh.Trimesh(vertices=np.asarray(cutter_box.vertices),
                                          faces=np.asarray(cutter_box.faces), process=False),
                          2.0, "cutter")
    pieces = [B.boolean_difference([source, cutter], label="d1"),
              B.boolean_difference([source, cutter], label="d2")]
    assert all(piece.n_faces > 0 for piece in pieces)
    # the box (x in [-10, 10]) minus the half-space x >= 0 keeps exactly half of its volume
    assert float(abs(pieces[0].mesh.volume)) == pytest.approx(4000.0, rel=1.0e-6)
    joined = B.concat_tagged(pieces, label="joined")
    assert joined.mesh.faces.shape[0] == sum(p.n_faces for p in pieces)
    assert joined.point.shape == joined.mesh.vertices.shape
    assert joined.bary.shape == (joined.mesh.vertices.shape[0], 2)
    # the reconstructed source position must still sit on the output vertex
    residual = np.linalg.norm(joined.point - np.asarray(joined.mesh.vertices, dtype=np.float64),
                              axis=1)
    assert float(np.max(residual)) < 1.0e-4
    assert np.all(joined.source_tri >= 0)


def test_whole_body_boolean_of_interpenetrating_shells_is_not_a_closed_surface():
    """Negative control: the defect the per-shell cut avoids, on the very same cutter."""
    mother = _FakeMother(_interpenetrating_pair())
    cutter = make_closed_cutter(mother, PLANE_SPEC, np.random.default_rng(11))
    cutter_source = B.tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                                 faces=np.asarray(cutter.mesh.faces),
                                                 process=False), 2.0, "cutter")
    whole = B.boolean_intersection([_tagged(mother.mesh), cutter_source], label="M_minus")
    boundary, over = _edge_use(whole.mesh)
    assert not bool(whole.mesh.is_watertight)
    assert over > 0, f"expected non-manifold edges from the whole-body boolean, got {over}"
    assert boundary == 0, "a purely geometric closure still has no boundary edge"


def test_shared_cut_of_an_interpenetrating_assembly_is_closed_and_audited():
    mother = _FakeMother(_interpenetrating_pair())
    cutter = make_closed_cutter(mother, PLANE_SPEC, np.random.default_rng(11))
    source_cutter = B.tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                                 faces=np.asarray(cutter.mesh.faces),
                                                 process=False), 2.0, "cutter")
    minus, plus = _cut_both_sides(_tagged(mother.mesh), source_cutter)
    assert minus.mesh.is_watertight and plus.mesh.is_watertight
    for side in (minus, plus):
        boundary, over = _edge_use(side.mesh)
        assert boundary == 0 and over == 0
        # one piece per shell, i.e. the shells were cut independently and not welded together
        assert len(side.mesh.split(only_watertight=False)) == 2
    # geometric identity with the whole-body answer: the fix is topological, not a different cut
    cut_volume = float(abs(minus.mesh.volume)) + float(abs(plus.mesh.volume))
    assert cut_volume == pytest.approx(float(abs(mother.mesh.volume)), rel=1.0e-6)

    result = fracture_event(mother, PLANE_SPEC, np.random.default_rng(11), event_id="synthetic_E01")
    assert len(result.fragments) == 4
    assert all(f.mesh.is_watertight for f in result.fragments)
    audit = audit_fracture_result(result, mother)
    assert audit["passed"] is True, audit["failures"]
    assert audit["overlap_ratio"] <= audit["overlap_tolerance"]
    assert audit["volume_rel_diff"] <= audit["volume_tolerance"]


def test_single_shell_mother_keeps_the_whole_body_path_bit_for_bit():
    """23 of the 24 vessels are single-shell: their result must not move by a single float."""
    mesh = trimesh.creation.box(extents=[30.0, 30.0, 30.0])
    mother = _FakeMother(mesh)
    cutter = make_closed_cutter(mother, PLANE_SPEC, np.random.default_rng(3))
    source_cutter = B.tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                                 faces=np.asarray(cutter.mesh.faces),
                                                 process=False), 2.0, "cutter")
    source_mother = _tagged(mesh)
    minus, plus = _cut_both_sides(source_mother, source_cutter)
    direct_minus = B.boolean_intersection([source_mother, source_cutter], label="M_minus")
    direct_plus = B.boolean_difference([source_mother, source_cutter], label="M_plus")
    for fixed, direct in ((minus, direct_minus), (plus, direct_plus)):
        assert np.array_equal(np.asarray(direct.mesh.vertices), np.asarray(fixed.mesh.vertices))
        assert np.array_equal(np.asarray(direct.mesh.faces), np.asarray(fixed.mesh.faces))


def test_real_v10_lid_skirt_lineage_is_cut_into_closed_fragments():
    """The lineage the batch failed on, with the frozen plan parameters (``--only 0``)."""
    from synlab.config import load_generation_spec
    from synlab.mothers.api import create_mother
    from synlab.pipeline import derive_named_rngs, plan_generation

    spec = load_generation_spec("configs/a12/next_experiment.yaml")
    plan = plan_generation(spec)
    lineage = next(l for l in plan.lineages if l.mother_index == 0)
    assert lineage.lineage_id == "LIN0000_V10_M11_PAT15"
    rngs = derive_named_rngs(spec.master_seed, lineage.lineage_id)
    mother = create_mother(lineage.vessel_id, lineage.material_id, lineage.params,
                           rngs["shape"], mother_id=lineage.lineage_id)
    assert len(B.mesh_shells(mother.mesh)) == 3
    result = fracture_event(mother, spec.fracture, rngs["cut"],
                            event_id=lineage.event_ids[0])
    assert len(result.fragments) == 6
    assert all(f.mesh.is_watertight for f in result.fragments)
    audit = audit_fracture_result(result, mother)
    assert audit["passed"] is True, audit["failures"]
    assert float(audit["source_coverage"]) >= 0.999
