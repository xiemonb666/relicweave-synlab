"""Fracture-local ROI close-ups: the contract's ``fracture_local_2d`` view family.

Why this module exists
----------------------
The contract asks for a **second 2D view family** next to the whole-fragment overview:

* ``capture_checklist.fracture_local_2d`` (``t042``/``p0431``/``p0881``): "逐真实断口多角度近摄；
  实际断裂表面、两侧壁、厚度变化、边缘", with ``effective_directions_per_fracture = [3, 6]``;
* ``working_distance_and_resolution.closeup_local_cm = [5, 10]`` (``p0511``): mechanical-safety
  permitting, a 5-10 cm local close-up is measured **as a separate condition** (``p1155``);
* ``structure_sampling_targets`` (``p0517``): the pilot sampling target is "0.2 mm 结构 ≥4 像素",
  explicitly *not* a measurement-accuracy promise.

Measured state before this module (``docs/a12/precision_audit.md`` §1/§7): every delivered view is
a whole-fragment view at 0.27 mm/px, so a 0.2 mm structure spans 0.74 px and the smallest
resolvable feature is 1.088 mm; the contract's close-up family did not exist at all, and
``px_per_mm``/``r_eff_mm``/``dof_cover_mm`` had **zero producers** in the repository.

What this module produces
-------------------------
1. :func:`fracture_rois` - the *measured* fracture patches of a render target: the faces whose
   ``origin_kind`` is ``ORIGIN_INTERFACE``, split by ``interface_id`` and connectivity, each with
   its area-weighted plane (centroid + outward normal), extent and **measured height-field
   statistics** (``Ra``/``Rq``/``Rz``/``Rt`` per band, see :func:`height_field_stats`).
2. :func:`make_fracture_roi_frames` - 3-6 directions per fracture: along the patch normal and at
   +/-30-60 deg to it, at the contract's 5-10 cm close-up working distance.
3. :func:`render_fracture_roi_views` - the frames rendered through
   :func:`synlab.observe.routes.render_frame_bundles`, i.e. the *same* scene/light/render/imaging
   path as the whole-fragment views (same basis) and the *same* run.
4. :func:`append_roi_views` - a new :class:`~synlab.schemas.runtime.ObservationResult` carrying the
   whole-fragment views **plus** the ROI views (a new view family, never a replacement), with the
   per-view resolution ledger ``px_per_mm`` / ``r_eff_mm`` / ``dof_cover_mm`` / ``mm_per_px``.
5. :func:`resolvability_report` - the real computation of "can the fracture relief be seen":
   the measured amplitudes of (1) evaluated at every rung of the documented resolution ladder and
   at the measured whole-fragment scale, with the **inverse solve** (which mm/px, which working
   distance, which delivered long edge, which focal length in px would be required).

Honesty rules kept by the code
------------------------------
* Nothing here upsamples an image to fake resolution: the ROI views are **rendered** at the
  requested grid, and the mm/px of every view is *measured* from that view's own depth channel
  (``median(depth_z) / K[0,0]`` of the delivered image), then cross-checked against the nominal
  ``working_distance_mm / f_px``.
* A camera condition that the declared rig cannot certify is labelled, never silently asserted:
  the close-up condition is outside the declared U travel, so it is written as
  ``CLOSEUP_DECLARED_NOT_CALIBRATED`` with the missing evidence named.
* Amplitude statistics are measured on the delivered mesh; a band with no measurable relief is
  reported with its measured value (which can be numerical-noise small) instead of an estimate.
"""

from __future__ import annotations

import copy
import json
import math
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import ORIGIN_INTERFACE, CameraProfile, ObservationResult, ViewFrame

#: Schema id of ``configs/a12/imaging_fracture_roi.yaml``.
ROI_SPEC_SCHEMA = "synlab.imaging_fracture_roi.v1"
#: Value written into ``view.meta['view_family']`` for the close-up views.
VIEW_FAMILY_WHOLE = "WHOLE_FRAGMENT"
VIEW_FAMILY_ROI = "FRACTURE_ROI"
#: Contract pointer of the two 2D families this module separates.
CONTRACT_POINTERS = {
    "whole_fragment_2d": "capture_checklist.whole_fragment_2d (t042/p0429-p0431)",
    "fracture_local_2d": "capture_checklist.fracture_local_2d (t042/p0431/p0881)",
    "closeup_distance": "working_distance_and_resolution.closeup_local_cm (p0511)",
    "sampling_target": "working_distance_and_resolution.structure_sampling_targets (p0517)",
    "separate_calibration": "calibration.global_vs_local_calibration (p1155)",
    "must_report_separately": "working_distance_and_resolution.must_report_separately (p0515)",
}
#: ``p0517`` pilot sampling target: a structure of size ``w`` should span at least this many px.
PILOT_PX_PER_STRUCTURE = 4.0
#: ``p0517`` detail goal.
DETAIL_PX_PER_STRUCTURE = 8.0
#: Contract's close-up distance window, cm -> mm.
CLOSEUP_MIN_MM, CLOSEUP_MAX_MM = 50.0, 100.0
#: Contract's per-fracture direction count.
MIN_DIRECTIONS, MAX_DIRECTIONS = 3, 6
#: Nyquist: a periodic feature needs >= 2 px per period.
NYQUIST_PX = 2.0

DEFAULT_CONFIG_PATH = "configs/a12/imaging_fracture_roi.yaml"


# ======================================================================================
# configuration
# ======================================================================================
@dataclass(frozen=True)
class FractureRoiConfig:
    """Switchable configuration of the fracture-local ROI view family (default **off**)."""

    enabled: bool = False
    #: Contract ``effective_directions_per_fracture``: 3-6 views per fracture.
    directions: int = 4
    #: Tilt of each direction away from the patch normal, degrees.  0 = along the normal,
    #: everything else 30-60 (contract "沿断口法向 ±30–60°").
    direction_offsets_deg: tuple[float, ...] = (0.0, 35.0, -35.0, 55.0, -55.0, 45.0)
    working_distance_mm: float = 60.0
    #: Delivered long edge of the close-up images (contract tier: 1024).
    resolution_ladder_px: tuple[int, ...] = (1024,)
    #: At most this many fractures per target are photographed (area-descending).
    max_fractures_per_target: int = 3
    #: A patch below either bound is not a photographer-visible fracture.
    min_patch_area_mm2: float = 25.0
    min_patch_faces: int = 24
    #: ``interface_id == -1`` faces are still ``origin_kind == ORIGIN_INTERFACE`` (born in the
    #: declared ROI band, source face carried no id).  Excluding them would drop the largest
    #: measured patches, so they are kept by default and their id is recorded verbatim.
    include_unassigned_interface_faces: bool = True
    #: Camera tier whose lens/f-number/distortion the close-up condition reuses.
    base_tier: str = "LOCAL"
    #: Resolution the inverse solve aims at (contract's tightest documented rung).
    target_mm_per_px: float = 0.039
    #: Measured height-field bands (local detrend radius, mm).
    height_bands_mm: tuple[float, ...] = (5.0, 1.0, 0.25)
    #: Rays used for the occlusion test that orients the patch normal and scores a direction.
    visibility_rays: int = 400
    #: In-plane azimuths tried per tilted direction (360 / step candidates, measured occlusion).
    azimuth_step_deg: float = 45.0
    #: A close-up needs free material-free space for the lens: the outward segment must be clear.
    require_free_optical_path: bool = True
    #: Smallest |z| of any mesh vertex in the camera frame.  Below this the Blender worker's
    #: camera self-check cannot be evaluated (float32 vs float64 on a vertex at z ~ 0), so the
    #: planner refuses the position instead of blaming the check.
    min_camera_plane_clearance_mm: float = 2.0
    #: A direction is reported as *effective* when it shows at least this many fracture pixels.
    effective_rim_px_min: int = 200
    #: Raw document (kept verbatim in the observation meta for reproducibility).
    document: Mapping[str, Any] = field(default_factory=dict)
    source_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled), "directions": int(self.directions),
            "direction_offsets_deg": [float(v) for v in self.direction_offsets_deg],
            "working_distance_mm": float(self.working_distance_mm),
            "resolution_ladder_px": [int(v) for v in self.resolution_ladder_px],
            "max_fractures_per_target": int(self.max_fractures_per_target),
            "min_patch_area_mm2": float(self.min_patch_area_mm2),
            "min_patch_faces": int(self.min_patch_faces),
            "include_unassigned_interface_faces":
                bool(self.include_unassigned_interface_faces),
            "base_tier": str(self.base_tier),
            "target_mm_per_px": float(self.target_mm_per_px),
            "height_bands_mm": [float(v) for v in self.height_bands_mm],
            "visibility_rays": int(self.visibility_rays),
            "azimuth_step_deg": float(self.azimuth_step_deg),
            "require_free_optical_path": bool(self.require_free_optical_path),
            "min_camera_plane_clearance_mm": float(self.min_camera_plane_clearance_mm),
            "effective_rim_px_min": int(self.effective_rim_px_min),
            "source_path": self.source_path,
            "schema": ROI_SPEC_SCHEMA,
        }


def _config_from_document(document: Mapping[str, Any], *, source_path: str = "") -> FractureRoiConfig:
    block = dict(document.get("fracture_roi") or {})
    if not block:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"{source_path or 'document'} has no 'fracture_roi:' block; the ROI view family is "
            f"configured there (schema {ROI_SPEC_SCHEMA})",
            stage="observe.fracture_roi.load_fracture_roi_config",
        )
    known = {
        "enabled", "directions", "direction_offsets_deg", "working_distance_mm",
        "resolution_ladder_px", "max_fractures_per_target", "min_patch_area_mm2",
        "min_patch_faces", "include_unassigned_interface_faces", "base_tier",
        "target_mm_per_px", "height_bands_mm", "visibility_rays", "effective_rim_px_min",
        "azimuth_step_deg", "require_free_optical_path", "min_camera_plane_clearance_mm",
        "contract_pointers",
    }
    unknown = sorted(set(block) - known)
    if unknown:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"unknown fracture_roi keys {unknown}; known keys are {sorted(known)}",
            stage="observe.fracture_roi.load_fracture_roi_config",
        )
    config = FractureRoiConfig(
        enabled=bool(block.get("enabled", False)),
        directions=int(block.get("directions", 4)),
        direction_offsets_deg=tuple(float(v) for v in
                                    block.get("direction_offsets_deg", (0.0, 35.0, -35.0, 55.0))),
        working_distance_mm=float(block.get("working_distance_mm", 60.0)),
        resolution_ladder_px=tuple(int(v) for v in block.get("resolution_ladder_px", (1024,))),
        max_fractures_per_target=int(block.get("max_fractures_per_target", 3)),
        min_patch_area_mm2=float(block.get("min_patch_area_mm2", 25.0)),
        min_patch_faces=int(block.get("min_patch_faces", 24)),
        include_unassigned_interface_faces=bool(
            block.get("include_unassigned_interface_faces", True)),
        base_tier=str(block.get("base_tier", "LOCAL")).upper(),
        target_mm_per_px=float(block.get("target_mm_per_px", 0.039)),
        height_bands_mm=tuple(float(v) for v in block.get("height_bands_mm", (5.0, 1.0, 0.25))),
        visibility_rays=int(block.get("visibility_rays", 400)),
        azimuth_step_deg=float(block.get("azimuth_step_deg", 45.0)),
        require_free_optical_path=bool(block.get("require_free_optical_path", True)),
        min_camera_plane_clearance_mm=float(block.get("min_camera_plane_clearance_mm", 2.0)),
        effective_rim_px_min=int(block.get("effective_rim_px_min", 200)),
        document=dict(document), source_path=str(source_path),
    )
    validate_config(config)
    return config


