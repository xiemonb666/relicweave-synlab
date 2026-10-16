"""Write the before -> after comparison table for the diversity report.

Reads the two machine-readable snapshots and emits:

* ``data/a12/reports/diversity_before_after.json`` -- the machine-readable comparison;
* the markdown table printed to stdout, which ``docs/a12/diversity_report.md`` embeds.

Every row names its **denominator** and the direction that counts as an improvement, so the table
cannot be read as "bigger is better" without saying so.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS = REPO_ROOT / "data" / "a12" / "reports"
BEFORE = REPORTS / "diversity_before.json"
AFTER = REPORTS / "diversity_after.json"
OUT = REPORTS / "diversity_before_after.json"


def _get(report: dict[str, Any], path: str, default: Any = None) -> Any:
    node: Any = report
    for key in path.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        elif isinstance(node, list) and key.isdigit() and int(key) < len(node):
            node = node[int(key)]
        else:
            return default
    return node


#: ``(row label, before path, after path, direction, unit, denominator)``.  ``direction`` is what
#: counts as the improvement, so a reader never has to guess.
ROWS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("谱系数 / lineages", "lineages", "lineages", "context", "count", "磁盘上全部谱系"),
    ("碎片段 / fragments", "fragments", "fragments", "context", "count", "全部 fragment_mesh"),
    ("(vessel,material,pattern,layer) 组合数",
     "planning_layer.distinct_vessel_material_pattern_layer_combos",
     "planning_layer.distinct_vessel_material_pattern_layer_combos", "context", "count",
     "谱系数"),
    ("事件切面法向集合大小",
     "event_layer.normal_set_size_distinct_2dp",
     "event_layer.normal_set_size_distinct_2dp", "up", "count", "有 clean_truth 的事件数"),
    ("事件切面法向两两夹角·均值",
     "event_layer.normal_pairwise_spread_overall.mean_deg",
     "event_layer.normal_pairwise_spread_overall.mean_deg", "up", "deg", "全部法向对"),
    ("每谱系事件数·取值个数",
     "event_layer.events_per_lineage.distinct", "event_layer.events_per_lineage.distinct",
     "up", "count", "谱系数"),
    ("每谱系碎片数·取值个数",
     "event_layer.fragments_per_lineage.distinct", "event_layer.fragments_per_lineage.distinct",
     "up", "count", "谱系数"),
    ("断裂后端·种类数",
     "event_layer.backend", "event_layer.backend", "up", "count", "事件数"),
    ("切面偏移·取值个数",
     "event_layer.offset_distinct_4dp", "event_layer.offset_distinct_4dp", "up", "count",
     "事件数"),
    ("母体参数·被抽到的键数",
     "parameter_layer.param_keys_seen", "parameter_layer.param_keys_seen", "context", "count",
     "谱系 x 键"),
    ("花纹配色·取值个数",
     "material_pattern_layer.pattern_palette", "material_pattern_layer.pattern_palette", "up",
     "count", "有 pattern_recipe 的谱系"),
    ("花纹配方 hash·唯一数",
     "material_pattern_layer.pattern_recipe_hash.distinct_recipe_hashes",
     "material_pattern_layer.pattern_recipe_hash.distinct_recipe_hashes", "up", "count",
     "有 pattern_recipe 的谱系"),
    ("相机档位·取值数",
     "observation_layer.profile_id", "observation_layer.profile_id", "up", "count",
     "全部观测"),
    ("工作距离·取值数",
     "observation_layer.working_distance_distinct",
     "observation_layer.working_distance_distinct", "up", "count", "全部观测"),
    ("灯态·取值数",
     "observation_layer.light_mode", "observation_layer.light_mode", "up", "count", "全部观测"),
    ("视图数·取值数",
     "observation_layer.views_per_observation.distinct",
     "observation_layer.views_per_observation.distinct", "up", "count", "全部观测"),
    ("交付分辨率·取值数",
     "observation_layer.image_size.distinct", "observation_layer.image_size.distinct", "up",
     "count", "全部观测"),
    ("方位角落在 4 方位基准网格上的比例",
     "observation_layer.azimuth_on_canonical_grid.on_grid_fraction",
     "observation_layer.azimuth_on_canonical_grid.on_grid_fraction", "context", "fraction",
     "全部视图"),
    ("曝光 EV·取值个数",
     "observation_layer.imaging.exposure_ev.distinct_rounded_4",
     "observation_layer.imaging.exposure_ev.distinct_rounded_4", "up", "count", "全部观测"),
    ("离焦 PSF sigma·取值个数",
     "observation_layer.imaging.defocus_sigma_px.distinct_rounded_4",
     "observation_layer.imaging.defocus_sigma_px.distinct_rounded_4", "up", "count", "全部观测"),
    ("读出噪声 sigma·取值个数",
     "observation_layer.imaging.read_noise_sigma.distinct_rounded_4",
     "observation_layer.imaging.read_noise_sigma.distinct_rounded_4", "up", "count", "全部观测"),
    ("退化轴子集·不同组合数",
     "degradation_layer.distinct_axis_subsets",
     "degradation_layer.distinct_axis_subsets", "up", "count", "有退化变体的谱系"),
    ("退化 轴x档 组合数",
     "degradation_layer.distinct_axis_level_combos",
     "degradation_layer.distinct_axis_level_combos", "up", "count", "有退化变体的谱系"),
    ("资产级重复：fragment_mesh 同 role 同 blob 的占比",
     "repetition_layer.assets.per_role(fragment_mesh).duplicate_asset_fraction",
     "repetition_layer.assets.per_role(fragment_mesh).duplicate_asset_fraction", "down",
     "fraction", "fragment_mesh 资产数"),
    ("几何级最近对：碎片体积相似度",
     "repetition_layer.geometry.closest_volume_pair.similarity",
     "repetition_layer.geometry.closest_volume_pair.similarity", "down", "similarity",
     "全部碎片对"),
    ("图像级最近对：描述子相似度",
     "repetition_layer.imagery.closest_pair.similarity",
     "repetition_layer.imagery.closest_pair.similarity", "down", "similarity", "抽样图像对"),
    ("关系级最近对：共享面积相似度",
     "repetition_layer.relations.closest_shared_area_pair.similarity",
     "repetition_layer.relations.closest_shared_area_pair.similarity", "down", "similarity",
     "R2 共享面积对"),
)


def _resolve(report: dict[str, Any], path: str) -> Any:
    """Resolve a row path, including the ``per_role(role).field`` pseudo-segment."""
    if "per_role(" in path:
        head, rest = path.split(".per_role(", 1)
        role, tail = rest.split(")", 1)
        rows = _get(report, head + ".per_role", []) or []
        for row in rows:
            if row.get("role") == role:
                node: Any = row
                for key in tail.lstrip(".").split("."):
                    if isinstance(node, dict) and key in node:
                        node = node[key]
                    else:
                        return None
                return node
        return None
    if path.endswith("}") or "{" in path:
        return None
    # mapping-valued rows collapse to their number of keys
    value = _get(report, path)
    if isinstance(value, dict):
        return len(value)
    if isinstance(value, list):
        return len(value)
    return value


def build(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for label, before_path, after_path, direction, unit, denominator in ROWS:
        b = _resolve(before, before_path)
        a = _resolve(after, after_path)
        delta = None
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta = a - b
        verdict = "context"
        if direction == "up" and isinstance(delta, (int, float)):
            verdict = "improved" if delta > 0 else ("unchanged" if delta == 0 else "regressed")
        elif direction == "down" and isinstance(delta, (int, float)):
            verdict = "improved" if delta < 0 else ("unchanged" if delta == 0 else "regressed")
        rows.append({"metric": label, "before": b, "after": a, "delta": delta, "unit": unit,
                     "direction_of_improvement": direction, "verdict": verdict,
                     "denominator": denominator,
                     "before_path": before_path, "after_path": after_path})
    return {
        "schema": "synlab.diversity_before_after.v1",
        "before": {"stores": before.get("stores_scanned"), "lineages": before.get("lineages"),
                   "fragments": before.get("fragments")},
        "after": {"stores": after.get("stores_scanned"), "lineages": after.get("lineages"),
                  "fragments": after.get("fragments")},
        "rows": rows,
        "improved": sum(1 for r in rows if r["verdict"] == "improved"),
        "unchanged": sum(1 for r in rows if r["verdict"] == "unchanged"),
        "regressed": sum(1 for r in rows if r["verdict"] == "regressed"),
    }


def markdown(comparison: dict[str, Any]) -> str:
    lines = ["| 指标 | before | after | Δ | 方向 | 判定 | 分母 |",
             "|---|---:|---:|---:|---|---|---|"]
    for row in comparison["rows"]:
        def fmt(value: Any) -> str:
            if value is None:
                return "—"
            if isinstance(value, float):
                return f"{value:.4g}"
            return str(value)
        lines.append(
            f"| {row['metric']} | {fmt(row['before'])} | {fmt(row['after'])} | "
            f"{fmt(row['delta'])} | {row['direction_of_improvement']} | {row['verdict']} | "
            f"{row['denominator']} |")
    return "\n".join(lines)


def main() -> int:
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    comparison = build(before, after)
    OUT.write_text(json.dumps(comparison, ensure_ascii=False, indent=1, default=str),
                   encoding="utf-8")
    print(markdown(comparison))
    print(f"\nimproved={comparison['improved']} unchanged={comparison['unchanged']} "
          f"regressed={comparison['regressed']}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
