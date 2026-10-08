"""Observation routes: ``ideal_visible``, ``proxy_scan`` and real ``photo_mvs``.

Route boundaries (plan 14.1)
----------------------------
``ideal_visible``
    Visible ray -> z back-projection -> per-fragment fusion on the *renderer* depth and
    the reference camera pose.  Result class ``SENSOR_UPPER_BOUND``: it may not be used to
    claim that a phone-RGB pipeline works.
``proxy_scan``
    Partial observation plus controlled degradation (correlated depth error, holes, frame
    drift, simplification, spurious surfaces) applied to the depth/pose it holds.  Stress
    proxy only.
``photo_mvs``
    RGB plus actually obtained calibration through **pycolmap**.  Ground-truth poses,
    depth and scale are never fed into the reconstruction: the only inputs are the
    delivered images, the deployment mask and the initial intrinsics estimate.  SfM
    failure stops the route with ``STOP_SFM`` and is recorded (never back-filled with
    ideal depth); a missing dense backend yields ``MVS_NOT_AVAILABLE``.

Fixed camera on a turntable
---------------------------
The bench rotates the *object* while the camera is bolted to the slide.  For
``photo_mvs`` the geometric content of such a capture is identical to orbiting the camera
around a fixed object (the relative motion is the same up to a global rigid transform),
and that equivalent formulation is what is handed to COLMAP; no background, support or
scale bar that violates the single-rigid-scene assumption is rendered into those frames.
The masks handed to the feature extractor are the *deployable* foreground masks
(rendered-object vs background), never the research id labels.
"""

from __future__ import annotations

import copy
import json
import math
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..roles import (
    SOURCE_CALIBRATED,
    SOURCE_OBS_EST,
    SOURCE_SENSOR_SIM,
)
from ..schemas.runtime import (
    ORIGIN_AMBIGUOUS,
    ORIGIN_INTERFACE,
    ORIGIN_MOTHER_SURFACE,
    CameraProfile,
    ObservationResult,
    ObsView,
    RenderOutput,
    ViewFrame,
)
from .imaging import ImagingResult, ImagingSpec, apply_imaging_chain
from .quality import OBS_EST_VERSION, estimate_quality
from .render import (
    BACKEND_BLENDER,
    BACKEND_SOFTWARE,
    LightSpec,
    RenderSpec,
    Scene,
    build_scene,
    capability_probe,
    deployment_mask_from_render,
    render_view,
)

ROUTE_IDEAL_VISIBLE = "ideal_visible"
ROUTE_PROXY_SCAN = "proxy_scan"
ROUTE_PHOTO_MVS = "photo_mvs"

#: Route -> (input_profile, evidence class) as declared in plan 14.1 / 30.1.
ROUTE_SPECS: dict[str, dict[str, str]] = {
    ROUTE_IDEAL_VISIBLE: {
        "input_profile": "SENSOR_UPPER_BOUND",
        "evidence_class": "SENSOR_UPPER_BOUND",
        "claim_boundary": "sensor upper bound; cannot support a phone-RGB deployment claim",
    },
    ROUTE_PROXY_SCAN: {
        "input_profile": "SENSOR_PROXY",
        "evidence_class": "STRESS_PROXY",
        "claim_boundary": "stress proxy; needs real calibration before any scan claim",
    },
    ROUTE_PHOTO_MVS: {
        "input_profile": "PHONE_RGB",
        "evidence_class": "REAL_PIPELINE_SYNTHETIC_INPUT",
        "claim_boundary": "real SfM/dense pipeline on synthetic renders; REAL_CAPTURE pending",
    },
}

#: Origin kind -> ``SurfaceTag`` index used by ``MotherGeometry.surface_tag_names``.
ORIGIN_TO_TAG: dict[int, int] = {
    ORIGIN_MOTHER_SURFACE: 0,   # outer_wall
    ORIGIN_INTERFACE: 2,        # rim (the new fracture surface)
    ORIGIN_AMBIGUOUS: 6,        # attachment / ambiguous
}

#: Default 3-layer x 4-azimuth cache (plan 13.1).
DEFAULT_VIEW_COUNT = 12

# --------------------------------------------------------------------------------------
# renderer selection (plan 13.2: the Blender worker is the physical reference backend)
# --------------------------------------------------------------------------------------
#: Values accepted for ``spec.observation.renderer`` / :attr:`ObsSpec.renderer` /
#: ``observe(..., renderer=...)``.  ``auto`` keeps the historical behaviour: the in-process
#: software rasteriser.  Nothing here changes the default of a run that does not ask for
#: Blender: the *request* is the only thing that selects the backend.
RENDERER_AUTO = "auto"
RENDERER_SOFTWARE = "software_rasterizer"
RENDERER_BLENDER = "blender"

#: Declared vocabulary -> backend constant of :mod:`synlab.observe.render`.  An unknown
#: value is refused; there is no implicit "closest match".
RENDERER_TO_BACKEND: dict[str, str] = {
    RENDERER_AUTO: BACKEND_SOFTWARE,
    "auto_software": BACKEND_SOFTWARE,
    RENDERER_SOFTWARE: BACKEND_SOFTWARE,
    "software": BACKEND_SOFTWARE,
    "rasterizer": BACKEND_SOFTWARE,
    RENDERER_BLENDER: BACKEND_BLENDER,
    "blender_cycles": BACKEND_BLENDER,
    "cycles": BACKEND_BLENDER,
}

#: Distortion handling of a Blender frame (the Blender worker renders an ideal pinhole):
#: ``error`` refuses a distorted frame with a structured error (default, unchanged),
#: ``undistort`` renders the *undistorted* pinhole camera (``cv2.undistort`` with the
#: nominal ``K`` as the new camera matrix), ``ignore`` renders the pinhole camera anyway and
#: records the dropped coefficients together with their measured pixel effect.
DISTORTION_POLICY_ERROR = "error"
DISTORTION_POLICY_UNDISTORT = "undistort"
DISTORTION_POLICY_IGNORE = "ignore"
DISTORTION_POLICIES: tuple[str, ...] = (DISTORTION_POLICY_ERROR, DISTORTION_POLICY_UNDISTORT,
                                        DISTORTION_POLICY_IGNORE)

#: Evidence text attached to the structured refusal of a distorted Blender frame.
DISTORTION_REFUSAL_DETAIL = (
    "the Blender worker renders an ideal pinhole camera and cannot represent OpenCV "
    "distortion; render a PINHOLE frame, set distortion_policy='undistort' (render the "
    "undistorted pinhole camera) or distortion_policy='ignore' (render anyway and record "
    "the dropped coefficients).  The software rasteriser handles distortion directly."
)


@dataclass
class ObsSpec:
    """Observation request: view cache, delivered image size and per-route degradations."""

    view_count: int = DEFAULT_VIEW_COUNT
    #: Delivered (post-encoding) image size; derived from the profile frame by a *legal*
    #: resize whose affine and ``K`` are recorded (plan 30.3).  Never a silent crop.
    delivered_size: tuple[int, int] = (512, 384)
    #: Rendering resolution budget.  The pipeline grid is
    #: ``max(delivered pixels, max_render_pixels)`` scaled to the profile aspect ratio, and
    #: the delivered images are produced from it by the *declared* crop+resize step, so the
    #: mm/px of every measurement is recorded rather than implied by a sensor spec.  The
    #: delivered image is never created at a higher resolution than the pipeline grid,
    #: which would fabricate detail.
    max_render_pixels: int = 786_432
    tiers: tuple[str, ...] = ("GLOBAL", "MID", "LOCAL")
    render_spec: RenderSpec = field(default_factory=RenderSpec)
    imaging: ImagingSpec = field(default_factory=ImagingSpec)
    light: LightSpec | None = None
    route_params: dict[str, Any] = field(default_factory=dict)
    workdir: str | None = None
    freeze_label_files: bool = False
    master_seed: int = 20261001
    lineage_id: str = "lineage_default"
    frame_id: str = "S_mm"
    #: Which render backend the view cache uses: ``auto``/``software_rasterizer`` (the
    #: historical default, in-process NumPy rasteriser) or ``blender`` (the portable Blender
    #: Cycles worker, :mod:`synlab.observe.blender`).  Mirrors
    #: ``ObservationConfig.renderer`` of the generation spec; ``auto`` never silently
    #: becomes Blender and a ``blender`` request never silently becomes the rasteriser.
    renderer: str = RENDERER_AUTO
    #: OpenCV-distortion handling of the Blender backend (see
    #: :data:`DISTORTION_POLICIES`).  Ignored by the software rasteriser, which applies the
    #: frame's distortion directly.
    distortion_policy: str = DISTORTION_POLICY_ERROR
    #: Optional :class:`synlab.observe.blender.BlenderBackendConfig` passthrough (samples,
    #: filter width, denoise, work directory, timeout); ``None`` means the adapter default.
    blender_config: Any = None

    def resolved_light(self) -> LightSpec:
        if self.light is not None:
            return self.light
        direction = np.array([-0.35, -0.62, -0.70], dtype=np.float64)
        direction /= np.linalg.norm(direction)
        return LightSpec(direction=direction,
                         color=np.array([2.35, 2.25, 2.10], dtype=np.float64),
                         ambient=np.array([0.30, 0.30, 0.33], dtype=np.float64))

    # -------------------------------------------------------------- geometry of output
    def derivation(self, frame_size: tuple[int, int]
                   ) -> tuple[tuple[int, int], int, int, float, float]:
        """``(render_size, x0, y0, sx, sy)`` for one profile frame size.

        The pipeline grid keeps the frame's aspect ratio and is capped by
        ``max_render_pixels`` (so the rasteriser budget is explicit), and the delivered
        size is reached by a centre crop to the delivered aspect ratio followed by a
        resize.  ``sx``/``sy`` are the realised scales used to build ``K_new = A K``.
        """
        width, height = int(frame_size[0]), int(frame_size[1])
        budget = max(int(self.max_render_pixels),
                     int(self.delivered_size[0]) * int(self.delivered_size[1]))
        scale = min(1.0, math.sqrt(budget / float(max(width * height, 1))))
        render_w = max(int(round(width * scale)), 64)
        render_h = max(int(round(height * scale)), 48)
        dw, dh = int(self.delivered_size[0]), int(self.delivered_size[1])
        aspect = dw / float(dh)
        crop_w = min(render_w, int(round(render_h * aspect)))
        crop_h = min(render_h, int(round(crop_w / aspect)))
        crop_w = max(crop_w, 8)
        crop_h = max(crop_h, 8)
        x0 = max((render_w - crop_w) // 2, 0)
        y0 = max((render_h - crop_h) // 2, 0)
        sx = dw / float(crop_w)
        sy = dh / float(crop_h)
        return (render_w, render_h), x0, y0, sx, sy


# --------------------------------------------------------------------------------------
# target resolution
# --------------------------------------------------------------------------------------
@dataclass
class Target:
    """One residual fragment/component resolved into a renderable target."""

    mother_id: str
    fragment_id: str
    component_id: str
    mesh: Any
    surface_tag: np.ndarray
    face_id: np.ndarray
    face_origin_kind: np.ndarray | None
    source_kind: str
    bbox: np.ndarray
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_faces(self) -> int:
        return int(np.asarray(self.mesh.faces).shape[0])


def resolve_target(physical_or_fragment: Any, fragment_id: str | None = None) -> Target:
    """Resolve a PhysicalResult / Fragment / raw mesh into a renderable :class:`Target`."""
    import trimesh

    obj = physical_or_fragment
    mother_id = str(getattr(obj, "mother_id", "") or "")
    component_id = ""
    face_origin_kind = None
    surface_tag_override = None
    meta: dict[str, Any] = {}

    if hasattr(obj, "components") and hasattr(obj, "representative_map"):
        # PhysicalResult
        components = list(obj.components)
        if not components:
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, "physical result has no components",
                              stage="observe.routes.resolve_target")
        wanted = fragment_id
        chosen = None
        for comp in components:
            if wanted is None or comp.clean_fragment_id == wanted or comp.component_id == wanted:
                chosen = comp
                break
        if chosen is None:
            raise SynLabError(
                ErrorCode.INPUT_UNAVAILABLE,
                f"fragment {wanted!r} is not present in the physical result "
                f"({[c.clean_fragment_id for c in components][:8]}...)",
                stage="observe.routes.resolve_target",
                evidence_refs=[c.component_id for c in components][:8],
            )
        mesh = trimesh.Trimesh(vertices=np.asarray(chosen.mesh.vertices),
                               faces=np.asarray(chosen.mesh.faces), process=False)
        frag_id = str(chosen.clean_fragment_id)
        component_id = str(chosen.component_id)
        meta["physical_version"] = int(getattr(obj, "version", 0))
        meta["lost_volume_ratio"] = float(getattr(obj, "lost_volume_ratio", 0.0))
        meta["status"] = str(getattr(chosen, "status", "CORE"))
    elif hasattr(obj, "fragment_id") and hasattr(obj, "mesh"):
        # Fragment
        mesh = trimesh.Trimesh(vertices=np.asarray(obj.mesh.vertices),
                               faces=np.asarray(obj.mesh.faces), process=False)
        frag_id = str(obj.fragment_id)
        component_id = f"comp_{frag_id}"
        face_origin_kind = np.asarray(getattr(obj, "face_origin_kind", None))
    elif hasattr(obj, "mesh") and hasattr(obj, "face_surface_tag"):
        # MotherGeometry: closed body with the mother's own face-tag vocabulary, which is the
        # vocabulary ``ORIGIN_TO_TAG``/``surface_tag_names`` speaks (0 outer_wall, 2 rim,
        # 6 interface).  A mother has no fracture interface, so tag 2 is its vessel mouth rim
        # there; the tag is *passed through*, never relabelled.
        mesh = trimesh.Trimesh(vertices=np.asarray(obj.mesh.vertices),
                               faces=np.asarray(obj.mesh.faces), process=False)
        tags = np.asarray(obj.face_surface_tag, dtype=np.int32).reshape(-1)
        if tags.shape[0] != int(np.asarray(mesh.faces).shape[0]):
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"mother {getattr(obj, 'mother_id', '')!r}: {tags.shape[0]} face tags for "
                f"{int(np.asarray(mesh.faces).shape[0])} faces",
                stage="observe.routes.resolve_target",
            )
        frag_id = str(getattr(obj, "mother_id", "") or f"{getattr(obj, 'vessel_id', 'mother')}")
        component_id = f"comp_{frag_id}"
        surface_tag_override = tags.astype(np.int16)
        meta.update({
            "input_kind": "mother_geometry",
            "vessel_id": str(getattr(obj, "vessel_id", "")),
            "material_id": str(getattr(obj, "material_id", "")),
            "mother_params": {str(k): _jsonable(v)
                              for k, v in dict(getattr(obj, "params", {}) or {}).items()},
            "surface_tag_source": "MOTHER_FACE_SURFACE_TAG",
            "truth_channels_role": "research_label_only",
        })
    elif hasattr(obj, "vertices") and hasattr(obj, "faces"):
        mesh = trimesh.Trimesh(vertices=np.asarray(obj.vertices),
                               faces=np.asarray(obj.faces), process=False)
        frag_id = str(fragment_id or "fragment_unknown")
        component_id = f"comp_{frag_id}"
        meta["input_kind"] = "raw_mesh"
    elif isinstance(obj, dict) and "mesh" in obj:
        raw = obj["mesh"]
        mesh = trimesh.Trimesh(vertices=np.asarray(raw.vertices),
                               faces=np.asarray(raw.faces), process=False)
        frag_id = str(obj.get("fragment_id", fragment_id or "fragment_unknown"))
        component_id = str(obj.get("component_id", f"comp_{frag_id}"))
        face_origin_kind = np.asarray(obj.get("face_origin_kind")) \
            if obj.get("face_origin_kind") is not None else None
    else:
        raise SynLabError(
            ErrorCode.INPUT_UNAVAILABLE,
            f"cannot resolve a renderable target from {type(obj)!r}; expected "
            f"PhysicalResult, Fragment, trimesh mesh or a mapping with 'mesh'",
            stage="observe.routes.resolve_target",
        )

    n = int(np.asarray(mesh.faces).shape[0])
    if n == 0:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, "target mesh has no faces",
                          stage="observe.routes.resolve_target")
    if surface_tag_override is not None:
        surface_tag = np.asarray(surface_tag_override, dtype=np.int16)
    elif face_origin_kind is not None and face_origin_kind.shape[0] == n:
        surface_tag = np.vectorize(lambda k: ORIGIN_TO_TAG.get(int(k), 6),
                                   otypes=[np.int16])(face_origin_kind)
    else:
        surface_tag = np.zeros(n, dtype=np.int16)
    face_id = np.arange(n, dtype=np.int32)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    if verts.ndim != 2 or verts.shape[1] != 3 or verts.shape[0] == 0:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"target mesh vertices must be (N,3) with N>0, got {tuple(verts.shape)} "
            f"({n} faces); a 2-column vertex array would read column 2 out of bounds",
            stage="observe.routes.resolve_target",
            measurements={"actual_shape": list(verts.shape), "n_faces": int(n)},
        )
    bbox = np.array([verts[:, 0].min(), verts[:, 1].min(), verts[:, 2].min(),
                     verts[:, 0].max(), verts[:, 1].max(), verts[:, 2].max()])
    return Target(
        mother_id=mother_id, fragment_id=frag_id, component_id=component_id,
        mesh=mesh, surface_tag=surface_tag, face_id=face_id,
        face_origin_kind=face_origin_kind, source_kind=SOURCE_SENSOR_SIM,
        bbox=bbox, meta=meta,
    )


