from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
from pathlib import Path

from synlab.qa.source_readers.pgfrag_result import read_pgfrag_result


_ACTUAL_OUTPUT = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "pgfrag"
    / "result_v1_toy_endpoint"
    / "output"
)
_FIXTURE_JOB = _ACTUAL_OUTPUT.parent / "job.json"
_FIXTURE_JOB_SHA256 = "83af8ea8cb0fd204ab288841fd87382c9dae77ec1cfb5dc9d0c925d610d430d1"
_FIXTURE_RESULT_SHA256 = "b3fb84f20d409f4a4dca0b34ffd8b95a07b7c7944b8b6ecd70100b0b5b17dc20"


def _load_result(root: Path) -> dict:
    return json.loads((root / "result.json").read_text(encoding="utf-8"))


def _save_result(root: Path, result: dict) -> None:
    raw = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    (root / "result.json").write_bytes(raw)


def _refresh_output(root: Path, relative_path: str) -> None:
    result = _load_result(root)
    payload = (root / relative_path).read_bytes()
    record = next(item for item in result["outputs"] if item["path"] == relative_path)
    record["bytes"] = len(payload)
    record["sha256"] = hashlib.sha256(payload).hexdigest()
    _save_result(root, result)


def _copy_actual_output(tmp_path: Path) -> Path:
    target = tmp_path / "output"
    target.mkdir()
    result = _load_result(_ACTUAL_OUTPUT)
    shutil.copy2(_ACTUAL_OUTPUT / "result.json", target / "result.json")
    for item in result["outputs"]:
        shutil.copy2(_ACTUAL_OUTPUT / item["path"], target / item["path"])
    return target


def _read_csv(root: Path, relative_path: str) -> tuple[list[str], list[list[str]]]:
    with (root / relative_path).open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    return rows[0], rows[1:]


