"""Job stage registry: capability requirements, cost class and DAG expansion.

``POST /jobs`` is fail-closed: if any capability the requested stage needs is missing, the
API answers 503 ``DEPENDENCY_CAPABILITY_MISSING`` and creates **nothing**.  Stages that are
implemented by this API package itself (``freeze_spec``, ``audit``, ``export``,
``display_lod``) need no capability module and are always accepted — they produce real,
hash-verifiable content, never placeholder geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StageSpec:
    stage: str
    title: str
    capabilities: tuple[str, ...]
    #: env capabilities, reported as ENV_CAPABILITY_MISSING rather than a module gap
    env: tuple[str, ...] = ()
    requires_gpu: bool = False
    cost_class: str = "medium"
    estimate: dict[str, float] = field(default_factory=dict)
    description: str = ""
    implemented_by: str = "worker"

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage, "title": self.title, "capabilities": list(self.capabilities),
            "env": list(self.env), "requires_gpu": self.requires_gpu,
            "cost_class": self.cost_class, "estimate": self.estimate,
            "description": self.description, "implemented_by": self.implemented_by,
        }


def _est(rss: float, temp: float, cpu: float, *, vram: float = 0.0) -> dict[str, float]:
    return {"rss_gb": rss, "temp_disk_gb": temp, "cpu_seconds": cpu, "vram_gb": vram,
            "persistent_disk_gb": 0.0}


STAGES: dict[str, StageSpec] = {
    spec.stage: spec
    for spec in (
        StageSpec(
            stage="freeze_spec", title="冻结输入合同",
            capabilities=(), env=(), cost_class="light",
            estimate=_est(0.3, 0.05, 2.0),
            description="校验 spec 与输入资产 hash，提交不可变的 run_spec 资产；不产生几何。",
            implemented_by="synlab.api",
        ),
        StageSpec(
            stage="audit", title="审计（覆盖/闭包/权限/门）",
            capabilities=(), env=(), cost_class="light",
            estimate=_est(0.6, 0.05, 5.0),
            description="真实闭包与 hash 校验、覆盖矩阵与 profile gate 评估；缺能力的门记 PENDING。",
            implemented_by="synlab.api",
        ),
        StageSpec(
            stage="export", title="导出（manifest / obs pack）",
            capabilities=(), env=(), cost_class="light",
            estimate=_est(0.5, 0.5, 10.0),
            description="从已冻结 release 生成只读导出包并记录 manifest hash。",
            implemented_by="synlab.api",
        ),
        StageSpec(
            stage="display_lod", title="派生展示 GLB（L0/L1/L2）",
            capabilities=(), env=("trimesh",), cost_class="light",
            estimate=_est(1.0, 0.3, 8.0),
            description="从权威 mesh 资产派生米制/Y-up 的展示 GLB；只改展示，不回写权威资产。",
            implemented_by="synlab.api",
        ),
        StageSpec(stage="mother", title="母体生成", capabilities=("mothers",),
                  estimate=_est(2.5, 0.5, 60.0), description="create_mother + audit_mother。"),
        StageSpec(stage="material", title="材料剖面", capabilities=("materials",),
                  estimate=_est(1.5, 0.2, 30.0)),
        StageSpec(stage="pattern", title="纹样生成与几何化", capabilities=("patterns", "mothers"),
                  estimate=_est(3.0, 0.8, 120.0)),
        StageSpec(stage="fracture", title="断裂事件", capabilities=("fracture", "mothers"),
                  estimate=_est(4.0, 1.5, 240.0)),
        StageSpec(stage="physical", title="物理损伤", capabilities=("physical", "truth"),
                  estimate=_est(3.0, 1.0, 180.0)),
        StageSpec(stage="truth", title="三层真值", capabilities=("truth",),
                  estimate=_est(1.5, 0.3, 40.0)),
        StageSpec(stage="degrade", title="退化轴应用", capabilities=("degrade",),
                  estimate=_est(3.0, 1.2, 150.0)),
        StageSpec(stage="observe", title="观测渲染/重建", capabilities=("observe", "cameras"),
                  estimate=_est(6.0, 3.0, 600.0)),
        StageSpec(stage="pool", title="关系池构建", capabilities=("relations",),
                  estimate=_est(4.0, 2.0, 300.0)),
        StageSpec(stage="training", title="预训练", capabilities=("training",),
                  requires_gpu=True, cost_class="heavy",
                  estimate=_est(12.0, 8.0, 7200.0, vram=8.0)),
        StageSpec(stage="diagnostics", title="诊断评测", capabilities=("diagnostics", "training"),
                  requires_gpu=True, cost_class="heavy",
                  estimate=_est(8.0, 4.0, 1800.0, vram=4.0)),
        StageSpec(stage="episode", title="主动观察 episode", capabilities=("episodes", "relations"),
                  estimate=_est(4.0, 1.0, 300.0)),
        StageSpec(stage="generate", title="批量生成（完整 DAG）",
                  capabilities=("mothers", "materials", "patterns", "fracture", "degrade", "observe"),
                  cost_class="heavy", estimate=_est(16.0, 12.0, 7200.0),
                  description="按 target_mothers 展开真实 DAG；任一能力缺失则整体拒绝，不创建半成品 run。"),
    )
}

#: stage order used to expand ``generate`` into a dependency DAG
PIPELINE_STAGES: tuple[str, ...] = ("mother", "pattern", "fracture", "degrade", "observe")


def stage_spec(stage: str) -> StageSpec:
    if stage not in STAGES:
        from .problems import API_CODE_BAD_REQUEST, ApiProblem

        raise ApiProblem(422, API_CODE_BAD_REQUEST,
                         f"unknown stage {stage!r}; known stages: {sorted(STAGES)}",
                         stage="stages.resolve")
    return STAGES[stage]


def required_capabilities(stage: str) -> tuple[str, ...]:
    """Capability closure for a stage (``generate`` unions its whole pipeline)."""
    spec = stage_spec(stage)
    if stage != "generate":
        return spec.capabilities
    seen: list[str] = []
    for sub in PIPELINE_STAGES:
        for cap in STAGES[sub].capabilities:
            if cap not in seen:
                seen.append(cap)
    return tuple(seen)


def required_env(stage: str) -> tuple[str, ...]:
    return stage_spec(stage).env


def plan_generate(spec: dict[str, Any], *, max_mothers: int = 4) -> list[dict[str, Any]]:
    """Expand a ``generate`` request into an explicit dependency DAG description."""
    dataset = spec.get("dataset", {}) if isinstance(spec, dict) else {}
    target = int(dataset.get("target_mothers", 1) or 1)
    chains = max(1, min(target, max_mothers))
    nodes: list[dict[str, Any]] = []
    for chain in range(chains):
        previous: str | None = None
        for stage in PIPELINE_STAGES:
            node_id = f"m{chain:02d}_{stage}"
            nodes.append({
                "node_id": node_id, "stage": stage, "chain": chain,
                "depends_on": [previous] if previous else [],
                "cost_class": STAGES[stage].cost_class,
            })
            previous = node_id
    nodes.append({
        "node_id": "run_audit", "stage": "audit", "chain": -1,
        "depends_on": [n["node_id"] for n in nodes if n["stage"] == "observe"],
        "cost_class": STAGES["audit"].cost_class,
    })
    return nodes


def stage_catalog() -> list[dict[str, Any]]:
    return [STAGES[key].as_dict() for key in sorted(STAGES)]
