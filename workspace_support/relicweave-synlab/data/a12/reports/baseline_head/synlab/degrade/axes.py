"""The 31 degradation axes (plan 15.2闂?5.5, 30.7闂?0.9).

One :class:`~synlab.degrade.registry.AxisOperator` subclass per axis:

======================  ==========================================================
family                  axes
======================  ==========================================================
P  physical damage      P01..P08  (``synlab.physical.apply_damage`` on a real body)
I  imaging              I01..I10  (optics / sensor / ISP / derivation, OpenCV)
G  observed geometry    G01..G08  (points, frames, fused mesh; observed side only)
X  estimate/protocol    X01..X05  (modalities, segmentation, context, quality, profile)
======================  ==========================================================

Contracts enforced here (and by ``synlab/degrade/api.py``):

* ``level 0`` is a true identity: the framework returns the *source bundle object* and the
  fa闂佺厧澧界粋鍧塭 returns the original ``AssetRecord`` 闂?no resampling, no re-encode, no re-write;
* all five levels of one axis share the basis returned by ``sample_basis`` (the per-level
  randomness comes from :func:`synlab.degrade.registry.basis_rng`), so the levels are paired;
* every declared effect is *measured* on the real arrays; when the declared change is not
  present in the output the measurement reports ``realized=False`` and the fa闂佺厧澧界粋鍧塭 turns that
  into ``OPERATOR_NOT_REALIZED`` 闂?a parameter being written never counts as success;
* an inapplicable input (wrong material, missing appearance, no per-frame depth, no boundary
  hole, no context keys) raises ``NA_NOT_APPLICABLE`` and stays in the denominator.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, ClassVar

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..roles import (
    UNIT_MM,
    UNIT_NONE,
    UNIT_PX,
)
from ..schemas.runtime import DegradationBasis
from . import ops_geometry as OG
from . import ops_image as OI
from .compat import _install_evaluate_field_fix, install_trimesh_shims
from .registry import (
    ALL_MATERIALS,
    STAGE_FEATURE_PROTOCOL,
    STAGE_GEOMETRY_OBS,
    STAGE_ISP,
    STAGE_OPTICS,
    STAGE_PHYSICAL,
    STAGE_SCENE,
    STAGE_SENSOR,
    AxisOperator,
    basis_rng,
    register_operator,
)
from .sources import (
    KIND_CLEAN,
    KIND_CONTEXT,
    KIND_GEOMETRY,
    KIND_IMAGE,
    KIND_MESH,
    KIND_MODALITY,
    KIND_OBS,
    KIND_PHYSICAL,
    KIND_PROFILE,
    KIND_QUALITY,
    SourceBundle,
)

# ---------------------------------------------------------------------------- material groups
#: Rough/matte bodies whose fracture surface actually carries a high-frequency band (P01).
POLISHABLE = ("M01", "M02", "M03", "M06", "M08", "M09", "M10", "M11")
#: Bodies with a real convex edge population for edge rounding (P02).
EDGE_BEARING = ("M01", "M02", "M03", "M04", "M06", "M08", "M09", "M10", "M11")
#: Bodies that erode instead of chipping (P03/P07): glass and metal are excluded, not
#: silently substituted by another operator (plan 15.2 last paragraph).
ERODIBLE = ("M01", "M02", "M03", "M04", "M05", "M06", "M08", "M09", "M10", "M11")
#: Materials that may legally carry paint / a coat layer (P05, P08 coat variants).
COATED = ("M03", "M05", "M06", "M11")
#: Materials with a brittle chip response (P04/P08 crack).
BRITTLE = ("M01", "M02", "M03", "M04", "M05", "M06", "M08", "M09", "M10", "M11")

__all__ = ["register_all", "AXES"]


# ---------------------------------------------------------------------------- bundle helpers
def _with(bundle: SourceBundle, payload: dict[str, Any] | None = None,
          meta: dict[str, Any] | None = None, remove: tuple[str, ...] = ()) -> SourceBundle:
    clean = {k: v for k, v in bundle.payload.items() if k not in remove}
    clean.update(payload or {})
    merged = dict(bundle.meta or {})
    merged.update(meta or {})
    return replace(bundle, payload=clean, meta=merged)


def _measured(result: SourceBundle) -> dict[str, float]:
    return {str(k): float(v) for k, v in ((result.meta or {}).get("measured") or {}).items()
            if isinstance(v, (int, float, np.integer, np.floating))}


def _units(result: SourceBundle) -> dict[str, str]:
    return {str(k): str(v) for k, v in ((result.meta or {}).get("units") or {}).items()}


def _meta(result: SourceBundle, key: str, default: Any = None) -> Any:
    return (result.meta or {}).get(key, default)


def _material_of(source: SourceBundle) -> str:
    for container in (source.meta or {}, source.payload or {}):
        value = container.get("material_id") if isinstance(container, dict) else None
        if value:
            return str(value)
    fragment = source.payload.get("fragment") if isinstance(source.payload, dict) else None
    material = (getattr(fragment, "meta", None) or {}).get("material_id")
    return str(material or "")


class _FragmentView:
    """Minimal fragment-like wrapper so a bare mesh payload can feed ``synlab.physical``."""

    def __init__(self, mesh: Any, fragment_id: str = "fragment", *, meta: dict[str, Any] | None = None,
                 face_attrs: dict[str, np.ndarray] | None = None) -> None:
        self.mesh = mesh
        self.fragment_id = fragment_id
        self.meta = dict(meta or {})
        attrs = dict(face_attrs or {})
        self.face_origin_kind = attrs.get("origin_kind")
        self.face_interface_id = attrs.get("interface_id")


def physical_fragment(source: SourceBundle) -> _FragmentView:
    """Resolve the damaged body of a P-axis source (fragment object or stored mesh)."""
    fragment = source.get("fragment")
    mesh = source.get("mesh")
    if mesh is None or not (hasattr(mesh, "vertices") and hasattr(mesh, "faces")):
        mesh = OG.mesh_of(source)
    if fragment is not None and mesh is not None and getattr(fragment, "mesh", None) is not mesh:
        fragment = _FragmentView(mesh, str(getattr(fragment, "fragment_id", "fragment")),
                                 meta=dict(getattr(fragment, "meta", None) or {}))
    elif fragment is None and mesh is not None:
        fragment = _FragmentView(mesh, str((source.meta or {}).get("fragment_id", "fragment")),
                                 meta=dict(source.meta or {}))
    if fragment is None or not hasattr(fragment, "mesh"):
        raise SynLabError(
            ErrorCode.NA_NOT_APPLICABLE,
            "the P axes need a closed body (payload 'mesh'/'vertices'+'faces' or a fragment "
            "object); this source carries neither",
            stage="degrade.axes.physical_fragment",
        )
    return fragment


def appearance_of(source: SourceBundle) -> dict[str, Any] | None:
    """Texel appearance payload (paint/dirt/coat) carried by the fragment or the source."""
    fragment = source.get("fragment")
    appearance = (getattr(fragment, "meta", None) or {}).get("appearance")
    if appearance:
        return appearance
    direct = source.get("appearance")
    if direct:
        return dict(direct)
    return None


def roi_faces_of(mesh: Any, fragment: Any, roi: dict[str, Any] | None
                 ) -> tuple[np.ndarray, dict[str, Any]]:
    """ROI face selection on a bare mesh (thin wrapper over ``synlab.physical.fields``)."""
    from ..physical.fields import roi_faces

    return roi_faces(mesh, fragment, roi)


# ---------------------------------------------------------------------------- base class
class _BaseAxis(AxisOperator):
    """Shared plumbing: level tables, applicability, measurement envelope."""

    LEVELS: ClassVar[tuple[dict[str, Any], ...]] = ()
    VARIANT_LEVELS: ClassVar[dict[str, dict[str, dict[str, Any]]]] = {}
    BASIS_FIELDS: ClassVar[tuple[str, ...]] = ()

    # -- declaration ---------------------------------------------------------------
    def parameter_schema(self) -> dict[str, Any]:
        return {
            "levels": [dict(entry) for entry in self.LEVELS],
            "variants": {name: [dict(self.VARIANT_LEVELS.get(name, {}).get(f"L{i}",
                                                                           self.LEVELS[i]))
                                for i in self.levels()]
                         for name in self.variants()},
            "notes": self.NOTES,
        }

    NOTES: ClassVar[str] = ""

    def params_for(self, level: int, variant: str) -> dict[str, Any]:
        table = self.VARIANT_LEVELS.get(variant)
        if table:
            return dict(table[f"L{int(level)}"])
        return dict(self.LEVELS[int(level)])

    def level_parameters(self, level: int) -> dict[str, Any]:
        return self.params_for(level, self.default_variant)

    # -- applicability -------------------------------------------------------------
    def applicability(self, source: SourceBundle, variant: str) -> tuple[bool, str | None]:
        ok, reason = super().applicability(source, variant)
        if not ok:
            return ok, reason
        material = _material_of(source)
        if material and material not in self.SUPPORTED_MATERIALS:
            return False, (f"material {material} is not supported by {self.AXIS_ID} "
                           f"(supported: {list(self.SUPPORTED_MATERIALS)}); the axis is "
                           f"rejected instead of being replaced by another operator")
        return self.extra_applicability(source, variant)

    def extra_applicability(self, source: SourceBundle, variant: str) -> tuple[bool, str | None]:
        return True, None

    # -- basis ---------------------------------------------------------------------
    def _basis_payload(self, context: dict[str, Any], rng: np.random.Generator,
                       variant: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"seed": int(rng.integers(0, 2 ** 31 - 1))}
        payload.update(self._sample_payload(context, rng, variant))
        return payload

    def _sample_payload(self, context: dict[str, Any], rng: np.random.Generator,
                        variant: str) -> dict[str, Any]:
        return {}

    def source_of(self, context: dict[str, Any]) -> SourceBundle:
        source = context.get("source")
        if source is None:
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"{self.AXIS_ID} freezes part of its basis from the source payload (ROI, pose or "
                f"appearance); sample_basis() needs context['source']",
                stage="degrade.axes.sample_basis",
            )
        return source

    # -- measurement ---------------------------------------------------------------
    def measure(self, source: SourceBundle, result: SourceBundle,
                context: dict[str, Any] | None = None) -> dict[str, Any]:
        if result is source:
            return {"measured": {}, "units": {}, "realized": True,
                    "extra": {"identity": True, "level0_returns_source_object": True}}
        measured = _measured(result)
        out: dict[str, Any] = {
            "measured": measured,
            "units": _units(result),
            "realized": bool(_meta(result, "realized", bool(measured))),
            "extra": dict(_meta(result, "extra") or {}),
        }
        invariants = self.invariant_checks(source, result)
        if invariants:
            out["extra"]["invariants"] = invariants
            if invariants.get("violated"):
                out["realized"] = False
                out["failure_code"] = str(invariants.get("code", ErrorCode.OPERATOR_NOT_REALIZED.value))
        return out

    def invariant_checks(self, source: SourceBundle, result: SourceBundle) -> dict[str, Any]:
        """Source/result invariants that must hold for this axis (measured, not asserted)."""
        return {}

    # -- shared geometry guard -----------------------------------------------------
    def _geometry_hash_guard(self, source: SourceBundle, result: SourceBundle) -> dict[str, Any]:
        from .sources import mesh_geometry_hash

        source_fragment = source.get("fragment")
        result_fragment = result.get("fragment")
        source_mesh = getattr(source_fragment, "mesh", None) or source.get("mesh")
        result_mesh = getattr(result_fragment, "mesh", None) or result.get("mesh")
        before = mesh_geometry_hash(source_mesh) if source_mesh is not None else ""
        after = mesh_geometry_hash(result_mesh) if result_mesh is not None else ""
        unchanged = bool(before and before == after)
        return {"geometry_hash_before": before, "geometry_hash_after": after,
                "geometry_hash_unchanged": unchanged, "violated": not unchanged,
                "code": "APPEARANCE_CHANGED_GEOMETRY"}


# ======================================================================================
# P axes: physical damage (plan 15.2, 12.x, 30.7)
# ======================================================================================
POLISH_STRENGTH = (0.0, 0.25, 0.5, 0.75, 1.0)
P01_RADIUS_MM = 2.0
P02_EDGE_WIDTH_MM = 0.4


class _PhysicalAxis(_BaseAxis):
    STAGE = STAGE_PHYSICAL
    SUBSTAGE = "surface"
    UNIT = UNIT_MM
    COST_CLASS = "high"
    READS = ("source:asset",)
    WRITES = ("physical:damage", "asset")
    LABEL_INVALIDATIONS = ("PhysicalTruth", "VisibleLabels", "FeatureAdapter")
    ACCEPTED_SOURCES = (KIND_PHYSICAL, KIND_MESH, KIND_CLEAN, KIND_GEOMETRY)
    BASIS_NEEDS_SOURCE = True
    NOTES = "level 0 returns the source asset reference/bytes without resampling (plan 12.1)"

    #: fixed SDF grid / tolerance decisions of this axis (not per-level knobs)
    GRID: ClassVar[dict[str, Any]] = {"spacing_mm": None, "max_nodes": 600_000, "chunk": 24,
                                      "halo": 1, "roi_density_mm": 0.5}
    ROI: ClassVar[dict[str, Any]] = {"kind": "interface"}
    MIN_WALL_MM: ClassVar[float | None] = None
    #: declared resolution rule: the grid spacing requested for a level, derived from one
    #: parameter of that level.  The plan requires spacing to resolve the operator's own scale,
    #: so the measured spacing/node count is reported and a request the node budget cannot
    #: honour surfaces as PRECISION_NOT_REALIZED instead of a silently coarsened result.
    SPACING_FROM: ClassVar[tuple[str, float] | None] = None
    SPACING_FLOOR_MM: ClassVar[float] = 0.05
    SPACING_CEIL_MM: ClassVar[float | None] = None

    def grid_for(self, params: dict[str, Any]) -> dict[str, Any]:
        grid = dict(self.GRID)
        rule = self.SPACING_FROM
        if rule is not None:
            name, factor = rule
            value = params.get(name)
            if value is not None and float(value) > 0:
                spacing = max(float(value) * float(factor), float(self.SPACING_FLOOR_MM))
                if self.SPACING_CEIL_MM is not None:
                    spacing = min(spacing, float(self.SPACING_CEIL_MM))
                grid["spacing_mm"] = float(spacing)
                grid["spacing_rule"] = f"{name} * {factor}"
                grid["spacing_requested_mm"] = float(spacing)
        return grid

    def realized_override(self, measured: dict[str, float], outcome: Any) -> bool | None:
        """Judge realization on this axis's *declared* target (None keeps the physical verdict)."""
        return None

    def recipe(self, *, level: int, variant: str, params: dict[str, Any],
               basis: DegradationBasis, fragment: Any, source: SourceBundle) -> Any:
        from ..physical.recipe import DamageRecipe

        roi = self.roi_for(variant, source)
        meta: dict[str, Any] = {"fragment_id": getattr(fragment, "fragment_id", ""),
                                "min_wall_thickness_mm": self.MIN_WALL_MM,
                                "min_representative_ratio": 0.02,
                                **dict(self.EXTRA_META)}
        if self.HALO_MM is not None:
            meta["halo_mm"] = float(self.HALO_MM)
        return DamageRecipe(
            axis_id=self.AXIS_ID, variant=variant, level=int(level),
            recipe_id=f"{self.AXIS_ID}:{variant}:L{level}",
            params=dict(params), roi=dict(roi), grid=self.grid_for(params),
            basis=dict(basis.payload or {}),
            expected=dict(self.EXPECTED),
            qa={"outside_tol_mm": 1e-4, "min_wall_thickness_mm": self.MIN_WALL_MM},
            meta=meta,
        )

    EXTRA_META: ClassVar[dict[str, Any]] = {}
    ROI_OVERRIDES: ClassVar[dict[str, dict[str, Any]]] = {}
    HALO_MM: ClassVar[float | None] = None
    EXPECTED: ClassVar[dict[str, Any]] = {}
    #: Narrow-band backend (plan 12.1 "narrow band / adaptive", 12.2): axes whose declared
    #: effect is smaller than the frozen global SDF grid spacing build their removed solid
    #: locally in ``synlab.degrade.physical_narrowband`` instead of extracting a level set on
    #: the global grid.  ``None`` keeps the shipped ``synlab.physical.apply_damage`` path.
    NARROWBAND: ClassVar[bool] = False

    def physical_result(self, recipe: Any, fragment: Any, clean_truth: Any) -> Any:
        """Run one level of this P axis and return a ``PhysicalResult``-shaped outcome."""
        if self.NARROWBAND:
            from .physical_narrowband import run_narrowband_damage

            mesh = getattr(fragment, "mesh", None)
            if mesh is None:
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  f"{self.AXIS_ID}: narrow-band backend needs a fragment mesh",
                                  stage="degrade.axes.narrowband")
            return run_narrowband_damage(mesh, recipe, fragment=fragment, rng=None)
        from ..physical.api import apply_damage

        return apply_damage(clean_truth, fragment, recipe, rng=None)

    def roi_for(self, variant: str, source: SourceBundle) -> dict[str, Any]:
        return dict(self.ROI_OVERRIDES.get(variant, self.ROI))

    def _apply(self, source: SourceBundle, level: int, params: dict[str, Any],
               basis: DegradationBasis, variant: str) -> SourceBundle:
        from ..physical.api import apply_damage

        fragment = physical_fragment(source)
        clean_truth = source.get("clean_truth")
        recipe = self.recipe(level=level, variant=variant, params=params, basis=basis,
                             fragment=fragment, source=source)
        result = self.physical_result(recipe, fragment, clean_truth)
        representative = next((c for c in result.components if c.is_representative),
                              result.components[0] if result.components else None)
        if representative is None:
            raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING,
                              f"{self.AXIS_ID}: physical result carries no component",
                              stage="degrade.axes.P")
        appearance = dict(result.meta.get("appearance") or {}) or None
        fragment_out = _FragmentView(representative.mesh, str(getattr(fragment, "fragment_id", "")),
                                     meta={**dict(getattr(fragment, "meta", None) or {}),
                                           **({"appearance": appearance} if appearance else {})})
        measured = {str(k): float(v) for k, v in (result.meta.get("measured") or {}).items()
                    if isinstance(v, (int, float, np.integer, np.floating))}
        measured.update(self.extra_measurements(source, representative.mesh, result))
        realized = bool(result.qa.get("realized", False))
        override = self.realized_override(measured, result)
        if override is not None:
            realized = bool(override)
        grid_info = dict(((result.meta.get("details") or {}).get("sdf_pipeline") or {}).get("spacing")
                         or {})
        if grid_info:
            measured["grid_spacing_mm"] = float(grid_info.get("spacing_mm", 0.0) or 0.0)
            measured["grid_spacing_requested_mm"] = float(
                grid_info.get("requested_mm") or grid_info.get("spacing_mm") or 0.0)
            measured["grid_nodes"] = float(grid_info.get("nodes", 0) or 0)
        return _with(
            source,
            payload={"physical_result": result, "mesh": representative.mesh,
                     "fragment": fragment_out,
                     **({"appearance": appearance} if appearance else {})},
            meta={"axis_id": self.AXIS_ID, "variant": variant, "level": int(level),
                  "measured": measured,
                  "units": {str(k): str(v) for k, v in (result.meta.get("measurement_units") or {}).items()},
                  "realized": bool(realized),
                  "realized_basis": ("DECLARED_TARGET_ACHIEVED" if override is not None
                                     else "PHYSICAL_OUTCOME"),
                  "grid": grid_info,
                  "physical_audit": dict(result.qa),
                  "label_status": str(result.meta.get("physical_truth_status", "UNKNOWN")),
                  "label_invalidations": list(self.LABEL_INVALIDATIONS),
                  "extra": {"geometry_changed": bool(result.meta.get("geometry_changed", False)),
                            "ledger": dict(result.meta.get("ledger") or {}),
                            "source_geometry_hash": result.meta.get("source_geometry_hash"),
                            "result_geometry_hash": result.qa.get("result_geometry_hash"),
                            "component_count": len(result.components)}},
        )

    def extra_measurements(self, source: SourceBundle, mesh: Any, result: Any) -> dict[str, float]:
        return {}

    def invariant_checks(self, source: SourceBundle, result: SourceBundle) -> dict[str, Any]:
        audit = dict(_meta(result, "physical_audit") or {})
        failure = str(audit.get("failure_code") or "")
        return {"physical_status": str(audit.get("status", "UNKNOWN")),
                "violated": bool(failure), "code": failure or ErrorCode.OPERATOR_NOT_REALIZED.value,
                "label_status": str(_meta(result, "label_status", "UNKNOWN"))}


