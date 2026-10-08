"""Freeze-side of the pattern module: one builder per family (plan 9.1 / 9.3).

``build_pattern`` calls exactly one builder per recipe.  A builder:

1. draws its coefficients once from the supplied generator (nothing is redrawn later),
2. normalises continuous random fields on **area-weighted mother samples** (de-mean,
   unit RMS) and stores the measured band energy,
3. rasterises vector/raster families once and freezes the tile as PNG bytes,
4. measures real quantities (achieved spacing, chord error, distance-field error,
   retention rate, density) instead of declaring them.

Every frozen parameter dictionary is JSON-safe: arrays become rounded nested lists, so
the recipe hash covers the whole frozen state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Sequence

import numpy as np
from scipy.ndimage import binary_erosion

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import MotherGeometry
from . import grammar
from .charts import ChartFrame
from .fields import (FourierBasis, WarpField, band_projection_energy, footprint_policy,
                     jacobian_report, sample_fourier_basis, weighted_stats)
from .glyphs import discs_check, layout_text_run, resolve_font, signed_distance_mm
from .layers import FieldContext
from .params import (BandParams, BaseFamilyParams, ComboParams, CrosshatchParams, DotParams,
                     EngraveParams, GlyphParams, GridParams, KilnParams, LeafParams,
                     MeanderParams, PlainParams, ReliefParams, StripeParams, SymbolParams,
                     TriangleParams, WaveParams)
from .raster import (RasterTile, TileCanvas, distance_layer, periodic_distance, plan_raster)
from .spatial import (distance_to_points, distance_to_segments, lattice_dots,
                      polyline_segments, sample_periodic_dots)
from .symbols import (SymbolShape, build_programmatic_symbol, coverage_fraction,
                      load_svg_symbol, scale_symbol)

TWO_PI = 2.0 * np.pi
MAX_RASTER_PIXELS = 2_500_000


# ---------------------------------------------------------------------------------------
# build context
# ---------------------------------------------------------------------------------------
@dataclass
class BuildContext:
    mother: MotherGeometry
    frame: ChartFrame
    palette: dict[str, Any]
    region: dict[str, Any]
    complexity: int
    line_width_mm: float
    footprint_mm: float
    footprint_source: str
    texture_mm_per_px: float | None
    samples: np.ndarray
    sample_x: np.ndarray
    sample_s: np.ndarray
    sample_w: np.ndarray
    warp: WarpField
    warp_report: dict[str, Any]
    rng: np.random.Generator
    height: dict[str, Any]
    resource_entries: list[dict[str, Any]] = dc_field(default_factory=list)
    notes: list[str] = dc_field(default_factory=list)

    # ------------------------------------------------------------------ helpers
    @property
    def x_period_mm(self) -> float:
        return float(self.frame.x_period_mm or self.frame.s_span_mm)

    @property
    def s_min_mm(self) -> float:
        return float(self.region["s_min_mm"])

    @property
    def s_max_mm(self) -> float:
        return float(self.region["s_max_mm"])

    def palette_body(self) -> np.ndarray:
        return np.asarray(self.palette["body"], dtype=np.float64)

    def palette_paints(self) -> np.ndarray:
        return np.asarray(self.palette["paints"], dtype=np.float64)

    def sub_rng(self, key: str) -> np.random.Generator:
        """Independent PCG64 sub-stream drawn from the pattern stream (frozen once)."""
        seed = int(self.rng.integers(0, 2 ** 63, dtype=np.uint64))
        return np.random.default_rng(seed)

    def base_params(self, *, line_width_mm: float | None = None,
                    footprint_cap_mm: float | None = None) -> dict[str, Any]:
        """Frozen common parameters for one family.

        The antialiasing footprint is re-checked against *this family's* feature width: a
        footprint larger than 45% of the line half-width would erase the line core, so it
        is capped here and the cap is recorded in the source string.  Families whose
        smallest feature is not a stroke (dots) can pass ``footprint_cap_mm``.
        """
        width = float(self.line_width_mm if line_width_mm is None else line_width_mm)
        footprint = float(self.footprint_mm)
        source = str(self.footprint_source)
        cap = 0.45 * 0.5 * width if footprint_cap_mm is None else float(footprint_cap_mm)
        if footprint > cap:
            footprint = cap
            source = (f"{source}; capped to {cap:.6g} mm for the family feature width "
                      f"{width:.6g} mm")
        return {
            "complexity": int(self.complexity),
            "line_width_mm": width,
            "footprint_mm": footprint,
            "footprint_source": source,
            "requested_footprint_mm": float(self.footprint_mm),
            "paint_roughness": float(self.palette["paint_roughness"]),
            "s_periodic": bool(self.frame.s_periodic),
            "texture_mm_per_px": (None if self.texture_mm_per_px is None
                                  else float(self.texture_mm_per_px)),
        }


def _round(value: Any, ndigits: int = 9) -> Any:
    if isinstance(value, np.ndarray):
        return np.round(value, ndigits).tolist()
    if isinstance(value, (np.floating, float)):
        return float(np.round(float(value), ndigits))
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (list, tuple)):
        return [_round(v, ndigits) for v in value]
    return value


def normalize_basis_on_samples(basis: FourierBasis, ctx: BuildContext) -> dict[str, Any]:
    """De-mean and RMS-normalise a frozen basis on the area-weighted mother samples."""
    raw = basis.value(ctx.sample_x, ctx.sample_s, ctx.x_period_mm)
    stats = weighted_stats(raw, ctx.sample_w)
    offset = -float(stats["mean"])
    scale = 0.0 if stats["rms"] <= 1e-12 else 1.0 / float(stats["rms"])
    basis.offset = offset
    basis.rms_scale = scale
    basis.normalisation = {
        "mean_raw": float(stats["mean"]), "rms_raw": float(stats["rms"]),
        "offset": offset, "rms_scale": scale, "offset_units": "field",
        "n_samples": int(ctx.samples.shape[0]), "weights": "area_mm2",
        "domain": {"x_mm": [0.0, ctx.x_period_mm], "s_mm": [ctx.s_min_mm, ctx.s_max_mm]},
        "method": "area-weighted mother surface samples via trimesh.Trimesh.sample",
    }
    return basis.normalisation


def measured_field_report(basis: FourierBasis, ctx: BuildContext) -> dict[str, Any]:
    """Measured per-band energy of a frozen basis on the real mother surface."""
    energy = band_projection_energy(basis, ctx.sample_x, ctx.sample_s, ctx.sample_w,
                                    ctx.x_period_mm)
    energy["band_summary"] = basis.band_summary()
    energy["samples"] = int(ctx.samples.shape[0])
    return energy


def _tile_from_canvases(*, plan: dict[str, Any], ctx: BuildContext, rgb: np.ndarray | None = None,
                        cov: np.ndarray | None = None, dist: np.ndarray | None = None,
                        rough: np.ndarray | None = None, dist_scale_mm: float = 1.0,
                        meta: dict[str, Any] | None = None) -> RasterTile:
    shape = (int(plan["height_px"]), int(plan["width_px"]))
    layers: dict[str, np.ndarray] = {}
    if rgb is None:
        rgb = np.zeros((shape[0], shape[1], 3))
    layers["rgb_r"] = rgb[:, :, 0].astype(np.float32)
    layers["rgb_g"] = rgb[:, :, 1].astype(np.float32)
    layers["rgb_b"] = rgb[:, :, 2].astype(np.float32)
    layers["cov"] = (np.zeros(shape) if cov is None else cov).astype(np.float32)
    layers["rough"] = (np.zeros(shape) if rough is None else rough).astype(np.float32)
    payload_meta = dict(meta or {})
    if dist is not None:
        layers["dist"] = dist.astype(np.float32)
        payload_meta["dist_scale_mm"] = float(dist_scale_mm)
    return RasterTile(layers=layers, x_period_mm=ctx.x_period_mm, s0_mm=ctx.s_min_mm,
                      s1_mm=ctx.s_max_mm, px_per_mm=float(plan["px_per_mm"]), meta=payload_meta)


def _canvas(plan: dict[str, Any], ctx: BuildContext, *, mode: str = "L", background: Any = 0,
            pad_px: int = 0) -> TileCanvas:
    return TileCanvas(width_px=int(plan["width_px"]), height_px=int(plan["height_px"]),
                      s0_mm=ctx.s_min_mm, px_per_mm=float(plan["px_per_mm"]), pad_px=pad_px,
                      mode=mode, background=background)


def _stroke_distance_scale_mm(width_mm: float, footprint_mm: float) -> float:
    """Distance range a stroke layer must store: twice the alpha transition half-width.

    Storing `2*(w/2 + footprint)` keeps the saturation of the stored distance well past
    the point where the alpha already reached zero, so the saturation boundary is
    invisible in the rendered field and identical on both sides of the periodic seam.
    """
    return float(2.0 * (0.5 * float(width_mm) + float(footprint_mm)))


def _stroke_pad_px(plan: dict[str, Any], width_mm: float, footprint_mm: float) -> int:
    """EDT border wide enough that no relevant distance is truncated at the tile edge.

    A narrow border makes border pixels see "no content", so the cropped periodic
    distance carries a one-texel step at the wrap: a real seam defect even when the value
    exactly at the seam looks continuous.
    """
    scale = _stroke_distance_scale_mm(width_mm, footprint_mm)
    return int(math.ceil(scale * plan["px_per_mm"])) + 4


def _distance_from_canvas(plan: dict[str, Any], ctx: BuildContext, *, draw: Callable[[TileCanvas], None],
                          width_mm: float, footprint_mm: float) -> tuple[np.ndarray, int, dict[str, Any]]:
    """Rasterise a stroke set with wrapped copies and return the periodic EDT distance."""
    pad = _stroke_pad_px(plan, width_mm, footprint_mm)
    canvas = _canvas(plan, ctx, pad_px=pad)
    painted = canvas.render(draw)
    dist, report = distance_layer(painted > 0.5, px_per_mm=plan["px_per_mm"], pad_px=pad)
    return dist, pad, report


def validate_distance_field(*, dist: np.ndarray, plan: dict[str, Any], ctx: BuildContext,
                            segments: np.ndarray, rng: np.random.Generator, n: int = 600
                            ) -> dict[str, Any]:
    """Compare the rasterised distance with the exact periodic polyline distance."""
    if segments.size == 0:
        return {"status": "NOT_MEASURED", "reason": "no vector segments retained"}
    # bounded work: the brute-force reference is O(points x segments)
    n_eff = int(np.clip(150000 // max(1, int(segments.shape[0])), 200, int(n)))
    rng = np.random.default_rng(int(rng.integers(0, 2 ** 63, dtype=np.uint64)))
    xs = rng.uniform(0.0, ctx.x_period_mm, size=n_eff)
    ss = rng.uniform(ctx.s_min_mm, ctx.s_max_mm, size=n_eff)
    exact = distance_to_segments(xs, ss, segments, ctx.x_period_mm)
    height, width = dist.shape
    col = np.mod(xs, ctx.x_period_mm) * plan["px_per_mm"]
    row = np.clip((ss - ctx.s_min_mm) * plan["px_per_mm"], 0.0, height - 1.0)
    from scipy.ndimage import map_coordinates

    got = map_coordinates(dist, np.vstack([row, col]), order=1, mode="grid-wrap")
    error = np.abs(got - exact)
    return {
        "status": "OK", "n_samples": int(n_eff), "n_samples_requested": int(n),
        "max_abs_error_mm": float(error.max()),
        "mean_abs_error_mm": float(error.mean()),
        "p95_abs_error_mm": float(np.percentile(error, 95)),
        "texel_mm": float(1.0 / plan["px_per_mm"]),
        "method": "raster EDT distance vs exact periodic segment distance",
        "sampling_note": "sample count bounded by 150000/segments to keep the reference "
                         "comparison affordable; the exact side is brute force",
    }


# ---------------------------------------------------------------------------------------
# PAT01 / PAT02 / PAT03 / PAT04 / PAT09
# ---------------------------------------------------------------------------------------
def build_plain(model: PlainParams, ctx: BuildContext) -> dict[str, Any]:
    p = ctx.base_params()
    p.update({
        "base_color": _round(ctx.palette_body()), "base_roughness": float(ctx.palette["body_roughness"]),
        "color_amount": float(model.color_amount), "roughness_variation": float(model.roughness_variation),
        "basis": None, "roughness_basis": None,
        "plain": not (model.low_freq_color or ctx.complexity >= 2),
    })
    if not p["plain"]:
        basis = sample_fourier_basis(ctx.sub_rng("plain-colour"), x_period_mm=ctx.x_period_mm,
                                     base_wavelength_mm=model.base_wavelength_mm,
                                     n_bands=int(model.colour_bands), components_per_band=1,
                                     angle_spread_deg=50.0)
        normalize_basis_on_samples(basis, ctx)
        p["basis"] = basis.as_dict()
        if ctx.complexity >= 3 and model.roughness_variation > 0:
            rough = sample_fourier_basis(ctx.sub_rng("plain-rough"), x_period_mm=ctx.x_period_mm,
                                        base_wavelength_mm=model.base_wavelength_mm * 0.5,
                                        n_bands=1, components_per_band=2)
            normalize_basis_on_samples(rough, ctx)
            p["roughness_basis"] = rough.as_dict()
    return p


def build_band(model: BandParams, ctx: BuildContext) -> dict[str, Any]:
    width = float(model.band_width_mm)
    period = width + float(model.gap_mm)
    pair_gap = float(model.pair_gap_mm)
    width_ratio = 1.0
    if ctx.complexity >= 2 and pair_gap <= 0.0:
        pair_gap = 0.35 * width
    if ctx.complexity >= 3:
        width_ratio = 0.6
    phase = float(ctx.rng.uniform(0.0, period)) + float(model.phase_s_mm)
    p = ctx.base_params(line_width_mm=width)
    p.update({
        "band_width_mm": width, "period_mm": period, "phase_s_mm": phase,
        "pair_gap_mm": pair_gap, "width_ratio": width_ratio, "filled": bool(model.filled),
        "paint_index": 0,
        "spacing_requested_mm": float(model.gap_mm), "spacing_achieved_mm": float(model.gap_mm),
        "seam_note": "bands are constant along the periodic axis: u=0/1 agree exactly",
    })
    return p


def _stripe_group(ctx: BuildContext, *, theta_deg: float, spacing_mm: float, width_mm: float,
                  paint_index: int, phase_turns: float, thin_ratio: float = 1.0,
                  n_stripes: int | None = None) -> dict[str, Any]:
    """Freeze one stripe set with an *integer* azimuthal count.

    ``theta`` is the angle between the stripe lines and the profile axis (0 deg = lines
    running along the profile, 90 deg = lines running along the circumference).  Near 90
    deg the cosine is clamped so that at least one azimuthal cycle still fits around the
    reference circumference; without that clamp the phase would not close at the seam.
    """
    theta = math.radians(float(theta_deg))
    period = float(ctx.x_period_mm)
    spacing = float(spacing_mm)
    min_cos = 1.0 / max(1.0, period / spacing)
    cos_t = float(min(1.0, max(abs(math.cos(theta)), min_cos)))
    sin_t = math.sqrt(max(0.0, 1.0 - cos_t ** 2))
    tan_theta = sin_t / cos_t
    if n_stripes is None:
        n_int = max(1, int(round(period * cos_t / spacing)))
    else:
        n_int = max(1, int(n_stripes))
    snapped: int | None = None
    if float(thin_ratio) != 1.0:
        # Alternating thin/thick lines are a 2-colouring of the line index.  Moving x by one
        # reference circumference shifts that index by exactly n_int, so an ODD count would
        # give the two sides of the seam opposite parities and break the azimuthal seam
        # (measured: 0.80 albedo step).  The count is therefore snapped to an even number
        # and the change is recorded instead of being hidden.
        even = max(2, 2 * int(round(n_int / 2.0)))
        if even != n_int:
            snapped = int(n_int)
            n_int = even
    achieved = period * cos_t / n_int
    return {
        "n_int": int(n_int), "tan_theta": float(tan_theta),
        "theta_deg": float(theta_deg), "theta_achieved_deg": float(math.degrees(math.acos(cos_t))),
        "width_mm": float(width_mm),
        "paint_index": int(paint_index), "phase_turns": float(phase_turns),
        "thin_ratio": float(thin_ratio),
        "odd_count_snapped_from": snapped,
        "snap_rule": ("thin/thick alternation needs an even azimuthal count to stay periodic"
                      if float(thin_ratio) != 1.0 else "no alternation: count unchanged"),
        "spacing_requested_mm": float(spacing), "spacing_achieved_mm": float(achieved),
        "spacing_deviation_mm": float(achieved - spacing),
        "spacing_deviation_frac": float((achieved - spacing) / max(spacing, 1e-9)),
        "azimuthal_wavelength_mm": float(period / n_int),
        "seam_closes_exactly": True,
    }


def build_stripe(model: StripeParams, ctx: BuildContext) -> dict[str, Any]:
    theta = float(model.tilt_deg)
    groups = []
    n_groups = int(model.n_groups) if ctx.complexity >= 3 else 1
    for index in range(n_groups):
        group = _stripe_group(ctx, theta_deg=theta,
                              spacing_mm=float(model.spacing_mm),
                              width_mm=float(model.line_width_mm) * (1.0 if index == 0 else 0.65),
                              paint_index=index % max(1, ctx.palette_paints().shape[0]),
                              phase_turns=float(index) / n_groups,
                              thin_ratio=(float(model.thin_ratio)
                                          if (model.double_line and ctx.complexity >= 2) else 1.0),
                              n_stripes=(model.n_stripes if n_groups == 1 else None))
        groups.append(group)
    p = ctx.base_params()
    p.update({
        "groups": groups, "n_groups": n_groups,
        "spacing_requested_mm": float(model.spacing_mm),
        "n_stripes_requested": (None if model.n_stripes is None else int(model.n_stripes)),
        "spacing_achieved_mm": float(groups[0]["spacing_achieved_mm"]),
        "circumferential_count_integer": int(groups[0]["n_int"]),
    })
    return p


def build_grid(model: GridParams, ctx: BuildContext) -> dict[str, Any]:
    sets = [
        _stripe_group(ctx, theta_deg=0.0, spacing_mm=float(model.spacing_mm),
                      width_mm=float(model.line_width_mm), paint_index=0, phase_turns=0.0,
                      thin_ratio=float(model.thin_ratio)),
        _stripe_group(ctx, theta_deg=float(model.tilt_b_deg), spacing_mm=float(model.spacing_b_mm),
                      width_mm=float(model.line_width_mm) * float(model.thin_ratio),
                      paint_index=1, phase_turns=0.0, thin_ratio=1.0),
    ]
    if ctx.complexity >= 3:
        sets.append(_stripe_group(ctx, theta_deg=min(75.0, float(model.tilt_b_deg) * 0.5),
                                  spacing_mm=float(model.spacing_mm) * 0.5,
                                  width_mm=float(model.line_width_mm) * 0.6,
                                  paint_index=2, phase_turns=0.0, thin_ratio=1.0))
    p = ctx.base_params()
    p.update({
        "sets": sets, "mode": str(model.mode), "order": str(model.order),
        "inter_set_angle_deg": float(model.tilt_b_deg),
        "spacing_achieved_mm": [float(s["spacing_achieved_mm"]) for s in sets],
    })
    return p


def build_crosshatch(model: CrosshatchParams, ctx: BuildContext) -> dict[str, Any]:
    groups = []
    missing_fraction = float(model.missing_fraction)
    if ctx.complexity >= 3 and missing_fraction <= 0.0:
        missing_fraction = 0.12
    for index in range(int(model.groups)):
        group = _stripe_group(ctx, theta_deg=float(model.angles_deg[index]),
                              spacing_mm=float(model.spacings_mm[index]),
                              width_mm=float(model.line_width_mm) * (1.0 if index == 0 else 0.8),
                              paint_index=index % max(1, ctx.palette_paints().shape[0]),
                              phase_turns=float(ctx.rng.uniform(0.0, 1.0)))
        phi_span = _phase_span(group, ctx)
        offset = phi_span[0]
        length = phi_span[1] - phi_span[0] + 1
        # The keep/drop flags must be periodic *in the chart*: moving x by one reference
        # circumference shifts the line phase index by exactly n_int, so a flag table that
        # were random over the whole index range would drop a different line at u=0 and
        # u=1 and break the azimuthal seam.  The flags therefore repeat with period n_int.
        period = max(1, int(group["n_int"]))
        base = (ctx.rng.random(period) >= missing_fraction).astype(float)
        flags = base[np.mod(np.arange(offset, offset + length), period)]
        group["kept_lookup"] = flags.tolist()
        group["lookup_offset"] = int(offset)
        group["flags_period_lines"] = int(period)
        group["missing_fraction_requested"] = float(missing_fraction)
        group["missing_fraction_achieved"] = float(1.0 - flags.mean())
        groups.append(group)
    p = ctx.base_params()
    p.update({"groups": groups, "mix_order": str(model.mix_order),
              "n_groups": int(model.groups)})
    return p


def _phase_span(group: dict[str, Any], ctx: BuildContext) -> tuple[int, int]:
    xs = np.array([0.0, ctx.x_period_mm])
    ss = np.array([ctx.s_min_mm, ctx.s_max_mm])
    gx, gs = np.meshgrid(xs, ss, indexing="xy")
    a = group["n_int"] / ctx.x_period_mm
    phi = a * gx.reshape(-1) - a * group["tan_theta"] * gs.reshape(-1) + group["phase_turns"]
    return int(math.floor(phi.min())) - 1, int(math.ceil(phi.max())) + 2


# ---------------------------------------------------------------------------------------
# PAT05 waves (raster distance of a frozen centre line)
# ---------------------------------------------------------------------------------------
def build_wave(model: WaveParams, ctx: BuildContext) -> dict[str, Any]:
    width = float(model.line_width_mm)
    n_waves = int(model.n_waves) if model.n_waves else max(1, int(round(ctx.x_period_mm / model.wavelength_mm)))
    wavelength = ctx.x_period_mm / n_waves
    amplitude = float(model.amplitude_mm)
    n_harmonics = int(model.n_harmonics) if ctx.complexity >= 2 else 1
    s_centre = float(0.5 * (ctx.s_min_mm + ctx.s_max_mm))
    rows = 1
    row_spacing = 0.0
    if ctx.complexity >= 3 and float(model.row_spacing_mm) > 0:
        row_spacing = float(model.row_spacing_mm)
        rows = max(1, int(np.floor(ctx.s_max_mm - ctx.s_min_mm) / row_spacing))
    lines: list[np.ndarray] = []
    amplitude_achieved = 0.0
    phase0 = float(ctx.rng.uniform(0.0, TWO_PI))
    factors = [1.0, 0.22, 0.09][:n_harmonics]

    def analytic(xs_query: np.ndarray) -> np.ndarray:
        """Periodic multi-harmonic centre line: every harmonic has an integer count."""
        offset = np.zeros_like(np.asarray(xs_query, dtype=np.float64))
        for order, factor in enumerate(factors, start=1):
            offset = offset + factor * np.sin(TWO_PI * (n_waves * order) * np.asarray(xs_query)
                                               / ctx.x_period_mm + phase0 * order)
        return s_centre + amplitude * offset / max(1e-9, float(np.abs(offset).max()))

    if model.variant == "bezier":
        path = grammar.bezier_wave_path(x_period_mm=ctx.x_period_mm, s_centre_mm=s_centre,
                                        amplitude_mm=amplitude, n_waves=n_waves,
                                        harmonics=tuple(1.0 for _ in range(n_harmonics)))
        flat = grammar.flatten_path(path, max_chord_error_mm=max(0.02, width / 8.0), max_points=4096)
        base = flat.xy
        chord_error = float(flat.stats["achieved_chord_error_mm"])
        path_length = float(flat.stats["length_mm"])
    else:
        steps = int(np.clip(round(ctx.x_period_mm / max(wavelength / 48.0, 0.05)), 64, 4096))
        xs = np.linspace(0.0, ctx.x_period_mm, steps)
        base = np.stack([xs, analytic(xs)], axis=1)
        mid = 0.5 * (xs[:-1] + xs[1:])
        chord_error = float(np.abs(analytic(mid) - 0.5 * (base[:-1, 1] + base[1:, 1])).max())
        path_length = float(grammar.polyline_length(base))
    amplitude_achieved = float(np.abs(base[:, 1] - s_centre).max())
    endpoint_mismatch = float(abs(base[0, 1] - base[-1, 1]))
    for row in range(rows):
        s_row = (ctx.s_min_mm + (row + 0.5) * row_spacing) if rows > 1 else s_centre
        shift = s_row - s_centre
        lines.append(np.stack([base[:, 0], base[:, 1] + shift], axis=1))
    segments = np.vstack([polyline_segments(line[:, 0], line[:, 1]) for line in lines])
    plan = plan_raster(x_period_mm=ctx.x_period_mm, s_min_mm=ctx.s_min_mm, s_max_mm=ctx.s_max_mm,
                       feature_mm=width, max_pixels=MAX_RASTER_PIXELS)

    def draw(canvas: TileCanvas) -> None:
        for line in lines:
            canvas.line_mm(line[:, 0], line[:, 1], 255, width)
        if bool(model.double_line) and ctx.complexity >= 2:
            for line in lines:
                offset_mm = 1.6 * width
                canvas.line_mm(line[:, 0], line[:, 1] + offset_mm, 255, width * 0.6)

    dist, pad, edt_report = _distance_from_canvas(plan, ctx, draw=draw, width_mm=width,
                                                 footprint_mm=ctx.footprint_mm)
    dist_scale = _stroke_distance_scale_mm(width, ctx.footprint_mm)
    validation = validate_distance_field(dist=dist, plan=plan, ctx=ctx, segments=segments,
                                        rng=ctx.sub_rng("wave-validate"))
    tile = _tile_from_canvases(plan=plan, ctx=ctx, dist=dist, dist_scale_mm=dist_scale,
                               meta={"family": "PAT05", "plan": plan, "edt": edt_report})
    p = ctx.base_params(line_width_mm=width)
    p.update({
        "raster": tile.to_payload(),
        "paint_index": 0,
        "n_waves": int(n_waves), "wavelength_achieved_mm": float(wavelength),
        "wavelength_requested_mm": float(model.wavelength_mm),
        "amplitude_requested_mm": amplitude, "amplitude_achieved_mm": amplitude_achieved,
        "endpoint_mismatch_mm": endpoint_mismatch,
        "variant": str(model.variant), "n_harmonics": n_harmonics,
        "rows": int(rows), "row_spacing_mm": float(row_spacing),
        "path_length_mm": path_length, "chord_error_mm": float(chord_error),
        "polyline_points": int(base.shape[0]),
        "raster_plan": plan, "distance_validation": validation,
    })
    return p


# ---------------------------------------------------------------------------------------
# PAT06 dots
# ---------------------------------------------------------------------------------------
def build_dots(model: DotParams, ctx: BuildContext) -> dict[str, Any]:
    mode = str(model.mode)
    if ctx.complexity >= 3 and mode == "poisson" and model.var_radius_mm is None:
        var_radius = (0.6 * float(model.radius_mm), 1.4 * float(model.radius_mm))
    else:
        var_radius = model.var_radius_mm
    if mode == "lattice":
        dots = lattice_dots(x_period_mm=ctx.x_period_mm, s_min_mm=ctx.s_min_mm,
                            s_max_mm=ctx.s_max_mm, spacing_mm=float(model.spacing_mm),
                            radius_mm=float(model.radius_mm), mode=str(model.lattice_mode),
                            phase_x_mm=float(ctx.rng.uniform(0.0, ctx.x_period_mm)),
                            phase_s_mm=float(ctx.rng.uniform(0.0, model.spacing_mm)))
    else:
        dots = sample_periodic_dots(ctx.rng, x_period_mm=ctx.x_period_mm, s_min_mm=ctx.s_min_mm,
                                    s_max_mm=ctx.s_max_mm, radius_mm=float(model.radius_mm),
                                    var_radius_mm=var_radius,
                                    clearance_mm=float(model.clearance_mm),
                                    density_target_per_100mm2=model.density_target_per_100mm2)
    p = ctx.base_params(footprint_cap_mm=0.45 * (float(var_radius[0]) if var_radius
                                                 else float(model.radius_mm)))
    p.update({
        "dots": dots.payload(), "sampling_report": dots.report,
        "solid": bool(model.solid), "ring_ratio": float(model.ring_ratio),
        "mode": mode, "paint_index": 0,
        "radius_mm": float(model.radius_mm),
        "dot_diameter_requested_mm": 2.0 * float(model.radius_mm),
        "dot_diameter_realized_mm": (2.0 * float(model.radius_mm) if var_radius is None
                                     else [2.0 * float(var_radius[0]), 2.0 * float(var_radius[1])]),
        "var_radius_mm": (None if var_radius is None else [float(var_radius[0]), float(var_radius[1])]),
        "requested_spacing_mm": (float(model.spacing_mm) if mode == "lattice" else None),
    })
    return p


# ---------------------------------------------------------------------------------------
# PAT07 triangles
# ---------------------------------------------------------------------------------------
def _triangle_lattice(ctx: BuildContext, *, edge_x_mm: float, row_height_mm: float,
                      shear: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (vertices, up-triangles, down-triangles) as index tuples in chart mm."""
    rows = int(np.ceil(ctx.frame.s_span_mm / row_height_mm)) + 2
    cols = int(round(ctx.x_period_mm / edge_x_mm))
    verts: list[tuple[float, float]] = []
    index = np.full((rows + 1, cols + 1), -1, dtype=np.int64)
    for k in range(rows + 1):
        y = ctx.s_min_mm + (k - 1) * row_height_mm
        for i in range(cols + 1):
            x = (i + 0.5 * (k % 2)) * edge_x_mm + shear * (y - ctx.s_min_mm)
            index[k, i] = len(verts)
            verts.append((x, y))
    up: list[tuple[int, int, int]] = []
    down: list[tuple[int, int, int]] = []
    for k in range(rows):
        for i in range(cols):
            a, b = index[k, i], index[k, i + 1]
            c, d = index[k + 1, i], index[k + 1, i + 1]
            up.append((a, b, d))
            down.append((a, d, c))
    return np.asarray(verts), np.asarray(up), np.asarray(down)


