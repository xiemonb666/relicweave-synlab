"""partB_table -- joins the three sources into the deliverable per-role contract table.

Sources
  1. sqlite   : data/a12/metadata.sqlite  (assets table, mode=ro&immutable=1)
  2. roles.py : synlab/roles.py           (schema / role / unit / frame constants)
  3. runtime  : synlab/schemas/runtime.py (dataclasses) + every commit call site in the live tree

Writes partB_table.md (the deliverable table + mismatch list), partB_table.txt (full detail) and
partB_table.json.  The script only reads; it never writes to the database.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
DB = REPO / "data" / "a12" / "metadata.sqlite"

LIVE_PREFIXES = ("synlab/", "tests/", "tools/", "blender_scripts/", "configs/", "frontend/")

# ---------------------------------------------------------------------------------------
# role -> runtime model.  ``name`` is the dataclass in synlab/schemas/runtime.py; ``evidence``
# is the site that proves the role is produced/consumed as that model.  ``None`` means the role
# has no runtime dataclass in runtime.py at all (a dict / array bag), and the closest existing
# substitute is named.
# ---------------------------------------------------------------------------------------
ROLE_MODEL: dict[str, tuple[str | None, str]] = {
    "fragment_mesh": ("Fragment", "fracture/api.py:310-331 commit_fracture serialises Fragment fields"),
    "mother_mesh": ("MotherGeometry", "mothers/api.py:743 isinstance(mother, MotherGeometry)"),
    "pattern_channels": ("PatternChannels", "patterns/commit.py:77 channels_payload(channels)"),
    "pattern_recipe": ("PatternRecipe", "patterns/commit.py:52 isinstance(recipe, PatternRecipe)"),
    "clean_truth": ("CleanTruth", "truth/api.py:1215 isinstance(obj, CleanTruth)"),
    "physical_component": ("PhysicalComponent", "physical/api.py:815 _component_meta(component, result)"),
    "material_profile": (None, "commit_material takes a Mapping profile (materials/api.py:466-483); "
                              "closest runtime type is MaterialSample (a per-point field sample, "
                              "not a profile)"),
    "obs_view": ("ObsView", "observe/routes.py:1236 _obs_views -> list[ObsView]"),
    "feature_bundle": (None, "meta+array bag assembled in pipeline._commit_features; no runtime dataclass"),
    "label_bundle": (None, "meta+array bag assembled in pipeline._commit_labels; no runtime dataclass"),
    "provenance": (None, "plain dict at pipeline._commit_provenance; no runtime dataclass"),
    "physical_truth": ("PhysicalTruth", "truth/api.py:1217 isinstance(obj, PhysicalTruth)"),
    "visible_labels": ("VisibleLabels", "truth/api.py:1219 isinstance(obj, VisibleLabels)"),
    "obs_result": ("ObservationResult", "observe/api.py:198-227 commit_observation + "
                                        "observe/routes.py:1923 observation_meta(obs)"),
    "obs_fused_geometry": (None, "degrade.api SourceBundle(KIND_GEOMETRY) payload, degrade/api.py:589-603; "
                                 "no runtime dataclass"),
    "physical_result": ("PhysicalResult", "physical/api.py:990-994 commit_physical_result consumes PhysicalResult"),
    "degrade_measurement": ("Measurement", "degrade/api.py:83 COMMIT_ROLES X -> Measurement rows "
                                           "(degrade/registry.py measurement_from)"),
    "qa_report": (None, "doctor.py:522-527 commits an ad-hoc probe dict; no runtime dataclass"),
    "relation_pool": (None, "RelationPool lives in synlab/relations/gallery.py:273, NOT in runtime.py; "
                            "closest runtime dataclass is GallerySpec (the meta['gallery'] sub-object)"),
    "query_roster": ("QueryRosterEntry", "relations/api.py:589 _roster_dict(entry) over QueryRosterEntry"),
}

# ---------------------------------------------------------------------------------------
# commit sites whose role/schema/unit/frame are not literal kwargs at the commit_asset call
# (resolved dynamically).  Each entry is (file, line, note) and is quoted verbatim in the table.
# ---------------------------------------------------------------------------------------
DYNAMIC_CONTRACT: dict[str, list[str]] = {
    "clean_truth": ["synlab/truth/api.py:1216 -> schema=SCHEMA_TRUTH_CLEAN",
                    "synlab/truth/api.py:1244 -> unit=UNIT_MM, frame=FRAME_WORLD"],
    "physical_truth": ["synlab/truth/api.py:1218 -> schema=SCHEMA_TRUTH_PHYSICAL",
                       "synlab/truth/api.py:1244 -> unit=UNIT_MM, frame=FRAME_WORLD"],
    "visible_labels": ["synlab/truth/api.py:1220 -> schema=SCHEMA_TRUTH_VISIBLE",
                       "synlab/truth/api.py:1244 -> unit=UNIT_MM, frame=FRAME_WORLD"],
    "obs_view": ["synlab/degrade/api.py:81 COMMIT_ROLES['I'] = (ROLE_OBS_VIEW, SCHEMA_OBS)",
                 "synlab/degrade/api.py:572 SourceBundle(unit='px', frame=meta['frame_id'])",
                 "synlab/degrade/sources.py:389-390 commit_source forwards source.unit/source.frame"],
    "obs_fused_geometry": ["synlab/degrade/api.py:82 COMMIT_ROLES['G'] = (ROLE_OBS_FUSED, SCHEMA_OBS)",
                           "synlab/degrade/api.py:602 SourceBundle(unit='mm', frame=meta['frame_id'])"],
    "degrade_measurement": ["synlab/degrade/api.py:83 COMMIT_ROLES['X'] = (ROLE_DEGRADE_MEASUREMENT, "
                            "SCHEMA_MEASUREMENT)",
                            "synlab/degrade/api.py:647 SourceBundle(unit='1', frame=meta['frame_id'])"],
    "obs_result": ["synlab/observe/api.py:214-216 schema=SCHEMA_OBS, "
                   "unit='mm' if obs.scale_valid else 'unknown', frame=obs.frame_id"],
    "qa_report": ["synlab/doctor.py:522 and :525 role='qa_report', schema='synlab.qa.v1', unit='1', "
                  "frame='none'"],
}


def connect(path: Path) -> sqlite3.Connection:
    uri = "file:" + str(path).replace("\\", "/") + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def is_live(where: str) -> bool:
    return where.startswith(LIVE_PREFIXES)


def main() -> int:
    census = json.loads((HERE / "partB_census.json").read_text(encoding="utf-8"))
    meta_keys = json.loads((HERE / "partB_meta_keys.json").read_text(encoding="utf-8"))
    contract = json.loads((HERE / "partB_contract.json").read_text(encoding="utf-8"))

    constants = contract["roles_py_constants"]
    by_value = {info["value"]: (name, info) for name, info in constants.items()}
    dataclasses_ = contract["runtime_dataclasses"]
    live_usage = contract["constant_usage_live"]

    #: role constants declared OUTSIDE roles.py (module-level ``ROLE_* = "..."`` in the live tree).
    #: ast-parsed from the live tree, so the count of "roles named in code" is not limited to
    #: roles.py.
    extra_role_constants: "OrderedDict[str, dict]" = OrderedDict()
    for path in sorted((REPO / "synlab").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel_path = str(path.relative_to(REPO)).replace("\\", "/")
        if rel_path == "synlab/roles.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            targets: list[str] = []
            value_node = None
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                value_node = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
                value_node = node.value
            for name in targets:
                if not name.startswith("ROLE_"):
                    continue
                try:
                    value = ast.literal_eval(value_node) if value_node is not None else None
                except Exception:  # noqa: BLE001
                    value = None
                if isinstance(value, str):
                    extra_role_constants[name] = {"value": value, "file": rel_path,
                                                  "line": node.lineno}
    all_role_constants = dict(constants)
    all_role_constants.update(extra_role_constants)

    per_role = census["per_role"]
    roles_sqlite = list(per_role.keys())

    con = connect(DB)
    cur = con.cursor()

    def rows(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        return list(cur.execute(sql, args))

    schema_rows = {r["schema"]: r["n"] for r in rows(
        "SELECT schema, COUNT(*) n FROM assets GROUP BY 1 ORDER BY n DESC")}
    role_rows = {r["role"]: r["n"] for r in rows(
        "SELECT role, COUNT(*) n FROM assets GROUP BY 1 ORDER BY n DESC")}
    unit_rows = {r["unit"]: r["n"] for r in rows(
        "SELECT unit, COUNT(*) n FROM assets GROUP BY 1 ORDER BY n DESC")}
    frame_rows = {r["frame"]: r["n"] for r in rows(
        "SELECT frame, COUNT(*) n FROM assets GROUP BY 1 ORDER BY n DESC")}
    qa_rows = {r["qa_status"]: r["n"] for r in rows(
        "SELECT qa_status, COUNT(*) n FROM assets GROUP BY 1 ORDER BY n DESC")}
    total_rows = sum(role_rows.values())

    # ---------------------------------------------------------------- resolve code contract
    def resolve(expr: str) -> str:
        expr = (expr or "").strip()
        if expr in all_role_constants:
            return f"{expr} = {all_role_constants[expr]['value']!r}"
        try:
            literal = ast.literal_eval(expr)
        except Exception:  # noqa: BLE001
            literal = None
        if isinstance(literal, str):
            return repr(literal)
        return f"DYNAMIC({expr})"

    #: commit sites are taken from the shipped package (``synlab/``) — tests and tools also call
    #: commit_asset but are not the production contract.  ``contract['commit_calls_live']`` keeps
    #: the full live-tree list for reference.
    code_by_role: dict[str, list[dict]] = defaultdict(list)
    for call in contract["commit_calls_live"]:
        if not call["file"].startswith("synlab/"):
            continue
        role_expr = call["kwargs"].get("role", "")
        role_val = None
        if role_expr in all_role_constants and role_expr.startswith("ROLE_"):
            role_val = all_role_constants[role_expr]["value"]
        else:
            try:
                maybe = ast.literal_eval(role_expr)
            except Exception:  # noqa: BLE001
                maybe = None
            if isinstance(maybe, str):
                role_val = maybe
        entry = {
            "site": f"{call['file']}:{call['line']}",
            "func": call["func"],
            "role_expr": role_expr,
            "role": role_val,
            "schema": resolve(call["kwargs"].get("schema", "")),
            "unit": resolve(call["kwargs"].get("unit", "")),
            "frame": resolve(call["kwargs"].get("frame", "")),
        }
        if role_val:
            code_by_role[role_val].append(entry)

    # ---------------------------------------------------------------- extra probes
    lineage_null = {r["role"]: r["n"] for r in rows(
        "SELECT role, COUNT(*) n FROM assets WHERE lineage_id IS NULL GROUP BY 1")}
    split_null = {r["role"]: r["n"] for r in rows(
        "SELECT role, COUNT(*) n FROM assets WHERE split IS NULL GROUP BY 1")}
    nested_pixel = [dict(r) for r in rows(
        "SELECT DISTINCT json_extract(meta_json, '$.meta.pixel_convention') v FROM assets "
        "WHERE json_extract(meta_json, '$.meta.pixel_convention') IS NOT NULL")]
    qa_meta = [dict(r) for r in rows("SELECT asset_id, meta_json, created_at FROM assets "
                                     "WHERE role='qa_report' ORDER BY created_at")]
    obs_unit_frame = [dict(r) for r in rows(
        "SELECT unit, frame, COUNT(*) n FROM assets WHERE role='obs_view' GROUP BY 1,2")]

    # ---------------------------------------------------------------- zero-row lists
    declared_roles = OrderedDict(
        (name, info) for name, info in constants.items() if name.startswith("ROLE_"))
    roles_zero_from_registry = [(name, info["value"], info["file"], info["line"])
                                for name, info in declared_roles.items()
                                if info["value"] not in role_rows]
    declared_schemas = OrderedDict(
        (name, info) for name, info in constants.items() if name.startswith("SCHEMA_"))
    schemas_zero = [(name, info["value"], info["file"], info["line"]) for name, info in declared_schemas.items()
                    if info["value"] not in schema_rows]
    literal_schemas = sorted({s for s in contract["literal_schemas"]})
    #: an *asset* schema id must either be a SCHEMA_* constant or be passed as the ``schema=``
    #: argument of a live commit call.  A bare "synlab.*.v1" string elsewhere in the repo is a
    #: report/format id (e.g. schema_meta rows), not an asset schema.
    commit_schema_literals: set[str] = set()
    for call in contract["commit_calls_live"]:
        if not call["file"].startswith("synlab/"):
            continue
        raw = (call["kwargs"].get("schema") or "").strip()
        try:
            maybe = ast.literal_eval(raw)
        except Exception:  # noqa: BLE001
            maybe = None
        if isinstance(maybe, str):
            commit_schema_literals.add(maybe)
    declared_schema_values = {i["value"] for i in declared_schemas.values()}
    literal_only = sorted(commit_schema_literals - declared_schema_values)
    literal_only_zero = [s for s in literal_only if s not in schema_rows]

    # role names that appear as string literals in live code but are not roles.py constants
    role_literals_live: dict[str, list[str]] = defaultdict(list)
    for item in contract["role_literals"]:
        if is_live(item["file"]):
            role_literals_live[item["role"]].append(f"{item['file']}:{item['line']}")
    declared_role_values = {i["value"] for i in declared_roles.values()}
    code_only_roles = OrderedDict(
        (r, sorted(where)) for r, where in sorted(role_literals_live.items())
        if r not in declared_role_values)

    # extra hard-coded role sets outside roles.py (found by reading, cited below)
    extra_role_sets = {
        "synlab/api/security.py:52-54 RESEARCH_ONLY_ROLES extras": ["spurious_mask", "hard_case_tag",
                                                                   "ancestry_graph"],
        "synlab/degrade/diversity.py:68": ["degrade_source"],
        "synlab/degrade/diversity.py:75": ["degrade_variant"],
        "synlab/degrade/sources.py:389 default": ["degradation_output"],
    }

    # ---------------------------------------------------------------- markdown table
    md: list[str] = []
    txt: list[str] = []

    def out(text: str = "") -> None:
        txt.append(text)

    def cell_hist(hist: dict) -> str:
        return "<br>".join(f"`{k}` n={v}" for k, v in hist.items()) if hist else "无 (none)"

    md.append("# Metadata contract per asset role — sqlite vs synlab/roles.py vs "
              "synlab/schemas/runtime.py")
    md.append("")
    md.append(f"- store: `data/a12/metadata.sqlite` (opened `mode=ro&immutable=1`), "
              f"assets rows total = **{census['assets_rows_total']}**, distinct roles = "
              f"**{census['distinct_roles_in_sqlite']}**")
    #: module-level ROLE_* constants outside roles.py split into (a) values that really are used as
    #: an asset ``role=`` at a commit site, and (b) constants that name something else (session
    #: roles, multi-event plan labels) and never become an asset role.
    asset_role_constants_outside = OrderedDict(
        (name, info) for name, info in extra_role_constants.items() if code_by_role.get(info["value"]))
    non_asset_role_constants = OrderedDict(
        (name, info) for name, info in extra_role_constants.items()
        if not code_by_role.get(info["value"]))
    extra_desc = ", ".join(f"{name} = {info['value']!r} @ {info['file']}:{info['line']}"
                           for name, info in extra_role_constants.items())
    asset_extra_desc = ", ".join(
        f"{name} = {info['value']!r} @ {info['file']}:{info['line']}"
        for name, info in asset_role_constants_outside.items())
    non_asset_desc = ", ".join(f"{name} = {info['value']!r} @ {info['file']}:{info['line']}"
                               for name, info in non_asset_role_constants.items())
    md.append(f"- roles declared in `synlab/roles.py` = **{len(declared_roles)}**; "
              f"schema ids declared = **{len(declared_schemas)}**")
    md.append(f"- asset roles named in code but declared OUTSIDE roles.py = "
              f"**{len(asset_role_constants_outside)}** ({asset_extra_desc}) → distinct asset roles "
              f"named in code = **{len(declared_roles) + len(asset_role_constants_outside)}**")
    md.append(f"- other module-level `ROLE_*` constants that never become an asset role = "
              f"**{len(non_asset_role_constants)}** ({non_asset_desc})")
    md.append("- citation convention: the table cites the `commit_asset(` **call line**; a bullet "
              "cites the line carrying the literal when the two differ (the `schema=`/`unit=`/"
              "`frame=` kwarg sits on the following line)")
    md.append(f"- `meta_json` is **not** a wrapper: {census['assets_rows_total'] - 37}/"
              f"{census['assets_rows_total']} rows have no top-level `meta` key; only `obs_result` "
              f"(37/37) carries a key named `meta`, and that key is the `ObservationResult.meta` "
              f"field (observe/routes.py:1932)")
    md.append("")
    md.append("| role | row_count | schema | unit | frame | qa_status | meta_keys (top level of "
              "meta_json) | code_schema (synlab/ commit site) | code_unit | code_frame | "
              "runtime_dataclass | MISMATCH |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|")

    mismatch_notes: dict[str, list[str]] = defaultdict(list)
    detail: "OrderedDict[str, dict]" = OrderedDict()

    for role in roles_sqlite:
        e = per_role[role]
        mk = meta_keys[role]
        row_count = e["row_count"]
        full = mk["meta_keys_full"]
        partial = mk["meta_keys_partial"]
        mk_cell = (f"n={row_count} (all {row_count} rows): " + ", ".join(f"`{k}`" for k in full)
                   if full else "无 (none in all rows)")
        if partial:
            mk_cell += "<br>partial: " + ", ".join(f"`{k}` n={v}" for k, v in partial.items())
        if mk["n_rows_with_nested_meta_key"]:
            mk_cell += (f"<br>**nested `meta` field: {mk['n_rows_with_nested_meta_key']}/"
                        f"{row_count} rows**, inner keys: "
                        + ", ".join(f"`{k}` n={v}"
                                    for k, v in mk["nested_meta_inner_keys"].items()))

        model_name, model_ev = ROLE_MODEL.get(role, (None, "not mapped"))
        if model_name and model_name in dataclasses_:
            dc = dataclasses_[model_name]
            fields = ", ".join(f["name"] for f in dc["fields"])
            dc_cell = (f"`{model_name}` (runtime.py:{dc['line']}, {len(dc['fields'])} fields)<br>"
                       f"fields: {fields}<br>evidence: {model_ev}")
        else:
            dc_cell = f"无 (none in runtime.py)<br>closest substitute: {model_ev}"

        sites = code_by_role.get(role, [])
        if sites:
            cs = "<br>".join(f"{s['site']} {s['func']}: schema={s['schema']}" for s in sites)
            cu = "<br>".join(f"{s['site']}: unit={s['unit']}" for s in sites)
            cf = "<br>".join(f"{s['site']}: frame={s['frame']}" for s in sites)
        else:
            cs = cu = cf = "无 (no literal commit_asset call site)"
        if role in DYNAMIC_CONTRACT:
            dyn = "<br>".join(DYNAMIC_CONTRACT[role])
            cs += f"<br>dynamic: {dyn}"
            cu += f"<br>dynamic: {dyn}"
            cf += f"<br>dynamic: {dyn}"

        mism: list[str] = []
        # ---- sqlite vs roles.py
        schema_vals = list(e["schema"].keys())
        for sv in schema_vals:
            if sv not in {i["value"] for i in declared_schemas.values()}:
                mism.append(f"schema `{sv}` ({e['schema'][sv]}/{row_count} rows) is NOT declared in "
                            f"synlab/roles.py")
        unit_vals = list(e["unit"].keys())
        frame_vals = list(e["frame"].keys())
        frame_const_values = {info["value"] for name, info in constants.items()
                              if name.startswith("FRAME_")}
        for fv in frame_vals:
            if fv not in frame_const_values:
                mism.append(f"frame `{fv}` ({e['frame'][fv]}/{row_count} rows) is not a FRAME_* "
                            f"constant of synlab/roles.py")
        unit_const_values = {info["value"] for name, info in constants.items()
                             if name.startswith("UNIT_")}
        for uv in unit_vals:
            if uv not in unit_const_values:
                mism.append(f"unit `{uv}` ({e['unit'][uv]}/{row_count} rows) is not a UNIT_* "
                            f"constant of synlab/roles.py")
        # ---- role-specific concrete mismatches
        if role == "obs_view" and "px" in e["unit"] and "S_mm" in e["frame"]:
            mism.append("same asset declares unit=`px` AND frame=`S_mm` (mm): 48/48 rows "
                        "(degrade/api.py:572 unit='px' vs degrade/api.py:568 frame_id default 'S_mm')")
        if role == "qa_report":
            mism.append(f"2 rows, 2 distinct meta_json payloads: "
                        f"{[q['meta_json'] for q in qa_meta]} — the `doctor` key is present in "
                        f"1/2 rows only")
        if role == "obs_result" and nested_pixel:
            mism.append(f"nested meta field `meta.pixel_convention` = "
                        f"{[p['v'] for p in nested_pixel]} (37/37) while roles.py FRAME_PIXEL="
                        f"'pixel_cv_center' (roles.py:73) has 0 uses and frame='pixel_cv_center' "
                        f"has 0 rows")
        if lineage_null.get(role):
            mism.append(f"lineage_id IS NULL in {lineage_null[role]}/{row_count} rows")
        if split_null.get(role):
            mism.append(f"split IS NULL in {split_null[role]}/{row_count} rows")
        if role not in code_by_role and role not in DYNAMIC_CONTRACT:
            mism.append("no commit call site in the live tree resolves to this role")

        mism_cell = "<br>".join(f"• {m}" for m in mism) if mism else "—"
        mismatch_notes[role] = mism

        md.append("| " + " | ".join([
            f"`{role}`",
            f"**{row_count}**",
            cell_hist(e["schema"]).replace("<br>", "<br>"),
            cell_hist(e["unit"]),
            cell_hist(e["frame"]),
            cell_hist(e["qa_status"]),
            mk_cell,
            cs,
            cu,
            cf,
            dc_cell,
            mism_cell,
        ]) + " |")

        detail[role] = {
            "row_count": row_count,
            "schema": e["schema"], "unit": e["unit"], "frame": e["frame"],
            "qa_status": e["qa_status"], "split": e["split"],
            "meta_keys_full": full, "meta_keys_partial": partial,
            "nested_meta_rows": mk["n_rows_with_nested_meta_key"],
            "runtime_dataclass": model_name, "runtime_evidence": model_ev,
            "commit_sites": sites, "dynamic_contract": DYNAMIC_CONTRACT.get(role, []),
            "mismatches": mism,
        }

    md.append("")
    md.append("---")
    md.append("")
    md.append("## (b) schema ids defined in `synlab/roles.py` — assets in sqlite")
    md.append("")
    md.append("| # | constant | file:line | schema id | asset rows in sqlite | live-tree uses |")
    md.append("|---|---|---|---|---|---|")
    for index, (name, info) in enumerate(declared_schemas.items(), start=1):
        value = info["value"]
        n = schema_rows.get(value, 0)
        uses = len(live_usage.get(name, []))
        flag = "**0 rows**" if n == 0 else str(n)
        md.append(f"| {index} | `{name}` | {info['file']}:{info['line']} | `{value}` | {flag} | {uses} |")
    md.append("")
    md.append(f"**schema ids with ZERO asset rows: {len(schemas_zero)} of {len(declared_schemas)}** — "
              + ", ".join(f"`{v}` ({n} @ {f}:{l})" for n, v, f, l in schemas_zero))
    md.append("")
    md.append("Schema ids passed to a live commit call as a **string literal** (not declared in "
              "roles.py):")
    md.append("")
    md.append("| schema literal | asset rows in sqlite |")
    md.append("|---|---|")
    for s in literal_only:
        md.append(f"| `{s}` | {schema_rows.get(s, 0)} |")
    md.append("")
    md.append(f"**literal-only asset schema ids with ZERO rows: {len(literal_only_zero)}** — "
              + ", ".join(f"`{s}`" for s in literal_only_zero))
    md.append("")
    md.append(f"(The repo also contains {len(literal_schemas)} `synlab.*.v1`/`a12.*.v1` string "
              f"literals that are NOT asset schemas — report/format ids written by probes and "
              f"diagnostic reports; the full list is in partB_contract.txt.)")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## (c) roles named in code — assets in sqlite")
    md.append("")
    md.append(f"- distinct roles in sqlite: **{len(roles_sqlite)}**")
    md.append(f"- distinct roles in synlab/roles.py: **{len(declared_roles)}**")
    md.append(f"- asset roles named in code outside roles.py: "
              f"**{len(asset_role_constants_outside)}** ({asset_extra_desc}) — total distinct ASSET "
              f"roles named in code = **{len(declared_roles) + len(asset_role_constants_outside)}**")
    md.append(f"- every one of the {len(roles_sqlite)} sqlite roles IS declared in roles.py "
              f"({len(roles_sqlite)}/{len(roles_sqlite)}); roles in roles.py with ZERO asset rows: "
              f"**{len(roles_zero_from_registry)}**")
    md.append("")
    md.append("| role constant | file:line | role | asset rows | live-tree uses | commit site |")
    md.append("|---|---|---|---|---|---|")
    for name, value, file, line in roles_zero_from_registry:
        uses = len(live_usage.get(name, []))
        sites = code_by_role.get(value, [])
        site = ", ".join(f"{s['site']} {s['func']}" for s in sites) if sites else "无 (none)"
        md.append(f"| `{name}` | {file}:{line} | `{value}` | **0** | {uses} | {site} |")
    md.append("")
    md.append("Roles named in live code that are **not** in roles.py and have 0 asset rows:")
    md.append("")
    md.append("| role name | where declared | asset rows | commit site |")
    md.append("|---|---|---|---|")
    for where, names in extra_role_sets.items():
        for nm in names:
            sites = code_by_role.get(nm, [])
            site = ", ".join(f"{s['site']} {s['func']}" for s in sites) if sites else "无 (none)"
            md.append(f"| `{nm}` | {where} | {role_rows.get(nm, 0)} | {site} |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## (d) mismatch list (each with file:line + real numbers)")
    md.append("")

    # ---------------------------------------------------------------- mismatch block
    all_sites = [s for sites in code_by_role.values() for s in sites]

    def sites_with(**want: str) -> list[str]:
        out_sites = []
        for s in all_sites:
            if all(s.get(k) == v for k, v in want.items()):
                out_sites.append(s["site"])
        return sorted(set(out_sites))

    smm_sites = sites_with(frame="'S_mm'")
    none_sites = sites_with(frame="'none'")
    labels_sites = sites_with(role="label_bundle")
    provenance_sites = sites_with(role="provenance")

    bullets: list[str] = []
    bullets.append(
        f"**M1 — the stated `meta_json['meta']` contract does not hold.** "
        f"{census['assets_rows_total'] - 37}/{census['assets_rows_total']} rows have NO top-level "
        f"`meta` key; `meta_json` is written directly from the `meta` mapping at "
        f"synlab/storage/store.py:413 (`_dumps(meta)`) and store.py:356 writes the *file* "
        f"`meta.json` as `{{'meta': meta, 'qa': qa, 'files': {{}}}}`. Only `obs_result` "
        f"(37/37 rows) has a key named `meta`, and it is the `ObservationResult.meta` field "
        f"(observe/routes.py:1932), not a wrapper. Reading `json.loads(meta_json)['meta']` raises "
        f"KeyError on 857/894 rows (95.9%).")
    bullets.append(
        f"**M2 — role count: sqlite {len(roles_sqlite)} vs roles.py {len(declared_roles)}.** "
        f"{len(roles_zero_from_registry)} of the {len(declared_roles)} registered roles have 0 rows "
        f"in data/a12/metadata.sqlite; 0 of the {len(roles_sqlite)} sqlite roles is missing from "
        f"roles.py (all 20 are declared there).")
    bullets.append(
        f"**M3 — {len(schemas_zero)} of {len(declared_schemas)} schema ids in roles.py have 0 asset "
        f"rows:** " + ", ".join(f"`{v}` ({f}:{l})" for _n, v, f, l in schemas_zero) + ".")
    bullets.append(
        f"**M4 — 2 schema ids in sqlite are not declared in roles.py at all:** "
        f"`synlab.labels.v1` ({schema_rows.get('synlab.labels.v1', 0)} rows) is committed as a "
        f"string literal at {', '.join(labels_sites)}; `synlab.provenance.v1` "
        f"({schema_rows.get('synlab.provenance.v1', 0)} rows) at {', '.join(provenance_sites)}. "
        f"`ROLE_LABEL_BUNDLE` (roles.py:50) and `ROLE_PROVENANCE` (roles.py:51) exist, but no "
        f"SCHEMA_* constant does. (Sites are the `commit_asset(` call lines; the literal itself is "
        f"on the `schema=` line just below.)")
    bullets.append(
        f"**M5 — `SCHEMA_CAMERA_PROFILE` (roles.py:17, `synlab.camera_profile.v1`) has 0 live-tree "
        f"uses and 0 rows** (only occurrence in the live tree is its own definition). "
        f"`ROLE_MOTHER_META` (roles.py:29) and `ROLE_MVS_RESULT` (roles.py:63) also have "
        f"0 live-tree uses, and `ROLE_PATTERN_AUDIT` (roles.py:33) has 1 use "
        f"(synlab/qc/gates.py:25) with no commit site.")
    bullets.append(
        f"**M6 — frame constants that no code writes:** `FRAME_SCAN='S_mm'` (roles.py:71) has "
        f"0 live-tree uses although frame `S_mm` has {frame_rows.get('S_mm', 0)} rows — written as "
        f"the string literal `'S_mm'` at {', '.join(smm_sites)} and as a default value at "
        f"synlab/degrade/api.py:568 and synlab/observe/routes.py:175. "
        f"`FRAME_CAMERA='C_mm'` (roles.py:72) 0 uses, frame `C_mm` {frame_rows.get('C_mm', 0)} rows. "
        f"`FRAME_PIXEL='pixel_cv_center'` (roles.py:73) 0 uses, frame `pixel_cv_center` "
        f"{frame_rows.get('pixel_cv_center', 0)} rows (the value only exists inside obs_result "
        f"meta.meta.pixel_convention, which holds `opencv_pixel_center_0_0` 37/37 — a THIRD "
        f"spelling of the same convention).")
    bullets.append(
        f"**M7 — frame values in sqlite that are not FRAME_* constants:** `none` "
        f"({frame_rows.get('none', 0)} rows = provenance 45 + qa_report 2), written at "
        f"{', '.join(none_sites)}. Additionally the live tree writes `frame='NA'` "
        f"(synlab/training/trainer.py:809) and `frame=f'{{display.DISPLAY_UP_AXIS}}_up_m'` "
        f"(synlab/api/handlers.py:579); both have 0 rows because train_checkpoint and "
        f"display_lod_glb have 0 rows.")
    bullets.append(
        f"**M8 — unit values:** sqlite has {len(unit_rows)} units — "
        + ", ".join(f"`{k}` {v}" for k, v in unit_rows.items()) + ". "
        f"`px` occurs only on `obs_view` ({per_role['obs_view']['unit'].get('px', 0)}/"
        f"{per_role['obs_view']['row_count']} rows) and is set at synlab/degrade/api.py:572 while "
        f"the generic committer default is `unit: str = UNIT_MM` (synlab/degrade/sources.py:166 "
        f"and :230). `UNIT_PX` (roles.py:67) has 2 live uses, both axis declarations "
        f"(synlab/degrade/axes.py:38, :756), none at a commit site. synlab/observe/api.py:215 can "
        f"write `unit='unknown'` (when `obs.scale_valid` is false); that string is not a UNIT_* "
        f"constant and {unit_rows.get('unknown', 0)} rows carry it (obs_result unit is "
        f"`{list(per_role['obs_result']['unit'].keys())}` "
        f"{list(per_role['obs_result']['unit'].values())}).")
    bullets.append(
        f"**M9 — roles.py declares NO per-role schema/unit/frame table.** 无 (none): the file defines "
        f"20 SCHEMA_*, 32 ROLE_*, 3 UNIT_*, 5 FRAME_* constants (roles.py:6-73) but no mapping from a "
        f"role to its schema/unit/frame. The closest substitutes are the commit-site literals in the "
        f"table above, `COMMIT_ROLES` (synlab/degrade/api.py:79-84) and "
        f"`FAMILY_SCHEMA`/`FAMILY_UNIT` (synlab/degrade/diversity.py:79-87).")
    bullets.append(
        f"**M10 — the family→(role, schema) map is declared twice and the units disagree in shape:** "
        f"`COMMIT_ROLES` (synlab/degrade/api.py:79-84) maps P/I/G/X to roles+schema with **no unit "
        f"entry**, while `FAMILY_UNIT` (synlab/degrade/diversity.py:87) maps the same four families "
        f"to `{{'P': 'mm', 'I': 'px', 'G': 'mm', 'X': '1'}}` and `FAMILY_SCHEMA` "
        f"(synlab/degrade/diversity.py:79-84) repeats the schema map. Values agree for I=`px`, "
        f"G=`mm`, X=`1`, P=`mm`, but two code paths must be kept in sync by hand.")
    bullets.append(
        f"**M11 — {len(asset_role_constants_outside)} asset roles are committed by live code but are "
        f"declared outside roles.py, so no registry lists them, and they have 0 asset rows:** "
        + "; ".join(f"`{info['value']}` ({info['file']}:{info['line']}) committed at "
                    f"{', '.join(sites_with(role=info['value']))}"
                    for info in asset_role_constants_outside.values())
        + f". 0 rows each in data/a12/metadata.sqlite ({len(roles_sqlite)} roles).")
    bullets.append(
        f"**M12 — `obs_view` declares pixel unit with a millimetre frame:** 48/48 rows carry "
        f"unit=`px` + frame=`S_mm`; the runtime dataclass `ObsView` (runtime.py:432) mixes "
        f"`rgb` (uint8 pixels) with `depth_z` documented as mm (runtime.py:437).")
    bullets.append(
        f"**M13 — NULL lineage/split:** lineage_id IS NULL in 5/894 rows "
        f"(qa_report 2/2, relation_pool 2/2, query_roster 1/1) and split IS NULL in 2/894 rows "
        f"(qa_report 2/2). Every other role has 0 NULL lineage_id and 0 NULL split.")
    bullets.append(
        f"**M14 — qa_report rows are not homogeneous:** 2 rows, meta_json = `{{}}` and "
        f"`{{\"doctor\": true}}` (1/2 rows carry `doctor`), 2 distinct asset_ids and 2 distinct "
        f"created_at values, both schema `synlab.qa.v1`, unit `1`, frame `none`, qa_status QA_PASS.")
    bullets.append(
        f"**M15 — the schema id is stored a third time inside meta_json for 3 roles:** "
        f"meta['schema'] present in material_profile 50/50, feature_bundle 45/45, relation_pool 2/2, "
        f"and in every case it equals the `schema` column "
        f"(synlab.material.v1 / a12.obs.v1 / synlab.pool.v1) — consistent, but a second copy that "
        f"can drift (materials/api.py:492, pipeline._commit_features, relations/api.py:562).")
    bullets.append(
        f"**M16 — qa_status is not derivable from a single rule:** sqlite holds "
        + ", ".join(f"{k} {v}" for k, v in qa_rows.items()) + f" of {total_rows} rows; "
        f"physical_component {per_role['physical_component']['qa_status'].get('QA_PENDING', 0)}/"
        f"{per_role['physical_component']['row_count']}, obs_view "
        f"{per_role['obs_view']['qa_status'].get('QA_PENDING', 0)}/"
        f"{per_role['obs_view']['row_count']}, obs_fused_geometry "
        f"{per_role['obs_fused_geometry']['qa_status'].get('QA_PENDING', 0)}/"
        f"{per_role['obs_fused_geometry']['row_count']} and degrade_measurement "
        f"{per_role['degrade_measurement']['qa_status'].get('QA_PENDING', 0)}/"
        f"{per_role['degrade_measurement']['row_count']} are QA_PENDING, visible_labels is QA_FAIL "
        f"{per_role['visible_labels']['qa_status'].get('QA_FAIL', 0)}/"
        f"{per_role['visible_labels']['row_count']} + QA_PASS "
        f"{per_role['visible_labels']['qa_status'].get('QA_PASS', 0)}/"
        f"{per_role['visible_labels']['row_count']}, physical_result is QA_PASS "
        f"{per_role['physical_result']['qa_status'].get('QA_PASS', 0)}/"
        f"{per_role['physical_result']['row_count']} + QA_FAIL "
        f"{per_role['physical_result']['qa_status'].get('QA_FAIL', 0)}/"
        f"{per_role['physical_result']['row_count']}, pattern_recipe/channels are QA_PENDING "
        f"{per_role['pattern_recipe']['qa_status'].get('QA_PENDING', 0)}/"
        f"{per_role['pattern_recipe']['row_count']} (with QA_PASS "
        f"{per_role['pattern_recipe']['qa_status'].get('QA_PASS', 0)} and QA_FAIL "
        f"{per_role['pattern_recipe']['qa_status'].get('QA_FAIL', 0)}).")
    for b in bullets:
        md.append(f"- {b}")

    # ---------------------------------------------------------------- citation stability
    cited = sorted({s.split(":")[0] for s in all_sites} |
                   {"synlab/roles.py", "synlab/schemas/runtime.py", "synlab/storage/store.py",
                    "synlab/degrade/sources.py", "synlab/degrade/diversity.py",
                    "synlab/observe/routes.py", "synlab/api/security.py", "synlab/api/handlers.py"})
    hashes: "OrderedDict[str, dict]" = OrderedDict()
    for rel_path in cited:
        path = REPO / rel_path
        if not path.exists():
            hashes[rel_path] = {"exists": False}
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[rel_path] = {"sha256": digest, "bytes": path.stat().st_size,
                            "mtime": path.stat().st_mtime}
    db_digest = hashlib.sha256(DB.read_bytes()).hexdigest()
    md.append("")
    md.append("---")
    md.append("")
    md.append("## (e) citation stability — sha256 of every cited file at table-generation time")
    md.append("")
    md.append(f"- `data/a12/metadata.sqlite` sha256 = `{db_digest}` "
              f"({DB.stat().st_size} bytes)")
    md.append(f"- the working tree is being edited concurrently: re-check a hash before trusting a "
              f"line number from the table")
    md.append("")
    md.append("| file | sha256 (first 16) | bytes |")
    md.append("|---|---|---|")
    for rel_path, info in hashes.items():
        if info.get("exists"):
            md.append(f"| `{rel_path}` | `{info['sha256'][:16]}` | {info['bytes']} |")
        else:
            md.append(f"| `{rel_path}` | (missing) | — |")

    # ---------------------------------------------------------------- txt report extras
    out("=" * 100)
    out("PART B — metadata contract census (join of sqlite + roles.py + runtime.py)")
    out("=" * 100)
    out(f"sqlite roles = {len(roles_sqlite)}   roles.py roles = {len(declared_roles)}   "
        f"roles.py schemas = {len(declared_schemas)}   runtime dataclasses = {len(dataclasses_)}")
    out("")
    for b in bullets:
        out("- " + b.replace("<br>", " "))
    out("")
    out("=" * 100)
    out("PER-ROLE DETAIL")
    out("=" * 100)
    for role, d in detail.items():
        out(f"\n### {role}  rows={d['row_count']}")
        out(f"    schema   : {d['schema']}")
        out(f"    unit     : {d['unit']}")
        out(f"    frame    : {d['frame']}")
        out(f"    qa_status: {d['qa_status']}")
        out(f"    split    : {d['split']}")
        out(f"    runtime  : {d['runtime_dataclass']}  ({d['runtime_evidence']})")
        for s in d["commit_sites"]:
            out(f"      commit {s['site']} {s['func']}: schema={s['schema']} unit={s['unit']} "
                f"frame={s['frame']}")
        for s in d["dynamic_contract"]:
            out(f"      dynamic: {s}")
        for m in d["mismatches"]:
            out(f"      MISMATCH: {m}")
    out("")
    out("=" * 100)
    out("ROLE-MODEL MAP USED (role -> synlab/schemas/runtime.py dataclass + field names)")
    out("=" * 100)
    for role in roles_sqlite:
        name, ev = ROLE_MODEL.get(role, (None, ""))
        if name and name in dataclasses_:
            dc = dataclasses_[name]
            out(f"  {role:<22} -> {name:<20} runtime.py:{dc['line']:<4} "
                f"fields[{len(dc['fields'])}] = {', '.join(f['name'] for f in dc['fields'])}")
        else:
            out(f"  {role:<22} -> 无 (none)          closest substitute: {ev}")

    (HERE / "partB_table.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (HERE / "partB_table.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")
    payload = {
        "sqlite_roles": roles_sqlite,
        "roles_py_role_count": len(declared_roles),
        "roles_py_schema_count": len(declared_schemas),
        "runtime_dataclass_count": len(dataclasses_),
        "per_role": detail,
        "schemas_zero_rows": [v for _n, v, _f, _l in schemas_zero],
        "literal_only_schemas": literal_only,
        "literal_only_schemas_zero_rows": literal_only_zero,
        "roles_zero_rows": [v for _n, v, _f, _l in roles_zero_from_registry],
        "code_only_roles": code_only_roles,
        "extra_role_sets": extra_role_sets,
        "asset_role_constants_outside_roles_py": asset_role_constants_outside,
        "non_asset_role_constants": non_asset_role_constants,
        "file_hashes": hashes,
        "db_sha256": db_digest,
        "mismatches": bullets,
    }
    (HERE / "partB_table.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
    con.close()
    print(f"wrote {HERE / 'partB_table.md'} ({(HERE / 'partB_table.md').stat().st_size} bytes)")
    print(f"wrote {HERE / 'partB_table.txt'} ({(HERE / 'partB_table.txt').stat().st_size} bytes)")
    print(f"wrote {HERE / 'partB_table.json'} ({(HERE / 'partB_table.json').stat().st_size} bytes)")
    print(f"roles_sqlite={len(roles_sqlite)} roles_py={len(declared_roles)} "
          f"schemas_py={len(declared_schemas)} dataclasses={len(dataclasses_)}")
    print(f"schemas_zero={len(schemas_zero)} roles_zero={len(roles_zero_from_registry)} "
          f"literal_only={literal_only}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
