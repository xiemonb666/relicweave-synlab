"""Fracture appearance layer: deliver the sub-millimetre relief through the *normal* channel.

Why this file exists
--------------------
`docs/a12/fracture_visible.md` established three measured facts that this module acts on:

1. the geometric fracture face of the campaign lineage is **exactly flat** below 1 mm
   (local-detrended ``Ra`` measured ``0.000``), so no camera can photograph relief that is not
   in the geometry;
2. relief of a few tens of micrometres can **never** reach 4 px laterally under any real lens
   (``Ra = 0.02 mm`` needs ``mm/px <= 0.005``), so its only delivery path is
   **normal -> shading** in the frozen Lambert + ambient model;
3. but the frozen software rasteriser shades **one flat normal per triangle**, so whatever
   relief exists below the triangle size is invisible, and the triangles themselves become the
   dominant visible pattern (the "radial streaks" that turn out to be fan-shaped
   triangle-topology shading rather than physical hackle).

This module adds the missing channel *without touching the fracture geometry*:

* ``normal_mode`` selects the per-pixel shading normal: ``FLAT`` (the frozen behaviour),
  ``SMOOTH`` (area-weighted vertex normals interpolated per pixel) or ``SMOOTH_CREASE``
  (face-varying corner normals with a crease angle, so a real rim edge stays sharp);
* ``relief`` perturbs that normal per pixel by the **analytic gradient of the audited fracture
  morphology field** of :mod:`synlab.fracture.morphology` - the same field the gated
  ``morphology_shared_cut`` backend was built to put into the mesh.  It is evaluated in the ROI
  plane's ``(u, v)`` millimetres, so the perturbation is continuous across triangles and
  independent of triangle size; the vertices and faces are untouched and their hash is reported
  next to every render.

Every number this module reports is measured on a real render of a real target:

* ``dDN`` is the per-pixel code-value change between two renders of the **same view, same
  geometry, same imaging chain, same noise seed** that differ only in the shading normal;
* ``facet_edge_dn_step`` and ``median_face_area_px`` are measured on the delivered image together
  with the integer ``id_map``, so "the facets are visible" is a number, not an opinion;
* the required mesh density is an inverse solve from the field's own shortest wavelength, with
  the measured triangle edge length of the real patch next to it.

Honest boundaries
-----------------
* the relief field is the **appearance-layer** realisation of the morphology model; it is *not* a
  mesh modification and it is *not* the ``synlab/fracture`` backend (a different workstream that
  still FAILs its precision budget);
* ``diffuse_weight`` (``1 - transmission`` for transmissive profiles) is a **declared** extension
  of the frozen model; every table that uses it reports the unweighted number as well;
* no upsampling: the delivered grid is never larger than the render grid, and supersampling is
  applied *downward* (pixel integration), never upward (interpolation).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..roles import SOURCE_SENSOR_SIM
from ..schemas.runtime import ORIGIN_INTERFACE, RenderOutput, ViewFrame
from .render import (
    MASK_SEMANTICS,
    MASK_SEMANTICS_PIXEL_UNITS_V1,
    LightSpec,
    RenderSpec,
    Scene,
    _block_reduce,
    _disagreement_i,
    circle_of_confusion_px,
    resolve_declared_optics,
)

__all__ = [
    "APPEARANCE_SCHEMA",
    "BACKEND_APPEARANCE",
    "CONTRACT_LIGHT_MODES",
    "CONTRACT_LIGHT_PURPOSE",
    "FACET_RESOLUTION_RATIO",
    "INTERPOLATIONS",
    "NORMAL_MODES",
    "TEXTURE_MIN_PERIOD_PX",
    "TEXTURE_WAVELENGTH_FRACTIONS",
    "TEXTURE_WAVE_DIRECTIONS",
    "AlbedoTexture",
    "AppearanceParameters",
    "AppearanceSpec",
    "FractureAppearanceConfig",
    "LightChoice",
    "ReliefField",
    "appearance_parameters_from_profile",
    "build_relief_field",
    "choose_contract_light",
    "contract_light",
    "corner_normals",
    "directional_index",
    "dn_statistics",
    "facet_metrics",
    "field_spectrum_report",
    "frozen_light",
    "geometry_hash",
    "glaze_step_report",
    "grain_pixel_statistics",
    "lambert_ambient_linear",
    "lambert_response_score",
    "load_fracture_appearance_config",
    "make_albedo_texture",
    "measured_edge_length_mm",
    "render_appearance_view",
    "required_mesh_density",
    "resample_relief_ra",
    "side_by_side_png",
    "texture_consistency_report",
    "texture_spectrum_report",
    "validate_config",
    "vertex_normals",
    "write_rgb_png",
]

#: Backend name recorded in ``RenderOutput.backend`` and in every report row.
BACKEND_APPEARANCE = "APPEARANCE_NORMAL_CHANNEL"
APPEARANCE_SCHEMA = "synlab.a12.fracture_appearance.v1"

NORMAL_MODES = ("FLAT", "SMOOTH", "SMOOTH_CREASE")
INTERPOLATIONS = ("FROZEN", "PERSPECTIVE_CORRECT")

#: A facet must be ``lambda_min / FACET_RESOLUTION_RATIO`` across for its own orientation error to
#: stay inside the 1-code-value shading floor (see :func:`required_mesh_density`).
FACET_RESOLUTION_RATIO = 8.0

DEFAULT_CONFIG_PATH = "configs/a12/imaging_fracture_appearance.yaml"


# ======================================================================================
# frozen lighting and shading (a verbatim mirror of the observation pipeline)
# ======================================================================================
def frozen_light() -> LightSpec:
    """The frozen directional light of the observation pipeline (``routes.ObsSpec``)."""
    direction = np.array([-0.35, -0.62, -0.70], dtype=np.float64)
    direction /= np.linalg.norm(direction)
    return LightSpec(direction=direction,
                     color=np.array([2.35, 2.25, 2.10], dtype=np.float64),
                     ambient=np.array([0.30, 0.30, 0.33], dtype=np.float64))


def lambert_ambient_linear(*, normals_world: np.ndarray, T_WC: np.ndarray, albedo: np.ndarray,
                           light: LightSpec) -> np.ndarray:
    """The frozen shading model, verbatim and per pixel.

    ``render._rasterise_buffers`` computes ``scene_normals = world_normals @ T_WC[:3, :3]`` and
    then ``clip(-(scene_normals @ light.direction), 0, 1)``; this is that expression with one row
    per pixel instead of one row per face, which is what makes a per-pixel normal comparable with
    the frozen backend.
    """
    n = np.asarray(normals_world, dtype=np.float64)
    scene_normals = n @ np.asarray(T_WC, dtype=np.float64)[:3, :3]
    lambert = np.clip(-(scene_normals @ np.asarray(light.direction, dtype=np.float64)), 0.0, 1.0)
    a = np.asarray(albedo, dtype=np.float64)
    return a * (np.asarray(light.ambient, dtype=np.float64)[None, :]
                + np.asarray(light.color, dtype=np.float64)[None, :] * lambert[..., None])


def shade_world_normals(*, normals_world: np.ndarray, albedo: np.ndarray,
                        light: LightSpec) -> np.ndarray:
    """The frozen shading with a genuine **world** normal: ``albedo*(ambient + color*clip(-(n.l)))``.

    ``render._rasterise_buffers`` names its cross-product "world_normals" but the vertices it uses
    are camera-space, and it then applies ``T_WC[:3, :3]``; for a rigid transform that composes to
    ``scene_normals = R^T n_cam = n_world``.  The frozen light is therefore expressed in the
    **world** frame, and this function is the same model written in the frame the relief
    perturbation lives in.  The two forms agree to floating-point round-off.
    """
    n = np.asarray(normals_world, dtype=np.float64)
    lambert = np.clip(-(n @ np.asarray(light.direction, dtype=np.float64)), 0.0, 1.0)
    a = np.asarray(albedo, dtype=np.float64)
    return a * (np.asarray(light.ambient, dtype=np.float64)[None, :]
                + np.asarray(light.color, dtype=np.float64)[None, :] * lambert[..., None])


# ======================================================================================
# A1: the contract's documented light states, and which one a fracture view can respond to
# ======================================================================================
#: The five light states of the capture contract (``configs/a12/capture_contract.json`` ->
#: ``lighting.real_capture_light_modes``; table t053 in ``docs/a12/v144_project_core.md`` §4.4,
#: documented in ``synlab/degrade/specs.py::LIGHT_MODE_NAMES``).  This layer **invents no light**:
#: it selects among these, and the numeric vectors it uses are the frozen realisation already in
#: ``synlab.pipeline.LIGHT_MODE_SPECS`` - the same ``LightSpec`` a real observation is rendered
#: with.  ``purpose`` is the contract's own statement of what the state is for.
CONTRACT_LIGHT_MODES: tuple[str, ...] = ("WHITE_DIFFUSE", "LEFT_GRAZE", "RIGHT_GRAZE",
                                         "CROSS_POL", "NORMAL_REFLECT")

CONTRACT_LIGHT_PURPOSE: dict[str, str] = {
    "WHITE_DIFFUSE": "轮廓、颜色和基础纹饰",
    "LEFT_GRAZE": "断口起伏和裂纹",
    "RIGHT_GRAZE": "验证另一方向纹理与阴影",
    "CROSS_POL": "降低部分釉面高光",
    "NORMAL_REFLECT": "保留光泽等材质证据",
}


def contract_light(mode: str) -> LightSpec:
    """One of the five documented light states as the frozen :class:`LightSpec` of the pipeline.

    The vectors come from ``synlab.pipeline.LIGHT_MODE_SPECS`` (this build's frozen realisation of
    the contract's qualitative setups, recorded in every observation's metadata).  No new light is
    defined here; an unknown mode is an error, never silently mapped.
    """
    from ..pipeline import LIGHT_MODE_SPECS

    key = str(mode).upper()
    if key not in CONTRACT_LIGHT_MODES or key not in LIGHT_MODE_SPECS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"light mode {mode!r} is not one of the contract's five "
                          f"{list(CONTRACT_LIGHT_MODES)}",
                          stage="observe.fracture_appearance.contract_light")
    spec = LIGHT_MODE_SPECS[key]
    direction = np.asarray(spec["direction"], dtype=np.float64).reshape(3)
    direction = direction / max(float(np.linalg.norm(direction)), 1e-30)
    return LightSpec(direction=direction,
                     color=np.asarray(spec["color"], dtype=np.float64).reshape(3),
                     ambient=np.asarray(spec["ambient"], dtype=np.float64).reshape(3))


def lambert_response_score(*, normal_world: np.ndarray, light: LightSpec) -> float:
    """``-(n . light.direction)``: the fraction of the frozen Lambert term a flat fracture gets.

    The frozen model is ``albedo * (ambient + color * clip(-(n . l), 0, 1))`` with the Lambert term
    clipped at 0, so on a fracture patch whose normal faces away from the light the shading is
    ``albedo * ambient`` everywhere and **no** per-pixel normal perturbation can change a code
    value.  This score is therefore the measured gate on whether a light state can show relief at
    all: ``<= 0`` means zero response, ``>= 1`` means the term is clipped at the top (also zero
    response), and a mid value means the surface sits inside the linear part of the response.
    """
    n = np.asarray(normal_world, dtype=np.float64).reshape(3)
    n = n / max(float(np.linalg.norm(n)), 1e-30)
    return float(-(n @ np.asarray(light.direction, dtype=np.float64).reshape(3)))


@dataclass(frozen=True)
class LightChoice:
    """The light state chosen for one fracture view out of the contract's five."""

    mode: str
    direction: tuple[float, float, float]
    color: tuple[float, float, float]
    ambient: tuple[float, float, float]
    response_score: float
    #: every candidate of the contract, measured - so the choice is auditable, not asserted
    ranking: tuple[dict[str, Any], ...]
    rule: str = "MAX_LAMBERT_RESPONSE_IN_LINEAR_BAND"

    @property
    def light(self) -> LightSpec:
        return LightSpec(direction=np.asarray(self.direction, dtype=np.float64),
                         color=np.asarray(self.color, dtype=np.float64),
                         ambient=np.asarray(self.ambient, dtype=np.float64))

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "rule": self.rule,
                "response_score": float(self.response_score),
                "purpose": CONTRACT_LIGHT_PURPOSE.get(self.mode, ""),
                "direction": [float(x) for x in self.direction],
                "color": [float(x) for x in self.color],
                "ambient": [float(x) for x in self.ambient],
                "source": ("synlab.pipeline.LIGHT_MODE_SPECS - this build's frozen realisation of "
                           "the five documented light states (t053); no light is invented here"),
                "candidates": [dict(r) for r in self.ranking],
                "n_candidates": len(self.ranking)}


def _interior_linear_band_score(raw: float) -> float:
    """Reward the *interior* of the Lambert response, where a normal change still moves the image.

    ``raw <= 0`` is clipped to 0 by the frozen model; ``raw >= 1`` is clipped to 1.  Both give a
    zero derivative.  The useful band is ``0 < raw < 1``, and the response to a normal tilt is
    proportional to the component of the light perpendicular to the surface, so the score is
    ``sin(acos(raw))`` = ``sqrt(1 - raw^2)`` inside the band and 0 outside it.
    """
    r = float(raw)
    if r <= 0.0 or r >= 1.0:
        return 0.0
    return float(math.sqrt(max(0.0, 1.0 - r * r)))


def choose_contract_light(*, normal_world: np.ndarray,
                          modes: Sequence[str] = CONTRACT_LIGHT_MODES) -> LightChoice:
    """Pick the contract light state with the largest usable normal response for this view.

    The selection is a measurement, not a preference: for each of the five documented states the
    signed Lambert response ``-(n . l)`` of the fracture normal is evaluated, and the state that
    puts the surface deepest inside the linear band (``0 < response < 1``) wins.  The whole ranking
    is returned so a reader can see the losers and by how much.  Ties break on the contract's
    declared order, so the choice is deterministic.
    """
    rows: list[dict[str, Any]] = []
    for mode in modes:
        light = contract_light(mode)
        raw = lambert_response_score(normal_world=normal_world, light=light)
        rows.append({"mode": mode, "purpose": CONTRACT_LIGHT_PURPOSE.get(mode, ""),
                     "lambert_response": raw,
                     "raw_negative": bool(raw <= 0.0), "raw_clipped_high": bool(raw >= 1.0),
                     "usable_response": _interior_linear_band_score(raw),
                     "direction": [float(x) for x in np.asarray(light.direction).reshape(3)]})
    ranking = tuple(sorted(rows, key=lambda r: (-float(r["usable_response"]),
                                                CONTRACT_LIGHT_MODES.index(str(r["mode"])))))
    best = ranking[0]
    light = contract_light(str(best["mode"]))
    return LightChoice(mode=str(best["mode"]),
                       direction=tuple(float(x) for x in np.asarray(light.direction).reshape(3)),
                       color=tuple(float(x) for x in np.asarray(light.color).reshape(3)),
                       ambient=tuple(float(x) for x in np.asarray(light.ambient).reshape(3)),
                       response_score=float(lambert_response_score(normal_world=normal_world,
                                                                   light=light)),
                       ranking=ranking)


