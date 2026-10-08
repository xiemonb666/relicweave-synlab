# Physical QA fix v2 — review and one-shot test plan

This version adds the narrowband adapter acceptance gate and truthful raw-effect propagation. It also fixes the P04 test fixture by carrying the same top-face `ORIGIN_INTERFACE` and `interface_id=1` face channels as the existing closed-box fixture.

No v2 tests have been run. The failed v1 `run_01` artifacts and `freeze_manifest_v1.json` remain unchanged.

After root reviews `prepared_diff_v2.patch` and `new_test_v2.diff` and explicitly releases execution, run once from `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab`:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/a12/operators/test_postassembly_qa_20261003.py tests/a12/degrade/test_physical_acceptance_20261004.py
```

Save the run to `tmp/degradation_qa_fix/run_02/` with stdout, stderr, argv, exit code, and before/after SHA-256 values for the six production/test files listed in the freeze manifest. Do not rerun automatically if it fails; retain the evidence for root review.