def build_triangle(model: TriangleParams, ctx: BuildContext) -> dict[str, Any]:
    requested_edge = float(model.edge_mm)
    n_cols = max(1, int(round(ctx.x_period_mm / requested_edge)))
    edge_x = ctx.x_period_mm / n_cols
    row_height = edge_x * math.sqrt(3.0) / 2.0
    shear = math.tan(math.radians(float(model.orientation_deg)))
    verts, up, down = _triangle_lattice(ctx, edge_x_mm=edge_x, row_height_mm=row_height, shear=shear)
    solid = str(model.mode) == "solid"
    n_colours = int(model.n_colours) if ctx.complexity >= 2 else 1
    paints = ctx.palette_paints()
    plan = plan_raster(x_period_mm=ctx.x_period_mm, s_min_mm=ctx.s_min_mm, s_max_mm=ctx.s_max_mm,
                       feature_mm=(0.6 * float(model.line_width_mm) if not solid else edge_x / 8.0),
                       max_pixels=MAX_RASTER_PIXELS)
    rgb = np.zeros((int(plan["height_px"]), int(plan["width_px"]), 3))
    cov = np.zeros((int(plan["height_px"]), int(plan["width_px"])))
    segments = np.vstack([polyline_segments(verts[[a, b, c, a]][:, 0], verts[[a, b, c, a]][:, 1])
                          for a, b, c in up])
    if solid:
        want_down = ctx.complexity >= 3 and bool(model.barycentric)
        triangles = list(up) + (list(down) if want_down else [])
        palette = np.vstack([ctx.palette_body()[None, :], ctx.palette_paints()])

        def draw_fill(canvas: TileCanvas) -> None:
            for index, tri in enumerate(triangles):
                canvas.polygon_mm(*_triangle_xy(verts, tri), 255)

        canvas_cov = _canvas(plan, ctx, mode="L")
        cov = canvas_cov.render(draw_fill)
        for channel in range(3):
            channel_canvas = _canvas(plan, ctx, mode="L")
            for index, tri in enumerate(triangles):
                colour = palette[(index % max(1, n_colours)) + 1]

                def draw_channel(c: TileCanvas, tri=tri, colour=colour, channel=channel) -> None:
                    c.polygon_mm(*_triangle_xy(verts, tri), int(round(255 * float(colour[channel]))))
                channel_canvas.render(draw_channel)
            rgb[:, :, channel] = np.asarray(channel_canvas.image, dtype=np.float64) / 255.0
        dist = None
        pad = 0
        edt_report = {"status": "NA", "reason": "solid tile has no stroke distance layer"}
        validation = {"status": "NA", "reason": "solid tile is a fill, not a stroke"}
    else:
        def draw(canvas: TileCanvas) -> None:
            for a, b, c in up:
                pts = verts[[a, b, c, a]]
                canvas.line_mm(pts[:, 0], pts[:, 1], 255, float(model.line_width_mm))

        dist, pad, edt_report = _distance_from_canvas(plan, ctx, draw=draw,
                                                     width_mm=float(model.line_width_mm),
                                                     footprint_mm=ctx.footprint_mm)
        validation = validate_distance_field(dist=dist, plan=plan, ctx=ctx, segments=segments,
                                            rng=ctx.sub_rng("triangle-validate"))
        rgb = _triangle_colour_map(plan, ctx, verts, up, down, n_colours)
    dist_scale = _stroke_distance_scale_mm(float(model.line_width_mm), ctx.footprint_mm)
    tile = _tile_from_canvases(plan=plan, ctx=ctx, rgb=rgb, cov=cov,
                               dist=(dist if dist is not None else None),
                               dist_scale_mm=dist_scale,
                               meta={"family": "PAT07", "plan": plan, "edt": edt_report})
    p = ctx.base_params(line_width_mm=float(model.line_width_mm))
    p.update({
        "raster": tile.to_payload(), "mode": str(model.mode), "paint_index": 0,
        "n_cols": int(n_cols), "edge_requested_mm": requested_edge,
        "edge_achieved_mm": float(edge_x), "row_height_mm": float(row_height),
        "shear": float(shear), "orientation_kind": "chart_plane_shear",
        "n_vertices": int(verts.shape[0]), "n_triangles": int(up.shape[0] + down.shape[0]),
        "n_colours": n_colours, "barycentric": bool(model.barycentric),
        "raster_plan": plan, "distance_validation": validation, "edt": edt_report,
    })
    return p


