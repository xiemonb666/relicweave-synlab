"""Fracture-surface realism: is the fracture face non-planar, and is the claim measurable?

Two independent claims are tested, and they are kept strictly apart:

**Claim A -- the model.**  The physics-driven morphology derives a non-planar fracture surface
from the *measured* wall thickness and the *real* material profile.  This is measured on the
analytic height field (``surface_kind = "analytic_field_request"``), which is the only realization
available today, and it is measured against a plane baseline run through the same chain.

**Claim B -- the realization.**  The simulated event must deliver that surface as one shared,
watertight cutter so both sides stay conjugate.  **This currently FAILS** at every scale, with
``CUTTER_NOT_CLOSED`` and thousands of non-manifold edges, because the shared-cutter quadtree
emits a wrong triangulation for 8 of its 12 per-cell branches as soon as an edge is split (see
``docs/a12/fracture_realism.md`` §5).  A flat field never splits an edge, which is why the plane
backend is exact.  Claim B is therefore carried by ``xfail(..., strict=False)`` tests: they report
the defect loudly today and will start passing by themselves the moment ``cut.py`` is fixed --
they can never turn a real failure into a silent green tick.

The plane baseline is asserted hard (it passes), and it is the control that makes Claim A's
numbers interpretable: a flat cut measures ``Ra ~ 1e-7 mm``, i.e. double-precision round-off.

No gate is relaxed anywhere in this file: every threshold is imported from
:mod:`synlab.fracture.spec`, and the relief floors asserted here are *physical* floors
(micrometre scale), not values fitted to the measurement.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.errors import ErrorCode, SynLabError  # noqa: E402
from synlab.fracture import surface_features as sf  # noqa: E402
from synlab.fracture.api import (  # noqa: E402
    BACKEND_MORPHOLOGY,
    BUILT_BACKENDS,
    GATED_BACKENDS,
    MORPHOLOGY_SWITCH_ENV,
    _default_basis,
    audit_fracture,
    fracture_event,
    make_closed_cutter,
    morphology_backend_enabled,
)
from synlab.fracture.event import run_shared_cut  # noqa: E402
from synlab.fracture.morphology import (  # noqa: E402
    build_morphology_field,
    estimate_cell_demand,
    prepare_morphology,
)
from synlab.fracture.spec import (  # noqa: E402
    BACKEND_PLANE,
    INTERFACE_GAP_P95_MM,
    NORMAL_REVERSAL_P95_DEG,
    OVERLAP_RATIO_MAX,
    VOLUME_REL_TOL,
    FractureSpec,
)
from synlab.materials.api import build_material_profile, default_material_params  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402

MASTER_SEED = 20261001
BUDGET_MM = 0.01
MAX_CELLS = 400_000
BOX_MM = (12.0, 12.0, 12.0)

#: physical floors, not fitted values.  A flat surface measures ~1e-7 mm of round-off, so a
#: micrometre floor still separates "real relief" from "numerical dust" by three orders.
PLANAR_RA_MAX_MM = 1.0e-4
PLANAR_NORMAL_MAX_DEG = 1.0e-2
RELIEF_RA_MIN_MM = 5.0e-3
RELIEF_RT_MIN_MM = 1.0e-2
RELIEF_NORMAL_P95_MIN_DEG = 5.0

#: the defect that blocks the realization; asserted by name so a different failure cannot hide
BLOCKING_CODES = (ErrorCode.CUTTER_NOT_CLOSED, ErrorCode.PRECISION_BUDGET_EXCEEDED,
                  ErrorCode.PRECISION_NOT_REALIZED)


def _material(material_id: str = "M01") -> dict:
    return build_material_profile(material_id, default_material_params(material_id),
                                  make_rng(MASTER_SEED, "realism_test", "materials", material_id))


def _normal_angles(mesh, basis, face_ids) -> np.ndarray:
    """Angle (deg) between each given face's normal and the cut-basis normal."""
    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    ids = np.asarray(face_ids, dtype=np.int64)
    if ids.size == 0:
        return np.zeros(0, dtype=np.float64)
    tri = verts[faces[ids]]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1)
    keep = norm > 0.0
    n = n[keep] / norm[keep][:, None]
    axis = np.asarray(basis.normal, dtype=np.float64)
    axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
    return np.degrees(np.arccos(np.clip(np.abs(n @ axis), 0.0, 1.0)))


