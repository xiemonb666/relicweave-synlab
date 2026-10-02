"""Medallion symbols: programmatic vector symbols or *restricted* registered SVG paths.

Plan 9.3/9.5 requires PAT11 to use either a programmatic vector symbol or a **legal SVG
path**.  The parsing restrictions enforced here (and returned by
:func:`svg_restrictions` so they travel with the recipe) are:

============================  ====================================================
limit                          rule
============================  ====================================================
file size                      at most ``max_file_bytes`` (default 256 KiB)
XML entity / DOCTYPE           rejected outright (no external entity expansion)
elements                       only ``svg`` and ``path`` are accepted
attributes                     ``on*``, ``href``, ``xlink:*``, ``style`` rejected
path data                      parsed by ``svgpathtools.parse_path`` (library parser)
element count                  at most ``max_elements`` (default 64)
segment count                  at most ``max_segments`` (default 2048)
external reference             no ``<use>``, ``<image>``, ``<script>``, no network I/O
============================  ====================================================

The XML is read with the standard library parser; path data is never parsed by hand.
A missing file, an unreadable file or a rule violation raise structured errors - the
loader never falls back to a built-in symbol behind the caller's back.
"""

from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry import Polygon
from svgpathtools import Arc, CubicBezier, Line, parse_path
from svgpathtools import Path as SvgPath

from ..errors import ErrorCode, SynLabError
from .grammar import flatten_path

ALLOWED_ELEMENTS = {"svg", "path"}
FORBIDDEN_ATTRIBUTE_PREFIXES = ("on", "href", "xlink:", "style", "src")
SVG_NS = "{http://www.w3.org/2000/svg}"


@dataclass
class SymbolShape:
    """Frozen symbol geometry in local millimetres (origin at the symbol centre)."""

    outlines: list[np.ndarray]                 # (M,2) closed polylines
    symbol_id: str
    source: str
    resource_hash: str
    license_ref: str
    meta: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "outlines": [[[float(x), float(y)] for x, y in outline] for outline in self.outlines],
            "symbol_id": self.symbol_id, "source": self.source,
            "resource_hash": self.resource_hash, "license_ref": self.license_ref,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SymbolShape":
        return cls(outlines=[np.asarray(o, dtype=np.float64) for o in payload["outlines"]],
                   symbol_id=str(payload["symbol_id"]), source=str(payload["source"]),
                   resource_hash=str(payload.get("resource_hash", "")),
                   license_ref=str(payload.get("license_ref", "")),
                   meta=dict(payload.get("meta") or {}))


def svg_restrictions(*, max_file_bytes: int, max_elements: int, max_segments: int) -> dict[str, Any]:
    return {
        "allowed_elements": sorted(ALLOWED_ELEMENTS),
        "forbidden_attribute_prefixes": list(FORBIDDEN_ATTRIBUTE_PREFIXES),
        "max_file_bytes": int(max_file_bytes),
        "max_elements": int(max_elements),
        "max_segments": int(max_segments),
        "path_parser": "svgpathtools.parse_path",
        "xml_parser": "xml.etree.ElementTree (standard library)",
        "external_references": "rejected",
        "scripts": "rejected",
        "notes": "no <use>/<image>/<script>/<style>/transform; coordinates are user units "
                 "and are scaled into millimetres by the caller",
    }


# ---------------------------------------------------------------------------------------
# programmatic symbols (svgpathtools primitives only)
# ---------------------------------------------------------------------------------------
def _circle_path(*, radius: float, centre: complex = 0j, segments: int = 4,
                 sweep: int = 1) -> SvgPath:
    """Closed circle built from ``svgpathtools.Arc`` segments (library primitive)."""
    points = [centre + radius * complex(math.cos(2 * math.pi * i / segments),
                                        math.sin(2 * math.pi * i / segments))
              for i in range(segments + 1)]
    return SvgPath(*[Arc(points[i], complex(radius, radius), 0, 0, sweep, points[i + 1])
                  for i in range(segments)])


def _rosette(petals: int = 6) -> list[SvgPath]:
    paths: list[Path] = [_circle_path(radius=1.0)]
    for index in range(petals):
        angle = 2 * math.pi * index / petals
        tip = complex(0.95 * math.cos(angle), 0.95 * math.sin(angle))
        left = complex(0.35 * math.cos(angle - 0.45), 0.35 * math.sin(angle - 0.45))
        right = complex(0.35 * math.cos(angle + 0.45), 0.35 * math.sin(angle + 0.45))
        paths.append(SvgPath(CubicBezier(0j, left, tip * 0.9 + left * 0.2, tip),
                          CubicBezier(tip, tip * 0.9 + right * 0.2, right, 0j)))
    return paths


def _lozenge_trefoil(turns: int = 3) -> list[SvgPath]:
    paths: list[Path] = []
    for index in range(turns):
        angle = 2 * math.pi * index / turns
        rot = complex(math.cos(angle), math.sin(angle))
        start = 0.15j * rot
        c1 = (0.9 + 0.45j) * rot
        c2 = (0.9 - 0.45j) * rot
        end = (0.75 + 0.0j) * rot
        paths.append(SvgPath(CubicBezier(start, c1, c2, end),
                          Line(end, -0.2j * rot)))
    return paths


