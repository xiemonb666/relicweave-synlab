"""Diagnose why writing into .venv/Lib/site-packages/torch/lib fails (WinError 5).

Distinguishes three causes that look identical from pip's error message:
  * the directory is not writable (ACL / read-only)
  * a specific file is locked by another process (sharing violation -> also WinError 5/32)
  * the file exists but is read-only
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
LIB = ROOT / ".venv" / "Lib" / "site-packages" / "torch" / "lib"
SP = ROOT / ".venv" / "Lib" / "site-packages"

print("torch dir exists :", (SP / "torch").is_dir())
print("lib dir exists   :", LIB.is_dir())
if LIB.is_dir():
    files = sorted(p.name for p in LIB.iterdir())
    print("lib entries      :", len(files))
    print("first 10         :", files[:10])
for name in ("c10.dll", "c10_cuda.dll", "caffe2_nvrtc.dll", "torch_cpu.dll"):
    p = LIB / name
    print(f"  {name:20s} exists={p.exists()}", end="")
    if p.exists():
        try:
            st = os.stat(p)
            print(f" size={st.st_size} mode={oct(st.st_mode)}")
        except OSError as exc:
            print(f" stat failed: {exc}")
    else:
        print()

# 1) can we create a file in lib/ ?
probe = LIB / "_dsh_write_probe.tmp"
try:
    probe.write_bytes(b"x")
    print("create in lib/   : OK")
    probe.unlink()
except OSError as exc:
    print(f"create in lib/   : FAIL {type(exc).__name__} {exc}")

# 2) can we create a file in site-packages/ ?
probe2 = SP / "_dsh_write_probe.tmp"
try:
    probe2.write_bytes(b"x")
    print("create in sp/    : OK")
    probe2.unlink()
except OSError as exc:
    print(f"create in sp/    : FAIL {type(exc).__name__} {exc}")

# 3) can we rename a big existing dll (the trick pip uses to dodge locks)?
for name in ("c10_cuda.dll", "c10.dll"):
    p = LIB / name
    if not p.exists():
        continue
    tmp = LIB / (name + ".dshmovetest")
    try:
        os.replace(p, tmp)
        os.replace(tmp, p)
        print(f"rename {name:16s}: OK (not locked)")
    except OSError as exc:
        print(f"rename {name:16s}: FAIL {type(exc).__name__} {exc}  <-- locked")

# 4) can we open the dll for write (append) -- the operation pip needs?
for name in ("c10_cuda.dll", "c10.dll"):
    p = LIB / name
    if not p.exists():
        continue
    try:
        with open(p, "r+b"):
            pass
        print(f"open-rw {name:15s}: OK")
    except OSError as exc:
        print(f"open-rw {name:15s}: FAIL {type(exc).__name__} {exc}")

sys.exit(0)
