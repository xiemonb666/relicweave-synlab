"""Read-only synthesis aggregation + a synchronous single-lineage preview (U14 support).

Why this router exists
----------------------
The U07/U14 panels have to answer four questions that the pre-existing routes could not
answer without the *frontend* inventing numbers:

* **batch accounting** — planned / attempted / accepted / failed per batch, the failure
  error codes, and the bytes actually on disk (assets table + reports, not a guess);
* **coverage matrix** — vessel × material × pattern × layer, taken from the cross-run
  ``reports/coverage_aggregate.json`` (the same document the coverage gates read) and
  cross-referenced with the assets that really exist;
* **paired degradation preview** — level 0 vs level n of one axis that share a
  ``basis_id`` and one source asset, with the ``meta.measured`` deltas computed from the
  two rows that the degradation stage really wrote;
* **one-lineage synchronous preview** — run exactly one real lineage (``target_mothers=1``)
  through the frozen pipeline and return the per-stage outcome, so "预览" is a real
  computation with a real result, not a form that says "未计算".

Honesty contract
----------------
* Every number is read from the store (assets table, ``reports/*.json``, ``events``) or
  from a run that this process actually executed.  Missing data is ``null`` / an explicit
  ``empty_reason``, never a placeholder.
* Nothing here writes assets or creates a run except ``POST /synthesis/chain-preview``,
  which goes through the *existing* ``POST /jobs`` path (capability gate, budget gate,
  idempotency) and then executes the queued jobs in a separate worker process — the same
  isolation rule the rest of the API follows.
* Errors reuse the standard problem envelope, so the UI can show ``code`` + ``repro``.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ...canonical import hash_json
from ...errors import SynLabError
from ...jobs.state import TERMINAL
from ...registry import REGISTRY
from ...roles import ROLE_FRAGMENT_MESH, ROLE_MOTHER_MESH, ROLE_PATTERN_RECIPE
from ..deps import JobCreateEnvelope, SessionDep
from ..problems import API_CODE_NOT_FOUND, ApiProblem
from ..specs import validate_spec

router = APIRouter(tags=["synthesis"])

#: Safety valve for the cartesian combination space (24×12×16×4 = 18432 today).
MAX_COMBINATIONS = 200_000

#: How long ``POST /synthesis/chain-preview`` may spend inside one request before it gives
#: up and reports the real job state it reached (the run keeps going in the worker).
MAX_PREVIEW_SECONDS = 900.0
DEFAULT_PREVIEW_SECONDS = 600.0

#: Terminal job states (imported so this file cannot drift from the scheduler's definition).
TERMINAL_STATES = {state.value for state in TERMINAL}


# --------------------------------------------------------------------------- DTOs
class ChainPreviewEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any] = Field(default_factory=dict)
    run: bool = True
    #: ``pipeline`` = call the façade chain directly (real assets, real per-stage timings);
    #: ``jobs`` = enqueue through POST /jobs and drain with one worker subprocess.
    mode: Literal["pipeline", "jobs"] = "pipeline"
    max_retries: int = Field(default=1, ge=0, le=4)
    timeout_seconds: float = Field(default=DEFAULT_PREVIEW_SECONDS, ge=5.0, le=MAX_PREVIEW_SECONDS)
    idempotency_key: str | None = Field(default=None, max_length=128)


class BatchPlanEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any] = Field(default_factory=dict)
    requested: int = Field(default=4, ge=1, le=64)
    batch_size: int = Field(default=4, ge=1, le=64)
    cursor: int = Field(default=0, ge=0)
    resume: bool = False
    idempotency_key: str | None = Field(default=None, max_length=128)


# --------------------------------------------------------------------------- helpers
def _iso_seconds(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _asset_rows(session: SessionDep, *, limit: int = 500000) -> list[Any]:
    return list(session.store.list_assets(limit=limit))


def _asset_bytes(session: SessionDep, asset_ids: Iterable[str]) -> tuple[int, int]:
    """Real payload bytes on disk for these assets: ``(files, bytes)``.

    The number comes from ``stat()`` on the files the store itself records — no estimate,
    no compression assumption.  A file that vanished is simply not counted.
    """
    return _asset_bytes_for_records(session, _records(session, asset_ids))


def _records(session: SessionDep, asset_ids: Iterable[str]) -> list[Any]:
    out: list[Any] = []
    for asset_id in asset_ids:
        try:
            out.append(session.store.get_asset(asset_id))
        except SynLabError:
            continue
    return out


def _asset_bytes_for_records(session: SessionDep, records: Sequence[Any]) -> tuple[int, int]:
    files = 0
    total = 0
    root = session.store.root
    seen: set[str] = set()
    for record in records:
        for relative in (record.files or {}).values():
            target = root / str(relative)
            if str(target) in seen:
                continue
            seen.add(str(target))
            try:
                if target.is_file():
                    files += 1
                    total += target.stat().st_size
            except OSError:
                continue
    return files, total


def _load_report(session: SessionDep, name: str) -> tuple[dict[str, Any] | None, str | None]:
    """Read ``reports/<name>.json`` verbatim; ``(payload, path)`` or ``(None, None)``."""
    path = session.store.root / "reports" / f"{name}.json"
    if not path.is_file():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, str(path)
    if not isinstance(payload, dict):
        return None, str(path)
    return payload, str(path)


def _coverage_payload(session: SessionDep) -> tuple[dict[str, Any], str | None]:
    """The cross-run aggregate when it exists, else the store-global single-run ledger."""
    aggregate, aggregate_path = _load_report(session, "coverage_aggregate")
    if aggregate is not None:
        return aggregate, aggregate_path
    single, single_path = _load_report(session, "coverage")
    return (single or {}), single_path


def _str_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item) not in ("", "None")]
    if isinstance(value, str) and value:
        return [value]
    return []


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _registry_ids(kind: str) -> list[str]:
    try:
        return sorted(entry.id for entry in REGISTRY.list(kind))
    except Exception:  # noqa: BLE001 - an empty registry must not break a read-only route
        return []


# --------------------------------------------------------------------------- coverage
def _coverage_dimensions(session: SessionDep) -> dict[str, Any]:
    payload, path = _coverage_payload(session)
    gaps = _as_mapping(payload.get("gaps"))
    targets = _as_mapping(payload.get("coverage_targets")) or {
        "vessels": 24, "materials": 12, "patterns": 16, "layer_combos": 4,
        "fracture_backends": 4, "axes": 31,
    }
    covered: dict[str, list[str]] = {}
    missing: dict[str, list[str]] = {}
    for key in targets:
        present = _str_list(payload.get(key))
        if key == "fracture_backends" and not present:
            single = payload.get("fracture_backend")
            present = [str(single)] if single else []
        gap = _as_mapping(gaps.get(key))
        declared_missing = _str_list(gap.get("missing"))
        required_ids = _str_list(gap.get("required_list"))
        if not required_ids:
            # ``gaps`` only spells the full required list for the axis dimension; for the other
            # dimensions the registry is the real declaration of what could be covered.
            registry_kind = {"vessels": "vessel", "materials": "material", "patterns": "pattern",
                             "layer_combos": "layer_combo", "fracture_backends": "fracture_backend",
                             "axes": "axis"}.get(key, key)
            required_ids = _registry_ids(registry_kind)
        if not declared_missing and required_ids:
            declared_missing = sorted(set(required_ids) - set(present))
        covered[key] = sorted(set(present))
        missing[key] = declared_missing
    data_gaps: dict[str, Any] = {}
    for key, gap in gaps.items():
        entry = _as_mapping(gap)
        data_gaps[key] = {
            "target": entry.get("target"),
            "present": entry.get("present"),
            "shortfall": entry.get("shortfall"),
            "status": entry.get("status"),
            "missing": _str_list(entry.get("missing")),
        }
    return {
        "targets": {str(key): int(value) for key, value in targets.items() if isinstance(value, (int, float))},
        "covered": covered,
        "missing": missing,
        "gaps": data_gaps,
        "sources": [str(path)] if path else [],
        "note": ("覆盖值只来自 reports/coverage_aggregate.json（跨 run 聚合）或 reports/coverage.json；"
                 "两者都不存在时这里如实为空，不会用 registry 的目标数冒充已覆盖数"),
    }


# --------------------------------------------------------------------------- inventory
def _role_summary(rows: Sequence[Any], root: Path) -> dict[str, dict[str, int]]:
    """Assets and **real** payload bytes per role (one ``stat()`` pass per file)."""
    out: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for asset in rows:
        bucket = out.setdefault(asset.role, {"assets": 0, "bytes": 0})
        bucket["assets"] += 1
        for relative in (asset.files or {}).values():
            target = root / str(relative)
            if str(target) in seen:
                continue
            seen.add(str(target))
            try:
                if target.is_file():
                    bucket["bytes"] += target.stat().st_size
            except OSError:
                continue
    return {role: {"assets": int(bucket["assets"]), "bytes": int(bucket["bytes"])}
            for role, bucket in sorted(out.items())}


def _bucket_rows(rows: Sequence[Any], covered_ids: set[str]) -> list[dict[str, Any]]:
    """vessel × material × pattern buckets that really exist in the assets table."""
    buckets: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}
    for asset in rows:
        meta = _as_mapping(asset.meta)
        combo = COMBO_ID.search(str(meta.get("mother_id") or meta.get("event_id") or
                                   asset.lineage_id or ""))
        vessel = meta.get("vessel_id") or (combo.group(1) if combo else None)
        material = meta.get("material_id") or (combo.group(2) if combo else None)
        pattern = meta.get("family_id") or (combo.group(3) if combo else None)
        layer = meta.get("layer_combo_id")
        if not (vessel and material):
            continue
        key = (str(vessel), str(material), str(pattern) if pattern else "", str(layer) if layer else None)
        entry = buckets.setdefault(key, {
            "id": "|".join(part for part in key if part),
            "vessel_id": str(vessel), "material_id": str(material),
            "pattern_id": str(pattern) if pattern else None,
            "layer_combo_id": str(layer) if layer else None,
            "assets": 0, "fragments": 0, "lineages": set(), "runs": set(), "covered": False,
        })
        entry["assets"] += 1
        if asset.role == ROLE_FRAGMENT_MESH:
            entry["fragments"] += 1
        if asset.lineage_id:
            entry["lineages"].add(str(asset.lineage_id))
        run_id = meta.get("run_id")
        if run_id:
            entry["runs"].add(str(run_id))
    out: list[dict[str, Any]] = []
    for entry in buckets.values():
        entry["lineages"] = len(entry["lineages"])
        entry["runs"] = sorted(entry["runs"])
        entry["covered"] = bool(
            (entry["vessel_id"] in covered_ids) and (entry["material_id"] in covered_ids)
            if covered_ids else False
        )
        out.append(entry)
    out.sort(key=lambda item: (-int(item["fragments"]), -int(item["assets"]), str(item["id"])))
    return out


#: Roles that really carry the degradation identity (``meta.axis_id`` + ``level`` + ``basis_id``).
#: A derived display/presentation asset may repeat the axis/level token without being a
#: measurement — pairing one of those with a real measurement would report a difference that no
#: stage ever computed, so they are excluded from the pairing by role.
DEGRADATION_MEASUREMENT_ROLES: frozenset[str] = frozenset({
    "physical_component", "physical_result", "degrade_measurement", "obs_view", "obs_result",
})


def _degradation_identity(asset: Any) -> tuple[str, int, str, str] | None:
    """``(axis, level, basis, source)`` of a real degradation asset, or ``None``.

    Requires the axis/level token **and** at least one of basis/source: without a basis or a
    declared source there is nothing to pair on, and the row would otherwise be grouped under an
    empty key together with unrelated sources.
    """
    if asset.role not in DEGRADATION_MEASUREMENT_ROLES:
        return None
    meta = _as_mapping(asset.meta)
    axis_id = meta.get("axis_id")
    if not axis_id:
        return None
    try:
        level = int(meta.get("level"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    basis = str(meta.get("basis_id") or "")
    source = str(meta.get("source_asset_id") or "")
    if not basis and not source:
        return None
    return str(axis_id), level, basis, source


def _degradation_axes(rows: Sequence[Any]) -> list[dict[str, Any]]:
    axes: dict[str, dict[str, Any]] = {}
    for asset in rows:
        identity = _degradation_identity(asset)
        if identity is None:
            continue
        axis_id, level_int, basis, source = identity
        entry = axes.setdefault(axis_id, {"axis_id": axis_id, "levels": {}, "basis_ids": set(),
                                          "sources": set(), "roles": set()})
        bucket = entry["levels"].setdefault(level_int, {"level": level_int, "assets": 0, "identity": 0,
                                                       "measured_keys": set()})
        bucket["assets"] += 1
        if bool((asset.qa or {}).get("identity")):
            bucket["identity"] += 1
        measured = _as_mapping(asset.meta.get("measured"))
        bucket["measured_keys"].update(str(key) for key in measured)
        if basis:
            entry["basis_ids"].add(basis)
        if source:
            entry["sources"].add(source)
        entry["roles"].add(asset.role)
    out: list[dict[str, Any]] = []
    for entry in axes.values():
        levels = []
        for level_int in sorted(entry["levels"]):
            bucket = entry["levels"][level_int]
            levels.append({"level": level_int, "assets": bucket["assets"], "identity": bucket["identity"],
                           "measured_keys": sorted(bucket["measured_keys"])})
        materialized = len(levels) > 0
        note = (
            f"assets 表里出现 {len(entry['basis_ids'])} 个 basis_id"
            if materialized else "该轴没有任何已物化资产"
        )
        if materialized and len(entry["basis_ids"]) > 1:
            note += "（跨 basis：paired 比较必须锁定同一 basis_id）"
        out.append({
            "axis_id": entry["axis_id"],
            "levels": levels,
            "basis_ids": sorted(entry["basis_ids"]),
            "roles": sorted(entry["roles"]),
            "paired_levels": materialized and len(entry["basis_ids"]) == 1
            and len({row["level"] for row in levels if row["level"] > 0}) > 0
            and any(row["level"] == 0 for row in levels),
            "materialized": materialized,
            "note": note,
        })
    out.sort(key=lambda item: item["axis_id"])
    return out


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _delta_rows(level_0: Mapping[str, Any], level_n: Mapping[str, Any]) -> list[dict[str, Any]]:
    before = _as_mapping(level_0.get("measured"))
    after = _as_mapping(level_n.get("measured"))
    rows: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        left = _number(before.get(key))
        right = _number(after.get(key))
        rows.append({
            "key": str(key),
            "from": left,
            "to": right,
            "delta": (right - left) if (left is not None and right is not None) else None,
            "unit": "1",
        })
    return rows


def _pair_row(level_0: Any, level_n: Any) -> dict[str, Any]:
    meta_0 = _as_mapping(level_0.meta)
    meta_n = _as_mapping(level_n.meta)

    def side(asset: Any, meta: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "axis_id": meta.get("axis_id"),
            "level": meta.get("level"),
            "identity": asset.qa.get("identity"),
            "realized": asset.qa.get("realized"),
            "basis_id": meta.get("basis_id"),
            "asset_id": asset.asset_id,
            "role": asset.role,
            "meta": dict(meta),
            "measured": dict(_as_mapping(meta.get("measured"))),
        }

    basis_0 = str(meta_0.get("basis_id") or "") or None
    basis_n = str(meta_n.get("basis_id") or "") or None
    source_0 = str(meta_0.get("source_asset_id") or "") or None
    source_n = str(meta_n.get("source_asset_id") or "") or None
    paired = bool(basis_0) and basis_0 == basis_n
    same_source = bool(source_0) and source_0 == source_n
    note = (
        "L0 与 Ln 同 basis、同 source：这是真正 paired 的比较"
        if paired and same_source else
        "basis 相同但 source 不同（或缺失）：比较是跨来源的，页面对此如实标注"
        if paired else
        "basis_id 不一致：这两级不是 paired 的，差值不能当作同一 basis 上的退化量"
    )
    return {
        "pair_key": f"{meta_n.get('axis_id')}:{basis_n or source_n or 'nobasis'}",
        "axis_id": meta_n.get("axis_id"),
        "source_asset_id": source_n or source_0,
        "basis_id": basis_n or basis_0,
        "level_0": side(level_0, meta_0),
        "level_n": side(level_n, meta_n),
        "paired": paired,
        "same_source": same_source,
        "deltas": _delta_rows(meta_0, meta_n),
        "note": note,
    }


def _degradation_pairs(rows: Sequence[Any], axis_id: str | None) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for asset in rows:
        identity = _degradation_identity(asset)
        if identity is None:
            continue
        one_axis, level, basis, source = identity
        if axis_id and one_axis != axis_id:
            continue
        key = (one_axis, basis, source)
        entry = groups.setdefault(key, {"levels": {}, "sources": set(), "axis_id": one_axis,
                                        "basis_id": basis or None, "source": source or None})
        entry["sources"].add(asset.asset_id)
        # The highest level wins when a level was produced more than once (a re-run):
        # the newest asset of that level is the one a reviewer should be looking at.
        current = entry["levels"].get(level)
        if current is None or asset.created_at >= current.created_at:
            entry["levels"][level] = asset
    pairs: list[dict[str, Any]] = []
    for entry in groups.values():
        if 0 not in entry["levels"]:
            continue
        higher = sorted(level for level in entry["levels"] if level > 0)
        if not higher:
            continue
        pairs.append(_pair_row(entry["levels"][0], entry["levels"][higher[-1]]))
    pairs.sort(key=lambda item: (str(item["axis_id"]), str(item["basis_id"])))
    return pairs


# --------------------------------------------------------------------------- panel
def _bytes_for_assets(records: Sequence[Any], root: Path) -> int:
    """``stat()`` bytes of the payload files these asset records point at."""
    total = 0
    seen: set[str] = set()
    for record in records:
        for relative in (record.files or {}).values():
            target = root / str(relative)
            if str(target) in seen:
                continue
            seen.add(str(target))
            try:
                if target.is_file():
                    total += target.stat().st_size
            except OSError:
                continue
    return total


def _panel(rows: Sequence[Any], session: SessionDep, coverage: Mapping[str, Any]) -> dict[str, Any]:
    by_state: dict[str, int] = {}
    failure_codes: dict[str, dict[str, Any]] = {}
    with session.store.connect() as conn:
        for row in conn.execute("SELECT state, COUNT(*) AS n FROM jobs GROUP BY state"):
            by_state[str(row["state"])] = int(row["n"])
        for row in conn.execute(
            "SELECT job_id, error_json FROM jobs WHERE error_json IS NOT NULL AND error_json != '' LIMIT 5000"
        ):
            try:
                error = json.loads(row["error_json"])
            except (TypeError, ValueError):
                continue
            code = str(_as_mapping(error).get("code") or "UNKNOWN")
            entry = failure_codes.setdefault(code, {"code": code, "count": 0, "job_ids": [],
                                                    "retryable": None})
            entry["count"] += 1
            if len(entry["job_ids"]) < 10:
                entry["job_ids"].append(str(row["job_id"]))
            retryable = _as_mapping(error).get("retryable")
            if isinstance(retryable, bool):
                entry["retryable"] = retryable
        runs = int(conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"])
        events = int(conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"])
    planned = sum(by_state.values())
    attempted = sum(count for state, count in by_state.items()
                    if state not in ("PENDING", "BLOCKED", "CANCELLED"))
    accepted = sum(count for state, count in by_state.items()
                   if state in ("OUTPUT_READY", "QA_PASS", "COMMITTED"))
    failed = sum(count for state, count in by_state.items()
                 if state in ("FAILED", "QUARANTINED", "RETRYABLE"))
    pending = int(by_state.get("PENDING", 0)) + int(by_state.get("BLOCKED", 0))
    asset_count = len(rows)
    files, disk_bytes = _asset_bytes_for_records(session, rows)
    asset_ids = [asset.asset_id for asset in rows]
    codes = sorted(failure_codes.values(), key=lambda item: (-int(item["count"]), str(item["code"])))
    return {
        "planned": planned,
        "attempted": attempted,
        "accepted": accepted,
        "failed": failed,
        "pending": pending,
        "by_state": dict(sorted(by_state.items())),
        "failure_codes": codes,
        "disk_bytes": disk_bytes,
        "disk_files": files,
        "asset_count": asset_count,
        "runs": runs,
        "events": events,
        "note": ("planned/attempted/accepted/failed 全部由 jobs 表的权威 state 计数"
                 "（attempted = 已离开 PENDING/BLOCKED/CANCELLED 的 job；accepted = OUTPUT_READY/QA_PASS/COMMITTED）；"
                 "disk_bytes 是资产 payload 文件的 stat() 实测字节和，不是估算"),
    }


def _runs_summary(session: SessionDep, rows: Sequence[Any]) -> list[dict[str, Any]]:
    """Per-run asset/job accounting, with the real payload bytes of that run's assets."""
    root = session.store.root
    per_run: dict[str, dict[str, Any]] = {}
    by_id = {asset.asset_id: asset for asset in rows}
    for asset in rows:
        run_id = _as_mapping(asset.meta).get("run_id")
        if not run_id:
            continue
        entry = per_run.setdefault(str(run_id), {"run_id": str(run_id), "status": None, "jobs": 0,
                                                 "assets": 0, "bytes": 0, "asset_ids": []})
        entry["assets"] += 1
        entry["asset_ids"].append(asset.asset_id)
    with session.store.connect() as conn:
        for row in conn.execute("SELECT run_id, status FROM runs"):
            entry = per_run.setdefault(str(row["run_id"]), {"run_id": str(row["run_id"]), "status": None,
                                                            "jobs": 0, "assets": 0, "bytes": 0,
                                                            "asset_ids": []})
            entry["status"] = row["status"]
        for row in conn.execute("SELECT run_id, COUNT(*) AS n FROM jobs GROUP BY run_id"):
            entry = per_run.setdefault(str(row["run_id"]), {"run_id": str(row["run_id"]), "status": None,
                                                            "jobs": 0, "assets": 0, "bytes": 0,
                                                            "asset_ids": []})
            entry["jobs"] = int(row["n"])
    for entry in per_run.values():
        entry["bytes"] = _bytes_for_assets([by_id[item] for item in entry.pop("asset_ids")
                                            if item in by_id], root)
    return sorted(per_run.values(), key=lambda item: (-int(item["assets"]), str(item["run_id"])))