# ======================================================================================
# A3: a continuous, band-limited surface albedo bound to the sampling scale
# ======================================================================================
#: Feature wavelengths of the delivered albedo texture as fractions of the **material's own
#: correlation length** (``stats.correlation_length_mm``, the same audited statistic the relief
#: spectrum is built from).  ``(0.5, 1.0, 2.0) * correlation_length`` - for M01 coarse pottery
#: (2.6 mm) that is ``1.3 / 2.6 / 5.2 mm``, i.e. the material's grain, its correlation length and
#: one octave above it.  Expressing the scale in millimetres rather than in pixels is what makes
#: the texture describe ONE surface: at a finer ``mm/px`` the same three wavelengths simply land on
#: more pixels, their mm statistics stay identical, and the frequency-to-Nyquist ratio improves.
TEXTURE_WAVELENGTH_FRACTIONS: tuple[float, ...] = (0.5, 1.0, 2.0)

#: Unit propagation directions of the three texture plane waves as ``(dx, dy)`` with
#: ``dx^2 + dy^2 = 1``: ``(1, 0)``, ``(3, 4)/5`` and ``(5, 12)/13``.  The two oblique waves use
#: exact Pythagorean slopes so the pattern has no axis-aligned bias, and every wave is a pure
#: plane wave of one wavelength - the texture is band-limited by construction, it is not filtered
#: after the fact.
TEXTURE_WAVE_DIRECTIONS: tuple[tuple[float, float], ...] = ((1.0, 0.0), (3.0 / 5.0, 4.0 / 5.0),
                                                            (5.0 / 13.0, 12.0 / 13.0))

#: Shortest feature a texture may be delivered at, in delivered pixels.  ``5 px`` is 2.5x the
#: Nyquist limit, so the delivered texture can never alias; a rung that cannot carry a material's
#: shortest wavelength reports ``nyquist_ok = False`` instead of silently filtering it.
TEXTURE_MIN_PERIOD_PX: float = 5.0


@dataclass(frozen=True)
class AlbedoTexture:
    """A continuous band-limited albedo modulation bound to one delivered sampling scale.

    The modulation is a sum of three plane waves whose **physical** wavelengths are
    :data:`TEXTURE_WAVELENGTH_FRACTIONS` times the material's correlation length.  Its value at a
    point depends only on the point's position in millimetres, so:

    * it is C0-continuous across triangle boundaries (nothing in it depends on which triangle a
      point belongs to - which is what removes the per-face palette's facet pattern);
    * its feature scale is tied to ``mm/px``: the pixel wavelength of each wave is
      ``wavelength_mm / mm_per_px``, so a finer rung samples the same surface more densely;
    * it is band-limited by construction with a measurable dominant frequency;
    * it is normalised so its spatial RMS over a lattice window is exactly 1, so the delivered
      albedo keeps the material's mean colour and carries a modulation of known depth.
    """

    mm_per_px: float
    material_albedo: tuple[float, float, float]
    wavelengths_mm: tuple[float, ...]
    #: modulation depth: peak-to-mean contrast of the delivered albedo
    contrast: float = 0.30
    #: signature window used for the normalisation, in delivered pixels
    normalise_window_px: int = 512
    #: cached exact lattice RMS (depends only on the wavelengths, never on the query points)
    _rms_value: float | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def wavelengths_px(self) -> tuple[float, ...]:
        return tuple(float(w) / float(self.mm_per_px) for w in self.wavelengths_mm)

    @property
    def dominant_wavelength_mm(self) -> float:
        """The shortest wave carries the highest frequency, so it is the one Nyquist acts on."""
        return float(min(self.wavelengths_mm))

    @property
    def shortest_period_px(self) -> float:
        return float(min(self.wavelengths_px))

    def dominant_cycles_per_px(self) -> float:
        return 1.0 / self.shortest_period_px

    def dominant_cycles_per_mm(self) -> float:
        return 1.0 / self.dominant_wavelength_mm

    def nyquist_ratio(self, *, cycles_per_px: float | None = None) -> float:
        """Dominant spatial frequency as a fraction of Nyquist (0.5 cyc/px)."""
        f = self.dominant_cycles_per_px() if cycles_per_px is None else float(cycles_per_px)
        return float(f / 0.5)

    def nyquist_ok(self) -> bool:
        return bool(self.shortest_period_px >= TEXTURE_MIN_PERIOD_PX)

    def raw(self, uv_mm: np.ndarray) -> np.ndarray:
        """Un-normalised, zero-mean modulation at **millimetre** surface coordinates."""
        uv = np.asarray(uv_mm, dtype=np.float64).reshape(-1, 2)
        out = np.zeros(uv.shape[0], dtype=np.float64)
        for wl, (dx, dy) in zip(self.wavelengths_mm, TEXTURE_WAVE_DIRECTIONS):
            k = 2.0 * math.pi / float(wl)
            out += np.cos(k * (dx * uv[:, 0] + dy * uv[:, 1]))
        return out

    def rms(self, *, window_px: int | None = None) -> float:
        """Measured RMS of :meth:`raw` over an exact lattice window (not an assumed 1/sqrt(2))."""
        n = int(window_px if window_px is not None else self.normalise_window_px)
        ax = (np.arange(n, dtype=np.float64) + 0.5) * float(self.mm_per_px)
        uu, vv = np.meshgrid(ax, ax, indexing="ij")
        v = self.raw(np.stack([uu.ravel(), vv.ravel()], axis=1))
        return float(np.sqrt(np.mean(v ** 2)))

    def _rms_cached(self) -> float:
        """The exact lattice RMS, computed once (it depends only on the wavelengths)."""
        if self._rms_value is None:
            object.__setattr__(self, "_rms_value", float(self.rms()))
        return float(self._rms_value)

    def modulation(self, uv_mm: np.ndarray) -> np.ndarray:
        """Zero-mean modulation in ``[-1, 1] * contrast`` after exact RMS normalisation."""
        v = self.raw(uv_mm) / max(self._rms_cached(), 1e-30)
        return np.clip(float(self.contrast) * v, -0.95, 0.95)

    def albedo(self, uv_mm: np.ndarray) -> np.ndarray:
        """Per-point albedo: the material's own colour times ``1 + modulation`` (always positive)."""
        mod = self.modulation(uv_mm)
        base = np.asarray(self.material_albedo, dtype=np.float64).reshape(1, 3)
        return base * (1.0 + mod)[:, None]

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "CONTINUOUS_BANDLIMITED_ALBEDO",
                "mm_per_px": float(self.mm_per_px),
                "wavelengths_mm": [float(w) for w in self.wavelengths_mm],
                "wavelengths_px": [float(w) for w in self.wavelengths_px],
                "dominant_wavelength_mm": float(self.dominant_wavelength_mm),
                "dominant_cycles_per_px": float(self.dominant_cycles_per_px()),
                "dominant_cycles_per_mm": float(self.dominant_cycles_per_mm()),
                "nyquist_cycles_per_px": 0.5,
                "dominant_over_nyquist": float(self.nyquist_ratio()),
                "shortest_period_px": float(self.shortest_period_px),
                "min_period_px_required": float(TEXTURE_MIN_PERIOD_PX),
                "nyquist_ok": bool(self.nyquist_ok()),
                "contrast": float(self.contrast),
                "material_albedo": [float(x) for x in self.material_albedo],
                "wave_directions": [[float(a), float(b)] for a, b in TEXTURE_WAVE_DIRECTIONS],
                "wavelength_fractions_of_correlation_length":
                    [float(x) for x in TEXTURE_WAVELENGTH_FRACTIONS],
                "normalise_window_px": int(self.normalise_window_px),
                "measured_rms_before_normalisation": float(self.rms()),
                "definition": ("a sum of three plane waves whose wavelengths are fixed in "
                               "MILLIMETRES (fractions of the material correlation length); the "
                               "value depends only on position, so it is C0-continuous across "
                               "triangle boundaries, and its pixel wavelength is "
                               "wavelength_mm / mm_per_px")}


def make_albedo_texture(*, mm_per_px: float, material_albedo: Sequence[float],
                        correlation_length_mm: float, contrast: float = 0.30) -> AlbedoTexture:
    """The delivered albedo texture at one sampling scale, from the material's own length scale.

    ``correlation_length_mm`` is the audited ``stats.correlation_length_mm`` of the material record,
    the same statistic the relief band set is built from, so the texture's feature scale and the
    relief's feature scale are the same physical quantity rather than two unrelated knobs.
    """
    if not (float(mm_per_px) > 0.0):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "mm_per_px must be > 0",
                          stage="observe.fracture_appearance.make_albedo_texture")
    if not (float(correlation_length_mm) > 0.0):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "correlation_length_mm must be > 0",
                          stage="observe.fracture_appearance.make_albedo_texture")
    wl = tuple(float(f) * float(correlation_length_mm) for f in TEXTURE_WAVELENGTH_FRACTIONS)
    return AlbedoTexture(mm_per_px=float(mm_per_px),
                         material_albedo=tuple(float(x) for x in
                                               np.asarray(material_albedo).reshape(-1)[:3]),
                         wavelengths_mm=wl, contrast=float(contrast))


def texture_spectrum_report(texture: AlbedoTexture, *, n: int = 512) -> dict[str, Any]:
    """Measure the delivered texture's spectrum: dominant frequency, Nyquist ratio, anisotropy.

    The report is computed on a real ``n x n`` sampling of the modulation at one delivered pixel
    per sample, so it is the spectrum of what is actually delivered rather than of the formula.
    """
    ax = np.arange(n, dtype=np.float64)
    step = float(texture.mm_per_px)
    uu, vv = np.meshgrid(ax * step, ax * step, indexing="ij")
    img = texture.modulation(np.stack([uu.ravel(), vv.ravel()], axis=1)).reshape(n, n)
    win = np.hanning(n)[:, None] * np.hanning(n)[None, :]
    spec = np.abs(np.fft.fftshift(np.fft.fft2(img * win))) ** 2
    # ``d=step`` makes the FFT axes cycles per MILLIMETRE; the delivered lattice's Nyquist is
    # therefore 0.5/step cyc/mm, and dividing by it is the same as dividing the pixel-domain
    # frequency by 0.5 cyc/px.
    fy = np.fft.fftshift(np.fft.fftfreq(n, d=step))
    fx = fy.copy()
    kx, ky = np.meshgrid(fx, fy, indexing="ij")
    kr = np.hypot(kx, ky)
    nyquist_per_mm = 0.5 / step
    valid = kr > 0
    peak = float(kr[valid][np.argmax(spec[valid])])
    total = float(spec[valid].sum())
    gy, gx = np.gradient(img, step, step)
    jxx, jyy, jxy = float(np.mean(gx ** 2)), float(np.mean(gy ** 2)), float(np.mean(gx * gy))
    tr, det = jxx + jyy, jxx * jyy - jxy ** 2
    disc = math.sqrt(max(tr * tr / 4.0 - det, 0.0))
    lam1, lam2 = tr / 2.0 + disc, tr / 2.0 - disc
    return {
        "status": "OK", "grid": f"{n}x{n} at 1 delivered px ({step:.6f} mm)",
        "n": int(n), "mm_per_px": step,
        "dominant_cycles_per_mm": peak,
        "dominant_cycles_per_px": float(peak * step),
        "dominant_wavelength_mm": (float("inf") if peak <= 0 else 1.0 / peak),
        "dominant_wavelength_px": (float("inf") if peak <= 0 else 1.0 / (peak * step)),
        "nyquist_cycles_per_mm": float(nyquist_per_mm),
        "nyquist_cycles_per_px": 0.5,
        "dominant_over_nyquist": float(peak / nyquist_per_mm),
        "declared_dominant_over_nyquist": float(texture.nyquist_ratio()),
        "power_fraction_above_nyquist": float(
            spec[valid & (kr > nyquist_per_mm)].sum() / max(total, 1e-30)),
        "power_fraction_above_declared_shortest": float(
            spec[valid & (kr > 1.0 / texture.dominant_wavelength_mm)].sum()
            / max(total, 1e-30)),
        "modulation_rms": float(np.sqrt(np.mean(img ** 2))),
        "modulation_min": float(img.min()), "modulation_max": float(img.max()),
        "slope_rms_per_mm": float(np.sqrt(np.mean(gx ** 2 + gy ** 2))),
        "anisotropy": float((lam1 - lam2) / max(lam1 + lam2, 1e-30)),
        "nyquist_ok": bool(texture.nyquist_ok()),
        "definition": ("radial power spectrum of the delivered modulation sampled at one delivered "
                       "pixel per sample; a per-face palette has no spectrum (its 'frequency' is "
                       "one cycle per triangle) while this texture is band-limited by construction"),
    }


def texture_consistency_report(*, material_albedo: Sequence[float], correlation_length_mm: float,
                               rungs_mm_per_px: Sequence[float], contrast: float = 0.30,
                               n: int = 512) -> dict[str, Any]:
    """The same material at several ``mm/px`` rungs: does the texture describe one surface?

    For each rung the texture is built with that rung's scale and its spectrum is measured.  Two
    rungs are *consistent* when their physical statistics agree - the same wavelengths in
    millimetres, the same dominant frequency in ``cyc/mm``, the same modulation RMS and the same
    ``mm^-1`` slope RMS - while their pixel wavelengths scale exactly as ``1/mm_per_px``.  That is
    the precise statement of "the feature scale is bound to ``mm/px`` while the surface is not".
    """
    rows: list[dict[str, Any]] = []
    for rung in rungs_mm_per_px:
        tex = make_albedo_texture(mm_per_px=float(rung), material_albedo=material_albedo,
                                  correlation_length_mm=float(correlation_length_mm),
                                  contrast=contrast)
        rep = texture_spectrum_report(tex, n=n)
        rows.append({
            "mm_per_px": float(rung),
            "wavelengths_mm": [float(w) for w in tex.wavelengths_mm],
            "wavelengths_px": [float(w) for w in tex.wavelengths_px],
            "dominant_cycles_per_px": float(rep["dominant_cycles_per_px"]),
            "dominant_cycles_per_mm": float(rep["dominant_cycles_per_mm"]),
            "dominant_wavelength_mm": float(rep["dominant_wavelength_mm"]),
            "dominant_over_nyquist": float(rep["dominant_over_nyquist"]),
            "nyquist_ok": bool(rep["nyquist_ok"]),
            "shortest_period_px": float(tex.shortest_period_px),
            "power_fraction_above_nyquist": float(rep["power_fraction_above_nyquist"]),
            "modulation_rms": float(rep["modulation_rms"]),
            "slope_rms_per_mm": float(rep["slope_rms_per_mm"]),
            "anisotropy": float(rep["anisotropy"]),
        })
    ref = rows[0] if rows else None
    for row in rows:
        if ref:
            row["wavelengths_mm_ratio_to_first"] = [float(a / b) for a, b
                                                    in zip(row["wavelengths_mm"],
                                                           ref["wavelengths_mm"])]
            row["wavelengths_px_ratio_to_first"] = [float(a / b) for a, b
                                                    in zip(row["wavelengths_px"],
                                                           ref["wavelengths_px"])]
            row["slope_rms_ratio_to_first"] = float(
                row["slope_rms_per_mm"] / max(float(ref["slope_rms_per_mm"]), 1e-30))
            row["modulation_rms_ratio_to_first"] = float(
                row["modulation_rms"] / max(float(ref["modulation_rms"]), 1e-30))
    dev = max((max(abs(float(r["slope_rms_ratio_to_first"]) - 1.0),
                   abs(float(r["modulation_rms_ratio_to_first"]) - 1.0),
                   max(abs(float(x) - 1.0) for x in r["wavelengths_mm_ratio_to_first"]))
               for r in rows), default=float("inf"))
    all_ok = all(bool(r["nyquist_ok"]) for r in rows)
    return {
        "status": "OK", "rows": rows, "contrast": float(contrast),
        "correlation_length_mm": float(correlation_length_mm),
        "max_relative_deviation": float(dev),
        "nyquist_ok_every_rung": bool(all_ok),
        "verdict": ("CONSISTENT" if dev < 0.05 and all_ok
                    else ("CONSISTENT_BUT_ALIASED" if dev < 0.05 else "INCONSISTENT")),
        "definition": ("each rung gets the texture built with ITS mm/px from the material's own "
                       "correlation length; a consistent texture must give the same wavelengths in "
                       "mm and the same mm^-1 slope RMS, while the pixel wavelengths scale as "
                       "1/mm_per_px and the frequency-to-Nyquist ratio improves with a finer rung"),
    }


