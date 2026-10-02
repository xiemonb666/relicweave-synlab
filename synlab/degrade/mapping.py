"""The mapping between the synthetic 14-component degradation vector and the real 8-item quality
vector, plus the *inversion* that turns measured quality into synthetic levels.

The gap this module closes
--------------------------
Plan §5, item 9 (``docs/a12/v144_project_core.md`` line 1108):

    "退化向量字段不一致——合成侧有 14 分量统一 ``D=[...]`` 向量（p365），真实侧只有 8 项质量向量
     （p236），中间缺映射表。"

The synthetic side (p365, quoted verbatim in ``data/a12/reports/frag_synth_G.md`` line 213) is::

    D = [fracture_smoothing, edge_rounding, fracture_missing, texture_loss, blur, glare,
         exposure, view_coverage, point_dropout, mesh_holes, depth_noise, normal_noise,
         curvature_noise, calibration_error]

The real side (A6, p199/p236) is:

    Q = [blur, exposure, coverage, occlusion, reconstruction confidence, point density,
         normal stability, curvature stability]

Three kinds of relation actually exist between them and the module refuses to pretend they are
all one-to-one:

``ONE_TO_ONE``
    the component and the quality item are the same physical quantity (``blur`` of ``D`` is
    ``blur`` of ``Q``);
``COMPOSITE``
    the component lands in several quality items at once (``calibration_error`` moves *reconstruction
    confidence* and *point density* together, and with the scale term also the absolute scale);
``UNMAPPABLE``
    no real-side quality item can see the component at all.  ``fracture_smoothing``,
    ``fracture_missing`` and ``texture_loss`` are statements about the *fracture surface as a
    material fact*; ``Q`` is a capture-quality vector, so a perfect capture of a heavily smoothed
    fracture scores exactly like a perfect capture of a fresh one.  That is not a modelling gap to
    paper over with a coefficient — it is a real limit of the real-side vector, and the honest
    consequence is that a synthetic-to-real comparison must not use those three as if they were
    measured.

The inversion
-------------
:func:`levels_from_quality` is the direction the plan actually needs ("真实统计校准"): given the
eight measured quality values **and the declared calibration between each component and its quality
items**, return a candidate synthetic level per component together with an honest residual and a
``kind`` (``OBSERVED`` / ``CONSTRAINED`` / ``UNIDENTIFIED``).  A component whose quality items are
not observable in the input stays ``UNIDENTIFIED`` — it is never given a number by default.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from .specs import DEGRADATION_VECTOR_14, QUALITY_VECTOR_ITEMS

__all__ = [
    "LINK_KINDS", "ONE_TO_ONE", "COMPOSITE", "UNMAPPABLE",
    "DegradationLink", "MAPPING_TABLE", "mapping_table", "mapping_completeness",
    "QUALITY_ITEM_SOURCES", "levels_from_quality", "quality_from_levels",
    "QualityCalibration",
]

ONE_TO_ONE = "ONE_TO_ONE"
COMPOSITE = "COMPOSITE"
UNMAPPABLE = "UNMAPPABLE"
LINK_KINDS: tuple[str, ...] = (ONE_TO_ONE, COMPOSITE, UNMAPPABLE)


# ======================================================================================
# the table
# ======================================================================================
@dataclass(frozen=True)
class DegradationLink:
    """One component of the 14-vector and how it reaches the real 8-item quality vector.

    ``sensitivity``
        d(quality item)/d(component level), signed, in the quality item's own unit per unit of
        synthetic level.  ``+1`` means "a higher synthetic level makes the quality value larger"
        (note that several real-side items are *degradation* measures, i.e. larger = worse).
    ``evidence``
        where the number comes from: ``MEASURED_ON_THIS_MACHINE`` (the axis ladder in
        ``synlab.degrade.axes`` and the measurement runs in this package),
        ``DERIVED`` (a stated physical relation, e.g. the pinhole noise law for ``depth_noise``),
        or ``CANDIDATE`` (no measurement exists; must be calibrated with real paired data).
    """

    component: str
    kind: str
    quality_items: tuple[str, ...]
    sensitivity: tuple[float, ...]
    synthetic_axis: str
    evidence: str
    note: str

    def __post_init__(self) -> None:
        if self.kind not in LINK_KINDS:
            raise ValueError(f"unknown link kind {self.kind!r}")
        if len(self.quality_items) != len(self.sensitivity):
            raise ValueError(f"{self.component}: {len(self.quality_items)} items but "
                             f"{len(self.sensitivity)} sensitivities")
        for item in self.quality_items:
            if item not in QUALITY_VECTOR_ITEMS:
                raise ValueError(f"{self.component}: unknown quality item {item!r}; the real "
                                 f"8-item vector is {list(QUALITY_VECTOR_ITEMS)}")
        if self.kind == UNMAPPABLE and self.quality_items:
            raise ValueError(f"{self.component}: an UNMAPPABLE link must carry no quality item")
        if self.kind != UNMAPPABLE and not self.quality_items:
            raise ValueError(f"{self.component}: a mapped link needs at least one quality item")

    def as_dict(self) -> dict[str, Any]:
        return {"component": self.component, "kind": self.kind,
                "quality_items": list(self.quality_items),
                "sensitivity": list(self.sensitivity),
                "synthetic_axis": self.synthetic_axis, "evidence": self.evidence,
                "note": self.note}

    @property
    def invertible(self) -> bool:
        return self.kind != UNMAPPABLE


#: Where each real-side quality item is produced in this repository.  A mapping that cannot name
#: the producer of a quality item is not a calibration, it is a story.
QUALITY_ITEM_SOURCES: dict[str, str] = {
    "blur": "synlab.observe.quality.blur_metric / blur_laplacian_p95 (I01, I02, and the rig "
            "defocus term of synlab.degrade.rig_error)",
    "exposure": "synlab.observe.quality.exposure_clip_metrics (I03, I04; light states of "
                "synlab.degrade.rig_error)",
    "coverage": "synlab.observe.quality view_coverage_mean / roi_coverage_mean (I08 frame "
                "selection, G03 holes, the reconstruction model of synlab.degrade.rig_error)",
    "occlusion": "synlab.observe.render occlusion channel (I07 occluder re-render); the plan's "
                 "own phrase is 支撑遮挡-affected representative pieces (p1500)",
    "reconstruction_confidence": "backend_report.reconstruction (COLMAP reprojection error, "
                                 "scale_valid) + synlab.degrade.rig_error.reconstruction_noise",
    "point_density": "synlab.degrade.ops_geometry.point_density / median_spacing (G01, G02, and "
                     "the resolution-at-distance term of the rig model)",
    "normal_stability": "normal drift under a resample; measured by "
                        "synlab.degrade.rig_error.measure_point_cloud_quality",
    "curvature_stability": "the spread of the local plane residual under a resample; measured by "
                           "synlab.degrade.rig_error.measure_point_cloud_quality",
}


def _table() -> tuple[DegradationLink, ...]:
    return (
        DegradationLink(
            component="fracture_smoothing", kind=UNMAPPABLE, quality_items=(), sensitivity=(),
            synthetic_axis="P01/P02/P03 (recession, edge rounding, smooth recession)",
            evidence="DERIVED",
            note=("a capture-quality vector cannot see a material fact: the real 8 items describe "
                  "how well the *capture* went, so a perfect capture of a smoothed fracture and "
                  "of a fresh one score identically.  This is the plan's own structural limit "
                  "(line 1108), not a missing coefficient.")),
        DegradationLink(
            component="edge_rounding", kind=COMPOSITE,
            quality_items=("normal_stability", "curvature_stability"),
            sensitivity=(-0.35, -0.25),
            synthetic_axis="P02 (edge fillet) / wear.edge_chip",
            evidence="CANDIDATE",
            note=("edge rounding locally *lowers* the normal and curvature variation, so it can "
                  "show up as a small change of those two stability items — but so can capture "
                  "noise.  Treat as weakly observable only; the real distinguishing measurement "
                  "is a fracture-surface label, not a quality item.")),
        DegradationLink(
            component="fracture_missing", kind=UNMAPPABLE, quality_items=(), sensitivity=(),
            synthetic_axis="P04 (contact loss) / G03 (holes)",
            evidence="DERIVED",
            note=("missing fracture area is a material fact; the real vector has no "
                  "'fracture completeness' item.  Do not infer it from coverage: coverage also "
                  "falls when the rig simply failed to see a present surface.")),
        DegradationLink(
            component="texture_loss", kind=UNMAPPABLE, quality_items=(), sensitivity=(),
            synthetic_axis="P06 (dirt) / wear.glaze_loss (appearance side)",
            evidence="DERIVED",
            note=("paint/glaze/soil layers change the *appearance* of a surface, and the real "
                  "quality vector has no texture item.  texture_loss under P05/P06 is currently "
                  "carried only on the appearance channel, which the eight items do not read.")),
        DegradationLink(
            component="blur", kind=ONE_TO_ONE, quality_items=("blur",),
            sensitivity=(+1.0,),
            synthetic_axis="I01 (PSF sigma) + I02 (motion) + rig_error defocus/rolling shutter",
            evidence="MEASURED_ON_THIS_MACHINE",
            note=("same quantity on both sides.  Real side is the Laplacian-variance family "
                  "(synlab.observe.quality.blur_metric); synthetic side is psf_sigma_px, so the "
                  "calibration is monotone but not linear — the ladder must be fitted, not "
                  "assumed.")),
        DegradationLink(
            component="glare", kind=COMPOSITE, quality_items=("exposure", "blur"),
            sensitivity=(+0.6, -0.15),
            synthetic_axis="I06 (saturation_target) + rig_error light states (5 documented modes)",
            evidence="CANDIDATE",
            note=("a clipped highlight raises the exposure item and *lowers* the measured blur "
                  "metric (a saturated plateau has no Laplacian detail), which is why glare must "
                  "never be read off blur alone.  The five documented light states (t053) are the "
                  "real lever; their weights are candidates.")),
        DegradationLink(
            component="exposure", kind=ONE_TO_ONE, quality_items=("exposure",),
            sensitivity=(+1.0,),
            synthetic_axis="I04 (exposure_ev / digital_gain / negative_exposure)",
            evidence="MEASURED_ON_THIS_MACHINE",
            note="same quantity; the real side carries both over- and under-exposure fractions."),
        DegradationLink(
            component="view_coverage", kind=ONE_TO_ONE, quality_items=("coverage",),
            sensitivity=(-1.0,),
            synthetic_axis="I08 (frame selection) + G03 (observed holes)",
            evidence="MEASURED_ON_THIS_MACHINE",
            note=("opposite sign convention: the synthetic level is 'how much is missing', the "
                  "real item is 'how much is covered'.  The sign is part of the table so an "
                  "inversion cannot silently flip it.")),
        DegradationLink(
            component="point_dropout", kind=ONE_TO_ONE, quality_items=("point_density",),
            sensitivity=(-1.0,),
            synthetic_axis="G01/G02 (sparsify, nested prefix deletion)",
            evidence="MEASURED_ON_THIS_MACHINE",
            note="dropped points lower the density item; the sign is declared, not assumed."),
        DegradationLink(
            component="mesh_holes", kind=COMPOSITE,
            quality_items=("coverage", "reconstruction_confidence"),
            sensitivity=(-0.8, -0.4),
            synthetic_axis="G03 (carved holes) + rig_error hole census (<=2 holes r<=3 mm)",
            evidence="MEASURED_ON_THIS_MACHINE",
            note=("holes land in coverage *and* in the confidence item; the plan's 3-D floor "
                  "(<=2 holes of r<=3 mm) is a hole-census statement, so the rig model reports "
                  "the census directly.")),
        DegradationLink(
            component="depth_noise", kind=COMPOSITE,
            quality_items=("reconstruction_confidence", "point_density"),
            sensitivity=(-0.7, -0.2),
            synthetic_axis="G04 (depth error) + rig_error depth-from-disparity noise",
            evidence="DERIVED",
            note=("depth noise scales as z^2/(f_px B) (stated in "
                  "synlab.degrade.rig_error.noise_sigma_mm), so it is derivable from the working "
                  "distance and the baseline rather than being a free knob.")),
        DegradationLink(
            component="normal_noise", kind=ONE_TO_ONE, quality_items=("normal_stability",),
            sensitivity=(-1.0,),
            synthetic_axis="G05 (normal perturbation)",
            evidence="MEASURED_ON_THIS_MACHINE",
            note="the normals' stability item is the direct counterpart."),
        DegradationLink(
            component="curvature_noise", kind=ONE_TO_ONE, quality_items=("curvature_stability",),
            sensitivity=(-1.0,),
            synthetic_axis="G06 (curvature perturbation)",
            evidence="MEASURED_ON_THIS_MACHINE",
            note="the curvature stability item is the direct counterpart."),
        DegradationLink(
            component="calibration_error", kind=COMPOSITE,
            quality_items=("reconstruction_confidence", "point_density"),
            sensitivity=(-0.6, -0.3),
            synthetic_axis="G07 (intrinsics from images only) + rig_error intrinsics drift and "
                           "scale drift",
            evidence="CANDIDATE",
            note=("intrinsics/scale drift deforms and re-scales the whole cloud, so it moves "
                  "confidence and density together.  The scale part is special: without a "
                  "traceable scale reference the reconstruction scale is ARBITRARY, which no "
                  "bounded percentage describes.")),
    )


MAPPING_TABLE: tuple[DegradationLink, ...] = _table()


def mapping_table() -> list[dict[str, Any]]:
    """The table as plain data (what ``docs/a12/degrade_realism.md`` prints)."""
    return [link.as_dict() for link in MAPPING_TABLE]


def mapping_completeness() -> dict[str, Any]:
    """Every 14-component and every 8-item appears exactly once / is reachable (a test asserts it)."""
    components = [link.component for link in MAPPING_TABLE]
    covered_items: list[str] = []
    reach: dict[str, list[str]] = {item: [] for item in QUALITY_VECTOR_ITEMS}
    for link in MAPPING_TABLE:
        for item in link.quality_items:
            covered_items.append(item)
            reach[item].append(link.component)
    missing_components = [c for c in DEGRADATION_VECTOR_14 if c not in components]
    extra_components = [c for c in components if c not in DEGRADATION_VECTOR_14]
    missing_items = [i for i in QUALITY_VECTOR_ITEMS if i not in reach or not reach[i]]
    return {
        "components_expected": list(DEGRADATION_VECTOR_14),
        "components_present": components,
        "missing_components": missing_components, "extra_components": extra_components,
        "quality_items_expected": list(QUALITY_VECTOR_ITEMS),
        "quality_items_reachable": {k: v for k, v in reach.items()},
        "quality_items_unreachable": missing_items,
        "unmappable_components": [link.component for link in MAPPING_TABLE
                                  if link.kind == UNMAPPABLE],
        "complete": not missing_components and not extra_components and not missing_items,
        "item_usage": {item: covered_items.count(item) for item in QUALITY_VECTOR_ITEMS},
        "structural_gaps": [
            {"gap": "the real 8-item vector has an 'occlusion' item but the synthetic 14-component "
                    "vector has no occlusion component",
             "evidence": ("p365 (14 components, verbatim in data/a12/reports/frag_synth_G.md line "
                          "213) vs p236 (8 items).  The nearest synthetic operator is the shipped "
                          "I07 occluder re-render, which is *not* one of the 14 components, and "
                          "the plan's own §G14.4 notes that the five light states have no "
                          "counterpart in the synthetic vector either (line 1101)."),
             "consequence": ("occlusion can be produced and measured in this repository "
                             "(I07 + the renderer's occlusion channel) but it cannot be *named* "
                             "inside the 14-component vector, so a synthetic-to-real comparison "
                             "of occlusion has to carry it as a separate field.  Reported, not "
                             "papered over with a coefficient.")},
        ],
    }


# ======================================================================================
# inversion: real 8-item quality -> synthetic levels
# ======================================================================================
@dataclass(frozen=True)
class QualityCalibration:
    """The declared per-component calibration (what a real paired capture must fill in).

    ``levels``
        the synthetic level grid of each component (the shipped axes use five levels);
    ``quality_at_zero``
        the quality value of the *identity* run of each item (level 0 of every component);
    ``quality_scale``
        the quality change per unit level, per item, as actually measured on this machine for the
        components marked ``MEASURED_ON_THIS_MACHINE``.  Components without a measurement keep the
        non-dimensional sensitivities of :data:`MAPPING_TABLE` and are reported as candidates.
    """

    levels: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
    quality_at_zero: Mapping[str, float] = field(default_factory=lambda: {
        "blur": 0.0, "exposure": 0.0, "coverage": 1.0, "occlusion": 0.0,
        "reconstruction_confidence": 1.0, "point_density": 1.0, "normal_stability": 1.0,
        "curvature_stability": 1.0,
    })
    #: per item: how much the item moves between level 0 and level 1 of a *unit* component
    quality_span: Mapping[str, float] = field(default_factory=lambda: {
        "blur": 1.0, "exposure": 1.0, "coverage": 1.0, "occlusion": 1.0,
        "reconstruction_confidence": 1.0, "point_density": 1.0, "normal_stability": 1.0,
        "curvature_stability": 1.0,
    })
    calibrated_components: tuple[str, ...] = (
        "blur", "exposure", "view_coverage", "point_dropout", "mesh_holes", "normal_noise",
        "curvature_noise",
    )

    def as_dict(self) -> dict[str, Any]:
        return {"levels": list(self.levels),
                "quality_at_zero": dict(self.quality_at_zero),
                "quality_span": dict(self.quality_span),
                "calibrated_components": list(self.calibrated_components),
                "note": "quality_at_zero is the identity-run reading; quality_span is the item's "
                        "full-range swing.  Both must come from a real paired capture before any "
                        "inversion is trusted."}


def levels_from_quality(quality: Mapping[str, float], *,
                        calibration: QualityCalibration | None = None,
                        quality_validity: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """Invert the real 8-item quality vector into candidate synthetic levels.

    The inversion is a **weighted least-squares fit over the declared table**, not a lookup: for
    every component the predicted quality delta is
    ``sum_i sensitivity_i * quality_span_i * level`` and the residual is reported per item.  A
    component is

    * ``OBSERVED`` when at least one of its quality items is present *and* valid in the input and
      the component is listed in ``calibration.calibrated_components``;
    * ``CONSTRAINED`` when it is observable but the columns of the table are collinear with another
      component's (the fit splits the signal and the split is reported, not hidden);
    * ``UNIDENTIFIED`` when the real vector cannot see it at all (``UNMAPPABLE``) or every item it
      would need is missing/invalid.

    A component is **never** given a default level.  ``levels`` carries ``None`` for every
    ``UNIDENTIFIED`` component so a downstream consumer cannot mistake an unknown for a zero.
    """
    cal = calibration or QualityCalibration()
    validity = dict(quality_validity or {})
    for item in QUALITY_VECTOR_ITEMS:
        validity.setdefault(item, item in quality)
    observed_items = [item for item in QUALITY_VECTOR_ITEMS
                      if validity.get(item, False) and quality.get(item) is not None]

    def reach_of(item: str) -> bool:
        """True when at least one component of the 14-vector can move this quality item."""
        return any(item in link.quality_items for link in MAPPING_TABLE if link.invertible)

    links = [link for link in MAPPING_TABLE if link.invertible]
    usable = [link for link in links
              if any(item in observed_items for item in link.quality_items)]
    if not usable:
        return {
            "levels": {link.component: None for link in MAPPING_TABLE},
            "kind": {link.component: "UNIDENTIFIED" for link in MAPPING_TABLE},
            "residual": {}, "observed_items": observed_items,
            "calibration": cal.as_dict(),
            "note": "the real quality vector carries no usable item; no level is assigned",
        }

    # design matrix: one column per usable component, one row per observed item
    design = np.zeros((len(observed_items), len(usable)), dtype=np.float64)
    for column, link in enumerate(usable):
        for item, sensitivity in zip(link.quality_items, link.sensitivity):
            if item in observed_items:
                row = observed_items.index(item)
                design[row, column] += (float(sensitivity)
                                        * float(cal.quality_span.get(item, 1.0)))
    target = np.asarray([
        (float(quality[item]) - float(cal.quality_at_zero.get(item, 0.0)))
        / max(float(cal.quality_span.get(item, 1.0)), 1e-9)
        for item in observed_items], dtype=np.float64)
    result = np.linalg.lstsq(design, target, rcond=None)
    raw = np.asarray(result[0], dtype=np.float64)
    residual = design @ raw - target
    lo, hi = float(min(cal.levels)), float(max(cal.levels))
    clipped = np.clip(raw, lo, hi)

    # collinearity: which components share a direction in the design space
    collinear: dict[str, list[str]] = {}
    if design.shape[1] > 1:
        norms = np.linalg.norm(design, axis=0)
        unit = design / np.maximum(norms, 1e-12)[None, :]
        correlation = unit.T @ unit
        for i, link in enumerate(usable):
            peers = [usable[j].component for j in range(len(usable))
                     if j != i and abs(correlation[i, j]) > 0.995]
            if peers:
                collinear[link.component] = peers

    levels: dict[str, float | None] = {}
    kinds: dict[str, str] = {}
    for link in MAPPING_TABLE:
        if not link.invertible:
            levels[link.component] = None
            kinds[link.component] = "UNIDENTIFIED"
            continue
        if link not in usable:
            levels[link.component] = None
            kinds[link.component] = "UNIDENTIFIED"
            continue
        index = usable.index(link)
        levels[link.component] = float(np.round(clipped[index], 6))
        if link.component not in cal.calibrated_components:
            kinds[link.component] = "CANDIDATE_LEVEL"
        elif link.component in collinear:
            kinds[link.component] = "CONSTRAINED"
        else:
            kinds[link.component] = "OBSERVED"
    per_item_residual = {item: float(residual[index]) for index, item in enumerate(observed_items)}
    mappable_residual = np.asarray([value for item, value in per_item_residual.items()
                                    if reach_of(item)], dtype=np.float64)
    return {
        "levels": levels, "kind": kinds,
        "level_clipped": {link.component: bool(levels[link.component] is not None
                                              and abs(float(levels[link.component])
                                                      - float(raw[usable.index(link)])) > 1e-9)
                          for link in usable},
        "residual": per_item_residual,
        #: RMS over the items the 14-component vector can actually reach.  An item with no
        #: component (the documented occlusion gap) keeps its residual in ``residual`` but is
        #: excluded here, because it is not an inversion error — it is a missing column.
        "residual_rms": float(np.sqrt(np.mean(mappable_residual ** 2)))
        if mappable_residual.size else 0.0,
        "residual_items_used": sorted(item for item in per_item_residual if reach_of(item)),
        "residual_items_excluded": sorted(item for item in per_item_residual
                                          if not reach_of(item)),
        "observed_items": observed_items,
        "collinear_groups": collinear,
        "unmappable": [link.component for link in MAPPING_TABLE if link.kind == UNMAPPABLE],
        "calibration": cal.as_dict(),
        "note": ("levels are candidate values fitted through the declared table; a component "
                 "whose real-side quality item is absent or invalid is returned as None "
                 "(UNIDENTIFIED), never as 0"),
    }


def quality_from_levels(levels: Mapping[str, float], *,
                        calibration: QualityCalibration | None = None
                        ) -> dict[str, float | None]:
    """Forward direction: synthetic levels -> predicted real quality items.

    Only the two items that every invertible link can reach are returned with a number; an item
    with no contributing component comes back as ``None``.  The function exists so a round trip
    (:func:`levels_from_quality` then :func:`quality_from_levels`) can be checked, and so the
    documentation can state which synthetic settings are *invisible* on the real side.
    """
    cal = calibration or QualityCalibration()
    out: dict[str, float | None] = {}
    for item in QUALITY_VECTOR_ITEMS:
        total = 0.0
        touched = False
        for link in MAPPING_TABLE:
            if item not in link.quality_items:
                continue
            level = levels.get(link.component)
            if level is None:
                continue
            sensitivity = link.sensitivity[link.quality_items.index(item)]
            total += float(sensitivity) * float(cal.quality_span.get(item, 1.0)) * float(level)
            touched = True
        out[item] = (float(cal.quality_at_zero.get(item, 0.0)) + total) if touched else None
    return out
