"""Public façade of the parametric mother generator (plan 7, frozen contract in
``docs/a12/interfaces.md`` section 2).

Exported functions
------------------
``create_mother(vessel_id, material_id, params, rng, *, mother_id="") -> MotherGeometry``
    Build one watertight closed material body in millimetres, with face-level
    ``surface_tag``/``component_id`` semantics and frozen charts.
``audit_mother(mother) -> dict``
    Wrap :func:`synlab.mothers.audit.audit_mother` and re-raise structural problems as
    structured errors; QA failures come back with ``ok=False`` and real metrics.
``sample_parameters(vessel_id, n, rng, *, bounds=None) -> list[dict]``
    Latin-hypercube draw of *feasible* parameter dictionaries (Scipy QMC).  Rejected
    combinations are counted and reported, never silently replaced by a default.
``commit_mother(store, mother, *, lineage_id, split, ancestry=()) -> AssetRecord``
``load_mother(store, asset_id) -> MotherGeometry``
    Round-trip through the content-addressed store with ``role="mother_mesh"``.

All twenty-four registered vessels (V01..V24) are reachable through this module; the
construction code lives in ``synlab.mothers.vessels`` and each entry point is registered
with its own pydantic parameter model, so no two ids share one mesh under a new name.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import trimesh

from ..errors import ErrorCode, SynLabError
from ..registry import REGISTRY, RegistryEntry
from ..roles import (FRAME_WORLD, ROLE_MOTHER_MESH, SCHEMA_MOTHER, UNIT_MM)
from ..schemas.runtime import Chart, MotherGeometry
from ..seeds import seed64
from ..storage.mesh_io import with_face_attrs
from ..storage.store import AssetStore, AssetRecord, QA_FAIL, QA_PASS
from . import audit as _audit
from .charts import chart_payload, charts_from_payload
from .tagging import TAG_NAMES, TAG_UNASSIGNED
from .vessels import (  # noqa: F401  (import registers V01..V24)
    group_composite, group_extrude, group_revolve, group_sheet,
)

STAGE = "mothers.api"

#: Construction families whose bodies are surfaces of revolution with a real cavity.
REVOLVE_FAMILIES = ("revolve", "revolve+attachment", "revolve+revolve", "revolve+foot",
                    "revolve+spout", "revolve+lid", "revolve+pierced")

#: Sampling policy: the parameters that actually move the silhouette get the quota, and
#: wall/base thickness is drawn from the plan's 2..10 mm band (plan 7.1).
MIN_WALL_SAMPLING_MM = 1.6
MAX_WALL_SAMPLING_MM = 10.0
MIN_BASE_SAMPLING_MM = 2.0
MAX_BASE_SAMPLING_MM = 18.0

#: Parameters that are never drawn by the sampler: they are not shape parameters of the
#: vessel body, or they select a construction variant rather than a dimension.
NON_SHAPE_FIELDS = frozenset({"warp_lobes"})

_SAMPLER_OVERRIDES: dict[str, tuple[float, float] | str] = {
    "wall_mm": (MIN_WALL_SAMPLING_MM, MAX_WALL_SAMPLING_MM),
    "base_mm": (MIN_BASE_SAMPLING_MM, MAX_BASE_SAMPLING_MM),
    "warp_amplitude": (0.0, 0.035),
    "warp_eccentricity_mm": (0.0, 2.5),
    "hole_count": "int",
    "foot_count": "int",
    "repeat_count": "int",
    "repeat_columns": "int",
    "repeat_rows": "int",
}


# ---------------------------------------------------------------------------------------
# registry access
# ---------------------------------------------------------------------------------------
def ensure_registered() -> None:
    """Import every vessel module so that the registry is complete."""
    from . import vessels  # noqa: F401  (package import registers all families)


def vessel_entry(vessel_id: str) -> RegistryEntry:
    if not REGISTRY.has("vessel", vessel_id):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unregistered vessel id {vessel_id!r}",
                          stage=STAGE,
                          measurements={"registered": REGISTRY.ids("vessel")})
    return REGISTRY.get("vessel", vessel_id)


def vessel_ids() -> list[str]:
    ensure_registered()
    return REGISTRY.ids("vessel")


# ---------------------------------------------------------------------------------------
# parameter helpers
# ---------------------------------------------------------------------------------------
#: Fallbacks only for fields whose schema carries no usable numeric bound.
_PROTOTYPE_FALLBACKS: dict[str, float] = {
    "wall_mm": 4.0,
    "base_mm": 6.5,
    "warp_amplitude": 0.02,
    "warp_eccentricity_mm": 0.6,
    "warp_lobes": 2.0,
}


def prototype_params(vessel_id: str) -> dict[str, Any]:
    """A valid default parameter set derived from the *registered* schema.

    Fields without a default get the midpoint of their declared ``ge``/``le`` bounds, so
    an empty request (``create_mother(V01, M01, {}, rng)``) still builds the prototype the
    registry describes instead of failing or inventing a hidden constant.  Explicit
    fallbacks exist only where the schema declares no numeric range.
    """
    entry = vessel_entry(vessel_id)
    model = entry.param_model
    if model is None:  # pragma: no cover
        return {}
    out: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if not field.is_required():
            continue
        low, high, is_int = _field_bounds(field)
        if low is not None and high is not None and high > low:
            mid = 0.5 * (low + high)
            out[name] = int(round(mid)) if is_int else float(mid)
        elif isinstance(field.default, (int, float, bool, str)):
            out[name] = field.default
        elif name in _PROTOTYPE_FALLBACKS:
            value = _PROTOTYPE_FALLBACKS[name]
            out[name] = int(value) if is_int else float(value)
        else:
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"{vessel_id}: required field {name!r} has no default and no numeric bounds; "
                "the parameter model must expose ge/le for the sampler",
                stage=f"{STAGE}.prototype_params",
            )
    return out


def canonical_params(vessel_id: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate ``params`` against the vessel's pydantic model and return plain JSON.

    Missing fields are filled from :func:`prototype_params` (schema midpoints) so a
    partial request is completed rather than silently dropped.  Unknown keys, out-of-range
    values and non-positive thicknesses raise ``SynLabError(MOTHER_INVALID)`` with the
    offending field recorded.
    """
    entry = vessel_entry(vessel_id)
    model = entry.param_model
    raw = {**prototype_params(vessel_id), **dict(params or {})}
    if model is None:  # pragma: no cover - every registered vessel ships a model
        return raw
    try:
        validated = model.model_validate(raw)
    except Exception as exc:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            f"{vessel_id}: invalid parameters: {exc}",
            stage=f"{STAGE}.canonical_params",
            measurements={"vessel_id": vessel_id, "params": _jsonable_params(raw)},
        ) from exc
    out = validated.model_dump(mode="python")
    for key in ("wall_mm", "base_mm"):
        if key in out and float(out[key]) <= 0:
            raise SynLabError(ErrorCode.MOTHER_INVALID,
                              f"{vessel_id}: {key} must be positive, got {out[key]!r}",
                              stage=f"{STAGE}.canonical_params",
                              measurements={"vessel_id": vessel_id, key: out[key]})
    return _jsonable_params(out)