# --------------------------------------------------------------------------- routes
@router.get("/synthesis/inventory",
            summary="只读聚合：资产/磁盘/覆盖矩阵/退化配对/批处理计数（不建 run、不写资产）")
def get_inventory(session: SessionDep) -> dict[str, Any]:
    rows = _asset_rows(session)
    coverage = _coverage_dimensions(session)
    covered_ids = set(coverage["covered"].get("vessels", [])) | set(coverage["covered"].get("materials", []))
    field = "vessel_id+material_id+family_id"
    buckets = _bucket_rows(rows, covered_ids)
    backends: dict[str, dict[str, Any]] = {}
    for asset in rows:
        meta = _as_mapping(asset.meta)
        backend = meta.get("backend") if asset.role in (ROLE_FRAGMENT_MESH, "clean_truth") else None
        if not backend:
            continue
        entry = backends.setdefault(str(backend), {"backend": str(backend), "assets": 0, "qa_status": set()})
        entry["assets"] += 1
        entry["qa_status"].add(asset.qa_status)
    lineages = {str(asset.lineage_id) for asset in rows if asset.lineage_id}
    panel = _panel(rows, session, coverage)
    payload: dict[str, Any] = {
        "ok": True,
        "store_root": str(session.store.root),
        "assets_total": len(rows),
        "bytes_total": panel["disk_bytes"],
        "roles": _role_summary(rows, session.store.root),
        "lineages": len(lineages),
        "events": panel["events"],
        "runs": _runs_summary(session, rows),
        "fracture_backends": [
            {"backend": entry["backend"], "assets": entry["assets"],
             "qa_status": sorted(entry["qa_status"])}
            for entry in sorted(backends.values(), key=lambda item: str(item["backend"]))
        ],
        "buckets": {
            "field": field,
            "declared_field": "vessel_id / material_id / family_id（来自资产 meta）",
            "rows": buckets,
            "covered_ids": coverage["covered"].get("vessels", []),
            "missing_ids": coverage["missing"].get("vessels", []),
            "covered": len(coverage["covered"].get("vessels", [])),
            "target": coverage["targets"].get("vessels"),
            "source": (coverage["sources"] or [None])[0],
            "note": ("每个组合的 assets/fragments/lineages 都来自资产表；regime 覆盖标志取 "
                     "coverage aggregate 的 vessels/materials 集合。layer_combo_id 在已提交资产的 "
                     "meta 里不存在（后端 coverage sources 已说明它只出现在逐谱系 coverage rows），"
                     "因此这里如实为 null，而不是从 registry 猜一个"),
        },
        "coverage": coverage,
        "degradation_axes": _degradation_axes(rows),
        "degradation_pairs": _degradation_pairs(rows, None),
        "panel": panel,
        "empty_reason": None if rows else (
            "该 store 还没有任何资产：GET /assets 为空表示真的没有产出，不是被过滤掉了"
        ),
        "note": ("本端点是只读聚合，不创建 run、不写资产；所有计数来自 assets/runs/jobs/events 表与 "
                 "reports/*.json"),
    }
    return payload


