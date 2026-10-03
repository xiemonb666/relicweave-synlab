# CAD-clipped cells, fixed 8 mm case03

**Decision: FAIL — `INCOMPLETE_COM_OUT`.** The corrected case03 run stopped after 58 of 294 boxes when the native center of mass for one retained clipped solid classified `OUT` against the canonical source. The output is a partial diagnostic with a complete per-box ledger, not a completed CAD volume partition.

## Input and run

The input is the manifest-selected canonical STEP at `relicweave-synlab/tmp/review_20261003/implementation/vf/artifacts/four_bands_brep_semantics1_final/geometry/solid.step`, SHA-256 `4623bd373aeed0acfacfbf6cc0dda65952339561779b43429c59d61b8b5a1c30`. The fixed grid used 8 mm spacing, 294 boxes (cap 512), and single-thread OCC `BOPAlgo_BOP` `COMMON` operations with a 300 second ceiling. Each processed cell used an exact native intersection; no corner or center exclusion shortcut was used.

The only COMMON run was invoked from the repository root with:

```powershell
& '.\third_party\vesselforge-runtime\venv\Scripts\python.exe' 'pgfrag\experiments\cad_clipped_cells_spike.py'
```

It exited `1`. The recorded experiment runtime was `1.187 s`, including `0.656 s` of Boolean work. It processed cells 0–57 and stopped at cell 57 (`ijk=[1,2,1]`, bounds `x=[-12.5,-4.5]`, `y=[-4.5,3.5]`, `z=[8,16]` mm). That cell produced component 48, volume `3.263481677 mm³`, with native COM `(-12.272229,-1.528229,8.656097) mm`; OCC classified it `OUT`. No alternate point was sampled and no additional COMMON run was made. The remaining 236 cells are recorded as not run.

The 58 processed cells contain 9 valid empty-material compounds and 49 positive native solids. Of the 49 retained solids, 48 COMs classified `IN` and one classified `OUT`. The output arrays and BREP files preserve those 49 pieces for review and are marked `INCOMPLETE_COM_OUT`, partial-diagnostic-only, not solver input, not a bond graph, and ineligible for training.

The processed solids sum to `7,699.598018 mm³`, or `29.674388%` of the canonical CAD volume. This is a partial retained-volume subtotal. **Full-partition volume accuracy and mass conservation are `NOT_EVALUATED_INCOMPLETE_PARTITION`; the former 70.3256% subtotal-versus-whole difference is not a partition error.** The candidate remains FAIL.

## Figure correction

The first PNG used world X/Z bounds as local UV bounds on a plane whose axes were not aligned to world X/Z. That clipped the source section. It is retained as `cad_clipped_cells_y0_SUPERSEDED_wrong_plane_uv.png` and is superseded by the figure below. The corrected diagnostic uses an explicit plane frame (`U=+X`, `V=+Z`, normal `-Y`) and was rendered from the saved canonical STEP plus the 49 saved component BREP files. This figure-only pass performed no Boolean COMMON operations.

![Corrected exact OCC y=0 section with saved clipped pieces and projected COMs](../../../../tmp/review_20261004/implementation/cad_clipped_cells/fixed8mm_singlethread_case03_native_empty_compound_policy/cad_clipped_cells_y0_ax3_corrected.png)

The canonical y=0 OCC section spans x `[-20.5, 32.6] mm` and z `[0, 56] mm`, matching the source bbox in that plane. Both negative-X and positive-X vessel walls were sampled in each of the z bands 8, 16, 24, 32, 40, 48, and 52 mm. The corrected PNG SHA-256 is `7f0e26809153e7f495f5feef46b99daf41e312428f9ff2d6c377e2deb215168f`.

The blue COM markers show all retained component COMs projected onto XZ; they do not mean those points lie on y=0. The red marker is the OUT COM that fails this representation. The pale clipped curves show only the 58 processed boxes, while the black source section covers the complete canonical solid.

## Interpretation and boundary

A connected non-convex clipped solid can have its exact volume centroid outside the solid or in a void. That is a failure for this one-COM-per-piece point-support rule. Moving the COM or selecting an interior point would change the first moment and would no longer represent the same quadrature rule. The OUT result therefore triggers review of point-support quadrature; it does not justify a point substitution, retry, threshold relaxation, or further mesh-size sweep.

The existing linear-tet h8 and h6 volume candidates remain FAIL at `2.03434%` and `1.61417%` volume error, respectively. The 8 mm grid is twice the nominal 4 mm wall thickness, so physical resolution remains `NOT_VALIDATED`. This result creates no PG job, bonds, solver input, fracture output, or training eligibility.

## Artifacts

- Machine report and per-gate reasons: `relicweave-synlab/tmp/review_20261004/implementation/cad_clipped_cells/fixed8mm_singlethread_case03_native_empty_compound_policy/report.json`
- Human report: `relicweave-synlab/tmp/review_20261004/implementation/cad_clipped_cells/fixed8mm_singlethread_case03_native_empty_compound_policy/report.md`
- Complete 294-row cell ledger, including 236 not-run rows: `relicweave-synlab/tmp/review_20261004/implementation/cad_clipped_cells/fixed8mm_singlethread_case03_native_empty_compound_policy/cell_records.json`
- 49 retained positive component BREP files and records: `relicweave-synlab/tmp/review_20261004/implementation/cad_clipped_cells/fixed8mm_singlethread_case03_native_empty_compound_policy/components/`
- Partial arrays, with incomplete provenance: `relicweave-synlab/tmp/review_20261004/implementation/cad_clipped_cells/fixed8mm_singlethread_case03_native_empty_compound_policy/cad_clipped_cells_candidate.npz`
- Corrected figure diagnostics: `relicweave-synlab/tmp/review_20261004/implementation/cad_clipped_cells/fixed8mm_singlethread_case03_native_empty_compound_policy/figure_diagnostics.json`
- Original failure logs and audit corrections: `relicweave-synlab/tmp/review_20261004/implementation/cad_clipped_cells/fixed8mm_singlethread_case03_native_empty_compound_policy/run.log`

Case01 and case02 historical failure artifacts under `review_20261003` were left unchanged.
