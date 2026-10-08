"""Stable keyset pagination for list routes (plan 21.1: fixed cap, no full-database scans).

The cursor is an opaque base64url token holding the last ``(created_at, id)`` pair seen.
Because ordering is ``created_at ASC, id ASC`` and the cursor is a *keyset* rather than an
offset, inserting new rows while a client pages cannot duplicate or skip items.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Iterable, Sequence

from ..storage.store import AssetStore
from .problems import API_CODE_INVALID_CURSOR, ApiProblem

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
ORDER = "created_at.asc,id.asc"
CURSOR_VERSION = 1


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    try:
        value = int(limit)
    except (TypeError, ValueError):
        raise ApiProblem(400, "BAD_REQUEST", "limit must be an integer", stage="pagination.limit")
    if value < 1:
        raise ApiProblem(400, "BAD_REQUEST", "limit must be >= 1", stage="pagination.limit")
    return min(value, MAX_LIMIT)


def encode_cursor(kind: str, created_at: float, row_id: str) -> str:
    payload = json.dumps({"v": CURSOR_VERSION, "kind": kind, "t": created_at, "id": row_id},
                         separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None, kind: str) -> tuple[float, str] | None:
    if cursor is None or cursor == "":
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ApiProblem(400, API_CODE_INVALID_CURSOR, f"cursor is not decodable: {exc}",
                         stage="pagination.cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise ApiProblem(400, API_CODE_INVALID_CURSOR, "unsupported cursor version",
                         stage="pagination.cursor")
    if payload.get("kind") != kind:
        raise ApiProblem(400, API_CODE_INVALID_CURSOR,
                         f"cursor was issued for {payload.get('kind')!r}, not {kind!r}",
                         stage="pagination.cursor")
    try:
        return float(payload["t"]), str(payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiProblem(400, API_CODE_INVALID_CURSOR, "cursor payload is incomplete",
                         stage="pagination.cursor") from exc


def page_envelope(items: list[dict[str, Any]], *, kind: str, limit: int, has_more: bool,
                  total: int | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    last = items[-1] if items else None
    next_cursor = None
    if has_more and last is not None:
        next_cursor = encode_cursor(kind, float(last["created_at"]), str(last["_sort_id"]))
    out: dict[str, Any] = {
        "kind": kind,
        "order": ORDER,
        "limit": limit,
        "count": len(items),
        "has_more": bool(has_more),
        "next_cursor": next_cursor,
        "items": [{k: v for k, v in item.items() if k != "_sort_id"} for item in items],
    }
    if total is not None:
        out["total"] = total
    if extra:
        out.update(extra)
    return out


def _keyset_clause(alias_pk: str, cursor: tuple[float, str] | None) -> tuple[str, list[Any]]:
    if cursor is None:
        return "", []
    return f" AND (created_at > ? OR (created_at = ? AND {alias_pk} > ?))", [cursor[0], cursor[0], cursor[1]]


# --------------------------------------------------------------------------- assets
def page_assets(
    store: AssetStore,
    *,
    roles: Sequence[str] | None = None,
    exclude_roles: Iterable[str] = (),
    lineage_id: str | None = None,
    split: str | None = None,
    qa_status: str | None = None,
    workspace: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    with_total: bool = False,
) -> dict[str, Any]:
    """Keyset page over ``assets`` with server-side role/workspace filtering."""
    resolved_limit = clamp_limit(limit)
    keyset, params = _keyset_clause("asset_id", decode_cursor(cursor, "asset"))

    query = "SELECT * FROM assets WHERE 1=1"
    filters: list[Any] = []
    if roles:
        query += f" AND role IN ({','.join('?' for _ in roles)})"
        filters.extend(roles)
    excluded = [r for r in exclude_roles if r]
    if excluded:
        query += f" AND role NOT IN ({','.join('?' for _ in excluded)})"
        filters.extend(excluded)
    if lineage_id:
        query += " AND lineage_id = ?"
        filters.append(lineage_id)
    if split:
        query += " AND split = ?"
        filters.append(split)
    if qa_status:
        query += " AND qa_status = ?"
        filters.append(qa_status)

    query += keyset
    query += " ORDER BY created_at ASC, asset_id ASC LIMIT ?"
    all_params = filters + params + [resolved_limit + 1]

    with store.connect() as conn:
        rows = conn.execute(query, all_params).fetchall()
        total = None
        if with_total:
            # Explicit opt-in only: the total needs the workspace filter applied row by row
            # because workspace is carried in meta_json, which SQLite cannot index here.
            total = 0
            count_rows = conn.execute(
                "SELECT meta_json FROM assets WHERE 1=1"
                + ("".join([" AND role IN (" + ",".join("?" for _ in roles) + ")"] if roles else []))
                + ("".join([" AND role NOT IN (" + ",".join("?" for _ in exclude_roles) + ")"] if exclude_roles else [])),
                list(roles or []) + list(exclude_roles),
            ).fetchall()
            for count_row in count_rows:
                meta = json.loads(count_row["meta_json"] or "{}")
                if workspace is not None and meta.get("workspace", "default") != workspace:
                    continue
                total += 1

    records = [dict(r) for r in rows]
    # workspace isolation: a session only sees assets stamped with its workspace
    # (assets committed without a stamp belong to the default workspace).
    kept: list[dict[str, Any]] = []
    for row in records:
        meta = json.loads(row.get("meta_json") or "{}")
        row_ws = meta.get("workspace", "default")
        if workspace is not None and row_ws != workspace:
            continue
        row["meta"] = meta
        row["files"] = json.loads(row.pop("files_json") or "{}")
        row["qa"] = json.loads(row.pop("qa_json") or "{}")
        row["ancestry"] = json.loads(row.pop("ancestry_json") or "[]")
        row.pop("meta_json", None)
        row["_sort_id"] = row["asset_id"]
        kept.append(row)

    has_more = len(kept) > resolved_limit
    kept = kept[:resolved_limit]
    return page_envelope(kept, kind="asset", limit=resolved_limit, has_more=has_more, total=total,
                         extra={"workspace": workspace})


# --------------------------------------------------------------------------- jobs
def page_jobs(
    store: AssetStore,
    *,
    run_id: str | None = None,
    states: Sequence[str] | None = None,
    stage: str | None = None,
    workspace: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    with_total: bool = False,
) -> dict[str, Any]:
    resolved_limit = clamp_limit(limit)
    items: list[dict[str, Any]] = []
    scanned = 0
    scan_cap = 5000
    next_cursor = cursor
    has_more = False
    while len(items) <= resolved_limit and scanned < scan_cap:
        keyset, params = _keyset_clause("job_id", decode_cursor(next_cursor, "job"))
        query = "SELECT * FROM jobs WHERE 1=1"
        filters: list[Any] = []
        if run_id:
            query += " AND run_id = ?"
            filters.append(run_id)
        if states:
            query += f" AND state IN ({','.join('?' for _ in states)})"
            filters.extend(states)
        if stage:
            query += " AND stage = ?"
            filters.append(stage)
        query += keyset
        query += " ORDER BY created_at ASC, job_id ASC LIMIT ?"
        with store.connect() as conn:
            rows = conn.execute(query, filters + params + [resolved_limit + 1]).fetchall()
        if not rows:
            break
        for row in rows:
            scanned += 1
            item = dict(row)
            item["spec"] = json.loads(item.pop("spec_json") or "{}")
            item["inputs"] = json.loads(item.pop("inputs_json") or "[]")
            item["outputs"] = json.loads(item.pop("output_json") or "[]")
            item["error"] = json.loads(item.pop("error_json") or "null")
            item["_sort_id"] = item["job_id"]
            row_ws = (item["spec"] or {}).get("workspace", "default")
            if workspace is not None and row_ws != workspace:
                continue
            items.append(item)
        next_cursor = encode_cursor("job", float(rows[-1]["created_at"]), str(rows[-1]["job_id"]))
        if len(rows) <= resolved_limit:
            break
    total = None
    if with_total:
        with store.connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) AS n FROM jobs WHERE 1=1", []).fetchone()["n"])
    has_more = len(items) > resolved_limit
    return page_envelope(items[:resolved_limit], kind="job", limit=resolved_limit,
                         has_more=has_more, total=total,
                         extra={"workspace": workspace, "scanned": scanned})
