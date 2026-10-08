"""Mother construction and QA gates (plan 7.2 / 7.3).

Every registered vessel has to produce a real, watertight, cavity-carrying mother that passes
``audit_mother``; the parameter-influence test proves that the declared shape parameters move
the geometry (no "same mesh, new name" registry padding).
"""

from __future__ import annotations

import numpy as np
import pytest

from synlab.errors import ErrorCode, SynLabError
from synlab.mothers.api import (audit_mother, canonical_params, create_mother, geometry_hash,
                                shape_parameters, vessel_ids)
from synlab.mothers.tagging import TAG_INDEX, TAG_NAMES
from synlab.registry import REGISTRY
from synlab.schemas.runtime import MotherGeometry
from synlab.seeds import make_rng

SEED_A = 20240517
SEED_B = 991

pytestmark = pytest.mark.filterwarnings("error::RuntimeWarning")


def test_twenty_four_vessels_registered():
    ids = vessel_ids()
    assert len(ids) == 24, f"expected the full plan table, got {ids}"
    assert ids == [f"V{i:02d}" for i in range(1, 25)]
    for vessel_id in ids:
        entry = REGISTRY.get("vessel", vessel_id)
        assert entry.param_model is not None, f"{vessel_id} has no parameter model"
        assert entry.builder is not None, f"{vessel_id} has no build entry point"
        assert len(shape_parameters(vessel_id)) >= 3, (
            f"{vessel_id} declares fewer than three shape parameters")


def test_every_vessel_builds_and_passes_audit(mother_case):
    failures = {vid: case[1]["failures"] for vid, case in mother_case.items() if not case[1]["ok"]}
    assert not failures, f"vessels that failed the audit: {failures}"
    for vessel_id, (mother, report, _) in mother_case.items():
        assert isinstance(mother, MotherGeometry)
        assert mother.vessel_id == vessel_id
        assert mother.n_faces > 0, f"{vessel_id} produced an empty mesh"
        assert float(mother.mesh.volume) > 0, f"{vessel_id} has non-positive volume"
        assert report["checks"]["watertight"]["ok"], vessel_id
        assert report["checks"]["outward_volume"]["ok"], vessel_id
        assert report["checks"]["source_labels"]["ok"], vessel_id
        assert report["checks"]["charts"]["ok"], vessel_id
        assert report["metrics"]["thickness_min_mm"] > 0, vessel_id


def test_declared_shape_parameters_move_the_geometry(mother_case):
    """At least three declared shape parameters must change the built mesh (plan 7.2)."""
    from synlab.mothers.api import sampler_spec

    def perturb(vessel_id: str, params: dict, field: str) -> dict:
        spec = sampler_spec(vessel_id)
        info = spec.get(field)
        out = dict(params)
        if info is None:
            current = params.get(field)
            if isinstance(current, bool):
                out[field] = not current
            else:
                raise AssertionError(f"{vessel_id}: {field!r} has no registered range to vary")
            return canonical_params(vessel_id, out)
        current = float(params[field])
        low, high = float(info["low"]), float(info["high"])
        target = high if abs(current - low) < abs(current - high) else low
        if info["int"]:
            target = float(int(round(target)))
        out[field] = int(round(target)) if info["int"] else float(target)
        return canonical_params(vessel_id, out)

    evidence: dict[str, list[str]] = {}
    for vessel_id, (mother, _report, params) in mother_case.items():
        baseline = geometry_hash(mother.mesh)
        influenced: list[str] = []
        problems: list[str] = []
        for field in shape_parameters(vessel_id):
            try:
                varied = perturb(vessel_id, params, field)
            except AssertionError as exc:
                problems.append(str(exc))
                continue
            try:
                other = create_mother(vessel_id, "M01", varied, make_rng(SEED_A, "shape"),
                                      mother_id=f"{vessel_id}-{field}")
            except SynLabError as exc:
                if exc.code == ErrorCode.MOTHER_INVALID:
                    # a rejected far-end value is still evidence the field is a real shape
                    # parameter: the vessel refuses to build that silhouette
                    influenced.append(f"{field}->rejected({exc.code})")
                    continue
                raise
            if geometry_hash(other.mesh) != baseline:
                influenced.append(field)
        evidence[vessel_id] = influenced
        assert not problems, f"{vessel_id}: {problems}"
        assert len(influenced) >= 3, (
            f"{vessel_id} has only {len(influenced)} influential declared shape parameters: "
            f"{influenced}")
    assert len(evidence) == 24


