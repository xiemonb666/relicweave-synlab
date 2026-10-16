"""Release gate evaluation (plan 30.18).

Gates are decided from *real evidence present in the store*: a gate is PASS only when the
corresponding audit artefact exists and reports success.  Absent evidence is PENDING, and
a PENDING REQUIRED gate blocks the release profile.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..errors import ErrorCode, SynLabError
from ..roles import (
    ROLE_CLEAN_TRUTH,
    ROLE_COVERAGE,
    ROLE_FEATURE_BUNDLE,
    ROLE_FRAGMENT_MESH,
    ROLE_LABEL_BUNDLE,
    ROLE_MOTHER_MESH,
    ROLE_OBS_RESULT,
    ROLE_OPERATOR_AUDIT,
    ROLE_PATTERN_AUDIT,
    ROLE_POOL,
    ROLE_QA_REPORT,
    ROLE_RUN_SPEC,
)
from ..storage.release import PROFILE_GATES
from ..storage.store import QA_PASS, AssetStore


def _reports_dir(store: AssetStore) -> Path:
    path = store.root / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_dirs(store: AssetStore, extra: Sequence[str | Path] | None = None) -> list[Path]:
    """Report directories searched for gate evidence, most specific first.

    A closed-loop release is often frozen in a *new* store while the operator/pattern/registry
    audits live in the long-lived evidence store.  Rather than copying those reports around (or
    quietly inventing them), extra roots can be named explicitly and every gate records which
    file it actually read.
    """
    dirs = [_reports_dir(store)]
    for root in extra or ():
        path = Path(root)
        if path.name != "reports":
            path = path / "reports"
        if path not in dirs:
            dirs.append(path)
    return dirs


def load_report(store: AssetStore, name: str,
                extra_dirs: Sequence[str | Path] | None = None) -> dict[str, Any] | None:
    """Load ``<name>.json`` from the store's report directory, then from any extra root."""
    return load_report_from(reports_dirs(store, extra_dirs), name)[0]


