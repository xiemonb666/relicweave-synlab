"""Axis operator protocol, registry and shared measurement plumbing (plan 15.1, 30.9).

Every one of the 31 degradation axes is an :class:`AxisOperator` subclass instance
registered here.  The registry is the single place where stage, unit, applicability,
cost class, declared field writes and label invalidations live; ``synlab.config``
imports :func:`get_operator` when it compiles a recipe DAG.

Honesty rules encoded in this module:

* ``apply`` for ``level == 0`` **always** returns the source payload unchanged (the
  framework enforces it, subclasses cannot opt out);
* ``apply`` must not draw randomness: the frozen :class:`DegradationBasis` sampled by
  ``sample_basis`` carries every random decision, so all five levels of an axis share
  one basis and stay paired (plan 5.1, 15.7);
* ``measure`` reports *measured* quantities between source and result; an axis whose
  declared effect is not observed reports ``realized=False`` and the caller turns that
  into ``OPERATOR_NOT_REALIZED`` instead of a silent success.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Iterable

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..roles import UNIT_NONE
from ..schemas.spec import AXIS_IDS
from ..seeds import basis_id as make_basis_id, make_rng, seed_ref
from ..schemas.runtime import DegradationBasis, Measurement
from .sources import SourceBundle

#: All twelve registered materials; individual axes narrow this with ``SUPPORTED_MATERIALS``.
ALL_MATERIALS: tuple[str, ...] = tuple(f"M{i:02d}" for i in range(1, 13))

FACTOR_KINDS = ("SINGLE_PARAMETER", "ONE_DIMENSIONAL_RECIPE", "BUNDLED_STRESS", "CATEGORICAL_SHIFT")

STAGE_PHYSICAL = "PHYSICAL"
STAGE_SCENE = "SCENE"
STAGE_OPTICS = "OPTICS"
STAGE_SENSOR = "SENSOR"
STAGE_ISP = "ISP"
STAGE_GEOMETRY_OBS = "GEOMETRY_OBS"
STAGE_FEATURE_PROTOCOL = "FEATURE_PROTOCOL"

#: Substage names understood by ``synlab.schemas.spec.SUBSTAGE_ORDER``.
SUB_EXPOSURE = "exposure"
SUB_FRAME_SELECTION = "frame_selection"
SUB_MASK_ESTIMATION = "mask_estimation"
SUB_SFM = "sfm"
SUB_PER_VIEW_GEOMETRY = "per_view_geometry"
SUB_FUSION = "fusion"
SUB_SURFACE = "surface"
SUB_QUALITY = "quality"
SUB_FEATURE = "feature"


class FrozenRng:
    """Guard passed to ``apply``: drawing randomness outside ``sample_basis`` is an error."""

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - guard path
        raise SynLabError(
            ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
            f"apply() must not draw randomness ({item}); freeze every random decision in "
            f"sample_basis() and derive per-level noise from basis_rng(basis, level, stream)",
            stage="degrade.registry",
        )


def basis_rng(basis: DegradationBasis, level: int, stream: str = "apply") -> np.random.Generator:
    """Deterministic generator derived from a frozen basis (no per-level redraw drift)."""
    key = int(basis.basis_id[:16], 16) if basis.basis_id else 0
    return make_rng(key, basis.axis_id, basis.variant, int(level), stream)


@dataclass
class AxisOperator:
    """Base class for the 31 degradation axes.

    Every declaration is a :class:`typing.ClassVar`, *not* a dataclass field: subclasses
    override them with plain class attributes (``AXIS_ID = "P01"``) and no mutable default
    is ever shared between instances.  (The previous ``VARIANT_KINDS: dict = {}`` field made
    ``import synlab.degrade.registry`` fail with *mutable default ... use default_factory*.)
    """

    AXIS_ID: ClassVar[str] = ""
    STAGE: ClassVar[str] = ""
    SUBSTAGE: ClassVar[str] = ""
    UNIT: ClassVar[str] = UNIT_NONE
    SUPPORTED_MATERIALS: ClassVar[tuple[str, ...]] = ALL_MATERIALS
    COST_CLASS: ClassVar[str] = "medium"
    VERSION: ClassVar[str] = "1.0"
    READS: ClassVar[tuple[str, ...]] = ("source:asset",)
    WRITES: ClassVar[tuple[str, ...]] = ("asset",)
    LABEL_INVALIDATIONS: ClassVar[tuple[str, ...]] = ()
    ALLOWED_PROFILES: ClassVar[tuple[str, ...]] = ("PHONE_RGB", "SENSOR_PROXY",
                                                   "SENSOR_UPPER_BOUND")
    default_variant: ClassVar[str] = ""
    factor_kind: ClassVar[str] = "SINGLE_PARAMETER"
    ACCEPTED_SOURCES: ClassVar[tuple[str, ...]] = ()
    #: per-variant factor kind override; variants absent here use ``factor_kind``
    VARIANT_KINDS: ClassVar[dict[str, str]] = {}
    #: prerequisite axes that must appear earlier in a compiled recipe (plan 30.2)
    PREREQUISITES: ClassVar[tuple[str, ...]] = ()
    LEVEL_COUNT: ClassVar[int] = 5
    #: relative-tolerance below which a declared effect counts as "not realized"
    EFFECT_EPS: ClassVar[float] = 1e-9
    ALIASES: ClassVar[dict[str, str]] = {}
    #: number of independent mothers required by the public acceptance contract (plan 15.7)
    MIN_INDEPENDENT_MOTHERS: ClassVar[int] = 20
    #: True when ``sample_basis`` needs the actual source payload (ROI/pose/appearance)
    BASIS_NEEDS_SOURCE: ClassVar[bool] = False

    # ------------------------------------------------------------------ declaration
    def parameter_schema(self) -> dict[str, Any]:
        """JSON schema (or schema-like description) of the per-level parameters."""
        raise NotImplementedError(f"{type(self).__name__}.parameter_schema")

    def level_parameters(self, level: int) -> dict[str, Any]:
        """Declared parameters of one of the five levels (level 0 is the identity)."""
        raise NotImplementedError(f"{type(self).__name__}.level_parameters")

    def variants(self) -> list[str]:
        """Registered variants; the default variant comes first."""
        names = [self.default_variant] if self.default_variant else []
        names.extend(v for v in self.VARIANT_KINDS if v not in names)
        return names

    def resolve_variant(self, variant: str | None) -> str:
        name = variant or self.default_variant
        name = self.ALIASES.get(name, name)
        if name not in self.variants():
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"axis {self.AXIS_ID}: unknown variant {variant!r}; "
                              f"registered: {self.variants()}", stage="degrade.registry")
        return name

    def factor_kind_for(self, variant: str) -> str:
        kind = self.VARIANT_KINDS.get(variant, self.factor_kind)
        if kind not in FACTOR_KINDS:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"axis {self.AXIS_ID}/{variant}: bad factor_kind {kind!r}",
                              stage="degrade.registry")
        return kind

    def levels(self) -> list[int]:
        return list(range(self.LEVEL_COUNT))

    def declared(self) -> dict[str, Any]:
        return {
            "axis_id": self.AXIS_ID, "stage": self.STAGE, "substage": self.SUBSTAGE,
            "unit": self.UNIT, "cost_class": self.COST_CLASS, "version": self.VERSION,
            "reads": list(self.READS), "writes": list(self.WRITES),
            "label_invalidations": list(self.LABEL_INVALIDATIONS),
            "allowed_profiles": list(self.ALLOWED_PROFILES),
            "supported_materials": list(self.SUPPORTED_MATERIALS),
            "variants": self.variants(), "default_variant": self.default_variant,
            "factor_kinds": {v: self.factor_kind_for(v) for v in self.variants()},
            "accepted_sources": list(self.ACCEPTED_SOURCES),
            "prerequisites": list(self.PREREQUISITES),
            "parameter_schema": self.parameter_schema(),
        }

    # ------------------------------------------------------------------ basis / applicability
    def sample_basis(self, context: dict[str, Any], rng: np.random.Generator,
                     variant: str | None = None) -> DegradationBasis:
        """Freeze every random decision of this axis once, shared by all five levels."""
        variant = self.resolve_variant(variant)
        lineage = str(context.get("lineage_id", "lineage"))
        fragment = str(context.get("fragment_id", "fragment"))
        master = int(context.get("master_seed", 0))
        payload = self._basis_payload(context, rng, variant)
        return DegradationBasis(
            axis_id=self.AXIS_ID, variant=variant,
            basis_id=make_basis_id(self.AXIS_ID, master, lineage, fragment),
            seed_ref=seed_ref(master, lineage, fragment, self.AXIS_ID, variant),
            payload=payload,
            meta={"declared_parameters": {lvl: self.level_parameters(lvl) for lvl in self.levels()}},
        )

    def _basis_payload(self, context: dict[str, Any], rng: np.random.Generator,
                       variant: str) -> dict[str, Any]:
        return {}

    def applicability(self, source: SourceBundle, variant: str) -> tuple[bool, str | None]:
        """(applicable, na_reason).  Data qualification happens *before* any score."""
        if self.ACCEPTED_SOURCES and source.source_kind not in self.ACCEPTED_SOURCES:
            return False, (f"source_kind {source.source_kind} not accepted by {self.AXIS_ID}; "
                           f"expected {list(self.ACCEPTED_SOURCES)}")
        return True, None

    # ------------------------------------------------------------------ apply
    def apply(self, source: SourceBundle, level: int, basis: DegradationBasis,
              rng: FrozenRng | None = None, parameters: dict[str, Any] | None = None
              ) -> SourceBundle:
        """Framework entry point; level 0 is enforced identity.

        ``parameters`` are the effective per-level parameters: :func:`synlab.degrade.api._apply_impl`
        merges the caller's overrides into :meth:`params_for` and passes the result here, so a
        compiled recipe node or an explicit ``parameters=`` override really reaches the operator
        instead of only appearing in the recorded ``planned`` block.
        """
        if level not in self.levels():
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"axis {self.AXIS_ID}: level {level} outside 0..{self.LEVEL_COUNT - 1}",
                              stage="degrade.apply")
        variant = self.resolve_variant(basis.variant)
        if level == 0:
            return source
        if basis.axis_id != self.AXIS_ID:
            raise SynLabError(ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
                              f"basis for {basis.axis_id} used on axis {self.AXIS_ID}",
                              stage="degrade.apply")
        effective = dict(self.params_for(level, variant))
        effective.update(parameters or {})
        return self._apply(source, level, effective, basis, variant)

    def _apply(self, source: SourceBundle, level: int, params: dict[str, Any],
               basis: DegradationBasis, variant: str) -> SourceBundle:
        raise NotImplementedError(f"{type(self).__name__}._apply")

    # ------------------------------------------------------------------ measure / validate
    def measure(self, source: SourceBundle, result: SourceBundle,
                context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Measure the realized effect.

        Returns ``{"measured": {name: float}, "units": {name: str}, "realized": bool,
        "extra": {...}}`` plus optional ``failure_code``/``na_reason``.
        """
        raise NotImplementedError(f"{type(self).__name__}.measure")

    def validate(self, source: SourceBundle, result: SourceBundle,
                 measurement: Measurement) -> None:
        """Contract checks that must hold for every level of this axis."""
        if measurement.identity:
            if result.content_hash() != source.content_hash():
                raise SynLabError(ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
                                  f"{self.AXIS_ID}: level 0 changed the source content hash",
                                  stage="degrade.validate")
        if not measurement.valid:
            return
        if measurement.level > 0 and not measurement.realized:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                              f"{self.AXIS_ID}/{measurement.variant} level {measurement.level}: "
                              f"declared degradation was not measured in the output",
                              stage="degrade.validate", measurements=dict(measurement.measured))


