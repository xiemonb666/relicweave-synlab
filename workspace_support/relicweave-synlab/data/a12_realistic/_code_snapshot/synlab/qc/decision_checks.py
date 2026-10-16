"""Read-only conformance checks for the A12 human adjudications (``D1``-``D12``).

Why this module exists
----------------------
``docs/a12/rig_contract.md`` §12 lists 18 items the read-only contract could not decide.
They were adjudicated by the Lead and written down in ``docs/a12/decision_record.md``
(prose) and ``configs/a12/decision_defaults.json`` (machine readable).  A written ruling
is not a landed ruling: the values it freezes only exist once the artefacts carry them.
This module measures that, from the artefacts, and never repairs anything.

What it checks
--------------
======================  =========================================================  =========
check id                question                                                   decision
======================  =========================================================  =========
defaults.present        the 10 machine-readable sections exist, each with a        D1-D12
                        non-empty ``source`` and an ``assumption`` flag
defaults.action_        the D1 union (14 fields) is declared per field with a      D1
proposal_union          source pointer, and a producer exists in the code
metrics.primary_        the 7 document-named primary metrics are frozen, and       D3
metric_freeze           工时 -30% is listed separately as a process metric
metrics.m_and_delta_    every result row reporting ``any@M``/``PoolCov@M`` also     D2
recorded                records its ``M`` and its frozen ``delta``
surface.authority_      ``origin_kind`` vs ``interface_id >= 0`` conflicts are      D4
conflicts               reported and have been driven to 0
relations.loss_mask_    ``loss_mask`` is the only supervision gate and              D10
authority               ``eligible_as_negative`` is derived from it
relations.negative_     legal negatives actually exist (coupled consequence         D10
supply                  of the frozen ``loss_mask`` semantics)
relations.gate_         the visible layer carries the gate or an explicit           D12.3
columns_visible         marker (open residual; report-only)
export.synthetic_only_  synthetic-only channels are marked ``synthetic_only``       D5
marking
quality.mapping_        the 8 quality and 14 degradation components are mapped      D8
direction               with a direction, unmapped ones marked ``unmapped``
quality.store_key_      the store's quality vectors use the frozen 8 names          D8
alignment
context.v1_fields_      the frozen context v1 field set is landed and its           D11
queryable               ``context_id``/``batch_id``/``bag_id`` are queryable
structured_light.       no positive structured-light / laser capability claim       D5
claim_free              exists in ``synlab``
======================  =========================================================  =========

Honesty rules this module obeys
-------------------------------
* it **never writes** to the store: SQLite is opened ``mode=ro`` and every other artefact
  is only read;
* it **never repairs** anything it finds;
* an absent quantity is ``MISSING``, never "probably fine"; a denominator of 0 is
  ``NOT_APPLICABLE`` with the reason recorded, never a silent pass;
* no threshold is loosened to make a particular store look better: every threshold it
  applies is quoted from ``configs/a12/decision_defaults.json`` and echoed in the check's
  ``thresholds`` list with its source pointer.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

__all__ = [
    "SCHEMA",
    "PASS",
    "FAIL",
    "MISSING",
    "NOT_APPLICABLE",
    "UNREADABLE",
    "DEFAULT_SECTIONS",
    "ACTION_PROPOSAL_FIELDS",
    "PRIMARY_METRICS",
    "QUALITY_COMPONENTS",
    "DEGRADATION_COMPONENTS",
    "CONTEXT_QUERY_KEYS",
    "STRUCTURED_LIGHT_FORBIDDEN_TOKENS",
    "DEFAULTS_RELPATH",
    "QcDecisionInputError",
    "CheckResult",
    "load_defaults",
    "check_store",
    "run_checks",
    "report_slug",
    "default_report_dir",
    "write_report",
    "format_summary",
]

SCHEMA = "synlab.decision_checks.v1"

PASS = "PASS"
FAIL = "FAIL"
MISSING = "MISSING"
NOT_APPLICABLE = "NOT_APPLICABLE"
UNREADABLE = "UNREADABLE"

#: The 10 machine-readable sections ``configs/a12/decision_defaults.json`` must carry.
DEFAULT_SECTIONS: tuple[str, ...] = (
    "action_proposal",
    "stopping_rule",
    "metric_contract",
    "surface_authority",
    "structured_light",
    "assumed_optics",
    "quality_mapping",
    "misdirection_denominator",
    "loss_mask_authority",
    "context_v1_fields",
)

#: D1: the union of ``p0276`` (9) + ``p0638`` (5); ``p0574`` co-occurs but adds ``pose_id``,
#: which the Lead's field list does not contain -> it stays an unresolved residual (D12.4).
ACTION_PROPOSAL_FIELDS: tuple[str, ...] = (
    "query_id", "evidence_revision", "action_id", "target_region", "reason", "expected_cost",
    "u_profile_id", "distance_mode", "focus_setting_id", "intrinsics_profile_id", "expected_roi",
    "camera_id", "target_pose_or_relative_angle", "light_mode",
)
ACTION_PROPOSAL_SOURCES: frozenset[str] = frozenset({"p0276", "p0638", "p0574"})

#: D3: the document-named primary metrics, frozen as the whole list.
PRIMARY_METRICS: tuple[str, ...] = (
    "any_at_50_macro",
    "hit_at_10_macro_with_lower95",
    "low_quality_hit_at_10",
    "new_method_gain_pt",
    "clean_guard_drop_pt",
    "mate_absent_misdirection",
    "mate_present_acceptance_coverage",
)
PROCESS_METRIC_IDS: tuple[str, ...] = ("workflow_median_time_reduction",)

#: D8: two different spaces.  They are never the same schema (``p0236`` vs ``p0365``).
QUALITY_COMPONENTS: tuple[str, ...] = (
    "blur", "exposure", "coverage", "occlusion", "reconstruction_confidence",
    "point_density", "normal_stability", "curvature_stability",
)
DEGRADATION_COMPONENTS: tuple[str, ...] = (
    "fracture_smoothing", "edge_rounding", "fracture_missing", "texture_loss", "blur", "glare",
    "exposure", "view_coverage", "point_dropout", "mesh_holes", "depth_noise", "normal_noise",
    "curvature_noise", "calibration_error",
)

#: D11: the three keys a query row must be able to resolve.
CONTEXT_QUERY_KEYS: tuple[str, ...] = ("context_id", "batch_id", "bag_id")
CONTEXT_IMPL_FILES: tuple[str, ...] = ("synlab/pipeline.py", "synlab/storage/export.py")

#: D5: tokens that would amount to a *positive* structured-light / laser capability claim.
STRUCTURED_LIGHT_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "structured_light", "structured light", "structured-light",
    "fringe_projection", "laser_scanner", "laser_triangulation", "laser_scan",
)

#: D4: the counter the writer must drive to zero.
SURFACE_CONFLICT_KEY = "origin_interface_vs_interface_id_conflicts"
SURFACE_AUTHORITY_ROLE = "display_lod_glb"

#: D2: keys that mean "this row reports an ``any@M`` / ``PoolCov@M`` family metric".
M_METRIC_KEYS: tuple[str, ...] = ("any_at_m", "pool_cov_at_m", "any@M", "PoolCov@M", "poolcov@m")
M_RECORD_KEYS: tuple[str, ...] = ("m", "M", "pool_size", "candidate_pool_size", "pool_m")
M_DERIVABLE_KEYS: tuple[str, ...] = ("first_stage", "initial_pool", "retrieved")
DELTA_RECORD_KEYS: tuple[str, ...] = (
    "delta", "frozen_delta", "delta_frozen", "resolution_delta", "ci_half_width", "delta_definition",
)

DEFAULTS_RELPATH = "configs/a12/decision_defaults.json"

#: Modules excluded from the source scans of :func:`_check_action_proposal` and
#: :func:`_check_structured_light`: this module *defines* the tokens those scans look for, so
#: without the exclusion the gate reports itself as both a producer and a claimant -- a
#: self-referential false positive, not a finding.
SELF_MODULES: frozenset[str] = frozenset({"synlab/qc/decision_checks.py"})


class QcDecisionInputError(ValueError):
    """The target cannot be judged at all (wrong shape / not found)."""


# --------------------------------------------------------------------------- small helpers
@dataclass
class CheckResult:
    """One check: id, status, the real denominator and the measured hits."""

    id: str
    status: str
    detail: str
    required: bool = True
    denominator: int | None = None
    hits: int | None = None
    decisions: tuple[str, ...] = ()
    thresholds: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "status": self.status,
            "required": bool(self.required),
            "detail": self.detail,
        }
        if self.denominator is not None:
            out["denominator"] = int(self.denominator)
        if self.hits is not None:
            out["hits"] = int(self.hits)
        if self.decisions:
            out["decisions"] = list(self.decisions)
        if self.thresholds:
            out["thresholds"] = list(self.thresholds)
        if self.evidence:
            out["evidence"] = self.evidence
        return out


def _guess_repo(start: Path) -> Path:
    """Walk up until ``synlab`` + ``configs`` are both present, else return ``start``."""
    here = start if start.is_dir() else start.parent
    for candidate in (here, *here.parents):
        if (candidate / "synlab").is_dir() and (candidate / "configs").is_dir():
            return candidate
    return start if start.is_dir() else start.parent


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_dicts(node: Any) -> Iterator[Mapping[str, Any]]:
    """Yield every mapping in a nested JSON document."""
    if isinstance(node, Mapping):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _iter_dicts(item)


def _has_key_ci(row: Mapping[str, Any], names: Iterable[str]) -> bool:
    lowered = {str(k).lower() for k in row}
    return any(str(n).lower() in lowered for n in names)


def _store_db(target: Path) -> Path | None:
    """``<root>/metadata.sqlite`` or ``<root>`` itself when it *is* the SQLite file."""
    if target.is_file() and target.suffix == ".sqlite":
        return target
    candidate = target / "metadata.sqlite"
    return candidate if candidate.exists() else None


def _open_ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)


def default_report_dir(repo: Path | None = None) -> Path:
    return (repo or _guess_repo(Path.cwd())) / "data" / "a12" / "reports"


def report_slug(target: str | Path, *, repo: str | Path | None = None) -> str:
    path = Path(target)
    repo_path = Path(repo) if repo is not None else _guess_repo(path)
    try:
        rel = path.resolve().relative_to(repo_path.resolve())
        text = str(rel).replace("\\", "/")
    except ValueError:
        text = path.name
    text = text.strip("/") or path.name
    slug = re.sub(r"[^0-9A-Za-z._-]+", "__", text).strip("_")
    return slug.replace("/", "__")


# --------------------------------------------------------------------------- the defaults file
def load_defaults(repo: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(defaults, error)``; exactly one of the two is ``None``."""
    path = repo / DEFAULTS_RELPATH
    if not path.exists():
        return None, f"{DEFAULTS_RELPATH} is missing"
    try:
        payload = _read_json(path)
    except Exception as exc:  # noqa: BLE001
        return None, f"{DEFAULTS_RELPATH} is not readable JSON: {exc}"
    if not isinstance(payload, dict):
        return None, f"{DEFAULTS_RELPATH} is not a JSON object"
    return payload, None


