import json
for f in ("index","variants","sources"):
    p=f"data/a12_degrade/exports/rel_degrade_diversity_1790919754/training_package/degrade/{f}.json"
    try:
        d=json.load(open(p,encoding="utf-8"))
    except Exception as e:
        print(f,"ERR",e); continue
    print("="*40,f)
    if isinstance(d,dict):
        for k,v in d.items():
            s=json.dumps(v,ensure_ascii=False,default=str) if not isinstance(v,str) else v
            print(f"  {k}: {s[:400]}")
