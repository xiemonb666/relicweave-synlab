import json,sys
m=json.load(open("data/a12_exports/trainable/next_experiment/training_package/export_manifest.json",encoding="utf-8"))
print("top keys:", sorted(m.keys()))
for k in ("schema","package_schema","release_id","package_id","manifest_hash","created_utc","formats"):
    if k in m: print(" ",k,"=",json.dumps(m[k])[:200])
print("counts:", json.dumps(m.get("counts"),ensure_ascii=False)[:1200])
print("counts_total:", m.get("counts_total"), "bytes_total:", m.get("bytes_total"))
print("views:", json.dumps(m.get("views"),ensure_ascii=False)[:800])
print("separation:", json.dumps(m.get("separation"),ensure_ascii=False)[:1500])
print("n files:", len(m.get("files",[])))
print("file entry sample:", json.dumps(m["files"][0],ensure_ascii=False))
print("labels keys:", json.dumps({k:(v if not isinstance(v,list) else f"list[{len(v)}]") for k,v in (m.get("labels") or {}).items()},ensure_ascii=False)[:800])
print("other keys:", [k for k in m if k not in ("files",)])
