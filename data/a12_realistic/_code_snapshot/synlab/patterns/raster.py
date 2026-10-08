"""Frozen raster tiles with exact periodic sampling (plan 9.3, 9.5).

Pattern families that are naturally vector/raster shaped (glyphs, symbols, leaves,
meanders, solid triangle tiles) are laid out **once** into a chart-aligned raster.  The
raster is stored inside the recipe as PNG bytes, so ``evaluate`` never re-rasterises and
never draws randomness; it only samples the frozen tile.

Sampling rules
--------------
* ``x`` is the periodic chart axis: the tile is wrapped with
  ``scipy.ndimage.map_coordinates(mode="grid-wrap", order=3)`` so the sampled field is
  C1 across ``u=0/u=1`` (no seam) and never nearest-neighbour aliased.
* ``s`` is open: rows are edge-padded before the spline prefilter and queries are
  clamped to the tile, so the profile *end* is a legal drawing boundary, not a seam.
* Distance layers are produced by ``scipy.ndimage.distance_transform_edt`` on a canvas
  that already contains the wrapped copies of the content, then cropped, which makes the
  stored distance the true *periodic* distance in millimetres.

Hand-written convolution kernels, SVG engines and font engines are not used anywhere:
only PIL rasterisation, SciPy transforms and NumPy indexing.
"""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, map_coordinates, spline_filter

LAYER_RGB = ("rgb_r", "rgb_g", "rgb_b")
PAD_ROWS = 4
#: Cubic B-spline sampling order (C2 within the tile, periodic across the seam).
SAMPLE_ORDER = 3