def _check_defaults_present(defaults: dict[str, Any] | None, error: str | None) -> CheckResult:
    thresholds = [{"threshold": "all 10 sections present", "value": len(DEFAULT_SECTIONS),
                   "source": "task brief (decision_defaults.json field list)"},
                  {"threshold": "each section carries source + assumption",
                   "source": "task brief"}]
    if defaults is None:
        return CheckResult("defaults.present", UNREADABLE, error or "defaults unreadable",
                           denominator=len(DEFAULT_SECTIONS), hits=0, decisions=("D1-D12",),
                           thresholds=thresholds)
    hits = 0
    missing: list[str] = []
    incomplete: list[str] = []
    for section in DEFAULT_SECTIONS:
        block = defaults.get(section)
        if not isinstance(block, dict):
            missing.append(section)
            continue
        source = block.get("source")
        has_source = bool(source) if isinstance(source, (list, tuple, str)) else False
        has_flag = isinstance(block.get("assumption"), bool)
        if has_source and has_flag:
            hits += 1
        else:
            incomplete.append({"section": section, "source": has_source,
                               "assumption": has_flag})
    status = PASS if hits == len(DEFAULT_SECTIONS) else FAIL
    detail = (f"{hits}/{len(DEFAULT_SECTIONS)} sections with source+assumption"
              + (f"; missing={missing}" if missing else "")
              + (f"; incomplete={incomplete}" if incomplete else ""))
    return CheckResult("defaults.present", status, detail, denominator=len(DEFAULT_SECTIONS),
                       hits=hits, decisions=("D1-D12",), thresholds=thresholds,
                       evidence={"path": DEFAULTS_RELPATH, "sections": list(DEFAULT_SECTIONS)})


