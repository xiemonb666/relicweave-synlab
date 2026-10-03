# Akantu cohesive capability spike — 2026-10-04

## Decision

The isolated Akantu 5.0.7.post1 runtime demonstrated **3D dynamic extrinsic cohesive insertion and paired native connectivity on one fixed contract interface**. This is a narrow backend capability pass only. The loaded runs **fail the signed cohesive-energy acceptance check**: native dissipated energy is negative, and neither run reaches the frozen `Gc·A` energy target. The runner's `getEnergy('contact')` selector is not verified by the reviewed API source, so that channel and any derived energy-ledger interpretation are **UNKNOWN**. Timestep/full-debond acceptance is therefore **NOT_REACHED**; damage/full-failure and exposed-fracture status are **UNKNOWN**. This does not qualify the backend for rough ceramic fracture or physical R2 truth labels. Keep the PD baseline.

The test's central `z=2 mm` interface is explicitly a declared API/contract surface (8 triangular facets, area `4e-6 m²`), not a free physical crack path. Insertion of 8 potential cohesive facets proves topology construction; it does not prove that those facets fully failed or became exposed fracture surfaces.

## Runtime, inputs, and provenance

The upstream PyPI wheel metadata identified `akantu-5.0.7.post1-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`; downloaded and local wheel SHA-256 both equal `f618c31bb4cdf23d86e74a10f7e94dac3dae7b0ae2cfd057d352c1b156c0654b`. The wheel was installed in `third_party/akantu-runtime/venv` under WSL Ubuntu 2, Python 3.12.15 (base WSL Python 3.14.4); import and a 3D preflight both exited 0. No Docker was used. Installation and preflight records are in [runtime_install_evidence.json](evidence/20261004/copies/cohesive/runtime_install_evidence.json), [preflight.json](evidence/20261004/copies/cohesive/preflight.json), and [api_probe.json](evidence/20261004/copies/cohesive/api_probe.json).

The frozen mesh has 96 tetrahedra, 45 initial nodes, body dimensions `2×2×4 mm`, volume `16e-9 m³`, and a single declared 8-facet central interface. Material parameters are toy and unvalidated: `ρ=2500 kg/m³`, `E=70 GPa`, `ν=0.22`, `Gc=7.6 J/m²`, `σc=70 MPa`, `β=3`, `δc=2.1714285714285712e-7 m`; units are SI. Parameters/load were frozen before the recorded runs in manifest SHA-256 `21b563069550e2091474fe94877bd3ceaae094ac4c92aed3900ecdd94702dd68` ([canonical manifest copy](evidence/20261004/copies/cohesive/manifest.json)); the frozen mesh and material inputs are also preserved in the evidence bundle. Expected full-interface dissipation is `Gc·A = 3.04e-5 J`; end time is `1e-4 s`.

Each run status contains `source_file_sha256=67dd1eb98acc5f5369b9cbf1a9bfbd7f6681068172e537768e788274cb10652d`. The current `pgfrag/experiments/cohesive_capability/run_contract.py` is 29,542 bytes and independently hashes to that same SHA-256; the runner itself computes its SHA with `sha256(Path(__file__))`. The canonical manifest's `source_sha256.run_contract.py` entry matches this runner digest; the manifest file itself has SHA-256 `21b563069550e2091474fe94877bd3ceaae094ac4c92aed3900ecdd94702dd68`. Thus the retained runner bytes are hash-matched to all three case records. This closes executed-source provenance only; full experiment reproducibility has not been accepted, and no independent-machine replay or complete environment package is claimed. Post-run review/visualization is separate in `postprocess_contract.py`, `render_preview.ps1`, and `api_semantics_review.json`; the render script only reads saved traces/JSON and did not invoke the solver.

There was one preliminary `zero_load` invocation that exited 1 with `KeyError('expected_insertion_facets')` before any solve step because the first manifest revision omitted runner metadata. Its argv/traceback are retained in `zero_load_command.log`; `manifest_revision_event.json` records the metadata-only correction. The corrected zero-load case below then exited 0. No material or loading parameters were changed to find a passing result.

## Recorded solver cases

All three completed cases used WSL argv of the form:

```text
wsl -d Ubuntu -- bash -lc cd '/mnt/c/Users/xiemo/Desktop/ShardForge/pgfrag/experiments/cohesive_capability' && '/mnt/c/Users/xiemo/Desktop/ShardForge/third_party/akantu-runtime/venv/bin/python' 'run_contract.py' '<case>'
```

Exact argv and exits are in `zero_load_retry1_command.log`, `modeI_dt_command.log`, and `modeI_dt2_command.log`; all final case exits were 0. Each ran to the same `1e-4 s` end time, within the 10,000-step/300-second limits.

| Case | dt (s) | Steps | Dynamic insertion | Native `dissipated` final (J) | Energy ledger residual / external-work estimate |
|---|---:|---:|---:|---:|---:|
| zero load | `5.8582308142940834e-8` | 1707 | 0; 45 nodes; 96 tets | 0 | 0 J; external work 0 |
| mode-I, dt | `5.8582308142940834e-8` | 1707 | 8 at step 650 (`3.807850029291154e-5 s`); 45→54 nodes; 96 tets unchanged | `-5.572968137645039e-5` | `-9.01043008991664e-6 J` (`-1.788686%`); work estimate `5.037457682805293e-4 J` |
| mode-I, dt/2 | `2.9291154071470417e-8` | 3414 | 2 at step 1297 and 6 at step 1300; total 8; 45→54 nodes; 96 tets unchanged | `-9.726359554870569e-6` | `-1.2001214499001876e-6 J` (`-0.239400%`); work estimate `5.013039202350114e-4 J` |

