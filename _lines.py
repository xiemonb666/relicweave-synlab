from pathlib import Path
p = Path("synlab/storage/export.py")
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
print("total lines", len(lines))
print("2438:", repr(lines[2437]))
print("2439:", repr(lines[2438]))
print("2507:", repr(lines[2506]))
print("2508:", repr(lines[2507]))
print("2509:", repr(lines[2508]))