def _check_action_proposal(defaults: dict[str, Any] | None, repo: Path) -> CheckResult:
    thresholds = [
        {"threshold": f"denominator == {len(ACTION_PROPOSAL_FIELDS)} D1 fields",
         "source": "decision_defaults.json:action_proposal.field_count"},
        {"threshold": "every field carries a source in {p0276,p0638,p0574} and an "
                      "optional_extension flag",
         "source": "docs/a12/decision_record.md D1"},
        {"threshold": "at least one ActionProposal producer exists in synlab/",
         "source": "docs/a12/decision_record.md D1 落地动作"},
    ]
    block = (defaults or {}).get("action_proposal")

    # The code side first: does anything actually produce the proposal object?  This module
    # itself is excluded -- it names the type in its thresholds, it does not produce it.
    producers: list[str] = []
    for path in sorted((repo / "synlab").rglob("*.py")):
        rel = path.relative_to(repo).as_posix()
        if rel in SELF_MODULES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "ActionProposal" in text:
            producers.append(rel)

    if not isinstance(block, dict):
        return CheckResult("defaults.action_proposal_union", MISSING,
                           "action_proposal section absent from decision_defaults.json"
                           f"; code producers={producers or 'none'}",
                           denominator=len(ACTION_PROPOSAL_FIELDS) + 1, hits=0, decisions=("D1",),
                           thresholds=thresholds, evidence={"producers": producers})
    declared: dict[str, dict[str, Any]] = {}
    for entry in block.get("fields") or []:
        if isinstance(entry, Mapping) and entry.get("name"):
            declared[str(entry["name"])] = dict(entry)
    hits = 0
    offenders: list[dict[str, Any]] = []
    for name in ACTION_PROPOSAL_FIELDS:
        entry = declared.get(name)
        if entry is None:
            offenders.append({"field": name, "why": "not declared"})
            continue
        source = entry.get("source")
        source_list = [str(s).strip() for s in source] if isinstance(source, (list, tuple)) else []
        ok_source = bool(source_list) and all(
            any(s.startswith(ptr) for ptr in ACTION_PROPOSAL_SOURCES) for s in source_list)
        ok_flag = isinstance(entry.get("optional_extension"), bool)
        if ok_source and ok_flag and entry.get("tier"):
            hits += 1
        else:
            offenders.append({"field": name, "source": source_list,
                              "source_ok": ok_source, "optional_extension": entry.get(
                                  "optional_extension"), "tier": entry.get("tier")})

    declaration_ok = hits == len(ACTION_PROPOSAL_FIELDS)
    code_ok = bool(producers)

    denominator = len(ACTION_PROPOSAL_FIELDS) + 1
    measured = hits + (1 if code_ok else 0)
    status = PASS if (declaration_ok and code_ok) else FAIL
    detail = (f"declaration {hits}/{len(ACTION_PROPOSAL_FIELDS)}"
              + (f" offenders={offenders}" if offenders else "")
              + f"; code producers={producers or 'none'}")
    return CheckResult("defaults.action_proposal_union", status, detail, denominator=denominator,
                       hits=measured, decisions=("D1",), thresholds=thresholds,
                       evidence={"declared_field_count": len(declared),
                                 "tiers": block.get("tiers", {}),
                                 "producers": producers,
                                 "unresolved": block.get("unresolved", [])})


def _check_primary_metrics(defaults: dict[str, Any] | None) -> CheckResult:
    thresholds = [
        {"threshold": f"denominator == {len(PRIMARY_METRICS)} frozen primary metrics",
         "source": "docs/a12/decision_record.md D3 / t005"},
        {"threshold": "工时 -30% listed as a process metric outside the primary list",
         "source": "docs/a12/decision_record.md D3"},
    ]
    contract = (defaults or {}).get("metric_contract")
    if not isinstance(contract, dict):
        return CheckResult("metrics.primary_metric_freeze", MISSING,
                           "metric_contract section absent from decision_defaults.json",
                           denominator=len(PRIMARY_METRICS), hits=0, decisions=("D3",),
                           thresholds=thresholds)
    primary = contract.get("primary_frozen") or []
    ids = [str(entry.get("id")) for entry in primary if isinstance(entry, Mapping)]
    hits = 0
    offenders: list[str] = []
    for want in PRIMARY_METRICS:
        if want in ids:
            entry = next(e for e in primary if str(e.get("id")) == want)
            if entry.get("label") and entry.get("source"):
                hits += 1
            else:
                offenders.append(f"{want}: label/source missing")
        else:
            offenders.append(f"{want}: absent")
    process = [str(e.get("id")) for e in (contract.get("process_metric_separate") or [])
               if isinstance(e, Mapping)]
    process_ok = all(pid in process for pid in PROCESS_METRIC_IDS) and not any(
        pid in ids for pid in PROCESS_METRIC_IDS)
    denominator = len(PRIMARY_METRICS) + 1
    measured = hits + (1 if process_ok else 0)
    if hits == len(PRIMARY_METRICS) and process_ok:
        status = PASS
    elif not primary:
        status = MISSING
    else:
        status = FAIL
    detail = (f"{hits}/{len(PRIMARY_METRICS)} primary metrics frozen"
              + (f"; offenders={offenders}" if offenders else "")
              + f"; process_metric_separate={process} (ok={process_ok})")
    return CheckResult("metrics.primary_metric_freeze", status, detail, denominator=denominator,
                       hits=measured, decisions=("D3",), thresholds=thresholds,
                       evidence={"declared_primary": ids, "process_metrics": process,
                                 "sy_q_uncalibrated": [
                                     p for p in ((contract.get("sy_q_to_q_mapping") or {})
                                                 .get("pairs") or [])
                                     if p.get("status") == "unmapped"]})