Both loaded cases have target `+3.04e-5 J`, do not reach it, and store no damage/full-failure output. Their signed relative errors against target are 2.833213 and 1.319946; no `abs()` correction was applied. The final signed values differ by `4.6003321821579815e-5 J` (82.547% of the coarse run's absolute value). This is a negative-dissipation contract failure plus a not-reached energy gate, not a fully debonded convergence pass. The root's ≤1% timestep criterion cannot be assessed as a full-debond result because neither run is fully debonded by an independently observed failure state.

**Energy-key caveat:** `run_contract.py` requests `model.getEnergy('contact')`. The reviewed Akantu v5.0.7 `MaterialCohesive::getEnergy` source recognizes `dissipated`, `reversible`, and `cohesive contact`; it does not establish `contact` as a valid selector. Whether the installed 5.0.7.post1 wheel throws or silently returns a fallback for this unknown key is unverified. Therefore the reported contact-energy channel and energy-ledger residuals are diagnostic only / **UNKNOWN**, even though the raw signed `dissipated` values and target comparison above remain recorded. This does not change the manifest's physical contact nonclaim: **NOT_RUN**. Raw traces/status records are preserved without rewriting.

For the zero and loaded runs, the lumped mass sum for each coordinate component is `4.0e-5 kg`, matching `ρV=2500×16e-9=4.0e-5 kg`; each component is conserved exactly across insertion. Summing all three DOF columns gives `1.2e-4 kg` and is a repeated-DOF sum, not the body's total mass. The trace retains external-work estimate, kinetic energy, bulk potential, signed cohesive dissipation/reversible/contact terms, residual, force, displacement, and mass histories. Contact is `NOT_RUN`.

## Native insertion and lineage evidence

Preflight observed no initial cohesive elements and an initialized stable time step of `7.326084549265489e-8 s`. Loaded traces show actual native connectivity growth and nonzero API insertion counts, with 8 cohesive elements total. On the frozen contract mesh, postprocessing used native bulk element IDs plus local vertex ordinals and cohesive connectivity, not nearest-coordinate matching: it checked 384 `(bulk cell ID, local ordinal)` pairs, found 0 mapping conflicts, mapped all 54 post-insertion current bulk nodes to the 45 original material nodes, and back-mapped all 96 post-insertion bulk rows. In the loaded case, 24 bulk connectivity rows changed and 72 remained unchanged; the run-specific mapping remained conflict-free. This is exact lineage evidence for this retained mesh snapshot only. A general persistent parent/material ID contract for production meshes remains **UNKNOWN**; the installed Python probe did not expose a parent/event/origin API.

The 8 native cohesive pairs each map to the declared central input face with one adjacent bulk parent per side. Both rest-side area sums are `4e-6 m²` (zero area error), paired rest gap is zero, and parent-derived outward normals on the two sides are opposite. The fragment manager reports 2 fragments for this toy interface; this does not establish a production fragment count. These facts prove paired-surface topology/ancestry for the contract mesh, not damage state or a physically exposed crack.

## API/source semantics review

The retained read-only review is [api_semantics_review.json](evidence/20261004/copies/cohesive/api_semantics_review.json). It uses five SHA-verified official source files from Akantu tag `v5.0.7`, commit `5a4215a100dc3e73eb031b1358740147178563e2`, listed in `third_party/akantu-runtime/source-v5.0.7/source_manifest.json`. The installed wheel is `5.0.7.post1`; exact source/build correspondence between that wheel and the inspected `v5.0.7` tag is **UNKNOWN**.

In the reviewed tag, `SolidMechanicsModel::getEnergy("potential")` sums material energy, while `MaterialCohesive::getEnergy` returns values for `dissipated`, `reversible`, and `cohesive contact`, not `potential`; this supports that the experiment's bulk-potential and separate cohesive reversible/contact terms are not double-counted in that source version. `getEnergy("external work")` calls `getExternalWork()`, which forms a constrained force/velocity contribution and multiplies by `dt` for dynamics; it is a per-call increment, not an accumulated history. The experiment did not use it as the external-work trace: `external_work_J` is a separate boundary reaction/displacement estimator.

The runner requests the cohesive energy selector as `getEnergy("contact")`, while the reviewed source only establishes `"cohesive contact"`. The installed wheel's handling of the unsupported `"contact"` key is **UNKNOWN**; a reported zero may be a fallback rather than a measured energy. Treat this channel and ledger residuals as UNKNOWN. Physical contact interaction remains **NOT_RUN**; do not alter the raw trace or status to reinterpret it.

The inspected cohesive source's insertion check stores insertion stress and the current facet traction as previous traction, and the cohesive model copies nodal states using its new-node event. The installed Python API does not expose that event. Exact installed-wheel initial cohesive energy initialization and the cause of negative native dissipation remain **UNKNOWN**. Official documentation and examples describe cohesive insertion and expect positive dissipated energy, but do not resolve the negative native result observed here. References: [Akantu cohesive insertion](https://akantu.readthedocs.io/en/stable/manual/solidmechanicsmodel.html#insertion-of-cohesive-elements), [Akantu examples](https://akantu.readthedocs.io/en/latest/examples.html), [PyPI wheel metadata](https://pypi.org/project/akantu/).

## Gate summary and evidence

| Gate | Result |
|---|---|
| 3D Akantu dynamic extrinsic insertion on fixed contract surface | PASS (narrow capability only) |
| Zero-load no insertion / zero energy | PASS |
| Mass conservation | PASS, each coordinate-component sum |
| Contract-mesh paired native connectivity, area, rest gap, and run-local material map | PASS for this fixed mesh only |
| General production parent/material lineage API | UNKNOWN |
| Native signed cohesive dissipation / `Gc·A` ±1% | FAIL / NOT_REACHED; raw native output is negative |
| Independent full-failure/damage/exposed-fracture proof | UNKNOWN |
| Full-debond timestep refinement | NOT_REACHED; not a pass |
| Contact | NOT_RUN |
| Roughness / real ceramic parameters / real-fracture qualification | NOT_VALIDATED / UNVALIDATED_TOY |
| GPU | UNKNOWN |

The review PNG is [cohesive_capability_preview.png](evidence/20261004/copies/cohesive/cohesive_capability_preview.png), 143,793 bytes, SHA-256 `b5bee415ee9916c4b2a98c0029fe8f6f788e009d32f57ba6bd46152169fc3638`. It plots the actual saved force/displacement and energy histories plus the native deformed interface projection; displacement is not visually magnified. Byte-exact copies of the three case statuses, runner, frozen inputs, commands, API/runtime records, and visualization data are listed in the [evidence index](evidence/20261004/index.md). The full contract review remains in the local evidence source tree; a hash-linked structured extract is in the bundle.
