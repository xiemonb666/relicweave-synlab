"""partB_contract -- READ-ONLY static extraction of the code-side contract.

* every SCHEMA_*/ROLE_*/UNIT_*/FRAME_* constant in synlab/roles.py (name, value, file:line)
* every dataclass in synlab/schemas/runtime.py (name, file:line, field names + file:line)
* every commit call site (commit_asset / commit_source / commit_truth / commit_mother /
  commit_material / commit_pattern / commit_observation) with its literal kwargs and file:line
* repo-wide usage lines for each roles.py constant name
* every schema-id string literal in the repo (*.py), with file:line
* every role=<string literal> occurrence, with file:line

Writes partB_contract.txt / partB_contract.json in this directory.  Reads only.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
ROLES = REPO / "synlab" / "roles.py"
RUNTIME = REPO / "synlab" / "schemas" / "runtime.py"

OUT_TXT = HERE / "partB_contract.txt"
OUT_JSON = HERE / "partB_contract.json"

COMMIT_FUNCS = {
    "commit_asset", "commit_source", "commit_truth", "commit_mother", "commit_material",
    "commit_pattern", "commit_observation", "commit_cutter", "commit_fracture", "commit_pool",
    "commit_roster", "commit_physical", "commit_physical_result", "commit_diagnostic_report",
    # ``synlab/api/handlers.py:90`` defines ``JobContext.commit(**kwargs)`` which forwards to
    # ``AssetStore.commit_asset``; its call sites (handlers.py:142/403/481/577) carry role= and
    # would otherwise be invisible to a commit-site scan.
    "commit",
}

SCHEMA_LITERAL = re.compile(r"[\"']((?:synlab|a12)\.[A-Za-z0-9_.]*\.v[0-9]+)[\"']")
ROLE_LITERAL = re.compile(r"role\s*=\s*[\"']([a-z][a-z0-9_]*)[\"']")

SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules", "third_party",
             "relicweave_synlab.egg-info", ".shots"}

#: directories that make up the *live* code tree.  Everything under ``data/`` is either a
#: frozen snapshot (``data/a12/reports/baseline_head/``) or a probe script, so it is counted
#: separately instead of being mixed into "the code references this constant".
LIVE_PREFIXES = ("synlab/", "tests/", "tools/", "blender_scripts/", "configs/", "frontend/")


def py_files() -> list[Path]:
    out = []
    for path in REPO.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return sorted(out)


def is_live(where: str) -> bool:
    """True for the live tree, False for a snapshot / probe copy under data/ or the repo root."""
    if where.startswith(LIVE_PREFIXES):
        return True
    return False


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def parse_module_constants(path: Path) -> "OrderedDict[str, dict]":
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: "OrderedDict[str, dict]" = OrderedDict()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value_node = node.value
        else:
            continue
        for name in targets:
            if not name.startswith(("SCHEMA_", "ROLE_", "UNIT_", "FRAME_")):
                continue
            try:
                value = ast.literal_eval(value_node) if value_node is not None else None
            except Exception:  # noqa: BLE001
                value = None
            out[name] = {"value": value, "file": rel(path), "line": node.lineno}
    return out


def parse_dataclasses(path: Path) -> "OrderedDict[str, dict]":
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: "OrderedDict[str, dict]" = OrderedDict()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any((isinstance(d, ast.Name) and d.id == "dataclass")
                   or (isinstance(d, ast.Attribute) and d.attr == "dataclass")
                   for d in node.decorator_list):
            continue
        fields = []
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                fields.append({"name": stmt.target.id, "line": stmt.lineno,
                               "annotation": ast.unparse(stmt.annotation)})
        out[node.name] = {"file": rel(path), "line": node.lineno, "fields": fields}
    return out


def scan_commit_calls(files: list[Path]) -> list[dict]:
    calls: list[dict] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name not in COMMIT_FUNCS:
                continue
            kwargs = OrderedDict()
            for kw in node.keywords:
                if kw.arg is None:
                    continue
                kwargs[kw.arg] = ast.unparse(kw.value)
            if "role" not in kwargs:
                continue
            calls.append({"file": rel(path), "line": node.lineno, "func": name, "kwargs": kwargs})
    calls.sort(key=lambda c: (c["file"], c["line"]))
    return calls


def main() -> int:
    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)

    constants = parse_module_constants(ROLES)
    dataclasses_ = parse_dataclasses(RUNTIME)
    files = py_files()

    # ------------------------------------------------------------------ roles.py
    emit("=" * 100)
    emit(f"synlab/roles.py constants   file={rel(ROLES)}  ({len(constants)} constants)")
    emit("=" * 100)
    by_kind: dict[str, list[str]] = defaultdict(list)
    for name, info in constants.items():
        kind = name.split("_", 1)[0]
        by_kind[kind].append(name)
    for kind in ("SCHEMA", "ROLE", "UNIT", "FRAME"):
        emit(f"\n--- {kind} ({len(by_kind[kind])}) ---")
        for name in by_kind[kind]:
            info = constants[name]
            emit(f"  {info['file']}:{info['line']:<4} {name:<28} = {info['value']!r}")

    # ------------------------------------------------------------------ usage scan
    usage: dict[str, list[str]] = {name: [] for name in constants}
    schema_literals: list[dict] = []
    role_literals: list[dict] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for index, line in enumerate(text.splitlines(), start=1):
            for name in constants:
                if re.search(rf"\b{name}\b", line):
                    usage[name].append(f"{rel(path)}:{index}")
            for match in SCHEMA_LITERAL.finditer(line):
                schema_literals.append({"schema": match.group(1), "file": rel(path), "line": index})
            for match in ROLE_LITERAL.finditer(line):
                role_literals.append({"role": match.group(1), "file": rel(path), "line": index})

    emit("\n" + "=" * 100)
    emit("USAGE of each roles.py constant in the LIVE tree (synlab/ tests/ tools/ blender_scripts/ "
         "configs/ frontend/)")
    emit("0 live uses = declared but referenced nowhere in the live code")
    emit("=" * 100)
    live_usage: dict[str, list[str]] = {}
    for name, info in constants.items():
        outside = [u for u in usage[name]
                   if not u.startswith("synlab/roles.py:") and is_live(u)]
        live_usage[name] = outside
        if outside:
            emit(f"  {name:<28} {len(outside)} live use(s): " + ", ".join(outside[:8])
                 + (" ..." if len(outside) > 8 else ""))
        else:
            emit(f"  {name:<28} 0 live uses  <-- DECLARED BUT UNUSED IN THE LIVE TREE")

    # ------------------------------------------------------------------ runtime dataclasses
    emit("\n" + "=" * 100)
    emit(f"synlab/schemas/runtime.py dataclasses  file={rel(RUNTIME)}  ({len(dataclasses_)})")
    emit("=" * 100)
    for name, info in dataclasses_.items():
        emit(f"\n  {info['file']}:{info['line']:<4} @dataclass {name}  ({len(info['fields'])} fields)")
        for f in info["fields"]:
            emit(f"        {info['file']}:{f['line']:<4} {f['name']}: {f['annotation']}")

    # ------------------------------------------------------------------ commit call sites
    calls = scan_commit_calls(files)
    live_calls = [c for c in calls if is_live(c["file"])]
    emit("\n" + "=" * 100)
    emit(f"COMMIT CALL SITES carrying role=   LIVE TREE: {len(live_calls)} calls "
         f"(all paths incl. snapshots: {len(calls)})")
    emit("=" * 100)
    for call in live_calls:
        emit(f"\n  {call['file']}:{call['line']}  {call['func']}(")
        for key in ("role", "schema", "unit", "frame"):
            if key in call["kwargs"]:
                emit(f"        {key} = {call['kwargs'][key]}")
        extra = [k for k in call["kwargs"] if k not in ("role", "schema", "unit", "frame")]
        if extra:
            emit(f"        other kwargs: {', '.join(extra)}")

    # ------------------------------------------------------------------ schema literals
    emit("\n" + "=" * 100)
    emit(f"SCHEMA-ID STRING LITERALS in the repo ({len(schema_literals)} occurrences)")
    emit("=" * 100)
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in schema_literals:
        grouped[item["schema"]].append(f"{item['file']}:{item['line']}")
    for schema in sorted(grouped):
        emit(f"\n  {schema!r}  ({len(grouped[schema])} occurrence(s))")
        for where in grouped[schema][:14]:
            emit(f"        {where}")
        if len(grouped[schema]) > 14:
            emit(f"        ... {len(grouped[schema]) - 14} more")

    declared_schemas = {info["value"] for name, info in constants.items() if name.startswith("SCHEMA_")}
    literal_schemas = set(grouped)
    emit(f"\n  schemas declared in roles.py            : {len(declared_schemas)}")
    emit(f"  schemas seen as string literals         : {len(literal_schemas)}")
    emit(f"  literal-only (NOT declared in roles.py) : {sorted(literal_schemas - declared_schemas)}")
    emit(f"  declared-only (never a string literal)  : {sorted(declared_schemas - literal_schemas)}")

    # ------------------------------------------------------------------ role literals
    emit("\n" + "=" * 100)
    emit(f"role=<string literal> occurrences ({len(role_literals)})")
    emit("=" * 100)
    rgroup: dict[str, list[str]] = defaultdict(list)
    for item in role_literals:
        rgroup[item["role"]].append(f"{item['file']}:{item['line']}")
    for role in sorted(rgroup):
        emit(f"  {role:<24} {len(rgroup[role])}: " + ", ".join(rgroup[role][:6]))

    declared_roles = {info["value"] for name, info in constants.items() if name.startswith("ROLE_")}
    emit(f"\n  roles declared in roles.py      : {len(declared_roles)}")
    emit(f"  roles seen as string literals   : {len(rgroup)}")
    emit(f"  literal-only (not in roles.py)  : {sorted(set(rgroup) - declared_roles)}")
    emit(f"  declared-only (no literal form) : {sorted(declared_roles - set(rgroup))}")

    payload = {
        "roles_py_constants": constants,
        "runtime_dataclasses": dataclasses_,
        "commit_calls": calls,
        "constant_usage": usage,
        "constant_usage_live": live_usage,
        "schema_literals": schema_literals,
        "role_literals": role_literals,
        "declared_schemas": sorted(declared_schemas),
        "literal_schemas": sorted(literal_schemas),
        "declared_roles": sorted(declared_roles),
        "commit_calls_live": [c for c in calls if is_live(c["file"])],
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_TXT} ({OUT_TXT.stat().st_size} bytes)")
    print(f"wrote {OUT_JSON} ({OUT_JSON.stat().st_size} bytes)")
    print(f"constants={len(constants)} dataclasses={len(dataclasses_)} commit_calls={len(calls)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