# ======================================================================================
# geometry hashing (so "the geometry did not change" is checkable)
# ======================================================================================
def geometry_hash(vertices: np.ndarray, faces: np.ndarray) -> str:
    """SHA-256 over the exact vertex and face bytes (normals are *not* part of the geometry)."""
    v = np.ascontiguousarray(np.asarray(vertices, dtype=np.float64))
    f = np.ascontiguousarray(np.asarray(faces, dtype=np.int64))
    h = hashlib.sha256()
    h.update(str(v.shape).encode("ascii"))
    h.update(v.tobytes())
    h.update(str(f.shape).encode("ascii"))
    h.update(f.tobytes())
    return "sha256:" + h.hexdigest()


# ======================================================================================
# normals
# ======================================================================================
def face_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Unit face normals (counter-clockwise winding)."""
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)


def _vertex_face_adjacency(faces: np.ndarray, n_vertices: int
                           ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(flat_face, starts, stops)``: for vertex ``v`` the incident faces are
    ``flat_face[starts[v]:stops[v]]`` (CSR-style, built once)."""
    f = np.asarray(faces, dtype=np.int64)
    flat_vert = f.reshape(-1)
    order = np.argsort(flat_vert, kind="stable")
    sorted_vert = flat_vert[order]
    sorted_face = np.repeat(np.arange(f.shape[0], dtype=np.int64), 3)[order]
    counts = np.bincount(sorted_vert, minlength=int(n_vertices))
    starts = np.concatenate(([0], np.cumsum(counts)[:-1])).astype(np.int64)
    stops = np.cumsum(counts).astype(np.int64)
    return sorted_face, starts, stops


def vertex_normals(vertices: np.ndarray, faces: np.ndarray, *,
                   weighting: str = "AREA") -> np.ndarray:
    """Per-vertex normals of the real mesh; ``AREA`` weights each face by its own area."""
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    fn = face_normals(v, f)
    if weighting == "AREA":
        w = 0.5 * np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]),
                                 axis=1)
    elif weighting in ("ANGLE", "UNIFORM"):
        w = np.ones(f.shape[0], dtype=np.float64)
    else:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown weighting {weighting!r}",
                          stage="observe.fracture_appearance.vertex_normals")
    acc = np.zeros_like(v)
    contrib = fn * w[:, None]
    for k in range(3):
        np.add.at(acc, f[:, k], contrib)
    norm = np.linalg.norm(acc, axis=1, keepdims=True)
    norm[norm < 1e-30] = 1.0
    return acc / norm


def corner_normals(vertices: np.ndarray, faces: np.ndarray, *,
                   crease_angle_deg: float = 180.0) -> np.ndarray:
    """Face-varying corner normals with a crease angle: shape ``(F, 3, 3)``.

    Each corner averages the unit normals of the faces sharing its vertex **that lie within
    ``crease_angle_deg`` of the face's own normal**.  With ``crease_angle_deg = 180`` this equals
    area-weighted vertex normals (pure smooth shading); with a finite angle a genuine edge - the
    rim of a sherd is one - stays a crease instead of being rounded away.
    """
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    fn = face_normals(v, f)
    cos_limit = math.cos(math.radians(float(np.clip(crease_angle_deg, 0.0, 180.0))))
    flat_face, starts, stops = _vertex_face_adjacency(f, v.shape[0])
    out = np.zeros((f.shape[0], 3, 3), dtype=np.float64)
    filled = np.zeros((f.shape[0], 3), dtype=bool)
    flat_verts = f.reshape(-1)
    # one pass per vertex; each (face, corner) pair of that vertex is resolved with the same
    # incident-face list, so a vertex with valence k costs O(k^2) dot products, not O(F).
    for vid in np.unique(flat_verts):
        a, b = int(starts[vid]), int(stops[vid])
        if b <= a:
            continue
        inc = flat_face[a:b]
        n_inc = fn[inc]
        local = np.nonzero(np.isin(f, vid))
        rows, cols = local[0], local[1]
        for row, col in zip(rows.tolist(), cols.tolist()):
            keep = (n_inc @ fn[row]) >= cos_limit
            acc = n_inc[keep].sum(axis=0)
            norm = float(np.linalg.norm(acc))
            out[row, col] = (acc / norm) if norm > 1e-30 else fn[row]
            filled[row, col] = True
    if not filled.all():
        rows, cols = np.nonzero(~filled)
        out[rows, cols] = fn[rows]
    return out


# ======================================================================================
# material statistics -> fracture appearance parameters
# ======================================================================================
@dataclass(frozen=True)
class AppearanceParameters:
    """Measured material statistics that drive the fracture appearance, with their origin."""

    material_id: str
    material_name: str
    grain_scale_mm: float
    correlation_length_mm: float
    porosity: float
    pore_amount: float
    pore_scale_mm: float
    grain_amount: float
    aggregate_amount: float
    aggregate_radius_mm: float
    anisotropy: float
    fiber_period_mm: float
    fiber_amount: float
    glaze_thickness_mm: float
    glaze_kind: str
    transmission: float
    albedo: tuple[float, float, float]
    roughness: float
    ior: float
    cut_mode: str
    #: ``sigma_r0`` of the audited morphology model: the band-field RMS height of the fracture
    #: surface, from ``morphology.derive_morphology_parameters`` (never invented here).
    sigma_r0_mm: float
    #: shortest / longest wavelength of the audited band set (mm).
    lambda_min_mm: float
    lambda_max_mm: float
    band_wavelengths_mm: tuple[float, ...]
    band_amplitudes_mm: tuple[float, ...]
    source: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["albedo"] = [float(x) for x in self.albedo]
        d["band_wavelengths_mm"] = [float(x) for x in self.band_wavelengths_mm]
        d["band_amplitudes_mm"] = [float(x) for x in self.band_amplitudes_mm]
        return d


def appearance_parameters_from_profile(profile: Mapping[str, Any],
                                       *, material_id: str = "") -> AppearanceParameters:
    """Map a real material profile to fracture-appearance parameters (measured, not invented).

    The mapping is **the project's own audited relation set** of
    :mod:`synlab.fracture.morphology`: ``material_fracture_inputs`` extracts the measured fields
    (grain scale, correlation length, pore amount/scale, fibre period/amount/direction, glaze
    thickness/kind, anisotropy) and ``sigma_r0 = c_g * grain * (1 + c_p * porosity)`` turns them
    into the surface-relief RMS; the band spectrum is the audited ``a(k) ~ k^-(H+1/2)`` set
    ``a_i = lc * 2^(i - (n-1)/2)``.  No wall measurement is needed for either, so the parameters
    can be reported for every material in the catalogue.
    """
    from ..fracture import morphology as mo

    inputs = mo.material_fracture_inputs(profile, material_id=material_id)
    stats = dict(profile.get("stats") or {})
    appearance = dict(profile.get("appearance") or {})
    cut = dict(stats.get("cut_statistics") or {})

    grain = float(max(inputs.grain_scale_mm, 1e-3))
    lc = float(max(inputs.correlation_length_mm, 1e-3))
    sigma_r0 = float(max(mo.GRAIN_RELIEF_FRACTION * grain
                        * (1.0 + mo.POROSITY_RELIEF_GAIN * float(inputs.porosity)), 1e-4))
    wavelengths = np.array([lc * (2.0 ** (i - (mo.ROUGHNESS_BANDS - 1) / 2.0))
                            for i in range(mo.ROUGHNESS_BANDS)], dtype=np.float64)
    wavelengths = np.clip(wavelengths, 0.20, max(4.0 * lc, 0.5))
    k = 2.0 * np.pi / wavelengths
    raw = (k / (2.0 * np.pi / lc)) ** (-(mo.HURST_EXPONENT + 0.5))
    raw = raw / max(float(np.sqrt(np.sum(0.5 * raw ** 2))), 1e-30)
    amplitudes = raw * sigma_r0

    albedo = appearance.get("albedo") or [0.55, 0.52, 0.48]
    return AppearanceParameters(
        material_id=str(inputs.material_id or material_id),
        material_name=str(profile.get("material_name") or ""),
        grain_scale_mm=grain, correlation_length_mm=lc,
        porosity=float(inputs.porosity), pore_amount=float(inputs.pore_amount),
        pore_scale_mm=float(inputs.pore_scale_mm), grain_amount=float(inputs.grain_amount),
        aggregate_amount=float(inputs.aggregate_amount),
        aggregate_radius_mm=float(inputs.aggregate_radius_mm),
        anisotropy=float(inputs.anisotropy), fiber_period_mm=float(inputs.fiber_period_mm),
        fiber_amount=float(inputs.fiber_amount),
        glaze_thickness_mm=float(inputs.glaze_thickness_mm),
        glaze_kind=str(inputs.glaze_kind),
        transmission=float(appearance.get("transmission") or 0.0),
        albedo=tuple(float(x) for x in np.asarray(albedo, dtype=np.float64).reshape(-1)[:3]),
        roughness=float(appearance.get("roughness") or 0.0),
        ior=float(appearance.get("ior") or 0.0),
        cut_mode=str(cut.get("mode") or ""),
        sigma_r0_mm=sigma_r0,
        lambda_min_mm=float(wavelengths.min()), lambda_max_mm=float(wavelengths.max()),
        band_wavelengths_mm=tuple(float(x) for x in wavelengths),
        band_amplitudes_mm=tuple(float(x) for x in amplitudes),
        source={
            "sigma_r0_mm": f"synlab.fracture.morphology: {mo._RELIEF_FORMULA} "
                           f"(c_g={mo.GRAIN_RELIEF_FRACTION}, c_p={mo.POROSITY_RELIEF_GAIN})",
            "spectrum": f"synlab.fracture.morphology: {mo._SPECTRUM_FORMULA} "
                        f"(H={mo.HURST_EXPONENT}, bands={mo.ROUGHNESS_BANDS})",
            "porosity": f"morphology.material_fracture_inputs: porosity = "
                        f"{mo.POROSITY_FROM_PORE_AMOUNT} * pore_amount",
            "grain_scale_mm": "material profile stats.grain_scale_mm (measured)",
            "correlation_length_mm": "material profile stats.correlation_length_mm (measured)",
            "fiber": "profile stats.fiber_period_mm + appearance.fiber_amount",
            "glaze": "profile layers[name~glaze/paint].thickness_mm",
            "transmission": "profile appearance.transmission",
        },
    )