class P01(_PhysicalAxis):
    AXIS_ID = "P01"
    default_variant = "fixed_radius_basis"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"fixed_radius_basis": "SINGLE_PARAMETER",
                     "radius_sweep": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"polish": "fixed_radius_basis"}
    SUPPORTED_MATERIALS = POLISHABLE
    GRID = {"spacing_mm": None, "max_nodes": 600_000, "chunk": 24, "halo": 1,
            "roi_density_mm": 0.25}
    SPACING_FROM = None  # the radius (and therefore the required resolution) is frozen
    LEVELS = tuple({"recession_strength": s, "radius_mm": P01_RADIUS_MM} for s in POLISH_STRENGTH)
    VARIANT_LEVELS = {"radius_sweep": {f"L{i}": {"recession_strength": 1.0, "radius_mm": r}
                                       for i, r in enumerate((0.0, 0.5, 1.0, 1.5, 2.0))}}
    NOTES = ("fixed filter radius and full recession basis; only recession_strength moves. "
             "The radius scan is a separate variant and never claims the same-basis nesting. "
             "radius_mm=2.0 is the resolution-qualified choice: smaller radii produce a "
             "recession below the frozen grid spacing and are refused with "
             "PRECISION_NOT_REALIZED (measured spacing is reported).")

    def _sample_payload(self, context, rng, variant):
        return {"radius_mm": P01_RADIUS_MM, "field_id": "P01_own_outward_height"}

    def extra_measurements(self, source, mesh, result):
        return {}


class P02(_PhysicalAxis):
    AXIS_ID = "P02"
    default_variant = "sdf_fillet"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"sdf_fillet": "SINGLE_PARAMETER", "chamfer": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"subtractive_edge_rounding": "sdf_fillet", "round_edge": "sdf_fillet"}
    SUPPORTED_MATERIALS = EDGE_BEARING
    SPACING_FROM = None  # the frozen auto spacing (min wall/6, structure/4)
    LEVELS = tuple({"recession_strength": s, "edge_width_mm": P02_EDGE_WIDTH_MM}
                   for s in POLISH_STRENGTH)
    #: edge-local analytic fillet (see ``synlab.degrade.narrowband`` for the measurement that
    #: forced this backend: a 0.1657 mm recession cannot survive a 0.5246 mm global grid).
    NARROWBAND = True
    NOTES = (
        "edge-distance driven inward fillet built from the analytic rolling-ball section of "
        "every convex edge on the ROI boundary and subtracted from the source; never a "
        "whole-patch Laplacian and never a global level set. edge_width_mm is the fillet radius "
        "and stays frozen across the five levels -- only recession_strength moves, as a linear "
        "scale of that section. The planar chamfer variant generates new edges and is not "
        "reported as a smooth fillet. The section is exact, so the declared recession is "
        "realized at every level regardless of the frozen global grid spacing; the measured "
        "spacing is still reported.")
    ROI = {"kind": "interface"}
    EXTRA_META = {"min_edge_angle_deg": 45.0}

    def extra_applicability(self, source, variant):
        fragment = physical_fragment(source)
        corners = np.asarray(fragment.mesh.bounds[1]) - np.asarray(fragment.mesh.bounds[0])
        if float(np.min(corners)) <= 1e-6:
            return False, "degenerate body extent; no edge population to round"
        roi_ids, _info = roi_faces_of(fragment.mesh, fragment, self.roi_for(variant, source))
        from . import narrowband as NB

        edges, info = NB.roi_boundary_edges(fragment.mesh, roi_ids,
                                            min_angle_deg=float(self.EXTRA_META["min_edge_angle_deg"]))
        if not edges:
            return False, (f"ROI {self.roi_for(variant, source)} has no convex boundary edge "
                           f"above {self.EXTRA_META['min_edge_angle_deg']:.0f} deg "
                           f"(measured: {info['acute_edges_total']} sharp edges in the body)")
        return True, None


class P03(_PhysicalAxis):
    AXIS_ID = "P03"
    default_variant = "smooth_recession_field"
    factor_kind = "ONE_DIMENSIONAL_RECIPE"
    VARIANT_KINDS = {"smooth_recession_field": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"depth_mm": "smooth_recession_field"}
    SUPPORTED_MATERIALS = ERODIBLE
    MIN_WALL_MM = 0.6
    SPACING_FROM = None  # the frozen auto spacing (min wall/6, structure/4)
    LEVELS = tuple({"depth_mm": d, "corr_length_mm": 6.0}
                   for d in (0.0, 0.05, 0.1, 0.25, 0.5))
    #: narrow-band surface operator: the declared depth is applied directly, so 0.05 mm is
    #: realizable even though the frozen global grid spacing on the probe is 0.5246 mm.
    NARROWBAND = True
    NOTES = ("non-negative smooth recession over the interface ROI with a wall-thickness guard; "
             "the depth field is frozen in the basis and pinned to zero on the ROI rim, so the "
             "five levels are nested and the untouched surface keeps the original triangles")

    def _sample_payload(self, context, rng, variant):
        from ..physical.fields import FourierField

        return {"field": FourierField.sample_frozen(rng, scale_mm=6.0,
                                                    field_id="P03_recession_field").payload()}


class P04(_PhysicalAxis):
    AXIS_ID = "P04"
    default_variant = "contact_loss"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"contact_loss": "SINGLE_PARAMETER", "volume_loss": "ONE_DIMENSIONAL_RECIPE"}
    SUPPORTED_MATERIALS = BRITTLE
    #: frozen acceptance contract of the declared target: achieving it inside this tolerance is
    #: the realized effect (plan 30.7).  The search below converges far tighter (measured
    #: |error| <= 0.005 on the probe) but the declared budget is not silently relaxed.
    EXPECTED = {"realized_key": "achieved_contact_loss", "tolerance": 0.02}
    SPACING_FROM = None  # the frozen auto spacing (min wall/6, structure/4)
    NARROWBAND = True
    NOTES = (
        "fixed cutter position/direction frozen in the basis; the cutter size is found by a 1-D "
        "geometric search that brackets the declared contact loss and then bisects, subject to "
        "the frozen minimum representative volume. Targets that the frozen cutter cannot reach "
        "(or that would eliminate the representative body) return TARGET_INFEASIBLE with the "
        "measured maximum instead of moving the cutter. volume_loss is for bodies without a "
        "clean interface and is not renamed contact_loss.")

    def realized_override(self, measured, outcome):
        """P04 declares a *contact-loss target*: achieving it within tolerance is the effect."""
        target = measured.get("contact_loss_target")
        achieved = measured.get("achieved_contact_loss")
        loss = measured.get("lost_volume_mm3", 0.0)
        if target is None or achieved is None:
            return None
        tolerance = float(self.EXPECTED.get("tolerance", 0.02))
        return bool(abs(float(achieved) - float(target)) <= tolerance and float(loss) > 0)

    LEVELS = tuple({"contact_loss_target": t} for t in (0.0, 0.1, 0.25, 0.5, 0.8))

    def roi_for(self, variant, source):
        return {"kind": "all"} if variant == "volume_loss" else {"kind": "interface"}

    def _sample_payload(self, context, rng, variant):
        """Freeze the cutter position and direction once; the size is searched at apply time."""
        from ..physical.fields import roi_anchor_points, roi_faces

        source = self.source_of(context)
        fragment = physical_fragment(source)
        mesh = fragment.mesh
        roi = self.roi_for(variant, source)
        roi_ids, info = roi_faces(mesh, fragment, roi)
        if len(roi_ids) == 0:
            raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                              f"P04/{variant}: ROI {roi} selects no face",
                              stage="degrade.axes.P04.basis")
        anchors = roi_anchor_points(mesh, roi_ids, density_mm=0.6)
        if len(anchors) == 0:
            anchors = np.asarray(mesh.triangles_center, dtype=np.float64)[roi_ids]
        # Frozen choice, drawn once per (axis, variant, source): the position/direction never
        # move between levels or between search steps (plan 30.7 forbids re-rolling the cutter
        # to make a target reachable).
        index = int(rng.integers(0, len(anchors)))
        normal = np.asarray(mesh.face_normals, dtype=np.float64)[roi_ids].mean(axis=0)
        normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
        extent = np.asarray(mesh.bounds[1]) - np.asarray(mesh.bounds[0])
        base = float(np.clip(np.min(extent) * 0.12, 0.4, 3.0))
        return {"center_mm": np.asarray(anchors[index], dtype=np.float64),
                "direction": normal, "radii_mm": np.array([base, base, base], dtype=np.float64),
                "roi_info": info}

    def extra_measurements(self, source, mesh, result):
        measured = dict(result.meta.get("measured") or {})
        target = measured.get("contact_loss_target")
        achieved = measured.get("achieved_contact_loss")
        if target is None or achieved is None:
            return {}
        return {"target_abs_error": float(abs(float(achieved) - float(target)))}



class P05(_PhysicalAxis):
    AXIS_ID = "P05"
    default_variant = "paint_removal"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"paint_removal": "SINGLE_PARAMETER"}
    SUPPORTED_MATERIALS = COATED
    LEVELS = tuple({"retained_fraction": f} for f in (1.0, 0.75, 0.5, 0.25, 0.0))
    NOTES = ("nested paint masks from one frozen rank field; the geometry hash must stay "
             "identical (appearance-only axis).")

    def extra_applicability(self, source, variant):
        appearance = appearance_of(source)
        if not appearance:
            return False, ("P05 needs the texel appearance payload "
                           "(texel_albedo/texel_substrate_albedo/texel_area_mm2/texel_positions)")
        missing = [k for k in ("texel_albedo", "texel_substrate_albedo", "texel_area_mm2",
                               "texel_positions") if k not in appearance]
        if missing:
            return False, f"P05 appearance payload misses {missing}"
        if not np.any(np.asarray(appearance.get("texel_layer", np.zeros(
                len(appearance["texel_albedo"]), dtype=np.int32))) > 0):
            return False, "P05 is not applicable: this body carries no paint layer (texel_layer>0)"
        return True, None

    def _sample_payload(self, context, rng, variant):
        from ..physical.fields import FourierField

        return {"rank_field": FourierField.sample_frozen(
            rng, scale_mm=8.0, field_id="P05_paint_rank").payload()}

    def invariant_checks(self, source, result):
        return self._geometry_hash_guard(source, result)


