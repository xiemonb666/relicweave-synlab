import sys, json, sqlite3, collections
sys.path.insert(0,'.')
from pathlib import Path
from synlab.qc.data_quality import DATA_SEMANTICS_ROLES, DAMAGE_MARKER_ROLES, _marker_values, _json_col
st = Path(r"data\a12_trainable\store")
con = sqlite3.connect(str(st/"metadata.sqlite")); con.row_factory = sqlite3.Row
print("roles currently in DATA_SEMANTICS_ROLES:", sorted(DATA_SEMANTICS_ROLES))
for role in ("visible_labels","clean_truth","physical_truth","obs_result"):
    rows = list(con.execute("select asset_id, meta_json, qa_json from assets where role=?", (role,)))
    have = 0
    for r in rows:
        v = _marker_values(_json_col(r, "meta_json"), _json_col(r, "qa_json"))
        if v.get("mask_semantics"): have += 1
    print(f"  {role:16s} n={len(rows):3d} with mask_semantics={have}")
# what keys does a visible_labels meta carry?
r = list(con.execute("select meta_json from assets where role='visible_labels' limit 1"))[0]
m = json.loads(r["meta_json"])
print()
print("visible_labels meta keys:", sorted(m.keys())[:30])
