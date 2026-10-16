# RelicWeave · SynLab (A12)

`relicweave-synlab` is the A12 synthetic-data, observation, degradation, relation, training,
diagnostics and release module in the broader RelicWeave effort. It is not the whole project and
does not own the CAD or fracture-solver kernels. The workspace has three independently installable
parts: [VesselForge](https://github.com/xiemonb666/vesselforge) builds vessel geometry and asset packages;
[PG-Frag](https://github.com/xiemonb666/pgfrag) hosts mechanics and fracture-solver experiments; SynLab consumes
geometry/material/pattern inputs and builds the observation and data workflows around them. Their
current boundaries and evidence are summarized in the [workspace handover](docs/handover/20261016/START_HERE.md).

The broader target covers both everyday and archaeological vessels, with source-grounded form,
surface materials, meaningful ornament, and eventual physical-fracture evidence. Existing A12
coverage of procedural controls remains useful, but a registered synthetic family, a passing
geometry check, or a convincing preview does not establish a match to a real object. Development
is currently paused; the [A12 status and handover](docs/handover/20261016/A12_STATUS.md) records
the latest accepted slice and remaining work.

## Install SynLab

Use CPython 3.11–3.13. The installable project name is `relicweave-synlab`; the `synlab` command
is its console entry point. From this directory, create or activate a virtual environment, then
install the package and its test tools:

```powershell
# If the Python launcher is available:
py -3.12 -m venv .venv
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -e ".[test]"

& $py -m synlab.cli --help
& $py -m synlab.cli doctor --json
& $py -m synlab.cli registry
& $py -m synlab.cli validate --config configs/a12/sandbox.yaml --json
```

If `py -3.12` is not available, use the path to an installed CPython 3.11–3.13 executable to
create the environment. `doctor` performs capability checks and writes the machine-specific
reports at `docs/a12/env_report.json` and `docs/a12/backend_capabilities.json`. It may report
optional native capabilities as missing; those are not synthesized by a fallback.

The base installation declared in `pyproject.toml` includes NumPy, SciPy, scikit-image,
OpenCV-headless, Pillow, pandas/pyarrow, trimesh/manifold3d, Shapely and the schema/API packages.
The extras are separate:

| Install extra | Adds | Use |
|---|---|---|
| `test` | pytest | Tests and focused checks |
| `external` | Gmsh, Open3D, pycolmap, faiss-cpu | Optional meshing, geometry, reconstruction and indexing routes |
| `train` | PyTorch (the project declaration pins 2.5.1) | SynLab training API; choose a compatible CPU/CUDA build for the host before relying on hardware claims |

For example, install the optional external integrations with `& $py -m pip install -e ".[external,test]"`.
`requirements.lock.txt` is a host `pip freeze` snapshot dated 2026-10-02, not a lock regenerated
from the current `pyproject.toml`: it records `torch==2.11.0+cu128`, while the `train` extra
declares `torch==2.5.1`. Treat it as historical environment evidence and resolve that mismatch
deliberately when reproducing a specific runtime.

## Optional native runtimes

SynLab extras do not install the other two projects' native toolchains:

| Capability | Where it is declared or supplied | Boundary |
|---|---|---|
| VesselForge native CAD | `vesselforge/pyproject.toml` declares CadQuery `>=2.8,<2.9`, which supplies the OpenCascade/OCP CAD stack. | CAD generation is a VesselForge capability, not part of SynLab's base install. |
| VesselForge VTK previews | The workspace's versioned `third_party/vesselforge-runtime` environment. | VTK is not declared as a SynLab extra; it is a renderer dependency and does not replace native CAD. |
| PG-Frag Peridynamics.jl | Julia 1.10.x plus the pinned headless environment documented in [PG-Frag's headless backend guide](https://github.com/xiemonb666/pgfrag/blob/backup/forge-work-20261003/docs/headless_backend.md); install Julia separately. | PG-Frag has its own Python package and runtime configuration. |
| PG-Frag Akantu | Separate Linux/WSL Akantu runtime under `third_party/akantu-runtime` for the relevant experiments. | Not installed or enabled by a SynLab pip extra. A weak-seam/control run is not calibrated ceramic fracture evidence. |

Install VesselForge separately so its native CAD dependency stays isolated from the SynLab
environment. From this directory:

```powershell
Push-Location ..\vesselforge
py -3.12 -m venv .venv
$vf = ".\.venv\Scripts\python.exe"
& $vf -m pip install -e ".[test]"
Pop-Location
```

The local VTK preview environment is intentionally separate from that command. Consult the
experiment README for its exact renderer invocation and the matching interpreter; installing
`relicweave-synlab` alone does not provide the VTK runtime. PG-Frag's own setup and runtime
variables are in [PG-Frag's README](https://github.com/xiemonb666/pgfrag). PG-Frag is a separate Python package
with a Julia 1.10.x runtime requirement; its local headless Peridynamics.jl backend has its own
runtime and depot settings. Native Akantu experiments use the Linux/WSL environment under
`third_party/akantu-runtime` and their experiment-specific scripts rather than the SynLab CLI.

## SynLab entry points

The CLI exposes configuration validation and resource estimates, generation and run audits,
registry/geometry-pattern/degradation audits, pool and release operations, export, training,
evaluation, diagnostics, episodes, resume and acceptance. Inspect the current command surface
with `synlab --help`; the command implementations live in `synlab/cli.py`.

Common checks and the bounded synthetic sandbox are documented in
[`docs/a12/runbook.md`](docs/a12/runbook.md). Useful starting commands are:

```powershell
& $py -m pytest tests -q
& $py -m synlab.cli doctor --json
& $py -m synlab.cli validate --config configs/a12/sandbox.yaml --json
& $py -m synlab.cli budget --config configs/a12/sandbox.yaml --json
& $py -m synlab.cli generate --config configs/a12/sandbox.yaml --json
& $py -m synlab.cli acceptance --profile SANDBOX_CORE --json
```

Generation, acceptance and `doctor` can write reports or data under their configured output roots.
Read the runbook and the current status page before running them against an existing store. The
earlier source-resolution slice recorded 55 passing checks. The pause delivery adds a separate
90-test A12 focused check, alongside VF 66 and PG 55 (211 total); commands and exact scope are in
[PAUSE_VALIDATION.json](docs/handover/20261016/PAUSE_VALIDATION.json). Neither result claims the
entire test suite or A12 acceptance profile passes. Development and solver runs remain paused.

## Current A12 slice

The existing A12 platform remains in scope: 24 procedural mother families, the M01–M12 material
catalog, 16 pattern families, fracture/observation/degradation routes, relations, episodes,
training and release tooling. Their registered breadth is a controllable synthetic baseline, not
24 real-vessel validations. Recent work adds source-guided geometry/material/pattern composition
on actual VesselForge candidate shapes and a bounded blue-and-white panel study. See the
[dated A12 evidence table](docs/handover/20261016/A12_STATUS.md), the
[workspace continuation status](docs/continuation/20261016/STATUS.md), and the experiment notes
under `experiments/continuation_20261016/`.

The latest source-resolution mode, `source_resolved_stationary_v1`, is opt-in. It preserves the
stationary part of the Met 50899 fired-photo mask at source resolution and samples the transported
mobile part from the finite-volume grid. The legacy grid-bilinear mode remains the default. This is
a source-image appearance proxy and a sampling-resolution experiment; it is not a complete
historical motif reconstruction, pre-firing pigment recovery, calibrated diffusion chemistry,
optical calibration, or a real-vessel material measurement.

## Repository layout

```text
synlab/       A12 schemas, storage, jobs, mothers, materials, patterns, fracture, observation,
              degradation, relations, training, diagnostics, API and CLI
configs/a12/  Generation, training, diagnostics, pool and QA configurations
tests/        Unit, property, contract, integration and focused source-guided checks
experiments/  Versioned, replayable experiments and their bounded output bundles
docs/a12/     A12 architecture, interfaces, contracts, audits and runbook
docs/handover/20261016/A12_STATUS.md  Current scoped evidence and remaining work
```

The A12 plan, APIs and acceptance harness describe software capabilities. Source qualification,
material calibration, physical fracture qualification, training eligibility and release
readiness are separate evidence gates; consult the dated status before making those claims.

## Pause handover and shared workspace

Start with the [developer handover](docs/handover/20261016/DEVELOPER_HANDOVER.md),
[evidence index](docs/handover/20261016/EVIDENCE_INDEX.md), and
[document review](docs/handover/20261016/DOCUMENT_REVIEW.md). The updated
[V1.48 engineering plan](docs/master/20261016/RelicWeave_V1.48_Engineering_Update_20261016.docx)
preserves the original research contracts and dates historical results explicitly.

Clone the three repositories as siblings. On Windows, use `git clone -c core.longpaths=true`
for the archived long source paths (see the restore guide for complete commands).
Shared scripts, small evidence, and dependency setup
metadata are preserved in `workspace_support/`; use its [restore guide](workspace_support/README.md)
to reconstruct the workspace paths without overwriting existing differing files. Solver runtimes,
SDK binaries and large raw histories stay external; their inventory and hashes are in the
[repository inventory](docs/handover/20261016/repository_inventory/SUMMARY.md).
Full qualified physical-fracture packages: **0**. Prepared native runs remain unstarted.

Dependency licenses and object-level image/model licenses apply separately. Keep provenance,
attribution, refinement and review records with each reused resource. This repository currently
has no project-level `LICENSE` file; upstream licenses do not license this project's code.
