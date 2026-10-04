# Akantu cohesive diagnostics — 2026-10-04

## Read-only topology and time-series review

The read-only analyzer exited 0 and did not invoke the solver. All 96/96 tetrahedra had positive signed volume. Input topology had 80 boundary and 152 internal faces; after insertion of eight coh6 elements it had 96 boundary and 144 internal faces, with 384 face slots conserved. Each coh6 local ordinal mapped exactly to its ancestor and rest coordinates; no nearest-coordinate matching was used. The nominal mode-I response is mixed-mode. The prior coarse and half-dt runs first showed negative dissipated output at steps 652 and 1299 respectively; their integration cause remains UNKNOWN.

The analyzer source is `../pgfrag/experiments/cohesive_diagnostics_20261004/diagnose_cohesive.py` (33,028 bytes, SHA-256 `5ddc66dfd7d8b585a35dda9a2b9f12c5ddafa11d08ccf6f1817eb4af1ab1aa7d`). Its exact argv was:

```text
C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\.venv\Scripts\python.exe C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\cohesive_diagnostics_20261004\diagnose_cohesive.py
```

The source report was 1,752 bytes, SHA-256 `ca743c4d92665e2604f09366096e71d00f8c8429d265811613609c77ba12eea0`; the exact copy and a structured receipt are in [the evidence index](evidence/20261004/index.md). The 144,879-byte derived diagnostics JSON remains in `tmp` and was not copied. Large traces, topology NPZs and dense states are also excluded from the evidence bundle.

## Event probe: early stop, diagnostic only

Run `coarse654_20261004_01` made one solver attempt, zero retries, 654/1707 steps in 2.932817 seconds, external exit 0, then stopped at the configured cap. The status is `DIAGNOSTIC_EARLY_STOP_NOT_COMPLETE`. The captured native phase window is steps 647–654, not a complete case. Baseline comparison covered rows 1–654: energy, mass, reaction and count fields matched exactly (all maximum absolute differences zero); position comparison is UNKNOWN because per-step baseline position frames are absent.

Eight facets were inserted at step 650. Step 651 phase D reported +1.7262621338279373e-7 J; step 652 phase D first reported −5.572968137645039e-5 J, two solver steps after insertion. At step 652 phases A/B/C remained +1.7262621338279373e-7 J, while reversible energy changed from +1.9561041022326483e-7 J before D to 0 after D. This is temporal association, not a demonstrated cause. Across 32 native opening/traction samples, step 651D to 652D mean xy opening changed from 0.156 to 350.186 nm, mean |z| from 1.298 to 20.391 nm, and maximum traction norm from 143.978 MPa to 0. Damage/history and the native material update phase remain UNKNOWN. A zero traction observation alone does not establish full damage or a crack event.

The accepted probe evidence is a bounded diagnostic, not physics PASS. API review lists `cohesive contact` as the native energy key; its value was 0 in this window. Legacy `contact` also returned 0, but alias versus unknown-key fallback semantics are UNKNOWN, so it is not a verified selector and neither zero establishes dissipated-energy validity. The driver, frozen inputs and manifest hash-match their pre-run snapshots; see the execution receipt and integrity evidence in [the evidence index](evidence/20261004/index.md). The concise `probe_conclusion.json` is a post-processed derived summary, not the original native receipt; the original receipt is separately preserved.

## Route and next gate

Pause promotion and repeated parameter tuning of the current freely evolving extrinsic tiny case while retaining its results. The next gate is a planned controlled native constitutive-patch benchmark with pure normal opening, pure shear, mixed loading, and unloading/reloading under known separation histories. It must independently confirm native opening/traction/damage/history support and check GcA, separate from free-dynamics response. A separate controlled `cohesive_bilinear` task is currently running/initializing; this note does not accept its result or claim a pass.

Akantu intrinsic `cohesive_bilinear` with a finite initial elastic segment δ0 is a candidate because the [Akantu 5.0.7-post1 model documentation](https://akantu.readthedocs.io/en/v5.0.7-post1/manual/models.html) and [v5.0.7 bilinear source](https://gitlab.com/akantu/akantu/-/raw/v5.0.7/src/model/solid_mechanics/solid_mechanics_model_cohesive/materials/constitutive_laws/material_cohesive_bilinear.cc) describe the model; the 3D wheel still needs an actual preflight, and this is not a production adoption. Added interface compliance and tetrahedral-face direction sensitivity require measurement. The [v5.0.7 linear cohesive source](https://gitlab.com/akantu/akantu/-/raw/v5.0.7/src/model/solid_mechanics/solid_mechanics_model_cohesive/materials/constitutive_laws/material_cohesive_linear_inline_impl.hh) shows direction-dependent stiffness near zero opening; that makes “bulk CFL alone may not ensure cohesive integration accuracy” a hypothesis to test, not an established cause, and the tag source is not asserted to be the exact post1 wheel implementation.

Do not add global x/y anchors or claim success by repeatedly reducing dt. Wall thickness t/h addresses only one geometric-resolution question; also check the chosen law's fracture-characteristic/process-zone/regularization scale and the spatial and temporal resolution required by its initial interface stiffness. Neither a bulk CFL nor finite h0.5 geometry QA establishes cohesive physical adequacy. The general engineering boundary also applies: whole-mesh rotation is not independent-remesh bias control; interface insertion is not full failure or physical R2; geometry QA and `Measurement.valid` are not physics/data admission.

## Provenance

- Read-only report: `tmp/review_20261004/implementation/cohesive_diagnostics_20261004/report.txt`, 1,752 bytes, SHA-256 `ca743c4d92665e2604f09366096e71d00f8c8429d265811613609c77ba12eea0`.
- Derived diagnostic JSON: `tmp/review_20261004/implementation/cohesive_diagnostics_20261004/cohesive_diagnostics.json`, 144,879 bytes, SHA-256 `155729813532452b49eb77d1ee6cb1bbc8e68502883473c8b791ce7e2a1cefca`; retained in `tmp`, not copied.
- Event run: `coarse654_20261004_01`; full WSL command, exit, source/input hashes and snapshot integrity are preserved in the evidence copy of `execution_receipt.json` and related JSON/JSONL artifacts.
- The 97,463-byte `phase_evidence.jsonl` is preserved byte-exact. The large CSV, NPZ, dense states, and repeated preflight output are not in the small evidence bundle.
