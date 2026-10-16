from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.errors import ErrorCode, SynLabError  # noqa: E402
from synlab.integrations import native_bowl as native_bowl_module  # noqa: E402
from synlab.integrations.native_bowl import (  # noqa: E402
    DATASET_MANIFEST_SCHEMA,
    FEATURE_VIEW_SCHEMA,
    NativeBowlDataset,
    PG_RESULT_SCHEMA,
    export_native_bowl_dataset,
    ingest_native_bowl_run,
    load_native_bowl_dataset,
    validate_ingested_native_bowl_run,
    validate_native_bowl_run,
)


RHO = 2300.0
E_PA = 70.0e9
NU = 0.25
GC = 7.6
OUTER_M = 0.012
INNER_M = 0.008
CENTER_M = np.asarray([0.0, 0.0, 0.012], dtype=np.float64)
H_M = 1e-3
DELTA_M = 2.5e-3


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_forge_asset(root: Path) -> Path:
    root.mkdir(parents=True)
    for folder in ("geometry", "fields", "validation"):
        (root / folder).mkdir()
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    for index in range(5):
        x = (index - 2) * 1.5
        start = len(vertices)
        vertices.extend([[x - 0.45, -0.5, 0.0], [x, 0.5, 0.0], [x + 0.45, -0.5, 0.0]])
        faces.append([start, start + 1, start + 2])
    vertices_array = np.asarray(vertices, dtype=np.float64)
    faces_array = np.asarray(faces, dtype=np.int32)
    np.savez(root / "geometry/surface.npz", vertices_mm=vertices_array, faces=faces_array)
    np.savez(root / "fields/surface.npz",
             face_region=np.asarray([1, 2, 3, 4, 5], dtype=np.uint8),
             albedo_linear_rgb=np.full((5, 3), 0.45, dtype=np.float32),
             roughness=np.full(5, 0.78, dtype=np.float32),
             vertices_material_xyz_mm=vertices_array.copy())
    (root / "geometry/solid.step").write_bytes(b"native-bowl synthetic geometry fixture")
    (root / "validation/geometry.json").write_text(json.dumps({
        "status": "PASS", "scope": "geometry_only", "checks": {"fixture_valid": True},
    }), encoding="utf-8")
    recipe = {
        "material_binding_id": "bowl_prototype",
        "historical_style_validation": "NOT_VALIDATED",
        "geometry_relief_mm": 0.0,
        "target_region_codes": [1],
    }
    records = {}
    for relative in ("fields/surface.npz", "geometry/surface.npz", "geometry/solid.step",
                     "validation/geometry.json"):
        path = root / relative
        records[relative] = {"bytes": path.stat().st_size, "sha256": _sha(path)}
    manifest = {
        "schema": "forge.asset.v1",
        "units": {"length": "mm", "time": "s", "mass": "kg"},
        "frame": "right_handed_z_up",
        "geometry": {"surface_npz": "geometry/surface.npz", "solid_step": "geometry/solid.step"},
        "fields": {"surface_fields_npz": "fields/surface.npz"},
        "material": {
            "id": "bowl_prototype", "calibration_status": "UNVALIDATED_PROTOTYPE",
            "mechanics": {"rho_kg_m3": RHO, "E_pa": E_PA, "nu": NU, "Gc_j_m2": GC},
        },
        "ornament": {"kind": "painted", "recipe": recipe},
        "files": records,
        "provenance": {
            "producer": "A12 native bowl test fixture", "seed": 17,
            "spec": {
                "shape": "concentric_lower_hemisphere",
                "outer_radius_mm": 12.0, "inner_radius_mm": 8.0,
                "center_xyz_mm": [0.0, 0.0, 12.0],
            },
        },
        "validation": {"report": "validation/geometry.json", "status": "PASS",
                       "scope": "geometry_only"},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return root


def _fixture_arrays() -> dict[str, np.ndarray]:
    x_ref = np.asarray([
        [0.0000, 0.0000, 0.0030],
        [0.0010, 0.0000, 0.0031],
        [0.0010, 0.0010, 0.0032],
        [0.0020, 0.0010, 0.0033],
    ], dtype=np.float64)
    bond_i = np.asarray([0, 1], dtype=np.int32)
    bond_j = np.asarray([1, 2], dtype=np.int32)
    rest = np.linalg.norm(x_ref[bond_j] - x_ref[bond_i], axis=1)
    position = np.repeat(x_ref[None, :, :], 3, axis=0)
    event_stretch = 0.02
    unit = (x_ref[1] - x_ref[0]) / rest[0]
    position[1:, 1] = x_ref[0] + unit * rest[0] * (1.0 + event_stretch)
    velocity = np.arange(36, dtype=np.float64).reshape(3, 4, 3) / 17.0
    damage = np.asarray([[0.0, 0.0, 0.0, 0.0],
                         [1.0, 0.5, 0.0, 0.0],
                         [1.0, 0.5, 0.0, 0.0]], dtype=np.float32)
    active = np.asarray([[1, 1], [0, 1], [0, 1]], dtype=np.uint8)
    packed = np.packbits(active, axis=1, bitorder="little")
    components = np.asarray([[0, 0, 0, 3], [0, 1, 1, 3], [0, 1, 1, 3]], dtype=np.int32)
    volume = np.full(4, H_M**3, dtype=np.float64)
    point_mass = volume * RHO
    bulk = E_PA / (3.0 * (1.0 - 2.0 * NU))
    critical = math.sqrt(5.0 * GC / (9.0 * bulk * DELTA_M))
    actual_stretch = (np.linalg.norm(position[1, 1] - position[1, 0]) - rest[0]) / rest[0]
    constant = 18.0 * bulk / (math.pi * DELTA_M**4)
    event_energy = 0.5 * constant * volume[0] * volume[1] * rest[0] * actual_stretch**2
    return {
        "point_id": np.arange(4, dtype=np.int32),
        "x_ref_m": x_ref,
        "position_m": position,
        "velocity_mps": velocity,
        "damage": damage,
        "step": np.asarray([0, 1, 2], dtype=np.int32),
        "time_s": np.asarray([0.0, 0.1, 0.2], dtype=np.float64),
        "volume_m3": volume,
        "point_mass_kg": point_mass,
        "bond_i": bond_i,
        "bond_j": bond_j,
        "bond_rest_length_m": rest.astype(np.float64),
        "bond_epsilon_c": np.full(2, critical, dtype=np.float64),
        "bond_first_break_step": np.asarray([1, -1], dtype=np.int32),
        "bond_first_break_time_s": np.asarray([0.1, -1.0], dtype=np.float64),
        "bond_first_break_stretch": np.asarray([actual_stretch, -1.0], dtype=np.float64),
        "bond_active_packed": packed.astype(np.uint8),
        "component_label": components,
        "event_bond_index": np.asarray([0], dtype=np.int32),
        "event_step": np.asarray([1], dtype=np.int32),
        "event_time_s": np.asarray([0.1], dtype=np.float64),
        "event_stretch": np.asarray([actual_stretch], dtype=np.float64),
        "event_pair_energy_J": np.asarray([event_energy], dtype=np.float64),
    }


def _write_pg_run(root: Path, forge_root: Path, *, arrays: dict[str, np.ndarray] | None = None) -> Path:
    root.mkdir(parents=True)
    data = arrays or _fixture_arrays()
    source_path = root / "source_snapshot" / "runner.py"
    source_path.parent.mkdir()
    source_path.write_text("# frozen test runner\n", encoding="utf-8")
    arrays_path = root / "arrays.npz"
    np.savez_compressed(arrays_path, **data)
    digest = _sha(arrays_path)
    byte_count = arrays_path.stat().st_size
    vf_manifest_sha = _sha(forge_root / "manifest.json")
    total_mass = float(np.sum(data["point_mass_kg"], dtype=np.float64))
    analytic_volume = 2.0 * math.pi / 3.0 * (OUTER_M**3 - INNER_M**3)
    result = {
        "schema": PG_RESULT_SCHEMA,
        "status": "PASS",
        "run_id": "native_bowl_fixture_3steps",
        "source_forge_manifest_sha256": vf_manifest_sha,
        "source_receipts": [{"path": "source_snapshot/runner.py",
                             "sha256": _sha(source_path),
                             "bytes": source_path.stat().st_size}],
        "source_forge_asset": {"manifest_schema": "forge.asset.v1",
                                "geometry_scope": "geometry_only",
                                "declared_geometry_status": "PASS"},
        "geometry": {
            "shape": "concentric_lower_hemisphere_shell",
            "outer_radius_m": OUTER_M, "inner_radius_m": INNER_M,
            "center_m": CENTER_M.tolist(), "h_m": H_M, "delta_m": DELTA_M,
            "n_points": int(data["point_id"].size),
            "analytic_volume_m3": analytic_volume,
        },
        "material": {
            "rho_kg_m3": RHO, "E_pa": E_PA, "nu": NU, "Gc_j_m2": GC,
            "calibration_status": "UNVALIDATED_PROTOTYPE",
            "model_mass_status": "DISCRETE_MODEL_MASS_FROM_APPROXIMATE_H3_VOLUMES_NOT_MEASURED",
            "total_mass_kg": total_mass,
        },
        "solver": {"steps": int(data["step"][-1])},
        "results": {
            "point_count": int(data["point_id"].size),
            "canonical_initial_pair_count": int(data["bond_i"].size),
            "initial_geometric_exclusion_count": 0,
            "broken_pair_count": int(data["event_bond_index"].size),
            "reported_point_mass_sum_kg": total_mass,
            "persistent_output_bytes": byte_count + source_path.stat().st_size,
        },
        "arrays": {"path": "arrays.npz", "sha256": digest,
                    "bytes": byte_count, "format": "npz"},
        "outputs": [{"path": "arrays.npz", "sha256": digest, "bytes": byte_count}],
    }
    (root / "result.json").write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    return root


def _rewrite_pg_arrays(pg_root: Path, change) -> None:
    result_path = pg_root / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    arrays_path = pg_root / result["arrays"]["path"]
    with np.load(arrays_path, allow_pickle=False) as source:
        arrays = {key: np.array(source[key], copy=True) for key in source.files}
    change(arrays)
    np.savez_compressed(arrays_path, **arrays)
    digest, byte_count = _sha(arrays_path), arrays_path.stat().st_size
    result["arrays"].update({"sha256": digest, "bytes": byte_count})
    result["outputs"][0].update({"sha256": digest, "bytes": byte_count})
    result["results"]["persistent_output_bytes"] = sum(
        path.stat().st_size for path in pg_root.rglob("*")
        if path.is_file() and path.name != "result.json"
    )
    result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")


@pytest.fixture
def verified_source(tmp_path: Path) -> tuple[Path, Path]:
    forge = _write_forge_asset(tmp_path / "vf")
    pg = _write_pg_run(tmp_path / "pg", forge)
    return forge, pg


def test_native_bowl_validate_ingest_export_loader_and_sensor_frame_alignment(
    tmp_path: Path, verified_source: tuple[Path, Path],
) -> None:
    forge, pg = verified_source
    report = validate_native_bowl_run(forge, pg)
    assert report["source"]["source_forge_manifest_sha256"] == _sha(forge / "manifest.json")
    assert report["counts"]["points"] == 4
    assert report["counts"]["point_mass_sum_kg"] == pytest.approx(4 * H_M**3 * RHO)
    assert report["qualification"]["observation_kind"] == "SIMULATION_POINT_SNAPSHOT"
    assert report["qualification"]["rig_obtainable"] is False
    assert report["qualification"]["r2_status"] == "UNKNOWN"
    assert report["qualification"]["pretrain_eligible"] is False

    run = tmp_path / "run"
    run_manifest = ingest_native_bowl_run(forge, pg, run)
    assert validate_ingested_native_bowl_run(run)["source"] == report["source"]
    assert run_manifest["status"] == "SOURCE_VERIFIED_DIAGNOSTIC_ONLY"
    dataset_path = tmp_path / "dataset"
    dataset_manifest = export_native_bowl_dataset(run, dataset_path, seed=31415,
                                                  state_indices=[0, 2])
    loaded = load_native_bowl_dataset(dataset_path)
    assert dataset_manifest["schema"] == DATASET_MANIFEST_SCHEMA
    assert dataset_manifest["output_kind"] == "RESEARCH_ONLY_POINT_SNAPSHOT_DATASET_NO_SHARDS"
    assert dataset_manifest["qualification"]["negative_labels"] == "NOT_GENERATED"
    assert dataset_manifest["qualification"]["pretrain_eligible"] is False
    assert dataset_manifest["research_feature_view"]["schema"] == FEATURE_VIEW_SCHEMA
    assert dataset_manifest["research_feature_view"]["rig_obtainable"] is False
    assert set(loaded.research_features) == {"position_m"}
    assert "bond_active_packed" in loaded.physics_targets
    assert "point_id" not in loaded.research_features
    assert {p.name for p in dataset_path.iterdir()} == {
        "dataset_manifest.json", "research_feature_view.npz", "physics_target.npz",
    }

    targets = loaded.physics_targets
    alignment = loaded.aligned_targets()
    selected = targets["selected_state_index"].astype(np.int64)
    point_map = targets["feature_to_point_index"].astype(np.int64)
    rotation = targets["frame_rotation_world_to_sensor"]
    expected_world = targets["velocity_mps"][selected[:, None], point_map]
    expected_sensor = np.matmul(expected_world, np.swapaxes(rotation, 1, 2))
    expected_damage = targets["damage"][selected[:, None], point_map]
    assert np.allclose(alignment["velocity_mps"], expected_sensor, rtol=0.0, atol=1e-14)
    assert np.allclose(alignment["damage"], expected_damage, rtol=0.0, atol=1e-7)
    assert not np.allclose(alignment["velocity_mps"], expected_world)
    assert dataset_manifest["physics_target"]["aligned_velocity_frame"] == \
        "INDEPENDENT_RANDOM_SENSOR_FRAME_PER_STATE"


def test_aligned_velocity_uses_hand_computable_nonidentity_sensor_rotation() -> None:
    # +90 degrees around z; row vectors use v_sensor = v_world @ R.T.
    # Therefore (x, y, z) maps to (-y, x, z).
    rotation = np.asarray([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    velocities = np.asarray([[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]])
    damage = np.asarray([[0.1, 0.4, 0.8]], dtype=np.float32)
    targets = {
        "selected_state_index": np.asarray([0]),
        "feature_to_point_index": np.asarray([[2, 0]]),
        "frame_rotation_world_to_sensor": rotation[None, :, :],
        "velocity_mps": velocities,
        "damage": damage,
    }
    aligned = NativeBowlDataset({}, {}, targets).aligned_targets()
    np.testing.assert_allclose(aligned["velocity_mps"], [[[-8.0, 7.0, 9.0], [-2.0, 1.0, 3.0]]])
    np.testing.assert_allclose(aligned["damage"], [[0.8, 0.1]])


def test_source_forge_manifest_is_bound_by_exact_manifest_bytes(
    tmp_path: Path, verified_source: tuple[Path, Path],
) -> None:
    forge, pg = verified_source
    with (forge / "manifest.json").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(SynLabError) as excinfo:
        validate_native_bowl_run(forge, pg)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert excinfo.value.measurements["field"] == "source_forge_manifest_sha256"


def test_source_snapshot_receipts_are_rechecked_against_exact_bytes(
    verified_source: tuple[Path, Path],
) -> None:
    forge, pg = verified_source
    (pg / "source_snapshot" / "runner.py").write_text("# changed after receipt\n", encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        validate_native_bowl_run(forge, pg)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert "source_receipts" in str(excinfo.value.measurements["field"])


def test_ingest_manifest_cannot_promote_unknown_qualification(
    tmp_path: Path, verified_source: tuple[Path, Path],
) -> None:
    forge, pg = verified_source
    run = tmp_path / "run"
    ingest_native_bowl_run(forge, pg, run)
    manifest_path = run / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["qualification"]["r2_status"] = "R0"
    manifest["manifest_sha256"] = native_bowl_module._manifest_hash(manifest)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        validate_ingested_native_bowl_run(run)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert excinfo.value.measurements["field"] == "qualification"


def test_every_point_mass_including_isolated_points_must_match_rho_times_volume(
    tmp_path: Path, verified_source: tuple[Path, Path],
) -> None:
    forge, pg = verified_source
    _rewrite_pg_arrays(pg, lambda arrays: arrays["point_mass_kg"].__setitem__(-1,
                                                                                arrays["point_mass_kg"][-1] * 2))
    with pytest.raises(SynLabError) as excinfo:
        validate_native_bowl_run(forge, pg)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert excinfo.value.measurements["field"] == "point_mass_kg"


def test_active_graph_reactivation_and_component_disagreement_fail_closed(
    tmp_path: Path, verified_source: tuple[Path, Path],
) -> None:
    forge, pg = verified_source
    _rewrite_pg_arrays(pg, lambda arrays: arrays["bond_active_packed"].__setitem__(2, [3]))
    with pytest.raises(SynLabError) as excinfo:
        validate_native_bowl_run(forge, pg)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert "active" in str(excinfo.value).lower()

    forge2 = _write_forge_asset(tmp_path / "vf2")
    pg2 = _write_pg_run(tmp_path / "pg2", forge2)
    _rewrite_pg_arrays(pg2, lambda arrays: arrays["component_label"].__setitem__((2, 1), 0))
    with pytest.raises(SynLabError) as excinfo2:
        validate_native_bowl_run(forge2, pg2)
    assert excinfo2.value.code == ErrorCode.SCHEMA_INVALID
    assert "component" in str(excinfo2.value).lower()


def test_source_material_must_be_unvalidated_and_bound_without_override(
    tmp_path: Path, verified_source: tuple[Path, Path],
) -> None:
    forge, pg = verified_source
    result_path = pg / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["material"]["rho_kg_m3"] = RHO / 2
    result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        validate_native_bowl_run(forge, pg)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert excinfo.value.measurements["field"] == "material.rho_kg_m3"


def test_payload_tamper_is_detected_before_array_loading(
    verified_source: tuple[Path, Path],
) -> None:
    forge, pg = verified_source
    with (pg / "arrays.npz").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(SynLabError) as excinfo:
        validate_native_bowl_run(forge, pg)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert "payload size or SHA-256" in str(excinfo.value)


def test_paths_and_event_times_fail_closed(
    tmp_path: Path, verified_source: tuple[Path, Path],
) -> None:
    forge, pg = verified_source
    result_path = pg / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["arrays"]["path"] = "../arrays.npz"
    result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    with pytest.raises(SynLabError) as path_error:
        validate_native_bowl_run(forge, pg)
    assert path_error.value.measurements["field"] == "arrays.path"

    forge2 = _write_forge_asset(tmp_path / "vf2")
    pg2 = _write_pg_run(tmp_path / "pg2", forge2)

    def shift_event_time(arrays: dict[str, np.ndarray]) -> None:
        arrays["event_time_s"][0] = 0.15
        arrays["bond_first_break_time_s"][0] = 0.15

    _rewrite_pg_arrays(pg2, shift_event_time)
    with pytest.raises(SynLabError) as event_error:
        validate_native_bowl_run(forge2, pg2)
    assert event_error.value.measurements["field"] == "event_time_s"


def test_loader_rejects_answer_leakage_and_r0_promotion(
    tmp_path: Path, verified_source: tuple[Path, Path],
) -> None:
    forge, pg = verified_source
    run = tmp_path / "run"
    ingest_native_bowl_run(forge, pg, run)
    dataset = tmp_path / "dataset"
    export_native_bowl_dataset(run, dataset, seed=99)
    manifest_path = dataset / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    feature_path = dataset / manifest["research_feature_view"]["file"]
    with np.load(feature_path, allow_pickle=False) as archive:
        features = {key: np.array(archive[key], copy=True) for key in archive.files}
    features["point_id"] = np.broadcast_to(np.arange(4, dtype=np.int32), (3, 4)).copy()
    np.savez_compressed(feature_path, **features)
    feature_meta = manifest["research_feature_view"]
    feature_meta.update({"sha256": _sha(feature_path), "bytes": feature_path.stat().st_size})
    # Keep the declared allowlist unchanged to prove the loader inspects payload keys.
    manifest["manifest_sha256"] = native_bowl_module._manifest_hash(manifest)
    native_bowl_module._write_json(manifest_path, manifest)
    with pytest.raises(SynLabError) as excinfo:
        load_native_bowl_dataset(dataset)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert "strict allowlist" in str(excinfo.value)

    # The package remains fail-closed if a caller attempts to reinterpret UNKNOWN as a label.
    # Use a fresh package because the previous payload is intentionally malformed.
    clean_dataset = tmp_path / "dataset_clean"
    export_native_bowl_dataset(run, clean_dataset, seed=101, state_indices=[0, 2])
    clean_manifest_path = clean_dataset / "dataset_manifest.json"
    clean_manifest = json.loads(clean_manifest_path.read_text(encoding="utf-8"))
    clean_manifest["qualification"]["r2_status"] = "R0"
    clean_manifest["manifest_sha256"] = native_bowl_module._manifest_hash(clean_manifest)
    native_bowl_module._write_json(clean_manifest_path, clean_manifest)
    with pytest.raises(SynLabError) as excinfo2:
        load_native_bowl_dataset(clean_dataset)
    assert excinfo2.value.code == ErrorCode.SCHEMA_INVALID
    assert "qualification" in str(excinfo2.value)

