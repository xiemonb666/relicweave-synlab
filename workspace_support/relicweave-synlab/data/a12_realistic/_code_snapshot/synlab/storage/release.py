"""Immutable release manifests and closure verification (plan 6.2 step 7, 30.18)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..canonical import hash_bytes, hash_file, hash_json
from ..errors import ErrorCode, SynLabError
from .store import QA_PASS, AssetStore

RELEASE_SCHEMA = "synlab.release.v1"

#: Gate names for the staged release profiles (plan 30.18).
PROFILE_GATES: dict[str, list[str]] = {
    "SANDBOX_CORE": ["fixture_contract", "coordinate_contract", "source_map", "readonly_commit",
                     "fracture_operator_runs", "observation_operator_runs"],
    "PILOT": ["fixture_contract", "coordinate_contract", "source_map", "readonly_commit",
              "fracture_operator_runs", "observation_operator_runs", "train_dev_lineage",
              "operators_used_pass", "legal_inputs", "relations_complete", "read_recovery",
              "leakage_audit"],
    "CORE_COVERAGE": ["fixture_contract", "coordinate_contract", "source_map", "readonly_commit",
                      "fracture_operator_runs", "observation_operator_runs", "train_dev_lineage",
                      "operators_used_pass", "legal_inputs", "relations_complete", "read_recovery",
                      "leakage_audit", "coverage_24_vessels", "coverage_12_materials", "coverage_4_layers",
                      "coverage_16_patterns", "coverage_4_backends", "coverage_31_axes",
                      "mvs_subset_real_run", "core_ui_api", "l2_qualification"],
    "SCALE_10K": ["accepted_nested_10k", "references_loadable", "loader_index_runnable", "resource_profile"],
    "SCALE_50K": ["accepted_nested_50k", "references_loadable", "loader_index_runnable", "resource_profile"],
    "SCALE_100K": ["accepted_nested_100k", "references_loadable", "loader_index_runnable", "resource_profile"],
    "CALIBRATED_PHONE": ["real_capture_dataset", "phone_rgb_mvs", "scale_source", "mask_source",
                         "capture_profile", "proxy_calibration"],
    "RESEARCH_EVIDENCE": ["frozen_protocol", "training_runs", "risk_calibration", "confirmation_complete"],
}


@dataclass
class ReleaseRecord:
    release_id: str
    manifest_hash: str
    scope: str
    profile: str
    frozen_at: float
    manifest_path: str
    asset_ids: list[str]
    gates: dict[str, str]
    scope_completed: list[str]
    scope_pending: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id, "manifest_hash": self.manifest_hash, "scope": self.scope,
            "profile": self.profile, "frozen_at": self.frozen_at, "manifest_path": self.manifest_path,
            "asset_count": len(self.asset_ids), "gates": self.gates,
            "scope_completed": self.scope_completed, "scope_pending": self.scope_pending,
        }


class ReleaseManager:
    def __init__(self, store: AssetStore):
        self.store = store

    # ------------------------------------------------------------------ closure
    def verify_closure(self, asset_ids: Sequence[str]) -> dict[str, Any]:
        """Verify every referenced asset exists, is QA_PASS and its files hash correctly."""
        problems: list[str] = []
        seen: set[str] = set()
        queue = list(asset_ids)
        files_checked = 0
        while queue:
            asset_id = queue.pop()
            if asset_id in seen:
                continue
            seen.add(asset_id)
            try:
                record = self.store.get_asset(asset_id)
            except SynLabError:
                problems.append(f"missing asset {asset_id}")
                continue
            if record.qa_status != QA_PASS:
                problems.append(f"asset {asset_id} qa_status={record.qa_status}")
            for name, rel in record.files.items():
                if name == "meta":
                    continue
                path = self.store.root / Path(*str(rel).split("/"))
                if not path.exists():
                    problems.append(f"{asset_id}:{name} missing")
                    continue
                expected = self.store.file_hashes(asset_id).get(name)
                if expected and hash_file(path) != expected:
                    problems.append(f"{asset_id}:{name} hash mismatch")
                files_checked += 1
            queue.extend(record.ancestry)
        return {"ok": not problems, "problems": problems, "assets": len(seen),
                "files_checked": files_checked}

    # ------------------------------------------------------------------ freeze
    def freeze(self, *, release_id: str, profile: str, scope: str, asset_ids: Sequence[str],
               gates: dict[str, str], coverage: dict[str, Any] | None = None,
               scope_pending: Sequence[str] | None = None,
               extra: dict[str, Any] | None = None) -> ReleaseRecord:
        """Freeze a release. Any REQUIRED gate that is not PASS blocks the release."""
        if profile not in PROFILE_GATES:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown release profile {profile}",
                              stage="release.freeze")
        required = PROFILE_GATES[profile]
        blocking = [g for g in required if gates.get(g) != "PASS"]
        if blocking:
            raise SynLabError(
                ErrorCode.STOP_QA,
                f"release {release_id} blocked: required gates not PASS: {blocking}",
                stage="release.freeze",
                evidence_refs=blocking,
                measurements={"gates": gates},
            )
        closure = self.verify_closure(asset_ids)
        if not closure["ok"]:
            raise SynLabError(
                ErrorCode.ASSET_HASH_MISMATCH,
                f"release {release_id} closure failed: {closure['problems'][:5]}",
                stage="release.freeze",
                measurements=closure,
            )
        manifest_dir = self.store.root / "releases" / release_id
        manifest_path = manifest_dir / "manifest.json"
        if manifest_path.exists():
            raise SynLabError(
                ErrorCode.STOP_QA,
                f"release {release_id} already frozen (immutable); create a new version",
                stage="release.freeze",
            )
        assets = [{"asset_id": a, **self.store.get_asset(a).as_dict()} for a in sorted(set(asset_ids))]
        manifest = {
            "schema": RELEASE_SCHEMA,
            "release_id": release_id,
            "profile": profile,
            "scope": scope,
            "frozen_at": time.time(),
            "gates": gates,
            "required_gates": required,
            "scope_completed": [g for g in required if gates.get(g) == "PASS"],
            "scope_pending": list(scope_pending or [g for g in required if gates.get(g) != "PASS"]),
            "coverage": coverage or {},
            "assets": assets,
            "closure": {"ok": closure["ok"], "files_checked": closure["files_checked"]},
            "extra": extra or {},
        }
        manifest_hash = hash_json({k: v for k, v in manifest.items() if k != "frozen_at"})
        manifest["manifest_hash"] = manifest_hash
        manifest_dir.mkdir(parents=True, exist_ok=True)
        tmp = manifest_path.with_suffix(".json.part")
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(manifest_path)
        with self.store.connect() as conn:
            conn.execute(
                """INSERT INTO releases(release_id, manifest_hash, scope, profile, frozen_at, manifest_path, meta_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (release_id, manifest_hash, scope, profile, manifest["frozen_at"], str(manifest_path),
                 json.dumps({"asset_count": len(assets), "coverage": coverage or {}})),
            )
        return ReleaseRecord(
            release_id=release_id, manifest_hash=manifest_hash, scope=scope, profile=profile,
            frozen_at=manifest["frozen_at"], manifest_path=str(manifest_path),
            asset_ids=sorted({a for a in asset_ids}), gates=dict(gates),
            scope_completed=manifest["scope_completed"], scope_pending=manifest["scope_pending"],
        )

    def load(self, release_id: str) -> dict[str, Any]:
        path = self.store.root / "releases" / release_id / "manifest.json"
        if not path.exists():
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH, f"unknown release {release_id}",
                              stage="release.load")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        stored = manifest.get("manifest_hash")
        recomputed = hash_json({k: v for k, v in manifest.items()
                                if k not in ("frozen_at", "manifest_hash")})
        if stored != recomputed:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"release manifest {release_id} modified", stage="release.load")
        return manifest

    def list_releases(self) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute("SELECT * FROM releases ORDER BY frozen_at DESC").fetchall()
        return [dict(r) for r in rows]