# ======================================================================================
# relief field: the audited morphology height field over the ROI plane
# ======================================================================================
@dataclass
class ReliefField:
    """Per-pixel normal-channel relief over one fracture ROI.

    ``height`` is a :class:`synlab.fracture.morphology.MorphologyHeightField`; only its analytic
    ``raw`` / ``gradient`` are used, in the ROI plane's ``(u, v)`` millimetres.  ``amplitude_scale``
    multiplies the field, so the realised ``Ra`` on the ROI is ``amplitude_scale * ra_at_unit_mm``
    with ``ra_at_unit_mm`` measured on a real sample grid - reported, never assumed.
    """

    height: Any
    origin_mm: np.ndarray
    u_axis: np.ndarray
    v_axis: np.ndarray
    normal: np.ndarray
    footprint_radius_mm: float
    ramp_width_mm: float
    parameters: AppearanceParameters
    amplitude_scale: float = 1.0
    ra_at_unit_mm: float = 0.0
    rq_at_unit_mm: float = 0.0
    sample_mm: float = 0.0
    dome_share: float = 0.0
    slope_rms_at_unit: float = 0.0
    slope_p95_at_unit: float = 0.0
    glaze_strip: Any = None
    meta: dict[str, Any] = field(default_factory=dict)
    #: cached (gu, gv) grid at unit amplitude, used only by :meth:`predicted_shading_ddn`
    _grid_cache: Any = None

    @property
    def realized_ra_mm(self) -> float:
        return float(self.amplitude_scale) * float(self.ra_at_unit_mm)

    def uv(self, points_world: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rel = np.asarray(points_world, dtype=np.float64).reshape(-1, 3) - self.origin_mm[None, :]
        return rel @ self.u_axis, rel @ self.v_axis

    def envelope(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Smooth radial envelope: exactly 1 inside the ROI radius, 0 beyond radius + ramp."""
        return _envelope(u, v, float(self.footprint_radius_mm), float(self.ramp_width_mm))[0]

    def sample(self, points_world: np.ndarray, *,
               scale: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(h, dh/du, dh/dv)`` at world points (mm and mm/mm), envelope included exactly.

        The envelope multiplies the height, so its gradient carries the extra term
        ``h * d(env)/du``; that term is evaluated analytically here instead of being dropped
        (dropping it would draw a bright ring at the ROI boundary).  The glaze strip multiplies the
        relief as well, with its own rasterised gradient.
        """
        s = float(self.amplitude_scale if scale is None else scale)
        u, v = self.uv(points_world)
        env, d_env_du, d_env_dv = _envelope(u, v, float(self.footprint_radius_mm),
                                            float(self.ramp_width_mm))
        h_raw = np.asarray(self.height.raw(u, v), dtype=np.float64) * s
        gu, gv = self.height.gradient(u, v)
        gu = np.asarray(gu, dtype=np.float64) * s
        gv = np.asarray(gv, dtype=np.float64) * s
        if self.glaze_strip is None:
            return (h_raw * env, env * gu + h_raw * d_env_du, env * gv + h_raw * d_env_dv)
        mod, d_mod_du, d_mod_dv = self.glaze_strip.sample(u, v)
        return (h_raw * env * mod,
                (env * mod) * gu + (h_raw * mod) * d_env_du + (h_raw * env) * d_mod_du,
                (env * mod) * gv + (h_raw * mod) * d_env_dv + (h_raw * env) * d_mod_dv)

    def predicted_shading_ddn(self, *, albedo: Sequence[float], light: LightSpec,
                              T_WC: np.ndarray, ra_scale: float = 1.0,
                              levels: float = 255.0) -> dict[str, Any]:
        """Predicted ``dDN`` of this field under the frozen model, using the *same* normals.

        The frozen shading is ``lambert = clip(-(n @ T_WC[:3, :3] @ light.direction), 0, 1)``, so
        the perturbation ``n -> n - gu*t_u - gv*t_v`` changes it by ``-(dn . l_eff)`` with
        ``l_eff = T_WC[:3, :3] @ light.direction`` in world coordinates.  The RMS of that quantity
        is evaluated on the field's **own** sample grid, which makes the prediction apples to apples
        with the rendered difference: it uses the real gradient field (whose RMS is dominated by the
        small-area pit and hackle features), not a nominal ``2 pi A / lambda``.
        """
        l_eff = np.asarray(light.direction, dtype=np.float64).reshape(3)
        a_u = float(np.dot(self.u_axis, l_eff))
        a_v = float(np.dot(self.v_axis, l_eff))
        gu, gv = self._grid_gradients()
        d_lambert = float(ra_scale) * (gu * a_u + gv * a_v)
        rms = float(np.sqrt(np.mean(d_lambert ** 2)))
        alb = np.asarray(albedo, dtype=np.float64).reshape(-1)[:3]
        factor = float(levels) * float(np.mean(alb * np.asarray(light.color, dtype=np.float64)))
        return {
            "light_effective_world": [float(x) for x in l_eff],
            "tangent_projection_u": a_u, "tangent_projection_v": a_v,
            "d_lambert_rms": rms, "predicted_dDN": factor * rms,
            "d_lambert_p95_abs": float(np.percentile(np.abs(d_lambert), 95)),
            "predicted_dDN_p95": factor * float(np.percentile(np.abs(d_lambert), 95)),
            "grid_points": int(gu.size), "ra_scale": float(ra_scale),
            "convention": ("d_lambert = ra_scale * (dh/du * (t_u . l_eff) + dh/dv * (t_v . l_eff)); "
                           "dDN = 255 * mean_c(albedo_c * color_c) * d_lambert; the clip of the "
                           "frozen Lambert term is NOT modelled, so this is an upper bound where "
                           "the surface sits at the terminator"),
        }

    def predicted_shading_ddn_on_points(self, points_world: np.ndarray, *,
                                        albedo: Sequence[float], light: LightSpec,
                                        base_normals: np.ndarray | None = None,
                                        ra_scale: float | None = None,
                                        levels: float = 255.0) -> dict[str, Any]:
        """Predicted ``dDN`` **on a given point set**, with the renderer's own linearisation.

        This is the scale-free form of :meth:`predicted_shading_ddn` and the one that is comparable
        with a rendered difference.  The renderer evaluates, per pixel,

            ``tp = t_p - (n . t_p) n`` (renormalised),  ``n' = normalize(n - amp*gu*tu - amp*gv*tv)``

        so the first-order change of the frozen Lambert term is
        ``d_lambert = amp * sum_p (dh/dp) * (tp_hat . light.direction)``.  Evaluating that on the
        points the renderer actually shaded is what makes prediction and measurement agree; the
        ``_grid_gradients`` variant is kept only as the legacy ROI-grid number and is biased low
        wherever the grid's radius distribution differs from the rendered pixels' (measured:
        finite forward differences recover ``0.437`` of the analytic gradient RMS ``0.783``, a
        factor ``1.79``, and that bias is *radius dependent*).
        """
        pts = np.asarray(points_world, dtype=np.float64).reshape(-1, 3)
        if pts.shape[0] == 0:
            return {"status": "NO_POINTS", "n_points": 0}
        _, gu, gv = self.sample(pts, scale=1.0)
        s = float(self.amplitude_scale if ra_scale is None else ra_scale)
        l_eff = np.asarray(light.direction, dtype=np.float64).reshape(3)
        if base_normals is None:
            n0 = np.repeat(np.asarray(self.normal, dtype=np.float64).reshape(1, 3), pts.shape[0],
                           axis=0)
        else:
            n0 = np.asarray(base_normals, dtype=np.float64).reshape(-1, 3)
        n0 = n0 / np.maximum(np.linalg.norm(n0, axis=1, keepdims=True), 1e-30)
        def _proj(t):
            p = t[None, :] - (n0 @ t)[:, None] * n0
            return p / np.maximum(np.linalg.norm(p, axis=1, keepdims=True), 1e-30)
        tu, tv = _proj(self.u_axis), _proj(self.v_axis)
        d_lambert = s * (gu * (tu @ l_eff) + gv * (tv @ l_eff))
        rms = float(np.sqrt(np.mean(d_lambert ** 2)))
        alb = np.asarray(albedo, dtype=np.float64).reshape(-1)[:3]
        factor = float(levels) * float(np.mean(alb * np.asarray(light.color, dtype=np.float64)))
        return {
            "status": "OK", "n_points": int(pts.shape[0]),
            "gradient_rms": float(np.sqrt(np.mean(gu ** 2 + gv ** 2))),
            "d_lambert_rms": rms, "predicted_dDN": factor * rms,
            "d_lambert_p95_abs": float(np.percentile(np.abs(d_lambert), 95)),
            "predicted_dDN_p95": factor * float(np.percentile(np.abs(d_lambert), 95)),
            "albedo_channels_used": [float(x) for x in alb],
            "ra_scale": s, "levels": float(levels),
            "convention": ("evaluated at the renderer's own hit points with the renderer's own "
                           "tangent renormalisation; the clip of the frozen Lambert term is not "
                           "modelled, so this is an upper bound at the terminator"),
        }

    def _grid_gradients(self) -> tuple[np.ndarray, np.ndarray]:
        """Cached gradient grid of the field at unit amplitude (mm/mm), envelope included."""
        if self._grid_cache is None:
            radius = float(self.footprint_radius_mm)
            step = float(self.sample_mm)
            uu, vv = np.meshgrid(np.arange(-radius, radius + 0.5 * step, step),
                                 np.arange(-radius, radius + 0.5 * step, step), indexing="ij")
            gu, gv = self.height.gradient(uu, vv)
            env, d_env_du, d_env_dv = _envelope(uu, vv, radius, float(self.ramp_width_mm))
            h_raw = np.asarray(self.height.raw(uu, vv), dtype=np.float64)
            self._grid_cache = (env * np.asarray(gu, dtype=np.float64) + h_raw * d_env_du,
                                env * np.asarray(gv, dtype=np.float64) + h_raw * d_env_dv)
        return self._grid_cache

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": APPEARANCE_SCHEMA + ".relief",
            "kind": "MORPHOLOGY_HEIGHT_FIELD_NORMAL_CHANNEL",
            "material_id": self.parameters.material_id,
            "origin_mm": [float(x) for x in self.origin_mm],
            "u_axis": [float(x) for x in self.u_axis],
            "v_axis": [float(x) for x in self.v_axis],
            "normal": [float(x) for x in self.normal],
            "footprint_radius_mm": float(self.footprint_radius_mm),
            "ramp_width_mm": float(self.ramp_width_mm),
            "amplitude_scale": float(self.amplitude_scale),
            "ra_at_unit_mm": float(self.ra_at_unit_mm),
            "rq_at_unit_mm": float(self.rq_at_unit_mm),
            "realized_ra_mm": self.realized_ra_mm,
            "sample_mm": float(self.sample_mm),
            "dome_share_of_ra_unit": float(self.dome_share),
            "slope_rms_at_unit_scale": float(self.slope_rms_at_unit),
            "slope_p95_at_unit_scale": float(self.slope_p95_at_unit),
            "lambda_min_mm": float(self.parameters.lambda_min_mm),
            "lambda_max_mm": float(self.parameters.lambda_max_mm),
            "sigma_r0_mm": float(self.parameters.sigma_r0_mm),
            "band_wavelengths_mm": [float(x) for x in self.parameters.band_wavelengths_mm],
            "band_amplitudes_mm": [float(x) for x in self.parameters.band_amplitudes_mm],
            "glaze_strip": None if self.glaze_strip is None else self.glaze_strip.as_dict(),
            "height_field_class": f"{type(self.height).__module__}.{type(self.height).__name__}",
            "geometry_modified": False,
            "meta": dict(self.meta),
        }


def _envelope(u: np.ndarray, v: np.ndarray, radius_mm: float, ramp_width_mm: float
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Smootherstep radial envelope and its exact ``(d/du, d/dv)``.

    ``env(r) = smoothstep(t)`` with ``t = clip((R + w - r) / w, 0, 1)``; hence
    ``d(env)/du = 6 t (1 - t) * (-1/w) * (u / r)`` on the ramp and 0 elsewhere.
    """
    uu = np.asarray(u, dtype=np.float64)
    vv = np.asarray(v, dtype=np.float64)
    w = max(float(ramp_width_mm), 1e-9)
    r = np.hypot(uu, vv)
    t = np.clip((float(radius_mm) + w - r) / w, 0.0, 1.0)
    env = t * t * (3.0 - 2.0 * t)
    on_ramp = (t > 0.0) & (t < 1.0)
    d_env_dt = 6.0 * t * (1.0 - t)
    safe_r = np.where(r > 1e-12, r, 1.0)
    factor = np.where(on_ramp, d_env_dt * (-1.0 / w) / safe_r, 0.0)
    return env, factor * uu, factor * vv


def _patch_triangles_uv(patch_vertices: np.ndarray, patch_triangles: np.ndarray,
                        origin: np.ndarray, u_axis: np.ndarray, v_axis: np.ndarray) -> np.ndarray:
    """``(n, 3, 2)`` ROI-plane coordinates of the patch triangles.

    ``patch_triangles`` is the ``(n, 3)`` **vertex-index** array of the patch (i.e.
    ``mesh.faces[face_mask]``), not a list of face indices.
    """
    verts = np.asarray(patch_vertices, dtype=np.float64)
    tri = verts[np.asarray(patch_triangles, dtype=np.int64)] - \
        np.asarray(origin, dtype=np.float64)[None, None, :]
    return np.stack([tri @ np.asarray(u_axis, dtype=np.float64),
                     tri @ np.asarray(v_axis, dtype=np.float64)], axis=2)


def _unit2(vector: Any) -> np.ndarray:
    v = np.asarray(vector, dtype=np.float64).reshape(-1)[:2]
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([1.0, 0.0])


def tangent_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic orthonormal ``(u, v)`` basis of the plane with the given unit normal."""
    n = np.asarray(normal, dtype=np.float64).reshape(3)
    n = n / max(float(np.linalg.norm(n)), 1e-30)
    helper = np.array([0.0, 1.0, 0.0]) if abs(float(n[1])) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(helper, n)
    u /= max(float(np.linalg.norm(u)), 1e-30)
    v = np.cross(n, u)
    return u, v


def triangle_areas_uv(tris_uv: np.ndarray) -> np.ndarray:
    t = np.asarray(tris_uv, dtype=np.float64).reshape(-1, 3, 2)
    return 0.5 * np.abs((t[:, 1, 0] - t[:, 0, 0]) * (t[:, 2, 1] - t[:, 0, 1])
                        - (t[:, 2, 0] - t[:, 0, 0]) * (t[:, 1, 1] - t[:, 0, 1]))


def measure_wall_thickness_mm(mesh: Any, points: np.ndarray, inward: np.ndarray, *,
                              max_probes: int = 240, clearance_mm: float = 0.1,
                              max_thickness_mm: float = 200.0,
                              rng: np.random.Generator | None = None) -> dict[str, Any]:
    """Wall thickness under the fracture patch, measured by casting rays from the patch inward.

    The instrument is the target's own ``trimesh`` ray engine - the same one
    :mod:`synlab.observe.fracture_roi` uses.  Two measured properties of these assets force the
    two declared guards:

    * the delivered fracture shells carry **coincident duplicate** interface faces (the
      mixed-level T-junction defect of ``docs/a12/fracture_realism.md`` §10.5), so the first hit
      is the duplicate itself at ~0 mm: hits closer than ``clearance_mm`` are discarded;
    * a ray can escape through an open boundary, so hits beyond ``max_thickness_mm`` are dropped.
    """
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    dirs = np.asarray(inward, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] == 0:
        return {"status": "NO_PROBES", "probes": 0}
    if pts.shape[0] > int(max_probes):
        idx = (rng.choice(pts.shape[0], size=int(max_probes), replace=False) if rng is not None
               else np.linspace(0, pts.shape[0] - 1, int(max_probes)).astype(int))
        pts, dirs = pts[idx], dirs[idx]
    origins = pts + 1e-6 * dirs
    hit = mesh.ray.intersects_location(origins, dirs, multiple_hits=True)
    locations = np.asarray(hit[0], dtype=np.float64) if len(hit) else np.zeros((0, 3))
    index_ray = (np.asarray(hit[1], dtype=np.int64).reshape(-1) if len(hit) > 1
                 else np.zeros((0,), dtype=np.int64))
    # ``np.minimum`` propagates NaN, so the accumulator starts at +inf and is masked at the end
    thickness = np.full(origins.shape[0], np.inf, dtype=np.float64)
    n_hits = np.zeros(origins.shape[0], dtype=np.int64)
    if index_ray.size:
        t = np.linalg.norm(locations - origins[index_ray], axis=1)
        np.add.at(n_hits, index_ray, 1)
        keep = (t > float(clearance_mm)) & (t < float(max_thickness_mm))
        np.minimum.at(thickness, index_ray[keep], t[keep])
    thickness[~np.isfinite(thickness)] = np.nan
    valid = thickness[np.isfinite(thickness)]
    base = {"probes": int(origins.shape[0]), "n_valid": int(valid.size),
            "clearance_mm": float(clearance_mm), "max_thickness_mm": float(max_thickness_mm),
            "hits_per_ray_median": float(np.median(n_hits)) if n_hits.size else 0.0,
            "instrument": ("trimesh ray cast from fracture samples along -normal, "
                           "multiple_hits=True; hits <= clearance or >= max are discarded "
                           "(coincident duplicate faces and open boundaries)")}
    if valid.size == 0:
        return {"status": "NO_HIT", **base}
    return {"status": "OK", **base,
            "min_mm": float(valid.min()), "p05_mm": float(np.percentile(valid, 5)),
            "median_mm": float(np.median(valid)), "max_mm": float(valid.max())}


@dataclass
class _GlazeStrip:
    """The audited glaze term: relief damped to ``ratio`` inside a strip along the patch edge.

    ``morphology._GLAZE_FORMULA`` = "strip = t_glaze * k_geo along the cross-section boundary;
    relief *= ratio".  Realised here as a distance-transform raster over the patch's own ``(u, v)``
    extent, so the strip follows the *real* fracture front rather than a circle.
    """

    grid: np.ndarray          # (nu, nv) modulation, 1 far from the boundary
    u0: float
    v0: float
    step_mm: float
    strip_width_mm: float
    ratio: float

    def sample(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(modulation, d mod/du, d mod/dv)`` by bilinear lookup, outside the patch = 1.

        ``cv2.remap`` wants ``(H, W)`` maps, so a flat query of N points is reshaped to ``(N, 1)``
        and the result is reshaped back: the renderer queries one point per pixel, the builder
        queries a whole grid, and both must give the same array shape back.
        """
        import cv2

        shape = np.broadcast(np.asarray(u, dtype=np.float64),
                             np.asarray(v, dtype=np.float64)).shape
        iu = ((np.asarray(u, dtype=np.float64) - self.u0) / self.step_mm)
        iv = ((np.asarray(v, dtype=np.float64) - self.v0) / self.step_mm)
        iu = np.ascontiguousarray(iu.astype(np.float32).reshape(-1, 1))
        iv = np.ascontiguousarray(iv.astype(np.float32).reshape(-1, 1))
        grid = self.grid.astype(np.float32)
        mod = cv2.remap(grid, iu, iv, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                        borderValue=1.0)
        gy, gx = np.gradient(self.grid.astype(np.float64), self.step_mm)
        d_mod_du = cv2.remap(gx.astype(np.float32), iu, iv, cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
        d_mod_dv = cv2.remap(gy.astype(np.float32), iu, iv, cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
        return (mod.astype(np.float64).reshape(shape),
                d_mod_du.astype(np.float64).reshape(shape),
                d_mod_dv.astype(np.float64).reshape(shape))

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "GLAZE_RELIEF_DAMPING_STRIP", "strip_width_mm": float(self.strip_width_mm),
                "ratio": float(self.ratio), "step_mm": float(self.step_mm),
                "grid": [int(self.grid.shape[0]), int(self.grid.shape[1])],
                "formula": "morphology._GLAZE_FORMULA"}


def build_glaze_strip(*, tris_uv: np.ndarray, strip_width_mm: float, ratio: float,
                      step_mm: float | None = None) -> _GlazeStrip:
    """Rasterise the glaze damping strip along the real patch boundary."""
    import cv2

    from ..fracture.morphology import points_in_triangles

    t = np.asarray(tris_uv, dtype=np.float64).reshape(-1, 3, 2)
    lo = t.reshape(-1, 2).min(axis=0)
    hi = t.reshape(-1, 2).max(axis=0)
    step = float(step_mm if step_mm is not None else max(strip_width_mm / 6.0, 0.05))
    nu = int(max(8, math.ceil((hi[0] - lo[0]) / step) + 1))
    nv = int(max(8, math.ceil((hi[1] - lo[1]) / step) + 1))
    uu, vv = np.meshgrid(lo[0] + step * np.arange(nu), lo[1] + step * np.arange(nv),
                         indexing="ij")
    inside = points_in_triangles(np.stack([uu.ravel(), vv.ravel()], axis=1), t)
    mask = inside.reshape(nu, nv).astype(np.uint8)
    if mask.sum() == 0:
        return _GlazeStrip(grid=np.ones((nu, nv)), u0=float(lo[0]), v0=float(lo[1]),
                           step_mm=step, strip_width_mm=float(strip_width_mm),
                           ratio=float(ratio))
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5) * step
    t_norm = np.clip(dist / max(float(strip_width_mm), 1e-9), 0.0, 1.0)
    smooth = t_norm * t_norm * (3.0 - 2.0 * t_norm)
    grid = 1.0 - smooth * (1.0 - float(ratio))
    grid[mask == 0] = 1.0
    return _GlazeStrip(grid=grid, u0=float(lo[0]), v0=float(lo[1]), step_mm=step,
                       strip_width_mm=float(strip_width_mm), ratio=float(ratio))


def build_relief_field(*, profile: Mapping[str, Any], roi: Any, patch_vertices: np.ndarray,
                       patch_triangles: np.ndarray, mesh: Any | None = None,
                       rng: np.random.Generator, amplitude_mm: float | None = None,
                       ramp_width_mm: float = 2.0, sample_mm: float | None = None,
                       material_id: str = "", window_area_mm2: float | None = None,
                       wall: Any | None = None, error_budget_mm: float = 0.01,
                       max_cells: int = 30000, glaze_strip: bool = True,
                       include_dome: bool = False) -> ReliefField:
    """Realise the audited morphology field of one material over one fracture ROI.

    ``patch_triangles`` is the ``(n, 3)`` vertex-index array of the fracture patch
    (``mesh.faces[patch_face_indices]``).  ``amplitude_mm`` (when given) rescales the field so that
    its **measured** ``Ra`` on the ROI equals that value; ``None`` keeps the material's own
    ``sigma_r0`` spectrum as derived.

    ``include_dome`` keeps the conchoidal bowl in the field.  It is **off** by default and the
    reason is measured, not aesthetic: the bowl is *form* (the audited model's own ``_scale_params``
    scales bands / hackle / ribs / pits / fibre and leaves the dome alone), its within-footprint
    sag over a 75 mm frame is a nearly constant tilt that adds no shading contrast, and for the
    ``a12_iface`` lineage the form is already in the geometry.  The audited dome numbers are
    reported in ``meta`` either way, so nothing is hidden.
    """
    from ..fracture import morphology as mo
    from ..fracture.cut import FourierBand
    from ..fracture.morphology import _PitSet, scatter_pits

    material_inputs = mo.material_fracture_inputs(profile, material_id=material_id)
    origin = np.asarray(roi.aim_mm if roi.aim_mm is not None else roi.centroid_mm,
                        dtype=np.float64).reshape(3)
    normal = np.asarray(roi.normal, dtype=np.float64).reshape(3)
    normal = normal / max(float(np.linalg.norm(normal)), 1e-30)
    u_axis, v_axis = tangent_basis(normal)
    tris_uv = _patch_triangles_uv(patch_vertices, patch_triangles, origin, u_axis, v_axis)
    flat = tris_uv.reshape(-1, 2)
    core_area = float(np.sum(triangle_areas_uv(tris_uv)))
    lo = flat.min(axis=0)
    hi = flat.max(axis=0)
    extent = (float(max(hi[0] - lo[0], 1e-6)), float(max(hi[1] - lo[1], 1e-6)))
    uv_centre = (float(lo[0] + 0.5 * extent[0]), float(lo[1] + 0.5 * extent[1]))

    if wall is None:
        idx = np.linspace(0, flat.shape[0] - 1,
                          min(240, flat.shape[0])).astype(int)
        world = (origin[None, :] + flat[idx, 0:1] * u_axis[None, :]
                 + flat[idx, 1:2] * v_axis[None, :])
        measured = (measure_wall_thickness_mm(
            mesh, world, np.repeat(-normal[None, :], world.shape[0], axis=0), rng=rng)
            if mesh is not None else {"status": "NO_MESH"})
        fallback = float(measured.get("median_mm") or 1.0) \
            if measured.get("status") == "OK" else 1.0
        wall = mo.WallThickness(
            min_mm=float(measured.get("min_mm") or fallback),
            p05_mm=float(measured.get("p05_mm") or fallback), median_mm=fallback,
            max_mm=float(measured.get("max_mm") or fallback),
            probes=int(measured.get("n_valid", 0) or 0),
            source="observe.fracture_appearance.measure_wall_thickness_mm")
    else:
        measured = dict(wall.as_dict())

    window_area = float(window_area_mm2 if window_area_mm2 is not None
                        else max(core_area, math.pi * float(roi.footprint_radius_mm or 1.0) ** 2))
    params = mo.derive_morphology_parameters(
        material=material_inputs, wall=wall, origin_uv=uv_centre, tris_uv=tris_uv,
        core_area_mm2=core_area, window_area_mm2=window_area, extent_mm=extent, rng=rng,
        vessel_id="", mother_id="", event_id=f"appearance:{roi.roi_id}",
        error_budget_mm=float(error_budget_mm), max_cells=int(max_cells),
        origin_world_mm=origin)
    params = replace(params, hackle_phase=float(rng.uniform(0.0, 2.0 * np.pi)),
                     pit_depth_mm=float(params.pit_depth_mm))

    bands = [FourierBand(amplitude_mm=a, wavelength_mm=w, direction=np.array([du, dv]),
                         phase=ph) for (a, w, du, dv, ph) in params.bands]
    fiber = _unit2(np.asarray(params.material.get("fiber_direction", [1.0, 0.0, 0.0]),
                              dtype=np.float64)[:2])
    height = mo.MorphologyHeightField(
        basis=None, bands=bands, bend=[], mean_mm=0.0,
        target_rms_mm=float(params.requested_rms_mm), realized_rms_mm=0.0,
        wavelength_min_mm=float(min([b.wavelength_mm for b in bands] or [float("inf")])),
        max_slope=0.0, window=None,
        meta={"morphology": params.as_dict(), "basis": None,
              "note": ("basis/window belong to the cutter; this layer uses raw()/gradient() only, "
                       "so the audited field is evaluated with its own band set and no "
                       "material-intersection envelope")},
        morphology=params, origin_uv=uv_centre,
        dome_radius_mm=(float(params.dome_radius_mm) if include_dome else 0.0),
        dome_amplitude_mm=float(params.dome_amplitude_mm),
        hackle_count=int(params.hackle_count),
        hackle_amplitude_mm=float(params.hackle_amplitude_mm),
        hackle_phase=float(params.hackle_phase),
        mirror_radius_mm=float(params.mirror_radius_mm),
        mist_radius_mm=float(params.mist_radius_mm),
        rib_amplitude_mm=float(params.rib_amplitude_mm),
        rib_spacing_mm=float(params.rib_spacing_at_mirror_mm),
        fiber_amplitude_mm=float(params.fiber_amplitude_mm),
        fiber_wavelength_mm=float(params.fiber_period_mm),
        fiber_direction=(float(fiber[0]), float(fiber[1])),
        amplitude_max_mm=float(max([b.amplitude_mm for b in bands]
                                   + [params.hackle_amplitude_mm, params.rib_amplitude_mm,
                                      params.fiber_amplitude_mm, params.pit_depth_mm, 0.0])))
    centres = scatter_pits(tris_uv, uv_centre, int(params.pit_count),
                           seed_material={"event": params.event_id,
                                          "material": params.material_id,
                                          "mirror": round(params.mirror_radius_mm, 6)},
                           min_radius_from_origin_mm=float(params.mirror_radius_mm))
    height.pits = _PitSet(centres_uv=centres, radius_mm=float(params.pit_radius_mm),
                          depth_mm=float(params.pit_depth_mm))

    radius = float(roi.footprint_radius_mm or 0.0)
    if radius <= 0.0:
        radius = float(max(0.5 * extent[0], 0.5 * extent[1], 1.0))
    if sample_mm is None:
        sample_mm = max(float(params.correlation_length_mm) / 24.0,
                        float(min(b.wavelength_mm for b in bands)) / 12.0, 1.0e-3)
    field_obj = ReliefField(
        height=height, origin_mm=origin, u_axis=u_axis, v_axis=v_axis, normal=normal,
        footprint_radius_mm=radius, ramp_width_mm=float(ramp_width_mm),
        parameters=appearance_parameters_from_profile(profile, material_id=material_id),
        sample_mm=float(sample_mm),
        meta={"wall_thickness": measured, "derive_morphology_parameters": params.as_dict(),
              "core_area_mm2": core_area, "window_area_mm2": window_area,
              "extent_mm": [float(extent[0]), float(extent[1])],
              "uv_centre_mm": [uv_centre[0], uv_centre[1]],
              "pit_centres_count": int(centres.shape[0]),
              "dome_included": bool(include_dome),
              "audited_dome": {
                  "dome_radius_mm": float(params.dome_radius_mm),
                  "dome_amplitude_mm": float(params.dome_amplitude_mm),
                  "sag_over_footprint_mm": float(radius ** 2
                                                 / (2.0 * max(params.dome_radius_mm, 1e-9))),
                  "note": ("the conchoidal bowl is FORM: the audited _scale_params scales bands / "
                           "hackle / ribs / pits / fibre and leaves the dome alone, and over a "
                           "75 mm frame its sag is a nearly constant tilt (no shading contrast)"),
              }})
    if glaze_strip and float(params.glaze_strip_width_mm) > 0.0:
        field_obj.glaze_strip = build_glaze_strip(
            tris_uv=tris_uv, strip_width_mm=float(params.glaze_strip_width_mm),
            ratio=float(params.glaze_roughness_ratio),
            step_mm=max(float(params.glaze_strip_width_mm) / 6.0, 0.05))
    uu, vv = np.meshgrid(np.arange(-radius, radius + 0.5 * sample_mm, sample_mm),
                         np.arange(-radius, radius + 0.5 * sample_mm, sample_mm), indexing="ij")
    raw = np.asarray(height.raw(uu, vv), dtype=np.float64)
    dome = np.asarray(height.dome(uu, vv), dtype=np.float64)  # 0 unless include_dome
    gu, gv = height.gradient(uu, vv)
    gu = np.asarray(gu, dtype=np.float64)
    gv = np.asarray(gv, dtype=np.float64)
    centred = raw - float(np.mean(raw))
    field_obj.ra_at_unit_mm = float(np.mean(np.abs(centred)))
    field_obj.rq_at_unit_mm = float(np.sqrt(np.mean(centred ** 2)))
    field_obj.slope_rms_at_unit = float(np.sqrt(np.mean(gu ** 2 + gv ** 2)))
    field_obj.slope_p95_at_unit = float(np.percentile(np.hypot(gu, gv), 95))
    field_obj.dome_share = float(np.mean(np.abs(dome - float(np.mean(dome))))
                                 / max(field_obj.ra_at_unit_mm, 1e-30))
    if amplitude_mm is not None:
        field_obj.amplitude_scale = float(amplitude_mm) / max(field_obj.ra_at_unit_mm, 1e-30)
    field_obj.meta["ra_measurement"] = {
        "instrument": "observe.fracture_appearance.build_relief_field",
        "grid": f"{uu.shape[0]}x{uu.shape[1]} at {field_obj.sample_mm:.4f} mm",
        "definition": "Ra = mean |h - mean(h)| of the audited field over the ROI footprint",
        "h_min_mm": float(raw.min()), "h_max_mm": float(raw.max())}
    return field_obj


def resample_relief_ra(field_obj: ReliefField, amplitude_mm: float) -> ReliefField:
    """Copy of ``field_obj`` rescaled so its measured ``Ra`` equals ``amplitude_mm``."""
    out = replace(field_obj, meta=dict(field_obj.meta))
    out.amplitude_scale = float(amplitude_mm) / max(float(field_obj.ra_at_unit_mm), 1e-30)
    return out


def field_spectrum_report(field_obj: ReliefField, *, extent_mm: float | None = None,
                          n: int = 512) -> dict[str, Any]:
    """Measure the realised relief spectrum: is it a white-noise field or a band-limited one?

    Reports the radial PSD slope, the autocorrelation length at 1/e and the fraction of the
    variance carried by each audited band.  This is the evidence that the appearance layer uses a
    physical, correlated surface rather than per-pixel noise.
    """
    radius = float(extent_mm if extent_mm is not None else field_obj.footprint_radius_mm)
    step = 2.0 * radius / float(n)
    uu, vv = np.meshgrid(np.arange(n) * step - radius, np.arange(n) * step - radius,
                         indexing="ij")
    h = np.asarray(field_obj.height.raw(uu, vv), dtype=np.float64)
    h = h - float(h.mean())
    win = np.hanning(n)[:, None] * np.hanning(n)[None, :]
    spec = np.abs(np.fft.fftshift(np.fft.fft2(h * win))) ** 2
    fy = np.fft.fftshift(np.fft.fftfreq(n, d=step))
    fx = fy.copy()
    kx, ky = np.meshgrid(fx, fy, indexing="ij")
    kr = np.hypot(kx, ky)
    valid = kr > 0
    bins = np.logspace(math.log10(max(kr[valid].min(), 1e-3)),
                       math.log10(kr[valid].max()), 24)
    idx = np.digitize(kr[valid], bins)
    power = np.array([spec[valid][idx == i].mean() if np.any(idx == i) else np.nan
                      for i in range(1, bins.size)])
    k_mid = np.array([kr[valid][idx == i].mean() if np.any(idx == i) else np.nan
                      for i in range(1, bins.size)])
    good = np.isfinite(power) & (power > 0)
    slope = float(np.polyfit(np.log(k_mid[good]), np.log(power[good]), 1)[0]) if good.sum() > 3 \
        else float("nan")
    ac = np.fft.ifft2(np.abs(np.fft.fft2(h)) ** 2).real
    ac = np.fft.fftshift(ac) / max(float(ac.max()), 1e-30)
    centre = n // 2
    row = ac[centre, centre:]
    below = np.nonzero(row < math.exp(-1.0))[0]
    corr_len = float(below[0] * step) if below.size else float("nan")
    return {
        "status": "OK", "grid": f"{n}x{n} at {step:.4f} mm", "extent_mm": float(2.0 * radius),
        "psd_slope_loglog": slope,
        "correlation_length_1e_mm": corr_len,
        "rms_mm_at_unit_scale": float(np.sqrt(np.mean(h ** 2))),
        "expected_correlation_length_mm": float(field_obj.parameters.correlation_length_mm),
        "band_wavelengths_mm": [float(x) for x in field_obj.parameters.band_wavelengths_mm],
        "note": ("white noise would give a flat PSD (slope ~0) and a correlation length of one "
                 "sample; the audited field is red (slope < 0) with the material's own correlation "
                 "length"),
    }


# ======================================================================================
# appearance spec
# ======================================================================================
@dataclass(frozen=True)
class AppearanceSpec:
    """One appearance configuration of one view (everything is recorded in the render meta)."""

    normal_mode: str = "FLAT"
    crease_angle_deg: float = 35.0
    interpolation: str = "FROZEN"
    relief: bool = False
    amplitude_scale: float = 1.0
    albedo: tuple[float, float, float] | None = None
    diffuse_weight: float = 1.0
    label: str = ""
    #: A3: continuous band-limited surface albedo evaluated **per pixel** instead of the frozen
    #: per-face palette.  ``None`` (the default) keeps the frozen ``scene.material.albedo``, so the
    #: bit-exact reduction to the software rasteriser is untouched.
    albedo_texture: "AlbedoTexture | None" = None

    def __post_init__(self) -> None:
        if self.normal_mode not in NORMAL_MODES:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"normal_mode {self.normal_mode!r} not in {NORMAL_MODES}",
                              stage="observe.fracture_appearance.AppearanceSpec")
        if self.interpolation not in INTERPOLATIONS:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"interpolation {self.interpolation!r} not in {INTERPOLATIONS}",
                              stage="observe.fracture_appearance.AppearanceSpec")

    def as_dict(self) -> dict[str, Any]:
        return {"normal_mode": self.normal_mode,
                "crease_angle_deg": float(self.crease_angle_deg),
                "interpolation": self.interpolation, "relief": bool(self.relief),
                "amplitude_scale": float(self.amplitude_scale),
                "albedo": None if self.albedo is None else [float(x) for x in self.albedo],
                "diffuse_weight": float(self.diffuse_weight), "label": str(self.label),
                "albedo_texture": (None if self.albedo_texture is None
                                   else self.albedo_texture.as_dict())}


# ======================================================================================
# renderer: frozen models, per-pixel normals
# ======================================================================================
def render_appearance_view(scene: Scene, frame: ViewFrame, *, light: LightSpec,
                           spec: RenderSpec | None = None,
                           appearance: AppearanceSpec | None = None,
                           relief_field: ReliefField | None = None,
                           object_pose: np.ndarray | None = None,
                           focus_distance_mm: float | None = None,
                           albedo: np.ndarray | None = None) -> RenderOutput:
    """Render one view with a **per-pixel** shading normal (the relief delivery channel).

    The scene, the frame, the light and the geometry channels (``depth_z``, ``id_map``,
    ``surface_tag``, ``visibility``, ``uncertain_mask``) are the frozen ones; what changes is that
    the shading normal is evaluated per pixel as

    ``n = normalize(n_base - dh/du * t_u - dh/dv * t_v)``

    where ``n_base`` is the face normal (``FLAT``), the interpolated vertex normal (``SMOOTH``) or
    the interpolated face-varying corner normal (``SMOOTH_CREASE``), and ``h`` is the audited
    morphology height field of the ROI plane.  With ``normal_mode="FLAT"``, ``relief=False`` and
    ``interpolation="FROZEN"`` this renderer reproduces
    :func:`synlab.observe.render.render_view` (software backend) **bit-exactly** on the RGB buffer.
    """
    spec = spec or RenderSpec()
    appearance = appearance or AppearanceSpec()
    width, height = int(frame.image_size[0]), int(frame.image_size[1])
    factor = max(int(spec.supersample), 1)
    if width * height * factor * factor > spec.max_pixels:
        raise SynLabError(ErrorCode.BUDGET_EXCEEDED,
                          f"appearance render {width}x{height} at supersample {factor} exceeds "
                          f"the pixel budget {spec.max_pixels}",
                          stage="observe.fracture_appearance.render_appearance_view")
    posed = scene.transformed(object_pose) if object_pose is not None else scene
    hi_w, hi_h = width * factor, height * factor
    buffers = _rasterise_appearance(posed, _scaled_frame(frame, factor), hi_w, hi_h, light,
                                    appearance, relief_field, spec, albedo=albedo)

    hit_hi = np.isfinite(buffers["depth"])
    rgb_hi = buffers["rgb"].copy()
    rgb_hi[~hit_hi] = np.asarray(spec.background_linear, dtype=np.float32)
    rgb = _block_reduce(rgb_hi, factor, mode="mean").astype(np.float32)
    depth_hi = np.where(hit_hi, buffers["depth"], np.nan)[:, :, None]
    all_hit = hit_hi.reshape(height, factor, width, factor).all(axis=(1, 3))
    depth = _block_reduce(depth_hi, factor, mode="min")[:, :, 0].astype(np.float32)
    depth[~all_hit] = np.nan
    id_map = buffers["id"][::factor, ::factor].copy()
    tag_map = buffers["tag"][::factor, ::factor].copy()
    mixed_id = _disagreement_i(buffers["id"], factor)
    mixed_tag = _disagreement_i(buffers["tag"].astype(np.int32), factor)
    visibility = (~mixed_id).astype(np.uint8) * (id_map >= 0).astype(np.uint8)

    focus = float(frame.working_distance_mm if focus_distance_mm is None else focus_distance_mm)
    f_px = 0.5 * (float(frame.K[0, 0]) + float(frame.K[1, 1]))
    optics = resolve_declared_optics(frame, spec)
    with np.errstate(invalid="ignore"):
        coc = circle_of_confusion_px(depth.astype(np.float64), focus, optics["f_number"], f_px,
                                     sampling_px_per_mm=optics["sampling_px_per_mm"])
    uncertain = (mixed_id | mixed_tag | (coc > spec.coc_px_threshold)) & (id_map >= 0)
    uncertain |= (~np.isfinite(depth)) & (id_map >= 0)
    meta = {
        "backend": BACKEND_APPEARANCE, "backend_class": "ADAPTER", "supersample": factor,
        "near_mm": spec.near_mm, "far_mm": spec.far_mm, "shade": spec.shade,
        "light_direction": np.asarray(light.direction, dtype=np.float64).tolist(),
        "light_color": np.asarray(light.color, dtype=np.float64).tolist(),
        "ambient": np.asarray(light.ambient, dtype=np.float64).tolist(),
        "background_linear": list(spec.background_linear), "bg_linear_present": True,
        "depth_semantics": "camera_frame_z_mm",
        "id_map_semantics": "integer face label, -1 = background, never interpolated",
        "mm_per_pixel": float(frame.working_distance_mm / frame.K[0, 0]),
        "object_pose_T_WO": (np.asarray(object_pose).tolist()
                             if object_pose is not None else None),
        "focus_distance_mm": focus, "coc_threshold_px": spec.coc_px_threshold,
        "mask_semantics": (MASK_SEMANTICS if optics["declared"]
                           else MASK_SEMANTICS_PIXEL_UNITS_V1),
        "coc_optics": {"rule": "c_px = D * f_mm^2 / (N * (z - f_mm)) * |z - z_f| / z_f",
                       "f_px": float(f_px), "focal_length_mm": float(optics["focal_length_mm"]),
                       "f_number": float(optics["f_number"]),
                       "sampling_px_per_mm": (None if optics["sampling_px_per_mm"] is None
                                              else float(optics["sampling_px_per_mm"])),
                       "declared": bool(optics["declared"]), "profile_id": optics["profile_id"],
                       "source": dict(optics["source"])},
        "coc_p95_px": float(np.nanpercentile(coc, 95)) if np.isfinite(coc).any() else 0.0,
        "surface_visible_fraction": float(np.mean(id_map >= 0)),
        "uncertain_fraction": float(np.mean(uncertain)),
        "albedo_source_kind": SOURCE_SENSOR_SIM,
        "n_faces_drawn": int(np.count_nonzero(np.isfinite(buffers["depth"]))),
        "appearance": {
            "schema": APPEARANCE_SCHEMA, "spec": appearance.as_dict(),
            "lambert": _lambert_report(
                None if buffers.get("lambert") is None
                else np.asarray(buffers["lambert"])[::factor, ::factor], tag_map),
            "normal_channel": "PER_PIXEL_SHADING_NORMAL", "geometry_modified": False,
            "relief_field": None if relief_field is None else relief_field.as_dict(),
            "geometry_hash": geometry_hash(posed.vertices, posed.faces),
            "relief_active": bool(appearance.relief and relief_field is not None),
            "albedo_channel": ("PER_PIXEL_CONTINUOUS_TEXTURE" if appearance.albedo_texture is not None
                               else "PER_FACE_PALETTE_FROZEN"),
            "albedo_texture": (None if appearance.albedo_texture is None
                               else appearance.albedo_texture.as_dict()),
            "realized_ra_mm": (float(relief_field.realized_ra_mm
                                     * float(appearance.amplitude_scale))
                               if relief_field is not None else None),
        },
    }
    return RenderOutput(rgb_linear=rgb, depth_z=depth, id_map=id_map.astype(np.int32),
                        surface_tag=tag_map.astype(np.int16),
                        visibility=visibility.astype(np.uint8),
                        uncertain_mask=uncertain.astype(bool), backend=BACKEND_APPEARANCE,
                        meta=meta)


def _lambert_report(lambert: Any, tag_map: np.ndarray) -> dict[str, Any]:
    """Statistics of the frozen Lambert term on the fracture (rim) pixels of one render.

    ``unlit_fraction`` is the share of fracture pixels whose Lambert term is clipped at 0: there the
    shading is ``albedo * ambient`` and **no** normal perturbation can change the image at all.
    ``fully_lit_fraction`` is the same for the clip at 1.  This is the measurement that decides
    whether a view can show relief under the frozen single-light model, and ``mean_raw_dot`` is the
    signed quantity ``-(n_world . light.direction)`` *before* the clip: it is negative when the
    fracture faces away from the light and the whole view is ambient-only.
    """
    if lambert is None:
        return {"status": "NOT_RECORDED"}
    lam = np.asarray(lambert, dtype=np.float64)
    rim = np.asarray(tag_map) == 2
    valid = rim & np.isfinite(lam)
    if not valid.any():
        return {"status": "NO_RIM_PIXELS", "n_px": 0}
    v = lam[valid]
    return {
        "status": "OK", "n_px": int(v.size), "mean_raw_dot": float(v.mean()),
        "unlit_fraction": float(np.mean(v <= 0.0)),
        "fully_lit_fraction": float(np.mean(v >= 1.0)),
        "lit_fraction": float(np.mean((v > 0.02) & (v < 0.98))),
        "p05_raw_dot": float(np.percentile(v, 5)), "p95_raw_dot": float(np.percentile(v, 95)),
        "definition": ("raw = -(n_world . light.direction); the frozen shading clips it to [0, 1]. "
                       "unlit_fraction = share of fracture pixels with no normal response at all"),
    }


def _scaled_frame(frame: ViewFrame, factor: int) -> ViewFrame:
    scaled = copy.copy(frame)
    K = np.asarray(frame.K, dtype=np.float64).copy()
    K[0, 0] *= factor
    K[1, 1] *= factor
    K[0, 2] = (K[0, 2] + 0.5) * factor - 0.5
    K[1, 2] = (K[1, 2] + 0.5) * factor - 0.5
    scaled.K = K
    scaled.image_size = (int(frame.image_size[0]) * factor, int(frame.image_size[1]) * factor)
    return scaled


def _rasterise_appearance(scene: Scene, frame: ViewFrame, width: int, height: int,
                          light: LightSpec, appearance: AppearanceSpec,
                          relief_field: ReliefField | None, spec: RenderSpec,
                          *, albedo: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Z-buffered rasterisation with a per-pixel shading normal."""
    from ..cameras.projection import distort_normalized

    T_CW = frame.T_CW
    R = T_CW[:3, :3]
    t = T_CW[:3, 3]
    world = np.asarray(scene.vertices, dtype=np.float64)
    verts = world @ R.T + t[None, :]
    z = verts[:, 2]
    safe = np.where(np.abs(z) > 1e-12, z, np.nan)
    x, y = verts[:, 0] / safe, verts[:, 1] / safe
    xd, yd = distort_normalized(x, y, frame.dist, frame.camera_model or "PINHOLE")
    K = frame.K
    uv = np.stack([K[0, 0] * xd + K[0, 1] * yd + K[0, 2],
                   K[1, 0] * xd + K[1, 1] * yd + K[1, 2]], axis=1)

    depth = np.full((height, width), np.inf, dtype=np.float64)
    id_buf = np.full((height, width), -1, dtype=np.int32)
    tag_buf = np.full((height, width), -1, dtype=np.int16)
    rgba = np.zeros((height, width, 3), dtype=np.float32)
    #: The frozen Lambert term of the pixel that won the z-buffer.  It is recorded because the
    #: normal channel can only deliver contrast where this term is strictly between 0 and 1: the
    #: frozen model clips it, so an unlit (or fully lit) surface has *no* normal response at all.
    lambert_buf = np.full((height, width), np.nan, dtype=np.float64)
    l_unit = np.asarray(light.direction, dtype=np.float64)
    faces = scene.faces
    if faces.shape[0] == 0:
        return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba,
                "lambert": lambert_buf}
    p0, p1, p2 = uv[faces[:, 0]], uv[faces[:, 1]], uv[faces[:, 2]]
    z0, z1, z2 = z[faces[:, 0]], z[faces[:, 1]], z[faces[:, 2]]
    area = (p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) \
        - (p2[:, 0] - p0[:, 0]) * (p1[:, 1] - p0[:, 1])
    cam0, cam1, cam2 = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    face_n = np.cross(cam1 - cam0, cam2 - cam0)
    visible = ((z0 > spec.near_mm) & (z1 > spec.near_mm) & (z2 > spec.near_mm)
               & (z0 < spec.far_mm) & (z1 < spec.far_mm) & (z2 < spec.far_mm)
               & (face_n[:, 2] < 0.0) & np.isfinite(area) & (np.abs(area) > 1e-12))
    order = np.nonzero(visible)[0]
    if order.size == 0:
        return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba,
                "lambert": lambert_buf}

    # `face_n` is a CAMERA-space normal (the vertices above are camera-space; the frozen
    # rasteriser calls the cross product "world_normals" only by history).  The frozen shading
    # composes to ``-(n_world . l)`` with a world-frame light, and the relief tangents live in the
    # world frame, so the perturbation is applied to the **world** normal and converted back.
    R_WC = np.asarray(T_CW, dtype=np.float64)[:3, :3]
    cam_normals = face_n / np.maximum(np.linalg.norm(face_n, axis=1, keepdims=True), 1e-30)
    world_normals = cam_normals @ R_WC
    vertex_n = corner_n = None
    if appearance.normal_mode != "FLAT":
        vertex_n = vertex_normals(world, faces, weighting="AREA")
        corner_n = (corner_normals(world, faces, crease_angle_deg=180.0)
                    if appearance.normal_mode == "SMOOTH"
                    else corner_normals(world, faces,
                                        crease_angle_deg=float(appearance.crease_angle_deg)))
    base_albedo = (np.asarray(albedo, dtype=np.float64).reshape(-1, 3) if albedo is not None
                   else np.asarray(scene.material.albedo, dtype=np.float64).reshape(-1, 3))
    if base_albedo.shape[0] != faces.shape[0]:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "albedo must have one row per face",
                          stage="observe.fracture_appearance._rasterise_appearance")
    albedo_px = base_albedo * float(appearance.diffuse_weight)
    #: A3: when a delivered albedo texture is attached, the albedo is evaluated at the SAME
    #: sub-pixel point the shading normal is evaluated at, so it is continuous across triangle
    #: boundaries by construction (its value depends only on position).  Sub-pixel raster
    #: coordinates are converted to delivered pixels (divide by the supersample factor) and then to
    #: millimetres through the frame's own scale, which is what makes the pattern independent of
    #: the supersampling.
    texture = appearance.albedo_texture
    #: ``_rasterise_appearance`` receives the ALREADY SCALED frame, so the supersample factor is
    #: recovered from the render grid / delivered grid ratio rather than from a parameter.
    tex_factor = max(int(round(float(width) / max(float(frame.image_size[0]), 1.0))), 1)
    tex_inv_mm_per_px = (1.0 / float(texture.mm_per_px)) if texture is not None else 1.0
    perspective = appearance.interpolation == "PERSPECTIVE_CORRECT"
    relief_on = bool(appearance.relief and relief_field is not None)
    if relief_on:
        t_u, t_v = relief_field.u_axis, relief_field.v_axis
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
        px, py = gx[None, :], gy[:, None]
        ax, ay, bx, by, cx, cy = (p0[f, 0], p0[f, 1], p1[f, 0], p1[f, 1], p2[f, 0], p2[f, 1])
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

        if appearance.normal_mode == "FLAT" and not relief_on and texture is None:
            shaded = shade_world_normals(normals_world=world_normals[f][None, :],
                                         albedo=albedo_px[f][None, :], light=light)[0]
            rgba[ymin:ymax + 1, xmin:xmax + 1][better] = shaded.astype(np.float32)
            lambert_buf[ymin:ymax + 1, xmin:xmax + 1][better] = float(
                -(world_normals[f] @ l_unit))
            continue

        rows, cols = np.nonzero(better)
        ww0, ww1, ww2 = w0[rows, cols], w1[rows, cols], w2[rows, cols]
        if perspective:
            iw0, iw1, iw2 = ww0 / z0[f], ww1 / z1[f], ww2 / z2[f]
            denom = iw0 + iw1 + iw2
            b0, b1, b2 = iw0 / denom, iw1 / denom, iw2 / denom
        else:
            b0, b1, b2 = ww0, ww1, ww2
        fv = faces[f]
        pts = (b0[:, None] * world[fv[0]] + b1[:, None] * world[fv[1]]
               + b2[:, None] * world[fv[2]])
        if appearance.normal_mode == "FLAT":
            n_px = np.repeat(world_normals[f][None, :], pts.shape[0], axis=0)
        elif appearance.normal_mode == "SMOOTH":
            n_px = (b0[:, None] * vertex_n[fv[0]] + b1[:, None] * vertex_n[fv[1]]
                    + b2[:, None] * vertex_n[fv[2]])
        else:
            n_px = (b0[:, None] * corner_n[f, 0] + b1[:, None] * corner_n[f, 1]
                    + b2[:, None] * corner_n[f, 2])
        n_px = n_px / np.maximum(np.linalg.norm(n_px, axis=1, keepdims=True), 1e-30)
        if relief_on:
            _, gu, gv = relief_field.sample(pts, scale=relief_field.amplitude_scale
                                            * float(appearance.amplitude_scale))
            tu = t_u[None, :] - (n_px @ t_u)[:, None] * n_px
            tv = t_v[None, :] - (n_px @ t_v)[:, None] * n_px
            tu = tu / np.maximum(np.linalg.norm(tu, axis=1, keepdims=True), 1e-30)
            tv = tv / np.maximum(np.linalg.norm(tv, axis=1, keepdims=True), 1e-30)
            n_px = n_px - gu[:, None] * tu - gv[:, None] * tv
            n_px = n_px / np.maximum(np.linalg.norm(n_px, axis=1, keepdims=True), 1e-30)
        shaded = shade_world_normals(
            normals_world=n_px,
            albedo=(np.repeat(albedo_px[f][None, :], pts.shape[0], axis=0)
                    if texture is None else
                    np.asarray(texture.albedo(np.stack([(xmin + cols + 0.5) * tex_inv_mm_per_px
                                                        / tex_factor,
                                                        (ymin + rows + 0.5) * tex_inv_mm_per_px
                                                        / tex_factor], axis=1)),
                               dtype=np.float64)
                    * float(appearance.diffuse_weight)),
            light=light)
        rgba[ymin:ymax + 1, xmin:xmax + 1][rows, cols] = shaded.astype(np.float32)
        lambert_buf[ymin:ymax + 1, xmin:xmax + 1][rows, cols] = -(n_px @ l_unit)
    return {"depth": depth, "id": id_buf, "tag": tag_buf, "rgb": rgba, "lambert": lambert_buf}


