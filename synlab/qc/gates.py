"""Release gate evaluation (plan 30.18).

Gates are decided from *real evidence present in the store*: a gate is PASS only when the
corresponding audit artefact exists and reports success.  Absent evidence is PENDING, and
a PENDING REQUIRED gate blocks the release profile.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..errors import ErrorCode, SynLabError
from ..roles import (
    ROLE_CLEAN_TRUTH,
    ROLE_COVERAGE,
    ROLE_FEATURE_BUNDLE,
    ROLE_FRAGMENT_MESH,
    ROLE_LABEL_BUNDLE,
    ROLE_MATERIAL_PROFILE,
    ROLE_MOTHER_MESH,
    ROLE_OBS_RESULT,
    ROLE_OPERATOR_AUDIT,
    ROLE_PATTERN_AUDIT,
    ROLE_PATTERN_RECIPE,
    ROLE_PHYSICAL_COMPONENT,
    ROLE_PHYSICAL_RESULT,
    ROLE_POOL,
    ROLE_QA_REPORT,
    ROLE_RUN_SPEC,
)
from ..storage.release import PROFILE_GATES
from ..storage.store import QA_PASS, AssetStore


def _reports_dir(store: AssetStore) -> Path:
    path = store.root / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_dirs(store: AssetStore, extra: Sequence[str | Path] | None = None) -> list[Path]:
    """Report directories searched for gate evidence, most specific first.

    A closed-loop release is often frozen in a *new* store while the operator/pattern/registry
    audits live in the long-lived evidence store.  Rather than copying those reports around (or
    quietly inventing them), extra roots can be named explicitly and every gate records which
    file it actually read.
    """
    dirs = [_reports_dir(store)]
    for root in extra or ():
        path = Path(root)
        if path.name != "reports":
            path = path / "reports"
        if path not in dirs:
            dirs.append(path)
    return dirs


def load_report(store: AssetStore, name: str,
                extra_dirs: Sequence[str | Path] | None = None) -> dict[str, Any] | None:
    """Load ``<name>.json`` from the store's report directory, then from any extra root."""
    return load_report_from(reports_dirs(store, extra_dirs), name)[0]


