import json, io
d = json.load(io.open("data/a12_reports/s12_axis_table.json", encoding="utf-8-sig"))
t = d["table"]
print("axes:", len(t["rows"]), "levels:", t["levels"])
for r in t["rows"]:
    lvl = r["levels"][0]
    deg = lvl.get("degrade") or {}
    print(f'{r["axis_id"]} stage={r["stage"]:<28} decl={r["declared_backend"]:<34} exec={",".join(r["executed_backends"]) or "-":<46} {r["agree"]:<12} L1 realized={deg.get("realized")} drift={deg.get("drift_mm")} p95={deg.get("drift_p95_mm")} grid={deg.get("grid_spacing_mm")} budget_limited={deg.get("grid_budget_limited")} fc={deg.get("failure_code")}')