# --------------------------------------------------------------------------------------
# rendering + imaging
# --------------------------------------------------------------------------------------
def blender_binary() -> str | None:
    """A usable Blender executable, or ``None`` (delegates to the adapter's discovery)."""
    from .blender import find_blender_binary

    return find_blender_binary()


def resolve_render_backend(renderer: Any = None, *,
                           spec: "ObsSpec | None" = None,
                           verify_available: bool = True) -> str:
    """Resolve the requested renderer onto a backend constant of :mod:`synlab.observe.render`.

    Precedence: an explicit ``renderer`` argument (the ``observe(..., renderer=...)``
    parameter) wins over ``spec.renderer`` (``configs/**.yaml: observation.renderer``); when
    neither is given the historical default :data:`BACKEND_SOFTWARE` is returned, so a caller
    that does not name a renderer keeps exactly the behaviour it had before this parameter
    existed.

    A ``blender`` request is *checked* against the host: when no Blender binary can be found
    the call raises ``ENV_CAPABILITY_MISSING`` with the probe evidence instead of returning
    the software backend (which would relabel a rasterised frame as Blender).
    """
    requested = renderer
    if requested is None and spec is not None:
        requested = getattr(spec, "renderer", None)
    if requested is None:
        return BACKEND_SOFTWARE
    if isinstance(requested, str):
        name = requested.strip()
    else:
        name = str(getattr(requested, "backend", requested)).strip()
    backend = RENDERER_TO_BACKEND.get(name.lower())
    if backend is None:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"unknown renderer {name!r}; expected one of "
            f"{sorted(set(RENDERER_TO_BACKEND))} or a backend constant of "
            f"synlab.observe.render ({BACKEND_SOFTWARE!r}, {BACKEND_BLENDER!r})",
            stage="observe.routes.resolve_render_backend",
            measurements={"requested": name, "known": sorted(set(RENDERER_TO_BACKEND))},
        )
    if backend == BACKEND_BLENDER and verify_available:
        exe = blender_binary()
        if exe is None:
            probe: dict[str, Any] = {}
            try:
                from .blender import selftest

                probe = selftest()
            except Exception as exc:  # noqa: BLE001 - the refusal keeps the probe error
                probe = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
            raise SynLabError(
                ErrorCode.ENV_CAPABILITY_MISSING,
                "renderer='blender' was requested but no Blender binary is available on this "
                "host (BLENDER_BIN / PATH / persisted user env / project third_party portable "
                "build).  The request is refused; it is NOT downgraded to the software "
                "rasteriser and no frame is labelled Blender.",
                stage="observe.routes.resolve_render_backend",
                evidence_refs=[json.dumps(probe, default=str)],
            )
    return backend


def frame_has_distortion(frame: ViewFrame) -> bool:
    """True when the frame carries non-zero OpenCV distortion coefficients."""
    dist = getattr(frame, "dist", None)
    if dist is None:
        return False
    arr = np.asarray(dist, dtype=np.float64).ravel()
    return bool(arr.size and float(np.abs(arr).max()) > 0.0)


def distortion_pixel_effect_px(frame: ViewFrame) -> float | None:
    """Max pixel effect of the frame's distortion over its own image (``None`` when none).

    The coefficients are evaluated at the extreme normalized coordinates the frame can see,
    so the number is the *measured* bound of what dropping them costs, not a claim.
    """
    if not frame_has_distortion(frame):
        return None
    from ..cameras.projection import distort_normalized

    K = np.asarray(frame.K, dtype=np.float64)
    width, height = int(frame.image_size[0]), int(frame.image_size[1])
    xs = (np.array([0.0, width - 1.0, 0.0, width - 1.0, (width - 1.0) / 2.0])
          - K[0, 2]) / K[0, 0]
    ys = (np.array([0.0, 0.0, height - 1.0, height - 1.0, (height - 1.0) / 2.0])
          - K[1, 2]) / K[1, 1]
    xd, yd = distort_normalized(xs, ys, np.asarray(frame.dist, dtype=np.float64),
                               frame.camera_model or "OPENCV")
    du = K[0, 0] * (np.asarray(xd) - xs)
    dv = K[1, 1] * (np.asarray(yd) - ys)
    return float(np.max(np.hypot(du, dv)))


def blender_config_for(spec: ObsSpec, *, frame: ViewFrame | None = None,
                       base: Any = None) -> Any:
    """The :class:`~synlab.observe.blender.BlenderBackendConfig` for one Blender request.

    ``base`` overrides ``spec.blender_config`` (the ``render_views(..., blender_config=...)``
    argument).  Only two knobs are derived here: the distortion policy of the spec and a
    per-view ``run_label`` so the work directories of a 12-view cache are distinguishable.
    """
    import dataclasses

    from .blender import BlenderBackendConfig

    config = base if base is not None else spec.blender_config
    if config is None:
        config = BlenderBackendConfig()
    elif not isinstance(config, BlenderBackendConfig):
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"blender_config must be a BlenderBackendConfig or None, got "
            f"{type(config).__name__}",
            stage="observe.routes.blender_config_for",
        )
    overrides: dict[str, Any] = {}
    if str(spec.distortion_policy or "").lower() == DISTORTION_POLICY_IGNORE:
        overrides["distortion_policy"] = DISTORTION_POLICY_IGNORE
    if frame is not None:
        overrides["run_label"] = f"{spec.lineage_id}_{frame.view_id}"
    return dataclasses.replace(config, **overrides) if overrides else config


def render_frame_for_backend(frame: ViewFrame, *, backend: str, spec: ObsSpec
                             ) -> tuple[ViewFrame, dict[str, Any]]:
    """The frame actually handed to ``render_view`` plus the distortion provenance.

    * software backend: returned unchanged (it applies ``dist`` itself).
    * Blender backend, undistorted frame: returned unchanged.
    * Blender backend, ``distortion_policy='error'``: structured refusal
      (``ENV_CAPABILITY_MISSING``), never a silently dropped coefficient.
    * Blender backend, ``distortion_policy='undistort'``: the *undistorted* pinhole camera.
      ``cv2.undistort`` with the nominal ``K`` as the new camera matrix maps the distorted
      image onto a pinhole image with that same ``K``; rendering the pinhole camera of that
      ``K`` is exactly that image, so the delivered frame declares ``dist=None``.
    * Blender backend, ``distortion_policy='ignore'``: rendered as an ideal pinhole and the
      dropped coefficients (with their measured pixel effect) are recorded.
    """
    policy = str(spec.distortion_policy or DISTORTION_POLICY_ERROR).lower()
    if policy not in DISTORTION_POLICIES:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"unknown distortion_policy {spec.distortion_policy!r}; expected one of "
            f"{list(DISTORTION_POLICIES)}",
            stage="observe.routes.render_frame_for_backend",
        )
    provenance: dict[str, Any] = {"distortion_policy": policy}
    if backend != BACKEND_BLENDER or not frame_has_distortion(frame):
        return frame, provenance
    dist = np.asarray(frame.dist, dtype=np.float64).ravel()
    provenance.update({
        "distortion_coefficients": dist.tolist(),
        "distortion_model": frame.camera_model,
        "distortion_max_pixel_effect_px": distortion_pixel_effect_px(frame),
        "distortion_frame_model": frame.camera_model,
    })
    if policy == DISTORTION_POLICY_ERROR:
        raise SynLabError(
            ErrorCode.ENV_CAPABILITY_MISSING,
            f"view {frame.view_id}: {DISTORTION_REFUSAL_DETAIL}",
            stage="observe.routes.render_frame_for_backend",
            measurements={"view_id": frame.view_id, "model": frame.camera_model,
                          "dist": dist.tolist(),
                          "max_pixel_effect_px": provenance["distortion_max_pixel_effect_px"]},
            evidence_refs=[DISTORTION_REFUSAL_DETAIL],
        )
    if policy == DISTORTION_POLICY_IGNORE:
        provenance["distortion_ignored"] = True
        provenance["distortion_note"] = (
            "coefficients dropped: the Blender render is an ideal pinhole; the delivered "
            "frame keeps the declared distortion and the pixel effect is recorded")
        return frame, provenance
    out = copy.copy(frame)
    out.dist = None
    out.camera_model = "PINHOLE"
    out.meta = dict(frame.meta)
    out.meta["distortion_policy"] = policy
    out.meta["undistorted_from"] = {"camera_model": frame.camera_model,
                                    "dist": dist.tolist()}
    provenance["distortion_undistorted"] = True
    provenance["distortion_note"] = (
        "rendered as the undistorted pinhole camera with the nominal K (equivalent to "
        "cv2.undistort with K as the new camera matrix); the delivered frame declares "
        "dist=None")
    return out, provenance


