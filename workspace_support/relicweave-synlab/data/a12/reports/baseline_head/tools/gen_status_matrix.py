"""Generate docs/a12/algorithm_registry.md and docs/a12/status_matrix.csv from real state.

Usage:
    python tools/gen_status_matrix.py [--data-root data/a12]

The registry comes from the live capability registry (code), the acceptance status from
the acceptance harness summary, and the reuse status from the reuse manifest.  Nothing is
hand-written, so the shipped documents always match the code that produced them.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_registry() -> dict:
    from synlab.registry import REGISTRY, load_all

    load_all()
    return {f"{e.kind}/{e.id}": e.as_dict() for e in REGISTRY.list()}


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_algorithm_registry(registry: dict, reuse: dict | None, out: Path) -> None:
    kinds = {
        "vessel": "器型（24 品种）",
        "material": "材料族（12）",
        "layer_combo": "层结构组合（4）",
        "pattern": "纹样族（16）",
        "fracture_backend": "断裂后端（4 必做 + 1 选配）",
        "axis": "退化轴（31）",
    }
    lines = [
        "# docs/a12/algorithm_registry.md — 能力注册表（自动生成）",
        "",
        "> 本文件由 `tools/gen_status_matrix.py` 从代码内注册表、复用清单与验收结果生成，"
        "不要手工编辑。状态只反映实际实现的证据。",
        "",
        "## 1. 状态汇总",
        "",
        "| kind | count | by status |",
        "|---|---|---|",
    ]
    for kind in kinds:
        entries = [e for k, e in registry.items() if e["kind"] == kind]
        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        lines.append(f"| {kind} | {len(entries)} | {counts} |")
    lines += ["", "## 2. 逐项注册表", ""]
    for kind, title in kinds.items():
        entries = sorted((e for e in registry.values() if e["kind"] == kind), key=lambda e: e["id"])
        if not entries:
            continue
        lines += [f"### {title}", "", "| ID | 名称 | 版本 | 状态 | 模块 | 适用/备注 |", "|---|---|---|---|---|---|"]
        for entry in entries:
            applicable = entry.get("applicable") or {}
            note = entry.get("notes") or ""
            detail = "; ".join(f"{k}={v}" for k, v in list(applicable.items())[:3])
            detail = (detail + (" | " if detail and note else "") + note)[:180].replace("|", "/")
            lines.append(f"| {entry['id']} | {entry['name']} | {entry['version']} | {entry['status']} | "
                         f"`{entry['module']}` | {detail} |")
        lines.append("")
    if reuse:
        lines += ["## 3. 复用与自编缺口", "", "| module | selected dependency | version | mode |", "|---|---|---|---|"]
        for entry in reuse.get("modules", []):
            lines.append(f"| {entry.get('module')} | {entry.get('selected_dependency') or '-'} | "
                         f"{entry.get('version_or_commit') or '-'} | {entry.get('mode')} |")
        lines += ["", "### CUSTOM_GAP 明细", ""]
        for gap in reuse.get("custom_gaps", []):
            lines.append(f"- **{gap.get('module')}**: {gap.get('gap')} — 证据：{gap.get('evidence')}")
        lines.append("")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_status_matrix(registry: dict, acceptance: dict | None, reuse: dict | None, out: Path) -> None:
    rows: list[dict[str, str]] = []
    for entry in sorted(registry.values(), key=lambda e: (e["kind"], e["id"])):
        rows.append({
            "area": "capability",
            "kind": entry["kind"],
            "item": entry["id"],
            "name": entry["name"],
            "status": entry["status"],
            "evidence": entry["module"],
            "notes": (entry.get("notes") or "")[:200],
        })
    if acceptance:
        for acceptance_id, entry in sorted(acceptance.get("items", {}).items()):
            rows.append({
                "area": "acceptance",
                "kind": "A-item",
                "item": acceptance_id,
                "name": entry.get("title", ""),
                "status": entry.get("status", ""),
                "evidence": ", ".join(entry.get("evidence") or []) or "data/a12/reports",
                "notes": (entry.get("notes") or "")[:200],
            })
    if reuse:
        for entry in reuse.get("modules", []):
            rows.append({
                "area": "reuse",
                "kind": "module",
                "item": entry.get("module", ""),
                "name": entry.get("requirement", ""),
                "status": "IMPLEMENTED" if entry.get("selected_dependency") else "MISSING",
                "evidence": entry.get("poc_result_ref") or "",
                "notes": (entry.get("gap_reason") or "")[:200],
            })
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["area", "kind", "item", "name", "status", "evidence", "notes"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="data/a12")
    args = parser.parse_args()
    registry = load_registry()
    reuse = load_json(ROOT / "docs" / "a12" / "reuse_manifest.json")
    acceptance = load_json(Path(args.data_root) / "reports" / "acceptance_summary.json")
    docs = ROOT / "docs" / "a12"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "registry.json").write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True),
                                        encoding="utf-8")
    write_algorithm_registry(registry, reuse, docs / "algorithm_registry.md")
    write_status_matrix(registry, acceptance, reuse, docs / "status_matrix.csv")
    print(f"registry entries: {len(registry)}")
    print(f"acceptance items: {len((acceptance or {}).get('items', {}))}")
    print("wrote docs/a12/algorithm_registry.md, docs/a12/status_matrix.csv, docs/a12/registry.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
