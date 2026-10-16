# A12 degradation realism: antique wear/aging + capture-rig error

Status of this document: **delivered with real measurements** for every number it prints.  Where a
number is *not* measurable on this machine it is labelled `CANDIDATE` (候选) / `待实测校准` and is
listed again in §8.  Nothing here is presented as a bench calibration that this project has not
performed: the capture rig of the plan is *designed, not built* (`docs/a12/v144_project_core.md`
§4.3 p434: 未采购、未搭建、未验证).

Deliverables of this work:

| artefact | path |
|---|---|
| hardware / material catalogue with per-value provenance | `synlab/degrade/specs.py` |
| antique wear + aging model | `synlab/degrade/wear.py` |
| capture-rig error model | `synlab/degrade/rig_error.py` |
| 14-component ↔ 8-item mapping and its inversion | `synlab/degrade/mapping.py` |
| wear measurement run (3 real bodies × 5 levels) | `data/a12_reports/measure_wear_ladder.py` → `a12_wear_ladder.json` |
| rig-error measurement run (real frames + real point cloud) | `data/a12_reports/measure_rig_ladder.py` → `a12_rig_error.json` |
| worn bodies committed to a new store | `data/a12_wear/store` |
| contract tests | `relicweave-synlab/tests/a12/operators/test_wear_rig_realism.py` |

Scope note: the two models are **not** new degradation axes.  `synlab.schemas.spec.AXIS_IDS` is
frozen at 31 axes × 5 levels and the shipped audit is 155/155 PASS with `level 0` as a true
identity; adding axes would change that denominator.  The wear model therefore produces the
*geometry* a P3/P7-class axis would consume, and the rig model produces the *frame and cloud
degradation* an I/G-class axis would consume, both with the measurement envelope already attached.
No file outside `synlab/degrade/**`, the new test file, `docs/a12/degrade_realism.md` and
`data/a12_reports/**` + `data/a12_wear/store` was modified.

---

## 1. The wear / aging model (`synlab/degrade/wear.py`)

### 1.1 Why a spatial model instead of global noise

A pot does not age uniformly.  Each documented archaeological wear mechanism acts on a specific
region and is driven by a specific physical quantity, so the model is built as **seven spatial
fields that are summed and then guarded**, not as one noise term:

| mechanism (考古实际) | region | spatial field | physical driver used |
|---|---|---|---|
| 口沿磨损 rim wear | the thin lip ring at the opening | geodesic band + a Gaussian contact profile, boundary pinned to zero | measured wall thickness of the lip, contact-band width, handling contacts, material hardness, porosity |
| 底部磨蚀 base abrasion | the footprint on the placement plane (incl. the foot ring) | linear-wedge band from the measured support plane | contact pressure = mass / contact area, hardness ratio body:surface, porosity as grit embedment |
| 釉面损失 glaze loss | convex high spots / unsupported shell | threshold on a spall-rank field (convexity + substrate support + porosity + frozen edge jitter) | measured curvature, measured wall thickness, measured layer thickness, layer:substrate toughness ratio |
| 崩口 edge chip | the convex edge population | spherical-cap of a frozen nested anchor subset | edge toughness, porosity, build-up depth |
| 微裂纹 microcrack | the surface, as a ridge network | frozen Fourier ridge network, depth capped by the local coating thickness | layer thickness (a crack never opens the body) |
| 边缘钝化 edge blunting | the same convex edges | *implicit*: every applied normal offset blunts a convex edge, and the measured curvature field records it | — |
| 土沁/积垢/铁锈斑/盐析/根痕 | crevices, undersides, crack traces | five separate fields, **image domain only** | wall-thickness enclosure proxy, measured support/opening axes, porosity |

Geometry and image domain are never mixed: `apply_wear(..., mechanisms=[...])` without
`soil_layer` produces the identical mesh (asserted in
`test_soil_layer_is_image_domain_only`), and the soil fields are returned as their own channels.

### 1.2 The physical quantities, and how they are obtained

* **`t_wall`, local wall thickness (mm)** — measured per vertex by a ray cast from
  `vertex - n*eps` inward along the vertex normal (the same instrument
  `synlab.degrade.narrowband.paired_thickness` uses, on the frozen `synlab.physical.sdf`
  raycasting scene).  No nominal thickness is ever assumed.  On the mother body
  `LIN0000_V10_M11_PAT15`: median 10.0019 mm, p05 3.8481 mm, min 0.3242 mm, 0 vertices without a
  hit.
