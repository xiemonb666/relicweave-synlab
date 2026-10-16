# Source-conditioned reference materials (2026-10-15)

This first material slice binds the existing A12 material field engine to four named ceramic
objects. It does not replace M01–M12, and it does not claim that a photograph or catalogue label
measures a physical material property. Each numeric color, roughness, IOR, pore/grain scale, or
appearance-band depth in a generated recipe is tagged `DESIGN_CHOICE`; source-observed quantities
stay separate from it.

The adapter is [reference_materials.py](../../synlab/materials/reference_materials.py). Call
`list_reference_materials()` to inspect the style IDs and `reference_material(style_id, controls,
seed)` to build a profile. The result remains compatible with the existing
`synlab.materials.api.material_at(profile, points_mm, surface_tag)` query. For these source-bound
profiles, the versioned `coating_surface_policy` uses original semantic face tags: `outer_wall`,
`inner_wall`, and `rim` select the finish, while `foot`, `base`, `new_fracture`, `interface`, and
`attachment` select bare body where those tags are listed by the profile. Original-face query
depth is always zero, so rounded vessel coordinates do not inherit false glaze depth from distance
to an ideal cylinder. A separate `volume` query is supported only when the caller supplies explicit
`depth_mm`. The helper `sample_reference_material` adds transmission and the selected layer name
to the same coordinate query.

## Sources and model boundaries

