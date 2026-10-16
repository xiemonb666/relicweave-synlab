"""Read-only, fail-closed audit of the RelicWeave evidence chain.

The audit input is a small JSON document that names explicit producer manifests and
normalized lineage rows. It reads only those JSON references, verifies their hashes,
and never walks an asset/package directory. A structurally complete record is not a
scientific acceptance: physics and pretraining eligibility always remain unverified.

The field boundaries follow:
* ``forge.asset.v1`` (VesselForge manifest; geometry-only validation scope);
* ``pgfrag.job.v1`` / ``pgfrag.result.v1`` (PG-Frag job and bounded-result schema);
* A12 ``docs/a12/data_contract.md``, ``synlab/roles.py`` and
  ``synlab/schemas/view_channels.json`` (feature/label separation and input policy);
* the six separate gates in A12 ``docs/a12/engineering_policy.md``.

No producer schema is changed or treated as a physical truth oracle here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


INPUT_SCHEMA = "relicweave.chain.audit.input.v1"
REPORT_SCHEMA = "relicweave.chain.audit.report.v1"
MAX_REFERENCE_BYTES = 2_000_000

GATES = (
    "Geometry",
    "NativeRun",
    "NumericPhysical",
    "CalibratedMaterial",
    "CrackSurface",
    "RelicWeaveData",
)

# A12 roles.FORBIDDEN_FEATURE_FIELDS plus training.adapter.FEATURE_FORBIDDEN_FIELDS.
FORBIDDEN_FEATURE_FIELDS = frozenset({
    "parent_id", "object_id", "bag_id", "seed", "seed_ref", "generator_family_id",
    "interface_id", "relation", "historical_R2", "mate_present", "truth_pose", "T_WF",
    "clean_hidden_surface", "gt_thickness", "gt_normal", "gt_curvature",
    "damage_strength", "spurious_mask", "hard_case_tag", "lineage_id", "mother_id",
    "fragment_id", "event_id", "split", "variant", "axis_id", "level",
    "labels_relation", "R2", "neg_mask", "pos_mask", "quality_target", "corr_weight",
    "reward", "done_success",
})

# Fields in synlab.training.adapter.FeatureBundle that may reach the tensor bundle.
# fragment_ids and meta are intentionally absent: they are indexing/reporting only.
FEATURE_BUNDLE_FIELDS = frozenset({
    "global_rgb", "global_valid", "pixel_valid", "local_tokens", "token_valid",
    "token_view", "token_pixel", "token_modality", "token_source", "token_retrieval",
    "tokens_total", "points", "point_valid", "normals", "normal_valid", "quality",
    "quality_valid", "presence", "presence_valid", "scale_valid", "obs_version",
})

REQUIRED_REFERENCE_KEYS = {
    "parent_asset": "parent_asset_manifest",
    "native_job": "native_job",
    "native_result": "native_result",
    "fragment_set": "fragment_set_manifest",
    "crack_surfaces": "crack_surface_manifest",
    "material_calibration": "material_calibration_record",
    "historical_relations": "historical_relations_record",
    "degradation_recipe": "degradation_recipe_record",
    "degradation_measurements": "degradation_measurements",
    "observations": "observations_manifest",
    "capture_records": "capture_records",
    "input_feature_whitelist": "input_feature_spec",
    "isolated_labels": "isolated_label_spec",
    "feature_channel_policy": "feature_policy",
}

EXPECTED_SCHEMAS = {
    "parent_asset_manifest": "forge.asset.v1",
    "native_job": "pgfrag.job.v1",
    "native_result": "pgfrag.result.v1",
    "dataset_export_manifest": "synlab.training_package_manifest.v1",
    "feature_policy": "synlab.view_channel_policy.v1",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _gap(gaps: list[dict[str, str]], field: str, status: str, reason: str) -> None:
    item = {"field": field, "status": status, "reason": reason}
    if item not in gaps:
        gaps.append(item)


def _safe_relative_path(root: Path, raw_path: Any, *, allow_absolute: bool = False) -> tuple[Path | None, str | None]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, "path is missing or is not a non-empty string"
    if "\\" in raw_path or ":" in raw_path:
        return None, "path must be a root-relative POSIX path without drive, colon, or backslash"
    candidate_text = Path(raw_path)
    if candidate_text.is_absolute():
        if not allow_absolute:
            return None, "absolute paths are not allowed for evidence references"
        try:
            candidate_text.resolve(strict=False).relative_to(root.resolve(strict=True))
        except (OSError, ValueError):
            return None, "absolute path is outside the declared audit root"
        relative = candidate_text.resolve(strict=False).relative_to(root.resolve(strict=True))
        parts = relative.parts
    else:
        pure = PurePosixPath(raw_path)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            return None, "path traversal or non-normal path component is not allowed"
        parts = pure.parts
    if not parts:
        return None, "path must name a file below the audit root"

    root_real = root.resolve(strict=True)
    cursor = root_real
    try:
        for part in parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return None, "symlink components are not allowed in evidence paths"
        resolved = cursor.resolve(strict=True)
        resolved.relative_to(root_real)
    except FileNotFoundError:
        return None, "referenced file does not exist"
    except (OSError, ValueError):
        return None, "resolved path escapes the declared audit root"
    if not resolved.is_file():
        return None, "reference is not a regular file"
    return resolved, None


def _read_reference(root: Path, ref: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Read one explicitly named, small JSON reference and verify its declared digest."""
    result: dict[str, Any] = {"status": "INCOMPLETE", "path": None, "sha256": None, "reason": None}
    if not isinstance(ref, Mapping):
        result["reason"] = "reference object is missing"
        return None, result
    raw_path = ref.get("path")
    result["path"] = raw_path if isinstance(raw_path, str) else None
    resolved, path_error = _safe_relative_path(root, raw_path)
    if path_error:
        result["status"] = "UNSAFE_PATH" if "path traversal" in path_error or "absolute" in path_error or "symlink" in path_error or "escapes" in path_error else "MISSING"
        result["reason"] = path_error
        return None, result
    assert resolved is not None
    if resolved.suffix.lower() != ".json":
        result["status"] = "NON_JSON_REFERENCE"
        result["reason"] = "only explicitly named JSON metadata references may be read"
        return None, result
    try:
        size = resolved.stat().st_size
        if size > MAX_REFERENCE_BYTES:
            result["status"] = "OVERSIZE_NOT_READ"
            result["reason"] = f"reference is {size} bytes; explicit JSON references are capped at {MAX_REFERENCE_BYTES} bytes"
            return None, result
        raw = resolved.read_bytes()
    except OSError as exc:
        result["status"] = "READ_ERROR"
        result["reason"] = str(exc)
        return None, result
    actual_hash = _sha256(raw)
    result["sha256"] = actual_hash
    expected = ref.get("sha256")
    if isinstance(expected, str) and expected.startswith("sha256:"):
        expected = expected[7:]
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        result["status"] = "INCOMPLETE"
        result["reason"] = "reference must declare a 64-digit SHA-256"
        return None, result
    if actual_hash.lower() != expected.lower():
        result["status"] = "HASH_MISMATCH"
        result["reason"] = f"declared SHA-256 {expected.lower()} does not match file SHA-256 {actual_hash}"
        return None, result
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["status"] = "INVALID_JSON"
        result["reason"] = f"explicit reference is not valid UTF-8 JSON: {exc}"
        return None, result
    if not isinstance(document, dict):
        result["status"] = "INVALID_JSON"
        result["reason"] = "JSON reference root must be an object"
        return None, result
    result["status"] = "HASH_VERIFIED_JSON_READ"
    result["bytes"] = size
    result["reason"] = None
    return document, result


