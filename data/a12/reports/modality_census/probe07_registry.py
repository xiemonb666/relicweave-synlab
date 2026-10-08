import json,os,glob
ROOT=r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
d=json.load(open(os.path.join(ROOT,"docs","a12","registry.json"),encoding="utf-8"))
print("total registry entries:",len(d))
print()
for k in ("axis/X02","axis/X03"):
    print("="*70); print(k); print("="*70)
    print(json.dumps(d[k],indent=2)[:2600])
print()
print("ENTRIES CONTAINING 'episode'/'action'/'budget'/'cost':")
for k in d:
    s=json.dumps(d[k]).lower()
    if "episode" in s or "action" in s or "budget" in s or "cost" in s or k.lower().startswith(("episode","env")):
        print("   ",k, "->", json.dumps(d[k])[:180])