@router.get("/synthesis/degradation-pairs",
            summary="同一 axis 的 L0 与 Ln 配对（同 basis、同 source，含真实 measured 差值）")
def get_degradation_pairs(session: SessionDep, axis_id: str | None = None) -> dict[str, Any]:
    rows = _asset_rows(session)
    axes = _degradation_axes(rows)
    if axis_id and not any(entry["axis_id"] == axis_id for entry in axes):
        raise ApiProblem(
            404, API_CODE_NOT_FOUND,
            f"axis {axis_id!r} has no materialized degradation asset in this store",
            stage="synthesis.degradation_pairs",
            details={"materialized_axes": [entry["axis_id"] for entry in axes],
                     "hint": "未物化的轴要在报告里显示 NA 并给出补齐命令，而不是编造预览"},
        )
    pairs = _degradation_pairs(rows, axis_id)
    return {
        "ok": True,
        "axis_id": axis_id,
        "pairs": pairs,
        "axes": axes,
        "empty_reason": None if pairs else (
            "没有可配对的轴：需要一个 axis 同时存在 level=0 与 level>0 的退化资产"
            "（degrade_measurement / physical_component 的 meta.axis_id + level）"
        ),
        "note": "pairs 只来自资产表里真实写入的 meta（axis_id/level/basis_id/source_asset_id/measured）",
        "repro": [
            "python -m synlab.api.worker --store-root <store> --once --workspace default",
        ],
    }