@dataclass
class ViewBundle:
    frame: ViewFrame
    render_frame: ViewFrame
    render: RenderOutput
    imaging: ImagingResult
    deploy_mask: np.ndarray
    roi: np.ndarray
    object_pose: np.ndarray
    A: np.ndarray
    K: np.ndarray
    #: Backend that produced ``render`` (``SOFTWARE_RASTERIZER`` / ``BLENDER_CYCLES``).
    backend: str = BACKEND_SOFTWARE
    #: Distortion provenance of the Blender request (policy, coefficients, pixel effect).
    distortion: dict[str, Any] = field(default_factory=dict)

    @property
    def render_mm_per_px(self) -> float:
        return float(self.render_frame.working_distance_mm / self.render_frame.K[0, 0])


def render_views(target: Target, profile: CameraProfile, spec: ObsSpec,
                 rng: np.random.Generator, *, backend: str | None = None,
                 blender_config: Any = None) -> list[ViewBundle]:
    """Render the 3 x 4 cache and run the ordered imaging chain for every view.

    ``backend`` selects the render backend explicitly (see
    :func:`resolve_render_backend`); ``None`` falls back to ``spec.renderer``, whose default
    ``auto`` keeps the in-process software rasteriser.  ``blender_config`` overrides
    ``spec.blender_config`` for the Blender path.
    """
    from ..cameras.viewframes import make_view_frames

    resolved = resolve_render_backend(backend, spec=spec)
    requested_config = blender_config if blender_config is not None else spec.blender_config
    scene: Scene = build_scene(target.mesh, surface_tag=target.surface_tag,
                               face_id=target.face_id, name=target.fragment_id)
    frames = make_view_frames(profile, target.bbox, spec.view_count, rng,
                              tiers=spec.tiers, orbit=True)
    light = spec.resolved_light()
    bundles: list[ViewBundle] = []
    for frame in frames:
        render_size, x0, y0, sx, sy = spec.derivation(frame.image_size)
        render_frame = _rescaled_frame(frame, render_size)
        imaging_spec = copy.copy(spec.imaging)
        imaging_spec.crop_origin = (x0, y0)
        imaging_spec.resize_scale = (sx, sy)
        object_pose = None
        pose_json = frame.meta.get("object_pose_T_WO")
        if pose_json is not None:
            object_pose = np.asarray(pose_json, dtype=np.float64)
        # -- backend selection + distortion policy (plan 13.2, R7)
        render_frame, distortion = render_frame_for_backend(render_frame, backend=resolved,
                                                            spec=spec)
        cfg = None
        if resolved == BACKEND_BLENDER:
            cfg = blender_config_for(spec, frame=render_frame, base=requested_config)
        render = render_view(scene, render_frame, light=light, spec=spec.render_spec,
                             object_pose=object_pose,
                             focus_distance_mm=render_frame.working_distance_mm,
                             backend=resolved, blender_config=cfg)
        render_frame.meta = dict(render_frame.meta)
        render_frame.meta.update(distortion)
        cluster = _resize_to(render.uncertain_mask, render_size)
        imaging = apply_imaging_chain(
            render.rgb_linear, K=render_frame.K, dist=render_frame.dist,
            uncertain_mask=cluster, depth_z=render.depth_z,
            focus_distance_mm=render_frame.working_distance_mm, rng=rng,
            spec=imaging_spec, camera_model=render_frame.camera_model or "PINHOLE",
        )
        deploy = _resize_to(deployment_mask_from_render(render), imaging.image.shape[:2])
        roi = _resize_to(_roi_mask_full(render), imaging.image.shape[:2])
        bundles.append(ViewBundle(
            frame=frame, render_frame=render_frame, render=render, imaging=imaging,
            deploy_mask=deploy, roi=roi,
            object_pose=(object_pose if object_pose is not None else np.eye(4)),
            A=imaging.A, K=imaging.K_new, backend=resolved, distortion=distortion,
        ))
    return bundles


def _rescaled_frame(frame: ViewFrame, size: tuple[int, int]) -> ViewFrame:
    """Frame at the rendering resolution: same optics, declared pixel affine."""
    from ..cameras.projection import crop_resize_matrix

    target_w, target_h = int(size[0]), int(size[1])
    src_w, src_h = int(frame.image_size[0]), int(frame.image_size[1])
    if (src_w, src_h) == (target_w, target_h):
        return frame
    sx, sy = target_w / src_w, target_h / src_h
    A = crop_resize_matrix(0.0, 0.0, sx, sy)
    out = copy.copy(frame)
    out.K = A @ np.asarray(frame.K, dtype=np.float64)
    out.image_size = (target_w, target_h)
    out.meta = dict(frame.meta)
    out.meta["render_scale"] = [sx, sy]
    out.meta["render_affine_A"] = A.tolist()
    out.meta["profile_image_size"] = [src_w, src_h]
    return out


def _require_raster(arr: np.ndarray, size: tuple[int, int], *, what: str,
                    size_order: str) -> tuple[int, int]:
    """In-bounds precondition shared by the mask/depth resamplers of this module.

    ``cv2.resize`` refuses an empty source or an empty request with an opaque ``cv2.error``;
    a zero-sized or non-2-D raster is reported here as a structured ``SCHEMA_INVALID`` that
    carries the actual raster size *and* the requested size.  ``size_order`` states the
    convention of the caller (``"hw"`` for :func:`_resize_to`, ``"wh"`` for
    :func:`_resize_int` / :func:`_resample_depth`) so that a swapped argument shows up in the
    error message instead of quietly producing a transposed mask.
    """
    shape = tuple(int(s) for s in np.asarray(arr).shape)
    h, w = (int(size[0]), int(size[1])) if size_order == "hw" else (int(size[1]), int(size[0]))
    if len(shape) != 2 or shape[0] < 1 or shape[1] < 1 or h < 1 or w < 1:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"{what}: cannot resample a raster of shape {shape} to size={list(size)} "
            f"(interpreted as {'h,w' if size_order == 'hw' else 'w,h'})",
            stage="observe.routes._require_raster",
            measurements={"actual_shape": list(shape), "requested_size": [int(size[0]),
                                                                         int(size[1])],
                          "requested_size_order": size_order, "raster_kind": what},
        )
    return h, w


def _resize_to(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Nearest-neighbour resize of a boolean mask.

    ``size`` is ``(h, w)`` for this helper (the historical convention of its call sites:
    ``deployment_mask_from_render(...)`` is resized to ``image.shape[:2]``).  The delivered-grid
    helpers :func:`_resize_int` / :func:`_resample_depth` take ``(w, h)`` instead.  Both
    conventions are named here and in :func:`_require_raster` because a swapped pair cannot be
    recognised from the sizes alone on a square raster - only an empty size is refused.
    """
    import cv2

    h, w = _require_raster(mask, size, what="mask_resize", size_order="hw")
    if mask.shape[0] == h and mask.shape[1] == w:
        return np.asarray(mask, dtype=bool)
    return cv2.resize(np.asarray(mask, dtype=np.uint8), (w, h),
                      interpolation=cv2.INTER_NEAREST).astype(bool)


def _resize_mask(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return _resize_to(mask, size)


def _roi_mask_full(render: RenderOutput) -> np.ndarray:
    """Estimated fracture ROI on the render grid: observed interface faces (HEURISTIC_OBS)."""
    return (render.id_map >= 0) & (render.surface_tag == ORIGIN_TO_TAG[ORIGIN_INTERFACE])


def _frame_for_delivered(view: ViewBundle, spec: ObsSpec) -> ViewFrame:
    """Frame with ``image_size`` and ``K`` of the delivered encoded image."""
    K_new = np.asarray(view.K, dtype=np.float64).copy()
    frame = copy.copy(view.frame)
    frame.K = K_new
    frame.image_size = (int(view.imaging.image.shape[1]), int(view.imaging.image.shape[0]))
    frame.meta = dict(view.frame.meta)
    frame.meta["pixel_affine_A"] = np.asarray(view.A, dtype=np.float64).tolist()
    frame.meta["pipeline_image_size"] = list(view.render.rgb_linear.shape[:2][::-1])
    frame.meta["delivered_image_size"] = list(frame.image_size)
    frame.meta["pixel_convention"] = "opencv_pixel_center_0_0"
    frame.meta["backend"] = render_backend_name(view.backend)
    frame.meta["distortion"] = dict(view.distortion)
    if view.distortion.get("distortion_undistorted"):
        # the delivered image is the *undistorted* pinhole image of the nominal K
        frame.dist = None
        frame.camera_model = "PINHOLE"
    return frame


def render_backend_name(backend: str | None = None) -> str:
    """Backend name recorded in the observation; the default is the historical one."""
    return str(backend or BACKEND_SOFTWARE)


def render_backend_class(backend: str | None = None) -> str:
    """Evidence class of a backend: the rasteriser is a declared ``CUSTOM_GAP``."""
    return "CUSTOM_GAP" if render_backend_name(backend) == BACKEND_SOFTWARE else "ADAPTER"


# --------------------------------------------------------------------------------------
# depth back-projection + fusion
# --------------------------------------------------------------------------------------
def backproject_depth(depth_z: np.ndarray, K: np.ndarray, T_WC: np.ndarray,
                      dist: np.ndarray | None = None, *, model: str = "PINHOLE",
                      depth_scale: float = 1.0, depth_bias_map: np.ndarray | None = None,
                      pose_perturbation: np.ndarray | None = None,
                      stride: int = 1
                      ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Back-project a depth map to world points.

    Returns ``(points_mm, pixel_index, view_direction)``.  The depth map is interpreted as
    **camera-frame z in mm** (plan 4.3): this is checked against analytic planes in the
    renderer tests rather than inferred from a filename.
    """
    from ..cameras.projection import unproject

    depth = np.asarray(depth_z, dtype=np.float64)
    st = max(int(stride), 1)
    h, w = depth.shape
    yy, xx = np.mgrid[0:h:st, 0:w:st]
    d = depth[0:h:st, 0:w:st]
    valid = np.isfinite(d) & (d > 0)
    if not valid.any():
        return (np.zeros((0, 3), dtype=np.float64), np.zeros((0, 2), dtype=np.int64),
                np.zeros((0, 3), dtype=np.float64))
    if depth_bias_map is not None:
        bias = np.asarray(depth_bias_map, dtype=np.float64)
        if bias.ndim != 2 or bias.shape[0] < h or bias.shape[1] < w:
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"depth_bias_map of shape {tuple(bias.shape)} does not cover the depth raster "
                f"of shape ({h}, {w}): every sampled index must exist in both arrays",
                stage="observe.routes.backproject_depth",
                measurements={"actual_size_hw": [h, w],
                              "requested_bias_shape": list(bias.shape)},
            )
        d = d + bias[0:h:st, 0:w:st]
    d = d * float(depth_scale)
    uv = np.stack([xx[valid].astype(np.float64), yy[valid].astype(np.float64)], axis=1)
    z = d[valid]
    T_eff = np.asarray(T_WC, dtype=np.float64) if pose_perturbation is None \
        else np.asarray(T_WC, dtype=np.float64) @ np.asarray(pose_perturbation, dtype=np.float64)
    pts = unproject(uv, z, K, T_eff, dist, model=model)
    pixel_index = np.stack([xx[valid], yy[valid]], axis=1)
    dirs = pts - np.asarray(T_eff, dtype=np.float64)[:3, 3][None, :]
    dirs /= np.maximum(np.linalg.norm(dirs, axis=1, keepdims=True), 1e-12)
    return pts, pixel_index, dirs


