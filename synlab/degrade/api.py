"""``synlab.degrade`` fa闂佺厧澧界粋鍧塭 (frozen interface, ``docs/a12/interfaces.md`` section 2)::

    compile_recipe(spec) -> CompiledRecipe
    apply_axis(axis_id, level, source, store, *, rng=None, variant=None, source_kind=None,
               lineage_id="", split="train") -> (AssetRecord | OutputRef, Measurement)
    audit_axis(axis_id, levels, store, sources=None, **kw) -> dict
    audit_all_axes(store, *, levels=(0,1,2,3,4), sources=None, limit=1) -> dict
    operator_audit_table(rows) -> pyarrow.Table
    write_operator_measurements(rows, path=None, *, store=None) -> dict

Honesty rules:

* ``level 0`` never re-writes anything: no commit happens and the caller receives the
  **original** ``AssetRecord`` (same ``asset_id``/``blob_hash``) or, without a store, an
  ``OutputRef`` that points at the unchanged source bytes;
* a declared effect that is not present in the output raises ``OPERATOR_NOT_REALIZED`` (the
  measurement travels in ``SynLabError.measurements``) and an inapplicable input raises
  ``NA_NOT_APPLICABLE`` 闂?both stay in the audit denominator instead of being dropped;
* ``audit_all_axes`` builds its sources from the store when the caller does not supply any and
  labels every source with its provenance, so a built-in probe fixture is never mistaken for a
  production asset;
* repeated runs in a fixed environment produce identical reports (no timestamps, no wall clock,
  no fresh random stream).
"""

from __future__ import annotations

import gc
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from ..config import CompiledRecipe, compile_recipe as _compile_recipe
from ..errors import ErrorCode, SynLabError
from ..roles import (
    ROLE_DEGRADE_MEASUREMENT,
    ROLE_FRAGMENT_MESH,
    ROLE_OBS_FUSED,
    ROLE_OBS_RESULT,
    ROLE_OBS_VIEW,
    ROLE_PHYSICAL_COMPONENT,
    SCHEMA_MEASUREMENT,
    SCHEMA_OBS,
    SCHEMA_PHYSICAL,
)
from ..schemas.runtime import DegradationBasis, Measurement
from ..seeds import make_rng
from . import axes as AXES_MODULE
from .registry import AXIS_REGISTRY, FrozenRng, get_operator, measurement_from
from .sources import (
    KIND_GEOMETRY,
    KIND_IMAGE,
    KIND_OBS,
    KIND_PHYSICAL,
    OutputRef,
    SourceBundle,
    commit_source,
    identity_output,
    load_source,
    output_from,
)

FAMILY_PREFIX = {"P": "physical", "I": "image", "G": "geometry", "X": "estimate"}

#: Payload keys that only exist in memory (object graph); references are recorded instead.
IN_MEMORY_KEYS = ("fragment", "clean_truth", "physical_result", "observation")

#: role / schema used when a degraded bundle is committed, per axis family.
#:
#: The X family (observation *estimates*) is committed as a degradation **measurement**, never
#: as ``feature_bundle``: the committed metadata carries ``axis_id``/``level``/``variant`` (the
#: answer of the factor experiment) and ``roles.FORBIDDEN_FEATURE_FIELDS`` forbids exactly those
#: keys inside a feature bundle.  A feature-side consumer must not be able to read the factor
#: label off the asset it is asked to embed.
COMMIT_ROLES: dict[str, tuple[str, str]] = {
    "P": (ROLE_PHYSICAL_COMPONENT, SCHEMA_PHYSICAL),
    "I": (ROLE_OBS_VIEW, SCHEMA_OBS),
    "G": (ROLE_OBS_FUSED, SCHEMA_OBS),
    "X": (ROLE_DEGRADE_MEASUREMENT, SCHEMA_MEASUREMENT),
}

DEFAULT_MASTER_SEED = 20261001

__all__ = [
    "compile_recipe", "apply_axis", "audit_axis", "audit_all_axes", "probe_sources",
    "operator_audit_table", "write_operator_measurements", "run_recipe",
    "bundles_from_observation", "observe_probe", "assign_point_view",
]


# ======================================================================================
# compile_recipe
# ======================================================================================
def compile_recipe(spec: Any) -> CompiledRecipe:
    """Compile a degradation recipe (delegates to :func:`synlab.config.compile_recipe`).

    The delegated compiler owns stage/substage ordering and rejects an axis whose declared
    stage disagrees with the registry.  On top of that DAG this function enforces the
    plan-15.6 rejection list that is visible in the *declared* recipe:

    * a declared order that inverts the compiled field-dependency order (physical damage placed
      after observation, a frame/calibration fault placed after fusion, ...);
    * the same axis declared twice with contradictory parameters.
    """
    compiled = _compile_recipe(spec)
    compiled.errors = list(compiled.errors) + _order_violations(spec, compiled)
    compiled.warnings = list(compiled.warnings) + _duplicate_warnings(spec)
    compiled.meta = {**dict(compiled.meta), "declared_order_checked": True}
    return compiled


def _order_violations(spec: Any, compiled: CompiledRecipe) -> list[str]:
    operators = list(getattr(spec, "operators", []) or [])
    ranked: list[tuple[int, str, str]] = []
    for index, item in enumerate(operators):
        node_id = f"n{index:02d}_{item.axis_id}"
        order = [i for i, node in enumerate(compiled.nodes) if node.node_id == node_id]
        if not order:
            continue
        ranked.append((order[0], item.axis_id, str(getattr(item.stage, "value", item.stage))))
    errors: list[str] = []
    for a in range(len(ranked)):
        for b in range(a + 1, len(ranked)):
            first, second = ranked[a], ranked[b]
            if second[0] < first[0]:
                errors.append(
                    f"ILLEGAL_STAGE_ORDER: {second[1]} ({second[2]}) is declared after "
                    f"{first[1]} ({first[2]}) but must run before it; a declared inversion of the "
                    f"field-dependency order is rejected instead of being silently reordered "
                    f"(plan 15.6, 30.2)"
                )
    return errors


def _duplicate_warnings(spec: Any) -> list[str]:
    operators = list(getattr(spec, "operators", []) or [])
    seen: dict[str, tuple[int, str, str]] = {}
    out: list[str] = []
    for item in operators:
        fingerprint = hash_json({"level": int(item.level), "variant": item.variant,
                                 "parameters": _jsonable(dict(item.parameters or {}))})
        if item.axis_id in seen:
            previous = seen[item.axis_id]
            if previous[2] != fingerprint:
                out.append(
                    f"CONTRADICTORY_DUPLICATE_AXIS: {item.axis_id} is declared twice with "
                    f"different level/variant/parameters (levels {previous[0]} and "
                    f"{int(item.level)})"
                )
        seen[item.axis_id] = (int(item.level), item.variant, fingerprint)
    return out


def run_recipe(spec: Any, source: SourceBundle, store: Any = None, **kwargs: Any) -> dict[str, Any]:
    """Apply every node of a compiled recipe in DAG order, chaining the bundles."""
    compiled = compile_recipe(spec)
    if not compiled.ok:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"recipe {compiled.recipe_id} does not compile: {compiled.errors}",
                          stage="degrade.run_recipe")
    current = source
    nodes: list[dict[str, Any]] = []
    for node in compiled.nodes:
        current, record, measurement = _apply_impl(
            node.operator, int(node.level), current, store, variant=node.variant or None,
            parameters=dict(node.parameters or {}), **kwargs)
        nodes.append({"node_id": node.node_id, "axis_id": node.operator,
                      "variant": measurement.variant, "level": int(node.level),
                      "status": ("IDENTITY" if measurement.identity
                                 else ("REALIZED" if measurement.realized else "FAILED")),
                      "measured": _jsonable(measurement.measured),
                      "asset_id": getattr(record, "asset_id", None)})
    return {"recipe_id": compiled.recipe_id, "hash": compiled.hash, "nodes": nodes,
            "final": current.describe()}


# ======================================================================================
# apply_axis
# ======================================================================================
def _context_for(source: SourceBundle, *, axis_id: str, lineage_id: str,
                 master_seed: int) -> dict[str, Any]:
    return {
        "axis_id": axis_id,
        "lineage_id": lineage_id or str(source.lineage_id or "lineage"),
        "fragment_id": str(source.fragment_id or (source.meta or {}).get("fragment_id", "fragment")),
        "mother_id": str((source.meta or {}).get("mother_id", "")),
        "master_seed": int(master_seed),
        "source": source,
        "source_kind": source.source_kind,
    }


def _default_rng(context: Mapping[str, Any], axis_id: str, variant: str):
    value = context.get("master_seed", DEFAULT_MASTER_SEED)
    seed = int(value) if isinstance(value, (int, float)) else 0
    return make_rng(seed, context.get("lineage_id", "lineage"), "degrade", axis_id, variant)


def apply_axis(axis_id: str, level: int, source: SourceBundle, store: Any = None, *,
               rng: np.random.Generator | None = None, variant: str | None = None,
               source_kind: str | None = None, lineage_id: str = "", split: str = "train",
               parameters: dict[str, Any] | None = None,
               basis: DegradationBasis | None = None,
               commit: bool = True) -> tuple[Any, Measurement]:
    """Apply one axis level to ``source`` and return ``(asset_record_or_ref, measurement)``.

    ``store`` may be ``None`` (inspection only): the result is then an :class:`OutputRef`.
    Level 0 never commits and never touches the source: with a store the *original*
    ``AssetRecord`` is returned, so identity is provable by ``asset_id``/bytes.
    """
    _, record, measurement = _apply_impl(axis_id, level, source, store, rng=rng, variant=variant,
                                        source_kind=source_kind, lineage_id=lineage_id,
                                        split=split, parameters=parameters, basis=basis,
                                        commit=commit)
    return record, measurement