def load_report_from(dirs: Sequence[Path], name: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(report, path)`` for the first directory that carries ``<name>.json``."""
    for directory in dirs:
        path = Path(directory) / f"{name}.json"
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8")), str(path)
        except (OSError, ValueError):
            return None, f"{path} (unreadable)"
    return None, None


def acceptance_item(summary: Mapping[str, Any] | None, acceptance_id: str) -> dict[str, Any]:
    """Read one A-item out of an ``acceptance_summary.json`` payload.

    ``synlab.qc.acceptance.run_acceptance`` nests every item under ``items`` (the top-level
    document carries ``counts``/``registry``/``summary_hash``).  Reading ``summary[acceptance_id]``
    therefore never matched, which silently turned every acceptance-backed gate into PENDING even
    when the item was recorded as PASS.  Both shapes are accepted here so a gate reads the real
    item instead of a key that does not exist.
    """
    if not isinstance(summary, Mapping):
        return {}
    items = summary.get("items")
    if isinstance(items, Mapping) and isinstance(items.get(acceptance_id), Mapping):
        return dict(items[acceptance_id])
    direct = summary.get(acceptance_id)
    return dict(direct) if isinstance(direct, Mapping) else {}


def evaluate_gates(store: AssetStore, run_id: str, protocol_path: str | None = None, *,
                   evidence_dirs: Sequence[str | Path] | None = None
                   ) -> tuple[dict[str, str], list[str], str]:
    """Return (gates, asset_ids, requested_profile) for a run.

    ``evidence_dirs`` names additional report roots (for example the long-lived
    ``data/a12`` evidence store) that a gate may read from.  A gate is PASS only when the
    report it needs exists *and* reports success; a missing report stays PENDING.
    """
    try:
        run = store.get_run(run_id)
    except SynLabError as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, exc.message, stage="qc.gates") from exc
    profile = (run.get("profile") or "SANDBOX_CORE").upper()
    assets = [a for a in store.list_assets(limit=100000)
              if (a.meta or {}).get("run_id") == run_id]
    roles: dict[str, list[Any]] = {}
    for asset in assets:
        roles.setdefault(asset.role, []).append(asset)

    dirs = reports_dirs(store, evidence_dirs)
    evidence: dict[str, str] = {}
    values: dict[str, Any] = {}

    def report(name: str) -> dict[str, Any]:
        payload, path = load_report_from(dirs, name)
        if path:
            evidence[name] = path
            values[name] = payload
        return payload or {}

    audit, audit_path = load_report_from(dirs, f"audit_{run_id}")
    if audit_path:
        evidence[f"audit_{run_id}"] = audit_path
    audit = audit or {}
    operator_audit = report("operator_audit")
    pattern_audit = report("pattern_audit")
    acceptance = report("acceptance_summary")

    def has_qa(role: str, minimum: int = 1) -> bool:
        return len([a for a in roles.get(role, []) if a.qa_status == QA_PASS]) >= minimum

    def audit_status(name: str) -> str:
        if name in audit.get("problems", []):
            return "FAIL"
        return "PASS" if audit else "PENDING"

    gates: dict[str, str] = {}
    # ``fixture_contract``: the reuse/fixture manifest.  It is repository-level evidence; the
    # gate is PASS when a readable manifest is present either in the repository or staged into
    # one of the searched report directories (the staging step records source + hash).
    repo_manifest = Path("docs/a12/reuse_manifest.json")
    reuse_payload, reuse_evidence = load_report_from(dirs, "reuse_manifest")
    if reuse_evidence:
        evidence["reuse_manifest"] = reuse_evidence
    elif repo_manifest.exists():
        evidence["reuse_manifest"] = str(repo_manifest)
    gates["fixture_contract"] = "PASS" if (reuse_payload is not None
                                           or repo_manifest.exists()) else "PENDING"
    gates["coordinate_contract"] = "PASS" if acceptance_item(
        acceptance, "A02").get("status") == "PASS" else "PENDING"
    gates["source_map"] = "PASS" if has_qa(ROLE_FRAGMENT_MESH) else "PENDING"
    gates["readonly_commit"] = "PASS" if audit.get("store_health", {}).get("ok") else "PENDING"
    gates["fracture_operator_runs"] = "PASS" if has_qa(ROLE_CLEAN_TRUTH) else "PENDING"
    gates["observation_operator_runs"] = "PASS" if has_qa(ROLE_OBS_RESULT) else "PENDING"
    gates["train_dev_lineage"] = "PASS" if audit.get("lineage_splits") and all(
        split in {s for splits in audit["lineage_splits"].values() for s in splits}
        for split in ("train", "dev")
    ) else "PENDING"
    gates["operators_used_pass"] = "PASS" if operator_audit.get("ok") else "PENDING"
    gates["legal_inputs"] = "PASS" if (has_qa(ROLE_FEATURE_BUNDLE) and has_qa(ROLE_LABEL_BUNDLE)
                                       and audit.get("ok")) else "PENDING"
    gates["relations_complete"] = "PASS" if has_qa(ROLE_POOL) else "PENDING"
    recovery = report("recovery_probe")
    gates["read_recovery"] = "PASS" if audit.get("store_health", {}).get("ok") and (
        recovery.get("ok")) else "PENDING"
    gates["leakage_audit"] = "PASS" if acceptance_item(
        acceptance, "A32").get("status") == "PASS" else "PENDING"

    coverage = report("coverage")
    gates["coverage_24_vessels"] = "PASS" if len(coverage.get("vessels", [])) >= 24 else "PENDING"
    gates["coverage_12_materials"] = "PASS" if len(coverage.get("materials", [])) >= 12 else "PENDING"
    gates["coverage_4_layers"] = "PASS" if len(coverage.get("layer_combos", [])) >= 4 else "PENDING"
    gates["coverage_16_patterns"] = "PASS" if len(coverage.get("patterns", [])) >= 16 else "PENDING"
    gates["coverage_4_backends"] = "PASS" if len(coverage.get("fracture_backends", [])) >= 4 else "PENDING"
    gates["coverage_31_axes"] = "PASS" if len(coverage.get("axes", [])) >= 31 else "PENDING"
    gates["mvs_subset_real_run"] = "PASS" if report("mvs_subset").get("ok") else "PENDING"
    gates["core_ui_api"] = "PASS" if report("api_ui_evidence").get("ok") else "PENDING"
    gates["l2_qualification"] = "PASS" if report("l2_scale").get("ok") else "PENDING"

    for name in ("accepted_nested_10k", "accepted_nested_50k", "accepted_nested_100k"):
        target = int(name.rsplit("_", 1)[-1].rstrip("k")) * 1000
        gates[name] = "PASS" if report("scale_report").get("accepted_max", 0) >= target else "PENDING"
    gates["references_loadable"] = "PASS" if audit.get("closure", {}).get("ok") else "PENDING"
    gates["loader_index_runnable"] = "PASS" if report("loader_probe").get("ok") else "PENDING"
    gates["resource_profile"] = "PASS" if report("resource_profile").get("ok") else "PENDING"

    for name in ("real_capture_dataset", "phone_rgb_mvs", "scale_source", "mask_source",
                 "capture_profile", "proxy_calibration"):
        gates[name] = "PENDING"  # no real capture data on this host
    research = report("research_evidence")
    for name in ("frozen_protocol", "training_runs", "risk_calibration", "confirmation_complete"):
        gates[name] = "PASS" if research.get(name) == "PASS" else "PENDING"

    if profile not in PROFILE_GATES:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown release profile {profile}", stage="qc.gates")
    asset_ids = [a.asset_id for a in assets if a.qa_status == QA_PASS]
    return gates, asset_ids, profile


def gate_evidence(store: AssetStore, run_id: str,
                  evidence_dirs: Sequence[str | Path] | None = None) -> dict[str, dict[str, Any]]:
    """The report files the gates actually read, with a hash and a shallow metric digest.

    Every entry is ``{"path", "hash", "metrics"}``: the path is the file the gate read, the
    hash makes it auditable, and the metrics are the *scalar* values of that report (nested
    structures and non-finite numbers are dropped, because they cannot be canonicalised and
    they are not evidence by themselves).
    """
    from ..canonical import hash_file

    dirs = reports_dirs(store, evidence_dirs)
    out: dict[str, dict[str, Any]] = {}
    for name in ("audit", "audit_" + run_id, "operator_audit", "pattern_audit",
                 "acceptance_summary", "coverage", "recovery_probe", "loader_probe",
                 "resource_profile", "scale_report", "mvs_subset", "api_ui_evidence",
                 "l2_scale", "research_evidence", "reuse_manifest"):
        payload, path = load_report_from(dirs, name)
        if not path:
            continue
        entry: dict[str, Any] = {"path": path}
        if payload is not None:
            entry["hash"] = hash_file(path)
            entry["metrics"] = _scalar_digest(payload)
        else:
            entry["unreadable"] = True
        out[name] = entry
    return out


def _scalar_digest(payload: Any, *, depth: int = 2, limit: int = 40) -> dict[str, Any]:
    """Flatten finite scalars out of a report (bounded depth, NaN/Inf dropped)."""
    import math

    out: dict[str, Any] = {}

    def walk(node: Any, prefix: str, level: int) -> None:
        if len(out) >= limit:
            return
        if isinstance(node, dict) and level < depth:
            for key, value in sorted(node.items(), key=lambda kv: str(kv[0])):
                walk(value, f"{prefix}{key}.", level + 1)
            return
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, str)):
            out[prefix.rstrip(".")] = node
            return
        if isinstance(node, float):
            if math.isfinite(node):
                out[prefix.rstrip(".")] = node
            return

    walk(payload, "", 0)
    return out
