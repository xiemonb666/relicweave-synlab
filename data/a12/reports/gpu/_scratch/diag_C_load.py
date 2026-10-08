"""Diagnose why torch._C fails to initialise even though every file matches the wheel."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

SP = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\.venv\Lib\site-packages")
TORCH = SP / "torch"
LIB = TORCH / "lib"

print("torch dir :", TORCH.is_dir())
print("lib entries:", len(list(LIB.iterdir())) if LIB.is_dir() else "n/a")

KEY = ["torch_cpu.dll", "torch_cuda.dll", "c10.dll", "c10_cuda.dll", "cudart64_12.dll",
       "cudnn64_9.dll", "shm.dll", "uv.dll", "asmjit.dll", "fbgemm.dll", "libiomp5md.dll",
       "nvToolsExt64_1.dll", "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"]
present = {}
for name in KEY:
    p = LIB / name
    present[name] = p.stat().st_size if p.exists() else None
    print(f"  {name:22s} {'MISSING' if p is None or not p.exists() else p.stat().st_size}")

pyd = TORCH / "_C.cp312-win_amd64.pyd"
print("_C pyd    :", pyd.exists(), pyd.stat().st_size if pyd.exists() else "")

# The VC++ runtime is a common cause of "application failed to initialise" (0xc0000142).
sysdir = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
for rt in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll"):
    print(f"system32 {rt:20s}", (sysdir / rt).exists())

os.add_dll_directory(str(LIB))
os.add_dll_directory(str(TORCH))
try:
    ctypes.WinDLL(str(pyd))
    print("WinDLL(_C) : OK")
except OSError as exc:
    print(f"WinDLL(_C) : FAIL {exc}")

# try loading each lib explicitly to find the first that fails
for name in KEY:
    p = LIB / name
    if not p.exists():
        continue
    try:
        ctypes.WinDLL(str(p))
        print(f"  load {name:22s} OK")
    except OSError as exc:
        print(f"  load {name:22s} FAIL {exc}")
        break