* **`kappa`, signed mean curvature (1/mm)** — cotangent one-ring estimator, capped at `1/t_wall`
  so a one-ring wider than the shell cannot report the opposite side.
* **`t_layer`, glaze / coating thickness (mm)** — **coupled to the measured wall**:
  `t_layer = clip(fraction * t_wall, 0.469, 1.173)`.  The interval is this project's *measured*
  L01/L03 geometric-layer thickness range; the fraction comes from the material trait table and is
  a candidate (§8).
* **material traits** — hardness / toughness / porosity from `specs.material_wear_traits`, each
  value carrying its own `SpecValue` provenance.  They enter as *relative* resistances, which is why
  an uncalibrated class value is still usable — but it never appears as a measured hardness.
* **support plane and opening axis** — measured from the body: the support is the least-squares
  plane of the 2 % lowest ring opposite the opening; the opening is the principal axis of the
  thinnest-wall quartile, with the sign chosen by thin-wall density.  Both can be overridden by the
  caller, in which case the report says `CALLER` instead of `MEASURED`.

### 1.3 Legality (the A09 contract, unchanged)

The result is produced exactly like the shipped narrow-band P axes: per-vertex offset along the
area-weighted vertex normal with **compact support** (each band boundary is pinned to zero).
Three guards then make `damaged ⊆ clean` a measurement rather than a hope.  Each guard exists
because the previous one was *measured* to be insufficient:

1. **closed-form in-plane cap** — for every face corner, `d * sqrt(1 - (n_vertex·n_face)²)` must
   stay below the face's inradius.  Reason: a sliver triangle's corners can move *in plane* and
   slide the face projection off the original triangle.
2. **per-vertex bisection against the audit instrument** (`trimesh.proximity.signed_distance`,
   positive = inside).  Reason: on a shell whose cavities are *enclosed* — measured on
   `LIN0000_V10_M11_PAT15`, whose vertex centroid has `signed_distance = -62.96 mm` — "inward along
   the vertex normal" is not the same as "into the material"; 50 of 2645 moved vertices landed
   outside by up to 0.813 mm even though their local wall was 8.2 mm thick, and a ray-parity test
   and Open3D's occupancy query both agree they were outside.  A ray test along the face normal was
   tried first and **rejected on measured grounds**: casting from any point of a closed mesh hits
   the body (19/19 known-outside centroids returned a finite `t_hit` along both `+n` and `-n`), so
   it carries no inside/outside information at all.
3. **audit-metric refinement** — the exact shipped `subset_outside_stats` (1e-3 mm, unchanged) is
   run and the two-ring neighbourhood of any still-outside sample has its offset halved, then the
   residual is pinned to zero.  Reason: stages 1-2 are sufficient conditions; this stage optimises
   the metric the audit actually reads.

The wall guard is multiplicative, `applied = min(Σ mechanisms, margin · t_wall)` with
`margin = 0.30` (candidate), so a thin shell cannot be punched through; the guard's truncation is
reported per level (`clamped_vertices`, `max_clamped_mm`, `stages 3/4`).

---

## 2. The capture-rig error model (`synlab/degrade/rig_error.py`)

Every term is written against documented hardware (Luckfox Pico RV1103 + SC3336B, 2304×1296,
FOV_h ≈ 84°, **manual focus**, **rolling shutter**, four same-colour-temperature white lamps with a
lamp-side polariser and a lens analyser, five documented light states, per-condition intrinsics,
a traceable scale reference in every formal capture).