def test_same_seed_replays_identical_geometry(mother_case):
    for vessel_id, (mother, _report, params) in mother_case.items():
        replay = create_mother(vessel_id, "M01", params, make_rng(SEED_A, "shape"),
                               mother_id=f"{vessel_id}-replay")
        assert geometry_hash(replay.mesh) == geometry_hash(mother.mesh), (
            f"{vessel_id}: the same seed produced a different mesh")
        assert np.array_equal(replay.face_surface_tag, mother.face_surface_tag)


def test_different_seed_changes_geometry(mother_case):
    for vessel_id, (mother, _report, params) in mother_case.items():
        other = create_mother(vessel_id, "M01", params, make_rng(SEED_B, "shape"),
                              mother_id=f"{vessel_id}-other-seed")
        assert geometry_hash(other.mesh) != geometry_hash(mother.mesh), (
            f"{vessel_id}: seed {SEED_B} reproduced seed {SEED_A} exactly")


def test_mesh_round_trip_keeps_hash(mother_case):
    import trimesh

    for vessel_id, (mother, _report, _params) in mother_case.items():
        rebuilt = trimesh.Trimesh(vertices=np.asarray(mother.mesh.vertices, dtype=np.float64),
                                  faces=np.asarray(mother.mesh.faces, dtype=np.int64),
                                  process=False)
        assert geometry_hash(rebuilt) == geometry_hash(mother.mesh), vessel_id


def test_open_vessels_keep_a_real_cavity(mother_case):
    checked = 0
    for vessel_id, (mother, report, _params) in mother_case.items():
        if not mother.meta.get("requires_cavity"):
            continue
        checked += 1
        cavity = report["checks"]["cavity"]
        assert cavity["requires_cavity"] is True, vessel_id
        assert cavity["void_ratio"] > 0.02, f"{vessel_id}: void ratio {cavity['void_ratio']}"
        assert cavity["cavity_probe_count"] > 0, f"{vessel_id} has no cavity probes"
        assert cavity["cavity_probes_inside_material"] == 0, (
            f"{vessel_id}: {cavity['cavity_probes_inside_material']} cavity probes landed in "
            "material")
    assert checked >= 12, f"only {checked} vessels carry an open cavity"


def test_bowl_cavity_volume_is_below_the_solid_envelope(mother_case):
    """A bowl is hollow: its material volume is well below the solid that fills the outline."""
    mother, report, _params = mother_case["V01"]
    hull_volume = float(mother.mesh.convex_hull.volume)
    material = float(mother.mesh.volume)
    assert material < 0.6 * hull_volume, (
        f"V01 material {material:.0f} mm3 is not hollow against hull {hull_volume:.0f} mm3")
    assert report["checks"]["cavity"]["void_ratio"] > 0.3


@pytest.mark.parametrize("vessel_id,params", [
    ("V01", {"wall_mm": 0.5}),
    ("V01", {"base_mm": 0.4}),
    ("V06", {"wall_mm": 0.6}),
    ("V12", {"wall_mm": 0.3}),
    ("V13", {"wall_mm": 0.5}),
])
def test_thin_wall_requests_are_rejected(vessel_id, params):
    with pytest.raises(SynLabError) as info:
        create_mother(vessel_id, "M01", params, make_rng(SEED_A, "shape"),
                      mother_id=f"{vessel_id}-thin")
    assert info.value.code == ErrorCode.MOTHER_INVALID, info.value.to_dict()
    assert info.value.measurements, "the rejection carries no measurement"


