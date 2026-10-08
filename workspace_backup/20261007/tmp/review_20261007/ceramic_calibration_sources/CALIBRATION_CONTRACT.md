# Minimal fired-ceramic calibration contract

Status: design/interface only. No physical specimens were tested, and no literature values were written to solver or production configurations.

## Evidence boundary and current guard

- Literature and ASTM standards in [SOURCES.md](SOURCES.md) define test context. A literature number is not a measurement of this project's ceramic lot.
- Current project inventory says `0 physically qualified packs`. PG-Frag's toy card (`E=1 MPa`, `ν=0.3`, `ρ=1 kg/m³`, `K0=1e8 Pa/m`, `t_peak=1000 Pa`, `Gc=0.01 J/m²`) remains `NOT_MATERIAL_CALIBRATED`.
- Keep `material_calibration_status="NOT_MATERIAL_CALIBRATED"`, `production_material_card_admissible=false`, and `literature_values_promoted=false` until every promotion condition below is met. Missing values stay `null` with a reason; never fill from a generic ceramic value.
- A measured or fitted card is bound to its material lot, firing history, orientation, moisture condition, temperature, and test rate. A new condition creates a new state, not an implicit override.

## Minimum sample and measurement record

Start with one named fired-body lot that can be physically sampled. If that lot cannot supply valid coupons, record the limitation and stop the mechanical calibration claim. A replica body can calibrate only that replica recipe and firing process.

For each coupon, persist the following before testing:

| Group | Required fields |
|---|---|
| Identity | `material_lot_id`, `source_object_id` or `replica_batch_id`, `specimen_id`, extraction location, orientation, operator, fabrication date, chain-of-custody note |
| Body | clay/body recipe or `unknown`, temper type/size/fraction, additives/glaze, forming method and pressure, green dimensions, firing atmosphere, measured temperature curve, peak/soak/cooling, kiln/batch ID |
| State | dry/saturated/equilibrated state, dry mass, test-time mass, moisture content method and wt%, conditioning temperature, relative humidity, duration, test temperature |
| Geometry | measured coupon dimensions and tolerances, notch/crack geometry and images, surface finish, edge condition, loading span, fixture configuration |
| Method | standard plus edition or full nonstandard method, machine and calibration IDs, loading rate, support geometry, environment, valid/invalid decision and reason |
| Raw evidence | force-displacement/time series, crack-opening or crack-length observations, fracture-surface images, original filenames and SHA-256 for every raw file |

Use a pilot set for one body/firing/moisture condition: at least 10 valid flexural-strength coupons and 10 valid sharp-crack mode-I coupons; report every replicate and the mean, SD, range, and any justified exclusions. This is a project pilot minimum, not a quoted ASTM sample-count requirement or a reliability qualification. Measure bulk density/open porosity/water absorption on at least five companion coupons; collect dynamic `E`, shear modulus, and `ν` non-destructively on at least five matched coupons if geometry permits. Preserve raw observations even when an official method's sample geometry cannot fit the source fragment.

## Required outputs for a cohesive/fracture card

Store each value with its method, condition key, unit, statistic, `n`, uncertainty, source record IDs, and status (`MEASURED`, `DERIVED`, `FITTED`, `LITERATURE_CONTEXT`, `TOY`, or `UNKNOWN`). Keep static and dynamic moduli separate.