def _triangle_xy(verts: np.ndarray, tri: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
    pts = verts[np.asarray(list(tri), dtype=np.int64)]
    return pts[:, 0], pts[:, 1]


def _triangle_colour_map(plan: dict[str, Any], ctx: BuildContext, verts: np.ndarray,
                         up: np.ndarray, down: np.ndarray, n_colours: int) -> np.ndarray:
    """Per-pixel paint colour from the triangle index (frozen, periodic)."""
    del down
    palette = np.vstack([ctx.palette_body()[None, :], ctx.palette_paints()])
    rgb = np.zeros((int(plan["height_px"]), int(plan["width_px"]), 3))
    for channel in range(3):
        channel_canvas = _canvas(plan, ctx, mode="L")
        for index, tri in enumerate(up):
            colour = palette[(index % max(1, n_colours)) + 1]

            def draw(c: TileCanvas, tri=tri, colour=colour, channel=channel) -> None:
                c.polygon_mm(*_triangle_xy(verts, tri), int(round(255 * float(colour[channel]))))
            channel_canvas.render(draw)
        rgb[:, :, channel] = np.asarray(channel_canvas.image, dtype=np.float64) / 255.0
    return rgb


# ---------------------------------------------------------------------------------------
# PAT08 meander
# ---------------------------------------------------------------------------------------
def _meander_path(*, tile_w_mm: float, tile_h_mm: float, y0: float, n_turns: int,
                  wave: bool = False) -> np.ndarray:
    """One fret unit: enters at ``(0, y0)`` and leaves at ``(tile_w, y0)``."""
    margin_x = 0.12 * tile_w_mm
    left, right = margin_x, tile_w_mm - margin_x
    low, high = y0 + 0.18 * tile_h_mm, y0 + tile_h_mm
    pts: list[tuple[float, float]] = [(0.0, y0), (0.0, high), (right, high)]
    for _ in range(max(1, int(n_turns))):
        pts.append((right, low))
        pts.append((left, low))
        high_next = low + 0.62 * (high - low)
        pts.append((left, high_next))
        right_next = left + 0.55 * (right - left)
        pts.append((right_next, high_next))
        high, right = high_next, right_next
        if right - left < 0.15 * tile_w_mm or high - low < 0.15 * tile_h_mm:
            break
    inner_x = 0.5 * (left + right)
    pts.append((inner_x, y0))
    pts.append((tile_w_mm, y0))
    xy = np.asarray(pts, dtype=np.float64)
    if wave:
        dense = []
        for index in range(xy.shape[0] - 1):
            a, b = xy[index], xy[index + 1]
            steps = max(2, int(abs(b[0] - a[0]) / (0.08 * tile_w_mm)) + 2)
            for t in np.linspace(0.0, 1.0, steps, endpoint=False):
                point = a + t * (b - a)
                point[1] += 0.12 * tile_h_mm * math.sin(TWO_PI * t * 2.0)
                dense.append(point)
        dense.append(xy[-1])
        xy = np.asarray(dense, dtype=np.float64)
    return xy


def build_meander(model: MeanderParams, ctx: BuildContext) -> dict[str, Any]:
    requested_tile = float(model.tile_w_mm)
    n_tiles = max(1, int(round(ctx.x_period_mm / requested_tile)))
    tile_w = ctx.x_period_mm / n_tiles
    tile_h = float(model.tile_h_mm)
    rows = max(1, int(np.floor(ctx.frame.s_span_mm / tile_h)))
    width = float(model.line_width_mm)
    unit = _meander_path(tile_w_mm=tile_w, tile_h_mm=tile_h, y0=0.0,
                         n_turns=int(model.n_turns), wave=str(model.style) == "wave_key")
    lines: list[np.ndarray] = []
    for row in range(rows):
        y0 = ctx.s_min_mm + (row + 0.25) * tile_h
        for copy in range(n_tiles):
            block = unit.copy()
            block[:, 0] += copy * tile_w
            block[:, 1] += y0
            lines.append(block)
            if bool(model.double_line) and ctx.complexity >= 2:
                lines.append(block + np.array([0.0, 0.85 * width]))
    segments = np.vstack([polyline_segments(line[:, 0], line[:, 1]) for line in lines])
    plan = plan_raster(x_period_mm=ctx.x_period_mm, s_min_mm=ctx.s_min_mm, s_max_mm=ctx.s_max_mm,
                       feature_mm=width, max_pixels=MAX_RASTER_PIXELS)

    def draw(canvas: TileCanvas) -> None:
        for line in lines:
            canvas.line_mm(line[:, 0], line[:, 1], 255, width)

    dist, pad, edt_report = _distance_from_canvas(plan, ctx, draw=draw, width_mm=width,
                                                 footprint_mm=ctx.footprint_mm)
    validation = validate_distance_field(dist=dist, plan=plan, ctx=ctx, segments=segments,
                                        rng=ctx.sub_rng("meander-validate"))
    dist_scale = _stroke_distance_scale_mm(width, ctx.footprint_mm)
    tile = _tile_from_canvases(plan=plan, ctx=ctx, dist=dist, dist_scale_mm=dist_scale,
                               meta={"family": "PAT08", "plan": plan, "edt": edt_report})
    p = ctx.base_params(line_width_mm=width)
    p.update({
        "raster": tile.to_payload(), "paint_index": 0,
        "n_tiles_around": int(n_tiles), "tile_w_requested_mm": requested_tile,
        "tile_w_achieved_mm": float(tile_w), "tile_h_mm": tile_h, "rows": int(rows),
        "n_turns": int(model.n_turns), "style": str(model.style),
        "segment_count": int(segments.shape[0]),
        "endpoint_mismatch_mm": float(abs(unit[0, 1] - unit[-1, 1])),
        "tile_endpoints_connected": bool(abs(unit[0, 1] - unit[-1, 1]) < 1e-9),
        "double_line": bool(model.double_line),
        "raster_plan": plan, "distance_validation": validation,
    })
    return p


# ---------------------------------------------------------------------------------------
# PAT10 floral
# ---------------------------------------------------------------------------------------
def build_leaf(model: LeafParams, ctx: BuildContext) -> dict[str, Any]:
    text, grammar_stats = grammar.expand_lsystem("F[+F]F[-F]", int(model.generations),
                                                segment_cap=int(model.segment_cap))
    turtle = grammar.turtle_from_string(text, step_mm=float(model.step_mm),
                                        angle_deg=float(model.angle_deg),
                                        branch_probability=float(model.branch_probability),
                                        heading_deg=90.0)
    stems: list[np.ndarray] = []
    bezier_stats: list[dict[str, Any]] = []
    for branch in turtle.polylines:
        if branch.shape[0] < 2:
            continue
        path = grammar.polyline_to_bezier_path(branch, curvature=float(model.bezier_curvature))
        flat = grammar.flatten_path(path, max_chord_error_mm=max(0.02, float(model.stem_width_mm) / 8.0),
                                    max_points=2048)
        stems.append(flat.xy)
        bezier_stats.append(flat.stats)
    if not stems:
        raise SynLabError(ErrorCode.TARGET_INFEASIBLE,
                          "bounded L-system produced no drawable stem; check generations/segment_cap",
                          stage="patterns.builders.build_leaf")
    leaves: list[np.ndarray] = []
    leaf_stats: dict[str, Any] = {}
    for stem in stems:
        got, _, stats = grammar.leaf_placement(stem, spacing_mm=float(model.leaf_spacing_mm),
                                               length_mm=float(model.leaf_length_mm),
                                               width_mm=float(model.leaf_length_mm) * float(model.leaf_aspect),
                                               angle_deg=float(model.angle_deg))
        leaves.extend(got)
        leaf_stats = stats
    bbox = _bbox(np.vstack(stems + leaves))
    motif_w = max(bbox[2] - bbox[0], 1e-6)
    motif_h = max(bbox[3] - bbox[1], 1e-6)
    n_tiles = max(1, int(round(ctx.x_period_mm / (1.35 * motif_w))))
    tile_w = ctx.x_period_mm / n_tiles
    scale = max(min(0.85 * tile_w / motif_w, 0.85 * ctx.frame.s_span_mm / motif_h), 1e-3)
    dx = tile_w * 0.5 - 0.5 * (bbox[0] + bbox[2]) * scale
    ds = 0.5 * (ctx.s_min_mm + ctx.s_max_mm) - 0.5 * (bbox[1] + bbox[3]) * scale

    def place(points: np.ndarray) -> np.ndarray:
        return points * scale + np.array([dx + ctx.x_period_mm * 0.5, ds])

    placed_stems = [place(stem) for stem in stems]
    placed_leaves = [place(leaf) for leaf in leaves]
    requested_width = float(model.stem_width_mm) * max(scale, 0.2)
    # the plan's line-width floor applies to what is really drawn: a stem scaled below
    # 0.5 mm would be unrepresentable, so it is clamped and both values are recorded
    width = float(max(0.5, min(3.0, requested_width)))
    plan = plan_raster(x_period_mm=ctx.x_period_mm, s_min_mm=ctx.s_min_mm, s_max_mm=ctx.s_max_mm,
                       feature_mm=max(0.4, min(width, float(model.leaf_length_mm) * model.leaf_aspect / 4)),
                       max_pixels=MAX_RASTER_PIXELS)
    stem_segments = np.vstack([polyline_segments(stem[:, 0], stem[:, 1]) for stem in placed_stems])
    segments_all: list[np.ndarray] = [stem_segments]
    for copy in range(n_tiles):
        if copy:
            segments_all.append(stem_segments + np.array([copy * tile_w, 0.0, copy * tile_w, 0.0]))
    segments = np.vstack(segments_all)
    leaf_colour = ctx.palette_paints()[1 % max(1, ctx.palette_paints().shape[0])]
    n_leaves_per_tile = len(placed_leaves)

    def draw_dist(canvas: TileCanvas) -> None:
        for copy in range(n_tiles):
            shift = copy * tile_w
            for stem in placed_stems:
                canvas.line_mm(stem[:, 0] + shift, stem[:, 1], 255, width)
            if ctx.complexity >= 3:
                for stem in placed_stems:
                    canvas.line_mm(stem[:, 0] + shift, stem[:, 1] + 1.4 * width, 255, width * 0.5)

    dist, pad, edt_report = _distance_from_canvas(plan, ctx, draw=draw_dist, width_mm=width,
                                                 footprint_mm=ctx.footprint_mm)
    cov = np.zeros((int(plan["height_px"]), int(plan["width_px"])))
    rgb = np.zeros((int(plan["height_px"]), int(plan["width_px"]), 3))
    fallback_colour = ctx.palette_paints()[0]
    for channel in range(3):
        # the paint tile background is the fallback paint colour: the sampled paint channel
        # then stays continuous where the raster content ends (a hard switch to a palette
        # fallback would kink the albedo at the stroke boundary)
        canvas = _canvas(plan, ctx, mode="L",
                         background=int(round(255 * float(fallback_colour[channel]))))
        value = int(round(255 * float(leaf_colour[channel])))

        def draw_leaf(c: TileCanvas, value=value) -> None:
            for copy in range(n_tiles):
                shift = copy * tile_w
                for leaf in placed_leaves:
                    c.polygon_mm(leaf[:, 0] + shift, leaf[:, 1], value)
        canvas.render(draw_leaf)
        rgb[:, :, channel] = np.asarray(canvas.image, dtype=np.float64) / 255.0

    def draw_leaf_mask(c: TileCanvas) -> None:
        for copy in range(n_tiles):
            shift = copy * tile_w
            for leaf in placed_leaves:
                c.polygon_mm(leaf[:, 0] + shift, leaf[:, 1], 255)

    canvas_cov = _canvas(plan, ctx, mode="L")
    canvas_cov.render(draw_leaf_mask)
    cov = np.asarray(canvas_cov.image, dtype=np.float64) / 255.0
    validation = validate_distance_field(dist=dist, plan=plan, ctx=ctx, segments=segments,
                                        rng=ctx.sub_rng("leaf-validate"))
    dist_scale = _stroke_distance_scale_mm(width, ctx.footprint_mm)
    tile = _tile_from_canvases(plan=plan, ctx=ctx, rgb=rgb, cov=cov, dist=dist,
                               dist_scale_mm=dist_scale,
                               meta={"family": "PAT10", "plan": plan, "edt": edt_report})
    p = ctx.base_params(line_width_mm=width)
    p.update({
        "raster": tile.to_payload(), "paint_index": 0,
        "grammar": grammar_stats, "turtle": turtle.stats,
        "bezier": {"n_branches": len(bezier_stats),
                   "chord_error_mm_max": float(max(s["achieved_chord_error_mm"] for s in bezier_stats)),
                   "length_mm_total": float(sum(s["length_mm"] for s in bezier_stats))},
        "leaf": {k: v for k, v in leaf_stats.items() if k != "flatten"},
        "leaf_placement_scale": float(scale), "n_tiles_around": int(n_tiles),
        "stem_width_requested_mm": float(requested_width),
        "stem_width_realized_mm": float(width),
        "stem_width_rule": "clamped into the plan 9.3 line-width band [0.5, 3] mm after "
                           "scaling the motif into the tile",
        "tile_w_mm": float(tile_w), "n_leaves_per_tile": int(n_leaves_per_tile),
        "motif_bbox_mm": [float(v) for v in bbox],
        "raster_plan": plan, "distance_validation": validation,
    })
    return p


def _bbox(points: np.ndarray) -> tuple[float, float, float, float]:
    return (float(points[:, 0].min()), float(points[:, 1].min()),
            float(points[:, 0].max()), float(points[:, 1].max()))


# ---------------------------------------------------------------------------------------
# PAT11 medallion
# ---------------------------------------------------------------------------------------
def build_symbol(model: SymbolParams, ctx: BuildContext) -> dict[str, Any]:
    if model.source == "svg_path":
        shape = load_svg_symbol(str(model.svg_path), license_ref=str(model.license_ref),
                                max_file_bytes=int(model.max_file_bytes),
                                max_elements=int(model.max_elements),
                                max_segments=int(model.max_segments))
        ctx.resource_entries.append({"kind": "svg", "file": str(model.svg_path),
                                     "hash": shape.resource_hash,
                                     "license_ref": str(model.license_ref)})
    else:
        shape = build_programmatic_symbol(str(model.symbol_id))
    shape = scale_symbol(shape, size_mm=float(model.size_mm))
    count = max(1, int(model.count_around))
    s_place = float(model.placement_s_mm) if model.placement_s_mm is not None else \
        float(0.5 * (ctx.s_min_mm + ctx.s_max_mm))
    phase = float(ctx.rng.uniform(0.0, 1.0))
    placements = []
    placement_scale = [1.0] * count
    if bool(model.two_sizes) and ctx.complexity >= 2:
        placement_scale = [1.0 if i % 2 == 0 else float(model.small_ratio) for i in range(count)]
    for index in range(count):
        placements.append({
            "x_mm": float(((index + 0.5) / count + phase) % 1.0 * ctx.x_period_mm),
            "s_mm": s_place, "rotate_deg": float(model.rotate_deg), "scale": placement_scale[index],
        })
    clear_band = None
    if bool(model.keep_clear) and ctx.complexity >= 3:
        clear_band = {"centre_x_mm": float((phase + 0.5 / count) % 1.0 * ctx.x_period_mm),
                      "width_mm": float(ctx.x_period_mm / count * 0.35), "feather_mm": 1.5}
    connectors: list[list[list[float]]] = []
    if bool(model.connector_arcs) and ctx.complexity >= 3 and count >= 2:
        radius = float(model.size_mm) * 0.75
        for index in range(count):
            x0 = placements[index]["x_mm"]
            x1 = placements[(index + 1) % count]["x_mm"]
            span = (x1 - x0) % ctx.x_period_mm
            steps = 32
            xs = (x0 + np.linspace(0.0, span, steps)) % ctx.x_period_mm
            ss = s_place + radius * np.sin(np.linspace(0.0, math.pi, steps))
            connectors.append([[float(a), float(b)] for a, b in zip(xs, ss)])
    validity = coverage_fraction(shape, size_mm=float(model.size_mm))
    p = ctx.base_params(line_width_mm=float(model.stroke_width_mm))
    p.update({
        "shape": shape.as_payload(), "placements": placements,
        "two_sizes": bool(model.two_sizes) and ctx.complexity >= 2,
        "small_ratio": float(model.small_ratio),
        "stroke": bool(model.stroke), "fill": bool(model.fill),
        "stroke_width_mm": float(model.stroke_width_mm),
        "count_around": count, "clear_band": clear_band, "connectors": connectors,
        "paint_index": 0, "symbol_source": str(model.source),
        "shape_validity": validity, "resource_hash": shape.resource_hash,
        "license_ref": shape.license_ref, "shape_meta": shape.meta,
    })
    return p


# ---------------------------------------------------------------------------------------
# PAT12 glyphs
# ---------------------------------------------------------------------------------------
def build_glyph(model: GlyphParams, ctx: BuildContext) -> dict[str, Any]:
    font = resolve_font(model.font_id, model.font_path)
    ctx.resource_entries.append({"kind": "font", "font_id": font.font_id, "path": font.path,
                                 "hash": font.sha256, "license_ref": font.license_ref,
                                 "family": font.family, "style": font.style})
    stroke = bool(model.stroke)
    feature = float(model.stroke_width_mm) if stroke else float(model.font_size_mm) / 10.0
    plan = plan_raster(x_period_mm=ctx.x_period_mm, s_min_mm=ctx.s_min_mm, s_max_mm=ctx.s_max_mm,
                       feature_mm=max(0.4, feature), max_pixels=MAX_RASTER_PIXELS)
    rings = int(model.ring_count) if ctx.complexity >= 3 else 1
    span = ctx.frame.s_span_mm
    s_centres = [ctx.s_min_mm + span * (0.5 if rings == 1 else 0.34)]
    if rings > 1:
        s_centres.append(ctx.s_min_mm + span * 0.72)

    cov = np.zeros((int(plan["height_px"]), int(plan["width_px"])))
    edge = np.zeros_like(cov)
    rgb = np.zeros((int(plan["height_px"]), int(plan["width_px"]), 3))
    layouts: list[dict[str, Any]] = []
    paint_colour = ctx.palette_paints()[0]
    for ring_index, s_centre in enumerate(s_centres):
        baseline = float(model.baseline_s_mm) if model.baseline_s_mm is not None else s_centre
        size_mm = float(model.font_size_mm) * (1.0 if ring_index == 0
                                               else float(model.ring2_size_ratio))
        layout = layout_text_run(text=str(model.text), font=font, font_size_mm=size_mm,
                                 letter_spacing_mm=float(model.letter_spacing_mm),
                                 px_per_mm=float(plan["px_per_mm"]),
                                 tile_width_mm=ctx.x_period_mm,
                                 run_gap_mm=float(model.run_gap_mm),
                                 baseline_s_mm=baseline, s0_mm=ctx.s_min_mm,
                                 height_px=int(plan["height_px"]), copies_hint=0)
        layouts.append({"ring": ring_index, "s_centre_mm": s_centre, "size_mm": size_mm,
                        "baseline_s_mm": baseline, **layout.metrics,
                        "missing_glyphs": layout.missing_glyphs})
        cov = np.maximum(cov, layout.mask)
        eroded = binary_erosion(layout.mask > 0.5, iterations=1)
        edge = np.maximum(edge, (layout.mask > 0.5) & ~eroded)
    if bool(model.rule_lines) and ctx.complexity >= 3:
        band = np.zeros_like(cov)
        for factor in (0.18, 0.82):
            s_line = ctx.s_min_mm + span * factor
            band[np.abs(np.arange(int(plan["height_px"])) / plan["px_per_mm"]
                        + ctx.s_min_mm - s_line) <= 0.5 / plan["px_per_mm"]] = 1.0
        edge = np.maximum(edge, band)
    # the tile stores the *paint colour* over the glyph area (not colour*coverage): the
    # evaluator blends it with the palette fallback by the coverage layer, so a stroke that
    # crosses the azimuthal seam stays continuous in value and in its first derivative
    glyph_mask = cov > 0.0
    for channel in range(3):
        # uniform ink colour: the coverage channel carries the shape, so the paint channel
        # has no premultiplied-zero step at the glyph boundary
        rgb[:, :, channel] = float(paint_colour[channel]) * np.ones_like(cov)
    pad = _stroke_pad_px(plan, float(model.stroke_width_mm), ctx.footprint_mm)
    dist, edt_report = periodic_distance(edge > 0.5, px_per_mm=float(plan["px_per_mm"]), pad_px=pad)
    dist_scale = _stroke_distance_scale_mm(float(model.stroke_width_mm), ctx.footprint_mm)
    disc = discs_check(px_per_mm=float(plan["px_per_mm"]), radius_mm=max(1.0, feature * 4))
    tile = _tile_from_canvases(plan=plan, ctx=ctx, rgb=rgb, cov=cov, dist=dist,
                               dist_scale_mm=dist_scale,
                               meta={"family": "PAT12", "plan": plan, "edt": edt_report})
    p = ctx.base_params(line_width_mm=float(model.stroke_width_mm))
    p.update({
        "raster": tile.to_payload(), "paint_index": 0,
        "text": str(model.text), "font": font.as_dict(),
        "fill": not stroke, "stroke": stroke,
        "stroke_width_mm": float(model.stroke_width_mm),
        "rings": layouts, "ring_count": int(rings),
        "raster_plan": plan, "edt": edt_report,
        "edt_scale_check": disc,
        "layout_frozen_once": True,
    })
    return p


# ---------------------------------------------------------------------------------------
# PAT13 kiln
# ---------------------------------------------------------------------------------------
def build_kiln(model: KilnParams, ctx: BuildContext) -> dict[str, Any]:
    blotch = sample_fourier_basis(ctx.sub_rng("kiln-blotch"), x_period_mm=ctx.x_period_mm,
                                  base_wavelength_mm=float(model.base_wavelength_mm),
                                  n_bands=int(model.n_scales), components_per_band=1,
                                  angle_spread_deg=60.0)
    normalize_basis_on_samples(blotch, ctx)
    speckle = sample_fourier_basis(ctx.sub_rng("kiln-speckle"), x_period_mm=ctx.x_period_mm,
                                   base_wavelength_mm=float(model.speckle_wavelength_mm),
                                   n_bands=1, components_per_band=6, angle_spread_deg=90.0)
    normalize_basis_on_samples(speckle, ctx)
    # roughness uses an independent sub-stream: same recipe, different coefficients
    roughness = sample_fourier_basis(ctx.sub_rng("kiln-roughness"), x_period_mm=ctx.x_period_mm,
                                     base_wavelength_mm=float(model.base_wavelength_mm) * 0.7,
                                     n_bands=2, components_per_band=1, angle_spread_deg=45.0)
    normalize_basis_on_samples(roughness, ctx)
    paints = ctx.palette_paints()
    stops = [ctx.palette_body()] + [paints[i % paints.shape[0]] for i in range(int(model.colour_stops) - 1)]
    blotch_values = blotch.value(ctx.sample_x, ctx.sample_s, ctx.x_period_mm)
    rough_values = roughness.value(ctx.sample_x, ctx.sample_s, ctx.x_period_mm)
    if blotch_values.std() > 0 and rough_values.std() > 0:
        correlation = float(np.corrcoef(blotch_values, rough_values)[0, 1])
    else:
        correlation = 0.0
    p = ctx.base_params()
    p.update({
        "blotch": blotch.as_dict(), "speckle": speckle.as_dict(), "roughness": roughness.as_dict(),
        "blotch_contrast": float(model.blotch_contrast), "speckle_amount": float(model.speckle_amount),
        "colour_stops": _round(np.asarray(stops)), "colour_stop_count": int(model.colour_stops),
        "roughness_base": float(ctx.palette["body_roughness"]),
        "roughness_coupling": float(model.roughness_coupling) * float(model.roughness_scale),
        "roughness_speckle": float(model.roughness_scale) * float(model.speckle_amount),
        "roughness_stream": "independent PCG64 sub-stream drawn from the pattern generator",
        "measured_blotch_roughness_correlation": correlation,
        "gray_scott": {"status": "NOT_IMPLEMENTED_OPTIONAL",
                       "reason": "plan 9.5 keeps Gray-Scott optional; multi-scale continuous "
                                 "blotch field is the core implementation"},
        "geometry": "NONE: kiln transformation changes appearance only",
    })
    return p


# ---------------------------------------------------------------------------------------
# PAT14 relief
# ---------------------------------------------------------------------------------------
def build_relief(model: ReliefParams, ctx: BuildContext) -> dict[str, Any]:
    motif = str(model.motif)
    feather = float(model.mask_feather_mm)
    p = ctx.base_params(line_width_mm=float(model.line_width_mm))
    p.update({
        "motif": motif, "height_mm": float(model.height_mm), "power": float(model.power),
        "mask_feather_mm": feather, "threshold": float(model.threshold),
        "paint_index": None,
    })
    declared_thickness = None
    if isinstance(ctx.mother.meta, dict):
        declared_thickness = ctx.mother.meta.get("min_wall_thickness_mm")
    if declared_thickness is None and isinstance(ctx.mother.params, dict):
        declared_thickness = ctx.mother.params.get("min_wall_thickness_mm")
    if declared_thickness:
        allowed = float(model.max_wall_fraction) * float(declared_thickness)
        p["wall_guard"] = {
            "declared_min_wall_mm": float(declared_thickness),
            "max_wall_fraction": float(model.max_wall_fraction),
            "allowed_amplitude_mm": float(allowed),
            "requested_amplitude_mm": float(model.height_mm),
            "feasible": bool(float(model.height_mm) <= allowed),
            "checked_at": "apply_pattern_geometry performs the hard rejection; this entry warns",
        }
    if motif == "blobs":
        blotch = sample_fourier_basis(ctx.sub_rng("relief-blobs"), x_period_mm=ctx.x_period_mm,
                                      base_wavelength_mm=float(model.base_wavelength_mm),
                                      n_bands=int(model.n_scales), components_per_band=1,
                                      angle_spread_deg=70.0)
        normalize_basis_on_samples(blotch, ctx)
        plan = plan_raster(x_period_mm=ctx.x_period_mm, s_min_mm=ctx.s_min_mm, s_max_mm=ctx.s_max_mm,
                           feature_mm=max(0.4, feather / 4.0), max_pixels=MAX_RASTER_PIXELS)
        height_px, width_px = int(plan["height_px"]), int(plan["width_px"])
        xs = (np.arange(width_px) + 0.5) / plan["px_per_mm"]
        ss = ctx.s_min_mm + (np.arange(height_px) + 0.5) / plan["px_per_mm"]
        gx, gs = np.meshgrid(xs, ss, indexing="xy")
        field = blotch.value(gx.reshape(-1), gs.reshape(-1), ctx.x_period_mm).reshape(height_px, width_px)
        binary = (field >= float(model.threshold)).astype(np.float64)
        # border wide enough that the signed distance is never truncated at the tile
        # edge (2*feather covers the whole smoothstep transition plus margin)
        pad = int(math.ceil(2.0 * feather * plan["px_per_mm"])) + 4
        padded = np.pad(binary, ((0, 0), (pad, pad)), mode="wrap")
        rd, edt_report = signed_distance_layers(padded, px_per_mm=float(plan["px_per_mm"]), pad_px=pad)
        mask = _smoothstep_array(-feather, feather, -rd)
        tile = _tile_from_canvases(plan=plan, ctx=ctx, cov=mask,
                                   meta={"family": "PAT14", "plan": plan, "edt": edt_report,
                                         "mask_source": "smoothstep(-feather, +feather, signed "
                                                        "EDT distance to the thresholded blotches)"})
        p["raster"] = tile.to_payload()
        p["blotch"] = blotch.as_dict()
        p["mask_area_fraction"] = float((mask > 0.5).mean())
        p["raster_plan"] = plan
        p["edt"] = edt_report
        p["mask_source"] = ("thresholded Fourier blotches -> SciPy EDT signed distance -> "
                            "smoothstep feather in millimetres")
        p["s_boundary_note"] = ("the profile axis is not periodic for the EDT; the legal region "
                                "weight feathers the s boundary")
    elif motif == "bands":
        period = max(2.0 * feather, float(model.band_width_mm) + 8.0)
        p.update({"period_mm": float(period), "band_width_mm": float(model.band_width_mm),
                  "phase_s_mm": float(ctx.rng.uniform(0.0, period)),
                  "ripple": None})
        if ctx.complexity >= 2:
            ripple = sample_fourier_basis(ctx.sub_rng("relief-ripple"), x_period_mm=ctx.x_period_mm,
                                          base_wavelength_mm=float(model.base_wavelength_mm),
                                          n_bands=2, components_per_band=1)
            normalize_basis_on_samples(ripple, ctx)
            p["ripple"] = ripple.as_dict()
        p["mask_source"] = "analytic band mask in profile arc length with millimetre feather"
    elif motif == "medallion":
        count = max(1, int(model.medallion_count))
        radius = float(model.base_wavelength_mm) * 0.35
        phase = float(ctx.rng.uniform(0.0, 1.0))
        centres = [[float(((i + 0.5) / count + phase) % 1.0 * ctx.x_period_mm),
                    0.5 * (ctx.s_min_mm + ctx.s_max_mm)] for i in range(count)]
        p.update({"medallion_centres": centres, "medallion_radius_mm": float(radius),
                  "ring_width_mm": (float(model.line_width_mm) if ctx.complexity >= 2 else 0.0),
                  "mask_source": "analytic periodic disc / ring mask"})
    elif motif == "panel_lattice":
        n_int = max(1, int(ctx.x_period_mm / max(float(model.base_wavelength_mm), 1.0)))
        p.update({"n_int": int(n_int),
                  "period_s_mm": float(model.band_width_mm) + float(model.base_wavelength_mm),
                  "phase_s_mm": float(ctx.rng.uniform(0.0, model.base_wavelength_mm)),
                  "mask_source": "analytic periodic raised panel lattice"})
    return p


def _smoothstep_array(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / max(edge1 - edge0, 1e-12), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def signed_distance_layers(mask: np.ndarray, *, px_per_mm: float,
                           pad_px: int) -> tuple[np.ndarray, dict[str, Any]]:
    """Signed EDT distance (mm) on a wrapped canvas, cropped back to the tile."""
    from scipy.ndimage import distance_transform_edt

    inside = np.asarray(mask) > 0.5
    sampling = (1.0 / px_per_mm, 1.0 / px_per_mm)
    d_out = distance_transform_edt(~inside, sampling=sampling)
    d_in = distance_transform_edt(inside, sampling=sampling)
    signed = d_out - d_in
    cropped = signed[:, pad_px:signed.shape[1] - pad_px]
    return cropped, {
        "kernel": "scipy.ndimage.distance_transform_edt", "passes": 2,
        "pixel_scale_mm": float(1.0 / px_per_mm), "pad_px": int(pad_px),
        "sign_convention": "positive inside the mask",
        "wrap": "x copies drawn into the padded canvas before the transform",
    }


# ---------------------------------------------------------------------------------------
# PAT15 engraving
# ---------------------------------------------------------------------------------------
def build_engrave(model: EngraveParams, ctx: BuildContext) -> dict[str, Any]:
    family = str(model.curve_family)
    depth = float(model.depth_mm)
    width = float(model.line_width_mm)
    p = ctx.base_params(line_width_mm=width)
    p.update({
        "depth_mm": depth, "line_width_mm": width, "curve_family": family,
        "paint_index": 0, "crossing_policy": "max_not_sum",
        "crossing_note": "overlapping grooves take the maximum depth, they never sum",
        "mode": "analytic",
    })
    if family == "stripe":
        p["groups"] = [_stripe_group(ctx, theta_deg=0.0, spacing_mm=float(model.spacing_mm),
                                     width_mm=width, paint_index=0, phase_turns=0.0)]
    elif family == "grid":
        p["groups"] = [
            _stripe_group(ctx, theta_deg=0.0, spacing_mm=float(model.spacing_mm), width_mm=width,
                          paint_index=0, phase_turns=0.0),
            _stripe_group(ctx, theta_deg=90.0, spacing_mm=float(model.spacing_mm), width_mm=width,
                          paint_index=1, phase_turns=0.0),
        ]
    else:
        sub_ctx_params = dict(model.curve_params)
        if family == "wave":
            sub_model = WaveParams(**{"line_width_mm": width,
                                      "spacing_mm": float(model.spacing_mm),
                                      **sub_ctx_params})
            got = build_wave(sub_model, ctx)
        else:
            sub_model = MeanderParams(**{"line_width_mm": width,
                                         "spacing_mm": float(model.spacing_mm),
                                         **sub_ctx_params})
            got = build_meander(sub_model, ctx)
        p["mode"] = "raster"
        p["raster"] = got["raster"]
        p["sub_family_params"] = {k: v for k, v in got.items()
                                  if k in ("n_waves", "wavelength_achieved_mm", "n_tiles_around",
                                           "tile_w_achieved_mm", "raster_plan", "distance_validation",
                                           "endpoint_mismatch_mm", "rows")}
    area = float(ctx.region.get("area_mm2", 0.0))
    removed_estimate = depth * width * area / max(width + float(model.spacing_mm), 1e-9)
    p["removed_volume_estimate_mm3"] = float(removed_estimate)
    p["groove_area_fraction_estimate"] = float(width / max(width + float(model.spacing_mm), 1e-9))
    return p


# ---------------------------------------------------------------------------------------
# PAT16 combination
# ---------------------------------------------------------------------------------------
def build_combo(model: ComboParams, ctx: BuildContext) -> dict[str, Any]:
    layers = [dict(layer.model_dump()) for layer in model.layers]
    if not layers:
        layers = [{"family": "PAT03", "params": {}, "zone": "full", "weight": 1.0},
                  {"family": "AUX_TINT", "params": {}, "zone": "full", "weight": 1.0}]
        if ctx.complexity >= 2:
            layers.append({"family": "AUX_BAND", "params": {}, "zone": "full", "weight": 1.0})
    if len(layers) > 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "PAT16 allows one primary and at most two auxiliary layers",
                          stage="patterns.builders.build_combo")
    geometry_layer = None
    frozen_layers = []
    common = {"complexity": int(ctx.complexity), "line_width_mm": float(model.line_width_mm),
              "spacing_mm": float(model.spacing_mm)}
    for index, layer in enumerate(layers):
        family = str(layer["family"]).upper()
        params = dict(layer.get("params") or {})
        if family in ("PAT14", "PAT15"):
            if not bool(model.allow_geometry):
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  "PAT16 geometry layers require allow_geometry=True",
                                  stage="patterns.builders.build_combo")
            if geometry_layer is not None:
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  "PAT16 allows at most one geometric layer",
                                  stage="patterns.builders.build_combo")
            geometry_layer = index
        if family.startswith("AUX_"):
            aux = build_aux_layer(family, ctx, rng=ctx.sub_rng(f"combo-{family}-{index}"))
            aux.update({k: v for k, v in params.items() if k in aux})
            frozen = {**aux, **params}
            frozen["family"] = family
            frozen.setdefault("complexity", int(ctx.complexity))
            frozen.setdefault("footprint_mm", float(ctx.footprint_mm))
        else:
            frozen = freeze_family(family, {**common, **params}, ctx)
        frozen_layers.append({"family": family, "params": frozen,
                              "zone": str(layer.get("zone", "full")),
                              "zone_params": _zone_params(model, ctx, index),
                              "weight": float(layer.get("weight", 1.0))})
    p = ctx.base_params()
    primary_width = float((frozen_layers[0]["params"] or {}).get("line_width_mm",
                                                                model.line_width_mm))
    p.update({
        "layers": frozen_layers, "geometry_layer": geometry_layer,
        "primary_line_width_mm": primary_width,
        "mix_order": str(model.mix_order), "boundary": str(model.boundary),
        "boundary_width_mm": float(model.boundary_width_mm),
        "boundary_feather_mm": float(model.boundary_feather_mm),
        "allow_geometry": bool(model.allow_geometry),
    })
    return p


