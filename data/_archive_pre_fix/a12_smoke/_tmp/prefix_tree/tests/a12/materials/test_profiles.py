"""Material profiles, the pure query field and the store round-trip (plan 8.1)."""

from __future__ import annotations

import numpy as np
import pytest

from synlab.errors import ErrorCode, SynLabError
from synlab.materials.api import (UNCALIBRATED_MECHANICS, build_material_profile,
                                  commit_material, default_material_params, load_material,
                                  material_at, material_entry, material_ids, validate_profile)
from synlab.registry import REGISTRY
from synlab.roles import ROLE_MATERIAL_PROFILE, SCHEMA_MATERIAL
from synlab.seeds import make_rng
from synlab.storage.store import AssetStore, QA_PASS

SEED_A = 4242
SEED_B = 77


def reference_profile(material_id: str, *, r_outer_mm: float = 80.0,
                      z_rim_mm: float = 130.0) -> dict:
    """A material profile whose outer reference is set to a documented shell size."""
    profile = build_material_profile(material_id, {}, make_rng(SEED_A, "material", material_id))
    profile["outer_reference"].update({"r_outer_mm": float(r_outer_mm), "r_inner_mm": 0.0,
                                       "z_floor_mm": 0.0, "z_rim_mm": float(z_rim_mm)})
    return profile


def test_twelve_materials_registered():
    ids = material_ids()
    assert ids == [f"M{i:02d}" for i in range(1, 13)]
    for mid in ids:
        entry = REGISTRY.get("material", mid)
        assert entry.param_model is not None, f"{mid} has no parameter model"
        assert entry.builder is not None, f"{mid} has no build entry point"
        assert entry.name, f"{mid} has no display name"


def test_every_material_profile_is_structurally_valid(profiles):
    for mid, profile in profiles.items():
        validate_profile(profile)
        assert profile["material_id"] == mid
        assert profile["schema"] == SCHEMA_MATERIAL
        assert profile["layers"], mid
        assert profile["outer_reference"]["r_outer_mm"] > 0
        assert profile["profile_hash"]


def test_profile_is_deterministic_and_seeded(profiles):
    for mid, profile in profiles.items():
        again = build_material_profile(mid, {}, make_rng(SEED_A, "material", mid))
        assert again["profile_hash"] == profile["profile_hash"], mid
        other = build_material_profile(mid, {}, make_rng(SEED_B, "material", mid))
        # the material statistics are fixed by the material, only the field salt follows the seed
        assert other["profile_hash"] != profile["profile_hash"], mid


def test_materials_differ_in_real_statistics(profiles):
    """The twelve materials must differ in grain / porosity / correlation length / direction."""
    grain = {mid: float(p["stats"]["grain_scale_mm"]) for mid, p in profiles.items()}
    pores = {mid: float(p["appearance"]["pore_amount"]) for mid, p in profiles.items()}
    aggregate = {mid: float(p["stats"]["aggregate_radius_mm"]) for mid, p in profiles.items()}
    fibre = {mid: float(p["stats"].get("fiber_period_mm", 0.0)) for mid, p in profiles.items()}
    direction = {mid: tuple(p["stats"].get("fiber_direction") or ()) for mid, p in profiles.items()}

    assert len(set(grain.values())) >= 8, grain
    assert len(set(pores.values())) >= 5, pores
    assert aggregate["M01"] > 0 and aggregate["M02"] == 0 and aggregate["M08"] > 0
    assert aggregate["M01"] != aggregate["M08"]
    assert fibre["M11"] > 0 and fibre["M10"] > 0 and fibre["M01"] == 0
    assert direction["M08"] and direction["M08"] != direction["M11"]
    assert grain["M01"] > grain["M02"] > grain["M04"], (grain["M01"], grain["M02"], grain["M04"])
    assert pores["M09"] > pores["M03"], (pores["M09"], pores["M03"])
    # glass transmits, everything else does not
    assert float(profiles["M07"]["appearance"]["transmission"]) > 0.5
    assert all(float(profiles[mid]["appearance"]["transmission"]) < 0.1
               for mid in ("M01", "M08", "M11"))


def test_uncalibrated_mechanics_are_unknown(profiles):
    for mid, profile in profiles.items():
        mechanics = profile["mechanics"]
        assert mechanics["status"] == "UNKNOWN", mid
        assert mechanics["reason"], mid
        for key in UNCALIBRATED_MECHANICS:
            assert mechanics.get(key) is None, f"{mid}: {key} must not carry an invented number"
    # a noise amplitude must never be recorded as a mechanical property
    for profile in profiles.values():
        for key, value in profile["mechanics"].items():
            assert key in UNCALIBRATED_MECHANICS or key in ("status", "reason"), key
            assert not isinstance(value, (int, float)) or key in ("status", "reason")


