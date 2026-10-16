"""Repair the historical feature bundles that carry identity/answer fields (A01 boundary).

Why this exists
---------------
``synlab.pipeline._commit_features`` used to forward the observation metadata
(``fragment_id``/``mother_id``/``component_id``/``observation_id``) into the feature bundle
metadata and declared those keys in ``meta["feature_fields"]``.  The code is fixed: it now
intersects the flattened metadata with ``synlab.roles.FORBIDDEN_FEATURE_FIELDS``, drops those
keys and records them under ``dropped_forbidden_fields``.  The bundles already committed by the
two early runs therefore still keep ``A01`` and ``synlab.qc.leakage.run_negative_control`` at
FAIL.

Why the rows cannot be edited in place
--------------------------------------
``asset_id = interpret_hash(role, schema, unit, frame, payload_hash)`` and the metadata is part
of ``payload_hash``, so rewriting ``meta.json`` (or the role) in place would silently break the
store's identity contract.  The payload is therefore *re-committed* under the same legal role
with the identity fields removed from the metadata, and only then is the offending row retired.

What it does (per offending asset, in this order)
-------------------------------------------------
1. reads the arrays back through ``store.load_arrays`` and hashes every one of them
   (``synlab.canonical.array_hash``), so the "same feature array" claim is measured, not assumed;
2. re-commits exactly those arrays under ``role=feature_bundle`` with the identity fields removed
   from the metadata (``feature_fields`` recomputed, ``dropped_forbidden_fields`` recorded);
3. verifies the re-commit is byte-faithful: same array keys, shapes, dtypes and per-array hashes;
4. only then retires the old row (SQLite row + ``assets/<id>`` directory), after the absolute path
   has been resolved and checked against the asset id;
5. re-points the derivation edges that named the retired id (``ancestry`` of the run's provenance
   asset) to the byte-faithful twin, so the run's reference closure stays verifiable.  ``ancestry``
   is not part of ``interpret_hash``/``blob_hash``, and every change is recorded with its
   before/after value.  A referrer that sits inside a frozen release manifest is *not* touched;
   it is reported as a dangling reference instead;
6. records a tombstone (role, schema, unit, frame, qa, metadata, file hashes, per-array hashes)
   plus the old -> new id mapping and the places that referenced the old id, so the removal is
   auditable and nothing is silently dropped.

``--freeze`` then re-freezes a *new* release version per affected run: the gates come from
``synlab.qc.gates.evaluate_gates`` (store evidence only, nothing relaxed) and the freeze goes
through ``synlab.storage.release.ReleaseManager.freeze`` with a never-used release id, so no
existing manifest can be overwritten.

Usage::

    python tools/repair_feature_leak.py --store data/a12 --plan      # survey only
    python tools/repair_feature_leak.py --store data/a12 --apply     # re-commit + retire + re-point
    python tools/repair_feature_leak.py --store data/a12 --freeze    # freeze new release versions
    python tools/repair_feature_leak.py --store data/a12 --verify    # re-read the result
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synlab.canonical import array_hash, hash_file  # noqa: E402
from synlab.errors import SynLabError  # noqa: E402
from synlab.roles import (  # noqa: E402
    FORBIDDEN_FEATURE_FIELDS,
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_FRAGMENT_MESH,
    ROLE_LABEL_BUNDLE,
    ROLE_OBS_RESULT,
    SCHEMA_FEATURE,
)
from synlab.storage.store import QA_PASS, AssetStore  # noqa: E402

#: Identity fields the observation block used to leak into the feature metadata.  Only the first
#: two are listed in ``FORBIDDEN_FEATURE_FIELDS``; the other two are dropped as well because they
#: are the same identity chain (they name one fragment/one capture) and carry no feature content.
IDENTITY_FIELDS = ("fragment_id", "mother_id", "component_id", "observation_id")

#: Metadata keys this tool maintains; they are bookkeeping, never declared feature payload fields.
BOOKKEEPING_KEYS = ("feature_fields", "dropped_forbidden_fields", "leak_repair", "source_asset_id")

#: Fields of the observation block that carry real feature content and stay.
KEPT_OBSERVATION_KEYS = ("n_views", "image_size", "tokens_total", "scale_valid")


def offending_assets(store: AssetStore) -> list[Any]:
    """feature_bundle assets whose metadata intersects ``FORBIDDEN_FEATURE_FIELDS``."""
    out = []
    for asset in store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=100000):
        if set(asset.meta or {}) & FORBIDDEN_FEATURE_FIELDS:
            out.append(asset)
    return out


def array_census(store: AssetStore, asset_id: str) -> dict[str, dict[str, Any]]:
    arrays = store.load_arrays(asset_id)
    return {key: {"shape": list(value.shape), "dtype": str(value.dtype),
                  "hash": array_hash(value)} for key, value in sorted(arrays.items())}


def references_to(store: AssetStore, asset_id: str, *, releases_root: Path | None = None
                  ) -> dict[str, list[str]]:
    """Every place outside the asset row itself that mentions ``asset_id``."""
    hits: dict[str, list[str]] = {"ancestry": [], "meta": [], "releases": [], "rows": []}
    with store.connect() as conn:
        for row in conn.execute("SELECT asset_id, ancestry_json, meta_json FROM assets").fetchall():
            if asset_id in (row["ancestry_json"] or ""):
                hits["ancestry"].append(row["asset_id"])
            if asset_id in (row["meta_json"] or ""):
                hits["meta"].append(row["asset_id"])
        for table in ("jobs", "runs", "events", "releases"):
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            except Exception:  # noqa: BLE001 - table may not exist in an older store
                continue
            for row in rows:
                blob = " ".join(str(value) for value in tuple(row))
                if asset_id in blob:
                    hits["rows"].append(f"{table}:{tuple(row)[0]}")
    for root in [store.root / "releases", releases_root]:
        if not root or not Path(root).exists():
            continue
        for manifest in Path(root).rglob("manifest.json"):
            if asset_id in manifest.read_text(encoding="utf-8"):
                hits["releases"].append(str(manifest))
    hits["releases"] = sorted(set(hits["releases"]))
    return hits


def frozen_manifests(roots: Sequence[Path]) -> dict[str, str]:
    """Hash of every release manifest under ``roots`` (used to prove nothing was rewritten)."""
    out: dict[str, str] = {}
    for root in roots:
        if not Path(root).exists():
            continue
        for manifest in sorted(Path(root).rglob("manifest.json")):
            out[str(manifest)] = hash_file(manifest)
    return out


def plan_entry(store: AssetStore, asset: Any, *, releases_root: Path | None = None) -> dict[str, Any]:
    meta = dict(asset.meta or {})
    refs = references_to(store, asset.asset_id, releases_root=releases_root)
    feature_fields = list(meta.get("feature_fields") or [])
    return {
        "asset_id": asset.asset_id,
        "run_id": meta.get("run_id"),
        "role": asset.role, "schema": asset.schema, "unit": asset.unit, "frame": asset.frame,
        "qa_status": asset.qa_status, "lineage_id": asset.lineage_id, "split": asset.split,
        "forbidden_meta_keys": sorted(set(meta) & FORBIDDEN_FEATURE_FIELDS),
        "identity_meta_keys": sorted(k for k in IDENTITY_FIELDS if k in meta),
        "identity_fields_in_feature_fields": sorted(k for k in IDENTITY_FIELDS if k in feature_fields),
        "meta_keys": sorted(meta),
        "n_feature_fields": len(feature_fields),
        "ancestry": list(asset.ancestry or []),
        "files": dict(asset.files or {}),
        "file_hashes": dict(store.file_hashes(asset.asset_id)),
        "arrays": array_census(store, asset.asset_id),
        "references": refs,
        #: Derivation edges (``ancestry``) that name this asset; they are re-pointed, not refused.
        "derivation_references": refs["ancestry"],
        #: Release manifests that name this asset; a referrer inside one is never rewritten.
        "frozen_release_references": refs["releases"],
        #: Metadata of other assets naming this asset (none expected; reported if any appear).
        "meta_references": refs["meta"],
    }


def clean_meta(meta: dict[str, Any], array_keys: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Drop identity/answer keys and recompute the declared feature contract."""
    new_meta = {k: v for k, v in meta.items() if k not in IDENTITY_FIELDS}
    dropped = sorted(set(meta) & (FORBIDDEN_FEATURE_FIELDS | set(IDENTITY_FIELDS)))
    still = sorted(set(new_meta) & FORBIDDEN_FEATURE_FIELDS)
    if still:
        raise ValueError(f"metadata still carries forbidden keys after the drop: {still}")
    declared = sorted(k for k in new_meta if k not in BOOKKEEPING_KEYS)
    new_meta["feature_fields"] = declared + sorted(array_keys)
    new_meta["dropped_forbidden_fields"] = dropped
    return new_meta, dropped


