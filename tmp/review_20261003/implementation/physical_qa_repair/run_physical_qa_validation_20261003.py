from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path.cwd()
OUT = ROOT / "tmp/review_20261003/implementation/physical_qa_repair"
OUT.mkdir(parents=True, exist_ok=True)
PYTHON = str((ROOT / ".venv/Scripts/python.exe").resolve())
commands = {
    "postassembly_and_damage_legality": [
        PYTHON, "-m", "pytest", "-q",
        "tests/a12/operators/test_postassembly_qa_20261003.py",
        "tests/a12/operators/test_damage_legality.py",
    ],
    "existing_narrowband_operator_suite": [
        PYTHON, "-m", "pytest", "-q",
        "tests/a12/operators/test_narrowband.py",
    ],
    "recovered_label_axis_control": [
        PYTHON, "-m", "pytest", "-q",
        "tests/a12/degrade/test_axis_routing_audit.py::test_operator_audit_route_and_production_route_agree_on_p03",
    ],
}
records = {}
for name, argv in commands.items():
    completed = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", check=False)
    output = completed.stdout
    log_path = OUT / f"{name}.log"
    log_path.write_text(output, encoding="utf-8")
    progress = "".join(
        match.group(1) for line in output.splitlines()
        if (match := re.match(r"^([.FEsx]+)(?:\s+\[\d+%\])?$", line.strip())))
    summary = progress or next((line.strip() for line in reversed(output.splitlines())
                                if re.search(r"\b(passed|failed|skipped)\b", line)), "")
    counts = {"passed": progress.count("."), "failed": progress.count("F"),
              "error": progress.count("E"), "skipped": progress.count("s"),
              "xfailed": progress.count("x"), "total": len(progress)}
    records[name] = {
        "argv": argv,
        "cwd": str(ROOT),
        "exit_code": int(completed.returncode),
        "summary": summary,
        "counts": counts,
        "log": log_path.name,
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
    }

manifest = OUT / "validation_runs_20261003.json"
manifest.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({"manifest": str(manifest), "runs": records}, indent=2, sort_keys=True))
