import json
c=json.load(open("data/a12_reports/experiment_ready_card.json",encoding="utf-8"))
print("schema:", c["schema"])
print("files_on_disk:", c["package"]["file_count_on_disk"], "bytes:", c["package"]["bytes_total"])
print("files_missing:", c["package"].get("files_missing"), "files_extra:", len(c["package"].get("files_extra") or []))
for e in c["honest_boundaries"]:
    if e["id"]=="undocumented_columns":
        v=e["current_value"]
        print("undocumented:", v.get("n_columns", v if isinstance(v,int) else json.dumps(v,ensure_ascii=False)[:600]))
    if e["id"]=="deploy_view_channels":
        print("deploy_view_channels:", json.dumps(e["current_value"],ensure_ascii=False)[:400])
    if e["id"]=="no_legal_negatives":
        print("no_legal_negatives:", e["status"], json.dumps(e["current_value"],ensure_ascii=False)[:250])
print("tables in card:", list((c.get("columns") or {}).keys()))
print("counts:", json.dumps(c["package"].get("counts") or {},ensure_ascii=False)[:200])
print("tasks:", {k:(v.get("measured") or {}).get("n_allowed") for k,v in c["tasks"].items() if k in ("view","rank","correspondence","quality","contradiction")})
