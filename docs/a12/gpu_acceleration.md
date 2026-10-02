# GPU / CUDA acceleration (A12 synthesis chain)

Measured on this host on 2026-10-02. Every number below comes from a run whose artefact is
listed in the evidence table; nothing here is a capability claim without a measurement behind
it.

**Headline, stated up front:** CUDA torch is installed and verified, and it is genuinely fast
on dense tensor work (18x on fp32 matmul, 35x on a batched convolution). Blender's Cycles GPU
backend works and speeds up the *multi-sample* passes by 2.5-3.8x, **but the ≥3x end-to-end
target was not reached**: the delivered 12-view task gains about 1.0-2.1x, because three of the
six render passes the worker issues are 1-sample geometry passes on which the GPU is 3-5x
*slower*, and because each view is rendered by a fresh Blender process that pays a ~1 s device
initialisation.

---

## 1. GPU and driver facts

| fact | value | source |
|---|---|---|
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU | `nvidia-smi`, `torch.cuda.get_device_name(0)` |
| Compute capability | 12.0 (`sm_120`, Blackwell) | `torch.cuda.get_device_capability(0)` |
| SMs / VRAM | 26 SMs / 8150.6 MiB (8 GB) | `torch.cuda.get_device_properties(0)` |
| Driver | 596.21 | `nvidia-smi` |
| CUDA runtime reported by driver | 13.2 | `nvidia-smi` |
| System CUDA toolkit (`nvcc`) | absent - not needed, the wheel bundles its own runtime | `Get-Command nvcc` |
| Other compute devices | AMD Radeon(TM) 860M (HIP, integrated), AMD Ryzen AI 7 H 350 (CPU, 16 threads) | Cycles device enumeration |

The driver is far newer than any CUDA version the wheels below need, so the usual
"driver too old for `sm_120`" failure mode does not apply here.

## 2. CUDA torch: installation and verification

### 2.1 Result

```
torch                   2.11.0+cu128
torch.version.cuda      12.8
torch.cuda.is_available()   True
torch.cuda.get_arch_list()  ['sm_75','sm_80','sm_86','sm_90','sm_100','sm_120']
torch.cuda.get_device_name(0)  NVIDIA GeForce RTX 5060 Laptop GPU
```

`sm_120` is present in `get_arch_list()`, i.e. the wheel ships real SASS for this part and is
not silently falling back to PTX JIT.

### 2.2 Real tensor operations (not just a capability flag)

Source: `data/a12/reports/gpu/torch_cuda.json` (`blender_scripts/bench_torch_cuda.py`).

| operation | CPU | GPU | speed-up | numerical agreement |
|---|---|---|---|---|
| `matmul` fp32, 4096x4096 | 0.3709 s (370.5 GFLOP/s) | 0.02044 s (6722.9 GFLOP/s) | **18.1x** | max abs diff 1.11e-3, `allclose(rtol=1e-3)` True |
| `matmul` fp16, 4096x4096 | - | 0.004957 s (27725 GFLOP/s) | 74.8x vs CPU fp32 | - |
| `conv2d` batch 12x3x1024x768, 7x7, grouped | 0.2120 s | 0.00600 s | **35.3x** | max abs diff **0.0** (bit-identical) |
| 64 MiB host->device / device->host | - | 0.0132 s / 0.0395 s | - | one transfer costs more than many small kernels |

A first version of this benchmark reported 20 microseconds for the 4096^3 matmul (6.8 PFLOP/s).
That was a bug in the harness, not a result: the timing did not call `torch.cuda.synchronize()`
and therefore measured only the asynchronous kernel launch. The harness now synchronises, and
the bug is recorded in the function docstring so it is not reintroduced.

### 2.3 Version changes and rollback

`requirements.lock.txt` was updated on exactly three lines (no unrelated line touched):

| package | before | after | why |
|---|---|---|---|
| `torch` | 2.5.1+cpu | **2.11.0+cu128** | 2.5.1 predates `sm_120`; cu128 is the first CUDA line with Blackwell consumer SASS |
| `sympy` | 1.13.1 | 1.14.0 | torch 2.11 requires `sympy>=1.13.3` |
| `networkx` | 3.7 | 3.6.1 | resolved down by the torch 2.11 dependency set |