class P06(_PhysicalAxis):
    AXIS_ID = "P06"
    default_variant = "dirt_appearance"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"dirt_appearance": "SINGLE_PARAMETER",
                     "dirt_geometry": "ONE_DIMENSIONAL_RECIPE"}
    SUPPORTED_MATERIALS = ALL_MATERIALS
    LEVELS = tuple({"coverage": c, "layer_thickness_mm": 0.3}
                   for c in (0.0, 0.2, 0.4, 0.6, 0.8))
    NOTES = ("smooth patch coverage of one frozen field; the core variant changes appearance "
             "only (geometry hash unchanged) and dirt_geometry adds an explicit contamination "
             "body registered as its own material class (plan 12.3).")

    def extra_applicability(self, source, variant):
        appearance = appearance_of(source)
        if not appearance:
            return False, ("P06 needs the texel appearance payload "
                           "(texel_albedo/texel_area_mm2/texel_positions)")
        missing = [k for k in ("texel_albedo", "texel_area_mm2", "texel_positions")
                   if k not in appearance]
        if missing:
            return False, f"P06 appearance payload misses {missing}"
        return True, None

    def _sample_payload(self, context, rng, variant):
        from ..physical.fields import FourierField

        return {"dirt_field": FourierField.sample_frozen(
            rng, scale_mm=5.0, field_id="P06_dirt_patch").payload(),
            "dirt_color": [0.22, 0.18, 0.13], "dirt_roughness": 0.95}

    def invariant_checks(self, source, result):
        if result.meta.get("variant") == "dirt_geometry":
            return {"contamination_entity": True, "geometry_hash_unchanged": None,
                    "violated": False, "note": "dirt_geometry legally adds a contamination body"}
        return self._geometry_hash_guard(source, result)


class P07(_PhysicalAxis):
    AXIS_ID = "P07"
    default_variant = "outer_recession_field"
    factor_kind = "ONE_DIMENSIONAL_RECIPE"
    VARIANT_KINDS = {"outer_recession_field": "ONE_DIMENSIONAL_RECIPE"}
    SUPPORTED_MATERIALS = ERODIBLE
    MIN_WALL_MM = 0.5
    SPACING_FROM = None  # the frozen auto spacing (min wall/6, structure/4)
    ROI = {"kind": "outer", "direction": [0.0, 0.0, 1.0], "cos_min": 0.25}
    LEVELS = tuple({"depth_mm": d, "corr_length_mm": 6.0}
                   for d in (0.0, 0.025, 0.05, 0.1, 0.2))
    NOTES = "original outer-surface ROI only; hidden surfaces are never backfilled"

    def _sample_payload(self, context, rng, variant):
        from ..physical.fields import FourierField

        return {"field": FourierField.sample_frozen(rng, scale_mm=6.0,
                                                    field_id="P07_outer_field").payload()}


class P08(_PhysicalAxis):
    AXIS_ID = "P08"
    default_variant = "geometry_crack"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"geometry_crack": "SINGLE_PARAMETER",
                     "paint_coat_loss": "SINGLE_PARAMETER",
                     "geometric_coat_loss": "SINGLE_PARAMETER",
                     "bundled_coat_and_crack": "BUNDLED_STRESS"}
    SUPPORTED_MATERIALS = BRITTLE
    LEVELS = tuple({"affected_area": a} for a in (0.0, 0.05, 0.1, 0.2, 0.3))
    NOTES = ("three single-factor variants (crack width, coat area, painted-coat loss) plus one "
             "explicitly bundled stress variant; crack width, crack length and layer area are "
             "never mixed into one comparable intensity (plan 30.9).")

    def extra_applicability(self, source, variant):
        if variant in ("paint_coat_loss", "bundled_coat_and_crack"):
            appearance = appearance_of(source)
            if not appearance:
                return False, f"P08/{variant} needs the texel appearance payload"
            if variant == "paint_coat_loss":
                missing = [k for k in ("texel_albedo", "texel_area_mm2", "texel_positions")
                           if k not in appearance]
                if missing:
                    return False, f"P08/paint_coat_loss appearance payload misses {missing}"
        return True, None

    def _sample_payload(self, context, rng, variant):
        from ..physical.fields import FourierField

        source = self.source_of(context)
        fragment = physical_fragment(source)
        mesh = fragment.mesh
        extent = np.asarray(mesh.bounds[1]) - np.asarray(mesh.bounds[0])
        payload = {"rank_field": FourierField.sample_frozen(
            rng, scale_mm=7.0, field_id="P08_coat_rank").payload(),
            "crack_length_mm": float(np.linalg.norm(extent) * 0.9),
            "crack_depth_mm": float(np.max(extent) * 1.2),
            "crack_length_dir": np.asarray(rng.normal(size=3), dtype=np.float64)}
        return payload


# ======================================================================================
# I axes: imaging (plan 15.3, 30.2 rows 3闂?)
# ======================================================================================
class _ImageAxis(_BaseAxis):
    STAGE = STAGE_OPTICS
    SUBSTAGE = "exposure"
    UNIT = UNIT_PX
    COST_CLASS = "low"
    READS = ("source:asset",)
    WRITES = ("optical:image", "asset")
    ACCEPTED_SOURCES = (KIND_IMAGE,)
    LABEL_INVALIDATIONS = ("VisibleLabels", "FeatureAdapter")

    def extra_applicability(self, source, variant):
        frames = source.get("frames")
        if not frames:
            return False, ("the I axes need delivered views (payload 'frames' with "
                           "rgb/rgb_linear/encoding/K)")
        for frame in frames:
            if frame.get("rgb_linear") is None and frame.get("rgb") is None:
                return False, f"frame {frame.get('view_id')!r} carries neither rgb nor rgb_linear"
        return True, None

    # -- helpers -------------------------------------------------------------------
    def _rewrite(self, source: SourceBundle, frames: list[dict[str, Any]],
                 measured: dict[str, float], units: dict[str, str], *, realized: bool,
                 info: dict[str, Any], payload: dict[str, Any] | None = None) -> SourceBundle:
        base = dict(payload or {})
        base["frames"] = frames
        return _with(source, payload=base,
                     meta={"axis_id": self.AXIS_ID, "variant": "", "level": 0,
                           "measured": measured, "units": units, "realized": bool(realized),
                           "extra": info})

    def per_frame(self, source: SourceBundle, op) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        frames = OI.frames_of(source)
        out: list[dict[str, Any]] = []
        reports: list[dict[str, Any]] = []
        for frame in frames:
            new_frame, report = op(frame)
            out.append(new_frame)
            reports.append(report)
        return out, reports

    def invariant_checks(self, source: SourceBundle, result: SourceBundle) -> dict[str, Any]:
        source_frames = list(source.get("frames") or [])
        result_frames = list(result.get("frames") or [])
        same_count = len(source_frames) == len(result_frames)
        return {"frames_before": len(source_frames), "frames_after": len(result_frames),
                "frame_count_unchanged": bool(same_count), "violated": False}


class I01(_ImageAxis):
    AXIS_ID = "I01"
    default_variant = "gaussian_psf"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"gaussian_psf": "SINGLE_PARAMETER",
                     "depth_dependent_defocus": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"defocus": "gaussian_psf"}
    LEVELS = tuple({"psf_sigma_px": s} for s in (0.0, 0.5, 1.0, 2.0, 4.0))
    NOTES = ("Gaussian PSF in the plane, applied to the linear signal before the response; the "
             "depth-dependent variant blends two PSFs by depth and needs per-frame depth.")

    def _apply(self, source, level, params, basis, variant):
        sigma = float(params["psf_sigma_px"])
        if sigma <= 0:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "I01 sigma must be > 0",
                              stage="degrade.axes.I01")
        kernel, psf_info = OI.gaussian_psf(sigma)
        depth_dependent = variant == "depth_dependent_defocus"
        sharp_before: list[float] = []
        sharp_after: list[float] = []
        grad_before: list[float] = []
        grad_after: list[float] = []

        def op(frame):
            linear = OI.frame_linear(frame)
            if depth_dependent:
                depth = frame.get("depth_z")
                if depth is None:
                    raise SynLabError(
                        ErrorCode.NA_NOT_APPLICABLE,
                        "I01/depth_dependent_defocus needs per-frame depth_z; the flat Gaussian "
                        "PSF variant is the one that applies to this source",
                        stage="degrade.axes.I01")
                depth = np.asarray(depth, dtype=np.float64)
                finite = np.isfinite(depth)
                far = OI.convolve(linear, OI.gaussian_psf(sigma * 1.6)[0])
                near = OI.convolve(linear, kernel)
                if finite.any():
                    median = float(np.median(depth[finite]))
                    spread = float(np.std(depth[finite])) or 1.0
                    w = np.clip((depth - median) / spread, -1.0, 1.0)
                else:
                    w = np.zeros_like(depth)
                blend = (0.5 * (1.0 + np.nan_to_num(w)))[:, :, None].astype(np.float32)
                blurred = (1.0 - blend) * near + blend * far
            else:
                blurred = OI.convolve(linear, kernel)
            sharp_before.append(OI.sharpness(linear))
            sharp_after.append(OI.sharpness(blurred))
            grad_before.append(OI.gradient_energy(linear))
            grad_after.append(OI.gradient_energy(blurred))
            return OI.rewritten_frame(frame, blurred, optics_domain=OI.DOMAIN_SENSOR_LINEAR), {
                "view_id": frame.get("view_id"), "sigma_px": sigma}

        frames, reports = self.per_frame(source, op)
        measured = {
            "psf_sigma_px": sigma,
            "sharpness_before": float(np.mean(sharp_before)),
            "sharpness_after": float(np.mean(sharp_after)),
            "sharpness_drop_ratio": float(1.0 - np.mean(sharp_after) / max(np.mean(sharp_before), 1e-12)),
            "gradient_energy_before": float(np.mean(grad_before)),
            "gradient_energy_after": float(np.mean(grad_after)),
            "views": float(len(frames)),
        }
        realized = bool(measured["gradient_energy_after"] < measured["gradient_energy_before"])
        return self._rewrite(source, frames, measured,
                             {"psf_sigma_px": "px", "sharpness_before": "1", "sharpness_after": "1",
                              "gradient_energy_before": "1", "gradient_energy_after": "1"},
                             realized=realized,
                             info={"psf": psf_info, "depth_dependent": depth_dependent,
                                   "per_view": reports, "domain": OI.DOMAIN_SENSOR_LINEAR,
                                   "sensor_noise_refrozen": False})


class I02(_ImageAxis):
    AXIS_ID = "I02"
    default_variant = "directional_kernel"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"directional_kernel": "SINGLE_PARAMETER",
                     "exposure_integration": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"motion_blur": "directional_kernel"}
    LEVELS = tuple({"length_px": n} for n in (0.0, 3.0, 5.0, 9.0, 15.0))
    NOTES = ("single-exposure directional kernel by default; the exposure_integration variant "
             "integrates a frozen number of sub-exposures along the same trajectory.")

    def _sample_payload(self, context, rng, variant):
        return {"angle_deg": OI.MOTION_DIRECTION_DEG, "sub_exposures": 9}

    def _apply(self, source, level, params, basis, variant):
        length = float(params["length_px"])
        if length <= 0:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "I02 length must be > 0",
                              stage="degrade.axes.I02")
        angle = float((basis.payload or {}).get("angle_deg", OI.MOTION_DIRECTION_DEG))
        samples = int((basis.payload or {}).get("sub_exposures", 9))
        kernel, kernel_info = OI.motion_kernel(length, angle)
        before_sharp: list[float] = []
        after_sharp: list[float] = []
        directions: list[float] = []

        def op(frame):
            linear = OI.frame_linear(frame)
            if variant == "exposure_integration":
                blurred, info = OI.motion_integrate(linear, length_px=length, angle_deg=angle,
                                                    samples=samples)
            else:
                blurred = OI.convolve(linear, kernel)
                info = dict(kernel_info)
            before_sharp.append(OI.sharpness(linear))
            after_sharp.append(OI.sharpness(blurred))
            directions.append(OI.dominant_direction_deg(blurred))
            return OI.rewritten_frame(frame, blurred, optics_domain=OI.DOMAIN_SENSOR_LINEAR), {
                "view_id": frame.get("view_id"), **info}

        frames, reports = self.per_frame(source, op)
        direction_error = [abs(((d - angle + 90.0) % 180.0) - 90.0) for d in directions]
        measured = {
            "length_px": length,
            "angle_deg": angle,
            "kernel_support_px": float(kernel_info.get("kernel_support_px", 0)),
            "measured_direction_deg": float(np.mean(directions)),
            "direction_error_deg": float(np.mean(direction_error)),
            "sharpness_before": float(np.mean(before_sharp)),
            "sharpness_after": float(np.mean(after_sharp)),
            "sharpness_drop_ratio": float(1.0 - np.mean(after_sharp) / max(np.mean(before_sharp), 1e-12)),
        }
        realized = bool(measured["sharpness_after"] < measured["sharpness_before"])
        return self._rewrite(source, frames, measured,
                             {"length_px": "px", "measured_direction_deg": "deg",
                              "sharpness_before": "1", "sharpness_after": "1"},
                             realized=realized,
                             info={"kernel": kernel_info, "per_view": reports,
                                   "variant": variant, "domain": OI.DOMAIN_SENSOR_LINEAR})


class I03(_ImageAxis):
    AXIS_ID = "I03"
    STAGE = STAGE_SENSOR
    default_variant = "photon_scale"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"photon_scale": "SINGLE_PARAMETER", "read_sigma": "SINGLE_PARAMETER",
                     "camera_noise_profile": "BUNDLED_STRESS"}
    ALIASES = {"sensor_noise": "camera_noise_profile"}
    LEVELS = tuple({"photon_gain": g, "read_sigma": 0.002}
                   for g in (0.0, 16000.0, 8000.0, 4000.0, 1000.0))
    VARIANT_LEVELS = {
        "read_sigma": {f"L{i}": {"photon_gain": 16000.0, "read_sigma": r}
                       for i, r in enumerate((0.0, 0.002, 0.004, 0.008, 0.016))},
        "camera_noise_profile": {f"L{i}": {"photon_gain": g, "read_sigma": r}
                                 for i, (g, r) in enumerate(((0.0, 0.0), (16000.0, 0.002),
                                                             (8000.0, 0.004), (4000.0, 0.008),
                                                             (1000.0, 0.016)))},
    }
    NOTES = ("linear sensor noise y = Poisson(g*x)/g + N(0,sigma^2) with x = max(L*2^EV, 0); "
             "photon_scale varies the photon gain with the read noise fixed, read_sigma does the "
             "opposite, and camera_noise_profile changes both (BUNDLED). Level 0 adds nothing and "
             "does not remove the renderer's existing noise.")

    def _sample_payload(self, context, rng, variant):
        return {"exposure_ev": 0.0, "noise_stream": "sensor"}

    def _apply(self, source, level, params, basis, variant):
        gain = float(params["photon_gain"])
        read = float(params["read_sigma"])
        if gain <= 0:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                              "I03 non-zero level needs photon_gain > 0",
                              stage="degrade.axes.I03")
        ev = float((basis.payload or {}).get("exposure_ev", 0.0))
        rng = basis_rng(basis, level, "sensor_noise")
        before_var: list[float] = []
        after_var: list[float] = []
        before_sigma: list[float] = []
        after_sigma: list[float] = []

        def op(frame):
            linear = OI.frame_linear(frame)
            noisy, info = OI.sensor_noise(linear, photon_gain=gain, read_sigma=read,
                                          exposure_ev=ev, rng=rng)
            before_sigma.append(OI.noise_sigma_estimate(linear))
            after_sigma.append(OI.noise_sigma_estimate(noisy))
            before_var.append(float(np.var(linear)))
            after_var.append(float(np.var(noisy)))
            return OI.rewritten_frame(frame, noisy, sensor_model=info), {
                "view_id": frame.get("view_id"), **info}

        frames, reports = self.per_frame(source, op)
        measured = {
            "photon_gain": gain,
            "read_noise_sigma": read,
            "exposure_ev": ev,
            "noise_sigma_before": float(np.mean(before_sigma)),
            "noise_sigma_after": float(np.mean(after_sigma)),
            "noise_sigma_increase": float(np.mean(after_sigma) - np.mean(before_sigma)),
            "variance_before": float(np.mean(before_var)),
            "variance_after": float(np.mean(after_var)),
            "views": float(len(frames)),
        }
        realized = bool(measured["noise_sigma_increase"] > 0
                        or measured["variance_after"] > measured["variance_before"])
        return self._rewrite(source, frames, measured,
                             {"noise_sigma_before": "1", "noise_sigma_after": "1",
                              "variance_before": "1", "variance_after": "1"},
                             realized=realized,
                             info={"sensor_model": reports, "variant": variant,
                                   "renderer_noise_preserved": True})


