"""Content-addressed, single-writer asset store (plan 6.2, 6.3, 23.2, 30.17).

Guarantees implemented here:
  * payload written to an attempt-private temporary directory, flushed, hashed, then
    atomically renamed into the immutable asset directory;
  * blobs deduplicate bytes only, while ``assets`` carry independent role/schema/unit/
    frame/interpretation semantics;
  * every commit and release is recorded in one SQLite transaction (WAL, single writer);
  * re-committing the same interpretation hash returns the existing asset (idempotent).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import numpy as np

from ..canonical import array_hash, hash_bytes, interpret_hash, sha256_hex
from ..errors import ErrorCode, SynLabError

SCHEMA_VERSION = "synlab.store.v1"

DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    spec_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    created_at REAL NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    profile TEXT,
    meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    inputs_json TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    owner TEXT,
    heartbeat REAL,
    lease_expires REAL,
    fencing INTEGER NOT NULL DEFAULT 0,
    spec_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '[]',
    error_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE TABLE IF NOT EXISTS dependencies (
    job_id TEXT NOT NULL,
    depends_on TEXT NOT NULL,
    PRIMARY KEY (job_id, depends_on)
);
CREATE TABLE IF NOT EXISTS blobs (
    blob_hash TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    blob_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    schema TEXT NOT NULL,
    unit TEXT NOT NULL,
    frame TEXT NOT NULL,
    interpretation_hash TEXT NOT NULL,
    qa_status TEXT NOT NULL,
    qa_json TEXT NOT NULL DEFAULT '{}',
    files_json TEXT NOT NULL DEFAULT '{}',
    meta_json TEXT NOT NULL DEFAULT '{}',
    ancestry_json TEXT NOT NULL DEFAULT '[]',
    lineage_id TEXT,
    split TEXT,
    created_at REAL NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_assets_role ON assets(role);
CREATE INDEX IF NOT EXISTS idx_assets_lineage ON assets(lineage_id);
CREATE INDEX IF NOT EXISTS idx_assets_interp ON assets(interpretation_hash);
CREATE TABLE IF NOT EXISTS events (
    event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    job_id TEXT,
    type TEXT NOT NULL,
    state TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS releases (
    release_id TEXT PRIMARY KEY,
    manifest_hash TEXT NOT NULL,
    scope TEXT NOT NULL,
    profile TEXT NOT NULL,
    frozen_at REAL NOT NULL,
    manifest_path TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS gpu_leases (
    device TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    token TEXT NOT NULL,
    acquired_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    state TEXT NOT NULL DEFAULT 'HELD',
    pid INTEGER,
    meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS idempotency (
    idempotency_key TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    job_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reservations (
    reservation_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount REAL NOT NULL,
    created_at REAL NOT NULL,
    released_at REAL
);
"""

QA_PASS = "QA_PASS"
QA_PENDING = "QA_PENDING"
QA_FAIL = "QA_FAIL"


@dataclass
class AssetRecord:
    asset_id: str
    blob_hash: str
    role: str
    schema: str
    unit: str
    frame: str
    interpretation_hash: str
    qa_status: str
    qa: dict[str, Any]
    files: dict[str, str]
    meta: dict[str, Any]
    ancestry: list[str]
    lineage_id: str | None
    split: str | None
    revision: int
    created_at: float
    path: Path = field(default_factory=Path)

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id, "blob_hash": self.blob_hash, "role": self.role,
            "schema": self.schema, "unit": self.unit, "frame": self.frame,
            "interpretation_hash": self.interpretation_hash, "qa_status": self.qa_status,
            "qa": self.qa, "files": self.files, "meta": self.meta, "ancestry": self.ancestry,
            "lineage_id": self.lineage_id, "split": self.split, "revision": self.revision,
            "created_at": self.created_at,
        }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.ndarray):
        return {"__ndarray__": array_hash(obj)}
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not JSON serialisable: {type(obj)!r}")


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=_json_default)


