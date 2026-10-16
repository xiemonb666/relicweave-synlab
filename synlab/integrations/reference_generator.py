"""Reference-guided appearance composition on existing VesselForge mother meshes.

This module is an execution adapter, not another vessel generator. It validates and loads
the supplied VF meridian candidate mesh without changing its vertices or faces, derives face
tags from the producer's exact B-rep-face/section-segment lineage, and evaluates the existing
SynLab pattern and material APIs on that source geometry. The source meshes are size-reference
design candidates; they are not scans or exact profile reconstructions of the catalogued pots.

The chart arclength is a finite polyline approximation to the serialized meridian curve. The
outer-wall period uses a representative radius measured from the supplied triangle centroids.
Both approximations are recorded explicitly; neither is a surface-error certificate.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import trimesh

from ..errors import ErrorCode, SynLabError
from ..materials.reference_materials import (
    process_compatibility,
    reference_material,
    sample_reference_material,
)
from ..mothers.charts import revolve_chart
from ..mothers.tagging import TAG_INDEX, TAG_NAMES
from ..patterns.api import evaluate as evaluate_pattern
from ..patterns.bluewhite_panel import (
    BlueWhitePanelResult,
    GRID_BILINEAR_SAMPLING,
    SOURCE_RESOLVED_STATIONARY_SAMPLING,
    build_bluewhite_panel,
    normalized_density_sha256,
)
from ..patterns.reference_styles import (
    build_reference_pattern,
    reference_style_record,
)
from ..schemas.runtime import MotherGeometry, PatternRecipe


STAGE = "integrations.reference_generator"
_SOURCE_SCHEMA = "vf.meridian_section.v1"
_LINEAGE_SCHEMA = "vf.native_meridian_face_lineage.v1"
_REPORT_SCHEMA = "vf.revolved_profile_geometry_candidate_report.v1"
_ROLE_TO_TAG = {
    "body_outer": "outer_wall",
    "body_inner": "inner_wall",
    "rim": "rim",
    "foot": "foot",
    "base": "base",
}
_ROLE_TO_REGION_CODE = {
    "body_outer": 1,
    "body_inner": 2,
    "rim": 3,
    "base": 4,
    "foot": 5,
}
_REGION_TO_ROLE = {value: key for key, value in _ROLE_TO_REGION_CODE.items()}
_REQUIRED_NPZ_KEYS = {
    "vertices_mm", "faces", "triangle_source_brep_face_index", "triangle_region_code",
}
_MAX_FILE_BYTES = 256 * 1024 * 1024
_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
_MAX_VERTICES = 2_000_000
_MAX_FACES = 4_000_000
_MAX_JSON_BYTES = 16 * 1024 * 1024
BLUEWHITE_PANEL_STYLE = "met_50899_partial_dragon_panel"
BLUEWHITE_PANEL_FIELD_FAMILY = "met_50899_photo_projection_cobalt_panel_two_fraction_bleed.v1"
BLUEWHITE_SOURCE_MASK_SHA256 = "bc166ca1adf15907f8049f39e81a8cfe75486818e231a2d4b998c49797782da5"
BLUEWHITE_SOURCE_MASK_PATH = (
    Path(__file__).resolve().parents[1] / "patterns" / "resources" / "bluewhite_20261015"
    / "derived" / "met_50899_O2_dragon_cobalt_fired_photo_mask.png"
)
BLUEWHITE_PANEL_CONTROL_DEFAULTS: dict[str, Any] = {
    "panel_width_mm": 45.0,
    "panel_height_mm": 26.0,
    "center_s_fraction": 0.5,
    "center_theta_rad": math.pi,
    "diffusivity_s_mm2_per_unit": 0.02,
    "diffusivity_theta_mm2_per_unit": 0.08,
    "duration": 1.0,
    "mobile_fraction": 0.25,
    "n_s": 240,
    "n_theta": 1024,
    "boundary_halo_mm": 2.0,
    "image_top_toward": "lower_s",
    "continuous_sampling_mode": GRID_BILINEAR_SAMPLING,
}
# The field module also records its standalone normalized color preview. The adapter always
# derives the visible result from the selected material profile, so that diagnostic white is
# fixed internally and is not exposed as a control that would have no effect on the bowl.
_BLUEWHITE_PANEL_CONTROL_KEYS = set(BLUEWHITE_PANEL_CONTROL_DEFAULTS) - {
    "glaze_white_linear_rgb",
} | {"tau_rgb"}


@dataclass(frozen=True)
class ReferenceInstance:
    """One immutable-mother appearance composition and its replayable evidence."""

    mother: MotherGeometry
    material_profile: dict[str, Any]
    pattern_recipe: PatternRecipe | None
    fields: dict[str, np.ndarray]
    recipe: dict[str, Any]
    provenance: dict[str, Any]
    metrics: dict[str, Any]
    pigment_panel: BlueWhitePanelResult | None = None


def _error(message: str, *, code: ErrorCode = ErrorCode.MOTHER_INVALID,
           stage: str = STAGE, measurements: Mapping[str, Any] | None = None) -> SynLabError:
    return SynLabError(code, message, stage=stage,
                       measurements=dict(measurements or {}))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_bluewhite_source_asset() -> Path:
    """Verify the retained fired-photo mask identity before any image decoder reads it."""
    path = BLUEWHITE_SOURCE_MASK_PATH
    if not path.is_file():
        raise _error(f"required blue-white source mask is missing: {path}",
                     code=ErrorCode.ASSET_HASH_MISMATCH)
    size = path.stat().st_size
    if size <= 0 or size > 5 * 1024 * 1024:
        raise _error("blue-white source mask is empty or exceeds the 5 MiB read limit",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements={"bytes": size, "maximum_bytes": 5 * 1024 * 1024})
    observed = _sha256(path)
    if observed != BLUEWHITE_SOURCE_MASK_SHA256:
        raise _error("source mask hash mismatch for retained Met 50899 fired-photo pigment field",
                     code=ErrorCode.ASSET_HASH_MISMATCH,
                     measurements={"expected_sha256": BLUEWHITE_SOURCE_MASK_SHA256,
                                   "observed_sha256": observed})
    return path


def validate_bluewhite_material_compatibility(
        material_profile: Mapping[str, Any]) -> dict[str, Any]:
    """Require an explicitly classified ceramic substrate for the panel appearance route.

    Historical source decoration metadata is retained as evidence about its source object, but
    its absence does not imply that another named ceramic material is incompatible.
    """
    source_conditioned = material_profile.get("source_conditioned")
    source_conditioned = source_conditioned if isinstance(source_conditioned, Mapping) else {}
    material_class = source_conditioned.get("material_class")
    evidence_status = source_conditioned.get("material_class_evidence_status", "UNKNOWN")
    if not isinstance(material_class, str) or not material_class.strip():
        compatibility = {
            "material_class": "unknown",
            "process": "underglaze_cobalt",
            "status": "UNKNOWN",
            "effect_scope": "UNKNOWN",
            "basis": "material profile does not provide a material class",
        }
    else:
        compatibility = process_compatibility(material_class, "underglaze_cobalt")
    compatibility = {**compatibility,
                     "material_class_evidence_status": str(evidence_status)}
    if compatibility["status"] != "COMPATIBLE_SUBSTRATE_CLASS":
        raise _error(
            "the Met 50899 panel route requires a known ceramic substrate class compatible "
            "with underglaze cobalt",
            code=ErrorCode.SCHEMA_INVALID,
            measurements={"substrate_compatibility": compatibility})
    return compatibility


def validate_bluewhite_panel_controls(overrides: Mapping[str, Any] | None = None
                                      ) -> dict[str, Any]:
    """Validate and resolve finite, bounded controls for the sourced panel route."""
    supplied = dict(overrides or {})
    unknown = sorted(set(supplied) - _BLUEWHITE_PANEL_CONTROL_KEYS)
    if unknown:
        raise _error(f"unsupported blue-white panel controls: {unknown}",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements={"allowed": sorted(_BLUEWHITE_PANEL_CONTROL_KEYS)})
    chosen = {**BLUEWHITE_PANEL_CONTROL_DEFAULTS, **supplied}
    float_controls = (
        "panel_width_mm", "panel_height_mm", "center_s_fraction", "center_theta_rad",
        "diffusivity_s_mm2_per_unit", "diffusivity_theta_mm2_per_unit", "duration",
        "mobile_fraction", "boundary_halo_mm",
    )
    for key in float_controls:
        value = chosen[key]
        if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
            raise _error(f"blue-white control {key!r} must be numeric",
                         code=ErrorCode.SCHEMA_INVALID)
        number = float(value)
        if not math.isfinite(number):
            raise _error(f"blue-white control {key!r} must be finite",
                         code=ErrorCode.SCHEMA_INVALID)
        chosen[key] = number
    for key in ("panel_width_mm", "panel_height_mm"):
        if not 0.0 < chosen[key] <= 500.0:
            raise _error(f"blue-white control {key!r} must be in (0, 500] mm",
                         code=ErrorCode.SCHEMA_INVALID)
    if not 0.0 <= chosen["center_s_fraction"] <= 1.0:
        raise _error("center_s_fraction must be in [0, 1]",
                     code=ErrorCode.SCHEMA_INVALID)
    for key in ("diffusivity_s_mm2_per_unit", "diffusivity_theta_mm2_per_unit",
                "duration", "boundary_halo_mm"):
        if chosen[key] < 0.0:
            raise _error(f"blue-white control {key!r} must be non-negative",
                         code=ErrorCode.SCHEMA_INVALID)
    if not 0.0 <= chosen["mobile_fraction"] <= 1.0:
        raise _error("mobile_fraction must be in [0, 1]",
                     code=ErrorCode.SCHEMA_INVALID)
    if (not isinstance(chosen["continuous_sampling_mode"], str)
            or chosen["continuous_sampling_mode"] not in {
                GRID_BILINEAR_SAMPLING, SOURCE_RESOLVED_STATIONARY_SAMPLING}):
        raise _error("continuous_sampling_mode must be grid_bilinear_v1 or "
                     "source_resolved_stationary_v1",
                     code=ErrorCode.SCHEMA_INVALID)
    for key, minimum in (("n_s", 2), ("n_theta", 3)):
        value = chosen[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise _error(f"blue-white control {key!r} must be an integer",
                         code=ErrorCode.SCHEMA_INVALID)
        value = int(value)
        if value < minimum:
            raise _error(f"blue-white control {key!r} must be at least {minimum}",
                         code=ErrorCode.SCHEMA_INVALID)
        chosen[key] = value
    from ..patterns.underglaze import MAX_GRID_CELLS

    if chosen["n_s"] * chosen["n_theta"] > MAX_GRID_CELLS:
        raise _error("blue-white grid exceeds the field module cell cap",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements={"cells": chosen["n_s"] * chosen["n_theta"],
                                   "maximum_cells": MAX_GRID_CELLS})
    if chosen["image_top_toward"] not in {"lower_s", "higher_s"}:
        raise _error("image_top_toward must be 'lower_s' or 'higher_s'",
                     code=ErrorCode.SCHEMA_INVALID)
    for key, default in (("glaze_white_linear_rgb", (0.94, 0.91, 0.84)),
                         ("tau_rgb", (3.04, 2.56, 0.93))):
        raw = chosen.get(key, default)
        array = np.asarray(raw, dtype=np.float64)
        if array.shape != (3,) or not np.isfinite(array).all():
            raise _error(f"blue-white control {key!r} must be a finite RGB triple",
                         code=ErrorCode.SCHEMA_INVALID)
        if key == "glaze_white_linear_rgb" and np.any((array < 0.0) | (array > 1.0)):
            raise _error("glaze_white_linear_rgb values must be in [0, 1]",
                         code=ErrorCode.SCHEMA_INVALID)
        if key == "tau_rgb" and np.any(array < 0.0):
            raise _error("tau_rgb values must be non-negative",
                         code=ErrorCode.SCHEMA_INVALID)
        chosen[key] = [float(value) for value in array]
    return chosen


def _load_bluewhite_source_density() -> tuple[np.ndarray, dict[str, str]]:
    path = validate_bluewhite_source_asset()
    # Hash, size, PNG dimensions, and pixel count are checked before materializing pixels.
    from PIL import Image

    try:
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (2000, 1160):
                raise _error("retained blue-white source mask has unexpected PNG format/dimensions",
                             code=ErrorCode.ASSET_HASH_MISMATCH,
                             measurements={"format": image.format, "size": list(image.size)})
            image.load()
            density = np.asarray(image.convert("L"), dtype=np.float64) / 255.0
    except SynLabError:
        raise
    except (OSError, ValueError) as exc:
        raise _error(f"cannot decode retained blue-white source mask: {exc}",
                     code=ErrorCode.ASSET_HASH_MISMATCH) from exc
    if density.shape != (1160, 2000) or not np.isfinite(density).all():
        raise _error("decoded blue-white source mask does not match its bounded dimensions",
                     code=ErrorCode.ASSET_HASH_MISMATCH,
                     measurements={"shape": list(density.shape)})
    workspace_root = Path(__file__).resolve().parents[3]
    metadata = {
        "source_id": "met-50899-o2-dragon-continuous-cobalt-chroma",
        "title": "Vase with dragon, already-fired O2 photo-derived crop",
        "source_url": "https://www.metmuseum.org/art/collection/search/50899",
        "source_mask_path": str(path.resolve().relative_to(workspace_root)),
        "source_mask_sha256": BLUEWHITE_SOURCE_MASK_SHA256,
        "normalized_density_sha256": normalized_density_sha256(density),
        "mask_semantics": (
            "continuous blue-excess chroma proxy from an already-fired photo; tonal values "
            "retained; not recovered pre-fire pigment"),
        "photo_state": "already_fired_photo",
    }
    return density, metadata


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise _error(f"required reference file is missing: {path.name}")
    if path.stat().st_size > _MAX_JSON_BYTES:
        raise _error(f"reference JSON exceeds the {_MAX_JSON_BYTES}-byte read limit: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error(f"invalid UTF-8 JSON in {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise _error(f"{path.name} must contain a JSON object")
    return value


def _load_surface(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if not path.is_file():
        raise _error("reference surface.npz is missing")
    size = path.stat().st_size
    if size <= 0 or size > _MAX_FILE_BYTES:
        raise _error("reference surface.npz is empty or exceeds the bounded input size",
                     measurements={"bytes": size, "maximum_bytes": _MAX_FILE_BYTES})
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if sum(item.file_size for item in members) > _MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise _error("reference surface archive expands beyond the bounded input size")
            if any(item.file_size > _MAX_FILE_BYTES for item in members):
                raise _error("reference surface archive contains an oversized member")
        with np.load(path, allow_pickle=False) as archive:
            keys = set(archive.files)
            if keys != _REQUIRED_NPZ_KEYS:
                raise _error("reference surface.npz has an unexpected array inventory",
                             measurements={"required": sorted(_REQUIRED_NPZ_KEYS),
                                           "observed": sorted(keys)})
            arrays = [np.array(archive[name], copy=True) for name in (
                "vertices_mm", "faces", "triangle_source_brep_face_index",
                "triangle_region_code")]
    except SynLabError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise _error(f"cannot safely read reference surface.npz: {exc}") from exc
    vertices, faces, source_faces, region_codes = arrays
    if (vertices.dtype.kind != "f" or faces.dtype.kind not in "iu"
            or source_faces.dtype.kind not in "iu" or region_codes.dtype.kind not in "iu"):
        raise _error("reference surface arrays have invalid dtypes",
                     measurements={"vertices": str(vertices.dtype), "faces": str(faces.dtype),
                                   "source_faces": str(source_faces.dtype),
                                   "region_codes": str(region_codes.dtype)})
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not 0 < len(vertices) <= _MAX_VERTICES:
        raise _error("vertices_mm must have bounded shape (V,3)",
                     measurements={"shape": list(vertices.shape)})
    if faces.ndim != 2 or faces.shape[1] != 3 or not 0 < len(faces) <= _MAX_FACES:
        raise _error("faces must have bounded shape (F,3)",
                     measurements={"shape": list(faces.shape)})
    if source_faces.shape != (len(faces),) or region_codes.shape != (len(faces),):
        raise _error("triangle lineage arrays must have one entry per source triangle")
    if not np.isfinite(vertices).all():
        raise _error("vertices_mm contains a NaN or infinity")
    if int(faces.min()) < 0 or int(faces.max()) >= len(vertices):
        raise _error("faces contains an out-of-range vertex index")
    if np.any((faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2])
              | (faces[:, 2] == faces[:, 0])):
        raise _error("reference mesh contains a triangle with repeated vertex indices")
    return vertices, faces, source_faces, region_codes


def _array_geometry_hash(vertices: np.ndarray, faces: np.ndarray) -> str:
    """Hash geometry values, independent of platform integer width and byte order."""
    digest = hashlib.sha256()
    digest.update(b"synlab.reference_geometry_arrays.v1\0")
    v = np.ascontiguousarray(vertices, dtype="<f8")
    f = np.ascontiguousarray(faces, dtype="<i8")
    digest.update(json.dumps([list(v.shape), list(f.shape)], separators=(",", ":")).encode())
    digest.update(v.tobytes())
    digest.update(f.tobytes())
    return digest.hexdigest()


def _sample_segment(segment: Mapping[str, Any], n: int = 128) -> np.ndarray:
    """Sample serialized source meridians; return rows of [radius,z]."""
    points = np.asarray(segment.get("points_rz_mm"), dtype=np.float64)
    kind = str(segment.get("curve", ""))
    if not np.isfinite(points).all() or points.ndim != 2 or points.shape[1] != 2:
        raise _error("section segment has malformed points_rz_mm")
    t = np.linspace(0.0, 1.0, n + 1)
    if kind == "line" and points.shape == (2, 2):
        out = (1.0 - t[:, None]) * points[0] + t[:, None] * points[1]
    elif kind == "bezier" and points.shape == (4, 2):
        omt = 1.0 - t
        weights = np.column_stack([omt ** 3, 3.0 * omt ** 2 * t,
                                   3.0 * omt * t ** 2, t ** 3])
        out = weights @ points
    elif kind == "arc" and points.shape == (3, 2):
        # Recover the unique circle through the producer's start/mid/end samples and select
        # the sweep containing the middle point. This is sampling of the source arc, not fit.
        a, b, c = points
        matrix = 2.0 * np.stack([b - a, c - a])
        rhs = np.asarray([b @ b - a @ a, c @ c - a @ a], dtype=np.float64)
        try:
            center = np.linalg.solve(matrix, rhs)
        except np.linalg.LinAlgError as exc:
            raise _error("section arc points are collinear; exact arc sampling is undefined") from exc
        radius = float(np.linalg.norm(a - center))
        angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
        ccw_mid = (angles[1] - angles[0]) % (2.0 * math.pi)
        ccw_end = (angles[2] - angles[0]) % (2.0 * math.pi)
        ccw = ccw_end <= ccw_mid + 1e-10
        sweep = ccw_end if ccw else ccw_end - 2.0 * math.pi
        angle = angles[0] + t * sweep
        out = center[None, :] + radius * np.column_stack([np.cos(angle), np.sin(angle)])
    else:
        raise _error(f"unsupported or malformed section curve {kind!r}")
    if not np.isfinite(out).all():
        raise _error("sampled section curve contains a NaN or infinity")
    return out


def _inside_floor_segment_index(section: Mapping[str, Any]) -> int:
    """Find the exact axis-to-inner-wall line that forms this bowl's inside floor.

    The CAD source calls both this surface and the exterior underside ``base``. We use the
    serialized section topology to distinguish them: the inside floor is the horizontal line
    beginning at the rotation axis and ending exactly where the next ``body_inner`` segment
    begins. No mesh proximity or nearest-surface classification is involved.
    """
    segments = section.get("segments")
    matches: list[int] = []
    for index, segment in enumerate(segments or []):
        if (segment.get("role") != "base" or segment.get("curve") != "line"
                or index + 1 >= len(segments)
                or segments[index + 1].get("role") != "body_inner"):
            continue
        points = np.asarray(segment.get("points_rz_mm"), dtype=np.float64)
        following = np.asarray(segments[index + 1].get("points_rz_mm"), dtype=np.float64)
        if (points.shape == (2, 2) and following.ndim == 2 and following.shape[1] == 2
                and abs(float(points[0, 0])) <= 1e-9
                and float(points[1, 0]) > 0.0
                and abs(float(points[0, 1] - points[1, 1])) <= 1e-9
                and np.allclose(points[1], following[0], atol=1e-8, rtol=0.0)):
            matches.append(index)
    if len(matches) != 1:
        raise _error("source section must identify one exact axis-to-inner-wall inside-floor segment",
                     measurements={"matching_segment_indices": matches})
    return matches[0]


def _native_face_smoothing_groups(section: Mapping[str, Any],
                                  face_rows: Mapping[str, Any],
                                  native_face_count: int) -> dict[int, int]:
    """Join source CAD faces only across serialized section joins that are C1-continuous."""
    parent = list(range(native_face_count))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    segment_faces: dict[int, set[int]] = {}
    for raw_face, entry in face_rows.items():
        for segment_index in entry["source_segment_indices"]:
            segment_faces.setdefault(int(segment_index), set()).add(int(raw_face))

    segments = section["segments"]
    curves = [_sample_segment(segment, n=256) for segment in segments]
    for index, curve in enumerate(curves):
        next_index = (index + 1) % len(curves)
        following = curves[next_index]
        if not np.allclose(curve[-1], following[0], atol=1e-7, rtol=0.0):
            continue
        left_tangent = curve[-1] - curve[-2]
        right_tangent = following[1] - following[0]
        left_norm = float(np.linalg.norm(left_tangent))
        right_norm = float(np.linalg.norm(right_tangent))
        if left_norm <= 0.0 or right_norm <= 0.0:
            continue
        cosine = float(np.dot(left_tangent, right_tangent) / (left_norm * right_norm))
        # The 0.9995 threshold allows endpoint sampling roundoff (~1.8 degrees), while
        # keeping real rim, foot, and underside corners as distinct normal groups.
        if cosine < 0.9995:
            continue
        for left_face in segment_faces.get(index, set()):
            for right_face in segment_faces.get(next_index, set()):
                union(left_face, right_face)
    return {face: find(face) for face in range(native_face_count)}


def _profile_for_role(section: Mapping[str, Any], role: str) -> np.ndarray:
    segments = section["segments"]
    rows: list[np.ndarray] = []
    for segment in segments:
        if segment["role"] != role:
            continue
        curve = _sample_segment(segment)
        if rows and np.allclose(rows[-1][-1], curve[0], atol=1e-9, rtol=0.0):
            curve = curve[1:]
        rows.append(curve)
    if not rows:
        raise _error(f"reference section has no {role!r} curve")
    return np.concatenate(rows, axis=0)


def _bind_lineage(section: Mapping[str, Any], lineage: Mapping[str, Any],
                  source_faces: np.ndarray, region_codes: np.ndarray,
                  face_count: int) -> tuple[np.ndarray, dict[int, str], dict[str, Any]]:
    if lineage.get("schema") != _LINEAGE_SCHEMA or lineage.get("status") != "PASS":
        raise _error("reference face lineage is not a passing native meridian lineage")
    native_count = lineage.get("face_count")
    face_rows = lineage.get("faces")
    if (isinstance(native_count, bool) or not isinstance(native_count, int)
            or not isinstance(face_rows, dict) or native_count <= 0):
        raise _error("face_lineage.json has invalid face inventory")
    if set(face_rows) != {str(index) for index in range(native_count)}:
        raise _error("face lineage inventory is incomplete or contains unknown face ids")
    segments = section["segments"]
    role_by_face: dict[int, str] = {}
    segment_map: dict[str, list[int]] = {}
    for raw_index, entry in face_rows.items():
        if not isinstance(entry, dict):
            raise _error(f"face lineage record {raw_index} is not an object")
        role = str(entry.get("role", ""))
        segment_indices = entry.get("source_segment_indices")
        if role not in _ROLE_TO_TAG or not isinstance(segment_indices, list) or not segment_indices:
            raise _error(f"face lineage record {raw_index} has an unknown role or no source segments")
        if any(isinstance(value, bool) or not isinstance(value, int)
               or value < 0 or value >= len(segments) for value in segment_indices):
            raise _error(f"face lineage record {raw_index} refers to an invalid source segment")
        roles = {str(segments[index].get("role", "")) for index in segment_indices}
        if roles != {role}:
            raise _error(f"face lineage record {raw_index} role disagrees with exact source segment lineage",
                         measurements={"face_role": role, "segment_roles": sorted(roles),
                                       "segment_indices": segment_indices})
        face_index = int(raw_index)
        role_by_face[face_index] = role
        segment_map[raw_index] = [int(value) for value in segment_indices]
    if source_faces.size and (int(source_faces.min()) < 0 or int(source_faces.max()) >= native_count):
        raise _error("triangle_source_brep_face_index refers outside the native face inventory")
    if not set(np.unique(source_faces).tolist()) <= set(role_by_face):
        raise _error("triangle source references a face with no source lineage")
    observed_roles = np.asarray([role_by_face[int(i)] for i in source_faces], dtype=object)
    expected_regions = np.asarray([_ROLE_TO_REGION_CODE[str(role)] for role in observed_roles],
                                  dtype=np.uint8)
    if not np.array_equal(expected_regions, region_codes):
        bad = np.flatnonzero(expected_regions != region_codes)
        first = int(bad[0]) if len(bad) else -1
        raise _error("triangle region codes disagree with exact B-rep face/section lineage",
                     measurements={"first_triangle": first,
                                   "source_role": str(observed_roles[first]) if first >= 0 else None,
                                   "expected_code": int(expected_regions[first]) if first >= 0 else None,
                                   "observed_code": int(region_codes[first]) if first >= 0 else None})
    floor_segment = _inside_floor_segment_index(section)
    surface_roles = dict(role_by_face)
    floor_faces = [face for face, indices in ((int(face), segment_map[str(face)])
                                               for face in role_by_face)
                   if role_by_face[face] == "base" and indices == [floor_segment]]
    if len(floor_faces) != 1:
        raise _error("exact inside-floor segment must map to one native base face",
                     measurements={"inside_floor_segment_index": floor_segment,
                                   "native_face_indices": floor_faces})
    surface_roles[floor_faces[0]] = "inner_floor"
    tag_for_surface_role = {**_ROLE_TO_TAG, "inner_floor": "inner_wall"}
    observed_surface_roles = np.asarray([surface_roles[int(i)] for i in source_faces],
                                        dtype=object)
    tags = np.asarray([TAG_INDEX[tag_for_surface_role[str(role)]]
                       for role in observed_surface_roles], dtype=np.int32)
    smoothing_groups = _native_face_smoothing_groups(section, face_rows, native_count)
    exact_lineage = {
        "native_face_roles": role_by_face,
        "native_face_surface_roles": surface_roles,
        "native_face_source_segment_indices": segment_map,
        "inside_floor_surface_binding": {
            "source_segment_index": floor_segment,
            "source_native_face_index": floor_faces[0],
            "source_role": "base",
            "surface_role": "inner_floor",
            "surface_tag": "inner_wall",
            "basis": "exact axis-to-body_inner section-line lineage; not a nearest-face assignment",
            "decoration_chart": "NONE; no inside-floor UV/pattern chart is claimed",
        },
        "native_face_smoothing_groups": smoothing_groups,
        "smoothing_group_policy": (
            "source CAD faces share display normals only when their serialized adjacent section "
            "segments join positionally and their sampled endpoint tangents agree within 0.9995"
        ),
    }
    return tags, role_by_face, exact_lineage


def load_reference_mother(geometrydir: str | os.PathLike[str]) -> MotherGeometry:
    """Load one VF meridian candidate with strict, lineage-based semantic binding.

    The input's mesh arrays are consumed as supplied. No repair, remeshing, nearest-surface
    classification, orientation fix, or V01 substitution is performed. Known producer hashes
    are verified before the candidate is admitted.
    """
    root = Path(geometrydir).expanduser().resolve()
    if not root.is_dir():
        raise _error(f"reference geometry directory does not exist: {root}")
    geometry_dir = root / "geometry"
    surface_path = geometry_dir / "surface.npz"
    section_path = geometry_dir / "section.json"
    lineage_path = geometry_dir / "face_lineage.json"
    report_path = root / "geometry_report.json"
    provenance_path = root / "provenance.json"
    vertices, faces, source_faces, region_codes = _load_surface(surface_path)
    section = _json(section_path)
    lineage = _json(lineage_path)
    report = _json(report_path)
    source_provenance = _json(provenance_path)
    if section.get("schema") != _SOURCE_SCHEMA:
        raise _error(f"unsupported section schema {section.get('schema')!r}")
    frame = str(section.get("coordinate_frame", ""))
    if frame != "radius_mm_vs_z_mm; revolved about Z axis; Z-up":
        raise _error("reference section has an unsupported unit/frame convention",
                     measurements={"coordinate_frame": frame})
    segments = section.get("segments")
    if not isinstance(segments, list) or not 4 <= len(segments) <= 256:
        raise _error("reference section has an invalid bounded segment list")
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or str(segment.get("role")) not in _ROLE_TO_TAG:
            raise _error(f"section segment {index} has an unknown role")
        _sample_segment(segment, n=8)
    if report.get("schema") != _REPORT_SCHEMA:
        raise _error(f"unsupported geometry report schema {report.get('schema')!r}")
    if report.get("candidate_geometry_status") != "PASS_STRUCTURAL_CAD_ONLY":
        raise _error("reference candidate has not passed its structural CAD gate")
    checks = report.get("checks")
    if not isinstance(checks, dict) or not checks or any(value is not True for value in checks.values()):
        raise _error("geometry report contains a failed or missing structural check",
                     measurements={key: value for key, value in (checks or {}).items()
                                   if value is not True})
    fidelity = report.get("source_profile_fidelity", "")
    if not isinstance(fidelity, str) or "NOT_ESTABLISHED" not in fidelity:
        raise _error("reference report does not preserve its source-profile uncertainty")
    if source_provenance.get("candidate_status") != report.get("candidate_status"):
        raise _error("geometry report and source provenance candidate statuses disagree")
    if not isinstance(source_provenance.get("record"), dict):
        raise _error("reference provenance is missing its linked source record")
    if not source_provenance.get("not_claimed"):
        raise _error("reference provenance is missing its explicit non-claims")
    if lineage.get("face_count") != report.get("measurements", {}).get("native_face_count"):
        raise _error("native face lineage count disagrees with geometry report")

    hashes = report.get("measurements", {}).get("artifact_sha256", {})
    files = {"surface.npz": surface_path, "section.json": section_path,
             "face_lineage.json": lineage_path}
    source_file_hashes = {name: _sha256(path) for name, path in files.items()}
    for name, path in files.items():
        expected = hashes.get(name) if isinstance(hashes, dict) else None
        if not isinstance(expected, str) or len(expected) != 64:
            raise _error(f"geometry report does not carry a valid producer hash for {name}")
        if source_file_hashes[name] != expected.lower():
            raise _error(f"reference source hash mismatch for {name}",
                         code=ErrorCode.ASSET_HASH_MISMATCH,
                         measurements={"expected_sha256": expected,
                                       "observed_sha256": source_file_hashes[name]})
    source_file_hashes["geometry_report.json"] = _sha256(report_path)
    source_file_hashes["provenance.json"] = _sha256(provenance_path)

    face_tags, face_roles, exact_lineage = _bind_lineage(
        section, lineage, source_faces, region_codes, len(faces))
    source_triangle_roles = np.asarray([face_roles[int(index)] for index in source_faces],
                                       dtype=object)
    mesh = trimesh.Trimesh(vertices=vertices.copy(), faces=faces.copy(), process=False)
    if not mesh.is_watertight or not mesh.is_winding_consistent or not mesh.is_volume:
        raise _error("source surface is not a closed, consistently wound positive-volume mesh",
                     measurements={"watertight": bool(mesh.is_watertight),
                                   "winding_consistent": bool(mesh.is_winding_consistent),
                                   "is_volume": bool(mesh.is_volume)})
    if len(mesh.split(only_watertight=False)) != 1:
        raise _error("reference mesh does not contain exactly one connected surface shell")
    if mesh.volume <= 0.0 or not math.isfinite(float(mesh.volume)):
        raise _error("reference mesh has a non-positive or non-finite signed volume")
    reported_volume = report.get("measurements", {}).get("surface_mesh", {}).get("signed_volume_mm3")
    if (not isinstance(reported_volume, (int, float))
            or abs(float(mesh.volume) - float(reported_volume)) > max(0.02, 1e-7 * abs(float(reported_volume)))):
        raise _error("loaded mesh volume disagrees with its structural report",
                     measurements={"loaded_mm3": float(mesh.volume),
                                   "reported_mm3": reported_volume})
    candidate_dims = source_provenance.get("candidate_dimensions_mm") or {}
    bounds_dims = np.ptp(mesh.bounds, axis=0)
    expected_dims = [candidate_dims.get("rim_outer_diameter_mm"),
                     candidate_dims.get("rim_outer_diameter_mm"),
                     candidate_dims.get("overall_height_mm")]
    if any(value is None for value in expected_dims) or not np.allclose(
            bounds_dims, np.asarray(expected_dims, dtype=np.float64), atol=0.15, rtol=0.0):
        raise _error("source mesh bounds disagree with its candidate envelope dimensions",
                     measurements={"mesh_bounds_mm": bounds_dims.tolist(),
                                   "candidate_dimensions_mm": expected_dims})

    # Exact serialized source roles bind face tags; curve charts use a finite sampling of the
    # corresponding actual meridian subcurves, never a nearest-face heuristic.
    charts = []
    for role in ("body_outer", "body_inner"):
        tag_name = _ROLE_TO_TAG[role]
        tag_value = TAG_INDEX[tag_name]
        # The material tag ``inner_wall`` also covers the exactly lined-up inside floor.
        # The body-inner chart remains limited to its own native section lineage; it does not
        # imply that the floor has a valid pattern UV chart.
        face_mask = (source_triangle_roles == role) & (face_tags == tag_value)
        profile_rz = _profile_for_role(section, role)
        profile_rzs = np.column_stack([profile_rz, np.zeros(len(profile_rz), dtype=np.float64)])
        centroid_r = np.hypot(mesh.triangles_center[face_mask, 0],
                              mesh.triangles_center[face_mask, 1])
        if not len(centroid_r) or not np.any(centroid_r > 0):
            raise _error(f"reference mesh has no usable {tag_name} triangles")
        r_ref = float(np.median(centroid_r))
        area = float(np.asarray(mesh.area_faces, dtype=np.float64)[face_mask].sum())
        chart = revolve_chart(
            f"reference_{role}_meridian_polyline",
            [tag_value], profile_rzs=profile_rzs, r_ref_mm=r_ref, area_mm2=area,
            tol_mm=1.0, legal_tags=[tag_name],
            stage=f"{STAGE}.load_reference_mother.chart")
        chart.meta["reference_curve_sampling"] = {
            "curve_source": "geometry/section.json source segments, exact source indices recorded in face_lineage.json",
            "curve_evaluation": "analytic line/cubic-Bezier/circular-arc sampling",
            "samples_per_source_segment": 128,
            "arclength_status": "FINITE_POLYLINE_APPROXIMATION_NOT_AN_EXACT_ARCLENGTH_CERTIFICATE",
            "tolerance_mm": 1.0,
            "tolerance_meaning": "chart point-to-polyline membership policy, not a CAD or tessellation error bound",
            "representative_radius_mm": r_ref,
            "representative_period_status": "MEDIAN_TRIANGLE_CENTROID_RADIUS_APPROXIMATION",
        }
        if role == "body_inner":
            chart.meta["surface_chart_scope"] = {
                "represented_source_role": "body_inner",
                "inside_floor_surface_tag": "inner_wall",
                "inside_floor_pattern_chart": "NOT_PROVIDED",
                "note": "Inside floor receives the original interior finish tag, but its own pattern chart is a separate unresolved mapping.",
            }
        charts.append(chart)

    geometry_hash = _array_geometry_hash(mesh.vertices, mesh.faces)
    record = source_provenance["record"]
    # The VF candidate source records do not carry a formal mesh license. Preserve that absence.
    rights_note = (source_provenance.get("license") or source_provenance.get("rights")
                   or "NOT_SPECIFIED_FOR_GENERATED_CANDIDATE_MESH; source-record rights are preserved in the linked record")
    mother_id = str(root.name)
    mother = MotherGeometry(
        mesh=mesh,
        face_surface_tag=face_tags,
        surface_tag_names=dict(TAG_NAMES),
        charts=charts,
        vessel_id=f"REFERENCE:{str(source_provenance.get('preset', 'candidate'))}",
        material_id="REFERENCE_GUIDED_DESIGN",
        params={},
        mother_id=mother_id,
        meta={
            "geometry_source_sha256": source_file_hashes["surface.npz"],
            "geometry_array_sha256": geometry_hash,
            "source_file_sha256": source_file_hashes,
            "source_geometry_directory": str(root),
            "source_section_frame": frame,
            "source_rights_status": rights_note,
            "source_profile_fidelity": source_provenance.get("source_profile_fidelity"),
            "candidate_status": source_provenance.get("candidate_status"),
            "candidate_geometry_status": report.get("candidate_geometry_status"),
            "source_record": record,
            "source_dimensions_mm": source_provenance.get("source_dimensions_mm", {}),
            "candidate_dimensions_mm": candidate_dims,
            "design_assumptions": source_provenance.get("design_assumptions", {}),
            "section_geometry_details": source_provenance.get("section_geometry_details", {}),
            "lineage": exact_lineage,
            "triangle_source_brep_face_index": source_faces.copy(),
            "triangle_display_normal_group": np.asarray([
                exact_lineage["native_face_smoothing_groups"][int(index)]
                for index in source_faces], dtype=np.int32),
            "triangle_region_code": region_codes.copy(),
            "construction_status": "SOURCE_GEOMETRY_UNCHANGED",
            "geometry_hash_policy": "canonical float64 vertices and int64 faces; SHA-256",
            "physical_properties_status": "UNKNOWN",
            "refinement_status": "SOURCE_PROFILE_FIDELITY_NOT_ESTABLISHED",
        },
    )
    return mother


def _seed_pair(seeds: int | Mapping[str, int]) -> dict[str, int]:
    if isinstance(seeds, bool):
        raise _error("seeds must be an integer or a mapping with material and pattern integers",
                     code=ErrorCode.SCHEMA_INVALID)
    if isinstance(seeds, (int, np.integer)):
        return {"material": int(seeds), "pattern": int(seeds)}
    if not isinstance(seeds, Mapping) or set(seeds) != {"material", "pattern"}:
        raise _error("seeds mapping must contain exactly material and pattern",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements={"required": ["material", "pattern"],
        "observed": [str(key) for key in seeds] if isinstance(seeds, Mapping) else None})
    output: dict[str, int] = {}
    for key, value in seeds.items():
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise _error(f"{key} seed must be an integer", code=ErrorCode.SCHEMA_INVALID)
        output[str(key)] = int(value)
    return output


def _palette_body(recipe: PatternRecipe) -> tuple[np.ndarray, float]:
    palette = dict(recipe.meta.get("palette") or {})
    body = np.asarray(palette.get("body", recipe.palette[0]), dtype=np.float64)
    if body.shape != (3,) or not np.isfinite(body).all():
        raise _error("pattern recipe has no finite three-channel base palette",
                     code=ErrorCode.SCHEMA_INVALID)
    roughness = float(palette.get("body_roughness", 0.6))
    return body, roughness


def _compose_pattern_transfer(material_albedo: np.ndarray,
                              material_roughness: np.ndarray,
                              pattern_albedo: np.ndarray,
                              pattern_roughness: np.ndarray,
                              pattern_recipe: PatternRecipe,
                              apply_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Apply the same explicit appearance transfer to face or continuous chart samples."""
    material_rgb = np.asarray(material_albedo, dtype=np.float64)
    material_r = np.asarray(material_roughness, dtype=np.float64)
    pattern_rgb = np.asarray(pattern_albedo, dtype=np.float64)
    pattern_r = np.asarray(pattern_roughness, dtype=np.float64)
    use = np.asarray(apply_mask, dtype=bool)
    if (material_rgb.shape != pattern_rgb.shape or material_rgb.ndim != 2
            or material_rgb.shape[1] != 3 or material_r.shape != use.shape
            or pattern_r.shape != use.shape or material_rgb.shape[0] != use.size):
        raise _error("appearance transfer arrays have incompatible shapes",
                     code=ErrorCode.SCHEMA_INVALID)
    base_color, base_roughness = _palette_body(pattern_recipe)
    transfer = pattern_rgb / np.maximum(base_color[None, :], 1e-6)
    combined_rgb = material_rgb.copy()
    combined_r = material_r.copy()
    combined_rgb[use] = np.clip(material_rgb[use] * transfer[use], 0.0, 1.0)
    combined_r[use] = np.clip(
        material_r[use] + pattern_r[use] - base_roughness, 0.02, 1.0)
    return combined_rgb, combined_r