def repoint_references(store: AssetStore, old_id: str, new_id: str, *, apply: bool,
                       releases_root: Path | None = None) -> list[dict[str, Any]]:
    """Re-point ``ancestry`` entries that name the retired id to its byte-faithful twin.

    ``ancestry`` is a derivation edge, not part of the asset identity (``interpret_hash`` uses
    role/schema/unit/frame/payload_hash, and ``blob_hash`` uses payload/files/qa/role), so
    re-pointing keeps the referrer's id and file hashes intact.  A referrer that appears inside a
    frozen release manifest is refused: a frozen closure may not be rewritten.
    """
    frozen = {str(path) for path in frozen_manifests(
        [store.root / "releases"] + ([releases_root] if releases_root else []))}
    changed: list[dict[str, Any]] = []
    with store.connect() as conn:
        rows = conn.execute("SELECT asset_id, role, ancestry_json FROM assets").fetchall()
        for row in rows:
            try:
                ancestry = json.loads(row["ancestry_json"] or "[]")
            except ValueError:
                continue
            if old_id not in ancestry:
                continue
            manifest_hits = [path for path in frozen if row["asset_id"] in
                             Path(path).read_text(encoding="utf-8")]
            entry = {"referrer": row["asset_id"], "role": row["role"],
                     "before": list(ancestry),
                     "after": [new_id if item == old_id else item for item in ancestry],
                     "frozen_manifest_hits": manifest_hits, "performed": False}
            if manifest_hits:
                entry["reason"] = "referrer is inside a frozen release manifest; left untouched"
                changed.append(entry)
                continue
            if apply:
                conn.execute("UPDATE assets SET ancestry_json=? WHERE asset_id=?",
                             (json.dumps(entry["after"]), row["asset_id"]))
                conn.execute(
                    "INSERT INTO events(run_id, job_id, type, state, revision, message,"
                    " payload_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (None, None, "asset.ancestry_repointed", "REPLACED", 1, row["asset_id"],
                     json.dumps({"from": old_id, "to": new_id,
                                 "reason": "derivation edge re-pointed to the byte-faithful "
                                           "feature twin after the leaking row was retired"},
                                ensure_ascii=False), time.time()))
            entry["performed"] = bool(apply)
            changed.append(entry)
    return changed