def validate_config(config: FractureRoiConfig) -> None:
    """Refuse a configuration the contract cannot honour (never clamp silently)."""
    problems: list[str] = []
    if not (MIN_DIRECTIONS <= config.directions <= MAX_DIRECTIONS):
        problems.append(
            f"directions={config.directions} is outside the contract's "
            f"[{MIN_DIRECTIONS}, {MAX_DIRECTIONS}] effective directions per fracture")
    if len(config.direction_offsets_deg) < config.directions:
        problems.append(
            f"direction_offsets_deg has {len(config.direction_offsets_deg)} entries but "
            f"directions={config.directions}")
    for offset in config.direction_offsets_deg[:config.directions]:
        magnitude = abs(float(offset))
        if magnitude != 0.0 and not (30.0 <= magnitude <= 60.0):
            problems.append(
                f"direction offset {offset} deg is neither 0 (along the fracture normal) nor "
                f"within +/-30-60 deg")
    if not (CLOSEUP_MIN_MM - 1e-9 <= config.working_distance_mm <= CLOSEUP_MAX_MM + 1e-9):
        problems.append(
            f"working_distance_mm={config.working_distance_mm} is outside the contract's "
            f"documented close-up window {CLOSEUP_MIN_MM:.0f}-{CLOSEUP_MAX_MM:.0f} mm (p0511)")
    if not config.resolution_ladder_px:
        problems.append("resolution_ladder_px is empty")
    for edge in config.resolution_ladder_px:
        if int(edge) < 64:
            problems.append(f"resolution_ladder_px entry {edge} is below 64 px")
    if config.max_fractures_per_target < 1:
        problems.append("max_fractures_per_target must be >= 1")
    if config.target_mm_per_px <= 0:
        problems.append("target_mm_per_px must be > 0")
    if config.base_tier not in ("GLOBAL", "MID", "LOCAL"):
        problems.append(f"base_tier {config.base_tier!r} is not a camera tier")
    if config.azimuth_step_deg <= 0 or config.azimuth_step_deg > 90:
        problems.append("azimuth_step_deg must be in (0, 90]")
    if config.min_camera_plane_clearance_mm < 0:
        problems.append("min_camera_plane_clearance_mm must be >= 0")
    if problems:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            "invalid fracture ROI configuration: " + "; ".join(problems),
            stage="observe.fracture_roi.validate_config",
            measurements={"problems": problems},
        )


def load_fracture_roi_config(path: str | Path = DEFAULT_CONFIG_PATH
                             ) -> FractureRoiConfig:
    """Load ``configs/a12/imaging_fracture_roi.yaml`` (schema-checked, fails closed)."""
    from ..config import load_document

    document = load_document(path)
    return _config_from_document(document, source_path=str(path))


# ======================================================================================
# resolution arithmetic (the "can it be seen" computation, and its inverse)
# ======================================================================================
def mm_per_px(*, working_distance_mm: float, f_px: float) -> float:
    """Object-space millimetres per delivered pixel: ``s = z / f_px`` (mm)."""
    if f_px <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"f_px must be > 0, got {f_px}",
                          stage="observe.fracture_roi.mm_per_px")
    return float(working_distance_mm) / float(f_px)


def px_per_mm(*, working_distance_mm: float, f_px: float) -> float:
    """Object-space pixels per millimetre (the contract's separately-reported quantity)."""
    return 1.0 / mm_per_px(working_distance_mm=working_distance_mm, f_px=f_px)


def r_eff_mm(*, working_distance_mm: float, f_px: float,
             k_px: float = PILOT_PX_PER_STRUCTURE) -> float:
    """Smallest *resolvable* structure size at ``k_px`` pixels: ``r_eff = k * z / f_px`` (mm).

    This is the producer the contract asks for (``p0515``: ``px_per_mm`` and ``r_eff_mm`` must be
    reported separately); ``k_px = 4`` is the ``p0517`` pilot sampling target.
    """
    return float(k_px) * mm_per_px(working_distance_mm=working_distance_mm, f_px=f_px)


def structure_px(size_mm: float, *, working_distance_mm: float, f_px: float) -> float:
    """How many pixels a structure of ``size_mm`` spans in the delivered image."""
    return float(size_mm) / mm_per_px(working_distance_mm=working_distance_mm, f_px=f_px)


def amplitude_px(amplitude_mm: float, mm_per_px_value: float) -> float:
    """How many pixels a *height* amplitude spans (lateral sampling, same scale)."""
    if mm_per_px_value <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "mm_per_px must be > 0",
                          stage="observe.fracture_roi.amplitude_px")
    return float(amplitude_mm) / float(mm_per_px_value)


def max_working_distance_mm(*, size_mm: float, f_px: float,
                            k_px: float = PILOT_PX_PER_STRUCTURE) -> float:
    """``z_max = size_mm / k_px * f_px``: the farthest distance at which ``size_mm`` spans ``k_px``."""
    return float(size_mm) / float(k_px) * float(f_px)


def required_f_px(*, size_mm: float, working_distance_mm: float,
                  k_px: float = PILOT_PX_PER_STRUCTURE) -> float:
    """``f_px = k_px * z / size_mm``: the focal length in pixels needed at that distance."""
    if size_mm <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "size_mm must be > 0",
                          stage="observe.fracture_roi.required_f_px")
    return float(k_px) * float(working_distance_mm) / float(size_mm)


def required_long_edge_px(*, size_mm: float, working_distance_mm: float, native_width_px: int,
                          f_px_native: float, k_px: float = PILOT_PX_PER_STRUCTURE) -> float:
    """Delivered long edge that realizes :func:`required_f_px` for the *same* lens.

    A delivered grid of ``L`` px scales the native intrinsics by ``L / native_width_px``
    (a declared crop+resize, not a digital zoom), so ``f_px(L) = f_px_native * L / native_width``.
    """
    need = required_f_px(size_mm=size_mm, working_distance_mm=working_distance_mm, k_px=k_px)
    if f_px_native <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "f_px_native must be > 0",
                          stage="observe.fracture_roi.required_long_edge_px")
    return need * float(native_width_px) / float(f_px_native)


def dof_report(*, working_distance_mm: float, focal_length_mm: float, f_number: float,
               pixel_pitch_mm: float, coc_px: float = 2.0) -> dict[str, float]:
    """Thin-lens depth of field of one camera condition, plus its millimetre cover.

    ``dof_cover_mm`` is the contract's ``景深覆盖`` field: ``far - near`` in object space.
    """
    from ..cameras.profiles import thin_lens_dof

    near, far = thin_lens_dof(working_distance_mm, focal_length_mm, f_number, coc_px,
                              pixel_pitch_mm)
    finite_far = float(far) if math.isfinite(float(far)) else float(far)
    cover = (finite_far - float(near)) if math.isfinite(finite_far) else math.inf
    return {
        "near_mm": float(near), "far_mm": finite_far, "dof_cover_mm": cover,
        "coc_px": float(coc_px), "pixel_pitch_mm": float(pixel_pitch_mm),
        "focal_length_mm": float(focal_length_mm), "f_number": float(f_number),
        "working_distance_mm": float(working_distance_mm),
    }


# ======================================================================================
# the documented ladder + the measured state it is compared with
# ======================================================================================
def documented_ladder() -> dict[str, Any]:
    """The contract's resolution ladder, recomputed from the declared pinhole formula.

    Values come from ``synlab.degrade.specs.capture_rig_spec()`` (which encodes ``t051``/
    ``p0518``) and are cross-checked against ``configs/a12/capture_contract.json``: a mismatch is
    reported in ``cross_check`` instead of being hidden.
    """
    from ..degrade.specs import capture_rig_spec

    rig = capture_rig_spec()
    camera = rig.camera
    rows = []
    for distance in sorted(int(k) for k in camera.resolution_mm_per_px):
        value = camera.mm_per_px_value(distance)
        s = float(value.value)
        rows.append({
            "distance_mm": float(distance),
            "mm_per_px": s,
            "px_per_mm": 1.0 / s,
            "structure_0p2mm_px": 0.2 / s,
            "r_eff_4px_mm": r_eff_mm(working_distance_mm=distance,
                                     f_px=1.0 / s * distance),
            "provenance": value.provenance,
            "source": value.ref,
        })
    cross_check: dict[str, Any] = {"status": "NOT_READ"}
    try:
        contract = json.loads((Path(__file__).resolve().parents[2]
                               / "configs/a12/capture_contract.json").read_text(encoding="utf-8"))
        contract_rows = contract["working_distance_and_resolution"]["resolution_table"]["rows"]
        mismatch = []
        for declared in contract_rows:
            match = next((r for r in rows if abs(r["distance_mm"] - declared["distance_mm"]) < 1e-9),
                         None)
            if match is None:
                mismatch.append({"distance_mm": declared["distance_mm"], "why": "no computed row"})
            elif abs(match["mm_per_px"] - float(declared["mm_per_px"])) > 1e-12:
                mismatch.append({"distance_mm": declared["distance_mm"],
                                 "declared": declared["mm_per_px"],
                                 "computed": match["mm_per_px"]})
        cross_check = {"status": "OK" if not mismatch else "MISMATCH", "rows": mismatch}
    except Exception as exc:  # noqa: BLE001 - the cross-check must never break a measurement
        cross_check = {"status": "UNREADABLE", "error": str(exc)[:200]}
    return {
        "rows": rows,
        "focal_px_native": float(camera.focal_px),
        "sensor_width_px": int(camera.sensor_width_px.value),
        "pixel_pitch_mm": float(camera.pixel_pitch_mm.value),
        "fov_h_deg": float(camera.fov_h_deg.value),
        "contract_cross_check": cross_check,
        "closeup_window_mm": [CLOSEUP_MIN_MM, CLOSEUP_MAX_MM],
        "source": "configs/a12/capture_contract.json working_distance_and_resolution (t051/p0518)",
    }


def shading_contrast(*, amplitude_mm: float, wavelength_mm: float,
                     light_direction: Sequence[float], light_color: Sequence[float],
                     ambient: Sequence[float], albedo: float = 0.55,
                     bit_depth: int = 8, quantisation_levels: float | None = None
                     ) -> dict[str, Any]:
    """Would the relief change the *RGB* of a rendered pixel by at least one code value?

    The renderer's frozen shading model is Lambert + ambient (``synlab.observe.render``): a
    surface height field ``h`` tilts the normal, and the Lambert term changes by
    ``|dl/dn| * slope``.  With one representative wavelength ``lambda`` per band and an RMS
    amplitude ``A``, the RMS slope is ``2 pi A / lambda``.  The resulting code-value step is

        ``dDN = levels * albedo * light_color * |light_perp| * slope``

    which is compared with the 1-code-value quantisation floor.  This is the criterion that
    decides whether a *sub-pixel-lateral* roughness is still visible as image texture: shading
    does not need 4 px per feature, but it does need the height field to exist.
    """
    a = float(amplitude_mm)
    lam = float(wavelength_mm)
    if lam <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "wavelength_mm must be > 0",
                          stage="observe.fracture_roi.shading_contrast")
    direction = np.asarray(light_direction, dtype=np.float64).reshape(3)
    direction = direction / max(float(np.linalg.norm(direction)), 1e-30)
    color = np.asarray(light_color, dtype=np.float64).reshape(3)
    amb = np.asarray(ambient, dtype=np.float64).reshape(3)
    levels = float(quantisation_levels if quantisation_levels is not None
                   else ((1 << int(bit_depth)) - 1))
    slope = 2.0 * math.pi * a / lam
    perpendicular = float(math.sqrt(max(0.0, 1.0 - float(direction[2]) ** 2)))
    delta_lambert = perpendicular * slope
    delta_dn = levels * float(albedo) * float(np.mean(color)) * delta_lambert
    return {
        "amplitude_mm": a, "wavelength_mm": lam, "slope_rms": slope,
        "light_perpendicular_component": perpendicular,
        "delta_lambert": delta_lambert, "delta_code_value": delta_dn,
        "code_value_floor": 1.0, "bit_depth": int(bit_depth),
        "visible_in_rgb": bool(delta_dn >= 1.0),
        "convention": ("one representative wavelength lambda per band; RMS amplitude A; "
                       "slope_rms = 2 pi A / lambda; frozen Lambert+ambient shading model of "
                       "synlab.observe.render"),
    }


