# Blender as the real offline imaging backend (plan 13.2 / §2.2 / R7)

Status: **implemented and measured on this host**. `synlab.observe.render.capability_probe()`
and `synlab doctor` now report `backend:blender_render = PASS` (they reported `MISSING`
before: no binary, and `bpy` has no Windows/CPython-3.12 wheel).

Everything on this page is a measurement produced by the commands in
[Reproduce](#reproduce). Nothing here is a plan value.

## 1. What runs

| piece | path | role |
|---|---|---|
| worker | [`blender_scripts/render_worker.py`](../blender_scripts/render_worker.py) | JSON config **in**, scene-linear RGB + exact geometry passes + manifest **out**; runs inside Blender's own Python 3.13.13 |
| self-test | [`blender_scripts/selftest.py`](../blender_scripts/selftest.py) | binary capability probe: engine assignable + a real 16×12 background render |
| adapter | [`synlab/observe/blender.py`](../../synlab/observe/blender.py) | binary discovery, subprocess call, channel assembly into `RenderOutput`, structured errors |
| dispatch | [`synlab/observe/render.py`](../../synlab/observe/render.py) | `render_view(..., backend="BLENDER_CYCLES")` → adapter; `BACKEND_SOFTWARE` unchanged |
| doctor | [`synlab/doctor.py`](../../synlab/doctor.py) `_blender_check` | uses the same probe as the render path |
| verification | [`blender_scripts/a12_channel_verify.py`](../blender_scripts/a12_channel_verify.py) | the channel/comparison/tier evidence below |
| API probes | [`blender_scripts/probe_blender_api*.py`](../blender_scripts/probe_blender_api7.py) | measured Blender 5.2 API facts the worker is built on |

Command form (a JSON file is the only worker input):

```powershell
& $env:BLENDER_BIN --background --python-exit-code 3 `
    --python blender_scripts/render_worker.py -- <config.json>
```

`BLENDER_BIN` = `C:\Users\xiemo\Desktop\ShardForge\third_party\blender-5.2.2-windows-x64\blender.exe`
(Blender **5.2.2 LTS**, build hash `d13f752e3b9c`, bundled Python 3.13.13). Discovery order in
`synlab.observe.blender.find_blender_binary`: process `BLENDER_BIN` → `PATH` → the persisted
Windows user/machine environment (a user-level variable set after the parent process started is
not in this process's environment block) → `third_party/blender-*/blender.exe` next to the repo or
its parent. The MSIX `WindowsApps` install is deliberately never searched (it is not executable by
path). No venv dependency is ever installed into Blender's interpreter.

Safety property: a Blender request **never** silently degrades to the rasteriser. A missing binary
raises `ENV_CAPABILITY_MISSING`; a non-zero worker exit raises with the return code, the full argv
and the stderr tail; an unsupported backend string and an EEVEE request are refused with reasons.

## 2. Delivered channels

Written into the worker's output directory (also `npy` next to the float `exr`):

| file | dtype | unit / semantics | source |
|---|---|---|---|
| `rgb_linear.npy` / `rgb_linear.exr` | float32 | scene-linear radiance, `view_transform=Standard`, `save_as_render=False` (no view transform baked in) | Cycles Combined |
| `depth_z_mm.npy` | float32 | **camera-frame z in mm** (not ray length), `NaN` = no hit | Cycles Depth (Z), one-sample exact pass |
| `depth_z_aa_mm.npy` | float32 | the same pass with the RGB filter/samples (AA evidence) | Cycles Depth |
| `id_face.npy` | int32 | per-face research label, `-1` = background, never interpolated | Shader AOV fed by a face-domain FLOAT attribute |
| `surface_tag.npy` | int16 | per-face surface tag, `-1` = background | Shader AOV (the Material Index pass is broken in 5.2.2, §4) |
| `object_index.npy` | int32 | Cycles Object Index (`pass_index`), `-1` = background | Cycles Object Index |
| `visibility.npy` | uint8 | 1 = primary hit is scene geometry **and** the pixel is not mixed (same meaning as the rasteriser) | Object Index + mixing test |
| `target_visibility.npy` | uint8 | 1 = primary hit is the *target* object and not mixed (Blender-only) | Object Index + mixing test |
| `occlusion.npy` | uint8 | 1 = the target is hit with the non-target objects hidden but **not** in the full scene | two geometry passes |
| `uncertain_mask.npy` | bool | mixed AA geometry / depth step inside the pixel / defocus CoC above threshold | measured, per-component counts in `channels.json` |
| `geometry_passes_*.exr` | float32 | the raw pass packs (unscaled) for audit | compositor |
| `channels.json`, `manifest.json` | – | per-channel semantics, and argv/samples/elapsed/version/device/output hashes | worker |

`RenderOutput` has no occlusion/target-visibility field, so `assemble_render_output` attaches them
as extra attributes (`render.occlusion`, `render.target_visibility`, `render.object_index`,
`render.depth_z_aa`) and lists them in `meta["extra_channel_attributes"]`; the frozen schema in
`synlab/schemas/runtime.py` is untouched.

The manifest records the **measured** run, not the request: `samples_requested` **and**
`samples_used`, `filter_width`, `denoise` (+ "applies to RGB only"), `max_bounces`, seed, device,
Blender version/build hash/binary path, per-render seconds, elapsed seconds, and a sha256 per
output file.

## 3. Self-checks (every worker run, recorded in `manifest.json:checks`)

| check | measured value (fixture of §5, 32 samples) | meaning |
|---|---|---|
| face order vs label file | max centroid error **0.0 mm** (both objects) | the PLY import preserves face order, so per-face labels are valid |
| Blender camera vs project pinhole | max uv error **6.6e-06 px** (8 mesh corners) | mm/OpenCV `K`+`T_WC` mapping is exact; `shift_x/y` are solved from Blender's own projection |
| exact pass vs independent ray cast | interior max depth error **6.1e-05 mm** (float32 resolution), **0/630** face-label mismatches, 724 rays | the delivered depth/ID is verified against `Scene.ray_cast`, not against itself |
| exact-pass integrality | 0 non-integral pixels in object index / material index / face label / tag | the delivered integer channels are integers, by construction and by measurement |
| anti-aliased pass | 1743 fractional face-label px, 516 fractional tag px, 0 fractional object-index px, 0 depth-mixing px | see §4 |
| RGB linearity | declared world radiance `[0.02, 0.02, 0.025]` returned as `[0.019999998, 0.019999998, 0.024999993]`, max abs error **7.1e-09**; the sRGB-encoded alternative would be `[0.152, 0.152, 0.172]` | proves the float EXR carries scene-linear numbers |
| pack cross-check | depth in pack A vs pack B max difference **0.0 mm** | the two 3-channel packs are consistent |

Boundary samples (94 of 1500 rays, i.e. pixels whose 3×3 neighbourhood is not one
(object, face) pair) are reported separately: there a pixel-centre ray and a filtered render may
legitimately disagree, and the maximum disagreement there is 101 mm — exactly the occluder/target
depth step. It is not hidden in the interior statistic.

## 4. Channel semantics (§2.2 / plan 13.2 / R7) — measured, not assumed

`blender_scripts/probe_blender_api9.py` renders the same geometry with filter widths
0.01 / 1.5 / 4.0 px and 1 / 16 / 64 samples:

| pass | filter-averaged like RGB? | evidence |
|---|---|---|
| Combined (RGB) | yes | 1.5 px / 64 spp is the standard filtered pass |
| **Shader AOV** (face label, surface tag) | **yes** | fractional values at mixed borders: 0.625 steps for a 10.0 label step at 4 px filter; 1743 fractional px in the fixture |
| **Depth (Z)** | **no** | min/max/mean identical (7 digits) across 0.01→4.0 px filter and 1→64 samples; 0 depth-mixing px |
| **Object Index** | **no** | 0 fractional px, identical across all filter/sample settings |
| Position | no | identical across settings |
| **Material Index** | **unusable** | constant **0.0** even though every face has material index 1 or 2 |

Consequences, all recorded in `manifest.json:checks.pass_aa_behaviour` and
`channels.json`:

* The plan's R7 statement holds and is sharpened for this build: the Z / Object Index passes do
  **not** share RGB's anti-aliasing behaviour — here they are not anti-aliased at all, while a
  Shader AOV *is* averaged exactly like RGB. A filtered RGB pixel therefore can never be used as an
  exact pixel label, and the Shader AOV is the channel that would silently produce fractional
  classes if it were used directly as `id_map`.
* The delivered `id_face` / `surface_tag` come from a **one-sample, 0.01 px-filter exact geometry
  pass** (plan 13.2's "pinhole ray / independent geometry pass"), which is integral to 0 pixels of
  27648 and is cross-checked pixel-wise by the ray cast (§3).
* Because the Cycles **Material Index** pass returns a constant in 5.2.2, the surface tag is
  published through a per-face Shader AOV instead. The Material Index pass stays in the pack as an
  audited channel; the manifest states `material_index_pass_usable: false` with its measured value.
* `uncertain_mask` = (fractional AOV | rounded-AOV ≠ exact label | hit/miss disagreement |
  depth step inside the pixel | defocus CoC > threshold) on hit pixels. Motion blur is an
  imaging-chain stage (plan 13.3), so the render-side mask only *dilates* the mixed mask when a
  motion amplitude is requested — declared, with `motion_dilation_px` in `channels.json`.

## 5. Verification numbers (`data/a12/reports/blender/channel_verification.json`)

Fixture: a 100 mm cube (target, faces 0–11, tag 0) plus an opaque 40 mm occluder plate 249 mm in
front of it (faces 12–23, tag 2), 192×144 px, `fx = fy = 400 px`, camera 400 mm away on the optical
axis, PINHOLE (no distortion), sun + ambient + a declared world background.

* **Analytic plane / depth** — the cube front face is at 350.000 mm: max |error| over 8900 pixels
  **0.0 mm**; the fitted plane normal is `(-0.0, -0.0, -1.0)`, angle to the analytic normal
  **0.0°**, RMS 0.0 mm, planarity 0.0.
* **Integer channels** — `id_map` int32 with 5 classes total (background −1 plus the visible
  faces), `surface_tag ∈ {−1, 0, 2}`; background is exactly −1 in both.
* **Uncertain mask** — 4946 px (17.9%): covers **100%** of the geometry silhouette; 0% of the flat
  in-focus target face away from silhouette and label boundaries (the remaining interior coverage is
  the out-of-focus occluder plus the label boundary between the two coplanar triangles of the cube
  face, both reported explicitly).
* **Occlusion** — 4096 px, against the analytic projection of the 40 mm plate at 249 mm
  (64.26 px → 4129 px): **0.8% deviation**.
* **Denoise** — with `denoise=True` the RGB changes (mean |Δ| 1.6e-03) while depth, id, tag,
  visibility and uncertain are **bit-identical**: measured confirmation of "denoise acts on RGB
  only" (the geometry channels are separate renders with `use_denoising=False`).
* **Low-cost tier (32 vs 64 samples)** — against a 256-sample reference on the same view:

  | samples | RGB mean abs rel err | RGB p99 rel err | depth/id/tag vs reference | RGB render s (192×144) |
  |---|---|---|---|---|
  | 32 | 0.0233 | 0.1139 | identical (bit-exact) | 1.19 |
  | 64 | 0.0179 | 0.0833 | identical (bit-exact) | 1.04 |

  Frozen tier = **32 samples** (lowest tier meeting every declared threshold: mean ≤ 5%,
  p99 ≤ 25%, geometry bit-identical). Caveat recorded with the freeze: at this verification
  resolution the RGB time is dominated by scene setup rather than by samples (1.19 s at 32 spp vs
  1.04 s at 64 spp, i.e. within noise), so the tier must be re-measured at production resolution
  before it is frozen for a confirmatory run. The geometry channels cost ~0.13 s in total for five
  extra passes.

## 6. Software rasteriser comparison (same `Scene`, `ViewFrame`, `LightSpec`, resolution)

| quantity | software rasteriser | Blender 5.2.2 (32 spp) | difference |
|---|---|---|---|
| cube front-face width × height (px) | 113 × 113 | 112 × 112 | −1 px (analytic projection: 114.29 px) |
| camera-depth at the image centre | 249.0 mm | 249.0 mm | 0.0 mm |
| fitted plane normal (deg vs analytic) | 0.0° | 0.0° | 0.0° |
| integer id classes (total / visible) | 5 / 4 | 5 / 4 | 0 |
| depth where neither backend flags a mixed border | – | – | max **< 1e-3 mm** |
| uncertain pixels | 4500 | 4946 | +446 (different mixed-border rules) |
| occlusion channel | **not provided** | 4096 px measured | backend capability difference |
| wall time (192×144, incl. process start) | 0.016 s | 2.75 s | ≈ 170× slower |

The geometry channels therefore agree to float32 precision and to ≤1 px on the silhouette; the
Blender path costs ~2.6 s per view (≈1.2 s RGB at 32 spp + 0.13 s for the five geometry passes +
≈1.4 s process start/import) against 0.016 s for the in-process rasteriser. The rasteriser remains
the right choice for high-volume smoke loops; Blender is the physical reference and the only backend
that measures occlusion, a filtered-vs-exact AA distinction and an unbiased integrator.

Honest differences that were **not** tuned away: the silhouette grows by 1 px (the rasteriser takes
its coverage from supersample disagreement, Blender from an exact pixel-centre sample), and the
rasteriser has no occlusion channel at all.

## 7. Limits and remaining gaps

1. **Distortion** — the Blender path renders an ideal pinhole. The production camera profiles carry
   OpenCV distortion (k1..k3, p1, p2), so `render_view(..., backend="BLENDER_CYCLES")` **refuses**
   such a frame (`ENV_CAPABILITY_MISSING`) instead of dropping the coefficients silently.
   `BlenderBackendConfig(distortion_policy="ignore")` renders anyway and records
   `distortion_ignored`. Alternative: undistort the frame first (a new pixel contract) or keep the
   rasteriser for distorted frames.
2. **Route wiring** — `synlab/observe/routes.py` still calls `render_view` without a backend
   (out of the allowed write scope for this task) and `synlab/observe/api.py` rejects non-software
   renderers; both must be switched to `BACKEND_BLENDER` for the 12-view cache to use Blender.
3. **EEVEE** — refused with a reason; EEVEE Next does not expose the same pass set.
4. **Motion boundary** — motion blur belongs to the imaging chain (I02); the worker only dilates the
   mixed mask by the requested amplitude.
5. **Spectrum/BRDF** — Cycles renders the declared per-face albedo/roughness; it is not a measured
   BRDF or a spectral render, and no such claim is made.
6. **Tier freeze at production resolution** — see §5.
7. **`bpy` remains unimportable** in the venv; everything goes through the subprocess contract, so an
   in-process API (no process start cost) is still unavailable.

## 8. Reproduce

```powershell
# capability probe / doctor (MISSING -> PASS)
.venv\Scripts\python.exe -m synlab.cli doctor --json

# channel semantics + software comparison + sample tiers  (~30 s)
.venv\Scripts\python.exe blender_scripts\a12_channel_verify.py --steps all --samples 32 --tier-samples 32,64

# backend tests (15 tests; run in groups if the host kills long process trees)
.venv\Scripts\python.exe -m pytest tests/a12/observe/test_blender_backend.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m pytest tests/a12/observe/test_blender_backend.py -q -p no:cacheprovider -k "not (agree or denoise or doctor)"
```

Artifacts: `data/a12/reports/blender/channel_verification.json`, `doctor_run.txt`,
`_pytest_*.txt`, `_probe_*_raw.txt`, and `work_*/` (raw EXR packs, `npy` channels,
`channels.json`, `manifest.json`, previews).