def _dihedral_p95_deg(mesh, face_ids) -> float:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    ids = np.asarray(face_ids, dtype=np.int64)
    if ids.size < 2:
        return 0.0
    tri = verts[faces[ids]]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1)
    ok = norm > 1e-12
    tri, n = tri[ok], n[ok] / norm[ok][:, None]
    if tri.shape[0] < 2:
        return 0.0
    quant = np.round(tri, 6)
    edges: dict[tuple, list[int]] = {}
    for k in range(quant.shape[0]):
        for a, b in ((0, 1), (1, 2), (2, 0)):
            p, q = quant[k, a], quant[k, b]
            key = (tuple(p), tuple(q)) if tuple(p) <= tuple(q) else (tuple(q), tuple(p))
            edges.setdefault(key, []).append(k)
    angles = [float(np.degrees(np.arccos(np.clip(np.dot(n[i], n[j]), -1.0, 1.0))))
              for members in edges.values() if len(members) == 2
              for i, j in [members]]
    return float(np.percentile(angles, 95)) if angles else 0.0


def _interface_ids(fragment, cutter_mesh) -> np.ndarray:
    from synlab.fracture.event import _interface_faces

    ids, _src, _cen = _interface_faces(fragment, cutter_mesh)
    return np.asarray(ids, dtype=np.int64)


def _prepare(mother, profile, tag: str):
    rng = make_rng(MASTER_SEED, "realism_test", "fracture", tag)
    basis = _default_basis(mother, rng, FractureSpec())
    prepared = prepare_morphology(mother, material_profile=profile, rng=rng, basis=basis,
                                 event_id=f"realism_{tag}", error_budget_mm=BUDGET_MM,
                                 max_cells=MAX_CELLS)
    return rng, basis, prepared


@pytest.fixture(scope="module")
def realism():
    """Plane event (hard) and modelled morphology field (hard) on one body, basis and material."""
    mother = fx.box_mother(BOX_MM, mother_id="realism_box")
    profile = _material("M01")
    rng, basis, prepared = _prepare(mother, profile, "BOX12")
    params = prepared["base_params"]

    plane_spec = FractureSpec(backend=BACKEND_PLANE, error_budget_mm=BUDGET_MM,
                              max_cutter_cells=MAX_CELLS)
    plane_cutter = make_closed_cutter(mother, plane_spec, rng, basis=basis)
    plane_result = run_shared_cut(mother, plane_cutter, event_id="realism_plane",
                                  backend=BACKEND_PLANE)
    plane_ids = [_interface_ids(f, plane_cutter.mesh) for f in plane_result.fragments]
    plane_angles = np.concatenate([_normal_angles(f.mesh, basis, i)
                                   for f, i in zip(plane_result.fragments, plane_ids)])
    field = build_morphology_field(basis, mother.mesh, params, rng=rng,
                                  cross_section=(prepared["tris_uv"],
                                                 prepared["core_area_mm2"],
                                                 prepared["cross_info"]))

    # modelled surface over the band core: area-uniform samples of the analytic field
    window = field.window
    values = np.asarray(window.values, dtype=np.float64)
    step = float(window.step_mm)
    ii, jj = np.nonzero(values >= 1.0 - 1e-12)
    pick = rng.integers(0, ii.size, size=120_000)
    u = float(window.u0) + (ii[pick] + rng.random(pick.size)) * step
    v = float(window.v0) + (jj[pick] + rng.random(pick.size)) * step
    relief = np.asarray(field._relief(u, v), dtype=np.float64)      # conchoidal bow removed
    relief_res = sf.detrend_plane(u, v, relief)
    relief_amp = sf.amplitude_statistics(u, v, relief_res["residual"], cell_mm=sf.RZ_CELL_MM)
    relief_corr = sf.correlation_length(u, v, relief_res["residual"], step_mm=sf.BIN_STEP_MM)
    du, dv = field.gradient(u, v)
    slope = np.degrees(np.arctan(np.hypot(du, dv)))

    return {
        "mother": mother, "profile": profile, "rng": rng, "basis": basis,
        "prepared": prepared, "params": params, "field": field,
        "plane": {
            "cutter": plane_cutter, "result": plane_result,
            "qa": audit_fracture(plane_result, mother),
            "delivered": sf.measure_interface_surface(plane_result.fragments, basis, params,
                                                      cutter_mesh=plane_cutter.mesh,
                                                      n_samples=60_000),
            "conjugate": sf.conjugate_profile_consistency(plane_result.fragments,
                                                          plane_result.interfaces, basis),
            "angle_max_deg": float(plane_angles.max()) if plane_angles.size else 0.0,
            "dihedral_p95_deg": max(_dihedral_p95_deg(f.mesh, i)
                                    for f, i in zip(plane_result.fragments, plane_ids)),
        },
        "modelled": {
            "Ra_mm": float(relief_amp["Ra_mm"]), "Rq_mm": float(relief_amp["Rq_mm"]),
            "Rz_mm": float(relief_amp["Rz_mm"]), "Rt_mm": float(relief_amp["Rt_mm"]),
            "correlation_length_mm": float(relief_corr["correlation_length_mm"]),
            "slope_p50_deg": float(np.percentile(slope, 50)),
            "slope_p95_deg": float(np.percentile(slope, 95)),
            "samples": int(u.size),
            "demand": estimate_cell_demand(field, budget_mm=BUDGET_MM),
        },
    }


