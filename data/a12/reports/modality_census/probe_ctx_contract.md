# Modality Census — Excavation/Scene Context & Metadata Contract per Asset Role

**Scope:** read-only evidence census of `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab`.
**No code, config or existing data was modified.** All probe scripts and raw outputs live next to this
report in `data/a12/reports/modality_census/` (named `probe01_*` … `probe15_*`).
**Python:** `.venv\Scripts\python.exe`. Every sqlite database was opened
`sqlite3.connect("file:<path>?mode=ro&immutable=1", uri=True)`.

## Headline

**This system produces no excavation-context, scene-context or archaeological-context data.**
Every one of `site`, `trench`, `stratum`, `batch`, `lot`, `findspot`, `locus`, `square`,
`coordinate_ref`, `scale_ref`, `scalebar`, `soil`, `earth`, `matrix`, `deposit`, `parcel`, `plot`,
`coexist`, `environment` has **0 matching keys** across all stores. The only field literally named
`context` is a 4-key **sensor/acquisition** dict. The only field literally named `scene` is a
**renderer** scene, and its occluder bodies are anonymous icospheres whose parameters — but not
identities — are recorded, while the `occluders` key itself is a hardcoded scalar `0`.

## Evidence base and denominator stability (read this before quoting any number)

The store population **mutated during this census** because other agents were writing into the same
workspace concurrently:

| probe run (local time) | stores | assets |
|---|---|---|
| `probe01` 12:51:21 | 22 | — |
| `probe02` re-run | 23 | 2253 |
| `probe13` / `probe14` | 25 | 2459 |

`data/a12_smoke/_tmp/v23store/metadata.sqlite` was created at **12:52:07** and
`data/a12_degrade/{_probe_store,store}/metadata.sqlite` at **12:55:15 / 12:55:37** — all mid-session,
by sibling processes, not by this census. **The archaeological conclusions are invariant to this:**
re-running the nested keyword census at 23 vs 22 stores gives byte-identical per-keyword key-path
counts (`787` matching key paths both times, `probe02_keywords.txt`).

Denominators used below:
- **Per-role contract (part B): `data/a12/metadata.sqlite`, 894 assets, 20 roles** (the store the task names).
- **Keyword census: 23 stores, 2253 assets, 7478 distinct `meta` key paths, 787 of them matching the keyword list.**
- **Vocabulary census (all stores at that moment): 25 stores, 2459 assets, 23 distinct roles.**

### One structural fact that determines how every key must be searched

`assets.meta_json` is a JSON object. Two different layouts exist, and **dotted paths are stored as
literal flat key strings, not nested dicts**:

- `probe05_flatkeys.txt` PART 0: for 20 of 21 observed roles `meta_json` is **flat at top level**;
  only `obs_result` wraps its metadata under a top-level `"meta"` key (119/119 rows wrapped).
- Example (`probe04_raw_meta.txt`), a real `degrade_measurement` row whose top-level keys include the
  literal strings `"payload.context.input_profile"`, `"payload.context.route"`, `"payload.scene.light"`.
  A `dict["payload"]["context"]` lookup therefore returns nothing; a substring scan over key names is
  the only correct search. `probe03`'s "0 context dicts" is an artefact of the opposite assumption and
  is superseded by `probe02`/`probe05`.

---

## A) CONTEXT DATA

### A1. Keyword census over every `meta_json` in every `metadata.sqlite`

`probe02_keywords.py` / `.txt` (nested key-path scan, 23 stores / 2253 assets / 7478 key paths).
Counts are **#assets carrying at least one key whose name contains the keyword**.

| keyword | key paths | verdict | what actually matched |
|---|---|---|---|
| `site` | 0 | **无** | — |
| `trench` | 0 | **无** | — |
| `stratum` | 0 | **无** | — |
| `batch` | 0 | **无** | — |
| `findspot` | 0 | **无** | — |
| `locus` | 0 | **无** | — |
| `square` | 0 | **无** | — |
| `coordinate_ref` | 0 | **无** | — |
| `scale_ref` | 0 | **无** | — |
| `scalebar` | 0 | **无** | — |
| `soil` | 0 | **无** | — |
| `earth` | 0 | **无** | — |
| `matrix` | 0 | **无** | — |
| `deposit` | 0 | **无** | — |
| `parcel` | 0 | **无** | — |
| `plot` | 0 | **无** | — |
| `coexist` | 0 | **无** | — |
| `environment` | 0 | **无** | — |
| `episode` | 0 | **无** | role `episode_trace` is declared in code but **no asset exists** (see A3) |
| `lot` | 144 | **false positive** | substring of **`blotch`** — `pattern_recipe` → `recipe.meta.bands.blotch.*`, `recipe.params.blotch.*` (n=3 assets) |
| `strat` | 1 | **false positive** | substring of **`substrate`** — `measured.revealed_substrate_fraction` (`physical_component`, n=12) |
| `grid` | 20 | **not archaeological** | numeric sampling grids: `recipe.meta.spectrum.grid.{ds_mm,dx_mm,n_s,n_x}`, `raster.grid.*`, `measured.grid_spacing_mm`, `event_tree.cutter.meta.grid_level` |
| `env` | 2 | **false positive** | substring of **`envelope`** — `mother_meta.assembly.warp.spec.envelope_{top,bottom}` (n=14) |
| `feature` | 38 | **not archaeological** | ML feature vectors: `feature_fields[]` (`feature_bundle`, n=107), `integrity.features_hash`, `geometry_feature_mm` (a **length in mm**), `fragment_records.*.feature_ref` |
| `provenance` | 7 | **software provenance** | `provenance_view_histogram[]` (`obs_result`, n=115) and `provenance.{note,source_kind}` (`material_profile`, n=103) — build/source lineage, not archaeological provenance |
| `association` | 4 | **model-relation association** | `history.association_kind` (n=394), `association_counts.{EXACT_SURVIVOR,UNKNOWN_MAPPING,VERIFIED_RECESSION}` — truth-layer clean↔physical↔visible mapping counts |
| `group` | 80 | **not archaeological** | ML/pattern grouping: `groups[]` (`feature_bundle`, n=133), `recipe.params.groups[].*` (pattern geometry), `surface_group_source` (`display_lod_glb`) |
| `roster` | 37 | **query roster** | `roster[]` in `relation_pool` (8) + `query_roster` (4): `fragment_id`, `gallery_id`, `mother_id`, `lineage_cluster`, `split`, `mate_present`, `historical_neighbours[]`, `applicability.{scope,gallery_version}` |
| `scene` | 72 | **renderer scene** | see A4 |
| `unit` | 119 | **units of measure** | `mm`, `px`, `1`, `mm/mm`, `1/mm2`, `m` etc. — **not** stratigraphic units |
| `layer` | 255 | **truth layer** | see A1b |
| `context` | 8 | **sensor context** | see A2 |

### A1b. What `layer` actually means — verified in the writer code

`layer` is the **truth layer** (`clean` / `physical` / `visible`), **not** a stratigraphic layer.

Code (`grep -n '"layer"' synlab/`, re-verified):

| citation | value |
|---|---|
| `synlab/truth/api.py:85` | `LAYER_CLEAN = "clean"` |
| `synlab/truth/api.py:86` | `LAYER_PHYSICAL = "physical"` |
| `synlab/truth/api.py:87` | `LAYER_VISIBLE = "visible"` |
| `synlab/truth/api.py:422`, `:671`, `:1090` | `"layer": LAYER_CLEAN` |
| `synlab/truth/api.py:798`, `:821` | `"layer": LAYER_PHYSICAL` |
| `synlab/truth/api.py:1025`, `:1046` | `"layer": LAYER_VISIBLE` |
| `synlab/truth/api.py:1232` | `meta["layer"] = meta.get("layer") or obj_role` |
| `synlab/physical/api.py:937` | `"layer": "physical"` |
| `synlab/pipeline.py:1239` | `qa={"ok": True, "layer": "visible"}` |
| `synlab/training/labels.py:157`, `:199` | `QUALITY_LAYER`, `CORRESPONDENCE_LAYER` |
| `synlab/materials/layers.py:235`, `:254`, `:258` | material **shell** layers (`measurements={"layer": entry.get("name"), "thickness_mm": ...}`) |
| `synlab/relations/negatives.py:173` | library layer |

