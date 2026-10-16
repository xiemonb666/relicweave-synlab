from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge").resolve()
OUT = ROOT / "tmp" / "backup_coordinator" / "closeout_20261007"
INV_PATH = OUT / "inventory.json"
MANIFEST_PATH = OUT / "explicit_action_manifest.json"
MAP_PATH = OUT / "WORKSPACE_SOURCE_MAP.json"
COVERAGE_PATH = OUT / "CODE_COVERAGE.md"
SUPPLEMENTARY_PATH = OUT / "SUPPLEMENTARY_EXPORT_MANIFEST.json"
ACTION_COPY = OUT / "explicit_action_manifest.json"
MAP_DEST = "workspace_backup/20261007/WORKSPACE_SOURCE_MAP.json"
COVERAGE_DEST = "docs/handover/20261007/CODE_COVERAGE.md"
ACTION_DEST = "docs/backup/20261007/CONTROL_ACTION_MANIFEST.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    inv_bytes = INV_PATH.read_bytes()
    action_bytes = MANIFEST_PATH.read_bytes()
    inv_hash = digest(inv_bytes)
    action_hash = digest(action_bytes)
    inv = json.loads(inv_bytes)
    action = json.loads(action_bytes)
    if action.get("inventory_sha256") != inv_hash:
        raise SystemExit("action manifest does not bind this inventory SHA-256")
    if inv.get("mode") != "PREPARE_ONLY_NO_COPY_NO_GIT_MUTATION":
        raise SystemExit("inventory is not a frozen prepare-only inventory")

    rows = []
    for entry in inv.get("entries", []):
        if not entry.get("sha256") or entry.get("bytes") is None:
            continue
        if not entry.get("destination_repo") or not entry.get("destination_repo_relative"):
            continue
        if entry.get("operation") == "exclude":
            continue
        source_repo = entry.get("repo")
        source_rel = entry.get("source_repo_relative")
        source_workspace = entry.get("source_workspace_relative")
        source_path = source_workspace or (f"{source_repo}/{source_rel}" if source_repo and source_rel else None)
        if not source_path:
            continue
        rows.append({
            "source_path": source_path.replace("\\", "/"),
            "source_kind": "workspace_root_external" if source_workspace else "repository_file",
            "source_repo": source_repo,
            "source_bytes": entry["bytes"],
            "source_sha256": entry["sha256"],
            "source_status": entry.get("git_status"),
            "source_worktree_head_relation": entry.get("worktree_head_relation"),
            "source_head_blob_oid": entry.get("git_head_blob_oid"),
            "destination_repo": entry["destination_repo"],
            "destination_path": entry["destination_repo_relative"].replace("\\", "/"),
            "operation": entry.get("operation"),
            "classification": entry.get("classification"),
            "reused_existing_destination_source": entry.get("reused_existing_destination_source"),
            "selected_replay_input": entry.get("selected_replay_input", False),
        })
    rows.sort(key=lambda x: (x["destination_repo"], x["destination_path"].lower(), x["source_path"].lower(), x["operation"] or ""))

    repo_rows = []
    for name, state in sorted(inv.get("repositories", {}).items()):
        repo_rows.append({
            "repo": name,
            "repo_root": state.get("repo_root"),
            "branch": state.get("branch"),
            "head": state.get("head"),
            "parent": state.get("parent"),
            "origin_sanitized": state.get("origin_sanitized"),
            "remote_head": state.get("remote_head"),
        })

    source_map = {
        "schema": "codex_workspace_source_recovery_map_v1",
        "state": "PREPARE_ONLY; mappings derive from a frozen inventory and are not proof of copied or committed content",
        "inventory_path": str(INV_PATH),
        "inventory_sha256": inv_hash,
        "action_manifest_path": str(MANIFEST_PATH),
        "action_manifest_sha256": action_hash,
        "repositories": repo_rows,
        "status_evidence_dependency_closure": inv.get("status_evidence_dependency_closure", []),
        "files": rows,
        "summary": {
            "recoverable_mapping_rows": len(rows),
            "mapping_source_bytes_sum_including_aliases": sum(x["source_bytes"] for x in rows),
            "workspace_external_rows": sum(x["source_kind"] == "workspace_root_external" for x in rows),
            "raw_snapshot_rows": sum("raw_snapshot" in str(x.get("classification", "")) for x in rows),
            "alias_rows": sum(x.get("operation") == "already_recoverable_same_bytes_destination" for x in rows),
        },
    }
    map_data = (json.dumps(source_map, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
    MAP_PATH.write_bytes(map_data)

    summary = inv.get("summary", {})
    per_repo = summary.get("per_repo", {})
    lines = [
        "# Source coverage and recovery map",
        "",
        "This file summarizes the frozen prepare-only source inventory. Candidate mappings are not evidence that a copy, Git commit, or push has occurred.",
        "",
        f"Inventory SHA-256: `{inv_hash}`",
        f"Action manifest SHA-256: `{action_hash}`",
        f"Inventory entries: {summary.get('inventory_entries', 'unknown')}",
        f"Candidate actions: {summary.get('action_count', 'unknown')} ({summary.get('action_bytes', 'unknown')} bytes)",
        f"Recovery-map rows: {len(rows)}; workspace-external rows: {source_map['summary']['workspace_external_rows']}; raw-snapshot rows: {source_map['summary']['raw_snapshot_rows']}; same-byte alias rows: {source_map['summary']['alias_rows']}.",
        "",
        "## Repository candidates",
        "",
        "| Repository | Candidate paths | Candidate bytes |",
        "|---|---:|---:|",
    ]
    for name in ("pgfrag", "vesselforge", "relicweave-synlab", "workspace_root_external"):
        state = per_repo.get(name, {})
        lines.append(f"| `{name}` | {state.get('action_count', 0)} | {state.get('action_bytes', 0)} |")
    lines.extend([
        "",
        "## Integrity and exclusions",
        "",
        f"Status-pin evidence references: {summary.get('status_evidence_refs', 0)}; unmatched: {summary.get('status_evidence_refs_unmatched', 0)}; without exact recovery mapping: {summary.get('status_evidence_refs_unmapped', 0)}.",
        f"Tracked worktree relations: raw HEAD match {summary.get('tracked_raw_matches_head', 0)}, CRLF/LF-only difference {summary.get('tracked_crlf_only_normalized', 0)}, other/unresolved {summary.get('tracked_other_or_unresolved', 0)}.",
        f"Files over 50 MiB: {summary.get('large_files_over_50MiB_count', 0)} (path and size only); credential-like paths: {summary.get('credential_path_status_only_count', 0)} (path/status only); scan errors: {summary.get('scan_errors_count', 0)}.",
        "",
        "The full per-source SHA-256, byte count, current source status, destination, and same-byte aliases are listed in `WORKSPACE_SOURCE_MAP.json`. Excluded generated datasets and runtime/install trees are not included in that map. No scientific or physical qualification follows from backup coverage.",
        "",
    ])
    coverage_data = "\n".join(lines).encode("utf-8")
    COVERAGE_PATH.write_bytes(coverage_data)

    repo_root = Path(inv["repositories"]["relicweave-synlab"]["repo_root"]).resolve()
    exports = [
        (COVERAGE_PATH, COVERAGE_DEST, "coverage_export"),
        (MAP_PATH, MAP_DEST, "source_map"),
        (ACTION_COPY, ACTION_DEST, "frozen_control_copy"),
    ]
    planned = []
    destinations = set()
    for src, rel, role in exports:
        target = (repo_root / Path(rel)).resolve()
        target.relative_to(repo_root)
        key = rel.lower()
        if key in destinations:
            raise SystemExit(f"duplicate supplementary destination: {rel}")
        destinations.add(key)
        payload = src.read_bytes()
        row = {
            "source_absolute": str(src),
            "source_workspace_relative": src.relative_to(ROOT).as_posix(),
            "destination_repo": "relicweave-synlab",
            "destination_repo_relative": rel,
            "role": role,
            "bytes": len(payload),
            "sha256": digest(payload),
            "operation": "copy_then_stage_exact",
            "destination_exists_before_go": target.exists(),
            "destination_sha256_before_go": digest(target.read_bytes()) if target.is_file() else None,
        }
        if target.exists() and (not target.is_file() or digest(target.read_bytes()) != row["sha256"]):
            row["operation"] = "blocked_destination_collision"
        elif target.is_file():
            row["operation"] = "stage_existing_exact"
        planned.append(row)

    supplement = {
        "schema": "independent_supplementary_exports_v1",
        "mode": "PREPARE_ONLY_REQUIRES_ROOT_GO",
        "source_inventory_sha256": inv_hash,
        "source_action_manifest_sha256": action_hash,
        "exports": planned,
        "summary": {"count": len(planned), "bytes": sum(x["bytes"] for x in planned), "all_targets_unique": len(destinations) == len(planned)},
    }
    SUPPLEMENTARY_PATH.write_text(json.dumps(supplement, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "inventory_sha256": inv_hash,
        "action_manifest_sha256": action_hash,
        "source_map": {"path": str(MAP_PATH), "bytes": len(map_data), "sha256": digest(map_data), "rows": len(rows)},
        "coverage_doc": {"path": str(COVERAGE_PATH), "bytes": len(coverage_data), "sha256": digest(coverage_data)},
        "supplementary_manifest": {"path": str(SUPPLEMENTARY_PATH), "bytes": SUPPLEMENTARY_PATH.stat().st_size, "sha256": digest(SUPPLEMENTARY_PATH.read_bytes())},
        "supplementary_summary": supplement["summary"],
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