def load_report_from(dirs: Sequence[Path], name: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(report, path)`` for the first directory that carries ``<name>.json``."""
    for directory in dirs:
        path = Path(directory) / f"{name}.json"
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8")), str(path)
        except (OSError, ValueError):
            return None, f"{path} (unreadable)"
    return None, None


def acceptance_item(summary: Mapping[str, Any] | None, acceptance_id: str) -> dict[str, Any]:
    """Read one A-item out of an ``acceptance_summary.json`` payload.

    ``synlab.qc.acceptance.run_acceptance`` nests every item under ``items`` (the top-level
    document carries ``counts``/``registry``/``summary_hash``).  Reading ``summary[acceptance_id]``
    therefore never matched, which silently turned every acceptance-backed gate into PENDING even
    when the item was recorded as PASS.  Both shapes are accepted here so a gate reads the real
    item instead of a key that does not exist.
    """
    if not isinstance(summary, Mapping):
        return {}
    items = summary.get("items")
    if isinstance(items, Mapping) and isinstance(items.get(acceptance_id), Mapping):
        return dict(items[acceptance_id])
    direct = summary.get(acceptance_id)
    return dict(direct) if isinstance(direct, Mapping) else {}


# --------------------------------------------------------------------------------------
# cross-run coverage aggregation (the coverage gates cannot be answered by one run)
# --------------------------------------------------------------------------------------
#: Report name the coverage gates prefer.  It is the *cross-run / cross-batch* aggregate written
#: by :func:`write_coverage_aggregate`; ``reports/coverage.json`` is store-global and is
#: overwritten by every generation, so it can only ever describe a single run.
COVERAGE_AGGREGATE_NAME = "coverage_aggregate"
COVERAGE_AGGREGATE_SCHEMA = "synlab.coverage_aggregate.v1"

#: What the coverage gates require, and the key each gate reads out of the coverage payload.
COVERAGE_TARGETS: dict[str, int] = {
    "vessels": 24, "materials": 12, "patterns": 16, "layer_combos": 4,
    "fracture_backends": 4, "axes": 31,
}
COVERAGE_GATE_KEYS: dict[str, str] = {
    "coverage_24_vessels": "vessels",
    "coverage_12_materials": "materials",
    "coverage_16_patterns": "patterns",
    "coverage_4_layers": "layer_combos",
    "coverage_4_backends": "fracture_backends",
    "coverage_31_axes": "axes",
}

#: Store report files that carry *per-lineage* coverage rows, most specific first.  The rows are
#: the only place a layer-combo id is recorded: the committed assets name the material, the vessel
#: and the pattern family, but never the layer combo, and the material profile only stores layer
#: *indices* (``layer_ids: [1]``).  Both shapes are read:
#:
#: * ``coverage_rows.json``    -- the list ``pipeline._write_coverage`` writes (a single run: the
#:   one named by the sibling ``coverage.json``);
#: * ``next_experiment_batches.json`` -- the batch driver's ledger, whose ``batches[]`` entries
#:   each name their ``run_id``, so it is the per-run record for a multi-run batch.
DEFAULT_COVERAGE_ROW_FILES: tuple[str, ...] = (
    "coverage_rows.json", "next_experiment_batches.json",
)

_ROW_ATTR_KEYS: tuple[str, ...] = ("vessel_id", "material_id", "pattern_id", "layer_combo_id",
                                   "backend")


def _runs_table(store: AssetStore) -> list[dict[str, Any]]:
    """Every run the store records, oldest first (``created_at`` then ``run_id``)."""
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT run_id, spec_hash, status, scope, profile, created_at, meta_json "
            "FROM runs ORDER BY created_at ASC, run_id ASC").fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        meta = json.loads(row["meta_json"] or "{}")
        out.append({"run_id": str(row["run_id"]), "spec_hash": row["spec_hash"],
                    "status": row["status"], "scope": row["scope"], "profile": row["profile"],
                    "created_at": row["created_at"],
                    "accepted": meta.get("accepted"), "attempted": meta.get("attempted")})
    return out


def registered_axis_ids() -> list[str]:
    """The axis ids this build registers (the denominator of ``coverage_31_axes``)."""
    try:
        from ..degrade.registry import AXIS_REGISTRY

        return sorted(str(a) for a in AXIS_REGISTRY.ids())
    except Exception:  # noqa: BLE001 - a missing registry must not silently shrink the target
        return []


def _asset_facts(store: AssetStore, *, limit: int = 500000) -> list[dict[str, Any]]:
    """The role/lineage/QA/attribution facts of every asset, without loading any payload."""
    facts: list[dict[str, Any]] = []
    for asset in store.list_assets(limit=limit):
        meta = dict(asset.meta or {})
        source = str(meta.get("run_id_source") or "")
        facts.append({
            "asset_id": asset.asset_id, "role": asset.role, "qa_status": asset.qa_status,
            "lineage_id": asset.lineage_id, "split": asset.split,
            "run_id": (str(meta["run_id"]) if meta.get("run_id") else None),
            "run_id_source": "repair" if source else ("commit" if meta.get("run_id") else "none"),
            "mother_id": meta.get("mother_id"), "vessel_id": meta.get("vessel_id"),
            "material_id": meta.get("material_id"),
            "family_id": meta.get("family_id") or meta.get("family"),
            "axis_id": meta.get("axis_id"), "backend": meta.get("backend"),
        })
    return facts


def _hash_of(path: Path) -> str | None:
    try:
        from ..canonical import hash_file

        return hash_file(path)
    except Exception:  # noqa: BLE001 - an unreadable optional source is reported, not fatal
        return None


def _row_source_rows(payload: Any) -> list[dict[str, Any]]:
    """Normalise one coverage-row file into a list of rows (both shipped shapes)."""
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    if isinstance(payload.get("rows"), list):
        return [dict(row) for row in payload["rows"] if isinstance(row, Mapping)]
    batches = payload.get("batches")
    if isinstance(batches, list):
        return [dict(row) for row in batches if isinstance(row, Mapping)]
    lineages = payload.get("lineages")
    if isinstance(lineages, Mapping):
        return [{"lineage_id": str(key), **dict(value)} for key, value in lineages.items()
                if isinstance(value, Mapping)]
    return []


def _coverage_row_sources(store: AssetStore,
                          extra_files: Sequence[str | Path] | None = None) -> dict[str, Any]:
    """Read the per-lineage coverage rows and say exactly which run each row belongs to.

    ``coverage_rows.json`` is store-global (overwritten by every generation) and carries no run
    id of its own, so its rows are attributed **only** to the run named by the sibling
    ``coverage.json`` -- the same rule ``tools/closed_loop.py`` uses.  A ledger whose rows name
    their own ``run_id`` (the batch driver's) keeps that attribution.
    """
    reports = store.root / "reports"
    summary: dict[str, Any] = {}
    summary_path = reports / "coverage.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary = {}
    ledger_run_id = summary.get("run_id")
    sources: list[dict[str, Any]] = []
    names = list(DEFAULT_COVERAGE_ROW_FILES) + [str(Path(p).name) for p in (extra_files or ())]
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        path = Path(name)
        if not path.is_absolute():
            path = reports / name
        if not path.exists():
            sources.append({"name": name, "path": str(path), "present": False,
                            "rows": [], "run_attribution": None})
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            sources.append({"name": name, "path": str(path), "present": True, "unreadable": str(exc),
                            "rows": [], "run_attribution": None})
            continue
        rows = _row_source_rows(payload)
        per_run = all(isinstance(row.get("run_id"), str) and row.get("run_id") for row in rows)
        if per_run:
            attribution = "row.run_id"
        elif ledger_run_id:
            attribution = f"coverage.json run_id ({ledger_run_id})"
        else:
            attribution = None
        sources.append({"name": name, "path": str(path), "present": True, "sha256": _hash_of(path),
                        "rows": rows, "row_count": len(rows), "run_attribution": attribution,
                        "ledger_run_id": ledger_run_id if not per_run else None})
    return {"sources": sources, "ledger_run_id": ledger_run_id,
            "ledger_path": str(summary_path) if summary_path.exists() else None}


def _rows_for_run(row_sources: Mapping[str, Any], run_id: str) -> list[dict[str, Any]]:
    """The accepted rows that belong to ``run_id``, with their source name attached."""
    out: list[dict[str, Any]] = []
    for source in row_sources.get("sources", []):
        attribution = source.get("run_attribution")
        if not attribution:
            continue
        if attribution == "row.run_id":
            picked = [row for row in source["rows"] if str(row.get("run_id")) == run_id]
        else:
            ledger = str(source.get("ledger_run_id"))
            if ledger != run_id:
                continue
            picked = list(source["rows"])
        for row in picked:
            accepted = row.get("accepted")
            if accepted is None:
                accepted = row.get("ok")
            if accepted is None:
                accepted = row.get("status") in ("OK", "QA_PASSED")
            out.append({**row, "_source": source["name"], "_accepted": bool(accepted)})
    return out


def coverage_aggregate(store: AssetStore, *, limit: int = 500000,
                       extra_row_files: Sequence[str | Path] | None = None) -> dict[str, Any]:
    """Aggregate real coverage over **every run in the store** (cross-run / cross-batch).

    Why this exists: ``reports/coverage.json`` is written by ``pipeline.run_generation`` once per
    run and overwrites the previous one, while a batch of data is produced as *many* runs (one
    ``run_id`` per batch).  A single run can therefore never show 24 vessels -- the coverage gates
    have to read an aggregate, and that aggregate has to be reproducible from the store.

    Every number comes from one of three measured sources, each recorded in ``sources``:

    * ``assets`` -- role/QA/lineage and the metadata keys the run itself wrote
      (``mother_mesh.vessel_id/material_id/mother_id``, ``pattern_recipe.family_id``,
      ``fragment_mesh.backend``, ``physical_component.axis_id`` ...).  Only assets attributed to a
      run through ``meta.run_id`` are counted for that run; the attribution *source* (written at
      commit vs. repaired afterwards) is counted separately so a polluted store can never be read
      as a clean one.
    * ``runs``   -- the store's run table (status, profile, scope, accepted/attempted).
    * coverage rows -- per-lineage rows for the attributes the assets do not carry (the layer
      combo).  ``coverage_rows.json`` is attributed only to the run its sibling ``coverage.json``
      names; a ledger whose rows carry their own ``run_id`` keeps it.

    Sets are the union over the runs that *realized* the attribute (a plan is not coverage), and
    the payload also carries the per-run breakdown, the targets, and the exact gaps.
    """
    from ..canonical import hash_json

    runs = _runs_table(store)
    facts = _asset_facts(store, limit=limit)
    row_sources = _coverage_row_sources(store, extra_row_files)
    axis_ids = registered_axis_ids()

    by_run: dict[str, list[dict[str, Any]]] = {}
    unattributed: list[dict[str, Any]] = []
    for fact in facts:
        if fact["run_id"]:
            by_run.setdefault(fact["run_id"], []).append(fact)
        else:
            unattributed.append(fact)

    def _sets(entries: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]
              ) -> dict[str, list[str]]:
        keys = {
            "vessels": {str(e["vessel_id"]) for e in entries if e.get("vessel_id")},
            "materials": {str(e["material_id"]) for e in entries if e.get("material_id")},
            "patterns": {str(e["family_id"]) for e in entries if e.get("family_id")},
            "fracture_backends": {str(e["backend"]) for e in entries if e.get("backend")},
            "axes": {str(e["axis_id"]) for e in entries if e.get("axis_id")},
            "layer_combos": {str(r["layer_combo_id"]) for r in rows
                             if r.get("layer_combo_id") and r.get("_accepted")},
        }
        return {name: sorted(values) for name, values in keys.items()}

    def _counts(entries: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]],
                run_id: str | None) -> dict[str, Any]:
        roles: dict[str, int] = {}
        qa: dict[str, int] = {}
        for entry in entries:
            roles[str(entry["role"])] = roles.get(str(entry["role"]), 0) + 1
            qa[str(entry["qa_status"])] = qa.get(str(entry["qa_status"]), 0) + 1
        attribution = {"stamped_at_commit": 0, "repair": 0, "none": 0}
        for entry in entries:
            source = str(entry["run_id_source"])
            if source == "repair":
                attribution["repair"] += 1
            elif source == "commit":
                attribution["stamped_at_commit"] += 1
            else:
                attribution["none"] += 1
        mothers = {str(e["mother_id"]) for e in entries
                   if e["role"] == ROLE_MOTHER_MESH and e.get("mother_id")}
        lineages = {str(e["lineage_id"]) for e in entries if e.get("lineage_id")}
        return {
            "run_id": run_id,
            "assets": len(entries), "assets_qa_pass": int(qa.get(QA_PASS, 0)),
            "assets_by_role": dict(sorted(roles.items())), "assets_by_qa_status": dict(sorted(qa.items())),
            "run_id_attribution": attribution,
            "mothers": len(mothers), "mother_ids": sorted(mothers),
            "lineages": len(lineages), "lineage_ids": sorted(lineages),
            "fragments": int(roles.get(ROLE_FRAGMENT_MESH, 0)),
            "observations": int(roles.get(ROLE_OBS_RESULT, 0)),
            "physical_components": int(roles.get(ROLE_PHYSICAL_COMPONENT, 0)),
            "material_profiles": int(roles.get(ROLE_MATERIAL_PROFILE, 0)),
            "pattern_recipes": int(roles.get(ROLE_PATTERN_RECIPE, 0)),
            "coverage_rows": len(rows), "coverage_rows_accepted": int(
                sum(1 for r in rows if r.get("_accepted"))),
            "coverage_row_sources": sorted({str(r.get("_source")) for r in rows}),
        }

    run_entries: list[dict[str, Any]] = []
    for run in runs:
        run_id = run["run_id"]
        entries = by_run.get(run_id, [])
        rows = _rows_for_run(row_sources, run_id)
        record = {**run, **_counts(entries, rows, run_id), **_sets(entries, rows)}
        # a store-global coverage summary is only this run's evidence when it says so
        summary = {}
        summary_path = store.root / "reports" / "coverage.json"
        if summary_path.exists() and row_sources.get("ledger_run_id") == run_id:
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                summary = {}
        record["coverage_summary_run_id"] = summary.get("run_id")
        record["coverage_summary_matches"] = summary.get("run_id") == run_id
        record["fracture_backend_summary"] = summary.get("fracture_backend")
        if record["fracture_backend_summary"] and record["coverage_summary_matches"]:
            merged = set(record["fracture_backends"]) | {str(record["fracture_backend_summary"])}
            record["fracture_backends"] = sorted(merged)
        run_entries.append(record)

    known = {run["run_id"] for run in runs}
    orphan_run_ids = sorted(set(by_run) - known)
    for run_id in orphan_run_ids:
        # assets stamped with a run id the run table does not carry are still real assets: they
        # are reported as their own bucket instead of being dropped or merged into another run
        entries = by_run[run_id]
        rows = _rows_for_run(row_sources, run_id)
        run_entries.append({"run_id": run_id, "status": "UNRECORDED", "scope": None,
                            "profile": None, "spec_hash": None, "accepted": None,
                            "attempted": None, **_counts(entries, rows, run_id),
                            **_sets(entries, rows)})

    # the store-wide totals count every real asset: the run-attributed ones and the unattributed
    # ones (which are reported separately as well, so a reader can subtract them)
    all_entries = list(facts)
    all_rows = [r for run in run_entries for r in _rows_for_run(row_sources, run["run_id"])]
    totals = _counts(all_entries, all_rows, None)
    totals_sets = _sets(all_entries, all_rows)
    totals.update(totals_sets)
    axes_present = sorted(set(totals_sets["axes"]) & set(axis_ids)) if axis_ids else \
        list(totals_sets["axes"])
    axes_unknown = sorted(set(totals_sets["axes"]) - set(axis_ids)) if axis_ids else []
    payload: dict[str, Any] = {
        "schema": COVERAGE_AGGREGATE_SCHEMA,
        "store_root": str(store.root),
        "runs": run_entries,
        "run_count": len(run_entries),
        "orphan_run_ids": orphan_run_ids,
        "totals": totals,
        "unattributed_assets": {
            "count": len(unattributed),
            "by_role": dict(sorted({role: sum(1 for e in unattributed if e["role"] == role)
                                    for role in {e["role"] for e in unattributed}}.items())),
            "note": ("assets whose meta.run_id is absent: they exist and are real, but no run "
                     "claims them, so they cannot be attributed to a run's coverage"),
        },
        # the coverage gates read these top-level keys, exactly as they read them from the
        # single-run coverage.json -- the aggregate is a drop-in superset of that document
        "vessels": totals_sets["vessels"], "materials": totals_sets["materials"],
        "patterns": totals_sets["patterns"], "layer_combos": totals_sets["layer_combos"],
        "fracture_backends": totals_sets["fracture_backends"],
        "fracture_backend": (totals_sets["fracture_backends"][0]
                             if len(totals_sets["fracture_backends"]) == 1 else None),
        "axes": axes_present,
        "axes_unknown": axes_unknown,
        "axes_required": axis_ids,
        "axes_missing": sorted(set(axis_ids) - set(axes_present)),
        "coverage_targets": dict(COVERAGE_TARGETS),
        "sources": {
            "assets": ("store.list_assets() role/qa_status/lineage_id + meta keys written by the "
                       "producing run (mother_mesh.vessel_id/material_id/mother_id, "
                       "pattern_recipe.family_id, fragment_mesh.backend, physical_*.axis_id)"),
            "runs": "runs table (run_id/status/profile/scope/accepted/attempted)",
            "layer_combos": (
                "per-lineage coverage rows only (no committed asset carries a layer combo id; "
                "material_profile.layer_ids stores layer indices).  "
                + "; ".join(f"{s['name']}: "
                            f"{'attributed by ' + str(s['run_attribution']) if s.get('run_attribution') else 'not attributed'}"
                            + (f", sha256 {s.get('sha256')}" if s.get("sha256") else "")
                            for s in row_sources["sources"])),
            "axes": ("physical_component / physical_result meta.axis_id, intersected with the "
                     "registered axis ids of this build"),
            "fracture_backends": ("fragment_mesh / clean_truth meta.backend plus the row files' "
                                  "'backend' column"),
        },
        "row_sources": [{k: v for k, v in source.items() if k != "rows"}
                        for source in row_sources["sources"]],
        "gaps": {},
    }
    payload["gaps"] = coverage_gaps(payload)
    digest = {key: payload[key] for key in
              ("vessels", "materials", "patterns", "layer_combos", "fracture_backends", "axes",
               "axes_missing", "run_count", "totals")}
    payload["content_hash"] = hash_json(digest)
    return payload


def coverage_gaps(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Measured value, target and shortfall of every coverage gate, from the payload it reads."""
    out: dict[str, Any] = {}
    for gate, key in COVERAGE_GATE_KEYS.items():
        present = _coverage_values(payload, key)
        target = int(COVERAGE_TARGETS[key])
        entry = {"key": key, "present": len(present), "target": target,
                 "shortfall": max(0, target - len(present)),
                 "status": "PASS" if len(present) >= target else "PENDING"}
        if key == "axes":
            required = [str(x) for x in (payload.get("axes_required") or [])] or registered_axis_ids()
            entry["required"] = len(required)
            entry["missing"] = sorted(set(required) - set(present)) if required else []
            entry["unknown_axes"] = list(payload.get("axes_unknown") or [])
        out[gate] = entry
    return out


def _coverage_values(payload: Mapping[str, Any], key: str) -> list[str]:
    """The set a coverage gate counts, reading the *real* keys of either payload shape.

    The single-run ``coverage.json`` spells the fracture backend in the **singular**
    (``fracture_backend: "plane_shared_cut"``) and carries no ``axes`` key at all; the aggregate
    spells it as a list and does carry ``axes``.  Both spellings are read here so the gate judges
    the value that exists instead of a key that never did.
    """
    if not isinstance(payload, Mapping):
        return []
    value = payload.get(key)
    if key == "fracture_backends" and value in (None, [], ""):
        value = payload.get("fracture_backend")
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return sorted(str(k) for k in value)
    if isinstance(value, (list, tuple, set)):
        return sorted(str(v) for v in value)
    return [str(value)]


def write_coverage_aggregate(store: AssetStore, *, out_dir: str | Path | None = None,
                             extra_row_files: Sequence[str | Path] | None = None,
                             limit: int = 500000) -> dict[str, Any]:
    """Write ``reports/coverage_aggregate.json`` (+ parquet) and return the payload.

    The JSON document is what the coverage gates read; the parquet copy is the tabular form of the
    same numbers (one row per run), so the aggregate can be re-derived with pandas/pyarrow without
    importing this module.
    """
    payload = coverage_aggregate(store, limit=limit, extra_row_files=extra_row_files)
    target_dir = Path(out_dir) if out_dir else store.root / "reports"
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / f"{COVERAGE_AGGREGATE_NAME}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                                    default=str), encoding="utf-8")
    parquet_path = target_dir / f"{COVERAGE_AGGREGATE_NAME}.parquet"
    rows: list[dict[str, Any]] = []
    for run in payload["runs"]:
        rows.append({
            "run_id": run["run_id"], "status": run.get("status"), "profile": run.get("profile"),
            "scope": run.get("scope"), "accepted": run.get("accepted"),
            "attempted": run.get("attempted"), "assets": run["assets"],
            "assets_qa_pass": run["assets_qa_pass"], "mothers": run["mothers"],
            "lineages": run["lineages"], "fragments": run["fragments"],
            "observations": run["observations"],
            "vessels": ";".join(run["vessels"]), "materials": ";".join(run["materials"]),
            "patterns": ";".join(run["patterns"]),
            "layer_combos": ";".join(run["layer_combos"]),
            "fracture_backends": ";".join(run["fracture_backends"]),
            "axes": ";".join(run["axes"]),
            "run_id_stamped_at_commit": run["run_id_attribution"]["stamped_at_commit"],
            "run_id_repaired": run["run_id_attribution"]["repair"],
        })
    parquet_written = False
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        pq.write_table(pa.Table.from_pylist(rows), parquet_path)
        parquet_written = True
    except Exception:  # noqa: BLE001 - the JSON document is canonical; parquet is a convenience
        parquet_written = False
    payload["artifacts"] = {"json": str(json_path), "json_sha256": _hash_of(json_path),
                            "parquet": str(parquet_path) if parquet_written else None,
                            "parquet_written": parquet_written, "rows": len(rows)}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                                    default=str), encoding="utf-8")
    return payload


