"""Configuration loading, canonicalisation and compilation (plan 5.2, 22, 30.2).

The compiler is the only place allowed to decide whether a spec is legal: it rejects
unknown fields (pydantic ``extra=forbid``), unregistered registry ids, illegal stage
order, unsupported material/axis combinations and profiles whose scope conflicts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .canonical import canonical_json, hash_json
from .errors import ErrorCode, SynLabError
from .registry import REGISTRY
from .schemas.spec import (
    AXIS_IDS,
    FRACTURE_BACKEND_IDS,
    LAYER_COMBO_IDS,
    MATERIAL_IDS,
    PATTERN_IDS,
    STAGE_ORDER,
    SUBSTAGE_ORDER,
    VESSEL_IDS,
    DegradationRecipeSpec,
    DiagnosticSpec,
    GenerationSpec,
    TrainingSpec,
)

SAFE_YAML_LIMIT_BYTES = 4 * 1024 * 1024


def load_document(path: str | Path) -> dict[str, Any]:
    """Load a YAML/JSON config with size and type limits (plan 30.16)."""
    path = Path(path)
    if not path.exists():
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"config not found: {path}", stage="config.load")
    if path.stat().st_size > SAFE_YAML_LIMIT_BYTES:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"config exceeds {SAFE_YAML_LIMIT_BYTES} bytes: {path}", stage="config.load")
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"invalid YAML in {path}: {exc}",
                          stage="config.load") from exc
    if not isinstance(data, dict):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"{path} must contain a mapping", stage="config.load")
    return data


@dataclass
class CompiledSpec:
    spec: GenerationSpec
    kind: str
    spec_hash: str
    canonical: str
    expanded: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "spec_hash": self.spec_hash, "ok": self.ok,
            "errors": self.errors, "warnings": self.warnings, "expanded": self.expanded,
            "canonical": self.canonical,
        }


def _model_to_dict(model: Any) -> dict[str, Any]:
    return json.loads(model.model_dump_json(by_alias=True))


def load_generation_spec(path: str | Path) -> GenerationSpec:
    data = load_document(path)
    try:
        return GenerationSpec.model_validate(data)
    except Exception as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"{path}: {exc}", stage="config.validate") from exc


def load_train_spec(path: str | Path) -> TrainingSpec:
    data = load_document(path)
    try:
        return TrainingSpec.model_validate(data)
    except Exception as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"{path}: {exc}", stage="config.validate") from exc


def load_diagnose_spec(path: str | Path) -> DiagnosticSpec:
    data = load_document(path)
    try:
        return DiagnosticSpec.model_validate(data)
    except Exception as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"{path}: {exc}", stage="config.validate") from exc


def load_recipe_spec(path: str | Path) -> DegradationRecipeSpec:
    data = load_document(path)
    try:
        return DegradationRecipeSpec.model_validate(data)
    except Exception as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"{path}: {exc}", stage="config.validate") from exc


def compile_spec(spec: GenerationSpec, *, registry_ids: dict[str, list[str]] | None = None) -> CompiledSpec:
    """Validate a generation spec against the registry and expand registry-derived fields."""
    reg = registry_ids or {
        "vessel": REGISTRY.ids("vessel") or VESSEL_IDS,
        "material": REGISTRY.ids("material") or MATERIAL_IDS,
        "pattern": REGISTRY.ids("pattern") or PATTERN_IDS,
        "layer_combo": REGISTRY.ids("layer_combo") or LAYER_COMBO_IDS,
    }
    errors: list[str] = []
    warnings: list[str] = []

    for kind, ids in (("vessel", spec.dataset.vessel_ids), ("material", spec.dataset.material_ids),
                      ("pattern", spec.dataset.pattern_ids),
                      ("layer_combo", spec.dataset.layer_combo_ids)):
        allowed = set(reg.get(kind, []))
        unknown = [i for i in ids if i not in allowed]
        if unknown:
            errors.append(f"dataset.{kind}_ids unregistered: {unknown}")
    if spec.fracture.backend not in FRACTURE_BACKEND_IDS:
        errors.append(f"fracture.backend unregistered: {spec.fracture.backend}")

    lo, hi = spec.fracture.target_piece_range
    if spec.dataset.target_fragments_estimate < lo:
        warnings.append(
            f"target_fragments_estimate {spec.dataset.target_fragments_estimate} below "
            f"per-mother piece range minimum {lo}; actual piece counts are recorded, never trimmed"
        )
    for ref in spec.degraded_recipe_refs:
        p = Path(ref)
        if not p.exists():
            warnings.append(f"degraded recipe ref not found at compile time: {ref}")
    if spec.implementation.require_poc_before_custom and not Path(spec.implementation.reuse_manifest_ref).exists():
        errors.append(
            f"reuse manifest {spec.implementation.reuse_manifest_ref} missing; CUSTOM_GAP evidence required"
        )
    if spec.pattern.height_policy != "none" and not spec.pattern.geometry_before_fracture:
        errors.append("geometry pattern must be applied before fracture")

    stats = REGISTRY.summary()
    expanded = {
        "vessels": spec.dataset.vessel_ids,
        "materials": spec.dataset.material_ids,
        "patterns": spec.dataset.pattern_ids,
        "fracture_backend": spec.fracture.backend,
        "registry": stats,
        "split": spec.dataset.shape_lineage_split.model_dump(),
        "target_mothers": spec.dataset.target_mothers,
    }
    payload = _model_to_dict(spec)
    return CompiledSpec(
        spec=spec, kind="synlab.v3", spec_hash=hash_json(payload),
        canonical=canonical_json(payload), expanded=expanded, warnings=warnings, errors=errors,
    )


# ---------------------------------------------------------------------------- DAG compilation
@dataclass
class DagNode:
    node_id: str
    operator: str
    variant: str
    stage: str
    substage: str
    level: int
    reads: list[str]
    writes: list[str]
    parameters: dict[str, Any]
    label_invalidations: list[str]
    allowed_profile: list[str]
    cost_class: str = "medium"

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "operator": self.operator, "variant": self.variant,
            "stage": self.stage, "substage": self.substage, "level": self.level,
            "reads": self.reads, "writes": self.writes, "parameters": self.parameters,
            "label_invalidations": self.label_invalidations, "allowed_profile": self.allowed_profile,
            "cost_class": self.cost_class,
        }


@dataclass
class CompiledRecipe:
    recipe_id: str
    nodes: list[DagNode]
    hash: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {"recipe_id": self.recipe_id, "hash": self.hash, "ok": self.ok,
                "errors": self.errors, "warnings": self.warnings,
                "nodes": [n.as_dict() for n in self.nodes], "meta": self.meta}


def sort_nodes(nodes: list[DagNode]) -> list[DagNode]:
    """Order nodes by (stage, substage) and verify no write-before-read inversion."""
    ordered = sorted(nodes, key=lambda n: (STAGE_ORDER.get(n.stage, 99),
                                           SUBSTAGE_ORDER.get(n.substage, 99), n.node_id))
    available: set[str] = set()
    for node in ordered:
        missing = [r for r in node.reads if r not in available and not r.startswith("source:")]
        if missing:
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"node {node.node_id} reads {missing} before they exist; illegal stage order",
                stage="config.compile",
            )
        available.update(node.writes)
    return ordered


def compile_recipe(spec: DegradationRecipeSpec) -> CompiledRecipe:
    """Compile a degradation recipe spec into a typed DAG (plan 15.1, 30.2)."""
    from .degrade.registry import get_operator

    errors: list[str] = []
    warnings: list[str] = []
    nodes: list[DagNode] = []
    for index, item in enumerate(spec.operators):
        if item.axis_id not in AXIS_IDS:
            errors.append(f"unregistered axis {item.axis_id}")
            continue
        try:
            operator = get_operator(item.axis_id)
        except SynLabError as exc:
            errors.append(str(exc))
            continue
        declared = operator.STAGE
        if declared != item.stage.value:
            errors.append(
                f"axis {item.axis_id} stage mismatch: registry says {declared}, spec says {item.stage.value}"
            )
        nodes.append(DagNode(
            node_id=f"n{index:02d}_{item.axis_id}",
            operator=item.axis_id,
            variant=item.variant or operator.default_variant,
            stage=declared,
            substage=getattr(operator, "SUBSTAGE", ""),
            level=int(item.level),
            reads=list(getattr(operator, "READS", ["asset"])),
            writes=list(getattr(operator, "WRITES", ["asset"])),
            parameters=dict(item.parameters or {}),
            label_invalidations=list(getattr(operator, "LABEL_INVALIDATIONS", [])),
            allowed_profile=list(getattr(operator, "ALLOWED_PROFILES", ["PHONE_RGB", "SENSOR_PROXY",
                                                                         "SENSOR_UPPER_BOUND"])),
            cost_class=getattr(operator, "COST_CLASS", "medium"),
        ))
    try:
        ordered = sort_nodes(nodes) if nodes else []
    except SynLabError as exc:
        errors.append(str(exc))
        ordered = nodes
    payload = {"recipe_id": spec.recipe_id, "nodes": [n.as_dict() for n in ordered],
               "basis_policy": spec.basis_policy, "source_role": spec.source_role}
    return CompiledRecipe(recipe_id=spec.recipe_id, nodes=ordered, hash=hash_json(payload),
                          warnings=warnings, errors=errors,
                          meta={"basis_policy": spec.basis_policy, "source_role": spec.source_role})