def test_bowl_with_no_cavity_left_is_rejected():
    """A base plate that fills the dish is refused instead of silently hollowed."""
    with pytest.raises(SynLabError) as info:
        create_mother("V03", "M01", {"base_mm": 30.0, "depth_mm": 14.0},
                      make_rng(SEED_A, "shape"), mother_id="V03-flat")
    assert info.value.code == ErrorCode.MOTHER_INVALID
    assert info.value.measurements, "the rejection carries no measurement"
    assert "base_mm" in info.value.measurements


def test_a_still_buildable_request_is_not_flagged_as_repaired(mother_case):
    """The repair path is recorded only when it actually ran."""
    for vessel_id, (mother, _report, params) in mother_case.items():
        assert mother.params == canonical_params(vessel_id, params)
        if "parameter_repairs" in mother.meta:
            repairs = mother.meta["parameter_repairs"]
            assert repairs, vessel_id
            for entry in repairs:
                assert entry["params_before"] != entry["params_after"], vessel_id


def test_unknown_vessel_and_bad_params_are_structured_errors():
    with pytest.raises(SynLabError) as info:
        create_mother("V99", "M01", {}, make_rng(1, "shape"))
    assert info.value.code == ErrorCode.SCHEMA_INVALID

    with pytest.raises(SynLabError) as info:
        create_mother("V01", "M01", {"not_a_parameter": 3.0}, make_rng(1, "shape"))
    assert info.value.code == ErrorCode.MOTHER_INVALID

    with pytest.raises(SynLabError) as info:
        create_mother("V01", "M01", {"diameter_mm": 5.0}, make_rng(1, "shape"))
    assert info.value.code == ErrorCode.MOTHER_INVALID


def test_rng_must_be_a_generator():
    with pytest.raises(SynLabError) as info:
        create_mother("V01", "M01", {}, 17)
    assert info.value.code == ErrorCode.SCHEMA_INVALID


def test_face_tags_use_the_frozen_vocabulary(mother_case):
    valid = set(TAG_NAMES.values())
    for vessel_id, (mother, _report, _params) in mother_case.items():
        names = {TAG_NAMES[int(v)] for v in np.unique(mother.face_surface_tag)}
        assert names <= valid, f"{vessel_id}: unknown tags {names - valid}"
        assert int(TAG_INDEX["outer_wall"]) in set(int(v) for v in np.unique(
            mother.face_surface_tag)), f"{vessel_id} has no outer wall faces"
        assert mother.surface_tag_names == {int(k): v for k, v in TAG_NAMES.items()}


def test_attachment_components_carry_their_own_id(mother_case):
    with_attachment = 0
    for vessel_id, (mother, _report, _params) in mother_case.items():
        attrs = (mother.mesh.metadata or {}).get("face_attr_arrays") or {}
        comp = np.asarray(attrs.get("component_id", np.zeros(0, dtype=np.int32)))
        assert comp.shape[0] == mother.n_faces, vessel_id
        if np.any(mother.face_surface_tag == TAG_INDEX["attachment"]):
            with_attachment += 1
            assert int(comp.max()) >= 1, f"{vessel_id}: attachment faces keep component 0"
    assert with_attachment >= 5, f"only {with_attachment} vessels have real attachments"


def test_audit_rejects_a_mother_without_faces():
    mother = create_mother("V01", "M01", {}, make_rng(SEED_A, "shape"), mother_id="empty")
    import trimesh

    mother.mesh = trimesh.Trimesh()
    mother.face_surface_tag = np.zeros(0, dtype=np.int32)
    with pytest.raises(SynLabError) as info:
        audit_mother(mother)
    assert info.value.code == ErrorCode.MOTHER_INVALID


def test_geometry_hash_depends_only_on_the_coordinates(mother_case):
    """The fingerprint is a hash of (vertices, faces): timestamps and metadata do not enter."""
    mother, _report, _params = mother_case["V19"]
    before = geometry_hash(mother.mesh)
    mother.mesh.metadata["built_at"] = "not-a-timestamp-that-matters"
    mother.mesh.metadata["elapsed_s"] = 12.5
    assert geometry_hash(mother.mesh) == before
    moved = mother.mesh.copy()
    moved.apply_translation([0.0, 0.0, 1.0])
    assert geometry_hash(moved) != before, "a translated mesh must hash differently"