| Quantity | Minimum defensible evidence |
|---|---|
| `rho_bulk_kg_m3` | Dry mass / external volume for the stated fired condition; also record immersion-derived open porosity and water absorption when applicable. Do not use raw-material true density as bulk density. |
| `E_static_Pa` | Compliance-corrected loading slope on a recorded flexural/tensile geometry, or a clearly documented static method. |
| `E_dynamic_Pa`, `G_dynamic_Pa`, `nu_dynamic` | Matched resonance/impulse-excitation measurement with coupon mass and dimensions. Keep separate from static values and quantify directional variation. |
| `f_t_peak_Pa` | Direct tensile strength, or a documented mode-I cohesive inverse fit tied to measured force and crack-opening data. Flexural TRS alone is not `f_t`. |
| `K_Ic_modeI_Pa_sqrt_m` | Sharp-crack mode-I result under a stated fracture method, crack geometry, valid size checks, environment, rate, and crack-origin review. Retain method-specific value (e.g. `K_Ipb`, `K_Isc`, `K_Ivb`) rather than flattening distinctions. |
| `Gc_modeI_J_m2` | Direct energy release from a valid stable-growth/load-displacement or validated compliance/R-curve method, with surface-area convention recorded; otherwise mark `UNKNOWN`. A conversion from valid LEFM `K` is `DERIVED`, and requires the measured `E`, `ν`, constraint, and stated assumptions. |
| `traction_separation_law` | Chosen law family, peak traction, separation scale, softening shape, and measured/fitted work under the curve. Do not count the same fracture dissipation again in a separate Griffith gate. |

For isotropic LEFM mode I, use `G_Ic = K_Ic²/E'`, with `E'=E` in plane stress and `E'=E/(1−ν²)` in plane strain. These relations do not repair an indentation-derived apparent toughness or unknown `ν`.

## Process-zone and numerical-resolution gate

An energy/strength scale follows from dimensions and LEFM: stress intensity at a zone length `ℓ` scales as `K ~ f_t√ℓ`, while `G ~ K²/E'`. Equating `G` to `Gc` gives the characteristic scale

`ℓ_ch = E' Gc / f_t²`.

The actual cohesive process-zone length is `ℓ_pz = C_law · E' Gc / f_t²`; `C_law` depends on the traction-separation law, constraint, geometry, and zone-boundary definition. Do not assign a universal coefficient without fixing those choices. Units reduce to metres when `E'` and `f_t` are Pa and `Gc` is J/m². If any input is missing or is only literature-context/toy, the scale is `UNKNOWN`.

For PG-Frag, record `ℓ_ch`, the stated cohesive-law coefficient/definition, `ℓ_pz/h`, and horizon-to-zone relation separately. A wall thickness divided by `h`, number of particles across a wall, or one successful visual fracture is a geometry/discretization descriptor; it cannot by itself produce a physics-resolution `PASS`. Require at least three systematic refinements with force, initiation energy, dissipated energy, and fragment/candidate observables converging within predeclared tolerances. Report unresolved if the material scale or convergence is absent.

## Training and inference provenance guard

Each training/evaluation row must carry `dataset_version`, `observation_id`, `source_object_id`, `material_lot_id` if known, `raw_observation_hashes`, `label_source`, `label_method`, `annotator_or_instrument`, `ground_truth_accessed`, `split_group_id`, and `runtime_feature_allowlist`.

- The `observedfragment → rankedcandidates` runtime may read only fragment observations, public metadata, and explicitly admitted calibrated material fields. It must not read full-vessel ground-truth IDs, hidden candidate matches, reconstruction labels, or evaluation annotations.
- Offline labels may exist for evaluation/training, but split by source vessel/object (and lot where relevant); exclude labels and hidden match identifiers from runtime feature payloads, retrieval keys, caches, and logs used by ranking.
- Each rank result records input observation IDs/hashes and model/material-card versions. Set `gt_used_online=false` on every inference record and fail closed if the runtime feature allowlist admits a GT-only field.

## Promotion criteria and next executable task

Promotion requires: (1) a physically available, provenance-bound fired-body lot; (2) valid same-condition density/porosity, static and dynamic elastic data, tensile-strength evidence, and sharp-crack mode-I fracture evidence with dispersion; (3) an explicit cohesive law or justified LEFM model; (4) a computed process-zone scale and refinement study on the actual specimen geometry; and (5) an independent review of raw curves, fracture origins, unit conversions, and energy balance.

Next task: identify one candidate artifact/body lot that can supply coupons; freeze its provenance and moisture state; ask a ceramics lab to quote the above pilot matrix using ASTM C1421 methods where specimen scope fits, ASTM C1259 for dynamic elastic properties, and a matched flexural/tensile strength procedure. Do not change PG-Frag or VesselForge material files before the resulting raw measurements and independent review exist.