def _write_csv(root: Path, relative_path: str, header: list[str], rows: list[list[str]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    (root / relative_path).write_text(buffer.getvalue(), encoding="utf-8", newline="")
    _refresh_output(root, relative_path)


def _header_only(root: Path, relative_path: str) -> None:
    header, _rows = _read_csv(root, relative_path)
    _write_csv(root, relative_path, header, [])


def _synthetic_zero_broken_output(root: Path) -> Path:
    root.mkdir()
    dictionary = json.loads((_ACTUAL_OUTPUT / "data_dictionary.json").read_text(encoding="utf-8"))
    payloads = {
        "data_dictionary.json": (json.dumps(dictionary, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        "points.csv": (
            "point_id,x_ref_m,y_ref_m,z_ref_m,x_current_m,y_current_m,z_current_m,vx_mps,vy_mps,vz_mps,damage,n_active_bonds,strain_energy_density_J_m3,volume_m3,mass_kg,intact_bond_component_id\n"
            "1,0,0,0,0,0,0,0,0,0,0,1,0,1e-9,1e-6,1\n"
            "2,0.001,0,0,0.001,0,0,0,0,0,0,1,0,1e-9,1e-6,1\n"
        ).encode("utf-8"),
        "components.csv": (
            "point_id,component_id,point_mass_kg,damage\n"
            "1,1,1e-6,0\n"
            "2,1,1e-6,0\n"
        ).encode("utf-8"),
        "bond_states.csv": (
            "point_i_global,point_j_global,active,reference_length_m,current_length_m\n"
            "1,2,true,0.001,0.001\n"
        ).encode("utf-8"),
        "broken_bonds.csv": b"point_i_global,point_j_global,reference_length_m,current_length_m\n",
        "isolated_points.csv": b"point_id,x_ref_m,y_ref_m,z_ref_m,mass_kg\n",
    }
    outputs = []
    for name, payload in payloads.items():
        (root / name).write_bytes(payload)
        outputs.append({"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    result = {
        "schema": "pgfrag.result.v1",
        "status": "COMPLETED",
        "data_dictionary_path": "data_dictionary.json",
        "initial_condition": {"kind": "uniform_box_bar_fixture"},
        "job_id": "fixture-zero-broken",
        "input": {"job_sha256": "0" * 64},
        "outputs": outputs,
        "state": {
            "point_count": 2,
            "point_ids_complete_unique": True,
            "canonical_initial_bond_pairs": 1,
            "broken_bond_pairs_at_endpoint": 0,
            "broken_state_consistent": True,
        },
    }
    _save_result(root, result)
    return root


def test_actual_pgfrag_v1_is_source_bound_and_stays_diagnostic_only() -> None:
    report = read_pgfrag_result(
        _ACTUAL_OUTPUT,
        expected_result_sha256=_FIXTURE_RESULT_SHA256,
        job_path=_FIXTURE_JOB,
        expected_job_sha256=_FIXTURE_JOB_SHA256,
    )

    assert report["schema"] == "synlab.pgfrag.source_read.v1"
    assert report["status"] == "PG_DIAGNOSTIC_ONLY"
    assert report["scope"] == "PG_DIAGNOSTIC_ONLY"
    assert report["fixture_context"]["initial_condition_kind"] == "uniform_box_bar_fixture"
    assert report["row_counts"]["point_rows"] == 576
    assert report["row_counts"]["bond_state_rows"] == 20_780
    assert report["row_counts"]["broken_bond_rows"] == 5_236
    for component in ("points", "bonds", "components"):
        assert report["source_binding"]["components"][component]["bytes_verified"] is True
        assert report["source_binding"]["components"][component]["rows_compared"] > 0
    assert report["source_binding"]["components"]["points"]["files"]["points.csv"]["sha256_verified"] is True
    assert report["job_source"]["status"] == "SOURCE_VERIFIED"
    assert report["job_source"]["job_id_match"] is True
    assert report["job_source"]["sha256_match"] is True
    assert report["result_source"]["external_sha256_verified"] is True
    assert report["result_source"]["bytes_read"] == len((_ACTUAL_OUTPUT / "result.json").read_bytes())
    assert report["source_binding"]["component_partition_validation"]["status"] == "UNKNOWN"
    assert report["capabilities"]["physical_fragments"]["status"] == "UNKNOWN"
    assert report["capabilities"]["historical_R2"]["status"] == "UNKNOWN"
    assert "fragment_count" not in report
    assert "normalized_rows" not in report


def test_reader_compares_caller_rows_only_after_exact_typed_match() -> None:
    source = read_pgfrag_result(_ACTUAL_OUTPUT, include_normalized_rows=True)
    assert source["status"] == "PG_DIAGNOSTIC_ONLY"

    matched = read_pgfrag_result(
        _ACTUAL_OUTPUT,
        caller_normalized_rows=source["normalized_rows"],
    )
    assert matched["caller_match"]["status"] == "MATCH"
    assert set(matched["caller_match"]["components"].values()) == {"MATCH"}

    partial = read_pgfrag_result(_ACTUAL_OUTPUT, caller_normalized_rows={"points": []})
    assert partial["status"] == "FAIL"
    assert partial["caller_match"]["status"] == "MISMATCH"
    assert partial["source_binding"]["status"] == "SOURCE_VERIFIED"
    assert partial["source_binding"]["producer_rows_compared"] is True
    assert "MATCH" not in partial["caller_match"]["components"].values()


def test_caller_row_value_mismatch_fails_while_preserving_source_evidence() -> None:
    source = read_pgfrag_result(_ACTUAL_OUTPUT, include_normalized_rows=True)
    assert source["status"] == "PG_DIAGNOSTIC_ONLY"
    caller_rows = source["normalized_rows"]
    caller_rows["points"][0]["x_ref_m"] += 0.001

    report = read_pgfrag_result(_ACTUAL_OUTPUT, caller_normalized_rows=caller_rows)

    assert report["status"] == "FAIL"
    assert report["caller_match"]["status"] == "MISMATCH"
    assert report["source_binding"]["status"] == "SOURCE_VERIFIED"
    assert report["source_binding"]["components"]["points"]["caller_match"] == "MISMATCH"
    assert report["errors"][0]["field"] == "caller_normalized_rows"


def test_result_checksum_is_only_external_when_explicitly_matched() -> None:
    result_raw = (_ACTUAL_OUTPUT / "result.json").read_bytes()
    report = read_pgfrag_result(_ACTUAL_OUTPUT)
    assert report["result_source"]["external_sha256_verified"] is False

    mismatch = read_pgfrag_result(_ACTUAL_OUTPUT, expected_result_sha256="0" * 64)

    assert report["result_source"]["sha256"] == hashlib.sha256(result_raw).hexdigest()
    assert mismatch["status"] == "FAIL"
    assert mismatch["errors"][0]["field"] == "result.json.sha256"
    assert mismatch["result_source"]["bytes_read"] == len(result_raw)


def test_hash_mismatch_is_not_hidden_by_manifest_declaration(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    payload = (root / "points.csv").read_bytes()
    changed = payload.replace(b"-0.0025", b"-0.0026", 1)
    assert len(changed) == len(payload)
    assert changed != payload
    (root / "points.csv").write_bytes(changed)

    report = read_pgfrag_result(root)

    assert report["status"] == "FAIL"
    assert report["source_binding"]["status"] == "FAIL"
    assert report["errors"][0]["field"] == "points.csv"
    assert "traceback" not in json.dumps(report).lower()


def test_dictionary_unit_must_be_explicit_and_match_si_source(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    dictionary = json.loads((root / "data_dictionary.json").read_text(encoding="utf-8"))
    dictionary["tables"]["points.csv"]["columns"]["x_ref_m"]["unit"] = "mm"
    (root / "data_dictionary.json").write_text(json.dumps(dictionary, indent=2) + "\n", encoding="utf-8")
    _refresh_output(root, "data_dictionary.json")

    report = read_pgfrag_result(root)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["field"].endswith("x_ref_m.unit")


def test_dictionary_frame_mismatch_fails_closed(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    dictionary = json.loads((root / "data_dictionary.json").read_text(encoding="utf-8"))
    dictionary["tables"]["points.csv"]["columns"]["x_ref_m"]["frame"] = "left_handed_z_up"
    (root / "data_dictionary.json").write_text(json.dumps(dictionary, indent=2) + "\n", encoding="utf-8")
    _refresh_output(root, "data_dictionary.json")

    report = read_pgfrag_result(root)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["field"].endswith("x_ref_m.frame")


def test_points_components_id_rosters_must_be_complete_unique_and_equal(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    header, rows = _read_csv(root, "components.csv")
    rows[0][0] = rows[1][0]
    _write_csv(root, "components.csv", header, rows)

    report = read_pgfrag_result(root)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["field"] == "components.csv"


def test_bond_endpoint_orphan_is_rejected(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    header, rows = _read_csv(root, "bond_states.csv")
    rows[0][1] = "9999"
    _write_csv(root, "bond_states.csv", header, rows)

    report = read_pgfrag_result(root)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["field"] == "bond_states.csv"


def test_broken_bond_lengths_must_match_inactive_state_rows(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    header, rows = _read_csv(root, "broken_bonds.csv")
    rows[0][2] = "0.5"
    _write_csv(root, "broken_bonds.csv", header, rows)

    report = read_pgfrag_result(root)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["field"] == "broken_bonds.csv.reference_length_m"


def test_nonfinite_csv_numeric_is_rejected_even_with_updated_hash(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    header, rows = _read_csv(root, "points.csv")
    rows[0][10] = "NaN"
    _write_csv(root, "points.csv", header, rows)

    report = read_pgfrag_result(root)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["field"] == "points.csv"


def test_empty_main_csv_is_incomplete_not_a_zero_point_result(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    _header_only(root, "points.csv")

    report = read_pgfrag_result(root)

    assert report["status"] == "INCOMPLETE"
    assert report["source_binding"]["status"] == "UNKNOWN"


def test_huge_declared_point_count_is_rejected_before_roster_construction(tmp_path: Path) -> None:
    root = _synthetic_zero_broken_output(tmp_path / "huge-count")
    result = _load_result(root)
    result["state"]["point_count"] = 1_000_000_000
    _save_result(root, result)

    report = read_pgfrag_result(root)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["field"] == "result.state.point_count"
    assert report["source_binding"]["status"] == "FAIL"


def test_header_only_broken_and_isolated_tables_require_zero_controls(tmp_path: Path) -> None:
    root = _synthetic_zero_broken_output(tmp_path / "zero-control")

    report = read_pgfrag_result(root)

    assert report["status"] == "PG_DIAGNOSTIC_ONLY"
    assert report["row_counts"]["broken_bond_rows"] == 0
    assert report["row_counts"]["isolated_point_rows"] == 0
    assert report["source_binding"]["components"]["bonds"]["bytes_verified"] is True


def test_header_only_broken_table_fails_when_source_has_inactive_bonds(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    _header_only(root, "broken_bonds.csv")

    report = read_pgfrag_result(root)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["field"] == "broken_bonds.csv"


def test_job_hash_and_id_are_verified_from_explicit_source_bytes(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    job_path = tmp_path / "job.json"
    job_raw = json.dumps({"schema": "pgfrag.job.v1", "job_id": "osb-fracture-branch-001"}, sort_keys=True).encode("utf-8")
    job_path.write_bytes(job_raw)
    job_hash = hashlib.sha256(job_raw).hexdigest()
    result = _load_result(root)
    result["input"]["job_sha256"] = job_hash
    _save_result(root, result)

    report = read_pgfrag_result(root, job_path=job_path, expected_job_sha256=job_hash)

    assert report["status"] == "PG_DIAGNOSTIC_ONLY"
    assert report["job_source"]["status"] == "SOURCE_VERIFIED"
    assert report["job_source"]["bytes_verified"] is True
    assert report["job_source"]["job_id_match"] is True
    assert report["job_source"]["sha256_match"] is True


def test_job_declaration_cannot_override_source_hash_mismatch(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    job_path = tmp_path / "job.json"
    job_raw = json.dumps({"schema": "pgfrag.job.v1", "job_id": "osb-fracture-branch-001"}, sort_keys=True).encode("utf-8")
    job_path.write_bytes(job_raw)

    report = read_pgfrag_result(root, job_path=job_path, expected_job_sha256="0" * 64)

    assert report["status"] == "FAIL"
    assert report["job_source"]["bytes_verified"] is True
    assert report["job_source"]["sha256_match"] is False


def test_output_path_traversal_is_rejected(tmp_path: Path) -> None:
    root = _copy_actual_output(tmp_path)
    result = _load_result(root)
    result["outputs"][0]["path"] = "../points.csv"
    _save_result(root, result)

    report = read_pgfrag_result(root)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["field"] == "outputs.path"


def test_duplicate_json_keys_are_rejected_without_parser_details(tmp_path: Path) -> None:
    root = tmp_path / "duplicate-result"
    root.mkdir()
    (root / "result.json").write_text('{"schema":"pgfrag.result.v1","schema":"pgfrag.result.v1"}', encoding="utf-8")

    report = read_pgfrag_result(root)

    assert report["status"] == "FAIL"
    assert report["errors"][0]["field"] == "result.json"
    assert "traceback" not in json.dumps(report).lower()

