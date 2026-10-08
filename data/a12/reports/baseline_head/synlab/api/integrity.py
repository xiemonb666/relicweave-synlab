"""Per-file integrity ledger for asset payload downloads (plan 21.1, 30.16).

``AssetStore.resolve_asset_path`` compares a content hash with the *relative path* stored
in ``assets.files_json`` (that column holds paths, not hashes) and therefore cannot be
used for verification.  Rather than editing another module's file, the API keeps its own
ledger:

* when the worker commits an asset it immediately records ``size`` + ``sha256`` with
  ``source='producer'`` — those hashes are trusted;
* for assets committed by other tooling the first download records ``source='first_serve'``
  and the response says so explicitly instead of pretending the bytes were verified;
* every later download recomputes the hash and fails with ``ASSET_HASH_MISMATCH`` when the
  bytes changed on disk.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..canonical import hash_file
from ..errors import ErrorCode, SynLabError
from ..storage.store import AssetStore
from .problems import API_CODE_FILE_ROLE_MISMATCH, API_CODE_NOT_FOUND, ApiProblem
from .security import assert_within

SOURCE_PRODUCER = "producer"
SOURCE_FIRST_SERVE = "first_serve"

#: The ledger lives in the API's own table.  ``synlab.api.tables`` also declares it, but a
#: caller may hold a bare ``AssetStore`` that never went through ``AppContext`` (the worker
#: and tests do), so this module proves the table exists before touching it.  The DDL is
#: kept byte-identical to ``tables.DDL``.
LEDGER_DDL = """
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


def ensure_ledger(store: AssetStore) -> None:
    """Create the integrity ledger if it is missing (idempotent, never alters other tables)."""
    with store.connect() as conn:
        conn.executescript(LEDGER_DDL)


@dataclass
class FileRef:
    asset_id: str
    file_name: str
    relative_path: str
    path: Path
    size: int
    sha256: str
    hash_verified: str
    expected_sha256: str | None


def _ledger_row(store: AssetStore, asset_id: str, file_name: str) -> dict[str, Any] | None:
    ensure_ledger(store)
    with store.connect() as conn:
        row = conn.execute(
            "SELECT * FROM api_file_integrity WHERE asset_id = ? AND file_name = ?",
            (asset_id, file_name),
        ).fetchone()
    return dict(row) if row else None


def record_integrity(store: AssetStore, asset_id: str, *, source: str = SOURCE_PRODUCER,
                     names: list[str] | None = None) -> dict[str, str]:
    """Record size+hash for an asset's payload files (called right after commit)."""
    ensure_ledger(store)
    record = store.get_asset(asset_id)
    names = names or list(record.files)
    out: dict[str, str] = {}
    now = time.time()
    with store.connect() as conn:
        for name in names:
            rel = record.files.get(name)
            if not rel:
                continue
            path = assert_within(store.root, store.root / Path(*rel.split("/")),
                                 stage="integrity.record")
            if not path.exists():
                continue
            digest = hash_file(path)
            out[name] = digest
            conn.execute(
                """INSERT INTO api_file_integrity(asset_id, file_name, relative_path, size,
                   sha256, source, first_seen_at, last_verified_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(asset_id, file_name) DO UPDATE SET
                   size=excluded.size, sha256=excluded.sha256, source=excluded.source,
                   last_verified_at=excluded.last_verified_at""",
                (asset_id, name, rel, path.stat().st_size, digest, source, now, now),
            )
    return out


def resolve_file(store: AssetStore, asset_id: str, file_name: str, *,
                 verify: bool = True) -> FileRef:
    """Resolve a registered payload file, proving containment and (when possible) hash."""
    ensure_ledger(store)
    record = store.get_asset(asset_id)
    rel = record.files.get(file_name)
    if rel is None:
        raise ApiProblem(
            404, API_CODE_NOT_FOUND,
            f"asset {asset_id} has no payload file {file_name!r}",
            stage="integrity.resolve",
            details={"available": sorted(record.files)},
        )
    if rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        raise ApiProblem(400, "PATH_REJECTED", "asset payload path is not relative",
                         stage="integrity.resolve")
    path = assert_within(store.root, store.root / Path(*rel.replace("\\", "/").split("/")),
                         stage="integrity.resolve")
    if not path.exists():
        raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                          f"asset {asset_id} payload file {file_name!r} is missing on disk",
                          stage="integrity.resolve")
    size = path.stat().st_size
    if not verify:
        return FileRef(asset_id, file_name, rel, path, size, "", "skipped", None)

    actual = hash_file(path)
    row = _ledger_row(store, asset_id, file_name)
    expected = row["sha256"] if row else None
    if expected and expected != actual:
        raise SynLabError(
            ErrorCode.ASSET_HASH_MISMATCH,
            f"asset {asset_id} file {file_name!r} changed on disk "
            f"(recorded {expected[:19]}..., actual {actual[:19]}...)",
            stage="integrity.verify",
            evidence_refs=[asset_id],
        )
    verified = "recorded" if row else "first_seen"
    source = row["source"] if row else SOURCE_FIRST_SERVE
    now = time.time()
    with store.connect() as conn:
        conn.execute(
            """INSERT INTO api_file_integrity(asset_id, file_name, relative_path, size, sha256,
               source, first_seen_at, last_verified_at) VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(asset_id, file_name) DO UPDATE SET
               size=excluded.size, last_verified_at=excluded.last_verified_at""",
            (asset_id, file_name, rel, size, actual, source, now, now),
        )
    return FileRef(asset_id, file_name, rel, path, size, actual, verified, expected)


def verify_all_files(store: AssetStore, asset_id: str) -> dict[str, Any]:
    """Verify every payload file of an asset; returns per-file status (never invents ok)."""
    record = store.get_asset(asset_id)
    problems: list[str] = []
    files: dict[str, Any] = {}
    for name in sorted(record.files):
        try:
            ref = resolve_file(store, asset_id, name)
            files[name] = {"ok": True, "size": ref.size, "sha256": ref.sha256,
                           "hash_verified": ref.hash_verified}
        except (SynLabError, ApiProblem) as exc:
            problems.append(f"{name}: {exc}")
            files[name] = {"ok": False, "error": str(exc)}
    return {"ok": not problems, "asset_id": asset_id, "problems": problems, "files": files}


def role_mismatch(asset_role: str, requested_role: str) -> ApiProblem:
    return ApiProblem(
        409, API_CODE_FILE_ROLE_MISMATCH,
        f"asset role is {asset_role!r}, the requested file role is {requested_role!r}; "
        "file refs must name the registered asset role",
        stage="integrity.role",
        details={"asset_role": asset_role, "requested_role": requested_role},
    )