@dataclass
class RasterTile:
    """A frozen chart-aligned raster stack."""

    layers: dict[str, np.ndarray]          # (H,W) float32, values in [0,1] except dist
    x_period_mm: float
    s0_mm: float
    s1_mm: float
    px_per_mm: float
    meta: dict[str, Any] = field(default_factory=dict)
    _padded: dict[str, np.ndarray] = field(default_factory=dict, repr=False)
    _filtered: dict[str, np.ndarray] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.layers = {k: np.ascontiguousarray(v, dtype=np.float32) for k, v in self.layers.items()}
        heights = {v.shape[0] for v in self.layers.values()}
        widths = {v.shape[1] for v in self.layers.values()}
        if len(heights) != 1 or len(widths) != 1:
            raise ValueError(f"raster layers disagree on shape: {[(k, v.shape) for k, v in self.layers.items()]}")
        self._padded = {}
        self._filtered = {}

    # ------------------------------------------------------------------ geometry
    @property
    def shape(self) -> tuple[int, int]:
        any_layer = next(iter(self.layers.values()))
        return int(any_layer.shape[0]), int(any_layer.shape[1])

    @property
    def texel_mm(self) -> float:
        return 1.0 / float(self.px_per_mm)

    def layer_names(self) -> list[str]:
        return sorted(self.layers)

    def _pad(self, name: str) -> np.ndarray:
        if name not in self._padded:
            arr = self.layers[name]
            self._padded[name] = np.pad(arr, ((PAD_ROWS, PAD_ROWS), (0, 0)), mode="edge")
        return self._padded[name]

    def _spline(self, name: str) -> np.ndarray:
        """Cached periodic spline coefficients (same result as ``prefilter=True``).

        ``map_coordinates(..., prefilter=True)`` re-filters the whole tile on every call,
        which dominates the cost of a fragment query.  Filtering once and sampling with
        ``prefilter=False`` returns bit-identical values.
        """
        if name not in self._filtered:
            self._filtered[name] = spline_filter(self._pad(name), order=SAMPLE_ORDER,
                                                 mode="grid-wrap", output=np.float64)
        return self._filtered[name]

    def sample(self, x_mm: np.ndarray, s_mm: np.ndarray, names: Sequence[str],
               scales: dict[str, float] | None = None) -> dict[str, np.ndarray]:
        """Sample frozen layers at chart millimetres (periodic in x, clamped in s)."""
        x = np.asarray(x_mm, dtype=np.float64)
        s = np.asarray(s_mm, dtype=np.float64)
        height, width = self.shape
        col = np.mod(x, float(self.x_period_mm)) * self.px_per_mm
        row = np.clip((s - float(self.s0_mm)) * self.px_per_mm, 0.0, height - 1.0)
        coords = np.vstack([row + PAD_ROWS, col])
        out: dict[str, np.ndarray] = {}
        for name in names:
            if name not in self.layers:
                raise KeyError(f"raster layer {name!r} not present (have {self.layer_names()})")
            values = map_coordinates(self._spline(name), coords, order=SAMPLE_ORDER,
                                     mode="grid-wrap", prefilter=False)
            if scales and name in scales:
                values = values * float(scales[name])
            out[name] = np.asarray(values, dtype=np.float64)
        return out

    def sample_rgb(self, x_mm: np.ndarray, s_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(rgb, coverage)`` sampled from the frozen paint tile."""
        got = self.sample(x_mm, s_mm, [*LAYER_RGB, "cov"])
        rgb = np.stack([got["rgb_r"], got["rgb_g"], got["rgb_b"]], axis=1)
        return np.clip(rgb, 0.0, 1.0), np.clip(got["cov"], 0.0, 1.0)

    def distance_mm(self, x_mm: np.ndarray, s_mm: np.ndarray) -> np.ndarray:
        """Periodic distance to the frozen stroke set, in millimetres."""
        if "dist" not in self.layers:
            raise KeyError("raster has no distance layer")
        scale = float(self.meta.get("dist_scale_mm", 1.0))
        return self.sample(x_mm, s_mm, ["dist"], scales={"dist": scale})["dist"]

    # ------------------------------------------------------------------ payload
    def layer_bytes_hash(self) -> str:
        h = hashlib.sha256()
        for name in self.layer_names():
            h.update(name.encode("ascii"))
            h.update(np.ascontiguousarray(self.layers[name], dtype=np.float32).tobytes())
        return "sha256:" + h.hexdigest()

    def to_payload(self, *, compress_level: int = 6) -> dict[str, Any]:
        """Serialise to a JSON-safe payload (PNG bytes in base64).

        Quantisation is explicit: paint RGB/coverage/roughness use 8 bit, the distance
        layer 8 bit scaled by ``dist_scale_mm``.  ``quantisation_error`` records the
        measured error of the whole round-trip against the float layers.
        """
        height, width = self.shape
        rgb = np.zeros((height, width, 3), dtype=np.uint8)
        for index, name in enumerate(LAYER_RGB):
            rgb[:, :, index] = np.clip(np.round(np.clip(self.layers[name], 0, 1) * 255.0), 0, 255).astype(np.uint8)
        aux = np.zeros((height, width, 4), dtype=np.uint8)
        dist = self.layers.get("dist")
        dist_scale = float(self.meta.get("dist_scale_mm", 1.0))
        aux[:, :, 0] = np.clip(np.round(np.clip(self.layers.get("cov", 0.0), 0, 1) * 255.0), 0, 255)
        if dist is not None:
            aux[:, :, 1] = np.clip(np.round(np.clip(dist / max(dist_scale, 1e-9), 0, 1) * 255.0), 0, 255)
        aux[:, :, 2] = np.clip(np.round(np.clip(self.layers.get("rough", 0.0), 0, 1) * 255.0), 0, 255)
        aux[:, :, 3] = 255
        rgb_png = _png_bytes(Image.fromarray(rgb, mode="RGB"), compress_level)
        aux_png = _png_bytes(Image.fromarray(aux, mode="RGBA"), compress_level)
        payload = {
            "rgb_png_b64": base64.b64encode(rgb_png).decode("ascii"),
            "aux_png_b64": base64.b64encode(aux_png).decode("ascii"),
            "x_period_mm": float(self.x_period_mm), "s0_mm": float(self.s0_mm),
            "s1_mm": float(self.s1_mm), "px_per_mm": float(self.px_per_mm),
            "shape": [height, width], "dist_scale_mm": dist_scale,
            "layer_hash": self.layer_bytes_hash(),
            "meta": {k: v for k, v in self.meta.items() if k != "dist_scale_mm"},
            "quantisation": {
                "paint_rgb_bits": 8, "coverage_bits": 8, "roughness_bits": 8,
                "distance_bits": 8, "distance_step_mm": dist_scale / 255.0,
            },
        }
        payload["quantisation_error"] = self.quantisation_error(round_trip(payload))
        return payload

    def quantisation_error(self, other: "RasterTile") -> dict[str, float]:
        out: dict[str, float] = {}
        for name in self.layer_names():
            if name not in other.layers:
                continue
            diff = np.abs(np.asarray(self.layers[name], dtype=np.float64)
                          - np.asarray(other.layers[name], dtype=np.float64))
            out[f"{name}_max_abs"] = float(diff.max())
            out[f"{name}_mean_abs"] = float(diff.mean())
        return out


def _png_bytes(image: Image.Image, compress_level: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=int(compress_level), optimize=False)
    return buffer.getvalue()


def round_trip(payload: dict[str, Any]) -> "RasterTile":
    """Decode a payload exactly the way :func:`raster_from_payload` does."""
    return raster_from_payload(payload)


def raster_from_payload(payload: dict[str, Any]) -> RasterTile:
    rgb = np.asarray(Image.open(io.BytesIO(base64.b64decode(payload["rgb_png_b64"]))).convert("RGB"),
                     dtype=np.float64) / 255.0
    aux = np.asarray(Image.open(io.BytesIO(base64.b64decode(payload["aux_png_b64"]))).convert("RGBA"),
                     dtype=np.float64) / 255.0
    layers = {
        "rgb_r": rgb[:, :, 0].astype(np.float32),
        "rgb_g": rgb[:, :, 1].astype(np.float32),
        "rgb_b": rgb[:, :, 2].astype(np.float32),
        "cov": aux[:, :, 0].astype(np.float32),
        "rough": aux[:, :, 2].astype(np.float32),
    }
    if np.any(aux[:, :, 1] > 0):
        layers["dist"] = (aux[:, :, 1] * float(payload.get("dist_scale_mm", 1.0))).astype(np.float32)
    meta = dict(payload.get("meta") or {})
    meta["dist_scale_mm"] = float(payload.get("dist_scale_mm", 1.0))
    meta["layer_hash"] = payload.get("layer_hash", "")
    meta["quantisation"] = dict(payload.get("quantisation") or {})
    return RasterTile(layers=layers, x_period_mm=float(payload["x_period_mm"]),
                      s0_mm=float(payload["s0_mm"]), s1_mm=float(payload["s1_mm"]),
                      px_per_mm=float(payload["px_per_mm"]), meta=meta)


# ---------------------------------------------------------------------------------------
# rasterisation helpers (PIL + SciPy kernels only)
# ---------------------------------------------------------------------------------------
def plan_raster(*, x_period_mm: float, s_min_mm: float, s_max_mm: float,
                feature_mm: float, max_pixels: int = 2_500_000,
                min_px_per_mm: float = 2.0) -> dict[str, Any]:
    """Choose the frozen raster resolution from the smallest real feature.

    ``feature_mm`` is the smallest feature the family must represent (line width or
    glyph stroke).  The texel is ``feature_mm/8`` so that the largest gradient is
    sampled by eight texels; the total pixel budget is enforced and any reduction is
    recorded together with the resulting Nyquist wavelength.
    """
    px_per_mm = max(min_px_per_mm, 8.0 / max(float(feature_mm), 1e-3))
    notes: list[str] = []
    width_mm = float(x_period_mm)
    height_mm = float(s_max_mm - s_min_mm)
    while True:
        width_px = int(np.ceil(width_mm * px_per_mm))
        height_px = int(np.ceil(height_mm * px_per_mm))
        if width_px * height_px <= max_pixels or px_per_mm <= min_px_per_mm:
            break
        px_per_mm *= 0.85
        notes.append("pixel budget reduced resolution")
    if width_px < 8 or height_px < 4:
        raise ValueError(f"raster too small: {width_px}x{height_px}")
    requested = float(px_per_mm)
    # Snap the texel so that an integer number of columns spans exactly one azimuthal
    # period: the frozen tile is then periodic in x with the *same* period the sampler
    # folds with, so the sampled field is continuous in value **and** in its first
    # derivative across u=0/u=1 (otherwise the tile is one texel too wide and the seam
    # carries a one-texel content step).
    px_per_mm = width_px / width_mm
    height_px = int(np.ceil(height_mm * px_per_mm))
    return {
        "px_per_mm": float(px_per_mm), "width_px": int(width_px), "height_px": int(height_px),
        "texel_mm": float(1.0 / px_per_mm), "budget_reductions": notes,
        "requested_px_per_mm": requested,
        "period_exact": bool(abs(width_px / px_per_mm - width_mm) < 1e-9),
        "max_pixels": int(max_pixels), "nyquist_wavelength_mm": float(2.0 / px_per_mm),
        "feature_mm": float(feature_mm),
    }


class TileCanvas:
    """PIL canvas that draws in chart millimetres and wraps exactly at the seam.

    ``render(fn)`` calls ``fn(canvas)`` three times with the content shifted by
    ``-W, 0, +W`` pixels, so anything crossing ``x = 0 / x = C_ref`` lands on both sides
    and the frozen tile is periodic by construction.  With ``pad_px > 0`` the canvas is
    widened; the caller crops the border after a transform (used by the EDT distance
    layer) so that border distances include the wrapped neighbours.
    """

    def __init__(self, *, width_px: int, height_px: int, s0_mm: float, px_per_mm: float,
                 pad_px: int = 0, mode: str = "L", background: int = 0) -> None:
        from PIL import ImageDraw

        self.width_px = int(width_px)
        self.height_px = int(height_px)
        self.pad_px = int(pad_px)
        self.s0_mm = float(s0_mm)
        self.px_per_mm = float(px_per_mm)
        self.mode = mode
        self.shift_px = float(self.pad_px)
        self.image = Image.new(mode, (self.width_px + 2 * self.pad_px, self.height_px), background)
        self.draw = ImageDraw.Draw(self.image)

    def mm_to_px(self, x_mm: np.ndarray | float, s_mm: np.ndarray | float) -> np.ndarray:
        x = np.asarray(x_mm, dtype=np.float64) * self.px_per_mm + self.shift_px
        y = (np.asarray(s_mm, dtype=np.float64) - self.s0_mm) * self.px_per_mm
        return np.stack([x, y], axis=-1)

    def line_mm(self, x_mm: np.ndarray, s_mm: np.ndarray, fill: int, width_mm: float) -> None:
        pts = [tuple(p) for p in self.mm_to_px(x_mm, s_mm)]
        if len(pts) < 2:
            return
        width_px = max(1, int(round(float(width_mm) * self.px_per_mm)))
        self.draw.line(pts, fill=int(fill), width=width_px, joint="curve")

    def polygon_mm(self, x_mm: np.ndarray, s_mm: np.ndarray, fill: int) -> None:
        pts = [tuple(p) for p in self.mm_to_px(x_mm, s_mm)]
        if len(pts) < 3:
            return
        self.draw.polygon(pts, fill=int(fill))

    def render(self, fn: Callable[["TileCanvas"], None]) -> np.ndarray:
        for shift in (-self.width_px, 0, self.width_px):
            self.shift_px = float(self.pad_px + shift)
            fn(self)
        return np.asarray(self.image, dtype=np.float64) / 255.0


def periodic_distance(mask: np.ndarray, *, px_per_mm: float, pad_px: int
                      ) -> tuple[np.ndarray, dict[str, Any]]:
    """Periodic EDT distance for a tile that is already x-periodic.

    The tile is circularly padded in x before the transform and cropped afterwards, so
    the returned distance (shape ``(H, W)`` like the other layers) includes the wrapped
    neighbours.
    """
    pad = int(pad_px)
    if pad <= 0:
        raise ValueError("periodic_distance needs pad_px > 0")
    arr = np.asarray(mask, dtype=np.float64)
    if pad >= arr.shape[1]:
        reps = int(np.ceil(pad / arr.shape[1]))
        tiled = np.concatenate([arr] * (2 * reps + 1), axis=1)
        centre = reps * arr.shape[1]
        padded = tiled[:, centre - pad: centre + arr.shape[1] + pad]
    else:
        padded = np.concatenate([arr[:, -pad:], arr, arr[:, :pad]], axis=1)
    cropped, report = distance_layer(padded, px_per_mm=px_per_mm, pad_px=pad)
    report["wrap"] = "circular pad in x on the frozen periodic tile"
    return cropped, report


def distance_layer(mask: np.ndarray, *, px_per_mm: float, pad_px: int
                   ) -> tuple[np.ndarray, dict[str, Any]]:
    """Periodic Euclidean distance to ``mask`` using ``scipy.ndimage.distance_transform_edt``.

    ``mask`` is the padded canvas (content already includes the wrapped copies).  The
    centre tile is cropped after the transform, so border distances include the wrapped
    neighbours.  Pixel scale is explicit: ``sampling=(1/px_per_mm, 1/px_per_mm)``.
    """
    if pad_px <= 0:
        raise ValueError("distance_layer needs pad_px > 0")
    inside = np.asarray(mask, dtype=np.float64) > 0.5
    field = distance_transform_edt(~inside, sampling=(1.0 / px_per_mm, 1.0 / px_per_mm))
    cropped = field[:, pad_px:field.shape[1] - pad_px]
    report = {
        "kernel": "scipy.ndimage.distance_transform_edt",
        "pixel_scale_mm": float(1.0 / px_per_mm),
        "sampling": [float(1.0 / px_per_mm), float(1.0 / px_per_mm)],
        "pad_px": int(pad_px),
        "distance_clamp_mm": float(pad_px / px_per_mm),
    }
    return cropped, report


def distance_scale_from_pad(*, width_mm: float, footprint_mm: float, pad_px: int,
                            px_per_mm: float) -> float:
    half = 0.5 * float(width_mm)
    needed = half + float(footprint_mm) + 1e-6
    return float(max(needed * 1.05, min(pad_px / px_per_mm, needed * 3.0)))
