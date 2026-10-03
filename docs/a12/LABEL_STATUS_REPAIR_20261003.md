# Label status evidence repair — 2026-10-03

## Change

Degradation label status now follows evidence for every declared `LABEL_INVALIDATIONS`
dependency. A nonzero axis with invalidations reports overall `RECOMPUTED` only when every
dependency has matching recomputation evidence. A failed recomputation remains `FAILED`; an
invalidated dependency without a matching artifact is `PENDING_RECOMPUTE`. Axes with no label
dependency report `NO_LABEL_DEPENDENCY`. Level 0 keeps `NOT_INVALIDATED_AT_LEVEL0`.

Importing `synlab.truth` and copying a `label_status` string no longer count as recomputation
evidence. The physical route calls `truth.api.update_residual_truth` in
`physical.api.apply_damage`. When the returned `PhysicalTruth` is attached to the output,
degrade records `PhysicalTruth: UPDATED` only after checking its clean-truth hash and next version,
mother/event identity, axis/variant/level/recipe, and source/result geometry provenance. The
logical receipt reference names the attached object path and recipe/version. `PhysicalTruth`
does not currently carry a producer-issued artifact hash, so the reference is a verifiable
runtime object identity with consistency fields, not a cryptographic producer receipt.

The physical route does not rebuild `VisibleLabels` or `FeatureAdapter`; those dependencies stay
`PENDING_RECOMPUTE`. Therefore P axes that update PhysicalTruth still report overall
`PENDING_RECOMPUTE` until the remaining declared dependencies have their own verified artifacts.
I03 changes sensor frames but records no label artifact, so its visible-label and feature-adapter
dependencies also remain pending even when its pixel effect is nonzero.

## API and report compatibility

`Measurement.extra` now includes `label_dependency_status` and `label_receipt_refs`. The same
fields, plus `label_validity`, are carried into the degradation commit QA record and operator
audit level rows and Parquet measurements. `label_validity=UNKNOWN_INVALIDATED` means some
declared label dependency remains unresolved; `PENDING_RECOMPUTE` does not imply those labels are
valid. Raw states such as `UNKNOWN` remain visible as `reported_status` on the relevant dependency
record, without being treated as completion evidence. Consumers that previously treated an
imported truth module or a reported `RECOMPUTED` string as success should use the aggregate
`label_status` and inspect the structured dependency records. A physical result's previous
`UPDATED` value is retained at the
`PhysicalTruth` dependency level; it does not imply that all invalidated labels were refreshed.
Legacy `PENDING_DEPENDENCY` outputs are normalized to `PENDING_RECOMPUTE` when no dependency
artifact is available.

`label_receipt_refs` are references, not new artifacts. They point to the in-memory
`payload.physical_result.physical_truth` object and include the recipe and resulting truth version.
No truth module is recreated here, and no visible-label or feature-adapter artifact is synthesized.

## Verification

The targeted test uses a 32 × 32 constant linear-RGB image: I03 changes pixels measurably while a
forged `RECOMPUTED` status remains pending. A separate 20 × 20 × 10 mm physical appearance fixture
executes the existing `apply_damage → update_residual_truth` route and confirms that valid
PhysicalTruth work is retained as `UPDATED`, with overall status pending for VisibleLabels and
FeatureAdapter. Tampered clean-truth references, output versions, and geometry references are
rejected. Level-0 identity, no-dependency, failed, missing-artifact, audit-row, and Parquet paths
are covered.

The runtime fixture is synthetic and proves status/provenance wiring only. It does not validate
archaeological labels, sensor calibration, or downstream model usability.
