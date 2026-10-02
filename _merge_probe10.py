import json
d=json.load(open("synlab/schemas/view_channels.json",encoding="utf-8"))
v=d["views"]
print("views keys:", list(v.keys()))
for view,block in v.items():
    print("="*30,view, list(block.keys()))
    ch=block.get("channels") or []
    print("  n channels:", len(ch))
    for c in ch:
        print("   ", json.dumps(c,ensure_ascii=False)[:260])
print("truth_roles:", json.dumps(d.get("truth_roles"),ensure_ascii=False)[:800])