#: Realised (vessel, material, pattern) combinations are read from the ids the pipeline itself
#: stamps: ``mother_mesh.meta.mother_id`` = ``LIN0001_V21_M06_PAT16`` and
#: ``fragment_mesh.meta.event_id`` = ``LIN0004_V10_M06_PAT03_E01``.  Both spell the same triple,
#: so a batch planner can tell what already exists without inventing a mapping.
COMBO_ID = re.compile(r"(V\d{2})_(M\d{2})_(PAT\d{2})")


def _realized_combinations(rows: Sequence[Any]) -> set[tuple[str, str, str]]:
    """The (vessel, material, pattern) triples the store really realized."""
    found: set[tuple[str, str, str]] = set()
    for asset in rows:
        meta = _as_mapping(asset.meta)
        for key in ("mother_id", "event_id", "lineage_id", "fragment_id"):
            value = meta.get(key)
            if value:
                found.update(COMBO_ID.findall(str(value)))
        if asset.lineage_id:
            found.update(COMBO_ID.findall(str(asset.lineage_id)))
        if meta.get("vessel_id") and meta.get("material_id") and meta.get("family_id"):
            found.add((str(meta["vessel_id"]), str(meta["material_id"]), str(meta["family_id"])))
    return found


@router.post("/synthesis/batch-plan",
             summary="按覆盖矩阵选出下一批组合，产出可直接提交的 spec 与续跑游标")
