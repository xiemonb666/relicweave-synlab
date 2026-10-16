"""Poll for prerequisite A landing: ``synlab.pipeline`` imports AND ``_stamp_obs_semantics`` exists.

Writes one line per poll to ``data/a12_trainable/logs/prereqA_poll.log`` and exits as soon as the
check passes (exit 0) or the budget runs out (exit 2).  Nothing outside that log is modified.

The check runs in a *subprocess* so that a half-written ``synlab/pipeline.py`` (the file is being
edited concurrently by another work stream) cannot poison this process, and so that a
``SyntaxError`` in the middle of their edit is reported as a plain ``import_error`` instead of
killing the poller.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LOG = REPO / "data" / "a12_trainable" / "logs" / "prereqA_poll.log"
INTERVAL_S = 90
BUDGET_S = 25 * 60
PIN = REPO / "synlab" / "pipeline.py"

PROBE = (
    "import sys; sys.path.insert(0, r'{repo}');"
    "import synlab.pipeline as p;"
    "print('HELPER=' + ('1' if hasattr(p, '_stamp_obs_semantics') else '0'));"
    "print('V2=' + ('1' if getattr(p, 'OBS_SEMANTICS_V2', None) == 'physical_side_v2' else '0'))"
)


def probe() -> tuple[bool, str]:
    code = PROBE.format(repo=str(REPO))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(REPO))
    if out.returncode != 0:
        tail = (out.stderr or "").strip().splitlines()
        return False, "import_error=" + (tail[-1][:160] if tail else f"rc={out.returncode}")
    helper = "HELPER=1" in out.stdout
    v2 = "V2=1" in out.stdout
    return (helper and v2), f"import_ok=True helper={helper} obs_semantics_v2={v2}"


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    polls = 0
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== poll session start {time.strftime('%Y-%m-%d %H:%M:%S')} "
                 f"budget={BUDGET_S}s interval={INTERVAL_S}s ===\n")
        fh.flush()
        while True:
            polls += 1
            ok, detail = probe()
            mtime = PIN.stat().st_mtime if PIN.exists() else 0.0
            elapsed = round(time.time() - started, 1)
            line = (f"poll={polls} t+{elapsed}s pipeline_mtime="
                    f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))} {detail}")
            fh.write(line + "\n")
            fh.flush()
            print(line, flush=True)
            if ok:
                fh.write("RESULT: PREREQ_A_LANDED\n")
                fh.flush()
                return 0
            if time.time() - started + INTERVAL_S > BUDGET_S:
                fh.write("RESULT: PREREQ_A_STILL_MISSING_AFTER_BUDGET\n")
                fh.flush()
                return 2
            time.sleep(INTERVAL_S)


if __name__ == "__main__":
    raise SystemExit(main())