# ======================================================================================
# measurement
# ======================================================================================
def dn_statistics(dn: np.ndarray, mask: np.ndarray, *, levels: float = 255.0) -> dict[str, Any]:
    """Code-value statistics of one band of a delivered image inside ``mask``."""
    a = np.asarray(dn, dtype=np.float64)
    if a.ndim == 3:
        a = a.mean(axis=2)
    m = np.asarray(mask, dtype=bool)
    if m.shape != a.shape:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "mask shape does not match the image",
                          stage="observe.fracture_appearance.dn_statistics")
    v = a[m]
    if v.size == 0:
        return {"n_px": 0, "status": "EMPTY_MASK"}
    p05, p50, p95 = (float(np.percentile(v, q)) for q in (5.0, 50.0, 95.0))
    return {"n_px": int(v.size), "status": "OK", "mean_dn": float(v.mean()),
            "std_dn": float(v.std()), "p05_dn": p05, "median_dn": p50, "p95_dn": p95,
            "dn_p95_minus_p05": float(p95 - p05),
            "dn_max_minus_min": float(v.max() - v.min()),
            "code_value_floor": 1.0, "levels": float(levels)}


def difference_dn_statistics(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    """Per-pixel code-value change between two renders of the *same* view and geometry."""
    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    if x.ndim == 3:
        x = x.mean(axis=2)
    if y.ndim == 3:
        y = y.mean(axis=2)
    d = x - y
    m = np.asarray(mask, dtype=bool)
    v = d[m]
    if v.size == 0:
        return {"n_px": 0, "status": "EMPTY_MASK"}
    ad = np.abs(v)
    return {"n_px": int(v.size), "status": "OK",
            "dDN_rms": float(np.sqrt(np.mean(v ** 2))), "dDN_mean_abs": float(ad.mean()),
            "dDN_p95_abs": float(np.percentile(ad, 95)),
            "dDN_max_abs": float(ad.max()),
            "fraction_above_1_dn": float(np.mean(ad >= 1.0)),
            "fraction_above_2_dn": float(np.mean(ad >= 2.0)),
            "definition": "|DN(relief_on) - DN(relief_off)| per pixel, same view and seed"}


def directional_index(dn: np.ndarray, mask: np.ndarray, *, smooth_px: float = 1.0
                      ) -> dict[str, Any]:
    """Structure-tensor anisotropy of the delivered shading (0 isotropic, 1 one direction)."""
    import cv2

    a = np.asarray(dn, dtype=np.float64)
    if a.ndim == 3:
        a = a.mean(axis=2)
    m = np.asarray(mask, dtype=bool)
    if int(m.sum()) < 64:
        return {"status": "TOO_FEW_PIXELS", "n_px": int(m.sum())}
    gy, gx = np.gradient(a)
    sel = m & np.isfinite(gx) & np.isfinite(gy)
    if int(sel.sum()) < 64:
        return {"status": "TOO_FEW_PIXELS", "n_px": int(sel.sum())}
    jxx = cv2.GaussianBlur((gx * gx).astype(np.float32), (0, 0), float(smooth_px))
    jyy = cv2.GaussianBlur((gy * gy).astype(np.float32), (0, 0), float(smooth_px))
    jxy = cv2.GaussianBlur((gx * gy).astype(np.float32), (0, 0), float(smooth_px))
    jxx_m, jyy_m, jxy_m = float(jxx[sel].mean()), float(jyy[sel].mean()), float(jxy[sel].mean())
    trace = jxx_m + jyy_m
    det = jxx_m * jyy_m - jxy_m ** 2
    disc = math.sqrt(max(trace * trace / 4.0 - det, 0.0))
    l1, l2 = trace / 2.0 + disc, trace / 2.0 - disc
    theta = 0.5 * math.atan2(2.0 * jxy_m, jxx_m - jyy_m)
    return {"status": "OK", "n_px": int(sel.sum()),
            "anisotropy": float((l1 - l2) / max(l1 + l2, 1e-30)),
            "dominant_orientation_deg": float(math.degrees(theta)),
            "dominant_orientation_mod180_deg": float(math.degrees(theta) % 180.0),
            "gradient_rms_dn_per_px": float(math.sqrt(max(trace, 0.0))),
            "method": "structure tensor of the shading gradient, averaged over the mask"}


def facet_metrics(dn: np.ndarray, id_map: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    """How visible the triangulation is, measured on the delivered image.

    ``facet_edge_dn_step`` is the mean ``|DN(p) - DN(q)|`` over 4-neighbour pixel pairs that lie
    inside the mask and **straddle a face-id boundary**; ``interior_dn_step`` is the same statistic
    for pairs with identical face ids.  A rasteriser with one flat normal per triangle makes the
    first number large; a per-pixel normal collapses it to the interior value.
    """
    a = np.asarray(dn, dtype=np.float64)
    if a.ndim == 3:
        a = a.mean(axis=2)
    ids = np.asarray(id_map, dtype=np.int64)
    m = np.asarray(mask, dtype=bool)
    if a.shape != ids.shape or m.shape != a.shape:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "shape mismatch in facet_metrics",
                          stage="observe.fracture_appearance.facet_metrics")
    cross_all, interior_all = [], []
    for axis in (0, 1):
        d = np.abs(np.diff(a, axis=axis))
        same = np.diff(ids, axis=axis) == 0
        n = m.shape[axis]
        lo = np.arange(0, n - 1)
        hi = np.arange(1, n)
        valid = np.take(m, lo, axis=axis) & np.take(m, hi, axis=axis)
        cross_all.append(d[valid & ~same].ravel())
        interior_all.append(d[valid & same].ravel())
    cross = np.concatenate(cross_all)
    interior = np.concatenate(interior_all)
    counts = np.bincount(ids[m].ravel()) if int(m.sum()) else np.zeros(0, dtype=np.int64)
    counts = counts[counts > 0]
    return {
        "status": "OK" if cross.size and interior.size else "TOO_FEW_PAIRS",
        "n_cross_pairs": int(cross.size), "n_interior_pairs": int(interior.size),
        "facet_edge_dn_step": float(cross.mean()) if cross.size else float("nan"),
        "facet_edge_dn_p95": float(np.percentile(cross, 95)) if cross.size else float("nan"),
        "interior_dn_step": float(interior.mean()) if interior.size else float("nan"),
        "facet_contrast_ratio": (float(cross.mean() / max(interior.mean(), 1e-9))
                                 if cross.size and interior.size else float("nan")),
        "median_face_area_px": float(np.median(counts)) if counts.size else float("nan"),
        "n_faces_in_mask": int(counts.size),
        "definition": ("mean |DN| across 4-neighbour pairs straddling a face-id boundary vs pairs "
                       "with the same face id, inside the mask")}


def grain_pixel_statistics(dn: np.ndarray, mask: np.ndarray, *, min_contrast_dn: float = 6.0
                           ) -> dict[str, Any]:
    """Footprint of the pull-out / pit features in pixels, measured by blob detection."""
    import cv2

    a = np.asarray(dn, dtype=np.float64)
    if a.ndim == 3:
        a = a.mean(axis=2)
    m = np.asarray(mask, dtype=bool)
    if int(m.sum()) < 256:
        return {"status": "TOO_FEW_PIXELS", "n_px": int(m.sum())}
    v = a[m]
    lo, hi = float(np.percentile(v, 5)), float(np.percentile(v, 95))
    if hi - lo < float(min_contrast_dn):
        return {"status": "NO_CONTRAST", "dn_p95_minus_p05": hi - lo,
                "min_contrast_dn": float(min_contrast_dn), "n_px": int(m.sum())}
    norm = np.clip((a - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    img = (norm * 255.0).astype(np.uint8)
    thr = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, -8)
    thr[~m] = 0
    n_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(thr, connectivity=8)
    areas = [int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, n_labels)]
    areas = [x for x in areas if 1 <= x <= 4096]
    if not areas:
        return {"status": "NO_BLOBS", "n_px": int(m.sum()), "dn_p95_minus_p05": hi - lo}
    return {"status": "OK", "n_blobs": len(areas),
            "median_blob_px": float(np.median(areas)),
            "p95_blob_px": float(np.percentile(areas, 95)),
            "median_blob_equivalent_diameter_px": float(2.0 * math.sqrt(np.median(areas)
                                                                        / math.pi)),
            "blobs_per_megapixel": float(len(areas) / max(int(m.sum()), 1) * 1e6),
            "dn_p05": lo, "dn_p95": hi, "dn_p95_minus_p05": hi - lo,
            "method": "adaptive threshold on the DN map inside the fracture mask + "
                      "connected components"}


# ======================================================================================
# mesh density inverse solve (path 2 of facet suppression)
# ======================================================================================
def measured_edge_length_mm(vertices: np.ndarray, faces: np.ndarray,
                            *, face_mask: np.ndarray | None = None) -> dict[str, Any]:
    """Measured triangle edge-length distribution of the real mesh (mm)."""
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if face_mask is not None:
        f = f[np.asarray(face_mask, dtype=bool)]
    if f.shape[0] == 0:
        return {"status": "NO_FACES", "n_faces": 0}
    e = np.concatenate([np.linalg.norm(v[f[:, 1]] - v[f[:, 0]], axis=1),
                        np.linalg.norm(v[f[:, 2]] - v[f[:, 1]], axis=1),
                        np.linalg.norm(v[f[:, 0]] - v[f[:, 2]], axis=1)])
    area = 0.5 * np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]),
                                axis=1)
    return {"status": "OK", "n_faces": int(f.shape[0]), "n_edges": int(e.size),
            "edge_median_mm": float(np.median(e)), "edge_p05_mm": float(np.percentile(e, 5)),
            "edge_p95_mm": float(np.percentile(e, 95)), "edge_min_mm": float(e.min()),
            "edge_max_mm": float(e.max()), "area_mm2": float(area.sum()),
            "equivalent_edge_from_area_mm": float(math.sqrt(4.0 * area.sum()
                                                            / (math.sqrt(3.0) * f.shape[0])))}


