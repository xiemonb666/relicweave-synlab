"""The diversity contract, as assertions instead of prose.

These tests exist because "the data is more varied now" is not a checkable claim.  Each test names
the *property* that must hold (a value set is not closed, a draw is reproducible, a declared
envelope is respected) and measures it on the real sampler, so a future edit that quietly narrows an
axis fails here instead of silently shrinking the corpus.

Run::

    .venv\\Scripts\\python.exe -m pytest tests/a12/integration/test_diversity_variables.py -q
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CONFIG_PATH = REPO_ROOT / "configs" / "a12" / "diversity.yaml"
DEGRADE_PATH = REPO_ROOT / "configs" / "a12" / "degrade_diversity.yaml"
AFTER_STORE = REPO_ROOT / "data" / "a12_diversity" / "store"
AFTER_REPORT = REPO_ROOT / "data" / "a12" / "reports" / "diversity_after.json"
BEFORE_REPORT = REPO_ROOT / "data" / "a12" / "reports" / "diversity_before.json"


@pytest.fixture(scope="module")
def config() -> dict:
    from synlab.pipeline import _resolve_diversity

    resolved = _resolve_diversity(str(CONFIG_PATH))
    if resolved is None:
        pytest.fail(f"{CONFIG_PATH} did not resolve to a config")
    return resolved


@pytest.fixture(scope="module")
def lineage_plan(config: dict):
    """A real ``LineagePlan`` list built by the real planner with diversity switched on."""
    from synlab.config import load_generation_spec
    from synlab.pipeline import plan_generation

    spec = load_generation_spec(REPO_ROOT / "configs" / "a12" / "next_experiment.yaml")
    spec.dataset.target_mothers = 12
    return plan_generation(spec, diversity=config)


# ---------------------------------------------------------------------------------------
# 0. opt-in discipline
# ---------------------------------------------------------------------------------------
def test_absent_switch_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no explicit request the config is never read and no variable is ever drawn."""
    from synlab import pipeline as P

    monkeypatch.delenv(P.DIVERSITY_ENV, raising=False)
    assert P._resolve_diversity(None) is None
    plan = P.plan_generation(_tiny_spec(), max_mothers=2)
    assert all(lineage.variables is None for lineage in plan.lineages)


def test_config_schema_is_declared(config: dict) -> None:
    assert config["schema"] == "synlab.diversity.v1"
    assert config["config_hash"].startswith("sha256:")
    for block in ("event", "pattern", "observation", "degradation", "reproducibility"):
        assert block in config, f"diversity.yaml lost its {block!r} block"


def _tiny_spec():
    from synlab.config import load_generation_spec

    spec = load_generation_spec(REPO_ROOT / "configs" / "a12" / "next_experiment.yaml")
    spec.dataset.target_mothers = 2
    return spec


# ---------------------------------------------------------------------------------------
# 1. reproducibility
# ---------------------------------------------------------------------------------------
def test_same_seed_replays_bitwise(config: dict, lineage_plan) -> None:
    """Two plans of the same seed draw bit-identical variable tables for the same lineage."""
    from synlab.config import load_generation_spec
    from synlab.pipeline import plan_generation

    spec = load_generation_spec(REPO_ROOT / "configs" / "a12" / "next_experiment.yaml")
    spec.dataset.target_mothers = 12
    again = plan_generation(spec, diversity=config)
    first = {l.lineage_id: _jsonable(l.variables) for l in lineage_plan.lineages}
    second = {l.lineage_id: _jsonable(l.variables) for l in again.lineages}
    assert sorted(first) == sorted(second)
    for lineage_id in first:
        assert json.dumps(first[lineage_id], sort_keys=True) == \
            json.dumps(second[lineage_id], sort_keys=True), lineage_id


def test_sampling_does_not_depend_on_plan_size(config: dict) -> None:
    """Lineage *i* draws the same table whether the plan holds 4 or 12 lineages."""
    from synlab.config import load_generation_spec
    from synlab.pipeline import plan_generation

    spec = load_generation_spec(REPO_ROOT / "configs" / "a12" / "next_experiment.yaml")
    spec.dataset.target_mothers = 4
    small = plan_generation(spec, diversity=config)
    spec12 = load_generation_spec(REPO_ROOT / "configs" / "a12" / "next_experiment.yaml")
    spec12.dataset.target_mothers = 12
    big = plan_generation(spec12, diversity=config)
    for a, b in zip(small.lineages, big.lineages):
        assert a.lineage_id == b.lineage_id
        assert json.dumps(_jsonable(a.variables), sort_keys=True) == \
            json.dumps(_jsonable(b.variables), sort_keys=True), a.lineage_id


def _jsonable(variables) -> dict:
    from synlab.pipeline import _jsonable_variables

    return _jsonable_variables(variables or {})


