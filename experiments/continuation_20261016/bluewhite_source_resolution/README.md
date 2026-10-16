# Source-resolved stationary sampling for the blue-white photo panel

This controlled pair enables `source_resolved_stationary_v1` while keeping the retained
Met 50899 fired-photo mask, actual bowl profile, panel placement, material profile, seeds,
field grid, and spread controls fixed. The no-spread member sets duration to zero; the second
uses the same 25% mobile fraction and default diffusion controls as the existing pair.

At continuous queries, the bound 75% fraction is sampled directly from the immutable
full-resolution source mask through the same finite `x=r(s)*wrap(theta-center_theta)` profile
mapping used to initialize the FV grid. The transported mobile fraction is sampled from the
conservative FV result. With zero transport, the continuous result is the unchanged source
field. Grid-center checks require all returned components to reproduce their recorded arrays.
The FV receipt remains `DISCRETE_GRID_MASS_ONLY`; it makes no claim that its discrete mass is
the quadrature of the continuous source field or that this field grid is converged.

The optional continuous-texture grid below is 480 × 2048 (983,040 samples), within the
existing 1,000,000-cell texture cap. Field-solver defaults remain 240 × 1024. Texture output
preflight includes the float32 RGB, mask, pigment-density, and sRGB PNG pixel payloads plus
fixed archive overhead and is checked against the existing 64 MiB per-instance limit before
texture allocation. Memory, field, CAD-time, and experiment-size caps are unchanged.

From the `relicweave-synlab` directory, generate new geometry candidates and replayable bundles:

```powershell
.\.venv\Scripts\python.exe experiments\continuation_20261015\reference_generation\run_generation.py `
  --recipe experiments\continuation_20261016\bluewhite_source_resolution\recipe.json `
  --output experiments\continuation_20261016\bluewhite_source_resolution\outputs_v1 `
  --texture-grid 480 2048
```

The renderer preview uses the existing VTK PBR path and same neutral studio IBL preset for
both controlled instances. It adds panel-normal close views, keeps the full four-view layout,
and records the actual stored texture dimensions:

```powershell
..\third_party\vesselforge-runtime\venv\Scripts\python.exe `
  experiments\continuation_20261016\bluewhite_source_resolution\render_previews.py `
  --output experiments\continuation_20261016\bluewhite_source_resolution\outputs_v1 `
  --preview-revision source_resolved_v1 `
  --lighting studio_ibl
```

After generating the bundles, produce a numeric off-grid comparison against
`grid_bilinear_v1`:

```powershell
.\.venv\Scripts\python.exe `
  experiments\continuation_20261016\bluewhite_source_resolution\source_detail_probe.py `
  --output experiments\continuation_20261016\bluewhite_source_resolution\outputs_v1
```

The numeric probe compares source-resolved and legacy grid-bilinear values at a deterministic
high-density source pixel for each instance. It is a sampling-detail comparison only, not a
claim about recovered pre-fire pigment, optical calibration, historical reconstruction,
continuous-source mass conservation, or fine-grid convergence.

The generated `outputs_v1/` pair shares geometry-array SHA-256
`7714b224dfc866d119cc1e42c664bf31c3ba6a05584630bad1c19b2f68195729`. Both instances export
the 480 × 2048 texture with the unchanged 240 × 1024 FV field grid. The deterministic maximum
source-pixel probe records total density `1.0` versus `0.7373948` for no-spread source-resolved
and legacy grid-bilinear sampling, and `0.8608327` versus `0.6638789` for default spread.
The FV grid arrays are bitwise equal between the two sampling modes; the difference is the
off-grid continuous reconstruction of the stationary fraction. The output manifest records
the shared studio-IBL preview settings and actual texture sizes. The complete experiment,
including PBR previews and the numeric probe, is 27,304,078 bytes, within the existing
256 MiB experiment cap and 64 MiB per-instance bundle cap.

The regenerated candidate has the same canonical geometry-array hash as the earlier v6
witness, but a different source-section hash. This bundle therefore does not claim the exact
run05 source chain, native binding, or fracture provenance; no native fracture test was run.
