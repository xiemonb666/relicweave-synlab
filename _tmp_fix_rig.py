import io
import re

p = r"C:\Users\xiemo\Desktop\ShardForge\data\a12_reports\measure_rig_ladder.py"
t = io.open(p, encoding="utf-8").read()
t = t.replace("\u9225?", "\u2014").replace("\u9364", "\u00a7")
lines = t.splitlines()
out = []
for line in lines:
    stripped = line.strip()
    if stripped.startswith('"no_resize_rule"'):
        indent = line[: len(line) - len(line.lstrip())]
        out.append(indent + '"no_resize_rule": "G14.4 p1488: U moves the camera along the optical '
                          'axis; resize must not be used to simulate a physical approach",')
        continue
    if stripped.startswith('"ref":'):
        indent = line[: len(line) - len(line.lstrip())]
        out.append(indent + '"ref": "5.6 p1063 (a synthetic calibration line; it must be '
                          're-calibrated once a real scan exists)",')
        continue
    out.append(line)
t = "\n".join(out) + "\n"
io.open(p, "w", encoding="utf-8", newline="").write(t)
bad = [ln for ln in t.splitlines() if any(ord(ch) > 0x2FFF for ch in ln)]
print("remaining non-latin lines:", len(bad))
for ln in bad:
    print("  ", ln.strip()[:110])
