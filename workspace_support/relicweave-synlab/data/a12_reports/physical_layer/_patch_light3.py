from pathlib import Path
p = Path("tests/a12/observe/_run_fracture_appearance.py")
t = p.read_text(encoding="utf-8")
bad = "    min_amp = min(float(x) for x in config.amplitudes_mm)    field = fa.build_relief_field("
good = "    light = fa.frozen_light()\n    min_amp = min(float(x) for x in config.amplitudes_mm)\n    field = fa.build_relief_field("
assert t.count(bad) == 1
t = t.replace(bad, good, 1)
p.write_text(t, encoding="utf-8")
print("fixed")
