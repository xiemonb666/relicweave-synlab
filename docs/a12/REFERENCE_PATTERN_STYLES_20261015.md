# Source-grounded pattern styles — 2026-10-15

This adapter maps a small number of documented objects/processes to the existing
`synlab.patterns` families. Every generated result is a normal, frozen
`PatternRecipe`, marked `SYNTHETIC_REFERENCE_GUIDED`. The settings below are explicit
design choices constrained by source evidence; they are not distributions learned from
the few reviewed objects, and they are not exact reconstructions.

## Buildable styles

| Style ID | Primary evidence | Existing family | Mapped surface and process | Status |
|---|---|---|---|---|
| `daily_hasami_tokusa` | [Maruhiro / HASAMI SABI TOGUSA rice bowl](https://www.hasamiyaki.jp/en/item/sabitokusa-chawan/) | PAT03 longitudinal stripe field | `outer_wall`; meridian-running painted strokes repeated around the periodic chart | Source description and product photograph reviewed; brush/underglaze appearance remains an approximation |
| `historical_met_jun_plain` | [The Met 18.56.44 bowl](https://www.metmuseum.org/art/collection/search/52389) | PAT01 plain field | `outer_wall`; unpatterned surface field for a catalogued blue-gray glazed stoneware bowl | Source description and product photograph reviewed; this module does not simulate the Jun glaze |

### `daily_hasami_tokusa`

The maker describes a 13 cm rice bowl made by Rizaemon Kiln in Hasami, with hand-painted
vertical tokusa stripes. The source connects tokusa to horsetail grass and its upward
growth, and associates the motif with success and prosperity. It also describes the body
as sandy and iron-heavy, with rusty underglaze. The adapter therefore uses PAT03 at
`tilt_deg=0`, one stripe group, and a source-guided sandy/rust palette proxy. PAT03's
integer azimuthal count keeps the repeat closed at the chart seam.

Default spacing is 10 mm in the reference chart metric and stroke width is 1 mm. Neither
number is reported by the maker or measured from the uncalibrated product image. They are
synthetic defaults within documented PAT03 ranges. Callers may adjust spacing (5–30 mm),
line width (0.5–3 mm), and the outer-wall edge margin (0–0.35); family, surface tag,
palette mapping and process cannot be changed through this adapter.

The pattern is restricted to a resolved, periodic `outer_wall` chart measured from the
target `MotherGeometry`. The source does not provide a complete meridian, exact stripe
count/spacing/width, brush profile, pigment composition, firing schedule, calibrated color,
glaze BRDF, glaze thickness or batch variation. The current PAT03 implementation makes
periodic stripe geometry; it does not model brush taper, stroke overlap, pigment spread,
glaze pooling or a process-calibrated visual distribution.

### `historical_met_jun_plain`

The Met catalogues bowl 18.56.44 as Jin dynasty (1115–1234), 12th–13th century stoneware
with blue-gray Jun glaze. The record gives H 54 mm, rim diameter 111 mm and foot diameter
54 mm. The adapter maps only a plain PAT01 field to the measured `outer_wall` chart. Its
blue-gray palette is an uncalibrated display proxy; the material profile remains responsible
for glaze behavior. This entry adds no painted or incised motif and makes no claim about a
single-bowl glaze recipe, chemistry, firing schedule, layer thickness, crazing, pooling,
opalescence or calibrated BRDF.

### Research-only candidate: `research_met_hacilar_chevron`

The Met record for vessel 64.286.3 (ca. 5600–5400 BCE) describes hand-made thin-walled
ceramic with red paint on cream slip, two red rim bands, vertical chevrons in groups of
three, and concentric circles around two side projections. The source says the geometric
scheme is characteristic of Hacilar while the vessel's find site is unidentified. The Met
marks its image Public Domain. The adapter intentionally does not emit a buildable recipe:
current generic patterns do not provide a source-aligned mapping for separate rim, outer
wall and side-projection charts on an arbitrary mother. PAT07 triangles are not chevrons,
PAT10 foliage is not a substitute motif, and another object's interior radial pattern cannot
be placed on this vessel's exterior wall.

The source does not establish the object's exact pigment recipe, painting sequence, the
chevron's precise proportions/count, a broader symbolic meaning, or the target mother's
rim/projection chart. Those gaps need a measured, source-aligned layout before a renderer is
enabled.

## API and contract

```python
from synlab.patterns.reference_styles import (
    build_reference_pattern,
    list_reference_styles,
    reference_style_record,
    sample_reference_style,
)

recipe = build_reference_pattern(mother, "daily_hasami_tokusa", seed=20261015)
```

`build_reference_pattern` accepts an existing `MotherGeometry`, a buildable style ID, an
integer master seed and only the style's documented numeric overrides. It resolves the
mother's named exterior tag and requires an actual periodic chart with a positive measured
period, area and profile span. It does not assume V01, a fixed reference circumference, or
an inner-wall mapping. If a research-only ID is requested, it raises a structured schema
error rather than substituting another motif/family. `sample_reference_style` returns the
standard `(PatternRecipe, PatternChannels)` pair using the existing pure evaluator.

Both buildable recipes disable auxiliary random layers. Seed streams use
`make_rng(seed, mother_id, style_id, "pattern")`; repeated seed + mother + style inputs
produce the same frozen recipe. The attached `reference_style` record preserves source,
process, placement, known/unknown fields, palette limitations, mother/chart identity and
the explicit no-learned-distribution statement. The standard content recipe hash covers
that record and palette; the resource hash is recomputed over the frozen coefficient
payload after adapter-specific palette binding.

`evaluate(..., surface_tag="interface")` retains the normal fracture-surface behavior:
fresh fracture surfaces expose body material and do not inherit this exterior pattern.
The style adapter is a surface appearance/pattern layer. It does not modify mother geometry
or create physical paint, slip or glaze solids.

## Sources and reuse

- Maruhiro, [Rice Bowl / SABI TOGUSA](https://www.hasamiyaki.jp/en/item/sabitokusa-chawan/). Product page and photograph reviewed for qualitative pattern/process notes; no image copied into the repository and no image-reuse license asserted.
- The Metropolitan Museum of Art, [Bowl 18.56.44](https://www.metmuseum.org/art/collection/search/52389). The page marks the image Public Domain / Met Open Access; no image copied into the repository.
- The Metropolitan Museum of Art, [Vessel 64.286.3](https://www.metmuseum.org/art/collection/search/325698). The page marks the image Public Domain / Met Open Access; no image copied into the repository.

The palette numbers are linear-sRGB design proxies chosen for the style adapter. They are
not photo samples, calibrated color, pigment measurements or learned parameters.