Roles carrying the truth-layer key: `clean_truth`=112, `physical_truth`=93, `visible_labels`=88,
`physical_result`=57 (occurrences across all stores). The remaining `layer` hits are pattern
`aux_layers` (multi-layer painted decoration, `pattern_recipe` n=126) and material `layer_ids`
(`material_profile` n=103) — ceramic wall/slip/paint shells, again not stratigraphy.

### A2. `X02` and `X03` in `synlab/degrade/axes.py` — what "context" really is

**X02** (`synlab/degrade/axes.py:2169`, `AXIS_ID = "X02"` at `:2170`) — *not* a context axis at all.
It is **mask estimation**: variants `boundary_error`, `missing_blob`, `false_positive`,
`crop_and_mask_error` (`:2174-2176`), levels `boundary_px ∈ {0,1,2,3,5}` (`:2178`). It reads
`mask`, `mask_reference`, `K`, `crop` from the source bundle (`:2215-2219`) and erodes/dilates/labels
mask regions (`:2222-2259`). Its applicability gate is
`X02 needs the observed mask (payload 'mask')` (`:2195`). **There is no archaeological quantity in X02.**

**X03** (`synlab/degrade/axes.py:2318`) — `AXIS_ID = "X03"` (`:2319`), `default_variant = "missing_context"` (`:2320`),
variants `missing_context` and `conflicting_context` (`:2322-2323`), `ALIASES = {"context_error": "missing_context"}` (`:2324`),
levels `missing_rate` / `conflict_rate` ∈ `{0.0, 0.1, 0.2, 0.3, 0.5}` (`:2325-2327`).

X03 treats `context` as an **opaque key→value mapping**. It never interprets a key:

- gate: `context = source.get("context")`; empty ⇒ `X03 needs the observed context mapping (payload 'context')` (`:2332-2335`)
- `_sample_payload`: `keys = sorted(dict(source.get("context") or {}))` (`:2339`), frozen permutation → `key_order` (`:2341`)
- `_apply` (`:2343-2374`):
  - `missing_context` → `context[key] = None` for the first `ceil(rate × len(keys))` keys (`:2347`, `:2356-2357`)
  - `conflicting_context` → `context[key] = context.get(other)` where `other` is the **next key cyclically** (`:2352-2353`)
- writes `payload = {"context": context}` (`:2368`) and `extra = {"touched", "conflicts", "missing", "parent_encoding_used": False, "source_provenance": "OBS_CONTEXT"}` (`:2371-2374`)
- measured block keys (`:2359-2366`): `rate`, `keys_total`, `keys_touched`, `keys_missing`, `keys_conflicting`, `keys_present_after`
- invariant (`:2376-2382`): `{"missing_and_conflict_separated": ..., "code": "MISSING_CONFLATED_WITH_CONFLICT"}` — violated iff `keys_missing > 0 and keys_conflicting > 0`

**The concrete field names and values.** The dict is built in exactly one place —
`synlab/degrade/api.py:629-632`:

```python
"context": {"route": str(meta["route"]),
            "input_profile": str(meta["input_profile"]),
            "n_views": len(frames),
            "scale_valid": bool(getattr(observation, "scale_valid", True))},
```

Real values observed (`probe05_flatkeys.txt` PART 2, all stores):

| key | distinct values (count) |
|---|---|
| `payload.context.route` | `"proxy_scan"` (49/49) |
| `payload.context.input_profile` | `"SENSOR_PROXY"` (41), `null` (8) |
| `payload.context.n_views` | `4` (49/49) |
| `payload.context.scale_valid` | `true` (45), `null` (4) |

Roles carrying it: `feature_bundle`=29, `degrade_measurement`=20. Stores: `data/a12/metadata.sqlite`,
`data/a12_demo/store`, `data/a12_exports/_scratch/store_backup_a12`.

Real X03 assets: **8**, all in `data/a12/metadata.sqlite`, all `role=degrade_measurement`,
`axis_id="X03"`, `variant="missing_context"`, `schema=synlab.measurement.v1`, `unit=1`, `frame=S_mm`.
Example (`probe05_flatkeys.txt` PART 6, `asset_3208df03080664c25637`, level 1):

```
payload.context.route         = "proxy_scan"
payload.context.input_profile = null          # <- the single key X03 nulled
payload.context.n_views       = 4
payload.context.scale_valid   = true
measured = {"rate":0.1,"keys_total":4.0,"keys_touched":1.0,"keys_missing":1.0,
            "keys_conflicting":0.0,"keys_present_after":3.0}
planned  = {"missing_rate":0.1,"variant":"missing_context"}
units    = {}
```

`units = {}` and `keys_total = 4.0` for all 8 assets.
**Verdict: this is sensor/observation "context" (acquisition route, input profile, view count, scale
validity). It is not archaeological context.** `OBS_CONTEXT` at `:2374` is the honest label.

### A3. `synlab/episodes/env.py` + `synlab/episodes/api.py` — does an EpisodePack place the fragment in an environment with other objects?

**No. 无 real episode artifact exists.** Verified two ways:

- `probe06_episode_search.py` over every `metadata.sqlite`: **0 assets with `role='episode_trace'`**,
  **0 assets with `schema LIKE '%episode%'`**, and **0 rows in every `api_episodes` table**.
- `probe14_roles.py`: `episode_trace` is one of 11 roles declared in `synlab/roles.py` with **zero
  assets in any store**.
- `docs/a12/registry.json` has **92 entries** (axes / patterns / materials / vessels / layer combos /
  fracture backends) and **no episode or env entry** (`probe07_registry.py`).
- The only artifacts matching `stop_reason` are training-loop reports
  (`data/a12_trainable/reports/batch_driver.json:287` `"max_invocations_reached"`,
  `neg_run.json:324` `"indices_exhausted"`) — unrelated to episodes. `data/a12/reports/api_security.json`
  lists episode **routes** (`/api/synlab/episodes/{episode_id}[/reset|/step]`) but no runs.

What exists is the **code contract only**. The environment is over a *frozen gallery of other
fragments* — i.e. candidate **comparison** objects, not a physical scene:

| element | real field / value | citation |
|---|---|---|
| role / schema | `episode_trace` / `synlab.episode.v1` | `synlab/roles.py:54`, `:21` |
| commit unit / frame | `UNIT_NONE` = `"1"`, `FRAME_WORLD` = `"W_mm"` | `synlab/episodes/api.py:25`, `:211`; `roles.py:68`, `:69` |
| env version | `ENV_VERSION = "episodes.env.v1"` | `synlab/episodes/env.py:31` |
| STOP action | `STOP_ACTION = "STOP"` | `synlab/episodes/env.py:33` |
| action kinds (8) | `STOP`, `U_MOVE`, `LOCAL_FRACTURE_FRAME`, `ADD_AZIMUTH`, `ADD_ELEVATION`, `TOGGLE_LIGHT`, `TOGGLE_POLARIZATION`, `RECLAMP_FLIP` | `synlab/episodes/env.py:36-43` |
| default budget (STOP fields) | `{"max_actions": 6, "max_seconds": 600.0, "candidate_pool_size": 50}` | `synlab/episodes/env.py:52` |
| cost schema (per step) | `seconds`, `capture_seconds`, `inference_seconds`, `manual_seconds`, `frames`, `risk_events`, `delta_cov_recall`, `reward`, `cumulative`, `action` | `synlab/episodes/env.py:406-418` |
| cumulative cost keys | `seconds`, `capture_seconds`, `manual_seconds`, `inference_seconds`, `frames`, `actions` | `synlab/episodes/env.py:266-267`, `:359-366` |
| state (11 fields) | `episode_id`, `query_id`, `step`, `obs_version`, `revealed_views`, `candidate_ids`, `cumulative_cost`, `done`, `stop_reason`, `available_actions`, `meta` | `synlab/schemas/runtime.py:558-569` |
| stop reasons | `"BUDGET_ACTIONS"`, `"BUDGET_TIME"` (`:380-381`), `"NO_AVAILABLE_ACTION"` (`:403`), `"STOP"` (`:463`) | `synlab/episodes/env.py` |
| reward weights | `{"lambda_time": 1.0/600.0, "lambda_risk": 1.0}`; `reward = (gt_cov_after - gt_cov_before) - penalty` | `synlab/episodes/env.py:90-91`, `:373-375` |
| state/meta contract | `"no_ground_truth": True`; `no_ground_truth` also asserted in the docstring: the state carries observable information alone | `synlab/episodes/env.py:277`, `:13-15` |
| step return | `(EpisodeState, cost_dict, done: bool)` | `synlab/episodes/env.py:301-302`, `:450` |