# ---------------------------------------------------------------------------------------
# 2. the event axis is not a closed set
# ---------------------------------------------------------------------------------------
def test_every_lineage_draws_its_own_cut_plane(config: dict, lineage_plan) -> None:
    """The sampled plane normals must be a *set*, not one repeated direction.

    The reviewed stores got their plane from a hash of the body geometry, so the normal was a
    deterministic function of the mother and the event rng was never read.  This asserts the
    opposite property for the sampler: distinct normals, a real spread, and no two identical.
    """
    planes = _sampled_planes(config, lineage_plan, count=10)
    assert len(planes) >= 8, f"only {len(planes)} lineages produced a plane"
    keys = {tuple(np.round(n, 6).tolist()) for n, _ in planes}
    assert len(keys) == len(planes), "two lineages drew the same plane normal"
    angles = []
    for i in range(len(planes)):
        for j in range(i + 1, len(planes)):
            angles.append(float(np.degrees(np.arccos(np.clip(
                abs(float(np.dot(planes[i][0], planes[j][0]))), -1.0, 1.0)))))
    assert float(np.mean(angles)) > 20.0, f"normals are nearly parallel: mean {np.mean(angles):.2f} deg"
    assert max(angles) > 60.0, "no normal is close to perpendicular to another"


def test_offsets_are_drawn_independently_of_the_normal(config: dict, lineage_plan) -> None:
    planes = _sampled_planes(config, lineage_plan, count=10)
    offsets = [offset for _, offset in planes]
    assert len({round(v, 9) for v in offsets}) == len(offsets), "two lineages share a plane offset"
    assert max(offsets) - min(offsets) > 0.05, "offsets barely move"


def _sampled_planes(config: dict, lineage_plan, *, count: int) -> list[tuple[np.ndarray, float]]:
    """Build real mothers and draw the event variables for ``count`` lineages.

    Mother construction is 0.1-3 s each and needs no geometry kernel beyond trimesh, so this stays
    a unit-speed test; the heavy fracture itself is *not* run here.
    """
    from synlab.mothers.api import create_mother
    from synlab.pipeline import _div_fracture_spec, _div_rng
    from synlab.seeds import derive_named_rngs

    out: list[tuple[np.ndarray, float]] = []
    for lineage in lineage_plan.lineages[:count]:
        rngs = derive_named_rngs(lineage_plan.spec.master_seed, lineage.lineage_id)
        try:
            mother = create_mother(lineage.vessel_id, lineage.material_id, lineage.params,
                                   rngs["shape"], mother_id=lineage.lineage_id)
        except Exception:  # noqa: BLE001 - an unbuildable lineage is not a diversity failure
            continue
        spec, sampled = _div_fracture_spec(_div_rng(config, lineage.lineage_id, "event"),
                                           config, lineage, mother)
        assert spec.plane_normal is not None, "the fracture spec must carry an explicit normal"
        assert spec.plane_point is not None, "the fracture spec must carry an explicit anchor"
        normal = np.asarray(spec.plane_normal, dtype=np.float64)
        out.append((normal / float(np.linalg.norm(normal)),
                    float(sampled["offset_radius_units"])))
    return out


def test_fracture_spec_normal_is_honoured_by_the_event() -> None:
    """A spec with an explicit normal produces an interface with that normal (measured, not assumed).

    This is the load-bearing fact behind the whole event axis: if ``FractureSpec.plane_normal`` were
    ignored, sampling it would change nothing.
    """
    from synlab.fracture.api import fracture_event
    from synlab.fracture.spec import FractureSpec
    from synlab.mothers.api import create_mother
    from synlab.seeds import make_rng

    params = {"base_mm": 5.0, "belly": 0.8, "depth_ratio": 0.26, "diameter_mm": 170.0,
              "foot_height_ratio": 0.041, "foot_ring_ratio": 0.89, "rim_flare": -0.03,
              "wall_mm": 9.3, "warp_amplitude": 0.028, "warp_eccentricity_mm": 2.39,
              "warp_lobes": 2}
    mother = create_mother("V01", "M01", params, make_rng(1, "pytest", "shape"),
                           mother_id="pytest_V01")
    centre = np.asarray(mother.mesh.vertices, dtype=np.float64).mean(axis=0)
    wanted = np.array([0.0, 0.0, 1.0])
    fracture = fracture_event(mother, FractureSpec(backend="plane_shared_cut",
                                                   plane_normal=wanted, plane_point=centre),
                              make_rng(1, "pytest", "cut"), event_id="pytest_E01")
    points = np.concatenate([np.asarray(p.sample_points_a, dtype=np.float64)
                             for p in fracture.interfaces if np.asarray(p.sample_points_a).size])
    centred = points - points.mean(axis=0)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    measured = vt[-1] / float(np.linalg.norm(vt[-1]))
    angle = float(np.degrees(np.arccos(np.clip(abs(float(np.dot(measured, wanted))), -1.0, 1.0))))
    assert angle < 1.0, f"requested +Z but measured {np.round(measured, 4)} ({angle:.3f} deg)"