def _check_m_and_delta(reports_root: Path) -> CheckResult:
    thresholds = [
        {"threshold": "every row reporting any@M/PoolCov@M carries its M",
         "source": "docs/a12/decision_record.md D2"},
        {"threshold": "every such row carries the frozen delta (object-cluster bootstrap 95% "
                      "CI half-width)",
         "source": "docs/a12/decision_record.md D2 / p0106 / p0269"},
    ]
    if not reports_root.exists():
        return CheckResult("metrics.m_and_delta_recorded", MISSING,
                           f"reports root {reports_root} does not exist",
                           denominator=0, hits=0, decisions=("D2",), thresholds=thresholds)
    rows_total = 0
    m_recorded = 0
    delta_recorded = 0
    files_with_rows: dict[str, int] = {}
    unreadable: list[str] = []
    for path in sorted(reports_root.rglob("*.json")):
        try:
            payload = _read_json(path)
        except Exception:  # noqa: BLE001
            text = None
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                unreadable.append(path.name)
                continue
            payload = None
            if not any(k in text for k in M_METRIC_KEYS):
                continue
            files_with_rows[path.name] = -1
            continue
        n_here = 0
        for row in _iter_dicts(payload):
            if not any(str(k) in row for k in M_METRIC_KEYS):
                continue
            rows_total += 1
            n_here += 1
            explicit_m = _has_key_ci(row, M_RECORD_KEYS)
            derivable_m = any(_has_key_ci(row, (k,)) for k in M_DERIVABLE_KEYS)
            if explicit_m or derivable_m:
                m_recorded += 1
            if _has_key_ci(row, DELTA_RECORD_KEYS):
                delta_recorded += 1
        if n_here:
            files_with_rows[path.name] = n_here
    if rows_total == 0:
        status = MISSING
        detail = "no artifact row reports an any@M / PoolCov@M family metric"
    else:
        measured = min(m_recorded, delta_recorded)
        if m_recorded == rows_total and delta_recorded == rows_total:
            status = PASS
        else:
            status = FAIL
        detail = (f"M recorded {m_recorded}/{rows_total}; delta recorded {delta_recorded}/"
                  f"{rows_total} (denominator = rows reporting an any@M family metric)")
        return CheckResult("metrics.m_and_delta_recorded", status, detail, denominator=rows_total,
                           hits=measured, decisions=("D2",), thresholds=thresholds,
                           evidence={"files": files_with_rows, "unreadable": unreadable,
                                     "m_keys": list(M_RECORD_KEYS),
                                     "delta_keys": list(DELTA_RECORD_KEYS)})
    return CheckResult("metrics.m_and_delta_recorded", status, detail, denominator=rows_total,
                       hits=0, decisions=("D2",), thresholds=thresholds,
                       evidence={"files": files_with_rows, "unreadable": unreadable})


def _check_surface_authority(target: Path, defaults: dict[str, Any] | None) -> CheckResult:
    declared = ((defaults or {}).get("surface_authority") or {})
    predicate = str(declared.get("authoritative_predicate", "") or "")
    thresholds = [
        {"threshold": "conflicts == 0 under `interface_id >= 0`",
         "source": "docs/a12/decision_record.md D4"},
        {"threshold": "conflicts reported per run with faces_total",
         "source": "docs/a12/decision_record.md D4"},
        {"threshold": f"declared predicate == 'interface_id >= 0' (got {predicate!r})",
         "source": "configs/a12/decision_defaults.json:surface_authority"},
    ]
    db = _store_db(target)
    if db is None:
        return CheckResult("surface.authority_conflicts", NOT_APPLICABLE,
                           f"no metadata.sqlite under {target}", denominator=0, hits=0,
                           decisions=("D4",), thresholds=thresholds)
    try:
        con = _open_ro(db)
        try:
            rows = list(con.execute(
                "select asset_id, meta_json from assets where role = ?",
                (SURFACE_AUTHORITY_ROLE,)))
        finally:
            con.close()
    except sqlite3.Error as exc:
        return CheckResult("surface.authority_conflicts", UNREADABLE, f"assets unreadable: {exc}",
                           denominator=0, hits=0, decisions=("D4",), thresholds=thresholds)
    faces_total = 0
    conflicts = 0
    per_asset: list[dict[str, Any]] = []
    for asset_id, meta_json in rows:
        try:
            meta = json.loads(meta_json or "{}")
        except Exception:  # noqa: BLE001
            continue
        sga = meta.get("surface_group_authority")
        if not isinstance(sga, Mapping):
            continue
        faces = int(sga.get("faces_total") or 0)
        conf = int(sga.get(SURFACE_CONFLICT_KEY) or 0)
        faces_total += faces
        conflicts += conf
        per_asset.append({"asset_id": asset_id, "faces_total": faces, "conflicts": conf,
                          "pct": (100.0 * conf / faces) if faces else None})
    if faces_total == 0:
        return CheckResult("surface.authority_conflicts", NOT_APPLICABLE,
                           f"store holds no `{SURFACE_AUTHORITY_ROLE}` asset carrying "
                           f"surface_group_authority", denominator=0, hits=0, decisions=("D4",),
                           thresholds=thresholds,
                           evidence={"assets_with_authority_block": 0})
    hits = faces_total - conflicts
    if conflicts == 0 and predicate.startswith("interface_id"):
        status = PASS
    elif conflicts == 0:
        status = FAIL
    else:
        status = FAIL
    detail = (f"conflicts {conflicts}/{faces_total} faces "
              f"({100.0 * conflicts / faces_total:.2f}%) over {len(per_asset)} asset(s); "
              f"declared predicate {predicate!r}")
    return CheckResult("surface.authority_conflicts", status, detail, denominator=faces_total,
                       hits=hits, decisions=("D4",), thresholds=thresholds,
                       evidence={"conflict_counter_field": SURFACE_CONFLICT_KEY,
                                 "per_asset": per_asset,
                                 "declared_predicate": predicate,
                                 "measured_baseline_in_census": (
                                     declared.get("measured_baseline") or {})})


@dataclass
class _ParquetProbe:
    path: Path
    rows: int
    columns: list[str]
    data: dict[str, list[Any]]