Notable honesty properties actually implemented: no free camera teleport
(`:318-325` "an arbitrary camera teleport is not a legal action"), `pool_rerank_only` when no new
candidate enters (`:356`, `:395`), `no_new_evidence` when the observer returns nothing (`:393`), and
`environment_side_only: True` on every trace row (`:448`, `:483`).

**Closest existing substitute for "scene context":** the `obs_view` renderer scene (A4). **Closest
substitute for "other objects":** the gallery/roster candidate list (A5) — synthetic fragments from
the same generative family, never co-located physical objects.

### A4. `obs_view` `payload.scene.*` — is that a "scene context"?

Denominators from `probe15_obsview_scene.py` (`data/a12/metadata.sqlite`, role `obs_view`):

- **48 obs_view assets total**; unit `px` 48/48; frame `S_mm` 48/48; `qa_status = QA_PENDING` 48/48
- carrying **any** `payload.scene*` key: **48 / 48**
- carrying `payload.scene.occluders` (the scalar `0`): **32 / 48**
- carrying the real occluder **parameter** set: **8 / 48**
- scene keys with no occluder (lighting only): 8 / 48
- carrying no scene key: **0 / 48**
- **33 distinct `payload.scene.*` key names**

Exact sub-keys and real values (n out of 48):

| key | n | real values |
|---|---|---|
| `payload.scene.light` | 32 | `"ObsSpec.resolved_light"` — **a reference STRING**, not intensity/colour numbers |
| `payload.scene.occluders` | 32 | `0` — **hardcoded scalar**, `synlab/degrade/api.py:923` |
| `payload.scene.knob` | 16 | `"lighting"` (8), `"occluder"` (8) |
| `payload.scene.level` | 16 | `1`, `2`, `3`, `4` (4 each) |
| `payload.scene.seed` | 16 | `1685261052` (8), `321779558` (8) |
| `payload.scene.occluder_capacity` | 8 | `6` |
| `payload.scene.occluder_count` | 8 | `1`, `2`, `3`, `4` (2 each) |
| `payload.scene.occluder_radius_mm` | 8 | `3.9`, `4.8`, `5.7`, `6.6` (2 each) |
| `payload.scene.occluder_min_radius_mm` | 8 | `3.0` |
| `payload.scene.occluder_directions.{0..5}.{0,1,2}` | 8 | 6 frozen unit vectors, e.g. `(0.3990888332807723, -0.7287480593622461, -0.5564659640322596)` |
| `payload.scene.target_coverage` | 8 | `0.15`, `0.3`, `0.45`, `0.6` (2 each) |
| `payload.scene.light_intensity_scale` | 8 | `1.3`, `1.6`, `1.9`, `2.2` (2 each) |
| `payload.scene.saturation_target` | 8 | `0.1`, `0.2`, `0.3`, `0.4` (2 each) |
| `payload.scene.brdf_specular_scale` | 8 | `1.0` |
| `payload.scene.bundled` | 8 | `false` |
| `payload.scene.variant` | 8 | `"fixed_light_specular_profile"` |

**Are the occluders physical objects with identity? No — they are anonymous spheres.**
`synlab/degrade/api.py:829`: `block = trimesh.creation.icosphere(subdivisions=1, radius=radius)`.
They are placed at `centre + unit_view*(0.35*distance) + lateral*radius` between the object and one
camera (`:834-844`), then merged into the render mesh with `face_id = -1` and `is_target = 0`
(`:867-870`) and a generic albedo `[0.25,0.24,0.22]` / roughness `0.8` (`:862-866`). They carry **no
name, no catalogue id, no material id, no findspot** — only the frozen direction jitter
(`synlab/degrade/axes.py:1270-1275`, `occluder_capacity: 6`) and a level-derived count/radius
(`axes.py:1277-1282`: `occluder_count = round(target_coverage*6)`, `occluder_radius_mm = 3.0+6.0*coverage`,
`occluder_min_radius_mm = 3.0`). The **placed bodies are never persisted**: only count/radius/directions
reach the asset meta, and the `occluders` key itself is the constant `0`.

**Verdict:** `payload.scene.*` is a **rendering/appearance parameter block** (lighting + occlusion
proxies used to re-render a degraded view). It is a "scene" in the computer-graphics sense: a single
target object plus anonymous occluder spheres plus a light reference string. It is **not** an
archaeological scene: no other identified artefacts, no spatial relations, no depositional setting.
The honest label is *renderer scene*, and the light field is a symbolic pointer rather than data.

### A5. Does anything group fragments by "same batch / same mother / same event"?

`probe08_relations.py`, `probe09_prov_truth.txt` (A1b section), `probe14_roles.py`.

**Batch / lot: 无.** `bag_id` (the closest word) appears **only as a forbidden field name** —
`synlab/roles.py:88` and `synlab/observe/features.py:59` — and **0 assets in any store carry a
`bag_id`, `batch`, `lot_id`, `group_id`, `object_id`, `generator_family` or `generator_family_id` key**.
There is no batch/lot grouping concept anywhere.

**Mother / event grouping: yes, and this is the real substitute.** Key presence across all stores
(counted as assets carrying the key name at any depth):

| grouping key | assets | roles |
|---|---|---|
| `mother_id` | 836 | `mother_mesh`=168, `pattern_channels`=121, `clean_truth`=115, `label_bundle`=102, `physical_truth`=95, `visible_labels`=89, `physical_result`=59, `feature_bundle`=55, `pattern_recipe`=20, `relation_pool`=8, `query_roster`=4 |
| `event_id` | 741 | `fragment_mesh`=322, `clean_truth`=115, `physical_truth`=95, `visible_labels`=89, `physical_result`=59, `display_lod_glb`=27, `feature_bundle`=26, `relation_pool`=8 |
| `fragment_id` | 702 | `fragment_mesh`=322, `label_bundle`=102, `physical_truth`=95, `visible_labels`=89, `feature_bundle`=55, `display_lod_glb`=27, `relation_pool`=8, `query_roster`=4 |
| `parent_id` | 115 | `clean_truth`=115 |
| `interface_id` | 210 | `clean_truth`=115, `physical_truth`=95 |
| `lineage_id` | 155 | `obs_result`=121, `feature_bundle`=26, `relation_pool`=8 |
| `split` | 12 | `relation_pool`=8, `query_roster`=4 |

So grouping is by **generative lineage → mother → fracture event → fragment** (a synthetic
manufacturing/breakage genealogy), never by excavation batch.

**`relation_pool` (role `relation_pool`, 8 assets) — real meta keys.**
Top-level keys and carriers (n of 8): `api_version` 8, `fragment_records` 8, `gallery` 8,
`gallery_distractor_only` 8, `n2_materialised` 8, `pool_meta` 8, `relation_storage` 8, `roster` 8,
`schema` 8, `run_id` 1. Schema `synlab.pool.v1`, unit `1`, frame `W_mm`.
Real `gallery` value (`data/a12/metadata.sqlite`, `asset_19175585a8cd5d10cf52`):

```
{"gallery_version":"v1",
 "hash":"sha256:9d883914816807788103c64ba4de47d0ded1f6dfb0c767f9b6fcbf36a15269ef",
 "lineage_ids":["LIN0000_V10_M11_PAT15","LIN0001_V02_M01_PAT01","LIN0001_V21_M06_PAT16",
                "LIN0002_V03_M01_PAT01","LIN0002_V23_M07_PAT12","LIN0005_V03_M11_PAT16",
                "LIN0014_V16_M07_PAT10","LIN0018_V09_M05_PAT04"],
 "pool_id":"sandbox_dev","scope":"FULL","size_target":200,"split":"dev"}
```