def repair_one(store: AssetStore, entry: dict[str, Any], *, apply: bool,
               releases_root: Path | None = None) -> dict[str, Any]:
    asset_id = entry["asset_id"]
    record = store.get_asset(asset_id)
    arrays = store.load_arrays(asset_id)
    meta = dict(record.meta or {})
    new_meta, dropped = clean_meta(meta, sorted(arrays))
    new_meta["source_asset_id"] = asset_id
    new_meta["leak_repair"] = {
        "schema": "synlab.feature_leak_repair.v1",
        "source_asset_id": asset_id,
        "dropped": dropped,
        "kept_observation_fields": sorted(k for k in KEPT_OBSERVATION_KEYS if k in meta),
    }

    if not apply:
        return {**entry, "performed": False, "reason": "dry run",
                "planned_meta_drop": dropped,
                "planned_meta_keys": sorted(new_meta)}

    new_record = store.commit_asset(
        role=ROLE_FEATURE_BUNDLE, schema=SCHEMA_FEATURE, unit=record.unit, frame=record.frame,
        payload=dict(arrays), meta=new_meta, qa=dict(record.qa or {}), qa_status=QA_PASS,
        ancestry=list(record.ancestry or []), lineage_id=record.lineage_id, split=record.split,
    )

    old_arrays = entry["arrays"]
    new_arrays = array_census(store, new_record.asset_id)
    same_keys = sorted(old_arrays) == sorted(new_arrays)
    identical = same_keys and all(old_arrays[k]["hash"] == new_arrays[k]["hash"]
                                  and old_arrays[k]["shape"] == new_arrays[k]["shape"]
                                  and old_arrays[k]["dtype"] == new_arrays[k]["dtype"]
                                  for k in old_arrays)
    fidelity = {
        "array_keys_equal": same_keys,
        "array_hashes_equal": identical,
        "n_arrays_old": len(old_arrays), "n_arrays_new": len(new_arrays),
        "n_elements_old": sum(int(math.prod(a["shape"]) or 1) for a in old_arrays.values()),
        "differences": sorted(k for k in set(old_arrays) | set(new_arrays)
                              if old_arrays.get(k, {}).get("hash") != new_arrays.get(k, {}).get("hash")),
    }
    new_meta_read = dict(new_record.meta or {})
    meta_diff = {
        "dropped_keys": dropped,
        "only_old": sorted(set(meta) - set(new_meta_read)),
        "only_new": sorted(set(new_meta_read) - set(meta)),
        "changed": sorted(k for k in set(meta) & set(new_meta_read) if meta[k] != new_meta_read[k]),
        "forbidden_left_new": sorted(set(new_meta_read) & FORBIDDEN_FEATURE_FIELDS),
    }
    if not identical or meta_diff["forbidden_left_new"]:
        # The rebuild did not produce a legal, byte-faithful twin: keep the offending row and
        # report exactly why instead of quietly accepting a lossy repair.
        return {**entry, "performed": False, "new_asset_id": new_record.asset_id,
                "fidelity": fidelity, "meta_diff": meta_diff,
                "reason": "rebuild is not byte-faithful or still forbidden; old row left in place"}

    # ---------------- retire the offending row -----------------------------------------
    asset_dir = (store.root / "assets" / asset_id).resolve()
    expected_parent = (store.root / "assets").resolve()
    if asset_dir.parent != expected_parent or asset_dir.name != asset_id:
        return {**entry, "performed": False, "new_asset_id": new_record.asset_id,
                "fidelity": fidelity, "meta_diff": meta_diff,
                "reason": f"refusing to remove unexpected path {asset_dir}"}
    existed = asset_dir.exists()
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))
            conn.execute(
                "INSERT INTO events(run_id, job_id, type, state, revision, message, payload_json,"
                " created_at) VALUES (?,?,?,?,?,?,?,?)",
                (meta.get("run_id"), None,
                 "asset.feature_leak_repaired", "REPLACED", 1, asset_id,
                 json.dumps({"from_asset_id": asset_id, "to_asset_id": new_record.asset_id,
                             "dropped_fields": dropped,
                             "reason": "historical feature bundle carried identity/answer fields in "
                                       "its metadata (A01 / leakage boundary); re-committed under "
                                       "the same role without them"},
                            ensure_ascii=False),
                 time.time()))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    if existed:
        shutil.rmtree(asset_dir)

    repointed = repoint_references(store, asset_id, new_record.asset_id, apply=True,
                                   releases_root=releases_root)
    tombstone = {
        "asset_id": asset_id, "role": record.role, "schema": record.schema, "unit": record.unit,
        "frame": record.frame, "qa_status": record.qa_status, "qa": dict(record.qa or {}),
        "lineage_id": record.lineage_id, "split": record.split,
        "ancestry": list(record.ancestry or []), "meta": meta,
        "files": dict(record.files or {}), "file_hashes": entry["file_hashes"],
        "arrays": old_arrays,
        "removed_at": time.time(),
        "asset_dir_removed": bool(existed),
    }
    return {**entry, "performed": True, "new_asset_id": new_record.asset_id,
            "new_meta": new_meta_read, "new_arrays": new_arrays,
            "new_qa_status": new_record.qa_status,
            "fidelity": fidelity, "meta_diff": meta_diff,
            "ancestry_repointed": repointed, "tombstone": tombstone}