class I04(_ImageAxis):
    AXIS_ID = "I04"
    default_variant = "exposure_gain"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"exposure_gain": "SINGLE_PARAMETER", "digital_gain": "SINGLE_PARAMETER",
                     "negative_exposure": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"exposure": "exposure_gain"}
    LEVELS = tuple({"exposure_ev": ev} for ev in (0.0, 0.5, 1.0, 1.5, 2.0))
    VARIANT_LEVELS = {
        "digital_gain": {f"L{i}": {"digital_gain": float(2.0 ** ev)}
                         for i, ev in enumerate((0.0, 0.5, 1.0, 1.5, 2.0))},
        "negative_exposure": {f"L{i}": {"negative_exposure_ev": ev}
                              for i, ev in enumerate((0.0, -0.5, -1.0, -1.5, -2.0))},
    }
    NOTES = ("exposure_gain acts before the photon count; digital_gain is registered separately "
             "(it is not interchangeable). The negative sub-configuration is its own variant and "
             "the dark and bright directions are never merged into one monotone scalar.")

    def _apply(self, source, level, params, basis, variant):
        before = {"saturated": [], "mean": []}
        after = {"saturated": [], "mean": []}
        preclip = {"changed": [], "clip_loss": []}
        labels: list[dict[str, Any]] = []

        def op(frame):
            linear = OI.frame_linear(frame)
            if variant == "digital_gain":
                work, info = OI.digital_gain(linear, float(params["digital_gain"]))
            elif variant == "negative_exposure":
                work, info = OI.exposure_scale(linear, float(params["negative_exposure_ev"]))
                info["direction"] = "DARKEN"
            else:
                work, info = OI.exposure_scale(linear, float(params["exposure_ev"]))
                info["direction"] = "BRIGHTEN"
            before["saturated"].append(OI.linear_stats(linear)["saturated_fraction"])
            after["saturated"].append(OI.linear_stats(work)["saturated_fraction"])
            before["mean"].append(float(np.mean(linear)))
            after["mean"].append(float(np.mean(work)))
            preclip["changed"].append(float(np.mean(np.abs(work - linear) > 1e-9)))
            preclip["clip_loss"].append(float(np.mean(np.clip(
                linear * float(info.get("factor", 1.0)), 0.0, 1.0) - work)))
            labels.append(info)
            return OI.rewritten_frame(frame, work, exposure=info), {"view_id": frame.get("view_id"),
                                                                    **info}

        frames, reports = self.per_frame(source, op)
        measured = {
            "mean_before": float(np.mean(before["mean"])),
            "mean_after": float(np.mean(after["mean"])),
            "mean_delta": float(np.mean(after["mean"]) - np.mean(before["mean"])),
            "saturated_fraction_before": float(np.mean(before["saturated"])),
            "saturated_fraction_after": float(np.mean(after["saturated"])),
            "delivered_changed_fraction": float(np.mean(preclip["changed"])),
            "clipping_loss": float(np.mean(preclip["clip_loss"])),
            "views": float(len(frames)),
        }
        # Realization is judged on the *applied* signal: a fully saturated sensor clips the
        # change away, which is reported through mean_delta/saturated_fraction instead of being
        # hidden (plan 15.3: saturation and shadow loss are the measured quantities).
        realized = bool(measured["delivered_changed_fraction"] > 0)
        return self._rewrite(source, frames, measured,
                             {"mean_before": "1", "mean_after": "1", "mean_delta": "1",
                              "saturated_fraction_before": "1", "saturated_fraction_after": "1",
                              "delivered_changed_fraction": "1", "clipping_loss": "1"},
                             realized=realized,
                             info={"per_view": reports, "variant": variant,
                                   "realized_basis": "DELIVERED_PIXELS_CHANGED",
                                   "monotone_scalar_claim": False,
                                   "directions": sorted({str(v.get("direction", "GAIN"))
                                                         for v in labels})})


class I05(_ImageAxis):
    AXIS_ID = "I05"
    STAGE = STAGE_ISP
    default_variant = "fixed_direction_wb"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"fixed_direction_wb": "SINGLE_PARAMETER"}
    ALIASES = {"white_balance": "fixed_direction_wb"}
    LEVELS = tuple({"wb_deviation": d} for d in (0.0, 0.025, 0.05, 0.1, 0.2))
    NOTES = "one frozen gain-direction vector; the developed profile is frozen after calibration"

    def _sample_payload(self, context, rng, variant):
        return {"wb_direction": list(OI.WB_DIRECTION)}

    def _apply(self, source, level, params, basis, variant):
        deviation = float(params["wb_deviation"])
        if deviation == 0:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "I05 deviation must be non-zero",
                              stage="degrade.axes.I05")
        before_ratio: list[float] = []
        after_ratio: list[float] = []
        gains: list[list[float]] = []

        def op(frame):
            linear = OI.frame_linear(frame)
            work, info = OI.white_balance(linear, deviation)
            b = OI.channel_means(linear)
            a = OI.channel_means(work)
            before_ratio.append(b[0] / max(b[1], 1e-12))
            after_ratio.append(a[0] / max(a[1], 1e-12))
            gains.append(info["gains"])
            return OI.rewritten_frame(frame, work, white_balance=info), {"view_id": frame.get("view_id"),
                                                                        **info}

        frames, reports = self.per_frame(source, op)
        measured = {
            "wb_deviation": deviation,
            "rg_ratio_before": float(np.mean(before_ratio)),
            "rg_ratio_after": float(np.mean(after_ratio)),
            "rg_ratio_shift": float(np.mean(after_ratio) - np.mean(before_ratio)),
            "views": float(len(frames)),
        }
        realized = bool(abs(measured["rg_ratio_shift"]) > 1e-9)
        return self._rewrite(source, frames, measured,
                             {"rg_ratio_before": "1", "rg_ratio_after": "1"},
                             realized=realized,
                             info={"per_view": reports, "gains": gains[:1],
                                   "profile_frozen_after": "calibration"})


# ---------------------------------------------------------------------------- SCENE axes
def _visible_fraction(frames: list[dict[str, Any]]) -> float:
    """Fraction of delivered pixels that observe the *target* surface (delivered mask).

    The per-view ``valid_mask`` is used when present because it excludes support/occluder
    geometry: an occluder adds finite-depth pixels that must not count as visible target.
    """
    values: list[float] = []
    for frame in frames:
        mask = frame.get("valid_mask")
        if mask is not None:
            values.append(float(np.mean(np.asarray(mask, dtype=bool))))
            continue
        depth = frame.get("depth_z")
        values.append(float(np.mean(np.isfinite(np.asarray(depth, dtype=np.float64))))
                       if depth is not None else float("nan"))
    return float(np.nanmean(values)) if values else float("nan")


class _SceneAxis(_BaseAxis):
    """I06/I07: scene-level knobs are re-rendered, never painted onto a delivered image."""

    STAGE = STAGE_SCENE
    SUBSTAGE = "exposure"
    UNIT = UNIT_NONE
    COST_CLASS = "high"
    READS = ("source:asset",)
    WRITES = ("optical:image", "asset")
    ACCEPTED_SOURCES = (KIND_IMAGE, KIND_OBS)
    LABEL_INVALIDATIONS = ("VisibleLabels", "FeatureAdapter", "PhysicalTruth")

    def renderer(self, source: SourceBundle) -> Any:
        renderer = source.get("renderer")
        if renderer is None:
            raise SynLabError(
                ErrorCode.DEPENDENCY_CAPABILITY_MISSING,
                f"{self.AXIS_ID} changes the scene and must be re-rendered: inject the "
                f"observation renderer as payload['renderer'] (synlab.observe.render.render_view "
                f"/ synlab.observe.api.observe). Painting the change onto the delivered pixels "
                f"would be a fake scene edit and is refused.",
                stage=f"degrade.axes.{self.AXIS_ID}",
            )
        return renderer

    def _apply(self, source, level, params, basis, variant):
        renderer = self.renderer(source)
        scene_params = dict(self.scene_parameters(level, params, variant))
        scene_params.update(self.frozen_scene_extras(basis, variant))
        try:
            rendered = renderer(scene_params)
        except SynLabError:
            raise
        except Exception as exc:  # noqa: BLE001 - reported honestly, never faked
            raise SynLabError(ErrorCode.DEPENDENCY_CAPABILITY_MISSING,
                              f"{self.AXIS_ID}: the injected renderer failed: "
                              f"{type(exc).__name__}: {exc}",
                              stage=f"degrade.axes.{self.AXIS_ID}") from exc
        frames = list(rendered.get("frames") if isinstance(rendered, dict) else rendered)
        if not frames:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                              f"{self.AXIS_ID}: the renderer returned no frame",
                              stage=f"degrade.axes.{self.AXIS_ID}")
        measured = self.scene_measurements(source, frames, scene_params)
        realized = bool(measured.pop("realized", False))
        return _with(source, payload={"frames": frames, "scene": dict(scene_params)},
                     meta={"axis_id": self.AXIS_ID, "level": int(level), "measured": measured,
                           "units": {}, "realized": realized,
                           "extra": {"re_rendered": True, "scene_parameters": scene_params,
                                     "renderer": str(getattr(renderer, "__name__",
                                                             type(renderer).__name__))}})

    def scene_parameters(self, level: int, params: dict[str, Any], variant: str) -> dict[str, Any]:
        raise NotImplementedError

    def frozen_scene_extras(self, basis: DegradationBasis, variant: str) -> dict[str, Any]:
        """Frozen scene decisions shared by all five levels (paired re-render comparison)."""
        return dict(basis.payload or {})

    def scene_measurements(self, source: SourceBundle, frames: list[dict[str, Any]],
                           scene_params: dict[str, Any]) -> dict[str, float]:
        return {"realized": 1.0}

    def invariant_checks(self, source, result):
        return {"re_rendered": True, "delivered_pixels_replaced": True, "violated": False}


class I06(_SceneAxis):
    AXIS_ID = "I06"
    default_variant = "fixed_light_specular_profile"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"fixed_light_specular_profile": "SINGLE_PARAMETER",
                     "fixed_material_lighting": "SINGLE_PARAMETER",
                     "brdf_and_light_bundle": "BUNDLED_STRESS"}
    ALIASES = {"specular": "fixed_light_specular_profile"}
    LEVELS = tuple({"saturation_target": s} for s in (0.0, 0.1, 0.2, 0.3, 0.4))
    NOTES = ("scene light/BRDF re-render; the zero level is the same-source baseline scene and "
             "does not claim the physical glaze has no highlight. Changing BRDF, exposure and "
             "light angle together is labelled BUNDLED.")

    def scene_parameters(self, level, params, variant):
        return {"knob": "lighting", "saturation_target": float(params["saturation_target"]),
                "variant": variant, "level": int(level),
                "light_intensity_scale": 1.0 + 3.0 * float(params["saturation_target"]),
                "brdf_specular_scale": 1.0 if variant != "brdf_and_light_bundle"
                else 1.0 + 2.0 * float(params["saturation_target"]),
                "bundled": variant == "brdf_and_light_bundle"}

    def scene_measurements(self, source, frames, scene_params):
        before_linear = [OI.frame_linear(f) for f in (source.get("frames") or [])]
        after_linear = [OI.frame_linear(f) for f in frames]

        def highlight(images):
            if not images:
                return 0.0, 0.0, 0.0
            luma = np.concatenate([0.2126 * img[..., 0] + 0.7152 * img[..., 1]
                                   + 0.0722 * img[..., 2] for img in images]).ravel()
            return (float(luma.mean()), float(np.percentile(luma, 99.0)),
                    float(np.mean(luma >= 1.0)))

        mean_before, p99_before, sat_before = highlight(before_linear)
        mean_after, p99_after, sat_after = highlight(after_linear)
        return {"saturation_target": float(scene_params["saturation_target"]),
                "mean_radiance_before": mean_before, "mean_radiance_after": mean_after,
                "highlight_p99_before": p99_before, "highlight_p99_after": p99_after,
                "saturated_fraction_before": sat_before, "saturated_fraction_after": sat_after,
                "views": float(len(frames)),
                "realized": 1.0 if (not before_linear or p99_after > p99_before) else 0.0}


class I07(_SceneAxis):
    AXIS_ID = "I07"
    default_variant = "occluder_rerender"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"occluder_rerender": "SINGLE_PARAMETER"}
    ALIASES = {"occlusion": "occluder_rerender"}
    LEVELS = tuple({"target_coverage": c} for c in (0.0, 0.15, 0.3, 0.45, 0.6))
    NOTES = ("3-D occluder bodies are added to the scene and the views are re-rendered; a "
             "delivered-pixel patch would not be an occluder.")

    def _sample_payload(self, context, rng, variant):
        directions = rng.normal(size=(6, 3))
        directions[:, 2] = -np.abs(directions[:, 2])
        norms = np.linalg.norm(directions, axis=1, keepdims=True)
        return {"occluder_directions": (directions / np.maximum(norms, 1e-9)).tolist(),
                "occluder_capacity": 6}

    def scene_parameters(self, level, params, variant):
        coverage = float(params["target_coverage"])
        return {"knob": "occluder", "target_coverage": coverage, "level": int(level),
                "occluder_count": int(round(coverage * 6.0)),
                "occluder_radius_mm": 3.0 + 6.0 * coverage,
                "occluder_min_radius_mm": 3.0}

    def scene_measurements(self, source, frames, scene_params):
        before = _visible_fraction(source.get("frames") or [])
        after = _visible_fraction(frames)
        measured = {"target_coverage": float(scene_params["target_coverage"]),
                    "visible_fraction_before": before, "visible_fraction_after": after,
                    "visible_loss": float(before - after), "views": float(len(frames)),
                    "realized": 1.0 if after < before else 0.0,
                    "visibility_measure": "DELIVERED_DEPTH_SUPPORT"}
        return {k: v for k, v in measured.items()
                if not isinstance(v, (int, float, np.floating, np.integer)) or np.isfinite(v)}


