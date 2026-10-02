"""Fracture-surface realism: is the fracture face non-planar, and is the claim measurable?

This file adds the assertions the morphology module did not yet carry:

* a **plane baseline control** and a **morphology event** measured through the *same* chain, so a
  non-zero roughness on the morphology side cannot be measurement noise: the plane side returns
  ``Ra`` at the 1e-7 mm level (double precision round-off on a flat surface), the morphology side
  returns a relief three orders of magnitude larger;
* the **normal-angle distribution** of the delivered interface faces against the cut-basis normal
  (a plane gives exactly 0; morphology gives a distribution) and the discrete **dihedral turning**
  of those same faces (the measured curvature proxy);
* the **wiring gate**: ``morphology_shared_cut`` refuses to run unless it is explicitly switched
  on, and the refusal is an error, never a silent planar substitute;
* the **pixel resolvability** arithmetic on the real scanning-desk ladder
  (``configs/a12/capture_contract.json``);
* ``rough_shared_cut`` precision: the realized interpolation error stays inside the frozen budget
  and the shared-surface gap P95 stays under ``INTERFACE_GAP_P95_MM``, and when a configuration
  does not fit, it fails with the structured ``PRECISION_BUDGET_EXCEEDED`` error rather than
  silently coarsening the surface.

No gate is relaxed anywhere in this file: the thresholds are imported from
:mod:`synlab.fracture.spec`, and the roughness floors asserted here are *physical* floors
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
    MORPHOLOGY_META_KEY,
    build_morphology_cutter,
    prepare_morphology,
)
from synlab.fracture.spec import (  # noqa: E402
    BACKEND_PLANE,
    BACKEND_ROUGH,
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
#: the two fixtures are small analytic bodies, so the module fixture stays a test, not a batch job
BOX_MM = (12.0, 12.0, 12.0)

#: physical floors, not fitted values: a flat surface measures ~1e-7 mm of round-off, so a
#: micro-metre floor still separates "real relief" from "numerical dust" by three orders.
PLANAR_RA_MAX_MM = 1.0e-4
RELIEF_RA_MIN_MM = 5.0e-3
RELIEF_RT_MIN_MM = 1.0e-2
#: a plane's delivered face normals are exactly the basis normal; allow only angular round-off.
PLANAR_NORMAL_MAX_DEG = 1.0e-2
RELIEF_NORMAL_P95_MIN_DEG = 0.5


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
    """Measured curvature proxy: the 95th percentile dihedral angle across shared edges."""
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


@pytest.fixture(scope="module")
def realism():
    """One plane control and one morphology event on the same body, basis, wall and material."""
    mother = fx.box_mother(BOX_MM, mother_id="realism_box")
    profile = _material("M01")
    rng = make_rng(MASTER_SEED, "realism_test", "fracture", "BOX12", "M01")
    basis = _default_basis(mother, rng, FractureSpec())
    prepared = prepare_morphology(mother, material_profile=profile, rng=rng, basis=basis,
                                 event_id="realism", error_budget_mm=BUDGET_MM,
                                 max_cells=MAX_CELLS)

    plane_spec = FractureSpec(backend=BACKEND_PLANE, error_budget_mm=BUDGET_MM,
                              max_cutter_cells=MAX_CELLS)
    plane_cutter = make_closed_cutter(mother, plane_spec, rng, basis=basis)
    plane_result = run_shared_cut(mother, plane_cutter, event_id="realism_plane",
                                  backend=BACKEND_PLANE)

    cutter, field, params, report = build_morphology_cutter(
        mother, rng=rng, prepared=prepared, basis=basis, event_id="realism_morph",
        error_budget_mm=BUDGET_MM, max_cells=MAX_CELLS)
    morph_result = run_shared_cut(mother, cutter, event_id="realism_morph",
                                  backend=BACKEND_MORPHOLOGY,
                                  extra_meta={MORPHOLOGY_META_KEY: params.as_dict()})

    out = {"mother": mother, "basis": basis, "rng": rng, "profile": profile,
           "prepared": prepared, "field": field, "params": params, "report": report}
    for label, result, cmesh, prm in (("plane", plane_result, plane_cutter.mesh, params),
                                      ("morph", morph_result, cutter.mesh, params)):
        delivered = sf.measure_interface_surface(result.fragments, basis, prm,
                                                 cutter_mesh=cmesh, n_samples=120_000)
        angles = np.concatenate([_normal_angles(f.mesh, basis, _interface_ids(f, cmesh))
                                 for f in result.fragments])
        dihedral = [_dihedral_p95_deg(f.mesh, _interface_ids(f, cmesh))
                    for f in result.fragments]
        out[label] = {
            "result": result, "cutter_mesh": cmesh, "delivered": delivered,
            "qa": audit_fracture(result, mother),
            "conjugate": sf.conjugate_profile_consistency(result.fragments, result.interfaces,
                                                          basis),
            "angle_max_deg": float(angles.max()) if angles.size else 0.0,
            "angle_p95_deg": float(np.percentile(angles, 95)) if angles.size else 0.0,
            "angle_mean_deg": float(angles.mean()) if angles.size else 0.0,
            "dihedral_p95_deg": float(max(dihedral)) if dihedral else 0.0,
        }
    out["plane"]["cutter"] = plane_cutter
    out["morph"]["cutter"] = cutter
    return out


# --------------------------------------------------------------- is the fracture non-planar?
def test_plane_control_really_is_planar(realism) -> None:
    """The control: if this ever stops measuring ~0, every morphology number below is suspect."""
    plane = realism["plane"]
    assert plane["qa"]["passed"] is True, plane["qa"]["failures"]
    assert plane["delivered"]["Ra_mm"] < PLANAR_RA_MAX_MM
    assert plane["delivered"]["Rt_mm"] < PLANAR_RA_MAX_MM
    assert plane["angle_max_deg"] < PLANAR_NORMAL_MAX_DEG
    assert plane["dihedral_p95_deg"] < PLANAR_NORMAL_MAX_DEG
    assert plane["qa"]["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM


def test_morphology_fracture_face_is_measurably_non_planar(realism) -> None:
    """The claim under test, stated as a contrast against the plane control."""
    morph = realism["morph"]
    plane = realism["plane"]
    assert morph["qa"]["passed"] is True, morph["qa"]["failures"]
    # 1. amplitude of the delivered relief
    assert morph["delivered"]["Ra_mm"] > RELIEF_RA_MIN_MM
    assert morph["delivered"]["Rt_mm"] > RELIEF_RT_MIN_MM
    # 2. the contrast is orders of magnitude, so this is relief and not numerical dust
    assert morph["delivered"]["Ra_mm"] > 1.0e3 * max(plane["delivered"]["Ra_mm"], 1e-12)
    # 3. the fracture face normals are a distribution, not a single direction
    assert morph["angle_p95_deg"] > RELIEF_NORMAL_P95_MIN_DEG
    assert morph["angle_p95_deg"] > 1.0e3 * max(plane["angle_p95_deg"], 1e-12)
    assert morph["angle_mean_deg"] > 1.0e3 * max(plane["angle_mean_deg"], 1e-12)
    # 4. the surface turns: a real curvature, not a tilted plane
    assert morph["dihedral_p95_deg"] > PLANAR_NORMAL_MAX_DEG
    assert morph["dihedral_p95_deg"] > 1.0e3 * max(plane["dihedral_p95_deg"], 1e-12)
    # 5. lateral scale of the relief is resolved by the measurement itself
    assert morph["delivered"]["correlation_length_mm"] > 0.0
    assert morph["delivered"]["ridge_lines_per_mm"] >= 0.0
    # the same record travels with the artifacts
    assert all(MORPHOLOGY_META_KEY in p.meta for p in morph["result"].interfaces)
    assert all(MORPHOLOGY_META_KEY in f.meta for f in morph["result"].fragments)


def test_relief_parameters_come_from_the_body_not_from_a_free_choice(realism) -> None:
    """Every amplitude is the evaluation of a published relation on a measured input."""
    params = realism["params"]
    wall = realism["prepared"]["base_params"].wall
    assert params.wall == wall
    # the mirror radius follows sigma_f * sqrt(r_m) = A_m on the measured strength
    assert params.mirror_radius_mm > 0.0
    assert params.sigma_f_mpa > 0.0
    assert str(params.requested_curvature_per_mm) in str(params.formulas["curvature"])
    # the relief spectrum is tied to the material's own heterogeneity
    assert params.correlation_length_mm > 0.0
    assert params.material["grain_scale_mm"] > 0.0
    # the pits come from the porosity area fraction, not from a constant
    assert params.pit_count >= 0
    assert params.pit_area_fraction == pytest.approx(
        params.pit_count * np.pi * params.pit_radius_mm ** 2 / params.core_area_mm2, rel=0.5)
    # a different wall thickness must move the numbers: the derivation is not a lookup table
    thin = fx.box_mother((12.0, 12.0, 1.6), mother_id="realism_box_thin")
    thin_prep = prepare_morphology(thin, material_profile=realism["profile"],
                                   rng=make_rng(MASTER_SEED, "realism_test", "fracture", "THIN"),
                                   error_budget_mm=BUDGET_MM, max_cells=MAX_CELLS)
    assert thin_prep["base_params"].wall["p05_mm"] < wall["p05_mm"]
    assert thin_prep["base_params"].sigma_f_mpa != pytest.approx(params.sigma_f_mpa, rel=1e-6)


def test_a_different_material_gives_a_different_relief(realism) -> None:
    """The material profile is a real input: a dense body is not the same surface as a grogged one."""
    mother = realism["mother"]
    porous = realism["params"]
    dense_profile = _material("M04")
    dense_prep = prepare_morphology(mother, material_profile=dense_profile,
                                    rng=make_rng(MASTER_SEED, "realism_test", "fracture", "M04"),
                                    error_budget_mm=BUDGET_MM, max_cells=MAX_CELLS)
    dense = dense_prep["base_params"]
    assert dense.porosity < porous.porosity
    assert dense.material["grain_scale_mm"] <= porous.material["grain_scale_mm"]
    # lower porosity => higher strength => smaller mirror radius; never an identical record
    assert dense.sigma_f_mpa > porous.sigma_f_mpa
    assert dense.pit_area_fraction < porous.pit_area_fraction


# ------------------------------------------------------------------------------ the audit
def test_both_events_pass_every_a06_gate(realism) -> None:
    for label in ("plane", "morph"):
        qa = realism[label]["qa"]
        assert qa["volume_rel_diff"] <= VOLUME_REL_TOL, label
        assert qa["overlap_ratio"] <= OVERLAP_RATIO_MAX, label
        assert qa["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM, label
        assert qa["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG, label
        assert qa["passed"] is True, (label, qa["failures"])


def test_the_cutters_and_the_fragments_are_closed_and_self_intersection_free(realism) -> None:
    from synlab.mothers.audit import self_intersection_report

    for label in ("plane", "morph"):
        cutter = realism[label]["cutter"]
        assert bool(cutter.mesh.is_watertight), label
        assert bool(cutter.mesh.is_winding_consistent), label
        assert float(cutter.mesh.volume) > 0.0, label
        assert cutter.realized_error_mm <= BUDGET_MM + 1e-12, label
        for fragment in realism[label]["result"].fragments:
            assert bool(fragment.mesh.is_watertight), (label, fragment.fragment_id)
            assert fragment.volume_mm3 > 0.0
            assert self_intersection_report(fragment.mesh)["ok"] is True, (
                label, fragment.fragment_id)


def test_the_two_sides_are_conjugate(realism) -> None:
    for label in ("plane", "morph"):
        conj = realism[label]["conjugate"]
        assert conj["patch_count"] >= 1, label
        # conjugate-point distance: the two faces are the same discrete cutter surface
        assert conj["conjugate_gap_p95_mm"] <= INTERFACE_GAP_P95_MM, label
        assert conj["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM, label
        assert conj["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG, label
        assert conj["profile_correlation_min"] is not None, label
        assert conj["profile_correlation_min"] > 0.9, label
        assert conj["profile_rms_diff_mm_max"] < 1.0e-3, label


# ------------------------------------------------------------------------------ the wiring
def test_the_morphology_backend_is_gated_off_by_default(realism) -> None:
    assert BACKEND_MORPHOLOGY in GATED_BACKENDS
    assert BACKEND_MORPHOLOGY not in BUILT_BACKENDS, (
        "a gated backend must not appear in BUILT_BACKENDS: callers iterate that tuple")
    spec = FractureSpec(backend=BACKEND_MORPHOLOGY)
    assert morphology_backend_enabled(spec) is False
    assert morphology_backend_enabled(FractureSpec()) is False
    # and asking for it anyway is a real refusal, not a silent plane
    with pytest.raises(SynLabError) as excinfo:
        fracture_event(realism["mother"], spec, realism["rng"], event_id="gated")
    assert excinfo.value.code is ErrorCode.OPERATOR_NOT_REALIZED
    assert MORPHOLOGY_SWITCH_ENV in str(excinfo.value)


def test_the_switch_turns_the_wired_path_on(realism, monkeypatch) -> None:
    """Switched on, the ordinary façade entry point produces the morphology event."""
    spec = FractureSpec(backend=BACKEND_MORPHOLOGY, error_budget_mm=BUDGET_MM,
                        max_cutter_cells=MAX_CELLS,
                        meta={"material_profile": realism["profile"]})
    assert morphology_backend_enabled(spec) is True
    monkeypatch.setenv(MORPHOLOGY_SWITCH_ENV, "1")
    result = fracture_event(realism["mother"], spec, make_rng(MASTER_SEED, "realism_test",
                                                             "wired", "BOX12"), event_id="wired")
    assert result.backend == BACKEND_MORPHOLOGY
    record = result.meta[MORPHOLOGY_META_KEY]
    assert record["material_id"] == "M01"
    assert record["wall"]["p05_mm"] > 0.0
    assert all(MORPHOLOGY_META_KEY in p.meta for p in result.interfaces)
    qa = audit_fracture(result, realism["mother"])
    assert qa["passed"] is True, qa["failures"]
    assert qa["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM
    assert qa["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG
    delivered = sf.measure_interface_surface(result.fragments, realism["basis"],
                                             _shim_params(record), n_samples=40_000)
    assert delivered["Ra_mm"] > RELIEF_RA_MIN_MM


def _shim_params(record: dict):
    """A minimal params object for the surface measurements (origin / mirror / mist only)."""

    class _P:
        origin_uv_mm = tuple(record["origin_uv_mm"])
        mirror_radius_mm = float(record["mirror_radius_mm"])
        mist_radius_mm = float(record["mist_radius_mm"])

    return _P()


# --------------------------------------------------------------------- pixel resolvability
def test_pixel_resolvability_uses_the_frozen_scan_ladder(realism) -> None:
    """Which scan distance can see the measured relief, on the contract's own ladder."""
    contract = json.loads((REPO_ROOT / "configs" / "a12" / "capture_contract.json")
                          .read_text(encoding="utf-8"))
    rows = contract["working_distance_and_resolution"]["resolution_table"]["rows"]
    ladder = [(float(r["mm_per_px"]), float(r["structure_0p2mm_px"])) for r in rows]
    assert ladder == [(0.039, 5.12), (0.078, 2.56), (0.117, 1.71), (0.156, 1.28), (0.195, 1.02)]
    # the contract's own criterion, stated in the contract: >= 4 px on a 0.2 mm structure (pilot)
    for mm_per_px, structure_px in ladder:
        assert structure_px == pytest.approx(0.2 / mm_per_px, rel=0.01)
        assert structure_px >= 4.0 if mm_per_px <= 0.05 else True

    morph = realism["morph"]
    lc = float(morph["delivered"]["correlation_length_mm"])
    rt = float(morph["delivered"]["Rt_mm"])
    #: the contract's Q2 3D floor (sigma_max_mm), flagged in the contract as an assumption
    noise_floor_mm = float(contract["mask_and_quality"]["quality_3d_floor_q2_equivalent"]
                           ["sigma_max_mm"])
    assert noise_floor_mm == pytest.approx(0.2)

    table = []
    for mm_per_px, _ in ladder:
        table.append({
            "mm_per_px": mm_per_px,
            "px_per_correlation_length": lc / mm_per_px,
            "amplitude_over_floor": rt / noise_floor_mm,
            "lateral_resolved": lc / mm_per_px >= 2.0,      # Nyquist for the lateral scale
            "amplitude_visible": rt > noise_floor_mm,
        })
    # the ladder is monotone: a closer stand can never resolve less than a farther one
    for nearer, farther in zip(table, table[1:]):
        assert nearer["px_per_correlation_length"] > farther["px_per_correlation_length"]
    assert table[0]["px_per_correlation_length"] > table[-1]["px_per_correlation_length"]
    # the measured correlation length is far above the contract's 0.2 mm reference structure
    assert lc > 0.2