def fuse_points(points: np.ndarray, *, voxel_mm: float, origin_tag: np.ndarray | None = None,
                keep: str = "first") -> tuple[np.ndarray, np.ndarray]:
    """Frozen-order voxel fusion (no random draw, no repeated-point density inflation).

    Returns ``(fused_points, source_index)`` where ``source_index`` maps each fused point
    back to the input index it came from, so view/pixel provenance survives.
    ``keep='first'`` keeps the lowest input index per voxel (deterministic); ``keep='last'``
    keeps the highest.
    """
    pts = np.asarray(points, dtype=np.float64)
    n = pts.shape[0]
    if n == 0:
        return pts, np.zeros(0, dtype=np.int64)
    voxel = max(float(voxel_mm), 1e-9)
    keys = np.floor(pts / voxel).astype(np.int64)
    if origin_tag is not None:
        keys = np.concatenate([keys, np.asarray(origin_tag, dtype=np.int64)[:, None]], axis=1)
    if keep == "first":
        order = np.arange(n)
    else:
        order = np.arange(n)[::-1]
    _, first_idx = np.unique(keys[order], axis=0, return_index=True)
    chosen = order[np.sort(first_idx)]
    return pts[chosen], chosen


def estimate_normals_open3d(points: np.ndarray, *, k: int = 16,
                            orient_towards: np.ndarray | None = None
                            ) -> tuple[np.ndarray, np.ndarray]:
    """Normals from Open3D's KD-tree/hybrid search.  Validity is reported honestly."""
    n = int(np.asarray(points).shape[0])
    normals = np.zeros((n, 3), dtype=np.float32)
    valid = np.zeros(n, dtype=bool)
    if n < 3:
        return normals, valid
    try:
        import open3d as o3d

        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(np.asarray(points, dtype=np.float64))
        pcd.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamKNN(knn=int(min(k, n))))
        est = np.asarray(pcd.normals, dtype=np.float64)
        norms = np.linalg.norm(est, axis=1)
        ok = norms > 1e-12
        est[ok] /= norms[ok, None]
        if orient_towards is not None and np.asarray(orient_towards).shape == est.shape:
            ref = np.asarray(orient_towards, dtype=np.float64)
            flip = np.einsum("ij,ij->i", est, ref) < 0.0
            est[flip] *= -1.0
        normals[:] = est.astype(np.float32)
        valid[:] = ok
    except Exception:  # noqa: BLE001 - optional backend; validity stays False
        pass
    return normals, valid


def _default_stride(frame: ViewFrame, long_edge_target: int = 512) -> int:
    """Sampling stride on the render grid so the fused cloud stays a bounded budget."""
    long_edge = max(int(frame.image_size[0]), int(frame.image_size[1]))
    return max(int(round(long_edge / float(max(long_edge_target, 1)))), 1)


def _voxel_of(points: np.ndarray, voxel_mm: float) -> np.ndarray:
    return np.floor(np.asarray(points, dtype=np.float64) / max(voxel_mm, 1e-9)).astype(np.int64)


# --------------------------------------------------------------------------------------
# route: ideal_visible
# --------------------------------------------------------------------------------------
def route_ideal_visible(target: Target, profile: CameraProfile, spec: ObsSpec,
                        rng: np.random.Generator, *,
                        backend: str | None = None) -> tuple[ObservationResult, list[ViewBundle]]:
    bundles = render_views(target, profile, spec, rng, backend=backend)
    params = dict(spec.route_params or {})
    voxel = float(params.get("voxel_mm", 0.0)) or max(
        bundles[0].render_mm_per_px * 2.0 if bundles else 0.5, 0.05)
    all_pts: list[np.ndarray] = []
    all_dirs: list[np.ndarray] = []
    proven_view: list[np.ndarray] = []
    proven_pix: list[np.ndarray] = []
    for vi, bundle in enumerate(bundles):
        rf = bundle.render_frame
        stride = int(params.get("stride", 0)) or _default_stride(rf)
        pts, pix, dirs = backproject_depth(
            bundle.render.depth_z, rf.K, rf.T_WC, rf.dist,
            model=rf.camera_model or "PINHOLE", stride=stride)
        all_pts.append(pts)
        all_dirs.append(dirs)
        proven_view.append(np.full(pts.shape[0], vi, dtype=np.int32))
        proven_pix.append(pix.astype(np.int32))
    if all_pts:
        points = np.concatenate(all_pts, axis=0)
        dirs = np.concatenate(all_dirs, axis=0)
        view_of = np.concatenate(proven_view, axis=0)
        pix_of = np.concatenate(proven_pix, axis=0)
        points, src = fuse_points(points, voxel_mm=voxel, keep=str(params.get("keep", "first")))
        dirs, view_of, pix_of = dirs[src], view_of[src], pix_of[src]
    else:
        points = np.zeros((0, 3), dtype=np.float64)
        dirs = np.zeros((0, 3), dtype=np.float64)
        view_of = np.zeros(0, dtype=np.int32)
        pix_of = np.zeros((0, 2), dtype=np.int32)
    normals, nvalid = estimate_normals_open3d(points, k=int(params.get("normal_k", 16)),
                                              orient_towards=dirs)
    obs = _assemble_result(
        target=target, route=ROUTE_IDEAL_VISIBLE, spec=spec, bundles=bundles,
        points=points, normals=normals, point_valid=np.ones(points.shape[0], dtype=bool),
        normal_valid=nvalid, scale_valid=True,        # renderer depth is in mm by construction
        fused_mesh=None,
        backend_report={
            "route": ROUTE_IDEAL_VISIBLE,
            "evidence_class": ROUTE_SPECS[ROUTE_IDEAL_VISIBLE]["evidence_class"],
            "claim_boundary": ROUTE_SPECS[ROUTE_IDEAL_VISIBLE]["claim_boundary"],
            "renderer_backend": render_backend_name(bundles[0].backend if bundles else None),
            "renderer_requested": str(spec.renderer),
            "renderer_class": render_backend_class(bundles[0].backend if bundles else None),
            "distortion_policy": str(spec.distortion_policy),
            "depth_source": "RENDERER_EXACT_DEPTH_Z",
            "pose_source": "REFERENCE_VIEW_FRAME",
            "voxel_mm": voxel,
            "fusion": "deterministic_voxel_first_index",
            "depth_semantics": "camera_frame_z_mm",
            "scale_source_kind": SOURCE_SENSOR_SIM,
            "gt_used_in_geometry": False,
            "backprojection_stride": int(params.get("stride", 0)) or
            (_default_stride(bundles[0].render_frame) if bundles else 1),
            "render_mm_per_pixel": bundles[0].render_mm_per_px if bundles else None,
            "delivered_mm_per_pixel": (bundles[0].K[0, 0] and
                                       bundles[0].render_frame.working_distance_mm /
                                       bundles[0].K[0, 0]) if bundles else None,
        },
        extra_meta={"n_provenance": int(view_of.shape[0]),
                    "provenance_view_histogram":
                        np.bincount(view_of, minlength=len(bundles)).tolist()
                        if view_of.size else [],
                    "provenance_head": [(int(v), int(p[0]), int(p[1]))
                                        for v, p in list(zip(view_of, pix_of))[:5]],
                    "renderer_backend": render_backend_name(
                        bundles[0].backend if bundles else None),
                    "renderer_requested": str(spec.renderer),
                    "renderer_class": render_backend_class(
                        bundles[0].backend if bundles else None),
                    "distortion_policy": str(spec.distortion_policy)},
    )
    return obs, bundles


# --------------------------------------------------------------------------------------
# route: proxy_scan
# --------------------------------------------------------------------------------------
def route_proxy_scan(target: Target, profile: CameraProfile, spec: ObsSpec,
                     rng: np.random.Generator, *,
                     backend: str | None = None) -> tuple[ObservationResult, list[ViewBundle]]:
    """Partial observation + controlled degradation of the depth/pose it holds (plan 14.2).

    Degradations are applied to the *depth-view* route only: correlated low-frequency depth
    error, sparse nesting, connected holes, per-view SE(3) drift and a calibration fault
    are all applied before fusion, and normals/curvature/validity are re-estimated
    afterwards.
    """
    bundles = render_views(target, profile, spec, rng, backend=backend)
    params = dict(spec.route_params or {})
    depth_sigma = float(params.get("depth_error_sigma_mm", 0.35))
    depth_corr_mm = float(params.get("depth_error_correlation_mm", 8.0))
    inclination_scale = float(params.get("depth_inclination_scale", 0.5))
    outlier_prob = float(params.get("depth_outlier_prob", 0.002))
    drift_sigma_mm = float(params.get("drift_translation_sigma_mm", 0.12))
    drift_rot_deg = float(params.get("drift_rotation_sigma_deg", 0.06))
    calib_scale = float(params.get("calib_focal_scale", 1.0))
    calib_dist_scale = float(params.get("calib_dist_scale", 1.0))
    sparse_keep = float(params.get("sparse_keep", 0.35))
    hole_count = int(params.get("hole_count", 2))
    voxel = float(params.get("voxel_mm", 0.0)) or max(
        bundles[0].render_mm_per_px * 2.0 if bundles else 0.5, 0.05)

    all_pts, all_dirs, all_pix, all_view = [], [], [], []
    drift_log: list[dict[str, float]] = []
    holes_clipped: list[dict[str, Any]] = []
    for vi, bundle in enumerate(bundles):
        rf = bundle.render_frame
        depth = np.asarray(bundle.render.depth_z, dtype=np.float64).copy()
        valid = np.isfinite(depth) & (depth > 0)
        # -- low-frequency correlated depth error field (not i.i.d. noise)
        field = _correlated_field(depth.shape, sigma_mm=depth_sigma,
                                  correlation_mm=depth_corr_mm,
                                  pixel_pitch_mm=bundle.render_mm_per_px)
        depth = depth + field
        # -- variance grows with distance (a proxy for the incidence-angle term, whose
        #    true dependence needs a depth normal we do not have at this stage)
        if valid.any():
            med = float(np.median(depth[valid]))
            depth = depth * (1.0 + inclination_scale * 1e-3 *
                             np.clip((depth - med) / max(med, 1e-9), -1, 1))
        # -- fixed outlier probability
        if outlier_prob > 0:
            out = rng.random(depth.shape) < outlier_prob
            depth[out & valid] += rng.normal(scale=5.0 * max(depth_sigma, 0.1),
                                             size=int(np.count_nonzero(out & valid)))
        # -- connected holes in the depth map (a disc that touches the raster edge is carved as
        #    ``disc ∩ raster`` and reported, see ``_carve_holes``)
        view_clip: list[dict[str, Any]] = []
        depth = _carve_holes(depth, hole_count, rng, min_radius_px=3, max_radius_px=7,
                             clip_report=view_clip)
        holes_clipped.extend({"view": int(vi), **entry} for entry in view_clip)
        # -- calibration fault: perturbed K/dist used for the back-projection
        K_fault = np.asarray(rf.K, dtype=np.float64).copy()
        K_fault[0, 0] *= calib_scale
        K_fault[1, 1] *= calib_scale
        dist_fault = None if rf.dist is None else \
            np.asarray(rf.dist, dtype=np.float64) * calib_dist_scale
        # -- per-view SE(3) registration drift
        pert = _se3_perturbation(rng, drift_sigma_mm, drift_rot_deg)
        stride = int(params.get("stride", 0)) or _default_stride(rf)
        pts, pix, dirs = backproject_depth(
            depth, K_fault, rf.T_WC, dist_fault,
            model=rf.camera_model or "PINHOLE", pose_perturbation=pert, stride=stride)
        drift_log.append({"view": float(vi),
                          "t_norm_mm": float(np.linalg.norm(pert[:3, 3])),
                          "r_deg": float(np.degrees(np.arccos(
                              np.clip((np.trace(pert[:3, :3]) - 1.0) / 2.0, -1.0, 1.0))))})
        all_pts.append(pts)
        all_dirs.append(dirs)
        all_pix.append(pix)
        all_view.append(np.full(pts.shape[0], vi, dtype=np.int32))
    points = np.concatenate(all_pts, axis=0) if all_pts else np.zeros((0, 3))
    dirs = np.concatenate(all_dirs, axis=0) if all_dirs else np.zeros((0, 3))
    view_of = np.concatenate(all_view, axis=0) if all_view else np.zeros(0, dtype=np.int32)
    if points.shape[0]:
        points, src = fuse_points(points, voxel_mm=voxel, keep="first")
        dirs, view_of = dirs[src], view_of[src]
    # -- G02 sparse: frozen per-point priority, nested prefixes per level
    priority = np.random.Generator(np.random.PCG64(np.uint64(spec.master_seed))).permutation(
        points.shape[0])
    if sparse_keep < 1.0 and points.shape[0]:
        n_keep = max(int(round(points.shape[0] * sparse_keep)), 1)
        keep_idx = np.sort(priority[:n_keep])
        points, dirs, view_of = points[keep_idx], dirs[keep_idx], view_of[keep_idx]
    normals, nvalid = estimate_normals_open3d(points, k=int(params.get("normal_k", 16)),
                                              orient_towards=dirs)
    # -- report the actual per-view cover rather than the plan
    obs = _assemble_result(
        target=target, route=ROUTE_PROXY_SCAN, spec=spec, bundles=bundles,
        points=points, normals=normals, point_valid=np.ones(points.shape[0], dtype=bool),
        normal_valid=nvalid, scale_valid=True, fused_mesh=None,
        backend_report={
            "route": ROUTE_PROXY_SCAN,
            "evidence_class": ROUTE_SPECS[ROUTE_PROXY_SCAN]["evidence_class"],
            "claim_boundary": ROUTE_SPECS[ROUTE_PROXY_SCAN]["claim_boundary"],
            "degradations": {
                "G01_depth_error": {"sigma_mm": depth_sigma,
                                    "correlation_mm": depth_corr_mm,
                                    "correlation_length_px": depth_corr_mm /
                                    max(bundles[0].render_mm_per_px if bundles else 1.0, 1e-9),
                                    "inclination_scale": inclination_scale,
                                    "outlier_prob": outlier_prob},
                "G02_sparse": {"keep_fraction": sparse_keep,
                               "priority": "frozen_permutation_nested_prefix"},
                "G03_holes": {"requested": hole_count, "radius_px": [3, 7],
                              "clip_rule": HOLE_CLIP_RULE,
                              "clipped_count": len(holes_clipped),
                              "clipped": holes_clipped[:24]},
                "G04_drift": {"sigma_translation_mm": drift_sigma_mm,
                              "sigma_rotation_deg": drift_rot_deg,
                              "per_view": drift_log[:6]},
                "G07_calibration": {"focal_scale": calib_scale,
                                    "dist_scale": calib_dist_scale},
            },
            "fusion": "deterministic_voxel_first_index",
            "depth_semantics": "camera_frame_z_mm_at_fusion_reference",
            "normals_reestimated": True,
            "pose_source": "DRIFTED_REFERENCE_VIEW_FRAME",
            "gt_used_in_geometry": False,
        },
        extra_meta={"n_views": len(bundles), "provenance_view_histogram":
                    np.bincount(view_of, minlength=len(bundles)).tolist()
                    if points.shape[0] else []},
    )
    return obs, bundles


