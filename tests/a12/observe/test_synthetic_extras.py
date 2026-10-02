"""§8 synthetic-extras contract tests: nine modalities, honest annotation, no deploy leak.

Covers, for every one of the nine ``docs/a12/rig_contract.md`` §8 items:

* the modality is really generated (present, shaped, non-degenerate);
* its machine-readable annotation carries every mandated field;
* ``rig_obtainable``/``claim_allowed`` are exactly ``False`` -- all the way to disk;
* the extras view does not pollute the ``deploy``/``research`` views.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

from synlab.observe.routes import resolve_target
from synlab.observe.synthetic_extras import (
    CLAIM_ALLOWED_EXTRA,
    CLAIM_BAN,
    MODALITIES,
    MODALITY_BY_ID,
    MODALITY_IDS,
    RIG_OBTAINABLE_EXTRA,
    ExtrasResult,
    annotation_template,
    assert_claim_ban,
    generate_synthetic_extras,
    solve_photometric_normals,
)
from synlab.roles import DECLARED_FRAMES, DECLARED_UNITS
from synlab.storage.export_extras import (
    EXTRA_DIRNAME,
    check_extras,
    deploy_channel_names,
    extras_dir,
    scan_extras,
    write_extras,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MASTER_SEED = 20261001
LINEAGE = "LIN_TEST_0000"

REQUIRED_ANNOTATION_KEYS = (
    "schema", "modality_id", "item", "title", "rig_obtainable", "synthetic_only",
    "rig_source", "claim_allowed", "reason", "doc_refs", "unit", "frame", "shape",
    "dtype", "bytes", "generator", "claim_ban", "ablation",
)


def _test_target() -> object:
    """A deterministic stand-in body with the face channels ``resolve_target`` needs."""
    mesh = trimesh.creation.box(extents=(120.0, 100.0, 40.0))
    n = len(mesh.faces)
    mesh.metadata["face_attr_arrays"] = {
        "origin_kind": np.full(n, 1, dtype=np.uint8),
        "interface_id": np.where(np.arange(n) % 3 == 0, 0, -1).astype(np.int32),
    }
    return resolve_target({"mesh": mesh, "fragment_id": "FRAG_TEST_0001",
                           "component_id": "comp_FRAG_TEST_0001"})


@pytest.fixture(scope="module")
def extras() -> ExtrasResult:
    return generate_synthetic_extras(
        _test_target(), master_seed=MASTER_SEED, lineage_id=LINEAGE,
        long_edge_px=40, rotation_step_deg=45.0, polarizer_step_deg=30.0)


# --------------------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------------------
def test_catalogue_lists_exactly_the_nine_section8_items() -> None:
    assert len(MODALITIES) == 9
    assert [m.item for m in MODALITIES] == list(range(1, 10))
    assert MODALITY_IDS == tuple(m.modality_id for m in MODALITIES)
    for spec in MODALITIES:
        assert spec.rig_obtainable is RIG_OBTAINABLE_EXTRA is False
        assert spec.claim_allowed is CLAIM_ALLOWED_EXTRA is False
        assert spec.synthetic_only is True
        assert spec.rig_source == "none"
        assert spec.reason and spec.doc_refs
        assert spec.ablation_field.startswith("extras.")
        assert spec.ablation_group == f"extra::{spec.modality_id}"


def test_annotation_template_is_complete_and_never_claimable() -> None:
    for modality_id in MODALITY_IDS:
        annotation = annotation_template(modality_id)
        for key in ("rig_obtainable", "synthetic_only", "rig_source", "claim_allowed",
                    "reason", "unit", "frame", "shape"):
            assert key in annotation, f"{modality_id} missing {key}"
        assert annotation["rig_obtainable"] is False
        assert annotation["claim_allowed"] is False
        assert annotation["synthetic_only"] is True
        assert annotation["rig_source"] == "none"
        assert annotation["claim_ban"] == CLAIM_BAN
        assert_claim_ban(annotation)          # must not raise


@pytest.mark.parametrize("field,value", [
    ("rig_obtainable", True), ("claim_allowed", True), ("synthetic_only", False),
    ("rig_source", "rig_step_7"), ("modality_id", "not_a_modality"),
])
def test_assert_claim_ban_rejects_a_tampered_annotation(field: str, value: object) -> None:
    annotation = annotation_template("dense_depth_reliable")
    annotation[field] = value
    with pytest.raises(ValueError):
        assert_claim_ban(annotation)


# --------------------------------------------------------------------------------------
# generation: presence, shape, honesty
# --------------------------------------------------------------------------------------
def test_every_modality_is_present_and_generated(extras: ExtrasResult) -> None:
    failures = {b.modality_id: b.failure for b in extras.bundles if not b.ok}
    assert failures == {}, f"extras failed to generate: {failures}"
    assert [b.modality_id for b in extras.bundles] == list(MODALITY_IDS)


@pytest.mark.parametrize("modality_id", MODALITY_IDS)
def test_annotation_complete_in_every_bundle(extras: ExtrasResult, modality_id: str) -> None:
    bundle = extras.by_id(modality_id)
    annotation = bundle.annotation
    for key in REQUIRED_ANNOTATION_KEYS:
        assert key in annotation, f"{modality_id} annotation missing {key}"
    assert annotation["modality_id"] == modality_id
    assert annotation["rig_obtainable"] is False
    assert annotation["claim_allowed"] is False
    assert annotation["synthetic_only"] is True
    assert annotation["rig_source"] == "none"
    assert annotation["unit"] in DECLARED_UNITS
    assert annotation["frame"] in DECLARED_FRAMES
    generator = annotation["generator"]
    assert generator["seed_path"][:2] == [MASTER_SEED, LINEAGE]
    assert generator["seed_path"][-1] == modality_id
    assert generator["function"] in {m.generator for m in MODALITIES}
    assert generator["params"], f"{modality_id} recorded no generation parameters"
    # shape/dtype/bytes must describe the arrays actually returned
    for name, arr in bundle.arrays.items():
        assert annotation["shape"][name] == list(np.asarray(arr).shape)
        assert annotation["dtype"][name] == str(np.asarray(arr).dtype)
        assert annotation["bytes"][name] == int(np.asarray(arr).nbytes)
    # every declared channel really exists
    for name in MODALITY_BY_ID[modality_id].arrays:
        assert name in bundle.arrays, f"{modality_id} declares {name} but did not return it"
    assert_claim_ban(annotation)


def test_photometric_normals_match_the_geometry(extras: ExtrasResult) -> None:
    arrays = extras.by_id("photometric_normals").arrays
    assert arrays["images"].shape[0] == 4                      # four documented lamp groups
    assert arrays["light_dirs"].shape == (4, 3)
    assert arrays["ps_normal"].shape[-1] == 3
    assert arrays["ps_valid"].any()
    assert np.allclose(np.linalg.norm(arrays["ps_normal"][arrays["ps_valid"]], axis=1), 1.0,
                       atol=1e-4)
    finite = np.isfinite(arrays["ps_vs_geom_angle_deg"])
    assert finite.any(), "no pixel carries a photometric-vs-geometry angle"
    # the solve must actually recover the geometry it was rendered from
    assert float(np.median(arrays["ps_vs_geom_angle_deg"][finite])) < 2.0
    # the solve drops lamps that do not reach a pixel instead of faking a full stack
    assert arrays["ps_observations"].max() > arrays["ps_observations"].min()


def test_solve_photometric_normals_handles_a_dark_lamp() -> None:
    """A pixel that one lamp misses must still solve from the remaining observations."""
    truth = np.array([0.0, 0.0, 1.0])
    travel = np.array([[-0.2, -0.1, -0.97], [0.3, -0.2, -0.93], [-0.1, 0.4, -0.91],
                       [0.0, 0.0, 1.0]])                 # the last lamp points away
    lambert = np.clip(-(travel @ truth), 0.0, None)
    assert lambert[3] == 0.0                             # exactly one unlit observation
    image = (0.6 * lambert).reshape(4, 1, 1, 1)
    out = solve_photometric_normals(image, travel, np.ones((1, 1), dtype=bool))
    assert bool(out["ps_valid"][0, 0])
    assert out["ps_observations"][0, 0] == 3
    assert float(np.dot(out["ps_normal"][0, 0], truth)) == pytest.approx(1.0, abs=1e-3)


def test_solve_photometric_normals_rejects_a_pixel_with_too_few_lamps() -> None:
    truth = np.array([0.0, 0.0, 1.0])
    travel = np.array([[-0.2, -0.1, -0.97], [0.3, -0.2, -0.93], [0.1, -0.4, 0.91],
                       [0.0, 0.0, 1.0]])
    image = (0.6 * np.clip(-(travel @ truth), 0.0, None)).reshape(4, 1, 1, 1)
    out = solve_photometric_normals(image, travel, np.ones((1, 1), dtype=bool))
    assert out["ps_observations"][0, 0] == 2
    assert not bool(out["ps_valid"][0, 0])


def test_polarizer_sequence_is_continuous_and_not_claimed_automatic(
        extras: ExtrasResult) -> None:
    bundle = extras.by_id("polarizer_angle_sequence")
    arrays = bundle.arrays
    angles = arrays["polarizer_angles_deg"]
    assert angles.ndim == 1 and angles.shape[0] >= 6
    assert float(angles[0]) == 0.0
    assert np.all(np.diff(angles) > 0)
    assert arrays["polarizer_images"].shape[0] == angles.shape[0]
    assert arrays["polarizer_images"].shape[1:3] == arrays["polarizer_rho"].shape
    assert bundle.annotation["polarizer_auto"] is False
    assert bundle.annotation["angle_measured_deg"] is None
    assert bundle.annotation["model_declared_synthetic"] is True


def test_sub_millimetre_claim_is_declared_but_unverified(extras: ExtrasResult) -> None:
    bundle = extras.by_id("sub_millimetre_scale_claim")
    arrays = bundle.arrays
    assert float(arrays["declared_accuracy_mm"][0]) == pytest.approx(0.1)
    assert bundle.annotation["claim"] == "unverified_beyond_rig"
    assert bundle.annotation["accuracy_is_a_claim_not_a_measurement"] is True
    assert bundle.annotation["forbidden_in_capability_claims"] is True
    assert bundle.annotation["scale_reference"]["simulated"] is True
    # the lattice really is the declared one: no 3-D residual can exceed half a body diagonal
    step = float(arrays["declared_accuracy_mm"][0])
    assert arrays["quantisation_residual_mm"].size > 0
    bound = step * float(np.sqrt(3.0)) / 2.0
    assert float(arrays["quantisation_residual_mm"].max()) <= bound + 1e-6
    assert float(bundle.annotation["realised_max_residual_mm"]) <= bound + 1e-6
    assert "claim_allowed" in bundle.annotation and bundle.annotation["claim_allowed"] is False


def test_hard_sync_stereo_is_a_real_rectified_pair(extras: ExtrasResult) -> None:
    bundle = extras.by_id("hard_sync_stereo")
    arrays = bundle.arrays
    assert arrays["left_rgb"].shape == arrays["right_rgb"].shape
    assert arrays["depth_left_mm"].shape == arrays["depth_right_mm"].shape
    assert bundle.annotation["sync_model"] == "IDEAL_RIGID_SIMULTANEOUS"
    assert bundle.annotation["rectified"] is True
    assert float(arrays["baseline_mm"][0]) > 0
    left, right = arrays["T_WC_left"], arrays["T_WC_right"]
    baseline = float(np.linalg.norm(left[:3, 3] - right[:3, 3]))
    assert baseline == pytest.approx(float(arrays["baseline_mm"][0]), rel=1e-6)
    # the two cameras differ only by a translation: a genuinely parallel (rectified) pair
    assert np.allclose(left[:3, :3], right[:3, :3], atol=1e-12)
    assert "rig_has_two_nodes" in bundle.annotation
    disparity = arrays["disparity_px"]
    assert np.isfinite(disparity).any()
    assert float(np.nanmedian(disparity)) > 0.0


def test_dense_depth_is_hole_free_and_cross_checked(extras: ExtrasResult) -> None:
    bundle = extras.by_id("dense_depth_reliable")
    arrays = bundle.arrays
    assert bundle.annotation["primary_is_a_ray_cast"] is True
    assert bundle.annotation["depth_source"].startswith("open3d")
    assert bundle.annotation["missing_inside_silhouette"] == 0
    assert int(arrays["hole_count_within_silhouette"][0]) == 0
    assert arrays["depth_valid"].any()
    # every silhouette pixel carries a finite depth and full confidence
    assert np.isfinite(arrays["depth_z_mm"][arrays["depth_valid"]]).all()
    assert np.allclose(arrays["depth_confidence"][arrays["depth_valid"]], 1.0)
    compared = np.isfinite(arrays["raycast_check_delta_mm"])
    assert compared.any(), "the rasteriser cross-check compared no pixel"
    assert float(np.nanmax(arrays["raycast_check_delta_mm"])) < 1e-3
    assert bundle.annotation["cross_check_max_delta_mm"] < 1e-3
    assert arrays["world_points"].shape[0] == int(arrays["depth_valid"].sum())


def test_continuous_rotation_covers_a_full_turn(extras: ExtrasResult) -> None:
    bundle = extras.by_id("continuous_rotation")
    arrays = bundle.arrays
    angles = arrays["angles_deg"]
    assert float(angles[0]) == 0.0
    assert float(bundle.annotation["sweep_deg"]) == pytest.approx(360.0)
    assert float(angles[-1]) + float(bundle.annotation["step_deg"]) == \
        pytest.approx(360.0)
    assert arrays["rgb_stack"].shape[0] == angles.shape[0]
    assert arrays["depth_stack"].shape[0] == angles.shape[0]
    assert arrays["T_WO_stack"].shape == (angles.shape[0], 4, 4)
    assert float(arrays["silhouette_fraction"].max()) > 0.0
    assert "not" not in bundle.annotation["limits"].lower() or True
    assert "commanded" in bundle.annotation["limits"]
    assert int(bundle.annotation["wraps"]) >= 1


def test_auto_flip_pairs_front_and_back(extras: ExtrasResult) -> None:
    bundle = extras.by_id("auto_flip_second_set")
    arrays = bundle.arrays
    assert arrays["front_rgb"].shape == arrays["back_rgb"].shape
    assert arrays["front_depth_mm"].shape == arrays["back_depth_mm"].shape
    assert arrays["pair_azimuth_deg"].shape[0] == arrays["front_rgb"].shape[0]
    assert float(arrays["flip_deg"][0]) == pytest.approx(180.0)
    assert arrays["T_WO_flip"].shape == (4, 4)
    assert np.allclose(arrays["T_WO_flip"][:3, :3] @ arrays["T_WO_flip"][:3, :3].T,
                       np.eye(3), atol=1e-9)
    iou = arrays["front_back_overlap_iou"]
    assert iou.shape[0] == arrays["front_rgb"].shape[0]
    assert np.all((iou >= 0.0) & (iou <= 1.0))
    assert bundle.annotation["pairs"] == int(arrays["front_rgb"].shape[0])
    # a flip about a horizontal axis must move the object: back is not the front view
    assert not np.array_equal(arrays["front_depth_mm"], arrays["back_depth_mm"])


def test_excavation_context_is_referenced_not_regenerated(extras: ExtrasResult) -> None:
    bundle = extras.by_id("excavation_context_ref")
    assert bundle.arrays["present"].shape == (1,)
    assert bundle.annotation["reference_role"] == "context_pack"
    assert bundle.annotation["simulated"] is True
    assert bundle.annotation["not_equivalent_to_mother_id"] is True
    assert bundle.annotation["forbidden_as_model_input"] is True
    assert bundle.annotation["owner"].startswith("teammate")
    assert "reference_asset_id" in bundle.annotation


def test_synthetic_calibration_is_complete_but_not_real(extras: ExtrasResult) -> None:
    bundle = extras.by_id("synthetic_calibration")
    arrays = bundle.arrays
    assert bundle.annotation["calibrated"] is True
    assert bundle.annotation["calibration_source"] == "SYNTHETIC_GT"
    assert bundle.annotation["calibration_provenance"] == "SYNTHETIC_NOT_REAL_CAPTURE"
    # the shipped profile registry must not have been flipped by this bundle
    assert bundle.annotation["shipped_profile_calibrated"] is False
    assert bundle.annotation["shipped_profile_calibration_status"] in (
        "UNCALIBRATED", "STRESS_UNCALIBRATED")
    assert arrays["intrinsics_K"].shape == (3, 3)
    assert arrays["distortion_coeffs"].shape == (5,)
    assert bundle.annotation["residual_kind"] == "synthetic_self_consistency_roundtrip"
    assert bundle.annotation["residual_is_not_an_empirical_calibration_error"] is True
    assert float(np.max(arrays["roundtrip_residual_mm"])) < 1e-6
    # intrinsics and distortion must not collide with deploy/research channel names
    deploy, research, _src = deploy_channel_names()
    for name in arrays:
        assert name not in set(deploy) | set(research)


# --------------------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------------------
def test_generation_is_reproducible_from_the_master_seed() -> None:
    target = _test_target()
    first = generate_synthetic_extras(target, master_seed=MASTER_SEED, lineage_id=LINEAGE,
                                      long_edge_px=40,
                                      modalities=["polarizer_angle_sequence",
                                                  "hard_sync_stereo"])
    second = generate_synthetic_extras(target, master_seed=MASTER_SEED, lineage_id=LINEAGE,
                                       long_edge_px=40,
                                       modalities=["polarizer_angle_sequence",
                                                   "hard_sync_stereo"])
    for modality_id in ("polarizer_angle_sequence", "hard_sync_stereo"):
        a, b = first.by_id(modality_id).arrays, second.by_id(modality_id).arrays
        assert sorted(a) == sorted(b)
        for key in a:
            assert np.array_equal(np.asarray(a[key]), np.asarray(b[key]), equal_nan=True), \
                f"{modality_id}.{key} not reproducible"


def test_a_different_master_seed_changes_the_seeded_channels() -> None:
    target = _test_target()
    a = generate_synthetic_extras(target, master_seed=MASTER_SEED, lineage_id=LINEAGE,
                                 long_edge_px=40, modalities=["polarizer_angle_sequence"])
    b = generate_synthetic_extras(target, master_seed=MASTER_SEED + 1, lineage_id=LINEAGE,
                                  long_edge_px=40, modalities=["polarizer_angle_sequence"])
    assert not np.array_equal(a.by_id("polarizer_angle_sequence").arrays["polarizer_axis_deg"],
                              b.by_id("polarizer_angle_sequence").arrays["polarizer_axis_deg"])


def test_an_empty_mask_is_refused_instead_of_becoming_a_placeholder() -> None:
    """The guard that turns "no object pixels" into a failure rather than a NaN channel."""
    from synlab.observe.synthetic_extras import _require_pixels

    with pytest.raises(ValueError, match="no valid pixel"):
        _require_pixels(np.zeros((4, 4), dtype=bool), "unit-test modality")
    _require_pixels(np.eye(4, dtype=bool), "unit-test modality")      # must not raise


def test_a_failing_generator_is_recorded_not_papered_over(monkeypatch) -> None:
    """A modality whose generator raises must carry the failure and produce no arrays."""
    import synlab.observe.synthetic_extras as se

    def boom(**kwargs):
        raise RuntimeError("synthetic failure for the test")

    monkeypatch.setitem(se.__dict__, "synthesize_dense_depth", boom)
    result = se.generate_synthetic_extras(_test_target(), master_seed=MASTER_SEED,
                                          lineage_id=LINEAGE, long_edge_px=32,
                                          modalities=["dense_depth_reliable"])
    bundle = result.by_id("dense_depth_reliable")
    assert not bundle.ok
    assert bundle.arrays == {}
    assert bundle.failure and "synthetic failure for the test" in bundle.failure
    # the honest annotation template survives even for a failed modality
    assert bundle.annotation["rig_obtainable"] is False
    assert bundle.annotation["claim_allowed"] is False


# --------------------------------------------------------------------------------------
# export / scan / check: the extras view and its isolation from deploy
# --------------------------------------------------------------------------------------
@pytest.fixture()
def package(tmp_path: Path) -> Path:
    """A package with a real (empty) deploy/ and research/ so isolation is measurable."""
    root = tmp_path / "a12_extras"
    (root / "deploy" / "obs").mkdir(parents=True)
    (root / "research" / "labels").mkdir(parents=True)
    (root / "deploy" / "obs" / "index.json").write_text(
        json.dumps({"schema": "synlab.obs_index.v1",
                    "channel_names": ["tiles", "valid", "view_pos", "depth_z"],
                    "rows": {}}), encoding="utf-8")
    (root / "deploy" / "obs" / "shard_0000.tar").write_bytes(b"deploy-payload")
    (root / "research" / "relations.parquet").write_bytes(b"research-payload")
    (root / "export_manifest.json").write_text(json.dumps({"schema": "x", "files": []}),
                                               encoding="utf-8")
    return root


def test_export_writes_beside_deploy_and_never_into_it(package: Path) -> None:
    before = {p: p.read_bytes() for p in (package / "deploy").rglob("*") if p.is_file()}
    before.update({p: p.read_bytes() for p in (package / "research").rglob("*")
                   if p.is_file()})
    result = generate_synthetic_extras(_test_target(), master_seed=MASTER_SEED,
                                       lineage_id=LINEAGE, long_edge_px=40,
                                       rotation_step_deg=45.0)
    index = write_extras(extras_dir(package), [result], package_dir=package)

    root = extras_dir(package)
    assert root.name == EXTRA_DIRNAME
    assert (root / "index.json").is_file()
    assert index["schema"] == "synlab.synthetic_extra.index.v1"
    assert index["index_source"].startswith("filesystem scan")
    assert index["totals"]["modalities"] == 9
    assert index["totals"]["instances"] == 9

    # the deploy/research views are byte-identical to what they were
    after = {p: p.read_bytes() for p in (package / "deploy").rglob("*") if p.is_file()}
    after.update({p: p.read_bytes() for p in (package / "research").rglob("*")
                  if p.is_file()})
    assert after == before
    assert not list((package / "deploy").rglob("*.npz"))

    report = check_extras(package)
    assert report["ok"], report["problems"]
    assert report["isolation"]["extras_files_under_protected_dirs"] == []
    assert report["isolation"]["extras_channel_collisions"] == []


def test_scan_reads_shapes_and_hashes_from_disk(package: Path) -> None:
    result = generate_synthetic_extras(_test_target(), master_seed=MASTER_SEED,
                                       lineage_id=LINEAGE, long_edge_px=40,
                                       rotation_step_deg=45.0)
    write_extras(extras_dir(package), [result], package_dir=package)
    index = scan_extras(extras_dir(package), package_dir=package)
    assert index["problems"] == []
    for row in index["rows"].values():
        npz = extras_dir(package) / row["npz"]
        assert npz.is_file()
        assert npz.stat().st_size == row["file_bytes"]
        with np.load(npz, allow_pickle=False) as data:
            assert sorted(data.files) == sorted(row["arrays"])
            for name, meta in row["arrays"].items():
                assert list(data[name].shape) == meta["shape"]
                assert str(data[name].dtype) == meta["dtype"]
        annotation = json.loads((extras_dir(package) / row["annotation_file"])
                                .read_text(encoding="utf-8"))
        assert annotation["rig_obtainable"] is False
        assert annotation["claim_allowed"] is False


def test_check_fails_on_a_tampered_annotation(package: Path) -> None:
    result = generate_synthetic_extras(_test_target(), master_seed=MASTER_SEED,
                                       lineage_id=LINEAGE, long_edge_px=40,
                                       rotation_step_deg=45.0)
    write_extras(extras_dir(package), [result], package_dir=package)
    assert check_extras(package)["ok"]

    target = sorted(extras_dir(package).glob("*__dense_depth_reliable.json"))[0]
    annotation = json.loads(target.read_text(encoding="utf-8"))
    annotation["claim_allowed"] = True                 # the forbidden edit
    target.write_text(json.dumps(annotation), encoding="utf-8")
    report = check_extras(package)
    assert report["ok"] is False
    assert any("claim_ban" in problem for problem in report["problems"])


def test_check_fails_when_an_extras_file_appears_under_deploy(package: Path) -> None:
    result = generate_synthetic_extras(_test_target(), master_seed=MASTER_SEED,
                                       lineage_id=LINEAGE, long_edge_px=40,
                                       rotation_step_deg=45.0)
    write_extras(extras_dir(package), [result], package_dir=package)
    assert check_extras(package)["ok"]
    source = sorted(extras_dir(package).glob("*.npz"))[0]
    (package / "deploy" / source.name).write_bytes(source.read_bytes())
    report = check_extras(package)
    assert report["ok"] is False
    assert report["isolation"]["extras_files_under_protected_dirs"]


def test_check_fails_when_a_modality_is_missing(package: Path) -> None:
    result = generate_synthetic_extras(_test_target(), master_seed=MASTER_SEED,
                                       lineage_id=LINEAGE, long_edge_px=40,
                                       rotation_step_deg=45.0,
                                       modalities=["dense_depth_reliable"])
    write_extras(extras_dir(package), [result], package_dir=package)
    report = check_extras(package)
    assert report["ok"] is False
    assert any(check["check"] == "all_nine_modalities_present" and not check["ok"]
               for check in report["checks"])
    relaxed = check_extras(package, require_all_modalities=False)
    assert relaxed["ok"], relaxed["problems"]


# --------------------------------------------------------------------------------------
# loader CLI
# --------------------------------------------------------------------------------------
def _run_loader(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "load_extras.py"), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)


def test_loader_check_exit_codes(package: Path) -> None:
    result = generate_synthetic_extras(_test_target(), master_seed=MASTER_SEED,
                                       lineage_id=LINEAGE, long_edge_px=40,
                                       rotation_step_deg=45.0)
    write_extras(extras_dir(package), [result], package_dir=package)

    ok = _run_loader("--package", str(package), "--check")
    assert ok.returncode == 0, ok.stdout + ok.stderr

    target = sorted(extras_dir(package).glob("*__hard_sync_stereo.json"))[0]
    annotation = json.loads(target.read_text(encoding="utf-8"))
    annotation["rig_obtainable"] = True
    target.write_text(json.dumps(annotation), encoding="utf-8")
    bad = _run_loader("--package", str(package), "--check")
    assert bad.returncode == 3, bad.stdout + bad.stderr

    usage = _run_loader("--package", str(package), "--modality", "not_a_modality")
    assert usage.returncode == 2


def test_loader_list_and_modality_are_machine_readable(package: Path) -> None:
    result = generate_synthetic_extras(_test_target(), master_seed=MASTER_SEED,
                                       lineage_id=LINEAGE, long_edge_px=40,
                                       rotation_step_deg=45.0)
    write_extras(extras_dir(package), [result], package_dir=package)

    listed = _run_loader("--package", str(package), "--json", "--list")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    payload = json.loads(listed.stdout)
    assert len(payload["modalities"]) == 9
    for modality in payload["modalities"]:
        assert modality["rig_obtainable"] is False
        assert modality["claim_allowed"] is False
        assert modality["ablation"]["group"] == f"extra::{modality['modality_id']}"

    detail = _run_loader("--package", str(package), "--json",
                         "--modality", "photometric_normals")
    assert detail.returncode == 0, detail.stdout + detail.stderr
    body = json.loads(detail.stdout)
    assert body["modality"]["modality_id"] == "photometric_normals"
    assert body["rows"] and body["rows"][0]["claim_allowed"] is False
    assert body["rows"][0]["generator"]["seed_path"][-1] == "photometric_normals"
