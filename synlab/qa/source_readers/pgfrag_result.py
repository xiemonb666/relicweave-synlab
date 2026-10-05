"""Read and cross-check explicitly named PG-Frag ``result.json`` artifacts.

The reader verifies the bytes for every table it consumes before parsing them.
Its result is deliberately limited to ``PG_DIAGNOSTIC_ONLY`` source evidence:
endpoint intact-bond components are not accepted as physical fragments, and no
crack surface, event history, or historical relation is inferred.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


REPORT_SCHEMA = "synlab.pgfrag.source_read.v1"
RESULT_SCHEMA = "pgfrag.result.v1"
DICTIONARY_SCHEMA = "pgfrag.output_dictionary.v1"
JOB_SCHEMA = "pgfrag.job.v1"

MAX_RESULT_BYTES = 1_000_000
MAX_JOB_BYTES = 1_000_000
MAX_OUTPUT_FILES = 32
MAX_OUTPUT_BYTES = 5_000_000
MAX_OUTPUT_FILE_BYTES = 2_000_000

FRAME = "right_handed_z_up"

# (name, dtype, unit, frame). A null frame is explicit in the producer
# dictionary; coordinates and velocities remain in SI and in the named frame.
_TABLE_SPECS: dict[str, tuple[tuple[str, str, str, str | None], ...]] = {
    "points.csv": (
        ("point_id", "int", "1", None),
        ("x_ref_m", "float64", "m", FRAME),
        ("y_ref_m", "float64", "m", FRAME),
        ("z_ref_m", "float64", "m", FRAME),
        ("x_current_m", "float64", "m", FRAME),
        ("y_current_m", "float64", "m", FRAME),
        ("z_current_m", "float64", "m", FRAME),
        ("vx_mps", "float64", "m/s", FRAME),
        ("vy_mps", "float64", "m/s", FRAME),
        ("vz_mps", "float64", "m/s", FRAME),
        ("damage", "float64", "1", None),
        ("n_active_bonds", "int", "1", None),
        ("strain_energy_density_J_m3", "float64", "J/m^3", None),
        ("volume_m3", "float64", "m^3", None),
        ("mass_kg", "float64", "kg", None),
        ("intact_bond_component_id", "int", "1", None),
    ),
    "components.csv": (
        ("point_id", "int", "1", None),
        ("component_id", "int", "1", None),
        ("point_mass_kg", "float64", "kg", None),
        ("damage", "float64", "1", None),
    ),
    "bond_states.csv": (
        ("point_i_global", "int", "1", None),
        ("point_j_global", "int", "1", None),
        ("active", "bool", "1", None),
        ("reference_length_m", "float64", "m", None),
        ("current_length_m", "float64", "m", None),
    ),
    "broken_bonds.csv": (
        ("point_i_global", "int", "1", None),
        ("point_j_global", "int", "1", None),
        ("reference_length_m", "float64", "m", None),
        ("current_length_m", "float64", "m", None),
    ),
    "isolated_points.csv": (
        ("point_id", "int", "1", None),
        ("x_ref_m", "float64", "m", FRAME),
        ("y_ref_m", "float64", "m", FRAME),
        ("z_ref_m", "float64", "m", FRAME),
        ("mass_kg", "float64", "kg", None),
    ),
}

_REQUIRED_OUTPUTS = frozenset({
    "data_dictionary.json",
    "points.csv",
    "components.csv",
    "bond_states.csv",
    "broken_bonds.csv",
    "isolated_points.csv",
})
_INT_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_FLOAT_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")


class _ReadFailure(Exception):
    """A sanitized, expected source-read rejection."""

    def __init__(self, field: str, reason: str, status: str = "FAIL") -> None:
        super().__init__(reason)
        self.field = field
        self.reason = reason
        self.status = status


def _fail(field: str, reason: str, status: str = "FAIL") -> None:
    raise _ReadFailure(field, reason, status)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_linklike(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction is not None and is_junction())
    except OSError:
        return True


def _reject_link_components(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    chain = [absolute, *absolute.parents]
    for item in reversed(chain):
        if _is_linklike(item):
            _fail("path", "symlink or junction components are not allowed")


def _strict_json(raw: bytes, field: str) -> dict[str, Any]:
    def reject_constant(_token: str) -> None:
        raise ValueError("non-finite JSON constant")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = child
        return value

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _fail(field, "source is not strict UTF-8 JSON")
    if not isinstance(parsed, dict):
        _fail(field, "JSON root must be an object")

    def finite_tree(value: Any) -> bool:
        if isinstance(value, float):
            return math.isfinite(value)
        if isinstance(value, dict):
            return all(finite_tree(child) for child in value.values())
        if isinstance(value, list):
            return all(finite_tree(child) for child in value)
        return True

    if not finite_tree(parsed):
        _fail(field, "JSON contains a non-finite number")
    return parsed


def _root_directory(raw_root: str | Path) -> Path:
    root_arg = Path(raw_root)
    _reject_link_components(root_arg)
    try:
        root = root_arg.resolve(strict=True)
    except OSError:
        _fail("result_root", "explicit result root is unavailable", "INCOMPLETE")
    if not root.is_dir():
        _fail("result_root", "explicit result root is not a directory", "INCOMPLETE")
    return root


def _safe_output_path(root: Path, raw_path: Any) -> Path:
    if not isinstance(raw_path, str) or not raw_path or raw_path.strip() != raw_path:
        _fail("outputs.path", "output path is missing or malformed", "INCOMPLETE")
    if "\\" in raw_path or ":" in raw_path:
        _fail("outputs.path", "output path must be root-relative POSIX syntax")
    pure = PurePosixPath(raw_path)
    if pure.is_absolute() or raw_path != pure.as_posix() or not pure.parts:
        _fail("outputs.path", "absolute or non-canonical output path is rejected")
    if any(part in {"", ".", ".."} for part in pure.parts):
        _fail("outputs.path", "path traversal is rejected")

    candidate = root
    for part in pure.parts:
        candidate = candidate / part
        if _is_linklike(candidate):
            _fail("outputs.path", "symlink or junction artifact path is rejected")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file():
            _fail("outputs.path", "output artifact is not a regular file", "INCOMPLETE")
    except _ReadFailure:
        raise
    except (OSError, ValueError):
        _fail("outputs.path", "output artifact is absent or escapes the result root", "INCOMPLETE")
    return resolved


def _read_bounded_file(path: Path, limit: int, field: str) -> bytes:
    try:
        with path.open("rb") as stream:
            file_stat = os.fstat(stream.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                _fail(field, "source is not a regular file", "INCOMPLETE")
            if file_stat.st_size > limit:
                _fail(field, "source exceeds the bounded byte limit")
            raw = stream.read(limit + 1)
    except _ReadFailure:
        raise
    except OSError:
        _fail(field, "source could not be read", "INCOMPLETE")
    if len(raw) > limit:
        _fail(field, "source exceeds the bounded byte limit")
    if len(raw) != file_stat.st_size:
        _fail(field, "source size changed while being read")
    return raw


def _verify_outputs(root: Path, result: Mapping[str, Any]) -> dict[str, tuple[Path, int, str]]:
    raw_outputs = result.get("outputs")
    if not isinstance(raw_outputs, list):
        _fail("outputs", "result output manifest is absent or malformed", "INCOMPLETE")
    if len(raw_outputs) > MAX_OUTPUT_FILES:
        _fail("outputs", "result output manifest exceeds the file-count limit")

    records: dict[str, tuple[Path, int, str]] = {}
    total_bytes = 0
    for index, raw_entry in enumerate(raw_outputs):
        if not isinstance(raw_entry, Mapping):
            _fail(f"outputs[{index}]", "output manifest entry is malformed")
        raw_path = raw_entry.get("path")
        path = _safe_output_path(root, raw_path)
        assert isinstance(raw_path, str)
        if raw_path in records:
            _fail("outputs", "duplicate output path in result manifest")
        size = raw_entry.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            _fail("outputs.bytes", "output byte count must be a non-negative integer")
        if size > MAX_OUTPUT_FILE_BYTES:
            _fail("outputs.bytes", "an output exceeds the per-file byte limit")
        digest = raw_entry.get("sha256")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            _fail("outputs.sha256", "output manifest must declare a 64-digit SHA-256", "INCOMPLETE")
        try:
            actual_size = path.stat().st_size
        except OSError:
            _fail("outputs.path", "output artifact is unavailable", "INCOMPLETE")
        if actual_size != size:
            _fail("outputs.bytes", "declared output byte count does not match source size")
        total_bytes += size
        if total_bytes > MAX_OUTPUT_BYTES:
            _fail("outputs", "result output manifest exceeds the aggregate byte limit")
        records[raw_path] = (path, size, digest.lower())

    missing = _REQUIRED_OUTPUTS.difference(records)
    if missing:
        # Keep error text independent of arbitrary manifest-provided paths.
        _fail("outputs", "one or more required PG-Frag outputs are absent", "INCOMPLETE")
    return records


def _read_verified_output(
    records: Mapping[str, tuple[Path, int, str]], raw_path: str, field: str,
) -> tuple[bytes, dict[str, Any]]:
    record = records.get(raw_path)
    if record is None:
        _fail(field, "required output is absent from the result manifest", "INCOMPLETE")
    path, expected_size, expected_hash = record
    raw = _read_bounded_file(path, MAX_OUTPUT_FILE_BYTES, field)
    if len(raw) != expected_size:
        _fail(field, "source byte count does not match the output manifest")
    actual_hash = _sha256(raw)
    if actual_hash != expected_hash:
        _fail(field, "source SHA-256 does not match the output manifest")
    return raw, {"path": raw_path, "bytes_verified": True, "bytes": len(raw), "sha256_verified": True}


def _validate_dictionary(raw: bytes) -> dict[str, Any]:
    dictionary = _strict_json(raw, "data_dictionary.json")
    if dictionary.get("schema") != DICTIONARY_SCHEMA:
        _fail("data_dictionary.schema", "unsupported data dictionary schema")
    frame = dictionary.get("frame")
    if not isinstance(frame, Mapping) or frame.get("name") != FRAME:
        _fail("data_dictionary.frame", "explicit coordinate frame does not match the PG-Frag v1 frame")
    tables = dictionary.get("tables")
    if not isinstance(tables, Mapping):
        _fail("data_dictionary.tables", "data dictionary tables are absent or malformed")

    for table_name, specs in _TABLE_SPECS.items():
        table = tables.get(table_name)
        columns = table.get("columns") if isinstance(table, Mapping) else None
        if not isinstance(columns, Mapping) or set(columns) != {spec[0] for spec in specs}:
            _fail(f"data_dictionary.tables.{table_name}.columns", "column schema is absent or differs from the supported v1 table")
        for name, dtype, unit, column_frame in specs:
            metadata = columns.get(name)
            if not isinstance(metadata, Mapping):
                _fail(f"data_dictionary.{table_name}.{name}", "column metadata is absent")
            if metadata.get("dtype") != dtype:
                _fail(f"data_dictionary.{table_name}.{name}.dtype", "declared column type does not match the supported source schema")
            if metadata.get("unit") != unit:
                _fail(f"data_dictionary.{table_name}.{name}.unit", "declared unit does not match the supported source schema")
            if metadata.get("frame") != column_frame:
                _fail(f"data_dictionary.{table_name}.{name}.frame", "declared frame does not match the supported source schema")
    return dictionary


def _parse_number(token: str, field: str, *, integer: bool) -> int | float:
    if integer:
        if not _INT_RE.fullmatch(token):
            _fail(field, "integer column contains a non-canonical or non-integer value")
        return int(token)
    if not _FLOAT_RE.fullmatch(token):
        _fail(field, "floating-point column contains a malformed or non-finite value")
    try:
        value = float(token)
    except (ValueError, OverflowError):
        _fail(field, "floating-point column contains an invalid value")
    if not math.isfinite(value):
        _fail(field, "floating-point column contains a non-finite value")
    return value


def _parse_csv(raw: bytes, table_name: str, *, allow_header_only: bool = False) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _fail(table_name, "CSV source is not UTF-8")
    if not text:
        _fail(table_name, "CSV source is empty; a typed header is required", "INCOMPLETE")
    expected = _TABLE_SPECS[table_name]
    expected_header = [spec[0] for spec in expected]
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        if header != expected_header:
            _fail(table_name, "CSV header does not match the supported v1 schema")
        rows: list[dict[str, Any]] = []
        for row_index, values in enumerate(reader):
            if len(values) != len(expected) or any(value == "" for value in values):
                _fail(table_name, f"CSV row {row_index + 2} is incomplete")
            typed: dict[str, Any] = {}
            for (name, dtype, _unit, _frame), token in zip(expected, values):
                if dtype == "bool":
                    if token not in {"true", "false"}:
                        _fail(table_name, "boolean column must contain lowercase true or false")
                    typed[name] = token == "true"
                else:
                    typed[name] = _parse_number(token, table_name, integer=(dtype == "int"))
            rows.append(typed)
    except _ReadFailure:
        raise
    except (csv.Error, StopIteration):
        _fail(table_name, "CSV source has invalid row syntax or no header")
    if not rows and not allow_header_only:
        _fail(table_name, "CSV contains a header but no source rows", "INCOMPLETE")
    return rows


def _source_ids(rows: Sequence[Mapping[str, Any]], table: str, key: str) -> set[int]:
    ids: set[int] = set()
    previous = 0
    for row in rows:
        value = row[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            _fail(table, "source IDs must be positive integers")
        if value in ids:
            _fail(table, "source IDs are not unique")
        if value <= previous:
            _fail(table, "source rows are not in canonical increasing ID order")
        ids.add(value)
        previous = value
    return ids


def _validate_rows(
    result: Mapping[str, Any],
    points: list[dict[str, Any]],
    components: list[dict[str, Any]],
    bond_states: list[dict[str, Any]],
    broken_bonds: list[dict[str, Any]],
    isolated_points: list[dict[str, Any]],
) -> dict[str, int]:
    points_by_id: dict[int, dict[str, Any]] = {}
    point_ids = _source_ids(points, "points.csv", "point_id")
    components_ids = _source_ids(components, "components.csv", "point_id")
    if point_ids != components_ids:
        _fail("components.csv.point_id", "points and components ID rosters differ")

    state = result.get("state")
    if not isinstance(state, Mapping):
        _fail("result.state", "required result state metadata is absent", "INCOMPLETE")
    declared_point_count = state.get("point_count")
    if isinstance(declared_point_count, bool) or not isinstance(declared_point_count, int) or declared_point_count <= 0:
        _fail("result.state.point_count", "declared point count is absent or invalid", "INCOMPLETE")
    if declared_point_count != len(points):
        _fail("result.state.point_count", "declared point count does not match bounded points.csv rows")
    if any(row["point_id"] != expected_id for expected_id, row in enumerate(points, start=1)):
        _fail("points.csv.point_id", "point IDs are not the complete declared 1-based roster")
    if state.get("point_ids_complete_unique") is not True:
        _fail("result.state.point_ids_complete_unique", "producer completeness claim is absent or false")

    component_by_id: dict[int, dict[str, Any]] = {}
    for row in points:
        point_id = row["point_id"]
        if not 0.0 <= row["damage"] <= 1.0:
            _fail("points.csv.damage", "damage is outside the declared [0, 1] range")
        if row["n_active_bonds"] < 0 or row["intact_bond_component_id"] <= 0:
            _fail("points.csv", "point bond count or component label is invalid")
        if row["volume_m3"] <= 0 or row["mass_kg"] <= 0:
            _fail("points.csv", "point volume and mass must be positive")
        points_by_id[point_id] = row
    for row in components:
        if row["component_id"] <= 0:
            _fail("components.csv.component_id", "component labels must be positive integers")
        if not 0.0 <= row["damage"] <= 1.0 or row["point_mass_kg"] <= 0:
            _fail("components.csv", "component damage or point mass is invalid")
        component_by_id[row["point_id"]] = row
        point_row = points_by_id[row["point_id"]]
        if row["component_id"] != point_row["intact_bond_component_id"]:
            _fail("components.csv.component_id", "component label contradicts points.csv")
        if row["point_mass_kg"] != point_row["mass_kg"]:
            _fail("components.csv.point_mass_kg", "point mass contradicts points.csv")
        if row["damage"] != point_row["damage"]:
            _fail("components.csv.damage", "point damage contradicts points.csv")

    point_set = set(points_by_id)
    bond_keys: set[tuple[int, int]] = set()
    active_degree = {point_id: 0 for point_id in point_set}
    inactive_keys: set[tuple[int, int]] = set()
    previous_key: tuple[int, int] | None = None
    bond_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    for row in bond_states:
        point_i, point_j = row["point_i_global"], row["point_j_global"]
        key = (point_i, point_j)
        if point_i >= point_j or point_i not in point_set or point_j not in point_set:
            _fail("bond_states.csv", "bond endpoints must be valid point IDs in increasing canonical order")
        if key in bond_keys:
            _fail("bond_states.csv", "bond endpoint pair is duplicated")
        if previous_key is not None and key <= previous_key:
            _fail("bond_states.csv", "bond rows are not in canonical sorted order")
        if row["reference_length_m"] <= 0 or row["current_length_m"] <= 0:
            _fail("bond_states.csv", "bond lengths must be positive finite SI values")
        bond_keys.add(key)
        previous_key = key
        bond_by_key[key] = row
        if row["active"]:
            active_degree[point_i] += 1
            active_degree[point_j] += 1
        else:
            inactive_keys.add(key)
    for point_id, point_row in points_by_id.items():
        if point_row["n_active_bonds"] != active_degree[point_id]:
            _fail("points.csv.n_active_bonds", "point active-bond count contradicts bond_states.csv")

    broken_keys: set[tuple[int, int]] = set()
    previous_key = None
    for row in broken_bonds:
        point_i, point_j = row["point_i_global"], row["point_j_global"]
        key = (point_i, point_j)
        if point_i >= point_j or point_i not in point_set or point_j not in point_set:
            _fail("broken_bonds.csv", "broken-bond endpoints must be valid point IDs in increasing canonical order")
        if key in broken_keys:
            _fail("broken_bonds.csv", "broken-bond endpoint pair is duplicated")
        if previous_key is not None and key <= previous_key:
            _fail("broken_bonds.csv", "broken-bond rows are not in canonical sorted order")
        source_bond = bond_by_key.get(key)
        if source_bond is None or source_bond["active"]:
            _fail("broken_bonds.csv", "broken bonds must be an inactive subset of bond_states.csv")
        if row["reference_length_m"] != source_bond["reference_length_m"]:
            _fail("broken_bonds.csv.reference_length_m", "broken-bond reference length contradicts bond_states.csv")
        if row["current_length_m"] != source_bond["current_length_m"]:
            _fail("broken_bonds.csv.current_length_m", "broken-bond current length contradicts bond_states.csv")
        if row["reference_length_m"] <= 0 or row["current_length_m"] <= 0:
            _fail("broken_bonds.csv", "broken-bond lengths must be positive finite SI values")
        broken_keys.add(key)
        previous_key = key
    if broken_keys != inactive_keys:
        _fail("broken_bonds.csv", "broken_bonds.csv does not equal the inactive bond-state subset")

    isolated_ids = _source_ids(isolated_points, "isolated_points.csv", "point_id") if isolated_points else set()
    expected_isolated_ids = {point_id for point_id, degree in active_degree.items() if degree == 0}
    if isolated_ids != expected_isolated_ids:
        _fail("isolated_points.csv.point_id", "isolated-point roster contradicts zero-degree points in bond_states.csv")
    for row in isolated_points:
        point = points_by_id[row["point_id"]]
        for name in ("x_ref_m", "y_ref_m", "z_ref_m"):
            if row[name] != point[name]:
                _fail(f"isolated_points.csv.{name}", "isolated-point coordinates contradict points.csv")
        if row["mass_kg"] != point["mass_kg"]:
            _fail("isolated_points.csv.mass_kg", "isolated-point mass contradicts points.csv")

    declared_bonds = state.get("canonical_initial_bond_pairs")
    declared_broken = state.get("broken_bond_pairs_at_endpoint")
    if isinstance(declared_bonds, bool) or not isinstance(declared_bonds, int) or declared_bonds != len(bond_states):
        _fail("result.state.canonical_initial_bond_pairs", "declared bond count contradicts bond_states.csv")
    if isinstance(declared_broken, bool) or not isinstance(declared_broken, int) or declared_broken != len(broken_bonds):
        _fail("result.state.broken_bond_pairs_at_endpoint", "declared broken-bond count contradicts broken_bonds.csv")
    if state.get("broken_state_consistent") is not True:
        _fail("result.state.broken_state_consistent", "producer broken-state consistency claim is absent or false")

    return {
        "point_rows": len(points),
        "component_rows": len(components),
        "bond_state_rows": len(bond_states),
        "broken_bond_rows": len(broken_bonds),
        "isolated_point_rows": len(isolated_points),
        "inactive_bond_rows": len(inactive_keys),
    }


def _caller_rows_match(
    supplied: Any,
    source_rows: Sequence[Mapping[str, Any]],
    table_name: str,
) -> bool:
    if not isinstance(supplied, list) or len(supplied) != len(source_rows):
        return False
    specs = _TABLE_SPECS[table_name]
    expected_names = {item[0] for item in specs}
    for supplied_row, source_row in zip(supplied, source_rows):
        if not isinstance(supplied_row, Mapping) or set(supplied_row) != expected_names:
            return False
        for name, dtype, _unit, _frame in specs:
            value = supplied_row.get(name)
            source_value = source_row[name]
            if dtype == "bool":
                if type(value) is not bool or value is not source_value:
                    return False
            elif dtype == "int":
                if isinstance(value, bool) or not isinstance(value, int) or value != source_value:
                    return False
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return False
                numeric = float(value)
                if not math.isfinite(numeric) or numeric != source_value:
                    return False
    return True


def _base_report() -> dict[str, Any]:
    unknown_components = {
        name: {
            "status": "UNKNOWN",
            "bytes_verified": False,
            "rows_compared": 0,
            "files": {},
            "caller_match": "UNKNOWN",
        }
        for name in ("points", "bonds", "components")
    }
    return {
        "schema": REPORT_SCHEMA,
        "status": "INCOMPLETE",
        "scope": "PG_DIAGNOSTIC_ONLY",
        "source_binding": {
            "status": "UNKNOWN",
            "producer_rows_compared": False,
            "dictionary": {"status": "UNKNOWN", "bytes_verified": False, "path": None},
            "components": unknown_components,
            "component_partition_validation": {
                "status": "UNKNOWN",
                "reason": "component labels are cross-checked with points.csv but graph connectivity is not recomputed",
            },
        },
        "caller_match": {"status": "UNKNOWN", "components": {}},
        "job_source": {
            "status": "UNKNOWN",
            "bytes_verified": False,
            "job_id_match": None,
            "sha256_match": None,
            "source_supplied": False,
        },
        "result_source": {
            "bytes_read": 0,
            "sha256": None,
            "external_sha256_verified": False,
        },
        "fixture_context": {"initial_condition_kind": "UNKNOWN"},
        "capabilities": {
            "physical_fragments": {"status": "UNKNOWN", "reason": "endpoint intact-bond components do not certify physical fragments"},
            "crack_surfaces": {"status": "UNKNOWN", "reason": "surface geometry and paired-face lineage are not source fields in this fixture"},
            "event_history": {"status": "UNKNOWN", "reason": "endpoint bond state does not contain a per-step event timeline"},
            "historical_R2": {"status": "UNKNOWN", "reason": "no historical surface adjacency or relation labels are emitted"},
        },
        "errors": [],
    }


def _verify_job_source(
    report: dict[str, Any],
    result: Mapping[str, Any],
    job_path: str | Path | None,
    expected_job_sha256: str | None,
) -> None:
    if job_path is None:
        if expected_job_sha256 is not None:
            report["job_source"]["reason"] = "expected hash was supplied without a job source file"
        else:
            report["job_source"]["reason"] = "job source file was not supplied; result job identity and hash remain declarations"
        return
    report["job_source"]["source_supplied"] = True
    source_path = Path(job_path)
    _reject_link_components(source_path)
    try:
        resolved = source_path.resolve(strict=True)
        if not resolved.is_file():
            _fail("job_source", "explicit job source is not a regular file", "INCOMPLETE")
    except _ReadFailure:
        raise
    except OSError:
        _fail("job_source", "explicit job source is unavailable", "INCOMPLETE")
    raw = _read_bounded_file(resolved, MAX_JOB_BYTES, "job_source")
    job = _strict_json(raw, "job_source")
    if job.get("schema") != JOB_SCHEMA:
        _fail("job_source.schema", "explicit job source has an unsupported schema")
    result_input = result.get("input")
    if not isinstance(result_input, Mapping):
        _fail("result.input", "result input identity metadata is absent", "INCOMPLETE")
    declared_hash = result_input.get("job_sha256")
    if not isinstance(declared_hash, str) or not _SHA256_RE.fullmatch(declared_hash):
        _fail("result.input.job_sha256", "result job hash is absent or malformed", "INCOMPLETE")
    actual_hash = _sha256(raw)
    hash_matches_result = actual_hash == declared_hash.lower()
    hash_matches_expected = True
    if expected_job_sha256 is not None:
        if not isinstance(expected_job_sha256, str) or not _SHA256_RE.fullmatch(expected_job_sha256):
            _fail("expected_job_sha256", "expected job hash is malformed")
        hash_matches_expected = actual_hash == expected_job_sha256.lower()
    source_job_id = job.get("job_id")
    result_job_id = result.get("job_id")
    safe_source_id = isinstance(source_job_id, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", source_job_id)
    safe_result_id = isinstance(result_job_id, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", result_job_id)
    id_matches = bool(safe_source_id and safe_result_id and source_job_id == result_job_id)
    report["job_source"].update({
        "status": "SOURCE_VERIFIED" if hash_matches_result and hash_matches_expected and id_matches else "MISMATCH",
        "bytes_verified": True,
        "bytes": len(raw),
        "sha256": actual_hash,
        "job_id_match": id_matches,
        "sha256_match": hash_matches_result and hash_matches_expected,
    })
    if not hash_matches_result or not hash_matches_expected:
        _fail("job_source.sha256", "explicit job source SHA-256 does not match the result or requested digest")
    if not id_matches:
        _fail("job_source.job_id", "explicit job source ID does not match result job ID")


def read_pgfrag_result(
    result_root: str | Path,
    *,
    expected_result_sha256: str | None = None,
    job_path: str | Path | None = None,
    expected_job_sha256: str | None = None,
    caller_normalized_rows: Mapping[str, Any] | None = None,
    include_normalized_rows: bool = False,
) -> dict[str, Any]:
    """Read one PG-Frag result directory without trusting caller PASS claims.

    ``result_root`` must explicitly name the directory containing ``result.json``.
    Every path in ``result.json.outputs`` is checked as a canonical root-relative
    POSIX path. The output count, per-file size, aggregate bytes, and all consumed
    output digests are bounded and verified. ``expected_result_sha256`` optionally
    binds the result metadata bytes to an independently supplied digest.
    ``job_path`` optionally supplies the actual job JSON bytes used to verify the
    result's declared job hash and ID.

    ``caller_normalized_rows`` may contain typed lists under ``points``,
    ``components``, ``bonds`` (bond-state rows), and ``broken_bonds``. A caller
    match is reported only after exact typed comparison with the source rows.
    ``include_normalized_rows`` is opt-in because the bond table may be sizable.
    All coordinates, velocities, lengths, masses, and volumes stay in their
    explicit SI units; no silent millimeter conversion is performed.
    """
    report = _base_report()
    try:
        root = _root_directory(result_root)
        result_path = _safe_output_path(root, "result.json")
        result_raw = _read_bounded_file(result_path, MAX_RESULT_BYTES, "result.json")
        actual_result_hash = _sha256(result_raw)
        report["result_source"].update({"bytes_read": len(result_raw), "sha256": actual_result_hash})
        if expected_result_sha256 is not None:
            if not isinstance(expected_result_sha256, str) or not _SHA256_RE.fullmatch(expected_result_sha256):
                _fail("expected_result_sha256", "expected result hash is malformed")
            if actual_result_hash != expected_result_sha256.lower():
                _fail("result.json.sha256", "result metadata SHA-256 does not match the supplied digest")
            report["result_source"]["external_sha256_verified"] = True
        result = _strict_json(result_raw, "result.json")
        if result.get("schema") != RESULT_SCHEMA:
            _fail("result.schema", "unsupported PG-Frag result schema")
        if result.get("status") != "COMPLETED":
            _fail("result.status", "PG-Frag result is not marked COMPLETED", "INCOMPLETE")

        records = _verify_outputs(root, result)
        dictionary_path = result.get("data_dictionary_path")
        if dictionary_path != "data_dictionary.json":
            _fail("result.data_dictionary_path", "result must name the supported root-relative data dictionary")

        verified: dict[str, dict[str, Any]] = {}
        raw_tables: dict[str, bytes] = {}
        for name in sorted(_REQUIRED_OUTPUTS):
            raw, evidence = _read_verified_output(records, name, name)
            raw_tables[name] = raw
            verified[name] = evidence
        _validate_dictionary(raw_tables["data_dictionary.json"])

        points = _parse_csv(raw_tables["points.csv"], "points.csv")
        components = _parse_csv(raw_tables["components.csv"], "components.csv")
        bond_states = _parse_csv(raw_tables["bond_states.csv"], "bond_states.csv")
        # A header-only broken or isolated table is accepted only if the other
        # source tables prove the corresponding set is empty.
        broken_bonds = _parse_csv(raw_tables["broken_bonds.csv"], "broken_bonds.csv", allow_header_only=True)
        isolated_points = _parse_csv(raw_tables["isolated_points.csv"], "isolated_points.csv", allow_header_only=True)
        counts = _validate_rows(result, points, components, bond_states, broken_bonds, isolated_points)

        result_input = result.get("input")
        if isinstance(result_input, Mapping):
            claimed_job_hash = result_input.get("job_sha256")
            if not isinstance(claimed_job_hash, str) or not _SHA256_RE.fullmatch(claimed_job_hash):
                _fail("result.input.job_sha256", "result job hash is absent or malformed", "INCOMPLETE")
        else:
            _fail("result.input", "result input identity metadata is absent", "INCOMPLETE")
        result_job_id = result.get("job_id")
        if not isinstance(result_job_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", result_job_id):
            _fail("result.job_id", "result job ID is absent or malformed", "INCOMPLETE")

        source_binding_components = report["source_binding"]["components"]
        report["source_binding"]["dictionary"] = {
            "status": "SOURCE_VERIFIED",
            "bytes_verified": verified["data_dictionary.json"]["bytes_verified"],
            "path": "data_dictionary.json",
        }
        source_binding_components["points"].update({
            "status": "SOURCE_VERIFIED",
            "bytes_verified": verified["points.csv"]["bytes_verified"],
            "rows_compared": counts["point_rows"],
            "files": {"points.csv": verified["points.csv"]},
            "caller_match": "UNKNOWN",
        })
        source_binding_components["components"].update({
            "status": "SOURCE_VERIFIED",
            "bytes_verified": verified["components.csv"]["bytes_verified"],
            "rows_compared": counts["component_rows"],
            "files": {"components.csv": verified["components.csv"]},
            "caller_match": "UNKNOWN",
        })
        source_binding_components["bonds"].update({
            "status": "SOURCE_VERIFIED",
            "bytes_verified": all(verified[name]["bytes_verified"] for name in (
                "bond_states.csv", "broken_bonds.csv", "isolated_points.csv",
            )),
            "rows_compared": counts["bond_state_rows"] + counts["broken_bond_rows"] + counts["isolated_point_rows"],
            "files": {name: verified[name] for name in (
                "bond_states.csv", "broken_bonds.csv", "isolated_points.csv",
            )},
            "inactive_bond_rows": counts["inactive_bond_rows"],
            "caller_match": "UNKNOWN",
        })
        report["source_binding"].update({"status": "SOURCE_VERIFIED", "producer_rows_compared": True})

        _verify_job_source(report, result, job_path, expected_job_sha256)
        initial_condition = result.get("initial_condition")
        initial_kind = initial_condition.get("kind") if isinstance(initial_condition, Mapping) else None
        report["fixture_context"]["initial_condition_kind"] = (
            initial_kind if initial_kind == "uniform_box_bar_fixture" else "UNKNOWN"
        )

        caller_matches: dict[str, str] = {}
        if caller_normalized_rows is not None:
            if not isinstance(caller_normalized_rows, Mapping):
                _fail("caller_normalized_rows", "caller normalized rows must be a mapping")
            caller_match_values = {
                "points": _caller_rows_match(caller_normalized_rows.get("points"), points, "points.csv"),
                "components": _caller_rows_match(caller_normalized_rows.get("components"), components, "components.csv"),
                "bonds": (
                    _caller_rows_match(caller_normalized_rows.get("bonds"), bond_states, "bond_states.csv")
                    and _caller_rows_match(caller_normalized_rows.get("broken_bonds"), broken_bonds, "broken_bonds.csv")
                ),
            }
            caller_matches = {name: ("MATCH" if matched else "MISMATCH") for name, matched in caller_match_values.items()}
            for name, value in caller_matches.items():
                source_binding_components[name]["caller_match"] = value
            report["caller_match"] = {
                "status": "MATCH" if all(caller_match_values.values()) else "MISMATCH",
                "components": caller_matches,
                "rows_compared": {
                    "points": len(points) if caller_match_values["points"] else 0,
                    "components": len(components) if caller_match_values["components"] else 0,
                    "bonds": len(bond_states) + len(broken_bonds) if caller_match_values["bonds"] else 0,
                },
            }
            if not all(caller_match_values.values()):
                report["status"] = "FAIL"
                report["errors"].append({
                    "field": "caller_normalized_rows",
                    "status": "FAIL",
                    "reason": "one or more supplied normalized-row components differ from source rows",
                })

        if include_normalized_rows:
            report["normalized_rows"] = {
                "points": points,
                "components": components,
                "bonds": bond_states,
                "broken_bonds": broken_bonds,
                "isolated_points": isolated_points,
            }
        report["identity"] = {
            "job_id": result_job_id,
            "declared_job_sha256": claimed_job_hash.lower(),
            "result_sha256": actual_result_hash,
            "result_bytes": len(result_raw),
            "result_external_sha256_verified": report["result_source"]["external_sha256_verified"],
        }
        report["row_counts"] = counts
        if report["status"] != "FAIL":
            report["status"] = "PG_DIAGNOSTIC_ONLY"
        return report
    except _ReadFailure as exc:
        report["status"] = exc.status
        if report["source_binding"]["status"] != "SOURCE_VERIFIED":
            report["source_binding"]["status"] = "FAIL" if exc.status == "FAIL" else "UNKNOWN"
            report["source_binding"]["producer_rows_compared"] = False
        report["errors"].append({"field": exc.field, "status": exc.status, "reason": exc.reason})
        if caller_normalized_rows is not None:
            report["caller_match"] = {"status": "UNKNOWN", "components": {}}
        return report
    except Exception:
        # Parser diagnostics never include raw paths, source contents, or traces.
        report["status"] = "FAIL"
        if report["source_binding"]["status"] != "SOURCE_VERIFIED":
            report["source_binding"]["status"] = "FAIL"
            report["source_binding"]["producer_rows_compared"] = False
        report["errors"].append({"field": "source_reader", "status": "FAIL", "reason": "source payload could not be safely interpreted"})
        return report


__all__ = ["read_pgfrag_result"]