def _fsync_dir(path: Path) -> None:
    """Best-effort directory fsync; Windows cannot fsync a directory handle."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class AssetStore:
    """Immutable asset store with a single-writer SQLite metadata database."""

    def __init__(self, root: str | os.PathLike[str], db_path: str | os.PathLike[str] | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "blobs").mkdir(exist_ok=True)
        (self.root / "assets").mkdir(exist_ok=True)
        (self.root / "tmp").mkdir(exist_ok=True)
        (self.root / "releases").mkdir(exist_ok=True)
        (self.root / "reports").mkdir(exist_ok=True)
        self.db_path = Path(db_path) if db_path else self.root / "metadata.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------ database
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=60.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=60000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(DDL)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
                ("schema_version", SCHEMA_VERSION),
            )

    # ------------------------------------------------------------------ blobs
    def blob_path(self, blob_hash: str) -> Path:
        digest = blob_hash.split(":", 1)[-1]
        return self.root / "blobs" / digest[:2] / digest[2:4] / digest

    def put_bytes(self, data: bytes) -> str:
        blob_hash = hash_bytes(data)
        path = self.blob_path(blob_hash)
        if path.exists():
            return blob_hash
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO blobs(blob_hash, relative_path, size, created_at) VALUES (?,?,?,?)",
                (blob_hash, str(path.relative_to(self.root)).replace("\\", "/"), len(data), time.time()),
            )
        return blob_hash

    def read_blob(self, blob_hash: str) -> bytes:
        path = self.blob_path(blob_hash)
        if not path.exists():
            raise SynLabError(
                ErrorCode.ASSET_HASH_MISMATCH,
                f"blob {blob_hash} missing at {path}",
                stage="storage.read_blob",
            )
        data = path.read_bytes()
        actual = hash_bytes(data)
        if actual != blob_hash:
            raise SynLabError(
                ErrorCode.ASSET_HASH_MISMATCH,
                f"blob {blob_hash} content hash mismatch ({actual})",
                stage="storage.read_blob",
            )
        return data

    # ------------------------------------------------------------------ assets
    def attempt_dir(self, job_id: str) -> Path:
        """Attempt-private output directory; a stale worker can never write a new attempt."""
        path = self.root / "tmp" / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def commit_asset(
        self,
        *,
        role: str,
        schema: str,
        unit: str,
        frame: str,
        payload: dict[str, Any],
        meta: dict[str, Any] | None = None,
        qa: dict[str, Any] | None = None,
        qa_status: str = QA_PENDING,
        ancestry: Sequence[str] = (),
        lineage_id: str | None = None,
        split: str | None = None,
        attempt_dir: Path | None = None,
        interpretation_extra: dict[str, Any] | None = None,
        allow_existing: bool = True,
    ) -> AssetRecord:
        """Write payload files atomically and register the asset in one transaction.

        ``payload`` values may be ``np.ndarray`` (stored in ``arrays.npz``), ``bytes``
        (stored as ``data.bin``) or JSON-serialisable metadata (merged into ``meta.json``).
        """
        meta = dict(meta or {})
        qa = dict(qa or {})
        arrays: dict[str, np.ndarray] = {}
        blobs: dict[str, bytes] = {}
        for key, value in payload.items():
            if isinstance(value, np.ndarray):
                arrays[key] = np.ascontiguousarray(value)
            elif isinstance(value, (bytes, bytearray)):
                blobs[key] = bytes(value)
            elif hasattr(value, "vertices") and hasattr(value, "faces"):
                from .mesh_io import mesh_arrays

                for sub_key, arr in mesh_arrays(value).items():
                    arrays[f"{key}.{sub_key}"] = arr
            elif value is None:
                continue
            else:
                meta[key] = value

        tmp_root = Path(attempt_dir) if attempt_dir else self.root / "tmp" / f"commit_{uuid.uuid4().hex}"
        tmp_root.mkdir(parents=True, exist_ok=True)

        file_hashes: dict[str, str] = {}
        file_names: dict[str, str] = {}
        staged: list[tuple[Path, str]] = []
        if arrays:
            npz_path = tmp_root / "arrays.npz"
            np.savez(npz_path, **arrays)
            file_hashes["arrays"] = self._register_staged(npz_path, staged)
            file_names["arrays"] = "arrays.npz"
        if blobs:
            for key, data in blobs.items():
                name = f"{key}.bin"
                blob_path = tmp_root / name
                blob_path.write_bytes(data)
                file_hashes[key] = self._register_staged(blob_path, staged)
                file_names[key] = name
        meta_path = tmp_root / "meta.json"
        meta_path.write_text(_dumps({"meta": meta, "qa": qa, "files": {} }), encoding="utf-8")
        file_hashes["meta"] = self._register_staged(meta_path, staged)
        file_names["meta"] = "meta.json"

        payload_hash = _hash_mapping({
            **{f"array:{k}": array_hash(v) for k, v in sorted(arrays.items())},
            **{f"blob:{k}": hash_bytes(v) for k, v in sorted(blobs.items())},
            "meta": _dumps(meta),
        })
        interp = interpret_hash(role, schema, unit, frame, payload_hash, interpretation_extra)
        asset_id = "asset_" + interp.split(":", 1)[-1][:20]

        existing = self._maybe_existing(asset_id) if allow_existing else None
        if existing is not None:
            self._cleanup_tmp(tmp_root)
            return existing

        asset_dir = self.root / "assets" / asset_id
        if not asset_dir.exists():
            asset_dir.parent.mkdir(parents=True, exist_ok=True)
            if tmp_root.parent == asset_dir.parent:
                pass
            target = tmp_root
            try:
                os.replace(target, asset_dir)
            except OSError:
                # cross-directory move: copy then rename
                import shutil

                shutil.copytree(target, asset_dir)
                shutil.rmtree(target, ignore_errors=True)
            _fsync_dir(asset_dir.parent)
        else:
            self._cleanup_tmp(tmp_root)
        files = {name: f"assets/{asset_id}/{file_names[name]}" for name in file_names}
        meta_path = asset_dir / "meta.json"
        manifest_core = {"meta": meta, "qa": qa, "files": files, "file_hashes": file_hashes}
        manifest = dict(manifest_core)
        manifest["meta_hash"] = hash_bytes(_dumps(manifest_core).encode("utf-8"))
        meta_path.write_text(_dumps(manifest), encoding="utf-8")

        combined = _hash_mapping({"payload": payload_hash, "files": file_hashes, "qa": qa, "role": role})
        record = AssetRecord(
            asset_id=asset_id, blob_hash=combined, role=role, schema=schema, unit=unit, frame=frame,
            interpretation_hash=interp, qa_status=qa_status, qa=qa, files=files, meta=meta,
            ancestry=list(ancestry), lineage_id=lineage_id, split=split, revision=1,
            created_at=time.time(), path=asset_dir,
        )
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """INSERT INTO assets(asset_id, blob_hash, role, schema, unit, frame,
                       interpretation_hash, qa_status, qa_json, files_json, meta_json,
                       ancestry_json, lineage_id, split, created_at, revision)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (record.asset_id, record.blob_hash, role, schema, unit, frame, interp, qa_status,
                     _dumps(qa), _dumps(files), _dumps(meta), _dumps(list(ancestry)), lineage_id,
                     split, record.created_at),
                )
                conn.execute(
                    """INSERT INTO events(run_id, job_id, type, state, revision, message, payload_json, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (None, None, "asset.committed", qa_status, 1, record.asset_id,
                     _dumps({"role": role, "blob_hash": combined}), time.time()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return record

    def _register_staged(self, path: Path, staged: list[tuple[Path, str]]) -> str:
        data = path.read_bytes()
        return hash_bytes(data)

    def _cleanup_tmp(self, path: Path) -> None:
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    def _maybe_existing(self, asset_id: str) -> AssetRecord | None:
        try:
            return self.get_asset(asset_id)
        except SynLabError:
            return None

    def get_asset(self, asset_id: str) -> AssetRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        if row is None:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH, f"unknown asset {asset_id}",
                              stage="storage.get_asset")
        return self._row_to_asset(row)

    def _row_to_asset(self, row: sqlite3.Row) -> AssetRecord:
        return AssetRecord(
            asset_id=row["asset_id"], blob_hash=row["blob_hash"], role=row["role"],
            schema=row["schema"], unit=row["unit"], frame=row["frame"],
            interpretation_hash=row["interpretation_hash"], qa_status=row["qa_status"],
            qa=json.loads(row["qa_json"]), files=json.loads(row["files_json"]),
            meta=json.loads(row["meta_json"]), ancestry=json.loads(row["ancestry_json"]),
            lineage_id=row["lineage_id"], split=row["split"], revision=row["revision"],
            created_at=row["created_at"], path=self.root / "assets" / row["asset_id"],
        )

    def set_qa(self, asset_id: str, qa_status: str, qa: dict[str, Any]) -> None:
        if qa_status not in (QA_PASS, QA_PENDING, QA_FAIL):
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"bad qa status {qa_status}",
                              stage="storage.set_qa")
        with self.connect() as conn:
            conn.execute("UPDATE assets SET qa_status=?, qa_json=? WHERE asset_id=?",
                         (qa_status, _dumps(qa), asset_id))

    def list_assets(self, *, role: str | None = None, lineage_id: str | None = None,
                    split: str | None = None, qa_status: str | None = None,
                    limit: int = 500, offset: int = 0) -> list[AssetRecord]:
        query = "SELECT * FROM assets WHERE 1=1"
        params: list[Any] = []
        if role:
            query += " AND role = ?"
            params.append(role)
        if lineage_id:
            query += " AND lineage_id = ?"
            params.append(lineage_id)
        if split:
            query += " AND split = ?"
            params.append(split)
        if qa_status:
            query += " AND qa_status = ?"
            params.append(qa_status)
        query += " ORDER BY created_at ASC, asset_id ASC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_asset(r) for r in rows]

    def count_assets(self, **filters: Any) -> int:
        query = "SELECT COUNT(*) AS n FROM assets WHERE 1=1"
        params: list[Any] = []
        for key in ("role", "lineage_id", "split", "qa_status"):
            value = filters.get(key)
            if value:
                query += f" AND {key} = ?"
                params.append(value)
        with self.connect() as conn:
            return int(conn.execute(query, params).fetchone()["n"])

    # ------------------------------------------------------------------ payload IO
    def load_arrays(self, asset_id: str, keys: Iterable[str] | None = None) -> dict[str, np.ndarray]:
        record = self.get_asset(asset_id)
        npz_rel = record.files.get("arrays")
        if not npz_rel:
            return {}
        npz_path = self.root / Path(*npz_rel.split("/"))
        if not npz_path.exists():
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"asset {asset_id} payload missing: {npz_path}", stage="storage.load_arrays")
        with np.load(npz_path, allow_pickle=False) as data:
            wanted = set(keys) if keys is not None else set(data.files)
            out = {k: data[k] for k in data.files if k in wanted}
        if keys is not None:
            missing = set(keys) - set(out)
            if missing:
                raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                                  f"asset {asset_id} missing arrays {sorted(missing)}",
                                  stage="storage.load_arrays")
        if record.blob_hash and not out:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"asset {asset_id} has no arrays", stage="storage.load_arrays")
        return out

    def load_bytes(self, asset_id: str, key: str) -> bytes:
        record = self.get_asset(asset_id)
        rel = record.files.get(key) or record.files.get(f"{key}.bin")
        if not rel:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"asset {asset_id} has no blob {key}", stage="storage.load_bytes")
        path = self.root / Path(*rel.split("/"))
        data = path.read_bytes()
        expected = self.file_hashes(asset_id).get(key)
        if expected and hash_bytes(data) != expected:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"asset {asset_id} blob {key} modified", stage="storage.load_bytes")
        return data

    def file_hashes(self, asset_id: str) -> dict[str, str]:
        """Per-file content hashes recorded at commit time (meta.json)."""
        path = self.root / "assets" / asset_id / "meta.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return dict(payload.get("file_hashes") or {})

    def load_mesh(self, asset_id: str, key: str = "mesh") -> Any:
        from .mesh_io import arrays_to_mesh

        record = self.get_asset(asset_id)
        prefix = f"{key}."
        arrays = self.load_arrays(asset_id)
        selected = {k[len(prefix):]: v for k, v in arrays.items() if k.startswith(prefix)}
        if not selected:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"asset {asset_id} has no mesh {key}", stage="storage.load_mesh")
        mesh, attrs = arrays_to_mesh(selected)
        mesh.metadata = dict(mesh.metadata or {})
        mesh.metadata["asset_id"] = record.asset_id
        if attrs:
            mesh.metadata["face_attrs"] = list(attrs)
        return mesh

    def asset_path(self, asset_id: str, name: str) -> Path:
        record = self.get_asset(asset_id)
        rel = record.files.get(name)
        if rel is None:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"asset {asset_id} has no file {name}", stage="storage.asset_path")
        return self.root / Path(*rel.split("/"))

    def resolve_asset_path(self, asset_id: str, name: str) -> tuple[Path, str]:
        """Return (path, hash) after verifying the file has not been modified."""
        path = self.asset_path(asset_id, name)
        if not path.exists():
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"asset file missing: {path}", stage="storage.resolve_asset_path")
        from ..canonical import hash_file

        actual = hash_file(path)
        expected = self.file_hashes(asset_id).get(name)
        if expected and actual != expected:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"asset {asset_id} file {name} hash mismatch", stage="storage.resolve_asset_path")
        return path, actual

    # ------------------------------------------------------------------ runs / events
    def create_run(self, run_id: str, spec_hash: str, scope: str, profile: str | None = None,
                   meta: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO runs(run_id, spec_hash, status, scope, created_at, revision, profile, meta_json)
                   VALUES (?,?,?,?,?,1,?,?)""",
                (run_id, spec_hash, "PENDING", scope, time.time(), profile, _dumps(meta or {})),
            )
            conn.execute(
                """INSERT INTO events(run_id, job_id, type, state, revision, message, payload_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (run_id, None, "run.created", "PENDING", 1, run_id, "{}", time.time()),
            )

    def set_run_status(self, run_id: str, status: str, meta: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE runs SET status=?, revision=revision+1, meta_json=? WHERE run_id=?",
                         (status, _dumps(meta or {}), run_id))
            conn.execute(
                """INSERT INTO events(run_id, job_id, type, state, revision, message, payload_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (run_id, None, "run.status", status, 1, status, "{}", time.time()),
            )

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown run {run_id}", stage="storage.get_run")
        return dict(row)

    def append_event(self, *, run_id: str | None, job_id: str | None, type: str,
                     state: str | None = None, revision: int = 0, message: str = "",
                     payload: dict[str, Any] | None = None) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO events(run_id, job_id, type, state, revision, message, payload_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (run_id, job_id, type, state, revision, message, _dumps(payload or {}), time.time()),
            )
            return int(cur.lastrowid)

    def events_since(self, seq: int, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE event_seq > ? ORDER BY event_seq ASC LIMIT ?",
                (int(seq), int(limit)),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            out.append(item)
        return out

    # ------------------------------------------------------------------ backups
    def backup(self, target: str | os.PathLike[str]) -> dict[str, Any]:
        """Consistent online snapshot through the SQLite backup API (plan 23.4 / R34)."""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as src, sqlite3.connect(str(target)) as dst:
            src.backup(dst)
        from ..canonical import hash_file

        return {"path": str(target), "hash": hash_file(target)}


def _hash_mapping(mapping: dict[str, Any]) -> str:
    return hash_bytes(_dumps(mapping).encode("utf-8"))


def health_check(root: str | os.PathLike[str]) -> dict[str, Any]:
    """Verify DB integrity and every asset file hash (used by doctor and recovery audit)."""
    from ..canonical import hash_file

    store = AssetStore(root)
    problems: list[str] = []
    with store.connect() as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            problems.append(f"sqlite integrity: {integrity}")
        assets = conn.execute("SELECT asset_id, files_json FROM assets").fetchall()
        blobs = conn.execute("SELECT blob_hash, relative_path, size FROM blobs").fetchall()
    checked = 0
    for row in assets:
        asset_id = row["asset_id"]
        meta_path = store.root / "assets" / asset_id / "meta.json"
        if not meta_path.exists():
            problems.append(f"{asset_id}: meta.json missing")
            continue
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        stored_meta_hash = payload.pop("meta_hash", None)
        if stored_meta_hash and stored_meta_hash != hash_bytes(_dumps(payload).encode("utf-8")):
            problems.append(f"{asset_id}:manifest self-hash mismatch")
        for name, rel in (payload.get("files") or {}).items():
            if name == "meta":
                continue
            path = store.root / Path(*str(rel).split("/"))
            if not path.exists():
                problems.append(f"{asset_id}:{name} missing")
                continue
            expected = (payload.get("file_hashes") or {}).get(name)
            if expected and hash_file(path) != expected:
                problems.append(f"{asset_id}:{name} hash mismatch")
            checked += 1
    for row in blobs:
        path = store.root / Path(*str(row["relative_path"]).split("/"))
        if not path.exists():
            problems.append(f"blob {row['blob_hash']} missing")
            continue
        if hash_file(path) != row["blob_hash"]:
            problems.append(f"blob {row['blob_hash']} hash mismatch")
        checked += 1
    return {"ok": not problems, "problems": problems, "files_checked": checked,
            "assets": len(assets), "blobs": len(blobs), "db": str(store.db_path)}