Real `pool_meta` keys: `distractor_isolated`, `distractor_overlap`, `edge_counts_loaded`
(`{"R1":158,"R2":21,"TINY_CONTACT":0,"UNKNOWN":2}`), `out_of_gallery_neighbours`,
`portable_json` (`"PENDING"`), `query_per_mother` (`4`), `refinement_candidates` (`[10,20,50]`),
`release`, `top_k` (`[1,5,10]`). `fragment_records` is a dict with 23 entries (keys are fragment ids,
values carry `feature_ref`); `roster` is a list of 15 entries with keys
`applicability.{gallery_version,scope}`, `fragment_id`, `gallery_id`, `historical_neighbours[]`,
`lineage_cluster`, `mate_present`, `mother_id`, `query_id`, `split`, `status`.

`query_roster` (4 assets) keys: `frozen`, `gallery_version`, `hash`, `pool_id`, `queries`, `roster`
(+`run_id` on 1); schema `synlab.roster.v1`, unit `1`, frame `W_mm`.

**`research/relations.parquet` — real columns and cardinalities.**
`data/a12_exports/next_experiment/training_package/research/relations.parquet`: **150 rows × 12 columns**.

| column | dtype | unique | value counts |
|---|---|---|---|
| `query` | object | 58 | max `'LIN0014_V16_M07_PAT10_E01-m'`:11 |
| `candidate` | object | 58 | max `'LIN0014_V16_M07_PAT10_E01-p__+1c6'`:11 |
| `kind` | object | 2 | `R1`:117, `R2`:33 |
| `area_mm2` | float64 | 34 | `0.0`:117, then distinct areas |
| `valid` | bool | 2 | `False`:117, `True`:33 |
| `loss_mask` | bool | 2 | `False`:117, `True`:33 |
| `pool_id` | object | 1 | `''`:150 (**empty for every row**) |
| `split` | object | 4 | `''`:115, `train`:20, `confirm`:14 |
| `lineage_cluster` | object | 19 | `''`:115, `LIN0014_V16_M07_PAT10`:11, `LIN0007_V08_M01_PAT01`:3, … |
| `eligible_as_negative` | bool | 1 | `False`:150 |
| `has_observation` | bool | 1 | `False`:150 |
| `reason` | object | 2 | `no_direct_fracture_surface (same event, mutually exclusive)`:117; `shared_new_fracture_surface;…`:33 |

**Yes — `lineage_cluster` and `split` do provide grouping**, but they are *leakage-control* groupings:
`lineage_cluster` = the mother lineage (`LIN0014_V16_M07_PAT10`), `split` = `train`/`confirm`/`dev`
assignment for leakage-safe evaluation. `lineage_cluster` is populated on only **35 / 150** rows
(115 empty). Both are declared **forbidden model inputs** (`synlab/roles.py:91-92`:
`"lineage_id"`, `"split"`), i.e. they are *grouping keys for evaluation*, deliberately withheld from
the features. They do **not** encode "same excavation batch".

The `reason` string `no_direct_fracture_surface (same event, mutually exclusive)` is the closest
textual trace of an "event": fragments named `…_E01-m` / `…_E01-p` share fracture event `E01`, and the
`event_id` field (741 assets) records exactly that.

---

## B) METADATA CONTRACT PER ROLE (three-source cross-check)

Sources cross-checked:
1. **artifact**: `data/a12/metadata.sqlite` `assets` table (894 rows, 20 roles) — `probe12_role_table.py` / `.txt`
2. **`synlab/roles.py`** constants — 20 `SCHEMA_*`, 32 `ROLE_*`, 3 `UNIT_*`, 5 `FRAME_*` (line numbers re-verified)
3. **`synlab/schemas/runtime.py`** dataclasses — `28` `@dataclass` definitions (verified: `(Select-String -Pattern '^@dataclass').Count` = 28)

Contract vocabulary in code: `UNIT_MM="mm"` (`:66`), `UNIT_PX="px"` (`:67`), `UNIT_NONE="1"` (`:68`);
`FRAME_WORLD="W_mm"` (`:69`), `FRAME_FRAGMENT="F_mm"` (`:70`), `FRAME_SCAN="S_mm"` (`:71`),
`FRAME_CAMERA="C_mm"` (`:72`), `FRAME_PIXEL="pixel_cv_center"` (`:73`).

| role | rows | schema (+n) | unit (+n) | frame (+n) | qa_status (+n) | runtime dataclass (file:line) | MISMATCH |
|---|---|---|---|---|---|---|---|
| `clean_truth` | 55 | `synlab.truth.clean.v1`:55 | `mm`:55 | `W_mm`:55 | `QA_PASS`:55 | `CleanTruth` runtime.py:295 | none |
| `mother_mesh` | 71 | `synlab.mother.v1`:71 | `mm`:71 | `W_mm`:71 | `QA_PASS`:71 | `MotherGeometry` runtime.py:64 | none |
| `fragment_mesh` | 154 | `synlab.fragment.v1`:154 | `mm`:154 | `W_mm`:154 | `QA_PASS`:154 | `Fragment` runtime.py:193 | none |
| `material_profile` | 50 | `synlab.material.v1`:50 | `mm`:50 | `W_mm`:50 | `QA_PASS`:50 | `MaterialSample` runtime.py:103 | 19/50 rows carry `schema` in meta (harmless self-echo) |
| `pattern_recipe` | 59 | `synlab.pattern.v1`:59 | `mm`:59 | `W_mm`:59 | `QA_PENDING`:53, `QA_PASS`:5, `QA_FAIL`:1 | `PatternRecipe` runtime.py:130 | `mother_id` present in only **6/59** rows |
| `pattern_channels` | 59 | `synlab.pattern.v1`:59 | `mm`:59 | `W_mm`:59 | `QA_PENDING`:53, `QA_PASS`:5, `QA_FAIL`:1 | `PatternChannels` runtime.py:144 | same `synlab.pattern.v1` for **two** different roles |
| `physical_component` | 55 | `synlab.physical.v1`:55 | `mm`:55 | `F_mm`:55 | `QA_PENDING`:55 | `PhysicalComponent` runtime.py:342 | none (`component_id` is `str` in artifacts — matches `runtime.py:343`; see the type check below) |
| `physical_result` | 30 | `synlab.physical.v1`:30 | `mm`:30 | `F_mm`:30 | `QA_PASS`:16, `QA_FAIL`:14 | `PhysicalResult` runtime.py:354 | same `synlab.physical.v1` for `physical_component` **and** `physical_result` |
| `physical_truth` | 43 | `synlab.truth.physical.v1`:43 | `mm`:43 | `W_mm`:43 | `QA_PASS`:43 | `PhysicalTruth` runtime.py:318 | none |
| `visible_labels` | 41 | `synlab.truth.visible.v1`:41 | `mm`:41 | `W_mm`:41 | **`QA_FAIL`:23, `QA_PASS`:18** | `VisibleLabels` runtime.py:330 | none (QA_FAIL is real, see C2) |
| `obs_view` | 48 | `synlab.obs.v1`:48 | **`px`:48** | `S_mm`:48 | `QA_PENDING`:48 | `ObsView` runtime.py:432 | **same schema id as `obs_result`/`obs_fused_geometry` but unit `px` vs `mm`** |
| `obs_result` | 37 | `synlab.obs.v1`:37 | `mm`:37 | `S_mm`:37 | `QA_PASS`:37 | `ObservationResult` runtime.py:449 | **`observe/api.py:215` can write `unit="unknown"` — not in roles.py; 12 such assets exist in other stores** |
| `obs_fused_geometry` | 32 | `synlab.obs.v1`:32 | `mm`:32 | `S_mm`:32 | `QA_PENDING`:32 | — (no dataclass; fused mesh inside `ObservationResult.fused_mesh`, runtime.py:464) | no dataclass of its own |
| `feature_bundle` | 45 | `a12.obs.v1`:45 | `mm`:45 | `S_mm`:45 | `QA_PASS`:45 | — (no dataclass; produced by `training/adapter.py`) | **no runtime dataclass**; 3 different units across stores for this role (`mm`:157, `1`:29) |
| `label_bundle` | 45 | **`synlab.labels.v1`:45** | `1`:45 | `W_mm`:45 | `QA_PASS`:45 | — (no dataclass) | **`synlab.labels.v1` is NOT declared in roles.py** (no `SCHEMA_LABELS`) |
| `provenance` | 45 | **`synlab.provenance.v1`:45** | `1`:45 | **`none`:45** | `QA_PASS`:45 | — (no dataclass; `pipeline.py:80-91` `Provenance`) | **schema NOT in roles.py; frame `"none"` NOT in roles.py** |
| `degrade_measurement` | 20 | `synlab.measurement.v1`:20 | `1`:20 | `S_mm`:20 | `QA_PENDING`:20 | `Measurement` runtime.py:486 | none |
| `relation_pool` | 2 | `synlab.pool.v1`:2 | `1`:2 | `W_mm`:2 | `QA_PASS`:2 | `GallerySpec` runtime.py:531 | none |
| `query_roster` | 1 | `synlab.roster.v1`:1 | `1`:1 | `W_mm`:1 | `QA_PASS`:1 | `QueryRosterEntry` runtime.py:544 | none |
| `qa_report` | 2 | `synlab.qa.v1`:2 | `1`:2 | **`none`:2** | `QA_PASS`:2 | — (no dataclass) | **frame `"none"` NOT in roles.py**; only 1 of 2 rows carries a meta key (`doctor`) |