def _correlated_field(shape: tuple[int, int], *, sigma_mm: float, correlation_mm: float,
                      pixel_pitch_mm: float) -> np.ndarray:
    """Low-frequency correlated error field with a frozen spectral shape.

    The field is a real Gaussian random field whose correlation length is expressed in mm
   : a white field at the pixel grid is low-pass filtered with the equivalent Gaussian.
    Per-point i.i.d. noise is explicitly not used (plan 14.2).
    """
    import cv2

    h, w = int(shape[0]), int(shape[1])
    if sigma_mm <= 0:
        return np.zeros((h, w), dtype=np.float64)
    sigma_px = max(correlation_mm / max(pixel_pitch_mm, 1e-9), 0.5)
    rng = np.random.default_rng(0)  # deterministic filter construction
    white = rng.standard_normal((h, w))
    smooth = cv2.GaussianBlur(white, (0, 0), sigmaX=sigma_px, sigmaY=sigma_px,
                              borderType=cv2.BORDER_REFLECT101)
    std = float(smooth.std())
    if std < 1e-12:
        return np.zeros((h, w), dtype=np.float64)
    return (smooth / std) * float(sigma_mm)


#: Rule applied when a requested hole disc does not fit inside the raster: the carved region is
#: ``disc ∩ raster`` (recorded per hole in the ``G03_holes`` degradation report).
HOLE_CLIP_RULE = "disc_intersect_raster"


def _carve_holes(depth: np.ndarray, count: int, rng: np.random.Generator,
                 *, min_radius_px: int, max_radius_px: int,
                 clip_report: list[dict[str, Any]] | None = None) -> np.ndarray:
    """Delete connected image regions (plan 14.2 G03) and keep the local cover信息.

    Boundary rule (defect fix; see ``docs/a12/observe_evidence.md``)
    ---------------------------------------------------------------
    A hole is the intersection of the requested disc with the **raster**: ``disc ∩ raster``.
    The centre is always a pixel of the map, so for a non-empty raster that intersection is
    never empty; pixels outside the raster do not exist and are therefore neither written nor
    invented.  Clipping is never silent: with ``clip_report`` given, every disc whose bounding
    box leaves the raster appends ``{rule, centre_yx, radius_px, raster_size_hw,
    requested_bbox_yxhw, written_bbox_yxhw, disc_pixels, carved_pixels, out_of_raster_pixels}``,
    and :func:`route_proxy_scan` records those entries in its ``G03_holes`` degradation report.

    The draw order of ``rng`` is unchanged and the disc test keeps absolute pixel coordinates,
    so for every disc that lies fully inside the raster the produced mask is bit-identical to
    the historical implementation; only requests that used to raise ``IndexError``
    (``x0 + r > w - 1`` or ``y0 + r > h - 1``) now carve their in-raster part instead of
    aborting the whole lineage.

    Structurally unusable requests raise a structured :class:`SynLabError` (never a bare
    ``IndexError``/``ValueError``): a non-2-D raster, a non-floating raster (the deletion is
    expressed as ``NaN``), an empty raster, and a radius range that is not a pixel radius
    (``min < 0`` or ``max < min``; the historical code silently carved nothing for a negative
    radius).  Every rejection reports the actual raster and the requested geometry.
    """
    if count <= 0:
        # no holes requested: identity, exactly as before (no validation, no copy, no draw)
        return depth
    arr = np.asarray(depth)
    requested = {"requested_hole_count": int(count),
                 "requested_radius_px": [int(min_radius_px), int(max_radius_px)]}
    if arr.ndim != 2:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"hole carving needs a 2-D depth raster, got shape {tuple(arr.shape)}",
            stage="observe.routes._carve_holes",
            measurements={"actual_shape": list(arr.shape), **requested},
        )
    if not np.issubdtype(arr.dtype, np.floating):
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"hole carving marks pixels invalid with NaN, which dtype {arr.dtype} cannot "
            f"represent; deliver the depth raster as float",
            stage="observe.routes._carve_holes",
            measurements={"actual_dtype": str(arr.dtype),
                          "actual_size_hw": [int(arr.shape[0]), int(arr.shape[1])], **requested},
        )
    if int(min_radius_px) < 0 or int(max_radius_px) < int(min_radius_px):
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"radius range [{int(min_radius_px)}, {int(max_radius_px)}] is not a pixel radius "
            f"(needs 0 <= min_radius_px <= max_radius_px)",
            stage="observe.routes._carve_holes",
            measurements={"actual_size_hw": [int(arr.shape[0]), int(arr.shape[1])], **requested},
        )
    out = depth.copy()
    h, w = int(out.shape[0]), int(out.shape[1])
    if h == 0 or w == 0:
        raise SynLabError(
            ErrorCode.TARGET_INFEASIBLE,
            f"cannot carve {int(count)} hole(s) of radius "
            f"[{int(min_radius_px)}, {int(max_radius_px)}] px into an empty raster {h}x{w}: "
            f"no pixel can hold a disc",
            stage="observe.routes._carve_holes",
            measurements={"actual_size_hw": [h, w], **requested},
        )
    valid = np.isfinite(out) & (out > 0)
    if not valid.any():
        return out
    ys, xs = np.nonzero(valid)
    for _ in range(int(count)):
        k = int(rng.integers(0, ys.size))
        r = int(rng.integers(int(min_radius_px), int(max_radius_px) + 1))
        y0, x0 = int(ys[k]), int(xs[k])
        # -- the *written window* is clipped to the raster; the disc test keeps absolute pixel
        #    coordinates, so an in-raster pixel keeps exactly the verdict it had before.
        y_lo, y_hi = max(y0 - r, 0), min(y0 + r + 1, h)
        x_lo, x_hi = max(x0 - r, 0), min(x0 + r + 1, w)
        yy, xx = np.mgrid[y_lo:y_hi, x_lo:x_hi]
        disc = (yy - y0) ** 2 + (xx - x0) ** 2 <= r * r
        out[yy[disc], xx[disc]] = np.nan
        if clip_report is not None and (y_lo > y0 - r or x_lo > x0 - r
                                        or y_hi < y0 + r + 1 or x_hi < x0 + r + 1):
            fy, fx = np.mgrid[y0 - r:y0 + r + 1, x0 - r:x0 + r + 1]
            full = (fy - y0) ** 2 + (fx - x0) ** 2 <= r * r
            clip_report.append({
                "rule": HOLE_CLIP_RULE,
                "centre_yx": [y0, x0],
                "radius_px": r,
                "raster_size_hw": [h, w],
                "requested_bbox_yxhw": [y0 - r, x0 - r, 2 * r + 1, 2 * r + 1],
                "written_bbox_yxhw": [y_lo, x_lo, y_hi - y_lo, x_hi - x_lo],
                "disc_pixels": int(full.sum()),
                "carved_pixels": int(disc.sum()),
                "out_of_raster_pixels": int(full.sum()) - int(disc.sum()),
            })
    return out


def _se3_perturbation(rng: np.random.Generator, sigma_mm: float,
                      sigma_rot_deg: float) -> np.ndarray:
    from ..cameras.viewframes import quaternion_matrix, sample_so3_quaternion

    q = sample_so3_quaternion(rng)
    R = quaternion_matrix(q)
    # scale the rotation angle to sigma_rot_deg (the sampled axis is Haar-uniform)
    angle = float(np.degrees(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))))
    if angle > 1e-9:
        from ..cameras.viewframes import rotation_about_axis

        axis = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
        axis /= max(float(np.linalg.norm(axis)), 1e-12)
        R = rotation_about_axis(axis, np.deg2rad(float(rng.normal(scale=sigma_rot_deg))))
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R
    T[:3, 3] = rng.normal(scale=sigma_mm, size=3)
    return T


# --------------------------------------------------------------------------------------
# assembling the result
# --------------------------------------------------------------------------------------
def _obs_views(bundles: list[ViewBundle], spec: ObsSpec) -> list[ObsView]:
    """Per-view observation at the **delivered** pixel grid.

    Every per-pixel channel is on the delivered grid so that no measurement quietly uses a
    finer grid than the picture that was actually encoded.  Integer research channels use
    nearest-neighbour resampling only (a class label is never interpolated); the
    continuous renderer depth is resampled linearly and records its own ``A``.
    """
    import cv2

    views: list[ObsView] = []
    for bundle in bundles:
        frame = _frame_for_delivered(bundle, spec)
        imaging = bundle.imaging
        size = (int(imaging.image.shape[1]), int(imaging.image.shape[0]))
        depth_render = np.asarray(bundle.render.depth_z, dtype=np.float32)
        depth_delivered = _resample_depth(depth_render, size)
        views.append(ObsView(
            view_id=bundle.frame.view_id,
            frame=frame,
            rgb=np.asarray(imaging.image, dtype=np.uint8),
            rgb_linear=np.asarray(imaging.linear, dtype=np.float32),
            depth_z=depth_delivered,
            id_map=_resize_int(bundle.render.id_map, size, fill=-1),
            surface_tag=_resize_int(bundle.render.surface_tag, size, fill=-1),
            deployment_mask=np.asarray(bundle.deploy_mask, dtype=bool),
            roi=np.asarray(bundle.roi, dtype=bool),
            uncertain_mask=np.asarray(imaging.uncertain_mask, dtype=bool),
            quality={},
            source_kind=SOURCE_SENSOR_SIM,
            meta={
                "render_backend": render_backend_name(bundle.backend),
                "render_backend_class": render_backend_class(bundle.backend),
                "render_backend_requested": str(spec.renderer),
                "distortion": dict(bundle.distortion),
                "view_meta": dict(bundle.frame.meta),
                "render_grid": {"size": list(bundle.render_frame.image_size),
                                "mm_per_pixel": bundle.render_mm_per_px,
                                "K": np.asarray(bundle.render_frame.K).tolist()},
                "delivered_grid": {"size": list(size),
                                   "mm_per_pixel": float(bundle.render_frame.working_distance_mm
                                                         / bundle.K[0, 0])},
                "deployment_mask_source": "RENDERED_FOREGROUND_ESTIMATE",
                "roi_source": "HEURISTIC_OBS",
                "id_map_resampling": "nearest_no_interpolation",
                "depth_resampling": "linear_then_invalid_propagated",
                "imaging_labels": list(imaging.labels),
                "imaging_stages": copy.deepcopy(imaging.stages),
                "pixel_convention": "opencv_pixel_center_0_0",
            },
        ))
    return views