def default_params(vessel_id: str) -> dict[str, Any]:
    """The vessel's own defaults, with required fields taken from the schema midpoint."""
    return canonical_params(vessel_id, {})


def _jsonable_params(params: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, (np.floating, np.integer)):
            out[key] = value.item()
        elif isinstance(value, (bool, int, float, str)) or value is None:
            out[key] = value
        elif isinstance(value, (list, tuple)):
            out[key] = [_jsonable_params({"v": v})["v"] for v in value]
        elif isinstance(value, Mapping):
            out[key] = _jsonable_params(value)
        else:  # pragma: no cover - defensive
            out[key] = str(value)
    return out


def shape_parameters(vessel_id: str) -> list[str]:
    """Fields that actually change the silhouette (documented per vessel in the doc)."""
    entry = vessel_entry(vessel_id)
    return list((entry.applicable or {}).get("shape_parameters") or [])


# ---------------------------------------------------------------------------------------
# mother construction
# ---------------------------------------------------------------------------------------
def create_mother(vessel_id: str, material_id: str, params: dict, rng,
                  *, mother_id: str = "", max_repair_attempts: int = 3) -> MotherGeometry:
    """Build one mother.  Raises ``SynLabError`` instead of returning an empty mesh.

    A request whose base plate is *provably* too thick for the outline it has to turn (the
    offset profile would fold) is repaired from the numeric diagnosis of the real build and then
    rebuilt; the repair is recorded in the mother metadata and the number of attempts is
    bounded.  A request that still fails after those attempts raises the structured
    ``MOTHER_INVALID``/``TARGET_INFEASIBLE`` error with the last measurement - nothing is
    silently replaced by a default mesh, and a wall below the vessel's gate is always rejected
    rather than thickened.
    """
    ensure_registered()
    if not isinstance(rng, np.random.Generator):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "rng must be a numpy.random.Generator sub-stream",
                          stage=f"{STAGE}.create_mother",
                          measurements={"got": type(rng).__name__})
    if not isinstance(material_id, str) or not material_id:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "material_id must be a non-empty string",
                          stage=f"{STAGE}.create_mother")
    entry = vessel_entry(vessel_id)
    clean = canonical_params(vessel_id, params)
    builder = REGISTRY.resolve_builder("vessel", vessel_id)
    repairs: list[dict[str, Any]] = []
    last_error: SynLabError | None = None
    for attempt in range(int(max(1, max_repair_attempts))):
        try:
            assembly = builder(copy.deepcopy(clean), rng, material_id)
        except SynLabError as exc:
            last_error = exc
            repaired = repair_params(vessel_id, clean, exc)
            if repaired is None or repaired == clean:
                raise
            repairs.append({"attempt": attempt + 1, "code": str(exc.code),
                            "message": exc.message[:200],
                            "params_before": copy.deepcopy(clean),
                            "params_after": copy.deepcopy(repaired)})
            clean = canonical_params(vessel_id, repaired)
            continue
        mother = _wrap_assembly(entry, assembly, material_id=material_id, params=clean,
                                mother_id=mother_id or f"{vessel_id}-{material_id}")
        if repairs:
            mother.meta["parameter_repairs"] = repairs
        return mother
    if last_error is not None:
        raise last_error
    raise SynLabError(  # pragma: no cover - defensive
        ErrorCode.MOTHER_INVALID, f"{vessel_id}: no build attempt succeeded",
        stage=f"{STAGE}.create_mother")