def test_material_at_is_pure_and_deterministic(outer_points):
    profile = reference_profile("M06")
    first = material_at(profile, outer_points, "outer_wall")
    second = material_at(profile, outer_points, "outer_wall")
    for field in ("albedo", "roughness", "grain", "porosity", "ior", "direction",
                  "layer_id", "layer_depth_mm"):
        a = np.asarray(getattr(first, field))
        b = np.asarray(getattr(second, field))
        assert np.array_equal(a, b), field
    # calling with a different tag order/mix must not change the values of the shared points
    mixed = material_at(profile, outer_points, np.array(["outer_wall"] * len(outer_points)))
    assert np.allclose(mixed.albedo, first.albedo)


def test_material_at_is_continuous_across_fragments(outer_points):
    """Two fragments that share a boundary see the same field along it (plan 8.1)."""
    profile = reference_profile("M11")
    boundary = outer_points[::4]
    fragment_a = np.vstack([outer_points[:8], boundary[:3]])
    fragment_b = np.vstack([outer_points[-8:], boundary[:3]])
    sample_a = material_at(profile, fragment_a, "outer_wall")
    sample_b = material_at(profile, fragment_b, "outer_wall")
    tail = len(boundary[:3])
    for field in ("albedo", "roughness", "grain", "porosity", "ior", "direction"):
        a = np.asarray(getattr(sample_a, field))[-tail:]
        b = np.asarray(getattr(sample_b, field))[-tail:]
        assert np.allclose(a, b), f"{field} differs across the fracture boundary"
    # and a single shifted query reproduces the same point exactly
    shifted = material_at(profile, boundary[:3] + np.array([0.0, 0.0, 0.0]), "outer_wall")
    assert np.allclose(shifted.albedo, sample_a.albedo[-tail:])


def test_material_at_rejects_bad_input(outer_points):
    profile = reference_profile("M01")
    with pytest.raises(SynLabError) as info:
        material_at(profile, np.zeros((3, 2)), "outer_wall")
    assert info.value.code == ErrorCode.SCHEMA_INVALID
    with pytest.raises(SynLabError) as info:
        material_at(profile, np.array([[np.nan, 0.0, 0.0]]), "outer_wall")
    assert info.value.code == ErrorCode.SCHEMA_INVALID
    with pytest.raises(SynLabError) as info:
        material_at({"material_id": "M01"}, outer_points, "outer_wall")
    assert info.value.code == ErrorCode.SCHEMA_INVALID


def test_new_surfaces_expose_the_body_not_the_coating():
    """Plan 8.2: a fresh section must not reuse the decoration of the original outer surface."""
    profile = reference_profile("M06", r_outer_mm=80.0)  # pottery + a real glaze layer
    glaze = float(profile["layers"][0]["thickness_mm"])
    body_layer = int(profile["layer_ids"][-1])
    glaze_layer = int(profile["layer_ids"][0])
    assert glaze > 0 and glaze_layer != body_layer
    # points inside the glaze band (outer), and points below it (body)
    angles = np.linspace(0.0, 0.9 * np.pi, 6)
    outer_points = np.column_stack([
        (80.0 - 0.5 * glaze) * np.cos(angles), (80.0 - 0.5 * glaze) * np.sin(angles),
        np.full(angles.size, 40.0)])
    deep_points = np.column_stack([
        (80.0 - 8.0 * glaze) * np.cos(angles), (80.0 - 8.0 * glaze) * np.sin(angles),
        np.full(angles.size, 40.0)])
    outer = material_at(profile, outer_points, "outer_wall")
    deep = material_at(profile, deep_points, "outer_wall")
    inner = material_at(profile, outer_points, "inner_wall")
    interface = material_at(profile, outer_points, "interface")
    assert set(np.unique(outer.layer_id).tolist()) == {glaze_layer}
    assert set(np.unique(deep.layer_id).tolist()) == {body_layer}
    assert set(np.unique(inner.layer_id).tolist()) == {body_layer}
    assert set(np.unique(interface.layer_id).tolist()) == {body_layer}
    assert not np.allclose(outer.albedo, inner.albedo), "the glaze shares the body colour"
    assert np.all(inner.layer_depth_mm == 0.0)
    assert np.all(outer.layer_depth_mm >= 0.0)
    assert np.all(interface.roughness >= inner.roughness.min())


