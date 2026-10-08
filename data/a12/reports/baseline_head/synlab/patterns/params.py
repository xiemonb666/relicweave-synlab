"""Frozen pydantic parameter models for the 16 pattern families (plan 9.3).

Units are authoritative millimetres.  Colours are **linear** albedo with sRGB primaries
(``color_space = "linear_srgb_primaries"``); display encoding happens in the renderer,
never here.  Every model forbids extra fields, so a typo in a caller's parameter dict is
a structured error instead of a silently ignored value.

Complexity tiers (1/2/3) are explicit on every family and change real parameters
(number of bands, harmonics, turns, generations, rings, colour counts); they are not a
relabelling of one fixed tile.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..errors import ErrorCode, SynLabError

LINE_WIDTH_RANGE = (0.5, 3.0)      # plan 9.3
SPACING_RANGE = (5.0, 30.0)        # plan 9.3


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------------------
# palettes (linear albedo)
# ---------------------------------------------------------------------------------------
PALETTES: dict[str, dict[str, Any]] = {
    "iron_slip": {
        "body": (0.212, 0.150, 0.108), "body_roughness": 0.72,
        "paints": [(0.055, 0.035, 0.028), (0.520, 0.300, 0.150), (0.640, 0.610, 0.560)],
        "paint_roughness": 0.58, "tradition": "iron oxide slip on earthenware",
    },
    "celadon": {
        "body": (0.330, 0.318, 0.286), "body_roughness": 0.55,
        "paints": [(0.140, 0.330, 0.230), (0.400, 0.560, 0.430), (0.700, 0.720, 0.680)],
        "paint_roughness": 0.32, "tradition": "reduced celadon glaze",
    },
    "cobalt_white": {
        "body": (0.760, 0.752, 0.720), "body_roughness": 0.28,
        "paints": [(0.045, 0.070, 0.330), (0.180, 0.240, 0.520), (0.870, 0.860, 0.830)],
        "paint_roughness": 0.22, "tradition": "cobalt underglaze on white porcelain",
    },
    "ochre_red": {
        "body": (0.430, 0.240, 0.140), "body_roughness": 0.66,
        "paints": [(0.640, 0.520, 0.300), (0.240, 0.090, 0.060), (0.720, 0.330, 0.180)],
        "paint_roughness": 0.54, "tradition": "ochre and red iron pigments",
    },
    "ash_grey": {
        "body": (0.185, 0.180, 0.174), "body_roughness": 0.78,
        "paints": [(0.420, 0.410, 0.395), (0.060, 0.058, 0.056), (0.560, 0.530, 0.480)],
        "paint_roughness": 0.62, "tradition": "ash glaze over stoneware",
    },
    "slip_white_earth": {
        "body": (0.250, 0.170, 0.120), "body_roughness": 0.74,
        "paints": [(0.780, 0.760, 0.720), (0.430, 0.290, 0.180), (0.150, 0.110, 0.090)],
        "paint_roughness": 0.50, "tradition": "white slip on red earthenware body",
    },
}
PALETTE_IDS: tuple[str, ...] = tuple(sorted(PALETTES))
COLOR_SPACE = "linear_srgb_primaries"


def palette_payload(palette_id: str) -> dict[str, Any]:
    spec = PALETTES[palette_id]
    return {
        "palette_id": palette_id,
        "body": list(spec["body"]),
        "paints": [list(p) for p in spec["paints"]],
        "body_roughness": float(spec["body_roughness"]),
        "paint_roughness": float(spec["paint_roughness"]),
        "color_space": COLOR_SPACE,
        "tradition": spec["tradition"],
    }


# ---------------------------------------------------------------------------------------
# shared building blocks
# ---------------------------------------------------------------------------------------
class RegionSpec(StrictModel):
    surface_tag: str | None = Field(None, description="None = choose from the mother's charts")
    s_margin_frac: float = Field(0.12, ge=0.0, le=0.45)
    feather_mm: float = Field(1.5, ge=0.0, le=10.0)


class WarpSpec(StrictModel):
    enabled: bool = False
    amplitude_mm: float = Field(0.0, ge=0.0, le=6.0)
    wavelength_mm: float = Field(8.0, gt=0.0)
    components: int = Field(1, ge=1, le=3)


class HeightSpec(StrictModel):
    mode: Literal["none", "relief", "engrave"] = "none"
    amplitude_mm: float = Field(0.0, ge=0.0, le=4.0)
    profile: Literal["smoothstep", "raised_cosine", "power"] = "smoothstep"
    power: float = Field(1.0, ge=0.2, le=4.0)
    max_wall_fraction: float = Field(0.25, gt=0.0, le=0.5)


class BaseFamilyParams(StrictModel):
    complexity: int = Field(1, ge=1, le=3)
    line_width_mm: float = Field(1.5, ge=LINE_WIDTH_RANGE[0], le=LINE_WIDTH_RANGE[1])
    spacing_mm: float = Field(10.0, ge=SPACING_RANGE[0], le=SPACING_RANGE[1])
    roughness_paint: float | None = Field(None, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------------------
# PAT01..PAT16
# ---------------------------------------------------------------------------------------
class PlainParams(BaseFamilyParams):
    """PAT01 plain ware: constant colour, optionally a very low frequency colour field."""

    low_freq_color: bool = False
    color_amount: float = Field(0.05, ge=0.0, le=0.4)
    colour_bands: int = Field(2, ge=1, le=3)
    base_wavelength_mm: float = Field(60.0, gt=0.0)
    roughness_variation: float = Field(0.04, ge=0.0, le=0.3)
    spacing_mm: float = 30.0


class BandParams(BaseFamilyParams):
    """PAT02 circumferential bands measured in profile arc length."""

    band_width_mm: float = Field(2.0, ge=LINE_WIDTH_RANGE[0], le=LINE_WIDTH_RANGE[1])
    line_width_mm: float = 2.0
    gap_mm: float = Field(8.0, ge=1.0, le=30.0)
    phase_s_mm: float = 0.0
    pair_gap_mm: float = Field(0.0, ge=0.0, le=10.0)
    filled: bool = False


class StripeParams(BaseFamilyParams):
    """PAT03 stripes with an integer azimuthal count (seam closes exactly)."""

    n_stripes: int | None = Field(None, ge=1, le=400)
    tilt_deg: float = Field(0.0, ge=0.0, le=75.0)
    double_line: bool = False
    thin_ratio: float = Field(0.45, gt=0.0, le=1.0)
    n_groups: int = Field(1, ge=1, le=3)


class GridParams(BaseFamilyParams):
    """PAT04 grid: two stripe sets combined by union or intersection."""

    spacing_b_mm: float = Field(10.0, ge=SPACING_RANGE[0], le=SPACING_RANGE[1])
    tilt_b_deg: float = Field(90.0, ge=0.0, le=90.0)
    mode: Literal["union", "intersection"] = "union"
    order: Literal["a_then_b", "b_then_a"] = "a_then_b"
    thin_ratio: float = Field(0.5, gt=0.0, le=1.0)


class WaveParams(BaseFamilyParams):
    """PAT05 wave: sinusoidal or Bezier centre line, endpoint matched."""

    wavelength_mm: float = Field(40.0, gt=0.0)
    amplitude_mm: float = Field(3.0, ge=0.0, le=25.0)
    n_waves: int | None = Field(None, ge=1, le=64)
    n_harmonics: int = Field(1, ge=1, le=3)
    row_spacing_mm: float = Field(0.0, ge=0.0, le=60.0)
    double_line: bool = False
    variant: Literal["sine", "bezier"] = "sine"
    spacing_mm: float = 20.0


class DotParams(BaseFamilyParams):
    """PAT06 dot lattice: crystal lattice or periodic Poisson disk."""

    mode: Literal["lattice", "poisson"] = "poisson"
    lattice_mode: Literal["hex", "square"] = "hex"
    radius_mm: float = Field(2.0, ge=0.3, le=6.0)
    var_radius_mm: tuple[float, float] | None = None
    clearance_mm: float = Field(0.5, ge=0.0, le=5.0)
    density_target_per_100mm2: float | None = Field(None, gt=0.0)
    solid: bool = True
    ring_ratio: float = Field(0.5, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _var_radius(self) -> "DotParams":
        if self.var_radius_mm is not None:
            lo, hi = self.var_radius_mm
            if not (0.2 <= lo <= hi <= 6.0):
                raise ValueError("var_radius_mm must satisfy 0.2 <= lo <= hi <= 6 mm")
        return self


class TriangleParams(BaseFamilyParams):
    """PAT07 periodic triangular tile."""

    edge_mm: float = Field(12.0, ge=3.0, le=40.0)
    orientation_deg: float = Field(0.0, ge=0.0, le=60.0)
    mode: Literal["line", "solid"] = "line"
    n_colours: int = Field(1, ge=1, le=3)
    barycentric: bool = False
    line_width_mm: float = 1.0
    spacing_mm: float = 12.0


class MeanderParams(BaseFamilyParams):
    """PAT08 meander / key fret inside a periodic tile with shared endpoints."""

    tile_w_mm: float = Field(20.0, ge=4.0, le=60.0)
    tile_h_mm: float = Field(12.0, ge=3.0, le=40.0)
    n_turns: int = Field(2, ge=1, le=6)
    line_width_mm: float = 1.2
    double_line: bool = False
    style: Literal["key", "double_key", "wave_key"] = "key"
    spacing_mm: float = 20.0


class CrosshatchParams(BaseFamilyParams):
    """PAT09 crosshatch: 2-3 line fields with optional deliberate missing strokes."""

    groups: int = Field(2, ge=2, le=3)
    angles_deg: list[float] = Field(default_factory=lambda: [0.0, 90.0])
    spacings_mm: list[float] = Field(default_factory=lambda: [12.0, 12.0])
    line_width_mm: float = 1.0
    missing_fraction: float = Field(0.0, ge=0.0, le=0.4)
    mix_order: Literal["a_then_b", "b_then_a"] = "a_then_b"

    @model_validator(mode="after")
    def _lengths(self) -> "CrosshatchParams":
        if len(self.angles_deg) != self.groups or len(self.spacings_mm) != self.groups:
            raise ValueError("angles_deg and spacings_mm must have exactly `groups` entries")
        if any(s < SPACING_RANGE[0] or s > SPACING_RANGE[1] for s in self.spacings_mm):
            raise ValueError(f"spacings_mm must lie in {SPACING_RANGE} mm")
        return self


class LeafParams(BaseFamilyParams):
    """PAT10 floral: bounded L-system skeleton plus Bezier leaf outlines."""

    generations: int = Field(4, ge=3, le=5)
    segment_cap: int = Field(256, ge=32, le=1024)
    step_mm: float = Field(6.0, gt=0.0, le=30.0)
    angle_deg: float = Field(25.0, ge=5.0, le=70.0)
    branch_probability: float = Field(0.6, ge=0.0, le=1.0)
    leaf_spacing_mm: float = Field(8.0, ge=1.0, le=40.0)
    leaf_length_mm: float = Field(6.0, ge=1.0, le=40.0)
    leaf_aspect: float = Field(0.45, gt=0.05, le=1.0)
    stem_width_mm: float = 1.0
    bezier_curvature: float = Field(0.3, ge=0.0, le=1.0)
    spacing_mm: float = 6.0
    line_width_mm: float = 1.0


class SymbolParams(BaseFamilyParams):
    """PAT11 medallion: programmatic vector symbol or a restricted, registered SVG path."""

    symbol_id: str = "rosette"
    source: Literal["programmatic", "svg_path"] = "programmatic"
    svg_path: str | None = None
    license_ref: str | None = None
    size_mm: float = Field(14.0, ge=2.0, le=80.0)
    count_around: int = Field(4, ge=1, le=24)
    placement_s_mm: float | None = None
    rotate_deg: float = Field(0.0, ge=-180.0, le=180.0)
    two_sizes: bool = False
    small_ratio: float = Field(0.55, gt=0.1, le=1.0)
    connector_arcs: bool = False
    keep_clear: bool = False
    stroke: bool = True
    fill: bool = False
    stroke_width_mm: float = 1.0
    max_elements: int = Field(64, ge=1, le=512)
    max_segments: int = Field(2048, ge=8, le=16384)
    max_file_bytes: int = Field(262144, ge=1024, le=4_194_304)
    spacing_mm: float = 14.0
    line_width_mm: float = 1.0

    @model_validator(mode="after")
    def _source(self) -> "SymbolParams":
        if self.source == "svg_path":
            if not self.svg_path:
                raise ValueError("source='svg_path' requires svg_path")
            if not self.license_ref:
                raise ValueError("source='svg_path' requires an explicit license_ref")
        return self


class GlyphParams(BaseFamilyParams):
    """PAT12 glyphs: one-shot Pillow layout plus a SciPy distance map."""

    text: str = Field("A", min_length=1, max_length=64)
    font_id: str | None = None
    font_path: str | None = None
    font_size_mm: float = Field(10.0, ge=1.0, le=80.0)
    letter_spacing_mm: float = Field(1.5, ge=-5.0, le=20.0)
    run_gap_mm: float = Field(6.0, ge=0.0, le=80.0)
    stroke: bool = False
    stroke_width_mm: float = 1.0
    baseline_s_mm: float | None = None
    ring_count: int = Field(1, ge=1, le=2)
    ring2_size_ratio: float = Field(0.6, gt=0.1, le=1.0)
    rule_lines: bool = False
    spacing_mm: float = 16.0
    line_width_mm: float = 1.0


class KilnParams(BaseFamilyParams):
    """PAT13 kiln transformation: multi-scale continuous blotches with a separate
    roughness sub-stream (no geometry change; Gray-Scott stays optional/unimplemented)."""

    n_scales: int = Field(3, ge=3, le=5)
    base_wavelength_mm: float = Field(45.0, gt=0.0)
    blotch_contrast: float = Field(0.8, ge=0.0, le=1.0)
    speckle_wavelength_mm: float = Field(1.2, ge=0.2, le=10.0)
    speckle_amount: float = Field(0.25, ge=0.0, le=1.0)
    roughness_coupling: float = Field(0.5, ge=0.0, le=1.0)
    roughness_scale: float = Field(0.25, ge=0.0, le=1.0)
    colour_stops: int = Field(4, ge=2, le=5)
    spacing_mm: float = 30.0


class ReliefParams(BaseFamilyParams):
    """PAT14 relief: smooth mask -> positive height -> displacement of the whole body."""

    motif: Literal["blobs", "bands", "medallion", "panel_lattice"] = "blobs"
    height_mm: float = Field(1.0, gt=0.0, le=4.0)
    base_wavelength_mm: float = Field(20.0, gt=0.0)
    n_scales: int = Field(2, ge=1, le=4)
    mask_feather_mm: float = Field(1.5, gt=0.0, le=8.0)
    threshold: float = Field(0.45, ge=-1.0, le=1.0)
    power: float = Field(1.0, ge=0.2, le=4.0)
    max_wall_fraction: float = Field(0.25, gt=0.0, le=0.5)
    medallion_count: int = Field(4, ge=1, le=16)
    band_width_mm: float = Field(6.0, ge=1.0, le=40.0)
    spacing_mm: float = 20.0
    line_width_mm: float = 3.0


class EngraveParams(BaseFamilyParams):
    """PAT15 engraving: curve distance -> negative displacement of the whole body."""

    curve_family: Literal["stripe", "wave", "meander", "grid"] = "stripe"
    depth_mm: float = Field(0.6, gt=0.0, le=3.0)
    line_width_mm: float = 1.5
    spacing_mm: float = 12.0
    max_wall_fraction: float = Field(0.3, gt=0.0, le=0.5)
    curve_params: dict[str, Any] = Field(default_factory=dict)
    crossing_depth_limit: bool = True


class ComboLayer(StrictModel):
    family: str
    params: dict[str, Any] = Field(default_factory=dict)
    zone: Literal["full", "upper", "lower", "centre_band", "side_bands"] = "full"
    weight: float = Field(1.0, ge=0.0, le=1.0)


class ComboParams(BaseFamilyParams):
    """PAT16 combination: region masks and a bounded mix of the layers above."""

    layers: list[ComboLayer] = Field(default_factory=list)
    boundary: Literal["horizontal_band", "vertical_band", "periodic_curve"] = "horizontal_band"
    boundary_width_mm: float = Field(20.0, gt=0.0, le=200.0)
    boundary_feather_mm: float = Field(3.0, ge=0.0, le=40.0)
    mix_order: Literal["primary_then_aux", "aux_then_primary"] = "primary_then_aux"
    allow_geometry: bool = False
    spacing_mm: float = 20.0
    line_width_mm: float = 1.5

    @model_validator(mode="after")
    def _layer_count(self) -> "ComboParams":
        if len(self.layers) > 3:
            raise ValueError("PAT16 combines at most one primary and two auxiliary layers")
        return self


FAMILY_MODELS: dict[str, type[BaseFamilyParams]] = {
    "PAT01": PlainParams, "PAT02": BandParams, "PAT03": StripeParams, "PAT04": GridParams,
    "PAT05": WaveParams, "PAT06": DotParams, "PAT07": TriangleParams, "PAT08": MeanderParams,
    "PAT09": CrosshatchParams, "PAT10": LeafParams, "PAT11": SymbolParams, "PAT12": GlyphParams,
    "PAT13": KilnParams, "PAT14": ReliefParams, "PAT15": EngraveParams, "PAT16": ComboParams,
}

FAMILY_NAMES: dict[str, str] = {
    "PAT01": "素面 plain", "PAT02": "环带 bands", "PAT03": "条纹 stripes", "PAT04": "格网 grid",
    "PAT05": "波浪 waves", "PAT06": "点阵 dots", "PAT07": "三角 triangles", "PAT08": "回纹 meander",
    "PAT09": "交叉线 crosshatch", "PAT10": "花叶 floral", "PAT11": "局部徽记 medallion",
    "PAT12": "字符 glyphs", "PAT13": "窑变 kiln", "PAT14": "浮雕 relief", "PAT15": "刻线 engrave",
    "PAT16": "组合 combination",
}

GEOMETRIC_FAMILIES = ("PAT14", "PAT15")
APPEARANCE_FAMILIES = tuple(f"PAT{i:02d}" for i in range(1, 14))


class PatternSpec(StrictModel):
    """Caller-facing request for :func:`synlab.patterns.api.build_pattern`."""

    family: str | None = Field(None, description="PAT01..PAT16, None = draw with quota")
    complexity: int | None = Field(None, ge=1, le=3)
    palette_id: str | None = None
    surface_tag: str | None = None
    region: RegionSpec = RegionSpec()
    warp: WarpSpec | None = None
    height: HeightSpec | None = None
    texture_mm_per_px: float | None = Field(None, gt=0.0)
    footprint_mm: float | None = Field(None, gt=0.0)
    allow_aux_layers: bool = True
    max_aux_layers: int = Field(2, ge=0, le=2)
    quota_class: Literal["FREE", "PLAIN", "STRONG_REPEAT"] = "FREE"
    seed_ref: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


def family_model(family_id: str) -> type[BaseFamilyParams]:
    if family_id not in FAMILY_MODELS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown pattern family {family_id!r}; known: {sorted(FAMILY_MODELS)}",
                          stage="patterns.params.family_model")
    return FAMILY_MODELS[family_id]


def validate_family_params(family_id: str, payload: dict[str, Any] | BaseFamilyParams
                           ) -> BaseFamilyParams:
    model = family_model(family_id)
    if isinstance(payload, BaseFamilyParams):
        if not isinstance(payload, model):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"params model {type(payload).__name__} does not belong to {family_id}",
                              stage="patterns.params.validate_family_params")
        return payload
    try:
        return model(**dict(payload or {}))
    except Exception as exc:  # pydantic ValidationError -> structured error
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{family_id} parameters rejected: {exc}",
                          stage="patterns.params.validate_family_params") from exc
