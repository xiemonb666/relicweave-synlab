"""API-owned metadata tables.

These tables are created with ``CREATE TABLE IF NOT EXISTS`` through the asset store's
public ``connect()``; the store's own schema is never altered.  They hold long-lived
records that are not assets (audits, exports, camera profiles, pools, training /
diagnostics runs, episodes) so that "not run yet" is represented as a durable row with
status ``NOT_RUN`` rather than as an invented result.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from ..errors import ErrorCode, SynLabError
from ..storage.store import AssetStore

API_SCHEMA_VERSION = "synlab.api.v1"

DDL = """
CREATE TABLE IF NOT EXISTS api_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_audits (
    audit_id TEXT PRIMARY KEY,
    run_id TEXT,
    release_id TEXT,
    scope_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    job_id TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    error_json TEXT,
    workspace TEXT NOT NULL DEFAULT 'default',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_audits_created ON api_audits(created_at);
CREATE TABLE IF NOT EXISTS api_exports (
    export_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    adapter TEXT NOT NULL,
    status TEXT NOT NULL,
    job_id TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    error_json TEXT,
    workspace TEXT NOT NULL DEFAULT 'default',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_camera_profiles (
    profile_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    tier TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    calibration_source TEXT,
    workspace TEXT NOT NULL DEFAULT 'default',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_pools (
    pool_id TEXT PRIMARY KEY,
    release_id TEXT,
    spec_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    job_id TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    error_json TEXT,
    workspace TEXT NOT NULL DEFAULT 'default',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_training_runs (
    training_run_id TEXT PRIMARY KEY,
    release_id TEXT,
    spec_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    job_id TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    error_json TEXT,
    workspace TEXT NOT NULL DEFAULT 'default',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_diagnostics_runs (
    diagnostics_run_id TEXT PRIMARY KEY,
    protocol_id TEXT,
    spec_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    job_id TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    error_json TEXT,
    workspace TEXT NOT NULL DEFAULT 'default',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_episodes (
    episode_id TEXT PRIMARY KEY,
    spec_json TEXT NOT NULL DEFAULT '{}',
    state_json TEXT NOT NULL DEFAULT '{}',
    observation_json TEXT NOT NULL DEFAULT '{}',
    steps_json TEXT NOT NULL DEFAULT '[]',
    cost_total REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    workspace TEXT NOT NULL DEFAULT 'default',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_file_integrity (
    asset_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    source TEXT NOT NULL,
    first_seen_at REAL NOT NULL,
    last_verified_at REAL NOT NULL,
    PRIMARY KEY (asset_id, file_name)
);
"""

#: columns per table, used by the generic helpers
TABLES: dict[str, tuple[str, ...]] = {
    "api_audits": ("audit_id", "run_id", "release_id", "scope_json", "status", "job_id",
                   "result_json", "error_json", "workspace", "created_at", "updated_at"),
    "api_exports": ("export_id", "release_id", "adapter", "status", "job_id", "result_json",
                    "error_json", "workspace", "created_at", "updated_at"),
    "api_camera_profiles": ("profile_id", "version", "tier", "status", "payload_json",
                            "calibration_source", "workspace", "created_at"),
    "api_pools": ("pool_id", "release_id", "spec_json", "status", "job_id", "result_json",
                  "error_json", "workspace", "created_at", "updated_at"),
    "api_training_runs": ("training_run_id", "release_id", "spec_json", "status", "job_id",
                          "result_json", "error_json", "workspace", "created_at", "updated_at"),
    "api_diagnostics_runs": ("diagnostics_run_id", "protocol_id", "spec_json", "status", "job_id",
                             "result_json", "error_json", "workspace", "created_at", "updated_at"),
    "api_episodes": ("episode_id", "spec_json", "state_json", "observation_json", "steps_json",
                     "cost_total", "status", "workspace", "created_at", "updated_at"),
}

_JSON_SUFFIX = "_json"


def ensure_api_schema(store: AssetStore) -> None:
    with store.connect() as conn:
        conn.executescript(DDL)
        conn.execute("INSERT OR REPLACE INTO api_meta(key, value) VALUES (?, ?)",
                     ("schema_version", API_SCHEMA_VERSION))


def new_id(prefix: str, *, deterministic_seed: str | None = None) -> str:
    if deterministic_seed:
        from ..canonical import hash_json

        return f"{prefix}_" + hash_json({"seed": deterministic_seed}).split(":", 1)[-1][:20]
    return f"{prefix}_" + uuid.uuid4().hex[:20]


def insert(store: AssetStore, table: str, row: dict[str, Any]) -> dict[str, Any]:
    columns = TABLES[table]
    now = time.time()
    payload: dict[str, Any] = {}
    for column in columns:
        if column in row:
            value = row[column]
        elif column.endswith(_JSON_SUFFIX):
            value = [] if column.startswith("steps") else {}
        elif column in ("created_at", "updated_at"):
            value = now
        elif column == "cost_total":
            value = 0.0
        else:
            value = None
        payload[column] = _encode(value)
    placeholders = ",".join("?" for _ in columns)
    with store.connect() as conn:
        conn.execute(
            f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders})",
            [payload[c] for c in columns],
        )
    got = get(store, table, columns[0], row[columns[0]])
    assert got is not None
    return got


def _encode(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def get(store: AssetStore, table: str, key_column: str, key: str) -> dict[str, Any] | None:
    with store.connect() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE {key_column} = ?", (key,)).fetchone()
    if row is None:
        return None
    return _decode(dict(row))


def update(store: AssetStore, table: str, key_column: str, key: str, **fields: Any) -> dict[str, Any]:
    columns = TABLES[table]
    assignments: list[str] = []
    params: list[Any] = []
    for name, value in fields.items():
        if name not in columns:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"{table} has no column {name}",
                              stage="api.tables.update")
        assignments.append(f"{name} = ?")
        params.append(_encode(value))
    if "updated_at" in columns:
        assignments.append("updated_at = ?")
        params.append(time.time())
    if not assignments:
        got = get(store, table, key_column, key)
        assert got is not None
        return got
    params.append(key)
    with store.connect() as conn:
        cur = conn.execute(f"UPDATE {table} SET {','.join(assignments)} WHERE {key_column} = ?", params)
        if cur.rowcount != 1:
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, f"unknown {table} row {key}",
                              stage="api.tables.update")
    got = get(store, table, key_column, key)
    assert got is not None
    return got


def list_rows(store: AssetStore, table: str, *, workspace: str | None = None,
              where: str = "", params: list[Any] | None = None,
              limit: int = 100, order: str | None = None) -> list[dict[str, Any]]:
    columns = TABLES[table]
    key = columns[0]
    query = f"SELECT * FROM {table} WHERE 1=1"
    values: list[Any] = []
    if where:
        query += f" AND ({where})"
        values.extend(params or [])
    if workspace is not None:
        query += " AND workspace = ?"
        values.append(workspace)
    query += f" ORDER BY {order or f'created_at DESC, {key} ASC'} LIMIT ?"
    values.append(int(limit))
    with store.connect() as conn:
        rows = conn.execute(query, values).fetchall()
    return [_decode(dict(r)) for r in rows]


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    for key in list(row):
        if key.endswith(_JSON_SUFFIX):
            raw = row.pop(key)
            row[key[: -len(_JSON_SUFFIX)]] = json.loads(raw) if raw else ([] if "steps" in key else {})
    return row


def schema_info(store: AssetStore) -> dict[str, Any]:
    with store.connect() as conn:
        row = conn.execute("SELECT value FROM api_meta WHERE key = 'schema_version'").fetchone()
        counts = {}
        for table in TABLES:
            counts[table] = int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
    return {"schema_version": row["value"] if row else None, "rows": counts}