def post_batch_plan(session: SessionDep, body: BatchPlanEnvelope) -> dict[str, Any]:
    validation = validate_spec(body.spec or {}, kind="generation", registry_check=True)
    if not validation["ok"]:
        raise ApiProblem(422, "SCHEMA_INVALID",
                         f"spec rejected: {len(validation['errors'])} error(s)",
                         stage="synthesis.batch_plan", details={"validation": validation})
    spec = dict(body.spec)
    dataset = dict(_as_mapping(spec.get("dataset")))
    coverage = _coverage_dimensions(session)
    vessels = _registry_ids("vessel") or _str_list(dataset.get("vessel_ids"))
    materials = _registry_ids("material") or _str_list(dataset.get("material_ids"))
    patterns = _registry_ids("pattern") or _str_list(dataset.get("pattern_ids"))
    layers = _registry_ids("layer_combo")
    if not (vessels and materials and patterns):
        raise ApiProblem(
            409, "REGISTRY_EMPTY",
            "registry does not declare vessel/material/pattern ids; a batch plan cannot enumerate "
            "combinations without the real declaration",
            stage="synthesis.batch_plan",
            details={"vessels": len(vessels), "materials": len(materials), "patterns": len(patterns)},
        )
    space: list[tuple[str, str, str, str | None]] = []
    for vessel, material, pattern in itertools.product(vessels, materials, patterns):
        space.append((vessel, material, pattern, None))
    if len(space) > MAX_COMBINATIONS:
        raise ApiProblem(409, "COVERAGE_SPACE_TOO_LARGE",
                         f"combination space {len(space)} exceeds {MAX_COMBINATIONS}",
                         stage="synthesis.batch_plan")

    rows = _asset_rows(session)
    existing = _realized_combinations(rows)

    batch_size = body.batch_size
    requested = body.requested
    start = body.cursor or 0
    notes: list[str] = []
    if body.resume:
        # ``--resume`` semantics: skip what the store already realized and continue from the
        # first combination that is not in the assets table, not from the client's cursor.
        already = 0
        first_free = None
        for index, combo in enumerate(space):
            if (combo[0], combo[1], combo[2]) in existing:
                already += 1
                continue
            if first_free is None:
                first_free = index
        start = first_free if first_free is not None else len(space)
        notes.append(
            f"resume：组合空间里已实现 {already} 个组合，cursor 推进到第一个未实现组合 {start}"
        )
    selected = space[start:start + max(batch_size, requested)]
    combos = [
        {"index": start + offset, "vessel_id": combo[0], "material_id": combo[1],
         "pattern_id": combo[2], "layer_combo_id": combo[3]}
        for offset, combo in enumerate(selected)
    ]
    next_cursor = start + len(selected)
    next_vessels = sorted({combo[0] for combo in space[start:next_cursor]}) or list(dataset.get("vessel_ids") or [])
    next_materials = sorted({combo[1] for combo in space[start:next_cursor]}) or list(dataset.get("material_ids") or [])
    next_patterns = sorted({combo[2] for combo in space[start:next_cursor]}) or list(dataset.get("pattern_ids") or [])
    pending = max(0, len(space) - len(existing))
    spec_hash = None
    applied: dict[str, Any] = {}
    if combos:
        dataset.update({
            "vessel_ids": next_vessels,
            "material_ids": next_materials,
            "pattern_ids": next_patterns,
            "target_mothers": max(1, len(next_vessels)),
        })
        layers_declared = _str_list(dataset.get("layer_combo_ids")) or layers[:1]
        if layers_declared:
            dataset["layer_combo_ids"] = layers_declared
        spec.update({"dataset": dataset})
        recheck = validate_spec(spec, kind="generation", registry_check=True)
        spec_hash = recheck["spec_hash"]
        applied = {"vessel_ids": next_vessels, "material_ids": next_materials,
                   "pattern_ids": next_patterns,
                   "layer_combo_ids": list(dataset.get("layer_combo_ids") or [])}
        notes.append(
            f"本批 {len(combos)} 个组合 → dataset 展开为 {len(next_vessels)}×{len(next_materials)}×{len(next_patterns)}"
        )
    return {
        "ok": True,
        "stage": "generate",
        "spec_hash": spec_hash,
        "next_cursor": next_cursor,
        "requested": requested,
        "selected": len(combos),
        "pending_combinations": pending,
        "combinations": combos,
        "applied_combo": applied,
        "spec": spec if combos else {},
        "coverage_source": (coverage["sources"] or [None])[0],
        "budget": None,
        "empty_reason": None if combos else (
            "组合空间已经走完：按 assets 表的 vessel/material/pattern 去重后没有剩余组合，"
            "继续跑不会新增覆盖"
        ),
        "resume": {
            "requested": body.resume,
            "semantics": ("resume=true 时忽略客户端 cursor：后端按 assets 表里已实现的组合推进到第一个未实现组合；"
                          "resume=false 时严格从 cursor 开始，允许重跑已有组合（幂等键不同即为新 run）"),
            "next_from": start,
            "already_covered": len(existing),
            "completed_assets": len(rows),
            "note": " | ".join(notes) or "未请求 resume",
        },
        "repro": [
            "python tests/a12/api_ui/_serve.py --store-root <store> --port 8077 --role researcher",
            f"curl -s -X POST http://127.0.0.1:8077/api/synlab/synthesis/batch-plan -H 'Content-Type: application/json' "
            f"-d '{{\"spec\": <spec>, \"cursor\": {next_cursor}, \"resume\": true}}'",
        ],
    }