**Rollback to CPU torch**

```powershell
# 1. stop every process using the venv (see 2.4 - a mapped c10.dll blocks the swap)
# 2. restore the CPU build
.\.venv\Scripts\python.exe -m pip install "torch==2.5.1+cpu" `
    --index-url https://download.pytorch.org/whl/cpu
# 3. restore the two transitive pins
.\.venv\Scripts\python.exe -m pip install "sympy==1.13.1" "networkx==3.7"
```

Nothing in the repository *requires* CUDA torch: every `torch` import in `synlab/` is inside a
function or guarded, and `synlab/observe/blender.py` (the only file changed for the render side)
does not import torch at all. The GPU rendering path works with CPU torch installed.

### 2.4 Installation was the hard part - failure record, kept verbatim

The pin itself is unremarkable. What took the time was that the virtualenv is shared: at the
time of writing, **12 live processes had torch DLLs mapped**, and two other agents were
running their own `pip install ... torch` against the same venv.

Three attempts failed:

1. `pip install torch==2.11.0+cu128` ->
   `ERROR: Could not install packages due to an OSError: [WinError 5] ... torch\lib\c10.dll`
2. `pip install --force-reinstall torch==2.11.0+cu128` ->
   `[WinError 5] ... torch\lib\c10_cuda.dll`
3. After clearing the path, `pip` got as far as `Installing collected packages: torch` and was
   **killed by the host** (`exit -1`) while unpacking the 2.75 GB wheel.

Diagnosis (`data/a12/reports/gpu/_scratch/diag_torch_lock.py`):

```
create in lib/   : OK                 <- the directory is writable
rename c10.dll   : OK (not locked)    <- so it is not a delete/rename sharing violation
open-rw c10.dll  : FAIL PermissionError
```

The directory is writable and the DLLs can be *renamed*, but cannot be opened for writing,
because a live process has them mapped (`LoadLibrary` maps without `FILE_SHARE_WRITE`). This
is self-perpetuating: a broken torch loads `c10.dll` successfully and only then fails on
`caffe2_nvrtc.dll`, so **every failed `import torch` re-pins `c10.dll`**.

What worked, and is non-destructive to the other agents (no process was killed):

1. **Move the broken tree aside.** Renaming succeeds even while the DLLs are mapped, and the
   running processes keep their mappings (a mapping follows the handle, not the path).
   `_scratch/evict_broken_torch.py`.
2. **Unpack the wheel with a resumable extractor** instead of letting pip do it in one long
   process that the host kills. `_scratch/extract_wheel.py` skips files already written at the
   right size, so a re-run continues rather than restarts.
3. **Verify against the wheel's own CRCs**, because a resumed extraction after a kill can leave
   a file whose size matches but whose content does not.
   `_scratch/verify_extract.py` -> `verified OK: 11818, missing: 0, corrupt: 0`.

Because a second agent re-ran `pip install --force-reinstall` and clobbered the working tree
mid-session, the install had to be repaired twice with the same procedure. The cached wheel is
kept at `data/a12/reports/gpu/_wheels/torch-2.11.0+cu128-cp312-cp312-win_amd64.whl`; installing
from that file avoids a 2.75 GB re-download.

**Operational rule that follows from this:** installing torch into this venv must be
serialised across agents, and must not run while other venv processes are alive.

---

## 3. Blender Cycles GPU rendering

### 3.1 What was changed

`blender_scripts/render_worker.py`:

* `resolve_compute_device()` performs the handshake Cycles actually requires. Setting
  `scene.cycles.device = "GPU"` alone selects **no** device - the addon preference must also
  name the backend and mark the device `use = True`, otherwise Cycles renders on the CPU while
  the scene setting still reads "GPU". The function returns what it *measured* (backend
  selected, devices enabled), never what was requested.
* New config keys under `render`: `device` (`CPU` default, `GPU`, `AUTO`),
  `compute_device_type` (`AUTO` -> OPTIX, CUDA, HIP, ONEAPI, METAL in that order, or explicit),
  `gpu_require` (a GPU request that cannot be honoured raises `GPU_UNAVAILABLE` instead of
  silently falling back), `gpu_device_index`.
* `manifest.blender.device_selection` records the resolved device, the enabled devices, and the
  fallback reason when one was taken. The manifest cannot claim an unused device.
* The independent `Scene.ray_cast` geometry cross-check is CPU-side and still runs on GPU
  renders, so a GPU geometry error cannot pass unnoticed.

`synlab/observe/blender.py` (minimal change, GPU switch only): the four config fields, their
pass-through in `build_config`, the `cycles_device_selection` entry in the result `meta`, and a
`gpu_probe()` helper that runs `blender_scripts/probe_gpu_devices.py`.

`blender_scripts/probe_gpu_devices.py` measures the exposed backends. Note a measured quirk:
`prefs.bl_rna.properties['compute_device_type'].enum_items` returns **empty** on this build
even though the property accepts `OPTIX`/`CUDA`/`HIP`, so usability is decided by whether a
device of that type is enumerated *and* whether assigning the property reads back unchanged.
An earlier version of the probe trusted the enum query and wrongly reported "no GPU backend".

### 3.2 Device selection verified through the real pipeline

`data/a12/reports/gpu/smoke_gpu.json` - one view, 1024x768, 32 samples, `gpu_require=True`:

```
resolved_device                  GPU
resolved_compute_device_type     OPTIX
enabled_devices                  ["NVIDIA GeForce RTX 5060 Laptop GPU"]
compute_device_type_after_scene_setting  OPTIX
cycles_device_setting            GPU
fallback                         false
vram peak                        826 MB
```

### 3.3 Render throughput by device (one process, same scene, best of 3)

`data/a12/reports/gpu/device_sweep.json` - 1024x768, 96-face box, `blender_scripts/bench_cycles_devices.py`.

| samples | CPU | CUDA | OptiX | CUDA/CPU | OptiX/CPU |
|---|---|---|---|---|---|
| 1 | 0.047 s | 0.298 s | 0.360 s | 0.16x | 0.13x |
| 8 | 0.183 s | 0.327 s | 0.387 s | 0.56x | 0.47x |
| 32 | 0.897 s | 0.309 s | 0.494 s | **2.90x** | **1.82x** |
| 128 | 1.711 s | 0.397 s | 0.507 s | **4.31x** | **3.37x** |

Two facts drive everything that follows:

* The GPU has a **fixed cost of roughly 0.3 s per `render.render()` call** (CUDA) / ~0.36-0.40 s
  (OptiX) that barely moves with sample count, while the CPU cost scales with samples. The
  crossover is around 16-24 samples; the project's default is 32.
* In a **fresh process the first CUDA render took 1.298 s against 0.298 s warm** - about 1 s of
  one-time device initialisation. OptiX showed only ~0.05 s on this host because its module
  cache was already warm from earlier probes.
* On this scene **CUDA is faster than OptiX at every sample count**. `AUTO` still prefers OptiX
  (as specified), but `compute_device_type: "CUDA"` is the measured faster choice here.

### 3.4 The pass mix is what decides the outcome

The worker does not render one image per view; it issues **six** renders: RGB (32 samples), two
anti-aliased geometry packs (32 samples), and three one-sample exact geometry passes. Measuring
the real mix in one process (`data/a12/reports/gpu/worker_mix.json`,
`blender_scripts/bench_worker_mix.py`):

| device | cold view | warm view | warm vs CPU | cold vs CPU |
|---|---|---|---|---|
| CPU | 3.492 s | 2.973 s | 1.00x | 1.00x |
| CUDA | 2.050 s | 1.809 s | 1.64x | 1.70x |
| OptiX | 3.536 s | 3.492 s | 0.85x | 0.99x |
| HYBRID (GPU for >=2 samples, CPU for 1) | **1.636 s** | 2.113 s | 1.41x | **2.13x** |

Per-pass, warm view:

| pass | samples | CPU | CUDA | CUDA/CPU |
|---|---|---|---|---|
| `rgb` | 32 | 0.841 s | 0.337 s | **2.5x** |
| `geometry_aa_a` | 32 | 0.813 s | 0.333 s | 2.4x |
| `geometry_aa_b` | 32 | 1.102 s | 0.312 s | 3.5x |
| `geometry_exact_a` | 1 | 0.065 s | 0.271 s | **0.24x** |
| `geometry_exact_b` | 1 | 0.061 s | 0.269 s | **0.23x** |
| `geometry_targetonly` | 1 | 0.091 s | 0.286 s | **0.32x** |

The GPU wins the three expensive passes and **loses the three cheap ones by 3-5x**, because the
~0.3 s fixed per-call cost dominates a one-sample render that the CPU finishes in 60-90 ms. The
three cheap passes cost the CPU 0.217 s and the GPU 0.826 s: a **+0.61 s/view penalty** that
eats most of the ~1.55 s/view the GPU saves elsewhere. Routing per pass (HYBRID) is the best
measured configuration.

### 3.5 End-to-end: the identical 1024x768x12-view task

`data/a12/reports/gpu/bench12_*.json`, `blender_scripts/bench_gpu_render.py`, driving the real
pipeline (`synlab.observe.routes.render_views`, `backend="blender"`, `CAM_MID_V3`,
`delivered_size=(1024,768)`, 32 samples, one Blender process per view, 6 renders per view).

| run | device | total wall (incl. process start) | per view | render passes | worker wall | VRAM peak |
|---|---|---|---|---|---|---|
| run 1 | CPU | 184.79 s | 15.40 s | 84.45 s | 174.32 s | - |
| run 1 | CUDA | **86.29 s** | 7.19 s | 35.74 s | 82.44 s | **815 MB** |
| run 2 | CPU | 88.41 s | 7.37 s | 37.78 s | 85.18 s | - |
| run 2 | OptiX | 119.18 s | 9.93 s | 53.24 s | 114.53 s | **4839 MB** |

**The honest reading is that this table does not support a clean speed-up claim.**

* Taken at face value, run 1 gives CPU 184.79 s vs CUDA 86.29 s = **2.14x** (render passes
  2.36x). That is the number to quote *only* with its caveat.
* The caveat is fatal to a naive claim: **the same CPU configuration measured 184.79 s in run 1
  and 88.41 s in run 2** - a 2.1x spread. Parallel agents on this host were competing for the
  CPU, and the run-1 CPU baseline is the contended one (its render passes took 84.4 s against
  37.8 s in run 2).
* Comparing the two measurements taken under comparable load - run-1 CUDA (86.29 s) against
  run-2 CPU (88.41 s) - gives **1.02x**, i.e. no end-to-end gain.
* OptiX was **slower than CPU** end-to-end (119.18 s vs 88.41 s) and used ~4.8 GB of the 8 GB,
  which is a real risk on this part.
* The isolated, load-robust measurement in 3.4 agrees with the pessimistic reading: the real
  pass mix in one process is 1.6-1.7x (CUDA) and 0.85-0.99x (OptiX) against CPU.

**Conclusion: the ≥3x target is not met.** The measured render-kernel speed-up is real (2.9x at
32 samples on a single warm render; 2.5-3.5x on the multi-sample passes of the real mix), but it
does not survive into the delivered task because of per-pass fixed costs, per-process device
initialisation, and the fact that only ~43% of the wall clock is rendering at all (section 5).

### 3.6 Numerical difference CPU vs CUDA, 12 views

`data/a12/reports/gpu/compare_cpu_vs_cuda.json` (`bench_gpu_render.py compare`). The two runs
were byte-compared channel by channel; `0 / 12` views hashed identically, so the difference is
quantified rather than assumed away.

| channel | bit-identical | elements differing | fraction | max abs diff | p99 abs diff | median |
|---|---|---|---|---|---|---|
| `visibility` | **yes** | 0 | 0 | 0 | 0 | 0 |
| `occlusion` | **yes** | 0 | 0 | 0 | 0 | 0 |
| `target_visibility` | **yes** | 0 | 0 | 0 | 0 | 0 |
| `id_map` | no | 1 | 1.1e-7 | 5 | 0 | 0 |
| `surface_tag` | no | 1 | 1.1e-7 | 1 | 0 | 0 |
| `uncertain_mask` | no | 1 | 1.1e-7 | 1 | 0 | 0 |
| `object_index` | no | 1 | 1.1e-7 | 2 | 0 | 0 |
| `depth_z` | no | 103358 | 2.9e-1 | 214.25 mm | 3.05e-5 mm | 0 |
| `rgb_linear` | no | 825272 | 2.9e-2 | 0.0442 | 1.19e-7 | 0 |

Read against thresholds that matter (`_scratch/threshold_diff.py`):

* `depth_z`: of the **356,968** pixels with valid depth in both runs, exactly **1** differs by
  more than 0.001 mm. That pixel (view 8, y=328, x=621) is a silhouette pixel where the two
  devices resolved *different surfaces* (214 mm apart). Every other differing pixel is below
  1 micrometre - float32 round-off on an interpolated edge weight.
* `rgb_linear`: of 28,311,552 elements, **20** differ by more than 0.01 and 2,415 by more than
  1e-6; the median difference is exactly 0.
* The three **geometry classification** channels are bit-identical, which is the important
  result: GPU rendering does not change which surface a pixel belongs to.

**Is this acceptable?** For the delivered integer/classification channels, yes - the differences
are single anti-aliased edge pixels. For `depth_z` and `rgb_linear` the maximum differences are
real and must be declared: one silhouette pixel per 12-view cache can resolve to a surface up
to 214 mm away, and ~20 RGB elements (of 28.3 M) shift by up to 0.044 in scene-linear units.
Whether that is acceptable is a downstream decision, so the numbers are reported rather than
summarised away. Note also that Cycles' CPU and GPU backends are **not** bit-reproducible in
general; this is not a defect of the integration.

`raycast_vs_exact_pass` reports `DEPTH_MISMATCH` on some views - **on CPU as well as GPU**, so
it is a property of this synthetic box scene, not something the GPU introduced.

### 3.7 Switches and fallback

```python
from synlab.observe.blender import BlenderBackendConfig