def _chevron_knot(arms: int = 4) -> list[SvgPath]:
    paths: list[Path] = []
    outer = 1.0
    for index in range(arms):
        angle = 2 * math.pi * index / arms
        rot = complex(math.cos(angle), math.sin(angle))
        a = 0.2j * rot
        b = (0.55 * outer + 0.55j * outer) * rot
        c = (outer + 0.0j) * rot
        paths.append(SvgPath(Line(a, b), Line(b, c), Line(c, 0.15j * rot)))
    paths.append(_circle_path(radius=0.28))
    return paths


def _wave_triskele(arms: int = 3) -> list[SvgPath]:
    paths: list[Path] = []
    for index in range(arms):
        angle = 2 * math.pi * index / arms
        rot = complex(math.cos(angle), math.sin(angle))
        p0 = 0.1j * rot
        p1 = (0.45 + 0.35j) * rot
        p2 = (0.85 + 0.05j) * rot
        c1 = (0.35 + 0.75j) * rot
        c2 = (0.75 + 0.55j) * rot
        paths.append(SvgPath(CubicBezier(p0, c1, c2, p2), Line(p2, (0.55 + 0.0j) * rot)))
    return paths


PROGRAMMATIC_SYMBOLS: dict[str, Any] = {
    "rosette": _rosette,
    "lozenge_trefoil": _lozenge_trefoil,
    "chevron_knot": _chevron_knot,
    "wave_triskele": _wave_triskele,
}


def build_programmatic_symbol(symbol_id: str, *, chord_error_mm: float = 0.03) -> SymbolShape:
    if symbol_id not in PROGRAMMATIC_SYMBOLS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown programmatic symbol {symbol_id!r}; "
                          f"known: {sorted(PROGRAMMATIC_SYMBOLS)}",
                          stage="patterns.symbols.build_programmatic_symbol")
    paths = PROGRAMMATIC_SYMBOLS[symbol_id]()
    outlines: list[np.ndarray] = []
    lengths: list[float] = []
    for path in paths:
        flat = flatten_path(path, max_chord_error_mm=chord_error_mm, max_points=2048)
        xy = flat.xy
        xy = xy - xy.mean(axis=0)[None, :]
        outlines.append(xy)
        lengths.append(float(path.length()))
    return SymbolShape(
        outlines=outlines, symbol_id=symbol_id, source="programmatic",
        resource_hash="sha256:" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest(),
        license_ref="project-generated vector symbol (no external asset)",
        meta={
            "n_paths": len(paths), "n_points": int(sum(o.shape[0] for o in outlines)),
            "path_lengths": lengths,
            "chord_error_mm": float(chord_error_mm),
            "primitives": "svgpathtools Line/CubicBezier/Arc",
        })