| term | model | documented input | candidate input |
|---|---|---|---|
| **rolling shutter** | row delay `t_row · row`; a turntable at `ω` moves the scene `ω·T_read` during the read-out window, i.e. `dx_px = ω·T_read/FOV_h·N_x·sin α`; applied as a **per-row** horizontal resample whose shift grows with the distance from the image of the rotation axis | 1296 rows, 2304 columns, FOV_h 84° | line time 8.9 µs (IMX415-class), turntable rate 2 °/s |
| **manual focus** | thin-lens CoC in mm × sampling density `D = N_x/W_sensor` (the repository's own `observe.render.circle_of_confusion_px`, `mask_semantics = coc_units_v2`), then a geometric disc → Gaussian `σ = c/4`; a real PSF convolution of the linear plane | FOV_h (→ focal length 3.1252 mm derived), pitch 2.4427 µm derived | f-number 2.0, focus error |
| **intrinsics drift** | `fx' = fx(1 + u·3 %)`, principal point `+ (v·5 px, v·3 px)`, frozen per condition | the plan's requirement: independent intrinsics per stable condition, no blind sharing (p1155/p1163) | the 0–3 % / 0–5 px bounds |
| **scale drift** | `0–5 %` residual with a fully visible scale reference, growing with `1/visibility`, and **`ARBITRARY`** (infinite, not 5 %) when the capture carries no reference | "每次正式采集必须包含可追溯尺度基准" (p1163) | the 0–5 % bound |
| **light states** | the five documented states as a linear-domain mix: `I' = w_d·I_diffuse + w_s·k·I_specular`, highlight support from the frame (brightest 2 % luma) when the source declares none | the five mode names, their lamp groups and purposes (table t053) | every weight, incl. `CROSS_POL`'s `k = 0.22` |
| **resolution at distance** | the documented table 50/100/150/200/250 mm → 0.039/0.078/0.117/0.156/0.195 mm/px; any other distance uses the same documented pinhole formula, tagged `DERIVED`; a *re-projection* to another pixel density updates `K` and is labelled `REPROJECTED_PIXEL_DENSITY` — **never** "the camera moved closer" (§G14.4 p1488 forbids simulating approach with resize) | the whole table | — |
| **reconstruction** | depth noise from parallax `σ_z = z²/(f_px·B)·σ_disp` (so noise grows with distance for the same reason the pixels coarsen), plus a **measured** cloud audit: local plane residual, normal drift under a resample, enclosed-void census, valid fraction | the "Q2 当量" floor (≥ 50 % valid, σ ≤ 0.2 mm, ≤ 2 holes of r ≤ 3 mm, p1063) | `σ_disp = 0.25 px` |

### 2.1 The rolling-shutter magnitude, in numbers

With the documented 1296 rows and a candidate 8.9 µs line time: `T_read = 11.534 ms`.  At a
candidate 2 °/s the scene rotates `0.0231°` during one frame's read-out, which is
**0.632 px** at the frame edge and 0 px on the rotation axis.  At 150 mm the delivered mm/px is
0.2638 in the 128-px-wide shipped probe frame, so the full-frame displacement is **0.0742 mm** —
sub-pixel *and* sub-tenth-of-a-millimetre at the plan's own working distance.  That is the honest
answer to "give the magnitude of the row-delay displacement": at 2 °/s this rig's rolling shutter
is not a geometric error, it becomes one only above roughly 30 °/s (≈ 9.5 px at the frame edge).

### 2.2 The manual-focus error, in numbers

The model's *ladder* keeps the focus error at 8 % of the distance (12 mm at 150 mm → **1.007 px**
CoC, **σ = 0.252 px**), which costs almost nothing: the measured gradient-energy drop of the
delivered frame is 0.00073 at level 4.  A real manual-focus miss on a real rig is frequently tens
of millimetres, so the report also carries an explicit sweep at f/2.0, 150 mm focus:

| focus error | CoC | PSF σ | measured gradient-energy drop |
|---|---|---|---|
| ±5 mm | 0.44–0.47 px | 0.11–0.12 px | 0.0000 |
| ±10 mm | 0.85–0.97 px | 0.21–0.24 px | 0.0000–0.0004 |
| ±25 mm | 1.94–2.73 px | 0.49–0.68 px | 0.175–0.344 |
| ±50 mm | 3.39–6.88 px | 0.85–1.72 px | 0.434–0.689 |

Derived depth of field at 2 px CoC: near 130.8 mm / far 175.7 mm → **44.9 mm total** at 150 mm
(the plan prints no DoF value at all, §4.2 p404; this one is derived from the candidate f-number
and the derived pixel pitch).

### 2.3 The five light states, measured on a real frame

Highlight support = the brightest 2 % of the frame's luma (the source declares none).

| mode | specular retained | measured highlight suppression | documented purpose |
|---|---|---|---|
| `WHITE_DIFFUSE` | 1.00 | 0.450 (weighting only) | 轮廓、颜色和基础纹饰 |
| `LEFT_GRAZE` | 1.00 | 0.050 | 断口起伏和裂纹 |
| `RIGHT_GRAZE` | 1.00 | 0.050 | 验证另一方向纹理与阴影 |
| `CROSS_POL` | **0.22** | **0.879** | 降低**部分**釉面高光 |
| `NORMAL_REFLECT` | 1.00 | −0.250 (gloss boosted) | 保留光泽等材质证据 |