# ---------------------------------------------------------------------------------------
# 3. the observation axis is not a closed set
# ---------------------------------------------------------------------------------------
def _sampled_cameras(config: dict, lineage_plan, *, count: int) -> list[dict]:
    """The camera draw of ``count`` lineages, straight from the pipeline's own sampler."""
    from synlab.pipeline import _div_camera, _div_rng

    out: list[dict] = []
    for lineage in lineage_plan.lineages[:count]:
        camera = _div_camera(_div_rng(config, lineage.lineage_id, "camera"), config)
        out.append({key: value for key, value in camera.items() if key != "profile"})
    return out


def test_working_distance_and_camera_are_not_pinned(config: dict, lineage_plan) -> None:
    """Sampled working distances must differ across lineages and stay inside a declared envelope.

    The reviewed stores measured exactly **one** working distance (220 mm) and **one** profile
    (``CAM_MID_V3``) across every observation, because ``observe(profile=None)`` always resolves to
    ``camera_profiles()[1]``.
    """
    seen = _sampled_cameras(config, lineage_plan, count=12)
    assert len(seen) >= 6, f"only {len(seen)} camera draws"
    distances = sorted({round(row["realized_working_distance_mm"], 3) for row in seen})
    assert len(distances) >= 2, f"all draws landed on one working distance: {distances}"
    profiles = {row["profile_id"] for row in seen}
    assert len(profiles) >= 2, f"all draws landed on one profile: {profiles}"
    registry = set(seen[0]["registry_profile_ids"])
    # every draw is either a registry tier or a documented-envelope distance
    envelope = {float(v) for v in config["observation"]["documented_envelope_mm"]}
    for row in seen:
        if row["source"] == "registry_tier":
            assert row["profile_id"] in registry
        else:
            assert round(row["realized_working_distance_mm"], 3) in envelope or \
                row["unreachable_tiers"], row
    # and the registered travel is never exceeded (transform_profile_u would have refused)
    assert all(row["realized_working_distance_mm"] > 0 for row in seen)


def test_light_modes_are_enumerated_and_real(config: dict, lineage_plan) -> None:
    """Every drawn light mode is one of the five documented controls and has a real direction."""
    from synlab.pipeline import LIGHT_MODE_SPECS, _div_light, _div_rng

    declared = list(LIGHT_MODE_SPECS)
    assert set(declared) == set(config["observation"]["light_modes"]), \
        "the code's light vocabulary and the config's must be the same five modes"
    assert len(declared) == 5
    seen = set()
    directions = []
    for lineage in lineage_plan.lineages[:12]:
        mode, light = _div_light(_div_rng(config, lineage.lineage_id, "light"), config)
        assert mode in declared
        seen.add(mode)
        unit = np.asarray(light.direction, dtype=np.float64)
        assert abs(float(np.linalg.norm(unit)) - 1.0) < 1e-9, "the light direction must be a unit vector"
        assert np.all(np.asarray(light.color) > 0) and np.all(np.asarray(light.ambient) >= 0)
        directions.append(tuple(np.round(unit, 6).tolist()))
    assert len(seen) >= 2, f"only one light mode was ever drawn: {seen}"
    assert len(set(directions)) >= 2, "all drawn lights share one direction"


def test_observation_knobs_vary_and_carry_measurements(config: dict, lineage_plan) -> None:
    """View count / delivered size / imaging knobs are drawn, and the focus offset is measured.

    ``defocus_sigma_px`` is deliberately **not** asserted to vary here.  Measured on this rig the
    current sampler saturates it: the focus offset is drawn inside the profile's depth of field, and
    at f/2.x the thin-lens blur of that offset already exceeds the declared
    ``max_defocus_sigma_px`` for every draw, so every lineage clamps to the ceiling.  That is a real
    remaining gap, it is reported in ``docs/a12/diversity_report.md``, and the exact wiring point for
    the fix is recorded there; asserting variation here would hide it.
    """
    from synlab.pipeline import _div_rng, _div_sample_static, _resolve_observe_spec
    from synlab.degrade.diversity import load_diversity_config

    base = _resolve_observe_spec(lineage_plan.spec, None)
    degrade = load_diversity_config(DEGRADE_PATH)
    views, sizes, sigmas, exposures = set(), set(), set(), set()
    for lineage in lineage_plan.lineages:
        table = _div_sample_static(config, lineage, base_observe_spec=base, degrade_cfg=degrade)
        obs = table["observation"]
        views.add(obs["view_count"])
        sizes.add(tuple(obs["delivered_size"]))
        sigmas.add(round(float(obs["defocus_sigma_px"]), 6))
        exposures.add(round(float(obs["exposure_ev"]), 6))
        assert obs["focus_offset_mm"] is not None, "the focus offset must be recorded, not implied"
        assert 0.0 <= float(obs["defocus_sigma_px"]) <= \
            float(config["observation"]["focus_error"]["max_defocus_sigma_px"]) + 1e-9
    assert len(views) >= 2, f"view count is pinned: {views}"
    assert len(sizes) >= 2, f"delivered size is pinned: {sizes}"
    assert len(exposures) >= 2, f"exposure is pinned: {exposures}"
    # the sampled blur is a real measurement chain: the offset it was derived from is non-zero
    assert any(abs(float(obs["focus_offset_mm"])) > 0 for obs in
               (_div_sample_static(config, l, base_observe_spec=base,
                                   degrade_cfg=degrade)["observation"]
                for l in lineage_plan.lineages[:6])), "no lineage drew a focus offset"