def _relations_tables(exports_root: Path) -> tuple[list[_ParquetProbe], list[str]]:
    probes: list[_ParquetProbe] = []
    unreadable: list[str] = []
    if not exports_root.exists():
        return probes, unreadable
    try:
        import pyarrow.parquet as pq  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return probes, ["pyarrow unavailable: relations.parquet cannot be read"]
    for path in sorted(exports_root.rglob("relations.parquet")):
        try:
            table = pq.read_table(path)
        except Exception as exc:  # noqa: BLE001
            unreadable.append(f"{path}: {exc}")
            continue
        probes.append(_ParquetProbe(path=path, rows=table.num_rows,
                                    columns=list(table.column_names),
                                    data={k: list(v) for k, v in table.to_pydict().items()}))
    return probes, unreadable


def _check_loss_mask_authority(exports_root: Path) -> CheckResult:
    thresholds = [
        {"threshold": "eligible_as_negative == (kind in {R0,R1} and loss_mask) for every row",
         "source": "docs/a12/decision_record.md D10"},
        {"threshold": "valid is a derived alias: valid == loss_mask",
         "source": "docs/a12/decision_record.md D10"},
    ]
    probes, unreadable = _relations_tables(exports_root)
    if not probes:
        return CheckResult("relations.loss_mask_authority", MISSING,
                           f"no readable relations.parquet under {exports_root}"
                           + (f"; {unreadable}" if unreadable else ""),
                           denominator=0, hits=0, decisions=("D10",), thresholds=thresholds)
    total = 0
    hits = 0
    violations: list[dict[str, Any]] = []
    columns_present: dict[str, list[str]] = {}
    negative_supply = 0
    negative_denominator = 0
    for probe in probes:
        columns_present[probe.path.name if False else str(probe.path)] = probe.columns
        kinds = probe.data.get("kind") or []
        loss = probe.data.get("loss_mask")
        eligible = probe.data.get("eligible_as_negative")
        valid = probe.data.get("valid")
        for index in range(probe.rows):
            total += 1
            kind = kinds[index] if index < len(kinds) else None
            lm = bool(loss[index]) if loss is not None and index < len(loss) else None
            en = bool(eligible[index]) if eligible is not None and index < len(eligible) else None
            vd = bool(valid[index]) if valid is not None and index < len(valid) else None
            if kind in ("R0", "R1"):
                negative_denominator += 1
            ok = True
            if kind in ("R0", "R1"):
                if lm and en:
                    negative_supply += 1
            want = (kind in ("R0", "R1")) and bool(lm)
            if en is None or en != want:
                ok = False
            if vd is not None and lm is not None and vd != lm:
                ok = False
            if ok:
                hits += 1
            elif len(violations) < 20:
                violations.append({"file": str(probe.path), "index": index, "kind": kind,
                                   "loss_mask": lm, "eligible_as_negative": en, "valid": vd})
    if hits == total:
        status = PASS
    elif total == 0:
        status = NOT_APPLICABLE
    else:
        status = FAIL
    detail = (f"{hits}/{total} relation rows satisfy the single-gate rule "
              f"(eligible derived from kind and loss_mask; valid == loss_mask)")
    return CheckResult("relations.loss_mask_authority", status, detail, denominator=total,
                       hits=hits, decisions=("D10",), thresholds=thresholds,
                       evidence={"files": {str(p.path): p.rows for p in probes},
                                 "columns": columns_present,
                                 "violations": violations,
                                 "legal_negative_supply": negative_supply,
                                 "negative_side_rows": negative_denominator,
                                 "unreadable": unreadable})


def _check_negative_supply(exports_root: Path) -> CheckResult:
    thresholds = [{"threshold": "at least 1 eligible legal negative",
                   "source": "docs/a12/decision_record.md D10 联动约束 / t042"}]
    probes, unreadable = _relations_tables(exports_root)
    if not probes:
        return CheckResult("relations.negative_supply", MISSING,
                           f"no readable relations.parquet under {exports_root}",
                           denominator=0, hits=0, required=False, decisions=("D10",),
                           thresholds=thresholds)
    total_negative_side = 0
    eligible = 0
    loss_true_on_negative_side = 0
    for probe in probes:
        kinds = probe.data.get("kind") or []
        loss = probe.data.get("loss_mask") or []
        eligible_col = probe.data.get("eligible_as_negative")
        for index, kind in enumerate(kinds):
            if kind not in ("R0", "R1"):
                continue
            total_negative_side += 1
            lm = bool(loss[index]) if index < len(loss) else False
            if lm:
                loss_true_on_negative_side += 1
            if eligible_col is not None and index < len(eligible_col):
                eligible += 1 if bool(eligible_col[index]) else 0
    status = PASS if eligible >= 1 else FAIL
    detail = (f"legal negative supply {eligible}; negative-side rows {total_negative_side}, of "
              f"which loss_mask true {loss_true_on_negative_side}")
    return CheckResult("relations.negative_supply", status, detail,
                       denominator=total_negative_side, hits=eligible, required=False,
                       decisions=("D10",), thresholds=thresholds,
                       evidence={"unreadable": unreadable,
                                 "note": "with loss_mask == (kind == 'R2') this is "
                                         "structurally 0; it is a coupled constraint of the "
                                         "frozen single-gate rule, not a D10 violation"})


def _check_visible_gate_columns(exports_root: Path) -> CheckResult:
    thresholds = [{"threshold": "the visible layer carries loss_mask (or an explicit marker)",
                   "source": "docs/a12/decision_record.md D12.3 (open residual)"}]
    files = sorted(exports_root.rglob("visible.parquet")) if exports_root.exists() else []
    if not files:
        return CheckResult("relations.gate_columns_visible", MISSING,
                           f"no visible.parquet under {exports_root}", denominator=0, hits=0,
                           required=False, decisions=("D10", "D12.3"), thresholds=thresholds)
    try:
        import pyarrow.parquet as pq  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return CheckResult("relations.gate_columns_visible", UNREADABLE,
                           "pyarrow unavailable", denominator=len(files), hits=0, required=False,
                           decisions=("D12.3",), thresholds=thresholds)
    hits = 0
    per_file: dict[str, list[str]] = {}
    for path in files:
        try:
            columns = list(pq.read_schema(path).names)
        except Exception as exc:  # noqa: BLE001
            per_file[str(path)] = [f"unreadable: {exc}"]
            continue
        per_file[str(path)] = columns
        if "loss_mask" in columns:
            hits += 1
    status = PASS if hits == len(files) else MISSING
    detail = (f"{hits}/{len(files)} visible.parquet files carry loss_mask "
              f"(residual D12.3 stays open)")
    return CheckResult("relations.gate_columns_visible", status, detail, denominator=len(files),
                       hits=hits, required=False, decisions=("D10", "D12.3"),
                       thresholds=thresholds, evidence={"columns": per_file})


