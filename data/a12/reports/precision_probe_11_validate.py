import json
import pathlib

p = pathlib.Path("data/a12/reports/precision_audit.json")
d = json.loads(p.read_text(encoding="utf-8"))
print("schema", d["schema"], "bytes", p.stat().st_size)
print("code_state", d["code_state"]["git_head"], "dirty", len(d["code_state"]["git_status_porcelain"]))
for dim in d["dimensions"]:
    print("  dim%d %-20s %s rig_spec_keys=%d now_keys=%d"
          % (dim["id"], dim["key"], dim["priority"], len(dim["rig_spec"]), len(dim["synthetic_now"])))
print("top5:")
for t in d["top5_shortfalls"]:
    print("  ", t["rank"], t["priority"], t["title"][:70])
print("missing:", len(d["missing_metrics"]))
print("probe_scripts:", d["probe_scripts"])
print("probe_outputs:", len(d["probe_outputs"]))
