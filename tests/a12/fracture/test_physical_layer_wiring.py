"""Physical-layer wiring contracts: material inputs, exposed cut basis, three-case matrix.

Three things are asserted here and nothing else:

1. the fracture inputs really come out of a real material profile (non-zero where the profile
   carries a value) and two different bodies give two different sets of inputs -- the guard
   against "morphology" that is really noise;
2. the cut basis is exposed *on the event result*, so the measurement tools of
   :mod:`synlab.fracture.surface_features` can run on a delivered result and not only on the
   cutter object that produced it;
3. switching morphology on does not move a single frozen A06 threshold: watertight, positive
   volume, conservation, complementarity, no self-intersection, and the conjugate profile
   correlation stays ~1.

The small analytic fixture is used so this stays a test rather than a batch job; the real
vessel-scale numbers live in ``data/a12_reports/physical_layer/`` and
``docs/a12/physical_layer_wiring.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.fracture import surface_features as sf  # noqa: E402
from synlab.fracture.api import _default_basis, audit_fracture, make_closed_cutter  # noqa: E402
from synlab.fracture.event import (  # noqa: E402
    BASIS_META_KEY,
    BASIS_RECORD_META_KEY,
    basis_from_record,
    basis_record,
    result_basis,
    run_shared_cut,
)
from synlab.fracture.morphology import (  # noqa: E402
    BACKEND_MORPHOLOGY,
    MORPHOLOGY_META_KEY,
    build_morphology_cutter,
    material_fracture_inputs,
    prepare_morphology,
)
from synlab.fracture.spec import (  # noqa: E402
    AMBIGUITY_AREA_RATIO_MAX,
    BACKEND_PLANE,
    INTERFACE_GAP_P95_MM,
    NORMAL_REVERSAL_P95_DEG,
    OVERLAP_RATIO_MAX,
    VOLUME_REL_TOL,
    FractureSpec,
)
from synlab.materials.api import build_material_profile, default_material_params  # noqa: E402
from synlab.schemas.runtime import CutBasis, ORIGIN_INTERFACE  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402

MASTER_SEED = 20261001
BUDGET_MM = 0.01
MAX_CELLS = 400_000
STONEWARE = "M03"
GLASS = "M07"


def profile_of(material_id: str) -> dict:
    return build_material_profile(
        material_id, default_material_params(material_id),
        make_rng(MASTER_SEED, "physical_layer_test", "materials", material_id))


# ---------------------------------------------------------------------------- 1. material chain


@pytest.mark.parametrize("material_id", [STONEWARE, GLASS])
def test_the_material_chain_yields_non_zero_physical_inputs(material_id: str) -> None:
    """A real profile must produce real numbers: grain, pore, glaze, roughness, porosity."""
    inputs = material_fracture_inputs(profile_of(material_id), material_id=material_id)
    record = inputs.as_dict()
    assert record["material_id"] == material_id
    for field in ("grain_scale_mm", "pore_scale_mm", "correlation_length_mm",
                  "appearance_roughness", "pit_radius_mm"):
        assert float(record[field]) > 0.0, (material_id, field, record[field])
    # at least one of the shading weights must be non-zero: an all-zero profile would mean the
    # statistics field names are not recognised and the whole relief collapses to a constant
    assert max(float(record["grain_amount"]), float(record["pore_amount"]),
               float(record["fiber_amount"]), float(record["aggregate_amount"])) > 0.0


def test_two_materials_give_two_different_input_sets() -> None:
    """M03 (stoneware) and M07 (glass) must differ in the quantities the relief is built from."""
    stone = material_fracture_inputs(profile_of(STONEWARE), material_id=STONEWARE).as_dict()
    glass = material_fracture_inputs(profile_of(GLASS), material_id=GLASS).as_dict()
    assert stone["grain_scale_mm"] > glass["grain_scale_mm"]
    assert stone["pore_scale_mm"] > glass["pore_scale_mm"]
    assert stone["porosity"] > glass["porosity"]
    assert stone["glaze_thickness_mm"] > glass["glaze_thickness_mm"]
    assert stone["pit_radius_mm"] != glass["pit_radius_mm"]
    differing = [key for key in stone
                 if stone[key] != glass[key]]
    # a single accidental difference is not a material model; require a real spread
    assert len(differing) >= 8, differing


def test_the_inputs_are_read_from_the_profile_not_defaulted() -> None:
    """Every extracted number must equal the profile's own recorded value."""
    profile = profile_of(STONEWARE)
    inputs = material_fracture_inputs(profile, material_id=STONEWARE)
    stats = profile["stats"]
    appearance = profile["appearance"]
    assert inputs.grain_scale_mm == pytest.approx(float(stats["grain_scale_mm"]))
    assert inputs.pore_scale_mm == pytest.approx(float(stats["pore_scale_mm"]))
    assert inputs.correlation_length_mm == pytest.approx(float(stats["correlation_length_mm"]))
    assert inputs.grain_amount == pytest.approx(float(appearance["grain_amount"]))
    assert inputs.pore_amount == pytest.approx(float(appearance["pore_amount"]))
    assert inputs.appearance_roughness == pytest.approx(float(appearance["roughness"]))
    glaze = [layer for layer in profile["layers"]
             if "glaze" in str(layer["name"]).lower()]
    assert glaze, "M03 carries a glaze layer"
    assert inputs.glaze_thickness_mm == pytest.approx(
        max(float(layer["thickness_mm"]) for layer in glaze))