def required_mesh_density(*, lambda_min_mm: float, area_mm2: float, current_edge_mm: float,
                          ratio: float = FACET_RESOLUTION_RATIO) -> dict[str, Any]:
    """How dense a mesh must be for its facets to stop being the visible pattern.

    The criterion is a **shading** criterion, not a Nyquist one: a triangle of lateral size ``L``
    carrying one flat normal misrepresents the surface by the normal change across ``L``.  For a
    band-limited surface whose shortest wavelength is ``lambda_min`` the normal can swing by the
    full slope within one wavelength, so keeping a facet's own orientation error inside ``1/ratio``
    of that needs ``L <= lambda_min / ratio``; the equilateral-triangle count for an area ``A`` is
    ``4A / (sqrt(3) L^2)``.
    """
    lam = float(lambda_min_mm)
    if lam <= 0.0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "lambda_min_mm must be > 0",
                          stage="observe.fracture_appearance.required_mesh_density")
    edge = lam / float(ratio)
    n_tri = 4.0 * float(area_mm2) / (math.sqrt(3.0) * edge ** 2) if area_mm2 > 0 else 0.0
    n_tri_now = (4.0 * float(area_mm2) / (math.sqrt(3.0) * float(current_edge_mm) ** 2)
                 if current_edge_mm > 0 else float("nan"))
    return {
        "lambda_min_mm": lam, "ratio": float(ratio), "required_edge_mm": float(edge),
        "required_triangles": float(n_tri), "current_edge_mm": float(current_edge_mm),
        "current_triangles_equivalent": float(n_tri_now),
        "density_factor": (float(n_tri / n_tri_now) if n_tri_now and math.isfinite(n_tri_now)
                           else float("nan")),
        "required_cells_equivalent": float(n_tri / 2.0),
        "required_edge_px_at_2048": None,
        "criterion": (f"facet orientation error < 1/{ratio:g} of the surface normal change over "
                      f"lambda_min; L = lambda_min / ratio"),
        "formulas": {"edge": "L = lambda_min / ratio",
                     "count": "N = 4 A / (sqrt(3) L^2) (equilateral triangles)",
                     "cells": "N_cells = N / 2 (two triangles per quadtree cell)"},
    }