def compose_reference_instance(
    geometrydir: str | os.PathLike[str],
    material_style: str,
    pattern_style: str,
    seeds: int | Mapping[str, int],
    controls: Mapping[str, Any] | None = None,
) -> ReferenceInstance:
    """Compose named material and appearance-pattern recipes on an unchanged VF mesh.

    ``controls`` may contain ``material`` controls plus either source-style pattern overrides
    or the finite controls for ``met_50899_partial_dragon_panel``. Pattern channels are
    appearance-only here: nonzero height is rejected instead of being advertised as shape that
    was not actually applied to the mesh. The photo-derived field is an explicit non-PAT route.
    A new ``interface`` query always exposes body material and never receives decoration.
    """
    seed_values = _seed_pair(seeds)
    supplied = dict(controls or {})
    unknown_controls = sorted(set(supplied) - {"material", "pattern"})
    if unknown_controls:
        raise _error(f"unknown composition control groups: {unknown_controls}",
                     code=ErrorCode.SCHEMA_INVALID)
    material_controls = supplied.get("material", {})
    pattern_overrides = supplied.get("pattern", {})
    if not isinstance(material_controls, Mapping):
        raise _error("controls.material must be a mapping", code=ErrorCode.SCHEMA_INVALID)
    if not isinstance(pattern_overrides, Mapping):
        raise _error("controls.pattern must be a mapping", code=ErrorCode.SCHEMA_INVALID)

    is_bluewhite_panel = str(pattern_style) == BLUEWHITE_PANEL_STYLE
    panel_controls = (validate_bluewhite_panel_controls(pattern_overrides)
                      if is_bluewhite_panel else None)
    if is_bluewhite_panel:
        validate_bluewhite_source_asset()

    mother = load_reference_mother(geometrydir)
    before_hash = _array_geometry_hash(mother.mesh.vertices, mother.mesh.faces)
    material_profile = reference_material(
        str(material_style), controls=dict(material_controls), seed=seed_values["material"])
    pigment_panel: BlueWhitePanelResult | None = None
    bluewhite_material_compatibility: dict[str, Any] | None = None
    if is_bluewhite_panel:
        bluewhite_material_compatibility = validate_bluewhite_material_compatibility(
            material_profile)
        source_density, source_metadata = _load_bluewhite_source_density()
        outer_chart = mother.chart_for_tag(TAG_INDEX["outer_wall"])
        if outer_chart is None:
            raise _error("blue-white panel route requires the actual outer-wall chart")
        profile_rzs = np.asarray(
            outer_chart.meta.get("arrays", {}).get("profile_rzs"), dtype=np.float64)
        if profile_rzs.ndim != 2 or profile_rzs.shape[1] != 3 or len(profile_rzs) < 3:
            raise _error("blue-white route has no valid source outer-meridian profile")
        meridian_length = float(np.linalg.norm(np.diff(profile_rzs[:, :2], axis=0), axis=1).sum())
        if not math.isfinite(meridian_length) or meridian_length <= 0.0:
            raise _error("blue-white route has an invalid finite-polyline meridian length")
        pigment_panel = build_bluewhite_panel(
            profile_rzs,
            source_density,
            source_metadata=source_metadata,
            panel_width_mm=panel_controls["panel_width_mm"],
            panel_height_mm=panel_controls["panel_height_mm"],
            center_s_mm=panel_controls["center_s_fraction"] * meridian_length,
            center_theta_rad=panel_controls["center_theta_rad"],
            diffusivity_s_mm2_per_unit=panel_controls["diffusivity_s_mm2_per_unit"],
            diffusivity_theta_mm2_per_unit=panel_controls["diffusivity_theta_mm2_per_unit"],
            duration=panel_controls["duration"],
            mobile_fraction=panel_controls["mobile_fraction"],
            n_s=panel_controls["n_s"],
            n_theta=panel_controls["n_theta"],
            boundary_halo_mm=panel_controls["boundary_halo_mm"],
            image_top_toward=panel_controls["image_top_toward"],
            glaze_white_linear_rgb=tuple(panel_controls["glaze_white_linear_rgb"]),
            tau_rgb=tuple(panel_controls["tau_rgb"]),
            continuous_sampling_mode=panel_controls["continuous_sampling_mode"],
        )
        pattern_recipe = None
        style_record = None
    else:
        pattern_recipe = build_reference_pattern(
            mother, str(pattern_style), seed=seed_values["pattern"],
            overrides=dict(pattern_overrides))
        style_record = reference_style_record(str(pattern_style))
    centers = np.asarray(mother.mesh.triangles_center, dtype=np.float64)
    tags = np.asarray(mother.face_surface_tag, dtype=np.int32)
    tag_names = np.asarray([mother.tag_name(tag) for tag in tags], dtype=object)
    material_samples = sample_reference_material(material_profile, centers, tag_names)
    outer_tag = TAG_INDEX["outer_wall"]
    outer_face_mask = tags == outer_tag
    if pigment_panel is not None:
        outer_chart = mother.chart_for_tag(outer_tag)
        outer_points = centers[outer_face_mask]
        face_uv = outer_chart.uv(outer_points)
        face_theta = np.mod(np.arctan2(outer_points[:, 1], outer_points[:, 0]), 2.0 * math.pi)
        face_density = np.zeros(len(centers), dtype=np.float64)
        face_density[outer_face_mask] = pigment_panel.sample_density(
            face_uv[:, 1], face_theta, component="total")
        face_transfer = np.ones((len(centers), 3), dtype=np.float64)
        face_transfer[outer_face_mask] = np.exp(
            -face_density[outer_face_mask, None]
            * np.asarray(pigment_panel.tau_rgb, dtype=np.float64)[None, :])
        height = np.zeros(len(centers), dtype=np.float64)
        pat_albedo = face_transfer.astype(np.float32)
        pat_roughness = np.zeros(len(centers), dtype=np.float32)
        # The field is never applied outside this exact outer-wall tag. The threshold is an
        # evidence/display support only; the transfer itself uses the full continuous density.
        pat_mask = ((face_density > 0.01) & outer_face_mask).astype(np.uint8)
        style_face_mask = outer_face_mask
        pattern_surface = "outer_wall"
    else:
        assert pattern_recipe is not None and style_record is not None
        pattern_channels = evaluate_pattern(pattern_recipe, mother, centers, tags)
        height = np.asarray(pattern_channels.height_mm, dtype=np.float64)
        pat_albedo = np.asarray(pattern_channels.albedo, dtype=np.float32)
        pat_roughness = np.asarray(pattern_channels.roughness, dtype=np.float32)
        pat_mask = np.asarray(pattern_channels.pattern_region, dtype=np.uint8)
        style_record_mapping = style_record.get("pattern_mapping") or {}
        pattern_surface = str(style_record_mapping.get("surface_tag") or "")
        if not pattern_surface:
            raise _error("buildable pattern style has no source-bound surface tag",
                         code=ErrorCode.SCHEMA_INVALID)
        pattern_tag = TAG_INDEX.get(pattern_surface)
        if pattern_tag is None:
            raise _error(f"pattern style refers to unsupported surface tag {pattern_surface!r}",
                         code=ErrorCode.SCHEMA_INVALID)
        style_face_mask = tags == pattern_tag
    if height.shape != (len(mother.mesh.faces),) or not np.isfinite(height).all():
        raise _error("pattern output height channel is malformed", code=ErrorCode.SCHEMA_INVALID)
    max_abs_height = float(np.max(np.abs(height))) if len(height) else 0.0
    if max_abs_height > 1e-9:
        raise _error("pattern recipe requests geometric relief but the source mesh was not modified",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements={"max_abs_pattern_height_mm": max_abs_height,
                                   "geometry_status": "SOURCE_GEOMETRY_UNCHANGED"})

    mat_albedo = np.asarray(material_samples["albedo"], dtype=np.float32)
    mat_roughness = np.asarray(material_samples["roughness"], dtype=np.float32)
    if mat_albedo.shape != (len(centers), 3) or mat_roughness.shape != (len(centers),):
        raise _error("material profile returned malformed per-face appearance arrays",
                     code=ErrorCode.SCHEMA_INVALID)
    if (pat_albedo.shape != (len(centers), 3) or pat_roughness.shape != (len(centers),)
            or pat_mask.shape != (len(centers),)):
        raise _error("pattern recipe returned malformed per-face appearance arrays",
                     code=ErrorCode.SCHEMA_INVALID)

    if pigment_panel is not None:
        # This is the declared appearance proxy: preserve each material sample's roughness
        # and IOR while multiplying its source-conditioned albedo by exp(-tau_rgb * density).
        combined_albedo = np.clip(mat_albedo.astype(np.float64) * pat_albedo, 0.0, 1.0)
        combined_roughness = mat_roughness.copy()
    else:
        assert pattern_recipe is not None
        combined_albedo, combined_roughness = _compose_pattern_transfer(
            mat_albedo, mat_roughness, pat_albedo, pat_roughness, pattern_recipe,
            style_face_mask)

    after_hash = _array_geometry_hash(mother.mesh.vertices, mother.mesh.faces)
    if after_hash != before_hash:
        raise _error("composition changed source vertices or faces",
                     code=ErrorCode.ASSET_HASH_MISMATCH,
                     measurements={"before_geometry_sha256": before_hash,
                                   "after_geometry_sha256": after_hash})
    policy = dict(material_profile.get("coating_surface_policy") or {})
    coated_tags = set(policy.get("coated_tags") or [])
    bare_tags = set(policy.get("bare_body_tags") or [])
    if "interface" not in bare_tags:
        raise _error("material profile does not mark fresh interface surfaces as bare body",
                     code=ErrorCode.SCHEMA_INVALID)
    if pattern_surface in {"interface", "attachment"}:
        raise _error("the selected reference pattern may not target a fresh interface/attachment",
                     code=ErrorCode.SCHEMA_INVALID)

    source_meta = mother.meta
    if pigment_panel is not None:
        panel_receipt_bytes = json.dumps(
            pigment_panel.receipt, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")
        pattern_record: dict[str, Any] = {
            "style_id": BLUEWHITE_PANEL_STYLE,
            "family_id": None,
            "field_family_id": BLUEWHITE_PANEL_FIELD_FAMILY,
            "seed_ref": None,
            "source_field": {
                "source_id": pigment_panel.receipt["source"]["source_id"],
                "title": pigment_panel.receipt["source"]["title"],
                "source_url": pigment_panel.receipt["source"]["source_url"],
                "source_mask_path": pigment_panel.receipt["source"]["source_mask_path"],
                "source_mask_sha256": pigment_panel.receipt["source"]["source_mask_sha256"],
                "normalized_density_sha256": pigment_panel.receipt["source"][
                    "normalized_density_sha256"],
                "mask_semantics": pigment_panel.receipt["source"]["mask_semantics"],
                "photo_state": pigment_panel.receipt["source"]["photo_state"],
            },
            "mapping_and_spread_controls": dict(panel_controls or {}),
            "composed_color_law": "source_conditioned_material_albedo_linear_rgb * exp(-tau_rgb * total_density); material roughness and IOR unchanged",
            "field_receipt_schema": pigment_panel.receipt["schema"],
            "field_receipt_sha256": hashlib.sha256(panel_receipt_bytes).hexdigest(),
            "substrate_compatibility": bluewhite_material_compatibility,
            "claim_boundary": "finite photo-derived appearance proxy; not recovered pre-fire placement, authentic wrap, calibrated optics, chemistry, or firing mechanics",
        }
        pattern_source = {
            "source": pattern_record["source_field"],
            "known_semantic_motif": "dragon (named by the Met object title)",
            "unseen_wrap_or_symbolic_meaning_inferred": False,
            "field_receipt_sha256": pattern_record["field_receipt_sha256"],
        }
    else:
        assert pattern_recipe is not None
        pattern_record = {
            "style_id": str(pattern_style),
            "family_id": pattern_recipe.family_id,
            "seed_ref": pattern_recipe.seed_ref,
            "params": pattern_recipe.params,
            "recipe_hash": pattern_recipe.meta.get("recipe_hash", ""),
            "reference_style": pattern_recipe.meta.get("reference_style", {}),
        }
        pattern_source = pattern_recipe.meta.get("reference_style", {})
    recipe = {
        "schema": "synlab.reference_instance_recipe.v1",
        "generation_mode": "NEW_REFERENCE_GUIDED_DESIGN",
        "source_geometry": {
            "directory_name": Path(geometrydir).resolve().name,
            "geometry_source_sha256": source_meta["geometry_source_sha256"],
            "geometry_array_sha256": before_hash,
            "frame": source_meta["source_section_frame"],
            "candidate_status": source_meta["candidate_status"],
            "source_profile_fidelity": source_meta["source_profile_fidelity"],
            "refinement_status": source_meta["refinement_status"],
        },
        "seeds": dict(seed_values),
        "controls_requested": {"material": dict(material_controls),
                               "pattern": dict(pattern_overrides)},
        "material": {
            "style_id": str(material_style),
            "profile_hash": str(material_profile.get("profile_hash", "")),
            "material_id": str(material_profile.get("material_id", "")),
            "source_conditioned": material_profile.get("source_conditioned", {}),
            "coating_surface_policy": policy,
        },
        "pattern": pattern_record,
        "composition_policy": {
            "material_field": "source-conditioned material profile sampled at original triangle centroids and lineage tags",
            "pattern_field": ("finite photo-derived pigment density sampled on the actual outer-wall chart"
                              if pigment_panel is not None else
                              "existing pattern evaluator, applied only to the style's declared source surface tag"),
            "appearance_transfer": ("outer-wall source-conditioned material albedo multiplied by exp(-tau_rgb * total_density); roughness and IOR unchanged; appearance-only proxy"
                                    if pigment_panel is not None else
                                    "pattern albedo ratio and roughness delta over material sample; appearance-only approximation"),
            "geometry_effect": "none; source geometry remains byte-value-identical in canonical array representation",
            "fresh_interface": "body material only; no glaze and no original-surface pattern",
            "coating_claim": "appearance layer selection only; no physical glaze thickness or mechanics claim",
            "inside_floor_binding": ("The exact axis-to-body_inner source section segment is mapped to inner_wall for original-surface finish selection. The exterior underside remains base/bare. The body_inner pattern chart excludes this inside floor; no floor UV/pattern placement is claimed."),
            "continuous_preview_texture": ("deterministic bounded API samples on the actual outer meridian chart; dimensions are recorded in texture metrics; defaults are 512 x 1024; linear RGB retained, preview PNG converted to sRGB; no geometry refinement"),
        },
    }
    provenance = {
        "schema": "synlab.reference_instance_provenance.v1",
        "interpretation": "A reference-guided design candidate combining an unchanged VF size-reference geometry with independent documented style recipes; not an exact source-object clone.",
        "source_record": source_meta["source_record"],
        "source_file_sha256": source_meta["source_file_sha256"],
        "source_rights_status": source_meta["source_rights_status"],
        "source_dimensions_mm": source_meta["source_dimensions_mm"],
        "candidate_dimensions_mm": source_meta["candidate_dimensions_mm"],
        "design_assumptions": source_meta["design_assumptions"],
        "section_geometry_details": source_meta["section_geometry_details"],
        "native_face_lineage": source_meta["lineage"],
        "surface_tag_map": {str(index): name for index, name in mother.surface_tag_names.items()},
        "pattern_source": pattern_source,
        "material_source": material_profile.get("source_conditioned", {}),
        "known": [
            "The mesh is a VF generated candidate whose listed envelope dimensions are source-recorded or family-anchor dimensions.",
            "Triangle tags are bound through source B-rep face indices and exact meridian segment indices.",
            ("Pattern/material output uses the deterministic sourced blue-white panel and material APIs; "
             "the pattern seed is recorded but unused by this deterministic photo-derived field."
             if pigment_panel is not None else
             "Pattern/material output uses existing deterministic SynLab APIs and explicit independent seeds."),
        ],
        "unknown": [
            "Exact source-object meridian and local construction are not established.",
            "Optical colorimetry, glaze chemistry, glaze thickness, forming/firing history, and mechanical properties are unknown.",
            "Appearance composition is not a calibrated physical shader or coupled material-pattern model.",
        ],
    }
    metrics = {
        "geometry_array_sha256_before": before_hash,
        "geometry_array_sha256_after": after_hash,
        "geometry_unchanged": before_hash == after_hash,
        "vertex_count": int(len(mother.mesh.vertices)),
        "triangle_count": int(len(mother.mesh.faces)),
        "bounds_mm": [[float(value) for value in row] for row in mother.mesh.bounds],
        "dimensions_mm": [float(value) for value in np.ptp(mother.mesh.bounds, axis=0)],
        "signed_volume_mm3": float(mother.mesh.volume),
        "pattern_region_triangle_count": int(np.count_nonzero(pat_mask)),
        "pattern_style_triangle_count": int(np.count_nonzero(style_face_mask)),
        "material_layer_triangle_counts": {
            name: int(count) for name, count in zip(*np.unique(
                np.asarray(material_samples["layer_name"], dtype=object), return_counts=True))
        },
        "coated_source_tags_present": sorted(coated_tags & set(tag_names.tolist())),
        "bare_source_tags_present": sorted(bare_tags & set(tag_names.tolist())),
        "max_abs_pattern_height_mm": max_abs_height,
        "bluewhite_panel_status": ("SOURCE_PHOTO_APPEARANCE_PROXY" if pigment_panel is not None
                                    else "NOT_APPLICABLE"),
        "pattern_roughness_unchanged": bool(
            pigment_panel is not None and np.array_equal(
                mat_roughness[outer_face_mask], combined_roughness[outer_face_mask])),
        "pattern_ior_unchanged": bool(pigment_panel is not None),
        "pattern_albedo_field_semantics": ("per-channel exp(-tau_rgb * face_pigment_density) multiplicative transfer"
                                           if pigment_panel is not None else
                                           "reference pattern albedo sampled by the selected style"),
        "physical_properties_status": "UNKNOWN",
        "training_export_status": "NOT_REQUESTED_NOT_EXPORTED",
    }
    fields = {
        "face_centers_mm": centers.astype(np.float64, copy=False),
        "face_surface_tag": tags.astype(np.int32, copy=False),
        "source_brep_face_index": np.asarray(
            mother.meta["triangle_source_brep_face_index"], dtype=np.int32),
        "display_normal_group": np.asarray(
            mother.meta["triangle_display_normal_group"], dtype=np.int32),
        "material_layer_id": np.asarray(material_samples["layer_id"], dtype=np.int32),
        "material_albedo_linear_rgb": mat_albedo,
        "material_roughness": mat_roughness,
        "material_ior": np.asarray(material_samples["ior"], dtype=np.float32),
        "material_transmission": np.asarray(material_samples["transmission"], dtype=np.float32),
        "pattern_albedo_linear_rgb": pat_albedo,
        "pattern_roughness": pat_roughness,
        "pattern_height_mm": height.astype(np.float32),
        "pattern_region": pat_mask,
        "combined_albedo_linear_rgb": combined_albedo.astype(np.float32),
        "combined_roughness": combined_roughness.astype(np.float32),
    }
    if pigment_panel is not None:
        fields["face_pigment_density"] = np.asarray(
            face_density, dtype=np.float32)
    return ReferenceInstance(
        mother=mother,
        material_profile=material_profile,
        pattern_recipe=pattern_recipe,
        fields=fields,
        recipe=recipe,
        provenance=provenance,
        metrics=metrics,
        pigment_panel=pigment_panel,
    )


def sample_outer_wall_texture(instance: ReferenceInstance, *, n_theta: int = 1024,
                              n_s: int = 512) -> dict[str, Any]:
    """Evaluate appearance continuously on a regular (theta, actual-chart-s) grid.

    Each sample lies on the sampled source Bézier chart profile. The existing pattern and
    material evaluators—not per-triangle centroid colors—supply texture values. `s` is still a
    finite-polyline arclength approximation to the serialized source curve, as recorded in the
    mother chart metadata. This output is for texturing/rendering only and never changes mesh
    positions, topology, volume, or face fields.
    """
    if isinstance(n_theta, bool) or isinstance(n_s, bool):
        raise _error("texture dimensions must be integers", code=ErrorCode.SCHEMA_INVALID)
    if not isinstance(n_theta, (int, np.integer)) or not isinstance(n_s, (int, np.integer)):
        raise _error("texture dimensions must be integers", code=ErrorCode.SCHEMA_INVALID)
    n_theta, n_s = int(n_theta), int(n_s)
    if not 3 <= n_theta <= 4096 or not 2 <= n_s <= 2048 or n_theta * n_s > 1_000_000:
        raise _error("texture grid is outside the bounded sampling limits",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements={"n_theta": n_theta, "n_s": n_s,
                                   "max_cells": 1_000_000})
    texture_preflight_bytes = n_s * n_theta * (3 * 4 + 1 + 4 + 3) + 64 * 1024
    if texture_preflight_bytes > 64 * 1024 * 1024:
        raise _error("outer texture output preflight exceeds the 64 MiB per-instance ceiling",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements={"estimated_texture_output_bytes": texture_preflight_bytes,
                                   "maximum_bytes": 64 * 1024 * 1024})
    mother = instance.mother
    outer_tag = TAG_INDEX["outer_wall"]
    chart = mother.chart_for_tag(outer_tag)
    if chart is None:
        raise _error("reference mother has no outer-wall chart")
    profile = np.asarray(chart.meta.get("arrays", {}).get("profile_rzs"), dtype=np.float64)
    if profile.ndim != 2 or profile.shape[1] != 3 or len(profile) < 3:
        raise _error("outer-wall chart has no valid source profile array")
    ds = np.linalg.norm(np.diff(profile[:, :2], axis=0), axis=1)
    s_profile = np.concatenate([[0.0], np.cumsum(ds)])
    s_total = float(s_profile[-1])
    if not math.isfinite(s_total) or s_total <= 0:
        raise _error("outer-wall chart has invalid sampled meridian length")
    s_centers = (np.arange(n_s, dtype=np.float64) + 0.5) * (s_total / n_s)
    radius = np.interp(s_centers, s_profile, profile[:, 0])
    z = np.interp(s_centers, s_profile, profile[:, 1])
    # The API's general revolve chart projects every query onto every polyline segment.
    # Texture points are constructed on this exact sampled meridian, and these source
    # profiles have monotone z, so a private, equivalent lookup chart avoids O(N*segments)
    # projection work without changing the registered mother/chart or the evaluated pattern.
    z_ascending = profile[::-1, 1]
    s_ascending = s_profile[::-1]
    if np.any(np.diff(z_ascending) < -1e-10):
        raise _error("outer profile z is not monotone; fast texture lookup is unavailable")
    keep = np.concatenate([[True], np.diff(z_ascending) > 1e-10])
    z_lookup = z_ascending[keep]
    s_lookup = s_ascending[keep]
    fast_chart = copy.copy(chart)

    def fast_to_uv(points_mm: np.ndarray) -> np.ndarray:
        points = np.atleast_2d(np.asarray(points_mm, dtype=np.float64))
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError("outer texture chart expects points shaped (N,3)")
        u = np.mod(np.arctan2(points[:, 1], points[:, 0]) / (2.0 * np.pi), 1.0)
        s_value = np.interp(points[:, 2], z_lookup, s_lookup)
        return np.column_stack([u, s_value])

    def fast_region_mask(points_mm: np.ndarray) -> np.ndarray:
        points = np.atleast_2d(np.asarray(points_mm, dtype=np.float64))
        s_value = fast_to_uv(points)[:, 1]
        r_expected = np.interp(s_value, s_profile, profile[:, 0])
        z_expected = np.interp(s_value, s_profile, profile[:, 1])
        radial = np.hypot(points[:, 0], points[:, 1])
        tolerance = float((chart.meta.get("spec") or {}).get("tol_mm", 1.0))
        distance = np.hypot(radial - r_expected, points[:, 2] - z_expected)
        return np.asarray(distance <= tolerance, dtype=bool)

    fast_chart.to_uv = fast_to_uv
    fast_chart.region_mask = fast_region_mask
    texture_mother = copy.copy(mother)
    texture_mother.charts = [fast_chart if candidate is chart else candidate
                             for candidate in mother.charts]
    theta_centers = (np.arange(n_theta, dtype=np.float64) + 0.5) * (2.0 * math.pi / n_theta)
    output = np.empty((n_s, n_theta, 3), dtype=np.float32)
    mask = np.zeros((n_s, n_theta), dtype=np.uint8)
    pigment_density_output = np.zeros((n_s, n_theta), dtype=np.float32)
    for start in range(0, n_s, 64):
        stop = min(n_s, start + 64)
        theta_grid = np.broadcast_to(theta_centers[None, :], (stop - start, n_theta))
        radius_grid = np.broadcast_to(radius[start:stop, None], theta_grid.shape)
        z_grid = np.broadcast_to(z[start:stop, None], theta_grid.shape)
        points = np.stack([radius_grid * np.cos(theta_grid),
                           radius_grid * np.sin(theta_grid), z_grid], axis=-1)
        flat_points = points.reshape(-1, 3)
        point_tags = np.full(len(flat_points), outer_tag, dtype=np.int32)
        material = sample_reference_material(
            instance.material_profile, flat_points, "outer_wall")
        if instance.pigment_panel is not None:
            s_grid = np.broadcast_to(s_centers[start:stop, None], theta_grid.shape)
            density = instance.pigment_panel.sample_density(
                s_grid.reshape(-1), theta_grid.reshape(-1), component="total")
            tau = np.asarray(instance.pigment_panel.tau_rgb, dtype=np.float64)
            transfer = np.exp(-density[:, None] * tau[None, :])
            combined = np.clip(np.asarray(material["albedo"], dtype=np.float64) * transfer,
                               0.0, 1.0)
            density_grid = density.reshape(stop - start, n_theta)
            pigment_density_output[start:stop] = density_grid.astype(np.float32)
            mask[start:stop] = (density_grid > 0.01).astype(np.uint8)
        else:
            if instance.pattern_recipe is None:
                raise _error("continuous texture route has neither pattern recipe nor pigment field")
            pattern = evaluate_pattern(instance.pattern_recipe, texture_mother,
                                       flat_points, point_tags)
            if np.any(np.abs(pattern.height_mm) > 1e-9):
                raise _error("continuous pattern texture contains un-applied geometric relief",
                             code=ErrorCode.SCHEMA_INVALID)
            combined, _ = _compose_pattern_transfer(
                np.asarray(material["albedo"], dtype=np.float64),
                np.asarray(material["roughness"], dtype=np.float64),
                np.asarray(pattern.albedo, dtype=np.float64),
                np.asarray(pattern.roughness, dtype=np.float64),
                instance.pattern_recipe,
                np.ones(len(flat_points), dtype=bool),
            )
            mask[start:stop] = np.asarray(pattern.pattern_region, dtype=np.uint8).reshape(
                stop - start, n_theta)
        output[start:stop] = combined.reshape(stop - start, n_theta, 3).astype(np.float32)

    # Check a deterministic subset against the original general-purpose chart closure. The
    # fast evaluator above is only an optimization for this known monotone-z profile; it must
    # continue to agree with the registered chart on actual source-chart points.
    row_indices = np.unique(np.asarray(
        [0, n_s // 4, n_s // 2, (3 * n_s) // 4, n_s - 1], dtype=np.int64))
    column_indices = np.unique(np.asarray(
        [0, n_theta // 4, n_theta // 2, (3 * n_theta) // 4, n_theta - 1],
        dtype=np.int64))
    probe_rows, probe_columns = np.meshgrid(row_indices, column_indices, indexing="ij")
    flat_rows = probe_rows.reshape(-1)
    probe_r = radius[flat_rows]
    probe_z = z[flat_rows]
    probe_theta = theta_centers[probe_columns.reshape(-1)]
    probe_points = np.column_stack([probe_r * np.cos(probe_theta),
                                    probe_r * np.sin(probe_theta), probe_z])
    expected_u = np.mod(probe_theta / (2.0 * math.pi), 1.0)
    expected_s = s_centers[flat_rows]
    observed_uv = chart.uv(probe_points)
    observed_u_delta = np.abs(observed_uv[:, 0] - expected_u)
    observed_u_delta = np.minimum(observed_u_delta, 1.0 - observed_u_delta)
    observed_s_delta = np.abs(observed_uv[:, 1] - expected_s)
    chart_membership = np.asarray(chart.region_mask(probe_points), dtype=bool)
    chart_tolerance_mm = max(1e-7, 1e-9 * s_total)
    chart_validation = {
        "method": "ORIGINAL_UNMODIFIED_GENERAL_CHART_UV_AND_REGION_MASK",
        "sample_count": int(len(probe_points)),
        "maximum_periodic_u_error": float(observed_u_delta.max()),
        "maximum_s_error_mm": float(observed_s_delta.max()),
        "maximum_allowed_s_error_mm": chart_tolerance_mm,
        "source_chart_membership_true": int(np.count_nonzero(chart_membership)),
        "passed": bool(np.all(observed_u_delta <= 1e-12)
                       and np.all(observed_s_delta <= chart_tolerance_mm)
                       and np.all(chart_membership)),
    }
    if not chart_validation["passed"]:
        raise _error("fast outer texture lookup disagrees with the original general chart",
                     code=ErrorCode.ASSET_HASH_MISMATCH,
                     measurements=chart_validation)

    seam_delta = np.abs(output[:, 0, :] - output[:, -1, :])
    interior_delta = np.abs(np.diff(output, axis=1))
    interior_p99 = float(np.quantile(interior_delta, 0.99))
    seam_limit = interior_p99 * 1.5 + 1e-4
    seam_metrics = {
        "comparison": "FIRST_AND_LAST_AZIMUTH_PIXEL_CENTERS_VS_INTERIOR_NEIGHBORS",
        "maximum_linear_rgb_delta": float(seam_delta.max()),
        "mean_linear_rgb_delta": float(seam_delta.mean()),
        "interior_neighbor_p99_linear_rgb_delta": interior_p99,
        "maximum_allowed_linear_rgb_delta": seam_limit,
        "passed": bool(float(seam_delta.max()) <= seam_limit),
    }
    if not seam_metrics["passed"]:
        raise _error("outer texture has a discontinuity at its periodic azimuth seam",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements=seam_metrics)

    return {
        "outer_texture_linear_rgb": output,
        "outer_pattern_region": mask,
        "outer_pigment_density": pigment_density_output,
        "s_centers_mm": s_centers.astype(np.float64),
        "theta_centers_rad": theta_centers.astype(np.float64),
        "profile_radius_mm": radius.astype(np.float64),
        "metrics": {
            "grid_shape_s_theta": [n_s, n_theta],
            "texture_output_preflight_upper_bound_bytes": texture_preflight_bytes,
            "grid_sampling": "CELL_CENTERED_UNIFORM_FINITE_POLYLINE_ARCLENGTH_X_PERIODIC_AZIMUTH",
            "arclength_status": chart.meta.get("reference_curve_sampling", {}).get(
                "arclength_status"),
            "profile_status": "ANALYTIC_SOURCE_CUBIC_BEZIER_SAMPLED_AS_FINITE_POLYLINE",
            "geometry_changed": False,
            "pattern_region_cell_count": int(np.count_nonzero(mask)),
            "color_space": "LINEAR_SRGB_PRIMARIES",
            "source_pattern_recipe_hash": (instance.pattern_recipe.meta.get("recipe_hash", "")
                                           if instance.pattern_recipe is not None else None),
            "source_material_profile_hash": instance.material_profile.get("profile_hash", ""),
            "bluewhite_field_receipt_sha256": (
                instance.recipe["pattern"].get("field_receipt_sha256")
                if instance.pigment_panel is not None else None),
            "pigment_density_sha256": hashlib.sha256(
                np.ascontiguousarray(pigment_density_output, dtype="<f4").tobytes()).hexdigest(),
            "general_chart_validation": chart_validation,
            "periodic_seam_validation": seam_metrics,
        },
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_reference_instance(instance: ReferenceInstance, output_dir: str | os.PathLike[str],
                             *, texture: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Write a replayable JSON/NPZ evidence bundle; no training export is produced."""
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite reference instance output: {target}")
    mesh_path = target / "geometry_and_fields.npz"
    outer_tag = TAG_INDEX["outer_wall"]
    outer_mask = np.asarray(instance.mother.face_surface_tag, dtype=np.int32) == outer_tag
    outer_chart = instance.mother.chart_for_tag(outer_tag)
    if outer_chart is None:
        raise _error("reference mother has no outer-wall chart")
    profile_rzs = np.asarray(
        (outer_chart.meta.get("arrays") or {}).get("profile_rzs"), dtype=np.float64)
    if (profile_rzs.ndim != 2 or profile_rzs.shape[1] < 2 or len(profile_rzs) < 2
            or not np.isfinite(profile_rzs[:, :2]).all()):
        raise _error("outer-wall chart has no finite meridian profile for its replay bundle",
                     code=ErrorCode.SCHEMA_INVALID)
    outer_profile_rz_mm = np.asarray(profile_rzs[:, :2], dtype=np.float64)
    face_uv = np.full((instance.mother.n_faces, 3, 2), np.nan, dtype=np.float32)
    if np.any(outer_mask):
        tri_indices = np.asarray(instance.mother.mesh.faces, dtype=np.int64)[outer_mask]
        tri_points = np.asarray(instance.mother.mesh.vertices, dtype=np.float64)[tri_indices]
        flat_uv = outer_chart.uv(tri_points.reshape(-1, 3))
        total = float((outer_chart.meta.get("spec") or {}).get("s_total_mm") or 0.0)
        if total <= 0:
            raise _error("outer-wall chart has no positive s span for texture coordinates")
        uv = flat_uv.reshape(-1, 3, 2).astype(np.float64)
        uv[:, :, 1] /= total
        # Unwrap only this display texture coordinate at the periodic seam. Source geometry
        # and the native mesh indices remain exactly as supplied.
        for tri in uv:
            if float(tri[:, 0].max() - tri[:, 0].min()) > 0.5:
                tri[tri[:, 0] < 0.5, 0] += 1.0
        face_uv[outer_mask] = uv.astype(np.float32)
        u_spans = np.ptp(face_uv[outer_mask, :, 0], axis=1)
        if not np.isfinite(face_uv[outer_mask]).all() or np.any(u_spans > 0.5 + 1e-6):
            raise _error("outer face UVs contain a periodic seam-spanning triangle",
                         code=ErrorCode.SCHEMA_INVALID,
                         measurements={"maximum_triangle_u_span": float(u_spans.max()),
                                       "triangle_count": int(len(u_spans))})
    else:
        u_spans = np.zeros(0, dtype=np.float64)
    texture = sample_outer_wall_texture(instance) if texture is None else dict(texture)
    texture_metrics = dict(texture.get("metrics") or {})
    grid_shape = texture_metrics.get("grid_shape_s_theta")
    if (not isinstance(grid_shape, (list, tuple)) or len(grid_shape) != 2
            or any(isinstance(value, bool) or not isinstance(value, (int, np.integer))
                   for value in grid_shape)):
        raise _error("outer texture metrics must record integer grid_shape_s_theta",
                     code=ErrorCode.SCHEMA_INVALID)
    n_s, n_theta = (int(grid_shape[0]), int(grid_shape[1]))
    if (n_theta < 3 or n_theta > 4096 or n_s < 2 or n_s > 2048
            or n_s * n_theta > 1_000_000):
        raise _error("outer texture metrics describe a grid outside the bounded sampling limits",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements={"grid_shape_s_theta": [n_s, n_theta],
                                   "max_cells": 1_000_000})
    expected_texture_shape = (n_s, n_theta, 3)
    texture_rgb = np.asarray(texture.get("outer_texture_linear_rgb"))
    density_texture = np.asarray(texture.get("outer_pigment_density"))
    region_texture = np.asarray(texture.get("outer_pattern_region"))
    s_texture = np.asarray(texture.get("s_centers_mm"))
    theta_texture = np.asarray(texture.get("theta_centers_rad"))
    radius_texture = np.asarray(texture.get("profile_radius_mm"))
    if (texture_rgb.dtype != np.dtype(np.float32)
            or texture_rgb.shape != expected_texture_shape
            or not np.isfinite(texture_rgb).all()
            or density_texture.dtype != np.dtype(np.float32)
            or density_texture.shape != (n_s, n_theta)
            or not np.isfinite(density_texture).all()
            or region_texture.dtype != np.dtype(np.uint8)
            or region_texture.shape != (n_s, n_theta)
            or s_texture.shape != (n_s,) or not np.isfinite(s_texture).all()
            or theta_texture.shape != (n_theta,) or not np.isfinite(theta_texture).all()
            or radius_texture.shape != (n_s,) or not np.isfinite(radius_texture).all()
            or texture_metrics.get("grid_sampling") !=
               "CELL_CENTERED_UNIFORM_FINITE_POLYLINE_ARCLENGTH_X_PERIODIC_AZIMUTH"):
        raise _error("outer texture is malformed or has an unsupported grid shape",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements={"observed_shape": list(texture_rgb.shape),
                                   "expected_shape": list(expected_texture_shape)})
    expected_preflight_bytes = n_s * n_theta * (3 * 4 + 1 + 4 + 3) + 64 * 1024
    if (texture_metrics.get("texture_output_preflight_upper_bound_bytes")
            != expected_preflight_bytes
            or expected_preflight_bytes > 64 * 1024 * 1024):
        raise _error("outer texture is missing a passing 64 MiB output preflight",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements={"expected_preflight_bytes": expected_preflight_bytes,
                                   "recorded_preflight_bytes": texture_metrics.get(
                                       "texture_output_preflight_upper_bound_bytes"),
                                   "maximum_bytes": 64 * 1024 * 1024})
    if (not (texture_metrics.get("general_chart_validation") or {}).get("passed")
            or not (texture_metrics.get("periodic_seam_validation") or {}).get("passed")):
        raise _error("outer texture is missing passing general-chart or seam validation",
                     code=ErrorCode.SCHEMA_INVALID,
                     measurements={"texture_metrics": texture_metrics})
    target.mkdir(parents=True, exist_ok=False)
    texture_npz_path = target / "appearance_texture.npz"
    np.savez_compressed(
        texture_npz_path,
        outer_texture_linear_rgb=texture["outer_texture_linear_rgb"],
        outer_pattern_region=texture["outer_pattern_region"],
        outer_pigment_density=texture["outer_pigment_density"],
        s_centers_mm=texture["s_centers_mm"],
        theta_centers_rad=texture["theta_centers_rad"],
        profile_radius_mm=texture["profile_radius_mm"],
    )
    texture_png_path = target / "outer_texture_srgb.png"
    from PIL import Image

    rgb = np.asarray(texture_rgb, dtype=np.float64)
    srgb = np.where(rgb <= 0.0031308, 12.92 * rgb,
                    1.055 * np.power(np.maximum(rgb, 0.0), 1.0 / 2.4) - 0.055)
    pixels = np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)
    Image.fromarray(pixels, mode="RGB").save(texture_png_path, format="PNG", optimize=False)
    np.savez_compressed(
        mesh_path,
        vertices_mm=np.asarray(instance.mother.mesh.vertices, dtype=np.float64),
        faces=np.asarray(instance.mother.mesh.faces, dtype=np.int64),
        outer_profile_rz_mm=outer_profile_rz_mm,
        face_outer_texture_uv=face_uv,
        face_outer_texture_mask=outer_mask.astype(np.uint8),
        face_surface_tag=instance.fields["face_surface_tag"],
        face_source_brep_face_index=instance.fields["source_brep_face_index"],
        face_display_normal_group=instance.fields["display_normal_group"],
        face_material_layer_id=instance.fields["material_layer_id"],
        face_material_albedo_linear_rgb=instance.fields["material_albedo_linear_rgb"],
        face_material_roughness=instance.fields["material_roughness"],
        face_material_ior=instance.fields["material_ior"],
        face_material_transmission=instance.fields["material_transmission"],
        face_pattern_albedo_linear_rgb=instance.fields["pattern_albedo_linear_rgb"],
        face_pattern_roughness=instance.fields["pattern_roughness"],
        face_pattern_height_mm=instance.fields["pattern_height_mm"],
        face_pattern_region=instance.fields["pattern_region"],
        face_combined_albedo_linear_rgb=instance.fields["combined_albedo_linear_rgb"],
        face_combined_roughness=instance.fields["combined_roughness"],
        **({"face_pigment_density": instance.fields["face_pigment_density"]}
           if "face_pigment_density" in instance.fields else {}),
    )
    panel_output_paths: list[Path] = []
    panel_array_hashes: dict[str, str] | None = None
    if instance.pigment_panel is not None:
        panel = instance.pigment_panel
        panel_arrays = {
            "initial_density": panel.initial_density,
            "bound_density": panel.bound_density,
            "mobile_density": panel.mobile_density,
            "total_density": panel.total_density,
            "linear_rgb": panel.linear_rgb,
            "s_centers_mm": panel.s_centers_mm,
            "radius_mm": panel.radius_mm,
            "theta_centers_rad": panel.theta_centers_rad,
            "cell_area_mm2": panel.cell_area_mm2,
        }
        if panel.continuous_sampling_mode == SOURCE_RESOLVED_STATIONARY_SAMPLING:
            if panel.source_density is None:
                raise _error("source-resolved panel has no immutable source array",
                             code=ErrorCode.SCHEMA_INVALID)
            panel_arrays["normalized_source_density"] = panel.source_density
        panel_npz_path = target / "bluewhite_panel_fields.npz"
        np.savez_compressed(panel_npz_path, **panel_arrays)
        panel_array_hashes = {}
        for name, array in panel_arrays.items():
            value = np.ascontiguousarray(array)
            digest = hashlib.sha256()
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(value.dtype.str.encode("ascii") + b"\0")
            digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode())
            digest.update(value.tobytes())
            panel_array_hashes[name] = digest.hexdigest()
        panel_receipt_path = target / "bluewhite_panel_receipt.json"
        panel_receipt_path.write_text(json.dumps(
            _jsonable(panel.receipt), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        panel_output_paths.extend([panel_npz_path, panel_receipt_path])
    recipe_path = target / "recipe.json"
    recipe_path.write_text(json.dumps(_jsonable(instance.recipe), ensure_ascii=False,
                                      sort_keys=True, indent=2) + "\n", encoding="utf-8")
    provenance_path = target / "provenance.json"
    provenance_path.write_text(json.dumps(_jsonable(instance.provenance), ensure_ascii=False,
                                          sort_keys=True, indent=2) + "\n", encoding="utf-8")
    metrics_path = target / "metrics.json"
    metrics_document = {
        **instance.metrics,
        "continuous_outer_texture": texture_metrics,
        "outer_face_texture_uv": {
            "triangle_count": int(len(u_spans)),
            "maximum_periodic_u_span_after_unwrap": (
                float(u_spans.max()) if len(u_spans) else 0.0),
            "passed": bool(not len(u_spans) or np.all(u_spans <= 0.5 + 1e-6)),
        },
    }
    if panel_array_hashes is not None:
        metrics_document["bluewhite_panel_persisted_field_array_sha256"] = panel_array_hashes
    metrics_path.write_text(json.dumps(_jsonable(metrics_document), ensure_ascii=False,
                                      sort_keys=True, indent=2) + "\n", encoding="utf-8")
    canonical_recipe_hash = hashlib.sha256(json.dumps(
        _jsonable(instance.recipe), ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    output_paths = (mesh_path, texture_npz_path, texture_png_path,
                    recipe_path, provenance_path, metrics_path, *panel_output_paths)
    outputs = {path.name: _sha256(path) for path in output_paths}
    receipt = {
        "schema": "synlab.reference_generation_sha256_receipt.v1",
        "canonical_recipe_sha256": canonical_recipe_hash,
        "geometry_array_sha256": instance.metrics["geometry_array_sha256_after"],
        "source_geometry_file_sha256": instance.mother.meta["source_file_sha256"],
        "file_sha256": outputs,
        "receipt_self_hash": "OMITTED_BY_DESIGN",
    }
    receipt_path = target / "sha256_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                       indent=2) + "\n", encoding="utf-8")
    outputs[receipt_path.name] = _sha256(receipt_path)
    manifest = {
        "schema": "synlab.reference_generation_output_manifest.v1",
        "status": "REFERENCE_GUIDED_DESIGN_CANDIDATE",
        "geometry_array_sha256": instance.metrics["geometry_array_sha256_after"],
        "canonical_recipe_sha256": canonical_recipe_hash,
        "source_geometry_file_sha256": instance.mother.meta["source_file_sha256"],
        "file_sha256": outputs,
        "training_export": "NONE",
    }
    manifest_path = target / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                         indent=2) + "\n", encoding="utf-8")
    outputs[manifest_path.name] = _sha256(manifest_path)
    return {"output_dir": str(target), "files": outputs, "manifest": manifest}


__all__ = [
    "BLUEWHITE_PANEL_STYLE",
    "ReferenceInstance",
    "compose_reference_instance",
    "load_reference_mother",
    "sample_outer_wall_texture",
    "validate_bluewhite_panel_controls",
    "validate_bluewhite_material_compatibility",
    "validate_bluewhite_source_asset",
    "write_reference_instance",
]