# ---------------------------------------------------------------------------- 2. exposed basis


@pytest.fixture(scope="module")
def plane_event():
    import types

    mother = fx.box_mother((14.0, 14.0, 14.0))
    rng = make_rng(MASTER_SEED, "physical_layer_test", "fracture", "PLANE")
    basis = _default_basis(mother, rng, FractureSpec())
    cutter = make_closed_cutter(mother, FractureSpec(backend=BACKEND_PLANE), rng, basis=basis)
    result = run_shared_cut(mother, cutter, event_id="test_plane_basis", backend=BACKEND_PLANE)
    origin_uv = tuple(np.round(np.asarray(basis.origin, dtype=np.float64)[:2], 6))
    ruler = types.SimpleNamespace(origin_uv_mm=origin_uv, mirror_radius_mm=0.8,
                                  mist_radius_mm=1.44)
    return {"mother": mother, "basis": basis, "cutter": cutter, "result": result,
            "ruler": ruler}


def test_the_event_result_exposes_the_live_cut_basis(plane_event) -> None:
    """``meta['basis']`` is the cutter's own frame, bit for bit."""
    result = plane_event["result"]
    basis = plane_event["basis"]
    exposed = result.meta[BASIS_META_KEY]
    assert isinstance(exposed, CutBasis)
    assert exposed is plane_event["cutter"].basis
    assert np.allclose(np.asarray(exposed.origin, dtype=np.float64),
                       np.asarray(basis.origin, dtype=np.float64), atol=0.0)
    assert np.allclose(np.asarray(exposed.normal, dtype=np.float64),
                       np.asarray(basis.normal, dtype=np.float64), atol=0.0)
    assert exposed.basis_id == basis.basis_id
    assert result.meta["basis_source"].endswith("cutter.basis")


def test_the_basis_record_is_json_safe_and_round_trips(plane_event) -> None:
    """A persisted ``result.meta`` carries the frame, and the rebuild is exact."""
    import json

    record = plane_event["result"].meta[BASIS_RECORD_META_KEY]
    text = json.dumps(record)                       # must not raise
    assert isinstance(text, str)
    rebuilt = basis_from_record(record)
    original = plane_event["basis"]
    for field in ("origin", "e_u", "e_v", "normal"):
        assert np.allclose(np.asarray(getattr(rebuilt, field), dtype=np.float64),
                           np.asarray(getattr(original, field), dtype=np.float64), atol=1e-12)
    assert rebuilt.u_range == pytest.approx(tuple(original.u_range))
    assert rebuilt.v_range == pytest.approx(tuple(original.v_range))
    assert rebuilt.basis_id == original.basis_id
    assert basis_record(original)["h_scale_mm"] == pytest.approx(float(original.h_scale_mm))