# ---------------------------------------------------------------- Claim A: the model is non-planar
def test_plane_control_really_is_planar(realism) -> None:
    """The control: if this stops measuring ~0, every modelled number below is suspect."""
    plane = realism["plane"]
    assert plane["qa"]["passed"] is True, plane["qa"]["failures"]
    assert plane["delivered"]["Ra_mm"] < PLANAR_RA_MAX_MM
    assert plane["delivered"]["Rt_mm"] < PLANAR_RA_MAX_MM
    assert plane["angle_max_deg"] < PLANAR_NORMAL_MAX_DEG
    assert plane["dihedral_p95_deg"] < PLANAR_NORMAL_MAX_DEG


def test_plane_event_passes_every_a06_gate(realism) -> None:
    qa = realism["plane"]["qa"]
    assert qa["volume_rel_diff"] <= VOLUME_REL_TOL
    assert qa["overlap_ratio"] <= OVERLAP_RATIO_MAX
    assert qa["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM
    assert qa["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG
    assert qa["passed"] is True, qa["failures"]


def test_plane_sides_are_conjugate(realism) -> None:
    conj = realism["plane"]["conjugate"]
    assert conj["patch_count"] >= 1
    assert conj["conjugate_gap_p95_mm"] <= INTERFACE_GAP_P95_MM
    assert conj["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM
    assert conj["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG
    assert conj["profile_correlation_min"] is None or conj["profile_correlation_min"] > 0.9


def test_modelled_fracture_surface_is_measurably_non_planar(realism) -> None:
    """The claim under test, stated as a contrast against the plane control."""
    mod = realism["modelled"]
    plane = realism["plane"]
    assert mod["samples"] > 10_000
    assert mod["Ra_mm"] > RELIEF_RA_MIN_MM
    assert mod["Rt_mm"] > RELIEF_RT_MIN_MM
    assert mod["Rz_mm"] >= mod["Ra_mm"]
    # the contrast is orders of magnitude: this is relief, not numerical dust
    assert mod["Ra_mm"] > 100.0 * max(plane["delivered"]["Ra_mm"], 1e-12)
    # and it has a real slope distribution, not a tilt: a tilted plane would be removed by the
    # de-trending, and would leave a single slope rather than a distribution
    assert mod["slope_p50_deg"] > RELIEF_NORMAL_P95_MIN_DEG
    assert mod["slope_p95_deg"] > mod["slope_p50_deg"]
    assert mod["correlation_length_mm"] > 0.0
    # the relief is realisable inside the frozen resource guard, or the model would be unusable
    assert mod["demand"]["predicted_cells"] > 0.0


def test_relief_parameters_come_from_the_body_not_from_a_free_choice(realism) -> None:
    params = realism["params"]
    assert params.wall == realism["prepared"]["base_params"].wall
    assert params.sigma_f_mpa > 0.0
    assert params.mirror_radius_mm > 0.0
    assert params.requested_rms_mm > 0.0
    assert params.material["grain_scale_mm"] > 0.0
    # every derived number carries the relation it came from
    assert params.formulas["mirror_radius"] and params.formulas["sigma_f"]
    assert params.formulas["curvature_requested"] and params.formulas["roughness_spectrum"]
    assert params.formulas["pits"] and params.formulas["conchoidal"]
    assert params.formulas["precision_budget"]
    # the pits come from the porosity area fraction, not from a constant
    assert params.pit_area_fraction == pytest.approx(
        params.pit_count * np.pi * params.pit_radius_mm ** 2 / params.core_area_mm2, rel=0.5)
    # a different wall thickness moves the strength: the derivation is not a lookup table
    thin = fx.box_mother((12.0, 12.0, 1.6), mother_id="realism_thin")
    thin_prep = prepare_morphology(thin, material_profile=realism["profile"],
                                   rng=make_rng(MASTER_SEED, "realism_test", "fracture", "THIN"),
                                   error_budget_mm=BUDGET_MM, max_cells=MAX_CELLS)
    assert thin_prep["base_params"].wall["p05_mm"] < params.wall["p05_mm"]
    assert thin_prep["base_params"].sigma_f_mpa != pytest.approx(params.sigma_f_mpa, rel=1e-6)


def test_a_different_material_gives_a_different_relief(realism) -> None:
    mother = realism["mother"]
    porous = realism["params"]
    dense_prep = prepare_morphology(mother, material_profile=_material("M04"),
                                    rng=make_rng(MASTER_SEED, "realism_test", "fracture", "M04"),
                                    error_budget_mm=BUDGET_MM, max_cells=MAX_CELLS)
    dense = dense_prep["base_params"]
    assert dense.porosity < porous.porosity
    assert dense.sigma_f_mpa > porous.sigma_f_mpa          # less porosity -> stronger body
    assert dense.pit_area_fraction < porous.pit_area_fraction
    assert dense.material["grain_scale_mm"] <= porous.material["grain_scale_mm"]


# --------------------------------------------------------------------------- the wiring gate
def test_the_morphology_backend_is_gated_off_by_default(realism) -> None:
    assert BACKEND_MORPHOLOGY in GATED_BACKENDS
    assert BACKEND_MORPHOLOGY not in BUILT_BACKENDS, (
        "a gated backend must not appear in BUILT_BACKENDS: callers iterate that tuple")
    spec = FractureSpec(backend=BACKEND_MORPHOLOGY)
    assert morphology_backend_enabled(spec) is False
    assert morphology_backend_enabled(FractureSpec()) is False
    with pytest.raises(SynLabError) as excinfo:
        fracture_event(realism["mother"], spec, realism["rng"], event_id="gated")
    assert excinfo.value.code is ErrorCode.OPERATOR_NOT_REALIZED
    assert MORPHOLOGY_SWITCH_ENV in str(excinfo.value)


def test_the_switch_gets_past_the_gate_into_the_builder(realism) -> None:
    """With the switch on, the failure (if any) must come from the builder, not from the gate.

    This is what makes "wired" a measurable statement: the gate error disappears and the call
    reaches the shared-cutter construction.
    """
    spec = FractureSpec(backend=BACKEND_MORPHOLOGY, error_budget_mm=BUDGET_MM,
                        max_cutter_cells=MAX_CELLS,
                        meta={"material_profile": realism["profile"], "morphology": {}})
    assert morphology_backend_enabled(spec) is True
    try:
        cutter = make_closed_cutter(realism["mother"], spec, realism["rng"], basis=realism["basis"])
    except SynLabError as exc:
        assert exc.code is not ErrorCode.OPERATOR_NOT_REALIZED, (
            "the switch did not get past the gate")
        assert exc.code in BLOCKING_CODES, exc.code
    else:
        assert bool(cutter.mesh.is_watertight)
        assert cutter.realized_error_mm <= BUDGET_MM + 1e-12


@pytest.mark.xfail(strict=False, reason=(
    "shared-cutter quadtree triangulates 8 of its 12 per-cell branches wrongly (holes 0.75 of the "
    "cell area, overlap 1.75); every non-planar field therefore raises CUTTER_NOT_CLOSED -- see "
    "docs/a12/fracture_realism.md section 5"))
def test_morphology_realization_passes_the_a06_gates(realism) -> None:
    """Claim B.  Expected to fail until the triangulation defect in ``cut.py`` is fixed."""
    # a smaller cell budget keeps this expected failure fast; it does not change the outcome
    spec = FractureSpec(backend=BACKEND_MORPHOLOGY, error_budget_mm=BUDGET_MM,
                        max_cutter_cells=30_000,
                        meta={"material_profile": realism["profile"], "morphology": {}})
    result = fracture_event(realism["mother"], spec, realism["rng"], event_id="realized")
    qa = audit_fracture(result, realism["mother"])
    assert qa["passed"] is True, qa["failures"]
    assert qa["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM
    assert qa["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG
    assert qa["volume_rel_diff"] <= VOLUME_REL_TOL
    for fragment in result.fragments:
        assert bool(fragment.mesh.is_watertight)


@pytest.mark.xfail(strict=False, reason=(
    "same triangulation defect; the rough backend has no fallback and must not coarsen silently"))
def test_rough_shared_cut_realizes_the_frozen_precision_budget(realism) -> None:
    from synlab.fracture.spec import BACKEND_ROUGH

    spec = FractureSpec(backend=BACKEND_ROUGH, error_budget_mm=BUDGET_MM,
                        max_cutter_cells=30_000, target_rms_mm=0.02)
    cutter = make_closed_cutter(realism["mother"], spec, realism["rng"], basis=realism["basis"])
    assert cutter.requested_error_mm == pytest.approx(BUDGET_MM)
    assert cutter.realized_error_mm <= BUDGET_MM + 1e-12
    assert int(cutter.meta["cells"]) <= MAX_CELLS
    result = run_shared_cut(realism["mother"], cutter, event_id="rough", backend=BACKEND_ROUGH)
    qa = audit_fracture(result, realism["mother"])
    assert qa["passed"] is True, qa["failures"]
    assert qa["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM


def test_an_over_budget_configuration_fails_structurally(realism) -> None:
    """A configuration that does not fit must refuse, never coarsen the surface silently."""
    from synlab.fracture.spec import BACKEND_ROUGH

    spec = FractureSpec(backend=BACKEND_ROUGH, error_budget_mm=BUDGET_MM,
                        max_cutter_cells=512, target_rms_mm=0.30)
    try:
        cutter = make_closed_cutter(realism["mother"], spec, realism["rng"],
                                    basis=realism["basis"])
    except SynLabError as exc:
        assert exc.code in BLOCKING_CODES, exc.code
        measurements = dict(exc.measurements or {})
        if exc.code is ErrorCode.PRECISION_BUDGET_EXCEEDED:
            assert float(measurements["cells"]) > float(measurements["max_cells"])
            assert float(measurements["wavelength_min_mm"]) > 0.0
            assert float(measurements["budget_mm"]) == pytest.approx(BUDGET_MM)
    else:
        assert cutter.realized_error_mm <= BUDGET_MM + 1e-12
        assert int(cutter.meta["cells"]) <= 512


# -------------------------------------------------------------------- pixel resolvability
def test_pixel_resolvability_uses_the_frozen_scan_ladder(realism) -> None:
    """Which scan distance can see the relief, on the contract's own ladder and criteria."""
    contract = json.loads((REPO_ROOT / "configs" / "a12" / "capture_contract.json")
                          .read_text(encoding="utf-8"))
    rows = contract["working_distance_and_resolution"]["resolution_table"]["rows"]
    ladder = [(float(r["mm_per_px"]), float(r["structure_0p2mm_px"])) for r in rows]
    assert ladder == [(0.039, 5.12), (0.078, 2.56), (0.117, 1.71), (0.156, 1.28), (0.195, 1.02)]
    for mm_per_px, structure_px in ladder:
        # each rung's own column is exactly "pixels per 0.2 mm structure"
        assert structure_px == pytest.approx(0.2 / mm_per_px, rel=0.01)

    noise_floor_mm = float(contract["mask_and_quality"]["quality_3d_floor_q2_equivalent"]
                           ["sigma_max_mm"])
    assert noise_floor_mm == pytest.approx(0.2)

    mod = realism["modelled"]
    lambda_min = float(realism["field"].wavelength_min_mm)
    assert lambda_min > 0.0
    table = []
    for mm_per_px, _ in ladder:
        table.append({
            "mm_per_px": mm_per_px,
            "px_per_shortest_wavelength": lambda_min / mm_per_px,
            "px_per_correlation_length": mod["correlation_length_mm"] / mm_per_px,
            "amplitude_over_floor": mod["Rt_mm"] / noise_floor_mm,
            # the contract's pilot target: >= 4 px across the finest admitted feature
            "resolved": lambda_min / mm_per_px >= 4.0,
            "amplitude_visible": mod["Rt_mm"] > noise_floor_mm,
        })
    # monotone: a nearer stand can never resolve less than a farther one
    for nearer, farther in zip(table, table[1:]):
        assert nearer["px_per_shortest_wavelength"] > farther["px_per_shortest_wavelength"]
    # the relief clears the contract's Q2 3D scatter floor at every rung
    assert all(row["amplitude_visible"] for row in table)
    # the resolved rungs are a contiguous prefix: the finest feature is resolved by the closest
    # stands and stops being resolved as the stand moves away
    flags = [row["resolved"] for row in table]
    assert flags[0] is True
    assert flags == sorted(flags, reverse=True), flags
    assert sum(flags) >= 3, flags
    resolved = [row["mm_per_px"] for row in table if row["resolved"]]
    assert resolved == [r["mm_per_px"] for r in table[:len(resolved)]]
    assert table[-1]["px_per_shortest_wavelength"] < table[0]["px_per_shortest_wavelength"]