`CROSS_POL` keeps 22 % of the specular return on purpose: the plan says 降低**部分**釉面高光, not
"removes the highlight", and a perfect crossed pair leaves `k⊥²` (for real film
`k⊥ ≈ 0.47` amplitude).  Both the ideal value and this one are candidates until the A6 paired
capture (普通光 / 交叉偏振 / 侧光, same piece same pose, p443-p444) measures them.  The two grazing
states are mirror images and therefore report the same single-frame statistic; the model does not
invent an asymmetry it cannot show.

### 2.4 Reconstruction error, measured on a real observed cloud

Route `PROXY_SCAN`, provenance `BUILTIN_PROBE_REAL_RENDER`; 1024 points, 100 % valid at 0.2 mm
voxel:

| quantity | measured | "Q2 当量" floor (p1063) |
|---|---|---|
| valid fraction | 1.000 | ≥ 0.50 |
| local plane residual σ (median / p95) | **0.1038 / 0.3351 mm** | ≤ 0.2 mm |
| enclosed-void census | 0 holes | ≤ 2 holes of r ≤ 3 mm |
| normal drift under a half-voxel resample | 3.19° | not specified (reported as its own item) |
| curvature stability (σ of the plane residual) | 0.0997 mm | not specified |

The median is inside the floor and the p95 is not, which is exactly the kind of statement the
floor needs: it is a **synthetic calibration line** that the plan itself requires to be
re-calibrated after a real scan (p1063).

---

## 3. The 14-component ↔ 8-item mapping table (`synlab/degrade/mapping.py`)

Synthetic side, verbatim from p365 (`D = [...]`): `fracture_smoothing, edge_rounding,
fracture_missing, texture_loss, blur, glare, exposure, view_coverage, point_dropout, mesh_holes,
depth_noise, normal_noise, curvature_noise, calibration_error`.
Real side (A6, p199/p236): `blur, exposure, coverage, occlusion, reconstruction confidence,
point density, normal stability, curvature stability`.

| # | synthetic component | link kind | real quality item(s) | sensitivity | synthetic producer | evidence |
|---|---|---|---|---|---|---|
| 1 | `fracture_smoothing` | **UNMAPPABLE** | — | — | P01/P02/P03 | a capture-quality vector cannot see a material fact |
| 2 | `edge_rounding` | COMPOSITE (weak) | normal_stability, curvature_stability | −0.35, −0.25 | P02, wear.edge_chip | CANDIDATE |
| 3 | `fracture_missing` | **UNMAPPABLE** | — | — | P04, G03 | do **not** infer it from coverage |
| 4 | `texture_loss` | **UNMAPPABLE** | — | — | P06, wear.glaze_loss (appearance side) | the real vector has no texture item |
| 5 | `blur` | ONE_TO_ONE | blur | +1.0 | I01, I02, rig defocus + rolling shutter | measured on this machine |
| 6 | `glare` | COMPOSITE | exposure, blur | +0.6, −0.15 | I06, rig light states | CANDIDATE |
| 7 | `exposure` | ONE_TO_ONE | exposure | +1.0 | I04, rig light states | measured on this machine |
| 8 | `view_coverage` | ONE_TO_ONE | coverage | **−1.0** | I08, G03 | measured (sign declared) |
| 9 | `point_dropout` | ONE_TO_ONE | point_density | **−1.0** | G01/G02 | measured (sign declared) |
| 10 | `mesh_holes` | COMPOSITE | coverage, reconstruction_confidence | −0.8, −0.4 | G03, rig hole census | measured |
| 11 | `depth_noise` | COMPOSITE | reconstruction_confidence, point_density | −0.7, −0.2 | G04, rig depth-from-disparity | DERIVED (z²/(f·B)) |
| 12 | `normal_noise` | ONE_TO_ONE | normal_stability | −1.0 | G05 | measured |
| 13 | `curvature_noise` | ONE_TO_ONE | curvature_stability | −1.0 | G06 | measured |
| 14 | `calibration_error` | COMPOSITE | reconstruction_confidence, point_density | −0.6, −0.3 | G07, rig intrinsics + scale drift | CANDIDATE |