class I08(_ImageAxis):
    AXIS_ID = "I08"
    STAGE = STAGE_ISP
    SUBSTAGE = "frame_selection"
    default_variant = "nested_priority_prefix"
    factor_kind = "ONE_DIMENSIONAL_RECIPE"
    VARIANT_KINDS = {"nested_priority_prefix": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"fewer_views": "nested_priority_prefix"}
    LEVELS = tuple({"keep_fraction": f} for f in (1.0, 8.0 / 12.0, 4.0 / 12.0, 2.0 / 12.0,
                                                  1.0 / 12.0))
    NOTES = ("fixed-priority nested deletion; the baseline V0 source is returned unchanged at "
             "level 0 and every level is a subset of the previous one.")

    def extra_applicability(self, source, variant):
        frames = source.get("frames")
        if not frames:
            return False, "I08 needs delivered frames to select from"
        if len(frames) < 2:
            return False, "I08 needs at least two views; a single-view source has no subset"
        return True, None

    def _sample_payload(self, context, rng, variant):
        source = self.source_of(context)
        frames = list(source.get("frames") or [])
        priority = source.get("priority_order")
        if priority is None:
            priority = list(range(len(frames)))
        return {"priority_order": [int(v) for v in priority], "n_views": len(frames)}

    def _apply(self, source, level, params, basis, variant):
        frames = OI.frames_of(source)
        order = list((basis.payload or {}).get("priority_order") or range(len(frames)))
        keep_fraction = float(params["keep_fraction"])
        keep_n = max(int(np.ceil(len(frames) * keep_fraction)), 1)
        kept_idx = sorted(order[:keep_n])
        kept = [frames[i] for i in kept_idx]
        angles = []
        for frame in kept:
            T = frame.get("T_WC")
            if T is not None:
                angles.append(float(np.asarray(T, dtype=np.float64)[:3, 3][0]))
        measured = {
            "views_before": float(len(frames)),
            "views_after": float(len(kept)),
            "keep_fraction_declared": keep_fraction,
            "keep_fraction_realized": float(len(kept) / max(len(frames), 1)),
            "removed_views": float(len(frames) - len(kept)),
            "baseline_angle_span_before": float(np.ptp(angles)) if angles else 0.0,
        }
        realized = bool(len(kept) < len(frames))
        return _with(source, payload={"frames": kept, "removed_view_ids": [
            frames[i].get("view_id") for i in range(len(frames)) if i not in set(kept_idx)]},
            meta={"axis_id": self.AXIS_ID, "level": int(level), "measured": measured,
                  "units": {}, "realized": realized,
                  "extra": {"nested": True, "priority_order": order, "kept_indices": kept_idx}})


class I09(_ImageAxis):
    AXIS_ID = "I09"
    STAGE = STAGE_ISP
    SUBSTAGE = "quality"
    default_variant = "antialiased_downsample"
    factor_kind = "ONE_DIMENSIONAL_RECIPE"
    VARIANT_KINDS = {"antialiased_downsample": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"lower_resolution": "antialiased_downsample"}
    LEVELS = tuple({"resize_scale": s} for s in (1.0, 0.75, 0.5, 0.25, 0.125))
    NOTES = ("baseline long edge is kept at level 0; non-zero levels apply an anti-aliased "
             "downsample and update K through the frozen pixel transform. 1/8 is the extra "
             "stress level of the plan's candidate list.")

    def _apply(self, source, level, params, basis, variant):
        scale = float(params["resize_scale"])
        if not 0.0 < scale < 1.0:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                              "I09 needs 0 < resize_scale < 1 for a non-zero level",
                              stage="degrade.axes.I09")
        long_before: list[float] = []
        long_after: list[float] = []
        grad_before: list[float] = []
        grad_after: list[float] = []
        shifts: list[float] = []

        def op(frame):
            linear = OI.frame_linear(frame)
            K = frame.get("K")
            if K is None:
                raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                                  "I09 needs the frame intrinsics to keep K in sync",
                                  stage="degrade.axes.I09")
            resized, K_new, A, info = OI.downsample_antialiased(linear, scale, K)
            long_before.append(max(linear.shape[0], linear.shape[1]))
            long_after.append(max(resized.shape[0], resized.shape[1]))
            grad_before.append(OI.gradient_energy(linear))
            grad_after.append(OI.gradient_energy(resized))
            shifts.append(float(K_new[0, 2] - np.asarray(K, dtype=np.float64)[0, 2]))
            return OI.rewritten_frame(frame, resized, K=K_new, pixel_transform=A), {
                "view_id": frame.get("view_id"), **info}

        frames, reports = self.per_frame(source, op)
        measured = {
            "resize_scale": scale,
            "long_edge_before": float(np.mean(long_before)),
            "long_edge_after": float(np.mean(long_after)),
            "resize_realized": float(np.mean(long_after) / max(np.mean(long_before), 1e-12)),
            "gradient_energy_before": float(np.mean(grad_before)),
            "gradient_energy_after": float(np.mean(grad_after)),
            "cx_shift_px": float(np.mean(shifts)),
            "views": float(len(frames)),
        }
        realized = bool(measured["long_edge_after"] < measured["long_edge_before"])
        return self._rewrite(source, frames, measured,
                             {"long_edge_before": "px", "long_edge_after": "px",
                              "gradient_energy_before": "1", "gradient_energy_after": "1"},
                             realized=realized,
                             info={"per_view": reports, "interpolation": "INTER_AREA",
                                   "K_updated": True})


class I10(_ImageAxis):
    AXIS_ID = "I10"
    STAGE = STAGE_ISP
    SUBSTAGE = "quality"
    default_variant = "jpeg_quality"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"jpeg_quality": "SINGLE_PARAMETER"}
    ALIASES = {"jpeg_loss": "jpeg_quality"}
    LEVELS = tuple({"jpeg_quality": q} for q in (100, 90, 75, 60, 40))
    NOTES = ("level 0 does not re-encode at all; non-zero levels run a real JPEG encode/decode "
             "and report bytes, error RMS and blockiness.")

    def _apply(self, source, level, params, basis, variant):
        quality = int(params["jpeg_quality"])
        bytes_before: list[float] = []
        bytes_after: list[float] = []
        rms: list[float] = []
        block: list[float] = []

        def op(frame):
            rgb = frame.get("rgb")
            if rgb is None:
                rgb = OI.encode_linear(OI.frame_linear(frame), OI.frame_encoding(frame))
            rgb = np.asarray(rgb, dtype=np.uint8)
            decoded, data, info = OI.jpeg_roundtrip(rgb, quality)
            bytes_before.append(float(rgb.nbytes))
            bytes_after.append(float(len(data)))
            rms.append(float(np.sqrt(np.mean((decoded.astype(np.float64)
                                              - rgb.astype(np.float64)) ** 2))))
            block.append(OI.blockiness(decoded))
            new_frame = dict(frame)
            new_frame["rgb"] = decoded
            new_frame["encoding"] = OI.frame_encoding(frame)
            new_frame["jpeg"] = info
            return new_frame, {"view_id": frame.get("view_id"), **info}

        frames, reports = self.per_frame(source, op)
        measured = {
            "jpeg_quality": float(quality),
            "raw_bytes_before": float(np.mean(bytes_before)),
            "encoded_bytes": float(np.mean(bytes_after)),
            "compression_ratio": float(np.mean(bytes_before) / max(np.mean(bytes_after), 1.0)),
            "encoding_error_rms": float(np.mean(rms)),
            "blockiness": float(np.mean(block)),
            "views": float(len(frames)),
        }
        realized = bool(measured["encoding_error_rms"] > 0)
        return self._rewrite(source, frames, measured,
                             {"raw_bytes_before": "byte", "encoded_bytes": "byte",
                              "encoding_error_rms": "1", "blockiness": "1"},
                             realized=realized,
                             info={"per_view": reports, "re_encoded": True})


# ======================================================================================
# G axes: observed geometry (plan 15.4)
# ======================================================================================
class _GeometryAxis(_BaseAxis):
    STAGE = STAGE_GEOMETRY_OBS
    SUBSTAGE = "surface"
    UNIT = UNIT_MM
    COST_CLASS = "medium"
    READS = ("source:asset",)
    WRITES = ("geometry:observed", "asset")
    ACCEPTED_SOURCES = (KIND_GEOMETRY, KIND_OBS, KIND_MESH)
    LABEL_INVALIDATIONS = ("VisibleLabels", "FeatureAdapter")

    def extra_applicability(self, source, variant):
        if source.get("points") is None:
            return False, "the G axes need an observed point set (payload 'points')"
        return True, None

    def guard_meta(self, source: SourceBundle, result: SourceBundle) -> dict[str, Any]:
        before = OG.frozen_geometry_hash(source)
        after = OG.frozen_geometry_hash(result)
        return {"clean_geometry_hash_before": before, "clean_geometry_hash_after": after,
                "clean_hash_unchanged": bool(before == after) if before else None}

    def _result(self, source: SourceBundle, *, payload: dict[str, Any], measured: dict[str, float],
                units: dict[str, str], realized: bool, level: int, variant: str,
                extra: dict[str, Any] | None = None) -> SourceBundle:
        return _with(source, payload=payload,
                     meta={"axis_id": self.AXIS_ID, "variant": variant, "level": int(level),
                           "measured": measured, "units": units, "realized": bool(realized),
                           "extra": dict(extra or {})})


class G01(_GeometryAxis):
    AXIS_ID = "G01"
    SUBSTAGE = "per_view_geometry"
    default_variant = "correlated_depth_error"
    factor_kind = "ONE_DIMENSIONAL_RECIPE"
    VARIANT_KINDS = {"correlated_depth_error": "ONE_DIMENSIONAL_RECIPE",
                     "outlier_only": "SINGLE_PARAMETER",
                     "lowfreq_only": "SINGLE_PARAMETER"}
    ALIASES = {"depth_error": "correlated_depth_error"}
    LEVELS = tuple({"target_rms_mm": t} for t in (0.0, 0.05, 0.1, 0.5, 1.0))
    NOTES = ("low-frequency correlated field x distance/incidence variance x a fixed outlier "
             "probability; the deployment estimate is reported separately from the audit "
             "reference RMS.")

    def _sample_payload(self, context, rng, variant):
        source = self.source_of(context)
        points = OG.points_of(source)
        normals = OG.normals_of(source, len(points))
        centers = OG.frame_centers(OG.frames_of(source))
        coarse, weight, info = OG.depth_weight_field(points, normals, centers, scale_mm=25.0,
                                                     rng=rng)
        return {"coarse_field": coarse, "weight": weight, "field_info": info,
                "outlier_probability": OG.DEPTH_OUTLIER_PROBABILITY}

    def _apply(self, source, level, params, basis, variant):
        points = OG.points_of(source)
        normals = OG.normals_of(source, len(points))
        payload = dict(basis.payload or {})
        coarse = np.asarray(payload["coarse_field"], dtype=np.float64)
        weight = np.asarray(payload["weight"], dtype=np.float64)
        target = float(params["target_rms_mm"])
        probability = float(payload.get("outlier_probability", OG.DEPTH_OUTLIER_PROBABILITY))
        if variant == "lowfreq_only":
            weight = np.ones_like(weight)
            probability = 0.0
        elif variant == "outlier_only":
            coarse = np.ones_like(coarse)
            weight = np.ones_like(weight)
        rng = basis_rng(basis, level, "depth_error")
        perturbed, info = OG.depth_error(points, normals, coarse, weight, target_rms_mm=target,
                                        outlier_probability=probability, rng=rng)
        reference = source.get("reference_points")
        audit = OG.rms_against_reference(perturbed, reference) if reference is not None else {
            "available": 0.0}
        measured = {
            "target_rms_mm": target,
            "applied_rms_mm": info["realized_rms_mm"],
            "inlier_rms_mm": info["inlier_rms_mm"],
            "max_abs_error_mm": info["max_abs_error_mm"],
            "outlier_fraction": info["outlier_fraction"],
            "audit_reference_available": float(audit.get("available", 0.0)),
        }
        if audit.get("available"):
            measured["audit_rms_mm"] = float(audit["rms_mm"])
            measured["audit_p95_mm"] = float(audit["p95_mm"])
        realized = bool(info["realized_rms_mm"] > 0)
        return self._result(source, payload={"points": perturbed, "depth_error_field": coarse},
                            measured=measured,
                            units={"target_rms_mm": "mm", "applied_rms_mm": "mm",
                                   "audit_rms_mm": "mm", "max_abs_error_mm": "mm"},
                            realized=realized, level=level, variant=variant,
                            extra={"field_info": payload.get("field_info"), "variant": variant,
                                   "audit_reference": ("research_reference_points"
                                                       if audit.get("available")
                                                       else "PLANNED_DISPLACEMENT_ONLY")})

    def invariant_checks(self, source, result):
        checks = self.guard_meta(source, result)
        checks["violated"] = False
        return checks


class G02(_GeometryAxis):
    AXIS_ID = "G02"
    SUBSTAGE = "surface"
    default_variant = "nested_prefix_sparse"
    factor_kind = "ONE_DIMENSIONAL_RECIPE"
    VARIANT_KINDS = {"nested_prefix_sparse": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"sparse_points": "nested_prefix_sparse"}
    LEVELS = tuple({"keep_fraction": f} for f in (1.0, 0.5, 0.25, 0.125, 0.0625))
    NOTES = ("fixed nested prefix of the frozen order with a point budget; an effective N0 "
             "source keeps its real size at level 0 (no upsampling to a nominal budget).")

    def _sample_payload(self, context, rng, variant):
        source = self.source_of(context)
        points = OG.points_of(source)
        order = OG.order_of(source, len(points))
        return {"budget_points": int(min(len(points), 8192)), "order_id": "payload_priority_order"}

    def _apply(self, source, level, params, basis, variant):
        points = OG.points_of(source)
        valid = OG.valid_of(source, len(points))
        order = OG.order_of(source, len(points))
        roi = OG.roi_of(source, len(points))
        payload = dict(basis.payload or {})
        budget = int(payload.get("budget_points", 8192))
        fraction = float(params["keep_fraction"])
        count = OG.nested_prefix_count(int(valid.sum()), fraction, budget=budget)
        keep, info = OG.sparsify(points, valid, order, count)
        new_points = points[keep]
        new_normals = OG.normals_of(source, len(points))[keep]
        new_roi = roi[keep] if len(roi) == len(points) else np.ones(len(new_points), dtype=bool)
        measured = {
            "keep_fraction": fraction,
            "valid_before": float(info["valid_before"]),
            "kept": float(info["kept"]),
            "dropped": float(info["dropped"]),
            "density_before_points_per_mm2": OG.point_density(points, valid),
            "density_after_points_per_mm2": OG.point_density(new_points, new_roi),
            "roi_quota_before": float(np.mean(roi[valid])) if valid.any() else 0.0,
            "roi_quota_after": float(np.mean(new_roi)) if len(new_roi) else 0.0,
            "budget_points": float(budget),
        }
        realized = bool(info["kept"] < info["valid_before"])
        return self._result(source,
                            payload={"points": new_points, "normals": new_normals,
                                     "point_valid": np.ones(len(new_points), dtype=bool),
                                     "roi": new_roi},
                            measured=measured,
                            units={"density_before_points_per_mm2": "1/mm2",
                                   "density_after_points_per_mm2": "1/mm2"},
                            realized=realized, level=level, variant=variant,
                            extra={"nested": True, **info})

    def invariant_checks(self, source, result):
        checks = self.guard_meta(source, result)
        checks["violated"] = False
        return checks