def coverage_payload(store: AssetStore, dirs: Sequence[Path]) -> tuple[dict[str, Any], str | None]:
    """The coverage payload the coverage gates read: the aggregate when it exists, else the
    store-global single-run ``coverage.json``."""
    payload, path = load_report_from(dirs, COVERAGE_AGGREGATE_NAME)
    if payload is not None:
        return payload, path
    payload, path = load_report_from(dirs, "coverage")
    return (payload or {}), path


def scoped_coverage(store: AssetStore, dirs: Sequence[Path], run_id: str,
                    assets: Sequence[Any] | None = None) -> tuple[dict[str, Any], str | None]:
    """The coverage payload as the *run-scoped* gates must read it.

    ``coverage.json`` never carried an ``axes`` key, while the run's own physical assets do record
    the axis each factor belongs to (``meta.axis_id``).  When the payload has no axis set, the one
    the run really exercised is measured from those assets -- so a missing key is never confused
    with a satisfied target, and :func:`evaluate_gates` / :func:`gate_measurements` read the same
    thing.
    """
    payload, path = coverage_payload(store, dirs)
    payload = dict(payload)
    if not _coverage_values(payload, "axes"):
        if assets is None:
            assets = [a for a in store.list_assets(limit=100000)
                      if (a.meta or {}).get("run_id") == run_id]
        exercised = sorted({str((a.meta or {}).get("axis_id")) for a in assets
                            if (a.meta or {}).get("axis_id")})
        if exercised:
            payload["axes"] = exercised
            payload["axes_source"] = "assets(meta.run_id == run_id).meta.axis_id"
    return payload, path