def _zone_params(model: ComboParams, ctx: BuildContext, index: int) -> dict[str, Any]:
    """Zone parameters for a PAT16 layer.

    The primary layer (index 0) covers the whole legal region; auxiliary layers receive
    the deliberate boundary zone, so the boundary separates "primary only" from
    "primary + auxiliary" areas instead of blanking the whole region.
    """
    if index == 0:
        return {}
    if str(model.boundary) == "periodic_curve":
        n_int = max(1, int(ctx.x_period_mm / max(float(model.boundary_width_mm), 4.0)))
        return {"kind": "periodic_curve", "n_int": int(n_int),
                "amplitude_mm": 0.25 * ctx.frame.s_span_mm,
                "phase": float(ctx.rng.uniform(0.0, TWO_PI)),
                "feather_mm": float(model.boundary_feather_mm)}
    if str(model.boundary) == "vertical_band":
        return {"kind": "vertical_band", "width_mm": float(model.boundary_width_mm),
                "feather_mm": float(model.boundary_feather_mm)}
    return {"kind": "horizontal_band", "width_mm": float(model.boundary_width_mm),
            "feather_mm": float(model.boundary_feather_mm)}


# ---------------------------------------------------------------------------------------
# auxiliary appearance layers
# ---------------------------------------------------------------------------------------
def build_aux_layer(kind: str, ctx: BuildContext, *, rng: np.random.Generator) -> dict[str, Any]:
    base = ctx.base_params()
    base["family"] = kind
    if kind == "AUX_TINT":
        basis = sample_fourier_basis(rng, x_period_mm=ctx.x_period_mm,
                                     base_wavelength_mm=max(30.0, ctx.frame.s_span_mm),
                                     n_bands=2, components_per_band=1, angle_spread_deg=40.0)
        normalize_basis_on_samples(basis, ctx)
        base.update({"basis": basis.as_dict(), "alpha": float(rng.uniform(0.08, 0.22)),
                     "paint_index": int(rng.integers(0, max(1, ctx.palette_paints().shape[0]))),
                     "kind": kind,
                     "blend": "low-frequency colour wash over the primary layer"})
    elif kind == "AUX_SPECKLE":
        basis = sample_fourier_basis(rng, x_period_mm=ctx.x_period_mm, base_wavelength_mm=0.9,
                                     n_bands=1, components_per_band=6, angle_spread_deg=90.0)
        normalize_basis_on_samples(basis, ctx)
        base.update({"basis": basis.as_dict(), "alpha": float(rng.uniform(0.05, 0.15)),
                     "paint_index": 0, "roughness_delta": float(rng.uniform(0.04, 0.12)),
                     "kind": kind, "blend": "fine speckle on albedo and roughness only"})
    elif kind == "AUX_BAND":
        width = float(ctx.line_width_mm) * 2.0
        period = width + float(rng.uniform(12.0, 25.0))
        base.update({"period_mm": float(period), "width_mm": width,
                     "phase_s_mm": float(rng.uniform(0.0, period)),
                     "alpha": float(rng.uniform(0.15, 0.35)),
                     "paint_index": 1, "kind": kind,
                     "blend": "single faint circumferential band"})
    else:  # pragma: no cover - guarded by caller
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown auxiliary layer {kind!r}",
                          stage="patterns.builders.build_aux_layer")
    return base


