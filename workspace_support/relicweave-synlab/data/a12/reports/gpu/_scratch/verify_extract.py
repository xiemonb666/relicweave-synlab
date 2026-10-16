"""Verify every extracted file against the wheel's stored size and CRC32.

A partial pip install followed by a resumable extraction can leave a file whose *size* matches
but whose *content* is from the interrupted write.  Checking the zip CRC is the only cheap way
to prove the tree on disk is byte-identical to the wheel.
"""

from __future__ import annotations

import sys
import zipfile
import zlib
from pathlib import Path

wheel = Path(sys.argv[1])
dest = Path(sys.argv[2])
bad: list[str] = []
missing: list[str] = []
ok = 0
with zipfile.ZipFile(wheel) as zf:
    for info in zf.infolist():
        if info.is_dir():
            continue
        target = dest / info.filename
        if not target.exists():
            missing.append(info.filename)
            continue
        data = target.read_bytes()
        if len(data) != info.file_size or zlib.crc32(data) != info.CRC:
            bad.append(f"{info.filename} (size {len(data)} vs {info.file_size}, "
                       f"crc {'mismatch' if len(data) == info.file_size else 'n/a'})")
        else:
            ok += 1
print(f"verified OK   : {ok}")
print(f"missing       : {len(missing)}")
for m in missing[:20]:
    print(f"    {m}")
print(f"corrupt       : {len(bad)}")
for b in bad[:20]:
    print(f"    {b}")
sys.exit(0 if not bad and not missing else 1)