def evaluate_gates(store: AssetStore, run_id: str, protocol_path: str | None = None, *,
                   evidence_dirs: Sequence[str | Path] | None = None
                   ) -> tuple[dict[str, str], list[str], str]:
    """Return (gates, asset_ids, requested_profile) for a run.

    ``evidence_dirs`` names additional report roots (for example the long-lived
    ``data/a12`` evidence store) that a gate may read from.  A gate is PASS only when the
    report it needs exists *and* reports success; a missing report stays PENDING.
    """
    try:
        run = store.get_run(run_id)
    except SynLabError as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, exc.message, stage="qc.gates") from exc
    profile = (run.get("profile") or "SANDBOX_CORE").upper()
    assets = [a for a in store.list_assets(limit=100000)
              if (a.meta or {}).get("run_id") == run_id]
    roles: dict[str, list[Any]] = {}
    for asset in assets:
        roles.setdefault(asset.role, []).append(asset)

    dirs = reports_dirs(store, evidence_dirs)
    evidence: dict[str, str] = {}
    values: dict[str, Any] = {}

    def report(name: str) -> dict[str, Any]:
        payload, path = load_report_from(dirs, name)
        if path:
            evidence[name] = path
            values[name] = payload
        return payload or {}

    audit, audit_path = load_report_from(dirs, f"audit_{run_id}")
    if audit_path:
        evidence[f"audit_{run_id}"] = audit_path
    audit = audit or {}
    operator_audit = report("operator_audit")
    pattern_audit = report("pattern_audit")
    acceptance = report("acceptance_summary")

    def has_qa(role: str, minimum: int = 1) -> bool:
        return len([a for a in roles.get(role, []) if a.qa_status == QA_PASS]) >= minimum

    def audit_status(name: str) -> str:
        if name in audit.get("problems", []):
            return "FAIL"
        return "PASS" if audit else "PENDING"

    gates: dict[str, str] = {}
    # ``fixture_contract``: the reuse/fixture manifest.  It is repository-level evidence; the
    # gate is PASS when a readable manifest is present either in the repository or staged into
    # one of the searched report directories (the staging step records source + hash).
    repo_manifest = Path("docs/a12/reuse_manifest.json")
    reuse_payload, reuse_evidence = load_report_from(dirs, "reuse_manifest")
    if reuse_evidence:
        evidence["reuse_manifest"] = reuse_evidence
    elif repo_manifest.exists():
        evidence["reuse_manifest"] = str(repo_manifest)
    gates["fixture_contract"] = "PASS" if (reuse_payload is not None
                                           or repo_manifest.exists()) else "PENDING"
    gates["coordinate_contract"] = "PASS" if acceptance_item(
        acceptance, "A02").get("status") == "PASS" else "PENDING"
    gates["source_map"] = "PASS" if has_qa(ROLE_FRAGMENT_MESH) else "PENDING"
    gates["readonly_commit"] = "PASS" if audit.get("store_health", {}).get("ok") else "PENDING"
    gates["fracture_operator_runs"] = "PASS" if has_qa(ROLE_CLEAN_TRUTH) else "PENDING"
    gates["observation_operator_runs"] = "PASS" if has_qa(ROLE_OBS_RESULT) else "PENDING"
    gates["train_dev_lineage"] = "PASS" if audit.get("lineage_splits") and all(
        split in {s for splits in audit["lineage_splits"].values() for s in splits}
        for split in ("train", "dev")
    ) else "PENDING"
    gates["operators_used_pass"] = "PASS" if operator_audit.get("ok") else "PENDING"
    gates["legal_inputs"] = "PASS" if (has_qa(ROLE_FEATURE_BUNDLE) and has_qa(ROLE_LABEL_BUNDLE)
                                       and audit.get("ok")) else "PENDING"
    gates["relations_complete"] = "PASS" if has_qa(ROLE_POOL) else "PENDING"
    recovery = report("recovery_probe")
    gates["read_recovery"] = "PASS" if audit.get("store_health", {}).get("ok") and (
        recovery.get("ok")) else "PENDING"
    gates["leakage_audit"] = "PASS" if acceptance_item(
        acceptance, "A32").get("status") == "PASS" else "PENDING"

    coverage, coverage_path = scoped_coverage(store, dirs, run_id, assets)
    if coverage_path:
        loaded = Path(coverage_path).stem
        evidence.setdefault(loaded, coverage_path)
        values[loaded] = coverage
    for gate, key in COVERAGE_GATE_KEYS.items():
        gates[gate] = "PASS" if len(_coverage_values(coverage, key)) >= COVERAGE_TARGETS[key] \
            else "PENDING"
    gates["mvs_subset_real_run"] = "PASS" if report("mvs_subset").get("ok") else "PENDING"
    gates["core_ui_api"] = "PASS" if report("api_ui_evidence").get("ok") else "PENDING"
    gates["l2_qualification"] = "PASS" if report("l2_scale").get("ok") else "PENDING"

    for name in ("accepted_nested_10k", "accepted_nested_50k", "accepted_nested_100k"):
        target = int(name.rsplit("_", 1)[-1].rstrip("k")) * 1000
        gates[name] = "PASS" if report("scale_report").get("accepted_max", 0) >= target else "PENDING"
    gates["references_loadable"] = "PASS" if audit.get("closure", {}).get("ok") else "PENDING"
    gates["loader_index_runnable"] = "PASS" if report("loader_probe").get("ok") else "PENDING"
    gates["resource_profile"] = "PASS" if report("resource_profile").get("ok") else "PENDING"

    for name in ("real_capture_dataset", "phone_rgb_mvs", "scale_source", "mask_source",
                 "capture_profile", "proxy_calibration"):
        gates[name] = "PENDING"  # no real capture data on this host
    research = report("research_evidence")
    for name in ("frozen_protocol", "training_runs", "risk_calibration", "confirmation_complete"):
        gates[name] = "PASS" if research.get(name) == "PASS" else "PENDING"

    if profile not in PROFILE_GATES:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown release profile {profile}", stage="qc.gates")
    asset_ids = [a.asset_id for a in assets if a.qa_status == QA_PASS]
    return gates, asset_ids, profile