# ---------------------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------------------
FAMILY_BUILDERS: dict[str, Callable[[Any, BuildContext], dict[str, Any]]] = {
    "PAT01": build_plain, "PAT02": build_band, "PAT03": build_stripe, "PAT04": build_grid,
    "PAT05": build_wave, "PAT06": build_dots, "PAT07": build_triangle, "PAT08": build_meander,
    "PAT09": build_crosshatch, "PAT10": build_leaf, "PAT11": build_symbol, "PAT12": build_glyph,
    "PAT13": build_kiln, "PAT14": build_relief, "PAT15": build_engrave, "PAT16": build_combo,
}


def freeze_family(family_id: str, params: dict[str, Any] | BaseFamilyParams,
                  ctx: BuildContext) -> dict[str, Any]:
    """Validate parameters through the pydantic model, then freeze coefficients once."""
    from .params import validate_family_params

    if family_id not in FAMILY_BUILDERS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"no builder for pattern family {family_id!r}",
                          stage="patterns.builders.freeze_family")
    payload: dict[str, Any]
    if isinstance(params, BaseFamilyParams):
        payload = params.model_dump()
        payload["complexity"] = int(ctx.complexity)
    else:
        payload = {"complexity": int(ctx.complexity), "line_width_mm": float(ctx.line_width_mm),
                   **dict(params or {})}
    model = validate_family_params(family_id, payload)
    return FAMILY_BUILDERS[family_id](model, ctx)


def field_context(recipe_meta: dict[str, Any], palette_payload: dict[str, Any],
                  warp: WarpField) -> FieldContext:
    regions = recipe_meta.get("regions") or [{}]
    region = regions[0]
    return FieldContext(
        x_period_mm=float(recipe_meta["chart"]["x_period_mm"]),
        s_min_mm=float(region.get("s_min_mm", 0.0)),
        s_max_mm=float(region.get("s_max_mm", 1.0)),
        s_periodic=bool(recipe_meta["chart"].get("s_periodic", False)),
        footprint_mm=float(recipe_meta["footprint_mm"]),
        body=np.asarray(palette_payload["body"], dtype=np.float64),
        body_roughness=float(palette_payload["body_roughness"]),
        paints=np.asarray(palette_payload["paints"], dtype=np.float64),
        paint_roughness=float(palette_payload["paint_roughness"]),
        warp=warp,
    )