def _apply_impl(axis_id: str, level: int, source: SourceBundle, store: Any = None, *,
                rng: np.random.Generator | None = None, variant: str | None = None,
                source_kind: str | None = None, lineage_id: str = "", split: str = "train",
                parameters: dict[str, Any] | None = None,
                basis: DegradationBasis | None = None,
                commit: bool = True) -> tuple[SourceBundle, Any, Measurement]:
    operator = get_operator(axis_id)
    level = int(level)
    if level not in operator.levels():
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"axis {axis_id}: level {level} outside 0..{operator.LEVEL_COUNT - 1}",
                          stage="degrade.apply_axis")
    if source_kind is not None and source.source_kind != source_kind:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"axis {axis_id}: source_kind declared as {source_kind!r} but the "
                          f"bundle is {source.source_kind!r}",
                          stage="degrade.apply_axis")
    variant_name = operator.resolve_variant(variant)
    master_seed = int((source.meta or {}).get("master_seed", DEFAULT_MASTER_SEED))
    context = _context_for(source, axis_id=axis_id, lineage_id=lineage_id, master_seed=master_seed)
    context["variant"] = variant_name
    if basis is None:
        generator = rng if rng is not None else _default_rng(context, axis_id, variant_name)
        basis = operator.sample_basis(context, generator, variant_name)
    elif basis.axis_id != axis_id:
        raise SynLabError(ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
                          f"basis {basis.basis_id} was frozen for axis {basis.axis_id} but "
                          f"{axis_id} was requested",
                          stage="degrade.apply_axis")
    elif basis.variant != variant_name:
        raise SynLabError(ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
                          f"basis {basis.basis_id} was frozen for variant {basis.variant} but "
                          f"{variant_name} was requested; re-freeze the basis for this variant",
                          stage="degrade.apply_axis")

    planned = dict(operator.params_for(level, variant_name))
    planned.update(parameters or {})
    planned.setdefault("variant", variant_name)

    # ------------------------------------------------------------------ identity
    if level == 0:
        measurement = measurement_from(
            operator, level=0, variant=variant_name, planned=planned, measured={}, units={},
            identity=True, realized=True, source_hash=source.content_hash(),
            result_hash=source.content_hash(), valid=True,
            extra={"basis_id": basis.basis_id, "basis_seed_ref": basis.seed_ref,
                   "support": "IDENTITY_LEVEL0", "source_kind": source.source_kind,
                   "identity_contract": "source asset reference/bytes returned unchanged",
                   "label_invalidations": list(operator.LABEL_INVALIDATIONS),
                   "label_status": "NOT_INVALIDATED_AT_LEVEL0",
                   "label_validity": "NOT_INVALIDATED_AT_LEVEL0",
                   "label_dependency_status": {
                       name: {"status": "NOT_INVALIDATED_AT_LEVEL0",
                              "validity": "NOT_INVALIDATED_AT_LEVEL0",
                              "reason": "level 0 returns the source unchanged"}
                       for name in operator.LABEL_INVALIDATIONS},
                   "label_receipt_refs": {}},
            calibration_status=_calibration_status(operator))
        return source, _identity_record(source, store, operator), measurement

    # ------------------------------------------------------------------ applicability
    applicable, na_reason = operator.applicability(source, variant_name)
    if not applicable:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                          f"{axis_id}/{variant_name}: {na_reason}",
                          stage="degrade.apply_axis",
                          measurements={"planned": _jsonable(planned), "level": level,
                                        "variant": variant_name},
                          seed_ref=basis.seed_ref)
    try:
        result = operator.apply(source, level, basis, FrozenRng(), parameters=planned)
    except SynLabError as exc:
        exc.measurements.setdefault("planned", _jsonable(planned))
        exc.measurements.setdefault("level", level)
        exc.measurements.setdefault("variant", variant_name)
        exc.seed_ref = exc.seed_ref or basis.seed_ref
        raise
    metrics = operator.measure(source, result, context)
    label_dependency_status = _label_dependency_status(operator, source, result)
    label_receipt_refs = {
        name: evidence["receipt_ref"]
        for name, evidence in label_dependency_status.items()
        if evidence.get("receipt_ref")
    }
    label_status = _label_status(
        operator, source, result, dependency_status=label_dependency_status)
    label_validity = _label_validity(label_status, label_dependency_status)
    measurement = measurement_from(
        operator, level=level, variant=variant_name, planned=planned,
        measured=metrics.get("measured", {}), units=metrics.get("units", {}),
        identity=False, realized=bool(metrics.get("realized", False)), valid=True,
        source_hash=source.content_hash(), result_hash=result.content_hash(),
        na_reason=metrics.get("na_reason"), failure_code=metrics.get("failure_code"),
        extra={"basis_id": basis.basis_id, "basis_seed_ref": basis.seed_ref,
               "support": "MEASURED", "source_kind": source.source_kind,
               **(metrics.get("extra") or {}),
               "label_invalidations": list(operator.LABEL_INVALIDATIONS),
               "label_status": label_status,
               "label_validity": label_validity,
               "label_dependency_status": label_dependency_status,
               "label_receipt_refs": label_receipt_refs},
        calibration_status=_calibration_status(operator))
    operator.validate(source, result, measurement)

    # ------------------------------------------------------------------ commit
    if store is None or not commit:
        return result, output_from(source, result,
                                   notes=f"{axis_id}/{variant_name}/L{level}"), measurement
    payload_bundle = result.without(*IN_MEMORY_KEYS)
    role, schema = COMMIT_ROLES[axis_id[0]]
    record = commit_source(
        store, payload_bundle, role=role, schema=schema,
        lineage_id=lineage_id or source.lineage_id, split=split,
        qa={"axis_id": axis_id, "variant": variant_name, "level": level, "identity": False,
            "realized": bool(measurement.realized), "basis_id": basis.basis_id,
            "source_hash": measurement.source_hash, "result_hash": measurement.result_hash,
            "label_invalidations": list(operator.LABEL_INVALIDATIONS),
            "label_status": measurement.extra.get("label_status"),
            "label_validity": measurement.extra.get("label_validity"),
            "label_dependency_status": measurement.extra.get("label_dependency_status"),
            "label_receipt_refs": measurement.extra.get("label_receipt_refs")},
        meta={"origin_role": source.role or "degradation_source", "axis_id": axis_id,
              "variant": variant_name, "level": level, "factor_kind": measurement.factor_kind,
              "basis_id": basis.basis_id, "basis_seed_ref": basis.seed_ref,
              "planned": _jsonable(planned), "measured": _jsonable(measurement.measured),
              "units": _jsonable(measurement.units), "source_kind": source.source_kind,
              "source_asset_id": source.asset_id,
              "clean_geometry_hash": result.get("clean_geometry_hash"),
              "reference_refs": _reference_refs(result)})
    return result, record, measurement


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist() if value.size <= 64 else f"<array {value.shape}>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


def _reference_refs(result: SourceBundle) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    physical = result.get("physical_result")
    if physical is not None:
        refs["physical_recipe_id"] = str(getattr(physical, "recipe_id", ""))
        refs["clean_ref"] = str(getattr(physical, "clean_ref", ""))
        refs["component_ids"] = [c.component_id for c in getattr(physical, "components", [])]
    observation = result.get("observation")
    if observation is not None:
        refs["observation_id"] = str(getattr(observation, "observation_id", ""))
        refs["route"] = str(getattr(observation, "route", ""))
    return refs


def _identity_record(source: SourceBundle, store: Any, operator: Any) -> Any:
    if store is not None and source.asset_id:
        try:
            return store.get_asset(source.asset_id)
        except SynLabError:
            pass
    return identity_output(
        source,
        notes=f"{operator.AXIS_ID} level 0 identity: source asset reference returned unchanged")


def _calibration_status(operator: Any) -> str:
    if operator.AXIS_ID == "I05":
        return "FROZEN_PROFILE_AFTER_CALIBRATION"
    return "UNCALIBRATED"