def repair_params(vessel_id: str, params: Mapping[str, Any],
                  exc: SynLabError) -> dict[str, Any] | None:
    """Repair a request from the measured failure; ``None`` means "not repairable here".

    Only the *base plate* is repaired, and only when the failure says the offset profile folded
    at a corner because the plate is too thick for the outline it has to turn.  That is a real
    design limit with a unique direction (thinner), so the plate is scaled down and rebuilt.

    A wall below the vessel's gate is **not** repaired: the plan lists thin walls as a stress
    category, so the request is rejected with ``MOTHER_INVALID`` and the measured gate instead of
    being silently thickened.  Only fields the vessel actually declares are touched, and every
    repair is validated against the vessel's own model before it is returned.
    """
    entry = vessel_entry(vessel_id)
    model = entry.param_model
    declared = set(model.model_fields) if model is not None else set()
    out = dict(params)
    message = exc.message
    measurements = dict(exc.measurements or {})
    changed_fields: list[str] = []
    if "half thickness exceeds the local profile curvature" in message and "base_mm" in declared:
        base = float(out.get("base_mm", measurements.get("t_max_mm", 0.0)) or 0.0)
        curvature = float(measurements.get("r_min_curvature_mm", 0.0) or 0.0)
        if base > 0 and curvature > 0:
            new = max(0.35 * base, min(base - 0.5, 0.9 * curvature))
            if new < base - 1e-6:
                out["base_mm"] = round(float(new), 4)
                changed_fields.append("base_mm")
    if not changed_fields:
        return None
    try:
        validated = canonical_params(vessel_id, out)
    except SynLabError:
        return None
    if validated == canonical_params(vessel_id, params):
        return None
    return validated


