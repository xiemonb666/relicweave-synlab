import json, sys
d = json.load(open(r"data\a12_reports\s12_probe_backend_routing.json", encoding="utf-8"))
rows = []
for ax in d["axes"]:
    aid = ax["axis_id"]
    fam = ax["family"]
    if fam != "P":
        # single implementation; just record the declared backend and one realized level
        lvl = ax["observed"][0] if ax["observed"] else {}
        deg = lvl.get("degrade", {})
        rows.append((aid, ax["declared_backend"], ax["declared_backend"], "yes",
                     f"realized={deg.get('realized')} fc={deg.get('failure_code')}"))
        continue
    for lvl in ax["observed"]:
        deg = lvl.get("degrade", {})
        phy = lvl.get("physical", {})
        db = phy.get("damage_backend")
        sel = phy.get("backend_selection") or {}
        rows.append((f"{aid}/L{lvl['level']}", ax["declared_backend"], str(db), 
                     "yes" if (db and ax["declared_narrowband"] == ("narrowband" in str(db)) ) else "NO",
                     f"declared_nb={sel.get('declared_narrowband')} sel={sel.get('backend')} deg_realized={deg.get('realized')} deg_keys={deg.get('measured_backend_keys')} phy_grid={phy.get('grid_spacing_mm')} deg_grid={deg.get('grid_spacing_mm')}"))
for r in rows:
    print(" | ".join(str(x) for x in r))