# --------------------------------------------------------------------------- chain preview
def _events_for(session: SessionDep, run_id: str, limit: int = 400) -> list[dict[str, Any]]:
    """Ordered events of one run.  The store spells the cursor ``event_seq`` (see ``api/tables``)."""
    with session.store.connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
        key = "seq" if "seq" in columns else "event_seq"
        rows = conn.execute(
            f"SELECT {key} AS seq, revision, type, state, message, created_at FROM events "
            "WHERE run_id = ? ORDER BY event_seq ASC LIMIT ?", (run_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _jobs_for(session: SessionDep, run_id: str) -> list[Any]:
    return list(session.scheduler.list_jobs(run_id=run_id, limit=200))


def _step_rows(session: SessionDep, jobs: Sequence[Any]) -> list[dict[str, Any]]:
    """Per-stage rows from the **job** path (``POST /jobs`` + worker)."""
    steps: list[dict[str, Any]] = []
    for job in jobs:
        outputs = list(job.outputs or [])
        files, total = _asset_bytes(session, outputs)
        with session.store.connect() as conn:
            row = conn.execute(
                "SELECT MIN(created_at) AS first, MAX(created_at) AS last FROM events WHERE job_id = ?",
                (job.job_id,),
            ).fetchone()
        first = _iso_seconds(row["first"]) if row else None
        last = _iso_seconds(row["last"]) if row else None
        steps.append({
            "node_id": str(_as_mapping(job.spec).get("node_id") or job.job_id),
            "stage": job.stage,
            "job_id": job.job_id,
            "state": job.state,
            "attempt": int(job.attempt),
            "outputs": len(outputs),
            "output_bytes": total if files else 0,
            "seconds": (last - first) if (first is not None and last is not None) else None,
            "error": job.error,
        })
    steps.sort(key=lambda item: (item["node_id"], item["job_id"]))
    return steps


def _pipeline_step_rows(session: SessionDep, run_id: str,
                        stage_seconds: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Per-stage rows from the **pipeline** path (``synlab.pipeline.build_one_mother``).

    ``stage_seconds`` is the real ``perf_counter`` delta the pipeline recorded for each stage of
    this one lineage; the asset count/bytes next to it are read back from the store for this run,
    so the table shows what each step actually produced.
    """
    rows: list[dict[str, Any]] = []
    role_by_stage = {
        "mother": {"mother_mesh", "material_profile"},
        "material": {"material_profile"},
        "pattern": {"pattern_recipe", "pattern_channels"},
        "fracture": {"fragment_mesh", "clean_truth"},
        "clean_truth": {"clean_truth"},
        "physical": {"physical_component", "physical_result", "physical_truth"},
        "observe": {"obs_view", "obs_result", "obs_fused_geometry", "visible_labels"},
        "feature": {"feature_bundle"},
        "labels": {"label_bundle", "visible_labels"},
        "provenance": {"provenance"},
        "context": {"context_pack"},
    }
    run_assets = [asset for asset in session.store.list_assets(limit=200000)
                  if str(_as_mapping(asset.meta).get("run_id") or "") == run_id]
    for stage, seconds in stage_seconds.items():
        wanted = role_by_stage.get(str(stage), set())
        selected = [asset for asset in run_assets if asset.role in wanted] if wanted else []
        files, total = _asset_bytes_for_records(session, selected)
        rows.append({
            "stage": str(stage),
            "seconds": _iso_seconds(seconds),
            "outputs": len(selected),
            "output_bytes": total if files else 0,
            "asset_ids": [asset.asset_id for asset in selected],
            "roles": sorted({asset.role for asset in selected}),
            "state": "OK" if selected else "NO_ASSET",
            "error": None,
        })
    return rows


def _worker_command(session: SessionDep, *, workspace: str, max_jobs: int, timeout_seconds: float) -> list[str]:
    return [
        str(sys.executable), "-m", "synlab.api.worker",
        "--store-root", str(session.store.root),
        "--once", "--max-jobs", str(max_jobs),
        "--workspace", workspace,
        "--json", "--quiet",
        "--lease-seconds", str(max(60.0, timeout_seconds)),
    ]


def _spawn_worker(command: Sequence[str], *, timeout_seconds: float) -> dict[str, Any]:
    """Run one ``--once`` worker to completion inside this request (job-queue preview mode).

    The child's stdout/stderr are captured as **bytes** and decoded here: the worker prints
    UTF-8 (and may print non-ASCII), while this host's default codec is GBK, and a text-mode
    pipe would raise ``UnicodeDecodeError`` inside ``communicate()``.
    """
    started = time.time()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    kwargs: dict[str, Any] = {
        "cwd": str(Path(__file__).resolve().parents[3]),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": env,
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
    process = subprocess.Popen(list(command), **kwargs)  # noqa: S603 - fixed argv, no shell

    def _text(raw: bytes | None, keep: int) -> str:
        return (raw or b"").decode("utf-8", "replace")[-keep:]

    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return {"ok": process.returncode == 0, "exit": process.returncode,
                "seconds": time.time() - started, "command": " ".join(command),
                "stdout": _text(stdout, 4000), "stderr": _text(stderr, 4000)}
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        return {"ok": False, "exit": None, "seconds": time.time() - started,
                "command": " ".join(command), "stdout": _text(stdout, 2000),
                "stderr": _text(stderr, 4000) + "\n[killed after timeout]"}


def _wait_for_run(session: SessionDep, run_id: str, *, deadline: float) -> tuple[bool, dict[str, Any]]:
    """Poll the real job rows until the run settled or the deadline passed.

    ``True`` means every job of the run reached a terminal state.  A DAG whose remaining jobs can
    never become ready (all BLOCKED/CANCELLED) also settles — reported as ``False`` — so a blocked
    queue cannot hang the request.
    """
    last: dict[str, Any] = {}
    while True:
        jobs = _jobs_for(session, run_id)
        states = {job.state for job in jobs}
        last = {"jobs": len(jobs), "states": sorted(states)}
        if jobs and states <= TERMINAL_STATES:
            return True, last
        if jobs and states <= (TERMINAL_STATES | {"BLOCKED", "CANCELLED"}):
            return False, last
        if time.time() >= deadline:
            return False, last
        time.sleep(0.4)


@router.post("/synthesis/chain-preview",
             summary="同步跑一条真实谱系（target_mothers=1）并返回各阶段结果与实测耗时")
def post_chain_preview(session: SessionDep, body: ChainPreviewEnvelope) -> dict[str, Any]:
    """One real lineage, synchronously, with the real per-stage outcome.

    ``mode="pipeline"`` (default) runs ``synlab.pipeline.build_one_mother`` — the same façade chain
    ``tools/batch_generate.py`` drives — so the preview produces real assets, real per-stage
    ``perf_counter`` timings and a real coverage row.  ``mode="jobs"`` instead enqueues through the
    existing ``POST /jobs`` and (optionally) drains the queue with one ``synlab.api.worker --once``
    subprocess; on this build the job handlers are capability-gated and answer
    ``INTEGRATION_PENDING``, which the response reports verbatim.
    """
    validation = validate_spec(body.spec or {}, kind="generation", registry_check=True)
    if not validation["ok"]:
        raise ApiProblem(422, "SCHEMA_INVALID",
                         f"spec rejected: {len(validation['errors'])} error(s)",
                         stage="synthesis.chain_preview", details={"validation": validation})
    from ...config import compile_spec
    from ...pipeline import build_one_mother, plan_generation
    from ...schemas.spec import GenerationSpec
    from ...storage.store import AssetStore

    spec_dict = dict(body.spec)
    dataset = dict(_as_mapping(spec_dict.get("dataset")))
    dataset["target_mothers"] = 1
    if not dataset.get("vessel_ids"):
        dataset["vessel_ids"] = _registry_ids("vessel")[:1]
    if not dataset.get("material_ids"):
        dataset["material_ids"] = _registry_ids("material")[:1]
    if not dataset.get("pattern_ids"):
        dataset["pattern_ids"] = _registry_ids("pattern")[:1]
    spec_dict["dataset"] = dataset

    try:
        model = GenerationSpec.model_validate(spec_dict)
    except Exception as exc:  # noqa: BLE001 - pydantic errors must surface as a real 422
        raise ApiProblem(422, "SCHEMA_INVALID",
                         f"spec rejected by the generation schema: {exc}",
                         stage="synthesis.chain_preview") from exc
    registry_ids = {kind: _registry_ids(kind) for kind in
                    ("vessel", "material", "pattern", "layer_combo")}
    compiled = compile_spec(model, registry_ids={key: value for key, value in registry_ids.items() if value})
    if not compiled.ok:
        raise ApiProblem(422, "SCHEMA_INVALID",
                         f"spec rejected by the compiler: {'; '.join(compiled.errors[:4])}",
                         stage="synthesis.chain_preview",
                         details={"errors": compiled.errors, "warnings": compiled.warnings})
    plan = plan_generation(compiled.spec, max_mothers=1)
    run_id = f"run_{plan.job_id.split('_', 1)[-1][:16]}"
    repro = [
        "python tools/batch_generate.py --config configs/a12/realistic.yaml --root "
        f"{session.store.root} --batch 1 --only 1",
        f"python -m synlab.api.worker --store-root {session.store.root} --once "
        f"--workspace {session.workspace}",
    ]

    if body.mode == "jobs":
        return _chain_preview_via_jobs(session, body, spec_dict, validation, repro)

    started = time.time()
    store = AssetStore(session.store.root)
    mode = "pipeline"
    run_created = False
    try:
        store.get_run(run_id)
    except SynLabError:
        store.create_run(run_id, plan.spec_hash, compiled.spec.data_scope.value,
                         compiled.spec.release_profile.value,
                         meta={"workspace": session.workspace, "stage": "synthesis.chain_preview",
                               "spec_hash": plan.spec_hash, "mode": mode})
        run_created = True
    plan_path = store.root / "reports" / f"run_spec_{run_id}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps({**plan.as_dict(), "plan": [vars(lineage) for lineage in plan.lineages]},
                                    ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    attempt = {"run_id": run_id, "ok": False, "error": None, "assets": [], "asset_files": 0,
               "asset_bytes": 0, "stages": [], "wall_seconds": 0.0}
    for retry in range(body.max_retries + 1):
        attempt_started = time.time()
        outcome = build_one_mother(plan, plan.lineages[0], store, run_id=run_id, degrade_cfg=None,
                                   total_lineages=1)
        row = _as_mapping(outcome.get("coverage_row"))
        stage_seconds = _as_mapping(row.get("stages"))
        if outcome.get("ok"):
            attempt = {
                "run_id": run_id, "ok": True, "error": None,
                "wall_seconds": time.time() - attempt_started,
                "stages": _pipeline_step_rows(session, run_id, stage_seconds),
                "coverage_row": dict(row),
                "retry": retry,
            }
            break
        attempt = {
            "run_id": run_id, "ok": False,
            "error": dict(_as_mapping(outcome.get("error"))),
            "wall_seconds": time.time() - attempt_started,
            "stages": _pipeline_step_rows(session, run_id, stage_seconds),
            "coverage_row": dict(row),
            "retry": retry,
        }
    wall = time.time() - started

    lineage_assets = [asset for asset in store.list_assets(limit=200000)
                      if str(_as_mapping(asset.meta).get("run_id") or "") == run_id]
    asset_dicts: list[dict[str, Any]] = []
    for asset in lineage_assets:
        item = asset.as_dict()
        item.pop("path", None)
        asset_dicts.append(item)
    files, total = _asset_bytes_for_records(session, lineage_assets)
    try:
        store.set_run_status(run_id, "QA_PASSED" if attempt["ok"] else "FAILED",
                             meta={"workspace": session.workspace,
                                   "accepted": 1 if attempt["ok"] else 0, "attempted": 1})
    except SynLabError:
        pass

    blocked = None
    if not attempt["ok"]:
        error = _as_mapping(attempt.get("error"))
        blocked = {
            "code": str(error.get("code") or "CHAIN_PREVIEW_FAILED"),
            "stage": str(error.get("stage") or "pipeline"),
            "message": str(error.get("message") or "该谱系未完成"),
            "attempts": body.max_retries + 1,
            "outputs": len(asset_dicts),
            "output_bytes": total,
            "repro": repro,
            "hint": ("这是真实管线的拒绝/失败：code 与 stage 来自 synlab 的错误信封。"
                     "先按 repro 跑一次同一谱系，再看 reports/coverage.json 里的 failures"),
            "note": "mode=pipeline 直接调用 façade 链，不经过 job handler 的能力门",
        }
    return {
        "ok": True,
        "mode": mode,
        "executed": bool(attempt["ok"]),
        "state": "COMMITTED" if attempt["ok"] else "FAILED",
        "run_id": run_id,
        "run_created": run_created,
        "spec_hash": plan.spec_hash,
        "validate": validation,
        "lineage_id": plan.lineages[0].lineage_id,
        "vessel_id": plan.lineages[0].vessel_id,
        "material_id": plan.lineages[0].material_id,
        "pattern_id": plan.lineages[0].pattern_id,
        "stages": attempt["stages"],
        "steps": attempt["stages"],
        "assets": asset_dicts,
        "asset_files": files,
        "asset_bytes": total,
        "wall_seconds": wall,
        "stage_wall_seconds": attempt.get("wall_seconds"),
        "retry": attempt.get("retry"),
        "coverage_row": attempt.get("coverage_row") or {},
        "coverage_ref": str(store.root / "reports" / "coverage.json"),
        "run_spec_ref": str(plan_path),
        "events": _events_for(session, run_id),
        "blocked": blocked,
        "repro": repro,
        "note": ("mode=pipeline：直接调用 synlab.pipeline.build_one_mother 跑完一条真实谱系"
                 "（母体→纹样→断裂→真值→物理损伤→退化→观测→特征/标注/provenance→出土上下文），"
                 "资产真实写入 store 并带 run_id 归属；阶段耗时是管线内部的 perf_counter 实测值"),
        "timing_note": ("stages[].seconds 来自管线对该阶段的 perf_counter 差值（实测）；"
                        "wall_seconds 是本次请求端到端耗时；outputs/output_bytes 是阶段产出资产个数与 "
                        "payload 的 stat() 字节和"),
    }


def _chain_preview_via_jobs(
    session: SessionDep,
    body: "ChainPreviewEnvelope",
    spec: dict[str, Any],
    validation: dict[str, Any],
    repro: list[str],
) -> dict[str, Any]:
    """The job-queue variant: ``POST /jobs`` (+ optional one-shot worker) instead of the façade."""
    from .jobs import post_jobs

    key = body.idempotency_key or (
        "chainpreview:" + hash_json({"spec": spec, "max_retries": body.max_retries}).split(":", 1)[-1][:48]
    )
    accepted = post_jobs(session, JobCreateEnvelope(
        schema_version="synlab.v3", spec=spec, stage="generate",
        planned_jobs=1, idempotency_key=key,
    ))
    run_id = accepted["run_id"]
    command = _worker_command(session, workspace=session.workspace,
                              max_jobs=max(1, len(accepted.get("job_ids") or [1]) * (body.max_retries + 1)),
                              timeout_seconds=body.timeout_seconds)
    repro = [" ".join(command), *repro]
    started = time.time()
    runner: dict[str, Any] | None = None
    completed = False
    if body.run:
        runner = _spawn_worker(command, timeout_seconds=body.timeout_seconds)
        completed, _ = _wait_for_run(session, run_id,
                                     deadline=started + max(1.0, body.timeout_seconds - 1.0))
    wall = time.time() - started
    jobs = _jobs_for(session, run_id)
    steps = _step_rows(session, jobs)
    assets: list[dict[str, Any]] = []
    for job in jobs:
        for asset_id in job.outputs or []:
            try:
                record = session.store.get_asset(asset_id)
            except SynLabError:
                continue
            item = record.as_dict()
            item.pop("path", None)
            assets.append(item)
    files, total = _asset_bytes(session, [item["asset_id"] for item in assets])
    states = sorted({job.state for job in jobs})
    failed = [job for job in jobs if job.state in ("FAILED", "QUARANTINED")]
    error = _as_mapping(failed[0].error) if failed else {}
    blocked: dict[str, Any] | None = None
    if not completed:
        blocked = {
            "code": str(error.get("code") or ("CHAIN_PREVIEW_FAILED" if failed else "CHAIN_PREVIEW_INCOMPLETE")),
            "stage": str(error.get("stage") or "synthesis.chain_preview"),
            "message": (str(error.get("message"))
                        or f"job 路径未跑完谱系：states={states}"),
            "job_id": accepted["job_id"],
            "states": states,
            "outputs": len(assets),
            "output_bytes": total,
            "runner": runner,
            "repro": repro,
            "hint": ("job 路径的每个阶段都由 synlab.api.worker 里的 handler 执行；"
                     "handler 对未接线的 façade 会返回 INTEGRATION_PENDING（见 FROZEN_CALLS）"),
            "note": "run=false 时不会启动 worker，blocked 只反映真实队列状态",
        }
    return {
        "ok": True,
        "mode": "jobs",
        "executed": bool(body.run and completed),
        "state": jobs[0].state if jobs else accepted.get("status"),
        "run_id": run_id,
        "job_id": accepted["job_id"],
        "job_ids": accepted.get("job_ids") or [accepted["job_id"]],
        "spec_hash": validation["spec_hash"],
        "validate": validation,
        "dag": accepted.get("dag") or [],
        "stages": steps,
        "steps": steps,
        "assets": assets,
        "asset_files": files,
        "asset_bytes": total,
        "wall_seconds": wall,
        "events": _events_for(session, run_id),
        "idempotent_replay": bool(accepted.get("idempotent_replay")),
        "created": bool(accepted.get("created")),
        "blocked": blocked,
        "repro": repro,
        "note": "mode=jobs：走既有 POST /jobs + synlab.api.worker 路径，state 是 worker 写下的权威值",
        "timing_note": "stages[].seconds 由 events 表里该 job 的首/末事件 created_at 相减得到（实测）",
    }


__all__ = ["router"]