def _wrap_assembly(entry: RegistryEntry, assembly: Any, *, material_id: str,
                   params: dict[str, Any], mother_id: str) -> MotherGeometry:
    mesh = getattr(assembly, "mesh", None)
    tags = np.asarray(getattr(assembly, "surface_tag", np.zeros(0, dtype=np.int32)),
                      dtype=np.int32)
    comp = np.asarray(getattr(assembly, "component_id", np.zeros(0, dtype=np.int32)),
                      dtype=np.int32)
    charts: Sequence[Chart] = list(getattr(assembly, "charts", []) or [])
    meta: dict[str, Any] = dict(getattr(assembly, "meta", {}) or {})
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"{entry.id}: the builder returned no mesh faces",
                          stage=f"{STAGE}.create_mother",
                          measurements={"vessel_id": entry.id, "params": params})
    if tags.shape[0] != len(mesh.faces):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"{entry.id}: surface_tag has {tags.shape[0]} entries for "
                          f"{len(mesh.faces)} faces",
                          stage=f"{STAGE}.create_mother")
    if comp.shape[0] != len(mesh.faces):
        comp = np.zeros(len(mesh.faces), dtype=np.int32)
    if not charts:
        raise SynLabError(ErrorCode.MOTHER_INVALID, f"{entry.id}: builder produced no charts",
                          stage=f"{STAGE}.create_mother")
    valid = sorted(int(k) for k in TAG_NAMES)
    if not np.all(np.isin(tags, valid)):
        bad = sorted({int(v) for v in np.unique(tags) if int(v) not in valid})
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"{entry.id}: face tags outside the frozen vocabulary: {bad}",
                          stage=f"{STAGE}.create_mother")
    if int(TAG_UNASSIGNED) in {int(v) for v in np.unique(tags)}:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"{entry.id}: {int(np.count_nonzero(tags == TAG_UNASSIGNED))} faces "
                          "kept the unassigned tag",
                          stage=f"{STAGE}.create_mother")
    with_face_attrs(mesh, surface_tag=tags, component_id=comp,
                    source_triangle=np.arange(len(mesh.faces), dtype=np.int32))
    meta.setdefault("vessel_name", entry.name)
    meta.setdefault("vessel_family", str((entry.applicable or {}).get("family", "unknown")))
    meta.setdefault("registry_version", entry.version)
    meta.setdefault("builder", entry.meta.get("builder_name", ""))
    meta.setdefault("params", params)
    meta.setdefault("surface_tag_names", {int(k): v for k, v in TAG_NAMES.items()})
    meta["n_faces"] = int(len(mesh.faces))
    meta["geometry_hash"] = _audit.geometry_hash(mesh)
    if "min_wall_mm" not in meta:
        meta["min_wall_mm"] = float((entry.applicable or {}).get("min_wall_mm", 0.8))
    meta.setdefault("requires_cavity", bool((entry.applicable or {}).get("requires_cavity", False)))
    return MotherGeometry(
        mesh=mesh,
        face_surface_tag=tags,
        surface_tag_names={int(k): v for k, v in TAG_NAMES.items()},
        charts=list(charts),
        vessel_id=entry.id,
        material_id=material_id,
        params=params,
        mother_id=mother_id,
        meta=meta,
    )


# ---------------------------------------------------------------------------------------
# QA
# ---------------------------------------------------------------------------------------
def audit_mother(mother: MotherGeometry, *, max_thickness_probes: int = 320,
                 run_self_intersection: bool = True) -> dict[str, Any]:
    """Return-before-output QA of one mother (plan 7.3).

    ``ok`` is a real boolean and ``metrics``/``checks`` carry the measured values.  A
    mother with no mesh, no charts or inconsistent face arrays raises
    ``SynLabError(MOTHER_INVALID)`` because those are structural, not tolerances.
    """
    if not isinstance(mother, MotherGeometry):  # pragma: no cover - defensive
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "audit_mother expects a MotherGeometry",
                          stage=f"{STAGE}.audit")
    mesh = mother.mesh
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "mother has no mesh faces",
                          stage=f"{STAGE}.audit",
                          measurements={"mother_id": mother.mother_id})
    if len(np.asarray(mother.face_surface_tag)) != len(mesh.faces):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "face_surface_tag length does not match the mesh",
                          stage=f"{STAGE}.audit",
                          measurements={"mother_id": mother.mother_id,
                                        "tags": int(len(np.asarray(mother.face_surface_tag))),
                                        "faces": int(len(mesh.faces))})
    if not mother.charts:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "mother has no charts",
                          stage=f"{STAGE}.audit",
                          measurements={"mother_id": mother.mother_id})
    return _audit.audit_mother(mother, max_thickness_probes=max_thickness_probes,
                               run_self_intersection=run_self_intersection)