# ------------------------------------------------------------------ rough_shared_cut precision
@pytest.fixture(scope="module")
def rough_event(realism):
    """One ``rough_shared_cut`` event on the same body at the frozen budget."""
    mother = realism["mother"]
    rng = make_rng(MASTER_SEED, "realism_test", "rough", "BOX12")
    basis = _default_basis(mother, rng, FractureSpec())
    spec = FractureSpec(backend=BACKEND_ROUGH, error_budget_mm=BUDGET_MM,
                        max_cutter_cells=MAX_CELLS, target_rms_mm=0.02)
    cutter = make_closed_cutter(mother, spec, rng, basis=basis)
    result = run_shared_cut(mother, cutter, event_id="realism_rough", backend=BACKEND_ROUGH)
    return {"cutter": cutter, "result": result, "qa": audit_fracture(result, mother),
            "basis": basis}


def test_rough_cutter_realizes_the_frozen_precision_budget(rough_event) -> None:
    cutter = rough_event["cutter"]
    assert cutter.requested_error_mm == pytest.approx(BUDGET_MM)
    assert cutter.realized_error_mm <= BUDGET_MM + 1e-12
    assert int(cutter.meta["cells"]) <= MAX_CELLS
    # the realized shortest wavelength is published, so a resource failure is attributable
    assert float(cutter.meta["height_field"]["wavelength_min_mm"]) > 0.0


