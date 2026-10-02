"""Count pass/fail/skip markers in the recorded pytest -q logs (no assertions here)."""
import json
import pathlib
import re

base = pathlib.Path("data/a12/reports/fracture_surface_signal")
for row in json.loads((base / "pytest_files.json").read_text(encoding="utf-8")):
    text = pathlib.Path(row["log"]).read_text(encoding="utf-8", errors="replace")
    # the progress line is the only place pytest -q writes the markers
    marks = ""
    for line in text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"[.xFsE]+ +\[\s*\d+%\]", stripped):
            marks += stripped.split()[0]
    print(f"{row['file'].split('/')[-1]:44s} exit={row['exit_code']} "
          f"passed={marks.count('.')} xfail={marks.count('x')} skipped={marks.count('s')} "
          f"failed={marks.count('F')} errors={marks.count('E')}")