def _check_synthetic_only(exports_root: Path, defaults: dict[str, Any] | None) -> CheckResult:
    hook = ((defaults or {}).get("structured_light") or {}).get("hook_retained") or {}
    thresholds = [
        {"threshold": "every synthetic-only channel manifest carries synthetic_only",
         "source": "docs/a12/decision_record.md D5 / rig_contract §11.1 第 2 条"},
        {"threshold": "hook declares synthetic_only + upper_bound_only",
         "source": "configs/a12/decision_defaults.json:structured_light.hook_retained"},
    ]
    indexes: list[Path] = []
    if exports_root.exists():
        indexes = sorted(p for p in exports_root.rglob("index.json") if p.is_file())
    if not indexes:
        return CheckResult("export.synthetic_only_marking", MISSING,
                           f"no index.json under {exports_root}", denominator=0, hits=0,
                           decisions=("D5",), thresholds=thresholds)
    hits = 0
    with_entries = 0
    per_file: dict[str, dict[str, Any]] = {}
    for path in indexes:
        try:
            payload = _read_json(path)
        except Exception as exc:  # noqa: BLE001
            per_file[path.name] = {"error": str(exc)}
            continue
        declares_entries = False
        for key in ("channels", "arrays", "rows", "assets", "entries"):
            value = payload.get(key) if isinstance(payload, Mapping) else None
            if isinstance(value, (list, tuple)) and value:
                declares_entries = True
        if not declares_entries:
            continue
        with_entries += 1
        marked = "synthetic_only" in json.dumps(payload, ensure_ascii=False)
        per_file[str(path)] = {"declares_entries": True, "synthetic_only": marked}
        if marked:
            hits += 1
    if with_entries == 0:
        return CheckResult("export.synthetic_only_marking", NOT_APPLICABLE,
                           "no index.json declares channels/arrays/rows entries",
                           denominator=0, hits=0, decisions=("D5",), thresholds=thresholds)
    hook_ok = bool(hook.get("synthetic_only") or hook.get("marker") == "synthetic_only") and \
        bool(hook.get("upper_bound_only"))
    status = PASS if (hits == with_entries and hook_ok) else FAIL
    detail = (f"{hits}/{with_entries} entry-declaring manifests carry synthetic_only; "
              f"hook upper_bound_only={hook.get('upper_bound_only')}")
    return CheckResult("export.synthetic_only_marking", status, detail, denominator=with_entries,
                       hits=hits, decisions=("D5",), thresholds=thresholds,
                       evidence={"files": per_file,
                                 "synthetic_modalities_to_mark": ["depth", "normal",
                                                                  "point_cloud", "mesh",
                                                                  "geometry", "tokens"],
                                 "hook": hook})


def _check_quality_mapping(defaults: dict[str, Any] | None) -> CheckResult:
    thresholds = [
        {"threshold": f"denominator == {len(QUALITY_COMPONENTS) + len(DEGRADATION_COMPONENTS)} "
                      f"components across the two spaces",
         "source": "docs/a12/decision_record.md D8 / p0236 / p0365"},
        {"threshold": "every unmapped component is explicitly marked unmapped",
         "source": "docs/a12/decision_record.md D8"},
        {"threshold": "the two spaces are never declared equivalent",
         "source": "docs/a12/decision_record.md D8"},
    ]
    block = (defaults or {}).get("quality_mapping")
    if not isinstance(block, dict):
        return CheckResult("quality.mapping_direction", MISSING,
                           "quality_mapping section absent from decision_defaults.json",
                           denominator=len(QUALITY_COMPONENTS) + len(DEGRADATION_COMPONENTS),
                           hits=0, decisions=("D8",), thresholds=thresholds)
    forward = {str(e.get("quality")): e for e in (block.get("mapping") or [])
               if isinstance(e, Mapping)}
    reverse = {str(e.get("degradation")): e for e in (block.get("reverse_mapping") or [])
               if isinstance(e, Mapping)}
    hits = 0
    offenders: list[str] = []
    unmapped_declared = 0
    for name in QUALITY_COMPONENTS:
        entry = forward.get(name)
        if entry is None:
            offenders.append(f"quality:{name} absent")
            continue
        empty = not entry.get("estimated_from")
        marked = str(entry.get("status") or "") == "unmapped"
        if empty and not marked:
            offenders.append(f"quality:{name} has no driver and is not marked unmapped")
        else:
            hits += 1
            if marked:
                unmapped_declared += 1
    for name in DEGRADATION_COMPONENTS:
        entry = reverse.get(name)
        if entry is None:
            offenders.append(f"degradation:{name} absent")
            continue
        empty = not entry.get("drives")
        marked = str(entry.get("status") or "") == "unmapped"
        if empty and not marked:
            offenders.append(f"degradation:{name} drives nothing and is not marked unmapped")
        else:
            hits += 1
            if marked:
                unmapped_declared += 1
    total = len(QUALITY_COMPONENTS) + len(DEGRADATION_COMPONENTS)
    forbidden = bool(block.get("forbidden_equivalence"))
    status = PASS if (hits == total and forbidden) else FAIL
    detail = (f"{hits}/{total} components mapped with a direction; unmapped declared "
              f"{unmapped_declared}; forbidden_equivalence={forbidden}"
              + (f"; offenders={offenders}" if offenders else ""))
    return CheckResult("quality.mapping_direction", status, detail, denominator=total, hits=hits,
                       decisions=("D8",), thresholds=thresholds,
                       evidence={"unmapped_declared": unmapped_declared,
                                 "declared_unmapped_count": block.get("unmapped_count"),
                                 "spaces": block.get("spaces", {}),
                                 "offenders": offenders})