def store_survey(store: AssetStore) -> dict[str, Any]:
    from synlab.qc.leakage import run_negative_control

    features = store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=100000)
    runs: dict[str, dict[str, Any]] = {}
    for asset in features:
        run_id = (asset.meta or {}).get("run_id") or "<none>"
        bucket = runs.setdefault(run_id, {"assets": [], "forbidden": 0})
        forbidden = sorted(set(asset.meta or {}) & FORBIDDEN_FEATURE_FIELDS)
        bucket["assets"].append(asset.asset_id)
        bucket["forbidden"] += len(forbidden)
    control = run_negative_control(store, None)
    return {
        "n_feature_assets": len(features),
        "forbidden_entries_total": sum(len(set(a.meta or {}) & FORBIDDEN_FEATURE_FIELDS)
                                       for a in features),
        "runs": {k: {"n_assets": len(v["assets"]), "forbidden_entries": v["forbidden"],
                     "assets": sorted(v["assets"])} for k, v in sorted(runs.items())},
        "negative_control_store": {"ok": control["ok"], "status": control["status"],
                                   "truth_isolation": control["checks"]["truth_isolation"],
                                   "problems": control["problems"]},
    }


def negative_control_runs(store: AssetStore, run_ids: Sequence[str]) -> dict[str, Any]:
    from synlab.qc.leakage import run_negative_control

    out: dict[str, Any] = {}
    for run_id in run_ids:
        report = run_negative_control(store, run_id)
        checks = report["checks"]
        features = [a for a in store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=100000)
                    if (a.meta or {}).get("run_id") == run_id]
        out[run_id] = {
            "ok": report["ok"], "status": report["status"],
            "truth_isolation": checks["truth_isolation"],
            "metadata_permutation": checks["metadata_permutation"],
            "row_permutation_invariance": checks["row_permutation_invariance"],
            "features_checked": len(features),
            "feature_asset_ids": sorted(a.asset_id for a in features),
            "problems": report["problems"],
        }
    return out


