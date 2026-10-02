import json
d=json.load(open("data/a12_exports/experiment_ready/training_package/research/fracture/index.json",encoding="utf-8"))
print("counts:", json.dumps(d["counts"],ensure_ascii=False))
rows=[r for r in d["rows"] if r.get("n_interface_faces")]
print("rows with ifaces:", len(rows))
for r in rows[:6]:
    print("  ", r["asset_id"], r["lineage_id"], "faces", r["n_interface_faces"], "area", round(r["area_mm2"],3), "planar", r["planar_geometry"], "resmax", r["plane_residual_max_mm"])
rows0=[r for r in d["rows"] if r.get("n_interface_faces")==0]
print("rows with zero ifaces:", len(rows0), "skipped:", sum(1 for r in d["rows"] if r.get("skipped")))
d2=json.load(open("data/a12_exports/experiment_ready/training_package/research/degrade/index.json",encoding="utf-8"))
print("degrade counts:", json.dumps(d2["counts"],ensure_ascii=False))
print("axes sample:", [(a["axis_id"], a["materialised_levels"], a.get("declared_levels")) for a in d2["axes"][:6]])
print("no-level axes:", [a["axis_id"] for a in d2["axes"] if not a["materialised"]])
