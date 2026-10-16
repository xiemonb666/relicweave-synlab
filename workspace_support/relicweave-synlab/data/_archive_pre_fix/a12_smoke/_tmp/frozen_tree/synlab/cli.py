"""``synlab`` console entry point (plan 22.4).

Contract: machine results go to stdout as the universal ``Result`` JSON when ``--json``
is given, logs go to stderr, and any structured failure returns a non-zero exit code
(1 for FAILED, 2 for BLOCKED/PENDING, 3 for schema/usage errors).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

import typer

from .canonical import hash_file, hash_json
from .config import compile_spec, load_diagnose_spec, load_generation_spec, load_train_spec
from .errors import ErrorCode, Result, SynLabError
from .jobs.resources import Estimate, ResourceBudget, ResourceGuard
from .registry import REGISTRY, load_all
from .roles import ROLE_COVERAGE, ROLE_QA_REPORT, ROLE_RUN_SPEC
from .storage.release import ReleaseManager
from .storage.store import QA_PASS, AssetStore

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="A12 controllable synthetic fragment laboratory (standalone)")

DEFAULT_DATA_ROOT = "data/a12"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2
EXIT_USAGE = 3


def _store(root: str) -> AssetStore:
    return AssetStore(Path(root))


def _emit(result: Result, *, json_mode: bool, exit_code: int = EXIT_OK) -> None:
    if json_mode:
        sys.stdout.write(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(f"{result.status}\n")
        for key, value in result.metrics.items():
            sys.stdout.write(f"  {key}: {value}\n")
    raise typer.Exit(code=exit_code)


def _fail(exc: SynLabError, *, json_mode: bool) -> None:
    result = Result.failure(exc) if exc.code not in (ErrorCode.INPUT_UNAVAILABLE,) else Result.blocked(exc)
    code = EXIT_FAILED if result.status == "FAILED" else EXIT_BLOCKED
    if exc.code in (ErrorCode.SCHEMA_INVALID,):
        code = EXIT_USAGE
    sys.stderr.write(f"[{exc.code}] ({exc.stage}) {exc.message}\n")
    _emit(result, json_mode=json_mode, exit_code=code)


# ---------------------------------------------------------------------------- doctor
@app.command("doctor")
def doctor(
    root: str = typer.Option(DEFAULT_DATA_ROOT, "--root", help="data root"),
    json_mode: bool = typer.Option(False, "--json"),
    out: str = typer.Option("docs/a12/env_report.json", "--out"),
    capabilities_out: str = typer.Option("docs/a12/backend_capabilities.json", "--capabilities-out"),
) -> None:
    """Environment and minimum real capability checks."""
    from .doctor import write_env_report

    report = __import__("synlab.doctor", fromlist=["run_doctor"]).run_doctor(root)
    write_env_report(report, out)
    caps = {
        "schema": "synlab.backend_capabilities.v1",
        "generated_at": report["generated_at"],
        "checks": [c for c in report["checks"] if c["name"].startswith("backend:")],
        "note": ("actual behaviour measured on this host; absence is reported as MISSING, "
                 "never replaced by a fake result"),
    }
    write_env_report(caps, capabilities_out)
    result = Result.ok(
        metrics={"pass": report["summary"]["pass"], "fail": report["summary"]["fail"],
                 "missing": report["summary"]["missing"], "report": out},
        qa_report_ref=str(out),
    )
    _emit(result, json_mode=json_mode,
          exit_code=EXIT_OK if report["summary"]["fail"] == 0 else EXIT_FAILED)


# ---------------------------------------------------------------------------- specs
@app.command("validate")
def validate(config: str = typer.Option(..., "--config"), json_mode: bool = typer.Option(False, "--json")) -> None:
    """Schema, stage, applicability and file-dependency validation."""
    try:
        load_all()
        spec = load_generation_spec(config)
        compiled = compile_spec(spec)
        if compiled.errors:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "; ".join(compiled.errors), stage="validate")
        result = Result.ok(
            metrics={"spec_hash": compiled.spec_hash, "warnings": compiled.warnings,
                     "expanded": compiled.expanded},
        )
        _emit(result, json_mode=json_mode)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("budget")
def budget(config: str = typer.Option(..., "--config"), root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
           json_mode: bool = typer.Option(False, "--json")) -> None:
    """CPU/GPU/temporary-disk/long-term-disk budget estimate."""
    try:
        spec = load_generation_spec(config)
        compiled = compile_spec(spec)
        if compiled.errors:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "; ".join(compiled.errors), stage="budget")
        store = _store(root)
        guard = ResourceGuard(store, ResourceBudget(**spec.resources.model_dump()))
        estimate = Estimate(
            rss_gb=2.0,
            vram_gb=2.0 if spec.observation.renderer == "blender" else 0.0,
            temp_disk_gb=1.0,
            persistent_disk_gb=0.05,
            assumptions={"per_mother_rss_gb": 2.0, "note": "development initial values"},
        )
        report = guard.budget_report(planned_jobs=max(1, spec.dataset.target_mothers), estimates=[estimate])
        result = Result.ok(
            metrics=report,
            input_hashes=[compiled.spec_hash],
            status="OK" if report["feasible"] else "BLOCKED",
            qa_report_ref=None,
        )
        if not report["feasible"]:
            raise SynLabError(ErrorCode.BUDGET_EXCEEDED, "budget infeasible for requested plan",
                              stage="budget", measurements=report)
        _emit(result, json_mode=json_mode)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


# ---------------------------------------------------------------------------- generation
@app.command("generate")
def generate(
    config: str = typer.Option(..., "--config"),
    root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
    json_mode: bool = typer.Option(False, "--json"),
    resume: bool = typer.Option(False, "--resume"),
) -> None:
    """Build and execute the real asset DAG."""
    try:
        from .pipeline import run_generation

        load_all()
        spec = load_generation_spec(config)
        report = run_generation(spec, store_root=root, resume=resume)
        status = "QA_PASSED" if report.get("accepted", 0) > 0 and not report.get("errors") else "FAILED"
        result = Result.ok(
            metrics=report, input_hashes=[report.get("spec_hash", "")],
            status=status,
        )
        _emit(result, json_mode=json_mode, exit_code=EXIT_OK if status == "QA_PASSED" else EXIT_FAILED)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("audit")
def audit(run: str = typer.Option(..., "--run"), root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
          json_mode: bool = typer.Option(False, "--json")) -> None:
    """Data closure, permission, split and truth audit for a run."""
    try:
        from .qc.audit import audit_run

        store = _store(root)
        report = audit_run(store, run)
        status = "QA_PASSED" if report["ok"] else "QA_FAILED"
        result = Result.ok(metrics=report, status=status)
        _emit(result, json_mode=json_mode, exit_code=EXIT_OK if report["ok"] else EXIT_FAILED)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("pattern-audit")
def pattern_audit(root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
                  json_mode: bool = typer.Option(False, "--json")) -> None:
    """Seam, scale, inheritance and determinism audit across the 16 pattern families."""
    try:
        from .patterns.audit_all import audit_all_patterns

        report = audit_all_patterns(_store(root))
        result = Result.ok(metrics=report, status="QA_PASSED" if report["ok"] else "QA_FAILED")
        _emit(result, json_mode=json_mode, exit_code=EXIT_OK if report["ok"] else EXIT_FAILED)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("operator-audit")
def operator_audit(root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
                   json_mode: bool = typer.Option(False, "--json"),
                   levels: str = typer.Option("0,1,2,3,4", "--levels")) -> None:
    """31-axis identity, effect and label audit."""
    try:
        from .degrade.api import audit_all_axes

        level_list = [int(x) for x in levels.split(",") if x.strip()]
        report = audit_all_axes(_store(root), levels=level_list)
        result = Result.ok(metrics=report, status="QA_PASSED" if report["ok"] else "QA_FAILED")
        _emit(result, json_mode=json_mode, exit_code=EXIT_OK if report["ok"] else EXIT_FAILED)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("profile")
def profile(run: str = typer.Option(..., "--run"), root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
            json_mode: bool = typer.Option(False, "--json")) -> None:
    """Measured wall time, memory and throughput for a run."""
    try:
        from .qc.profile import profile_run

        report = profile_run(_store(root), run)
        _emit(Result.ok(metrics=report), json_mode=json_mode)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


# ---------------------------------------------------------------------------- pools / releases
@app.command("build-pool")
def build_pool(release: str = typer.Option(..., "--release"), config: str = typer.Option(..., "--config"),
               root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
               json_mode: bool = typer.Option(False, "--json")) -> None:
    """Build a frozen gallery/query pool with full R2 closure."""
    try:
        from .relations.api import build_pool_from_config

        store = _store(root)
        report = build_pool_from_config(store, release, config)
        status = "QA_PASSED" if report.get("ok") else "QA_FAILED"
        _emit(Result.ok(metrics=report, status=status), json_mode=json_mode,
              exit_code=EXIT_OK if report.get("ok") else EXIT_FAILED)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


release_app = typer.Typer(no_args_is_help=True, help="release operations")
app.add_typer(release_app, name="release")


@release_app.command("freeze")
def release_freeze(
    run: str = typer.Option(..., "--run"),
    protocol: Optional[str] = typer.Option(None, "--protocol"),
    root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
    json_mode: bool = typer.Option(False, "--json"),
) -> None:
    """Verify gates and freeze an immutable release."""
    try:
        from .qc.gates import evaluate_gates

        store = _store(root)
        gates, asset_ids, profile = evaluate_gates(store, run, protocol)
        manager = ReleaseManager(store)
        release_id = f"{run}_{profile.lower()}"
        record = manager.freeze(release_id=release_id, profile=profile, scope=run,
                                asset_ids=asset_ids, gates=gates)
        _emit(Result.ok(metrics=record.as_dict()), json_mode=json_mode)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("export")
def export(release: str = typer.Option(..., "--release"), fmt: str = typer.Option("parquet", "--format"),
           root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
           out: Optional[str] = typer.Option(None, "--out"),
           json_mode: bool = typer.Option(False, "--json")) -> None:
    """Export a portable package; the source release stays unchanged."""
    try:
        from .storage.export import export_release

        store = _store(root)
        manifest = export_release(store, release, fmt=fmt, out_dir=out)
        _emit(Result.ok(metrics=manifest), json_mode=json_mode)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


# ---------------------------------------------------------------------------- learning
@app.command("train")
def train(config: str = typer.Option(..., "--config"), root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
          json_mode: bool = typer.Option(False, "--json")) -> None:
    try:
        from .training.api import train as run_train

        spec = load_train_spec(config)
        report = run_train(spec, _store(root))
        status = "QA_PASSED" if report.get("ok") else "FAILED"
        _emit(Result.ok(metrics=report, status=status), json_mode=json_mode,
              exit_code=EXIT_OK if report.get("ok") else EXIT_FAILED)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("evaluate")
def evaluate(config: str = typer.Option(..., "--config"), root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
             json_mode: bool = typer.Option(False, "--json")) -> None:
    """Fixed-model, fixed-pool, fixed-roster evaluation (no tuning)."""
    try:
        from .training.api import evaluate as run_eval

        spec = load_diagnose_spec(config)
        store = _store(root)
        report = run_eval(spec.checkpoint_ref, spec.candidate_pool_ref, store=store,
                          split=spec.evaluation_split,
                          top_k=tuple(spec.metrics and [1, 5, 10, 20] or [1, 5, 10, 20]))
        _emit(Result.ok(metrics=report), json_mode=json_mode)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("diagnose")
def diagnose(config: str = typer.Option(..., "--config"), root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
             json_mode: bool = typer.Option(False, "--json")) -> None:
    try:
        from .diagnostics.api import run_diagnosis

        spec = load_diagnose_spec(config)
        report = run_diagnosis(spec, _store(root))
        _emit(Result.ok(metrics=report), json_mode=json_mode)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("resume")
def resume(run: str = typer.Option(..., "--run"), root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
           json_mode: bool = typer.Option(False, "--json")) -> None:
    """Resume a data job or a training checkpoint from its safe point."""
    try:
        from .jobs.recovery import resume_run

        report = resume_run(_store(root), run)
        _emit(Result.ok(metrics=report), json_mode=json_mode)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("episode")
def episode(config: str = typer.Option(..., "--config"), root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
            json_mode: bool = typer.Option(False, "--json")) -> None:
    try:
        from .episodes.api import run_episode_config

        report = run_episode_config(_store(root), config)
        _emit(Result.ok(metrics=report), json_mode=json_mode)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("acceptance")
def acceptance(
    root: str = typer.Option(DEFAULT_DATA_ROOT, "--root"),
    profile: str = typer.Option("SANDBOX_CORE", "--profile"),
    json_mode: bool = typer.Option(False, "--json"),
    out: str = typer.Option("docs/a12/acceptance_report.md", "--out"),
) -> None:
    """Run the A01–A36 acceptance harness and write the report."""
    try:
        from .qc.acceptance import run_acceptance

        report = run_acceptance(store_root=root, profile=profile, report_path=out)
        failed = [k for k, v in report["items"].items() if v["status"] == "FAIL"]
        _emit(Result.ok(metrics={"report": out, "profile": profile, "failed": failed,
                                 "counts": report["counts"]}),
              json_mode=json_mode, exit_code=EXIT_OK if not failed else EXIT_FAILED)
    except SynLabError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("registry")
def registry(kind: Optional[str] = typer.Option(None, "--kind"), json_mode: bool = typer.Option(False, "--json"),
             out: Optional[str] = typer.Option(None, "--out")) -> None:
    """Print the capability registry (ids, versions, schemas, status)."""
    load_all()
    entries = [e.as_dict() for e in (REGISTRY.list(kind) if kind else REGISTRY.list())]
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True),
                             encoding="utf-8")
    if json_mode:
        sys.stdout.write(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
    else:
        for entry in entries:
            sys.stdout.write(f"{entry['kind']:18s} {entry['id']:20s} {entry['status']:12s} "
                             f"{entry['name']}\n")
    raise typer.Exit(code=EXIT_OK)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