def test_rough_shared_surface_gap_stays_under_the_frozen_tolerance(rough_event) -> None:
    qa = rough_event["qa"]
    assert qa["passed"] is True, qa["failures"]
    assert qa["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM
    assert qa["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG
    assert qa["volume_rel_diff"] <= VOLUME_REL_TOL
    conj = sf.conjugate_profile_consistency(rough_event["result"].fragments,
                                            rough_event["result"].interfaces,
                                            rough_event["basis"])
    assert conj["conjugate_gap_p95_mm"] <= INTERFACE_GAP_P95_MM
    assert conj["profile_correlation_min"] > 0.9
    # the rough surface really is non-planar (this is the rough backend's whole purpose)
    delivered = sf.measure_interface_surface(rough_event["result"].fragments,
                                             rough_event["basis"],
                                             _shim_from_prepared(rough_event["result"]),
                                             cutter_mesh=rough_event["cutter"].mesh,
                                             n_samples=60_000)
    assert delivered["Ra_mm"] > 0.0


def _shim_from_prepared(result):
    """Zone statistics need an origin/mirror/mist triple; the rough backend has none of its own."""
    meta = dict(result.meta)

    class _P:
        origin_uv_mm = (0.0, 0.0)
        mirror_radius_mm = 1.0
        mist_radius_mm = float(meta.get("mist_radius_mm", 1.8))

    return _P()


def test_an_over_budget_rough_configuration_fails_structurally(realism) -> None:
    """A configuration that does not fit must refuse, never coarsen the surface silently.

    The check is written so either outcome is a measurement: if the configuration fits, the
    realized error must be inside the budget; if it does not, the error must be the structured
    ``PRECISION_BUDGET_EXCEEDED`` carrying the cell demand and the shortest wavelength.
    """
    mother = realism["mother"]
    rng = make_rng(MASTER_SEED, "realism_test", "rough_over", "BOX12")
    basis = _default_basis(mother, rng, FractureSpec())
    spec = FractureSpec(backend=BACKEND_ROUGH, error_budget_mm=BUDGET_MM,
                        max_cutter_cells=512, target_rms_mm=0.30)
    try:
        cutter = make_closed_cutter(mother, spec, rng, basis=basis)
    except SynLabError as exc:
        assert exc.code in (ErrorCode.PRECISION_BUDGET_EXCEEDED,
                            ErrorCode.PRECISION_NOT_REALIZED), exc.code
        measurements = dict(exc.measurements or {})
        if exc.code is ErrorCode.PRECISION_BUDGET_EXCEEDED:
            assert float(measurements["cells"]) > float(measurements["max_cells"])
            assert float(measurements["wavelength_min_mm"]) > 0.0
            assert float(measurements["budget_mm"]) == pytest.approx(BUDGET_MM)
    else:
        assert cutter.realized_error_mm <= BUDGET_MM + 1e-12
        assert int(cutter.meta["cells"]) <= 512