# ---------------------------------------------------------------------------------------
# 4. the degradation axis subset is not a closed set
# ---------------------------------------------------------------------------------------
def test_degradation_subsets_differ_per_lineage(config: dict, lineage_plan) -> None:
    """Each lineage draws its own axis subset, and level 0 (identity) is never dropped."""
    from synlab.degrade.diversity import load_diversity_config
    from synlab.pipeline import _div_rng, _div_sample_static, _resolve_observe_spec

    base = _resolve_observe_spec(lineage_plan.spec, None)
    degrade = load_diversity_config(DEGRADE_PATH)
    subsets = set()
    for lineage in lineage_plan.lineages:
        table = _div_sample_static(config, lineage, base_observe_spec=base, degrade_cfg=degrade)
        entry = table["degradation"]
        key = tuple(sorted(entry["declared_axes"]))
        subsets.add(key)
        assert entry["axis_count"] >= 1
        for axis_id, levels in entry["levels"].items():
            assert 0 in levels, f"{axis_id} lost its level-0 identity: {levels}"
            assert len(levels) >= 1
    assert len(subsets) >= 2, f"every lineage materialises the same subset: {subsets}"
    # every declared axis exists in the live 31-axis registry
    from synlab.degrade.diversity import AXIS_IDS

    pool = {item["axis_id"] for item in config["degradation"]["axis_pool"]}
    assert pool <= set(AXIS_IDS), f"unknown axes declared: {sorted(pool - set(AXIS_IDS))}"


# ---------------------------------------------------------------------------------------
# 5. the recorded artifacts back the claims
# ---------------------------------------------------------------------------------------
@pytest.mark.skipif(not AFTER_REPORT.exists(), reason="after-snapshot not produced yet")
def test_after_snapshot_improves_on_before() -> None:
    """The measured after-snapshot must beat the measured before-snapshot on the key axes."""
    if not BEFORE_REPORT.exists():
        pytest.skip("before-snapshot missing")
    before = json.loads(BEFORE_REPORT.read_text(encoding="utf-8"))
    after = json.loads(AFTER_REPORT.read_text(encoding="utf-8"))
    b_wd = before["observation_layer"]["working_distance_distinct"]
    a_wd = after["observation_layer"]["working_distance_distinct"]
    assert a_wd > b_wd, f"working distances did not diversify: {b_wd} -> {a_wd}"
    b_light = len(before["observation_layer"]["light_mode"])
    a_light = len(after["observation_layer"]["light_mode"])
    assert a_light > b_light, f"light modes did not diversify: {b_light} -> {a_light}"
    assert after["event_layer"]["events_per_lineage"]["distinct"] >= \
        before["event_layer"]["events_per_lineage"]["distinct"]


@pytest.mark.skipif(not AFTER_STORE.exists(), reason="after-store not built yet")
def test_after_store_declares_its_variables() -> None:
    """Every lineage of the after-store carries its drawn variable table in the run report."""
    import sqlite3

    db = AFTER_STORE / "metadata.sqlite"
    if not db.exists():
        pytest.skip("after-store has no metadata.sqlite")
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        runs = [row[0] for row in conn.execute("SELECT run_id FROM runs")]
    finally:
        conn.close()
    assert runs, "the after-store recorded no run"
    run_dir = AFTER_STORE / "reports" / "diversity_run"
    payloads = [json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(run_dir.glob("batch_*.json"))]
    assert payloads, f"no batch report under {run_dir}"
    outcomes = [entry for payload in payloads for entry in payload.get("outcomes") or []]
    assert outcomes, "the batch reports carry no outcomes"
    for entry in outcomes:
        assert "diversity" in entry, f"{entry.get('lineage_id')} has no variable table"