# default: unchanged, CPU
BlenderBackendConfig()

# automatic: GPU when a usable backend exists, else CPU (reason recorded in meta)
BlenderBackendConfig(device="AUTO")

# OptiX preferred (AUTO resolves OPTIX -> CUDA -> ...)
BlenderBackendConfig(device="GPU", compute_device_type="AUTO")

# measured fastest on this host/scene
BlenderBackendConfig(device="GPU", compute_device_type="CUDA")

# refuse to fall back silently: raises GPU_UNAVAILABLE instead
BlenderBackendConfig(device="GPU", gpu_require=True)

# pin one device
BlenderBackendConfig(device="GPU", gpu_device_index=0)
```

Autodetect without rendering anything: `synlab.observe.blender.gpu_probe()` returns
`preferred` = `OPTIX` / `CUDA` / `CPU`.

**CPU fallback is always available and is the default.** `device="CPU"` reproduces the previous
behaviour exactly. With `device="GPU"` and `gpu_require=False`, an unusable GPU falls back to
the CPU and records the reason in
`meta["cycles_device_selection"]["fallback_reason"]`.

## 4. Other GPU-able stages

### 4.1 Image-domain convolution - implemented and measured

The pipeline convolves one view at a time with `cv2.filter2D` (BORDER_REFLECT101):
`synlab.observe.imaging._convolve_linear`, and the identical `synlab.degrade.ops_image.convolve`.
`blender_scripts/gpu_image_ops.py` provides a batched torch equivalent;
`blender_scripts/bench_gpu_image_ops.py` measures it against the frozen CPU call.

Equivalence is asserted, not assumed: `cv2.filter2D` with reflect-101 is cross-correlation with
reflect padding, which is `F.pad(mode="reflect")` + `F.conv2d` for odd kernels. Verified on
random data with a 13x13 kernel: **max abs diff 4.77e-7**, `equivalent=True`.

On the workload the pipeline actually produces (12 views, 1024x768x3, the near/far
depth-dependent defocus pair):

| convolution | kernel | CPU | GPU (batched) | speed-up | max abs diff |
|---|---|---|---|---|---|
| near, sigma=1.0 | 7x7 | 0.1196 s | 0.0625 s | 1.91x | **0** |
| far, sigma=1.6 | 11x11 | 0.1469 s | 0.0435 s | 3.38x | **0** |
| **both (per 12-view cache)** | | **0.2665 s** | **0.1060 s** | **2.51x** | **0** |

Sweep over batch and kernel size (`image_ops.json`), which is where the regime dependence shows:

| batch | sigma | kernel | CPU | GPU | speed-up | worth it |
|---|---|---|---|---|---|---|
| 1 | 1.0 | 7 | 0.0072 s | 0.0059 s | 1.21x | **no** |
| 1 | 2.0 | 13 | 0.0360 s | 0.0054 s | 6.72x | yes |
| 12 | 1.0 | 7 | 0.0885 s | 0.0419 s | 2.11x | yes |
| 12 | 2.0 | 13 | 0.5116 s | 0.0534 s | **9.59x** | yes |
| 12 | 8.0 | 49 | 0.7518 s | 0.2082 s | 3.61x | yes |
| 48 | 2.0 | 13 | 2.2788 s | 0.2636 s | 8.65x | yes |

**Verdict:** the acceleration is real and numerically exact (bit-identical at the pipeline's own
sigmas), peaking at ~9.6x for medium kernels and large batches. **But it is not worth doing for
throughput**: the whole operator costs 0.267 s out of an 88-185 s run, i.e. **0.14-0.30 % of
end-to-end time**. It only becomes interesting if the blur radius is raised well above the
current sigma=1.0 default, or if many more views are rendered per cache.

### 4.2 Stages evaluated and **not** worth GPU-ising

| stage | assessment |
|---|---|
| The three 1-sample exact geometry passes | **Actively harmful on GPU** (0.23-0.32x). Keep on CPU. |
| Single-view small-sigma convolution (sigma<=1.0, batch 1) | 1.21x - below the transfer cost. Not worth it. |
| Software rasteriser (`_rasterise_buffers`) | Not attempted. It is a per-face Python loop, so it has the largest theoretical headroom of anything in the chain, but a faithful GPU port needs a tiled/scatter z-buffer with exact tie-breaking; it is a project, not a switch, and it cannot be validated by the existing goldens without changing them. Flagged as the best *future* target if the Blender path is not used. |
| Ray-cast self-check (`raycast_check`, 1500 rays via `Scene.ray_cast`) | CPU-only Blender API; cannot be moved to the GPU. Now a visible cost (section 5). |
| EXR decode, `.npy` writes, hashing, masks, previews | I/O and NumPy; GPU gives nothing. |
| Poisson/read noise in the imaging chain | `rng.poisson` on 1024x768x3 is ~2 ms; below any GPU break-even. |

## 5. Where the time actually goes

From `bench12_cpu.json` / `bench12_cuda.json` (12 views, 1024x768, 32 samples, one Blender
process per view). `worker_wall` is the subprocess wall time; `in-process` is the worker's own
`elapsed_seconds`, which excludes Blender startup and import.

| segment | CPU run 2 | share | CUDA run 1 | share |
|---|---|---|---|---|
| render passes (6 per view) | 37.78 s | 42.7 % | 35.74 s | 41.4 % |
| worker non-render work (EXR decode, ray-cast check, masks, `.npy`, hashing, previews) | 27.81 s | 31.5 % | 25.20 s | 29.2 % |
| Blender process start + interpreter + imports | 19.59 s | 22.2 % | 21.50 s | 24.9 % |
| pipeline outside the worker (scene build, imaging chain, delivery) | 3.23 s | 3.7 % | 3.85 s | 4.5 % |
| **total** | **88.41 s** | | **86.29 s** | |

Within the render passes (CPU): `rgb` 24.23 s, `geometry_aa` 11.48 s, `geometry_exact` 0.90 s,
`geometry_targetonly` 1.18 s.

**Why this caps the achievable gain.** Even a *free* renderer would remove only ~43 % of the
wall clock, i.e. a ceiling of ~1.75x end-to-end. The Amdahl limit, not the GPU, is what makes
≥3x unreachable by changing the render device. The two next-largest blocks - the worker's
CPU-only post-processing and Blender's per-view process startup - are untouched by any GPU
setting.

**Where the effort should go instead, in order of measured headroom:**

1. **Batch views per Blender process.** The ~1 s CUDA initialisation and Blender's ~1.6 s
   startup are paid 12 times for 12 views. The 3.3-3.4 s of per-view startup is 22-25 % of the
   run. One process rendering N views amortises both and is what would let the measured 2.9x
   render-kernel speed-up actually reach the delivered task.
2. **Route passes per device** (section 3.4): GPU for the multi-sample passes, CPU for the three
   one-sample geometry passes. Measured 2.13x on the isolated mix against 1.70x for all-GPU.
3. **Use CUDA rather than OptiX on this scene** (OptiX was slower and used 4.8 GB).
4. Only then consider GPU-ising the imaging chain (section 4.1): numerically free, but 0.14-0.30 %
   of end-to-end.

## 6. Evidence index

| artefact | what it proves |
|---|---|
| `data/a12/reports/gpu/torch_cuda.json` | torch version, CUDA availability, `sm_120`, timed matmul/conv2d, transfers |
| `data/a12/reports/gpu/device_sweep.json` | Cycles throughput per device vs sample count |
| `data/a12/reports/gpu/worker_mix.json` | the real 6-pass mix per device, cold and warm, incl. HYBRID |
| `data/a12/reports/gpu/bench12_{cpu,optix,cuda}.json` | end-to-end 12-view runs incl. VRAM and host CPU load |
| `data/a12/reports/gpu/compare_cpu_vs_cuda.json` | per-channel CPU-vs-GPU difference |
| `data/a12/reports/gpu/image_ops.json` | batched convolution vs `cv2.filter2D`, equivalence + sweep |
| `data/a12/reports/gpu/smoke_gpu.json` | resolved device through the real adapter |
| `data/a12/reports/gpu/torch_install{,2,3}.log` | the verbatim pip failures |
| `data/a12/reports/gpu/_scratch/` | the diagnostic/repair/analysis scripts used above |

Reproduce with:

```powershell
.\.venv\Scripts\python.exe blender_scripts\bench_torch_cuda.py --out data\a12\reports\gpu\torch_cuda.json
.\.venv\Scripts\python.exe blender_scripts\bench_gpu_image_ops.py --out data\a12\reports\gpu\image_ops.json
$b = "C:\Users\xiemo\Desktop\ShardForge\third_party\blender-5.2.2-windows-x64\blender.exe"
& $b --background --factory-startup --python-exit-code 1 `
    --python blender_scripts\bench_cycles_devices.py -- --res 1024x768 --samples 1,8,32,128 --devices CPU,CUDA,OPTIX
& $b --background --factory-startup --python-exit-code 1 `
    --python blender_scripts\bench_worker_mix.py -- --devices CPU,CUDA,OPTIX,HYBRID
