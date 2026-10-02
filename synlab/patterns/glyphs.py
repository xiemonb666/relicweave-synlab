"""Font resources and Pillow glyph layout with a SciPy distance map (plan 9.5 / 2.4).

Reuse policy:

* **Pillow** performs the font loading, the glyph metrics (``font.getbbox``,
  ``ImageDraw.textlength``) and the drawing.  No font engine, no kerning table and no
  outline extraction is written here.
* **SciPy** ``distance_transform_edt`` produces the millimetre distance map used for
  antialiased fills and stroked outlines; the pixel scale is passed explicitly and
  recorded in the recipe.

Resource honesty: a requested font that cannot be resolved raises
``INPUT_UNAVAILABLE``.  Fonts are never silently substituted.  The resolved file path,
its SHA-256 and its licence reference travel with the recipe because the glyph layout is
frozen per recipe (a fragment never re-lays-out text).
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt

from ..errors import ErrorCode, SynLabError


@dataclass(frozen=True)
class FontResource:
    font_id: str
    path: str
    sha256: str
    family: str
    style: str
    license_ref: str
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "font_id": self.font_id, "path": self.path, "sha256": self.sha256,
            "family": self.family, "style": self.style,
            "license_ref": self.license_ref, "source": self.source,
        }


_FONT_CACHE: dict[str, FontResource] = {}


def _candidate_files() -> list[tuple[str, str, str, str]]:
    """(font_id, path, license_ref, source) candidates found in this environment."""
    out: list[tuple[str, str, str, str]] = []
    for module_name, ids in (("open3d", ("Roboto-Medium.ttf", "Roboto-Bold.ttf",
                                         "RobotoMono-Medium.ttf")),):
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, ValueError):
            spec = None
        if spec is None or not spec.submodule_search_locations:
            continue
        for root in spec.submodule_search_locations:
            for name in ids:
                path = Path(root) / "resources" / name
                if path.is_file():
                    key = name.split(".")[0].lower().replace("-", "_")
                    out.append((key, str(path), "Apache-2.0 (Roboto, Google Inc.)",
                                f"{module_name} {os.path.basename(str(path))} bundled resource"))
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name, key in (("segoeui.ttf", "segoe_ui"), ("arial.ttf", "arial"),
                      ("times.ttf", "times_new_roman"), ("consola.ttf", "consolas")):
        path = windows / name
        if path.is_file():
            out.append((key, str(path),
                        "proprietary system font (Microsoft Windows EULA); not redistributable",
                        f"system font directory {windows}"))
    for directory in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/noto"):
        for name, key in (("DejaVuSans.ttf", "dejavu_sans"), ("NotoSans-Regular.ttf", "noto_sans")):
            path = Path(directory) / name
            if path.is_file():
                out.append((key, str(path), "DejaVu/Noto permissive font licence",
                            f"system font directory {directory}"))
    return out


def list_fonts() -> dict[str, FontResource]:
    if not _FONT_CACHE:
        for key, path, license_ref, source in _candidate_files():
            if key in _FONT_CACHE:
                continue
            _FONT_CACHE[key] = _describe_font(key, path, license_ref, source)
    return dict(_FONT_CACHE)


def _describe_font(font_id: str, path: str, license_ref: str, source: str) -> FontResource:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    try:
        font = ImageFont.truetype(path, 24)
        family, style = font.getname()
    except Exception:  # pragma: no cover - unreadable font file
        family, style = Path(path).stem, ""
    return FontResource(font_id=font_id, path=str(path), sha256="sha256:" + digest,
                        family=str(family), style=str(style), license_ref=license_ref,
                        source=source)


def resolve_font(font_id: str | None = None, font_path: str | None = None, *,
                 license_ref: str | None = None) -> FontResource:
    """Resolve a font resource or fail loudly (never substitute silently)."""
    if font_path:
        path = Path(font_path)
        if not path.is_file():
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                              f"font file {font_path!r} does not exist; "
                              "no substitute font is used",
                              stage="patterns.glyphs.resolve_font")
        key = path.stem.lower()
        return _describe_font(key, str(path),
                              license_ref or "UNKNOWN: caller must supply the font licence",
                              "caller supplied path")
    fonts = list_fonts()
    if font_id is None:
        if not fonts:
            raise SynLabError(
                ErrorCode.INPUT_UNAVAILABLE,
                "no font resource is available in this environment; PAT12 needs a real "
                "font file and will not substitute a placeholder",
                stage="patterns.glyphs.resolve_font",
                measurements={"searched": ["open3d bundled Roboto", "Windows Fonts",
                                           "DejaVu/Noto system directories"]})
        font_id = "roboto_medium" if "roboto_medium" in fonts else sorted(fonts)[0]
    if font_id not in fonts:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          f"font id {font_id!r} is not registered (available: {sorted(fonts)})",
                          stage="patterns.glyphs.resolve_font")
    return fonts[font_id]


# ---------------------------------------------------------------------------------------
# one-shot layout (frozen per recipe)
# ---------------------------------------------------------------------------------------
@dataclass
class GlyphLayout:
    """Frozen layout of one text run: pixel metrics plus the image-space mask."""

    mask: np.ndarray                  # (H,W) float in [0,1] on the tile canvas
    px_per_mm: float
    run_width_mm: float
    run_height_mm: float
    baseline_px: float
    missing_glyphs: list[str]
    metrics: dict[str, Any] = field(default_factory=dict)


def layout_text_run(*, text: str, font: FontResource, font_size_mm: float,
                    letter_spacing_mm: float, px_per_mm: float, tile_width_mm: float,
                    run_gap_mm: float, baseline_s_mm: float, s0_mm: float,
                    height_px: int, copies_hint: int = 1) -> GlyphLayout:
    """Lay out the whole text run once into a periodic tile canvas.

    The run is repeated with a constant pitch so the tile closes exactly; each
    repetition is drawn at shifts ``-W, 0, +W`` pixels so glyphs crossing the seam land
    on both sides.  Pillow owns the metrics and the drawing.
    """
    font_px = max(4, int(round(float(font_size_mm) * px_per_mm)))
    try:
        pil_font = ImageFont.truetype(font.path, font_px)
    except Exception as exc:  # pragma: no cover - defensive
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          f"Pillow could not load font {font.path!r}: {exc}",
                          stage="patterns.glyphs.layout_text_run") from exc

    width_px = max(8, int(np.ceil(float(tile_width_mm) * px_per_mm)))
    canvas = Image.new("L", (width_px, int(height_px)), 0)
    draw = ImageDraw.Draw(canvas)
    spacing_px = float(letter_spacing_mm) * px_per_mm

    advances = [float(draw.textlength(ch, font=pil_font)) for ch in text]
    run_width_px = float(sum(advances) + spacing_px * max(0, len(text) - 1))
    if run_width_px <= 0:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          f"text {text!r} renders with zero advance in {font.font_id}",
                          stage="patterns.glyphs.layout_text_run")
    pitch_requested_px = run_width_px + float(run_gap_mm) * px_per_mm
    copies = int(copies_hint)
    # The repetition pitch is snapped to an exact divisor of the tile width.  Otherwise the
    # run band does not close at x = C_ref: the value at the seam is still identical (both
    # sides sample column 0) but the *slope* jumps, i.e. a one-texel seam defect.
    if copies <= 0:
        copies = max(1, int(round(width_px / max(pitch_requested_px, 1.0))))
        pitch_px = width_px / copies
        pitch_rule = "snapped to width_px/copies so the tile wraps exactly"
    else:
        pitch_px = pitch_requested_px
        pitch_rule = "caller supplied copies_hint: pitch as requested"
    baseline_px = float((float(baseline_s_mm) - float(s0_mm)) * px_per_mm)
    missing: list[str] = []
    total_width = copies * pitch_px
    offsets = np.arange(copies, dtype=np.float64) * pitch_px
    # centre the whole repeated band on the tile
    offsets = offsets - 0.5 * total_width

    for shift in (-width_px, 0, width_px):
        for offset in offsets:
            x = offset + shift
            for index, ch in enumerate(text):
                bbox = pil_font.getbbox(ch)
                if bbox[2] - bbox[0] <= 0 or bbox[3] - bbox[1] <= 0:
                    if ch not in missing:
                        missing.append(ch)
                draw.text((x, baseline_px), ch, font=pil_font, fill=255, anchor="ls")
                x += float(draw.textlength(ch, font=pil_font)) + spacing_px
    mask = np.asarray(canvas, dtype=np.float64) / 255.0
    if float(mask.max()) <= 0.0:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          f"text {text!r} produced an empty raster in font {font.font_id}; "
                          "the font does not cover these characters",
                          stage="patterns.glyphs.layout_text_run",
                          measurements={"missing_glyphs": missing})
    bbox = pil_font.getbbox(text[0])
    return GlyphLayout(
        mask=mask, px_per_mm=float(px_per_mm), run_width_mm=float(run_width_px / px_per_mm),
        run_height_mm=float((bbox[3] - bbox[1]) / px_per_mm),
        baseline_px=baseline_px, missing_glyphs=missing,
        metrics={
            "font_size_px": int(font_px), "font_size_mm": float(font_size_mm),
            "advances_mm": [float(a / px_per_mm) for a in advances],
            "run_width_mm": float(run_width_px / px_per_mm),
            "run_gap_mm": float(run_gap_mm), "pitch_mm": float(pitch_px / px_per_mm),
            "pitch_requested_mm": float(pitch_requested_px / px_per_mm),
            "pitch_rule": pitch_rule,
            "run_wider_than_tile": bool(run_width_px > width_px),
            "tile_wrap_exact": bool(abs(width_px / max(pitch_px, 1e-9)
                                         - round(width_px / max(pitch_px, 1e-9))) < 1e-9),
            "copies": int(copies),
            "tile_width_mm": float(tile_width_mm),
            "cross_check_textlength_mm": float(draw.textlength(text, font=pil_font) / px_per_mm),
            "layout_api": "PIL.ImageFont.truetype + ImageDraw.text/textlength/getbbox",
            "layout_frozen_once": True,
            "letter_spacing_source": "Pillow advance widths (draw.textlength)",
        },
    )


def signed_distance_mm(mask: np.ndarray, *, px_per_mm: float) -> tuple[np.ndarray, dict[str, Any]]:
    """Signed distance (mm) to the mask boundary via two SciPy EDT passes."""
    inside = np.asarray(mask, dtype=np.float64) > 0.5
    sampling = (1.0 / float(px_per_mm), 1.0 / float(px_per_mm))
    d_in = distance_transform_edt(inside, sampling=sampling)
    d_out = distance_transform_edt(~inside, sampling=sampling)
    signed = d_out - d_in
    return signed, {
        "kernel": "scipy.ndimage.distance_transform_edt",
        "passes": 2,
        "sampling_mm": [float(sampling[0]), float(sampling[1])],
        "pixel_scale_mm": float(1.0 / px_per_mm),
        "sign_convention": "negative inside the glyph, positive outside",
    }


def discs_check(*, px_per_mm: float, radius_mm: float) -> dict[str, float]:
    """Validate the EDT pixel scale against an analytic disc (measured, not assumed)."""
    size = int(np.ceil(4.0 * radius_mm * px_per_mm)) | 1
    yy, xx = np.mgrid[0:size, 0:size]
    centre = 0.5 * (size - 1)
    rr = np.hypot(xx - centre, yy - centre) / px_per_mm
    mask = rr <= radius_mm
    d_in = distance_transform_edt(mask, sampling=(1.0 / px_per_mm, 1.0 / px_per_mm))
    sampled = d_in[mask]
    error = np.abs(sampled - (radius_mm - rr[mask]))
    return {
        "radius_mm": float(radius_mm), "px_per_mm": float(px_per_mm),
        "max_abs_error_mm": float(error.max()), "mean_abs_error_mm": float(error.mean()),
        "n_pixels": int(sampled.size),
    }