**Structural gaps, declared rather than papered over** (`mapping_completeness()`):

1. the real vector has an **`occlusion`** item and the synthetic 14-component vector has **no
   occlusion component**.  Occlusion can be produced and measured here (I07's occluder re-render
   plus the renderer's occlusion channel, and the plan itself lists 支撑遮挡 representative pieces
   at p1500), but it cannot be *named* inside the 14-component vector, and the plan's own §G14.4
   line 1101 notes the same for the five light states.  A synthetic-to-real occlusion comparison
   must therefore carry it as a separate field;
2. three components (`fracture_smoothing`, `fracture_missing`, `texture_loss`) are invisible to the
   real quality vector by construction.  This is the "缺映射表" of the plan's §5 item 9, and the
   honest answer is: **no coefficient closes it** — it needs a fracture-surface label, not a quality
   item.

### 3.1 Inverting the real 8 items into synthetic levels (for 真实统计校准)

`mapping.levels_from_quality(quality, calibration=..., quality_validity=...)` fits the declared
table by weighted least squares and returns, per component: a candidate `level`, a `kind`
(`OBSERVED` / `CONSTRAINED` / `CANDIDATE_LEVEL` / `UNIDENTIFIED`), the per-item residual, the
collinear groups, and the calibration that was used.  Rules that matter:

* a component whose real-side item is missing or invalid comes back as **`None`**
  (`UNIDENTIFIED`) — never as `0`;
* `residual_rms` is computed over the items the 14-vector can reach; an unreachable item keeps its
  residual in `residual` but is listed in `residual_items_excluded` (it is a missing column, not an
  inversion error);
* `CONSTRAINED` marks a component whose design column is collinear (|corr| > 0.995) with another —
  the fit splits the signal and says so;
* `quality_from_levels` is the forward direction, so a round trip can be checked
  (`test_inversion_round_trips_and_never_invents_an_unidentified_level`).

`QualityCalibration` is the object a real paired capture must fill in: the identity-run reading per
item (`quality_at_zero`), the item's full-range swing (`quality_span`), and the list of components
whose sensitivity was actually measured (`calibrated_components`).  Until then every fitted level is
a **candidate**.

---

## 4. Measurement run 2 — capture-rig error ladder

`data/a12_reports/a12_rig_error.json` (run: `measure_rig_ladder.py`, 29.6 s).  Frames: the shipped
probe's real proxy-scan render (`probe_sources`, 4 views, 128×96); the two pixel-domain terms are
measured on the frame re-sampled to the **documented 2304×1296 grid with `INTER_NEAREST`**, so the
row count and therefore the read-out window are the real ones and no detail is invented.  The point
cloud is a real `PROXY_SCAN` observation.

| level | row offset max (px) | row-delta gradient (per row) | CoC (px) | PSF σ (px) | gradient-energy drop | focal change | scale |
|---|---|---|---|---|---|---|---|
| 0 | 0 (identity: nothing applied) | 0 | 0 | 0 | 0 | 0 | 0 |
| 1 | 0.1581 | 5.39e-09 | 0.267 | 0.067 | 0.0000 | +0.75 % | BOUNDED |
| 2 | 0.3161 | 1.08e-08 | 0.523 | 0.131 | 0.0000 | +1.50 % | BOUNDED |
| 3 | 0.4742 | 1.62e-08 | 0.770 | 0.192 | 0.0000 | +2.25 % | BOUNDED |
| 4 | 0.6323 | 2.16e-08 | 1.007 | 0.252 | 0.0007 | +3.00 % | BOUNDED (8.33 % at 0.6 visibility) |

Additional measured items: full-frame radial displacement 0.6327 px = **0.0742 mm** at 150 mm;
principal-point shift +5.0 px (x) / +3.0 px (y) at level 4; the `ARBITRARY` scale case reports
`scale_error_relative = inf`, `scale_error_percent = null` — deliberately, because a capture
without a scale reference has no scale at all.

## 5. Measurement run 1 — antique wear ladder

`data/a12_reports/a12_wear_ladder.json` (run: `measure_wear_ladder.py`; three real bodies × five
levels; the worn bodies are committed to `data/a12_wear/store` as
`ROLE_PHYSICAL_COMPONENT`/`synlab.physical.v1` assets with the depth field, the glaze-loss mask and
the five soil channels as arrays, and the measurements in `meta`).