def gate_evidence(store: AssetStore, run_id: str,
                  evidence_dirs: Sequence[str | Path] | None = None) -> dict[str, dict[str, Any]]:
    """The report files the gates actually read, with a hash and a shallow metric digest.

    Every entry is ``{"path", "hash", "metrics"}``: the path is the file the gate read, the
    hash makes it auditable, and the metrics are the *scalar* values of that report (nested
    structures and non-finite numbers are dropped, because they cannot be canonicalised and
    they are not evidence by themselves).
    """
    from ..canonical import hash_file

    dirs = reports_dirs(store, evidence_dirs)
    out: dict[str, dict[str, Any]] = {}
    for name in ("audit", "audit_" + run_id, "operator_audit", "pattern_audit",
                 "acceptance_summary", "coverage", COVERAGE_AGGREGATE_NAME, "recovery_probe",
                 "loader_probe", "resource_profile", "scale_report", "mvs_subset",
                 "api_ui_evidence", "l2_scale", "research_evidence", "reuse_manifest"):
        payload, path = load_report_from(dirs, name)
        if not path:
            continue
        entry: dict[str, Any] = {"path": path}
        if payload is not None:
            entry["hash"] = hash_file(path)
            entry["metrics"] = _scalar_digest(payload)
        else:
            entry["unreadable"] = True
        out[name] = entry
    return out