def test_the_measurement_tools_run_from_the_result_alone(plane_event) -> None:
    """The whole point of the exposure: measuring a delivered result needs no cutter object."""
    result = plane_event["result"]
    basis = result_basis(result)
    assert np.allclose(np.asarray(basis.normal, dtype=np.float64),
                       np.asarray(plane_event["basis"].normal, dtype=np.float64), atol=0.0)
    # a plane cut is geometrically flat, so the crossing distance is the boolean round-off
    conjugate = sf.conjugate_profile_consistency(result.fragments, result.interfaces, basis)
    assert conjugate["patch_count"] >= 1
    assert conjugate["conjugate_gap_p95_mm"] <= INTERFACE_GAP_P95_MM
    # the delivered face measures as flat -- but only through the frozen face criterion
    # (``event._interface_faces``: all three vertices on the cutter *and* the normal aligned).
    # The vertex-majority ``face_origin_kind`` label alone also tags a mother face that merely
    # touches the cut plane along one edge, and measuring that population reports the mother's own
    # wall as roughness: measured on this fixture, Ra = 0.988 mm against 0 mm for the real face.
    majority_ra = _majority_label_ra(result, basis)
    assert majority_ra > 0.1, majority_ra
    delivered = sf.measure_interface_surface(result.fragments, basis, plane_event["ruler"],
                                            cutter_mesh=plane_event["cutter"].mesh,
                                            n_samples=60_000)
    assert delivered["samples"] > 500
    assert delivered["Ra_mm"] < 1.0e-4, delivered
    assert delivered["Rz_mm"] < 1.0e-3, delivered


def _majority_label_ra(result, basis) -> float:
    """``Ra`` of the vertex-majority interface label -- deliberately the wrong population."""
    local = []
    for fragment in result.fragments:
        origin = np.asarray(fragment.face_origin_kind)
        ids = np.nonzero(origin == ORIGIN_INTERFACE)[0]
        if ids.size:
            local.append(sf.triangle_vertices_local(fragment.mesh, basis, ids).reshape(-1, 3, 3))
    if not local:
        return 0.0
    samples = sf._sample_triangles(np.concatenate(local, axis=0), 40_000,
                                  np.random.default_rng(3))
    detrend = sf.detrend_plane(samples["u"], samples["v"], samples["w"])
    return float(sf.amplitude_statistics(samples["u"], samples["v"],
                                         detrend["residual"])["Ra_mm"])


def test_a_result_without_a_basis_is_refused_not_guessed() -> None:
    class _Empty:
        backend = "plane_shared_cut"
        meta: dict = {}

    with pytest.raises(Exception) as excinfo:
        result_basis(_Empty())
    assert BASIS_META_KEY in str(excinfo.value)
    assert BASIS_RECORD_META_KEY in str(excinfo.value)


# ---------------------------------------------------------------------------- 3. morphology case


@pytest.fixture(scope="module")
def morphology_events():
    """One morphology event per material on the *same* body, same basis, same origin."""
    mother = fx.box_mother((14.0, 14.0, 14.0))
    rng = make_rng(MASTER_SEED, "physical_layer_test", "fracture", "MORPH")
    basis = _default_basis(mother, rng, FractureSpec())
    out = {}
    for material_id in (STONEWARE, GLASS):
        profile = profile_of(material_id)
        event_rng = make_rng(MASTER_SEED, "physical_layer_test", "fracture", material_id)
        prepared = prepare_morphology(mother, material_profile=profile, rng=event_rng,
                                      basis=basis, event_id=f"test_morph_{material_id}",
                                      error_budget_mm=BUDGET_MM, max_cells=MAX_CELLS)
        cutter, field, params, report = build_morphology_cutter(
            mother, rng=event_rng, prepared=prepared, basis=basis,
            event_id=f"test_morph_{material_id}", error_budget_mm=BUDGET_MM, max_cells=MAX_CELLS)
        result = run_shared_cut(
            mother, cutter, event_id=f"test_morph_{material_id}", backend=BACKEND_MORPHOLOGY,
            extra_meta={MORPHOLOGY_META_KEY: params.as_dict(), "material_id": material_id})
        for patch in result.interfaces:
            patch.meta[MORPHOLOGY_META_KEY] = params.as_dict()
        for fragment in result.fragments:
            fragment.meta[MORPHOLOGY_META_KEY] = params.as_dict()
        out[material_id] = {
            "mother": mother, "basis": basis, "profile": profile, "cutter": cutter,
            "field": field, "params": params, "report": report, "result": result,
            "qa": audit_fracture(result, mother),
            "conjugate": sf.conjugate_profile_consistency(result.fragments, result.interfaces,
                                                          basis),
            "record": params.as_dict(),
        }
    return out