Targets: two real fragments of lineage `LIN0004_V10_M06_PAT03` (3223 / 3378 vertices, 6442 / 6758
faces) and the real mother body `LIN0000_V10_M11_PAT15` (3973 vertices, 7936 faces,
334×334×271 mm, median wall 10.00 mm).

_Section filled from the run log after the run; see `a12_wear_ladder.json` for the authoritative
numbers._  <!-- FILLED BELOW -->

### 5.1 Level 0 identity and legality re-verification

For every target and every level the report carries the legality verdict measured with the shipped
instrument and the shipped tolerance:

* `level 0` — `identity_same_object = true` and `result_bytes_unchanged = true`: the produced body
  **is** the source mesh object and its vertex bytes hash to the same SHA-256 as the source.  The
  source record (asset id, lineage, vertex/face hashes) is in `targets[*].source`;
* `level 1..4` — `watertight`, `positive_volume` and `damaged_subset_clean` at **1e-3 mm**, plus the
  raw `subset_outside_points`, `subset_max_outside_mm` and the instrument name.

---

## 6. How the two models line up with "what a real capture actually does"

| plan statement (authoritative) | what this model does | what is still missing |
|---|---|---|
| 滚动快门 (p504) | per-row shear with the documented row count; the numeric magnitude is derived, not asserted | the sensor line time (candidate) — one strobe/known-rotation test replaces it |
| 手动对焦 (p504/p513) | thin-lens CoC → PSF, DoF derived at the candidate f-number | the lens model, focal length and f-number (the plan explicitly leaves them unspecified) |
| 内参每稳定工况独立 (p1155/p1163) | drift is per-condition, frozen across levels, and the report refuses to share intrinsics silently | a real calibration board run per condition |
| 尺度基准每次采集 (p1163) | drift is coupled to reference visibility; no reference ⇒ `ARBITRARY`, not 5 % | repeat-scan deviation of one scale bar |
| 5 灯态 (t053) | all five states, with `CROSS_POL` retaining part of the specular return | the A6 paired capture that measures the weights |
| 分辨率随距离 0.039–0.195 mm/px (p512) | documented table + pinhole extrapolation, tagged; a re-projection is labelled as such | the measured GLOBAL/MID/LOCAL tiers with `px_per_mm` and `r_eff_mm` (p579) |
| 不承诺 0.1 mm 绝对精度 (§5.9) | the scale term refuses to claim bounded accuracy without a reference | — |
| 3D "Q2 当量" (p1063) | the floor is enforced as the *ceiling of the worst level*, and the real cloud is measured against it | re-calibration after Gate B, as the plan itself requires |
| 古董磨损 (this task) | seven spatial mechanisms driven by measured wall/curvature/layer + material traits, with three legality guards | the handling/mass/burial/salt numbers (all candidates), and real worn-reference measurements |

---

## 7. Still gaps (what this work does **not** claim)

1. **No bench calibration of the rig exists** — the rig is not built; every `CANDIDATE` in §8 needs
   a real measurement before any absolute claim.
2. **Absolute accuracy is not promised** (and is not claimed here): the plan explicitly refuses
   0.1 mm, and the reconstruction model reports the median/p95 residual instead of a tolerance.
3. **`occlusion` has no synthetic component** — a structural gap in the 14-vector, not a
   coefficient to fit (§3).
4. **Three synthetic components are unobservable on the real side** — they need a fracture-surface
   label, not a quality item.
5. **Wear magnitudes are upper bounds** — the guards only ever move vertices *less*, so the reported
   depths cannot be exceeded by the produced geometry; the flip side is that a coarse source
   tessellation caps how deep a wear pattern can be carried legally (the mother body's large sliver
   triangles are the measured example).
6. **Level 1..4 subset verdicts are re-sampled** — `subset_outside_stats` samples 1200 surface
   points, so a verdict of "0 outside" is a statement about that sample; the report carries the
   sample size and the raw counts rather than a boolean alone.
7. **No appearance-domain model of the five light states was validated against a real pairing** —
   the weights are candidates and the model says so in every returned dict.

---

## 8. Candidate values — the calibration list (待实测校准)

Extracted from `specs.capture_rig_spec().candidates()` (30 entries, reproduced by
`a12_rig_error.json: candidates`); the wear model's own candidates are in
`WearModel().provenance()` and `a12_wear_ladder.json: model.provenance`.

