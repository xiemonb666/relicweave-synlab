import json
r=json.load(open("data/a12_reports/../a12_exports/experiment_ready/experiment_ready_report.json",encoding="utf-8"))
m=r["merge"]
for d in m["dimensions"]:
    print("="*30, d["dimension"], d["ablation_group"], d["switch_field"])
    print("   counts:", json.dumps(d["counts"],ensure_ascii=False))
    print("   deploy_view_touched:", d["deploy_view_touched"])
