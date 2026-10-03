from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.errors import ErrorCode, SynLabError  # noqa: E402
from synlab.integrations import forge_asset as forge_asset_module  # noqa: E402
from synlab.integrations.forge_asset import (  # noqa: E402
    ADAPTER_SCHEMA,
    INPUT_KIND,
    TAG_MAPPING_SCHEMA,
    load_forge_asset,
    render_forge_asset_preview,
    scene_from_forge_asset,
)
from synlab.observe.fracture_roi import FractureRoiConfig, fracture_rois  # noqa: E402
from synlab.observe.render import LightSpec, RenderSpec  # noqa: E402
from synlab.cameras.projection import look_at_T_WC  # noqa: E402
from synlab.roles import SOURCE_SENSOR_SIM  # noqa: E402
from synlab.schemas.runtime import ViewFrame  # noqa: E402


def _fixture_arrays(region_codes: list[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray,
                                                       np.ndarray, np.ndarray]:
    # Independent, front-facing (normal -Z) triangles spaced across a small plane.
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    for i, _code in enumerate(region_codes):
        center_x = (i - (len(region_codes) - 1) / 2.0) * 1.5
        offset = len(vertices)
        vertices.extend([[center_x - 0.45, -0.5, 0.0],
                         [center_x, 0.5, 0.0],
                         [center_x + 0.45, -0.5, 0.0]])
        faces.append([offset, offset + 1, offset + 2])
    verts = np.asarray(vertices, dtype=np.float64)
    tris = np.asarray(faces, dtype=np.int32)
    albedo = np.asarray([[0.65 - i * 0.04, 0.4, 0.2] for i in range(len(faces))],
                        dtype=np.float32)
    roughness = np.full(len(faces), 0.72, dtype=np.float32)
    return (verts, tris, np.asarray(region_codes, dtype=np.uint8), albedo, roughness)


def _write_package(root: Path, *, status: str = "PASS", report_status: str | None = None,
                   region_codes: list[int] | None = None, solid_step: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    region_codes = region_codes or [1, 2, 3, 4, 5]
    vertices, faces, face_region, albedo, roughness = _fixture_arrays(region_codes)
    for subdir in ("geometry", "fields", "validation"):
        (root / subdir).mkdir(exist_ok=True)
    np.savez(root / "geometry/surface.npz", vertices_mm=vertices, faces=faces)
    np.savez(root / "fields/surface.npz", face_region=face_region,
             albedo_linear_rgb=albedo, roughness=roughness,
             vertices_material_xyz_mm=vertices.copy())
    if solid_step:
        (root / "geometry/solid.step").write_bytes(b"geometry-validation-fixture")
    report = {
        "status": report_status or status,
        "scope": "geometry_only",
        "checks": {"finite_surface": True, "faces_in_range": True},
    }
    (root / "validation/geometry.json").write_text(json.dumps(report), encoding="utf-8")
    files = {}
    declared = ["fields/surface.npz", "geometry/surface.npz", "validation/geometry.json"]
    if solid_step:
        declared.append("geometry/solid.step")
    for rel in declared:
        data = (root / rel).read_bytes()
        files[rel] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest = {
        "schema": "forge.asset.v1",
        "frame": "right_handed_z_up",
        "units": {"length": "mm", "mass": "kg", "time": "s"},
        "files": files,
        "geometry": {"surface_npz": "geometry/surface.npz",
                     **({"solid_step": "geometry/solid.step"} if solid_step else {})},
        "fields": {"surface_fields_npz": "fields/surface.npz"},
        "validation": {"report": "validation/geometry.json", "scope": "geometry_only",
                       "status": status},
        "material": {"id": "fixture_matte", "calibration_status": "UNVALIDATED_PROTOTYPE",
                     "mechanics": {"rho_kg_m3": 2100.0, "E_pa": 5.0e9, "nu": 0.25,
                                   "Gc_j_m2": 45.0}},
        "ornament": {"kind": "painted", "recipe": {
            "material_binding_id": "fixture_matte", "historical_style_validation": "NOT_VALIDATED",
            "geometry_relief_mm": 0.0, "target_region_codes": [1]}},
        "provenance": {"seed": 91},
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _frame() -> ViewFrame:
    return ViewFrame(
        view_id="forge-fixture-view",
        K=np.asarray([[80.0, 0.0, 31.5], [0.0, 80.0, 31.5], [0.0, 0.0, 1.0]]),
        T_WC=look_at_T_WC(np.asarray([0.0, 0.0, -12.0]), np.zeros(3),
                          up=np.asarray([0.0, -1.0, 0.0])),
        image_size=(64, 64), profile_id="", tier="TEST", u_position_mm=0.0,
        working_distance_mm=12.0, focus_setting="test", source_kind=SOURCE_SENSOR_SIM,
        camera_model="PINHOLE", dist=None,
        meta={"focal_length_mm": 35.0, "f_number": 5.6},
    )


def _light() -> LightSpec:
    return LightSpec(direction=np.asarray([0.0, 0.0, -1.0]),
                     color=np.asarray([1.0, 1.0, 1.0]),
                     ambient=np.asarray([0.2, 0.2, 0.2]))


def test_forge_mother_regions_map_to_legacy_surface_without_creating_fracture_roi(
    tmp_path: Path,
) -> None:
    asset = load_forge_asset(_write_package(tmp_path / "fixture"))
    scene = scene_from_forge_asset(asset, allow_prototype_preview=True)

    assert set(np.unique(asset.face_region)) == {1, 2, 3, 4, 5}
    assert np.array_equal(scene.surface_tag, np.zeros(asset.n_faces, dtype=np.int16))
    assert not np.any(scene.surface_tag == 2), "VF inner=2/rim=3 must not become A12 interface tag"
    assert scene.meta["input_kind"] == INPUT_KIND == "forge_mother_asset"
    assert scene.meta["tag_mapping_schema"] == TAG_MAPPING_SCHEMA
    assert scene.meta["fracture_output"] == "NONE" and scene.meta["r2_output"] == "NONE"
    assert scene.meta["adapter_schema"] == ADAPTER_SCHEMA
    assert scene.meta["geometry_validation_basis"] == \
        "HASHED_PRODUCER_REPORT_VERIFIED_NOT_INDEPENDENTLY_REMEASURED"
    assert np.array_equal(scene.material.albedo, asset.albedo_linear_rgb)
    assert np.array_equal(scene.material.roughness, asset.roughness)

    # This is the same origin-kind contract fracture_rois actually consumes.  All imported faces
    # are mother-origin even when the VF source taxonomy calls a face inner wall or natural rim.
    target = SimpleNamespace(
        mesh=trimesh.Trimesh(vertices=scene.vertices, faces=scene.faces, process=False),
        face_origin_kind=np.zeros(asset.n_faces, dtype=np.uint8),
        fragment_id="VF_MOTHER_FIXTURE",
    )
    assert fracture_rois(target, FractureRoiConfig(enabled=True, min_patch_faces=1,
                                                   min_patch_area_mm2=0.0)) == []


def test_unvalidated_prototype_requires_explicit_small_preview_opt_in(tmp_path: Path) -> None:
    asset = load_forge_asset(_write_package(tmp_path / "fixture"))
    with pytest.raises(SynLabError) as excinfo:
        scene_from_forge_asset(asset)
    assert excinfo.value.code == ErrorCode.INTEGRATION_PENDING

    scene = scene_from_forge_asset(asset, allow_prototype_preview=True)
    assert scene.meta["preview_only"] is True
    assert scene.meta["production_physical_pass"] is False
    assert scene.meta["production_visual_pass"] is False
    assert scene.meta["appearance_sampling"] == "FACE_SAMPLE_APPROXIMATION"


@pytest.mark.parametrize("manifest_status,report_status,expected_code", [
    ("FAIL", "FAIL", ErrorCode.STOP_QA),
    ("PENDING", "PENDING", ErrorCode.STOP_QA),
    ("PASS", "FAIL", ErrorCode.SCHEMA_INVALID),
])
def test_fail_pending_or_disagreeing_geometry_validation_is_rejected(
    tmp_path: Path, manifest_status: str, report_status: str, expected_code: ErrorCode,
) -> None:
    with pytest.raises(SynLabError) as excinfo:
        load_forge_asset(_write_package(tmp_path / "fixture", status=manifest_status,
                                        report_status=report_status))
    assert excinfo.value.code == expected_code


def test_reserved_vf_region_255_is_not_guessed_as_a_fracture_surface(tmp_path: Path) -> None:
    with pytest.raises(SynLabError) as excinfo:
        load_forge_asset(_write_package(tmp_path / "fixture", region_codes=[1, 2, 3, 4, 255]))
    assert excinfo.value.code == ErrorCode.LABEL_MAPPING_UNKNOWN
    assert "lineage" in str(excinfo.value).lower()


def test_payload_hash_is_checked_before_arrays_are_used(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "fixture")
    (root / "geometry/solid.step").write_bytes(b"mutated geometry payload")
    with pytest.raises(SynLabError) as excinfo:
        load_forge_asset(root)
    assert excinfo.value.code == ErrorCode.ASSET_HASH_MISMATCH


def test_ornament_material_reference_must_match_the_loaded_surface_material(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "fixture")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["ornament"]["recipe"]["material_binding_id"] = "different_material"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_forge_asset(root)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert "bind" in str(excinfo.value).lower()


def test_solid_step_is_optional_but_verified_when_declared(tmp_path: Path) -> None:
    asset = load_forge_asset(_write_package(tmp_path / "fixture", solid_step=False))
    assert asset.geometry_status == "PASS"


@pytest.mark.parametrize("invalid_field", ["integer_vertices", "integer_albedo",
                                            "integer_roughness", "shifted_material_coordinates"])
def test_forge_float_and_rest_coordinate_contract_is_enforced_before_scene_binding(
    tmp_path: Path, invalid_field: str,
) -> None:
    root = _write_package(tmp_path / "fixture")
    if invalid_field == "integer_vertices":
        target = root / "geometry/surface.npz"
        with np.load(target, allow_pickle=False) as source:
            arrays = {key: source[key] for key in source.files}
        arrays["vertices_mm"] = arrays["vertices_mm"].astype(np.int64)
    else:
        target = root / "fields/surface.npz"
        with np.load(target, allow_pickle=False) as source:
            arrays = {key: source[key] for key in source.files}
        if invalid_field == "integer_albedo":
            arrays["albedo_linear_rgb"] = arrays["albedo_linear_rgb"].astype(np.int32)
        elif invalid_field == "integer_roughness":
            arrays["roughness"] = arrays["roughness"].astype(np.int32)
        else:
            arrays["vertices_material_xyz_mm"] = arrays["vertices_material_xyz_mm"].copy()
            arrays["vertices_material_xyz_mm"][0, 0] += 0.25
    np.savez(target, **arrays)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = target.read_bytes()
    rel = target.relative_to(root).as_posix()
    manifest["files"][rel] = {"bytes": len(payload),
                              "sha256": hashlib.sha256(payload).hexdigest()}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_forge_asset(root)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


def test_prototype_mechanics_must_be_finite_positive_and_poisson_admissible(
    tmp_path: Path,
) -> None:
    root = _write_package(tmp_path / "fixture")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["material"]["mechanics"]["nu"] = 0.5
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_forge_asset(root)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


@pytest.mark.parametrize("mutation", [
    "self_hash", "validated_material", "nonzero_relief", "historical_style_pass",
    "not_painted",
])
def test_v1_prototype_contract_does_not_accept_unreviewed_semantic_changes(
    tmp_path: Path, mutation: str,
) -> None:
    root = _write_package(tmp_path / "fixture")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "self_hash":
        manifest["files"]["manifest.json"] = {"bytes": manifest_path.stat().st_size,
                                               "sha256": "0" * 64}
    elif mutation == "validated_material":
        manifest["material"]["calibration_status"] = "VALIDATED"
    elif mutation == "nonzero_relief":
        manifest["ornament"]["recipe"]["geometry_relief_mm"] = 0.1
    elif mutation == "historical_style_pass":
        manifest["ornament"]["recipe"]["historical_style_validation"] = "PASS"
    else:
        manifest["ornament"]["kind"] = "engraved"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_forge_asset(root)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


def test_geometry_with_fewer_than_four_faces_is_refused_before_material_loading(
    tmp_path: Path,
) -> None:
    with pytest.raises(SynLabError) as excinfo:
        load_forge_asset(_write_package(tmp_path / "fixture", region_codes=[1, 2, 3]))
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


def test_vertex_budget_is_checked_from_npz_header_before_array_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_package(tmp_path / "fixture")
    target = root / "geometry/surface.npz"
    with np.load(target, allow_pickle=False) as source:
        original_faces = source["faces"]
    np.savez_compressed(target, vertices_mm=np.zeros((500_001, 3), dtype=np.float64),
                        faces=original_faces)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = target.read_bytes()
    manifest["files"]["geometry/surface.npz"] = {
        "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def materialization_is_forbidden(*_args, **_kwargs):
        raise AssertionError("NPZ array materialization must not happen before header budgets")

    monkeypatch.setattr(forge_asset_module, "_load_npz", materialization_is_forbidden)
    with pytest.raises(SynLabError) as excinfo:
        load_forge_asset(root)
    assert excinfo.value.code == ErrorCode.BUDGET_EXCEEDED


def test_manifest_file_table_rejects_path_traversal(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "fixture")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["../outside.bin"] = {"bytes": 0, "sha256": "0" * 64}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_forge_asset(root)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert "parent" in str(excinfo.value).lower()


def test_face_material_binding_changes_rgb_without_changing_geometry_depth_or_labels(
    tmp_path: Path,
) -> None:
    asset = load_forge_asset(_write_package(tmp_path / "fixture"))
    spec = RenderSpec(supersample=1, near_mm=1.0, far_mm=100.0, max_pixels=64 * 64)
    bound = render_forge_asset_preview(asset, _frame(), light=_light(), spec=spec,
                                       allow_prototype_preview=True)
    counterfactual_albedo = np.tile(np.asarray([0.05, 0.65, 0.95], dtype=np.float32),
                                    (asset.n_faces, 1))
    counterfactual = render_forge_asset_preview(
        asset, _frame(), light=_light(), spec=spec, allow_prototype_preview=True,
        albedo_override=counterfactual_albedo,
        appearance_variant="test_only_saturated_counterfactual",
    )

    assert not np.array_equal(bound.rgb_linear, counterfactual.rgb_linear)
    assert np.array_equal(bound.depth_z, counterfactual.depth_z, equal_nan=True)
    assert np.array_equal(bound.id_map, counterfactual.id_map)
    assert np.array_equal(bound.surface_tag, counterfactual.surface_tag)
    assert bound.meta["base_renderer"] == counterfactual.meta["base_renderer"]
    assert bound.meta["appearance_sampling"] == "FACE_SAMPLE_APPROXIMATION"
    assert bound.meta["appearance_variant"] == "forge_bound_face_fields"
    assert counterfactual.meta["appearance_variant"] == "test_only_saturated_counterfactual"
    assert np.array_equal(bound.meta["light_direction"], counterfactual.meta["light_direction"])


def test_scene_and_render_metadata_do_not_export_producer_seed_or_rest_coordinates(
    tmp_path: Path,
) -> None:
    asset = load_forge_asset(_write_package(tmp_path / "fixture"))
    scene = scene_from_forge_asset(asset, allow_prototype_preview=True)
    output = render_forge_asset_preview(asset, _frame(), light=_light(),
                                        spec=RenderSpec(supersample=1, max_pixels=64 * 64),
                                        allow_prototype_preview=True)
    forbidden = {"seed", "producer", "vertices_material_xyz_mm", "face_region",
                 "r2_label", "fracture_label", "provenance"}
    assert not forbidden.intersection(scene.meta)
    assert not forbidden.intersection(output.meta)
    assert scene.meta["feature_export_allowed"] is False
    assert asset.vertices_material_xyz_mm.flags.writeable is False
    assert asset.face_region.flags.writeable is False