| Style ID | Primary object evidence | Material field base | Source facts used | Values kept unknown |
|---|---|---|---|---|
| `daily_aberdeen_porcelain_celadon` | [Aberdeen ABDMS095708.121](https://emuseum.aberdeencity.gov.uk/objects/186848/porcelain-small-footed-bowl) | M04 porcelain | Limoges porcelain and celadon; maker Chris Keenan; 2007–2009; H 53 mm, D 108 mm, foot-ring D 31 mm. The primary photographs support only a qualitative note: pale blue-green interior/exterior, dark rust upper band, pale foot. | Complete section, local thicknesses, making/firing schedule, glaze chemistry and thickness, calibrated color/BRDF, lot-specific mechanics. The profile's pale celadon RGB is a design choice, not an extraction from the image. |
| `historical_met_jun_stoneware_glaze` | [The Met 18.56.44](https://www.metmuseum.org/art/collection/search/52389) | M03 stoneware | Stoneware with blue-gray glaze (Jun ware); H 54 mm, rim D 111 mm, foot D 54 mm. | Complete section, local thicknesses, forming/firing schedule, glaze chemistry and thickness, calibrated color/BRDF, lot-specific mechanics. |
| `historical_met_50899_porcelain_clear_underglaze` | [The Met 29.149.50 / object 50899](https://www.metmuseum.org/art/collection/search/50899) | M04 porcelain | Vase with dragon; China, late 18th century, Qianlong period, Qing dynasty; porcelain painted in underglaze cobalt blue (Jingdezhen ware); H 184 mm; object image Public Domain. The retained O2 photograph qualitatively shows a pale warm-white body and bright surface reflections; this is not colorimetry. | Diameter/maximum width and full section, distinct clear-glaze presence and properties, firing schedule, calibrated color/BRDF, lot-specific mechanics. The profile invents no radius and does not rescale a vessel mesh. |
| `historical_smithsonian_colonoware_unglazed` | [Smithsonian 3D object page](https://3d.si.edu/object/3d/colonoware-pot-cooper-river-charleston-county-sc%3A79da3e3f-3ad7-41de-8956-e891d88a3c5f) and [NMAAHC object record](https://nmaahc.si.edu/object/nmaahc_2017.108.1.1) | M02 fine-earthenware field as a **design proxy** | Ceramic pottery with medium listed as clay, glue, plaster of Paris, and paint; the source calls the vessel unglazed; about 1700–1800; H 230 mm, D 267 mm; rounded body/base, narrow neck, slightly flared rim. Its record also describes stippling and circular marks, cross-mended breaks, and a plaster repair. The adapter's broad `earthenware` material class is a design classification. | Clay recipe, temper/grain distribution, forming/firing schedule, porosity/moisture, calibrated color/BRDF, mesh scale/wall completeness, lot-specific mechanics. M02's field defaults are not claims about grog or the Smithsonian vessel's fabric. |

The Aberdeen source records a celadon finish but not its layer geometry. The adapter uses the M04
porcelain body and an appearance-only celadon layer on semantic outer-wall, inner-wall, and rim
faces. The source photographs also show a dark rust upper band and pale foot; the current single
celadon finish does not claim to reproduce that regional decoration or infer numeric color from
the photographs. The Met Jun profile also uses an appearance-only glaze layer. For both profiles,
`coating_band_mm` is a design selector only for explicitly requested volume samples; it is not used
on original vessel faces and is not a physical glaze thickness. The profile records
`mode="SHADING_LAYER"`, `physical_solid_status="NOT_CREATED"`, and
`physical_thickness_status="UNKNOWN"`. A physical glaze body requires a separately built
`GEOMETRIC_LAYER`; these reference profiles do not create one. The Smithsonian profile has no
coating layer because its source record says unglazed.

The Met 50899 profile also uses M04 porcelain, with pale warm-white body controls and a clear/pale
appearance-only surface layer chosen as explicit rendering proxies. The retained O2 image supports
only a qualitative visual note; numeric albedo, roughness, IOR, transmission, and the volume-query
band remain `DESIGN_CHOICE`. The object record names underglaze cobalt but does not specify a
separate clear-glaze layer, glaze composition, thickness, or firing schedule. Its cobalt
decoration is recorded as a source-named process with substrate-class compatibility and is kept
separate from the substrate profile so a blue motif can be composed independently. Only the
documented 184 mm height is retained; no diameter or radial envelope is fabricated, and semantic
surface sampling does not transform or rescale geometry.

The catalogue's version-1 field hash used signed 64-bit intermediate shifts, which capped all
lattice values below 0.5. That made the existing 0.62 pore threshold unreachable. New reference
profiles explicitly record field-kernel version 2, which uses logical unsigned SplitMix64 shifts;
the threshold is unchanged. Existing M01–M12 profiles without an explicit version continue to use
the legacy kernel for reproducible assets. Generated reference samples are recomputed with v2;
older assets are not rewritten.

## Material mechanics remain unknown

The material profiles retain `mechanics.status = "UNKNOWN"`; density, elastic constants,
strength, fracture toughness, and fracture energy are not populated. The values found in primary
ceramic studies belong to their own specimen and process conditions. They are not measurements of
these named museum objects or of a ShardForge material lot.

The primary study by Müller, Vekinis, Day, and Kilikoglou, [“The influence of microstructure and
texture on the mechanical properties of rock tempered archaeological ceramics”](https://doi.org/10.1016/j.jeurceramsoc.2014.09.025), tests experimental clay briquettes and shows that firing and temper alter the measured material response. Its untempered Kalami clay condition at 1050 °C reports only a partial set: static bending modulus, flexural strength, and effective finite-notch mode-I toughness. It does not provide a fired bulk density, Poisson ratio, direct tensile strength, or an independent direct `Gc` for that condition. The values cannot be attached to these objects.

The primary porcelain-stoneware study by Martín-Márquez, Rincón, and Romero,
[“Effect of microstructure on mechanical properties of porcelain stoneware”](https://doi.org/10.1016/j.jeurceramsoc.2010.07.015), studies a fast-fired industrial tile recipe (50 wt% kaolinitic clay, 40 wt% feldspar, 10 wt% quartz). It reports dynamic modulus and indentation-derived toughness, with other results incomplete or method-specific. It does not provide a complete, lot-matched brittle-fracture card for an Aberdeen bowl, Jun ware bowl, or Colonoware pot. Its property values are not inserted into these profiles.

The project-specific measurement requirements and source-by-source method limits are documented in
[the fired-ceramic calibration contract](reviews/20261007/ceramic_calibration_sources/CALIBRATION_CONTRACT.md)
and [its primary-source notes](reviews/20261007/ceramic_calibration_sources/SOURCES.md). Neither
the programme placeholders nor the partial paper results are promoted to a physical card.

## Compatibility and sampled behavior

`process_compatibility` separates the operation from its visible result. Firing a glaze onto a clay
body is compatible with porcelain, stoneware, and earthenware as a substrate-class statement; it
does not certify an object's actual firing schedule or glaze formula. The same clay-body glazing
process is marked incompatible with wood and metal; metal vitreous enamelling is a separate
process. `surface_paint` is appearance-only, while `engrave_body` is explicitly
geometry-changing. Compatibility for unknown process/material pairs remains `UNKNOWN`.
`underglaze_cobalt` is also recognized for ceramic substrate classes as a separately composed
appearance layer; its pigment formulation and object-specific firing behavior remain unknown.

Run `python experiments/continuation_20261015/reference_materials/run_reference_materials.py`
from the `relicweave-synlab` directory to regenerate
[`material_samples.json`](../../experiments/continuation_20261015/reference_materials/material_samples.json)
and [the queried-channel swatch sheet](../../experiments/continuation_20261015/reference_materials/material_samples_preview.svg).
The record samples source-dimension-bounded mother-coordinate landmarks on outer wall, inner wall,
rim, foot, and a fresh interface at the same lower-wall point, then compares the existing synthetic
wood and metal catalog profiles. Landmark coordinates are not registered to museum meshes; the
unknown full meridians remain explicit. It includes queried layer IDs, albedo, roughness,
transmission, IOR, layer depth, porosity, and grain. These values demonstrate control effects in
the current field; they are not optical measurements of the objects.