def resolvability_report(*, mm_per_px_values: Mapping[str, float],
                         amplitudes_mm: Mapping[str, float],
                         k_px: float = PILOT_PX_PER_STRUCTURE) -> dict[str, Any]:
    """Evaluate every measured amplitude at every given mm/px (the "can it be seen" table).

    For each ``(rung, amplitude)``: the amplitude in pixels, the lateral-resolvability verdict
    (``>= k_px``) and the Nyquist verdict.  Nothing is interpolated or assumed.
    """
    table: dict[str, Any] = {}
    for rung, s in mm_per_px_values.items():
        entry: dict[str, Any] = {
            "mm_per_px": float(s),
            "px_per_mm": 1.0 / float(s),
            "smallest_resolvable_4px_mm": float(k_px) * float(s),
            "smallest_resolvable_8px_mm": DETAIL_PX_PER_STRUCTURE * float(s),
            "structure_0p2mm_px": 0.2 / float(s),
            "amplitudes": {},
        }
        for name, amp in amplitudes_mm.items():
            px = amplitude_px(amp, float(s))
            entry["amplitudes"][name] = {
                "amplitude_mm": float(amp),
                "amplitude_px": px,
                "lateral_resolved_4px": bool(px >= k_px),
                "nyquist_2px": bool(px >= NYQUIST_PX),
            }
        table[str(rung)] = entry
    return {
        "k_px_pilot": float(k_px),
        "k_px_detail": DETAIL_PX_PER_STRUCTURE,
        "nyquist_px": NYQUIST_PX,
        "rule": ("an amplitude is visible only when it spans >= 4 px (p0517 pilot target); "
                 "2 px is the Nyquist floor, not a visibility claim"),
        "table": table,
    }


def inverse_solve(*, amplitude_mm: float, k_px: float = PILOT_PX_PER_STRUCTURE,
                  working_distance_mm: float | None = None,
                  f_px_delivered: float | None = None,
                  f_px_native: float | None = None, native_width_px: int | None = None,
                  long_edge_px: int | None = None,
                  closeup_window_mm: tuple[float, float] = (CLOSEUP_MIN_MM, CLOSEUP_MAX_MM)
                  ) -> dict[str, Any]:
    """Solve "what would it take to see an amplitude of ``amplitude_mm``" in closed form.

    Returns the required object-space scale, the required ``f_px`` at a given working distance,
    the required delivered long edge at a given lens, the farthest working distance at a given
    delivered ``f_px``, and the verdict of the contract's own 5-10 cm window.
    """
    if amplitude_mm <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "amplitude_mm must be > 0",
                          stage="observe.fracture_roi.inverse_solve")
    need_s = float(amplitude_mm) / float(k_px)
    out: dict[str, Any] = {
        "amplitude_mm": float(amplitude_mm), "k_px": float(k_px),
        "required_mm_per_px": need_s, "required_px_per_mm": 1.0 / need_s,
    }
    if working_distance_mm is not None:
        out["required_f_px_at_working_distance"] = required_f_px(
            size_mm=amplitude_mm, working_distance_mm=working_distance_mm, k_px=k_px)
    if f_px_delivered is not None:
        out["max_working_distance_mm"] = max_working_distance_mm(
            size_mm=amplitude_mm, f_px=f_px_delivered, k_px=k_px)
        if working_distance_mm is not None:
            out["realized_mm_per_px"] = mm_per_px(working_distance_mm=working_distance_mm,
                                                  f_px=f_px_delivered)
            out["realized_amplitude_px"] = amplitude_px(
                amplitude_mm, out["realized_mm_per_px"])
            out["visible_at_working_distance"] = bool(
                out["realized_amplitude_px"] >= k_px)
    if f_px_native is not None and native_width_px is not None:
        if working_distance_mm is not None:
            out["required_long_edge_px"] = required_long_edge_px(
                size_mm=amplitude_mm, working_distance_mm=working_distance_mm,
                native_width_px=int(native_width_px), f_px_native=float(f_px_native), k_px=k_px)
        if long_edge_px is not None:
            f_px_l = float(f_px_native) * float(long_edge_px) / float(native_width_px)
            out["f_px_at_long_edge"] = f_px_l
            out["max_working_distance_mm_at_long_edge"] = max_working_distance_mm(
                size_mm=amplitude_mm, f_px=f_px_l, k_px=k_px)
    lo, hi = closeup_window_mm
    verdicts = {}
    for label, distance in (("near", lo), ("far", hi)):
        f_need = required_f_px(size_mm=amplitude_mm, working_distance_mm=distance, k_px=k_px)
        entry = {"working_distance_mm": float(distance), "required_f_px": f_need}
        if f_px_native is not None and native_width_px is not None:
            entry["required_long_edge_px"] = (
                f_need * float(native_width_px) / float(f_px_native))
        verdicts[label] = entry
    out["closeup_window_verdict"] = verdicts
    return out


# ======================================================================================
# measured height field of a fracture patch
# ======================================================================================
def height_field_stats(heights: np.ndarray, points: np.ndarray,
                       bands_mm: Sequence[float] = (5.0, 1.0, 0.25)) -> dict[str, Any]:
    """Amplitude statistics of a patch height field, per *band*.

    ``heights`` is the signed distance of the patch sample points from the patch's own
    area-weighted plane; ``points`` are those sample points (3-D, mm).  For every radius ``R``
    in ``bands_mm`` the field is locally detrended (the mean height of the samples inside a ball
    of radius ``R`` is subtracted), which separates

    * ``plane``: the whole-patch residual to the fitted plane (form + waviness + roughness), and
    * ``below_R_mm``: only what survives at scales **smaller** than ``R`` (waviness/roughness).

    All numbers are measured on the delivered mesh; nothing is modelled.
    """
    h = np.asarray(heights, dtype=np.float64).reshape(-1)
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if h.size != p.shape[0]:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"heights {h.shape} and points {p.shape} disagree",
                          stage="observe.fracture_roi.height_field_stats")
    out: dict[str, Any] = {"n_samples": int(h.size), "bands": {}}

    def stats(values: np.ndarray) -> dict[str, float]:
        v = np.asarray(values, dtype=np.float64).reshape(-1)
        if v.size == 0:
            return {"Ra_mm": 0.0, "Rq_mm": 0.0, "Rz_mm": 0.0, "Rt_mm": 0.0, "n": 0}
        a = np.abs(v)
        order = np.argsort(v)
        k = max(1, int(round(0.10 * v.size)))
        return {
            "n": int(v.size), "Ra_mm": float(a.mean()),
            "Rq_mm": float(np.sqrt((v ** 2).mean())),
            "Rz_mm": float(v[order[-k:]].mean() - v[order[:k]].mean()),
            "Rt_mm": float(v.max() - v.min()), "mean_mm": float(v.mean()),
            "p95_abs_mm": float(np.percentile(a, 95)),
        }

    out["plane"] = stats(h)
    if h.size >= 8:
        from scipy.spatial import cKDTree

        tree = cKDTree(p)
        for radius in sorted((float(r) for r in bands_mm), reverse=True):
            local = tree.query_ball_point(p, float(radius))
            means = np.array([h[idx].mean() if len(idx) else h[i]
                              for i, idx in enumerate(local)], dtype=np.float64)
            out["bands"][f"below_{radius:g}mm"] = stats(h - means)
    return out


# ======================================================================================
# fracture patches of a render target
# ======================================================================================
@dataclass
class FractureRoi:
    """One measured fracture ROI of a render target (the part a close-up actually frames)."""

    roi_id: str
    interface_id: int
    component_id: int
    n_faces: int
    area_mm2: float
    centroid_mm: np.ndarray
    normal: np.ndarray
    radius_p50_mm: float
    radius_p95_mm: float
    radius_max_mm: float
    height: dict[str, Any]
    normal_sign_source: str = "UNKNOWN"
    visibility_fraction: float = float("nan")
    #: The whole contiguous patch the ROI was cut out of (context for the *area* share).
    parent_n_faces: int = 0
    parent_area_mm2: float = 0.0
    parent_radius_p95_mm: float = float("nan")
    #: Close-up footprint radius the ROI was cut with (``None`` = the whole patch was used).
    footprint_radius_mm: float | None = None
    aim_mm: np.ndarray | None = None
    #: Normal of the faces inside the footprint (local), next to the patch's own plane normal.
    local_normal: np.ndarray | None = None
    #: Subsample of the ROI's measured surface points (mm), used for occlusion measurements.
    #: Never serialised: it is the instrument input, not a reported quantity.
    sample_points: np.ndarray | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "roi_id": self.roi_id, "interface_id": int(self.interface_id),
            "component_id": int(self.component_id), "n_faces": int(self.n_faces),
            "area_mm2": float(self.area_mm2),
            "centroid_mm": [float(v) for v in self.centroid_mm],
            "normal": [float(v) for v in self.normal],
            "local_normal": (None if self.local_normal is None
                             else [float(v) for v in self.local_normal]),
            "aim_mm": None if self.aim_mm is None else [float(v) for v in self.aim_mm],
            "radius_p50_mm": float(self.radius_p50_mm),
            "radius_p95_mm": float(self.radius_p95_mm),
            "radius_max_mm": float(self.radius_max_mm),
            "parent_n_faces": int(self.parent_n_faces),
            "parent_area_mm2": float(self.parent_area_mm2),
            "parent_radius_p95_mm": float(self.parent_radius_p95_mm),
            "footprint_radius_mm": self.footprint_radius_mm,
            "height": self.height,
            "normal_sign_source": str(self.normal_sign_source),
            "visibility_fraction": float(self.visibility_fraction),
        }


def _face_components(faces: np.ndarray) -> np.ndarray:
    """Connected components of a triangle soup (faces sharing an edge are the same component)."""
    from collections import defaultdict

    n = len(faces)
    edges: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (a, b, c) in enumerate(faces):
        for u, v in ((a, b), (b, c), (c, a)):
            edges[(min(u, v), max(u, v))].append(i)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for members in edges.values():
        root = find(members[0])
        for other in members[1:]:
            r2 = find(other)
            if r2 != root:
                parent[max(root, r2)] = min(root, r2)
                root = find(root)
    roots = np.array([find(i) for i in range(n)], dtype=np.int64)
    _, labels = np.unique(roots, return_inverse=True)
    return labels