def _check_quality_keys(target: Path, defaults: dict[str, Any] | None) -> CheckResult:
    thresholds = [
        {"threshold": f"the store's quality vectors use the {len(QUALITY_COMPONENTS)} frozen "
                      f"names",
         "source": "docs/a12/decision_record.md D8 / p0236"},
    ]
    db = _store_db(target)
    if db is None:
        return CheckResult("quality.store_key_alignment", NOT_APPLICABLE,
                           f"no metadata.sqlite under {target}",
                           denominator=len(QUALITY_COMPONENTS), hits=0, decisions=("D8",),
                           thresholds=thresholds)
    try:
        con = _open_ro(db)
        try:
            rows = list(con.execute("select meta_json from assets"))
        finally:
            con.close()
    except sqlite3.Error as exc:
        return CheckResult("quality.store_key_alignment", UNREADABLE, f"assets unreadable: {exc}",
                           denominator=len(QUALITY_COMPONENTS), hits=0, decisions=("D8",),
                           thresholds=thresholds)
    observed: dict[str, int] = {}
    for (meta_json,) in rows:
        try:
            meta = json.loads(meta_json or "{}")
        except Exception:  # noqa: BLE001
            continue
        for holder in ("quality", "quality_vector", "quality8"):
            block = meta.get(holder)
            if isinstance(block, Mapping):
                for key in block:
                    observed[str(key)] = observed.get(str(key), 0) + 1
    if not observed:
        return CheckResult("quality.store_key_alignment", MISSING,
                           "no quality vector found in the store metadata",
                           denominator=len(QUALITY_COMPONENTS), hits=0, decisions=("D8",),
                           thresholds=thresholds)
    exact = [name for name in QUALITY_COMPONENTS if name in observed]
    hits = len(exact)
    status = PASS if hits == len(QUALITY_COMPONENTS) else FAIL
    detail = (f"{hits}/{len(QUALITY_COMPONENTS)} frozen quality names observed as store keys; "
              f"observed keys={sorted(observed)}")
    return CheckResult("quality.store_key_alignment", status, detail,
                       denominator=len(QUALITY_COMPONENTS), hits=hits, decisions=("D8",),
                       thresholds=thresholds,
                       evidence={"observed_keys": dict(sorted(observed.items())),
                                 "missing": [n for n in QUALITY_COMPONENTS if n not in observed],
                                 "note": "renaming keys is a code-side change owned by "
                                         "synlab/observe/quality.py"})


def _check_context(repo: Path, target: Path, defaults: dict[str, Any] | None) -> CheckResult:
    block = (defaults or {}).get("context_v1_fields") or {}
    declared = [str(e.get("field")) for e in (block.get("v1_fields") or [])
                if isinstance(e, Mapping)]
    query_keys = [str(k) for k in (block.get("query_keys") or CONTEXT_QUERY_KEYS)]
    thresholds = [
        {"threshold": "every declared v1 field appears in the landed implementation",
         "source": "docs/a12/decision_record.md D11"},
        {"threshold": "context_id / batch_id / bag_id are queryable on every context pack",
         "source": "docs/a12/decision_record.md D11"},
    ]
    texts: dict[str, str] = {}
    for rel in CONTEXT_IMPL_FILES:
        path = repo / rel
        texts[rel] = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    blob = "\n".join(texts.values())
    field_hits = [name for name in declared if name and name in blob]
    key_hits = [k for k in query_keys if k in blob]
    denominator = len(declared) + len(query_keys)
    measured = len(field_hits) + len(key_hits)

    packs = 0
    pack_key_hits = 0
    db = _store_db(target)
    if db is not None:
        try:
            con = _open_ro(db)
            try:
                rows = list(con.execute("select meta_json from assets where role = ?",
                                        ("context_pack",)))
            finally:
                con.close()
            packs = len(rows)
            for (meta_json,) in rows:
                try:
                    meta = json.loads(meta_json or "{}")
                except Exception:  # noqa: BLE001
                    continue
                if all(str(meta.get(k, "") or "") for k in query_keys):
                    pack_key_hits += 1
        except sqlite3.Error:
            packs = 0
    implementation_ok = measured == denominator and denominator > 0
    if not implementation_ok:
        status = FAIL if declared else MISSING
        reason = "the frozen v1 field set is not fully landed in the implementation"
    elif packs == 0:
        status = MISSING
        reason = ("the v1 fields are landed in the implementation but this store holds no "
                  "context_pack asset, so context_id/batch_id/bag_id cannot be queried here")
    elif pack_key_hits == packs:
        status = PASS
        reason = "every context pack answers the three query keys"
    else:
        status = FAIL
        reason = "some context packs do not answer all three query keys"
    detail = (f"implementation {len(field_hits)}/{len(declared)} fields + "
              f"{len(key_hits)}/{len(query_keys)} query keys; store context packs {packs}, "
              f"with all query keys {pack_key_hits} -- {reason}")
    return CheckResult("context.v1_fields_queryable", status, detail, denominator=denominator,
                       hits=measured, decisions=("D11",), thresholds=thresholds,
                       evidence={"declared_fields": declared, "missing_in_implementation":
                                 [n for n in declared if n not in blob],
                                 "query_keys": query_keys,
                                 "store_packs": packs,
                                 "store_packs_with_query_keys": pack_key_hits,
                                 "simulated_flag": block.get("simulated"),
                                 "forbidden_fields": block.get("forbidden_fields", []),
                                 "unresolved": block.get("unresolved", [])})


def _check_structured_light(repo: Path, defaults: dict[str, Any] | None) -> CheckResult:
    block = (defaults or {}).get("structured_light") or {}
    thresholds = [
        {"threshold": "0 files in synlab/ carry a positive structured-light/laser claim",
         "source": "docs/a12/decision_record.md D5"},
        {"threshold": "v1_excluded == true",
         "source": "configs/a12/decision_defaults.json:structured_light"},
    ]
    files = sorted((repo / "synlab").rglob("*.py")) if (repo / "synlab").is_dir() else []
    offenders: list[dict[str, Any]] = []
    clean = 0
    scanned = 0
    for path in files:
        rel = path.relative_to(repo).as_posix()
        if rel in SELF_MODULES:
            continue  # this gate defines the forbidden tokens; it makes no capability claim
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        found = [tok for tok in STRUCTURED_LIGHT_FORBIDDEN_TOKENS if tok in text]
        if found:
            offenders.append({"file": rel, "tokens": found})
        else:
            clean += 1
    excluded_ok = block.get("v1_excluded") is True
    status = PASS if (clean == scanned and scanned and excluded_ok) else (
        MISSING if not scanned else FAIL)
    detail = (f"{clean}/{scanned} synlab modules free of a structured-light/laser claim; "
              f"v1_excluded={block.get('v1_excluded')}")
    return CheckResult("structured_light.claim_free", status, detail, denominator=scanned,
                       hits=clean, decisions=("D5",), thresholds=thresholds,
                       evidence={"offenders": offenders, "self_excluded": sorted(SELF_MODULES),
                                 "excluded_modalities": block.get("excluded_modalities", []),
                                 "reopen_path": block.get("reopen_path")})


