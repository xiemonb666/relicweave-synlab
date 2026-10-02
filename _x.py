import json, collections
d = json.load(open("data/a12_reports/s1_corr_token_dryrun.json", encoding="utf-8"))
print(json.dumps(d, ensure_ascii=False, indent=2)[:200])