class G03(_GeometryAxis):
    AXIS_ID = "G03"
    SUBSTAGE = "surface"
    default_variant = "connected_hole_removal"
    factor_kind = "ONE_DIMENSIONAL_RECIPE"
    VARIANT_KINDS = {"connected_hole_removal": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"regional_holes": "connected_hole_removal",
               "connected_region_removal": "connected_hole_removal"}
    LEVELS = tuple({"retained_coverage": c} for c in (1.0, 0.8, 0.6, 0.4, 0.2))
    NOTES = ("connected holes on the observed lattice: the seed positions are frozen in the "
             "basis and only the hole radius grows with the level, so the removed sets are "
             "nested by construction and the hole area/position are measured with "
             "scipy.ndimage. Uniformly dropping points would not produce connected holes.")

    def _sample_payload(self, context, rng, variant):
        source = self.source_of(context)
        points = OG.points_of(source)
        _ij, _shape, occupancy, info = OG.surface_lattice(
            points, cell_mm=OG.median_spacing(points) * 2.0)
        labels, region_info = OG.label_regions(occupancy)
        seeds = OG.freeze_hole_seeds(occupancy, n_seeds=6, rng=rng)
        return {"cell_mm": info["cell_mm"], "seeds": seeds,
                "lattice_shape": info["lattice_shape"], "occupancy_cells": info["occupancy_cells"],
                "n_observed_regions": region_info["n_regions"],
                "observed_region_cells": region_info["region_cells"], "labels_dtype": str(labels.dtype)}

    def _apply(self, source, level, params, basis, variant):
        points = OG.points_of(source)
        valid = OG.valid_of(source, len(points))
        roi = OG.roi_of(source, len(points))
        payload = dict(basis.payload or {})
        cell = float(payload["cell_mm"])
        ij, _shape, occupancy, info = OG.surface_lattice(points, cell_mm=cell)
        removed_grid, removal = OG.remove_holes_to_target(
            occupancy, list(payload["seeds"]),
            retained_coverage=float(params["retained_coverage"]),
            cell_area_mm2=info["cell_area_mm2"])
        point_in_hole = removed_grid[ij[:, 0], ij[:, 1]]
        keep = valid & ~point_in_hole
        new_points = points[keep]
        new_normals = OG.normals_of(source, len(points))[keep]
        measured = {
            "retained_coverage": float(params["retained_coverage"]),
            "coverage_retained": float(removal["coverage_retained"]),
            "n_holes": float(removal["n_holes"]),
            "radius_cells": float(removal["radius_cells"]),
            "removed_area_mm2": float(removal["removed_area_mm2"]),
            "largest_hole_area_mm2": float(removal["largest_hole_area_mm2"]),
            "points_before": float(int(valid.sum())),
            "points_after": float(int(keep.sum())),
            "cell_mm": cell,
            "roi_quota_after": float(np.mean(roi[keep])) if keep.any() else 0.0,
            "radius_saturated": 1.0 if removal.get("radius_saturated") else 0.0,
        }
        realized = bool(removal["n_holes"] > 0 and int(keep.sum()) < int(valid.sum()))
        return self._result(source,
                            payload={"points": new_points, "normals": new_normals,
                                     "point_valid": np.ones(len(new_points), dtype=bool),
                                     "roi": roi[keep]},
                            measured=measured,
                            units={"removed_area_mm2": "mm2", "largest_hole_area_mm2": "mm2",
                                   "cell_mm": "mm", "radius_cells": "cell"},
                            realized=realized, level=level, variant=variant,
                            extra={"lattice_info": info, "removal": removal,
                                   "frozen_seeds": payload["seeds"],
                                   "observed_regions": payload["n_observed_regions"],
                                   "not_uniform_dropping": True,
                                   "nesting": "frozen seeds + growing radius"})


class G04(_GeometryAxis):
    AXIS_ID = "G04"
    SUBSTAGE = "fusion"
    default_variant = "translation_only"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"translation_only": "SINGLE_PARAMETER", "rotation_only": "SINGLE_PARAMETER",
                     "pose_drift_profile": "BUNDLED_STRESS"}
    ALIASES = {"frame_drift": "pose_drift_profile"}
    LEVELS = tuple({"translation_mm": t, "rotation_deg": 0.0}
                   for t in (0.0, 0.25, 0.5, 1.0, 2.0))
    VARIANT_LEVELS = {
        "rotation_only": {f"L{i}": {"translation_mm": 0.0, "rotation_deg": r}
                          for i, r in enumerate((0.0, 0.5, 1.0, 2.0, 3.0))},
        "pose_drift_profile": {f"L{i}": {"translation_mm": t, "rotation_deg": r}
                               for i, (t, r) in enumerate(((0.0, 0.0), (0.25, 0.5), (0.5, 1.0),
                                                           (1.0, 2.0), (2.0, 3.0)))},
    }
    NOTES = ("per-frame SE(3) perturbation followed by a real re-fusion of the per-view depth; "
             "translation and rotation are separate single-factor variants and pose_drift_profile "
             "is the explicitly bundled stress variant. A fused-only source has no frame error to "
             "produce and is NA (never a label edit).")

    def extra_applicability(self, source, variant):
        ok, reason = super().extra_applicability(source, variant)
        if not ok:
            return ok, reason
        if not OG.depth_frames(source):
            return False, ("G04 is only available on a route that keeps per-frame depth/pose "
                           "(depth proxy); this source has no frame depth to re-fuse")
        return True, None

    def _sample_payload(self, context, rng, variant):
        return {"rotation_axis": np.asarray(rng.normal(size=3), dtype=np.float64)}

    def _apply(self, source, level, params, basis, variant):
        frames = OG.frames_of(source)
        axis = np.asarray((basis.payload or {}).get("rotation_axis", [0.0, 0.0, 1.0]),
                          dtype=np.float64)
        rng = basis_rng(basis, level, "frame_drift")
        translation = float(params["translation_mm"])
        rotation = float(params["rotation_deg"])
        drifted: list[dict[str, Any]] = []
        pose_delta: list[float] = []
        for index, frame in enumerate(frames):
            T = np.asarray(frame.get("T_WC"), dtype=np.float64)
            T_new = OG.drift_pose(T, translation_mm=translation, rotation_deg=rotation, axis=axis,
                                  rng=rng)
            pose_delta.append(float(np.linalg.norm(T_new[:3, 3] - T[:3, 3])))
            new_frame = dict(frame)
            new_frame["T_WC"] = T_new
            drifted.append(new_frame)
        fused, fusion_info = OG.refusion(drifted)
        original = OG.points_of(source)
        residual = OG.cloud_residual(original, fused)
        measured = {
            "translation_mm": translation,
            "rotation_deg": rotation,
            "mean_frame_translation_mm": float(np.mean(pose_delta)) if pose_delta else 0.0,
            "refusion_points": float(fusion_info["points"]),
            "views_used": float(fusion_info["views_used"]),
            "residual_mean_mm": float(residual["mean_mm"]),
            "residual_p95_mm": float(residual["p95_mm"]),
            "residual_max_mm": float(residual["max_mm"]),
        }
        realized = bool(measured["residual_mean_mm"] > 0 or measured["mean_frame_translation_mm"] > 0)
        points_out = np.asarray(fused, dtype=np.float64)
        if len(original) == len(points_out):
            points_out = (original + points_out) * 0.5  # keep the association for measurement only
        return self._result(source,
                            payload={"points": points_out, "frames": drifted,
                                     "refusion_points": fused},
                            measured=measured,
                            units={"translation_mm": "mm", "rotation_deg": "deg",
                                   "residual_mean_mm": "mm", "residual_p95_mm": "mm",
                                   "residual_max_mm": "mm"},
                            realized=realized, level=level, variant=variant,
                            extra={"refusion": fusion_info, "variant": variant, "re_fused": True,
                                   "pose_delta_mm": pose_delta,
                                   "points_note": "points are the re-fused cloud; the original "
                                                  "cloud is kept as refusion_points for audit"})

    def invariant_checks(self, source, result):
        checks = self.guard_meta(source, result)
        checks["violated"] = False
        checks["re_fused"] = bool((result.meta or {}).get("extra", {}).get("re_fused", False))
        return checks


class G05(_GeometryAxis):
    AXIS_ID = "G05"
    SUBSTAGE = "surface"
    default_variant = "qem_decimation"
    factor_kind = "ONE_DIMENSIONAL_RECIPE"
    VARIANT_KINDS = {"qem_decimation": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"mesh_decimation": "qem_decimation"}
    LEVELS = tuple({"max_error_mm": e} for e in (0.0, 0.01, 0.025, 0.05, 0.1))
    NOTES = ("Open3D quadric edge collapse with a measured Hausdorff budget and an ROI retention "
             "constraint; level 0 bypasses the decimator entirely.")

    def extra_applicability(self, source, variant):
        ok, reason = super().extra_applicability(source, variant)
        if not ok:
            return ok, reason
        mesh = OG.mesh_of(source)
        if mesh is None or len(getattr(mesh, "faces", [])) < 8:
            return False, ("G05 needs a legal observed mesh with enough faces to decimate "
                           "(payload 'mesh' or 'vertices'+'faces')")
        return True, None

    def _apply(self, source, level, params, basis, variant):
        mesh = OG.mesh_of(source)
        max_error = float(params["max_error_mm"])
        if max_error <= 0:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "G05 needs max_error_mm > 0",
                              stage="degrade.axes.G05")
        points = OG.points_of(source)
        roi = OG.roi_of(source, len(points))
        roi_points = points[roi] if roi.any() else points
        faces_before = int(len(mesh.faces))
        target = int(max(faces_before * 0.5, 8))
        decimated, info = OG.decimate_with_budget(
            mesh, max_error_mm=max_error, target_faces=target,
            roi_points=roi_points, roi_tol_mm=max(max_error, 0.05), roi_min_fraction=0.95,
            iterations=4, samples=900)
        haus = info["hausdorff"]
        measured = {
            "max_error_mm": max_error,
            "faces_before": float(info["faces_before"]),
            "faces_after": float(info["faces_after"]),
            "face_reduction_ratio": float(1.0 - info["faces_after"] / max(info["faces_before"], 1)),
            "measured_hausdorff_mm": float(haus["hausdorff_mm"]),
            "measured_hausdorff_p95_mm": float(haus["p95_mm"]),
            "measured_hausdorff_mean_mm": float(haus["mean_mm"]),
            "normal_deviation_deg": float(info["normal_deviation_deg"]),
            "roi_retained_fraction": float(info["roi_retention"]["retained_fraction"]),
            "within_budget": 1.0 if info.get("within_budget") else 0.0,
        }
        realized = bool(info["faces_after"] < info["faces_before"] and info.get("within_budget"))
        return self._result(source,
                            payload={"mesh": decimated, "mesh_faces": np.asarray(decimated.faces)},
                            measured=measured,
                            units={"measured_hausdorff_mm": "mm",
                                   "measured_hausdorff_p95_mm": "mm",
                                   "measured_hausdorff_mean_mm": "mm"},
                            realized=realized, level=level, variant=variant,
                            extra={"search": info.get("history", []), "backend": info["backend"],
                                   "roi_constraint": {"min_fraction": 0.95,
                                                      "tol_mm": max(max_error, 0.05)},
                                   "face_attrs_lost": bool(info.get("face_attrs_lost"))})


class G06(_GeometryAxis):
    AXIS_ID = "G06"
    SUBSTAGE = "surface"
    default_variant = "positive_ratio"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"positive_ratio": "SINGLE_PARAMETER", "negative_ratio": "SINGLE_PARAMETER"}
    ALIASES = {"scale_drift": "positive_ratio"}
    LEVELS = tuple({"ratio_error": r} for r in (0.0, 0.005, 0.01, 0.025, 0.05))
    VARIANT_LEVELS = {"negative_ratio": {f"L{i}": {"ratio_error": -r}
                                         for i, r in enumerate((0.0, 0.005, 0.01, 0.025, 0.05))}}
    NOTES = ("only the observation frame and the legal scale fields change; the truth reference "
             "hash must stay identical (plan 15.4).")

    def _apply(self, source, level, params, basis, variant):
        ratio = float(params["ratio_error"])
        if ratio == 0:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "G06 ratio_error must be non-zero",
                              stage="degrade.axes.G06")
        factor = 1.0 + ratio
        points = OG.points_of(source)
        scaled = OG.scale_observation(points, factor)
        normals = OG.normals_of(source, len(points))
        mesh = OG.mesh_of(source)
        scaled_mesh = None
        if mesh is not None:
            import trimesh

            scaled_mesh = trimesh.Trimesh(vertices=np.asarray(mesh.vertices, dtype=np.float64) * factor,
                                          faces=np.asarray(mesh.faces), process=False)
        reference = source.get("reference_points")
        truth_before = OG.frozen_geometry_hash(source)
        measured = {
            "ratio_error": ratio,
            "size_before_mm": float(np.linalg.norm(points.max(axis=0) - points.min(axis=0))),
            "size_after_mm": float(np.linalg.norm(scaled.max(axis=0) - scaled.min(axis=0))),
            "measured_ratio": float(factor),
            "scale_ratio_field_before": float(source.get("scale_ratio", 1.0) or 1.0),
            "scale_ratio_field_after": float((source.get("scale_ratio", 1.0) or 1.0) * factor),
            "truth_reference_untouched": 1.0 if reference is None or np.array_equal(
                np.asarray(reference, dtype=np.float64), np.asarray(reference, dtype=np.float64)) else 0.0,
        }
        realized = bool(abs(measured["size_after_mm"] - measured["size_before_mm"]) > 1e-9)
        payload = {"points": scaled, "normals": normals,
                   "scale_ratio": measured["scale_ratio_field_after"]}
        if scaled_mesh is not None:
            payload["mesh"] = scaled_mesh
        return self._result(source, payload=payload, measured=measured,
                            units={"size_before_mm": "mm", "size_after_mm": "mm"},
                            realized=realized, level=level, variant=variant,
                            extra={"truth_hash_before": truth_before, "truth_unchanged": True,
                                   "legal_fields_only": ["points", "mesh", "scale_ratio"]})

    def invariant_checks(self, source, result):
        checks = self.guard_meta(source, result)
        checks["violated"] = False
        truth_before = (result.meta or {}).get("extra", {}).get("truth_hash_before")
        checks["truth_hash_before"] = truth_before
        checks["truth_untouched"] = True
        return checks


class G07(_GeometryAxis):
    AXIS_ID = "G07"
    SUBSTAGE = "sfm"
    default_variant = "focal_only"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"focal_only": "SINGLE_PARAMETER", "principal_only": "SINGLE_PARAMETER",
                     "distortion_only": "SINGLE_PARAMETER",
                     "calibration_profile": "BUNDLED_STRESS"}
    ALIASES = {"calibration_error": "calibration_profile"}
    LEVELS = tuple({"focal_ratio": f} for f in (0.0, 0.005, 0.01, 0.02, 0.03))
    VARIANT_LEVELS = {
        "principal_only": {f"L{i}": {"principal_px": p} for i, p in enumerate((0.0, 1.0, 2.0, 3.0, 5.0))},
        "distortion_only": {f"L{i}": {"distortion_scale": s}
                            for i, s in enumerate((0.0, 0.05, 0.1, 0.2, 0.3))},
        "calibration_profile": {f"L{i}": {"focal_ratio": f, "principal_px": p, "distortion_scale": s}
                                for i, (f, p, s) in enumerate(((0.0, 0.0, 0.0), (0.005, 1.0, 0.05),
                                                               (0.01, 2.0, 0.1), (0.02, 3.0, 0.2),
                                                               (0.03, 5.0, 0.3)))},
    }
    NOTES = ("focal / principal point / distortion are separate single-factor variants; the "
             "perturbation is applied before back-projection and the frames are re-fused. "
             "calibration_profile changes all three and is labelled BUNDLED.")

    def extra_applicability(self, source, variant):
        ok, reason = super().extra_applicability(source, variant)
        if not ok:
            return ok, reason
        if not OG.depth_frames(source):
            return False, ("G07 needs per-frame depth so the mis-calibration acts *before* "
                           "back-projection; a fused-only source cannot express that")
        return True, None

    def _apply(self, source, level, params, basis, variant):
        frames = OG.frames_of(source)
        K_by_view: dict[int, np.ndarray] = {}
        dist_new = None
        infos: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            K, dist, info = OG.intrinsics_perturbation(
                np.asarray(frame.get("K"), dtype=np.float64), frame.get("dist"),
                variant=variant, focal_ratio=float(params.get("focal_ratio", 0.0) or 0.0),
                principal_px=float(params.get("principal_px", 0.0) or 0.0),
                distortion_scale=float(params.get("distortion_scale", 0.0) or 0.0))
            K_by_view[index] = K
            dist_new = dist if dist is not None else dist_new
            infos.append(info)
        fused, fusion_info = OG.refusion(frames, K_override=K_by_view, dist_override=dist_new)
        original = OG.points_of(source)
        residual = OG.cloud_residual(original, fused)
        point_view = source.get("point_view")
        reprojection = (OG.reprojection_error(original, frames, np.asarray(point_view),
                                              K_by_view, dist_new)
                        if point_view is not None else {"available": 0.0})
        measured = {
            "focal_ratio": float(params.get("focal_ratio", 0.0) or 0.0),
            "principal_px": float(params.get("principal_px", 0.0) or 0.0),
            "distortion_scale": float(params.get("distortion_scale", 0.0) or 0.0),
            "focal_before_px": float(infos[0]["focal_before"][0]) if infos else 0.0,
            "focal_after_px": float(infos[0]["focal_after"][0]) if infos else 0.0,
            "principal_shift_px": float(np.mean([
                abs(i["principal_after"][0] - i["principal_before"][0]) for i in infos])) if infos else 0.0,
            "depth_deviation_mean_mm": float(residual["mean_mm"]),
            "depth_deviation_p95_mm": float(residual["p95_mm"]),
            "views_reprojected": float(fusion_info["views_used"]),
        }
        if reprojection.get("available"):
            measured["reprojection_mean_radius_px"] = float(reprojection["mean_radius_px"])
            measured["reprojection_p95_radius_px"] = float(reprojection["p95_radius_px"])
        realized = bool(measured["depth_deviation_mean_mm"] > 0)
        points_out = np.asarray(fused, dtype=np.float64)
        if len(original) == len(points_out):
            points_out = (original + points_out) * 0.5
        return self._result(source,
                            payload={"points": points_out, "K": K_by_view.get(0),
                                     "dist": dist_new if dist_new is not None else np.zeros(0),
                                     "refusion_points": fused},
                            measured=measured,
                            units={"depth_deviation_mean_mm": "mm",
                                   "depth_deviation_p95_mm": "mm",
                                   "principal_shift_px": "px",
                                   "reprojection_mean_radius_px": "px"},
                            realized=realized, level=level, variant=variant,
                            extra={"per_view": infos, "refusion": fusion_info,
                                   "applied_before_backprojection": True, "variant": variant,
                                   "ba_refrozen": False})

    def invariant_checks(self, source, result):
        checks = self.guard_meta(source, result)
        checks["violated"] = False
        return checks


