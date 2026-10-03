"""Realism layer: turn a generation config into a *capture-style* observation request.

Why this module exists
----------------------
``synlab.pipeline._resolve_observe_spec`` projects a :class:`GenerationSpec` onto an
:class:`~synlab.observe.routes.ObsSpec` using exactly seven fields -- ``view_count``,
``delivered_size``, ``max_render_pixels``, ``render_spec``, ``master_seed``,
``lineage_id`` and (implicitly) the camera-profile registry -- and therefore **cannot**
express the realism knobs that the observation routes already support:

* ``observation.renderer`` (``auto`` | ``software_rasterizer`` | ``blender``) is read by
  ``synlab.cli`` for the VRAM estimate and by nothing else in the generation path;
* ``ObsSpec.distortion_policy`` (``error`` | ``undistort`` | ``ignore``) has no config key
  at all: the camera profiles of this repository **do** carry OpenCV distortion
  (``CAM_MID_V3``: k1=-0.033, k2=0.008, k3=-0.0018), and the Blender worker renders an
  ideal pinhole, so a Blender request against a distorted profile is *refused* by default
  (``synlab/observe/blender.py::build_config``);
* ``ObsSpec.imaging`` (the ordered exposure/PSF/sensor/gain/encode chain) is reachable from
  no config field, so a config-only run always observes through a **true identity**
  imaging chain: no shot noise, no read noise, no blur, no JPEG;
* ``ObsSpec.route_params`` (per-route work directory, ``photo_mvs`` SfM limits) likewise.

This module is the declared bridge for those four knobs.  It never changes a default of an
existing caller: the pipeline keeps its behaviour unless a caller explicitly asks for a
:func:`observe_spec_from_config` result (see ``tests/a12/observe/run_realistic_lineage.py``,
which installs it through a documented patch of the frozen pipeline).

Honesty rules implemented here
------------------------------
* ``AXIS_LEVELS`` reproduces the *declared* per-level parameters of the degradation axes of
  :mod:`synlab.degrade.axes` (I01 blur, I03 sensor noise, I04 exposure, I05 white balance,
  I10 JPEG) instead of inventing new ladders, and **level 0 is the true identity**: it
  produces an :class:`~synlab.observe.imaging.ImagingSpec` for which
  ``ImagingSpec.is_identity()`` is ``True`` (asserted here, not assumed).
* A distorted profile on the Blender backend is never silently accepted: the policy is
  resolved explicitly (:func:`resolve_distortion_policy`) and the refusal path
  (``policy="error"``) stays reachable.
* The realism tags are *derived from measured fields* of a committed observation
  (:func:`realism_tags` / :func:`is_realistic_capture`), never asserted: ``data_semantics``
  and ``obs_semantics`` are written by the pipeline for old and new data alike, so they
  cannot distinguish the two on their own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ..errors import ErrorCode, SynLabError
from .imaging import ImagingSpec
from .render import RenderSpec
from .routes import (
    DISTORTION_POLICIES,
    DISTORTION_POLICY_ERROR,
    DISTORTION_POLICY_UNDISTORT,
    ObsSpec,
    ROUTE_PHOTO_MVS,
    ROUTE_SPECS,
    distortion_pixel_effect_px,
    frame_has_distortion,
)

#: Schema id of the realism block written into a run record / report.
REALISM_SCHEMA = "synlab.realism.v1"

#: Value written by the realistic pilot into ``store.create_run(..., meta=...)``.  The
#: pipeline writes ``data_semantics`` / ``obs_semantics`` for every batch, so the *run*
#: record is the place where "this library was observed capture-style" is recorded.
REALISM_RUN_TAG = "realistic_capture_style"

#: Levels of the imaging-side (I family) degradation ladder.  Level 0 is the identity.
LEVEL_IDENTITY = 0
#: Level used by the realistic baseline: a well-exposed handheld phone capture
#: (half-pixel PSF, ISO-class photon gain with 0.002 read noise, +0.5 EV auto-exposure,
#: 2.5 % white-balance deviation, JPEG q90).
LEVEL_REALISTIC = 1
LEVELS: tuple[int, ...] = (0, 1, 2, 3, 4)

#: Declared per-level parameters, copied from the registered axis declarations
#: (``synlab/degrade/axes.py``: ``I01.LEVELS``, ``I03.VARIANT_LEVELS['camera_noise_profile']``,
#: ``I04.LEVELS``, ``I05.LEVELS``, ``I10.LEVELS``).  Reproducing them here keeps the
#: observation route and the degradation module on one ladder instead of two:
#: ``I01``/``I04``/``I05``/``I10`` are the default variant's ``LEVELS`` and ``I03`` is the
#: registered **bundled** ladder (photon scale *and* read noise move together, which is what a
#: real camera does when the ISO changes).
AXIS_LEVELS: dict[str, dict[str, tuple[Any, ...]]] = {
    "I01": {"psf_sigma_px": (0.0, 0.5, 1.0, 2.0, 4.0)},                    # level 0 == no PSF
    "I03": {"photon_gain": (0.0, 16000.0, 8000.0, 4000.0, 1000.0),
            "read_sigma": (0.0, 0.002, 0.004, 0.008, 0.016)},
    "I04": {"exposure_ev": (0.0, 0.5, 1.0, 1.5, 2.0)},                     # exposure_gain variant
    "I05": {"wb_deviation": (0.0, 0.025, 0.05, 0.1, 0.2)},
    "I10": {"jpeg_quality": (100, 90, 75, 60, 40)},
}

#: Axes applied by the realistic baseline (:data:`LEVEL_REALISTIC`) and the axes that stay
#: at their identity level.  Everything is declared, nothing is implicit.
APPLIED_AXES: tuple[str, ...] = ("I01", "I03", "I04", "I05", "I10")

#: Delivery transfer function of the realistic baseline.  A phone hands over a *gamma-encoded*
#: JPEG; delivering linear radiance through a JPEG encoder is physically inconsistent with a
#: real capture.  Level 0 keeps ``LINEAR`` so that the identity claim of the ladder holds; the
#: response actually applied is written into the observation's own stage list.
DELIVERY_RESPONSE = "SRGB"

#: Photon scale (``ImagingSpec.effective_gain``) of the *ideal reference* variant used by the
#: probe.  The chain's default ``effective_gain = 1.0`` photon-starves the render: measured on
#: the control leg, the delivered 1024x768 PNGs contain **8 distinct grey levels** and SIFT sees
#: essentially noise (5200 keypoints/image but only 66 matches in total, no reconstruction).
#: ``1.0e4`` is the value the repository's own MVS evidence run uses for the same reason
#: (``synlab/observe/mvs_subset.py::MvsConfig.effective_gain``).
IDEAL_REFERENCE_GAIN = 1.0e4

#: Deployment-mask policies of the delivered frames.  The CoC mark-out is a *conservative
#: bound* of the thin-lens circle of confusion; it is only meaningful when the delivered image
#: really carries that defocus.  With the pipeline's value (``0.75 * f_number`` px) the
#: measured deployment mask covers ~0.5-2.6 % of the frame while the observed surface covers
#: ~17 %, i.e. the only mask handed to SfM keeps a few hundred pixels of the object.
MASK_POLICY_PIPELINE_COC = "pipeline_coc_markout"
MASK_POLICY_FOREGROUND = "foreground_silhouette"
MASK_POLICIES: tuple[str, ...] = (MASK_POLICY_PIPELINE_COC, MASK_POLICY_FOREGROUND)
#: CoC threshold that disables the defocus criterion while keeping the mixed-pixel and
#: depth-edge terms of the uncertain mask (the same choice the MVS evidence run records).
COC_THRESHOLD_UNBOUNDED_PX = 1.0e6


#: A JPEG-encoded delivery is what a phone hands over; the imaging chain labels such an
#: output ``ISP_PROXY``/``JPEG_PROXY`` (a linear-model claim on gamma/JPEG data is forbidden).
DELIVERY_ENCODE = "JPEG"

#: ``I09`` (delivery resolution) is deliberately **not** applied: the realistic baseline keeps
#: the configured long edge (1024 px) because a real capture is not downsampled before
#: delivery, and the ladder stays available through the axis itself.
DOWNSCALE_AXIS = "I09"

#: Geometry-side (G family) effects that the ``photo_mvs`` route carries *by construction*:
#: nothing is injected, the effect is whatever the real SfM/dense pipeline measured, and the
#: field below names where the measurement is read from.
GEOMETRY_BY_CONSTRUCTION: dict[str, dict[str, str]] = {
    "G07": {"name": "calibration estimation (intrinsics from the images only)",
            "field": "backend_report.reconstruction.mean_reproj_error_px",
            "note": "COLMAP estimates SIMPLE_RADIAL from features; no simulator K is handed in"},
    "G02": {"name": "sparse observed surface",
            "field": "backend_report.reconstruction.num_points3D",
            "note": "the fused cloud comes from triangulated sparse points, not from renderer depth"},
    "G03": {"name": "coverage holes of the observed surface",
            "field": "quality.hole_ratio_max / quality.view_coverage_mean",
            "note": "triangulation gaps and mask/feature limits produce real holes"},
    "G06": {"name": "arbitrary reconstruction scale",
            "field": "scale_valid / backend_report.scale_estimate",
            "note": "SfM units stay arbitrary unless a declared scale source exists"},
}

#: Measured propagation facts of the frozen generation path (used by docs and tests).
PIPELINE_PROPAGATED_KEYS: tuple[str, ...] = (
    "view_count", "delivered_size", "max_render_pixels", "render_spec", "master_seed",
    "lineage_id",
)
PIPELINE_IGNORED_CONFIG_KEYS: tuple[str, ...] = (
    "observation.renderer", "observation.routes[1:]", "observation.camera_profile_ref(dist)",
    "ObsSpec.imaging", "ObsSpec.route_params", "ObsSpec.distortion_policy",
)


# --------------------------------------------------------------------------------------
# level tables -> ImagingSpec
# --------------------------------------------------------------------------------------
def level_parameters(axis_id: str, level: int) -> dict[str, Any]:
    """Declared parameters of one axis at one level (raises for an unknown level)."""
    if axis_id not in AXIS_LEVELS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown realism axis {axis_id!r}; known: "
                          f"{sorted(AXIS_LEVELS)}", stage="observe.realism.level_parameters")
    if int(level) not in LEVELS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"level {level} outside {list(LEVELS)}",
                          stage="observe.realism.level_parameters")
    return {name: values[int(level)] for name, values in AXIS_LEVELS[axis_id].items()}


def normalise_levels(levels: Mapping[str, int] | None = None, *,
                     default: int = LEVEL_REALISTIC) -> dict[str, int]:
    """Fill every applied axis with ``default`` unless the caller overrode it."""
    out = {axis: int(default) for axis in APPLIED_AXES}
    for axis, level in dict(levels or {}).items():
        if axis not in AXIS_LEVELS:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"unknown realism axis {axis!r}; known: {sorted(AXIS_LEVELS)}",
                              stage="observe.realism.normalise_levels")
        out[axis] = int(level)
    return out


def imaging_spec_for(levels: Mapping[str, int] | None = None, *,
                     photon_gain: float | None = None,
                     sensor_noise_enabled: bool | None = None) -> ImagingSpec:
    """The ordered imaging chain for one level assignment (level 0 == true identity).

    The mapping is one-to-one with the declared axes::

        I01 psf_sigma_px      -> ImagingSpec.defocus_sigma_px   (before photon counting)
        I03 photon_gain       -> ImagingSpec.effective_gain     (Poisson(g*x)/g)
        I03 read_sigma        -> ImagingSpec.read_noise_sigma
        I04 exposure_ev       -> ImagingSpec.exposure_ev        (scene-side amount, pre-photon)
        I05 wb_deviation      -> ImagingSpec.white_balance      (fixed direction gains)
        I10 jpeg_quality      -> ImagingSpec.encode/jpeg_quality

    plus one *delivery* property that no axis owns: level > 0 applies the
    :data:`DELIVERY_RESPONSE` transfer function, because a real phone hands over a
    gamma-encoded JPEG and shipping linear radiance through a JPEG encoder is not a capture.
    Level 0 keeps ``LINEAR`` so the identity assertion below stays true.

    ``photon_gain`` overrides the ladder's ``I03`` photon scale.  It is used for the *ideal
    reference* variant (:data:`IDEAL_REFERENCE_GAIN`): the chain's own default
    ``effective_gain = 1.0`` photon-starves the render (measured: 8 grey levels in the
    delivered 1024x768 frames), and such frames cannot be called an "ideal" observation.
    Sensor noise is enabled when I03 is nonzero or an explicit photon-gain override is
    requested. ``sensor_noise_enabled`` is an explicit override and takes precedence.
    """
    from ..degrade.ops_image import WB_DIRECTION

    resolved = normalise_levels(levels)
    if sensor_noise_enabled is not None and type(sensor_noise_enabled) is not bool:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "sensor_noise_enabled must be bool or None",
                          stage="observe.realism.imaging_spec_for")
    spec = ImagingSpec()
    spec.sensor_noise_enabled = (sensor_noise_enabled
                                 if sensor_noise_enabled is not None else
                                 bool(resolved["I03"] != LEVEL_IDENTITY
                                      or photon_gain is not None))
    spec.defocus_sigma_px = float(level_parameters("I01", resolved["I01"])["psf_sigma_px"])
    spec.defocus_depth_dependent = True
    i03 = level_parameters("I03", resolved["I03"])
    spec.effective_gain = (float(photon_gain) if photon_gain is not None
                           else (float(i03["photon_gain"]) or 1.0))
    spec.read_noise_sigma = float(i03["read_sigma"])
    spec.exposure_ev = float(level_parameters("I04", resolved["I04"])["exposure_ev"])
    deviation = float(level_parameters("I05", resolved["I05"])["wb_deviation"])
    direction = np.asarray(WB_DIRECTION, dtype=np.float64).reshape(3)
    spec.white_balance = tuple((1.0 + deviation * direction).tolist())
    quality = int(level_parameters("I10", resolved["I10"])["jpeg_quality"])
    if resolved["I10"] == LEVEL_IDENTITY:
        spec.encode = "PNG"
        spec.jpeg_quality = 100
    else:
        spec.encode = DELIVERY_ENCODE
        spec.jpeg_quality = quality
    if any(level != LEVEL_IDENTITY for level in resolved.values()):
        # a capture-style delivery is gamma-encoded (a real phone JFIF is sRGB, never linear)
        spec.response = DELIVERY_RESPONSE
    if (all(level == LEVEL_IDENTITY for level in resolved.values())
            and not spec.resolved_sensor_noise_enabled()):
        if not spec.is_identity():
            raise SynLabError(
                ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
                "level 0 must produce a true identity imaging chain, but the constructed "
                "ImagingSpec reports is_identity() == False",
                stage="observe.realism.imaging_spec_for",
                measurements={"levels": dict(resolved)},
            )
    return spec


def degradation_report(levels: Mapping[str, int] | None = None, *,
                       mask_policy: str = MASK_POLICY_FOREGROUND,
                       photon_gain: float | None = None,
                       sensor_noise_enabled: bool | None = None) -> dict[str, Any]:
    """Declared + realised description of one level assignment (for reports and run meta)."""
    resolved = normalise_levels(levels)
    spec = imaging_spec_for(resolved, photon_gain=photon_gain,
                            sensor_noise_enabled=sensor_noise_enabled)
    if mask_policy not in MASK_POLICIES:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown mask_policy {mask_policy!r}; expected {list(MASK_POLICIES)}",
                          stage="observe.realism.degradation_report")
    return {
        "schema": REALISM_SCHEMA,
        "levels": dict(resolved),
        "declared_parameters": {axis: level_parameters(axis, level)
                                for axis, level in sorted(resolved.items())},
        "axis_ladders": {axis: {name: list(values)
                                for name, values in AXIS_LEVELS[axis].items()}
                         for axis in APPLIED_AXES},
        "applied_axes": list(APPLIED_AXES),
        "delivery_encode": spec.encode,
        "delivery_response": spec.response,
        "jpeg_quality": int(spec.jpeg_quality),
        "photon_gain": float(spec.effective_gain),
        "photon_gain_overridden": photon_gain is not None,
        "sensor_noise_enabled": spec.resolved_sensor_noise_enabled(),
        "imaging_semantics_version": str(spec.version),
        "imaging_identity": bool(spec.is_identity()),
        "mask_policy": mask_policy,
        "mask_policy_note": (
            "the deployment mask is the only mask handed to SfM; "
            + ("the pipeline's CoC mark-out (0.75 x f_number px) is used unchanged"
               if mask_policy == MASK_POLICY_PIPELINE_COC else
               "the defocus CoC criterion is disabled (threshold "
               f"{COC_THRESHOLD_UNBOUNDED_PX:g} px) while the mixed-pixel and depth-edge "
               "terms of the uncertain mask are kept: the delivered image is not defocused "
               "by the nominal f/2.2 circle of confusion, so that criterion would exclude "
               "the observed surface from the mask (measured on the control leg)")),
        "geometry_by_construction": dict(GEOMETRY_BY_CONSTRUCTION),
        "not_applied": {
            DOWNSCALE_AXIS: ("delivery resolution stays at the configured long edge; the "
                             "registered axis is available but a real capture is not "
                             "downsampled before delivery"),
        },
    }


# --------------------------------------------------------------------------------------
# distortion policy
# --------------------------------------------------------------------------------------
def resolve_distortion_policy(profile: Any, backend: str, *,
                              policy: str | None = None) -> dict[str, Any]:
    """Explicit handling of a distorted profile on a given render backend.

    * No distortion in the profile -> ``not_applicable`` (nothing to decide).
    * Software rasteriser -> ``applied_by_backend``: the rasteriser projects through the
      OpenCV model itself, so the delivered image *carries* the distortion.
    * Blender -> the worker renders an ideal pinhole; ``error`` refuses, ``undistort``
      renders the undistorted pinhole camera, ``ignore`` renders anyway and records the
      dropped coefficients.  ``policy=None`` means "not declared" and is refused: a
      silently chosen policy is exactly what this module exists to prevent.
    """
    from .render import BACKEND_BLENDER, BACKEND_SOFTWARE

    has_dist = bool(getattr(profile, "dist", None) is not None
                    and np.asarray(profile.dist).size
                    and float(np.abs(np.asarray(profile.dist)).max()) > 0.0)
    out: dict[str, Any] = {
        "profile_id": str(getattr(profile, "profile_id", "")),
        "camera_model": str((getattr(profile, "meta", {}) or {}).get("camera_model", "OPENCV")),
        "distortion": (None if not has_dist
                       else np.asarray(profile.dist, dtype=np.float64).ravel().tolist()),
        "backend": str(backend),
        "policy": None,
        "decision": None,
    }
    if not has_dist:
        out["decision"] = "not_applicable"
        out["note"] = "the profile declares no distortion; no policy is needed"
        return out
    if backend == BACKEND_SOFTWARE:
        out["decision"] = "applied_by_backend"
        out["note"] = ("the software rasteriser projects through the OpenCV distortion model "
                       "itself, so the delivered image carries the profile's distortion")
        return out
    if backend != BACKEND_BLENDER:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown render backend {backend!r}",
                          stage="observe.realism.resolve_distortion_policy")
    if policy is None:
        raise SynLabError(
            ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
            f"profile {out['profile_id']} carries distortion {out['distortion']} and the "
            f"Blender backend renders an ideal pinhole; declare distortion_policy explicitly "
            f"({list(DISTORTION_POLICIES)}) - a default chosen here would be a silent decision",
            stage="observe.realism.resolve_distortion_policy",
        )
    name = str(policy).strip().lower()
    if name not in DISTORTION_POLICIES:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown distortion_policy {policy!r}; expected "
                          f"{list(DISTORTION_POLICIES)}",
                          stage="observe.realism.resolve_distortion_policy",
                          measurements={"known": list(DISTORTION_POLICIES)})
    out["policy"] = name
    if name == DISTORTION_POLICY_ERROR:
        out["decision"] = "refused"
        out["note"] = ("the Blender worker cannot represent OpenCV distortion; this policy "
                       "makes the request fail with ENV_CAPABILITY_MISSING instead of "
                       "rendering a pinhole frame that claims the distorted camera")
    elif name == DISTORTION_POLICY_UNDISTORT:
        out["decision"] = "undistorted_pinhole"
        out["note"] = ("the undistorted pinhole camera of the nominal K is rendered and the "
                       "delivered frame declares dist=None with the provenance recorded; the "
                       "distortion is *removed by an ideal, residual-free calibration*, not by "
                       "a resampled undistort step (no border loss, no focal change)")
    else:
        out["decision"] = "rendered_as_pinhole_coefficients_recorded"
        out["note"] = ("coefficients are dropped from the render but kept in the delivered "
                       "frame's declaration and their measured pixel effect is recorded")
    return out


# --------------------------------------------------------------------------------------
# config -> ObsSpec
# --------------------------------------------------------------------------------------
@dataclass
class RealismObsPlan:
    """Everything the bridge decided, with the evidence needed to check it."""

    obs_spec: ObsSpec
    profile: Any
    route: str
    renderer: str
    distortion: dict[str, Any]
    degradation: dict[str, Any]
    lineage_id: str
    store_root: str
    workdir: str
    declared_by: str = "synlab.observe.realism.observe_spec_from_config"
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": REALISM_SCHEMA,
            "route": self.route,
            "route_spec": dict(ROUTE_SPECS.get(self.route, {})),
            "renderer_requested": self.renderer,
            "renderer_class": "ADAPTER" if self.renderer == "blender" else "CUSTOM_GAP",
            "profile_id": str(getattr(self.profile, "profile_id", "")),
            "profile_calibrated": bool(getattr(self.profile, "calibrated", False)),
            "distortion": dict(self.distortion),
            "degradation": dict(self.degradation),
            "lineage_id": self.lineage_id,
            "store_root": self.store_root,
            "workdir": self.workdir,
            "delivered_size": list(self.obs_spec.delivered_size),
            "view_count": int(self.obs_spec.view_count),
            "max_render_pixels": int(self.obs_spec.max_render_pixels),
            "render_spec": {"supersample": int(self.obs_spec.render_spec.supersample),
                            "coc_px_threshold": float(self.obs_spec.render_spec.coc_px_threshold)},
            "imaging_identity": bool(self.obs_spec.imaging.is_identity()),
            "declared_by": self.declared_by,
            "pipeline_propagated_keys": list(PIPELINE_PROPAGATED_KEYS),
            "pipeline_ignored_config_keys": list(PIPELINE_IGNORED_CONFIG_KEYS),
            **dict(self.extra),
        }


def _declared_long_edge(spec: Any) -> int:
    """Long edge declared by the camera-profile registry (1024 on this host)."""
    ref = getattr(getattr(spec, "observation", None), "camera_profile_ref", None)
    path = Path(ref) if ref else None
    if path and path.exists():
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            edges = [int(p.get("image_long_edge_px", 0) or 0)
                     for p in (document.get("profiles") or [])]
            edges = [edge for edge in edges if edge > 0]
            if edges:
                return int(edges[0])
        except (OSError, ValueError):
            pass
    return 1024


def _declared_f_number(spec: Any, profile: Any) -> float:
    value = getattr(profile, "f_number", None)
    if value:
        return float(value)
    ref = getattr(getattr(spec, "observation", None), "camera_profile_ref", None)
    path = Path(ref) if ref else None
    if path and path.exists():
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            values = [float(p["f_number"]) for p in (document.get("profiles") or [])
                      if p.get("f_number")]
            if values:
                return float(values[0])
        except (OSError, ValueError, KeyError):
            pass
    return 8.0


def observe_spec_from_config(spec: Any, *, store_root: str | Path, lineage_id: str,
                             route: str | None = None, renderer: str | None = None,
                             levels: Mapping[str, int] | None = None,
                             distortion_policy: str | None = DISTORTION_POLICY_UNDISTORT,
                             profile: Any = None,
                             view_count: int | None = None,
                             mask_policy: str = MASK_POLICY_FOREGROUND,
                             photon_gain: float | None = None,
                             sensor_noise_enabled: bool | None = None,
                             blender_config: Any = None,
                             blender_samples: int = 32,
                             denoise: bool = False,
                             photo_mvs_params: Mapping[str, Any] | None = None
                             ) -> RealismObsPlan:
    """Project a :class:`GenerationSpec` onto a capture-style :class:`ObsSpec`.

    Every value that is *not* taken from the config is named in the returned plan, so a
    reader can tell which parts of a realistic run are declared by the config and which are
    declared by this bridge (``declared_by``).
    """
    from ..cameras.api import camera_profiles
    from .blender import BlenderBackendConfig
    from .routes import resolve_render_backend

    observation = getattr(spec, "observation", None)
    if observation is None:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "spec has no observation block",
                          stage="observe.realism.observe_spec_from_config")
    route_name = str(route or (observation.routes[0].value if observation.routes
                               else ROUTE_PHOTO_MVS))
    if route_name not in ROUTE_SPECS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown route {route_name!r}; expected {sorted(ROUTE_SPECS)}",
                          stage="observe.realism.observe_spec_from_config")
    renderer_name = str(renderer if renderer is not None else observation.renderer)
    # resolve_render_backend refuses an unknown name *and* a blender request without a binary;
    # the realistic path therefore cannot silently end up on the rasteriser.
    backend = resolve_render_backend(renderer_name)
    chosen_profile = profile if profile is not None else camera_profiles()[1]
    distortion = resolve_distortion_policy(chosen_profile, backend, policy=distortion_policy)
    degradation = degradation_report(levels, mask_policy=mask_policy, photon_gain=photon_gain,
                                     sensor_noise_enabled=sensor_noise_enabled)
    imspec = imaging_spec_for(levels, photon_gain=photon_gain,
                              sensor_noise_enabled=sensor_noise_enabled)

    edge = _declared_long_edge(spec)
    aspect = (float(chosen_profile.image_size[0]) / float(chosen_profile.image_size[1])
              if getattr(chosen_profile, "image_size", None) else 4.0 / 3.0)
    long_edge = int(getattr(observation, "image_long_edge_px", edge) or edge)
    if aspect >= 1.0:
        delivered = (long_edge, max(int(round(long_edge / aspect)), 8))
    else:
        delivered = (max(int(round(long_edge * aspect)), 8), long_edge)
    max_render_pixels = max(int(delivered[0]) * int(delivered[1]), 1)
    declared_coc = float(RenderSpec.coc_px_threshold)
    aperture = _declared_f_number(spec, chosen_profile)
    coc_threshold = (declared_coc * aperture if mask_policy == MASK_POLICY_PIPELINE_COC
                     else COC_THRESHOLD_UNBOUNDED_PX)

    root = Path(store_root)
    workdir = root / "observe" / route_name / str(lineage_id)
    workdir.mkdir(parents=True, exist_ok=True)
    route_params: dict[str, Any] = {"realism": degradation["schema"],
                                    "realism_levels": dict(degradation["levels"])}
    if route_name == ROUTE_PHOTO_MVS:
        route_params.update({"workdir": str(workdir), "camera_model": "SIMPLE_RADIAL",
                             "max_image_size": int(min(long_edge, 1024)),
                             "max_num_features": 4096, "use_mask": True,
                             "run_undistort": True, "keep_workdir": True,
                             "dense_backend": "SPARSE_DEPTH_PRIOR"})
    route_params.update(dict(photo_mvs_params or {}))
    if route_name == "proxy_scan":
        # the G-family geometric degradations of the proxy route (declared, not implicit)
        route_params.setdefault("voxel_mm", 0.2)

    obs_spec = ObsSpec(
        view_count=int(view_count or getattr(observation, "views_per_fragment", 12)),
        delivered_size=delivered,
        max_render_pixels=max_render_pixels,
        # mirrored from synlab/pipeline.py::_resolve_observe_spec: supersample=1 makes the
        # per-pixel foreground classification exact (a supersampled block that disagrees on
        # the face id rejects ~90 % of the object at this delivered resolution).  The CoC
        # mark-out follows ``mask_policy`` and its value is recorded, never implicit.
        render_spec=RenderSpec(supersample=1, coc_px_threshold=coc_threshold),
        imaging=imspec,
        route_params=route_params,
        workdir=str(workdir),
        master_seed=int(getattr(spec, "master_seed", 20261001)),
        lineage_id=str(lineage_id),
        renderer=renderer_name,
        distortion_policy=(distortion_policy if distortion.get("policy") else
                           DISTORTION_POLICY_ERROR),
    )
    if backend == "BLENDER_CYCLES" or renderer_name == "blender":
        base = blender_config if isinstance(blender_config, BlenderBackendConfig) else \
            BlenderBackendConfig()
        obs_spec.blender_config = BlenderBackendConfig(
            samples=int(blender_samples), filter_width=base.filter_width,
            denoise=bool(denoise), denoiser=base.denoiser, max_bounces=base.max_bounces,
            device=base.device, seed=int(getattr(spec, "master_seed", 20261001)),
            coc_px_threshold=coc_threshold, f_number=aperture,
            distortion_policy=(distortion_policy if distortion.get("policy")
                               else DISTORTION_POLICY_ERROR),
            work_root=str(root / "reports" / "blender" / "_work"),
            run_label=f"realistic_{lineage_id}"[:60],
            timeout_s=base.timeout_s, keep_workdir=True,
            raycast_samples=int(base.raycast_samples),
        )
    return RealismObsPlan(
        obs_spec=obs_spec, profile=chosen_profile, route=route_name, renderer=renderer_name,
        distortion=distortion, degradation=degradation, lineage_id=str(lineage_id),
        store_root=str(root), workdir=str(workdir),
        extra={"backend": backend, "declared_f_number": aperture,
               "declared_coc_px": declared_coc, "coc_px_threshold": float(coc_threshold),
               "mask_policy": mask_policy,
               "blender_samples": int(blender_samples) if renderer_name == "blender" else None,
               "denoise": bool(denoise) if renderer_name == "blender" else None},
    )


# --------------------------------------------------------------------------------------
# tags: making a realistic observation programmatically distinguishable
# --------------------------------------------------------------------------------------
def _level_from_declaration(axis_id: str, params: Mapping[str, Any]) -> int | None:
    """Which ladder level produced these realised parameters (``None`` when off-ladder)."""
    table = AXIS_LEVELS.get(axis_id) or {}
    for name, values in table.items():
        if name not in params:
            continue
        observed = float(params[name])
        for level, declared in enumerate(values):
            if abs(float(declared) - observed) <= 1e-9:
                return int(level)
    return None


def realised_levels(observation: Any) -> dict[str, Any]:
    """Read back which ladder levels an observation was actually produced with.

    The numbers come from the observation's own ``imaging_stages`` block (the stage list the
    imaging chain recorded), never from a caller-supplied claim.
    """
    stages: list[dict[str, Any]] = []
    for view in getattr(observation, "views", []) or []:
        stages.extend(list((view.meta or {}).get("imaging_stages") or []))
    exposure = next((s for s in stages if s.get("op") == "exposure_gain_before_photons"), {})
    psf = next((s for s in stages if s.get("op") == "psf_applied"), {})
    sensor = next((s for s in stages if s.get("stage") == "SENSOR_NOISE"), None)
    if sensor is None:  # read frozen pre-v2 stage records without reinterpreting new outputs
        sensor = next((s for s in stages if s.get("op") == "poisson_read_noise"), {})
    sensor_noise_enabled = bool(sensor.get(
        "enabled", sensor.get("op") == "poisson_read_noise"))
    wb = next((s for s in stages if s.get("op") == "white_balance"), {})
    response = next((s for s in stages if s.get("op") == "camera_response"), {})
    encode = next((s for s in stages if s.get("op") == "quantise_encode"), {})
    gains = [float(g) for g in (wb.get("gains") or [1.0, 1.0, 1.0])]
    deviation = gains[0] - 1.0
    # the depth-dependent defocus variant records the near/far pair instead of a single sigma
    psf_sigma = psf.get("sigma_px", psf.get("sigma_near_px", 0.0))
    # the sensor stage reports the *identity* gain as 1.0 (a gain of 0 would be a division by
    # zero), while the ladder declares 0.0 for "no photon noise": both mean level 0.
    gain = float(sensor.get("effective_gain", 1.0))
    gain = 0.0 if abs(gain - 1.0) <= 1e-12 else gain
    quality = encode.get("jpeg_quality")
    levels = {
        "I01": _level_from_declaration("I01", {"psf_sigma_px": psf_sigma}),
        "I03": _level_from_declaration("I03", {"photon_gain": gain,
                                               "read_sigma": sensor.get("read_noise_sigma", 0.0)}),
        "I04": _level_from_declaration("I04", {"exposure_ev": exposure.get("exposure_ev", 0.0)}),
        "I05": _level_from_declaration("I05", {"wb_deviation": deviation}),
        "I10": (_level_from_declaration("I10", {"jpeg_quality": int(quality)})
                if encode.get("encode") == DELIVERY_ENCODE and quality else LEVEL_IDENTITY),
    }
    return {
        **levels,
        "delivered_encode": encode.get("encode"),
        "delivered_response": response.get("response"),
        "photon_gain": gain if abs(gain) > 0 else 1.0,
        "bit_depth": encode.get("bit_depth"),
        "sensor_noise_enabled": sensor_noise_enabled,
        "imaging_semantics_version": sensor.get("version"),
        "identity": (all(level == LEVEL_IDENTITY for level in levels.values())
                     and not sensor_noise_enabled),
        "stages_seen": len(stages),
    }


def realism_tags(observation: Any) -> dict[str, Any]:
    """Measured discriminators of a capture-style observation (never a claim).

    ``data_semantics`` and ``obs_semantics`` are reported from the observation because the
    pipeline writes them, but they are **not** discriminators on their own: the frozen
    generation path stamps the same values on every batch.  What separates a realistic
    observation from the historical one is the measured block below (route, renderer,
    delivered encoding, realised ladder levels, distortion handling).
    """
    meta = dict(getattr(observation, "meta", {}) or {})
    report = dict(getattr(observation, "backend_report", {}) or {})
    views = list(getattr(observation, "views", []) or [])
    labels = sorted({str(label) for view in views
                     for label in ((view.meta or {}).get("imaging_labels") or [])})
    backends = sorted({str((view.meta or {}).get("render_backend", "")) for view in views})
    policies = sorted({str(meta.get("distortion_policy", ""))})
    route = str(report.get("route") or getattr(observation, "route", ""))
    levels = realised_levels(observation)
    return {
        "schema": REALISM_SCHEMA,
        "route": route,
        "renderer": str(meta.get("renderer", "")),
        "renderer_requested": str(meta.get("renderer_requested", "")),
        "renderer_class": str(meta.get("renderer_class", "")),
        "view_render_backends": backends,
        "distortion_policy": policies[0] if policies else "",
        "imaging_labels": labels,
        "delivered_encode": levels.get("delivered_encode"),
        "realised_levels": levels,
        "data_semantics": meta.get("data_semantics"),
        "obs_semantics": meta.get("obs_semantics"),
        "scale_valid": bool(getattr(observation, "scale_valid", False)),
        "photo_mvs_failure_code": report.get("failure_code"),
        "pipeline_propagated_keys": list(PIPELINE_PROPAGATED_KEYS),
        "pipeline_ignored_config_keys": list(PIPELINE_IGNORED_CONFIG_KEYS),
    }


def is_realistic_capture(observation: Any, *, require_route: str = ROUTE_PHOTO_MVS,
                         require_renderer: str = "BLENDER_CYCLES",
                         require_non_identity_imaging: bool = True
                         ) -> tuple[bool, list[str]]:
    """Is this observation a capture-style one?  Returns ``(verdict, failing reasons)``."""
    tags = realism_tags(observation)
    reasons: list[str] = []
    if tags["route"] != require_route:
        reasons.append(f"route={tags['route']!r} != {require_route!r}")
    if require_renderer and tags["renderer"] != require_renderer:
        reasons.append(f"renderer={tags['renderer']!r} != {require_renderer!r}")
    if require_non_identity_imaging and not any(
            label in ("ISP_PROXY", "JPEG_PROXY") for label in tags["imaging_labels"]):
        reasons.append(f"imaging_labels={tags['imaging_labels']} carry no ISP/JPEG label")
    if tags["delivered_encode"] != DELIVERY_ENCODE:
        reasons.append(f"delivered encode={tags['delivered_encode']!r} != {DELIVERY_ENCODE!r}")
    return (not reasons), reasons


def run_tag(spec: Any, plan: RealismObsPlan, *, root: str, run_id: str) -> dict[str, Any]:
    """The ``meta`` block a realistic run record carries (``store.create_run``).

    This is the durable, programmatic marker of the realistic library: the pipeline writes
    ``data_semantics``/``obs_semantics`` for old and new data alike, so the run record is
    where the capture-style declaration (and the exact level assignment) is stored.
    """
    return {
        "realism": REALISM_RUN_TAG,
        "realism_schema": REALISM_SCHEMA,
        "realism_plan": plan.as_dict(),
        "data_semantics": _pipeline_data_semantics(),
        "obs_semantics": _pipeline_obs_semantics(),
        "config_spec_hash": _spec_hash(spec),
        "root": str(root),
        "run_id": str(run_id),
        "where_to_read_it": ("synlab.observe.realism.realism_tags(load_observation(store, "
                             "asset_id)); store.get_run(run_id)['meta']['realism_plan']"),
    }


def _pipeline_data_semantics() -> Any:
    try:
        from ..pipeline import data_semantics

        return data_semantics()
    except Exception:  # noqa: BLE001 - reported as absent, never invented
        return None


def _pipeline_obs_semantics() -> Any:
    try:
        from ..pipeline import OBS_SEMANTICS_V2

        return OBS_SEMANTICS_V2
    except Exception:  # noqa: BLE001
        return None


def _spec_hash(spec: Any) -> str | None:
    try:
        from ..config import compile_spec

        return compile_spec(spec).spec_hash
    except Exception:  # noqa: BLE001
        return None


def distortion_evidence(profile: Any) -> dict[str, Any]:
    """Measured pixel effect of the profile's distortion (``None`` for a clean profile)."""
    from ..cameras.viewframes import make_view_frames

    rng = np.random.default_rng(0)
    bbox = np.array([-30.0, -30.0, -20.0, 30.0, 30.0, 20.0])
    frames = make_view_frames(profile, bbox, 1, rng, tiers=("MID",), orbit=True)
    frame = frames[0]
    if not frame_has_distortion(frame):
        return {"distortion": None, "max_pixel_effect_px": None}
    return {
        "distortion": np.asarray(frame.dist, dtype=np.float64).ravel().tolist(),
        "camera_model": frame.camera_model,
        "image_size": list(frame.image_size),
        "max_pixel_effect_px": distortion_pixel_effect_px(frame),
        "measured_on": "make_view_frames(profile, bbox, 1, tiers=('MID',))",
    }


__all__ = [
    "REALISM_SCHEMA", "REALISM_RUN_TAG", "LEVELS", "LEVEL_IDENTITY", "LEVEL_REALISTIC",
    "AXIS_LEVELS", "APPLIED_AXES", "DELIVERY_ENCODE", "DELIVERY_RESPONSE", "DOWNSCALE_AXIS",
    "IDEAL_REFERENCE_GAIN", "MASK_POLICY_PIPELINE_COC", "MASK_POLICY_FOREGROUND",
    "MASK_POLICIES", "COC_THRESHOLD_UNBOUNDED_PX",
    "GEOMETRY_BY_CONSTRUCTION", "PIPELINE_PROPAGATED_KEYS", "PIPELINE_IGNORED_CONFIG_KEYS",
    "level_parameters", "normalise_levels", "imaging_spec_for", "degradation_report",
    "resolve_distortion_policy", "RealismObsPlan", "observe_spec_from_config",
    "realism_tags", "is_realistic_capture", "realised_levels", "run_tag",
    "distortion_evidence",
]