# --------------------------------------------------------------------------- the driver
def run_checks(target: str | Path, *, repo: str | Path | None = None,
               exports_root: str | Path | None = None,
               reports_root: str | Path | None = None,
               defaults: dict[str, Any] | None = None,
               defaults_error: str | None = None) -> list[CheckResult]:
    """Run every read-only conformance check against ``target`` (a store root or db file)."""
    target_path = Path(target)
    repo_path = Path(repo) if repo is not None else _guess_repo(target_path)
    exports = Path(exports_root) if exports_root is not None else repo_path / "data" / "a12_exports"
    reports = Path(reports_root) if reports_root is not None else repo_path / "data" / "a12" / "reports"
    return [
        _check_defaults_present(defaults, defaults_error),
        _check_action_proposal(defaults, repo_path),
        _check_primary_metrics(defaults),
        _check_m_and_delta(reports),
        _check_surface_authority(target_path, defaults),
        _check_loss_mask_authority(exports),
        _check_negative_supply(exports),
        _check_visible_gate_columns(exports),
        _check_synthetic_only(exports, defaults),
        _check_quality_mapping(defaults),
        _check_quality_keys(target_path, defaults),
        _check_context(repo_path, target_path, defaults),
        _check_structured_light(repo_path, defaults),
    ]


def check_store(target: str | Path, *, repo: str | Path | None = None,
                exports_root: str | Path | None = None,
                reports_root: str | Path | None = None) -> dict[str, Any]:
    """The report document: verdict, first cause, every check, and the unreadable list."""
    target_path = Path(target)
    if not target_path.exists():
        raise QcDecisionInputError(f"target does not exist: {target_path}")
    repo_path = Path(repo) if repo is not None else _guess_repo(target_path)
    defaults, error = load_defaults(repo_path)
    checks = run_checks(target_path, repo=repo_path, exports_root=exports_root,
                        reports_root=reports_root, defaults=defaults, defaults_error=error)
    required = [c for c in checks if c.required]
    failed = [c for c in required if c.status != PASS]
    if defaults is None:
        verdict = "unreadable"
    elif not failed:
        verdict = "conformant"
    elif any(c.status == PASS for c in checks):
        verdict = "partial"
    else:
        verdict = "non_conformant"
    first_cause = None
    for check in checks:
        if check.required and check.status != PASS:
            first_cause = {"check_id": check.id, "status": check.status, "detail": check.detail}
            break
    unreadable: list[str] = []
    for check in checks:
        raw = check.evidence.get("unreadable")
        if isinstance(raw, str):
            unreadable.append(raw)
        elif isinstance(raw, (list, tuple)):
            unreadable.extend(str(item) for item in raw)
    unreadable = sorted(set(unreadable))
    statuses: dict[str, int] = {}
    for check in checks:
        statuses[check.status] = statuses.get(check.status, 0) + 1
    return {
        "schema": SCHEMA,
        # The numbers below are a *read-only snapshot* of the moment they were measured: a
        # store that another writer is still filling will move after this file is written.
        "generated_at": time.time(),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "target": {"path": str(target_path), "kind": "store"
                   if _store_db(target_path) is not None else "unknown"},
        "defaults": {"path": DEFAULTS_RELPATH, "loaded": defaults is not None,
                     "error": error, "sections": list(DEFAULT_SECTIONS)
                     if defaults is None else sorted(defaults)},
        "verdict": verdict,
        "conformant": verdict == "conformant",
        "checks_total": len(checks),
        "checks_required": len(required),
        "checks_failed_required": len(failed),
        "status_counts": statuses,
        "first_cause": first_cause,
        "checks": [c.as_dict() for c in checks],
        "unreadable": unreadable,
        "decision_coverage": sorted({d for c in checks for d in c.decisions}),
    }


def write_report(report: Mapping[str, Any], target: str | Path, *,
                 repo: str | Path | None = None,
                 out_dir: str | Path | None = None) -> Path:
    """Write ``data/a12/reports/decision_checks_<store>.json`` (the only file we write)."""
    directory = Path(out_dir) if out_dir is not None else default_report_dir(
        Path(repo) if repo is not None else None)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"decision_checks_{report_slug(target, repo=repo)}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True,
                               default=str) + "\n", encoding="utf-8")
    return path


def format_summary(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    target = report.get("target") or {}
    lines.append(f"decision conformance -- {target.get('path')} ({target.get('kind')})")
    lines.append(f"  verdict  : {report.get('verdict')}   "
                 f"required failed={report.get('checks_failed_required')}"
                 f"/{report.get('checks_required')}")
    first = report.get("first_cause")
    if first:
        lines.append(f"  first    : [{first['status']}] {first['check_id']} -- {first['detail']}")
    lines.append("  checks   :")
    for check in report.get("checks", []):
        denom = check.get("denominator")
        hits = check.get("hits")
        counts = "" if denom is None else f"  ({hits}/{denom})"
        flag = "" if check.get("required") else "  [report-only]"
        lines.append(f"    {check['status']:<14} {check['id']}{counts}{flag}")
        lines.append(f"        {check['detail']}")
    return "\n".join(lines)


def _main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m synlab.qc.decision_checks <store-root> [more store roots]")
        return 2
    repo = _guess_repo(Path(args[0]))
    exit_code = 0
    for raw in args:
        target = Path(raw)
        try:
            report = check_store(target, repo=repo)
        except QcDecisionInputError as exc:
            print(f"[SKIP] {exc}")
            exit_code = max(exit_code, 2)
            continue
        path = write_report(report, target, repo=repo)
        print(format_summary(report))
        print(f"  report   : {path}")
        if report["verdict"] != "conformant":
            exit_code = max(exit_code, 3)
    return exit_code


if __name__ == "__main__":  # pragma: no cover - CLI convenience
    raise SystemExit(_main())