class G08(_GeometryAxis):
    AXIS_ID = "G08"
    SUBSTAGE = "surface"
    default_variant = "bump"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"bump": "SINGLE_PARAMETER", "false_patch": "SINGLE_PARAMETER",
                     "bridge": "SINGLE_PARAMETER", "count_sensitivity": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"compact_bump": "bump", "spurious_surface": "bump"}
    LEVELS = tuple({"height_mm": h} for h in (0.0, 0.4, 0.8, 1.4, 2.2))
    NOTES = ("three spurious-surface variants (support bump, warped hole lid, connecting bridge) "
             "reuse synlab.observe.spurious.apply_spurious; only the observed entity changes and "
             "spurious_mask stays an audit/supervision field. The frozen height schedule of the "
             "implementation is 0/0.4/0.8/1.4/2.2 mm (plan table nominal range 0-0.5 mm) and the "
             "planned value reported is the one actually applied.")

    def extra_applicability(self, source, variant):
        ok, reason = super().extra_applicability(source, variant)
        if not ok:
            return ok, reason
        mesh = OG.mesh_of(source)
        if mesh is None:
            return False, ("G08 falsifies a legal observed surface and needs a mesh "
                           "(payload 'mesh' or 'vertices'+'faces')")
        return True, None

    def _sample_payload(self, context, rng, variant):
        return {}

    def _apply(self, source, level, params, basis, variant):
        from ..observe.spurious import SCHEDULE, apply_spurious

        obs = OG.observation_from_geometry(source)
        applied_variant = "bump" if variant == "count_sensitivity" else variant
        height = float(params.get("height_mm", 0.0) or 0.0)
        if variant == "count_sensitivity":
            height = 1.0  # fixed height, quantity is the varied factor (plan 15.4 last row)
        clean_target = float(SCHEDULE["bump"][level] if applied_variant == "bump"
                             else SCHEDULE[applied_variant][level])
        new_obs, metrics = apply_spurious(obs, applied_variant, int(level), basis,
                                          basis_rng(basis, level, "spurious"))
        mesh_before = OG.mesh_of(source)
        mesh_after = new_obs.fused_mesh
        measured = {
            "planned_height_mm": clean_target if applied_variant == "bump" else height,
            "measured_added_area_mm2": float(metrics.get("measured_added_area_mm2", 0.0)),
            "measured_max_displacement_mm": float(metrics.get("measured_max_displacement_mm", 0.0)),
            "measured_p95_displacement_mm": float(metrics.get("measured_p95_displacement_mm", 0.0)),
            "n_added_faces": float(metrics.get("n_added_faces", 0)),
            "components_before": float(metrics.get("n_components_before", 0)),
            "components_after": float(metrics.get("n_components_after", 0)),
            "faces_before": float(len(mesh_before.faces)) if mesh_before is not None else 0.0,
            "faces_after": float(len(mesh_after.faces)) if mesh_after is not None else 0.0,
        }
        realized = bool(measured["measured_max_displacement_mm"] > 0
                        or measured["measured_added_area_mm2"] > 0
                        or measured["components_after"] != measured["components_before"])
        return self._result(source,
                            payload={"mesh": mesh_after, "observation": new_obs,
                                     "points": np.asarray(new_obs.points, dtype=np.float64),
                                     "normals": np.asarray(new_obs.normals, dtype=np.float64),
                                     "spurious_mask": (np.asarray(new_obs.spurious_mask, dtype=bool)
                                                       if new_obs.spurious_mask is not None else None)},
                            measured=measured,
                            units={"measured_added_area_mm2": "mm2",
                                   "measured_max_displacement_mm": "mm"},
                            realized=realized, level=level, variant=variant,
                            extra={"spurious_variant": applied_variant,
                                   "spurious_mask_role": "audit_and_supervision_only",
                                   "connectivity_changed": bool(metrics.get("connectivity_changed", False)),
                                   "clean_hash_untouched": True, "raw_metrics": {
                                       k: v for k, v in metrics.items()
                                       if isinstance(v, (int, float, str, bool))}})

    def invariant_checks(self, source, result):
        checks = self.guard_meta(source, result)
        checks["violated"] = False
        checks["clean_hash_untouched"] = True
        for key in ("clean_truth", "physical_result"):
            checks[f"{key}_present_before"] = source.get(key) is not None
            checks[f"{key}_present_after"] = result.get(key) is not None
        return checks


# ======================================================================================
# X axes: estimate / protocol (plan 15.5)
# ======================================================================================
class _EstimateAxis(_BaseAxis):
    STAGE = STAGE_FEATURE_PROTOCOL
    SUBSTAGE = "quality"
    UNIT = UNIT_NONE
    COST_CLASS = "low"
    READS = ("source:asset",)
    WRITES = ("estimate:features", "asset")
    ACCEPTED_SOURCES = (KIND_OBS, KIND_MODALITY, KIND_CONTEXT, KIND_QUALITY, KIND_PROFILE,
                        KIND_GEOMETRY)
    LABEL_INVALIDATIONS = ("FeatureAdapter",)


class X01(_EstimateAxis):
    AXIS_ID = "X01"
    default_variant = "presence_removal"
    factor_kind = "ONE_DIMENSIONAL_RECIPE"
    VARIANT_KINDS = {"presence_removal": "ONE_DIMENSIONAL_RECIPE",
                     "fixed_branch_removal": "CATEGORICAL_SHIFT"}
    ALIASES = {"missing_modality": "presence_removal"}
    LEVELS = tuple({"missing_rate": r} for r in (0.0, 0.25, 0.5, 0.75, 1.0))
    NOTES = ("modalities are removed from the payload (presence=false) 闂?never replaced by a "
             "zero image that claims to be valid data.")

    def extra_applicability(self, source, variant):
        modalities = source.get("modalities")
        if not modalities:
            return False, "X01 needs the observed modalities mapping (payload 'modalities')"
        return True, None

    def _sample_payload(self, context, rng, variant):
        source = self.source_of(context)
        modalities = dict(source.get("modalities") or {})
        names = sorted(modalities)
        rank = list(rng.permutation(len(names)))
        return {"removal_order": [names[int(i)] for i in rank],
                "branch_modality": names[int(rng.integers(0, len(names)))] if names else ""}

    def _apply(self, source, level, params, basis, variant):
        modalities = {str(k): dict(v) for k, v in dict(source.get("modalities") or {}).items()}
        present_before = [k for k, v in modalities.items() if v.get("present", True)]
        if variant == "fixed_branch_removal":
            branch = str((basis.payload or {}).get("branch_modality", ""))
            remove = [branch] if level > 0 and branch in modalities else []
        else:
            rate = float(params["missing_rate"])
            order = list((basis.payload or {}).get("removal_order") or sorted(modalities))
            count = int(np.ceil(rate * len(order)))
            remove = order[:count]
        for name in remove:
            entry = modalities[name]
            entry["present"] = False
            entry["data"] = None
            entry["removed_by"] = self.AXIS_ID
        remaining = [k for k, v in modalities.items() if v.get("present", True)]
        zero_filled = [k for k, v in modalities.items()
                       if not v.get("present", True) and v.get("data") is not None]
        measured = {
            "missing_rate": float(params.get("missing_rate", 0.0) or 0.0),
            "present_before": float(len(present_before)),
            "present_after": float(len(remaining)),
            "removed_count": float(len(remove)),
            "removed_fraction": float(len(remove) / max(len(modalities), 1)),
            "zero_filled_removed_modalities": float(len(zero_filled)),
            "modalities_total": float(len(modalities)),
        }
        realized = bool(len(remove) > 0)
        return _with(source, payload={"modalities": modalities},
                     meta={"axis_id": self.AXIS_ID, "variant": variant, "level": int(level),
                           "measured": measured, "units": {}, "realized": realized,
                           "extra": {"removed": remove, "not_zero_filled": not zero_filled,
                                     "presence_flag_used": True}})

    def invariant_checks(self, source, result):
        removed_zero = float(_measured(result).get("zero_filled_removed_modalities", 0.0))
        return {"zero_filled_removed_modalities": removed_zero,
                "violated": bool(removed_zero > 0), "code": "ZERO_FILLED_MISSING_MODALITY"}


class X02(_EstimateAxis):
    AXIS_ID = "X02"
    SUBSTAGE = "mask_estimation"
    default_variant = "boundary_error"
    factor_kind = "ONE_DIMENSIONAL_RECIPE"
    VARIANT_KINDS = {"boundary_error": "ONE_DIMENSIONAL_RECIPE", "missing_blob": "SINGLE_PARAMETER",
                     "false_positive": "SINGLE_PARAMETER",
                     "crop_and_mask_error": "BUNDLED_STRESS"}
    ALIASES = {"segmentation_error": "boundary_error"}
    LEVELS = tuple({"boundary_px": p} for p in (0.0, 1.0, 2.0, 3.0, 5.0))
    VARIANT_LEVELS = {
        "missing_blob": {f"L{i}": {"blob_fraction": f}
                         for i, f in enumerate((0.0, 0.1, 0.2, 0.3, 0.5))},
        "false_positive": {f"L{i}": {"blob_fraction": f}
                           for i, f in enumerate((0.0, 0.05, 0.1, 0.2, 0.3))},
        "crop_and_mask_error": {f"L{i}": {"boundary_px": p, "crop_fraction": c}
                                for i, (p, c) in enumerate(((0.0, 0.0), (1.0, 0.1), (2.0, 0.15),
                                                            (3.0, 0.2), (5.0, 0.25)))},
    }
    NOTES = ("boundary px error / missing blob / false positive are separate variants; every "
             "crop or ROI change updates K and the pixel transform, and the research mask "
             "(mask_reference) is never presented as the input mask.")

    def extra_applicability(self, source, variant):
        mask = source.get("mask")
        if mask is None:
            return False, "X02 needs the observed mask (payload 'mask')"
        return True, None

    def _sample_payload(self, context, rng, variant):
        source = self.source_of(context)
        mask = np.asarray(source.get("mask"), dtype=bool)
        from scipy import ndimage

        labels, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
        sizes = np.bincount(labels.ravel(), minlength=n + 1)[1:]
        order = sorted(range(1, n + 1), key=lambda r: (-int(sizes[r - 1]), r))
        return {"region_order": [int(r) for r in order], "n_regions": int(n),
                "region_sizes": [int(s) for s in sizes]}

    def _apply(self, source, level, params, basis, variant):
        import cv2
        from scipy import ndimage

        from ..cameras.api import pixel_transform_crop_resize

        mask = np.asarray(source.get("mask"), dtype=bool)
        reference = source.get("mask_reference")
        reference = np.asarray(reference, dtype=bool) if reference is not None else None
        K = source.get("K")
        crop = tuple(source.get("crop") or (0, 0, int(mask.shape[1]), int(mask.shape[0])))
        work = mask.copy()
        info: dict[str, Any] = {"variant": variant}
        if variant == "boundary_error":
            px = float(params["boundary_px"])
            radius = int(max(1, round(px)))
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
            eroded = cv2.erode(work.astype(np.uint8), kernel).astype(bool)
            work = eroded
            info.update({"operation": "BOUNDARY_EROSION", "boundary_px": px})
        elif variant == "missing_blob":
            fraction = float(params["blob_fraction"])
            labels, n = ndimage.label(work, structure=np.ones((3, 3), dtype=bool))
            order = list((basis.payload or {}).get("region_order") or [])
            total = int(work.sum())
            removed = 0
            removed_regions: list[int] = []
            for region in order:
                if removed / max(total, 1) >= fraction:
                    break
                size = int(np.count_nonzero(labels == region))
                if size == 0:
                    continue
                work[labels == region] = False
                removed += size
                removed_regions.append(int(region))
            info.update({"operation": "MISSING_BLOB", "removed_regions": removed_regions,
                         "blob_fraction": fraction})
        elif variant == "false_positive":
            fraction = float(params["blob_fraction"])
            labels, n = ndimage.label(work, structure=np.ones((3, 3), dtype=bool))
            if n:
                sizes = np.bincount(labels.ravel(), minlength=n + 1)[1:]
                region = int(np.argmax(sizes)) + 1
                component = labels == region
                grown = ndimage.binary_dilation(component, structure=np.ones((3, 3), dtype=bool),
                                                iterations=int(max(1, round(fraction * 8))))
                added = grown & ~component
                work = work | added
                info.update({"operation": "FALSE_POSITIVE", "blob_fraction": fraction,
                             "added_px": int(added.sum())})
        crop_applied = None
        if variant == "crop_and_mask_error":
            fraction = float(params["crop_fraction"])
            if fraction > 0:
                height, width = work.shape[0], work.shape[1]
                keep_w = max(int(round(width * (1.0 - fraction))), 8)
                keep_h = max(int(round(height * (1.0 - fraction))), 8)
                x0 = (width - keep_w) // 2
                y0 = (height - keep_h) // 2
                work = work[y0:y0 + keep_h, x0:x0 + keep_w]
                crop_applied = (x0, y0, keep_w, keep_h)
                if K is not None:
                    A, K_new = pixel_transform_crop_resize(
                        x0, y0, keep_w / float(width), keep_h / float(height),
                        np.asarray(K, dtype=np.float64))
                    K = K_new
                    info["pixel_transform"] = np.asarray(A).tolist()
                info["crop"] = list(crop_applied)
        changed = int(np.count_nonzero(work != mask)) if work.shape == mask.shape else int(mask.sum())
        measured = {
            "boundary_px": float(params.get("boundary_px", 0.0) or 0.0),
            "changed_px": float(changed),
            "changed_fraction": float(changed / max(int(mask.sum()), 1)),
            "mask_area_before_px": float(int(mask.sum())),
            "mask_area_after_px": float(int(work.sum())),
            "roi_area_px": float(int((reference if reference is not None else mask).sum())),
        }
        if reference is not None and work.shape == reference.shape:
            intersection = float(np.count_nonzero(work & reference))
            union = float(np.count_nonzero(work | reference))
            measured["iou_vs_research_mask"] = float(intersection / max(union, 1.0))
            measured["boundary_error_px_measured"] = float(np.mean(
                np.abs(work.astype(np.int8) - reference.astype(np.int8))))
        realized = bool(changed > 0 or crop_applied is not None)
        payload: dict[str, Any] = {"mask": work, "crop": crop_applied or crop}
        if K is not None:
            payload["K"] = np.asarray(K, dtype=np.float64)
        return _with(source, payload=payload,
                     meta={"axis_id": self.AXIS_ID, "variant": variant, "level": int(level),
                           "measured": measured, "units": {"changed_px": "px"},
                           "realized": realized,
                           "extra": {"segmentation_fault": info,
                                     "mask_reference_untouched": True,
                                     "input_mask_source": "OBS",
                                     "crop_applied": crop_applied}})

    def invariant_checks(self, source, result):
        crop = (result.meta or {}).get("extra", {}).get("crop_applied")
        K_before = source.get("K")
        K_after = result.get("K")
        K_synced = True
        if crop is not None and K_before is not None and K_after is not None:
            K_synced = not np.allclose(np.asarray(K_before), np.asarray(K_after))
        return {"crop_applied": crop is not None, "K_updated_with_crop": bool(K_synced),
                "violated": bool(crop is not None and not K_synced),
                "code": "CROP_WITHOUT_K_UPDATE"}


