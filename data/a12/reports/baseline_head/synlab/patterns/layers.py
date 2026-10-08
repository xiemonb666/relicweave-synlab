"""Frozen pattern fields for PAT01..PAT16 (evaluation side, plan 9.3).

Every class here converts a *frozen* parameter dictionary (JSON-safe, produced once by
``synlab.patterns.builders``) into channel values.  Nothing in this module draws
randomness: ``process`` is a pure function of ``(x_mm, s_mm, context)``, so a fragment
querying the mother field gets exactly the value the original ornament had.

Channel contract
----------------
``coverage``   paint coverage in [0,1] (the frozen line-alpha of plan 9.3)
``paint``      linear albedo of the paint at that point
``roughness``  roughness of the painted surface
``height_mm``  **real** signed geometric displacement (only PAT14/PAT15/PAT16-restricted)
``modulation`` scalar used for measured spectra / width audits (never rendered)
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable

import numpy as np

from ..errors import ErrorCode, SynLabError
from .fields import FourierBasis, WarpField, line_alpha, smoothstep
from .raster import RasterTile, raster_from_payload
from .spatial import distance_to_points, distance_to_segments, nearest_neighbour_distance
from .symbols import SymbolShape, contains_xy, outline_polygons

TWO_PI = 2.0 * np.pi


# ---------------------------------------------------------------------------------------
# shared context / output
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class FieldContext:
    x_period_mm: float
    s_min_mm: float
    s_max_mm: float
    s_periodic: bool
    footprint_mm: float
    body: np.ndarray
    body_roughness: float
    paints: np.ndarray
    paint_roughness: float
    warp: WarpField

    @property
    def s_span_mm(self) -> float:
        return float(self.s_max_mm - self.s_min_mm)


@dataclass
class FieldOut:
    coverage: np.ndarray
    paint: np.ndarray
    roughness: np.ndarray
    height_mm: np.ndarray
    modulation: np.ndarray

    @classmethod
    def empty(cls, n: int, ctx: FieldContext) -> "FieldOut":
        return cls(coverage=np.zeros(n), paint=np.tile(ctx.body, (n, 1)),
                   roughness=np.full(n, ctx.body_roughness), height_mm=np.zeros(n),
                   modulation=np.zeros(n))


def _mix(a: np.ndarray, b: np.ndarray, t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)[:, None]
    return a * (1.0 - t) + b * t


def _mix_scalar(a: np.ndarray, b: np.ndarray, t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return a * (1.0 - t) + b * t


def _paint(ctx: FieldContext, index: int) -> np.ndarray:
    paints = ctx.paints
    if paints.shape[0] == 0:
        return ctx.body
    return paints[int(index) % paints.shape[0]]


def _paint_from_tile(rgb: np.ndarray, weight: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """Blend the frozen tile colour with the palette fallback *continuously*.

    A hard ``sum(rgb) < 1e-6`` test flips the albedo by the full paint/body contrast
    wherever the sampled rgb crosses zero - a value discontinuity inside a single texel,
    which shows up as a non-physical cusp in the seam derivative.  ``weight`` is the tile's
    own coverage layer (where the tile really stores a paint colour), so the blend is
    continuous and equals the fallback exactly where the tile is empty.
    """
    w = np.clip(np.asarray(weight, dtype=np.float64), 0.0, 1.0)[:, None]
    return np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0) * w + fallback * (1.0 - w)


_TILE_CACHE: dict[str, RasterTile] = {}
_TILE_CACHE_LIMIT = 24


def decode_tile(payload: dict[str, Any]) -> RasterTile:
    """Decode a frozen raster payload with a bounded cache (pure, deterministic)."""
    key = hashlib.sha256(
        (str(payload.get("rgb_png_b64", "")) + "|" + str(payload.get("aux_png_b64", ""))
         + "|" + str(payload.get("shape"))).encode("ascii")
    ).hexdigest()
    tile = _TILE_CACHE.get(key)
    if tile is None:
        tile = raster_from_payload(payload)
        if len(_TILE_CACHE) >= _TILE_CACHE_LIMIT:
            _TILE_CACHE.pop(next(iter(_TILE_CACHE)))
        _TILE_CACHE[key] = tile
    return tile


def _phase_turns(k_int: int, x_mm: np.ndarray, x_period_mm: float) -> np.ndarray:
    """``k*u`` folded onto [0,1): identical at u=0 and u=1 for integer k."""
    return np.mod(int(k_int) * (np.asarray(x_mm, dtype=np.float64) / float(x_period_mm)), 1.0)


def _stripe_geometry(x: np.ndarray, s: np.ndarray, *, x_period_mm: float, n_int: int,
                     tan_theta: float) -> tuple[np.ndarray, float]:
    """Phase of a stripe set whose lines make angle theta with the profile axis.

    ``phi = n_int*x/C - (n_int/C)*tan(theta)*s`` with integer ``n_int``, so the phase is
    exactly periodic in ``x``.  The gradient norm ``|grad phi|`` is constant, hence the
    perpendicular line spacing is exactly ``1/|grad phi|`` in chart millimetres.
    """
    a = float(n_int) / float(x_period_mm)
    phi = a * np.asarray(x, dtype=np.float64) - a * float(tan_theta) * np.asarray(s, dtype=np.float64)
    grad = a * math.sqrt(1.0 + float(tan_theta) ** 2)
    return phi, grad


def _stripe_distance(phi: np.ndarray, grad: float) -> np.ndarray:
    return np.abs(phi - np.round(phi)) / max(grad, 1e-12)


class BaseField:
    family_id: str = ""
    height_mode: str = "none"

    def __init__(self, params: dict[str, Any]) -> None:
        self.p = dict(params)

    # ------------------------------------------------------------------ interface
    def process(self, x_mm: np.ndarray, s_mm: np.ndarray, ctx: FieldContext) -> FieldOut:
        x = np.asarray(x_mm, dtype=np.float64)
        s = np.asarray(s_mm, dtype=np.float64)
        if ctx.warp.enabled:
            x, s = ctx.warp.apply(x, s, ctx.x_period_mm)
        return self._process(x, s, ctx)

    def _process(self, x: np.ndarray, s: np.ndarray, ctx: FieldContext) -> FieldOut:  # pragma: no cover
        raise NotImplementedError

    # ------------------------------------------------------------------ helpers
    @property
    def footprint_mm(self) -> float:
        return float(self.p.get("footprint_mm", 0.1))

    def line_width_mm(self) -> float:
        return float(self.p.get("line_width_mm", 1.0))


# ---------------------------------------------------------------------------------------
# PAT01 plain
# ---------------------------------------------------------------------------------------
class PlainField(BaseField):
    """常色 + optional low-frequency colour field (no motif)."""

    family_id = "PAT01"

    def _process(self, x, s, ctx):
        n = x.shape[0]
        basis = self.p.get("basis")
        paint = np.tile(np.asarray(self.p["base_color"], dtype=np.float64), (n, 1))
        coverage = np.ones(n)
        roughness = np.full(n, float(self.p["base_roughness"]))
        modulation = np.zeros(n)
        if basis:
            field = FourierBasis.from_dict(basis).value(x, s, ctx.x_period_mm)
            amount = float(self.p["color_amount"])
            t = np.clip(amount * 0.5 * (1.0 + field), 0.0, 1.0)
            paint = _mix(paint, _paint(ctx, 0)[None, :], t)
            modulation = field
        rough_basis = self.p.get("roughness_basis")
        if rough_basis:
            variation = float(self.p["roughness_variation"])
            roughness = np.clip(roughness + variation
                                * FourierBasis.from_dict(rough_basis).value(x, s, ctx.x_period_mm),
                                0.0, 1.0)
        return FieldOut(coverage=coverage, paint=paint, roughness=roughness,
                        height_mm=np.zeros(n), modulation=modulation)


# ---------------------------------------------------------------------------------------
# PAT02 circumferential bands
# ---------------------------------------------------------------------------------------
class BandField(BaseField):
    """环带: distance to periodic centre lines in the profile arc length ``s_mm``."""

    family_id = "PAT02"

    def _process(self, x, s, ctx):
        n = x.shape[0]
        period = float(self.p["period_mm"])
        phase = float(self.p["phase_s_mm"])
        pair_gap = float(self.p.get("pair_gap_mm", 0.0))
        delta = np.abs(np.mod(s - phase + 0.5 * period, period) - 0.5 * period)
        if pair_gap > 0:
            d2 = np.abs(np.mod(s - phase - pair_gap + 0.5 * period, period) - 0.5 * period)
            delta = np.minimum(delta, d2)
        width = float(self.p["band_width_mm"])
        if float(self.p.get("width_ratio", 1.0)) != 1.0:
            parity = np.floor((s - phase) / period).astype(np.int64) % 2
            width_arr = np.where(parity == 0, width, width * float(self.p["width_ratio"]))
        else:
            width_arr = np.full(n, width)
        alpha = line_alpha(delta, width_arr, self.footprint_mm)
        paint = np.tile(_paint(ctx, int(self.p.get("paint_index", 0))), (n, 1))
        rough = np.full(n, float(self.p.get("paint_roughness", ctx.paint_roughness)))
        return FieldOut(coverage=alpha, paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=alpha)


# ---------------------------------------------------------------------------------------
# PAT03 stripes
# ---------------------------------------------------------------------------------------
class StripeField(BaseField):
    """条纹: linear phase distance with an integer azimuthal frequency."""

    family_id = "PAT03"

    def _groups(self):
        return list(self.p.get("groups", []))

    def _process(self, x, s, ctx):
        n = x.shape[0]
        coverage = np.zeros(n)
        paint = np.tile(ctx.body, (n, 1))
        rough = np.full(n, ctx.body_roughness)
        for group in self._groups():
            phi, grad = _stripe_geometry(x, s, x_period_mm=ctx.x_period_mm,
                                         n_int=int(group["n_int"]),
                                         tan_theta=float(group["tan_theta"]))
            phi = phi + float(group.get("phase_turns", 0.0))
            dist = _stripe_distance(phi, grad)
            width = float(group["width_mm"])
            if float(group.get("thin_ratio", 1.0)) != 1.0:
                parity = np.floor(phi).astype(np.int64) % 2
                width = np.where(parity == 0, width, width * float(group["thin_ratio"]))
            alpha = line_alpha(dist, width, self.footprint_mm)
            colour = _paint(ctx, int(group.get("paint_index", 0)))
            take = alpha >= coverage
            paint = np.where(take[:, None], np.tile(colour, (n, 1)), paint)
            rough = np.where(take, float(group.get("paint_roughness", ctx.paint_roughness)), rough)
            coverage = np.maximum(coverage, alpha)
        return FieldOut(coverage=coverage, paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=coverage)


# ---------------------------------------------------------------------------------------
# PAT04 grid
# ---------------------------------------------------------------------------------------
class GridField(BaseField):
    """格网: two (or three) stripe sets combined by union / intersection."""

    family_id = "PAT04"

    def _sets(self):
        return list(self.p.get("sets", []))

    def _process(self, x, s, ctx):
        n = x.shape[0]
        mode = str(self.p.get("mode", "union"))
        order = str(self.p.get("order", "a_then_b"))
        alphas = []
        for entry in self._sets():
            phi, grad = _stripe_geometry(x, s, x_period_mm=ctx.x_period_mm,
                                         n_int=int(entry["n_int"]),
                                         tan_theta=float(entry["tan_theta"]))
            alphas.append(line_alpha(_stripe_distance(phi, grad), float(entry["width_mm"]),
                                     self.footprint_mm))
        if not alphas:
            return FieldOut.empty(n, ctx)
        combined = alphas[0]
        for extra in alphas[1:]:
            combined = (np.maximum(combined, extra) if mode == "union"
                        else np.minimum(combined, extra))
        paint = np.tile(ctx.body, (n, 1))
        rough = np.full(n, ctx.body_roughness)
        order_sets = self._sets() if order == "a_then_b" else list(reversed(self._sets()))
        order_alphas = alphas if order == "a_then_b" else list(reversed(alphas))
        for entry, alpha in zip(order_sets, order_alphas):
            take = alpha > 0.5
            colour = _paint(ctx, int(entry.get("paint_index", 0)))
            paint = np.where(take[:, None], np.tile(colour, (n, 1)), paint)
            rough = np.where(take, float(entry.get("paint_roughness", ctx.paint_roughness)), rough)
        return FieldOut(coverage=combined, paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=combined)


# ---------------------------------------------------------------------------------------
# PAT05 waves (raster distance of the frozen centre line)
# ---------------------------------------------------------------------------------------
class RasterStrokeField(BaseField):
    """Frozen raster stroke set: ``dist`` layer + line alpha, optional fill coverage."""

    def _tile(self) -> RasterTile:
        if not hasattr(self, "_tile_obj"):
            self._tile_obj = decode_tile(self.p["raster"])
        return self._tile_obj

    def _process(self, x, s, ctx):
        n = x.shape[0]
        tile = self._tile()
        names = ["cov", "rgb_r", "rgb_g", "rgb_b"]
        scales: dict[str, float] = {"dist": float(tile.meta.get("dist_scale_mm", 1.0))}
        if "dist" in tile.layers:
            names.insert(0, "dist")
        got = tile.sample(x, s, names, scales=scales)
        coverage = np.clip(got["cov"], 0.0, 1.0)
        if "dist" in got:
            alpha = line_alpha(got["dist"], self.line_width_mm(), self.footprint_mm)
            coverage = np.maximum(coverage, alpha)
        paint = np.stack([got["rgb_r"], got["rgb_g"], got["rgb_b"]], axis=1)
        fallback = np.tile(_paint(ctx, int(self.p.get("paint_index", 0))), (n, 1))
        paint = _paint_from_tile(paint, got["cov"], fallback)
        rough = np.full(n, float(self.p.get("paint_roughness", ctx.paint_roughness)))
        return FieldOut(coverage=coverage, paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=coverage)


class WaveField(RasterStrokeField):
    """波浪: sine or Bezier centre line at an integer number of waves."""

    family_id = "PAT05"


# ---------------------------------------------------------------------------------------
# PAT06 dots
# ---------------------------------------------------------------------------------------
class DotField(BaseField):
    """点阵: lattice or periodic Poisson disk, evaluated from the frozen dot set."""

    family_id = "PAT06"

    def _dots(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if not hasattr(self, "_dot_arrays"):
            rows = np.asarray(self.p["dots"], dtype=np.float64).reshape(-1, 3)
            self._dot_arrays = (rows[:, :2], rows[:, 2], rows)
        return self._dot_arrays

    def _process(self, x, s, ctx):
        n = x.shape[0]
        centres, radii, rows = self._dots()
        if centres.shape[0] == 0:
            return FieldOut.empty(n, ctx)
        from scipy.spatial import cKDTree

        tree = getattr(self, "_dot_tree", None)
        if tree is None or float(getattr(self, "_dot_period", -1.0)) != float(ctx.x_period_mm):
            copies = np.vstack([centres, centres + np.array([ctx.x_period_mm, 0.0]),
                                centres - np.array([ctx.x_period_mm, 0.0])])
            self._dot_tree = cKDTree(copies)
            self._dot_radii = np.tile(radii, 3)
            self._dot_period = float(ctx.x_period_mm)
            tree = self._dot_tree
        dist, index = tree.query(np.stack([x, s], axis=1), k=1)
        radius_here = self._dot_radii[np.asarray(index, dtype=np.int64)]
        if bool(self.p.get("solid", True)):
            alpha = 1.0 - smoothstep(radius_here - self.footprint_mm,
                                     radius_here + self.footprint_mm, dist)
        else:
            ring = float(self.p.get("ring_ratio", 0.5)) * radius_here
            alpha = (smoothstep(radius_here - ring - self.footprint_mm,
                                radius_here - ring + self.footprint_mm, dist)
                     * (1.0 - smoothstep(radius_here - self.footprint_mm,
                                         radius_here + self.footprint_mm, dist)))
        del rows
        paint = np.tile(_paint(ctx, int(self.p.get("paint_index", 0))), (n, 1))
        rough = np.full(n, float(self.p.get("paint_roughness", ctx.paint_roughness)))
        return FieldOut(coverage=alpha, paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=alpha)


# ---------------------------------------------------------------------------------------
# PAT07 triangles
# ---------------------------------------------------------------------------------------
class TriangleField(RasterStrokeField):
    """三角: periodic triangular tile (line lattice or solid barycentric fill)."""

    family_id = "PAT07"


# ---------------------------------------------------------------------------------------
# PAT08 meander
# ---------------------------------------------------------------------------------------
class MeanderField(RasterStrokeField):
    """回纹: periodic meander polyline with connected tile endpoints."""

    family_id = "PAT08"


# ---------------------------------------------------------------------------------------
# PAT09 crosshatch
# ---------------------------------------------------------------------------------------
class CrosshatchField(BaseField):
    """交叉线: 2-3 line fields, layered with an explicit order and missing strokes."""

    family_id = "PAT09"

    def _process(self, x, s, ctx):
        n = x.shape[0]
        groups = list(self.p.get("groups", []))
        coverage = np.zeros(n)
        paint = np.tile(ctx.body, (n, 1))
        rough = np.full(n, ctx.body_roughness)
        order = str(self.p.get("mix_order", "a_then_b"))
        seq = groups if order == "a_then_b" else list(reversed(groups))
        for group in seq:
            phi, grad = _stripe_geometry(x, s, x_period_mm=ctx.x_period_mm,
                                         n_int=int(group["n_int"]),
                                         tan_theta=float(group["tan_theta"]))
            phi = phi + float(group.get("phase_turns", 0.0))
            index = np.floor(phi).astype(np.int64)
            flags = group.get("kept_lookup")
            if flags:
                table = np.asarray(flags, dtype=np.float64)
                offset = int(group["lookup_offset"])
                table_index = np.clip(index - offset, 0, table.shape[0] - 1)
                present = table[table_index] > 0.5
            else:
                present = np.ones(n, dtype=bool)
            alpha = line_alpha(_stripe_distance(phi, grad), float(group["width_mm"]),
                               self.footprint_mm) * present
            colour = _paint(ctx, int(group.get("paint_index", 0)))
            take = alpha >= coverage
            paint = np.where(take[:, None], np.tile(colour, (n, 1)), paint)
            rough = np.where(take, float(group.get("paint_roughness", ctx.paint_roughness)), rough)
            coverage = np.maximum(coverage, alpha)
        return FieldOut(coverage=coverage, paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=coverage)


# ---------------------------------------------------------------------------------------
# PAT10 floral
# ---------------------------------------------------------------------------------------
class LeafField(RasterStrokeField):
    """花叶: bounded L-system stems plus Bezier leaf outlines."""

    family_id = "PAT10"


# ---------------------------------------------------------------------------------------
# PAT11 medallion (analytic polygons + Shapely containment)
# ---------------------------------------------------------------------------------------
class SymbolField(BaseField):
    """局部徽记: programmatic vector symbol or restricted SVG path, analytic evaluation."""

    family_id = "PAT11"

    def _shape(self) -> SymbolShape:
        if not hasattr(self, "_shape_obj"):
            self._shape_obj = SymbolShape.from_payload(self.p["shape"])
        return self._shape_obj

    def _process(self, x, s, ctx):
        n = x.shape[0]
        shape = self._shape()
        polygons = outline_polygons(shape)
        stroke_on = bool(self.p.get("stroke", True))
        fill_on = bool(self.p.get("fill", False))
        width = float(self.p.get("stroke_width_mm", self.line_width_mm()))
        coverage = np.zeros(n)
        extents = [float(np.abs(o).max()) for o in shape.outlines]
        extent = max(extents) if extents else 1.0
        segments = []
        for outline in shape.outlines:
            segments.append(np.stack([outline[:-1, 0], outline[:-1, 1],
                                      outline[1:, 0], outline[1:, 1]], axis=1))
        for placement in self.p.get("placements", []):
            scale = float(placement["scale"])
            rot = math.radians(float(placement.get("rotate_deg", 0.0)))
            dx = np.mod(x - float(placement["x_mm"]) + 0.5 * ctx.x_period_mm,
                        ctx.x_period_mm) - 0.5 * ctx.x_period_mm
            ds = s - float(placement["s_mm"])
            reach = extent * scale * 1.05 + width + self.footprint_mm
            near = (np.abs(dx) <= reach) & (np.abs(ds) <= reach)
            if not np.any(near):
                continue
            cos_r, sin_r = math.cos(-rot), math.sin(-rot)
            lx = (dx[near] * cos_r - ds[near] * sin_r) / scale
            ly = (dx[near] * cos_r + ds[near] * sin_r) / scale
            local = np.stack([lx, ly], axis=1)
            distance = np.full(local.shape[0], np.inf)
            for seg in segments:
                distance = np.minimum(distance, _segment_distance_local(local, seg))
            distance_mm = distance * scale
            alpha = np.zeros(local.shape[0])
            if fill_on and polygons:
                inside = contains_xy(polygons, lx, ly)
                # signed distance: positive inside the closed outline so that the
                # footprint-wide smoothstep fills the shape and fades at its edge
                signed = np.where(inside, distance_mm, -distance_mm)
                alpha = np.maximum(alpha, smoothstep(-self.footprint_mm, self.footprint_mm, signed))
            if stroke_on:
                alpha = np.maximum(alpha, line_alpha(distance_mm, width, self.footprint_mm))
            coverage[near] = np.maximum(coverage[near], alpha)
        if self.p.get("clear_band"):
            band = self.p["clear_band"]
            half = 0.5 * float(band["width_mm"])
            d = np.abs(np.mod(x - float(band["centre_x_mm"]) + 0.5 * ctx.x_period_mm,
                              ctx.x_period_mm) - 0.5 * ctx.x_period_mm)
            keep = smoothstep(half - float(band.get("feather_mm", 1.0)),
                              half + float(band.get("feather_mm", 1.0)), d)
            coverage = coverage * keep
        connectors = self.p.get("connectors") or []
        if connectors:
            width = float(self.p.get("connector_width_mm", width))
            for polyline in connectors:
                pts = np.asarray(polyline, dtype=np.float64)
                if pts.shape[0] < 2:
                    continue
                seg = np.stack([pts[:-1, 0], pts[:-1, 1], pts[1:, 0], pts[1:, 1]], axis=1)
                d = distance_to_segments(x, s, seg, ctx.x_period_mm)
                coverage = np.maximum(coverage, line_alpha(d, width, self.footprint_mm))
        paint = np.tile(_paint(ctx, int(self.p.get("paint_index", 0))), (n, 1))
        rough = np.full(n, float(self.p.get("paint_roughness", ctx.paint_roughness)))
        return FieldOut(coverage=coverage, paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=coverage)


def _segment_distance_local(points: np.ndarray, segments: np.ndarray) -> np.ndarray:
    """Distance from points to a small local segment set (no periodic copies)."""
    out = np.full(points.shape[0], np.inf)
    if segments.size == 0:
        return out
    p0 = segments[:, 0:2]
    d = segments[:, 2:4] - p0
    denom = np.where((d ** 2).sum(axis=1) > 0, (d ** 2).sum(axis=1), 1.0)
    for start in range(0, points.shape[0], 8192):
        stop = min(start + 8192, points.shape[0])
        q = points[start:stop]
        rel = q[:, None, :] - p0[None, :, :]
        t = np.clip((rel * d[None, :, :]).sum(axis=2) / denom[None, :], 0.0, 1.0)
        closest = p0[None, :, :] + t[:, :, None] * d[None, :, :]
        dist = np.sqrt(((q[:, None, :] - closest) ** 2).sum(axis=2))
        out[start:stop] = dist.min(axis=1)
    return out


# ---------------------------------------------------------------------------------------
# PAT12 glyphs
# ---------------------------------------------------------------------------------------
class GlyphField(RasterStrokeField):
    """字符: one-shot Pillow layout sampled through a frozen raster distance map.

    ``stroke`` selects a stroke centred on the glyph outline (distance layer); otherwise
    the filled glyph coverage layer is used.  Both come from the frozen tile, so a
    fragment never re-lays-out text.
    """

    family_id = "PAT12"

    def _process(self, x, s, ctx):
        n = x.shape[0]
        tile = self._tile()
        names = ["cov", "rgb_r", "rgb_g", "rgb_b"]
        if "dist" in tile.layers:
            names.append("dist")
        got = tile.sample(x, s, names,
                          scales={"dist": float(tile.meta.get("dist_scale_mm", 1.0))})
        coverage = np.zeros(n)
        if bool(self.p.get("fill", True)):
            coverage = np.clip(got["cov"], 0.0, 1.0)
        if bool(self.p.get("stroke", False)) and "dist" in got:
            alpha = line_alpha(got["dist"], float(self.p.get("stroke_width_mm", 1.0)),
                               self.footprint_mm)
            coverage = np.maximum(coverage, alpha)
        paint = np.stack([got["rgb_r"], got["rgb_g"], got["rgb_b"]], axis=1)
        fallback = np.tile(_paint(ctx, int(self.p.get("paint_index", 0))), (n, 1))
        paint = _paint_from_tile(paint, got["cov"], fallback)
        rough = np.full(n, float(self.p.get("paint_roughness", ctx.paint_roughness)))
        return FieldOut(coverage=coverage, paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=coverage)


# ---------------------------------------------------------------------------------------
# PAT13 kiln transformation
# ---------------------------------------------------------------------------------------
class KilnField(BaseField):
    """窑变: multi-scale continuous blotches, separate roughness sub-stream, no geometry."""

    family_id = "PAT13"

    def _process(self, x, s, ctx):
        n = x.shape[0]
        blotch = FourierBasis.from_dict(self.p["blotch"]).value(x, s, ctx.x_period_mm)
        speckle = FourierBasis.from_dict(self.p["speckle"]).value(x, s, ctx.x_period_mm)
        contrast = float(self.p["blotch_contrast"])
        value = np.clip(0.5 + 0.5 * contrast * np.tanh(blotch) + float(self.p["speckle_amount"]) * speckle,
                        0.0, 1.0)
        stops = np.asarray(self.p["colour_stops"], dtype=np.float64)
        paint = _interp_stops(stops, value)
        rough_basis = FourierBasis.from_dict(self.p["roughness"])
        rough = np.clip(float(self.p["roughness_base"])
                        + float(self.p["roughness_coupling"]) * np.tanh(rough_basis.value(x, s, ctx.x_period_mm))
                        + float(self.p["roughness_speckle"]) * speckle, 0.0, 1.0)
        return FieldOut(coverage=np.ones(n), paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=value)


def _interp_stops(stops: np.ndarray, value: np.ndarray) -> np.ndarray:
    """Piecewise-linear colour ramp over the frozen stops (linear albedo)."""
    m = stops.shape[0]
    if m == 1:
        return np.tile(stops[0], (value.shape[0], 1))
    pos = np.clip(value, 0.0, 1.0) * (m - 1)
    lo = np.clip(np.floor(pos).astype(np.int64), 0, m - 2)
    frac = (pos - lo)[:, None]
    return stops[lo] * (1.0 - frac) + stops[lo + 1] * frac


# ---------------------------------------------------------------------------------------
# PAT14 relief
# ---------------------------------------------------------------------------------------
class ReliefField(BaseField):
    """浮雕: smooth mask -> positive height_mm -> displacement of the complete body."""

    family_id = "PAT14"
    height_mode = "relief"

    def _process(self, x, s, ctx):
        n = x.shape[0]
        motif = str(self.p.get("motif", "blobs"))
        if motif == "blobs":
            tile = decode_tile(self.p["raster"])
            mask = np.clip(tile.sample(x, s, ["cov"])["cov"], 0.0, 1.0)
        elif motif == "bands":
            period = float(self.p["period_mm"])
            phase = float(self.p["phase_s_mm"])
            half = 0.5 * float(self.p["band_width_mm"])
            feather = float(self.p["mask_feather_mm"])
            delta = np.abs(np.mod(s - phase + 0.5 * period, period) - 0.5 * period)
            mask = 1.0 - smoothstep(half - feather, half + feather, delta)
            ripple = self.p.get("ripple")
            if ripple:
                basis = FourierBasis.from_dict(ripple)
                mask = np.clip(mask * (0.75 + 0.25 * np.tanh(basis.value(x, s, ctx.x_period_mm))), 0, 1)
        elif motif == "medallion":
            centres = np.asarray(self.p["medallion_centres"], dtype=np.float64)
            radius = float(self.p["medallion_radius_mm"])
            feather = float(self.p["mask_feather_mm"])
            d = distance_to_points(x, s, centres, ctx.x_period_mm)
            mask = 1.0 - smoothstep(radius - feather, radius + feather, d)
            if float(self.p.get("ring_width_mm", 0.0)) > 0:
                ring_w = float(self.p["ring_width_mm"])
                d_ring = distance_to_points(x, s, centres, ctx.x_period_mm)
                mask = np.maximum(mask, line_alpha(np.abs(d_ring - radius * 0.62), ring_w, feather))
        elif motif == "panel_lattice":
            n_int = int(self.p["n_int"])
            period_s = float(self.p["period_s_mm"])
            feather = float(self.p["mask_feather_mm"])
            phi = _phase_turns(n_int, x, ctx.x_period_mm)
            dx = np.minimum(phi, 1.0 - phi) * ctx.x_period_mm / max(n_int, 1)
            ds = np.abs(np.mod(s - float(self.p["phase_s_mm"]) + 0.5 * period_s, period_s) - 0.5 * period_s)
            mask = (1.0 - smoothstep(0.35 * ctx.x_period_mm / n_int - feather,
                                     0.35 * ctx.x_period_mm / n_int + feather, dx)) \
                * (1.0 - smoothstep(0.35 * period_s - feather, 0.35 * period_s + feather, ds))
        else:  # pragma: no cover - guarded by the parameter model
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"unknown relief motif {motif!r}",
                              stage="patterns.layers.ReliefField")
        height = float(self.p["height_mm"]) * np.clip(mask, 0.0, 1.0) ** float(self.p["power"])
        paint_index = self.p.get("paint_index")
        if paint_index is None:
            paint = np.tile(ctx.body, (n, 1))
            rough = np.full(n, ctx.body_roughness)
        else:
            paint = np.tile(_paint(ctx, int(paint_index)), (n, 1))
            rough = np.full(n, float(self.p.get("paint_roughness", ctx.paint_roughness)))
        return FieldOut(coverage=np.clip(mask, 0.0, 1.0), paint=paint, roughness=rough,
                        height_mm=height, modulation=np.clip(mask, 0.0, 1.0))


# ---------------------------------------------------------------------------------------
# PAT15 engraving
# ---------------------------------------------------------------------------------------
class EngraveField(BaseField):
    """刻线: curve distance -> negative height_mm (real material removal)."""

    family_id = "PAT15"
    height_mode = "engrave"

    def _groove_alpha(self, x, s, ctx) -> np.ndarray:
        mode = str(self.p.get("mode", "analytic"))
        width = float(self.p["line_width_mm"])
        if mode == "raster":
            tile = decode_tile(self.p["raster"])
            got = tile.sample(x, s, ["dist"], scales={"dist": float(tile.meta.get("dist_scale_mm", 1.0))})
            return line_alpha(got["dist"], width, self.footprint_mm)
        alpha = np.zeros(x.shape[0])
        for group in self.p.get("groups", []):
            phi, grad = _stripe_geometry(x, s, x_period_mm=ctx.x_period_mm,
                                         n_int=int(group["n_int"]),
                                         tan_theta=float(group["tan_theta"]))
            phi = phi + float(group.get("phase_turns", 0.0))
            alpha = np.maximum(alpha, line_alpha(_stripe_distance(phi, grad),
                                                 float(group.get("width_mm", width)),
                                                 self.footprint_mm))
        return alpha

    def _process(self, x, s, ctx):
        n = x.shape[0]
        alpha = self._groove_alpha(x, s, ctx)
        depth = float(self.p["depth_mm"])
        paint = np.tile(_paint(ctx, int(self.p.get("paint_index", 0))), (n, 1))
        rough = np.full(n, float(self.p.get("paint_roughness", ctx.paint_roughness)))
        return FieldOut(coverage=alpha, paint=paint, roughness=rough,
                        height_mm=-depth * alpha, modulation=alpha)


# ---------------------------------------------------------------------------------------
# PAT16 combination
# ---------------------------------------------------------------------------------------
class ComboField(BaseField):
    """组合: region masks and a bounded composition of the layers above."""

    family_id = "PAT16"

    def _process(self, x, s, ctx):
        n = x.shape[0]
        out = FieldOut.empty(n, ctx)
        layers = list(self.p.get("layers", []))
        if not layers:
            return out
        geometry_index = self.p.get("geometry_layer")
        for index, layer in enumerate(layers):
            sub = build_field(str(layer["family"]), dict(layer["params"]))
            weight = (_zone_weight(str(layer.get("zone", "full")), x, s, ctx,
                                   layer.get("zone_params"))
                      * float(layer.get("weight", 1.0)))
            got = sub._process(x, s, ctx)
            alpha = np.clip(got.coverage * weight, 0.0, 1.0)
            if index == 0:
                out.paint = got.paint
                out.roughness = got.roughness
                out.coverage = alpha
                out.modulation = got.modulation * (weight > 0)
            else:
                out.paint = _mix(out.paint, got.paint, alpha)
                out.roughness = _mix_scalar(out.roughness, got.roughness, alpha)
                out.coverage = np.clip(out.coverage + alpha * (1.0 - out.coverage), 0.0, 1.0)
                out.modulation = np.maximum(out.modulation, got.modulation * (weight > 0))
            if geometry_index is not None and index == int(geometry_index):
                out.height_mm = got.height_mm
        if geometry_index is None:
            out.height_mm = np.zeros(n)
        return out


def _zone_weight(zone: str, x: np.ndarray, s: np.ndarray, ctx: FieldContext,
                 zone_params: dict[str, Any] | None = None) -> np.ndarray:
    """Frozen zone mask; ``full``/``upper``/``lower`` stay constant along the periodic axis."""
    s0, s1 = ctx.s_min_mm, ctx.s_max_mm
    span = max(1e-9, s1 - s0)
    feather = max(0.05 * span, 1e-6)
    t = (s - s0) / span
    params = dict(zone_params or {})
    if zone == "full":
        if str(params.get("kind")) == "horizontal_band":
            width = float(params.get("width_mm", 0.5 * span))
            f = float(params.get("feather_mm", feather))
            d = np.abs(s - 0.5 * (s0 + s1))
            return smoothstep(0.5 * width - f, 0.5 * width + f, d)
        if str(params.get("kind")) == "vertical_band":
            width = float(params.get("width_mm", ctx.x_period_mm / 6.0))
            f = float(params.get("feather_mm", 2.0))
            quarter = ctx.x_period_mm / 4.0
            d1 = np.abs(np.mod(x - quarter + 0.5 * ctx.x_period_mm, ctx.x_period_mm) - 0.5 * ctx.x_period_mm)
            d2 = np.abs(np.mod(x - 3.0 * quarter + 0.5 * ctx.x_period_mm, ctx.x_period_mm)
                        - 0.5 * ctx.x_period_mm)
            return np.maximum(1.0 - smoothstep(0.5 * width - f, 0.5 * width + f, d1),
                              1.0 - smoothstep(0.5 * width - f, 0.5 * width + f, d2))
        if str(params.get("kind")) == "periodic_curve":
            n_int = max(1, int(params.get("n_int", 4)))
            amplitude = float(params.get("amplitude_mm", 0.25 * span))
            f = float(params.get("feather_mm", feather))
            phase = float(params.get("phase", 0.0))
            curve = 0.5 * (s0 + s1) + amplitude * np.sin(
                TWO_PI * n_int * np.asarray(x) / ctx.x_period_mm + phase)
            slope = amplitude * TWO_PI * n_int / ctx.x_period_mm * np.cos(
                TWO_PI * n_int * np.asarray(x) / ctx.x_period_mm + phase)
            signed = (s - curve) / np.sqrt(1.0 + slope ** 2)
            return smoothstep(-f, f, signed)
        return np.ones_like(t)
    if zone == "upper":
        return smoothstep(0.5 - 0.1, 0.5 + 0.1, t)
    if zone == "lower":
        return 1.0 - smoothstep(0.5 - 0.1, 0.5 + 0.1, t)
    if zone == "centre_band":
        d = np.abs(s - 0.5 * (s0 + s1))
        return 1.0 - smoothstep(0.3 * span - feather, 0.3 * span + feather, d)
    if zone == "side_bands":
        quarter = ctx.x_period_mm / 4.0
        d1 = np.abs(np.mod(x - quarter + 0.5 * ctx.x_period_mm, ctx.x_period_mm) - 0.5 * ctx.x_period_mm)
        d2 = np.abs(np.mod(x - 3.0 * quarter + 0.5 * ctx.x_period_mm, ctx.x_period_mm) - 0.5 * ctx.x_period_mm)
        band = ctx.x_period_mm / 12.0
        return np.maximum(1.0 - smoothstep(band - 1.0, band + 1.0, d1),
                          1.0 - smoothstep(band - 1.0, band + 1.0, d2))
    raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown PAT16 zone {zone!r}",
                      stage="patterns.layers.zone_weight")


# ---------------------------------------------------------------------------------------
# auxiliary appearance layers (max two, plan 9.1 step 1)
# ---------------------------------------------------------------------------------------
class TintWashField(BaseField):
    """Low-frequency colour wash blended over the primary layer."""

    family_id = "AUX_TINT"

    def _process(self, x, s, ctx):
        n = x.shape[0]
        field = FourierBasis.from_dict(self.p["basis"]).value(x, s, ctx.x_period_mm)
        alpha = np.clip(float(self.p["alpha"]) * 0.5 * (1.0 + field), 0.0, 1.0)
        paint = np.tile(_paint(ctx, int(self.p.get("paint_index", 1))), (n, 1))
        rough = np.full(n, float(self.p.get("paint_roughness", ctx.paint_roughness)))
        return FieldOut(coverage=alpha, paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=alpha)


class SpeckleWashField(BaseField):
    """Fine deterministic speckle: albedo/roughness only, never geometry."""

    family_id = "AUX_SPECKLE"

    def _process(self, x, s, ctx):
        n = x.shape[0]
        field = FourierBasis.from_dict(self.p["basis"]).value(x, s, ctx.x_period_mm)
        alpha = np.clip(float(self.p["alpha"]) * 0.5 * (1.0 + np.tanh(field)), 0.0, 1.0)
        paint = np.tile(_paint(ctx, int(self.p.get("paint_index", 0))), (n, 1))
        rough = np.clip(ctx.paint_roughness + float(self.p.get("roughness_delta", 0.08))
                        * np.tanh(field), 0.0, 1.0)
        return FieldOut(coverage=alpha, paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=alpha)


class BandWashField(BaseField):
    """One faint circumferential band drawn under/over the primary layer."""

    family_id = "AUX_BAND"

    def _process(self, x, s, ctx):
        n = x.shape[0]
        period = float(self.p["period_mm"])
        delta = np.abs(np.mod(s - float(self.p["phase_s_mm"]) + 0.5 * period, period) - 0.5 * period)
        alpha = float(self.p["alpha"]) * (1.0 - smoothstep(0.5 * float(self.p["width_mm"]) - self.footprint_mm,
                                                           0.5 * float(self.p["width_mm"]) + self.footprint_mm,
                                                           delta))
        paint = np.tile(_paint(ctx, int(self.p.get("paint_index", 1))), (n, 1))
        rough = np.full(n, float(self.p.get("paint_roughness", ctx.paint_roughness)))
        return FieldOut(coverage=alpha, paint=paint, roughness=rough,
                        height_mm=np.zeros(n), modulation=alpha)


FIELD_CLASSES: dict[str, type[BaseField]] = {
    "PAT01": PlainField, "PAT02": BandField, "PAT03": StripeField, "PAT04": GridField,
    "PAT05": WaveField, "PAT06": DotField, "PAT07": TriangleField, "PAT08": MeanderField,
    "PAT09": CrosshatchField, "PAT10": LeafField, "PAT11": SymbolField, "PAT12": GlyphField,
    "PAT13": KilnField, "PAT14": ReliefField, "PAT15": EngraveField, "PAT16": ComboField,
    "AUX_TINT": TintWashField, "AUX_SPECKLE": SpeckleWashField, "AUX_BAND": BandWashField,
}


def build_field(family_id: str, params: dict[str, Any]) -> BaseField:
    if family_id not in FIELD_CLASSES:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"no field implementation for family {family_id!r}",
                          stage="patterns.layers.build_field")
    return FIELD_CLASSES[family_id](params)


def geometry_mode_of(family_id: str) -> str:
    return {"PAT14": "relief", "PAT15": "engrave"}.get(family_id, "none")