def _resize_int(arr: np.ndarray, size: tuple[int, int], *, fill: int) -> np.ndarray:
    """Nearest-neighbour resampling of an integer label map (never interpolated).

    ``size`` is ``(w, h)`` here (the delivered grid of the observation).  ``fill`` is kept for
    call-site compatibility and is **unused**: nearest-neighbour resampling only ever returns
    labels that exist in the source, so no out-of-range label can be invented.
    """
    import cv2

    src = np.asarray(arr)
    h, w = _require_raster(src, size, what="label_resize", size_order="wh")
    if src.shape[0] == h and src.shape[1] == w:
        return src.astype(np.int32 if src.dtype != np.int16 else np.int16, copy=True)
    out = cv2.resize(src.astype(np.int32), (w, h), interpolation=cv2.INTER_NEAREST)
    if src.dtype == np.int16:
        out = out.astype(np.int16)
    return out


def _resample_depth(depth: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Linear depth resampling; an invalid (NaN) depth never becomes a finite value.

    ``size`` is ``(w, h)`` here (the delivered grid of the observation).
    """
    import cv2

    src = np.asarray(depth, dtype=np.float32)
    h, w = _require_raster(src, size, what="depth_resample", size_order="wh")
    if src.shape[0] == h and src.shape[1] == w:
        return src.copy()
    valid = np.isfinite(src) & (src > 0)
    filled = np.where(valid, src, 0.0).astype(np.float32)
    res = cv2.resize(filled, (w, h), interpolation=cv2.INTER_LINEAR)
    res_valid = cv2.resize(valid.astype(np.uint8), (w, h),
                           interpolation=cv2.INTER_NEAREST).astype(bool)
    out = np.where(res_valid, res, np.nan).astype(np.float32)
    return out


def _assemble_result(*, target: Target, route: str, spec: ObsSpec, bundles: list[ViewBundle],
                     points: np.ndarray, normals: np.ndarray, point_valid: np.ndarray,
                     normal_valid: np.ndarray, scale_valid: bool, fused_mesh: Any,
                     backend_report: dict[str, Any],
                     extra_meta: dict[str, Any] | None = None,
                     force_route: str | None = None) -> ObservationResult:
    views = _obs_views(bundles, spec)
    route_name = force_route or route
    result = ObservationResult(
        mother_id=target.mother_id,
        fragment_id=target.fragment_id,
        component_id=target.component_id,
        route=route_name,
        input_profile=ROUTE_SPECS[route]["input_profile"] if route in ROUTE_SPECS else "PHONE_RGB",
        observation_id="",
        views=views,
        points=np.asarray(points, dtype=np.float32).reshape(-1, 3),
        normals=np.asarray(normals, dtype=np.float32).reshape(-1, 3),
        point_valid=np.asarray(point_valid, dtype=bool),
        normal_valid=np.asarray(normal_valid, dtype=bool),
        scale_valid=bool(scale_valid),
        frame_id=spec.frame_id,
        quality={},
        fused_mesh=fused_mesh,
        spurious_mask=None,
        backend_report=dict(backend_report),
        meta={
            "obs_spec": {
                "view_count": int(spec.view_count),
                "delivered_size": list(spec.delivered_size),
                "tiers": list(spec.tiers),
                "master_seed": int(spec.master_seed),
                "lineage_id": spec.lineage_id,
                "imaging_identity": bool(spec.imaging.is_identity()),
                "freeze_label_files": bool(spec.freeze_label_files),
                "renderer_requested": str(spec.renderer),
                "distortion_policy": str(spec.distortion_policy),
            },
            "renderer": render_backend_name(bundles[0].backend if bundles else None),
            "renderer_requested": str(spec.renderer),
            "renderer_class": render_backend_class(bundles[0].backend if bundles else None),
            "distortion_policy": str(spec.distortion_policy),
            "target_meta": dict(target.meta),
            "surface_tag_names": {"0": "outer_wall", "2": "rim", "6": "attachment"},
            "pixel_convention": "opencv_pixel_center_0_0",
            "colmap_pixel_convention": "top_left_corner_0.5",
            "label_files_present": bool(spec.freeze_label_files),
            **(extra_meta or {}),
        },
    )
    result.quality = estimate_quality(result)
    result.observation_id = _observation_id(result)
    return result


def _observation_id(obs: ObservationResult) -> str:
    from ..canonical import hash_json

    payload = {
        "fragment": obs.fragment_id,
        "component": obs.component_id,
        "route": obs.route,
        "profile": obs.views[0].frame.profile_id if obs.views else "",
        "n_views": len(obs.views),
        "n_points": int(obs.points.shape[0]),
        "depth_semantics": "camera_frame_z_mm",
        "inputs": [view.frame.meta.get("pixel_affine_A") for view in obs.views][:4],
    }
    return "obs_" + hash_json(payload).split(":", 1)[-1][:20]


# --------------------------------------------------------------------------------------
# route: photo_mvs (real pycolmap)
# --------------------------------------------------------------------------------------
#: Release gate names that this route cannot satisfy in this environment.
MVS_GATE_NAME = "mvs_subset_real_run"


@dataclass
class PhotoMvsConfig:
    workdir: str
    min_registered_images: int = 4
    camera_model: str = "SIMPLE_RADIAL"
    max_image_size: int = 1024
    max_num_features: int = 4096
    use_mask: bool = True
    run_undistort: bool = True
    dense_backend: str = "SPARSE_DEPTH_PRIOR"
    keep_workdir: bool = True


def _colmap_help(argv: list[str], status: str = "NOT_RUN") -> dict[str, Any]:
    return {"argv": argv, "status": status, "returncode": None, "stdout_tail": "",
            "stderr_tail": "", "seconds": 0.0}


def route_photo_mvs(target: Target, profile: CameraProfile, spec: ObsSpec,
                    rng: np.random.Generator, *, backend: str | None = None
                    ) -> tuple[ObservationResult, list[ViewBundle], dict[str, Any]]:
    """Run real pycolmap SfM on the rendered RGB (+ deployable mask), then dense.

    Returns ``(result, bundles, report)``.  The report always contains the capability
    probe, the full argv log and the failure denominator.
    """
    params = dict(spec.route_params or {})
    workdir = Path(params.get("workdir") or spec.workdir or "data/a12/observe/_photo_mvs")
    cfg = PhotoMvsConfig(
        workdir=str(workdir),
        min_registered_images=int(params.get("min_registered_images", 4)),
        camera_model=str(params.get("camera_model", "SIMPLE_RADIAL")),
        max_image_size=int(params.get("max_image_size", 1024)),
        max_num_features=int(params.get("max_num_features", 4096)),
        use_mask=bool(params.get("use_mask", True)),
        run_undistort=bool(params.get("run_undistort", True)),
        dense_backend=str(params.get("dense_backend", "SPARSE_DEPTH_PRIOR")),
        keep_workdir=bool(params.get("keep_workdir", True)),
    )
    bundles = render_views(target, profile, spec, rng, backend=backend)
    report: dict[str, Any] = {
        "route": ROUTE_PHOTO_MVS,
        "evidence_class": ROUTE_SPECS[ROUTE_PHOTO_MVS]["evidence_class"],
        "claim_boundary": ROUTE_SPECS[ROUTE_PHOTO_MVS]["claim_boundary"],
        "data_scope": "SYNTHETIC",
        "input_profile": "PHONE_RGB",
        "source_kind": "SYNTHETIC_RENDER",
        "real_capture": False,
        "renderer_backend": render_backend_name(bundles[0].backend if bundles else None),
        "renderer_requested": str(spec.renderer),
        "distortion_policy": str(spec.distortion_policy),
        "capability_probe": _pycolmap_probe(),
        "argv_log": [],
        "gt_poses_used": False,
        "gt_depth_used": False,
        "gt_scale_used": False,
        "deployment_mask_used": bool(cfg.use_mask),
        "rigid_scene_handling": (
            "object turntable motion is re-expressed as an equivalent camera orbit around "
            "a fixed object (identical relative motion); background/support/scalemap "
            "features are excluded by the deployable foreground mask"
        ),
        "failure_code": None,
        "failure_reason": None,
    }
    try:
        import pycolmap  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        report["failure_code"] = ErrorCode.MVS_NOT_AVAILABLE.value
        report["failure_reason"] = f"pycolmap import failed: {type(exc).__name__}: {exc}"
        result = _stopped_result(target, spec, bundles, report, route=ROUTE_PHOTO_MVS,
                                 code=ErrorCode.MVS_NOT_AVAILABLE)
        return result, bundles, report

    workdir.mkdir(parents=True, exist_ok=True)
    images_dir = workdir / "images"
    masks_dir = workdir / "masks"
    db_path = workdir / "database.db"
    sparse_dir = workdir / "sparse"
    dense_dir = workdir / "dense"
    for path in (images_dir, masks_dir, sparse_dir):
        path.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    for old in sparse_dir.glob("*"):
        if old.is_file():
            old.unlink()
    shutil.rmtree(dense_dir, ignore_errors=True)

    # ---- write the delivered images and deployment masks under the equivalent orbit
    names: list[str] = []
    gen = np.random.Generator(np.random.PCG64(np.uint64(spec.master_seed + 17)))
    for vi, bundle in enumerate(bundles):
        name = f"view_{vi:03d}.png"
        _imwrite(images_dir / name, bundle.imaging.image)
        if cfg.use_mask:
            mask = bundle.deploy_mask
            _imwrite_mask(masks_dir / f"{name}.png", mask)
        names.append(name)
    report["n_input_images"] = len(names)
    report["mask_files"] = len(list(masks_dir.glob("*.png"))) if cfg.use_mask else 0
    report["image_size"] = list(bundles[0].imaging.image.shape[:2][::-1])

    t0 = time.time()
    maps: dict[int, Any] = {}
    try:
        import pycolmap

        reader = pycolmap.ImageReaderOptions()
        reader.camera_model = cfg.camera_model
        if cfg.use_mask:
            reader.mask_path = str(masks_dir)
        sift = pycolmap.SiftExtractionOptions()
        sift.max_image_size = int(cfg.max_image_size)
        sift.max_num_features = int(cfg.max_num_features)
        sift.num_threads = 2
        argv = ["pycolmap.extract_features", f"--database_path={db_path}",
                f"--image_path={images_dir}", f"--camera_model={cfg.camera_model}",
                f"--mask_path={masks_dir if cfg.use_mask else ''}",
                f"--SiftExtraction.max_image_size={cfg.max_image_size}",
                f"--SiftExtraction.max_num_features={cfg.max_num_features}"]
        entry = _colmap_help(argv, status="RUN")
        try:
            pycolmap.extract_features(str(db_path), str(images_dir), names,
                                      pycolmap.CameraMode.AUTO, cfg.camera_model,
                                      reader, sift)
            entry["status"] = "OK"
        except Exception as exc:  # noqa: BLE001
            entry["status"] = "FAIL"
            entry["stderr_tail"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            entry["seconds"] = time.time() - t0
            report["argv_log"].append(entry)

        t1 = time.time()
        argv = ["pycolmap.match_exhaustive", f"--database_path={db_path}",
                "--SiftMatching.use_gpu=0"]
        entry = _colmap_help(argv, status="RUN")
        try:
            pycolmap.match_exhaustive(str(db_path), device=pycolmap.Device.cpu)
            entry["status"] = "OK"
        except Exception as exc:  # noqa: BLE001
            entry["status"] = "FAIL"
            entry["stderr_tail"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            entry["seconds"] = time.time() - t1
            report["argv_log"].append(entry)

        t2 = time.time()
        argv = ["pycolmap.incremental_mapping", f"--database_path={db_path}",
                f"--image_path={images_dir}", f"--output_path={sparse_dir}"]
        entry = _colmap_help(argv, status="RUN")
        try:
            maps = pycolmap.incremental_mapping(str(db_path), str(images_dir),
                                               str(sparse_dir))
            entry["status"] = "OK"
        except Exception as exc:  # noqa: BLE001
            entry["status"] = "FAIL"
            entry["stderr_tail"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            entry["seconds"] = time.time() - t2
            report["argv_log"].append(entry)
    except Exception as exc:  # noqa: BLE001 - every SfM failure is a STOP_SFM
        report["failure_code"] = ErrorCode.STOP_SFM.value
        report["failure_reason"] = f"SfM raised {type(exc).__name__}: {exc}"
        (workdir / "STOP-SFM").write_text(json.dumps(report, indent=2, default=str),
                                          encoding="utf-8")
        result = _stopped_result(target, spec, bundles, report, route=ROUTE_PHOTO_MVS,
                                 code=ErrorCode.STOP_SFM)
        return result, bundles, report

    if not maps:
        report["failure_code"] = ErrorCode.STOP_SFM.value
        report["failure_reason"] = "incremental_mapping returned no reconstruction"
        (workdir / "STOP-SFM").write_text(json.dumps(report, indent=2, default=str),
                                          encoding="utf-8")
        result = _stopped_result(target, spec, bundles, report, route=ROUTE_PHOTO_MVS,
                                 code=ErrorCode.STOP_SFM)
        return result, bundles, report

    model_id = max(maps, key=lambda k: maps[k].num_reg_images)
    rec = maps[model_id]
    report["reconstruction"] = {
        "model_id": int(model_id),
        "num_reg_images": int(rec.num_reg_images()),
        "num_points3D": int(rec.num_points3D()),
        "num_cameras": int(rec.num_cameras()),
        "mean_reproj_error_px": float(rec.compute_mean_reprojection_error()),
        "mean_track_length": float(rec.compute_mean_track_length()),
        "registered_fraction": float(rec.num_reg_images() / max(len(names), 1)),
        "n_models": len(maps),
    }
    if rec.num_reg_images() < cfg.min_registered_images:
        report["failure_code"] = ErrorCode.STOP_SFM.value
        report["failure_reason"] = (
            f"only {rec.num_reg_images()} of {len(names)} images registered "
            f"(< min_registered_images={cfg.min_registered_images})"
        )
        (workdir / "STOP-SFM").write_text(json.dumps(report, indent=2, default=str),
                                          encoding="utf-8")
        result = _stopped_result(target, spec, bundles, report, route=ROUTE_PHOTO_MVS,
                                 code=ErrorCode.STOP_SFM)
        return result, bundles, report

    rec.write(str(sparse_dir / "0"))

    # ---- undistort (real pycolmap stage); the undistorted model drives the dense step
    undistorted_ok = False
    if cfg.run_undistort:
        t3 = time.time()
        argv = ["pycolmap.undistort_images", f"--output_path={dense_dir}",
                f"--input_path={sparse_dir / '0'}", f"--image_path={images_dir}"]
        entry = _colmap_help(argv, status="RUN")
        try:
            dense_dir.mkdir(parents=True, exist_ok=True)
            pycolmap.undistort_images(str(dense_dir), str(sparse_dir / "0"),
                                      str(images_dir), names)
            undistorted_ok = (dense_dir / "sparse").exists()
            entry["status"] = "OK" if undistorted_ok else "PARTIAL"
            if not undistorted_ok:
                entry["stderr_tail"] = "undistort produced no sparse model"
        except Exception as exc:  # noqa: BLE001
            entry["status"] = "FAIL"
            entry["stderr_tail"] = f"{type(exc).__name__}: {exc}"
        finally:
            entry["seconds"] = time.time() - t3
            report["argv_log"].append(entry)
    report["undistort_ok"] = undistorted_ok

    dense_model = None
    if undistorted_ok:
        try:
            import pycolmap

            dense_model = pycolmap.Reconstruction(str(dense_dir / "sparse"))
        except Exception as exc:  # noqa: BLE001
            report["undistort_model_error"] = f"{type(exc).__name__}: {exc}"
            dense_model = None
    model = dense_model if dense_model is not None else rec

    # ---- dense
    if cfg.dense_backend == "PATCHMATCH":
        report["dense_backend"] = "PATCHMATCH"
        report["failure_code"] = ErrorCode.MVS_NOT_AVAILABLE.value
        report["failure_reason"] = (
            "PatchMatch stereo is not exposed by pycolmap 3.11.1 (no patch_match_stereo "
            "symbol) and no standalone COLMAP executable exists on this host, so the dense "
            "MVS stage cannot be executed.  This is not reported as a successful dense run."
        )
        report["dense_attempt"] = {
            "requested_backend": "PATCHMATCH",
            "available_symbols": sorted(
                n for n in dir(pycolmap) if "stereo" in n.lower() or "patch" in n.lower()),
            "standalone_colmap_binary": _which_colmap(),
        }
        result = _stopped_result(target, spec, bundles, report, route=ROUTE_PHOTO_MVS,
                                 code=ErrorCode.MVS_NOT_AVAILABLE)
        return result, bundles, report

    points, provenance, dense_stats = _sparse_depth_prior(model, dense_dir, undistorted_ok)
    report["dense"] = dense_stats
    report["dense_backend"] = "SPARSE_DEPTH_PRIOR"
    report["dense_claim"] = (
        "depth maps are interpolated from the SPARSE COLMAP reconstruction (estimated "
        "cameras and triangulated points) and fused; this is NOT a PatchMatch run and is "
        "labelled accordingly (MVS_NOT_AVAILABLE for the PatchMatch stage)"
    )
    report["failure_code"] = ErrorCode.MVS_NOT_AVAILABLE.value
    report["failure_reason"] = (
        "PatchMatch dense stereo unavailable in this environment; the delivered cloud is a "
        "fused sparse-depth prior built from estimated COLMAP geometry, not a PatchMatch "
        "result"
    )

    dirs = points - np.array([0.0, 0.0, 0.0])[None, :]
    if points.shape[0]:
        # orient towards the reconstruction centroid direction for stability
        center = points.mean(axis=0)
        dirs = points - center[None, :]
    normals, nvalid = estimate_normals_open3d(points, k=int(params.get("normal_k", 12)),
                                              orient_towards=dirs if points.shape[0] else None)
    voxel = float(params.get("voxel_mm", max(profile.mm_per_pixel, 0.5)))
    if points.shape[0]:
        points, src = fuse_points(points, voxel_mm=voxel, keep="first")
        normals, nvalid = normals[src], nvalid[src]

    scale_valid = False
    scale_note = (
        "SfM delivers an arbitrary reconstruction unit; no deployable scale source was "
        "present in this synthetic input, so scale_valid=false and no mm claim is made"
    )
    if params.get("scale_target_radius_mm") is not None:
        scale_valid, scale_value = _align_scale(points, float(params["scale_target_radius_mm"]))
        report["scale_estimate"] = {"aligned": True, "scale": scale_value,
                                    "source_kind": SOURCE_CALIBRATED}
    else:
        report["scale_estimate"] = {"aligned": False, "scale": None,
                                    "source_kind": "NONE"}

    obs = _assemble_result(
        target=target, route=ROUTE_PHOTO_MVS, spec=spec, bundles=bundles,
        points=points, normals=normals,
        point_valid=np.ones(points.shape[0], dtype=bool), normal_valid=nvalid,
        scale_valid=scale_valid, fused_mesh=None, backend_report=report,
        extra_meta={"scale_note": scale_note,
                    "provenance_view_histogram": provenance,
                    "estimated_poses_in_labels_only": True},
    )
    result_status = "MVS_NOT_AVAILABLE" if report["failure_code"] else "OK"
    obs.meta["route_status"] = result_status
    return obs, bundles, report


def _which_colmap() -> str | None:
    return shutil.which("colmap")


def _pycolmap_probe() -> dict[str, Any]:
    probe: dict[str, Any] = {"import": False}
    try:
        import pycolmap

        probe["import"] = True
        probe["version"] = str(getattr(pycolmap, "__version__", "unknown"))
        probe["has_extract_features"] = hasattr(pycolmap, "extract_features")
        probe["has_match_exhaustive"] = hasattr(pycolmap, "match_exhaustive")
        probe["has_incremental_mapping"] = hasattr(pycolmap, "incremental_mapping")
        probe["has_undistort_images"] = hasattr(pycolmap, "undistort_images")
        probe["has_patch_match_stereo"] = hasattr(pycolmap, "patch_match_stereo")
        probe["has_stereo_fusion"] = hasattr(pycolmap, "stereo_fusion")
        probe["mask_path_support"] = "mask_path" in dir(pycolmap.ImageReaderOptions)
        probe["cuda_expected"] = False
        probe["standalone_colmap_binary"] = _which_colmap()
    except Exception as exc:  # noqa: BLE001
        probe["error"] = f"{type(exc).__name__}: {exc}"
    return probe


def _stopped_result(target: Target, spec: ObsSpec, bundles: list[ViewBundle],
                    report: dict[str, Any], *, route: str, code: ErrorCode
                    ) -> ObservationResult:
    """A structured *stop* result: no points, no mesh, explicit failure code."""
    obs = _assemble_result(
        target=target, route=route, spec=spec, bundles=bundles,
        points=np.zeros((0, 3), dtype=np.float64),
        normals=np.zeros((0, 3), dtype=np.float64),
        point_valid=np.zeros(0, dtype=bool), normal_valid=np.zeros(0, dtype=bool),
        scale_valid=False, fused_mesh=None, backend_report=report,
        extra_meta={"stopped": True, "stop_code": code.value,
                    "ideal_depth_backfill": False},
        force_route=route,
    )
    obs.meta["route_status"] = code.value
    # ``route`` field stays the real route name; the stop state lives in meta/backend report
    obs.route = route
    return obs


def _imwrite(path: Path, image: np.ndarray) -> None:
    import cv2

    arr = np.asarray(image)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if not cv2.imwrite(str(path), arr[:, :, ::-1] if arr.ndim == 3 and arr.shape[2] == 4
                       else arr):
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, f"failed to write {path}",
                          stage="observe.routes._imwrite")


def _imwrite_mask(path: Path, mask: np.ndarray) -> None:
    import cv2

    cv2.imwrite(str(path), (np.asarray(mask, dtype=bool).astype(np.uint8)) * 255)


def _sparse_depth_prior(model: Any, dense_dir: Path, undistorted: bool
                        ) -> tuple[np.ndarray, list[int], dict[str, Any]]:
    """Depth maps interpolated from the estimated sparse model, then fused.

    Every input here is *estimated*: cameras from ``model``, points from ``model``.  No
    simulator depth, pose or scale enters this function.
    """
    from scipy.spatial import Delaunay

    stats: dict[str, Any] = {"views_processed": 0, "views_with_depth": 0,
                             "per_view_points": [], "interpolation": "delaunay_barycentric",
                             "input": "COLMAP_ESTIMATED_SPARSE"}
    all_pts: list[np.ndarray] = []
    provenance: list[int] = []
    for image_id in model.reg_image_ids():
        image = model.image(image_id)
        cam = model.camera(image.camera_id)
        K = np.asarray(cam.calibration_matrix(), dtype=np.float64)
        T_CW = np.eye(4, dtype=np.float64)
        T_CW[:3, :3] = np.asarray(image.cam_from_world.rotation.matrix(), dtype=np.float64)
        T_CW[:3, 3] = np.asarray(image.cam_from_world.translation, dtype=np.float64)
        T_WC = np.linalg.inv(T_CW)
        pts3d = []
        for p2d in image.points2D:
            if not p2d.has_point3D():
                continue
            pid = p2d.point3D_id
            if pid == -1 or not model.exists_point3D(pid):
                continue
            pts3d.append(np.asarray(model.point3D(pid).xyz, dtype=np.float64))
        stats["views_processed"] += 1
        stats["per_view_points"].append(len(pts3d))
        if len(pts3d) < 6:
            continue
        P = np.asarray(pts3d, dtype=np.float64)
        Pc = P @ T_CW[:3, :3].T + T_CW[:3, 3][None, :]
        safe = Pc[:, 2] > 1e-6
        Pc = Pc[safe]
        if Pc.shape[0] < 4:
            continue
        uv = np.stack([K[0, 0] * Pc[:, 0] / Pc[:, 2] + K[0, 2],
                       K[1, 1] * Pc[:, 1] / Pc[:, 2] + K[1, 2]], axis=1)
        z = Pc[:, 2]
        h, w = int(cam.height), int(cam.width)
        inside = (uv[:, 0] >= 0) & (uv[:, 0] <= w - 1) & (uv[:, 1] >= 0) & (uv[:, 1] <= h - 1)
        uv, z = uv[inside], z[inside]
        if uv.shape[0] < 4:
            continue
        try:
            tri = Delaunay(uv)
        except Exception:  # noqa: BLE001 - degenerate configuration, keep the points only
            all_pts.append(Pc[inside] @ T_WC[:3, :3].T + T_WC[:3, 3][None, :])
            provenance.append(int(image_id))
            stats["views_with_depth"] += 1
            continue
        # sample the interpolated depth on a coarse grid and keep only inside-triangle pixels
        step = max(int(min(h, w) / 96), 1)
        gy, gx = np.mgrid[0:h:step, 0:w:step]
        grid = np.stack([gx.ravel().astype(np.float64), gy.ravel().astype(np.float64)], axis=1)
        simplex = tri.find_simplex(grid)
        ok = simplex >= 0
        if not ok.any():
            continue
        T = tri.transform[simplex[ok]]
        delta = grid[ok] - T[:, 2, :]
        bary = np.einsum("nij,nj->ni", T[:, :2, :], delta)
        bary = np.concatenate([bary, 1.0 - bary.sum(axis=1, keepdims=True)], axis=1)
        z_tri = z[tri.simplices[simplex[ok]]]
        z_grid = np.einsum("ni,ni->n", bary, z_tri)
        # positive-depth guard: a triangle that spans the camera plane is rejected
        good = np.isfinite(z_grid) & (z_grid > 0)
        if not good.any():
            continue
        gsel = grid[ok][good]
        zsel = z_grid[good]
        x_c = (gsel[:, 0] - K[0, 2]) / K[0, 0] * zsel
        y_c = (gsel[:, 1] - K[1, 2]) / K[1, 1] * zsel
        Pc_s = np.stack([x_c, y_c, zsel], axis=1)
        world = Pc_s @ T_WC[:3, :3].T + T_WC[:3, 3][None, :]
        all_pts.append(world)
        provenance.append(int(image_id))
        stats["views_with_depth"] += 1
    if not all_pts:
        return np.zeros((0, 3), dtype=np.float64), [], stats
    points = np.concatenate(all_pts, axis=0)
    stats["n_dense_points_before_fusion"] = int(points.shape[0])
    return points, provenance, stats


def _align_scale(points: np.ndarray, target_radius_mm: float) -> tuple[bool, float]:
    """Scale from a *declared* rigid target radius; returns ``(valid, scale)``."""
    if points.shape[0] < 3:
        return False, 1.0
    centre = points.mean(axis=0)
    radii = np.linalg.norm(points - centre[None, :], axis=1)
    r = float(np.percentile(radii, 90))
    if r <= 1e-9:
        return False, 1.0
    return True, float(target_radius_mm / r)


# --------------------------------------------------------------------------------------
# serialisation
# --------------------------------------------------------------------------------------
def observation_to_dict(obs: ObservationResult) -> dict[str, np.ndarray]:
    """Flatten an observation into a store payload (arrays keyed by view)."""
    payload: dict[str, np.ndarray] = {
        "points": np.asarray(obs.points, dtype=np.float32),
        "normals": np.asarray(obs.normals, dtype=np.float32),
        "point_valid": np.asarray(obs.point_valid, dtype=bool),
        "normal_valid": np.asarray(obs.normal_valid, dtype=bool),
    }
    for i, view in enumerate(obs.views):
        payload[f"v{i:03d}.rgb"] = np.asarray(view.rgb, dtype=np.uint8)
        payload[f"v{i:03d}.rgb_linear"] = np.asarray(view.rgb_linear, dtype=np.float32)
        payload[f"v{i:03d}.depth_z"] = np.nan_to_num(
            np.asarray(view.depth_z, dtype=np.float32), nan=-1.0, posinf=-1.0)
        payload[f"v{i:03d}.id_map"] = np.asarray(view.id_map, dtype=np.int32)
        payload[f"v{i:03d}.surface_tag"] = np.asarray(view.surface_tag, dtype=np.int16)
        payload[f"v{i:03d}.deployment_mask"] = np.asarray(view.deployment_mask, dtype=bool)
        if view.roi is not None:
            payload[f"v{i:03d}.roi"] = np.asarray(view.roi, dtype=bool)
        payload[f"v{i:03d}.uncertain_mask"] = np.asarray(view.uncertain_mask, dtype=bool)
        payload[f"v{i:03d}.K"] = np.asarray(view.frame.K, dtype=np.float64)
        payload[f"v{i:03d}.T_WC"] = np.asarray(view.frame.T_WC, dtype=np.float64)
        payload[f"v{i:03d}.dist"] = (np.zeros(0, dtype=np.float64) if view.frame.dist is None
                                     else np.asarray(view.frame.dist, dtype=np.float64))
    if obs.spurious_mask is not None:
        payload["spurious_mask"] = np.asarray(obs.spurious_mask, dtype=bool)
    if obs.fused_mesh is not None:
        from ..storage.mesh_io import mesh_arrays

        for key, arr in mesh_arrays(obs.fused_mesh).items():
            payload[f"mesh.{key}"] = arr
    return payload


def observation_meta(obs: ObservationResult) -> dict[str, Any]:
    """JSON-safe metadata of an observation (views are described, not embedded)."""
    return {
        "mother_id": obs.mother_id, "fragment_id": obs.fragment_id,
        "component_id": obs.component_id, "route": obs.route,
        "input_profile": obs.input_profile, "observation_id": obs.observation_id,
        "scale_valid": bool(obs.scale_valid), "frame_id": obs.frame_id,
        "quality": _jsonable(obs.quality),
        "backend_report": _jsonable(obs.backend_report),
        "meta": _jsonable(obs.meta),
        "n_points": int(np.asarray(obs.points).shape[0]),
        "views": [
            {
                "view_id": v.view_id, "image_size": list(np.asarray(v.rgb).shape[:2][::-1]),
                "profile_id": v.frame.profile_id, "tier": v.frame.tier,
                "u_position_mm": float(v.frame.u_position_mm),
                "working_distance_mm": float(v.frame.working_distance_mm),
                "focus_setting": v.frame.focus_setting,
                "camera_model": v.frame.camera_model,
                "source_kind": v.source_kind,
                "has_roi": v.roi is not None,
                "meta": _jsonable(v.meta),
            }
            for v in obs.views
        ],
    }


def observation_from_dict(meta: dict[str, Any], arrays: dict[str, np.ndarray]
                          ) -> ObservationResult:
    """Rebuild an observation from a store payload (inverse of the two functions above)."""
    from ..schemas.runtime import ObsView, ViewFrame

    n_views = len(meta.get("views", []))
    views: list[ObsView] = []
    for i in range(n_views):
        info = meta["views"][i]
        prefix = f"v{i:03d}."
        missing = [k for k in ("rgb", "depth_z", "id_map", "K", "T_WC") if prefix + k not in arrays]
        if missing:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"observation view {i} payload missing {missing}",
                              stage="observe.routes.observation_from_dict")
        depth = np.asarray(arrays[prefix + "depth_z"], dtype=np.float32).copy()
        depth[depth < 0] = np.nan
        dist = np.asarray(arrays.get(prefix + "dist", np.zeros(0)), dtype=np.float64)
        u = float(info.get("u_position_mm", 0.0))
        wd = float(info.get("working_distance_mm", 0.0))
        frame = ViewFrame(
            view_id=str(info["view_id"]),
            K=np.asarray(arrays[prefix + "K"], dtype=np.float64),
            T_WC=np.asarray(arrays[prefix + "T_WC"], dtype=np.float64),
            image_size=tuple(int(x) for x in info["image_size"]),
            profile_id=str(info.get("profile_id", "")),
            tier=str(info.get("tier", "")),
            u_position_mm=u,
            working_distance_mm=wd,
            focus_setting=str(info.get("focus_setting", "")),
            source_kind=str(info.get("source_kind", SOURCE_SENSOR_SIM)),
            camera_model=str(info.get("camera_model", "PINHOLE")),
            dist=(dist if dist.size else None),
            meta=dict(info.get("meta", {}).get("view_meta", {}) or {}),
        )
        views.append(ObsView(
            view_id=frame.view_id,
            frame=frame,
            rgb=np.asarray(arrays[prefix + "rgb"], dtype=np.uint8),
            rgb_linear=np.asarray(arrays[prefix + "rgb_linear"], dtype=np.float32),
            depth_z=depth,
            id_map=np.asarray(arrays[prefix + "id_map"], dtype=np.int32),
            surface_tag=np.asarray(arrays[prefix + "surface_tag"], dtype=np.int16),
            deployment_mask=np.asarray(arrays[prefix + "deployment_mask"], dtype=bool),
            roi=(np.asarray(arrays[prefix + "roi"], dtype=bool)
                 if prefix + "roi" in arrays else None),
            uncertain_mask=np.asarray(arrays[prefix + "uncertain_mask"], dtype=bool),
            quality={},
            source_kind=str(info.get("source_kind", SOURCE_SENSOR_SIM)),
            meta=dict(info.get("meta", {})),
        ))
    fused_mesh = None
    mesh_keys = [k for k in arrays if k.startswith("mesh.")]
    if mesh_keys:
        from ..storage.mesh_io import arrays_to_mesh

        fused_mesh, _ = arrays_to_mesh({k[len("mesh."):]: arrays[k] for k in mesh_keys})
    obs = ObservationResult(
        mother_id=str(meta.get("mother_id", "")),
        fragment_id=str(meta.get("fragment_id", "")),
        component_id=str(meta.get("component_id", "")),
        route=str(meta.get("route", "")),
        input_profile=str(meta.get("input_profile", "")),
        observation_id=str(meta.get("observation_id", "")),
        views=views,
        points=np.asarray(arrays["points"], dtype=np.float32),
        normals=np.asarray(arrays["normals"], dtype=np.float32),
        point_valid=np.asarray(arrays["point_valid"], dtype=bool),
        normal_valid=np.asarray(arrays["normal_valid"], dtype=bool),
        scale_valid=bool(meta.get("scale_valid", False)),
        frame_id=str(meta.get("frame_id", "S_mm")),
        quality=dict(meta.get("quality", {})),
        fused_mesh=fused_mesh,
        spurious_mask=(np.asarray(arrays["spurious_mask"], dtype=bool)
                       if "spurious_mask" in arrays else None),
        backend_report=dict(meta.get("backend_report", {})),
        meta=dict(meta.get("meta", {})),
    )
    return obs


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return {"__ndarray__": {"dtype": str(obj.dtype), "shape": list(obj.shape)}}
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return value if math.isfinite(value) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (int, str, bool)) or obj is None:
        return obj
    if hasattr(obj, "tolist"):
        return _jsonable(obj.tolist())
    return str(obj)


__all__ = [
    "ROUTE_IDEAL_VISIBLE", "ROUTE_PROXY_SCAN", "ROUTE_PHOTO_MVS", "ROUTE_SPECS",
    "ORIGIN_TO_TAG", "DEFAULT_VIEW_COUNT", "MVS_GATE_NAME", "ObsSpec", "Target",
    "ViewBundle", "PhotoMvsConfig", "resolve_target", "render_views",
    "backproject_depth", "fuse_points", "estimate_normals_open3d",
    "route_ideal_visible", "route_proxy_scan", "route_photo_mvs",
    "observation_to_dict", "observation_meta", "observation_from_dict",
    "RENDERER_AUTO", "RENDERER_SOFTWARE", "RENDERER_BLENDER", "RENDERER_TO_BACKEND",
    "DISTORTION_POLICIES", "DISTORTION_POLICY_ERROR", "DISTORTION_POLICY_UNDISTORT",
    "DISTORTION_POLICY_IGNORE", "blender_binary", "blender_config_for",
    "resolve_render_backend", "render_frame_for_backend", "frame_has_distortion",
    "distortion_pixel_effect_px", "render_backend_name", "render_backend_class",
]