def _visible_fraction(mesh: Any, eye: np.ndarray, targets: np.ndarray) -> float:
    """Fraction of ``targets`` that are not occluded from ``eye`` (measured by ray casting)."""
    if targets.size == 0:
        return float("nan")
    directions = targets - eye.reshape(1, 3)
    distance = np.linalg.norm(directions, axis=1)
    ok = distance > 1e-9
    if not bool(ok.any()):
        return float("nan")
    directions = directions[ok] / distance[ok].reshape(-1, 1)
    origins = np.repeat(eye.reshape(1, 3), directions.shape[0], axis=0)
    try:
        hit = mesh.ray.intersects_location(origins, directions, multiple_hits=False)
    except Exception:  # noqa: BLE001 - a mesh without an intersector must not fake a verdict
        return float("nan")
    # trimesh changed the arity of this return value between releases (5.x adds index_tri), so the
    # first two entries are taken by position instead of by unpacking a fixed tuple
    if len(hit) < 2:
        return float("nan")
    locations, index_ray = np.asarray(hit[0]), np.asarray(hit[1], dtype=np.int64).reshape(-1)
    hit_distance = np.full(directions.shape[0], np.inf)
    if index_ray.size:
        delta = locations - origins[index_ray]
        hit_distance[index_ray] = np.linalg.norm(delta, axis=1)
    return float(np.mean(hit_distance >= (distance[ok] - 1e-6)))


def fracture_rois(target: Any, config: FractureRoiConfig, *,
                  footprint_radius_mm: float | None = None) -> list[FractureRoi]:
    """Measure the fracture ROIs of ``target`` (``origin_kind == ORIGIN_INTERFACE``).

    Faces are grouped by ``interface_id`` and then by connectivity, so a "patch" is a contiguous
    piece of fracture surface with one declared interface id - which is what a close-up can be
    aimed at.  When ``footprint_radius_mm`` is given (the half-width of the close-up field of
    view), the ROI is the part of the patch **inside that footprint**, aimed at the patch medoid:
    the reported ``area_mm2``/``radius``/``height`` then describe what the camera actually frames,
    while the whole patch is kept as ``parent_*`` for context.  The normal comes from the face
    normal at the aim point and its sign is chosen by an occlusion measurement (rays from both
    candidate camera positions), never by a guess; ``normal_sign_source`` records the instrument.
    """
    mesh = target.mesh
    faces = np.asarray(mesh.faces)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    kind = getattr(target, "face_origin_kind", None)
    interface = None
    attrs = dict((getattr(mesh, "metadata", None) or {}).get("face_attr_arrays") or {})
    if "interface_id" in attrs:
        interface = np.asarray(attrs["interface_id"]).reshape(-1)
    if kind is None:
        raise SynLabError(
            ErrorCode.INPUT_UNAVAILABLE,
            "the render target carries no face origin_kind channel; the fracture faces cannot be "
            "identified and no ROI view can be aimed (resolve the target with its face "
            "provenance first)",
            stage="observe.fracture_roi.fracture_rois",
            measurements={"fragment_id": str(getattr(target, "fragment_id", ""))},
        )
    kind = np.asarray(kind).reshape(-1)
    if interface is None:
        interface = np.full(len(faces), -1, dtype=np.int64)
    sel = kind == ORIGIN_INTERFACE
    if not config.include_unassigned_interface_faces:
        sel = sel & (interface >= 0)
    if not bool(sel.any()):
        return []
    face_area = np.asarray(mesh.area_faces, dtype=np.float64)
    body_centre = verts.mean(axis=0)
    idx = np.flatnonzero(sel)
    subsoup = faces[idx]
    comp = _face_components(subsoup)
    rng = np.random.default_rng(20261001)
    raw: list[dict[str, Any]] = []
    for iid in sorted({int(v) for v in np.unique(interface[idx])}):
        id_mask = interface[idx] == iid
        for comp_id in sorted({int(v) for v in np.unique(comp[id_mask])}):
            mask = id_mask & (comp == comp_id)
            sub_faces = idx[mask]
            if sub_faces.size < int(config.min_patch_faces):
                continue
            area = float(face_area[sub_faces].sum())
            if area < float(config.min_patch_area_mm2):
                continue
            tri = verts[faces[sub_faces]]
            centroids = tri.mean(axis=1)
            w = np.maximum(face_area[sub_faces], 1e-12)
            w = w / w.sum()
            centroid = (centroids * w[:, None]).sum(axis=0)
            q = centroids - centroid
            cov = (q * w[:, None]).T @ q
            values, vectors = np.linalg.eigh(cov)
            normal = vectors[:, int(np.argmin(values))]
            normal = normal / max(float(np.linalg.norm(normal)), 1e-30)
            if float(np.dot(normal, centroid - body_centre)) < 0.0:
                normal = -normal
            radius = np.linalg.norm(q, axis=1)
            # aim at the densest measured point of the patch (the medoid), so the camera is
            # pointed at real fracture surface instead of at a void inside a curved band
            d2 = ((centroids[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2) \
                if centroids.shape[0] <= 1500 else None
            if d2 is not None:
                medoid = int(np.argmin(d2.sum(axis=1)))
            else:
                medoid = int(np.argmin(np.linalg.norm(centroids - centroid, axis=1)))
            raw.append({
                "interface_id": iid, "component_id": comp_id, "faces": sub_faces,
                "area_mm2": area, "centroid": centroid, "normal": normal,
                "points": centroids, "radius": radius, "medoid": medoid,
                "face_normals": np.asarray(mesh.face_normals, dtype=np.float64)[sub_faces],
                "face_area": face_area[sub_faces],
            })
    raw.sort(key=lambda item: -float(item["area_mm2"]))
    raw = raw[:int(config.max_fractures_per_target)]
    rois: list[FractureRoi] = []
    for item in raw:
        normal = np.asarray(item["normal"], dtype=np.float64)
        points = np.asarray(item["points"], dtype=np.float64)
        aim = points[int(item["medoid"])].copy()
        sub_faces = np.asarray(item["faces"])
        footprint = None
        if footprint_radius_mm is not None and float(footprint_radius_mm) > 0:
            inside = np.linalg.norm(points - aim.reshape(1, 3), axis=1) <= float(footprint_radius_mm)
            if int(inside.sum()) >= int(config.min_patch_faces):
                footprint = float(footprint_radius_mm)
                sub_faces = sub_faces[inside]
                points = points[inside]
        face_area_local = np.asarray(mesh.area_faces, dtype=np.float64)[sub_faces]
        w = np.maximum(face_area_local, 1e-12)
        w = w / w.sum()
        centroid = (points * w[:, None]).sum(axis=0)
        q = points - centroid
        cov = (q * w[:, None]).T @ q
        values, vectors = np.linalg.eigh(cov)
        plane_normal = vectors[:, int(np.argmin(values))]
        plane_normal = plane_normal / max(float(np.linalg.norm(plane_normal)), 1e-30)
        if float(np.dot(plane_normal, centroid - body_centre)) < 0.0:
            plane_normal = -plane_normal
        local_normals = np.asarray(mesh.face_normals, dtype=np.float64)[sub_faces]
        local_normal = (local_normals * w[:, None]).sum(axis=0)
        local_normal = local_normal / max(float(np.linalg.norm(local_normal)), 1e-30)
        aim_face = int(np.argmin(np.linalg.norm(points - aim.reshape(1, 3), axis=1))) \
            if footprint is not None else 0
        aim_normal = np.asarray(mesh.face_normals, dtype=np.float64)[sub_faces[aim_face]]
        normal = aim_normal / max(float(np.linalg.norm(aim_normal)), 1e-30)
        if float(np.dot(normal, plane_normal)) < 0.0:
            normal = -normal
        # -- normal sign by occlusion measurement (two candidate camera positions)
        sample = points if points.shape[0] <= int(config.visibility_rays) else \
            points[rng.choice(points.shape[0], size=int(config.visibility_rays), replace=False)]
        radius_sample = np.linalg.norm(points - aim.reshape(1, 3), axis=1)
        probe_distance = max(float(np.percentile(radius_sample, 95)) * 3.0,
                             float(config.working_distance_mm))
        sign_source = "OUTWARD_FROM_BODY_CENTROID"
        fraction = float("nan")
        best_sign, best_fraction = 1.0, -1.0
        for sign in (1.0, -1.0):
            eye = aim + sign * probe_distance * normal
            value = _visible_fraction(mesh, eye, sample)
            if math.isfinite(value) and value > best_fraction:
                best_sign, best_fraction = sign, value
        if best_fraction >= 0.0:
            normal = best_sign * normal
            fraction = best_fraction
            sign_source = "OCCLUSION_RAYCAST_TWO_SIGNS"
        heights = (points - centroid) @ normal
        radius = np.linalg.norm(points - centroid, axis=1)
        sample_points = (points if points.shape[0] <= int(config.visibility_rays)
                         else points[rng.choice(points.shape[0],
                                                size=int(config.visibility_rays),
                                                replace=False)])
        # the aim point is the pixel the camera is pointed at, so it must be part of every
        # visibility measurement (a random subsample of the patch can miss it, and then "the ROI
        # is visible" would not say anything about the aimed pixel)
        if float(np.min(np.linalg.norm(sample_points - aim.reshape(1, 3), axis=1))) > 1e-9:
            sample_points = np.vstack([aim.reshape(1, 3), sample_points])
        rois.append(FractureRoi(
            roi_id=f"iface{item['interface_id']:d}_c{item['component_id']:03d}",
            interface_id=int(item["interface_id"]), component_id=int(item["component_id"]),
            n_faces=int(sub_faces.size), area_mm2=float(face_area_local.sum()),
            centroid_mm=centroid, normal=normal,
            radius_p50_mm=float(np.percentile(radius, 50)),
            radius_p95_mm=float(np.percentile(radius, 95)),
            radius_max_mm=float(radius.max()),
            height=height_field_stats(heights, points, config.height_bands_mm),
            normal_sign_source=sign_source, visibility_fraction=fraction,
            parent_n_faces=int(np.asarray(item["faces"]).size),
            parent_area_mm2=float(item["area_mm2"]),
            parent_radius_p95_mm=float(np.percentile(np.asarray(item["radius"]), 95)),
            footprint_radius_mm=footprint, aim_mm=aim, local_normal=local_normal,
            sample_points=sample_points,
        ))
    return rois


# ======================================================================================
# the close-up camera condition
# ======================================================================================
def delivered_profile(base: CameraProfile, *, long_edge_px: int) -> CameraProfile:
    """The same optical condition *delivered* on a ``long_edge_px`` grid (aspect preserved).

    A real camera of the declared node outputs an image at its own resolution; this helper
    expresses the delivered grid as the camera's grid, so the render grid and the delivered grid
    are the same and no crop/resize sits between the render and the measurement
    (``pixel_affine_A = identity``).  ``fx == fy`` holds exactly, which the Blender worker
    requires, and the pixel scale is unchanged by construction (``z / f_px`` with ``f_px`` scaled
    by the same factor as the grid).
    """
    width, height = int(base.image_size[0]), int(base.image_size[1])
    long_edge = int(long_edge_px)
    if long_edge < 64:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"long_edge_px {long_edge} is too small",
                          stage="observe.fracture_roi.delivered_profile")
    scale = float(long_edge) / float(width)
    out_w = long_edge
    out_h = max(int(round(height * scale)), 1)
    K = np.asarray(base.K, dtype=np.float64).copy() * scale
    K[2, 2] = 1.0
    K[0, 2] = out_w / 2.0 - 0.5
    K[1, 2] = out_h / 2.0 - 0.5
    sensor_width_mm = float(base.meta.get("sensor_width_mm", 7.6))
    dof = dof_report(working_distance_mm=float(base.working_distance_mm),
                     focal_length_mm=float(base.meta.get("focal_length_mm", 6.1)),
                     f_number=float(base.f_number),
                     pixel_pitch_mm=sensor_width_mm / float(out_w),
                     coc_px=float(base.meta.get("coC_px", 2.0)))
    meta = dict(base.meta)
    meta.update({
        "delivered_from_profile": base.profile_id,
        "native_image_size": [width, height],
        "delivered_image_size": [out_w, out_h],
        "delivered_long_edge_px": long_edge,
        "delivered_scale": scale,
        "f_px_native_equivalent": float(np.asarray(base.K, dtype=np.float64)[0, 0]),
        "mm_per_pixel": float(base.working_distance_mm) / float(K[0, 0]),
        "px_per_mm": float(K[0, 0]) / float(base.working_distance_mm),
        "r_eff_mm": r_eff_mm(working_distance_mm=float(base.working_distance_mm),
                             f_px=float(K[0, 0])),
        "dof_cover_mm": dof["dof_cover_mm"],
        "depth_of_field_mm": [dof["near_mm"], dof["far_mm"]],
        "pixel_affine_is_identity": True,
    })
    return replace(
        base, profile_id=f"{base.profile_id}_D{long_edge}", K=K, image_size=(out_w, out_h),
        fov_mm=(float(base.working_distance_mm) * out_w / float(K[0, 0]),
                float(base.working_distance_mm) * out_h / float(K[1, 1])),
        depth_of_field_mm=(dof["near_mm"], dof["far_mm"]), meta=meta,
    )


def closeup_profile(config: FractureRoiConfig, *, base: CameraProfile | None = None,
                    delivered_long_edge_px: int | None = None) -> CameraProfile:
    """The fracture close-up camera condition (same node/lens, 5-10 cm object distance).

    The declared U travel of the rig does not reach a 5-10 cm object distance, so this is a
    *separate* condition (``p1155``: global and fracture close-up are two calibration
    conditions).  It is therefore marked ``CLOSEUP_DECLARED_NOT_CALIBRATED`` and the missing
    evidence is named in ``meta['pending']`` - the geometry of the render, however, is exact.

    ``delivered_long_edge_px`` fixes the sampling pitch the depth-of-field criterion is expressed
    at (``pitch = sensor_width / long_edge``), so the reported ``dof_cover_mm`` belongs to the
    image that is actually delivered rather than to the sensor's native grid.  Both grids are
    reported.
    """
    from ..cameras.profiles import camera_profiles

    if base is None:
        base = next((p for p in camera_profiles() if p.tier == config.base_tier), None)
    if base is None:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          f"no camera profile of tier {config.base_tier!r}",
                          stage="observe.fracture_roi.closeup_profile")
    z = float(config.working_distance_mm)
    width, height = int(base.image_size[0]), int(base.image_size[1])
    long_edge = int(delivered_long_edge_px or max(config.resolution_ladder_px))
    sensor_width_mm = float(base.meta.get("sensor_width_mm", 7.6))
    focal_mm = float(base.meta.get("focal_length_mm", 6.1))
    f_px_native = float(base.K[0, 0])
    coc_px = float(base.meta.get("coC_px", 2.0))
    dof = dof_report(working_distance_mm=z, focal_length_mm=focal_mm,
                     f_number=float(base.f_number),
                     pixel_pitch_mm=sensor_width_mm / float(long_edge), coc_px=coc_px)
    dof_native = dof_report(working_distance_mm=z, focal_length_mm=focal_mm,
                            f_number=float(base.f_number),
                            pixel_pitch_mm=sensor_width_mm / float(width), coc_px=coc_px)
    meta = dict(base.meta)
    meta.update({
        "fracture_closeup_condition": True,
        "calibration_status": "CLOSEUP_DECLARED_NOT_CALIBRATED",
        "u_move_forbidden": ["image_resize", "digital_crop", "digital_zoom"],
        "closeup_source": CONTRACT_POINTERS["closeup_distance"],
        "separate_calibration": CONTRACT_POINTERS["separate_calibration"],
        "declared_u_travel_mm": list(base.meta.get("u_travel_mm") or []),
        "u_travel_exceeded": True,
        "u_travel_note": ("a 5-10 cm object distance is outside the declared U travel of every "
                          "tier; the contract documents the close-up as a separate, "
                          "mechanical-safety-permitting condition (p0511/p1155)"),
        "depth_of_field_mm": [dof["near_mm"], dof["far_mm"]],
        "dof_cover_mm": dof["dof_cover_mm"],
        "dof_report": dof,
        "dof_grid": f"delivered long edge {long_edge} px (pitch {sensor_width_mm / long_edge:.6f} mm)",
        "dof_cover_native_grid_mm": dof_native["dof_cover_mm"],
        "dof_cover_native_grid_mm_is_not_delivered": True,
        "pending": list(base.meta.get("pending") or []) + [
            "CLOSEUP_CALIBRATION_PENDING: no target image at 5-10 cm exists in this repository",
        ],
    })
    native = CameraProfile(
        profile_id=f"{base.profile_id}_ROI{int(round(z))}mm",
        revision=int(base.revision), tier=base.tier, working_distance_mm=z,
        u_position_mm=float(base.u_position_mm) + (float(base.working_distance_mm) - z),
        K=np.asarray(base.K, dtype=np.float64).copy(),
        dist=np.asarray(base.dist, dtype=np.float64).copy(),
        image_size=(width, height),
        fov_mm=(z * width / f_px_native, z * height / f_px_native),
        depth_of_field_mm=(dof["near_mm"], dof["far_mm"]),
        focus_setting=f"{base.focus_setting}@CLOSEUP{int(round(z))}mm",
        calibration_refs=list(base.calibration_refs), calibrated=False,
        action_cost_seconds=float(base.action_cost_seconds),
        f_number=float(base.f_number), meta=meta,
    )
    if delivered_long_edge_px is None:
        return native
    return delivered_profile(native, long_edge_px=int(delivered_long_edge_px))