def gate_measurements(store: AssetStore, run_id: str,
                      evidence_dirs: Sequence[str | Path] | None = None) -> dict[str, Any]:
    """Why the coverage gates read PASS/PENDING, with the measured value and the shortfall.

    A blocked release has to name the real number it fell short of (``present`` / ``target`` /
    ``shortfall`` / ``missing``), not just the gate name.  This is read from the *same* payload
    :func:`evaluate_gates` reads (the aggregate when present, else the single-run coverage), so a
    refusal and its explanation can never disagree.
    """
    dirs = reports_dirs(store, evidence_dirs)
    payload, path = scoped_coverage(store, dirs, run_id)
    caps = payload.get("coverage_targets") if isinstance(payload, Mapping) else None
    targets = {key: int(value) for key, value in (caps or {}).items()} if isinstance(caps, Mapping) \
        else {}
    gaps = coverage_gaps(payload)
    if targets:
        for gate, entry in gaps.items():
            target = targets.get(str(entry["key"]))
            if target:
                entry["target"] = target
                entry["shortfall"] = max(0, target - int(entry["present"]))
                entry["status"] = "PASS" if int(entry["present"]) >= target else "PENDING"
    return {
        "coverage_source": path,
        "coverage_schema": payload.get("schema") if isinstance(payload, Mapping) else None,
        "coverage_content_hash": payload.get("content_hash") if isinstance(payload, Mapping) else None,
        "targets": targets or dict(COVERAGE_TARGETS),
        "gates": gaps,
        "axes_required": (payload.get("axes_required") if isinstance(payload, Mapping) else None),
        "axes_missing": (payload.get("axes_missing") if isinstance(payload, Mapping) else None),
    }


def _scalar_digest(payload: Any, *, depth: int = 2, limit: int = 40) -> dict[str, Any]:
    """Flatten finite scalars out of a report (bounded depth, NaN/Inf dropped)."""
    import math

    out: dict[str, Any] = {}

    def walk(node: Any, prefix: str, level: int) -> None:
        if len(out) >= limit:
            return
        if isinstance(node, dict) and level < depth:
            for key, value in sorted(node.items(), key=lambda kv: str(kv[0])):
                walk(value, f"{prefix}{key}.", level + 1)
            return
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, str)):
            out[prefix.rstrip(".")] = node
            return
        if isinstance(node, float):
            if math.isfinite(node):
                out[prefix.rstrip(".")] = node
            return

    walk(payload, "", 0)
    return out