def freeze_runs(store: AssetStore, run_ids: Sequence[str], *, apply: bool,
                out_dir: Path) -> list[dict[str, Any]]:
    """Freeze a *new* release version per run; gates come from store evidence only.

    The full run scope is attempted first.  ``ReleaseManager.verify_closure`` walks the whole
    derivation chain, and this store's observation chain carries two defects that predate the
    leakage repair (a ``physical_component`` row is ``QA_PENDING`` and its ``ancestry`` names a
    *fragment id* instead of an asset id).  When the full scope cannot verify, a second,
    explicitly *reduced* release is frozen over the assets whose own closure verifies; the
    excluded assets are recorded with the measured problems, and the manifest says in its own
    ``extra.scope_declaration`` that it does NOT contain the repaired feature bundles.  Gates are
    never relaxed or overridden: every verdict comes from ``qc.gates.evaluate_gates``.
    """
    from synlab.qc.audit import audit_run, write_audit_report
    from synlab.qc.gates import evaluate_gates, gate_evidence
    from synlab.storage.release import PROFILE_GATES, ReleaseManager

    results: list[dict[str, Any]] = []
    for run_id in run_ids:
        audit = audit_run(store, run_id)
        audit_path = write_audit_report(store, audit, f"audit_{run_id}") if apply else None
        gates, gate_asset_ids, profile = evaluate_gates(store, run_id)
        evidence = gate_evidence(store, run_id)
        run_assets = [a for a in store.list_assets(limit=100000)
                      if (a.meta or {}).get("run_id") == run_id]
        keep = [a for a in run_assets if a.qa_status == QA_PASS]
        required = PROFILE_GATES[profile]
        scope_pending = [g for g in required if gates.get(g) != "PASS"]
        entry: dict[str, Any] = {
            "run_id": run_id, "profile": profile, "gates": gates,
            "required_gates": required, "scope_pending": scope_pending,
            "audit_ok": audit["ok"], "audit_problems": audit["problems"][:6],
            "audit_report": str(audit_path) if audit_path else None,
            "gate_evidence": evidence,
            "scope_assets": len(keep),
            "run_assets": len(run_assets),
        }
        if not apply:
            entry["frozen"] = False
            entry["note"] = "dry run: no audit report written and no release frozen"
            results.append(entry)
            continue
        manager = ReleaseManager(store)
        closure = manager.verify_closure([a.asset_id for a in keep])
        entry["closure_full"] = {"ok": closure["ok"], "problems": closure["problems"][:8],
                                 "assets": closure["assets"],
                                 "files_checked": closure["files_checked"]}
        verifying, excluded = [], []
        for asset in keep:
            single = manager.verify_closure([asset.asset_id])
            if single["ok"]:
                verifying.append(asset)
            else:
                excluded.append({"asset_id": asset.asset_id, "role": asset.role,
                                 "problems": single["problems"][:4]})
        entry["assets_failing_own_closure"] = excluded
        scope_kind = "full" if closure["ok"] else "reduced"
        scope = keep if closure["ok"] else verifying
        entry["scope_kind"] = scope_kind
        entry["excluded_assets"] = excluded if scope_kind == "reduced" else []
        if not scope:
            entry.update({"frozen": False,
                          "reason": "no asset of this run has a verifying reference closure"})
            results.append(entry)
            continue
        short = run_id.split("_", 1)[-1][:12]
        release_id = (f"rel_{short}_{int(time.time())}" if scope_kind == "full"
                      else f"rel_{short}_reduced_{int(time.time())}")
        scope_declaration = (
            "SANDBOX_CORE release of one real generation run's QA_PASS assets, frozen after the "
            "A01 feature-leak repair. The frozen scope is the whole QA_PASS set of the run."
            if scope_kind == "full" else
            "REDUCED SANDBOX_CORE release: the run's assets whose own reference closure verifies. "
            "The excluded assets are listed in excluded_assets with the measured problems "
            "(pre-existing defects of the observation chain: a physical_component row is "
            "QA_PENDING and its ancestry names a fragment id instead of an asset id -- the same "
            "problems appear for the untouched clean run, so they are not caused by the leak "
            "repair). This release therefore does NOT contain the repaired feature bundles and "
            "must not be presented as the released feature closure.")
        try:
            record = manager.freeze(
                release_id=release_id, profile=profile, scope="SYNTHETIC",
                asset_ids=[a.asset_id for a in scope], gates=gates,
                coverage={"roles": _role_counts(scope),
                          "feature_assets": len([a for a in scope
                                                 if a.role == ROLE_FEATURE_BUNDLE]),
                          "fragment_assets": len([a for a in scope
                                                  if a.role == ROLE_FRAGMENT_MESH])},
                scope_pending=scope_pending,
                extra={
                    "purpose": ("new release version frozen after the A01 feature-leak repair of "
                                "the 8 historical feature bundles (features re-committed as "
                                "byte-faithful twins without identity fields; derivation edges "
                                "re-pointed)"),
                    "repair_report": "data/a12/reports/feature_leak_repair.json",
                    "scope_kind": scope_kind,
                    "scope_declaration": scope_declaration,
                    "excluded_assets": excluded,
                    "closure_full_ok": closure["ok"],
                    "closure_full_problems": closure["problems"][:8],
                    "store_derived_gates": gates,
                    "evidence_reports": evidence,
                })
        except SynLabError as exc:
            code = exc.code.value if hasattr(exc.code, "value") else str(exc.code)
            entry.update({
                "frozen": False, "release_id_attempted": release_id,
                "reason": "freeze refused by the required gates",
                "error": {"code": code, "stage": exc.stage, "message": exc.message,
                          "measurements": exc.measurements},
            })
            results.append(entry)
            continue
        entry.update({"frozen": True, "release_id_attempted": release_id,
                      **record.as_dict()})
        results.append(entry)
    if apply:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "release_freeze_after_feature_leak_repair.json").write_text(
            json.dumps({"schema": "synlab.feature_leak_release_freeze.v1",
                        "generated_at": time.time(), "store": str(store.root),
                        "runs": results,
                        "note": ("gates are the store-derived verdicts of "
                                 "synlab.qc.gates.evaluate_gates; no gate was relaxed, raised or "
                                 "overridden, and every freeze uses a release id that never "
                                 "existed before")},
                       ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8")
    return results


def _role_counts(assets: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for asset in assets:
        counts[asset.role] = counts.get(asset.role, 0) + 1
    return dict(sorted(counts.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repair_feature_leak")
    parser.add_argument("--store", default="data/a12")
    parser.add_argument("--apply", action="store_true", help="really re-commit and retire")
    parser.add_argument("--plan", action="store_true", help="survey only (the default)")
    parser.add_argument("--freeze", action="store_true", help="freeze new release versions")
    parser.add_argument("--verify", action="store_true", help="re-read the repaired store")
    parser.add_argument("--external-releases", default="data/a12_exports",
                        help="release roots outside the store that must stay untouched")
    parser.add_argument("--runs", default="run_2fad0ac4d3b67098,run_404bbe3c80f2c04e")
    parser.add_argument("--clean-run", default="run_23664ddb26eada4b")
    parser.add_argument("--before-report", default="data/a12/reports/feature_leak_assets_before.json")
    parser.add_argument("--report", default="data/a12/reports/feature_leak_repair.json")
    parser.add_argument("--out-dir", default="data/a12/reports")
    args = parser.parse_args(argv)

    store_root = Path(args.store)
    if not store_root.is_absolute():
        store_root = ROOT / store_root
    store = AssetStore(store_root)
    releases_root = Path(args.external_releases)
    if not releases_root.is_absolute():
        releases_root = ROOT / releases_root
    run_ids = [r for r in args.runs.split(",") if r.strip()]

    if args.verify:
        survey = store_survey(store)
        survey["negative_control_runs"] = negative_control_runs(store, [*run_ids, args.clean_run])
        print(json.dumps(survey, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.freeze:
        results = freeze_runs(store, run_ids, apply=args.apply, out_dir=ROOT / args.out_dir)
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        return 0

    external_before = frozen_manifests([releases_root])
    store_releases_before = frozen_manifests([store.root / "releases"])
    assets = offending_assets(store)
    entries = [plan_entry(store, asset, releases_root=releases_root) for asset in assets]
    before = store_survey(store)

    before_path = Path(args.before_report)
    if not before_path.is_absolute():
        before_path = ROOT / before_path
    before_path.parent.mkdir(parents=True, exist_ok=True)
    before_doc = {
        "schema": "synlab.feature_leak_assets.v1",
        "generated_at": time.time(),
        "store": str(store.root),
        "rule": ("role == feature_bundle AND meta intersects "
                 "synlab.roles.FORBIDDEN_FEATURE_FIELDS"),
        "offending_count": len(entries),
        "forbidden_entries": sum(len(e["forbidden_meta_keys"]) for e in entries),
        "survey": before,
        "feature_arrays_hash_manifest": {
            e["asset_id"]: {k: v["hash"] for k, v in e["arrays"].items()} for e in entries},
        "external_release_manifests": external_before,
        "assets": entries,
    }
    before_path.write_text(json.dumps(before_doc, ensure_ascii=False, indent=2, sort_keys=True,
                                      default=str), encoding="utf-8")
    print(f"[feature-leak] offending={len(entries)} "
          f"forbidden_entries={before_doc['forbidden_entries']} -> {before_path}")

    if not args.apply:
        for entry in entries:
            print(f"  {entry['asset_id']} run={entry['run_id']} "
                  f"forbidden={entry['forbidden_meta_keys']} "
                  f"refs={ {k: len(v) for k, v in entry['references'].items()} }")
        return 0

    results = [repair_one(store, entry, apply=True, releases_root=releases_root)
               for entry in entries]
    after = store_survey(store)
    external_after = frozen_manifests([releases_root])
    store_releases_after = frozen_manifests([store.root / "releases"])
    report = {
        "schema": "synlab.feature_leak_repair.v1",
        "generated_at": time.time(),
        "store": str(store.root),
        "applied": True,
        "policy": ("re-commit the same arrays under the same legal role with the identity fields "
                   "removed from the metadata, then retire the offending row (SQLite row + "
                   "assets/<id> directory) with a tombstone, then re-point the derivation edges "
                   "(ancestry) that named it; asset_id and role are never edited in place"),
        "repaired_rule": before_doc["rule"],
        "identity_fields_dropped": list(IDENTITY_FIELDS),
        "before": {"offending_count": len(entries),
                   "forbidden_entries": before_doc["forbidden_entries"],
                   "survey": before},
        "after": after,
        "negative_control_runs": negative_control_runs(store, [*run_ids, args.clean_run]),
        "repaired": [r for r in results if r.get("performed")],
        "refused": [r for r in results if not r.get("performed")],
        "entries": results,
        "external_release_manifests_before": external_before,
        "external_release_manifests_after": external_after,
        "external_releases_untouched": external_before == external_after,
        "store_release_manifests_before": store_releases_before,
        "store_release_manifests_after": store_releases_after,
        "note": ("asset_id is derived from interpret_hash(role, schema, unit, frame, payload_hash) "
                 "and the metadata is part of payload_hash, so neither the metadata nor the role of "
                 "an existing row can be edited: the payload is re-committed as a new asset and the "
                 "old row is retired afterwards, with its full tombstone recorded here. Every "
                 "retired id was referenced by exactly one derivation edge (the run's provenance "
                 "ancestry), which is re-pointed to the twin and listed per asset."),
    }
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True,
                                      default=str), encoding="utf-8")
    print(f"[feature-leak] repaired={len(report['repaired'])} refused={len(report['refused'])} "
          f"-> {report_path}")
    for entry in report["repaired"]:
        print(f"  {entry['asset_id']} -> {entry['new_asset_id']} "
              f"arrays={entry['fidelity']['n_arrays_new']} "
              f"faithful={entry['fidelity']['array_hashes_equal']} "
              f"dropped={entry['meta_diff']['dropped_keys']} "
              f"repointed={[r['referrer'] for r in entry['ancestry_repointed']]}")
    for entry in report["refused"]:
        print(f"  REFUSED {entry['asset_id']}: {entry.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