def _label_status(operator: Any, source: SourceBundle, result: SourceBundle, *,
                  dependency_status: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    """Aggregate label status from evidence for every declared invalidation dependency."""
    invalidations = tuple(getattr(operator, "LABEL_INVALIDATIONS", ()) or ())
    if not invalidations:
        return "NO_LABEL_DEPENDENCY"
    statuses = dependency_status or _label_dependency_status(operator, source, result)
    rows = [statuses.get(name, {}) for name in invalidations]
    values = [str(row.get("status", "PENDING_RECOMPUTE")) for row in rows]
    if any(status == "FAILED" for status in values) or any(
            row.get("validity") == "FAILED_VALIDATION" for row in rows):
        return "FAILED"
    if all(status in ("UPDATED", "RECOMPUTED") for status in values):
        return "RECOMPUTED"
    return "PENDING_RECOMPUTE"


def _label_validity(label_status: str,
                    dependency_status: Mapping[str, Mapping[str, Any]]) -> str:
    """State explicitly whether pending work leaves label validity unresolved."""
    if label_status in ("NOT_INVALIDATED_AT_LEVEL0", "NO_LABEL_DEPENDENCY"):
        return label_status
    if label_status == "FAILED":
        return "FAILED"
    values = [str(row.get("validity", "UNKNOWN_INVALIDATED"))
              for row in dependency_status.values()]
    if any(value in ("FAILED", "FAILED_VALIDATION") for value in values):
        return "FAILED"
    if values and all(value == "VALIDATED" for value in values):
        return "VALIDATED"
    return "UNKNOWN_INVALIDATED"


def _label_dependency_status(operator: Any, source: SourceBundle,
                              result: SourceBundle) -> dict[str, dict[str, Any]]:
    """Return one evidence record per declared invalidation, retaining partial work.

    ``physical.api.apply_damage`` calls ``truth.api.update_residual_truth`` and attaches the
    resulting ``PhysicalTruth``.  That work is reported as ``UPDATED`` only when the attached
    artifact agrees with its clean-truth reference, version, event, recipe and geometry
    provenance.  No current degrade route records a ``VisibleLabels`` or ``FeatureAdapter``
    recomputation receipt, so those dependencies remain pending even when physical truth updated.
    """
    invalidations = tuple(getattr(operator, "LABEL_INVALIDATIONS", ()) or ())
    if not invalidations:
        return {}

    physical_result = result.get("physical_result")
    physical_meta = getattr(physical_result, "meta", None) or {}
    physical_qa = getattr(physical_result, "qa", None) or {}
    reported = str((result.meta or {}).get("label_status", "") or "").upper()
    physical_status = str(physical_meta.get("physical_truth_status", "") or "").upper()
    physical_qa_status = str(physical_qa.get("status", "") or "").upper()
    postassembly = physical_qa.get("postassembly")
    postassembly_status = (str(postassembly.get("status", "") or "").upper()
                           if isinstance(postassembly, Mapping) else "")
    if postassembly_status in ("FAIL", "FAILED", "QA_FAILED"):
        physical_qa_status = postassembly_status
    physical_receipt = _physical_truth_recompute_receipt(operator, source, result)
    evidence: dict[str, dict[str, Any]] = {}
    for dependency in invalidations:
        if dependency == "PhysicalTruth":
            if physical_status == "FAILED" or (reported == "FAILED" and physical_result is not None):
                evidence[dependency] = {
                    "status": "FAILED",
                    "validity": "FAILED",
                    "reason": "physical truth recomputation reported failure",
                    "reported_status": physical_status or reported,
                }
            elif physical_qa_status in ("FAIL", "FAILED", "QA_FAILED"):
                evidence[dependency] = {
                    "status": "FAILED", "validity": "FAILED_VALIDATION",
                    "reason": "physical result QA failed; attached truth is not accepted as valid",
                    "reported_status": physical_status or reported or physical_qa_status,
                    "physical_result_qa_status": physical_qa_status,
                }
            elif physical_receipt is not None:
                evidence[dependency] = {"status": "UPDATED", **physical_receipt}
            else:
                reason = ("reported recompute status had no matching PhysicalTruth artifact"
                          if reported in ("UPDATED", "RECOMPUTED") or physical_status == "UPDATED"
                          else "no machine-verifiable PhysicalTruth artifact is attached")
                row = {"status": "PENDING_RECOMPUTE", "validity": "UNKNOWN_INVALIDATED",
                       "reason": reason}
                observed = physical_status or reported
                if observed:
                    row["reported_status"] = observed
                evidence[dependency] = row
        else:
            evidence[dependency] = {
                "status": "PENDING_RECOMPUTE",
                "validity": "UNKNOWN_INVALIDATED",
                "reason": "no matching recomputation artifact or receipt is recorded",
            }

    # Preserve an explicit failure as the aggregate status without treating a bare success
    # string as evidence.  The corresponding dependency record remains pending unless a
    # physical API failure can be tied to PhysicalTruth above.
    if reported == "FAILED" and not any(
            item.get("status") == "FAILED" for item in evidence.values()):
        evidence[invalidations[0]] = {
            "status": "FAILED", "validity": "FAILED",
            "reason": "result reports label recomputation failure",
            "reported_status": reported,
        }
    return evidence


def _physical_truth_recompute_receipt(operator: Any, source: SourceBundle,
                                      result: SourceBundle) -> dict[str, Any] | None:
    """Validate and describe the runtime PhysicalTruth artifact attached by the physical API."""
    if "PhysicalTruth" not in tuple(getattr(operator, "LABEL_INVALIDATIONS", ()) or ()):
        return None
    clean_truth = source.get("clean_truth")
    physical_result = result.get("physical_result")
    if clean_truth is None or physical_result is None:
        return None

    clean_meta = getattr(clean_truth, "meta", None) or {}
    clean_ref = str(clean_meta.get("truth_hash", "") or "")
    clean_mother = str(getattr(clean_truth, "mother_id", "") or "")
    clean_event = str(getattr(clean_truth, "event_id", "") or "")
    if not clean_ref or not clean_mother or not clean_event:
        return None
    try:
        clean_version = int(getattr(clean_truth, "version"))
        expected_version = clean_version + 1
    except (TypeError, ValueError, AttributeError):
        return None

    physical_truth = getattr(physical_result, "physical_truth", None)
    if physical_truth is None:
        return None
    truth_meta = getattr(physical_truth, "meta", None) or {}
    truth_qa = getattr(physical_truth, "qa", None) or {}
    physical_meta = getattr(physical_result, "meta", None) or {}
    physical_qa = getattr(physical_result, "qa", None) or {}
    result_meta = result.meta or {}
    result_extra = result_meta.get("extra") or {}
    damage = truth_meta.get("damage")
    if not isinstance(damage, Mapping):
        return None

    axis_id = str(getattr(operator, "AXIS_ID", "") or "")
    recipe_id = str(getattr(physical_result, "recipe_id", "") or "")
    result_variant = str(result_meta.get("variant", "") or "")
    physical_variant = str(physical_meta.get("variant", "") or "")
    damage_variant = str(damage.get("variant", "") or "")
    try:
        truth_version = int(getattr(physical_truth, "version"))
        result_level = int(result_meta.get("level"))
        physical_level = int(physical_meta.get("level"))
        damage_level = int(damage.get("level"))
    except (TypeError, ValueError):
        return None

    # apply_damage records these geometry identities on the result, and _PhysicalAxis carries
    # both into the SourceBundle receipt envelope.  Re-hash the actual input mesh before accepting
    # that envelope so unrelated or stale clean geometry cannot vouch for the truth artifact.
    source_mesh = source.get("mesh")
    if source_mesh is None:
        source_fragment = source.get("fragment")
        source_mesh = getattr(source_fragment, "mesh", None)
    if source_mesh is None:
        return None
    try:
        from ..physical.api import _geometry_hash as _physical_geometry_hash

        source_geometry_hash = _physical_geometry_hash(source_mesh)
    except Exception:  # noqa: BLE001 - absent geometry evidence means no receipt
        return None
    reported_source_hash = str(physical_meta.get("source_geometry_hash", "") or "")
    qa_source_hash = str(physical_qa.get("source_geometry_hash", "") or "")
    result_geometry_hash = str(physical_qa.get("result_geometry_hash", "") or "")
    if not result_geometry_hash or not source_geometry_hash:
        return None
    if str(physical_qa.get("status", "") or "").upper() != "PASS":
        return None
    postassembly = physical_qa.get("postassembly")
    if (not isinstance(postassembly, Mapping)
            or str(postassembly.get("status", "") or "").upper() != "PASS"):
        return None
    from ..physical.api import GEOMETRY_HASH_ALGORITHM

    # Older receipts only carried aggregate geometry summaries. They cannot prove the exact
    # vertex coordinates and oriented faces needed for this PhysicalTruth link.
    if (physical_meta.get("geometry_hash_algorithm") != GEOMETRY_HASH_ALGORITHM
            or physical_qa.get("geometry_hash_algorithm") != GEOMETRY_HASH_ALGORITHM
            or postassembly.get("geometry_hash_algorithm") != GEOMETRY_HASH_ALGORITHM):
        return None

    components = list(getattr(physical_result, "components", []) or [])
    if not components:
        return None
    output_mesh = result.get("mesh")
    representative = next((c for c in components if bool(getattr(c, "is_representative", False))),
                          components[0])
    representative_mesh = getattr(representative, "mesh", None)
    if output_mesh is None or representative_mesh is None:
        return None
    try:
        output_mesh_hash = _physical_geometry_hash(output_mesh)
        representative_mesh_hash = _physical_geometry_hash(representative_mesh)
        if output_mesh_hash != representative_mesh_hash:
            return None
        if len(components) == 1 and output_mesh_hash != result_geometry_hash:
            return None
        component_hash_rows = postassembly.get("component_geometry_hashes")
        if not isinstance(component_hash_rows, list) or len(component_hash_rows) != len(components):
            return None
        hashes_by_id: dict[str, str] = {}
        for row in component_hash_rows:
            if not isinstance(row, Mapping):
                return None
            component_id = str(row.get("component_id", "") or "")
            geometry_hash = str(row.get("geometry_hash", "") or "")
            if not component_id or not geometry_hash or component_id in hashes_by_id:
                return None
            hashes_by_id[component_id] = geometry_hash
        if len(hashes_by_id) != len(components):
            return None
        for component in components:
            component_id = str(getattr(component, "component_id", "") or "")
            component_mesh = getattr(component, "mesh", None)
            if not component_id or component_mesh is None:
                return None
            if hashes_by_id.get(component_id) != _physical_geometry_hash(component_mesh):
                return None
    except Exception:  # noqa: BLE001 - absent output geometry evidence means no receipt
        return None

    clean_identity = f"{clean_mother}:{clean_event}:v{clean_version}"
    if not (
        truth_version == expected_version
        and str(getattr(physical_truth, "clean_truth_ref", "") or "") == clean_ref
        and str(truth_meta.get("clean_truth_ref", "") or "") == clean_ref
        and truth_meta.get("layer") == "physical"
        and truth_qa.get("layer") == "physical"
        and str(getattr(physical_result, "mother_id", "") or "") == clean_mother
        and str(getattr(physical_result, "event_id", "") or "") == clean_event
        and str(getattr(physical_result, "clean_ref", "") or "") == clean_identity
        and str(truth_meta.get("mother_id", "") or "") == clean_mother
        and str(truth_meta.get("event_id", "") or "") == clean_event
        and recipe_id
        and str(damage.get("recipe_id", "") or "") == recipe_id
        and str(damage.get("axis_id", "") or "") == axis_id
        and str(physical_meta.get("axis_id", "") or "") == axis_id
        and str(result_meta.get("axis_id", "") or "") == axis_id
        and result_variant == physical_variant == damage_variant
        and damage_level == result_level == physical_level
        and source_geometry_hash == reported_source_hash == qa_source_hash
        and str(result_extra.get("source_geometry_hash", "") or "") == source_geometry_hash
        and str(result_extra.get("result_geometry_hash", "") or "") == result_geometry_hash
        and bool(damage.get("geometry_changed"))
        == bool(physical_meta.get("geometry_changed"))
        and isinstance(getattr(physical_truth, "residual", None), Mapping)
        and isinstance(getattr(physical_truth, "survivor_patches", None), Mapping)
        and isinstance(getattr(physical_truth, "current_fit_valid", None), Mapping)
        and isinstance(getattr(physical_truth, "association_counts", None), Mapping)
    ):
        return None

    return {
        "receipt_ref": f"PhysicalResult.physical_truth:{recipe_id}:v{truth_version}",
        "clean_truth_ref": clean_ref,
        "clean_truth_version": clean_version,
        "physical_truth_version": truth_version,
        "recipe_id": recipe_id,
        "axis_id": axis_id,
        "level": result_level,
        "source_geometry_hash": source_geometry_hash,
        "result_geometry_hash": result_geometry_hash,
        "output_geometry_verification": (
            "SINGLE_COMPONENT_HASH_REVERIFIED" if len(components) == 1
            else "ALL_COMPONENT_HASHES_REVERIFIED_FROM_POSTASSEMBLY_QA"),
        "artifact_path": "payload.physical_result.physical_truth",
        "validity": "VALIDATED" if bool(truth_qa.get("pass")) else "FAILED_VALIDATION",
    }


# ======================================================================================
# audit
# ======================================================================================
SourceProvider = Mapping[str, SourceBundle] | Sequence[SourceBundle] | Callable[[str], Any] | None


def _resolve_source(axis_id: str, sources: SourceProvider, store: Any,
                    cache: dict[str, SourceBundle]) -> SourceBundle | None:
    family = get_operator(axis_id).AXIS_ID[0]
    if callable(sources):
        candidate = sources(axis_id)
        if candidate is None:
            candidate = sources(family)
        return candidate
    if isinstance(sources, Mapping):
        for key in (axis_id, family, FAMILY_PREFIX.get(family, family)):
            if key in sources:
                return sources[key]
        return None
    if isinstance(sources, (list, tuple)):
        return sources[0] if sources else None
    if family not in cache:
        bundle = _source_from_store(store, family)
        if bundle is None:
            bundle = probe_sources(store=store).get(family)
        if bundle is not None:
            cache[family] = bundle
    return cache.get(family)


def _source_from_store(store: Any, family: str) -> SourceBundle | None:
    """Build a real source bundle from the newest matching store asset (or ``None``)."""
    if store is None:
        return None
    try:
        if family == "P":
            assets = (list(store.list_assets(role=ROLE_FRAGMENT_MESH, limit=1))
                      or list(store.list_assets(role=ROLE_PHYSICAL_COMPONENT, limit=1)))
            if not assets:
                return None
            bundle = load_source(store, assets[0].asset_id)
            bundle.meta.setdefault("provenance", f"STORE_ASSET:{assets[0].asset_id}")
            return bundle
        assets = list(store.list_assets(role=ROLE_OBS_RESULT, limit=1))
        if not assets:
            return None
        from ..observe.api import load_observation

        observation = load_observation(store, assets[0].asset_id)
        bundle = bundles_from_observation(observation).get(family)
        if bundle is not None:
            bundle.meta.setdefault("provenance", f"STORE_ASSET:{assets[0].asset_id}")
        return bundle
    except SynLabError:
        return None


def observe_probe(*, size: tuple[int, int] = (128, 96), views: int = 4,
                  seed: int = DEFAULT_MASTER_SEED) -> Any:
    """Run a *real* proxy-scan observation on a small probe body (used by the audit).

    The probe declares a realistic photon scale (``effective_gain=20000``) so the delivered
    linear plane is not quantised to {0, 1} by a gain of one photon per unit; the imaging
    parameters are part of the declared probe configuration, never a fabricated image.

    The body also declares its **face provenance** (``origin_kind = ORIGIN_MOTHER_SURFACE`` for
    every face, ``interface_id = -1``): the probe box has no fracture surface at all, and
    ``observe.routes.resolve_target`` now refuses an unlabelled render target instead of emitting
    an all-zero surface-tag map that is indistinguishable from "this body has no new surface".
    The declared channel produces the *same* tag map as before (``ORIGIN_TO_TAG[0] == 0``) while
    making the absence of a fracture surface a measurement rather than a missing channel.
    """
    import numpy as np
    import trimesh

    from ..observe.api import ROUTE_PROXY_SCAN, ObsSpec, observe
    from ..observe.imaging import ImagingSpec
    from ..schemas.runtime import ORIGIN_MOTHER_SURFACE
    from ..seeds import derive_named_rngs
    from ..storage.mesh_io import with_face_attrs

    mesh = trimesh.creation.box(extents=(60.0, 45.0, 25.0))
    with_face_attrs(mesh,
                    origin_kind=np.full(len(mesh.faces), ORIGIN_MOTHER_SURFACE, dtype=np.uint8),
                    interface_id=np.full(len(mesh.faces), -1, dtype=np.int32))
    spec = ObsSpec(view_count=int(views), delivered_size=(int(size[0]), int(size[1])),
                   max_render_pixels=int(size[0]) * int(size[1]), master_seed=int(seed),
                   lineage_id="probe_lineage",
                   imaging=ImagingSpec(effective_gain=20000.0, read_noise_sigma=0.002,
                                       response="LINEAR", encode="PNG",
                                       sensor_noise_enabled=True),
                   route_params={"voxel_mm": 0.2, "sparse_keep": 1.0, "hole_count": 2,
                                 "depth_error_sigma_mm": 0.05, "stride": 2})
    rngs = derive_named_rngs(int(seed), "probe_lineage")
    return observe(mesh, None, rngs, route=ROUTE_PROXY_SCAN, profile="LOCAL", spec=spec)


def depth_mesh_from_frames(frames: list[dict[str, Any]], *, stride: int = 4) -> Any:
    """Organized depth mesh per view, transformed and merged (a real depth-map fusion).

    Used when a route does not deliver a fused mesh (``PROXY_SCAN`` is a point-cloud route):
    every face comes from real depth pixels of the delivered views.  The provenance is recorded
    as ``ORGANIZED_DEPTH_MESH_PER_VIEW_MERGED`` so it is never mistaken for an MVS surface.
    """
    import trimesh

    from ..cameras.api import unproject

    vertices: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    offset = 0
    for frame in frames:
        depth = frame.get("depth_z")
        if depth is None:
            continue
        depth = np.asarray(depth, dtype=np.float64)
        rows = np.arange(0, depth.shape[0], max(int(stride), 1))
        cols = np.arange(0, depth.shape[1], max(int(stride), 1))
        sub = depth[np.ix_(rows, cols)]
        mask = frame.get("valid_mask")
        if mask is not None:
            sub_mask = np.asarray(mask, dtype=bool)[np.ix_(rows, cols)]
        else:
            sub_mask = np.ones_like(sub, dtype=bool)
        valid = np.isfinite(sub) & (sub > 0) & sub_mask
        if not np.any(valid):
            continue
        grid_rows, grid_cols = np.meshgrid(rows, cols, indexing="ij")
        uv = np.stack([grid_cols.ravel().astype(np.float64),
                       grid_rows.ravel().astype(np.float64)], axis=1)
        z = sub.ravel()
        keep = valid.ravel()
        world = unproject(uv[keep], z[keep], np.asarray(frame["K"], dtype=np.float64),
                          np.asarray(frame["T_WC"], dtype=np.float64), frame.get("dist"))
        index_grid = np.full(sub.shape, -1, dtype=np.int64)
        index_grid.ravel()[keep] = np.arange(int(keep.sum()))
        quads = []
        for i in range(sub.shape[0] - 1):
            for j in range(sub.shape[1] - 1):
                corners = [index_grid[i, j], index_grid[i, j + 1],
                           index_grid[i + 1, j + 1], index_grid[i + 1, j]]
                if min(corners) < 0:
                    continue
                quads.append([corners[0], corners[1], corners[2]])
                quads.append([corners[0], corners[2], corners[3]])
        if not quads:
            continue
        vertices.append(np.asarray(world, dtype=np.float64))
        faces.append(np.asarray(quads, dtype=np.int64) + offset)
        offset += len(world)
    if not vertices:
        return None
    return trimesh.Trimesh(vertices=np.vstack(vertices), faces=np.vstack(faces), process=False)


def bundles_from_observation(observation: Any) -> dict[str, SourceBundle]:
    """Convert one real observation into the I/G/X source bundles (no invented channels)."""
    frames: list[dict[str, Any]] = []
    for view in observation.views:
        depth = np.asarray(view.depth_z, dtype=np.float32)
        valid_depth = np.isfinite(depth) & (depth > 0)
        deployment = np.asarray(view.deployment_mask, dtype=bool)
        frames.append({
            "view_id": str(view.view_id),
            "rgb": np.asarray(view.rgb, dtype=np.uint8),
            "rgb_linear": np.asarray(view.rgb_linear, dtype=np.float32),
            "encoding": "LINEAR",
            "K": np.asarray(view.frame.K, dtype=np.float64),
            "T_WC": np.asarray(view.frame.T_WC, dtype=np.float64),
            "dist": (None if view.frame.dist is None
                     else np.asarray(view.frame.dist, dtype=np.float64)),
            "depth_z": depth,
            # per-view valid depth support: the deployment mask of this route is conservative
            # (all object pixels can be "uncertain" for a body deeper than the DoF), so the
            # delivered depth support is the honest per-view validity for fusion purposes.
            "valid_mask": valid_depth,
            "deployment_mask": deployment,
            "research_mask": (np.asarray(view.id_map, dtype=np.int32) >= 0),
            "focus_distance_mm": float(getattr(view.frame, "working_distance_mm", 0.0) or 0.0),
            "valid": True,
        })
    meta = {"mother_id": str(getattr(observation, "mother_id", "")),
            "fragment_id": str(getattr(observation, "fragment_id", "")),
            "component_id": str(getattr(observation, "component_id", "")),
            "route": str(getattr(observation, "route", "")),
            "input_profile": str(getattr(observation, "input_profile", "")),
            "observation_id": str(getattr(observation, "observation_id", "")),
            "frame_id": str(getattr(observation, "frame_id", "S_mm")),
            "quality": dict(getattr(observation, "quality", {}) or {}),
            "master_seed": DEFAULT_MASTER_SEED}
    image = SourceBundle(source_kind=KIND_IMAGE, payload={"frames": frames}, meta=dict(meta),
                         unit="px", frame=str(meta["frame_id"]))
    points = np.asarray(observation.points, dtype=np.float64)
    normals = (np.asarray(observation.normals, dtype=np.float64)
               if getattr(observation, "normals", None) is not None
               else np.tile(np.array([[0.0, 0.0, 1.0]]), (len(points), 1)))
    point_valid = (np.asarray(observation.point_valid, dtype=bool)
                   if getattr(observation, "point_valid", None) is not None
                   else np.ones(len(points), dtype=bool))
    geometry_frames = [{"view_id": f["view_id"], "T_WC": f["T_WC"], "K": f["K"],
                        "dist": f["dist"], "depth_z": f["depth_z"], "mask": f["valid_mask"]}
                       for f in frames]
    mesh = getattr(observation, "fused_mesh", None)
    mesh_source = "ROUTE_FUSED_MESH"
    if mesh is None:
        mesh = depth_mesh_from_frames(frames, stride=4)
        mesh_source = ("ORGANIZED_DEPTH_MESH_PER_VIEW_MERGED" if mesh is not None
                       else "NO_MESH_AVAILABLE")
    geometry = SourceBundle(
        source_kind=KIND_GEOMETRY,
        payload={"points": points, "normals": normals, "point_valid": point_valid,
                 "point_view": assign_point_view(points, geometry_frames),
                 "frames": geometry_frames, "mesh": mesh,
                 "roi": np.ones(len(points), dtype=bool),
                 "priority_order": np.arange(len(points), dtype=np.int64),
                 "reference_points": points.copy(), "scale_ratio": 1.0,
                 "K": np.asarray(frames[0]["K"], dtype=np.float64) if frames else np.eye(3),
                 "dist": (np.asarray(frames[0]["dist"], dtype=np.float64)
                          if frames and frames[0]["dist"] is not None else np.zeros(0)),
                 "clean_geometry_hash": hash_json({"points": list(points.shape),
                                                   "route": str(meta["route"])})},
        meta={**dict(meta), "fused_mesh_source": mesh_source}, unit="mm",
        frame=str(meta["frame_id"]))
    quality = dict(getattr(observation, "quality", {}) or {})
    channel_names, channel_values = _numeric_leaves(quality)
    first_view = observation.views[0] if observation.views else None
    first_frame = frames[0] if frames else None
    deployment = (np.asarray(first_frame["deployment_mask"], dtype=bool) if first_frame
                  else np.zeros((8, 8), dtype=bool))
    depth_support = (np.asarray(first_frame["valid_mask"], dtype=bool) if first_frame
                     else np.zeros((8, 8), dtype=bool))
    mask = deployment if bool(deployment.any()) else depth_support
    mask_source = "OBS_DEPLOYMENT_MASK" if bool(deployment.any()) else "OBS_DEPTH_VALIDITY"
    research = (np.asarray(first_frame["research_mask"], dtype=bool) if first_frame
                else np.zeros((8, 8), dtype=bool))
    roi = (np.asarray(first_view.roi, dtype=bool)
           if first_view is not None and getattr(first_view, "roi", None) is not None else research)
    estimate = SourceBundle(
        source_kind=KIND_OBS,
        payload={"modalities": {
            "rgb": {"present": bool(frames), "data": frames[0]["rgb"] if frames else None},
            "depth": {"present": bool(frames), "data": frames[0]["depth_z"] if frames else None},
            "mask": {"present": True, "data": mask},
            "fused_geometry": {"present": mesh is not None, "data": mesh}},
            "observed_est": {"kind": "regression",
                             "values": (np.asarray(channel_values, dtype=np.float32)
                                        if channel_values else np.zeros(1, dtype=np.float32)),
                             "labels": None, "channel_names": channel_names},
            "context": {"route": str(meta["route"]),
                        "input_profile": str(meta["input_profile"]),
                        "n_views": len(frames),
                        "scale_valid": bool(getattr(observation, "scale_valid", True))},
            "mask": mask, "mask_reference": research, "roi": roi,
            "crop": ((0, 0, int(frames[0]["rgb"].shape[1]), int(frames[0]["rgb"].shape[0]))
                     if frames else (0, 0, 8, 8)),
            "K": np.asarray(frames[0]["K"], dtype=np.float64) if frames else np.eye(3),
            "profile": {"camera": {"profile_id": str(getattr(first_view.frame, "profile_id", ""))
                                   if first_view is not None else "",
                                   "tier": str(getattr(first_view.frame, "tier", ""))
                                   if first_view is not None else "",
                                   "working_distance_mm": float(getattr(
                                       first_view.frame, "working_distance_mm", 0.0))
                                   if first_view is not None else 0.0},
                        "light": {"source": "ObsSpec.resolved_light"},
                        "isp": {"response": "LINEAR"}}},
        meta={**dict(meta), "mask_source": mask_source,
              "mask_reference_source": "RESEARCH_ID_MAP"}, unit="1", frame=str(meta["frame_id"]))
    return {"I": image, "G": geometry, "X": estimate}


def _numeric_leaves(mapping: Mapping[str, Any], prefix: str = "") -> tuple[list[str], list[float]]:
    """Flatten a (possibly nested) quality mapping into sorted numeric channels."""
    names: list[str] = []
    values: list[float] = []
    for key in sorted(mapping, key=str):
        value = mapping[key]
        path = f"{prefix}{key}"
        if isinstance(value, Mapping):
            sub_names, sub_values = _numeric_leaves(value, prefix=f"{path}.")
            names.extend(sub_names)
            values.extend(sub_values)
        elif isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
            number = float(value)
            if np.isfinite(number):
                names.append(path)
                values.append(number)
    return names, values


def assign_point_view(points: np.ndarray, frames: list[dict[str, Any]]) -> np.ndarray:
    """Assign every observed point to a view (best centre offset, positive depth, in frame)."""
    from ..cameras.api import project

    pts = np.asarray(points, dtype=np.float64)
    assignment = np.full(len(pts), -1, dtype=np.int32)
    best = np.full(len(pts), np.inf, dtype=np.float64)
    for index, frame in enumerate(frames):
        K = np.asarray(frame["K"], dtype=np.float64)
        depth = frame.get("depth_z")
        width = int(np.asarray(depth).shape[1]) if depth is not None else int(2 * K[0, 2])
        height = int(np.asarray(depth).shape[0]) if depth is not None else int(2 * K[1, 2])
        uv, z = project(pts, K, np.asarray(frame["T_WC"], dtype=np.float64), frame.get("dist"))
        inside = (np.isfinite(uv[:, 0]) & (z > 0) & (uv[:, 0] >= 0) & (uv[:, 0] < width)
                  & (uv[:, 1] >= 0) & (uv[:, 1] < height))
        if not np.any(inside):
            continue
        offset = np.linalg.norm(uv[inside] - np.array([K[0, 2], K[1, 2]])[None, :], axis=1)
        idx = np.flatnonzero(inside)
        better = offset < best[idx]
        assignment[idx[better]] = index
        best[idx[better]] = offset[better]
    return assignment


def probe_mesh(*, store: Any = None) -> tuple[Any, dict[str, Any], str]:
    """A real closed probe body with a tagged interface ROI and declared probe texels."""
    import trimesh

    from ..storage.mesh_io import with_face_attrs

    provenance = "BUILTIN_PROBE_FIXTURE_ROUGH_INTERFACE"
    if store is not None:
        bundle = _source_from_store(store, "P")
        if bundle is not None:
            mesh = bundle.get("mesh")
            if mesh is None:
                from .ops_geometry import mesh_of

                mesh = mesh_of(bundle)
            if mesh is not None:
                provenance = f"STORE_ASSET_MESH+{provenance}_APPEARANCE"
                return mesh, dict(bundle.meta or {}), provenance
    mesh = _rough_slab_probe()
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    interface = np.flatnonzero(normals[:, 2] > 0.9).astype(np.int32)
    origin_kind = np.zeros(len(mesh.faces), dtype=np.uint8)
    origin_kind[interface] = 1
    interface_id = np.full(len(mesh.faces), -1, dtype=np.int32)
    interface_id[interface] = 1
    with_face_attrs(mesh, origin_kind=origin_kind, interface_id=interface_id)
    return mesh, {"material_id": "M03", "fragment_id": "probe_fragment",
                  "mother_id": "probe_mother"}, provenance


def _rough_slab_probe(*, extents: tuple[float, float, float] = (24.0, 18.0, 3.2),
                      amplitude_mm: float = 0.18, correlation_mm: float = 2.5,
                      max_edge_mm: float = 1.2, seed: int = DEFAULT_MASTER_SEED) -> Any:
    """Closed slab whose outer face carries a frozen multi-scale roughness (probe fixture).

    A perfectly flat synthetic face would make the P01/P02 high-frequency band vanish, so the
    built-in probe declares a real roughness (amplitude 0.18 mm, correlation 2.5 mm) on the
    tagged interface.  The provenance string reports that this is a probe fixture.
    """
    import trimesh

    from ..physical.fields import FourierField

    mesh = trimesh.creation.box(extents=extents)
    vertices, faces = trimesh.remesh.subdivide_to_size(
        np.asarray(mesh.vertices, dtype=np.float64), np.asarray(mesh.faces, dtype=np.int64),
        max_edge=float(max_edge_mm))
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.merge_vertices()
    vertices = np.asarray(mesh.vertices, dtype=np.float64).copy()
    top = vertices[:, 2] >= float(extents[2]) / 2.0 - 1e-6
    field = FourierField.sample_frozen(np.random.default_rng(int(seed)),
                                       scale_mm=float(correlation_mm), n_components=10,
                                       field_id="probe_interface_roughness")
    if np.any(top):
        values = np.clip(field(vertices[top]), 0.0, 1.0) - 0.5
        vertices[top, 2] += float(amplitude_mm) * 2.0 * values
    out = trimesh.Trimesh(vertices=vertices, faces=np.asarray(mesh.faces), process=False)
    out.merge_vertices()
    return out


def probe_appearance(mesh: Any) -> dict[str, Any]:
    """Declared probe texel channels (never presented as measured material data)."""
    centers = np.asarray(mesh.triangles_center, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    albedo = np.tile(np.array([0.72, 0.34, 0.26], dtype=np.float32), (len(mesh.faces), 1))
    texel_layer = np.where(np.arange(len(mesh.faces)) % 3 == 0, 1, 0).astype(np.int32)
    return {
        "texel_albedo": albedo,
        "texel_substrate_albedo": np.tile(np.array([0.65, 0.62, 0.55], dtype=np.float32),
                                          (len(mesh.faces), 1)),
        "texel_area_mm2": areas,
        "texel_layer": texel_layer,
        "texel_roughness": np.full(len(mesh.faces), 0.6, dtype=np.float32),
        "texel_positions": centers,
        "pattern_region": texel_layer > 0,
        "interface_region": np.zeros(len(mesh.faces), dtype=bool),
    }


def make_probe_renderer(mesh: Any, frames: list[dict[str, Any]], *,
                        seed: int = DEFAULT_MASTER_SEED
                        ) -> Callable[[Mapping[str, Any]], list[dict[str, Any]]]:
    """Real scene re-renderer for I06/I07, built on ``synlab.observe.render``.

    The returned callable consumes the I06/I07 scene parameters and returns a fresh frame list
    from the *software rasteriser* (the only backend available on this host): the light is
    rescaled for I06 and 3-D occluder bodies are placed in the scene for I07.  Nothing is
    painted onto the delivered pixels, and the renderer identity is reported in the measurement.
    """
    import trimesh

    from ..observe.render import LightSpec, RenderSpec, build_scene, render_view
    from ..schemas.runtime import ViewFrame

    surface_tag = np.zeros(len(mesh.faces), dtype=np.int16)
    base_scene = build_scene(mesh, surface_tag=surface_tag,
                             face_id=np.arange(len(mesh.faces), dtype=np.int32), name="probe")
    view_frames: list[ViewFrame] = []
    for plan in frames:
        image = np.asarray(plan["rgb"])
        view_frames.append(ViewFrame(
            view_id=str(plan["view_id"]), K=np.asarray(plan["K"], dtype=np.float64),
            T_WC=np.asarray(plan["T_WC"], dtype=np.float64),
            image_size=(int(image.shape[1]), int(image.shape[0])),
            profile_id="probe", tier="LOCAL",
            u_position_mm=float(np.asarray(plan["T_WC"], dtype=np.float64)[0, 3]),
            working_distance_mm=float(plan.get("focus_distance_mm", 0.0) or 0.0),
            focus_setting="mid", source_kind="SENSOR_SIM",
            camera_model=("PINHOLE" if plan.get("dist") is None else "OPENCV"),
            dist=(None if plan.get("dist") is None
                  else np.asarray(plan["dist"], dtype=np.float64))))
    base_direction = np.array([-0.35, -0.62, -0.70], dtype=np.float64)
    base_direction /= np.linalg.norm(base_direction)
    base_color = np.array([2.35, 2.25, 2.10], dtype=np.float64)
    base_ambient = np.array([0.30, 0.30, 0.33], dtype=np.float64)
    spec = RenderSpec(supersample=1, max_pixels=8_000_000)
    rng = np.random.default_rng(int(seed))

    def renderer(scene_params: Mapping[str, Any]) -> list[dict[str, Any]]:
        intensity = float(scene_params.get("light_intensity_scale", 1.0))
        brdf_scale = float(scene_params.get("brdf_specular_scale", 1.0))
        light = LightSpec(direction=base_direction, color=base_color * intensity,
                          ambient=base_ambient * max(intensity, 1.0))
        scene = base_scene
        occluders = int(scene_params.get("occluder_count", 0) or 0)
        if occluders > 0:
            radius = float(scene_params.get("occluder_radius_mm", 6.0))
            centre = np.asarray(base_scene.vertices, dtype=np.float64).mean(axis=0)
            frozen_directions = list(scene_params.get("occluder_directions") or [])
            camera_centres = [np.asarray(plan["T_WC"], dtype=np.float64)[:3, 3] for plan in frames]
            blocks = []
            for index in range(occluders):
                block = trimesh.creation.icosphere(subdivisions=1, radius=radius)
                if camera_centres:
                    # Place the occluder between the object and one camera so that it really
                    # blocks that view; the axis supplies the frozen lateral jitter, which keeps
                    # the five levels paired (only the count/radius grows with the level).
                    camera = camera_centres[index % len(camera_centres)]
                    view_dir = camera - centre
                    distance = max(float(np.linalg.norm(view_dir)), 1e-9)
                    unit_view = view_dir / distance
                    lateral = (np.asarray(frozen_directions[index], dtype=np.float64)
                               if index < len(frozen_directions) else np.zeros(3))
                    lateral = lateral - float(lateral @ unit_view) * unit_view
                    position = centre + unit_view * (0.35 * distance) + lateral * radius
                else:  # pragma: no cover - frames are always present here
                    position = centre + np.array([0.0, 0.0, radius + 18.0])
                block.apply_translation(position)
                blocks.append(block)
            extra_faces = int(sum(len(b.faces) for b in blocks))
            vertices = np.vstack([np.asarray(base_scene.vertices, dtype=np.float64)]
                                 + [np.asarray(b.vertices, dtype=np.float64) for b in blocks])
            faces = [np.asarray(base_scene.faces, dtype=np.int32)]
            offset = len(base_scene.vertices)
            for block in blocks:
                faces.append(np.asarray(block.faces, dtype=np.int32) + offset)
                offset += len(block.vertices)
            faces_arr = np.vstack(faces)
            scene = type(base_scene)(
                name=f"{base_scene.name}+occluders", vertices=vertices, faces=faces_arr,
                surface_tag=np.concatenate([np.asarray(base_scene.surface_tag, dtype=np.int16),
                                            np.zeros(extra_faces, dtype=np.int16)]),
                material=replace(
                    base_scene.material,
                    albedo=np.vstack([np.asarray(base_scene.material.albedo, dtype=np.float32),
                                      np.tile(np.array([[0.25, 0.24, 0.22]], dtype=np.float32),
                                              (extra_faces, 1))]),
                    roughness=np.concatenate([
                        np.asarray(base_scene.material.roughness, dtype=np.float32),
                        np.full(extra_faces, 0.8, dtype=np.float32)])),
                face_id=np.concatenate([np.asarray(base_scene.face_id, dtype=np.int32),
                                        np.full(extra_faces, -1, dtype=np.int32)]),
                is_target=np.concatenate([np.asarray(base_scene.is_target, dtype=np.uint8),
                                          np.zeros(extra_faces, dtype=np.uint8)]))
        out: list[dict[str, Any]] = []
        for plan, view_frame in zip(frames, view_frames):
            render = render_view(scene, view_frame, light=light, spec=spec)
            linear = np.asarray(render.rgb_linear, dtype=np.float32)
            if brdf_scale != 1.0:
                linear = linear * (1.0 + 0.5 * (brdf_scale - 1.0) * np.clip(linear, 0.0, 1.0))
            out.append({**{k: v for k, v in plan.items() if k != "renderer"},
                        "rgb_linear": linear,
                        "rgb": np.rint(np.clip(linear, 0.0, 1.0) * 255.0).astype(np.uint8),
                        "depth_z": np.asarray(render.depth_z, dtype=np.float32),
                        "valid_mask": (np.asarray(render.id_map, dtype=np.int32) >= 0)
                        & (np.asarray(render.visibility, dtype=np.uint8) > 0),
                        "encoding": "LINEAR",
                        "re_rendered": True})
        return out

    return renderer


def probe_sources(*, store: Any = None, size: tuple[int, int] = (128, 96), views: int = 4,
                  seed: int = DEFAULT_MASTER_SEED) -> dict[str, SourceBundle]:
    """Real, labelled probe sources for the operator audit (one bundle per axis family).

    ``meta['provenance']`` records exactly where each bundle came from: ``STORE_ASSET:<id>``,
    ``BUILTIN_PROBE_REAL_RENDER`` (a real proxy-scan render at 128x96) or
    ``BUILTIN_PROBE_FIXTURE`` (a synthetic box used only when no fragment asset exists).
    """
    mesh, meta, provenance = probe_mesh(store=store)
    meta = dict(meta)
    meta.setdefault("master_seed", int(seed))
    meta.setdefault("fragment_id", "probe_fragment")
    meta.setdefault("mother_id", "probe_mother")
    appearance = probe_appearance(mesh)
    physical = SourceBundle(
        source_kind=KIND_PHYSICAL,
        payload={"mesh": mesh, "appearance": appearance,
                 "fragment": AXES_MODULE._FragmentView(mesh, str(meta["fragment_id"]),
                                                       meta={**meta, "appearance": appearance})},
        meta={**meta, "provenance": provenance}, unit="mm", frame="F_mm")
    out: dict[str, SourceBundle] = {"P": physical}
    observation = None
    try:
        observation = observe_probe(size=size, views=views, seed=seed)
    except SynLabError:
        observation = None
    if observation is not None:
        for key, bundle in bundles_from_observation(observation).items():
            bundle.meta.setdefault("provenance", "BUILTIN_PROBE_REAL_RENDER")
            out[key] = bundle
        renderer = make_probe_renderer(mesh, list(out["I"].get("frames") or []), seed=seed)
        out["I"] = out["I"].with_payload(renderer=renderer,
                                         scene={"light": "ObsSpec.resolved_light",
                                                "occluders": 0})
        out["I"].meta["renderer"] = "synlab.observe.render.render_view (software rasteriser)"
    else:
        kind = {"I": KIND_IMAGE, "G": KIND_GEOMETRY, "X": KIND_OBS}
        for key in ("I", "G", "X"):
            payload = {"points": np.zeros((0, 3))} if key == "G" else {}
            out[key] = SourceBundle(source_kind=kind[key], payload=payload,
                                    meta={"provenance": "NO_OBSERVATION_AVAILABLE",
                                          "master_seed": int(seed)})
    return out


def audit_axis(axis_id: str, levels: Iterable[int] = (0, 1, 2, 3, 4), store: Any = None,
               sources: SourceProvider = None, *, variant: str | None = None,
               limit: int = 1, basis: DegradationBasis | None = None,
               lineage_id: str = "audit_lineage", split: str = "train",
               cache: dict[str, SourceBundle] | None = None) -> dict[str, Any]:
    """Run every level of one axis on a real source and report the measured outcome."""
    operator = get_operator(axis_id)
    variant_name = operator.resolve_variant(variant)
    cache = cache if cache is not None else {}
    source = _resolve_source(axis_id, sources, store, cache)
    report: dict[str, Any] = {
        "axis_id": axis_id, "variant": variant_name, "stage": operator.STAGE,
        "substage": operator.SUBSTAGE, "factor_kind": operator.factor_kind_for(variant_name),
        "provided_values": sorted(operator.level_parameters(0).keys()),
        "label_invalidations": list(operator.LABEL_INVALIDATIONS), "levels": {},
        "independent_mothers": 0,
    }
    level_list = [int(l) for l in levels]
    if source is None:
        report["status"] = "NA"
        report["na_reason"] = "no applicable source bundle available for this axis family"
        report["levels"] = {str(l): {"status": "NA", "level": l, "variant": variant_name,
                                     "na_reason": report["na_reason"]} for l in level_list}
        return report
    report["source"] = {"provenance": str((source.meta or {}).get("provenance", "CALLER")),
                        "source_kind": source.source_kind, "asset_id": source.asset_id,
                        "content_hash": source.content_hash()}
    if basis is None:
        master_seed = int((source.meta or {}).get("master_seed", DEFAULT_MASTER_SEED))
        context = _context_for(source, axis_id=axis_id, lineage_id=lineage_id,
                               master_seed=master_seed)
        basis = operator.sample_basis(context, _default_rng(context, axis_id, variant_name),
                                      variant_name)
    report["basis_id"] = basis.basis_id
    mothers: set[str] = set()
    per_level: dict[str, Any] = {}
    statuses: list[str] = []
    for level in level_list:
        entry: dict[str, Any] = {"level": level, "variant": variant_name,
                                 "planned": _jsonable(operator.params_for(level, variant_name)),
                                 "basis_id": basis.basis_id}
        try:
            _, record, measurement = _apply_impl(axis_id, level, source, store,
                                                 variant=variant_name, lineage_id=lineage_id,
                                                 split=split, basis=basis)
            entry.update({
                "status": "PASS", "identity": bool(measurement.identity),
                "realized": bool(measurement.realized), "measured": _jsonable(measurement.measured),
                "units": _jsonable(measurement.units), "result_hash": measurement.result_hash,
                "source_hash": measurement.source_hash,
                "asset_id": getattr(record, "asset_id", None),
                "factor_kind": measurement.factor_kind,
                "invariants": _jsonable(measurement.extra.get("invariants", {})),
                "label_status": measurement.extra.get("label_status"),
                "label_validity": measurement.extra.get("label_validity"),
                "label_dependency_status": _jsonable(
                    measurement.extra.get("label_dependency_status", {})),
                "label_receipt_refs": _jsonable(
                    measurement.extra.get("label_receipt_refs", {})),
            })
            if level == 0:
                original = getattr(record, "asset_id", None)
                entry["identity_reference_ok"] = bool(source.asset_id is None
                                                      or original == source.asset_id)
                entry["bytes_unchanged"] = bool(measurement.result_hash == measurement.source_hash)
                if not (entry["identity_reference_ok"] and entry["bytes_unchanged"]):
                    entry["status"] = "FAIL"
                    entry["failure_code"] = "IDENTITY_BROKEN"
            else:
                mother = str((source.meta or {}).get("mother_id") or source.lineage_id or "unknown")
                mothers.add(f"{mother}:{source.asset_id or 'memory'}")
            statuses.append(entry["status"])
        except SynLabError as exc:
            code = exc.code.value if isinstance(exc.code, ErrorCode) else str(exc.code)
            status = "NA" if code in (ErrorCode.NA_NOT_APPLICABLE.value,
                                      ErrorCode.DEPENDENCY_CAPABILITY_MISSING.value) else "FAIL"
            entry.update({"status": status, "failure_code": code, "error": exc.message,
                          "measured": _jsonable(exc.measurements)})
            statuses.append(status)
            # Release the frames and multi-million-node SDF grids the traceback would keep
            # alive: the structured error keeps message + measurements, not the object graph.
            exc.__traceback__ = None
            exc.__context__ = None
        per_level[str(level)] = entry
    report["levels"] = per_level
    report["independent_mothers"] = len(mothers)
    if "FAIL" in statuses:
        report["status"] = "FAIL"
    elif "PASS" in statuses and all(s in ("PASS", "NA") for s in statuses):
        non_identity_pass = any(per_level[str(l)]["status"] == "PASS" and l > 0
                                for l in level_list if str(l) in per_level)
        report["status"] = "PASS" if (non_identity_pass or level_list == [0]) else "NA"
    else:
        report["status"] = "NA"
    if report["status"] == "NA":
        report["na_reasons"] = sorted({str(e.get("error")) for e in per_level.values()
                                       if e["status"] == "NA" and e.get("error")})
    return report


def audit_all_axes(store: Any = None, *, levels: Iterable[int] = (0, 1, 2, 3, 4),
                   sources: SourceProvider = None, limit: int = 1,
                   axes: Iterable[str] | None = None, lineage_id: str = "audit_lineage",
                   split: str = "train") -> dict[str, Any]:
    """Audit every registered axis and return the A10 acceptance report.

    ``{"ok": bool, "identity_ok": bool, "axes": {axis_id: {"status": "PASS/FAIL/NA/MISSING",
    "independent_mothers": int, "levels": {...}}}, ...}``.  ``MISSING`` means the axis is
    declared in the schema but not implemented.  No timestamps are written: a repeated run in a
    fixed environment reproduces the report.
    """
    wanted = list(axes) if axes is not None else AXIS_REGISTRY.ids()
    missing = list(AXIS_REGISTRY.missing())
    cache: dict[str, SourceBundle] = {}
    resolved = sources if sources is not None else probe_sources(store=store)
    level_list = [int(l) for l in levels]
    reports: dict[str, Any] = {}
    measurements: list[dict[str, Any]] = []
    for axis_id in wanted:
        if not AXIS_REGISTRY.has(axis_id):
            reports[axis_id] = {"status": "MISSING", "independent_mothers": 0, "levels": {},
                                "error": "axis is not registered"}
            continue
        report = audit_axis(axis_id, levels=level_list, store=store, sources=resolved,
                            limit=limit, lineage_id=lineage_id, split=split, cache=cache)
        reports[axis_id] = report
        measurements.extend(_rows_from_axis_report(report))
        if cache:
            cache.clear()  # keep only the shared bundle references the caller still needs
    for axis_id in missing:
        reports.setdefault(axis_id, {"status": "MISSING", "independent_mothers": 0, "levels": {},
                                     "error": "axis declared in the schema but not implemented"})
    for axis_id in AXIS_REGISTRY.ids():
        reports.setdefault(axis_id, {"status": "MISSING", "independent_mothers": 0, "levels": {}})
    evaluated = [r for r in reports.values() if r.get("status") != "MISSING"]
    with_identity = [r for r in evaluated if "0" in r.get("levels", {})]
    identity_ok = bool(with_identity) and all(
        bool(r["levels"]["0"].get("identity")) and bool(r["levels"]["0"].get("bytes_unchanged", True))
        for r in with_identity)
    positive = [r for r in evaluated
                if r.get("status") == "PASS" and r.get("independent_mothers", 0) > 0]
    failing = sorted(a for a, r in reports.items() if r.get("status") == "FAIL")
    # ``ok`` means "this audit is a valid, honest audit": every axis is registered, every
    # level-0 identity is proven and at least one axis realized a measured effect.  Per-axis
    # FAILs are reported in ``failing_axes``/``denominators`` and must not be hidden by a
    # global boolean; ``all_axes_pass`` is the strict gate a release may require.
    ok = bool(not missing and identity_ok and len(positive) >= 1)
    all_axes_pass = bool(not missing and not failing and identity_ok
                         and len(positive) == len(evaluated) and evaluated)
    denominators = {
        "axes_registered": len(AXIS_REGISTRY.ids()),
        "axes_audited": len(evaluated),
        "axes_pass": len([r for r in evaluated if r.get("status") == "PASS"]),
        "axes_na": len([r for r in evaluated if r.get("status") == "NA"]),
        "axes_fail": len([r for r in evaluated if r.get("status") == "FAIL"]),
        "axes_missing": len([r for r in reports.values() if r.get("status") == "MISSING"]),
        "levels_planned": int(sum(len(r.get("levels", {})) for r in reports.values())),
        "levels_passed": int(sum(1 for r in reports.values() for e in r.get("levels", {}).values()
                                 if e.get("status") == "PASS")),
        "levels_na": int(sum(1 for r in reports.values() for e in r.get("levels", {}).values()
                             if e.get("status") == "NA")),
        "levels_failed": int(sum(1 for r in reports.values() for e in r.get("levels", {}).values()
                                 if e.get("status") == "FAIL")),
    }
    return {
        "ok": ok, "identity_ok": identity_ok, "all_axes_pass": all_axes_pass,
        "failing_axes": failing, "levels": level_list, "axes": reports,
        "denominators": denominators, "measurements": measurements,
        "axis_registry": [op.declared() for op in AXIS_REGISTRY.all().values()],
        "source_provenance": sorted({str((r.get("source") or {}).get("provenance", "NONE"))
                                     for r in evaluated if r.get("source")}),
        "contract": {
            "level0": "true identity (original asset reference/bytes)",
            "paired_basis": "all five levels share one basis_id",
            "not_realized": "declared effect not measured => OPERATOR_NOT_REALIZED",
            "na": "inapplicable input => NA_NOT_APPLICABLE and stays in the denominator",
            "min_independent_mothers_per_axis": 20,
        },
        "limits": {
            "independent_mothers_observed": max([r.get("independent_mothers", 0)
                                                 for r in evaluated] or [0]),
            "min_independent_mothers_required": 20,
            "note": "the 20-mother requirement is a dataset-level requirement; this audit runs on "
                    "the sources available in the store plus the labelled probe fixture",
            "source_limit": int(limit),
        },
    }


def _rows_from_axis_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, entry in sorted(report.get("levels", {}).items()):
        row: dict[str, Any] = {
            "axis_id": report.get("axis_id"),
            "variant": entry.get("variant", report.get("variant")),
            "level": int(entry.get("level", key)),
            "factor_kind": entry.get("factor_kind", report.get("factor_kind")),
            "stage": report.get("stage"), "substage": report.get("substage"),
            "basis_id": entry.get("basis_id", report.get("basis_id")),
            "status": entry.get("status"), "identity": entry.get("identity"),
            "realized": entry.get("realized"), "valid": entry.get("status") == "PASS",
            "na_reason": entry.get("error") if entry.get("status") == "NA" else None,
            "failure_code": entry.get("failure_code"),
            "source_hash": entry.get("source_hash"), "result_hash": entry.get("result_hash"),
            "source_provenance": (report.get("source") or {}).get("provenance"),
            "source_asset_id": (report.get("source") or {}).get("asset_id"),
            "result_asset_id": entry.get("asset_id"),
            "calibration_status": "UNCALIBRATED",
            "independent_mothers": report.get("independent_mothers", 0),
            "label_status": entry.get("label_status"),
            "label_validity": entry.get("label_validity"),
            "label_dependency_status": entry.get("label_dependency_status", {}),
            "label_receipt_refs": entry.get("label_receipt_refs", {}),
            "label_invalidations": ",".join(report.get("label_invalidations", [])),
        }
        for name, value in dict(entry.get("planned") or {}).items():
            row[f"planned_{name}"] = value
        if entry.get("status") == "PASS":
            for name, value in dict(entry.get("measured") or {}).items():
                if isinstance(value, (int, float, bool, str)) or value is None:
                    row[f"measured_{name}"] = value
            for name, value in dict(entry.get("units") or {}).items():
                row[f"unit_{name}"] = value
        rows.append(row)
    return rows


# ======================================================================================
# parquet
# ======================================================================================
BASE_COLUMNS = ("axis_id", "variant", "level", "factor_kind", "stage", "substage", "basis_id",
                "status", "identity", "realized", "valid", "na_reason", "failure_code",
                "source_hash", "result_hash", "source_provenance", "source_asset_id",
                "result_asset_id", "calibration_status", "label_status", "label_validity",
                "label_invalidations",
                "label_dependency_status", "label_receipt_refs", "independent_mothers")


def operator_audit_table(rows: Sequence[Mapping[str, Any]]) -> Any:
    """Build the ``operator_measurements.parquet`` table (plan 15.7 row 7, line 934)."""
    import pyarrow as pa

    if not rows:
        schema = pa.schema([(name, pa.string()) for name in BASE_COLUMNS])
        return pa.Table.from_pylist([], schema=schema)
    columns = list(BASE_COLUMNS)
    columns.extend(sorted({str(k) for row in rows for k in row} - set(BASE_COLUMNS)))
    normalised: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {}
        for key in columns:
            value = row.get(key)
            if isinstance(value, (np.integer,)):
                value = int(value)
            elif isinstance(value, (np.floating,)):
                value = float(value)
            elif isinstance(value, (np.bool_,)):
                value = bool(value)
            elif isinstance(value, (np.ndarray, dict, list, tuple)):
                value = json_dumps(_jsonable(value))
            entry[key] = value
        normalised.append(entry)
    return pa.Table.from_pylist(normalised)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def write_operator_measurements(rows: Sequence[Mapping[str, Any]], path: str | Path | None = None,
                                *, store: Any = None) -> dict[str, Any]:
    """Write ``operator_measurements.parquet`` and return the path plus row/column counts."""
    import pyarrow.parquet as pq

    if path is None:
        if store is None:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "write_operator_measurements needs a path or a store root",
                              stage="degrade.write_operator_measurements")
        path = Path(getattr(store, "root", store)) / "reports" / "operator_measurements.parquet"
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    table = operator_audit_table(rows)
    pq.write_table(table, target)
    return {"path": str(target), "rows": int(table.num_rows), "columns": list(table.column_names)}
