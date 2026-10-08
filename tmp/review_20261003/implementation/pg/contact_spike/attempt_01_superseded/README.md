# Attempt 1 — superseded

The first runner invocation used the same fixed three cases but stopped each case before native integration while exporting initial point rows. The runner incorrectly offset body B's native local point IDs in its in-memory force dictionary, which raised `KeyError: (:b, 9)`; the B dictionary actually contained local IDs 1 through 8.

`run.log`, each case's `failure.log` / `summary.json`, `report.json`, and `contact_spike_actual_xz.png` are preserved here as evidence. All cases have zero integrated steps and the PNG contains no point state. Treat this attempt and image as superseded setup-failure evidence, not simulation output. The subsequent attempt uses explicit `body_local_point_id` and a separate unique `export_point_id`.