def raise_on_failure(report: dict[str, Any], *, stage: str = f"{STAGE}.audit") -> None:
    _audit.raise_on_failure(report, stage=stage)


def geometry_hash(mesh: trimesh.Trimesh) -> str:
    return _audit.geometry_hash(mesh)


# ---------------------------------------------------------------------------------------
# parameter sampling (plan 7.3)
# ---------------------------------------------------------------------------------------
def _field_bounds(field: Any) -> tuple[float | None, float | None, bool]:
    """Extract (low, high, is_int) from a pydantic v2 field."""
    low: float | None = None
    high: float | None = None
    is_int = False
    for meta in getattr(field, "metadata", ()) or ():
        name = type(meta).__name__
        if name == "Ge":
            low = float(meta.ge)
        elif name == "Gt":
            low = float(meta.gt) + (1.0 if field.annotation is int else 1e-6)
        elif name == "Le":
            high = float(meta.le)
        elif name == "Lt":
            high = float(meta.lt) - (1.0 if field.annotation is int else 1e-6)
        elif name in ("MultipleOf", "MinLen", "MaxLen"):
            continue
    if field.annotation is int or str(field.annotation).startswith("int"):
        is_int = True
    if low is not None and is_int:
        low = float(np.ceil(low))
    if high is not None and is_int:
        high = float(np.floor(high))
    return low, high, is_int


