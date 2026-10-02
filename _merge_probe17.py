import json
c=json.load(open("data/a12_reports/experiment_ready_loader_card.json",encoding="utf-8"))
for e in c["honest_boundaries"]:
    if e["id"]=="undocumented_columns":
        print(json.dumps(e["current_value"],ensure_ascii=False,indent=1)[:2500])
