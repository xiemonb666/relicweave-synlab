from pathlib import Path
p = Path("synlab/observe/fracture_appearance.py")
t = p.read_text(encoding="utf-8")
old = '"lambert": _lambert_report(buffers.get("lambert"), tag_map),'
new = ('"lambert": _lambert_report(\n'
       '                None if buffers.get("lambert") is None\n'
       '                else np.asarray(buffers["lambert"])[::factor, ::factor], tag_map),')
assert t.count(old) == 1
t = t.replace(old, new, 1)
p.write_text(t, encoding="utf-8")
q = Path("data/a12_reports/physical_layer/_read_quick.py")
s = q.read_text(encoding="utf-8")
s = s.replace("a['prediction']['predicted_dDN']", "a['prediction'].get('dDN_from_measured_slope', float('nan'))")
q.write_text(s, encoding="utf-8")
print("ok")
