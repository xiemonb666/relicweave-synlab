"""Audit fa莽ade, A10 report contract and the measurements parquet (plan 15.7, A10)."""

from __future__ import annotations

import json

import pyarrow.parquet as pq
import pytest

from synlab.degrade.api import (
    audit_all_axes,
    audit_axis,
    operator_audit_table,
    probe_sources,
    write_operator_measurements,
)
from synlab.degrade.registry import AXIS_REGISTRY

from tests.a12.operators.operator_test_support import ALL_AXES


def test_audit_all_axes_report_contract(probe: dict, source_store, tmp_path) -> None:
    report = audit_all_axes(source_store, levels=[0, 1], sources=probe)
    assert set(report) >= {"ok", "identity_ok", "axes", "denominators", "measurements"}
    assert report["identity_ok"] is True
    assert sorted(report["axes"]) == sorted(AXIS_REGISTRY.ids())
    for axis_id, entry in report["axes"].items():
        assert entry["status"] in ("PASS", "FAIL", "NA", "MISSING"), axis_id
        assert isinstance(entry["independent_mothers"], int)
        assert set(entry["levels"]) == {"0", "1"}
        for level, row in entry["levels"].items():
            assert row["status"] in ("PASS", "FAIL", "NA")
            if row["status"] == "PASS":
                assert row.get("basis_id")
    assert report["denominators"]["axes_registered"] == 31
    assert report["denominators"]["axes_missing"] == 0
    identity_rows = [entry["levels"]["0"] for entry in report["axes"].values()]
    assert identity_rows and all(row["identity"] and row["bytes_unchanged"]
                                 for row in identity_rows)
    # the report is JSON-serialisable and carries no wall-clock fields (fixed-environment replay)
    text = json.dumps(report, ensure_ascii=False, default=str)
    assert "generated_at" not in text and "timestamp" not in text


def test_audit_axis_reports_levels_and_provenance(probe: dict) -> None:
    report = audit_axis("G01", levels=[0, 1, 4], store=None, sources=probe)
    assert report["axis_id"] == "G01"
    assert report["status"] in ("PASS", "FAIL", "NA")
    assert report["source"]["provenance"].startswith(("BUILTIN_PROBE", "STORE_ASSET"))
    assert report["levels"]["0"]["identity"] is True
    assert report["levels"]["1"]["status"] == "PASS"
    assert report["levels"]["1"]["measured"]["applied_rms_mm"] > 0


def test_audit_marks_failing_axes_instead_of_hiding_them(probe: dict) -> None:
    """A resolution-limited axis is reported as FAIL with its code, never silently as NA."""
    strict = audit_axis("P02", levels=[1, 2], store=None, sources=probe)
    assert strict["status"] in ("FAIL", "PASS")
    if strict["status"] == "FAIL":
        codes = {row.get("failure_code") for row in strict["levels"].values()}
        assert codes & {"PRECISION_NOT_REALIZED", "OPERATOR_NOT_REALIZED"}, codes
    ok = audit_axis("P05", levels=[1, 2], store=None, sources=probe)
    assert ok["status"] == "PASS"


def test_operator_audit_table_and_parquet(probe: dict, tmp_path) -> None:
    report = audit_all_axes(None, levels=[0, 1], sources=probe)
    rows = report["measurements"]
    assert rows, "the audit must emit measurement rows"
    table = operator_audit_table(rows)
    for column in ("axis_id", "variant", "level", "basis_id", "status", "source_hash",
                   "result_hash", "calibration_status"):
        assert column in table.column_names, column
    assert table.num_rows == len(rows)
    written = write_operator_measurements(rows, tmp_path / "operator_measurements.parquet")
    assert written["rows"] == len(rows)
    back = pq.read_table(written["path"])
    assert back.num_rows == len(rows)
    assert set(back.column("axis_id").to_pylist()) == set(AXIS_REGISTRY.ids())


def test_audit_uses_store_assets_when_available(source_store, stored_sources) -> None:
    """Without an explicit source provider the audit reads the store and labels provenance."""
    report = audit_all_axes(source_store, levels=[0], axes=["P03", "G01", "X02"])
    for axis_id in ("P03", "G01", "X02"):
        entry = report["axes"][axis_id]
        assert entry["levels"]["0"]["identity"] is True
    assert report["axes"]["X02"]["source"]["provenance"]


@pytest.mark.parametrize("axis_id", ALL_AXES)
def test_every_axis_can_be_audited_on_its_family_source(axis_id: str, probe: dict) -> None:
    """No axis may crash the audit: level 0 is proven on the family source for all 31 axes.

    Non-zero levels are covered by the effect tests and by the full audit contract test; running
    a complete SDF level per axis here would only repeat the same native work 31 times.
    """
    entry = audit_axis(axis_id, levels=[0], store=None, sources=probe)
    assert entry["status"] in ("PASS", "FAIL", "NA")
    assert entry["levels"]["0"]["identity"] is True
    assert entry["levels"]["0"]["bytes_unchanged"] is True
    assert entry["variant"] == AXIS_REGISTRY.get(axis_id).default_variant


def test_audit_is_reproducible(probe: dict) -> None:
    first = audit_all_axes(None, levels=[0, 1], sources=probe, axes=["P05", "G03", "X01"])
    second = audit_all_axes(None, levels=[0, 1], sources=probe, axes=["P05", "G03", "X01"])
    for axis_id in ("P05", "G03", "X01"):
        for level in ("1",):
            assert (first["axes"][axis_id]["levels"][level]["measured"]
                    == second["axes"][axis_id]["levels"][level]["measured"]), (axis_id, level)


def test_probe_sources_are_labelled(probe: dict) -> None:
    for family, bundle in probe.items():
        provenance = str(bundle.meta.get("provenance", ""))
        assert provenance, family
        assert provenance.startswith(("BUILTIN_PROBE", "STORE_ASSET", "NO_OBSERVATION")), provenance
    assert probe["I"].get("frames"), "the probe must deliver real views"
    assert probe["G"].get("points") is not None
    assert probe_sources.__doc__ and "provenance" in probe_sources.__doc__
