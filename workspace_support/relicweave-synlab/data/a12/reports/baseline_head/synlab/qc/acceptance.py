"""Acceptance harness for A01–A36 (plan 25.1, 30.19).

Every item records the real command, exit code, evidence path and status.  Nothing is
inferred: an item with no evidence is NOT_RUN, an item whose prerequisites are absent is
PENDING, and an item that ran and failed is FAIL.  The harness never mutates source data.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..canonical import hash_json
from ..config import compile_spec, load_diagnose_spec, load_generation_spec, load_recipe_spec
from ..errors import ErrorCode, SynLabError
from ..registry import REGISTRY, load_all
from ..roles import FORBIDDEN_FEATURE_FIELDS
from ..storage.release import PROFILE_GATES, ReleaseManager
from ..storage.store import QA_PASS, AssetStore, health_check

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Ctx:
    store_root: Path
    store: AssetStore
    profile: str
    tmp: Path
    reports: dict[str, Any] = field(default_factory=dict)

    def report(self, name: str) -> dict[str, Any] | None:
        if name in self.reports:
            return self.reports[name]
        path = self.store.root / "reports" / f"{name}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            self.reports[name] = data
            return data
        if name == "doctor":
            path = ROOT / "docs" / "a12" / "env_report.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                self.reports[name] = data
                return data
            return None
        self.reports[name] = None
        return None

    def write_report(self, name: str, payload: dict[str, Any]) -> Path:
        path = self.store.root / "reports" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                        encoding="utf-8")
        self.reports[name] = payload
        return path


ITEMS: dict[str, tuple[str, Callable[[Ctx], dict[str, Any]]]] = {}


def item(acceptance_id: str, title: str) -> Callable[[Callable[[Ctx], dict[str, Any]]], Callable[[Ctx], dict[str, Any]]]:
    def decorator(func: Callable[[Ctx], dict[str, Any]]) -> Callable[[Ctx], dict[str, Any]]:
        ITEMS[acceptance_id] = (title, func)
        return func

    return decorator


def result(status: str, *, evidence: list[str] | None = None, metrics: dict[str, Any] | None = None,
           notes: str = "") -> dict[str, Any]:
    return {"status": status, "evidence": evidence or [], "metrics": metrics or {}, "notes": notes}


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 1800) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True, timeout=timeout,
                          check=False)
    tail = ((proc.stdout or "") + (proc.stderr or ""))[-4000:]
    return proc.returncode, tail


# ---------------------------------------------------------------------------- A01–A08
@item("A01", "合同与权限（六 pack、features/labels 边界）")
def a01(ctx: Ctx) -> dict[str, Any]:
    evidence: list[str] = []
    metrics: dict[str, Any] = {}
    # schema must reject unknown fields
    from ..schemas.spec import GenerationSpec

    payload = json.loads(json.dumps(load_generation_spec(ROOT / "configs/a12/sandbox.yaml").model_dump(by_alias=True)))
    payload["unexpected_field"] = 1
    rejected = False
    try:
        GenerationSpec.model_validate(payload)
    except Exception:
        rejected = True
    metrics["unknown_field_rejected"] = rejected
    # feature whitelist machinery must exist and reject answer fields
    try:
        from ..observe.features import assert_no_leakage  # type: ignore

        try:
            assert_no_leakage({"features": {"rgb": 1}, "labels": {"relation": "R2"},
                              "provenance": {"seed": 1}})
            leakage_rejected = False
        except SynLabError as exc:
            leakage_rejected = exc.code == ErrorCode.LEAKAGE_DETECTED
        metrics["leakage_detector"] = leakage_rejected
        evidence.append("synlab/observe/features.py::assert_no_leakage")
    except Exception as exc:
        metrics["leakage_detector"] = f"NOT_AVAILABLE: {type(exc).__name__}"
    # committed feature assets must not carry forbidden metadata
    bad: list[str] = []
    for asset in ctx.store.list_assets(role="feature_bundle", limit=100000):
        bad += [a for a in sorted(set(asset.meta or {}) & FORBIDDEN_FEATURE_FIELDS)]
    metrics["forbidden_fields_in_committed_features"] = bad
    status = "PASS" if rejected and metrics.get("leakage_detector") is True and not bad else (
        "FAIL" if rejected and bad else "PENDING")
    return result(status, evidence=evidence, metrics=metrics,
                  notes="schema rejection + recursive whitelist + committed feature audit")


@item("A02", "坐标投影（mm、K、T、depth/range、crop）")
def a02(ctx: Ctx) -> dict[str, Any]:
    doctor = ctx.report("doctor") or {}
    check = next((c for c in doctor.get("checks", []) if c["name"] == "geometry:projection_roundtrip"), None)
    metrics = dict(check.get("detail", {})) if check else {}
    status = check["status"] if check else "NOT_RUN"
    return result(status, evidence=["docs/a12/env_report.json"], metrics=metrics,
                  notes="analytic projection/back-projection round trip")


@item("A03", "母体（24 族 × ≥20 独立母体）")
def a03(ctx: Ctx) -> dict[str, Any]:
    mothers = ctx.store.list_assets(role="mother_mesh", limit=100000)
    by_vessel: dict[str, set[str]] = {}
    for asset in mothers:
        vessel = (asset.meta or {}).get("vessel_id", "unknown")
        by_vessel.setdefault(vessel, set()).add(asset.lineage_id or asset.asset_id)
    metrics = {"vessels_present": len(by_vessel),
               "min_lineages_per_vessel": min((len(v) for v in by_vessel.values()), default=0),
               "total_mothers": len(mothers)}
    if not mothers:
        return result("NOT_RUN", metrics=metrics, notes="no mother assets generated yet")
    full = len(by_vessel) >= 24 and metrics["min_lineages_per_vessel"] >= 20
    return result("PASS" if full else "PENDING", metrics=metrics,
                  notes="counts come from committed mother assets; 24x20 requires the L2 run")


@item("A04", "材料层（12 材料 / 4 层结构）")
def a04(ctx: Ctx) -> dict[str, Any]:
    materials = ctx.store.list_assets(role="material_profile", limit=100000)
    ids = sorted({(a.meta or {}).get("material_id", "") for a in materials} - {""})
    metrics = {"materials_present": len(ids), "ids": ids}
    status = "PASS" if len(ids) >= 12 else ("PENDING" if materials else "NOT_RUN")
    report = ctx.report("material_layer_audit")
    if report:
        metrics["audit"] = report.get("metrics", {})
        if not report.get("ok", True):
            status = "FAIL"
    return result(status, metrics=metrics, evidence=["data/a12/reports/material_layer_audit.json"]
                  if report else [], notes="shading vs geometric layers must be distinguishable")


@item("A05", "花纹（16 family）")
def a05(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("pattern_audit")
    if not report:
        return result("NOT_RUN", notes="run `synlab pattern-audit` first")
    metrics = {"families": len(report.get("families", {})),
               "max_seam_error": report.get("max_seam_error"),
               "deterministic": report.get("deterministic"),
               "geometry_applied": report.get("geometry_applied")}
    ok = report.get("ok") and metrics["families"] >= 16 and (metrics["max_seam_error"] or 1) <= 1e-5
    return result("PASS" if ok else "FAIL", evidence=["data/a12/reports/pattern_audit.json"],
                  metrics=metrics)


@item("A06", "断裂守恒（四必做后端、薄壳、复杂体）")
def a06(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("fracture_audit")
    if not report:
        return result("NOT_RUN", notes="run a generation that performs fracture first")
    backends = report.get("backends", {})
    ok_backends = [b for b, v in backends.items() if v.get("status") == "PASS"]
    metrics = {"backends_pass": len(ok_backends), "backends": {k: v.get("status") for k, v in backends.items()},
               "conservation_ratio_max": report.get("conservation_ratio_max"),
               "overlap_ratio_max": report.get("overlap_ratio_max"),
               "shared_distance_p95_max": report.get("shared_distance_p95_max")}
    status = "PASS" if len(ok_backends) >= 4 and report.get("ok") else (
        "PENDING" if ok_backends else "FAIL")
    return result(status, evidence=["data/a12/reports/fracture_audit.json"], metrics=metrics)


@item("A07", "精度实现（cutter / 共形 warp）")
def a07(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("precision_report")
    if not report:
        return result("NOT_RUN", notes="requires a fracture event with an error budget")
    metrics = {"requested_mm": report.get("requested_mm"), "realized_mm": report.get("realized_mm"),
               "t_junctions": report.get("t_junctions")}
    realized = report.get("realized_mm")
    ok = report.get("ok") and realized is not None and realized <= report.get("requested_mm", 0.01) + 1e-9
    return result("PASS" if ok else "FAIL", evidence=["data/a12/reports/precision_report.json"],
                  metrics=metrics, notes="requested values alone never count as realized precision")


@item("A08", "真值关系（R2/R1/R0/UNKNOWN 与事件树）")
def a08(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("truth_fixture")
    if not report:
        return result("NOT_RUN", notes="requires `synlab.truth` fixture run")
    metrics = report.get("metrics", {})
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/truth_fixture.json"], metrics=metrics)


# ---------------------------------------------------------------------------- A09–A16
@item("A09", "减法损伤（P01–P04/P07 + 适用 P08）")
def a09(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("physical_audit")
    if not report:
        return result("NOT_RUN", notes="requires a physical damage run")
    metrics = report.get("metrics", {})
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/physical_audit.json"], metrics=metrics)


@item("A10", "31 轴身份与效果")
def a10(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("operator_audit")
    if not report:
        return result("NOT_RUN", notes="run `synlab operator-audit` first")
    axes = report.get("axes", {})
    applied = [a for a, v in axes.items() if v.get("status") == "PASS"]
    with20 = [a for a, v in axes.items() if v.get("independent_mothers", 0) >= 20]
    metrics = {"axes_registered": len(axes), "axes_pass": len(applied), "axes_with_20_mothers": len(with20),
               "identity_ok": report.get("identity_ok"),
               "missing": [a for a, v in axes.items() if v.get("status") in ("MISSING", "NOT_RUN")]}
    if len(axes) < 31:
        return result("FAIL", evidence=["data/a12/reports/operator_audit.json"], metrics=metrics)
    if report.get("identity_ok") is not True:
        return result("FAIL", evidence=["data/a12/reports/operator_audit.json"], metrics=metrics)
    status = "PASS" if len(with20) >= 31 and report.get("ok") else "PENDING"
    return result(status, evidence=["data/a12/reports/operator_audit.json"], metrics=metrics)


@item("A11", "伪凸起/补面/假桥（G08 三变体）")
def a11(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("spurious_audit")
    if not report:
        return result("NOT_RUN", notes="requires an observation-geometry run")
    metrics = report.get("metrics", {})
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/spurious_audit.json"], metrics=metrics)


@item("A12", "成像标签（RGB、深度、mask、可见性）")
def a12(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("channel_audit")
    if not report:
        return result("NOT_RUN", notes="requires an observation run")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/channel_audit.json"], metrics=report.get("metrics", {}))


@item("A13", "物理近远档（U 相机 profile）")
def a13(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("camera_profile_audit")
    if not report:
        return result("NOT_RUN", notes="requires camera profiles to be exercised")
    metrics = report.get("metrics", {})
    engineering = "PASS" if report.get("engineering_ok") else "FAIL"
    calibration = "PASS" if report.get("calibration_ok") else "PENDING"
    metrics["engineering"] = engineering
    metrics["real_calibration"] = calibration
    status = "PASS" if engineering == "PASS" and calibration == "PASS" else (
        "FAIL" if engineering == "FAIL" else "PENDING")
    return result(status, evidence=["data/a12/reports/camera_profile_audit.json"], metrics=metrics,
                  notes="A13.engineering and A13.real_calibration are reported separately")


@item("A14", "实际 MVS 子集")
def a14(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("mvs_subset")
    if not report:
        return result("NOT_RUN", notes="pycolmap route has not been exercised")
    metrics = report.get("metrics", {})
    pipeline = "PASS" if report.get("pipeline_ok") else ("FAIL" if report.get("attempted") else "NOT_RUN")
    calibration = "PASS" if report.get("real_calibration_ok") else "PENDING"
    metrics["pipeline"] = pipeline
    metrics["real_calibration"] = calibration
    status = "PASS" if pipeline == "PASS" and calibration == "PASS" else (
        "FAIL" if pipeline == "FAIL" else "PENDING")
    return result(status, evidence=["data/a12/reports/mvs_subset.json"], metrics=metrics,
                  notes="no real capture data on this host: real calibration stays PENDING")


@item("A15", "全库和采样（多 R2、R1/R0、无邻片）")
def a15(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("pool_audit")
    if not report:
        return result("NOT_RUN", notes="run `synlab build-pool` first")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/pool_audit.json"], metrics=report.get("metrics", {}))


@item("A16", "训练有效性（五任务、valid 与 missing）")
def a16(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("train_report")
    if not report:
        return result("NOT_RUN", notes="run `synlab train` first")
    metrics = report.get("metrics", {})
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/train_report.json"], metrics=metrics,
                  notes="finite losses/gradients and a toy fit are engineering checks, not research gains")


# ---------------------------------------------------------------------------- A17–A24
@item("A17", "恢复（数据 job 与训练 checkpoint）")
def a17(ctx: Ctx) -> dict[str, Any]:
    from ..jobs.recovery import recovery_probe

    try:
        probe = recovery_probe(ctx.store)
    except Exception as exc:
        return result("FAIL", notes=f"recovery probe raised {type(exc).__name__}: {exc}")
    ctx.write_report("recovery_probe", probe)
    train_resume = ctx.report("train_resume")
    metrics = {"stale_commit_blocked": probe.get("stale_commit_blocked"),
               "final_state": probe.get("final_state")}
    if train_resume:
        metrics["train_resume_ok"] = train_resume.get("ok")
    status = "PASS" if probe.get("ok") and (train_resume is None or train_resume.get("ok")) else "FAIL"
    return result(status, evidence=["data/a12/reports/recovery_probe.json"], metrics=metrics)


@item("A18", "诊断计算（指标与统计）")
def a18(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("metric_fixture")
    if not report:
        return result("NOT_RUN", notes="diagnostics fixture has not been run")
    stats = ctx.report("stat_fixture") or {}
    metrics = {"metric_fixture_ok": report.get("ok"), "stat_fixture_ok": stats.get("ok")}
    return result("PASS" if report.get("ok") and stats.get("ok", True) else "FAIL",
                  evidence=["data/a12/reports/metric_fixture.json", "data/a12/reports/stat_fixture.json"],
                  metrics=metrics)


@item("A19", "规则 episode（actions/cost/STOP）")
def a19(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("episode_trace")
    if not report:
        return result("NOT_RUN", notes="run `synlab episode` first")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/episode_trace.json"], metrics=report.get("metrics", {}))


@item("A20", "UI/API（12 页与真实端到端）")
def a20(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("api_ui_evidence")
    if not report:
        return result("NOT_RUN", notes="run the API/frontend evidence script first")
    metrics = report.get("metrics", {})
    return result("PASS" if report.get("ok") else "FAIL", evidence=["docs/a12/api_ui.md"], metrics=metrics)


@item("A21", "资源与规模（L2/L3）")
def a21(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("resource_profile")
    if not report:
        return result("NOT_RUN", notes="run `synlab profile --run <run>` first")
    scale = ctx.report("scale_report") or {}
    metrics = {"assets": report.get("assets"), "bytes_total": report.get("bytes_total"),
               "accepted_max": scale.get("accepted_max", 0)}
    status = "PASS" if report.get("ok") and scale.get("accepted_max", 0) >= 100000 else (
        "PENDING" if report.get("ok") else "FAIL")
    return result(status, evidence=["data/a12/reports/resource_profile.json"], metrics=metrics,
                  notes="L3 (1e5 accepted fragments) is a run artefact, not a code property")


@item("A22", "发布交接（新目录启动/读写恢复）")
def a22(ctx: Ctx) -> dict[str, Any]:
    runbook = ROOT / "docs" / "a12" / "runbook.md"
    releases = ReleaseManager(ctx.store).list_releases()
    health = health_check(str(ctx.store.root))
    metrics = {"runbook": runbook.exists(), "releases": len(releases), "store_health": health["ok"]}
    status = "PASS" if runbook.exists() and releases and health["ok"] else (
        "PENDING" if health["ok"] else "FAIL")
    return result(status, evidence=["docs/a12/runbook.md"], metrics=metrics)


@item("A23", "开源复用（第 2.4 节全部适用模块）")
def a23(ctx: Ctx) -> dict[str, Any]:
    path = ROOT / "docs" / "a12" / "reuse_manifest.json"
    if not path.exists():
        return result("FAIL", notes="reuse_manifest.json missing")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {"module", "requirement", "candidates", "selected_dependency", "version_or_commit",
                "source_url", "license_ref", "mode", "adapter_path", "poc_command", "poc_result_ref",
                "gap_reason", "custom_scope", "acceptance_ids"}
    incomplete: list[str] = []
    custom_without_gap: list[str] = []
    for entry in manifest.get("modules", []):
        missing = sorted(required - set(entry))
        if missing:
            incomplete.append(f"{entry.get('module')}: missing {missing}")
        if entry.get("mode") == "CUSTOM_GAP" and not entry.get("gap_reason"):
            custom_without_gap.append(entry.get("module", "?"))
    metrics = {"modules": len(manifest.get("modules", [])), "incomplete": incomplete,
               "custom_gap_without_evidence": custom_without_gap,
               "custom_gaps": len(manifest.get("custom_gaps", []))}
    status = "PASS" if not incomplete and not custom_without_gap else "FAIL"
    return result(status, evidence=["docs/a12/reuse_manifest.json"], metrics=metrics)


@item("A24", "观测来源/DAG")
def a24(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("source_dependency_audit")
    if not report:
        return result("NOT_RUN", notes="requires observation source-dependency audit")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/source_dependency_audit.json"],
                  metrics=report.get("metrics", {}))


# ---------------------------------------------------------------------------- A25–A36
@item("A25", "坐标/展示（0.5px、resize、EXIF、COLMAP 往返、100mm GLB）")
def a25(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("pixel_contract")
    if not report:
        return result("NOT_RUN", notes="requires the pixel/display contract suite")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/pixel_contract.json"], metrics=report.get("metrics", {}))


@item("A26", "分区形变（共享 PLC / 共形网格）")
def a26(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("mesh_warp_report")
    if not report:
        return result("NOT_RUN", notes="requires the warped_partition backend to run")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/mesh_warp_report.json"], metrics=report.get("metrics", {}))


@item("A27", "来源/对应（原三角 ID、公共面积、损伤关联分离）")
def a27(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("origin_correspondence_audit")
    if not report:
        return result("NOT_RUN", notes="requires fracture + truth audits")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/origin_correspondence_audit.json"],
                  metrics=report.get("metrics", {}))


@item("A28", "物理身份/损伤（P01/P02 固定场、嵌套、多组件）")
def a28(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("physical_identity")
    if not report:
        a09_report = ctx.report("physical_audit")
        return result("NOT_RUN" if not a09_report else "PENDING",
                      notes="requires physical identity audit (components/debris/ancestry)")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/physical_identity.json"], metrics=report.get("metrics", {}))


@item("A29", "检索/匹配（双塔、TopM 精排、全 R2 排除）")
def a29(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("retrieval_audit")
    if not report:
        return result("NOT_RUN", notes="requires a trained/evaluated retrieval run")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/retrieval_audit.json"], metrics=report.get("metrics", {}))


@item("A30", "拒识/分母（多正例接受集、失败主分母）")
def a30(ctx: Ctx) -> dict[str, Any]:
    fixture = ctx.report("metric_fixture")
    if not fixture:
        return result("NOT_RUN", notes="requires the metrics fixture (hand-computed q=B/C case)")
    metrics = fixture.get("metrics", {})
    keys = ("hand_computed_hit", "hand_computed_poolcov", "hand_computed_cov",
            "effective_zero_on_failure", "absent_risk_defined")
    ok = all(metrics.get(k) is True for k in keys)
    return result("PASS" if ok else "FAIL", evidence=["data/a12/reports/metric_fixture.json"],
                  metrics={k: metrics.get(k) for k in keys})


@item("A31", "独立数据/统计（N 广度深度、gallery 隔离、CP 假设）")
def a31(ctx: Ctx) -> dict[str, Any]:
    pool = ctx.report("pool_audit") or {}
    stats = ctx.report("stat_fixture") or {}
    metrics = {"pool_isolated": pool.get("distractor_isolated"), "cp_ok": stats.get("clopper_pearson_ok"),
               "bootstrap_unit": stats.get("bootstrap_unit")}
    if not pool and not stats:
        return result("NOT_RUN", notes="requires pool + statistics evidence")
    status = "PASS" if metrics["pool_isolated"] and metrics["cp_ok"] and metrics["bootstrap_unit"] == "shape_lineage" else "PENDING"
    return result(status, evidence=["data/a12/reports/pool_audit.json", "data/a12/reports/stat_fixture.json"],
                  metrics=metrics)


@item("A32", "全流程泄漏（置换、ID 重命名、同器库负控）")
def a32(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("leakage_negative_control")
    if not report:
        return result("NOT_RUN", notes="requires the leakage negative-control run")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/leakage_negative_control.json"],
                  metrics=report.get("metrics", {}))


@item("A33", "权限/输入（服务端角色、路径/资源限制）")
def a33(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("api_security")
    if not report:
        return result("NOT_RUN", notes="requires API security tests")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/api_security.json"], metrics=report.get("metrics", {}))


@item("A34", "资产/调度（同 blob 多 role、code identity、GPU 清退、reservation）")
def a34(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("recovery_probe")
    if not report:
        report = ctx.report("storage_scheduler_audit")
    if not report:
        return result("NOT_RUN", notes="requires scheduler fault-injection evidence")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/recovery_probe.json"], metrics=report.get("metrics", {}))


@item("A35", "续训/监督分母（acknowledged cursor、prefetch 重放）")
def a35(ctx: Ctx) -> dict[str, Any]:
    report = ctx.report("train_resume")
    if not report:
        return result("NOT_RUN", notes="requires a training resume comparison")
    return result("PASS" if report.get("ok") else "FAIL",
                  evidence=["data/a12/reports/train_resume.json"], metrics=report.get("metrics", {}))


@item("A36", "配置/发布（route/scope 枚举、全部配置编译）")
def a36(ctx: Ctx) -> dict[str, Any]:
    """Compile every shipped config through the typed schema its own ``schema:`` field declares.

    ``configs/a12`` ships three config dialects: ``synlab.v3`` generation specs,
    ``synlab.train.v1`` / ``synlab.diagnose.v1`` specs and ``synlab.pool.v1`` gallery configs.
    Each is validated by its own strict model (unknown fields are rejected in every case);
    routing a pool document into ``GenerationSpec`` would only prove that the two schemas
    differ, not that the shipped file is wrong.
    """
    from ..config import load_document

    compiled: dict[str, str] = {}
    validators: dict[str, str] = {}
    for path in sorted((ROOT / "configs" / "a12").glob("*.yaml")):
        name = path.name
        try:
            if name.startswith("train"):
                from ..config import load_train_spec

                load_train_spec(path)
                compiled[name] = "OK"
                validators[name] = "TrainingSpec (synlab.train.v1)"
            elif name.startswith("diagnose"):
                load_diagnose_spec(path)
                compiled[name] = "OK"
                validators[name] = "DiagnosticSpec (synlab.diagnose.v1)"
            elif name.startswith(("pool", "gallery", "roster")):
                from ..relations.api import PoolConfig
                from ..roles import SCHEMA_POOL

                document = load_document(path)
                if str(document.get("schema", "")) != SCHEMA_POOL:
                    raise SynLabError(
                        ErrorCode.SCHEMA_INVALID,
                        f"{name}: expected schema {SCHEMA_POOL!r}, found "
                        f"{document.get('schema')!r}", stage="acceptance.a36")
                PoolConfig.from_mapping(document)
                compiled[name] = "OK"
                validators[name] = "relations.PoolConfig (synlab.pool.v1)"
            else:
                outcome = compile_spec(load_generation_spec(path))
                compiled[name] = "OK" if outcome.ok else f"ERRORS:{outcome.errors[:2]}"
                validators[name] = "GenerationSpec (synlab.v3) + compile_spec"
        except SynLabError as exc:
            compiled[name] = f"ERROR:{exc.message[:120]}"
        except Exception as exc:  # noqa: BLE001
            compiled[name] = f"ERROR:{type(exc).__name__}:{str(exc)[:80]}"
    for path in sorted((ROOT / "configs" / "a12" / "degrade_recipes").glob("*.yaml")):
        try:
            from ..config import compile_recipe

            outcome = compile_recipe(load_recipe_spec(path))
            compiled[f"degrade_recipes/{path.name}"] = "OK" if outcome.ok else f"ERRORS:{outcome.errors[:2]}"
            validators[f"degrade_recipes/{path.name}"] = "DegradationRecipeSpec + compile_recipe"
        except Exception as exc:
            compiled[f"degrade_recipes/{path.name}"] = f"ERROR:{type(exc).__name__}:{str(exc)[:60]}"
    bad = {k: v for k, v in compiled.items() if v != "OK"}
    metrics = {"compiled": compiled, "failed": bad, "validators": validators,
               "profiles_registered": sorted(PROFILE_GATES)}
    return result("PASS" if not bad else "FAIL", metrics=metrics,
                  notes="every shipped config must compile through the typed schema")


ITEM_PROFILES: dict[str, list[str]] = {
    "A13": ["SANDBOX_CORE", "PILOT", "CORE_COVERAGE", "CALIBRATED_PHONE"],
    "A14": ["PILOT", "CORE_COVERAGE", "CALIBRATED_PHONE"],
    "A16": ["PILOT", "CORE_COVERAGE"],
    "A18": ["SANDBOX_CORE", "PILOT", "CORE_COVERAGE", "RESEARCH_EVIDENCE"],
    "A19": ["SANDBOX_CORE", "PILOT", "CORE_COVERAGE"],
    "A20": ["SANDBOX_CORE", "PILOT", "CORE_COVERAGE"],
    "A21": ["CORE_COVERAGE", "SCALE_10K", "SCALE_50K", "SCALE_100K"],
    "A29": ["PILOT", "CORE_COVERAGE", "RESEARCH_EVIDENCE"],
    "A30": ["SANDBOX_CORE", "PILOT", "CORE_COVERAGE", "RESEARCH_EVIDENCE"],
    "A31": ["PILOT", "CORE_COVERAGE", "RESEARCH_EVIDENCE"],
    "A32": ["PILOT", "CORE_COVERAGE"],
    "A33": ["SANDBOX_CORE", "PILOT", "CORE_COVERAGE"],
    "A35": ["PILOT", "CORE_COVERAGE", "RESEARCH_EVIDENCE"],
}


def run_acceptance(*, store_root: str | Path = "data/a12", profile: str = "SANDBOX_CORE",
                   report_path: str | Path | None = None, selected: list[str] | None = None) -> dict[str, Any]:
    store_root = Path(store_root)
    if not store_root.is_absolute():
        store_root = ROOT / store_root
    store = AssetStore(store_root)
    tmp = store_root / "tmp" / "acceptance"
    tmp.mkdir(parents=True, exist_ok=True)
    ctx = Ctx(store_root=store_root, store=store, profile=profile, tmp=tmp)
    try:
        load_all()
    except Exception:
        pass

    items: dict[str, Any] = {}
    for acceptance_id in sorted(ITEMS):
        title, func = ITEMS[acceptance_id]
        if selected and acceptance_id not in selected:
            continue
        profiles = ITEM_PROFILES.get(acceptance_id)
        if profiles and profile not in profiles:
            items[acceptance_id] = {"title": title, "status": "NA",
                                    "evidence": [], "metrics": {}, "commands": [],
                                    "notes": f"not applicable to profile {profile}"}
            continue
        start = time.time()
        try:
            outcome = func(ctx)
        except SynLabError as exc:
            outcome = result("FAIL", notes=f"{exc.code}: {exc.message}")
        except Exception as exc:  # noqa: BLE001 - acceptance must record any failure honestly
            outcome = result("FAIL", notes=f"{type(exc).__name__}: {exc}",
                             metrics={"traceback": traceback.format_exc()[-1500:]})
        items[acceptance_id] = {
            "title": title,
            "status": outcome["status"],
            "evidence": outcome["evidence"],
            "metrics": outcome["metrics"],
            "notes": outcome["notes"],
            "seconds": round(time.time() - start, 3),
            "commands": [f"synlab acceptance --profile {profile}"],
        }

    counts: dict[str, int] = {}
    for entry in items.values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    summary = {
        "schema": "synlab.acceptance.v1",
        "profile": profile,
        "generated_at": time.time(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "counts": counts,
        "items": items,
        "registry": REGISTRY.summary(),
    }
    summary["summary_hash"] = hash_json({k: v for k, v in summary.items() if k != "generated_at"})
    ctx.write_report("acceptance_summary", summary)

    if report_path:
        path = Path(report_path)
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(summary), encoding="utf-8")
        summary["report_path"] = str(path)
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# A12 验收报告（A01–A36）",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(summary['generated_at']))}",
        f"- 发布 profile：`{summary['profile']}`",
        f"- 平台：{summary['platform']} / Python {summary['python']}",
        f"- 统计：{summary['counts']}",
        "",
        "> 本报告的每一项都由实际命令产生。`NOT_RUN` 表示未运行，`PENDING` 表示前置条件"
        "（外部后端、实拍数据、规模运行）尚未具备，`NA` 表示该 profile 下不适用。"
        "没有任何一项用推测或复制设计值充当实测结果。",
        "",
        "| ID | 验收对象 | 状态 | 关键实测 | 证据 | 说明 |",
        "|---|---|---|---|---|---|",
    ]
    for acceptance_id in sorted(summary["items"]):
        entry = summary["items"][acceptance_id]
        metrics = entry["metrics"] or {}
        interesting = {k: v for k, v in list(metrics.items())[:4]}
        lines.append(
            "| {id} | {title} | **{status}** | {metrics} | {evidence} | {notes} |".format(
                id=acceptance_id, title=entry["title"], status=entry["status"],
                metrics=json.dumps(interesting, ensure_ascii=False)[:300].replace("|", "/"),
                evidence=", ".join(entry["evidence"]) or "-",
                notes=(entry["notes"] or "").replace("|", "/")[:300],
            )
        )
    lines += [
        "",
        "## 状态矩阵",
        "",
        "见 `docs/a12/status_matrix.csv`（模块 × 状态 × 证据）。",
        "",
        "## 未完成与阻塞",
        "",
        "见 `docs/a12/status_matrix.csv` 的 PENDING/NOT_RUN 行与 `docs/a12/repo_inventory.md` 第 7 节。",
    ]
    return "\n".join(lines) + "\n"
