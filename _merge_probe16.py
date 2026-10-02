import json
d=json.load(open("data/a12_exports/experiment_ready/training_package/research/fracture/index.json",encoding="utf-8"))
zero=[p for p in d["patches"] if p.get("ra_below_1mm_mm")==0.0]
print("patches below_1mm Ra == 0:", len(zero), "of", len(d["patches"]))
import collections
print("by lineage:", collections.Counter(p["lineage_id"] for p in zero))
print("by n_faces:", collections.Counter(p["n_faces"] for p in zero))
nz=[p for p in d["patches"] if (p.get("ra_below_1mm_mm") or 0)>0]
nz.sort(key=lambda p:-p["ra_below_1mm_mm"])
print("largest below_1mm Ra:", [(p["lineage_id"], round(p["ra_below_1mm_mm"],5), p["n_faces"]) for p in nz[:6]])
print("areas of zero patches:", [round(p["area_mm2"],3) for p in zero])
t=json.load(open("data/a12_exports/experiment_ready/training_package/ablation_index.json",encoding="utf-8"))
print("\nablation counts:", json.dumps(t["counts"],ensure_ascii=False))
for g in t["groups"]:
    print(" ", g["group_id"], g["availability"], g["switch_field"], "|", g["dimension"])