**`runtime.py` contains no role→dataclass registry.** It defines 28 dataclasses
(`runtime.py:39`…`:558`) with plain names and **no schema/unit/frame constants at all**; the mapping in
column 7 is by name correspondence, verified case by case. So a code-vs-artifact mismatch of the
"role says `px`, dataclass says `mm`" kind cannot arise from `runtime.py` — it has no unit to disagree
with. The unit/frame authority is `synlab/roles.py` plus each writer call site.

**Checked and found *consistent* (not a mismatch): `component_id` has two different types in
`runtime.py` — `int` at `:204` (`Fragment`) and `str` at `:343` (`PhysicalComponent`) / `:452`
(`ObservationResult`) — and the artifacts match each exactly** (`probe16_id_types.py`, all stores):

| role | real JSON type | n | sample | matching dataclass |
|---|---|---|---|---|
| `fragment_mesh` | `int` | 341 | `0` | `Fragment.component_id: int` (`runtime.py:204`), written `synlab/pipeline.py:1160` `int(fragment.component_id)` |
| `physical_component` | `str` | 88 | `"LIN0000_V01_M01_PAT01_E01-m#c0"` | `PhysicalComponent.component_id: str` (`runtime.py:343`) |
| `feature_bundle` | `str` | 136 | `"LIN0002_V03_M01_PAT01_E01-m#c0"` | `synlab/pipeline.py:1313` `str(meta.get("component_id","") or "")` |
| `label_bundle` | `str` | 106 | `"LIN0000_V01_M01_PAT01_E01-m#c0"` | — |

Also verified consistent: `observation_id` is `str` in `feature_bundle` (136), `label_bundle` (106) and
`visible_labels` (96), sample `"obs_e3a49a7fc27b09f91100"`.

### Global vocabulary census vs `roles.py` — the real mismatches

`probe13_vocab.py` / `probe13_vocab.txt` (all stores at scan time: 25 stores, 2459 assets).

**Units on assets:** `mm` 1843 ✓, `1` 297 ✓, `px` 189 ✓, **`m` 118 ✗**, **`unknown` 12 ✗**.
**Frames on assets:** `W_mm` 1378 ✓, `S_mm` 612 ✓, `F_mm` 198 ✓, `pixel_cv_center` 42 ✓,
**`Y_up_m` 118 ✗**, **`none` 111 ✗**.
**Schemas on assets (17 distinct):** 14 declared, **3 not declared**: `synlab.display_glb.v1` (118),
`synlab.labels.v1` (107), `synlab.provenance.v1` (107).

Where the undeclared values are written:

| undeclared value | written at | roles |
|---|---|---|
| unit `"m"`, frame `"Y_up_m"`, schema `synlab.display_glb.v1` | display-LOD export path | `display_lod_glb` (118 assets, present in `data/a12_demo/store` — note **0 in the MAIN store**) |
| unit `"unknown"` | `synlab/observe/api.py:215` `unit="mm" if obs.scale_valid else "unknown"` | `obs_result` (12 assets) |
| frame `"none"` | `synlab/pipeline.py:1361` (provenance), `synlab/doctor.py:522,525` (qa_report), `synlab/api/handlers.py:143,403,482` (run_spec/operator_audit) | `provenance` 107, `qa_report` 4 |
| schema `synlab.provenance.v1` | `synlab/pipeline.py:1361` | `provenance` 107 |
| schema `synlab.labels.v1` | labels/training export path | `label_bundle` 107 |
| schema `synlab.run_spec.v1` | `synlab/api/handlers.py:143` | `run_spec` (0 assets in MAIN; role declared `ROLE_RUN_SPEC` `roles.py:61` but **no `SCHEMA_RUN_SPEC` exists**) |

**Schema ids declared in `roles.py` with ZERO assets in the MAIN store (6 of 20):**
`synlab.camera_profile.v1` (`:17`), `synlab.checkpoint.v1` (`:22`), `synlab.coverage.v1` (`:25`),
`synlab.cutter.v1` (`:9`), `synlab.episode.v1` (`:21`), `synlab.report.v1` (`:23`).

**Roles declared in `roles.py` with ZERO assets in the MAIN store (12 of 32):** `coverage` (`:60`),
`cutter_mesh` (`:34`), `diagnostic_report` (`:57`), `display_lod_glb` (`:62`),
`episode_trace` (`:54`), `mother_meta` (`:29`), `mvs_result` (`:63`), `operator_audit` (`:58`),
`pattern_audit` (`:33`), `run_spec` (`:61`), `train_checkpoint` (`:55`), `train_metrics` (`:56`).
Across **all** stores, 11 of these still have zero assets anywhere — every one except `display_lod_glb`.

