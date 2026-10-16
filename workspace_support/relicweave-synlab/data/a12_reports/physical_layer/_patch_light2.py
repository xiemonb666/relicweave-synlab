from pathlib import Path
p = Path("tests/a12/observe/_run_fracture_appearance.py")
t = p.read_text(encoding="utf-8")
old = "    min_amp = min(float(x) for x in config.amplitudes_mm)"
new = "    light = light if 'light' in dir() else fa.frozen_light()\n" + old
assert t.count(old) == 1, t.count(old)
t = t.replace(old, new, 1)
p.write_text(t, encoding="utf-8")
print("ok")
