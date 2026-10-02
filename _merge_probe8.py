import json
p="synlab/schemas/view_channels.json"
d=json.load(open(p,encoding="utf-8"))
print("top:",list(d.keys()))
for k in ("table_columns","capture_context_fields"):
    print(k,":",json.dumps(d.get(k),ensure_ascii=False)[:900])
sc=d.get("scan") or d.get("separation") or {}
print("other blocks:", [k for k in d])
