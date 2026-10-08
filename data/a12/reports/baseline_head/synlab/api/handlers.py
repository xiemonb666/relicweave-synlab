"""Worker-side job execution.

Every handler either produces real, hash-recorded content or raises a structured
``SynLabError``.  There is no branch that writes placeholder geometry, a synthetic metric
or a zero-filled report.

Stages implemented here directly (``implemented_by="synlab.api"``):

``freeze_spec``
    verifies the input asset references and their payload hashes, then commits an immutable
    ``run_spec`` asset holding the canonical spec + input hashes + registry/code fingerprints.
``audit``
    real closure/hash verification, real coverage matrix, real gate evaluation.  A gate this
    build cannot prove is reported ``PENDING`` with its reason — never ``PASS``.
``export``
    materialises a read-only export bundle from a frozen release and records its hash.
``display_lod``
    derives a metre/Y-up GLB **once** from an authoritative mm mesh asset.

All other stages require a parallel module; when it is absent the job fails with
``DEPENDENCY_CAPABILITY_MISSING`` and the exact missing façade list is recorded on the job.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..canonical import code_fingerprint, fingerprint_hash, hash_file, hash_json
from ..errors import ErrorCode, SynLabError
from ..jobs.resources import Estimate, ResourceGuard
from ..jobs.scheduler import JobRecord, Scheduler
from ..registry import REGISTRY
from ..roles import (
    ROLE_DISPLAY_LOD,
    ROLE_OPERATOR_AUDIT,
    ROLE_RUN_SPEC,
    SCHEMA_QA,
)
from ..schemas.spec import AXIS_IDS, FRACTURE_BACKEND_IDS, LAYER_COMBO_IDS, MATERIAL_IDS, PATTERN_IDS, VESSEL_IDS
from ..storage.release import PROFILE_GATES, ReleaseManager
from ..storage.store import QA_FAIL, QA_PASS, QA_PENDING, AssetRecord, AssetStore
from . import display
from .capabilities import CAPABILITY_MODULES, CAPABILITY_ENTRYPOINTS, probe_capability
from .integrity import record_integrity, verify_all_files
from .stages import STAGES, stage_spec

CODE_FP_CACHE: dict[str, Any] = {}


# --------------------------------------------------------------------------- context
@dataclass
class JobContext:
    store: AssetStore
    scheduler: Scheduler
    guard: ResourceGuard
    job: JobRecord
    token: str
    fence: int
    workspace: str = "default"
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def spec(self) -> dict[str, Any]:
        return dict(self.job.spec or {})

    def heartbeat(self) -> None:
        self.scheduler.heartbeat(self.job.job_id, self.token, self.fence)

    def progress(self, done: int, planned: int, unit: str, **extra: Any) -> None:
        """Record *counted* progress.  Never a wall-clock percentage."""
        payload = {"done": int(done), "planned": int(planned), "unit": unit}
        payload.update(extra)
        with self.store.connect() as conn:
            row = conn.execute("SELECT spec_json FROM jobs WHERE job_id = ?",
                               (self.job.job_id,)).fetchone()
            spec = json.loads(row["spec_json"]) if row else {}
            spec["progress"] = payload
            conn.execute("UPDATE jobs SET spec_json = ?, updated_at = ? WHERE job_id = ?",
                         (json.dumps(spec, ensure_ascii=False, sort_keys=True), time.time(),
                          self.job.job_id))
        self.store.append_event(run_id=self.job.run_id, job_id=self.job.job_id, type="job.progress",
                                state="RUNNING", revision=self.fence, message=unit,
                                payload={"progress": payload})
        self.heartbeat()

    def commit(self, **kwargs: Any) -> AssetRecord:
        """Commit through the store and immediately record payload hashes."""
        meta = dict(kwargs.pop("meta", {}) or {})
        meta.setdefault("workspace", self.workspace)
        meta.setdefault("run_id", self.job.run_id)
        meta.setdefault("job_id", self.job.job_id)
        record = self.store.commit_asset(meta=meta, attempt_dir=self.store.attempt_dir(self.job.job_id),
                                         **kwargs)
        record_integrity(self.store, record.asset_id)
        self.scheduler.record_outputs(self.job.job_id, [record.asset_id], token=self.token,
                                      fence=self.fence)
        return record


def _code_fingerprint(store: AssetStore) -> dict[str, Any]:
    if "value" in CODE_FP_CACHE:
        return CODE_FP_CACHE["value"]
    repo_root = Path(__file__).resolve().parents[2]
    info = code_fingerprint(repo_root)
    info["fingerprint_hash"] = fingerprint_hash(info)
    CODE_FP_CACHE["value"] = info
    return info


def _registry_fingerprint() -> dict[str, Any]:
    return {"fingerprint": REGISTRY.fingerprint(), "summary": REGISTRY.summary()}


# --------------------------------------------------------------------------- handlers
def run_freeze_spec(ctx: JobContext) -> dict[str, Any]:
    spec = ctx.spec.get("spec") or {}
    if not isinstance(spec, dict) or not spec:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "freeze_spec requires a non-empty spec object",
                          stage="handler.freeze_spec")
    inputs = list(ctx.job.inputs)
    verified: list[dict[str, Any]] = []
    ctx.progress(0, max(1, len(inputs) + 1), "input_assets")
    for index, asset_id in enumerate(inputs, start=1):
        report = verify_all_files(ctx.store, asset_id)
        if not report["ok"]:
            raise SynLabError(
                ErrorCode.ASSET_HASH_MISMATCH,
                f"input asset {asset_id} failed integrity verification: {report['problems'][:3]}",
                stage="handler.freeze_spec", evidence_refs=[asset_id],
            )
        record = ctx.store.get_asset(asset_id)
        verified.append({"asset_id": asset_id, "role": record.role, "qa_status": record.qa_status,
                         "files": sorted(record.files), "blob_hash": record.blob_hash})
        ctx.progress(index, max(1, len(inputs) + 1), "input_assets")

    frozen = dict(spec)
    spec_hash = hash_json(frozen)
    record = ctx.commit(
        role=ROLE_RUN_SPEC, schema="synlab.run_spec.v1", unit="1", frame="none",
        payload={"spec": frozen, "spec_hash": spec_hash, "input_refs": verified,
                 "registry": _registry_fingerprint(), "code": _code_fingerprint(ctx.store)},
        qa={"spec_hash": spec_hash, "inputs_verified": len(verified)},
        qa_status=QA_PASS,
        meta={"spec_hash": spec_hash, "workspace": ctx.workspace, "created_by": "freeze_spec"},
        lineage_id=spec_hash,
    )
    ctx.progress(len(inputs) + 1, len(inputs) + 1, "input_assets")
    return {"outputs": [record.asset_id], "metrics": {"spec_hash": spec_hash,
                                                      "inputs_verified": len(verified)},
            "spec_hash": spec_hash}


# --------------------------------------------------------------------------- coverage
COVERAGE_SPECS: dict[str, tuple[str, list[str], str]] = {
    "coverage_24_vessels": ("vessel", VESSEL_IDS, "vessel_id"),
    "coverage_12_materials": ("material", MATERIAL_IDS, "material_id"),
    "coverage_4_layers": ("layer_combo", LAYER_COMBO_IDS, "layer_combo_id"),
    "coverage_16_patterns": ("pattern", PATTERN_IDS, "pattern_id"),
    "coverage_4_backends": ("fracture_backend", FRACTURE_BACKEND_IDS[:4], "fracture_backend"),
    "coverage_31_axes": ("axis", list(AXIS_IDS), "axis_id"),
}


def coverage_matrix(store: AssetStore, *, workspace: str | None = None,
                    limit: int = 20000) -> dict[str, Any]:
    """Coverage counted from declared asset metadata only (never inferred from filenames)."""
    from .pagination import page_assets

    seen: dict[str, set[str]] = {key: set() for key in COVERAGE_SPECS}
    evidence: dict[str, dict[str, str]] = {key: {} for key in COVERAGE_SPECS}
    scanned = 0
    cursor: str | None = None
    while scanned < limit:
        page = page_assets(store, limit=200, cursor=cursor, workspace=workspace)
        for item in page["items"]:
            scanned += 1
            meta = item.get("meta") or {}
            for gate, (_kind, _ids, field_name) in COVERAGE_SPECS.items():
                value = meta.get(field_name)
                if isinstance(value, str) and value:
                    seen[gate].add(value)
                    evidence[gate].setdefault(value, item["asset_id"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    out: dict[str, Any] = {"scanned_assets": scanned,
                           "basis": "asset meta fields: vessel_id/material_id/layer_combo_id/"
                                    "pattern_id/fracture_backend/axis_id"}
    for gate, (kind, ids, field_name) in COVERAGE_SPECS.items():
        covered = sorted(i for i in ids if i in seen[gate])
        missing = [i for i in ids if i not in seen[gate]]
        out[gate] = {"kind": kind, "declared_field": field_name, "required": len(ids),
                     "covered": len(covered), "complete": not missing,
                     "covered_ids": covered, "missing_ids": missing,
                     "evidence": {i: evidence[gate][i] for i in covered}}
    return out


#: gates this build can actually prove; everything else is reported PENDING with a reason.
EVALUABLE_GATES = frozenset({
    "readonly_commit", "source_map", "coordinate_contract", "closed_assets",
    "coverage_24_vessels", "coverage_12_materials", "coverage_4_layers",
    "coverage_16_patterns", "coverage_4_backends", "coverage_31_axes",
    "references_loadable",
})

GATE_CAPABILITY: dict[str, str] = {
    "fracture_operator_runs": "fracture",
    "observation_operator_runs": "observe",
    "operators_used_pass": "degrade",
    "legal_inputs": "observe",
    "relations_complete": "relations",
    "train_dev_lineage": "training",
    "leakage_audit": "truth",
    "mvs_subset_real_run": "observe",
    "l2_qualification": "diagnostics",
    "real_capture_dataset": "cameras",
    "phone_rgb_mvs": "observe",
    "proxy_calibration": "cameras",
    "training_runs": "training",
    "risk_calibration": "diagnostics",
    "confirmation_complete": "diagnostics",
}


def evaluate_gates(store: AssetStore, *, profile: str, scope_assets: list[str],
                   coverage: dict[str, Any], workspace: str | None = None) -> dict[str, Any]:
    manager = ReleaseManager(store)
    closure = manager.verify_closure(scope_assets) if scope_assets else {
        "ok": True, "problems": [], "assets": 0, "files_checked": 0,
        "note": "no asset scope supplied; closure gate evaluated over an empty set"}

    gates: dict[str, Any] = {}
    required = PROFILE_GATES.get(profile, [])
    for gate in required:
        gates[gate] = _evaluate_one(store, gate, scope_assets=scope_assets, closure=closure,
                                    coverage=coverage, workspace=workspace)

    # structural gates evaluated over the whole store
    with store.connect() as conn:
        duplicated = conn.execute(
            "SELECT release_id FROM releases GROUP BY release_id HAVING COUNT(*) > 1").fetchall()
    gates["_structural"] = {
        "duplicate_release_rows": [r["release_id"] for r in duplicated],
        "registry_fingerprint": REGISTRY.fingerprint(),
    }
    passed = [g for g in required if gates[g]["status"] == "PASS"]
    pending = [g for g in required if gates[g]["status"] == "PENDING"]
    failed = [g for g in required if gates[g]["status"] == "FAIL"]
    na = [g for g in required if gates[g]["status"] == "NA"]
    return {
        "profile": profile,
        "required_gates": required,
        "gates": gates,
        "passed": passed, "pending": pending, "failed": failed, "not_applicable": na,
        "closure": closure,
        "release_ready": bool(required) and not failed and not pending,
        "note": "a gate is PASS only when this build produced direct evidence for it; "
                "ungated capability is reported PENDING with its reason",
    }


def _evaluate_one(store: AssetStore, gate: str, *, scope_assets: list[str], closure: dict[str, Any],
                  coverage: dict[str, Any], workspace: str | None) -> dict[str, Any]:
    if gate in COVERAGE_SPECS:
        block = coverage.get(gate, {})
        status = "PASS" if block.get("complete") else "FAIL"
        return {"status": status,
                "reason": "all required ids declared" if status == "PASS"
                          else f"missing ids: {block.get('missing_ids', [])[:8]}",
                "evidence": {"covered": block.get("covered"), "required": block.get("required"),
                             "basis": coverage.get("basis")}}
    if gate == "readonly_commit":
        manifest_problems = []
        manager = ReleaseManager(store)
        for row in manager.list_releases():
            try:
                manager.load(row["release_id"])
            except SynLabError as exc:
                manifest_problems.append(f"{row['release_id']}: {exc.message}")
        return {"status": "PASS" if not manifest_problems else "FAIL",
                "reason": "every frozen release manifest re-hashes to its stored hash"
                          if not manifest_problems else f"manifest hash mismatch: {manifest_problems[:3]}",
                "evidence": {"releases_checked": len(manager.list_releases())}}
    if gate == "source_map":
        problems, checked = _source_map_check(store, scope_assets)
        return {"status": "PASS" if not problems else "FAIL",
                "reason": "every asset ancestry reference resolves" if not problems
                          else f"dangling ancestry: {problems[:3]}",
                "evidence": {"assets_checked": checked}}
    if gate == "coordinate_contract":
        problems, checked = _coordinate_check(store, workspace)
        return {"status": "PASS" if not problems else "FAIL",
                "reason": "derived display assets carry exactly one display_to_authority transform"
                          if not problems else f"display transform problems: {problems[:3]}",
                "evidence": {"display_assets_checked": checked,
                             "expected_transform_id": display.TRANSFORM_ID}}
    if gate == "closed_assets":
        return {"status": "PASS" if closure.get("ok") else "FAIL",
                "reason": "all scoped assets are QA_PASS with matching file hashes" if closure.get("ok")
                          else f"closure problems: {closure.get('problems', [])[:3]}",
                "evidence": {"assets": closure.get("assets"), "files_checked": closure.get("files_checked")}}
    if gate == "references_loadable":
        problems, checked = _reference_check(store)
        return {"status": "PASS" if not problems else "FAIL",
                "reason": "all registered asset payload files are present" if not problems
                          else f"missing payloads: {problems[:3]}",
                "evidence": {"assets_checked": checked}}
    capability = GATE_CAPABILITY.get(gate)
    if capability:
        probe = probe_capability(capability)
        return {"status": "PENDING",
                "reason": f"requires capability {capability!r} ({CAPABILITY_MODULES.get(capability)}); "
                          f"probe={probe.status}",
                "evidence": {"capability": capability, "probe": probe.as_dict()}}
    return {"status": "PENDING",
            "reason": "no evidence producer for this gate is implemented in this build; "
                      "the gate is not claimed as passed",
            "evidence": {}}


def _source_map_check(store: AssetStore, scope: list[str]) -> tuple[list[str], int]:
    problems: list[str] = []
    checked = 0
    ids = scope or [a.asset_id for a in store.list_assets(limit=2000)]
    for asset_id in ids:
        try:
            record = store.get_asset(asset_id)
        except SynLabError:
            problems.append(f"{asset_id}: missing")
            continue
        checked += 1
        for ancestor in record.ancestry:
            try:
                store.get_asset(ancestor)
            except SynLabError:
                problems.append(f"{asset_id}->{ancestor}")
    return problems, checked


def _coordinate_check(store: AssetStore, workspace: str | None) -> tuple[list[str], int]:
    problems: list[str] = []
    checked = 0
    for record in store.list_assets(role=ROLE_DISPLAY_LOD, limit=2000):
        if workspace is not None and (record.meta or {}).get("workspace", "default") != workspace:
            continue
        checked += 1
        transform = (record.meta or {}).get("display_transform") or {}
        if transform.get("transform_id") != display.TRANSFORM_ID:
            problems.append(f"{record.asset_id}: transform_id={transform.get('transform_id')!r}")
        if transform.get("applied_count") != 1:
            problems.append(f"{record.asset_id}: applied_count={transform.get('applied_count')!r}")
        if record.unit != display.DISPLAY_UNIT:
            problems.append(f"{record.asset_id}: unit={record.unit!r}")
    return problems, checked


def _reference_check(store: AssetStore) -> tuple[list[str], int]:
    problems: list[str] = []
    records = store.list_assets(limit=5000)
    for record in records:
        for name, rel in record.files.items():
            path = store.root / Path(*str(rel).replace("\\", "/").split("/"))
            if not path.exists():
                problems.append(f"{record.asset_id}:{name}")
    return problems, len(records)


def run_audit(ctx: JobContext) -> dict[str, Any]:
    spec = ctx.spec
    profile = str(spec.get("release_profile") or spec.get("profile") or "SANDBOX_CORE")
    scope_assets = [str(a) for a in (spec.get("asset_ids") or [])]
    run_id = spec.get("run_id")
    if run_id:
        for job in ctx.scheduler.list_jobs(run_id=str(run_id), limit=500):
            scope_assets.extend(job.outputs)
    scope_assets = sorted(set(scope_assets))

    ctx.progress(0, 3, "audit_steps")
    coverage = coverage_matrix(ctx.store, workspace=ctx.workspace)
    ctx.progress(1, 3, "audit_steps")
    gates = evaluate_gates(ctx.store, profile=profile, scope_assets=scope_assets,
                           coverage=coverage, workspace=ctx.workspace)
    ctx.progress(2, 3, "audit_steps")

    result = {
        "profile": profile,
        "scope_assets": scope_assets,
        "coverage": coverage,
        "gates": gates,
        "permissions": {
            "role": "server-side",
            "truth_routes": "mounted only for researcher sessions",
            "oracle_export": "researcher only",
        },
        "produced_at": time.time(),
        "producer": "synlab.api.handlers.run_audit",
    }
    record = ctx.commit(
        role=ROLE_OPERATOR_AUDIT, schema=SCHEMA_QA, unit="1", frame="none",
        payload=result, qa=result["gates"], qa_status=QA_PASS,
        meta={"profile": profile, "workspace": ctx.workspace, "audit_kind": "release_scope"},
    )
    ctx.progress(3, 3, "audit_steps")
    audit_id = spec.get("audit_id")
    if audit_id:
        from .tables import get as _tget, update as _tupdate

        if _tget(ctx.store, "api_audits", "audit_id", str(audit_id)) is not None:
            _tupdate(ctx.store, "api_audits", "audit_id", str(audit_id), status="COMPLETED",
                     result=result)
    return {"outputs": [record.asset_id], "metrics": {
        "profile": profile, "passed": len(gates["passed"]), "pending": len(gates["pending"]),
        "failed": len(gates["failed"]), "release_ready": gates["release_ready"],
        "scanned_assets": coverage["scanned_assets"]}, "audit": result}


# --------------------------------------------------------------------------- export
EXPORT_ADAPTERS = ("manifest", "obs_pack", "feature_bundle", "oracle_truth")


def run_export(ctx: JobContext) -> dict[str, Any]:
    spec = ctx.spec
    release_id = str(spec.get("release_id") or "")
    adapter = str(spec.get("adapter") or "manifest")
    if adapter not in EXPORT_ADAPTERS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unsupported export adapter {adapter!r}; known: {list(EXPORT_ADAPTERS)}",
                          stage="handler.export")
    if not release_id:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "export requires release_id",
                          stage="handler.export")
    manager = ReleaseManager(ctx.store)
    manifest = manager.load(release_id)
    ctx.progress(0, 3, "export_steps")

    export_dir = ctx.store.root / "exports" / str(spec.get("export_id") or ctx.job.job_id)
    export_dir.mkdir(parents=True, exist_ok=True)
    from .security import DEPLOYMENT_SAFE_ROLES, RESEARCH_ONLY_ROLES

    entries = []
    for asset in manifest.get("assets", []):
        role = asset.get("role")
        if adapter == "oracle_truth":
            include = True
        elif adapter == "obs_pack":
            include = role in DEPLOYMENT_SAFE_ROLES or role in {ROLE_DISPLAY_LOD, ROLE_RUN_SPEC}
        else:
            include = role not in RESEARCH_ONLY_ROLES
        entries.append({
            "asset_id": asset["asset_id"], "role": role, "schema": asset.get("schema"),
            "unit": asset.get("unit"), "frame": asset.get("frame"),
            "qa_status": asset.get("qa_status"), "blob_hash": asset.get("blob_hash"),
            "included": bool(include),
            "files": sorted((asset.get("files") or {}).keys()),
        })
    ctx.progress(1, 3, "export_steps")

    (export_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (export_dir / "index.json").write_text(
        json.dumps({"release_id": release_id, "adapter": adapter,
                    "manifest_hash": manifest.get("manifest_hash"),
                    "release_profile": manifest.get("profile"),
                    "assets": entries, "exported_at": time.time()}, ensure_ascii=False,
                   indent=2, sort_keys=True), encoding="utf-8")
    ctx.progress(2, 3, "export_steps")

    checksums = {name: hash_file(export_dir / name)
                 for name in ("manifest.json", "index.json")}
    (export_dir / "checksums.sha256").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())),
        encoding="utf-8")
    checksums["checksums.sha256"] = hash_file(export_dir / "checksums.sha256")
    bundle_hash = hash_json(checksums)

    record = ctx.commit(
        role=ROLE_OPERATOR_AUDIT, schema="synlab.export.v1", unit="1", frame="none",
        payload={"export_index": {"release_id": release_id, "adapter": adapter, "assets": entries},
                 "checksums": checksums, "bundle_hash": bundle_hash},
        qa={"bundle_hash": bundle_hash, "adapter": adapter}, qa_status=QA_PASS,
        meta={"release_id": release_id, "adapter": adapter, "workspace": ctx.workspace},
    )
    ctx.progress(3, 3, "export_steps")
    export_id = spec.get("export_id")
    export_result = {"relative_dir": str(export_dir.relative_to(ctx.store.root)).replace("\\", "/"),
                     "checksums": checksums, "bundle_hash": bundle_hash,
                     "assets": len(entries), "adapter": adapter, "release_id": release_id}
    if export_id:
        from .tables import get as _tget, update as _tupdate

        if _tget(ctx.store, "api_exports", "export_id", str(export_id)) is not None:
            _tupdate(ctx.store, "api_exports", "export_id", str(export_id), status="COMPLETED",
                     result=export_result)
    return {"outputs": [record.asset_id],
            "metrics": {"bundle_hash": bundle_hash, "assets": len(entries),
                        "adapter": adapter, "release_id": release_id},
            "export": export_result}


# --------------------------------------------------------------------------- display LOD
def _mesh_from_asset(store: AssetStore, asset_id: str) -> tuple[Any, str]:
    import numpy as np  # noqa: PLC0415
    import trimesh  # noqa: PLC0415

    record = store.get_asset(asset_id)
    arrays = store.load_arrays(asset_id)
    keys = [k for k in arrays if k.endswith(".vertices") or k == "vertices"]
    if not keys:
        raise SynLabError(
            ErrorCode.INPUT_UNAVAILABLE,
            f"asset {asset_id} carries no mesh vertices (role={record.role}); "
            "display_lod needs an authoritative mesh asset",
            stage="handler.display_lod", evidence_refs=[asset_id],
        )
    prefix = keys[0][: -len("vertices")]
    vertices = np.asarray(arrays[f"{prefix}vertices"], dtype=np.float64)
    faces = np.asarray(arrays.get(f"{prefix}faces", np.zeros((0, 3), dtype=np.int64)))
    if faces.size == 0:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          f"asset {asset_id} has no faces; refusing to derive an empty display mesh",
                          stage="handler.display_lod")
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False), prefix.rstrip(".")


def run_display_lod(ctx: JobContext) -> dict[str, Any]:
    from .capabilities import env_report

    probe = env_report().get("trimesh", {})
    if probe.get("status") != "OK":
        raise SynLabError(ErrorCode.ENV_CAPABILITY_MISSING,
                          f"trimesh is required to export GLB: {probe.get('detail')}",
                          stage="handler.display_lod")
    spec = ctx.spec
    source = str(spec.get("asset_id") or "")
    if not source:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "display_lod requires asset_id",
                          stage="handler.display_lod")
    import numpy as np  # noqa: PLC0415
    import trimesh  # noqa: PLC0415

    mesh, mesh_key = _mesh_from_asset(ctx.store, source)
    ctx.progress(0, 3, "lod_levels")
    authority_extent = np.asarray(mesh.bounds[1]) - np.asarray(mesh.bounds[0])

    display_vertices = display.transform_vertices(np.asarray(mesh.vertices, dtype=np.float64))
    display_mesh = trimesh.Trimesh(vertices=display_vertices, faces=np.asarray(mesh.faces),
                                   process=False)
    display_extent = np.asarray(display_mesh.bounds[1]) - np.asarray(display_mesh.bounds[0])
    ctx.progress(1, 3, "lod_levels")

    levels: dict[str, Any] = {}
    lod_notes: list[str] = []
    scene = trimesh.Scene()
    scene.add_geometry(display_mesh, node_name="L0")
    levels["L0"] = {"faces": int(len(display_mesh.faces)), "vertices": int(len(display_mesh.vertices))}
    for level, ratio in (("L1", 0.3), ("L2", 0.08)):
        try:
            simplified = display_mesh.simplify_quadric_decimation(
                face_count=max(4, int(len(display_mesh.faces) * ratio)))
        except BaseException as exc:  # noqa: BLE001 - decimation backend is optional
            lod_notes.append(f"{level} skipped: {type(exc).__name__}: {exc}")
            continue
        if simplified is None or len(simplified.faces) == 0:
            lod_notes.append(f"{level} skipped: decimation returned no faces")
            continue
        scene.add_geometry(simplified.copy(), node_name=level)
        levels[level] = {"faces": int(len(simplified.faces)), "vertices": int(len(simplified.vertices))}
    glb = scene.export(file_type="glb")
    ctx.progress(2, 3, "lod_levels")

    transform = display.describe()
    record = ctx.commit(
        role=ROLE_DISPLAY_LOD, schema="synlab.display_glb.v1",
        unit=display.DISPLAY_UNIT, frame=f"{display.DISPLAY_UP_AXIS}_up_m",
        payload={"glb": bytes(glb)},
        meta={
            "derived": True, "source_asset": source, "source_mesh_key": mesh_key,
            "display_transform": transform,
            "authority_extent_mm": authority_extent.tolist(),
            "display_extent_m": display_extent.tolist(),
            "lod_levels": levels, "lod_notes": lod_notes,
            "display_simplified": bool(lod_notes) or len(levels) > 0,
            "note": "display-only derivation; authoritative geometry remains mm/Z-up and is untouched",
        },
        qa={"authority_extent_mm": authority_extent.tolist(),
            "display_extent_m": display_extent.tolist(),
            "scale_ratio": (display_extent / np.where(authority_extent == 0, 1.0, authority_extent)).tolist()
            if authority_extent.size else [],
            "transform_id": transform["transform_id"]},
        qa_status=QA_PASS, ancestry=[source], lineage_id=(ctx.store.get_asset(source).lineage_id),
    )
    ctx.progress(3, 3, "lod_levels")
    return {"outputs": [record.asset_id],
            "metrics": {"levels": sorted(levels), "authority_extent_mm": authority_extent.tolist(),
                        "display_extent_m": display_extent.tolist(),
                        "glb_bytes": len(glb), "source_asset": source},
            "display_asset": record.asset_id}


# --------------------------------------------------------------------------- gated stages
def run_capability_gated(ctx: JobContext) -> dict[str, Any]:
    """Stages owned by parallel modules.

    The worker refuses to invent their output.  When the module is absent the failure names
    the module and the missing façade functions, which is exactly what the UI shows.
    """
    stage = ctx.job.stage
    spec = stage_spec(stage)
    missing: list[dict[str, Any]] = []
    for key in spec.capabilities:
        probe = probe_capability(key)
        if not probe.available:
            missing.append({"capability": key, "module": probe.module, "status": probe.status,
                            "error": probe.error,
                            "expected_entry_points": list(CAPABILITY_ENTRYPOINTS.get(key, ()))})
    for env_key in spec.env:
        from .capabilities import env_report

        probe = env_report().get(env_key, {})
        if probe.get("status") != "OK":
            missing.append({"capability": env_key, "module": env_key,
                            "status": probe.get("status"), "error": probe.get("detail")})
    if missing:
        raise SynLabError(
            ErrorCode.DEPENDENCY_CAPABILITY_MISSING,
            f"stage {stage!r} needs capabilities that are not importable: "
            + ", ".join(m["capability"] for m in missing),
            stage=f"handler.{stage}", retryable=False,
            evidence_refs=[m["module"] for m in missing],
            measurements={"missing_capabilities": missing,
                          "frozen_call": FROZEN_CALLS.get(stage)},
        )
    raise SynLabError(
        ErrorCode.INTEGRATION_PENDING,
        f"stage {stage!r}: capability modules are importable but the API-side adapter for "
        f"façade call {FROZEN_CALLS.get(stage)} is not wired in this build",
        stage=f"handler.{stage}",
        measurements={"frozen_call": FROZEN_CALLS.get(stage)},
    )


#: the frozen façade calls these stages map onto (docs/a12/interfaces.md section 2).
FROZEN_CALLS: dict[str, str] = {
    "mother": "synlab.mothers.api.create_mother(vessel_id, material_id, params, rng, *, mother_id)",
    "material": "synlab.materials.api.build_material_profile(material_id, params, rng)",
    "pattern": "synlab.patterns.api.build_pattern(mother, spec, rng) + apply_pattern_geometry(...)",
    "fracture": "synlab.fracture.api.fracture_event(mother, spec, rng, *, event_id)",
    "physical": "synlab.physical.api.apply_damage(clean_truth, fragment, recipe, rng)",
    "truth": "synlab.truth.api.finalize_clean_truth(mother, result)",
    "degrade": "synlab.degrade.api.apply_axis(axis_id, level, source, store, *, rng, variant)",
    "observe": "synlab.observe.api.observe(physical, compiled, rngs, *, route)",
    "pool": "synlab.relations.api.build_pool(store, release, spec)",
    "training": "synlab.training.api.train(spec, store)",
    "diagnostics": "synlab.diagnostics.api.run_diagnosis(spec, store)",
    "episode": "synlab.episodes.api.EpisodeEnv(store, pool, cameras).step(state, action)",
    "generate": "full DAG: create_mother -> build_pattern -> fracture_event -> apply_axis -> observe",
}


HANDLERS: dict[str, Callable[[JobContext], dict[str, Any]]] = {
    "freeze_spec": run_freeze_spec,
    "audit": run_audit,
    "export": run_export,
    "display_lod": run_display_lod,
}
for _stage in STAGES:
    HANDLERS.setdefault(_stage, run_capability_gated)


def estimate_for(stage: str, *, planned_jobs: int = 1) -> Estimate:
    spec = stage_spec(stage)
    values = spec.estimate
    estimate = Estimate(
        rss_gb=float(values.get("rss_gb", 1.0)),
        vram_gb=float(values.get("vram_gb", 0.0)),
        temp_disk_gb=float(values.get("temp_disk_gb", 0.5)),
        persistent_disk_gb=float(values.get("persistent_disk_gb", 0.0)),
        cpu_seconds=float(values.get("cpu_seconds", 10.0)),
        assumptions={"stage": stage, "planned_jobs": planned_jobs,
                     "source": "development initial values; not a measured throughput guarantee"},
    )
    return estimate