def facet_pixel_budget(*, edge_mm: float, mm_per_px: float) -> dict[str, Any]:
    """The same mesh expressed in the units the images are judged in."""
    if mm_per_px <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "mm_per_px must be > 0",
                          stage="observe.fracture_appearance.facet_pixel_budget")
    return {"edge_mm": float(edge_mm), "mm_per_px": float(mm_per_px),
            "edge_px": float(edge_mm) / float(mm_per_px),
            "visible_if_edge_px_above": 3.0,
            "visible": bool(float(edge_mm) / float(mm_per_px) > 3.0)}


# ======================================================================================
# glaze step
# ======================================================================================
def glaze_step_report(*, thickness_mm: Sequence[float], mm_per_px: Sequence[float],
                      albedo_body: float, albedo_glaze: float, light: LightSpec | None = None,
                      relief_amplitude_mm: float = 0.0, relief_wavelength_mm: float = 0.0,
                      glaze_roughness_ratio: float = 0.12) -> dict[str, Any]:
    """What a real glaze layer step (mm) does to the delivered RGB.

    Two independent signatures, both computed from the measured layer thicknesses:

    1. **lateral band** - the step occupies a band of width ``t`` along the fracture boundary; at
       ``mm/px`` that is ``t / mm/px`` pixels, so below ~2 px it cannot be resolved laterally and
       only its albedo/normal signature survives;
    2. **shading step** - the frozen Lambert term is evaluated on the layer's own surface and on
       the body, and the layer's own audited relief damping (``glaze_roughness_ratio`` of the body
       relief inside the strip) removes most of the texture contrast there.
    """
    light = light or frozen_light()
    perpendicular = float(math.sqrt(max(0.0, 1.0 - float(light.direction[2]) ** 2)))
    color_mean = float(np.mean(light.color))
    rows = []
    for t in thickness_mm:
        for s in mm_per_px:
            step_wall = 0.5 * (1.0 + perpendicular)   # a step wall lit at ~normal incidence
            dn_body = 255.0 * float(albedo_body) * color_mean * perpendicular
            dn_glaze_face = 255.0 * float(albedo_glaze) * color_mean * perpendicular
            dn_glaze_wall = 255.0 * float(albedo_glaze) * color_mean * step_wall
            rows.append({
                "thickness_mm": float(t), "mm_per_px": float(s),
                "band_width_px": float(t) / float(s),
                "laterally_resolvable_2px": bool(float(t) / float(s) >= 2.0),
                "albedo_step_face_dn": float(dn_glaze_face - dn_body),
                "step_wall_dn": float(dn_glaze_wall - dn_body),
                "relief_inside_band_mm": float(relief_amplitude_mm) * float(glaze_roughness_ratio),
                "relief_outside_band_mm": float(relief_amplitude_mm),
                "relief_damping_ratio": float(glaze_roughness_ratio),
                "relief_wavelength_mm": float(relief_wavelength_mm),
            })
    return {"rows": rows, "glaze_roughness_ratio": float(glaze_roughness_ratio),
            "convention": ("band width = layer thickness / mm_per_px; the DN numbers use the frozen "
                           "Lambert + ambient expression with the measured layer albedos; relief "
                           "damping ratio is morphology.GLAZE_ROUGHNESS_RATIO (audited)")}