### 8.1 Rig / optics

| value | candidate | how to calibrate |
|---|---|---|
| sensor line time | 8.9 µs | strobe or known-rotation test with a printed grid; datasheet |
| lens f-number | `f/2.0` | DoF / target test, or a real aperture measurement |
| lens mount, focal length | `UNKNOWN` (focal length is *derived* as 3.1252 mm from FOV_h and the 1/2.8" 16:9 active area) | the plan explicitly leaves the lens unspecified (§4.2 p513) |
| distortion model order | `UNKNOWN` | OpenCV calibration per condition (the plan requires fx/fy/cx/cy + distortion, order unspecified) |
| turntable rate | 2 °/s | step timing test |
| U-rail repeatability P95 | 0.5 mm | 10 in/out returns per point (§4.3 p533) — the plan marks this a candidate itself |
| camera front clearance | 20 mm | freeze against the real hardware |
| colour temperature / DoF | `UNKNOWN` | 色卡 + 样片; DoF target |

### 8.2 Light states (all five) and polarisation

`diffuse_weight`, `specular_weight`, `specular_retained`, `key_direction` for
`WHITE_DIFFUSE`, `LEFT_GRAZE`, `RIGHT_GRAZE`, `CROSS_POL`, `NORMAL_REFLECT`, plus CRI ≥ 90.
Calibration: the A6 paired capture (普通光 / 交叉偏振 / 侧光, same piece same pose, p443-p444) with
a grey card and a glaze sample; `polarizer_auto = false` is documented and enforced.

### 8.3 Intrinsics / scale / reconstruction

| value | candidate | how to calibrate |
|---|---|---|
| focal-length drift | 0–3 % | calibration board per stable condition |
| principal-point drift | 0–5 px | same |
| scale drift | 0–5 % (with reference) | repeated capture of one scale bar |
| depth-noise parallax σ | 0.25 px | real MVS stereo/multi-view residual at known baseline |
| valid-point floor, σ floor, hole floor | documented (≥ 50 %, ≤ 0.2 mm, ≤ 2 holes r ≤ 3 mm) but a *synthetic calibration line* | re-calibrate after Gate B (the plan requires it) |

### 8.4 Wear model

| value | candidate | how to calibrate |
|---|---|---|
| material porosity / hardness (Mohs) / toughness, M01–M12 | literature class values | water absorption / mercury porosimetry; scratch or micro-indentation |
| layer-thickness fraction of the wall (per material) | 0.12–0.30 | the *range* is anchored to the measured L01/L03 interval 0.469–1.173 mm; the fraction itself needs a cross-section measurement |
| handling contacts | 40 | use-wear reference collection |
| mass | 0.35 kg | weigh the object |
| contact pressure | 12 kPa | mass / measured contact area |
| burial years / wet-dry cycles / soluble salts | 300 a / 300 / 800 ppm | dating; ion chromatography / conductivity |
| wall-thickness guard margin | 0.30 | penetration test on real thin-walled sherds |
| glaze-loss fraction, contact-band widths, chip radius, microcrack depth, soil thickness | 0.75, 2.5 mm, 4.0 mm, 1.6 mm, 0.18 mm, 60 µm | cross-sections / profilometry of real worn sherds |
| thin-sheet threshold | 1.0 mm | same |
| component sensitivities of the 14↔8 table | see the `evidence` column of §3 | a paired capture of the same objects with known synthetic levels |

---

## 9. Reproduction

```powershell
$R = "C:\Users\xiemo\Desktop\ShardForge"
# rig-error ladder (~30 s)
& "$R\relicweave-synlab\.venv\Scripts\python.exe" "$R\data\a12_reports\measure_rig_ladder.py"
# wear ladder (~15 min, 3 real bodies x 5 levels, writes data/a12_wear/store)
& "$R\relicweave-synlab\.venv\Scripts\python.exe" "$R\data\a12_reports\measure_wear_ladder.py"
# contract tests
& "$R\relicweave-synlab\.venv\Scripts\python.exe" -m pytest "$R\relicweave-synlab\tests\a12\operators" -q
```

`pytest tests/a12/operators -q` → **216 passed, exit code 0** (43 of them are the new realism
tests in `test_wear_rig_realism.py`).  This is the same suite that holds the 31-axis / 155-level
contract, so the new models did not disturb the shipped axes.