.\.venv\Scripts\python.exe blender_scripts\bench_gpu_render.py run --device GPU `
    --compute-device-type CUDA --require-gpu --views 12 --out data\a12\reports\gpu\bench12_cuda.json
```

## 7. Open gaps

* **The ≥3x target is not met** (best measured end-to-end 2.14x, and only ~1.0x under equal
  host load). The measured render-kernel speed-up is 2.5-3.5x; realising it end-to-end needs
  the architectural change in section 5, which is outside the files this task was allowed to
  touch (`synlab/pipeline.py` and the per-view process model).
* **Timings are contention-limited.** The host ran 12+ concurrent venv processes and two
  competing `pip install torch` jobs during this work. The CPU baseline varied 2.1x between two
  runs of the identical configuration. A quiet-host re-run is needed before the end-to-end
  factor is treated as final; the single-process measurements in 3.3/3.4 are the load-robust
  ones and the conclusions here rest on them.
* **The venv is shared and mutable.** A sibling agent re-installed torch mid-session and broke
  the tree; the repository was edited concurrently (`resolve_target` gained an
  `OBS_TARGET_PROVENANCE_MISSING` guard between two of my runs, which is why both devices are
  re-run with `allow_unlabeled=True`). Revision at time of writing: `c3a149f`.
* **OptiX is slower than CUDA here** and uses ~4.8 GB of 8 GB. Untested on a scene with heavy
  ray-type diversity, where OptiX would normally be expected to win.
* **No CUDA fallback beyond CPU.** If the driver is rolled back below CUDA 12.8 support, torch
  must return to `2.5.1+cpu` (section 2.3) and the render path to `device="CPU"`; the pipeline
  then runs exactly as before, with no GPU acceleration and no code change.
* **Software rasteriser left un-accelerated** (section 4.2) - the largest remaining headroom,
  but a real project rather than a switch.