# ======================================================================================
# images
# ======================================================================================
_COLOURS = ((235, 235, 235), (120, 200, 255), (120, 255, 160), (255, 190, 120), (255, 140, 200))


def write_rgb_png(image: np.ndarray, path: str | Path) -> str:
    """Write an 8-bit RGB array (H, W, 3) as a PNG; returns the path."""
    import cv2

    arr = np.asarray(image)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)):
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, f"PNG write failed: {path}",
                          stage="observe.fracture_appearance.write_rgb_png")
    return str(path)


def _label(image: np.ndarray, lines: Sequence[str], *, scale: float = 0.5) -> np.ndarray:
    import cv2

    out = np.asarray(image).copy()
    for i, text in enumerate(lines):
        y = 16 + i * int(round(18 * max(scale, 0.4)))
        cv2.putText(out, str(text), (8, y), cv2.FONT_HERSHEY_SIMPLEX, float(scale),
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, str(text), (8, y), cv2.FONT_HERSHEY_SIMPLEX, float(scale),
                    _COLOURS[i % len(_COLOURS)], 1, cv2.LINE_AA)
    return out


def side_by_side_png(panels: Sequence[tuple[str, np.ndarray, Sequence[str]]], path: str | Path,
                     *, gap_px: int = 8) -> dict[str, Any]:
    """Write a labelled side-by-side comparison PNG (panels keep their own pixels)."""
    if not panels:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "no panels to write",
                          stage="observe.fracture_appearance.side_by_side_png")
    prepared = []
    for _title, image, lines in panels:
        arr = np.asarray(image)
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        if arr.ndim == 2:
            arr = np.repeat(arr[:, :, None], 3, axis=2)
        prepared.append(_label(arr, lines))
    height = max(p.shape[0] for p in prepared)
    blocks = []
    for p in prepared:
        if p.shape[0] < height:
            p = np.concatenate([p, np.zeros((height - p.shape[0], p.shape[1], 3), np.uint8)],
                               axis=0)
        blocks.append(p)
        blocks.append(np.zeros((height, int(gap_px), 3), dtype=np.uint8))
    canvas = np.concatenate(blocks[:-1], axis=1)
    write_rgb_png(canvas, path)
    return {"path": str(path), "panel_size_px": [int(prepared[0].shape[1]),
                                                 int(prepared[0].shape[0])],
            "canvas_size_px": [int(canvas.shape[1]), int(canvas.shape[0])],
            "n_panels": len(prepared), "geometry_modified": False, "upsampled": False}


# ======================================================================================
# configuration
# ======================================================================================
@dataclass(frozen=True)
class FractureAppearanceConfig:
    """``configs/a12/imaging_fracture_appearance.yaml`` as a frozen record."""

    enabled: bool = False
    normal_mode: str = "SMOOTH_CREASE"
    crease_angle_deg: float = 35.0
    interpolation: str = "PERSPECTIVE_CORRECT"
    supersample: int = 2
    relief_enabled: bool = True
    amplitudes_mm: tuple[float, ...] = (0.02, 0.08, 0.4)
    materials: tuple[str, ...] = ("M01", "M04", "M07")
    rung_mm_per_px: tuple[float, ...] = (0.0365, 0.039, 0.073, 0.078, 0.117, 0.156, 0.195,
                                         0.2719)
    working_distance_mm: float = 60.0
    base_tier: str = "LOCAL"
    long_edges_px: tuple[int, ...] = (1024, 2048)
    ratio_facet: float = FACET_RESOLUTION_RATIO
    glaze_strip: bool = True
    #: A2: the **delivered default** exposure of the appearance profile, in stops, applied by the
    #: frozen chain at its ``EXPOSURE_OPTICS`` stage (``scene * 2**ev``, before photon counting).
    #: It is a rig-side setting (more lamps / longer exposure), never a post-process: the chain's
    #: ``denoise`` and ``sharpening`` stages stay at 0 and nothing is upsampled.
    imaging_exposure_ev: float = 7.0
    #: A3: use the continuous band-limited albedo texture instead of the frozen per-face palette.
    albedo_texture: bool = True
    #: A3: modulation depth (peak-to-mean) of that texture.
    albedo_texture_contrast: float = 0.30
    storage_root: str = "data/a12_fapp/store"
    report_dir: str = "data/a12_reports/physical_layer"
    source_path: str = ""

    @property
    def imaging_gain(self) -> float:
        """The photon scale the delivered profile actually reaches: ``2**imaging_exposure_ev``."""
        return float(2.0 ** float(self.imaging_exposure_ev))

    def as_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        for key in ("amplitudes_mm", "materials", "rung_mm_per_px", "long_edges_px"):
            d[key] = [str(x) for x in d[key]]
        d["imaging_gain"] = self.imaging_gain
        return d


def validate_config(config: FractureAppearanceConfig) -> None:
    """Reject an out-of-contract appearance configuration (no silent clamping)."""
    if config.normal_mode not in NORMAL_MODES:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"normal_mode {config.normal_mode!r} not in {NORMAL_MODES}",
                          stage="observe.fracture_appearance.validate_config")
    if config.interpolation not in INTERPOLATIONS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"interpolation {config.interpolation!r} not in {INTERPOLATIONS}",
                          stage="observe.fracture_appearance.validate_config")
    if not (0.0 < float(config.crease_angle_deg) <= 180.0):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "crease_angle_deg must be in (0, 180]",
                          stage="observe.fracture_appearance.validate_config")
    if not (1 <= int(config.supersample) <= 4):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "supersample must be in [1, 4]",
                          stage="observe.fracture_appearance.validate_config")
    if not config.amplitudes_mm or any(float(a) <= 0.0 for a in config.amplitudes_mm):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "amplitudes_mm must be positive",
                          stage="observe.fracture_appearance.validate_config")
    if len(config.materials) < 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "at least three materials are required for the appearance comparison",
                          stage="observe.fracture_appearance.validate_config")
    if not config.rung_mm_per_px or any(float(s) <= 0.0 for s in config.rung_mm_per_px):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "rung_mm_per_px must be positive",
                          stage="observe.fracture_appearance.validate_config")
    if any(int(x) < 64 for x in config.long_edges_px):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "long_edges_px must be >= 64",
                          stage="observe.fracture_appearance.validate_config")
    if not (50.0 <= float(config.working_distance_mm) <= 100.0):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "working_distance_mm must be inside the 5-10 cm close-up window",
                          stage="observe.fracture_appearance.validate_config")
    if float(config.ratio_facet) < 2.0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "ratio_facet must be >= 2",
                          stage="observe.fracture_appearance.validate_config")
    if not (0.0 <= float(config.imaging_exposure_ev) <= 16.0):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "imaging_exposure_ev must be in [0, 16] (a rig-side exposure of more "
                          "than 16 stops is not a capture setting)",
                          stage="observe.fracture_appearance.validate_config")
    if not (0.0 < float(config.albedo_texture_contrast) <= 0.95):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "albedo_texture_contrast must be in (0, 0.95] so the albedo stays > 0",
                          stage="observe.fracture_appearance.validate_config")


_KNOWN_KEYS = set(FractureAppearanceConfig().__dict__) - {"source_path"}


def _config_from_document(document: Mapping[str, Any], *, source_path: str = ""
                          ) -> FractureAppearanceConfig:
    block = dict(document.get("fracture_appearance") or {})
    unknown = sorted(set(block) - _KNOWN_KEYS)
    if unknown:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown fracture_appearance keys: {unknown}",
                          stage="observe.fracture_appearance._config_from_document")
    storage = dict(document.get("storage") or {})
    data: dict[str, Any] = {}
    for key, value in block.items():
        data[key] = tuple(value) if key in ("amplitudes_mm", "materials", "rung_mm_per_px",
                                            "long_edges_px") else value
    if storage.get("root"):
        data["storage_root"] = str(storage["root"])
    config = replace(FractureAppearanceConfig(), source_path=str(source_path), **data)
    validate_config(config)
    return config


def load_fracture_appearance_config(path: str | Path = DEFAULT_CONFIG_PATH
                                    ) -> FractureAppearanceConfig:
    """Load and validate the appearance configuration document."""
    from ..config import load_document

    return _config_from_document(load_document(path), source_path=str(path))


def config_as_dict(config: FractureAppearanceConfig) -> dict[str, Any]:
    return config.as_dict()


def write_json(payload: Any, path: str | Path) -> str:
    """Write UTF-8 JSON with a stable key order (helper for the runners)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return str(p)



