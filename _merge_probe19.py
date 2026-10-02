import json, numpy as np
c=json.load(open("data/a12_exports/experiment_ready/training_package/dataset_card.json",encoding="utf-8"))
a=c.get("arrays") or {}
print("arrays families:", {k: (len(v) if hasattr(v,"__len__") else v) for k,v in a.items()})
t=a.get("tokens") or {}
print("tokens family keys:", list(t)[:5])
for k in list(t)[:2]:
    print(" ", k, "->", json.dumps(t[k],ensure_ascii=False)[:400])
with np.load("data/a12_exports/experiment_ready/training_package/deploy/tokens/shard_0000.npz", allow_pickle=False) as d:
    print("npz keys:", d.files)