**Roles present on assets but absent from `roles.py` (2): `degrade_source` (6 assets),
`degrade_variant` (69 assets).** These are declared in a **different module**:
`synlab/degrade/diversity.py:68` `ROLE_DEGRADE_SOURCE = "degrade_source"`,
`:75` `ROLE_DEGRADE_VARIANT = "degrade_variant"` — so the role vocabulary is split across two files and
`roles.py` is not the single source of truth it claims to be (`roles.py:1` docstring: *"Asset role and
schema identifiers shared across modules (prevents semantic drift)"*). Found only in
`data/a12_degrade/{_probe_store,store}`.

**Wider schema-literal sprawl (`probe17_schema_literals.py`).** Counting quoted
`"<synlab|a12>.<dotted>.v<N>"` string literals in every `.py` and `.json` file under the repo
(excluding `.git`, `.venv`, `node_modules`, `__pycache__`, `.pytest_cache`): **3437 occurrences,
112 distinct literals, of which 92 are not declared in `roles.py`** (which declares 20). This counts
report/manifest schema ids in JSON artifacts as well as code, so it is not the asset contract — but it
shows `roles.py` covers only a small minority of the schema-id vocabulary actually in use. The
**asset-relevant** subset is the 3 undeclared schemas listed above.

*(A delegated companion probe left a broader code-literal inventory in
`data/a12/reports/modality_census/partB_contract.txt`; its headline scope differs from the count above,
so only the independently reproduced numbers are quoted here.)*

---

## C) PROVENANCE / TRUTH-LAYER SEPARATION

### C1. `provenance` role — exact keys, fingerprints, git state

`probe11_condensed.txt` (C1a), `data/a12/metadata.sqlite`, **45 provenance assets**:
schema `synlab.provenance.v1` 45/45, unit `1` 45/45, frame `none` 45/45, `qa_status` **`QA_PASS` 45/45**,
`split` = `train` 35 / `dev` 6 / `confirm` 4.

**Exact `meta` keys and carriers:** `backend_fingerprints` 45, `code_fingerprint` 45, `params` 45,
`run_id` 45, `seed_ref` 45, `spec_hash` 45, `data_semantics` 7.

**`code_fingerprint` fields** (written `synlab/canonical.py:111-132`, consumed `synlab/pipeline.py:80-91`):
`git`, `commit`, `dirty`, `diff_hash`, `source_tree_hash`, `untracked[]`.

Real values across all 45 rows — **11 distinct `(git, commit, dirty, source_tree_hash)` combinations**:

| git | dirty | diff_hash (all rows) | commits observed |
|---|---|---|---|
| `true` | **`false` (45/45)** | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (45/45) | `e392c12e311367c6aded5ec1c17d9015241d096d` (19 rows), `5ff765032193272f4c6f06162a0398fd662714cf` (12), `4f51a00edc2241be2669cf7b081eba322ac56f35` (4), `c311269a782b855fdc896874ab334ccee9249ace` (4), `807b71db1f35d7e340d3011e357c840c3992653c` (3), `c3a149f6aee73245db7c3540e55c0292da2d1a66` (3) — **6 distinct commits, summing to 45** |

`diff_hash` is **the SHA-256 of the empty string**, consistent with `dirty=false` on every row.
`untracked[]` length distribution: `0`:6, `3`:4, `4`:4, `27`:5, `55`:2, `61`:4, `69`:2, `94`:6,
`157`:4, `166`:8 — so 39/45 rows were written with a non-empty untracked set even though `dirty=false`
(the dirty flag tracks tracked-file modifications only).
**Current repo HEAD at census time: `c3a149f6aee73245db7c3540e55c0292da2d1a66` (2026-10-02 12:06:54 +0800),
working tree with 15+ modified tracked files** (`git status --porcelain`: `synlab/pipeline.py`,
`synlab/storage/export.py`, `synlab/relations/{negatives,multi_event}.py`, `synlab/physical/api.py`,
`synlab/fracture/*.py`, `synlab/degrade/__init__.py`, `synlab/training/adapter.py`,
`frontend/src/...`). So the newest assets were fingerprinted at a commit earlier than the live tree,
and the live tree is dirty — the fingerprints are per-asset historical facts, not a statement about
the current checkout.

**`backend_fingerprints`** — **8 packages, identical versions in 45/45 rows**:

| package | version | rows |
|---|---|---|
| `cv2` | `5.0.0` | 45 |
| `gmsh` | `4.15.2` | 45 |
| `manifold3d` | `3.5.4` | 45 |
| `open3d` | `0.19.0` | 45 |
| `pycolmap` | `3.11.1` | 45 |
| `scipy` | `1.18.1` | 45 |
| `torch` | `2.5.1+cpu` | 45 |
| `trimesh` | `5.1.0` | 45 |

**Other real provenance values:** `run_id` 12 distinct (e.g. `run_e031b5651fb7f7ff`:6);
`seed_ref` 37 distinct, format `[20261001,"<lineage_id>"]`; `spec_hash` 2 distinct —
`sha256:aa231f9c…` (33 rows) and `sha256:f67be1d2…` (12). `params` carries 85 distinct vessel-geometry
keys (`diameter_mm`:37, `base_mm`:39, `wall_mm`:39, `warp_amplitude`:42, …). `data_semantics` (7 rows) =
`{"damage_semantics":"subset_v2","defined_in":"docs/a12/data_semantics_versions.md","mask_semantics":"coc_units_v2","subset_instrument":"trimesh.proximity.signed_distance (exact, float64)"}`.

### C2. Truth layers — fields, semantics, and real QA counts

Writer: `synlab/truth/api.py`. Three layers, one serde each.

| layer | role | schema | rows (MAIN) | unit / frame | QA (MAIN) |
|---|---|---|---|---|---|
| clean | `clean_truth` | `synlab.truth.clean.v1` | 55 | `mm` / `W_mm` | **`QA_PASS` 55** |
| physical | `physical_truth` | `synlab.truth.physical.v1` | 43 | `mm` / `W_mm` | **`QA_PASS` 43** |
| visible | `visible_labels` | `synlab.truth.visible.v1` | 41 | `mm` / `W_mm` | **`QA_FAIL` 23, `QA_PASS` 18** |

Store-wide QA totals for `data/a12/metadata.sqlite` (894 assets):
**`QA_PASS` 594, `QA_PENDING` 261, `QA_FAIL` 39.**
The 39 failures: `visible_labels` 23 + `physical_result` 14 + `pattern_channels` 1 + `pattern_recipe` 1.
`QA_FAIL` rows are committed, not dropped — the failure is recorded in `qa_status`.

**Real field lists (artifact top-level `meta` keys, all n = row count).**
`clean_truth` (22 keys): `backend`, `correspondence_truncated`, `cutter_ref`, `event_id`, `event_tree`,
`fracture_qa`, `fragment_ids`, `history`, `interface_count`, `layer`, `mother_area_mm2`, `mother_id`,
`patch_evidence`, `r2_area_threshold_mm2`, `r2_count`, `relation_count`, `relations`, `relations_json`,
`truth_hash`, `truth_incomplete`, `version` (all 55), `run_id` (37).
`physical_truth` (21 keys): `association_counts`, `clean_truth_ref`, `current_fit_valid`, `damage`,
`event_id`, `fragment_id`, `fragment_ids`, `history`, `layer`, `mate_present`, `mother_id`, `r2_count`,
`relation_count`, `relations`, `relations_json`, `residual`, `survivor_patches`, `truth_hash`,
`truth_incomplete`, `version` (all 43), `run_id` (28).
`visible_labels` (18 keys): `association_counts`, `event_id`, `fragment_id`, `fragment_ids`, `history`,
`layer`, `mother_id`, `observation_id`, `per_view`, `physical_truth_ref`, `r2_count`, `relation_count`,
`relations`, `relations_json`, `truth_hash`, `truth_incomplete`, `version` (all 41), `run_id` (26).

Runtime dataclasses: `CleanTruth` (`synlab/schemas/runtime.py:295-304`: `mother_id`, `event_id`,
`version`, `relations`, `interfaces`, `correspondence`, `event_tree`, `qa`, `meta`),
`PhysicalTruth` (`:318-326`: `clean_truth_ref`, `version`, `residual`, `survivor_patches`,
`association_counts`, `current_fit_valid`, `qa`, `meta`),
`VisibleLabels` (`:330-335`: `physical_truth_ref`, `version`, `per_view`, `qa`, `meta`).

**What `truth_incomplete` means — read from the writers:**

| layer | writer | semantics | real values (MAIN) |
|---|---|---|---|
| `clean_truth` | `synlab/truth/api.py:438` `"truth_incomplete": False` | **hardcoded False** — the clean layer is never incomplete | `False` 55/55 |
| `physical_truth` | `synlab/truth/api.py:837` `"truth_incomplete": not bool(components)` | **True iff there are NO physical components** | `False` 43/43 |
| `visible_labels` | `synlab/truth/api.py:1059` `"truth_incomplete": bool(views) and int(np.sum(visible_valid)) == 0` | **True iff there are views but ZERO valid visible pixels** | **`True` 23, `False` 18** |

The `visible_labels` split is **exactly** the QA split (`QA_FAIL` 23 / `QA_PASS` 18) — the one place in
the store where a real data-quality failure is recorded rather than asserted away.

**What `history.historical_R2` means:** the **preserved historical R2 (mated-pair) fragment set**, so a
later physical/visible layer can be checked against the clean layer's original mating answer.
Written as `history = {"association_kind": ..., "historical_R2": _r2_fragments(...)}`
(`synlab/truth/api.py:1055-1056`, `:1357-1358`, `:1381-1382`). `history` always has exactly **3 keys**
(55/55, 43/43, 41/41). `historical_R2` values are **lists of fragment-id lists**: `[]` for 4 rows, and
otherwise either a pair `["…E01-m","…E01-p"]` or a full cluster of 4-6 ids, e.g.
`["LIN0000_V10_M11_PAT15_E01-m","LIN0000_V10_M11_PAT15_E01-m__-1c1","LIN0000_V10_M11_PAT15_E01-m__-1c2","LIN0000_V10_M11_PAT15_E01-p","LIN0000_V10_M11_PAT15_E01-p__+1c1","LIN0000_V10_M11_PAT15_E01-p__+1c2"]`.
`history.association_kind` = **`"EXACT_SURVIVOR"` in 55/55, 43/43 and 41/41 truth rows**
(hardcoded at `:1055`, `:1357`, `:1381`).
By contrast `label_bundle` (the deployment-side bundle) has
`history.association_kind = "UNKNOWN_MAPPING"` in **45/45** rows and `historical_R2 = []` in **45/45** —
correct, because the deployment side must not carry ground truth. `ASSOCIATION_KINDS` is defined at
`synlab/truth/api.py:90`: `("EXACT_SURVIVOR", "VERIFIED_RECESSION", "UNKNOWN_MAPPING")`.

**What `association_counts` means:** per-asset counts of how each clean fragment was associated into
the physical layer, keyed by those three `ASSOCIATION_KINDS`. Written at `truth/api.py:772`
(`counts = {name: 0 for name in ASSOCIATION_KINDS}`), `:805`, `:843`. Real values
(`physical_truth`, 43 rows; `visible_labels`, 41 rows):

| key | real values |
|---|---|
| `EXACT_SURVIVOR` | varies per asset: `259`…`2955` (e.g. `895`, `2880`, `1583`×3) — the counts are large because they count inter-fragment association events, not fragments |
| `UNKNOWN_MAPPING` | **`0` in 38/43** (`physical_truth`) and **`0` in 36/41** (`visible_labels`); non-zero only `311`, `406`, `416`, `442` (and one `1`) |
| `VERIFIED_RECESSION` | **`0` in 43/43 and 41/41** — the recession branch is never exercised in this data |

### C3. `loss_mask` semantics, writers/readers, and real counts

`loss_mask` is a **field of the relation edge** (`synlab/schemas/runtime.py:263-271`:
`RelationEdge(fragment_a, fragment_b, kind, interface_id, area_mm2, valid=True, reason="", loss_mask=True)`)
— type **`bool`**, default `True`.

**Who sets it (writer sites, all in the pair-verdict function):**

| citation | setting |
|---|---|
| `synlab/truth/api.py:510` | `RELATION_R1, False, False, "empty_patch"` — invalid |
| `synlab/truth/api.py:514` | `RELATION_R1, False, False` — `"not_a_new_fracture_surface (assembly / outer-surface contact)"` |
| `synlab/truth/api.py:518` | `RELATION_UNKNOWN, False, False, "no_unique_source"` |
| `synlab/truth/api.py:521` | `RELATION_UNKNOWN, False, False`, `"ambiguous_area_ratio>…"` |
| `synlab/truth/api.py:525` | `RELATION_UNKNOWN, False, False`, `"cavity_adjacency_or_outside_material"` |
| `synlab/truth/api.py:530` | `RELATION_UNKNOWN, False, False`, `"shared_surface_geometry_out_of_budget"` |
| `synlab/truth/api.py:535` | `RELATION_TINY, True, True, "structurally_valid_cut_face"` — valid **and** masked |
| `synlab/truth/api.py:588` | `RELATION_R2, True, True` — the confirmed mated pair |
| `synlab/truth/api.py:591`, `:595` | `RELATION_TINY, True, False` — **valid but NOT masked** |
| `synlab/truth/api.py:575`, `:581`, `:612`, `:617` | `valid=False, loss_mask=False` |
| `synlab/relations/negatives.py:116` | `"loss_mask": bool(row.get("loss_mask", False))` — **default False** (opposite of the dataclass default) |
| `synlab/relations/gallery.py:128` | `valid: bool = True, loss_mask: bool = True` — both default True |

**Stated semantics.** `loss_mask` is a **supervision mask on a relation statement**, not a spatial
image mask: it marks whether *this relation row may contribute to the loss*. The governing invariant is
written at `synlab/truth/api.py:13`: *"``UNKNOWN`` always carries ``loss_mask=False`` and is never
rewritten into ``R0``"*, checked at `:1150-1151` (`"UNKNOWN with loss_mask=True"` is a problem) and
reported as `unknown_loss_mask_false` (`:1174`). And `synlab/relations/negatives.py:558`:
*"a row is a positive, an ``R1``/``R0`` row that is ``valid`` *and* ``loss_mask``-ed is a legal [negative]"*.
`loss_mask` and `valid` are deliberately **separate**: `TINY_CONTACT` is `valid=True, loss_mask=False`
(`truth/api.py:591`), i.e. structurally real but too small to supervise on.

`eligible_as_negative = kind in {R1,R0} and valid and loss_mask` — `synlab/storage/export.py:581-583`
(also documented at `synlab/qc/data_quality.py:662`).

**Real value counts (`probe08_relations.py`).**

`research/relations.parquet` (150 rows): `loss_mask` `False`:117 / `True`:33 — **exactly identical to
`valid`** (`False`:117 / `True`:33), and `kind` `R1`:117 / `R2`:33. **In this artifact
`loss_mask == valid == (kind == "R2")`**, because all 117 `R1` rows are the `"empty_patch"` case
(`truth/api.py:510`, `valid=False, loss_mask=False`) and no `TINY_CONTACT` row is exported. The
`valid=True, loss_mask=False` distinction is therefore **present in the code and in the schema but not
observable in this export**.

`research/labels/*.parquet` real value counts:

| file | rows × cols | `loss_mask` | `valid` | `kind` | `split` |
|---|---|---|---|---|---|
| `labels/clean.parquet` | 258 × 15 | `False`:124, `None`:97, `True`:37 | `False`:124, `None`:97, `True`:37 | `R1`:124, `None`:97, `R2`:37 | `train`:141, `confirm`:105, `dev`:12 |
| `labels/physical.parquet` | 189 × 15 | `False`:95, `None`:68, `True`:26 | `False`:95, `None`:68, `True`:26 | `R1`:95, `None`:68, `R2`:26 | `train`:99, `confirm`:81, `dev`:9 |
| `labels/visible.parquet` | 64 × **8** | **column absent** | **column absent** | **column absent** | `train`:45, `confirm`:14, `dev`:5 |

`labels/visible.parquet` has only `['label_layer','asset_id','lineage','split','passed','fragment_id','role','detail']`
— no `loss_mask`/`valid`/`kind` at all. Its `detail` is `{"passed": false, "relations": 0}` on the first
row. In both other files `loss_mask` is again **identical to `valid`** and mirrors `kind` (`R1`→False,
`R2`→True, non-relation rows→`None`).

### C4. `FORBIDDEN_FEATURE_FIELDS` / leakage

`synlab/roles.py:87-93` defines `FORBIDDEN_FEATURE_FIELDS = frozenset({...})` with **27 names**:
`parent_id`, `object_id`, `bag_id`, `seed`, `seed_ref`, `generator_family_id`, `interface_id`,
`relation`, `historical_R2`, `mate_present`, `truth_pose`, `T_WF`, `clean_hidden_surface`,
`gt_thickness`, `gt_normal`, `gt_curvature`, `damage_strength`, `spurious_mask`, `hard_case_tag`,
`lineage_id`, `mother_id`, `fragment_id`, `event_id`, `split`, `variant`, `axis_id`, `level`.
Rationale in the neighbouring comment (`roles.py:45-48`): a degraded bundle *"is the answer side of a
factor experiment: its metadata carries `axis_id`/`level`/`variant` by design, and
`FORBIDDEN_FEATURE_FIELDS` lists exactly those keys, so it may never be committed under
`ROLE_FEATURE_BUNDLE`"*.

`synlab/observe/features.py:56-62` adds `EXTRA_FORBIDDEN` (27 more: `spurious`,
`spurious_vertex_mask`, `gt_roi`, `oracle_roi`, `clean_area`, `clean_volume`, `truth_scale`,
`scale_truth`, `hard_case`, `answer`, `relation_kind`, `r2_pair`, `candidate_id`, `object_id`,
`bag_id`, `generator_family`, `assembly_pose`, `object_pose_T_WO`, `T_WS`, `T_WC`, `T_CW`, `T_WF`,
`T_WO`, `fragment_index`, `view_index`, `profile_id`, `mother_ref`), and
`FORBIDDEN_UNION = FORBIDDEN_FEATURE_FIELDS | EXTRA_FORBIDDEN` (`:64`).

**`assert_no_leakage` implementation** (`synlab/observe/features.py:67-104`): recursive walk bounded at
`depth > 12` (`:77`) over dicts (`:79`), lists/tuples (`:91`) and dataclass fields (`:94`). It rejects a
name that **equals** a forbidden name (`:83`) *or* **contains** one as a substring (`:86-88`), so
`"gt_normal_p95"` is caught. Violations raise `SynLabError(ErrorCode.LEAKAGE_DETECTED, …)` with
`stage="observe.features.assert_no_leakage"` and the first 8 offending paths (`:99-104`). It is called
at `synlab/observe/features.py:213` and `:273`. Independent leakage gates also exist at
`synlab/qc/leakage.py:83`, `synlab/qc/audit.py:82,86`, `synlab/qc/acceptance.py:110-125`,
`synlab/diagnostics/runner.py:203`, `synlab/training/adapter.py:77`.

**Real `dropped_forbidden_fields` counts** (`probe11_condensed.txt` C4a, `data/a12/metadata.sqlite`,
role `feature_bundle`, writer `synlab/pipeline.py:1252` (`dropped = sorted(set(meta) & FORBIDDEN_FEATURE_FIELDS)`)
+ `:1258` (`meta["dropped_forbidden_fields"] = dropped`)):

- `feature_bundle` assets: **45**
- carrying `dropped_forbidden_fields`: **41 / 45**
- of those, empty list: **0 / 41**
- **4/45 carry no `dropped_forbidden_fields` key at all**

What was dropped (name → #assets): **`fragment_id` 41, `mother_id` 41, `component_id` 8,
`observation_id` 8** (4 distinct names total).

**Honest caveat:** `component_id` and `observation_id` are **not members of
`FORBIDDEN_FEATURE_FIELDS`** (verified against `roles.py:87-93`). Since `pipeline.py:1252` computes
`dropped = sorted(set(meta) & FORBIDDEN_FEATURE_FIELDS)`, those two names cannot have been produced by
that intersection — an additional drop site exists for them. Across all stores `feature_bundle` appears
with unit `mm` (157) and unit `1` (29), i.e. this role's contract is not uniform store-to-store.

---

## Summary of the honest answers

| question | answer |
|---|---|
| site / trench / layer(层位) / stratigraphic unit | **无** |
| co-existing objects (共存物) | **无** (closest: gallery/roster candidate lists, A5) |
| batch / lot grouping (同批次) | **无**; `bag_id` exists only as a forbidden field name, 0 assets |
| findspot | **无** |
| scale reference object (比例尺) | **无**; closest is `scale_valid` (a bool) and `display_transform.{authority_unit,display_unit}` (`mm`→`m`) |
| soil / earth (土层) | **无** |
| plot / parcel (地块) | **无** |
| `layer` | truth layer `clean`/`physical`/`visible` — **not** stratigraphy (`truth/api.py:85-87`) |
| `context` | sensor/acquisition dict, 4 keys: `route`, `input_profile`, `n_views`, `scale_valid` (`degrade/api.py:629-632`) |
| X03 `missing_context`/`conflicting_context` | nulls or cross-assigns those 4 sensor keys; `source_provenance="OBS_CONTEXT"` |
| `payload.scene.*` | renderer scene; `light` is a reference **string**; `occluders` is the scalar `0`; real occluder bodies are anonymous icospheres, identities never persisted |
| EpisodePack in an environment with other objects | **无 real artifact**; 0 `episode_trace` assets in all stores; code-only contract |
| truth layers | `clean` / `physical` / `visible`, QA_PASS 55/43/18 + QA_FAIL 0/0/23 |
| `loss_mask` | bool on `RelationEdge`; supervision mask; `UNKNOWN`⇒False invariant; in the export `== valid == (kind=="R2")` |
| `dropped_forbidden_fields` | 41/45 `feature_bundle` assets, 4 distinct names |

## Probe artifacts (all under `data/a12/reports/modality_census/`)

| script | raw output | what it establishes |
|---|---|---|
| `probe01_inventory.py` | `probe01_inventory.txt/.json` | store inventory, roles per store, `assets` columns |
| `probe02_keywords.py` | `probe02_keywords.txt/.json` | nested key-path keyword census (23 stores, 7478 paths, 787 matches) |
| `probe03_x03_context.py` | `probe03_x03_context.txt/.json` | axis_id/variant distribution; shows why a nested-dict search fails |
| `probe04_raw_meta.py` | `probe04_raw_meta.txt` | raw `meta_json` structure; flat dotted keys; `meta` wrapper rule |
| `probe05_flatkeys.py` | `probe05_flatkeys.txt/.json` | exact `payload.context.*`/`payload.scene.*` values; all 8 X03 assets |
| `probe06_episode_search.py` | stdout | 0 `episode_trace` assets anywhere |
| `probe07_registry.py` | stdout | `docs/a12/registry.json` = 92 entries, no episode/env |
| `probe08_relations.py` | `probe08_relations.txt` | relation_pool/roster meta; relations.parquet; labels parquet `loss_mask`/`valid`/`kind` |
| `probe09_prov_truth.py` | `probe09_prov_truth.txt` | provenance full dump; truth-layer keys; grouping-key search |
| `probe10_23stores.py` | `probe10_23stores.txt` | 23rd store detail; top-level keyword census |
| `probe11_condensed.py` | `probe11_condensed.txt` | QA per role; 11 fingerprint combos; backend versions; truth semantics; dropped fields |
| `probe12_role_table.py` | `probe12_role_table.txt` | the per-role contract table + schema cross-check |
| `probe13_vocab.py` | `probe13_vocab.txt` | unit/frame/schema vocabulary vs `roles.py` |
| `probe14_roles.py` | stdout | undeclared roles; declared-but-empty roles |
| `probe15_obsview_scene.py` | `probe15_obsview_scene.txt` | exact MAIN-store `obs_view` scene census |
| `probe16_id_types.py` | `probe16_id_types.txt` | real JSON types of `component_id`/`observation_id` per role (resolves the int/str question) |

## Caveats and limits of this census

1. **No artifact inspection beyond metadata was performed** for the geometry/imagery payloads; all
   claims are about `meta_json`, the `assets` columns and the parquet exports named above.
2. **The store population grew during the census** (22 → 23 → 25 stores) because sibling processes
   created `data/a12_smoke/_tmp/v23store` (12:52:07) and `data/a12_degrade/{_probe_store,store}`
   (12:55:15/12:55:37). Keyword conclusions were re-verified invariant across 22/23/25 stores; the
   all-store vocabulary and undeclared-role findings depend on the 25-store snapshot.
3. **Line numbers were re-verified against the live tree at report time, but the tree is being edited
   by other processes concurrently, so citations drift.** Observed during this census:
   `synlab/pipeline.py` was rewritten mid-session (`LastWriteTime` 12:54:49 → 12:59:59, size
   74985 → 75153 bytes), moving `dropped_forbidden_fields` from line 1146 → 1255 → 1258 and the
   provenance commit from 1358 → 1361; an earlier grep had already returned stale numbering
   (`dropped_forbidden_fields` at 1146). A `synlab/pipeline.py.damaged.bak` file appeared during the
   session. The tracked-file change count rose from **15 to 61** while this census ran, driven by other
   agents (including this census's own delegated probe) — none of it by the read-only probes reported
   here. Citations in this report are therefore given **with their anchor code text**; every one was
   green at the time of writing, but re-grep the anchor text rather than trusting the number.
   **All numbers in this report come from artifacts (`metadata.sqlite`, parquet), which are immune to
   this drift.**
4. `probe03`'s "0 context dicts" result is a **negative control**: it demonstrates that searching for a
   nested `context` dict finds nothing, because the keys are flat. It is not evidence of absence — the
   substring census in `probe02`/`probe05` is.
5. `association_counts.EXACT_SURVIVOR` values (259…2955) are reported as observed; this census did not
   verify the counting unit, only the field's presence, range and per-asset variability.
6. The episode contract in A3 is **read from code only**; it has never been executed into this
   workspace, so its numeric ranges beyond `DEFAULT_BUDGET` are unobserved.
