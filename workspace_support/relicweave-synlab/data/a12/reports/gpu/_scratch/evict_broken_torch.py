"""Move the broken torch tree aside so a fresh install can write into a clean path.

Why not just let pip uninstall it: pip must *overwrite* ``torch/lib/c10.dll`` in place, and a
dozen live processes have that DLL mapped (LoadLibrary maps it without FILE_SHARE_WRITE), so
every write fails with WinError 5.  Renaming the directory succeeds even while the DLLs are
mapped, so moving the tree aside frees the path without touching the running processes (their
mappings follow the handle, not the path).
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

SP = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\.venv\Lib\site-packages")
stamp = time.strftime("%Y%m%d-%H%M%S")
moved: list[tuple[str, str]] = []
failed: list[tuple[str, str]] = []

targets = [p for p in SP.iterdir()
           if p.name == "torch" or p.name.startswith("torch-") and p.name.endswith(".dist-info")
           or p.name == "functorch" or p.name == "torchgen"]

print("free space GB:",
      round(shutil.disk_usage(str(SP)).free / 1024 ** 3, 2))
for p in targets:
    if p.name.startswith("torch.broken"):
        continue
    dest = SP / f"{p.name}.broken-{stamp}"
    try:
        p.rename(dest)
        moved.append((p.name, dest.name))
    except OSError as exc:
        failed.append((p.name, f"{type(exc).__name__}: {exc}"))

print(f"moved {len(moved)} item(s):")
for a, b in moved:
    print(f"   {a}  ->  {b}")
if failed:
    print(f"FAILED to move {len(failed)}:")
    for a, b in failed:
        print(f"   {a}: {b}")
    sys.exit(1)
print("path is now clear for a fresh install")
sys.exit(0)
