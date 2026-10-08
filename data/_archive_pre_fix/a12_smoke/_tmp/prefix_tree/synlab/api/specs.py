"""Spec validation shared by ``POST /specs/validate``, ``POST /budgets`` and ``POST /jobs``.

Validation is delegated to the project's typed schemas (``extra="forbid"``) and to
``synlab.config`` — the API never keeps a second copy of ranges or identifier lists.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..canonical import canonical_json, hash_json
from ..config import compile_recipe, compile_spec, load_generation_spec  # noqa: F401 - re-exported
from ..errors import ErrorCode, SynLabError
from ..registry import REGISTRY
from ..schemas.spec import (
    DegradationRecipeSpec,
    DiagnosticSpec,
    GenerationSpec,
    TrainingSpec,
)
from .problems import API_CODE_BAD_REQUEST, ApiProblem

MODELS: dict[str, Any] = {
    "generation": GenerationSpec,
    "recipe": DegradationRecipeSpec,
    "train": TrainingSpec,
    "diagnose": DiagnosticSpec,
}

SCHEMA_IDS: dict[str, str] = {
    "generation": "synlab.v3",
    "recipe": "synlab.v3",
    "train": "synlab.train.v1",
    "diagnose": "synlab.diagnose.v1",
}


def kind_for_schema(schema_version: str) -> str:
    for kind, schema in SCHEMA_IDS.items():
        if schema == schema_version and kind != "recipe":
            return kind
    raise ApiProblem(422, API_CODE_BAD_REQUEST,
                     f"unknown schema_version {schema_version!r}; expected one of "
                     f"{sorted(set(SCHEMA_IDS.values()))}", stage="specs.kind")


def _pydantic_errors(exc: ValidationError) -> list[dict[str, Any]]:
    out = []
    for error in exc.errors():
        out.append({
            "loc": [str(part) for part in error.get("loc", ())],
            "type": error.get("type"),
            "msg": error.get("msg"),
            "input": _short(error.get("input")),
        })
    return out


def _short(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    text = repr(value)
    return text[:120]


def validate_spec(spec: dict[str, Any], *, kind: str = "generation",
                  registry_check: bool = True) -> dict[str, Any]:
    """Validate a spec.  Returns ``ok=False`` plus every reason; it never raises for content."""
    if kind not in MODELS:
        raise ApiProblem(422, API_CODE_BAD_REQUEST,
                         f"unknown spec kind {kind!r}; expected one of {sorted(MODELS)}",
                         stage="specs.validate")
    if not isinstance(spec, dict):
        raise ApiProblem(422, API_CODE_BAD_REQUEST, "spec must be a JSON object",
                         stage="specs.validate")

    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    model = None
    try:
        model = MODELS[kind].model_validate(spec)
    except ValidationError as exc:
        errors.extend(_pydantic_errors(exc))

    canonical: str | None = None
    spec_hash: str | None = None
    expanded: dict[str, Any] = {}
    if model is not None:
        dumped = model.model_dump(mode="json", by_alias=True)
        canonical = canonical_json(dumped)
        spec_hash = hash_json(dumped)
        if kind == "generation" and registry_check:
            compiled = compile_spec(model)
            errors.extend({"loc": ["compile"], "type": "compiler", "msg": message, "input": None}
                          for message in compiled.errors)
            warnings.extend(compiled.warnings)
            expanded = compiled.expanded
        elif kind == "recipe" and registry_check:
            try:
                compiled_recipe = compile_recipe(model)
                errors.extend({"loc": ["compile"], "type": "compiler", "msg": message, "input": None}
                              for message in compiled_recipe.errors)
                warnings.extend(compiled_recipe.warnings)
                expanded = {"recipe_hash": compiled_recipe.hash,
                            "nodes": [n.as_dict() for n in compiled_recipe.nodes]}
            except SynLabError as exc:
                # the degradation axis registry is a parallel module; report the real reason
                warnings.append(f"recipe operator registry unavailable: [{exc.code}] {exc.message}")
                expanded = {"recipe_uncompiled": True}

    return {
        "ok": not errors,
        "rejected": bool(errors),
        "kind": kind,
        "schema_id": SCHEMA_IDS[kind],
        "errors": errors,
        "warnings": warnings,
        "spec_hash": spec_hash,
        "canonical": canonical,
        "expanded": expanded,
        "registry_fingerprint": REGISTRY.fingerprint(),
        "note": "HTTP 200 with ok=false means the spec was rejected; POST /jobs answers 422 for "
                "the same spec",
    }