def _valid_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _check_feature_policy(policy: Mapping[str, Any]) -> set[str]:
    """Return the explicitly permitted deploy channel names from A12's policy JSON."""
    if policy.get("schema") != "synlab.view_channel_policy.v1":
        return set()
    deploy = ((policy.get("views") or {}).get("deploy") or {})
    channels = deploy.get("channels")
    if not isinstance(channels, list):
        return set()
    return {row["key"] for row in channels if isinstance(row, Mapping) and isinstance(row.get("key"), str)}


def audit_chain(document: Mapping[str, Any], root: str | Path) -> dict[str, Any]:
    """Audit one explicitly described lineage chain without mutating or scanning inputs."""
    root_path = Path(root)
    gaps: list[dict[str, str]] = []
    structural_problems: list[dict[str, str]] = []
    if document.get("schema") != INPUT_SCHEMA:
        _gap(gaps, "schema", "FAIL", f"expected {INPUT_SCHEMA!r}")
        structural_problems.append(gaps[-1])

    raw_refs = document.get("references")
    refs = raw_refs if isinstance(raw_refs, Mapping) else {}
    sources: dict[str, dict[str, Any]] = {}
    source_status: dict[str, dict[str, Any]] = {}
    for name, ref in refs.items():
        if not isinstance(name, str):
            continue
        loaded, status = _read_reference(root_path, ref)
        source_status[name] = status
        if loaded is not None:
            expected_schema = EXPECTED_SCHEMAS.get(name)
            if expected_schema and loaded.get("schema") != expected_schema:
                status["status"] = "SCHEMA_MISMATCH"
                status["reason"] = f"expected schema {expected_schema!r}, observed {loaded.get('schema')!r}"
            else:
                sources[name] = loaded
        if status["status"] != "HASH_VERIFIED_JSON_READ":
            _gap(gaps, f"references.{name}", "INCOMPLETE", str(status.get("reason")))
            structural_problems.append(gaps[-1])

    for component, ref_name in REQUIRED_REFERENCE_KEYS.items():
        if ref_name not in refs:
            _gap(gaps, f"references.{ref_name}", "UNKNOWN", f"no explicit source reference supplied for {component}")
            structural_problems.append(gaps[-1])

    chain_value = document.get("chain")
    chain = chain_value if isinstance(chain_value, Mapping) else {}
    parent_manifest = sources.get("parent_asset_manifest")
    job = sources.get("native_job")
    result = sources.get("native_result")
    export = sources.get("dataset_export_manifest")

    parent_id = chain.get("parent_asset_id")
    if not isinstance(parent_id, str) or not parent_id:
        _gap(gaps, "parent_asset.reference_id", "UNKNOWN", "parent asset identity is absent from the chain input")
        structural_problems.append(gaps[-1])
    if parent_manifest is None:
        _gap(gaps, "parent_asset.manifest", "UNKNOWN", "forge.asset.v1 manifest could not be hash-verified and read")
        structural_problems.append(gaps[-1])
    else:
        producer_asset_id = parent_manifest.get("asset_id")
        if isinstance(producer_asset_id, str) and producer_asset_id:
            if producer_asset_id != parent_id:
                _gap(gaps, "parent_asset.reference_id", "FAIL", "chain parent id does not match the producer's manifest.asset_id")
                structural_problems.append(gaps[-1])
        else:
            declared_manifest_hash = chain.get("parent_asset_manifest_sha256")
            actual_manifest_hash = (source_status.get("parent_asset_manifest") or {}).get("sha256")
            if not isinstance(declared_manifest_hash, str) or not declared_manifest_hash:
                _gap(gaps, "parent_asset.manifest_sha256", "UNKNOWN", "forge.asset.v1 has no producer asset_id; chain must identify this parent by its verified manifest SHA-256")
                structural_problems.append(gaps[-1])
            elif not isinstance(actual_manifest_hash, str) or declared_manifest_hash.lower() != actual_manifest_hash.lower():
                _gap(gaps, "parent_asset.manifest_sha256", "FAIL", "chain parent manifest digest does not match the hash-verified forge.asset.v1 reference")
                structural_problems.append(gaps[-1])
            elif parent_id not in {actual_manifest_hash, f"sha256:{actual_manifest_hash}"}:
                _gap(gaps, "parent_asset.reference_id", "FAIL", "without a producer asset_id, the chain reference_id must be the verified manifest SHA-256")
                structural_problems.append(gaps[-1])

        expected_units = {"length": "mm", "time": "s", "mass": "kg"}
        if parent_manifest.get("units") != expected_units:
            _gap(gaps, "parent_asset.units", "FAIL", "forge.asset.v1 units must be mm, seconds, and kg")
            structural_problems.append(gaps[-1])
        if parent_manifest.get("frame") != "right_handed_z_up":
            _gap(gaps, "parent_asset.frame", "FAIL", "forge.asset.v1 frame must be right_handed_z_up")
            structural_problems.append(gaps[-1])
        for section in ("geometry", "fields", "material", "ornament", "files", "provenance", "validation"):
            if not isinstance(parent_manifest.get(section), Mapping):
                _gap(gaps, f"parent_asset.{section}", "UNKNOWN", f"forge.asset.v1 manifest.{section} is not an object")
                structural_problems.append(gaps[-1])
        geometry = _object(parent_manifest.get("geometry"))
        fields = _object(parent_manifest.get("fields"))
        validation = _object(parent_manifest.get("validation"))
        provenance = _object(parent_manifest.get("provenance"))
        provenance_spec = _object(provenance.get("spec"))
        files = _object(parent_manifest.get("files"))
        package_paths = {
            "geometry.solid_step": geometry.get("solid_step"),
            "geometry.surface_npz": geometry.get("surface_npz"),
            "fields.surface_fields_npz": fields.get("surface_fields_npz"),
            "validation.report": validation.get("report"),
            "provenance.spec.mesh_lineage_npz": provenance_spec.get("mesh_lineage_npz"),
            "provenance.spec.face_semantics_report": provenance_spec.get("face_semantics_report"),
        }
        for field, relative in package_paths.items():
            if not isinstance(relative, str) or relative not in files:
                _gap(gaps, f"parent_asset.{field}", "INCOMPLETE", "forge.asset.v1 manifest reference is missing from its files hash table")
                structural_problems.append(gaps[-1])
        for relative, file_record in files.items():
            if not isinstance(file_record, Mapping) or not isinstance(file_record.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", file_record.get("sha256", "")) or isinstance(file_record.get("bytes"), bool) or not isinstance(file_record.get("bytes"), int) or file_record.get("bytes", -1) < 0:
                _gap(gaps, f"parent_asset.files.{relative}", "FAIL", "forge.asset.v1 file records need a 64-digit SHA-256 and nonnegative byte count")
                structural_problems.append(gaps[-1])
        step_record = files.get(geometry.get("solid_step")) if isinstance(geometry.get("solid_step"), str) else None
        step_hash = step_record.get("sha256") if isinstance(step_record, Mapping) else None
        if step_hash and provenance_spec.get("canonical_step_sha256") != step_hash:
            _gap(gaps, "parent_asset.provenance.spec.canonical_step_sha256", "FAIL", "VF provenance hash does not match its listed canonical STEP file")
            structural_problems.append(gaps[-1])

        parent_validation = _object(parent_manifest.get("validation"))
        parent_material = _object(parent_manifest.get("material"))
        if parent_validation.get("scope") != "geometry_only":
            _gap(gaps, "parent_asset.validation.scope", "UNKNOWN", "VF prototype manifest does not establish the required geometry-only scope")
        if not isinstance(parent_material.get("id"), str):
            _gap(gaps, "parent_asset.material.id", "UNKNOWN", "forge.asset.v1 material identity is missing")

    event_value = chain.get("event")
    event = event_value if isinstance(event_value, Mapping) else {}
    event_id = event.get("event_id")
    for field, value, reason in (
        ("event.event_id", event_id, "no event identifier connects the native run to fragments"),
        ("event.parent_asset_id", event.get("parent_asset_id"), "event does not explicitly name its parent asset"),
        ("event.native_job_id", event.get("native_job_id"), "event does not identify the executed PG job"),
        ("event.native_result_job_id", event.get("native_result_job_id"), "event does not identify the returned PG result"),
    ):
        if not isinstance(value, str) or not value:
            _gap(gaps, field, "UNKNOWN", reason)
            structural_problems.append(gaps[-1])
    if isinstance(event.get("parent_asset_id"), str) and event.get("parent_asset_id") != parent_id:
        _gap(gaps, "event.parent_asset_id", "FAIL", "event parent does not match the audited parent asset")
        structural_problems.append(gaps[-1])
    if job is None:
        _gap(gaps, "native_run.job", "UNKNOWN", "PG job reference is absent or invalid")
        structural_problems.append(gaps[-1])
    if result is None:
        _gap(gaps, "native_run.result", "UNKNOWN", "PG result reference is absent or invalid")
        structural_problems.append(gaps[-1])
    if job is not None and result is not None:
        job_id = job.get("job_id")
        result_job_id = result.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            _gap(gaps, "native_job.job_id", "UNKNOWN", "pgfrag.job.v1 job_id is absent")
            structural_problems.append(gaps[-1])
        if result_job_id != job_id:
            _gap(gaps, "native_result.job_id", "FAIL", "pgfrag.result.v1 job_id does not match the referenced job")
            structural_problems.append(gaps[-1])
        if event.get("native_job_id") and event.get("native_job_id") != job_id:
            _gap(gaps, "event.native_job_id", "FAIL", "event job id does not match pgfrag.job.v1 job_id")
            structural_problems.append(gaps[-1])
        if event.get("native_result_job_id") and event.get("native_result_job_id") != result_job_id:
            _gap(gaps, "event.native_result_job_id", "FAIL", "event result id does not match pgfrag.result.v1 job_id")
            structural_problems.append(gaps[-1])
        result_input = result.get("input") if isinstance(result.get("input"), Mapping) else {}
        job_ref_status = source_status.get("native_job") or {}
        if result_input.get("job_sha256") and job_ref_status.get("sha256") and result_input["job_sha256"].lower() != job_ref_status["sha256"].lower():
            _gap(gaps, "native_result.input.job_sha256", "FAIL", "result does not cite the hash-verified native job")
            structural_problems.append(gaps[-1])
        process = result.get("process") if isinstance(result.get("process"), Mapping) else {}
        solver = result.get("solver") if isinstance(result.get("solver"), Mapping) else {}
        if result.get("status") != "COMPLETED" or process.get("returncode") != 0 or not isinstance(solver.get("steps"), int) or solver.get("steps", 0) <= 0:
            _gap(gaps, "native_run.execution", "INCOMPLETE", "result lacks COMPLETED status, zero process return code, or nonzero solver steps")
            structural_problems.append(gaps[-1])
        initial = job.get("initial_condition") if isinstance(job.get("initial_condition"), Mapping) else {}
        if initial.get("kind") != "forge_asset_surface":
            _gap(gaps, "native_job.initial_condition", "UNKNOWN", f"PG run uses {initial.get('kind')!r}; it is not linked to this forge asset as a surface-derived initial condition")
            structural_problems.append(gaps[-1])

    fragments_value = chain.get("fragments")
    fragments = fragments_value if isinstance(fragments_value, list) else []
    fragment_ids: set[str] = set()
    if not fragments:
        _gap(gaps, "fragment_set.fragments", "UNKNOWN", "no row-level fragment set is supplied; PG graph components or A12 aggregate fragment counts are not fragment lineage")
        structural_problems.append(gaps[-1])
    for index, fragment in enumerate(fragments):
        field = f"fragment_set.fragments[{index}]"
        if not isinstance(fragment, Mapping):
            _gap(gaps, field, "FAIL", "fragment row must be an object and is retained as an invalid row")
            structural_problems.append(gaps[-1])
            continue
        fid = fragment.get("fragment_id")
        if not isinstance(fid, str) or not fid:
            _gap(gaps, f"{field}.fragment_id", "UNKNOWN", "fragment has no stable identifier")
            structural_problems.append(gaps[-1])
            continue
        if fid in fragment_ids:
            _gap(gaps, f"{field}.fragment_id", "FAIL", f"duplicate fragment id {fid!r}")
            structural_problems.append(gaps[-1])
        fragment_ids.add(fid)
        if fragment.get("event_id") != event_id:
            _gap(gaps, f"{field}.event_id", "FAIL", "orphan fragment: fragment event_id does not match the declared event")
            structural_problems.append(gaps[-1])
        if fragment.get("parent_asset_id") != parent_id:
            _gap(gaps, f"{field}.parent_asset_id", "FAIL", "orphan fragment: fragment does not descend from the audited parent asset")
            structural_problems.append(gaps[-1])
        parent_material_id = _object((parent_manifest or {}).get("material")).get("id")
        if fragment.get("material_id") != parent_material_id:
            _gap(gaps, f"{field}.material_id", "FAIL", "fragment material lineage does not match forge.asset.v1 material.id")
            structural_problems.append(gaps[-1])
        # Deliberately no fragment size/count threshold: every supplied row stays audited.
    if fragments and isinstance(event.get("fragment_ids"), list):
        declared_ids = set(event["fragment_ids"])
        if declared_ids != fragment_ids:
            _gap(gaps, "event.fragment_ids", "FAIL", "event fragment roster differs from the supplied fragment rows")
            structural_problems.append(gaps[-1])

    surfaces_value = chain.get("crack_surfaces")
    surfaces = surfaces_value if isinstance(surfaces_value, list) else []
    surface_ids: set[str] = set()
    pairs: dict[str, list[Mapping[str, Any]]] = {}
    if not surfaces:
        _gap(gaps, "crack_surfaces", "UNKNOWN", "no event-produced paired crack-surface rows are supplied; facets or graph components cannot substitute")
        structural_problems.append(gaps[-1])
    for index, surface in enumerate(surfaces):
        field = f"crack_surfaces[{index}]"
        if not isinstance(surface, Mapping):
            _gap(gaps, field, "FAIL", "surface row must be an object and is retained as an invalid row")
            structural_problems.append(gaps[-1])
            continue
        sid = surface.get("surface_id")
        pair_id = surface.get("interface_pair_id")
        side = surface.get("side")
        if not isinstance(sid, str) or not sid:
            _gap(gaps, f"{field}.surface_id", "UNKNOWN", "surface has no stable identifier")
            structural_problems.append(gaps[-1])
        elif sid in surface_ids:
            _gap(gaps, f"{field}.surface_id", "FAIL", f"duplicate surface id {sid!r}")
            structural_problems.append(gaps[-1])
        else:
            surface_ids.add(sid)
        if not isinstance(pair_id, str) or not pair_id or side not in {"A", "B"}:
            _gap(gaps, f"{field}.interface_pair_id", "FAIL", "surface must name an interface_pair_id and side A or B")
            structural_problems.append(gaps[-1])
        else:
            pairs.setdefault(pair_id, []).append(surface)
        area = surface.get("area_mm2")
        if not _valid_number(area) or float(area) <= 0:
            _gap(gaps, f"{field}.area_mm2", "FAIL", "paired crack surface must report a finite positive area in mm²")
            structural_problems.append(gaps[-1])
        if surface.get("event_id") != event_id:
            _gap(gaps, f"{field}.event_id", "FAIL", "crack surface is not linked to the declared event")
            structural_problems.append(gaps[-1])
        if surface.get("parent_asset_id") != parent_id:
            _gap(gaps, f"{field}.parent_asset_id", "FAIL", "crack surface is not linked to the parent asset")
            structural_problems.append(gaps[-1])
        if surface.get("fragment_id") not in fragment_ids:
            _gap(gaps, f"{field}.fragment_id", "FAIL", "crack surface references a missing or orphan fragment")
            structural_problems.append(gaps[-1])
        material_id = _object((parent_manifest or {}).get("material")).get("id")
        if surface.get("material_id") != material_id:
            _gap(gaps, f"{field}.material_id", "FAIL", "crack-surface material lineage does not match the parent asset")
            structural_problems.append(gaps[-1])
    for pair_id, rows in pairs.items():
        sides = [row.get("side") for row in rows]
        if sorted(sides) != ["A", "B"]:
            _gap(gaps, f"crack_surfaces[{pair_id}]", "INCOMPLETE", "paired interface needs exactly one A side and one B side")
            structural_problems.append(gaps[-1])

    material = chain.get("material") if isinstance(chain.get("material"), Mapping) else {}
    parent_material_id = _object((parent_manifest or {}).get("material")).get("id")
    if material.get("material_id") != parent_material_id:
        _gap(gaps, "material.material_id", "FAIL", "material lineage must identify the parent asset's declared material")
        structural_problems.append(gaps[-1])
    calibration_status = material.get("calibration_status")
    if not isinstance(calibration_status, str) or calibration_status.upper() in {"", "UNKNOWN", "UNVALIDATED", "UNVALIDATED_PROTOTYPE", "PENDING"}:
        _gap(gaps, "material.calibration_status", "UNKNOWN", "no measured/provenanced material calibration status is supplied")
        structural_problems.append(gaps[-1])

    relations_value = chain.get("historical_relations")
    relations = relations_value if isinstance(relations_value, list) else []
    relation_counts: dict[str, int] = {}
    if not relations:
        _gap(gaps, "historical_relations", "UNKNOWN", "no row-level historical_R2/R1/R0 evidence is linked to the audited fragment lineage")
        structural_problems.append(gaps[-1])
    for index, relation in enumerate(relations):
        field = f"historical_relations[{index}]"
        if not isinstance(relation, Mapping):
            _gap(gaps, field, "FAIL", "relation row must be an object")
            structural_problems.append(gaps[-1])
            continue
        label = relation.get("historical_relation")
        if label not in {"R0", "R1", "R2", "UNKNOWN"}:
            _gap(gaps, f"{field}.historical_relation", "UNKNOWN", f"unrecognized historical relation value {label!r}; it is not coerced to R0")
            structural_problems.append(gaps[-1])
            continue
        relation_counts[label] = relation_counts.get(label, 0) + 1
        if label == "UNKNOWN":
            _gap(gaps, f"{field}.historical_relation", "UNKNOWN", "historical relation is explicitly unresolved")
            structural_problems.append(gaps[-1])
        query = relation.get("query_fragment_id")
        candidate = relation.get("candidate_fragment_id")
        if query not in fragment_ids:
            _gap(gaps, f"{field}.query_fragment_id", "FAIL", "historical relation query is not in the audited fragment set")
            structural_problems.append(gaps[-1])
        if not isinstance(candidate, str) or not candidate or candidate == query:
            _gap(gaps, f"{field}.candidate_fragment_id", "FAIL", "historical relation needs a distinct, identified candidate")
            structural_problems.append(gaps[-1])
        if label == "R2":
            pair_id = relation.get("interface_pair_id")
            if pair_id not in pairs:
                _gap(gaps, f"{field}.interface_pair_id", "INCOMPLETE", "R2 row is not linked to a positive-area interface pair")
                structural_problems.append(gaps[-1])
            else:
                pair_fragments = {row.get("fragment_id") for row in pairs[pair_id]}
                if {query, candidate} != pair_fragments:
                    _gap(gaps, f"{field}.interface_pair_id", "FAIL", "R2 endpoints do not match the two fragments carrying its paired crack surfaces")
                    structural_problems.append(gaps[-1])
        if relation.get("event_id") != event_id:
            _gap(gaps, f"{field}.event_id", "FAIL", "historical relation row is not linked to the declared event/source lineage")
            structural_problems.append(gaps[-1])

    degradation = chain.get("degradation") if isinstance(chain.get("degradation"), Mapping) else {}
    if not isinstance(degradation.get("recipe_id"), str) or not degradation.get("recipe_id"):
        _gap(gaps, "degradation.recipe_id", "UNKNOWN", "no degradation recipe identity is supplied")
        structural_problems.append(gaps[-1])
    quantities = degradation.get("actual_quantities")
    if not isinstance(quantities, list) or not quantities:
        _gap(gaps, "degradation.actual_quantities", "UNKNOWN", "no actual measured degradation quantity is supplied")
        structural_problems.append(gaps[-1])
    else:
        for index, item in enumerate(quantities):
            field = f"degradation.actual_quantities[{index}]"
            if not isinstance(item, Mapping) or not isinstance(item.get("quantity"), str) or not item.get("quantity") or not _valid_number(item.get("value")) or not isinstance(item.get("unit"), str) or not item.get("unit"):
                _gap(gaps, field, "FAIL", "each degradation measurement must retain quantity, finite value, and unit")
                structural_problems.append(gaps[-1])
            if isinstance(item, Mapping) and item.get("fragment_id") not in fragment_ids:
                _gap(gaps, f"{field}.fragment_id", "FAIL", "degradation measurement references a missing fragment")
                structural_problems.append(gaps[-1])

    observations_value = chain.get("observations")
    observations = observations_value if isinstance(observations_value, list) else []
    if not observations:
        _gap(gaps, "observations", "UNKNOWN", "no observation rows are linked to the audited fragments")
        structural_problems.append(gaps[-1])
    observation_capture_ids: set[str] = set()
    for index, observation in enumerate(observations):
        field = f"observations[{index}]"
        if not isinstance(observation, Mapping):
            _gap(gaps, field, "FAIL", "observation row must be an object")
            structural_problems.append(gaps[-1])
            continue
        if observation.get("fragment_id") not in fragment_ids:
            _gap(gaps, f"{field}.fragment_id", "FAIL", "observation references a missing fragment")
            structural_problems.append(gaps[-1])
        capture_id = observation.get("capture_id")
        if not isinstance(capture_id, str) or not capture_id:
            _gap(gaps, f"{field}.capture_id", "UNKNOWN", "observation has no capture_id")
            structural_problems.append(gaps[-1])
        else:
            observation_capture_ids.add(capture_id)
        if not isinstance(observation.get("observation_id"), str) or not observation.get("observation_id"):
            _gap(gaps, f"{field}.observation_id", "UNKNOWN", "observation has no stable observation_id")
            structural_problems.append(gaps[-1])
    capture_rows = chain.get("capture_records")
    captures = capture_rows if isinstance(capture_rows, list) else []
    captures_by_id = {row.get("capture_id"): row for row in captures if isinstance(row, Mapping) and isinstance(row.get("capture_id"), str)}
    if not captures:
        _gap(gaps, "capture_records", "UNKNOWN", "no capture ledger rows or raw-capture references are supplied")
        structural_problems.append(gaps[-1])
    for capture_id in sorted(observation_capture_ids):
        if capture_id not in captures_by_id:
            _gap(gaps, f"capture_records[{capture_id}]", "INCOMPLETE", "observation capture_id has no matching capture ledger row")
            structural_problems.append(gaps[-1])
    for capture_id, capture in captures_by_id.items():
        if capture.get("fragment_id") not in fragment_ids:
            _gap(gaps, f"capture_records[{capture_id}].fragment_id", "FAIL", "capture references a missing fragment")
            structural_problems.append(gaps[-1])
        for field in ("device_id", "calibration_id", "timestamp"):
            if not isinstance(capture.get(field), str) or not capture.get(field):
                _gap(gaps, f"capture_records[{capture_id}].{field}", "UNKNOWN", f"capture ledger lacks {field}")
                structural_problems.append(gaps[-1])
        capture_hash = capture.get("sha256")
        if not isinstance(capture_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", capture_hash):
            _gap(gaps, f"capture_records[{capture_id}].sha256", "UNKNOWN", "capture ledger lacks a 64-digit raw-file SHA-256")
            structural_problems.append(gaps[-1])

    features = chain.get("features") if isinstance(chain.get("features"), Mapping) else {}
    feature_fields = features.get("fields")
    if not isinstance(feature_fields, list) or not feature_fields:
        _gap(gaps, "features.fields", "UNKNOWN", "actual feature-field whitelist is not enumerated")
        structural_problems.append(gaps[-1])
        feature_names: set[str] = set()
    else:
        feature_names = {field for field in feature_fields if isinstance(field, str)}
        if len(feature_names) != len(feature_fields):
            _gap(gaps, "features.fields", "FAIL", "feature field list contains non-string or duplicate entries")
            structural_problems.append(gaps[-1])
        policy_doc = sources.get("feature_policy")
        deploy_channels = _check_feature_policy(policy_doc or {})
        allowed = FEATURE_BUNDLE_FIELDS | deploy_channels
        for field in sorted(feature_names):
            if field in FORBIDDEN_FEATURE_FIELDS:
                _gap(gaps, f"features.fields.{field}", "FAIL", "A12 explicitly forbids this field in a feature bundle/model forward pass")
                structural_problems.append(gaps[-1])
            elif field not in allowed:
                _gap(gaps, f"features.fields.{field}", "FAIL", "field is outside synlab.training.adapter.FeatureBundle and the declared deploy channel policy")
                structural_problems.append(gaps[-1])
    if features.get("schema") != "a12.obs.v1":
        _gap(gaps, "features.schema", "UNKNOWN", "feature payload does not declare A12 a12.obs.v1")
        structural_problems.append(gaps[-1])
    if features.get("asset_role") != "feature_bundle":
        _gap(gaps, "features.asset_role", "FAIL", "A12 data contract requires a separate feature_bundle asset")
        structural_problems.append(gaps[-1])

    labels = chain.get("labels") if isinstance(chain.get("labels"), Mapping) else {}
    label_fields = labels.get("fields")
    if not isinstance(label_fields, list) or not label_fields:
        _gap(gaps, "labels.fields", "UNKNOWN", "label fields are not enumerated separately from model inputs")
        structural_problems.append(gaps[-1])
        label_names: set[str] = set()
    else:
        label_names = {field for field in label_fields if isinstance(field, str)}
    if labels.get("asset_role") is None or labels.get("separate_asset") is None:
        _gap(gaps, "labels.separate_asset", "UNKNOWN", "package evidence does not state whether labels are isolated in a label_bundle asset")
        structural_problems.append(gaps[-1])
    elif labels.get("asset_role") != "label_bundle" or labels.get("separate_asset") is not True:
        _gap(gaps, "labels.separate_asset", "FAIL", "A12 labels must live in a separate label_bundle asset")
        structural_problems.append(gaps[-1])
    overlap = feature_names & label_names
    for field in sorted(overlap):
        _gap(gaps, f"labels.fields.{field}", "FAIL", "label field overlaps the model-input feature list")
        structural_problems.append(gaps[-1])

    gates_value = chain.get("gates")
    gates_input = gates_value if isinstance(gates_value, Mapping) else {}
    gate_report: dict[str, Any] = {}
    for gate in GATES:
        row = gates_input.get(gate)
        if not isinstance(row, Mapping):
            _gap(gaps, f"gates.{gate}", "UNKNOWN", "gate claim and its evidence reference are absent")
            structural_problems.append(gaps[-1])
            gate_report[gate] = {"declared_status": "UNKNOWN", "audit_status": "UNKNOWN", "reason": "no gate claim supplied"}
            continue
        declared = row.get("status", "UNKNOWN")
        ref_name = row.get("evidence_ref")
        ref_ok = isinstance(ref_name, str) and source_status.get(ref_name, {}).get("status") == "HASH_VERIFIED_JSON_READ"
        if not ref_ok:
            _gap(gaps, f"gates.{gate}.evidence_ref", "UNKNOWN", "gate evidence reference is missing, unresolved, or hash-invalid")
            structural_problems.append(gaps[-1])
        if declared == "PASS":
            audit_status = "CLAIMED_PASS_UNVERIFIED"
            reason = "PASS is retained as a producer claim; this structural auditor cannot validate scientific truth or gate acceptance"
        elif declared in {"FAIL", "PENDING", "UNKNOWN"}:
            audit_status = declared
            reason = "gate remains unaccepted; declared status is not promoted by this audit"
        else:
            audit_status = "UNKNOWN"
            reason = f"unrecognized gate status {declared!r}"
            _gap(gaps, f"gates.{gate}.status", "FAIL", reason)
            structural_problems.append(gaps[-1])
        gate_report[gate] = {
            "declared_status": declared,
            "audit_status": audit_status,
            "evidence_ref": ref_name if isinstance(ref_name, str) else None,
            "evidence_reference_status": "HASH_VERIFIED_JSON_READ" if ref_ok else "UNKNOWN",
            "reason": reason,
        }

    # Read aggregate A12 metadata as context only. Counts never fill row-level lineage.
    producer_context: dict[str, Any] = {}
    if export is not None:
        counts = export.get("counts") if isinstance(export.get("counts"), Mapping) else {}
        assets = export.get("assets") if isinstance(export.get("assets"), Mapping) else {}
        by_role = assets.get("by_role") if isinstance(assets.get("by_role"), Mapping) else {}
        closure = export.get("reference_closure") if isinstance(export.get("reference_closure"), Mapping) else {}
        degrade_counts = export.get("degrade_diversity", {}).get("counts", {}) if isinstance(export.get("degrade_diversity"), Mapping) else {}
        degradation_index = sources.get("degradation_index", {})
        degradation_rows = degradation_index.get("rows") if isinstance(degradation_index.get("rows"), list) else []
        degradation_sources = degradation_index.get("sources") if isinstance(degradation_index.get("sources"), list) else []
        separation = export.get("separation", {}) if isinstance(export.get("separation"), Mapping) else {}
        answer_scan = separation.get("answer_field_scan", {}) if isinstance(separation.get("answer_field_scan"), Mapping) else {}
        producer_context = {
            "a12_release_id": export.get("release_id"),
            "a12_release_scope": export.get("release_scope"),
            "a12_release_profile": export.get("release_profile"),
            "a12_reference_closure_ok": closure.get("ok"),
            "a12_reference_closure_problem_count": len(closure.get("problems", [])) if isinstance(closure.get("problems"), list) else None,
            "a12_declared_feature_bundle_assets": by_role.get("feature_bundle"),
            "a12_declared_label_bundle_assets": by_role.get("label_bundle"),
            "a12_relation_kind_counts": counts.get("relation_kinds"),
            "a12_relation_counts_are_aggregate_only": True,
            "a12_degrade_actual_counts": degrade_counts,
            "a12_degrade_aggregate_variants": counts.get("degrade_materialised_variants"),
            "a12_degradation_index_row_count": len(degradation_rows),
            "a12_degradation_index_source_count": len(degradation_sources),
            "a12_observation_count": counts.get("observations"),
            "a12_answer_field_scan_hit_count": len(answer_scan.get("hits", [])) if isinstance(answer_scan.get("hits"), list) else None,
            "a12_answer_field_scan_key_count": answer_scan.get("keys_scanned"),
        }
        if closure.get("ok") is False:
            _gap(gaps, "dataset_export_manifest.reference_closure", "INCOMPLETE", "A12 export manifest declares reference_closure.ok=false; its aggregate package is not a closed lineage chain")
            structural_problems.append(gaps[-1])
        if isinstance(degrade_counts, Mapping) and degrade_counts and (degrade_counts.get("degrade_sources", 0) == 0 or degrade_counts.get("degrade_variants", 0) == 0):
            _gap(gaps, "degradation.actual_measurements", "UNKNOWN", "A12 degradation diversity metadata reports zero committed sources/variants; aggregate materialised counts do not supply row-level recipe measurements")
            structural_problems.append(gaps[-1])
        if "degradation_index" in sources and not degradation_rows and not degradation_sources:
            _gap(gaps, "degradation_index.rows", "UNKNOWN", "explicit A12 degrade/index.json reference has empty rows and sources")
            structural_problems.append(gaps[-1])
        if isinstance(counts.get("relation_kinds"), Mapping) and any(counts["relation_kinds"].get(key, 0) for key in ("R0", "R1", "R2")):
            _gap(gaps, "historical_relations.provenance", "UNKNOWN", "A12 relation counts are synthetic aggregates and are not row-level historical_R2/R1/R0 lineage from this PG event")
            structural_problems.append(gaps[-1])

    # Gate strings and output PASS fields never authorize physics or training.
    complete = not structural_problems
    ref_complete = all(source_status.get(ref_name, {}).get("status") == "HASH_VERIFIED_JSON_READ" for ref_name in REQUIRED_REFERENCE_KEYS.values())
    if complete and ref_complete:
        overall = "STRUCTURAL_PASS"
    else:
        overall = "INCOMPLETE"
    gap_status = "COMPLETE" if not gaps else "INCOMPLETE"
    return {
        "schema": REPORT_SCHEMA,
        "status": overall,
        "structural_completeness": {
            "status": "COMPLETE" if complete else "INCOMPLETE",
            "blocking_issue_count": len(structural_problems),
            "fragment_row_count_audited": len(fragments),
            "surface_row_count_audited": len(surfaces),
            "surface_pair_count_audited": len(pairs),
            "relation_row_count_audited": len(relations),
            "relation_labels_seen": relation_counts,
        },
        "evidence_reference_completeness": {
            "status": "COMPLETE" if ref_complete else "INCOMPLETE",
            "status_by_reference": source_status,
            "max_reference_bytes": MAX_REFERENCE_BYTES,
            "only_explicit_json_references_read": True,
            "package_payloads_scanned": False,
        },
        "science_qualification": {
            "status": "SCIENCE_UNVERIFIED",
            "physics_qualified": False,
            "pretrain_qualified": False,
            "reason": "Hash and structure checks cannot validate fracture physics, material calibration, historical adjacency, capture realism, or training safety. Producer PASS strings remain claims only.",
            "gate_statuses": gate_report,
        },
        "producer_context": producer_context,
        "gaps": gaps,
    }


def _read_cli_json(root: Path, raw_path: str) -> dict[str, Any]:
    resolved, error = _safe_relative_path(root, raw_path, allow_absolute=True)
    if error or resolved is None:
        raise ValueError(f"unsafe or missing input path: {error}")
    if resolved.suffix.lower() != ".json":
        raise ValueError("input must be an explicitly named JSON metadata file")
    if resolved.stat().st_size > MAX_REFERENCE_BYTES:
        raise ValueError(f"input JSON exceeds {MAX_REFERENCE_BYTES} byte limit")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read input JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("input JSON root must be an object")
    return value


def _write_report(root: Path, raw_path: str, report: Mapping[str, Any]) -> Path:
    resolved, error = _safe_relative_path(root, raw_path)
    if error:
        # Output may not exist yet, so validate existing parents without requiring the leaf.
        pure = PurePosixPath(raw_path)
        if "\\" in raw_path or ":" in raw_path or pure.is_absolute() or any(p in {"", ".", ".."} for p in pure.parts):
            raise ValueError(f"unsafe output path: {error}")
        root_real = root.resolve(strict=True)
        target = root_real.joinpath(*pure.parts)
        parent = target.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            parent.resolve(strict=True).relative_to(root_real)
        except (OSError, ValueError) as exc:
            raise ValueError(f"unsafe output parent: {exc}") from exc
        cursor = root_real
        for part in pure.parts[:-1]:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("symlink components are not allowed in output paths")
        resolved = target
    if resolved is None:
        raise ValueError("output path is invalid")
    if resolved.exists():
        raise FileExistsError(f"refusing to overwrite existing audit output: {raw_path}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only RelicWeave evidence-chain audit")
    parser.add_argument("--root", required=True, help="workspace root for root-relative source references")
    parser.add_argument("--input", required=True, help="root-relative audit input JSON")
    parser.add_argument("--output", required=True, help="new root-relative report JSON path")
    parser.add_argument("--fail-on-incomplete", action="store_true", help="return exit code 2 when the audit reports gaps")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve(strict=True)
    try:
        document = _read_cli_json(root, args.input)
        report = audit_chain(document, root)
        output = _write_report(root, args.output, report)
    except (OSError, ValueError, FileExistsError) as exc:
        print(f"forge-chain-audit: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": report["status"],
        "science": report["science_qualification"]["status"],
        "physics_qualified": report["science_qualification"]["physics_qualified"],
        "pretrain_qualified": report["science_qualification"]["pretrain_qualified"],
        "gap_count": len(report["gaps"]),
        "output": str(output),
    }, ensure_ascii=False))
    return 2 if args.fail_on_incomplete and report["status"] != "STRUCTURAL_PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