def sampler_spec(vessel_id: str,
                 bounds: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Continuous fields of a vessel that the LHS sampler varies, with real bounds."""
    entry = vessel_entry(vessel_id)
    model = entry.param_model
    if model is None:  # pragma: no cover
        return {}
    declared_shape = set(shape_parameters(vessel_id))
    spec: dict[str, dict[str, Any]] = {}
    for name, field in model.model_fields.items():
        if name in NON_SHAPE_FIELDS:
            continue
        low, high, is_int = _field_bounds(field)
        override = _SAMPLER_OVERRIDES.get(name)
        if override is not None:
            if override == "int":
                is_int = True
            else:
                low, high = float(override[0]), float(override[1])
        if low is None or high is None or high <= low:
            continue
        if bounds and name in bounds:
            given = bounds[name]
            if isinstance(given, (list, tuple)) and len(given) == 2:
                low, high = float(given[0]), float(given[1])
        spec[name] = {"low": float(low), "high": float(high), "int": bool(is_int),
                      "shape": name in declared_shape}
    return spec


def sample_parameters(vessel_id: str, n: int, rng, *,
                      bounds: Mapping[str, Any] | None = None,
                      max_attempts: int | None = None,
                      require_feasible: bool = True) -> list[dict]:
    """Draw ``n`` parameter dictionaries with a Latin hypercube and a feasibility gate.

    The draw is *not* a full Cartesian product: SciPy's ``LatinHypercube`` fills the unit
    cube with one point per stratum in every dimension, then the per-field bounds map the
    design onto the registered schema.  Each candidate passes a cheap analytic pre-gate, and by
    default (``require_feasible``) it is also really built and audited, so ``sample_parameters``
    only returns parameter sets that produce a mother.  Rejected candidates are counted and
    reported; a draw that cannot be filled raises ``SynLabError(TARGET_INFEASIBLE)``.

    The function returns a plain ``list[dict]`` as the frozen interface requires; the
    rejection statistics are appended to ``synlab.mothers.api.LAST_SAMPLING_REPORT`` and are
    retrievable with :func:`last_sampling_report`.
    """
    global _LAST_SAMPLING_REPORT
    ensure_registered()
    if not isinstance(rng, np.random.Generator):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "rng must be numpy.random.Generator",
                          stage=f"{STAGE}.sample_parameters")
    n = int(n)
    if n <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"n must be positive, got {n}",
                          stage=f"{STAGE}.sample_parameters")
    spec = sampler_spec(vessel_id, bounds)
    if not spec:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{vessel_id} exposes no continuous sampler fields",
                          stage=f"{STAGE}.sample_parameters")
    names = sorted(spec)
    model = vessel_entry(vessel_id).param_model
    baseline = default_params(vessel_id)

    attempts_limit = int(max_attempts) if max_attempts is not None else max(8 * n, 64)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    attempted = 0
    while len(accepted) < n and attempted < attempts_limit:
        block = min(max(n - len(accepted), 1) * 2 + 4, attempts_limit - attempted)
        unit = _latin_hypercube(block, len(names), rng)
        for row in unit:
            attempted += 1
            candidate = dict(baseline)
            for column, name in enumerate(names):
                info = spec[name]
                value = info["low"] + float(row[column]) * (info["high"] - info["low"])
                candidate[name] = int(round(value)) if info["int"] else float(value)
            reason = _pre_gate(vessel_id, candidate)
            if reason is None and require_feasible:
                reason = _build_gate(vessel_id, candidate, rng)
            if reason is None:
                accepted.append(_jsonable_params(candidate))
            else:
                rejected.append({"reason": reason, "params": _jsonable_params(candidate)})
            if len(accepted) >= n or attempted >= attempts_limit:
                break
    if len(accepted) < n:
        report = {
            "vessel_id": vessel_id, "planned": n, "attempted": attempted,
            "accepted": len(accepted), "rejected": len(rejected),
            "rejection_reasons": _reason_counts(rejected),
            "fields": names,
        }
        _LAST_SAMPLING_REPORT = report
        raise SynLabError(
            ErrorCode.TARGET_INFEASIBLE,
            f"{vessel_id}: only {len(accepted)}/{n} feasible parameter sets after "
            f"{attempted} Latin-hypercube attempts",
            stage=f"{STAGE}.sample_parameters",
            measurements=report,
        )
    strongest = 2 if (_is_prime_square(attempted) and attempted > (len(names) - 1) ** 2) else 1
    report = {
        "vessel_id": vessel_id, "planned": n, "attempted": attempted,
        "accepted": len(accepted), "rejected": len(rejected),
        "rejection_reasons": _reason_counts(rejected),
        "method": (f"scipy.stats.qmc.LatinHypercube (strength {strongest}, one point per "
                   "stratum)"),
        "fields": names, "bound_overrides": sorted(bounds) if bounds else [],
        "accepted_fraction": float(len(accepted)) / float(attempted) if attempted else 0.0,
        "feasibility_gate": "real build + audit" if require_feasible else "analytic pre-gate only",
    }
    _LAST_SAMPLING_REPORT = report
    return accepted


#: Statistics of the most recent :func:`sample_parameters` call (planned/attempted/
#: accepted/rejected plus the rejection reasons) - the coverage.parquet columns of plan 7.3.
_LAST_SAMPLING_REPORT: dict[str, Any] = {}


def last_sampling_report() -> dict[str, Any]:
    return copy.deepcopy(_LAST_SAMPLING_REPORT)


def _latin_hypercube(points: int, dimensions: int, rng: np.random.Generator) -> np.ndarray:
    """Latin hypercube design of ``points`` samples in ``dimensions`` dimensions.

    SciPy's ``strength=2`` (orthogonal-array based) design only exists for sample counts that
    are the square of a prime *and* larger than ``(d - 1) ** 2``; it is used when both hold
    (better space filling) and ``strength=1`` otherwise.  The realised strength is recorded in
    the sampling report, so a caller can always see which design was drawn.
    """
    from scipy.stats import qmc

    n = int(max(points, 1))
    d = int(max(dimensions, 1))
    seed = int(rng.integers(0, 2 ** 31 - 1))
    strength = 2 if (_is_prime_square(n) and n > (d - 1) ** 2) else 1
    sampler = qmc.LatinHypercube(d=d, strength=strength, seed=seed)
    return np.asarray(sampler.random(n), dtype=np.float64)


def _is_prime_square(n: int) -> bool:
    if n < 4:
        return False
    root = int(round(n ** 0.5))
    if root * root != n:
        return False
    if root < 2:
        return False
    for divisor in range(2, int(root ** 0.5) + 1):
        if root % divisor == 0:
            return False
    return True


def _reason_counts(rejected: Sequence[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in rejected:
        key = str(item.get("reason", "unknown"))
        out[key] = out.get(key, 0) + 1
    return out


def _pre_gate(vessel_id: str, candidate: Mapping[str, Any]) -> str | None:
    """Cheap analytic gate: catches the combinations the profile kernel would reject.

    Thin walls and over-thick bases are the two failure modes the plan calls out (a wall below
    the gate, and a base plate that leaves no cavity).  Both are stated in millimetres so the
    sampler never proposes a silhouette the builder has to refuse.
    """
    family = str((vessel_entry(vessel_id).applicable or {}).get("family", ""))
    wall = float(candidate.get("wall_mm", 4.0))
    base = float(candidate.get("base_mm", 6.0))
    if wall <= 0 or base <= 0:
        return "non_positive_thickness"
    diameter = float(candidate.get("diameter_mm", 100.0))
    if wall > 0.9 * diameter / 2.0:
        return "wall_exceeds_radius"
    # The base plate turns a corner of roughly its own thickness, so the half thickness must
    # stay below the local corner clearance or the offset profile folds.  The limit is kept
    # even stricter than the measured one because curvature grows as the diameter shrinks.
    base_limit = min(0.16 * diameter, 0.45 * wall + 0.24 * diameter)
    if base > base_limit:
        return "base_plate_too_thick_for_the_outline"
    if family.startswith("revolve"):
        depth = _pre_gate_depth(candidate, vessel_id)
        if depth is not None:
            if depth <= 2.5 * wall + 1e-9:
                return "depth_below_two_walls"
            if base > 0.62 * depth + wall:
                return "base_thicker_than_usable"
    if "spout_bore_mm" in candidate and "wall_mm" in candidate:
        if float(candidate["spout_bore_mm"]) > 4.0 * wall:
            return "spout_bore_wider_than_its_wall"
    if "hole_diameter_mm" in candidate and "base_to_mouth_ratio" in candidate:
        floor = 0.72 * 0.5 * diameter * float(candidate["base_to_mouth_ratio"])
        if float(candidate["hole_diameter_mm"]) > 1.2 * floor:
            return "drainage_hole_larger_than_the_floor"
    return None


def _pre_gate_depth(candidate: Mapping[str, Any], vessel_id: str) -> float | None:
    entry = vessel_entry(vessel_id)
    model = entry.param_model
    names = set(model.model_fields) if model is not None else set()
    if "depth_mm" in names:
        return float(candidate.get("depth_mm", 0.0)) or None
    if "depth_ratio" in names:
        return float(candidate.get("depth_ratio", 0.0)) * float(candidate.get("diameter_mm", 0.0)) or None
    if "height_mm" in names:
        return float(candidate.get("height_mm", 0.0)) or None
    if "cup_depth_ratio" in names:
        return float(candidate.get("cup_depth_ratio", 0.0)) * float(candidate.get("diameter_mm", 0.0)) or None
    return None


def _build_gate(vessel_id: str, candidate: Mapping[str, Any], rng: np.random.Generator) -> str | None:
    """Confirm a candidate by really building and auditing it (bounded cost).

    The probe uses its own generator derived from a fixed key and the vessel id, so the gate can
    never perturb the sampler's Latin-hypercube stream: the returned design is reproducible from
    the caller's seed alone.
    """
    from ..seeds import make_rng

    probe_seed = int(seed64(0xA12, vessel_id, "sampler_gate"))
    probe_rng = make_rng(probe_seed, vessel_id, "sampler_gate")
    try:
        mother = create_mother(vessel_id, "M01", dict(candidate), probe_rng,
                               mother_id=f"{vessel_id}-sampler-gate", max_repair_attempts=1)
    except SynLabError as exc:
        return f"{exc.code}:{exc.stage}" if exc.stage else str(exc.code)
    report = audit_mother(mother, max_thickness_probes=48, run_self_intersection=False)
    if report.get("ok"):
        return None
    first = (report.get("failures") or [{}])[0]
    return f"QA_FAILED:{first.get('check', 'unknown')}"


# ---------------------------------------------------------------------------------------
# store round-trip
# ---------------------------------------------------------------------------------------
def commit_mother(store: AssetStore, mother: MotherGeometry, *, lineage_id: str,
                  split: str, ancestry: Iterable[str] = ()) -> AssetRecord:
    """Persist one mother as ``role="mother_mesh"`` (mesh + charts + face semantics)."""
    if not isinstance(store, AssetStore):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "commit_mother needs an AssetStore",
                          stage=f"{STAGE}.commit_mother")
    if not isinstance(mother, MotherGeometry):  # pragma: no cover - defensive
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "commit_mother needs a MotherGeometry",
                          stage=f"{STAGE}.commit_mother")
    report = audit_mother(mother)
    with_face_attrs(mother.mesh,
                    surface_tag=np.asarray(mother.face_surface_tag, dtype=np.int32),
                    source_triangle=np.arange(len(mother.mesh.faces), dtype=np.int32))
    specs, arrays = chart_payload(mother.charts)
    payload: dict[str, Any] = {"mesh": mother.mesh, **arrays}
    meta = {
        "vessel_id": mother.vessel_id,
        "material_id": mother.material_id,
        "mother_id": mother.mother_id,
        "params": _jsonable_params(mother.params),
        "surface_tag_names": {str(k): v for k, v in mother.surface_tag_names.items()},
        "charts": specs,
        "chart_summary": [{"name": c.name, "kind": c.kind, "u_periodic": bool(c.u_periodic),
                           "area_mm2": float(c.area_mm2), "x_period_mm": c.x_period_mm}
                          for c in mother.charts],
        "mother_meta": _jsonable_params(_strip_arrays(mother.meta)),
        "geometry_hash": _audit.geometry_hash(mother.mesh),
        "schema": SCHEMA_MOTHER,
    }
    return store.commit_asset(
        role=ROLE_MOTHER_MESH, schema=SCHEMA_MOTHER, unit=UNIT_MM, frame=FRAME_WORLD,
        payload=payload, meta=meta, qa=report,
        qa_status=QA_PASS if report.get("ok") else QA_FAIL,
        ancestry=list(ancestry), lineage_id=lineage_id, split=split,
    )


def load_mother(store: AssetStore, asset_id: str) -> MotherGeometry:
    """Read a mother back: mesh, face tags, charts and metadata all survive the round-trip."""
    if not isinstance(store, AssetStore):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "load_mother needs an AssetStore",
                          stage=f"{STAGE}.load_mother")
    record = store.get_asset(asset_id)
    if record.role != ROLE_MOTHER_MESH:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"asset {asset_id} has role {record.role!r}, expected {ROLE_MOTHER_MESH!r}",
                          stage=f"{STAGE}.load_mother")
    mesh = store.load_mesh(asset_id, "mesh")
    arrays = store.load_arrays(asset_id)
    tag_key = "mesh.face__surface_tag"
    if tag_key not in arrays:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"asset {asset_id} has no stored surface_tag array",
                          stage=f"{STAGE}.load_mother")
    tags = np.asarray(arrays[tag_key], dtype=np.int32)
    if tags.shape[0] != len(mesh.faces):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"asset {asset_id}: surface_tag length mismatch",
                          stage=f"{STAGE}.load_mother")
    charts = charts_from_payload(record.meta.get("charts") or [], arrays)
    meta = dict(record.meta.get("mother_meta") or {})
    meta["loaded_from_asset"] = asset_id
    meta["stored_geometry_hash"] = record.meta.get("geometry_hash")
    return MotherGeometry(
        mesh=mesh,
        face_surface_tag=tags,
        surface_tag_names={int(k): v for k, v in (record.meta.get("surface_tag_names") or {}).items()},
        charts=charts,
        vessel_id=str(record.meta.get("vessel_id", "")),
        material_id=str(record.meta.get("material_id", "")),
        params=dict(record.meta.get("params") or {}),
        mother_id=str(record.meta.get("mother_id", "")),
        meta=meta,
    )


def _strip_arrays(payload: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, np.ndarray):
            continue
        if isinstance(value, Mapping):
            out[key] = _strip_arrays(value)
        elif isinstance(value, (list, tuple)):
            out[key] = [_strip_arrays({"v": v})["v"] if isinstance(v, Mapping) else v
                        for v in value if not isinstance(v, np.ndarray)]
        else:
            out[key] = value
    return out


__all__ = [
    "create_mother", "audit_mother", "sample_parameters", "commit_mother", "load_mother",
    "sampler_spec", "shape_parameters", "default_params", "canonical_params",
    "vessel_entry", "vessel_ids", "ensure_registered", "last_sampling_report",
    "geometry_hash", "raise_on_failure",
]
