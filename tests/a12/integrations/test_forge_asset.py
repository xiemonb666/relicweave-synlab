from __future__ import annotations

from dataclasses import asdict
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
from synlab.observe.continuous_appearance import (  # noqa: E402
    RestCoordinateAppearanceSampler,
)
from synlab.cameras.projection import look_at_T_WC  # noqa: E402
from synlab.roles import SOURCE_SENSOR_SIM  # noqa: E402
from synlab.schemas.runtime import ViewFrame  # noqa: E402


def _fixture_arrays(region_codes: list[int], *, sloped_region_1: bool = False
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray,
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
    if sloped_region_1 and vertices:
        # One front-facing triangle whose immutable material z crosses a narrow painted band.
        # Its face centroid is outside the band, so a per-face lookup cannot reproduce it.
        vertices[0] = [-0.45, -0.5, -2.0]
        vertices[1] = [0.0, 0.5, 5.0]
        vertices[2] = [0.45, -0.5, -2.0]
    verts = np.asarray(vertices, dtype=np.float64)
    tris = np.asarray(faces, dtype=np.int32)
    albedo = np.asarray([[0.65 - i * 0.04, 0.4, 0.2] for i in range(len(faces))],
                        dtype=np.float32)
    roughness = np.full(len(faces), 0.72, dtype=np.float32)
    return (verts, tris, np.asarray(region_codes, dtype=np.uint8), albedo, roughness)


def _write_package(root: Path, *, status: str = "PASS", report_status: str | None = None,
                   region_codes: list[int] | None = None, solid_step: bool = True,
                   continuous_recipe: bool = False,
                   sloped_region_1: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    region_codes = region_codes or [1, 2, 3, 4, 5]
    vertices, faces, face_region, albedo, roughness = _fixture_arrays(
        region_codes, sloped_region_1=sloped_region_1)
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
    recipe = {
        "material_binding_id": "fixture_matte",
        "historical_style_validation": "NOT_VALIDATED",
        "geometry_relief_mm": 0.0,
        "target_region_codes": [1],
    }
    if continuous_recipe:
        recipe.update({
            "coordinate_map": "cylindrical_z_up_mm",
            "palette_linear_rgb": {
                "base": [0.4, 0.58, 0.2], "red": [0.9, 0.025, 0.015],
                "dark": [0.04, 0.02, 0.015],
            },
            "bands": [{"center_z_mm": 0.0, "width_mm": 0.5, "color": "red"}],
        })
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
        "ornament": {"kind": "painted", "recipe": recipe},
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


def _truth_sampler() -> RestCoordinateAppearanceSampler:
    recipe = {
        "coordinate_map": "cylindrical_z_up_mm",
        "material_binding_id": "fixture_matte",
        "geometry_relief_mm": 0.0,
        "historical_style_validation": "NOT_VALIDATED",
        "target_region_codes": [1],
        "palette_linear_rgb": {"base": [0.4, 0.58, 0.2], "red": [0.9, 0.025, 0.015]},
        "bands": [{"center_z_mm": 0.0, "width_mm": 0.5, "color": "red"}],
    }
    return RestCoordinateAppearanceSampler.from_asset_truth(
        faces=np.asarray([[0, 1, 2]], dtype=np.int32),
        face_regions=np.asarray([1], dtype=np.uint8),
        vertices_material_xyz_mm=np.asarray([[0.0, 0.0, -1.0], [1.0, 0.0, 0.0],
                                             [0.0, 1.0, 1.0]], dtype=np.float64),
        recipe=recipe, material_binding_id="fixture_matte")


@pytest.mark.parametrize(("field", "bad_dtype"), [
    ("faces", np.float64), ("faces", np.bool_),
    ("face_regions", np.float64), ("face_regions", np.bool_),
])
def test_truth_sampler_rejects_noninteger_face_and_region_arrays(
    field: str, bad_dtype: type,
) -> None:
    sampler_inputs = {
        "faces": np.asarray([[0, 1, 2]], dtype=np.int32),
        "face_regions": np.asarray([1], dtype=np.uint8),
        "vertices_material_xyz_mm": np.asarray([[0.0, 0.0, -1.0], [1.0, 0.0, 0.0],
                                                 [0.0, 1.0, 1.0]], dtype=np.float64),
    }
    sampler_inputs[field] = sampler_inputs[field].astype(bad_dtype)
    recipe = {
        "coordinate_map": "cylindrical_z_up_mm",
        "material_binding_id": "fixture_matte",
        "geometry_relief_mm": 0.0,
        "historical_style_validation": "NOT_VALIDATED",
        "target_region_codes": [1],
        "palette_linear_rgb": {"base": [0.4, 0.58, 0.2], "red": [0.9, 0.025, 0.015]},
        "bands": [{"center_z_mm": 0.0, "width_mm": 0.5, "color": "red"}],
    }
    with pytest.raises(SynLabError) as excinfo:
        RestCoordinateAppearanceSampler.from_asset_truth(
            **sampler_inputs, recipe=recipe, material_binding_id="fixture_matte")
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


@pytest.mark.parametrize("barycentric", [
    [0.2, 0.2, 0.2],       # finite, individually bounded, but sum is not one
    [1.000001, 0.0, 0.0],  # never silently clamp or renormalize an invalid hit
    [np.nan, 0.5, 0.5],
    [0.4, 0.4, 0.4],
])
def test_truth_sampler_rejects_invalid_hit_barycentrics(barycentric: list[float]) -> None:
    sampler = _truth_sampler()
    with pytest.raises(SynLabError) as excinfo:
        sampler.sample_albedo(np.asarray([0]), np.asarray([barycentric]),
                              np.asarray([[0.3, 0.4, 0.5]], dtype=np.float32))
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


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
    legacy_default = render_forge_asset_preview(
        asset, _frame(), light=_light(), spec=spec, allow_prototype_preview=True,
        appearance_sampling="FACE_SAMPLE_APPROXIMATION")
    assert np.array_equal(bound.rgb_linear, legacy_default.rgb_linear)
    assert np.array_equal(bound.depth_z, legacy_default.depth_z, equal_nan=True)
    assert np.array_equal(bound.id_map, legacy_default.id_map)
    assert np.array_equal(bound.surface_tag, legacy_default.surface_tag)
    assert np.array_equal(bound.visibility, legacy_default.visibility)
    assert np.array_equal(bound.uncertain_mask, legacy_default.uncertain_mask)
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
    serialized_render = asdict(output)
    assert set(serialized_render) == {
        "rgb_linear", "depth_z", "id_map", "surface_tag", "visibility",
        "uncertain_mask", "backend", "meta",
    }
    assert not {"appearance_sampler", "face_region", "vertices_material_xyz_mm",
                "ornament_recipe_json"}.intersection(serialized_render)
    assert set(np.unique(output.surface_tag)).issubset({-1, 0})
    assert not hasattr(output, "face_region")
    assert not hasattr(output, "vertices_material_xyz_mm")
    forbidden = {"seed", "producer", "vertices_material_xyz_mm", "face_region",
                 "r2_label", "fracture_label", "provenance"}
    assert not forbidden.intersection(scene.meta)
    assert not forbidden.intersection(output.meta)
    assert scene.meta["feature_export_allowed"] is False
    assert asset.vertices_material_xyz_mm.flags.writeable is False
    assert asset.face_region.flags.writeable is False


def _render_face_normal_map(asset, id_map: np.ndarray, object_pose: np.ndarray | None = None
                            ) -> np.ndarray:
    scene = scene_from_forge_asset(asset, allow_prototype_preview=True)
    vertices = scene.vertices
    if object_pose is not None:
        vertices = vertices @ object_pose[:3, :3].T + object_pose[:3, 3]
    tri = vertices[scene.faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-15)
    normal_map = np.zeros((*id_map.shape, 3), dtype=np.float64)
    hit = id_map >= 0
    normal_map[hit] = normals[id_map[hit]]
    return normal_map


@pytest.mark.parametrize(("supersample", "camera_model", "dist"), [
    (1, "PINHOLE", None),
    (2, "PINHOLE", None),
    (1, "OPENCV", np.asarray([0.08, -0.01, 0.001, -0.001, 0.0])),
])
def test_continuous_bands_sample_hit_barycentrics_without_changing_geometry(
    tmp_path: Path, supersample: int, camera_model: str,
    dist: np.ndarray | None,
) -> None:
    pytest.importorskip("open3d") if camera_model != "PINHOLE" else None
    asset = load_forge_asset(_write_package(tmp_path / "fixture", continuous_recipe=True,
                                            sloped_region_1=True))
    frame = _frame()
    frame.camera_model = camera_model
    frame.dist = dist
    if supersample == 2:
        # Resolve the narrow band across more of the output grid while retaining SS2 filtering.
        frame.K[0, 0] = frame.K[1, 1] = 160.0
    spec = RenderSpec(supersample=supersample, near_mm=1.0, far_mm=100.0,
                      max_pixels=64 * 64 * supersample * supersample)
    continuous = render_forge_asset_preview(asset, frame, light=_light(), spec=spec,
                                            allow_prototype_preview=True)
    legacy = render_forge_asset_preview(
        asset, frame, light=_light(), spec=spec, allow_prototype_preview=True,
        appearance_sampling="FACE_SAMPLE_APPROXIMATION")

    # One coarse triangle has a centroid outside the painted band. Continuous per-hit sampling
    # must nevertheless put both base and red samples on that same face.
    face_pixels = continuous.id_map == 0
    rgb = continuous.rgb_linear[face_pixels]
    assert rgb.shape[0] >= 3
    tri = asset.vertices_mm[asset.faces[0]]
    normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
    normal /= np.linalg.norm(normal)
    lambert = np.clip(-float(np.dot(normal, _light().direction)), 0.0, 1.0)
    lighting = _light().ambient + _light().color * lambert
    expected_base = np.asarray([0.4, 0.58, 0.2]) * lighting
    expected_band = np.asarray([0.9, 0.025, 0.015]) * lighting
    if supersample == 1:
        assert np.any(np.all(np.isclose(rgb, expected_base, rtol=0.0, atol=2e-6), axis=1))
        assert np.any(np.all(np.isclose(rgb, expected_band, rtol=0.0, atol=2e-6), axis=1))
    else:
        # The final RGB is a 2×2 sample average. Require a fully visible face pixel whose
        # color differs from the base-only value, proving that a painted sub-sample contributes.
        interior_face = face_pixels & (continuous.visibility > 0)
        assert interior_face.any()
        assert np.any(np.linalg.norm(continuous.rgb_linear[interior_face] - expected_base,
                                     axis=1) > 1e-4)
    assert not np.array_equal(continuous.rgb_linear, legacy.rgb_linear)

    assert np.array_equal(continuous.id_map, legacy.id_map)
    assert np.array_equal(continuous.surface_tag, legacy.surface_tag)
    assert np.array_equal(continuous.visibility, legacy.visibility)
    assert np.array_equal(continuous.depth_z, legacy.depth_z, equal_nan=True)
    assert np.array_equal(_render_face_normal_map(asset, continuous.id_map),
                          _render_face_normal_map(asset, legacy.id_map))
    assert continuous.meta["appearance_sampling"] == "CONTINUOUS_REST_COORDINATE"
    assert legacy.meta["appearance_sampling"] == "FACE_SAMPLE_APPROXIMATION"
    forbidden = {"vertices_material_xyz_mm", "face_region", "bands", "palette_linear_rgb",
                 "pattern_id", "ornament_recipe_json"}
    assert not forbidden.intersection(continuous.meta)


def _ray_barycentric_world(origin: np.ndarray, direction: np.ndarray,
                           triangle: np.ndarray) -> tuple[float, np.ndarray] | None:
    # Independent scalar Möller–Trumbore oracle used only for the posed pinhole fixture.
    edge1 = triangle[1] - triangle[0]
    edge2 = triangle[2] - triangle[0]
    pvec = np.cross(direction, edge2)
    det = float(np.dot(edge1, pvec))
    if abs(det) < 1e-12:
        return None
    inv_det = 1.0 / det
    tvec = origin - triangle[0]
    b1 = float(np.dot(tvec, pvec) * inv_det)
    qvec = np.cross(tvec, edge1)
    b2 = float(np.dot(direction, qvec) * inv_det)
    distance = float(np.dot(edge2, qvec) * inv_det)
    b0 = 1.0 - b1 - b2
    if distance <= 0 or min(b0, b1, b2) < 0:
        return None
    return distance, np.asarray([b0, b1, b2], dtype=np.float64)


def _nearest_fixture_hit(origin: np.ndarray, direction: np.ndarray,
                         vertices: np.ndarray, faces: np.ndarray
                         ) -> tuple[int, float, np.ndarray] | None:
    nearest: tuple[int, float, np.ndarray] | None = None
    for face_index, face in enumerate(faces):
        hit = _ray_barycentric_world(origin, direction, vertices[face])
        if hit is not None and (nearest is None or hit[0] < nearest[1]):
            nearest = (face_index, hit[0], hit[1])
    return nearest


def _independent_subpixel_world_ray(frame: ViewFrame, row: int, col: int,
                                    supersample: int, subrow: int,
                                    subcol: int) -> tuple[np.ndarray, np.ndarray]:
    # The software renderer scales K by the supersample factor and shifts its principal point by
    # factor/2. Use that declared high-grid cell center, then independently undo OPENCV distortion.
    factor = int(supersample)
    K_hi = np.asarray(frame.K, dtype=np.float64) * factor
    K_hi[0, 2] += factor / 2.0
    K_hi[1, 2] += factor / 2.0
    K_hi[2, 2] = 1.0
    pixel = np.asarray([[[factor * col + subcol + 0.5,
                          factor * row + subrow + 0.5]]], dtype=np.float64)
    if (frame.camera_model or "PINHOLE").upper() == "OPENCV" \
            and frame.dist is not None and np.any(np.asarray(frame.dist) != 0.0):
        import cv2

        xy = cv2.undistortPoints(pixel, K_hi, np.asarray(frame.dist, dtype=np.float64)).reshape(2)
    else:
        xy1 = np.linalg.solve(K_hi, np.asarray([pixel[0, 0, 0], pixel[0, 0, 1], 1.0]))
        xy = xy1[:2] / xy1[2]
    ray_camera = np.asarray([xy[0], xy[1], 1.0], dtype=np.float64)
    return frame.T_WC[:3, 3], frame.T_WC[:3, :3] @ ray_camera


@pytest.mark.parametrize(("supersample", "camera_model", "dist"), [
    (1, "PINHOLE", None),
    (2, "PINHOLE", None),
    (1, "OPENCV", np.asarray([0.08, -0.01, 0.001, -0.001, 0.0])),
])
def test_continuous_appearance_follows_rest_coordinates_after_object_pose(
    tmp_path: Path, supersample: int, camera_model: str,
    dist: np.ndarray | None,
) -> None:
    if camera_model != "PINHOLE":
        pytest.importorskip("open3d")
    asset = load_forge_asset(_write_package(tmp_path / "fixture", continuous_recipe=True,
                                            sloped_region_1=True))
    angle = np.deg2rad(-24.0)
    pose = np.asarray([[1.0, 0.0, 0.0, 0.0],
                       [0.0, np.cos(angle), -np.sin(angle), 0.0],
                       [0.0, np.sin(angle), np.cos(angle), 0.0],
                       [0.0, 0.0, 0.0, 1.0]], dtype=np.float64)
    frame = _frame()
    frame.camera_model = camera_model
    frame.dist = dist
    # Keep the coarse tilted triangle large enough to include several interior painted samples.
    frame.K[0, 0] = frame.K[1, 1] = 160.0
    spec = RenderSpec(supersample=supersample, near_mm=1.0, far_mm=100.0,
                      max_pixels=64 * 64 * supersample * supersample)
    output = render_forge_asset_preview(
        asset, frame, light=_light(), spec=spec,
        allow_prototype_preview=True, object_pose=pose)
    face = asset.faces[0]
    posed_vertices = asset.vertices_mm @ pose[:3, :3].T + pose[:3, 3]
    posed_triangle = posed_vertices[face]
    world_normals = np.cross(posed_triangle[1] - posed_triangle[0],
                             posed_triangle[2] - posed_triangle[0])
    world_normals /= np.linalg.norm(world_normals)
    lambert = np.clip(-float(np.dot(world_normals, _light().direction)), 0.0, 1.0)
    lighting = _light().ambient + _light().color * lambert
    recipe = json.loads(asset.ornament_recipe_json)
    base_albedo = np.asarray(recipe["palette_linear_rgb"]["base"], dtype=np.float64)
    band_albedo = {str(name): np.asarray(rgb, dtype=np.float64)
                   for name, rgb in recipe["palette_linear_rgb"].items()}
    color_samples = {"base": 0, **{str(item["color"]): 0 for item in recipe["bands"]}}
    checked_pixels = 0
    for row, col in zip(*np.nonzero(output.id_map == 0)):
        sample_rgb: list[np.ndarray] = []
        sample_kinds: list[str] = []
        samples_valid = True
        for subrow in range(supersample):
            for subcol in range(supersample):
                origin, direction = _independent_subpixel_world_ray(
                    frame, int(row), int(col), supersample, subrow, subcol)
                hit = _nearest_fixture_hit(origin, direction, posed_vertices, asset.faces)
                if hit is None or hit[0] != 0:
                    samples_valid = False
                    break
                _, _, bary = hit
                if float(np.min(bary)) < 0.12:
                    samples_valid = False
                    break
                rest_z = float(np.dot(bary, asset.vertices_material_xyz_mm[face, 2]))
                if any(abs(abs(rest_z - float(item["center_z_mm"]))
                           - float(item["width_mm"]) / 2.0) < 0.08
                       for item in recipe["bands"]):
                    samples_valid = False
                    break
                color_name = "base"
                albedo = base_albedo
                for item in recipe["bands"]:
                    if abs(rest_z - float(item["center_z_mm"])) <= float(item["width_mm"]) / 2.0:
                        color_name = str(item["color"])
                        albedo = band_albedo[color_name]
                        break
                sample_kinds.append(color_name)
                sample_rgb.append(albedo * lighting)
            if not samples_valid:
                break
        if not samples_valid:
            continue
        expected = np.mean(np.asarray(sample_rgb), axis=0)
        assert np.allclose(output.rgb_linear[row, col], expected, rtol=0.0, atol=2e-6)
        for color_name in sample_kinds:
            color_samples[color_name] += 1
        checked_pixels += 1
    assert checked_pixels >= 3
    assert color_samples["base"] >= 3
    assert sum(count for color, count in color_samples.items() if color != "base") >= 3


def test_explicit_albedo_counterfactual_disables_continuous_sampler(tmp_path: Path) -> None:
    asset = load_forge_asset(_write_package(tmp_path / "fixture", continuous_recipe=True,
                                            sloped_region_1=True))
    spec = RenderSpec(supersample=1, near_mm=1.0, far_mm=100.0, max_pixels=64 * 64)
    continuous = render_forge_asset_preview(asset, _frame(), light=_light(), spec=spec,
                                            allow_prototype_preview=True)
    override = np.broadcast_to(np.asarray([0.25, 0.55, 0.35], dtype=np.float32),
                               (asset.n_faces, 3)).copy()
    counterfactual = render_forge_asset_preview(
        asset, _frame(), light=_light(), spec=spec, allow_prototype_preview=True,
        albedo_override=override, appearance_sampling="CONTINUOUS_REST_COORDINATE",
        appearance_variant="explicit_unpatterned_test_counterfactual")
    assert counterfactual.meta["appearance_sampling"] == "FACE_SAMPLE_APPROXIMATION"
    assert np.array_equal(continuous.depth_z, counterfactual.depth_z, equal_nan=True)
    assert np.array_equal(continuous.id_map, counterfactual.id_map)
    assert np.array_equal(continuous.surface_tag, counterfactual.surface_tag)
    assert not np.array_equal(continuous.rgb_linear, counterfactual.rgb_linear)


def test_unsupported_declared_continuous_coordinate_map_fails_closed(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "fixture", continuous_recipe=True,
                          sloped_region_1=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["ornament"]["recipe"]["coordinate_map"] = "unsupported_uv_guess"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    asset = load_forge_asset(root)
    with pytest.raises(SynLabError) as excinfo:
        render_forge_asset_preview(asset, _frame(), light=_light(),
                                   spec=RenderSpec(supersample=1, max_pixels=64 * 64),
                                   allow_prototype_preview=True)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