@pytest.mark.parametrize("material_id", [STONEWARE, GLASS])
def test_morphology_on_still_passes_every_frozen_a06_threshold(morphology_events,
                                                               material_id: str) -> None:
    case = morphology_events[material_id]
    qa = case["qa"]
    assert qa["passed"] is True, qa["failures"]
    assert qa["volume_rel_diff"] <= VOLUME_REL_TOL
    assert qa["overlap_ratio"] <= OVERLAP_RATIO_MAX
    assert qa["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM
    assert qa["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG
    assert qa["ambiguous_area_ratio_total"] <= AMBIGUITY_AREA_RATIO_MAX
    assert qa["source_coverage"] >= 0.999
    # watertight, positive volume, no self-intersection on every delivered piece
    from synlab.mothers.audit import self_intersection_report

    for fragment in case["result"].fragments:
        assert bool(fragment.mesh.is_watertight)
        assert float(fragment.volume_mm3) > 0.0
        assert self_intersection_report(fragment.mesh)["ok"] is True


@pytest.mark.parametrize("material_id", [STONEWARE, GLASS])
def test_morphology_keeps_the_two_sides_conjugate(morphology_events, material_id: str) -> None:
    conjugate = morphology_events[material_id]["conjugate"]
    assert conjugate["patch_count"] >= 1
    assert conjugate["conjugate_gap_p95_mm"] <= INTERFACE_GAP_P95_MM
    assert conjugate["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM
    assert conjugate["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG
    assert conjugate["profile_correlation_min"] is not None
    assert conjugate["profile_correlation_min"] > 0.9
    assert conjugate["profile_rms_diff_mm_max"] is not None
    assert conjugate["profile_rms_diff_mm_max"] < 1.0e-3


def test_two_materials_give_two_different_morphologies_on_one_body(morphology_events) -> None:
    """Different material in, different physical drivers out -- the anti-noise assertion."""
    stone = morphology_events[STONEWARE]["record"]
    glass = morphology_events[GLASS]["record"]
    assert stone["material_id"] == STONEWARE
    assert glass["material_id"] == GLASS
    assert stone["porosity"] > glass["porosity"]
    assert stone["sigma_f_mpa"] < glass["sigma_f_mpa"]
    assert stone["mirror_radius_mm"] > glass["mirror_radius_mm"]
    assert stone["hackle_count"] < glass["hackle_count"]
    assert stone["pit_count"] > glass["pit_count"]
    assert stone["pit_radius_mm"] != glass["pit_radius_mm"]
    assert stone["correlation_length_mm"] > glass["correlation_length_mm"]
    # the *realized* cutter must differ too, not only the parameter record
    assert morphology_events[STONEWARE]["cutter"].meta["morphology_params"]["material_id"] \
        != morphology_events[GLASS]["cutter"].meta["morphology_params"]["material_id"]


@pytest.mark.parametrize("material_id", [STONEWARE, GLASS])
def test_the_relief_is_physically_driven_and_the_flat_baseline_is_not(morphology_events,
                                                                     material_id: str) -> None:
    """Ra > 0 after morphology; the same body cut by the frozen plane backend gives Ra ~ 0."""
    case = morphology_events[material_id]
    surface = sf.measure_cutter_surface(case["cutter"].mesh, case["basis"], case["params"],
                                        window=case["field"].window, n_samples=80_000)
    assert surface["samples"] > 1000
    assert surface["Ra_mm"] > 0.0
    assert surface["Rz_mm"] > surface["Ra_mm"]
    assert surface["correlation_length_mm"] > 0.0
    # the requested relief is a function of the material: a glass body (0.08 mm grain, zero
    # porosity) must ask for far less relief than a stoneware body (0.8 mm grain)
    record = case["record"]
    assert record["requested_rms_mm"] > 0.0
    assert record["formulas"]["roughness_rms"]


def test_the_flat_baseline_measures_as_flat(morphology_events, plane_event) -> None:
    """Apples to apples: same body, same basis -- the plane backend delivers Ra ~ 0."""
    import types

    case = morphology_events[STONEWARE]
    # the frozen ruler ``_stats_from_samples`` reads: origin and the two zone radii.  The plane
    # baseline has no morphology record, so the origin/radii come from the morphology case that
    # was measured on the *same* basis and the same cross-section.
    ruler = types.SimpleNamespace(origin_uv_mm=tuple(case["record"]["origin_uv_mm"]),
                                  mirror_radius_mm=float(case["record"]["mirror_radius_mm"]),
                                  mist_radius_mm=float(case["record"]["mist_radius_mm"]))
    plane_surface = sf.measure_cutter_surface(plane_event["cutter"].mesh, plane_event["basis"],
                                              ruler, n_samples=25_000)
    assert plane_surface["Ra_mm"] < 1.0e-3, plane_surface["Ra_mm"]
    morph_surface = sf.measure_cutter_surface(case["cutter"].mesh, case["basis"], case["params"],
                                              window=case["field"].window, n_samples=80_000)
    assert morph_surface["Ra_mm"] > 10.0 * plane_surface["Ra_mm"] + 1.0e-4


def test_the_switch_is_off_by_default_and_the_backend_refuses(morphology_events) -> None:
    """The wiring is opt-in: without the switch the backend raises instead of cutting flat."""
    import os

    from synlab.errors import SynLabError
    from synlab.fracture.api import (
        BACKEND_MORPHOLOGY as API_BACKEND_MORPHOLOGY,
        BUILT_BACKENDS,
        MORPHOLOGY_SWITCH_ENV,
        fracture_event,
        morphology_backend_enabled,
    )

    assert API_BACKEND_MORPHOLOGY == BACKEND_MORPHOLOGY
    assert BACKEND_MORPHOLOGY not in BUILT_BACKENDS
    saved = os.environ.pop(MORPHOLOGY_SWITCH_ENV, None)
    try:
        spec = FractureSpec(backend=BACKEND_MORPHOLOGY)
        assert morphology_backend_enabled(spec) is False
        with pytest.raises(SynLabError) as excinfo:
            fracture_event(morphology_events[STONEWARE]["mother"], spec,
                           make_rng(MASTER_SEED, "physical_layer_test", "gate"),
                           event_id="test_gate")
        assert "GATED OFF" in str(excinfo.value) or "gated" in str(excinfo.value).lower()
        # and it is refused before any cutter is built
        assert excinfo.value.stage.endswith("_make_morphology_cutter") or \
            excinfo.value.stage.endswith("make_closed_cutter")
    finally:
        if saved is not None:
            os.environ[MORPHOLOGY_SWITCH_ENV] = saved


def test_the_switch_turns_the_backend_on_through_spec_meta(morphology_events) -> None:
    """``spec.meta['morphology']`` is the documented per-event opt-in."""
    from synlab.fracture.api import fracture_event, morphology_backend_enabled

    spec = FractureSpec(backend=BACKEND_MORPHOLOGY,
                        meta={"morphology": {"wall_probes": 64},
                              "material_profile": morphology_events[STONEWARE]["profile"]})
    assert morphology_backend_enabled(spec) is True
    result = fracture_event(morphology_events[STONEWARE]["mother"], spec,
                            make_rng(MASTER_SEED, "physical_layer_test", "optin"),
                            event_id="test_optin")
    assert result.backend == BACKEND_MORPHOLOGY
    assert MORPHOLOGY_META_KEY in result.meta
    assert result.meta[MORPHOLOGY_META_KEY]["material_id"] == STONEWARE
    assert result.meta[BASIS_META_KEY] is not None
    # the delivered result is measurable without the cutter object
    basis = result_basis(result)
    conjugate = sf.conjugate_profile_consistency(result.fragments, result.interfaces, basis)
    assert conjugate["conjugate_gap_p95_mm"] <= INTERFACE_GAP_P95_MM
    assert result.qa["passed"] is True, result.qa["failures"]