def test_layer_depth_selects_the_outer_layer(profiles):
    profile = reference_profile("M04", r_outer_mm=80.0)  # porcelain: a thin glaze
    glaze = float(profile["layers"][0]["thickness_mm"])
    assert glaze > 0
    points = np.array([[80.0, 0.0, 40.0], [80.0 - 0.5 * glaze, 0.0, 40.0],
                       [80.0 - 5.0 * glaze, 0.0, 40.0]])
    sample = material_at(profile, points, "outer_wall")
    assert sample.layer_id[0] == profile["layer_ids"][0]
    assert sample.layer_id[1] == profile["layer_ids"][0]
    assert sample.layer_id[2] == profile["layer_ids"][-1]
    assert sample.layer_depth_mm[0] < sample.layer_depth_mm[2]
def test_material_fields_stay_in_range(profiles, outer_points):
    for mid, profile in profiles.items():
        sample = material_at(profile, outer_points, "outer_wall")
        assert np.all(sample.albedo >= 0.0) and np.all(sample.albedo <= 1.0), mid
        assert np.all(sample.roughness > 0.0) and np.all(sample.roughness <= 1.0), mid
        assert np.all(sample.grain >= 0.0) and np.all(sample.grain <= 1.0), mid
        assert np.all(sample.porosity >= 0.0) and np.all(sample.porosity <= 1.0), mid
        assert np.all(sample.ior >= 1.0) and np.all(sample.ior <= 3.0), mid
        norms = np.linalg.norm(np.asarray(sample.direction, dtype=np.float64), axis=1)
        assert np.allclose(norms, 1.0), mid


def test_commit_and_load_round_trip(tmp_path):
    store = AssetStore(tmp_path / "store")
    profile = build_material_profile("M08", {}, make_rng(SEED_A, "material", "M08"))
    record = commit_material(store, profile, lineage_id="LIN0007", split="train")
    assert record.role == ROLE_MATERIAL_PROFILE
    assert record.schema == SCHEMA_MATERIAL
    assert record.qa_status == QA_PASS
    assert record.meta["material_id"] == "M08"
    loaded = load_material(store, record.asset_id)
    assert loaded["material_id"] == "M08"
    assert loaded["profile_hash"] == profile["profile_hash"]
    assert loaded["stats"] == profile["stats"]
    assert loaded["layers"] == profile["layers"]
    assert loaded["mechanics"]["status"] == "UNKNOWN"
    # the loaded profile keeps producing the same field
    points = np.array([[40.0, 0.0, 30.0], [50.0, 0.0, 30.0]])
    before = material_at(profile, points, "outer_wall")
    after = material_at(loaded, points, "outer_wall")
    assert np.allclose(before.albedo, after.albedo)
    assert np.allclose(before.grain, after.grain)


def test_commit_rejects_an_invalid_profile(tmp_path):
    store = AssetStore(tmp_path / "store")
    profile = build_material_profile("M01", {}, make_rng(SEED_A, "material", "M01"))
    broken = dict(profile)
    broken["layers"] = []
    with pytest.raises(SynLabError) as info:
        commit_material(store, broken, lineage_id="LIN", split="train")
    assert info.value.code == ErrorCode.SCHEMA_INVALID


def test_material_params_are_validated():
    with pytest.raises(SynLabError) as info:
        build_material_profile("M01", {"not_a_field": 1.0}, make_rng(1, "material"))
    assert info.value.code == ErrorCode.SCHEMA_INVALID
    with pytest.raises(SynLabError) as info:
        build_material_profile("M99", {}, make_rng(1, "material"))
    assert info.value.code == ErrorCode.SCHEMA_INVALID
    entry = material_entry("M11")
    assert "ring_period_mm" in entry.param_model.model_fields
    params = default_material_params("M11")
    coarse = build_material_profile("M11", {**params, "ring_period_mm": 20.0},
                                    make_rng(SEED_A, "material"))
    fine = build_material_profile("M11", {**params, "ring_period_mm": 1.5},
                                  make_rng(SEED_A, "material"))
    assert coarse["stats"]["fiber_period_mm"] != fine["stats"]["fiber_period_mm"]
    points = np.array([[40.0, 0.0, 30.0], [41.0, 0.0, 30.0]])
    assert not np.allclose(material_at(coarse, points, "outer_wall").grain,
                           material_at(fine, points, "outer_wall").grain)


def test_profiles_are_not_measured_distribution_claims(profiles):
    for mid, profile in profiles.items():
        assert profile["provenance"]["source_kind"] == "SYNTHETIC"
        assert "not a measured distribution" in profile["provenance"]["note"], mid
        assert "cut_statistics" in profile["stats"], mid
        assert profile["stats"]["cut_statistics"]["note"], mid