# ---------------------------------------------------------------------------------------
# restricted SVG path loading
# ---------------------------------------------------------------------------------------
def load_svg_symbol(path: str, *, license_ref: str, max_file_bytes: int = 262144,
                    max_elements: int = 64, max_segments: int = 2048,
                    chord_error_mm: float = 0.03,
                    user_unit_per_mm: float | None = None) -> SymbolShape:
    """Load and validate one SVG file under the documented restrictions."""
    file_path = Path(path)
    if not file_path.is_file():
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          f"SVG symbol file {path!r} does not exist; no substitute is used",
                          stage="patterns.symbols.load_svg_symbol")
    raw = file_path.read_bytes()
    if len(raw) > int(max_file_bytes):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"SVG {path!r} is {len(raw)} bytes, above the {max_file_bytes} byte limit",
                          stage="patterns.symbols.load_svg_symbol")
    head = raw[:4096].lower()
    for token in (b"<!doctype", b"<!entity", b"<?xml-stylesheet"):
        if token in head:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"SVG {path!r} contains {token!r}; entity/stylesheet features "
                              "are not allowed", stage="patterns.symbols.load_svg_symbol")
    try:
        root = ET.fromstring(raw)  # standard-library parser, no network access
    except ET.ParseError as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"SVG {path!r} is not valid XML: {exc}",
                          stage="patterns.symbols.load_svg_symbol") from exc

    elements = 0
    data: list[str] = []
    for element in root.iter():
        tag = element.tag if isinstance(element.tag, str) else ""
        tag = tag.replace(SVG_NS, "")
        if tag not in ALLOWED_ELEMENTS:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"SVG {path!r} contains element <{tag}> which is outside the "
                              f"allowed set {sorted(ALLOWED_ELEMENTS)}",
                              stage="patterns.symbols.load_svg_symbol")
        for attr, value in element.attrib.items():
            name = attr.replace(SVG_NS, "").lower()
            if any(name.startswith(prefix) for prefix in FORBIDDEN_ATTRIBUTE_PREFIXES):
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  f"SVG {path!r} uses forbidden attribute {attr!r}",
                                  stage="patterns.symbols.load_svg_symbol")
            del value
        if tag == "path":
            elements += 1
            if elements > int(max_elements):
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  f"SVG {path!r} has more than {max_elements} <path> elements",
                                  stage="patterns.symbols.load_svg_symbol")
            data.append(element.attrib.get("d", ""))
    if not data:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"SVG {path!r} contains no <path> element",
                          stage="patterns.symbols.load_svg_symbol")

    outlines: list[np.ndarray] = []
    total_segments = 0
    paths_meta: list[dict[str, Any]] = []
    for index, d in enumerate(data):
        try:
            parsed = parse_path(d)
        except Exception as exc:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"SVG {path!r} path #{index} could not be parsed by "
                              f"svgpathtools.parse_path: {exc}",
                              stage="patterns.symbols.load_svg_symbol") from exc
        total_segments += len(parsed)
        if total_segments > int(max_segments):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"SVG {path!r} exceeds {max_segments} path segments",
                              stage="patterns.symbols.load_svg_symbol")
        paths_meta.append({"index": index, "n_segments": len(parsed),
                           "length_user_units": float(parsed.length()),
                           "commands": sorted({type(seg).__name__ for seg in parsed})})
        for subpath in parsed.continuous_subpaths():
            flat = flatten_path(subpath, max_chord_error_mm=chord_error_mm, max_points=2048)
            if flat.xy.shape[0] >= 2:
                outlines.append(flat.xy)
    if not outlines:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"SVG {path!r} produced no drawable outline",
                          stage="patterns.symbols.load_svg_symbol")

    all_pts = np.vstack(outlines)
    scale = 1.0 if user_unit_per_mm is None else float(user_unit_per_mm)
    centre = all_pts.mean(axis=0)
    outlines = [(o - centre[None, :]) * scale for o in outlines]
    scaled = np.vstack(outlines)
    return SymbolShape(
        outlines=outlines, symbol_id=file_path.stem, source="svg_path",
        resource_hash="sha256:" + hashlib.sha256(raw).hexdigest(), license_ref=str(license_ref),
        meta={
            "file": str(file_path), "file_bytes": len(raw),
            "n_path_elements": elements, "n_segments": int(total_segments),
            "n_outlines": len(outlines), "paths": paths_meta,
            "user_unit_per_mm": scale,
            "bbox_mm": [float(scaled[:, 0].min()), float(scaled[:, 0].max()),
                        float(scaled[:, 1].min()), float(scaled[:, 1].max())],
            "restrictions": svg_restrictions(max_file_bytes=max_file_bytes,
                                             max_elements=max_elements,
                                             max_segments=max_segments),
        })


def scale_symbol(shape: SymbolShape, *, size_mm: float) -> SymbolShape:
    """Uniformly scale a symbol so its largest extent equals ``size_mm``."""
    pts = np.vstack(shape.outlines)
    extent = float(max(pts[:, 0].max() - pts[:, 0].min(), pts[:, 1].max() - pts[:, 1].min()))
    if extent <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "symbol has zero extent",
                          stage="patterns.symbols.scale_symbol")
    factor = float(size_mm) / extent
    outlines = [o * factor for o in shape.outlines]
    meta = dict(shape.meta)
    meta["scale_factor"] = factor
    meta["requested_size_mm"] = float(size_mm)
    meta["realized_extent_mm"] = float(extent * factor)
    return SymbolShape(outlines=outlines, symbol_id=shape.symbol_id, source=shape.source,
                       resource_hash=shape.resource_hash, license_ref=shape.license_ref, meta=meta)


# ---------------------------------------------------------------------------------------
# geometry queries (Shapely for containment, exact segments for strokes)
# ---------------------------------------------------------------------------------------
def outline_polygons(shape: SymbolShape) -> list[Polygon]:
    out: list[Polygon] = []
    for outline in shape.outlines:
        poly = Polygon(outline)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.area > 0:
            out.append(poly)
    return out


def coverage_fraction(shape: SymbolShape, *, size_mm: float) -> dict[str, float]:
    """Shapely-based validation metrics of the frozen symbol outlines."""
    polygons = outline_polygons(shape)
    pts = np.vstack(shape.outlines)
    area = float(sum(p.area for p in polygons))
    return {
        "n_outlines": float(len(shape.outlines)),
        "n_closed_polygons": float(len(polygons)),
        "fill_area_mm2": area,
        "bbox_width_mm": float(pts[:, 0].max() - pts[:, 0].min()),
        "bbox_height_mm": float(pts[:, 1].max() - pts[:, 1].min()),
        "size_mm": float(size_mm),
    }


def contains_xy(polygons: list[Polygon], x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Vectorised Shapely containment test across several polygons."""
    inside = np.zeros(np.asarray(x).shape[0], dtype=bool)
    for poly in polygons:
        if poly.is_empty:
            continue
        inside |= np.asarray(shapely.contains_xy(poly, x, y), dtype=bool)
    return inside