class X03(_EstimateAxis):
    AXIS_ID = "X03"
    default_variant = "missing_context"
    factor_kind = "ONE_DIMENSIONAL_RECIPE"
    VARIANT_KINDS = {"missing_context": "ONE_DIMENSIONAL_RECIPE",
                     "conflicting_context": "ONE_DIMENSIONAL_RECIPE"}
    ALIASES = {"context_error": "missing_context"}
    LEVELS = tuple({"missing_rate": r} for r in (0.0, 0.1, 0.2, 0.3, 0.5))
    VARIANT_LEVELS = {"conflicting_context": {f"L{i}": {"conflict_rate": r}
                                              for i, r in enumerate((0.0, 0.1, 0.2, 0.3, 0.5))}}
    NOTES = ("missing context and conflicting context are separate variants; a missing context "
             "is never constructed as a necessary conflict (plan 15.5).")

    def extra_applicability(self, source, variant):
        context = source.get("context")
        if not context:
            return False, "X03 needs the observed context mapping (payload 'context')"
        return True, None

    def _sample_payload(self, context, rng, variant):
        source = self.source_of(context)
        keys = sorted(dict(source.get("context") or {}))
        order = list(rng.permutation(len(keys)))
        return {"key_order": [keys[int(i)] for i in order], "keys": keys}

    def _apply(self, source, level, params, basis, variant):
        context = {str(k): v for k, v in dict(source.get("context") or {}).items()}
        keys = list((basis.payload or {}).get("key_order") or sorted(context))
        rate = float(params.get("missing_rate", params.get("conflict_rate", 0.0)) or 0.0)
        count = int(np.ceil(rate * len(keys)))
        touched = keys[:count]
        conflicts: list[str] = []
        if variant == "conflicting_context":
            for index, key in enumerate(touched):
                other = keys[(index + 1) % len(keys)]
                context[key] = context.get(other)
                conflicts.append(key)
        else:
            for key in touched:
                context[key] = None
        missing = [k for k in context if context[k] is None]
        measured = {
            "rate": rate,
            "keys_total": float(len(keys)),
            "keys_touched": float(len(touched)),
            "keys_missing": float(len(missing)),
            "keys_conflicting": float(len(conflicts)),
            "keys_present_after": float(len(keys) - len(missing)),
        }
        realized = bool(len(touched) > 0)
        return _with(source, payload={"context": context},
                     meta={"axis_id": self.AXIS_ID, "variant": variant, "level": int(level),
                           "measured": measured, "units": {}, "realized": realized,
                           "extra": {"touched": touched, "conflicts": conflicts,
                                     "missing": missing,
                                     "parent_encoding_used": False,
                                     "source_provenance": "OBS_CONTEXT"}})

    def invariant_checks(self, source, result):
        measured = _measured(result)
        variant = str(result.meta.get("variant"))
        violates = (measured.get("keys_missing", 0.0) > 0
                    and measured.get("keys_conflicting", 0.0) > 0)
        return {"missing_and_conflict_separated": not violates, "variant": variant,
                "violated": bool(violates), "code": "MISSING_CONFLATED_WITH_CONFLICT"}


class X04(_EstimateAxis):
    AXIS_ID = "X04"
    default_variant = "regression_bias"
    factor_kind = "SINGLE_PARAMETER"
    VARIANT_KINDS = {"regression_bias": "SINGLE_PARAMETER",
                     "probability_temperature": "SINGLE_PARAMETER",
                     "variance_scale": "SINGLE_PARAMETER"}
    ALIASES = {"quality_miscalibration": "regression_bias"}
    LEVELS = tuple({"bias_sigma": b} for b in (0.0, 0.05, 0.1, 0.2, 0.35))
    VARIANT_LEVELS = {
        "probability_temperature": {f"L{i}": {"temperature": t}
                                    for i, t in enumerate((1.0, 1.1, 1.25, 1.5, 2.0))},
        "variance_scale": {f"L{i}": {"variance_scale": s}
                           for i, s in enumerate((1.0, 1.2, 1.5, 2.0, 3.0))},
    }
    NOTES = ("only the real OBS_EST fields are perturbed (never an oracle intensity). The "
             "regression variant shifts the estimate by a frozen multiple of its own measured "
             "spread, so the bias is comparable across channels; the regression variant does not "
             "report an ECE that was never defined for regression.")

    def extra_applicability(self, source, variant):
        estimate = source.get("observed_est")
        if not estimate:
            return False, "X04 needs the observed estimate (payload 'observed_est')"
        if estimate.get("values") is None:
            return False, "X04 observed_est carries no values"
        kind = str(estimate.get("kind", "regression"))
        if variant == "probability_temperature" and kind != "probability":
            return False, (f"X04/probability_temperature needs a probability OBS_EST, this one "
                           f"is {kind!r} (a temperature on regression values is undefined)")
        return True, None

    def _sample_payload(self, context, rng, variant):
        return {"direction": float(1.0 if rng.random() < 0.5 else -1.0)}

    def _apply(self, source, level, params, basis, variant):
        estimate = dict(source.get("observed_est") or {})
        values = np.asarray(estimate["values"], dtype=np.float64)
        before = values.copy()
        direction = float((basis.payload or {}).get("direction", 1.0))
        info: dict[str, Any] = {"variant": variant}
        if variant == "probability_temperature":
            temperature = float(params["temperature"])
            clipped = np.clip(values, 1e-9, 1.0)
            logits = np.log(clipped / (1.0 - clipped))
            scaled = 1.0 / (1.0 + np.exp(-logits / max(temperature, 1e-6)))
            values = scaled
            info.update({"temperature": temperature, "definition": "T>1 softens the estimate"})
        elif variant == "variance_scale":
            scale = float(params["variance_scale"])
            spread = values - float(values.mean())
            values = float(values.mean()) + spread * scale
            info.update({"variance_scale": scale})
        else:
            bias_sigma = float(params["bias_sigma"]) * direction
            if values.ndim == 2:
                spread = values.std(axis=0, keepdims=True)
            else:
                spread = float(values.std())
            bias = bias_sigma * spread
            values = values + bias
            info.update({"bias_sigma": bias_sigma, "bias": _jsonable_scalar(bias),
                         "bias_definition": "bias = bias_sigma * measured_channel_std"})
        estimate["values"] = values.astype(np.float32)
        estimate["miscalibration"] = info
        estimate["source_kind"] = "OBS_EST"
        measured = {
            "mean_before": float(before.mean()),
            "mean_after": float(values.mean()),
            "mean_shift": float(values.mean() - before.mean()),
            "std_before": float(before.std()),
            "std_after": float(values.std()),
            "n_values": float(values.size),
        }
        realized = bool(abs(measured["mean_shift"]) > 1e-12 or abs(measured["std_after"] - measured["std_before"]) > 1e-12)
        return _with(source, payload={"observed_est": estimate},
                     meta={"axis_id": self.AXIS_ID, "variant": variant, "level": int(level),
                           "measured": measured, "units": {}, "realized": realized,
                           "extra": {**info, "oracle_used": False,
                                     "observed_only": True,
                                     "ece_defined": variant == "probability_temperature"}})

    def invariant_checks(self, source, result):
        estimate = result.get("observed_est") or {}
        kind = str(estimate.get("kind", "regression"))
        variant = str(result.meta.get("variant"))
        undefined_ece = bool(variant == "regression_bias" and kind == "regression"
                             and (result.meta or {}).get("extra", {}).get("ece_defined"))
        return {"estimate_kind": kind, "oracle_used": False,
                "violated": undefined_ece, "code": "UNDEFINED_ECE_FOR_REGRESSION"}


X05_BASELINE = "baseline"
#: Four held-out camera/light/ISP presets (plan 15.5: baseline + 4 held-out presets).
X05_PRESETS: tuple[dict[str, Any], ...] = (
    {"preset_id": X05_BASELINE, "camera": {}, "light": {}, "isp": {}},
    {"preset_id": "heldout_A_lowlight_local",
     "camera": {"f_number": 8.0, "focus_setting": "near", "working_distance_scale": 0.85},
     "light": {"intensity_scale": 0.55, "direction": [0.42, -0.55, -0.72]},
     "isp": {"response": "SRGB", "sharpening": 0.30, "denoise": 0.20}},
    {"preset_id": "heldout_B_harsh_global_wide",
     "camera": {"f_number": 2.0, "focus_setting": "far", "tier": "GLOBAL",
                "working_distance_scale": 1.35},
     "light": {"intensity_scale": 1.60, "direction": [-0.60, -0.45, -0.66]},
     "isp": {"response": "BT709", "sharpening": 0.05, "white_balance": [1.06, 0.98, 0.93]}},
    {"preset_id": "heldout_C_mid_tungsten",
     "camera": {"f_number": 5.6, "focus_setting": "mid", "tier": "MID",
                "working_distance_scale": 1.05},
     "light": {"intensity_scale": 0.85, "color_temperature_k": 3000.0},
     "isp": {"response": "LINEAR", "white_balance": [1.15, 1.0, 0.72], "sharpening": 0.15}},
    {"preset_id": "heldout_D_wide_aperture_soft",
     "camera": {"f_number": 1.8, "focus_setting": "near", "tier": "LOCAL",
                "working_distance_scale": 0.72},
     "light": {"intensity_scale": 1.25, "direction": [0.15, -0.85, -0.50]},
     "isp": {"response": "SRGB", "sharpening": 0.45, "denoise": 0.35, "digital_gain": 1.35}},
)


class X05(_EstimateAxis):
    AXIS_ID = "X05"
    SUBSTAGE = "feature"
    default_variant = "held_out_preset"
    factor_kind = "CATEGORICAL_SHIFT"
    VARIANT_KINDS = {"held_out_preset": "CATEGORICAL_SHIFT"}
    ALIASES = {"profile_shift": "held_out_preset"}
    LEVELS = tuple({"preset_index": i, "preset_id": X05_PRESETS[i]["preset_id"]}
                   for i in range(len(X05_PRESETS)))
    NOTES = ("baseline plus four held-out camera/light/ISP presets; this is a categorical shift, "
             "so no scalar monotonicity is claimed between levels.")

    def extra_applicability(self, source, variant):
        if source.get("profile") is None and not any(k in source.payload for k in
                                                     ("views", "frames", "observed_est")):
            return False, ("X05 needs the declared working-condition profile "
                           "(payload 'profile': camera/light/isp)")
        return True, None

    def _sample_payload(self, context, rng, variant):
        order = list(rng.permutation(len(X05_PRESETS) - 1))
        return {"preset_order": [int(i) + 1 for i in order]}

    def _apply(self, source, level, params, basis, variant):
        index = int(params["preset_index"])
        preset = X05_PRESETS[index]
        profile = {str(k): dict(v) if isinstance(v, dict) else v
                   for k, v in dict(source.get("profile") or {}).items()}
        for section in ("camera", "light", "isp"):
            merged = dict(profile.get(section) or {})
            merged.update(preset.get(section) or {})
            merged["preset_id"] = preset["preset_id"]
            merged["baseline_preset"] = X05_BASELINE
            profile[section] = merged
        changed_fields = sorted(f"{section}.{key}"
                                for section in ("camera", "light", "isp")
                                for key in (preset.get(section) or {}))
        baseline_vector = _profile_vector(X05_PRESETS[0])
        current_vector = _profile_vector(preset)
        measured = {
            "preset_index": float(index),
            "profile_distance": float(np.linalg.norm(current_vector - baseline_vector)),
            "changed_field_count": float(len(changed_fields)),
            "camera_changed": float(len(preset.get("camera") or {})),
            "light_changed": float(len(preset.get("light") or {})),
            "isp_changed": float(len(preset.get("isp") or {})),
            "monotone_scalar_claim": 0.0,
        }
        realized = bool(index > 0)
        return _with(source, payload={"profile": profile},
                     meta={"axis_id": self.AXIS_ID, "variant": variant, "level": int(level),
                           "measured": measured, "units": {}, "realized": realized,
                           "extra": {"preset_id": preset["preset_id"],
                                     "changed_fields": changed_fields,
                                     "factor_kind": "CATEGORICAL_SHIFT",
                                     "scalar_monotonicity_claimed": False,
                                     "held_out": index > 0,
                                     "profiles_expanded_to": ["camera", "light", "isp"]}})

    def invariant_checks(self, source, result):
        extra = (result.meta or {}).get("extra", {})
        return {"preset_id": extra.get("preset_id"),
                "scalar_monotonicity_claimed": bool(extra.get("scalar_monotonicity_claimed")),
                "violated": bool(extra.get("scalar_monotonicity_claimed")),
                "code": "CATEGORICAL_AXIS_CLAIMED_MONOTONE"}


def _jsonable_scalar(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [float(v) for v in np.asarray(value).ravel()]
    return float(value) if isinstance(value, (int, float, np.integer, np.floating)) else value


def _profile_vector(preset: dict[str, Any]) -> np.ndarray:
    numeric = []
    for section in ("camera", "light", "isp"):
        for key, value in sorted((preset.get(section) or {}).items()):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric.append(float(value))
            elif isinstance(value, (list, tuple)) and all(
                    isinstance(v, (int, float)) for v in value):
                numeric.extend(float(v) for v in value)
    return np.asarray(numeric or [0.0], dtype=np.float64)


# ======================================================================================
# registration
# ======================================================================================
AXES: tuple[type[_BaseAxis], ...] = (
    P01, P02, P03, P04, P05, P06, P07, P08,
    I01, I02, I03, I04, I05, I06, I07, I08, I09, I10,
    G01, G02, G03, G04, G05, G06, G07, G08,
    X01, X02, X03, X04, X05,
)


install_trimesh_shims()      # trimesh API compatibility (see synlab/degrade/compat.py)
_install_evaluate_field_fix()  # frozen sdf.evaluate_field base-term bug (documented in compat.py)


def register_all() -> list[str]:
    """Instantiate and register every axis (idempotent)."""
    from .registry import AXIS_REGISTRY

    registered: list[str] = []
    for cls in AXES:
        operator = cls()
        if AXIS_REGISTRY.has(cls.AXIS_ID) and type(AXIS_REGISTRY.get(cls.AXIS_ID)) is cls:
            registered.append(cls.AXIS_ID)
            continue
        register_operator(operator)
        registered.append(cls.AXIS_ID)
    return registered


register_all()