class AxisRegistry:
    """Process-wide axis registry keyed by axis id."""

    def __init__(self) -> None:
        self._operators: dict[str, AxisOperator] = {}

    def register(self, operator: AxisOperator) -> AxisOperator:
        axis_id = operator.AXIS_ID
        if axis_id not in AXIS_IDS:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"cannot register unknown axis {axis_id!r}", stage="degrade.registry")
        if not operator.STAGE:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"axis {axis_id} must declare STAGE", stage="degrade.registry")
        if not operator.default_variant:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"axis {axis_id} must declare default_variant", stage="degrade.registry")
        existing = self._operators.get(axis_id)
        if existing is not None and type(existing) is not type(operator):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"duplicate registration for axis {axis_id}", stage="degrade.registry")
        self._operators[axis_id] = operator
        return operator

    def get(self, axis_id: str) -> AxisOperator:
        if axis_id not in self._operators:
            self._ensure_loaded()
        if axis_id not in self._operators:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"axis {axis_id} is declared in the schema but not implemented",
                              stage="degrade.registry")
        return self._operators[axis_id]

    def has(self, axis_id: str) -> bool:
        if axis_id not in self._operators:
            self._ensure_loaded()
        return axis_id in self._operators

    def ids(self) -> list[str]:
        self._ensure_loaded()
        return sorted(self._operators)

    def missing(self) -> list[str]:
        self._ensure_loaded()
        return [axis for axis in AXIS_IDS if axis not in self._operators]

    def all(self) -> dict[str, AxisOperator]:
        self._ensure_loaded()
        return dict(self._operators)

    def _ensure_loaded(self) -> None:
        from . import axes  # noqa: F401  (registers every axis on import)

    def status_table(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return [self._operators[a].declared() for a in sorted(self._operators)]


AXIS_REGISTRY = AxisRegistry()


def register_operator(operator: AxisOperator) -> AxisOperator:
    return AXIS_REGISTRY.register(operator)


def get_operator(axis_id: str) -> AxisOperator:
    """Return the registered operator for ``axis_id`` (raises for unknown/unimplemented)."""
    return AXIS_REGISTRY.get(axis_id)


def measurement_from(axis: AxisOperator, *, level: int, variant: str, planned: dict[str, Any],
                     measured: dict[str, Any], units: dict[str, str], identity: bool,
                     realized: bool, source_hash: str, result_hash: str, valid: bool = True,
                     na_reason: str | None = None, failure_code: str | None = None,
                     extra: dict[str, Any] | None = None,
                     calibration_status: str = "UNCALIBRATED") -> Measurement:
    return Measurement(
        axis_id=axis.AXIS_ID, variant=variant, level=int(level),
        factor_kind=axis.factor_kind_for(variant), planned=dict(planned), measured=dict(measured),
        units=dict(units), identity=bool(identity), realized=bool(realized), valid=bool(valid),
        na_reason=na_reason, failure_code=failure_code, source_hash=source_hash,
        result_hash=result_hash, calibration_status=calibration_status, extra=dict(extra or {}),
    )


def changed(measured: dict[str, float], keys: Iterable[str] | None = None,
            eps: float = 1e-12) -> bool:
    """True when any of the measured quantities is non-zero beyond ``eps``."""
    items = measured.items() if keys is None else ((k, measured.get(k, 0.0)) for k in keys)
    return any(abs(float(v)) > eps for _, v in items)


def summary_table(operators: dict[str, AxisOperator] | None = None) -> list[dict[str, Any]]:
    """Per-axis declaration table (used by docs, CLI and tests)."""
    operators = operators if operators is not None else AXIS_REGISTRY.all()
    rows = []
    for axis_id in sorted(operators):
        op = operators[axis_id]
        rows.append({
            "axis_id": axis_id, "stage": op.STAGE, "substage": op.SUBSTAGE, "unit": op.UNIT,
            "cost_class": op.COST_CLASS, "version": op.VERSION,
            "variants": op.variants(), "default_variant": op.default_variant,
            "factor_kind": op.factor_kind_for(op.default_variant),
            "reads": list(op.READS), "writes": list(op.WRITES),
            "label_invalidations": list(op.LABEL_INVALIDATIONS),
            "supported_materials": list(op.SUPPORTED_MATERIALS),
            "levels": [op.level_parameters(lvl) for lvl in op.levels()],
        })
    return rows
