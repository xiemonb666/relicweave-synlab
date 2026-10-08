"""Render backends: the software rasteriser plus the Blender worker dispatch.

Why this file exists
--------------------
Plan 13.2 assigns scene-linear RGB plus exact geometry passes (depth z, integer ID,
surface tag, occlusion, uncertain mask) to a Blender worker.  ``bpy`` has **no wheel
for Windows + CPython 3.12**, so Blender is not importable into this venv; a portable
Blender 5.2.2 LTS binary *is* installed and is driven as an external subprocess through
:mod:`synlab.observe.blender` (worker: ``blender_scripts/render_worker.py``).

``render_view(..., backend=BACKEND_BLENDER)`` therefore dispatches to the real Blender
worker; when the binary is missing or the worker exits non-zero the call raises a
structured :class:`~synlab.errors.SynLabError` instead of quietly returning a rasterised
image.  The NumPy rasteriser in this module stays the in-process **comparison and
fallback** backend and records

* ``backend = "SOFTWARE_RASTERIZER"`` in every render output,
* ``CUSTOM_GAP`` evidence in :func:`capability_probe`,
* its declared ``not_equivalent_for`` list against the Blender reference path.

Semantics that are deliberately *not* softened
----------------------------------------------
* ``id_map`` and ``surface_tag`` are **integer** channels: every sub-sample votes with its
  own integer and the winner is chosen by the same z-buffer as the depth, so a mixed
  pixel never yields a fractional class.
* ``depth_z`` is camera-frame depth in mm (not ray length, plan 4.3).
* ``uncertain_mask`` marks pixels where a single surface cannot be assigned: mixed
  primitive edges (detected by disagreement between the supersamples) and pixels whose
  circle of confusion exceeds ``RenderSpec.coc_px_threshold`` (defocus).  The CoC is evaluated
  in millimetres under the *declared* optics and converted with the delivered sampling density
  ``D = f_px / focal_length_mm`` (``mask_semantics = "coc_units_v2"``); see
  :func:`circle_of_confusion_px` and docs/a12/data_semantics_versions.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..cameras.projection import CAMERA_MODELS, distort_normalized
from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import RenderOutput, ViewFrame
from ..roles import SOURCE_SENSOR_SIM

BACKEND_SOFTWARE = "SOFTWARE_RASTERIZER"
BACKEND_BLENDER = "BLENDER_CYCLES"
BACKEND_BLENDER_EEVEE = "BLENDER_EEVEE"

#: Semantic version of the delivered *mask* channels (``uncertain_mask`` -> ``deployment_mask``
#: -> ``visible``).  ``coc_units_v2`` is the thin-lens CoC evaluated in mm and converted to
#: delivered pixels with the sensor sampling density ``D = f_px / focal_length_mm`` under the
#: declared f-number.  ``coc_units_v1_pixel_units`` is the superseded expression that fed a
#: *pixel* focal length into the mm formula and dropped ``D`` (inflation factor ``D * N``,
#: measured 74.105 on the L0 views); it survives only for frames that declare no optics at all
#: (synthetic test/audit frames), and a render that uses it says so in ``meta``.  Every render
#: records the version it used, so two batches can be told apart programmatically
#: (docs/a12/data_semantics_versions.md).
MASK_SEMANTICS = "coc_units_v2"
MASK_SEMANTICS_PIXEL_UNITS_V1 = "coc_units_v1_pixel_units"

#: Structured record of what the software rasteriser is *not* equivalent to.  The Blender
#: reference path is the portable worker (``synlab.observe.blender``); ``status`` is filled
#: from the measured probe by :func:`capability_probe`.
BLENDER_GAP: dict[str, Any] = {
    "capability": "blender_render",
    "status": "AVAILABLE_VIA_WORKER",
    "detail": "portable Blender 5.2.2 LTS is driven as a subprocess worker "
              "(blender_scripts/render_worker.py); bpy itself is still not importable into "
              "this venv, so the in-process backend stays the software rasteriser",
    "replacement": BACKEND_SOFTWARE,
    "replacement_class": "CUSTOM_GAP",
    "probe": "synlab.observe.blender.capability_probe",
    "not_equivalent_for": [
        "spectral/measured BRDF",
        "measured light transport (indirect bounce, caustics)",
        "Blender Z/Position/Object-Index pass anti-aliasing semantics",
        "production denoiser",
    ],
}


def capability_probe(*, refresh: bool = False) -> dict[str, Any]:
    """Probe the render backends actually available on this host.

    The Blender entry is a **measured** self-test (binary discovery + a real background
    render, see ``blender_scripts/selftest.py``); it is never reported as available when
    the binary is absent or the self-test fails.
    """
    report: dict[str, Any] = {
        "software_rasterizer": {"status": "OK", "backend": BACKEND_SOFTWARE,
                                "class": "CUSTOM_GAP"},
    }
    try:
        from .blender import capability_probe as _blender_probe

        report["blender"] = _blender_probe(refresh=refresh)
    except Exception as exc:  # noqa: BLE001 - a probe failure is itself a capability gap
        probe_error = f"{type(exc).__name__}: {exc}"
        blender = dict(BLENDER_GAP)
        blender.update({"status": "ENV_CAPABILITY_MISSING", "probe_error": probe_error})
        report["blender"] = blender
        try:  # pragma: no cover - exercised only where bpy exists
            import bpy  # type: ignore

            report["blender"] = {
                "capability": "blender_render",
                "status": "OK",
                "bpy_version": str(getattr(bpy.app, "version", "unknown")),
                "replacement_class": None,
            }
        except Exception as import_exc:  # noqa: BLE001 - any import failure is a gap
            report["blender"]["import_error"] = f"{type(import_exc).__name__}: {import_exc}"
    return report


# --------------------------------------------------------------------------------------
# Scene description
# --------------------------------------------------------------------------------------
@dataclass
class MaterialSpec:
    """Minimal shading inputs.

    This is a *simulation* material record, not a measured material: albedo values are
    declared constants (or deterministic per-face procedural speckle).  A real material
    library lives in :mod:`synlab.materials`; when a profile is supplied its albedo is
    used verbatim and recorded as ``source_kind``.
    """

    albedo: np.ndarray                    # (F,3) linear, per face
    roughness: np.ndarray                 # (F,) 0..1
    source_kind: str = SOURCE_SENSOR_SIM

    def __post_init__(self) -> None:
        self.albedo = np.asarray(self.albedo, dtype=np.float32)
        self.roughness = np.asarray(self.roughness, dtype=np.float32)


@dataclass
class Scene:
    """Triangles with per-face integer labels plus a rendering material."""

    name: str
    vertices: np.ndarray                  # (V,3) float64 mm
    faces: np.ndarray                     # (F,3) int32
    surface_tag: np.ndarray               # (F,) int16
    material: MaterialSpec
    #: (F,) int32 research label; -1 for support/backdrop geometry that is never a
    #: supervision target.
    face_id: np.ndarray | None = None
    #: (F,) uint8: 1 = target geometry, 0 = support/backdrop.  The deployment mask
    #: (obtainable at deploy time) is derived from this, the *research* id_map is not.
    is_target: np.ndarray | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.vertices = np.asarray(self.vertices, dtype=np.float64).reshape(-1, 3)
        self.faces = np.asarray(self.faces, dtype=np.int32).reshape(-1, 3)
        if self.faces.size and int(self.faces.max(initial=-1)) >= self.vertices.shape[0]:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "scene face index out of range",
                              stage="observe.render.Scene")
        self.surface_tag = np.asarray(self.surface_tag, dtype=np.int16).reshape(-1)
        if self.surface_tag.shape[0] != self.faces.shape[0]:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "surface_tag length must match face count",
                              stage="observe.render.Scene")
        if self.face_id is None:
            self.face_id = np.arange(self.faces.shape[0], dtype=np.int32)
        else:
            self.face_id = np.asarray(self.face_id, dtype=np.int32).reshape(-1)
        if self.face_id.shape[0] != self.faces.shape[0]:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "face_id length must match face count",
                              stage="observe.render.Scene")
        if self.is_target is None:
            self.is_target = np.ones(self.faces.shape[0], dtype=np.uint8)
        else:
            self.is_target = np.asarray(self.is_target, dtype=np.uint8).reshape(-1)
        if self.material.albedo.shape[0] != self.faces.shape[0]:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "material albedo must have one row per face",
                              stage="observe.render.Scene")

    @property
    def n_faces(self) -> int:
        return int(self.faces.shape[0])

    def transformed(self, T_WO: np.ndarray) -> "Scene":
        """Rigidly re-pose the *target* geometry (turntable rotation)."""
        T = np.asarray(T_WO, dtype=np.float64)
        verts = self.vertices @ T[:3, :3].T + T[:3, 3][None, :]
        return Scene(name=self.name, vertices=verts, faces=self.faces,
                     surface_tag=self.surface_tag, material=self.material,
                     face_id=self.face_id, is_target=self.is_target, meta=dict(self.meta))


@dataclass
class LightSpec:
    """One directional light, frozen for all views of a fragment (plan 13.2)."""

    direction: np.ndarray      # (3,) unit, direction the light *travels*
    color: np.ndarray          # (3,) linear radiance
    ambient: np.ndarray        # (3,) linear ambient


@dataclass
class RenderSpec:
    """Renderer configuration; every knob is recorded in ``RenderOutput.meta``."""

    supersample: int = 2
    near_mm: float = 1.0
    far_mm: float = 1.0e6
    background_linear: tuple[float, float, float] = (0.02, 0.02, 0.025)
    coc_px_threshold: float = 0.75
    max_pixels: int = 4_000_000
    shade: str = "LAMBERT_AMBIENT"
    #: Declared optics of the defocus mark-out.  ``None`` resolves from the frame
    #: (``ViewFrame.meta["focal_length_mm"]`` / ``["f_number"]``) and then from the camera
    #: profile registry through ``frame.profile_id``; a frame that declares no optics at all
    #: falls back to the pre-v2 pixel-unit expression and is labelled as such in the metadata.
    focal_length_mm: float | None = None
    f_number: float | None = None


def build_scene(mesh: Any, *, surface_tag: np.ndarray, face_id: np.ndarray | None = None,
                albedo: np.ndarray | None = None, roughness: np.ndarray | None = None,
                is_target: np.ndarray | None = None, name: str = "target",
                albedo_source_kind: str = SOURCE_SENSOR_SIM) -> Scene:
    """Build a :class:`Scene` from a trimesh mesh with explicit face labels."""
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int32)
    n = faces.shape[0]
    if albedo is None:
        albedo = procedural_albedo(n)
    if roughness is None:
        roughness = np.full(n, 0.55, dtype=np.float32)
    return Scene(name=name, vertices=verts, faces=faces,
                 surface_tag=np.asarray(surface_tag, dtype=np.int16),
                 material=MaterialSpec(np.asarray(albedo, dtype=np.float32),
                                       np.asarray(roughness, dtype=np.float32),
                                       source_kind=albedo_source_kind),
                 face_id=face_id, is_target=is_target)


#: Deterministic palette for the untextured fallback albedo.  A flat single-colour body
#: would produce no SIFT features, so the rasteriser supplies a *simulation* speckle;
#: this is declared as SENSOR_SIM, never as a measured material.
_ALBEDO_PALETTE = np.array([
    [0.62, 0.55, 0.46],
    [0.48, 0.42, 0.35],
    [0.71, 0.65, 0.55],
    [0.55, 0.50, 0.44],
    [0.40, 0.34, 0.29],
    [0.66, 0.60, 0.51],
], dtype=np.float32)


def procedural_albedo(n_faces: int, *, seed: int = 0x5EED) -> np.ndarray:
    """Deterministic per-face speckle albedo (simulation stand-in for a real material)."""
    if n_faces <= 0:
        return np.zeros((0, 3), dtype=np.float32)
    state = np.random.Generator(np.random.PCG64(np.uint64(seed)))
    idx = state.integers(0, _ALBEDO_PALETTE.shape[0], size=int(n_faces))
    jitter = 1.0 + state.normal(scale=0.06, size=(int(n_faces), 1)).astype(np.float32)
    return np.clip(_ALBEDO_PALETTE[idx] * jitter, 0.0, 1.0).astype(np.float32)


# --------------------------------------------------------------------------------------
# Rasteriser
# --------------------------------------------------------------------------------------
def _project_with_distortion(cam: np.ndarray, K: np.ndarray, dist: np.ndarray | None,
                             model: str) -> tuple[np.ndarray, np.ndarray]:
    z = cam[:, 2]
    safe = np.where(np.abs(z) > 1e-12, z, np.nan)
    x, y = cam[:, 0] / safe, cam[:, 1] / safe
    xd, yd = distort_normalized(x, y, dist, model)
    u = K[0, 0] * xd + K[0, 1] * yd + K[0, 2]
    v = K[1, 0] * xd + K[1, 1] * yd + K[1, 2]
    return np.stack([u, v], axis=1), z


def _rasterise_buffers(scene: Scene, frame: ViewFrame, width: int, height: int,
                       light: LightSpec, spec: RenderSpec) -> dict[str, np.ndarray]:
    """Z-buffered rasterisation at ``width x height`` (the supersampled grid)."""
    T_CW = frame.T_CW
    R = T_CW[:3, :3]
    t = T_CW[:3, 3]
    verts = scene.vertices @ R.T + t[None, :]
    uv, z = _project_with_distortion(verts, frame.K, frame.dist,
                                     frame.camera_model or "PINHOLE")

    depth = np.full((height, width), np.inf, dtype=np.float64)
    id_buf = np.full((height, width), -1, dtype=np.int32)
    tag_buf = np.full((height, width), -1, dtype=np.int16)
    rgba = np.zeros((height, width, 3), dtype=np.float32)

    faces = scene.faces
    if faces.shape[0] == 0:
        return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba}
    p0, p1, p2 = uv[faces[:, 0]], uv[faces[:, 1]], uv[faces[:, 2]]
    z0, z1, z2 = z[faces[:, 0]], z[faces[:, 1]], z[faces[:, 2]]
    area = (p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) \
        - (p2[:, 0] - p0[:, 0]) * (p1[:, 1] - p0[:, 1])

    # Back-face culling in camera space (counter-clockwise winding is front-facing).
    cam0, cam1, cam2 = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    normals = np.cross(cam1 - cam0, cam2 - cam0)
    front = normals[:, 2] < 0.0
    visible = (z0 > spec.near_mm) & (z1 > spec.near_mm) & (z2 > spec.near_mm) \
        & (z0 < spec.far_mm) & (z1 < spec.far_mm) & (z2 < spec.far_mm) \
        & front & np.isfinite(area) & (np.abs(area) > 1e-12)
    order = np.nonzero(visible)[0]
    if order.size == 0:
        return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba}

    # Shading inputs (frozen light, flat shading per face).
    world_normals = normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-15)
    scene_normals = world_normals @ frame.T_WC[:3, :3]
    lambert = np.clip(-(scene_normals @ light.direction), 0.0, 1.0)
    albedo = scene.material.albedo
    # View-dependent term is omitted on purpose: a frozen Lambert + ambient model keeps
    # the render deterministic and is declared as such.  No specular claim is made.
    shaded = albedo * (light.ambient[None, :] + light.color[None, :] * lambert[:, None])

    inv_area = 1.0 / area
    for fi in order:
        f = int(fi)
        xs = (p0[f, 0], p1[f, 0], p2[f, 0])
        ys = (p0[f, 1], p1[f, 1], p2[f, 1])
        xmin = max(int(np.floor(min(xs))), 0)
        xmax = min(int(np.ceil(max(xs))), width - 1)
        ymin = max(int(np.floor(min(ys))), 0)
        ymax = min(int(np.ceil(max(ys))), height - 1)
        if xmax < xmin or ymax < ymin:
            continue
        gx = np.arange(xmin, xmax + 1, dtype=np.float64) + 0.5
        gy = np.arange(ymin, ymax + 1, dtype=np.float64) + 0.5
        px = gx[None, :]
        py = gy[:, None]
        ax, ay = p0[f, 0], p0[f, 1]
        bx, by = p1[f, 0], p1[f, 1]
        cx, cy = p2[f, 0], p2[f, 1]
        inv = inv_area[f]
        w0 = ((bx - px) * (cy - py) - (cx - px) * (by - py)) * inv
        w1 = ((cx - px) * (ay - py) - (ax - px) * (cy - py)) * inv
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not inside.any():
            continue
        zi = w0 * z0[f] + w1 * z1[f] + w2 * z2[f]
        sub_depth = depth[ymin:ymax + 1, xmin:xmax + 1]
        better = inside & (zi < sub_depth)
        if not better.any():
            continue
        sub_depth[better] = zi[better]
        id_buf[ymin:ymax + 1, xmin:xmax + 1][better] = scene.face_id[f]
        tag_buf[ymin:ymax + 1, xmin:xmax + 1][better] = scene.surface_tag[f]
        rgba[ymin:ymax + 1, xmin:xmax + 1][better] = shaded[f].astype(np.float32)
    return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba}


def _block_reduce(buf: np.ndarray, factor: int, *, mode: str) -> np.ndarray:
    """Reduce a (H*f, W*f, C) buffer to (H, W, C) with a frozen rule."""
    if factor == 1:
        return buf
    h, w = buf.shape[0] // factor, buf.shape[1] // factor
    trimmed = buf[: h * factor, : w * factor]
    if mode == "mean":
        return trimmed.reshape(h, factor, w, factor, -1).mean(axis=(1, 3))
    if mode == "min":
        return trimmed.reshape(h, factor, w, factor, -1).min(axis=(1, 3))
    raise ValueError(mode)


def _disagreement_i(buf: np.ndarray, factor: int) -> np.ndarray:
    """True where the supersamples of one output pixel do not carry the same integer."""
    if factor == 1:
        return np.zeros(buf.shape[:2], dtype=bool)
    h, w = buf.shape[0] // factor, buf.shape[1] // factor
    trimmed = buf[: h * factor, : w * factor]
    blocks = trimmed.reshape(h, factor, w, factor)
    return (blocks != blocks[:, :1, :, :1]).any(axis=(1, 3))


def profile_optics(profile_id: str) -> dict[str, float]:
    """Declared focal length and f-number of one camera profile (empty when unresolvable)."""
    if not profile_id:
        return {}
    try:  # a profile registry that is unavailable must never be faked
        from ..cameras.profiles import profile_by_id

        profile = profile_by_id(str(profile_id))
    except Exception:  # noqa: BLE001 - any failure means "not declared"
        return {}
    focal = profile.meta.get("focal_length_mm")
    return {"focal_length_mm": float(focal) if focal else 0.0,
            "f_number": float(profile.f_number) if profile.f_number else 0.0,
            "sensor_width_mm": float(profile.meta.get("sensor_width_mm") or 0.0)}


def resolve_declared_optics(frame: ViewFrame, spec: RenderSpec | None = None) -> dict[str, Any]:
    """Resolve the *declared* optics of one frame into the numbers the CoC needs.

    The delivered circle of confusion is a length in millimetres (on the sensor) converted to
    pixels by the sampling density ``D = f_px / focal_length_mm`` (px per mm of sensor).  Both
    the focal length and the f-number are resolved from the first source that declares them:

    1. ``RenderSpec.focal_length_mm`` / ``RenderSpec.f_number`` (an explicit caller override),
    2. ``ViewFrame.meta`` (what :func:`synlab.cameras.viewframes.make_view_frames` writes),
    3. the camera-profile registry entry named by ``frame.profile_id``.

    ``declared`` is False only when neither source provides a focal length, i.e. the frame is a
    synthetic one (test/audit fixtures) that carries no optics; the returned
    ``sampling_px_per_mm`` is then ``None`` and the caller falls back to the documented
    pre-v2 pixel-unit expression instead of inventing a sensor.
    """
    spec = spec or RenderSpec()
    f_px = 0.5 * (float(frame.K[0, 0]) + float(frame.K[1, 1]))
    meta = dict(getattr(frame, "meta", {}) or {})
    focal = spec.focal_length_mm or meta.get("focal_length_mm")
    f_number = spec.f_number or meta.get("f_number")
    registry: dict[str, float] = {}
    if not focal or not f_number:
        registry = profile_optics(str(getattr(frame, "profile_id", "") or ""))
        focal = focal or registry.get("focal_length_mm")
        f_number = f_number or registry.get("f_number")
    focal = float(focal) if focal else 0.0
    f_number = float(f_number) if f_number else 0.0
    return {
        "f_px": float(f_px),
        "focal_length_mm": focal,
        "f_number": f_number,
        "sampling_px_per_mm": float(f_px / focal) if focal > 0 else None,
        "declared": bool(focal > 0 and f_number > 0),
        "profile_id": str(getattr(frame, "profile_id", "") or ""),
        "sensor_width_mm": float(registry.get("sensor_width_mm") or 0.0),
        "source": {"focal_length_mm": ("render_spec" if spec.focal_length_mm else
                                      "frame_meta" if meta.get("focal_length_mm") else
                                      "camera_profile" if registry.get("focal_length_mm") else
                                      "NONE"),
                   "f_number": ("render_spec" if spec.f_number else
                                "frame_meta" if meta.get("f_number") else
                                "camera_profile" if registry.get("f_number") else "NONE")},
    }


def circle_of_confusion_px(z_mm: np.ndarray, focus_distance_mm: float, f_number: float,
                           f_px: float, *, sampling_px_per_mm: float | None = None,
                           image_distance_mm: float | None = None) -> np.ndarray:
    """Thin-lens circle of confusion **in delivered pixels** for focus at ``focus_distance_mm``.

    Units, which is what this function is about
    -------------------------------------------
    The thin-lens blur diameter is an *image-space length in millimetres*::

        c_mm = f_mm^2 / (N * (z - f_mm)) * |z - z_f| / z_f

    with ``f_mm`` the focal length, ``N`` the f-number and ``z``, ``z_f`` the object distances
    (all mm).  Converting it to delivered pixels needs the sampling density of the delivered
    grid, ``D = width_px / sensor_width_mm = f_px / f_mm`` (px per mm of sensor)::

        c_px = D * c_mm = f_px^2 / (D * N * (z - f_px / D)) * |z - z_f| / z_f

    ``f_px`` alone is therefore *not* enough.  Feeding a pixel focal length into the mm
    expression and dropping ``D`` inflates the result by ``D * N``: measured on the delivered
    L0 views the renderer/declared ratio is exactly ``74.105 = D * f_number``
    (data/a12/reports/visible_labels_coc_units.json).  ``image_distance_mm`` is accepted for
    backward compatibility only: the form above already evaluates the sensor at the focused
    image distance, so it is not used.

    ``sampling_px_per_mm=None`` declares "one pixel is one millimetre of sensor" (``D = 1``) and
    keeps the **pre-v2 expression bit for bit** (``f_px^2 / (N * z) * |z - z_f| / z_f``, with the
    pixel focal length standing in for a millimetre one) so that a frame which declares no optics
    reproduces the shipped numbers; :func:`render_view` labels such a render
    (``mask_semantics = "coc_units_v1_pixel_units"``) instead of mixing it with v2 numbers
    (docs/a12/data_semantics_versions.md).
    """
    z = np.asarray(z_mm, dtype=np.float64)
    if f_px <= 0 or f_number <= 0:
        return np.zeros_like(z)
    z_f = max(float(focus_distance_mm), 1e-6)
    if sampling_px_per_mm is None:
        # pre-v2: a *pixel* focal length inside the millimetre expression, no sampling density.
        coc = np.abs(float(f_px) ** 2 / (float(f_number) * np.maximum(z, 1e-6))
                     * (z - z_f) / z_f)
        return np.nan_to_num(coc, nan=0.0, posinf=1e6, neginf=0.0)
    density = float(sampling_px_per_mm)
    if density <= 0:
        return np.zeros_like(z)
    f_mm = float(f_px) / density
    # object distance measured from the lens plane; the focused image distance is f*z_f/(z_f-f)
    z_rel = np.maximum(z - f_mm, 1e-6)
    coc_mm = (f_mm ** 2) / (float(f_number) * z_rel) * np.abs(z - z_f) / z_f
    return np.nan_to_num(density * coc_mm, nan=0.0, posinf=1e6, neginf=0.0)


def render_view(scene: Scene, frame: ViewFrame, *, light: LightSpec,
                spec: RenderSpec | None = None,
                object_pose: np.ndarray | None = None,
                focus_distance_mm: float | None = None,
                backend: str = BACKEND_SOFTWARE,
                blender_config: Any = None) -> RenderOutput:
    """Render one view to a :class:`RenderOutput` (linear RGB + integer geometry passes).

    ``object_pose`` is the physical turntable pose ``T_WO`` for this view: the *object*
    turns while the camera and the light stay fixed, which is what the capture bench
    does (plan 13.4).  It is a scene motion, not an image transform.

    ``backend`` is either :data:`BACKEND_SOFTWARE` (in-process NumPy rasteriser) or
    :data:`BACKEND_BLENDER`/:data:`BACKEND_BLENDER_EEVEE`, which dispatch to the real
    Blender subprocess worker in :mod:`synlab.observe.blender`.  A Blender request never
    falls back to the rasteriser: a missing binary or a non-zero worker exit raises.
    ``blender_config`` is an optional
    :class:`synlab.observe.blender.BlenderBackendConfig` passthrough (samples, filter
    width, denoise, scratch directory); it is ignored by the software backend.
    """
    spec = spec or RenderSpec()
    if backend in (BACKEND_BLENDER, BACKEND_BLENDER_EEVEE):
        from .blender import render_view_blender

        return render_view_blender(scene, frame, light=light, spec=spec,
                                   object_pose=object_pose,
                                   focus_distance_mm=focus_distance_mm,
                                   config=blender_config, backend=backend)
    if backend != BACKEND_SOFTWARE:
        raise SynLabError(
            ErrorCode.ENV_CAPABILITY_MISSING,
            f"render backend {backend!r} is not available in this interpreter; use "
            f"{BACKEND_SOFTWARE!r} for the in-process rasteriser or {BACKEND_BLENDER!r} "
            f"for the Blender subprocess worker (which raises instead of substituting the "
            f"rasteriser when Blender is missing)",
            stage="observe.render.render_view",
            evidence_refs=[BLENDER_GAP["detail"]],
        )
    width, height = int(frame.image_size[0]), int(frame.image_size[1])
    factor = max(int(spec.supersample), 1)
    if width * height * factor * factor > spec.max_pixels:
        raise SynLabError(
            ErrorCode.BUDGET_EXCEEDED,
            f"render target {width}x{height} at supersample {factor} exceeds the pixel "
            f"budget {spec.max_pixels}",
            stage="observe.render.render_view",
            measurements={"width": width, "height": height, "supersample": factor},
        )
    posed = scene.transformed(object_pose) if object_pose is not None else scene
    hi_w, hi_h = width * factor, height * factor
    hi_frame = _scaled_frame(frame, factor)
    buffers = _rasterise_buffers(posed, hi_frame, hi_w, hi_h, light, spec)

    hit_hi = np.isfinite(buffers["depth"])
    rgb_hi = buffers["rgb"].copy()
    rgb_hi[~hit_hi] = np.asarray(spec.background_linear, dtype=np.float32)
    rgb = _block_reduce(rgb_hi, factor, mode="mean").astype(np.float32)

    depth_hi = np.where(hit_hi, buffers["depth"], np.nan)[:, :, None]
    all_hit = hit_hi.reshape(height, factor, width, factor).all(axis=(1, 3))
    depth = _block_reduce(depth_hi, factor, mode="min")[:, :, 0].astype(np.float32)
    # A pixel whose supersamples do not all hit the same surface has no single depth.
    depth[~all_hit] = np.nan

    id_map = buffers["id"][::factor, ::factor].copy()
    tag_map = buffers["tag"][::factor, ::factor].copy()
    mixed_id = _disagreement_i(buffers["id"], factor)
    mixed_tag = _disagreement_i(buffers["tag"].astype(np.int32), factor)
    visibility = (~mixed_id).astype(np.uint8) * (id_map >= 0).astype(np.uint8)

    focus = float(frame.working_distance_mm if focus_distance_mm is None
                  else focus_distance_mm)
    f_px = 0.5 * (float(frame.K[0, 0]) + float(frame.K[1, 1]))
    optics = resolve_declared_optics(frame, spec)
    with np.errstate(invalid="ignore"):
        coc = circle_of_confusion_px(depth.astype(np.float64), focus, optics["f_number"],
                                     f_px,
                                     sampling_px_per_mm=optics["sampling_px_per_mm"])
    uncertain = (mixed_id | mixed_tag | (coc > spec.coc_px_threshold)) \
        & (id_map >= 0)
    uncertain |= (~np.isfinite(depth)) & (id_map >= 0)

    mask_semantics = (MASK_SEMANTICS if optics["declared"]
                      else MASK_SEMANTICS_PIXEL_UNITS_V1)
    meta = {
        "backend": backend,
        "backend_class": "CUSTOM_GAP" if backend == BACKEND_SOFTWARE else "ADAPTER",
        "supersample": factor,
        "near_mm": spec.near_mm,
        "far_mm": spec.far_mm,
        "shade": spec.shade,
        "light_direction": np.asarray(light.direction, dtype=np.float64).tolist(),
        "light_color": np.asarray(light.color, dtype=np.float64).tolist(),
        "ambient": np.asarray(light.ambient, dtype=np.float64).tolist(),
        "background_linear": list(spec.background_linear),
        "bg_linear_present": True,
        "depth_semantics": "camera_frame_z_mm",
        "id_map_semantics": "integer face label, -1 = background, never interpolated",
        "mm_per_pixel": float(frame.working_distance_mm / frame.K[0, 0]),
        "object_pose_T_WO": (np.asarray(object_pose).tolist()
                             if object_pose is not None else None),
        "focus_distance_mm": focus,
        "coc_threshold_px": spec.coc_px_threshold,
        "mask_semantics": mask_semantics,
        "coc_optics": {
            "rule": "c_px = D * f_mm^2 / (N * (z - f_mm)) * |z - z_f| / z_f, "
                    "D = f_px / focal_length_mm",
            "f_px": float(f_px),
            "focal_length_mm": float(optics["focal_length_mm"]),
            "f_number": float(optics["f_number"]),
            "sampling_px_per_mm": (None if optics["sampling_px_per_mm"] is None
                                   else float(optics["sampling_px_per_mm"])),
            "declared": bool(optics["declared"]),
            "profile_id": optics["profile_id"],
            "source": dict(optics["source"]),
        },
        "coc_p95_px": float(np.nanpercentile(coc, 95)) if np.isfinite(coc).any() else 0.0,
        "surface_visible_fraction": float(np.mean(id_map >= 0)),
        "uncertain_fraction": float(np.mean(uncertain)),
        "albedo_source_kind": posed.material.source_kind,
        "blender_gap": dict(BLENDER_GAP),
        "n_faces_drawn": int(np.count_nonzero(np.isfinite(buffers["depth"]))),
        "backend_report_ref": "docs/a12/blender_backend.md#software-rasteriser",
    }
    return RenderOutput(
        rgb_linear=rgb,
        depth_z=depth,
        id_map=id_map.astype(np.int32),
        surface_tag=tag_map.astype(np.int16),
        visibility=visibility.astype(np.uint8),
        uncertain_mask=uncertain.astype(bool),
        backend=backend,
        meta=meta,
    )


def _scaled_frame(frame: ViewFrame, factor: int) -> ViewFrame:
    """Supersampled frame: same optics and pose, ``factor`` times the pixel grid."""
    if factor == 1:
        return frame
    K = np.asarray(frame.K, dtype=np.float64).copy() * factor
    K[2, 2] = 1.0
    return ViewFrame(
        view_id=f"{frame.view_id}@{factor}x",
        K=K,
        T_WC=np.asarray(frame.T_WC, dtype=np.float64).copy(),
        image_size=(int(frame.image_size[0]) * factor, int(frame.image_size[1]) * factor),
        profile_id=frame.profile_id,
        tier=frame.tier,
        u_position_mm=frame.u_position_mm,
        working_distance_mm=frame.working_distance_mm,
        focus_setting=frame.focus_setting,
        source_kind=frame.source_kind,
        camera_model=frame.camera_model,
        dist=None if frame.dist is None else np.asarray(frame.dist, dtype=np.float64).copy(),
        meta=dict(frame.meta),
    )


def deployment_mask_from_render(render: RenderOutput, *, erode_px: int = 1) -> np.ndarray:
    """Obtainable foreground mask: rendered object vs background.

    This is the deployable equivalent of a segmentation/background-subtraction mask: it
    uses only the delivered image and its own alpha/background separation, never the
    research ``id_map`` labels.  Uncertain boundary pixels are excluded so the mask is
    conservative, exactly as the sparse-feature mask in plan 14.4 requires.
    """
    mask = ((render.id_map >= 0) & (render.visibility > 0) & (~render.uncertain_mask))
    if erode_px > 0:
        try:
            import cv2

            k = np.ones((2 * int(erode_px) + 1, 2 * int(erode_px) + 1), np.uint8)
            mask = cv2.erode(mask.astype(np.uint8), k, iterations=1).astype(bool)
        except Exception:  # pragma: no cover - cv2 is a hard dependency elsewhere
            for _ in range(int(erode_px)):
                m = mask.copy()
                m[1:, :] &= mask[:-1, :]
                m[:-1, :] &= mask[1:, :]
                m[:, 1:] &= mask[:, :-1]
                m[:, :-1] &= mask[:, 1:]
                mask = m
    return mask.astype(bool)


def write_mask_png(mask: np.ndarray, path: str) -> str:
    """Write a COLMAP-style mask (white = used, black = ignored) as an 8-bit PNG."""
    import cv2

    arr = (np.asarray(mask, dtype=bool).astype(np.uint8)) * 255
    if not cv2.imwrite(str(path), arr):
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, f"failed to write mask {path}",
                          stage="observe.render.write_mask_png")
    return str(path)


__all__ = [
    "BACKEND_SOFTWARE", "BACKEND_BLENDER", "BACKEND_BLENDER_EEVEE", "BLENDER_GAP",
    "CAMERA_MODELS", "MASK_SEMANTICS", "MASK_SEMANTICS_PIXEL_UNITS_V1", "LightSpec",
    "MaterialSpec", "RenderSpec", "Scene",
    "build_scene", "capability_probe", "circle_of_confusion_px",
    "deployment_mask_from_render", "procedural_albedo", "profile_optics", "render_view",
    "resolve_declared_optics", "write_mask_png",
]
