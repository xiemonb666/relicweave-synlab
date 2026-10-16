"""Extract a wheel into site-packages directly, resumably.

pip unpacks the 2.75 GB torch wheel inside one long-lived process, which this host kills
(exit -1) part-way through.  Unpacking here is idempotent and skips files that are already
fully written, so re-running after a kill continues instead of starting over.

Usage: python extract_wheel.py <wheel> <site-packages> [--log <file>]
"""

from __future__ import annotations

import argparse
import sys
import time
import zipfile
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("wheel")
    ap.add_argument("site_packages")
    ap.add_argument("--log", default=None)
    ap.add_argument("--every", type=int, default=500)
    args = ap.parse_args()

    wheel = Path(args.wheel)
    dest = Path(args.site_packages)
    log_path = Path(args.log) if args.log else None

    def log(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        if log_path:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    log(f"opening {wheel} ({wheel.stat().st_size / 1024**2:.1f} MB)")
    written = skipped = 0
    total = 0
    t0 = time.perf_counter()
    with zipfile.ZipFile(wheel) as zf:
        members = zf.infolist()
        total = len(members)
        for i, info in enumerate(members, 1):
            target = dest / info.filename
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists() and target.stat().st_size == info.file_size:
                skipped += 1
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    while True:
                        chunk = src.read(1 << 22)
                        if not chunk:
                            break
                        out.write(chunk)
                written += 1
            if args.every and i % args.every == 0:
                log(f"{i}/{total} entries  written={written} skipped={skipped} "
                    f"({time.perf_counter() - t0:.0f}s)")
    log(f"DONE {total} entries  written={written} skipped={skipped} "
        f"in {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