def outward_clearance_mm(mesh: Any, aim: np.ndarray, direction: np.ndarray,
                         max_distance_mm: float) -> tuple[float, dict[str, Any]]:
    """How far the free line of sight runs outwards from ``aim`` along ``direction`` (mm).

    A real close-up needs a place to put the lens: the segment from the fracture surface outwards
    must be free of material for at least the working distance.  Measured by ray casting from just
    off the surface (the first hit is the material the ray leaves from, so hits at ``t <= 0`` are
    dropped).
    """
    origin = np.asarray(aim, dtype=np.float64).reshape(1, 3) + 1e-6 * np.asarray(
        direction, dtype=np.float64).reshape(1, 3)
    d = np.asarray(direction, dtype=np.float64).reshape(1, 3)
    d = d / max(float(np.linalg.norm(d)), 1e-30)
    try:
        hit = mesh.ray.intersects_location(origin, d, multiple_hits=True)
    except Exception as exc:  # noqa: BLE001
        return float("nan"), {"status": "RAYCAST_FAILED", "error": str(exc)[:160]}
    locations = np.asarray(hit[0], dtype=np.float64) if len(hit) else np.zeros((0, 3))
    if locations.shape[0] == 0:
        return float(max_distance_mm), {"status": "OK", "hits": 0}
    distance = np.sort(np.linalg.norm(locations - origin, axis=1))
    distance = distance[distance > 1e-3]
    if distance.size == 0:
        return float(max_distance_mm), {"status": "OK", "hits": 0}
    return float(distance[0]), {"status": "OK", "hits": int(distance.size),
                               "first_hit_mm": float(distance[0])}


def point_inside_mesh(mesh: Any, point: np.ndarray) -> bool | None:
    """Ray-parity inside test (odd number of crossings along one ray = inside).

    ``None`` when the mesh exposes no intersector: the answer is then *unknown* rather than
    guessed.  A non-watertight mesh makes the parity test unreliable, which is why the caller
    records the instrument instead of treating the verdict as ground truth.
    """
    direction = np.array([0.5773502691896258, 0.5773502691896258, 0.5773502691896258])
    try:
        hit = mesh.ray.intersects_location(np.asarray(point, dtype=np.float64).reshape(1, 3),
                                           direction.reshape(1, 3), multiple_hits=True)
    except Exception:  # noqa: BLE001
        return None
    locations = np.asarray(hit[0], dtype=np.float64) if len(hit) else np.zeros((0, 3))
    return bool(locations.shape[0] % 2 == 1)


