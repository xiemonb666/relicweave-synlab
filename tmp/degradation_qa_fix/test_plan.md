# Physical QA fix — one-shot targeted test plan

Prepared in `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab`; no tests have been run for this frozen source.

After root reviews the listed diff and explicitly releases execution, run exactly once:

```powershell
pytest -q tests/a12/operators/test_postassembly_qa_20261003.py tests/a12/degrade/test_physical_acceptance_20261004.py
```

The new tests cover: operator effect retained separately from postassembly acceptance; truth update blocked on QA failure or explicit false acceptance; P04 declared-target override gated by physical QA while clean truth remains referenced; audit rejection of missing/UNKNOWN status and PASS with false/None acceptance; valid P06 and valid L0 identity behavior; inverted L0 rejection; P03 unqualified wall probe reporting UNKNOWN at the declared 0.6 mm guard; NaN depth preflight before the geometry operator; and incomplete unsigned nearest-surface samples reported UNKNOWN with requested/finite/missing counts rather than zero.

The new P03 tests stub surface construction/intersection and postassembly geometry checks. The new API propagation, axis override, appearance, identity, audit, and distance tests do not invoke Boolean or solver routes. The pre-existing postassembly module includes its existing P02 operator routes; preserve the requested no-test/no-native/Boolean hold until root has reviewed and released the exact batch above. No broad suite is planned in this phase.

This is a plan only. Results are intentionally absent because execution is awaiting root review.