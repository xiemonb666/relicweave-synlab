"""Read-only adapter for VesselForge ``forge.asset.v1`` mother assets.

This is a narrow VF -> A12 rendering boundary.  It verifies the package before loading
arrays, keeps VF region/rest-coordinate fields on the provenance-side ``ForgeAsset`` record,
and exposes only A12's legacy *mother-surface* tag to ``Scene``.  It does not infer fracture
labels or R2 relations from VF surface-region codes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..observe.render import (
    BACKEND_SOFTWARE,
    LightSpec,
    MaterialSpec,
    RenderSpec,
    Scene,
    render_view,
)
from ..roles import SOURCE_SENSOR_SIM
from ..schemas.runtime import RenderOutput, ViewFrame


ADAPTER_SCHEMA = "synlab.forge_to_a12_scene.v1"
TAG_MAPPING_SCHEMA = "a12.legacy_fracture_origin_tag.v1"
INPUT_KIND = "forge_mother_asset"
SUPPORTED_FORGE_SCHEMA = "forge.asset.v1"
_MOTHER_REGION_CODES = frozenset((1, 2, 3, 4, 5))
_MAX_PROTOTYPE_PREVIEW_SAMPLES = 1_000_000


@dataclass(frozen=True, slots=True)
class ForgeAsset:
    """Verified package data, with source/truth channels kept outside the render scene.

    ``face_region`` and ``vertices_material_xyz_mm`` are explicitly provenance-side values.
    They are retained so later source/PG adapters can reason about lineage, but
    :func:`scene_from_forge_asset` never forwards them into ``Scene`` or render metadata.
    """

    manifest_sha256: str
    frame: str
    geometry_status: str
    validation_scope: str
    material_calibration_status: str
    historical_style_validation: str
    material_binding_id: str
    vertices_mm: np.ndarray
    faces: np.ndarray
    face_region: np.ndarray
    albedo_linear_rgb: np.ndarray
    roughness: np.ndarray
    vertices_material_xyz_mm: np.ndarray

    @property
    def n_faces(self) -> int:
        return int(self.faces.shape[0])


def _error(code: ErrorCode, message: str, *, stage: str,
           measurements: dict[str, Any] | None = None) -> SynLabError:
    return SynLabError(code, message, stage=stage, measurements=measurements or {})


def _safe_relative_path(value: Any, *, stage: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise _error(ErrorCode.SCHEMA_INVALID,
                     "asset paths must be non-empty POSIX relative paths",
                     stage=stage, measurements={"path": repr(value)})
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise _error(ErrorCode.SCHEMA_INVALID,
                     "asset paths must not contain empty, dot, or parent components",
                     stage=stage, measurements={"path": value})
    rel = PurePosixPath(value)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts) \
            or ":" in rel.parts[0]:
        raise _error(ErrorCode.SCHEMA_INVALID,
                     "absolute, traversing, drive-qualified, or non-normalized asset path",
                     stage=stage, measurements={"path": value})
    return rel


def _contained_file(root: Path, rel_value: Any, *, stage: str) -> Path:
    rel = _safe_relative_path(rel_value, stage=stage)
    root_resolved = root.resolve(strict=True)
    path = root.joinpath(*rel.parts).resolve(strict=True)
    try:
        path.relative_to(root_resolved)
    except ValueError as exc:
        raise _error(ErrorCode.SCHEMA_INVALID,
                     "asset path resolves outside the package directory",
                     stage=stage, measurements={"path": str(rel)}) from exc
    if not path.is_file():
        raise _error(ErrorCode.SCHEMA_INVALID, "declared asset payload is not a file",
                     stage=stage, measurements={"path": str(rel)})
    return path


def _read_json(path: Path, *, stage: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error(ErrorCode.SCHEMA_INVALID, "invalid JSON package document",
                     stage=stage, measurements={"path": str(path), "error": str(exc)}) from exc
    if not isinstance(value, dict):
        raise _error(ErrorCode.SCHEMA_INVALID, "package JSON root must be an object",
                     stage=stage, measurements={"path": str(path)})
    return value


def _get_path(mapping: dict[str, Any], *keys: str, stage: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise _error(ErrorCode.SCHEMA_INVALID,
                         f"missing required package field {'.'.join(keys)}", stage=stage)
        value = value[key]
    return value


def _freeze_array(value: np.ndarray, dtype: np.dtype[Any] | type | None = None) -> np.ndarray:
    out = np.array(value, dtype=dtype, copy=True, order="C")
    out.setflags(write=False)
    return out


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_npz(path: Path, *, stage: str) -> dict[str, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as payload:
            return {key: np.array(payload[key], copy=True) for key in payload.files}
    except (OSError, ValueError, KeyError) as exc:
        raise _error(ErrorCode.SCHEMA_INVALID, "invalid numeric NPZ payload",
                     stage=stage, measurements={"path": str(path), "error": str(exc)}) from exc


def load_forge_asset(package_dir: str | Path) -> ForgeAsset:
    """Verify and load a ``forge.asset.v1`` mother package; never repair it in place."""
    stage = "integrations.forge_asset.load"
    root = Path(package_dir)
    if not root.is_dir():
        raise _error(ErrorCode.INPUT_UNAVAILABLE, "Forge package directory is unavailable",
                     stage=stage, measurements={"path": str(root)})
    root = root.resolve(strict=True)
    manifest_path = _contained_file(root, "manifest.json", stage=stage)
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise _error(ErrorCode.INPUT_UNAVAILABLE, "cannot read Forge manifest",
                     stage=stage, measurements={"error": str(exc)}) from exc
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error(ErrorCode.SCHEMA_INVALID, "invalid Forge manifest JSON",
                     stage=stage, measurements={"error": str(exc)}) from exc
    if not isinstance(manifest, dict):
        raise _error(ErrorCode.SCHEMA_INVALID, "Forge manifest root must be an object",
                     stage=stage)
    if manifest.get("schema") != SUPPORTED_FORGE_SCHEMA:
        raise _error(ErrorCode.SCHEMA_INVALID, "unsupported Forge package schema",
                     stage=stage, measurements={"schema": manifest.get("schema")})
    units = manifest.get("units")
    if not isinstance(units, dict) or units.get("length") != "mm" \
            or units.get("mass") != "kg" or units.get("time") != "s":
        raise _error(ErrorCode.SCHEMA_INVALID, "Forge package units must be mm/kg/s",
                     stage=stage, measurements={"units": units})
    frame = manifest.get("frame")
    if frame != "right_handed_z_up":
        raise _error(ErrorCode.SCHEMA_INVALID, "unsupported Forge coordinate frame",
                     stage=stage, measurements={"frame": frame})

    file_table = manifest.get("files")
    if not isinstance(file_table, dict) or not file_table:
        raise _error(ErrorCode.SCHEMA_INVALID, "Forge manifest needs a non-empty file table",
                     stage=stage)
    verified: dict[str, Path] = {}
    for rel_value, record in file_table.items():
        rel = _safe_relative_path(rel_value, stage=stage)
        if not isinstance(record, dict):
            raise _error(ErrorCode.SCHEMA_INVALID, "file record must contain bytes and sha256",
                         stage=stage, measurements={"path": str(rel)})
        expected_bytes = record.get("bytes")
        expected_hash = record.get("sha256")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) \
                or expected_bytes < 0 or not isinstance(expected_hash, str) \
                or re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash) is None:
            raise _error(ErrorCode.SCHEMA_INVALID, "invalid file byte-count/hash record",
                         stage=stage, measurements={"path": str(rel)})
        path = _contained_file(root, str(rel), stage=stage)
        actual_bytes = path.stat().st_size
        digest = _sha256_file(path)
        if actual_bytes != expected_bytes or digest.lower() != expected_hash.lower():
            raise _error(
                ErrorCode.ASSET_HASH_MISMATCH,
                "Forge payload byte count or SHA-256 differs from its manifest",
                stage=stage,
                measurements={"path": str(rel), "expected_bytes": expected_bytes,
                              "actual_bytes": actual_bytes, "expected_sha256": expected_hash,
                              "actual_sha256": digest},
            )
        verified[str(rel)] = path

    def require_declared(value: Any, label: str) -> Path:
        rel = _safe_relative_path(value, stage=stage)
        key = str(rel)
        if key not in verified:
            raise _error(ErrorCode.SCHEMA_INVALID,
                         f"referenced {label} is absent from the manifest file table",
                         stage=stage, measurements={"path": key})
        return verified[key]

    geom_path = require_declared(_get_path(manifest, "geometry", "surface_npz", stage=stage),
                                 "surface geometry")
    # The adapter does not parse CAD or lineage payloads, but verifies their existence/reference
    # as part of the package contract when the manifest declares them.
    require_declared(_get_path(manifest, "geometry", "solid_step", stage=stage), "solid model")
    field_path = require_declared(
        _get_path(manifest, "fields", "surface_fields_npz", stage=stage), "surface fields")
    validation = manifest.get("validation")
    if not isinstance(validation, dict):
        raise _error(ErrorCode.SCHEMA_INVALID, "validation declaration must be an object",
                     stage=stage)
    report_path = require_declared(validation.get("report"), "geometry validation report")
    provenance = manifest.get("provenance")
    if isinstance(provenance, dict):
        for key in ("mesh_lineage_npz", "data_dictionary"):
            if provenance.get(key) is not None:
                require_declared(provenance[key], f"provenance {key}")

    report = _read_json(report_path, stage=stage)
    manifest_status = validation.get("status")
    report_status = report.get("status")
    manifest_scope = validation.get("scope")
    report_scope = report.get("scope")
    checks = report.get("checks")
    checks_ok = isinstance(checks, dict) and bool(checks) and all(value is True
                                                                    for value in checks.values())
    if manifest_status != "PASS" or report_status != "PASS" or not checks_ok:
        raise _error(
            ErrorCode.STOP_QA,
            "Forge geometry is not a fully passing asset; FAIL/PENDING is rejected",
            stage=stage,
            measurements={"manifest_status": manifest_status, "report_status": report_status,
                          "checks_all_true": checks_ok},
        )
    if manifest_scope != "geometry_only" or report_scope != "geometry_only":
        raise _error(ErrorCode.SCHEMA_INVALID,
                     "this adapter accepts only an explicitly geometry-only validation report",
                     stage=stage, measurements={"manifest_scope": manifest_scope,
                                                "report_scope": report_scope})

    material = manifest.get("material")
    ornament = manifest.get("ornament")
    if not isinstance(material, dict) or not isinstance(ornament, dict):
        raise _error(ErrorCode.SCHEMA_INVALID, "material and ornament declarations are required",
                     stage=stage)
    material_id = material.get("id")
    calibration = material.get("calibration_status")
    if not isinstance(material_id, str) or not material_id.strip() \
            or calibration not in ("UNVALIDATED_PROTOTYPE", "VALIDATED"):
        raise _error(ErrorCode.SCHEMA_INVALID, "unsupported material identity/calibration status",
                     stage=stage, measurements={"material_id": material_id,
                                                "calibration_status": calibration})
    recipe = ornament.get("recipe")
    if not isinstance(recipe, dict) or recipe.get("material_binding_id") != material_id:
        raise _error(ErrorCode.SCHEMA_INVALID,
                     "ornament recipe must bind to the declared material id",
                     stage=stage, measurements={"material_id": material_id,
                                                "recipe_binding": (recipe.get("material_binding_id")
                                                                   if isinstance(recipe, dict)
                                                                   else None)})
    style_status = recipe.get("historical_style_validation")
    if not isinstance(style_status, str) or not style_status:
        raise _error(ErrorCode.SCHEMA_INVALID,
                     "ornament recipe must declare historical style validation status",
                     stage=stage)

    geometry = _load_npz(geom_path, stage=stage)
    fields = _load_npz(field_path, stage=stage)
    for name in ("vertices_mm", "faces"):
        if name not in geometry:
            raise _error(ErrorCode.SCHEMA_INVALID, f"geometry payload lacks {name}", stage=stage)
    for name in ("face_region", "albedo_linear_rgb", "roughness",
                 "vertices_material_xyz_mm"):
        if name not in fields:
            raise _error(ErrorCode.SCHEMA_INVALID, f"surface fields payload lacks {name}",
                         stage=stage)

    vertices = np.asarray(geometry["vertices_mm"])
    faces_raw = np.asarray(geometry["faces"])
    if vertices.dtype.kind not in "fiu" or vertices.ndim != 2 or vertices.shape[1] != 3 \
            or not vertices.shape[0] or not np.isfinite(vertices).all():
        raise _error(ErrorCode.SCHEMA_INVALID, "vertices_mm must be a non-empty finite (V,3) array",
                     stage=stage, measurements={"shape": vertices.shape,
                                                "dtype": str(vertices.dtype)})
    if faces_raw.dtype.kind not in "iu" or faces_raw.ndim != 2 or faces_raw.shape[1] != 3 \
            or not faces_raw.shape[0]:
        raise _error(ErrorCode.SCHEMA_INVALID, "faces must be a non-empty integer (F,3) array",
                     stage=stage, measurements={"shape": faces_raw.shape,
                                                "dtype": str(faces_raw.dtype)})
    if int(faces_raw.min()) < 0 or int(faces_raw.max()) >= vertices.shape[0]:
        raise _error(ErrorCode.SCHEMA_INVALID, "face index is outside vertices_mm",
                     stage=stage, measurements={"vertex_count": int(vertices.shape[0]),
                                                "face_index_min": int(faces_raw.min()),
                                                "face_index_max": int(faces_raw.max())})
    if int(faces_raw.max()) > np.iinfo(np.int32).max:
        raise _error(ErrorCode.SCHEMA_INVALID, "face index exceeds A12 int32 scene capacity",
                     stage=stage, measurements={"face_index_max": int(faces_raw.max())})
    faces = faces_raw.astype(np.int32, copy=False)
    tri = np.asarray(vertices, dtype=np.float64)[faces.astype(np.int64)]
    area2 = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    if not np.isfinite(area2).all() or bool(np.any(area2 <= 0.0)):
        raise _error(ErrorCode.SCHEMA_INVALID, "faces must have finite non-zero area",
                     stage=stage, measurements={"degenerate_face_count": int(
                         np.count_nonzero(~np.isfinite(area2) | (area2 <= 0.0)))})

    face_region = np.asarray(fields["face_region"])
    albedo = np.asarray(fields["albedo_linear_rgb"])
    roughness = np.asarray(fields["roughness"])
    material_xyz = np.asarray(fields["vertices_material_xyz_mm"])
    if face_region.dtype.kind not in "iu" or face_region.shape != (faces.shape[0],):
        raise _error(ErrorCode.SCHEMA_INVALID, "face_region must be an integer (F,) array",
                     stage=stage, measurements={"shape": face_region.shape,
                                                "dtype": str(face_region.dtype)})
    unique_regions = set(int(value) for value in np.unique(face_region))
    # VF 255 is reserved for a future fracture surface.  Without event/source lineage this reader
    # refuses it instead of relabelling it as an A12 fracture/interface tag.
    if 255 in unique_regions:
        raise _error(ErrorCode.LABEL_MAPPING_UNKNOWN,
                     "reserved VF region 255 has no fracture event lineage and is not importable",
                     stage=stage)
    if not unique_regions or not unique_regions.issubset(_MOTHER_REGION_CODES):
        raise _error(ErrorCode.LABEL_MAPPING_UNKNOWN,
                     "VF face_region contains an unknown or unsupported code",
                     stage=stage, measurements={"codes": sorted(unique_regions)})
    if albedo.dtype.kind not in "fiu" or albedo.shape != (faces.shape[0], 3) \
            or not np.isfinite(albedo).all() or bool(np.any(albedo < 0.0)) \
            or bool(np.any(albedo > 1.0)):
        raise _error(ErrorCode.SCHEMA_INVALID,
                     "albedo_linear_rgb must be finite (F,3) values within [0,1]",
                     stage=stage, measurements={"shape": albedo.shape,
                                                "dtype": str(albedo.dtype)})
    if roughness.dtype.kind not in "fiu" or roughness.shape != (faces.shape[0],) \
            or not np.isfinite(roughness).all() or bool(np.any(roughness < 0.0)) \
            or bool(np.any(roughness > 1.0)):
        raise _error(ErrorCode.SCHEMA_INVALID, "roughness must be finite (F,) values in [0,1]",
                     stage=stage, measurements={"shape": roughness.shape,
                                                "dtype": str(roughness.dtype)})
    if material_xyz.dtype.kind not in "fiu" or material_xyz.shape != vertices.shape \
            or not np.isfinite(material_xyz).all():
        raise _error(ErrorCode.SCHEMA_INVALID,
                     "vertices_material_xyz_mm must be a finite (V,3) array",
                     stage=stage, measurements={"shape": material_xyz.shape,
                                                "expected_shape": vertices.shape,
                                                "dtype": str(material_xyz.dtype)})

    return ForgeAsset(
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        frame=frame,
        geometry_status=str(manifest_status),
        validation_scope=str(manifest_scope),
        material_calibration_status=str(calibration),
        historical_style_validation=style_status,
        material_binding_id=material_id,
        vertices_mm=_freeze_array(vertices, np.float64),
        faces=_freeze_array(faces, np.int32),
        face_region=_freeze_array(face_region),
        albedo_linear_rgb=_freeze_array(albedo, np.float32),
        roughness=_freeze_array(roughness, np.float32),
        vertices_material_xyz_mm=_freeze_array(material_xyz, np.float64),
    )


def scene_from_forge_asset(
    asset: ForgeAsset,
    *,
    allow_prototype_preview: bool = False,
    albedo_override: np.ndarray | None = None,
    roughness_override: np.ndarray | None = None,
    appearance_variant: str | None = None,
) -> Scene:
    """Bind verified face appearance fields to a render scene.

    All imported VF mother regions (1..5) intentionally collapse to the legacy A12 mother
    surface tag 0.  Full VF region codes remain only on ``ForgeAsset``; they never become tag 2,
    which A12 uses for event-origin-backed fracture pixels.
    """
    if asset.geometry_status != "PASS" or asset.validation_scope != "geometry_only":
        raise _error(ErrorCode.STOP_QA, "only a PASS geometry-only Forge asset may be rendered",
                     stage="integrations.forge_asset.scene",
                     measurements={"status": asset.geometry_status,
                                   "scope": asset.validation_scope})
    if asset.material_calibration_status != "VALIDATED" and not allow_prototype_preview:
        raise _error(
            ErrorCode.INTEGRATION_PENDING,
            "UNVALIDATED_PROTOTYPE material is available only for explicit temporary preview",
            stage="integrations.forge_asset.scene",
            measurements={"calibration_status": asset.material_calibration_status},
        )
    if (albedo_override is not None or roughness_override is not None) \
            and (not isinstance(appearance_variant, str) or not appearance_variant.strip()):
        raise _error(ErrorCode.SCHEMA_INVALID,
                     "appearance overrides require an explicit counterfactual variant label",
                     stage="integrations.forge_asset.scene")

    albedo = np.asarray(asset.albedo_linear_rgb if albedo_override is None else albedo_override,
                        dtype=np.float32)
    roughness = np.asarray(asset.roughness if roughness_override is None else roughness_override,
                           dtype=np.float32)
    if albedo.shape != (asset.n_faces, 3) or not np.isfinite(albedo).all() \
            or bool(np.any(albedo < 0.0)) or bool(np.any(albedo > 1.0)):
        raise _error(ErrorCode.SCHEMA_INVALID, "scene albedo must be finite (F,3) in [0,1]",
                     stage="integrations.forge_asset.scene",
                     measurements={"shape": albedo.shape})
    if roughness.shape != (asset.n_faces,) or not np.isfinite(roughness).all() \
            or bool(np.any(roughness < 0.0)) or bool(np.any(roughness > 1.0)):
        raise _error(ErrorCode.SCHEMA_INVALID, "scene roughness must be finite (F,) in [0,1]",
                     stage="integrations.forge_asset.scene",
                     measurements={"shape": roughness.shape})

    preview_only = asset.material_calibration_status != "VALIDATED"
    variant = appearance_variant or "forge_bound_face_fields"
    metadata = {
        "adapter_schema": ADAPTER_SCHEMA,
        "input_kind": INPUT_KIND,
        "tag_mapping_schema": TAG_MAPPING_SCHEMA,
        "tag_mapping_rule": "VF mother regions 1..5 -> A12 legacy mother-surface tag 0; 255 rejected",
        "vf_region_taxonomy_forward": False,
        "fracture_output": "NONE",
        "r2_output": "NONE",
        "production_physical_pass": False,
        "production_visual_pass": False,
        "feature_export_allowed": False,
        "preview_only": True,
        "prototype_preview_requires_opt_in": preview_only,
        "geometry_validation_status": asset.geometry_status,
        "geometry_validation_scope": asset.validation_scope,
        "material_calibration_status": asset.material_calibration_status,
        "historical_style_validation": asset.historical_style_validation,
        "appearance_binding": ("forge_face_fields" if albedo_override is None
                               and roughness_override is None
                               else "explicit_test_counterfactual_override"),
        "appearance_variant": variant,
        "appearance_sampling": "FACE_SAMPLE_APPROXIMATION",
        "material_binding_status": "bound_to_scene_materialspec",
        "face_region_255_policy": "REJECTED_NO_EVENT_LINEAGE",
    }
    material = MaterialSpec(albedo=albedo.copy(), roughness=roughness.copy(),
                            source_kind=SOURCE_SENSOR_SIM)
    # Do not include source IDs, manifest contents, seed, mechanics, VF region codes, or material
    # coordinates in Scene/meta: those remain package truth/provenance, not forward channels.
    return Scene(
        name="forge_mother_asset_preview",
        vertices=np.array(asset.vertices_mm, dtype=np.float64, copy=True),
        faces=np.array(asset.faces, dtype=np.int32, copy=True),
        surface_tag=np.zeros(asset.n_faces, dtype=np.int16),
        material=material,
        face_id=np.arange(asset.n_faces, dtype=np.int32),
        is_target=np.ones(asset.n_faces, dtype=np.uint8),
        meta=metadata,
    )


def render_forge_asset_preview(
    asset: ForgeAsset,
    frame: ViewFrame,
    *,
    light: LightSpec,
    spec: RenderSpec | None = None,
    allow_prototype_preview: bool = False,
    albedo_override: np.ndarray | None = None,
    roughness_override: np.ndarray | None = None,
    appearance_variant: str | None = None,
) -> RenderOutput:
    """Render a bounded software preview with explicit non-production semantics."""
    scene = scene_from_forge_asset(
        asset,
        allow_prototype_preview=allow_prototype_preview,
        albedo_override=albedo_override,
        roughness_override=roughness_override,
        appearance_variant=appearance_variant,
    )
    render_spec = spec or RenderSpec(supersample=1)
    width, height = map(int, frame.image_size)
    sample_count = width * height * max(int(render_spec.supersample), 1) ** 2
    if asset.material_calibration_status != "VALIDATED" \
            and sample_count > _MAX_PROTOTYPE_PREVIEW_SAMPLES:
        raise _error(
            ErrorCode.BUDGET_EXCEEDED,
            "UNVALIDATED_PROTOTYPE renders are limited to small temporary previews",
            stage="integrations.forge_asset.render_preview",
            measurements={"supersampled_pixel_count": sample_count,
                          "limit": _MAX_PROTOTYPE_PREVIEW_SAMPLES},
        )
    output = render_view(scene, frame, light=light, spec=render_spec,
                         backend=BACKEND_SOFTWARE)
    # RenderOutput does not copy Scene.meta itself.  Only the deliberately safe adapter
    # declaration is carried forward; it has no producer/seed/rest-coordinate values.
    output.meta.update(scene.meta)
    output.meta["base_renderer"] = output.backend
    return output


__all__ = [
    "ADAPTER_SCHEMA", "TAG_MAPPING_SCHEMA", "INPUT_KIND", "ForgeAsset",
    "load_forge_asset", "scene_from_forge_asset", "render_forge_asset_preview",
]