def camera_plane_clearance_mm(mesh: Any, eye: np.ndarray, rotation: np.ndarray) -> dict[str, Any]:
    """Smallest ``|z|`` of any mesh vertex in the camera frame, plus how many are close.

    The Blender worker verifies its camera by projecting **mesh vertices** through Blender and
    through this project's pinhole and requiring agreement within 0.1 px.  A vertex that lands on
    the camera plane (``z ~ 0``) projects to a coordinate of order ``f_px * x / z``, where the
    float32 arithmetic inside Blender and the float64 arithmetic here cannot agree - the check
    then reports a large error that says nothing about the camera.  A camera placed inside the
    body's own extent reaches that configuration, so the planner measures this clearance and
    refuses such a position instead of rendering it and blaming the check.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    cam = (vertices - np.asarray(eye, dtype=np.float64).reshape(1, 3)) @ np.asarray(
        rotation, dtype=np.float64)
    z = cam[:, 2]
    absolute = np.abs(z)
    return {
        "min_abs_z_mm": float(absolute.min()),
        "n_vertices_within_1mm_of_camera_plane": int(np.count_nonzero(absolute < 1.0)),
        "n_vertices": int(z.size),
        "instrument": "mesh vertices projected into the camera frame (float64)",
    }

def _orthonormal_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = np.asarray(normal, dtype=np.float64).reshape(3)
    n = n / max(float(np.linalg.norm(n)), 1e-30)
    helper = np.array([0.0, 1.0, 0.0])
    if abs(float(np.dot(n, helper))) > 0.99:
        helper = np.array([1.0, 0.0, 0.0])
    a1 = np.cross(helper, n)
    a1 = a1 / max(float(np.linalg.norm(a1)), 1e-30)
    a2 = np.cross(n, a1)
    return n, a1, a2


def _camera_frame(eye: np.ndarray, target_point: np.ndarray) -> np.ndarray:
    """OpenCV camera rotation (columns: right, down, forward) looking from ``eye`` at a point."""
    forward = (np.asarray(target_point, dtype=np.float64).reshape(3)
               - np.asarray(eye, dtype=np.float64).reshape(3))
    forward = forward / max(float(np.linalg.norm(forward)), 1e-30)
    up = np.array([0.0, 1.0, 0.0])
    if abs(float(np.dot(forward, up))) > 0.999:
        up = np.array([1.0, 0.0, 0.0])
    x_c = np.cross(up, forward)
    x_c = x_c / max(float(np.linalg.norm(x_c)), 1e-30)
    y_c = np.cross(forward, x_c)
    rotation = np.stack([x_c, y_c, forward], axis=1)
    return rotation


def plan_closeup_direction(*, mesh: Any, aim: np.ndarray, normal: np.ndarray,
                           theta_rad: float, points: np.ndarray, distance_mm: float,
                           rays: int, rng: np.random.Generator,
                           min_plane_clearance_mm: float = 2.0,
                           require_free_path: bool = True,
                           step_deg: float = 45.0
                           ) -> tuple[float, dict[str, Any]]:
    """Choose the in-plane azimuth of a tilted close-up by **measured** feasibility.

    A tilt that is legal on paper can still bury the ROI behind the fragment's own wall, or put
    the lens where no lens can go.  Each candidate azimuth is therefore evaluated with three
    measurements:

    1. ``outward_clearance_mm`` - is the segment from the fracture surface outwards free for at
       least the working distance (a place for the lens)?
    2. ``point_inside_mesh`` - is the camera centre actually outside the body (ray parity)?
    3. ``camera_plane_clearance_mm`` - does any mesh vertex land on the camera plane, where the
       Blender worker's camera self-check cannot be evaluated in float32?

    Among the candidates that pass, the one with the highest measured ROI visibility wins; the
    aim point is required to be visible.  When none passes, the best-visibility candidate is
    returned with ``feasible: false`` and the failing measurement named - never silently.
    """
    n, a1, a2 = _orthonormal_basis(normal)
    sample = points if points.shape[0] <= int(rays) else \
        points[rng.choice(points.shape[0], size=int(rays), replace=False)]
    if float(np.min(np.linalg.norm(sample - aim.reshape(1, 3), axis=1))) > 1e-9:
        sample = np.vstack([aim.reshape(1, 3), sample])

    def evaluate(direction: np.ndarray) -> dict[str, Any]:
        eye = aim + float(distance_mm) * direction
        visibility = _visible_fraction(mesh, eye, sample)
        aim_visible = bool(_visible_fraction(mesh, eye, aim.reshape(1, 3)) >= 1.0 - 1e-9)
        clearance, clearance_probe = outward_clearance_mm(mesh, aim, direction, distance_mm)
        inside = point_inside_mesh(mesh, eye)
        rotation = _camera_frame(eye, aim)
        plane = camera_plane_clearance_mm(mesh, eye, rotation)
        free_path = bool(not math.isfinite(clearance) or clearance >= distance_mm - 1e-6)
        feasible = bool(
            (free_path or not require_free_path)
            and (inside is not True)
            and float(plane["min_abs_z_mm"]) >= float(min_plane_clearance_mm))
        return {
            "eye_mm": [float(v) for v in eye], "visibility_fraction": visibility,
            "aim_visible": aim_visible, "outward_clearance_mm": clearance,
            "outward_probe": clearance_probe, "camera_inside_mesh": inside,
            "camera_plane_clearance_mm": plane["min_abs_z_mm"],
            "camera_plane_near_vertices": plane["n_vertices_within_1mm_of_camera_plane"],
            "free_path": free_path, "feasible": feasible,
        }

    if abs(math.cos(theta_rad) - 1.0) < 1e-12:
        candidate = evaluate(n)
        candidate["phi_deg"] = 0.0
        return 0.0, candidate
    candidates: list[dict[str, Any]] = []
    for phi_deg in np.arange(0.0, 360.0, float(step_deg)):
        phi = math.radians(float(phi_deg))
        in_plane = math.cos(phi) * a1 + math.sin(phi) * a2
        direction = math.cos(theta_rad) * n + math.sin(theta_rad) * in_plane
        direction = direction / max(float(np.linalg.norm(direction)), 1e-30)
        entry = evaluate(direction)
        entry["phi_deg"] = float(phi_deg)
        candidates.append(entry)

    def key(entry: dict[str, Any]) -> tuple:
        visibility = entry["visibility_fraction"]
        return (1 if entry["feasible"] else 0,
                1 if entry["aim_visible"] else 0,
                visibility if math.isfinite(visibility) else -1.0)

    best = max(candidates, key=key)
    best["candidates"] = candidates
    return float(best["phi_deg"]), best


def _choose_azimuth(mesh: Any, aim: np.ndarray, normal: np.ndarray, theta_rad: float,
                    points: np.ndarray, distance_mm: float, rays: int,
                    rng: np.random.Generator, step_deg: float = 45.0
                    ) -> tuple[float, float, bool, list[dict[str, Any]]]:
    """Pick the in-plane azimuth of a tilted close-up by **measured** occlusion.

    A tilt that is legal on paper can still bury the ROI behind the fragment's own wall; the
    contract asks for *effective* directions, so the azimuth is chosen by ray-casting the ROI
    sample points from each candidate camera position.  An azimuth that keeps the **aim point**
    (the pixel the camera is pointed at) visible always wins over one that does not; among those,
    the highest patch visibility wins.  Returns ``(phi_deg, visibility_fraction, aim_visible,
    all_candidates)``.
    """
    n, a1, a2 = _orthonormal_basis(normal)
    sample = points if points.shape[0] <= int(rays) else \
        points[rng.choice(points.shape[0], size=int(rays), replace=False)]
    if float(np.min(np.linalg.norm(sample - aim.reshape(1, 3), axis=1))) > 1e-9:
        sample = np.vstack([aim.reshape(1, 3), sample])

    def score(eye: np.ndarray) -> tuple[float, bool]:
        visibility = _visible_fraction(mesh, eye, sample)
        aim_visible = bool(_visible_fraction(mesh, eye, aim.reshape(1, 3)) >= 1.0 - 1e-9)
        return visibility, aim_visible

    if abs(math.cos(theta_rad) - 1.0) < 1e-12:
        visibility, aim_visible = score(aim + float(distance_mm) * n)
        return 0.0, visibility, aim_visible, []
    best_phi, best_visibility, best_aim = 0.0, -1.0, False
    candidates: list[dict[str, Any]] = []
    for phi_deg in np.arange(0.0, 360.0, float(step_deg)):
        phi = math.radians(float(phi_deg))
        in_plane = math.cos(phi) * a1 + math.sin(phi) * a2
        direction = math.cos(theta_rad) * n + math.sin(theta_rad) * in_plane
        direction = direction / max(float(np.linalg.norm(direction)), 1e-30)
        eye = aim + float(distance_mm) * direction
        visibility, aim_visible = score(eye)
        finite = visibility if math.isfinite(visibility) else -1.0
        candidates.append({"phi_deg": float(phi_deg), "visibility_fraction": visibility,
                           "aim_visible": bool(aim_visible)})
        key = (1 if aim_visible else 0, finite)
        current = (1 if best_aim else 0, best_visibility)
        if key > current:
            best_phi, best_visibility, best_aim = float(phi_deg), float(finite), bool(aim_visible)
    return best_phi, (best_visibility if best_visibility >= 0 else float("nan")), best_aim, \
        candidates


def make_fracture_roi_frames(*, rois: Sequence[FractureRoi], profile: CameraProfile,
                             spec: Any, config: FractureRoiConfig,
                             long_edge_px: int, rng: np.random.Generator,
                             run_id: str = "", mesh: Any | None = None) -> list[ViewFrame]:
    """Build 3-6 close-up frames per fracture, each with its own resolution ledger.

    The frames follow the same construction rule as
    :func:`synlab.cameras.viewframes.make_view_frames` (camera on the sampled direction looking
    at the target, ``object_pose`` identity), so they are rendered by the same code path; what
    changes is only *where the camera is aimed* and *how close it is*.

    ``mesh`` (the target's mesh) enables the measured azimuth choice of
    :func:`_choose_azimuth`: without it the in-plane azimuth is the frozen 0/90 deg pair and the
    view meta says so (``direction_azimuth_source``).
    """
    if not (MIN_DIRECTIONS <= int(config.directions) <= MAX_DIRECTIONS):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"directions={config.directions} outside [{MIN_DIRECTIONS}, "
                          f"{MAX_DIRECTIONS}]", stage="observe.fracture_roi.make_fracture_roi_frames")
    width, height = int(profile.image_size[0]), int(profile.image_size[1])
    #: the delivered grid is the render grid (identity crop): its scale is L / native width
    scale = float(long_edge_px) / float(width)
    f_px_delivered = float(profile.K[0, 0]) * scale
    z = float(config.working_distance_mm)
    s = mm_per_px(working_distance_mm=z, f_px=f_px_delivered)
    pitch_delivered = float(profile.meta.get("sensor_width_mm", 7.6)) / float(long_edge_px)
    dof = dof_report(working_distance_mm=z,
                     focal_length_mm=float(profile.meta.get("focal_length_mm", 6.1)),
                     f_number=float(profile.f_number), pixel_pitch_mm=pitch_delivered,
                     coc_px=float(profile.meta.get("coC_px", 2.0)))
    frames: list[ViewFrame] = []
    for roi in rois:
        target_point = (np.asarray(roi.aim_mm, dtype=np.float64)
                        if roi.aim_mm is not None
                        else np.asarray(roi.centroid_mm, dtype=np.float64))
        n, a1, a2 = _orthonormal_basis(roi.normal)
        for index in range(int(config.directions)):
            theta = math.radians(float(config.direction_offsets_deg[index]))
            phi = math.radians(0.0 if index % 2 == 0 else 90.0)
            azimuth_source = "FROZEN_0_90_DEG"
            measured_visibility = float("nan")
            aim_visible: bool | None = None
            azimuth_candidates: list[dict[str, Any]] = []
            feasibility: dict[str, Any] | None = None
            sample = (roi.sample_points if roi.sample_points is not None
                      else target_point.reshape(1, 3))
            if mesh is not None:
                phi_deg, feasibility = plan_closeup_direction(
                    mesh=mesh, aim=target_point, normal=roi.normal, theta_rad=theta,
                    points=sample, distance_mm=z,
                    rays=min(int(config.visibility_rays), 120), rng=rng,
                    min_plane_clearance_mm=float(config.min_camera_plane_clearance_mm),
                    require_free_path=bool(config.require_free_optical_path),
                    step_deg=float(config.azimuth_step_deg))
                measured_visibility = float(feasibility["visibility_fraction"])
                aim_visible = bool(feasibility["aim_visible"])
                azimuth_candidates = list(feasibility.pop("candidates", []))
                phi = math.radians(float(phi_deg))
                azimuth_source = "OCCLUSION_RAYCAST_BEST_OF_AZIMUTHS"
            in_plane = math.cos(phi) * a1 + math.sin(phi) * a2
            direction = math.cos(theta) * n + math.sin(theta) * in_plane
            direction = direction / max(float(np.linalg.norm(direction)), 1e-30)
            if feasibility is not None:
                # the planned position is the measured one: no extra jitter, so the feasibility
                # measurement describes the frame that is really rendered
                eye = np.asarray(feasibility["eye_mm"], dtype=np.float64)
            else:
                eye = target_point + z * direction
            forward = (target_point - eye)
            forward = forward / max(float(np.linalg.norm(forward)), 1e-30)
            up = np.array([0.0, 1.0, 0.0])
            if abs(float(np.dot(forward, up))) > 0.999:
                up = np.array([1.0, 0.0, 0.0])
            x_c = np.cross(up, forward)
            x_c = x_c / max(float(np.linalg.norm(x_c)), 1e-30)
            y_c = np.cross(forward, x_c)
            T_WC = np.eye(4, dtype=np.float64)
            T_WC[:3, 0], T_WC[:3, 1], T_WC[:3, 2] = x_c, y_c, forward
            jitter_applied = False
            if mesh is None:
                # only an unplanned frame (no mesh to measure against) keeps the historical
                # hand re-clamp jitter; a planned frame is rendered exactly where it was measured
                axis = rng.normal(size=3)
                axis /= max(float(np.linalg.norm(axis)), 1e-12)
                from ..cameras.viewframes import rotation_about_axis

                T_WC[:3, :3] = T_WC[:3, :3] @ rotation_about_axis(
                    axis, float(rng.normal(scale=np.deg2rad(0.35))))
                jitter_applied = True
            T_WC[:3, 3] = eye
            frame = ViewFrame(
                view_id=(f"{profile.profile_id}#roi{roi.interface_id:+03d}"
                         f"c{roi.component_id:03d}#d{index:02d}"),
                K=np.asarray(profile.K, dtype=np.float64).copy(), T_WC=T_WC,
                image_size=(width, height), profile_id=profile.profile_id,
                tier=str(profile.tier), u_position_mm=float(profile.u_position_mm),
                working_distance_mm=z, focus_setting=profile.focus_setting,
                source_kind=str(profile.meta.get("pose_source_kind", "SENSOR_SIM")),
                camera_model=str(profile.meta.get("camera_model", "PINHOLE")),
                dist=np.asarray(profile.dist, dtype=np.float64).copy(),
                meta={
                    "rig_model": "FRACTURE_ROI_CLOSEUP",
                    "framing": "FRACTURE_ROI",
                    "view_family": VIEW_FAMILY_ROI,
                    "run_id": str(run_id),
                    "fracture_roi_id": roi.roi_id,
                    "interface_id": int(roi.interface_id),
                    "component_id": int(roi.component_id),
                    "direction_index": int(index),
                    "direction_offset_deg": float(config.direction_offsets_deg[index]),
                    "direction_in_plane_deg": float(np.rad2deg(phi)),
                    "direction_azimuth_source": azimuth_source,
                    "direction_azimuth_candidates": azimuth_candidates,
                    "direction_visibility_fraction": measured_visibility,
                    "direction_aim_visible": aim_visible,
                    "capture_feasibility": feasibility,
                    "capture_feasible": (None if feasibility is None
                                         else bool(feasibility.get("feasible"))),
                    "planner_jitter_applied": bool(jitter_applied),
                    "direction_vector": [float(v) for v in direction],
                    "camera_centre_mm": [float(v) for v in eye],
                    "roi_aim_mm": [float(v) for v in target_point],
                    "roi_centroid_mm": [float(v) for v in roi.centroid_mm],
                    "roi_normal": [float(v) for v in n],
                    "roi_area_mm2": float(roi.area_mm2),
                    "roi_parent_area_mm2": float(roi.parent_area_mm2),
                    "roi_radius_p95_mm": float(roi.radius_p95_mm),
                    "roi_footprint_radius_mm": roi.footprint_radius_mm,
                    "roi_visibility_fraction": float(roi.visibility_fraction),
                    "roi_normal_sign_source": str(roi.normal_sign_source),
                    "roi_height_field": roi.height,
                    "object_pose_T_WO": np.eye(4).tolist(),
                    "target_center_mm": [float(v) for v in roi.centroid_mm],
                    "target_radius_mm": float(roi.radius_p95_mm),
                    "coverage_radius_covers_roi": bool(
                        z * 0.5 * float(long_edge_px) / f_px_delivered >= roi.radius_p95_mm),
                    "profile_revision": int(profile.revision),
                    "focal_length_mm": profile.meta.get("focal_length_mm"),
                    "mm_per_pixel": s,
                    "mm_per_pixel_source": ("nominal z / f_px of the delivered grid; the measured "
                                            "value from the rendered depth is reported per view"),
                    "px_per_mm": 1.0 / s,
                    "r_eff_mm": r_eff_mm(working_distance_mm=z, f_px=f_px_delivered),
                    "r_eff_mm_6px": r_eff_mm(working_distance_mm=z, f_px=f_px_delivered,
                                             k_px=6.0),
                    "r_eff_mm_8px": r_eff_mm(working_distance_mm=z, f_px=f_px_delivered,
                                             k_px=DETAIL_PX_PER_STRUCTURE),
                    "dof_cover_mm": dof["dof_cover_mm"],
                    "dof_near_mm": dof["near_mm"],
                    "dof_far_mm": dof["far_mm"],
                    "delivered_long_edge_px": int(long_edge_px),
                    "delivered_grid_px": [int(long_edge_px),
                                          int(round(long_edge_px * height / width))],
                    "f_px_delivered": f_px_delivered,
                    "calibration_status": profile.meta.get("calibration_status",
                                                           "CLOSEUP_DECLARED_NOT_CALIBRATED"),
                    "T_blender_from_opencv": None,
                    "digital_zoom_applied": False,
                    "upsampled": False,
                },
            )
            frames.append(frame)
    return frames


# ======================================================================================
# rendering + measurement
# ======================================================================================
def render_fracture_roi_views(*, target: Any, frames: Sequence[ViewFrame], spec: Any,
                              rng: np.random.Generator, backend: str | None = None,
                              blender_config: Any = None) -> tuple[list[Any], float]:
    """Render the ROI frames through the shared render+imaging path (wall seconds returned)."""
    from .routes import render_frame_bundles

    started = time.perf_counter()
    bundles = render_frame_bundles(target, list(frames), spec, rng, backend=backend,
                                   blender_config=blender_config)
    return bundles, float(time.perf_counter() - started)


def axis_raycast_depth_mm(mesh: Any, frame: ViewFrame) -> tuple[float, dict[str, Any]]:
    """First surface hit along the camera's optical axis, measured by ray casting (mm).

    An *independent* instrument for the working distance of the aimed pixel: the rendered depth
    channel is a rasterised buffer, and on grazing (near edge-on) triangles its screen-space
    linear ``z`` interpolation is not perspective-correct, so it can disagree with the geometry by
    centimetres.  This measurement is the cross-check, and the disagreement is reported rather
    than hidden.
    """
    if mesh is None:
        return float("nan"), {"status": "NO_MESH"}
    eye = np.asarray(frame.T_WC[:3, 3], dtype=np.float64).reshape(1, 3)
    forward = np.asarray(frame.T_WC[:3, 2], dtype=np.float64).reshape(1, 3)
    forward = forward / max(float(np.linalg.norm(forward)), 1e-30)
    try:
        hit = mesh.ray.intersects_location(eye, forward, multiple_hits=True)
    except Exception as exc:  # noqa: BLE001
        return float("nan"), {"status": "RAYCAST_FAILED", "error": str(exc)[:160]}
    locations = np.asarray(hit[0], dtype=np.float64) if len(hit) else np.zeros((0, 3))
    if locations.shape[0] == 0:
        return float("nan"), {"status": "NO_HIT"}
    distance = np.linalg.norm(locations - eye, axis=1)
    order = np.argsort(distance)
    return float(distance[order[0]]), {
        "status": "OK", "n_hits": int(distance.size),
        "first_hits_mm": [float(distance[i]) for i in order[:5]],
    }


def view_resolution_record(bundle: Any, *, rim_tag: int = 2,
                           mesh: Any | None = None) -> dict[str, Any]:
    """Measure one bundle's delivered resolution and fracture content.

    Everything here is measured from the bundle that was actually produced: the depth of the
    delivered pixels, the delivered ``K``, and the delivered surface-tag map.  When ``mesh`` is
    given, the aimed-pixel distance is *also* measured by an independent ray cast
    (:func:`axis_raycast_depth_mm`) and both numbers are reported, with their difference.
    """
    depth = np.asarray(bundle.render.depth_z, dtype=np.float64)
    size = (int(bundle.imaging.image.shape[1]), int(bundle.imaging.image.shape[0]))
    K_render = np.asarray(bundle.render_frame.K, dtype=np.float64)
    f_px = float(bundle.K[0, 0])
    valid = np.isfinite(depth) & (depth > 0)
    if bool(valid.any()):
        depth_median = float(np.median(depth[valid]))
        depth_p01 = float(np.percentile(depth[valid], 1))
        depth_p99 = float(np.percentile(depth[valid], 99))
    else:
        depth_median = depth_p01 = depth_p99 = float("nan")
    # depth of the surface the camera is aimed at: the frame is built looking at the ROI aim
    # point, so that point projects onto the principal point of the render grid
    cx, cy = int(round(float(K_render[0, 2]))), int(round(float(K_render[1, 2])))
    h, w = depth.shape
    window = depth[max(cy - 4, 0):min(cy + 5, h), max(cx - 4, 0):min(cx + 5, w)]
    window_valid = window[np.isfinite(window) & (window > 0)]
    depth_centre = float(np.median(window_valid)) if window_valid.size else float("nan")
    tag_delivered = np.asarray(bundle.render.surface_tag)
    tag = tag_delivered
    if tag.shape[0] != size[1] or tag.shape[1] != size[0]:
        import cv2

        tag = cv2.resize(np.asarray(tag_delivered, dtype=np.int32), size,
                         interpolation=cv2.INTER_NEAREST)
    rim_px = int(np.count_nonzero(tag == int(rim_tag)))
    object_px = int(np.count_nonzero(tag >= 0))
    mean_depth = float(np.nanmean(depth[valid])) if bool(valid.any()) else float("nan")
    s_measured = (depth_median / f_px) if (f_px > 0 and math.isfinite(depth_median)) else float("nan")
    s_centre = (depth_centre / f_px) if (f_px > 0 and math.isfinite(depth_centre)) else float("nan")
    axis_depth, axis_probe = axis_raycast_depth_mm(mesh, bundle.render_frame)
    s_axis = (axis_depth / f_px) if (f_px > 0 and math.isfinite(axis_depth)) else float("nan")
    return {
        "view_id": str(bundle.frame.view_id),
        "view_family": str((bundle.frame.meta or {}).get("view_family", VIEW_FAMILY_WHOLE)),
        "fracture_roi_id": (bundle.frame.meta or {}).get("fracture_roi_id"),
        "delivered_size_px": [int(size[0]), int(size[1])],
        "f_px_delivered": f_px,
        "f_px_native": float(bundle.render_frame.K[0, 0]),
        "working_distance_nominal_mm": float(bundle.render_frame.working_distance_mm),
        "depth_median_mm": depth_median,
        "depth_centre_mm": depth_centre,
        "depth_mean_mm": mean_depth,
        "depth_p01_mm": depth_p01,
        "depth_p99_mm": depth_p99,
        "mm_per_px_measured": s_measured,
        "mm_per_px_at_centre": s_centre,
        "depth_axis_raycast_mm": axis_depth,
        "axis_raycast_probe": axis_probe,
        "mm_per_px_axis_raycast": s_axis,
        "structure_0p2mm_px_axis_raycast": (0.2 / s_axis)
        if (s_axis and math.isfinite(s_axis)) else float("nan"),
        "depth_render_minus_raycast_mm": (depth_centre - axis_depth)
        if (math.isfinite(depth_centre) and math.isfinite(axis_depth)) else float("nan"),
        "instrument_disagreement_flag": (
            abs(depth_centre - axis_depth) > 1.0
            if (math.isfinite(depth_centre) and math.isfinite(axis_depth)) else None),
        "px_per_mm_at_centre": (1.0 / s_centre) if (s_centre and math.isfinite(s_centre))
        else float("nan"),
        "structure_0p2mm_px_at_centre": (0.2 / s_centre) if (s_centre and math.isfinite(s_centre))
        else float("nan"),
        "mm_per_px_nominal": (float(bundle.render_frame.working_distance_mm) / f_px)
        if f_px > 0 else float("nan"),
        "px_per_mm_measured": (1.0 / s_measured) if s_measured and math.isfinite(s_measured)
        else float("nan"),
        "r_eff_mm_4px": (PILOT_PX_PER_STRUCTURE * s_measured)
        if math.isfinite(s_measured) else float("nan"),
        "r_eff_mm_8px": (DETAIL_PX_PER_STRUCTURE * s_measured)
        if math.isfinite(s_measured) else float("nan"),
        "object_px": object_px,
        "rim_px": rim_px,
        "rim_fraction_of_object": (float(rim_px) / object_px) if object_px else 0.0,
        "rim_fraction_of_frame": float(rim_px) / float(size[0] * size[1]),
        "render_backend": str((bundle.frame.meta or {}).get("backend") or bundle.backend),
        "render_grid_px": [int(bundle.render_frame.image_size[0]),
                           int(bundle.render_frame.image_size[1])],
        "visibility_fraction": (bundle.frame.meta or {}).get("roi_visibility_fraction"),
        "direction_offset_deg": (bundle.frame.meta or {}).get("direction_offset_deg"),
        "direction_in_plane_deg": (bundle.frame.meta or {}).get("direction_in_plane_deg"),
        "direction_visibility_fraction": (bundle.frame.meta or {}).get(
            "direction_visibility_fraction"),
        "direction_aim_visible": (bundle.frame.meta or {}).get("direction_aim_visible"),
        "dof_cover_mm": (bundle.frame.meta or {}).get("dof_cover_mm"),
        "focus_error_mm": (depth_centre - float(bundle.render_frame.working_distance_mm))
        if math.isfinite(depth_centre) else float("nan"),
        "depth_centre_within_dof": (abs(depth_centre
                                        - float(bundle.render_frame.working_distance_mm))
                                    <= 0.5 * float((bundle.frame.meta or {}).get(
                                        "dof_cover_mm") or float("inf")))
        if math.isfinite(depth_centre) else None,
    }


def amplitude_px_from_roi(*, roi: FractureRoi, mm_per_px_measured: float,
                          band: str = "plane") -> dict[str, float]:
    """Convert a measured height-field band amplitude into delivered pixels for one view."""
    stats = dict(roi.height.get(band) or {})
    out: dict[str, float] = {}
    for key, value in stats.items():
        if key in ("Ra_mm", "Rq_mm", "Rz_mm", "Rt_mm", "p95_abs_mm"):
            out[f"{key}_px"] = amplitude_px(float(value), mm_per_px_measured)
    return out


# ======================================================================================
# observation assembly
# ======================================================================================
def append_roi_views(*, observation: ObservationResult, roi_bundles: Sequence[Any],
                     spec: Any, config: FractureRoiConfig, rois: Sequence[FractureRoi],
                     whole_records: Sequence[Mapping[str, Any]],
                     roi_records: Sequence[Mapping[str, Any]],
                     timings: Mapping[str, Any] | None = None) -> ObservationResult:
    """Return ``observation`` with the ROI views **appended** and the resolution ledger added.

    The whole-fragment views are kept byte-identical; the ROI views are new entries at the end of
    ``views``, each carrying ``meta['view_family'] = 'FRACTURE_ROI'`` and its own measured
    resolution.  Nothing is replaced and nothing is relabelled.
    """
    from .routes import observation_views

    extra = observation_views(list(roi_bundles), spec) if roi_bundles else []
    for view in extra:
        view.meta["view_family"] = VIEW_FAMILY_ROI
        view.meta["roi_source"] = "MEASURED_INTERFACE_PATCH"
    views = list(observation.views) + list(extra)
    meta = copy.deepcopy(observation.meta)
    whole = [dict(r) for r in whole_records]
    roi_views = [dict(r) for r in roi_records]
    per_view = {str(r.get("view_id")): r for r in whole}
    per_view.update({str(r.get("view_id")): r for r in roi_views})
    meta["fracture_roi"] = {
        "schema": ROI_SPEC_SCHEMA,
        "contract_pointers": dict(CONTRACT_POINTERS),
        "config": config.as_dict(),
        "n_roi_views": len(extra),
        "n_whole_views": int(len(observation.views)),
        "n_fractures_measured": len(rois),
        "fractures": [r.as_dict() for r in rois],
        "resolution_ledger": {
            "per_view": per_view,
            "whole_fragment": whole,
            "fracture_roi": roi_views,
            "units": {"mm_per_px": "mm per delivered pixel at the measured median depth",
                      "px_per_mm": "1 / mm_per_px", "r_eff_mm": "4 * mm_per_px",
                      "dof_cover_mm": "thin-lens far - near at the close-up condition"},
            "producers": ["px_per_mm", "r_eff_mm", "dof_cover_mm", "mm_per_px"],
        },
        "timings": dict(timings or {}),
        "same_run_as_whole_fragment": True,
        "views_added_not_replaced": True,
    }
    meta["view_family_counts"] = {
        VIEW_FAMILY_WHOLE: int(len(observation.views)),
        VIEW_FAMILY_ROI: int(len(extra)),
    }
    out = replace(observation, views=views, meta=meta)
    return out


def roi_summary(*, rois: Sequence[FractureRoi], whole_records: Sequence[Mapping[str, Any]],
                roi_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Whole-fragment vs ROI-contract comparison for one target (the hard metrics)."""
    def _median(records: Sequence[Mapping[str, Any]], key: str) -> float:
        values = [float(r[key]) for r in records
                  if r.get(key) is not None and math.isfinite(float(r[key]))]
        return float(np.median(values)) if values else float("nan")

    whole_s = _median(whole_records, "mm_per_px_measured")
    roi_s = _median(roi_records, "mm_per_px_measured")
    whole_c = _median(whole_records, "mm_per_px_at_centre")
    roi_c = _median(roi_records, "mm_per_px_at_centre")
    whole_a = _median(whole_records, "mm_per_px_axis_raycast")
    roi_a = _median(roi_records, "mm_per_px_axis_raycast")
    disagreements = [float(r["depth_render_minus_raycast_mm"]) for r in
                     list(whole_records) + list(roi_records)
                     if r.get("depth_render_minus_raycast_mm") is not None
                     and math.isfinite(float(r["depth_render_minus_raycast_mm"]))]
    amplitudes = {roi.roi_id: dict(roi.height.get("plane") or {}) for roi in rois}
    bands: dict[str, Any] = {}
    for roi in rois:
        for band, stats in (roi.height.get("bands") or {}).items():
            bands.setdefault(band, {})[roi.roi_id] = stats
    best_band = None
    best_ra = 0.0
    for band, per_roi in bands.items():
        for roi_id, stats in per_roi.items():
            if float(stats.get("Ra_mm", 0.0)) > best_ra:
                best_ra = float(stats["Ra_mm"])
                best_band = {"band": band, "roi_id": roi_id, "Ra_mm": best_ra}
    return {
        "whole_fragment": {
            "n_views": len(whole_records),
            "mm_per_px_median": whole_s,
            "mm_per_px_at_centre_median": whole_c,
            "px_per_mm_median": (1.0 / whole_s) if whole_s and math.isfinite(whole_s) else None,
            "r_eff_mm_4px": (PILOT_PX_PER_STRUCTURE * whole_s) if math.isfinite(whole_s) else None,
            "rim_px_total": int(sum(int(r.get("rim_px", 0)) for r in whole_records)),
            "rim_fraction_of_object_median": _median(whole_records, "rim_fraction_of_object"),
            "structure_0p2mm_px": (0.2 / whole_s) if whole_s and math.isfinite(whole_s) else None,
            "structure_0p2mm_px_at_centre": (0.2 / whole_c)
            if whole_c and math.isfinite(whole_c) else None,
        },
        "fracture_roi": {
            "n_views": len(roi_records),
            "mm_per_px_median": roi_s,
            "mm_per_px_at_centre_median": roi_c,
            "px_per_mm_median": (1.0 / roi_s) if roi_s and math.isfinite(roi_s) else None,
            "r_eff_mm_4px": (PILOT_PX_PER_STRUCTURE * roi_s) if math.isfinite(roi_s) else None,
            "rim_px_total": int(sum(int(r.get("rim_px", 0)) for r in roi_records)),
            "rim_fraction_of_object_median": _median(roi_records, "rim_fraction_of_object"),
            "structure_0p2mm_px": (0.2 / roi_s) if roi_s and math.isfinite(roi_s) else None,
            "structure_0p2mm_px_at_centre": (0.2 / roi_c)
            if roi_c and math.isfinite(roi_c) else None,
            "effective_directions_per_fracture": _effective_directions(roi_records),
        },
        "improvement_factor_mm_per_px": (whole_s / roi_s)
        if (roi_s and math.isfinite(roi_s) and math.isfinite(whole_s)) else None,
        "improvement_factor_mm_per_px_at_centre": (whole_c / roi_c)
        if (roi_c and math.isfinite(roi_c) and math.isfinite(whole_c)) else None,
        "axis_raycast": {
            "whole_fragment_mm_per_px_median": whole_a,
            "fracture_roi_mm_per_px_median": roi_a,
            "whole_fragment_structure_0p2mm_px": (0.2 / whole_a)
            if (whole_a and math.isfinite(whole_a)) else None,
            "fracture_roi_structure_0p2mm_px": (0.2 / roi_a)
            if (roi_a and math.isfinite(roi_a)) else None,
            "improvement_factor": (whole_a / roi_a)
            if (roi_a and math.isfinite(roi_a) and math.isfinite(whole_a)) else None,
            "note": ("first ray hit along the camera axis, cast on the target mesh: an "
                     "independent instrument for the aimed-pixel distance, used because a "
                     "rasterised depth buffer is not perspective-correct on grazing triangles"),
        },
        "instrument_disagreement_mm": {
            "n_views": len(disagreements),
            "median_mm": float(np.median(disagreements)) if disagreements else None,
            "max_abs_mm": float(np.max(np.abs(disagreements))) if disagreements else None,
            "n_views_over_1mm": int(sum(1 for d in disagreements if abs(d) > 1.0)),
        },
        "scale_convention": ("mm_per_px_median is measured over every valid depth pixel of the "
                             "frame (the convention docs/a12/precision_audit.md uses); "
                             "mm_per_px_at_centre is measured at the pixel the camera is aimed "
                             "at (the principal point = the ROI aim point for a close-up), which "
                             "is the scale of the surface the claim is about"),
        "measured_amplitudes_mm": amplitudes,
        "measured_bands_mm": bands,
        "largest_measured_band_Ra": best_band,
    }


def _effective_directions(roi_records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in roi_records:
        roi_id = str(record.get("fracture_roi_id") or "")
        if not roi_id:
            continue
        counts.setdefault(roi_id, 0)
        if int(record.get("rim_px", 0)) > 0:
            counts[roi_id] += 1
    return counts


__all__ = [
    "ROI_SPEC_SCHEMA", "VIEW_FAMILY_ROI", "VIEW_FAMILY_WHOLE", "CONTRACT_POINTERS",
    "PILOT_PX_PER_STRUCTURE", "DETAIL_PX_PER_STRUCTURE", "CLOSEUP_MIN_MM", "CLOSEUP_MAX_MM",
    "MIN_DIRECTIONS", "MAX_DIRECTIONS", "DEFAULT_CONFIG_PATH",
    "FractureRoiConfig", "FractureRoi", "load_fracture_roi_config", "validate_config",
    "mm_per_px", "px_per_mm", "r_eff_mm", "structure_px", "amplitude_px",
    "max_working_distance_mm", "required_f_px", "required_long_edge_px", "dof_report",
    "documented_ladder", "resolvability_report", "inverse_solve", "height_field_stats",
    "shading_contrast",
    "fracture_rois", "closeup_profile", "delivered_profile", "make_fracture_roi_frames",
    "render_fracture_roi_views", "view_resolution_record", "amplitude_px_from_roi",
    "append_roi_views", "roi_summary",
]
