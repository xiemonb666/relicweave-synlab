# Blue-and-white motif source: dragon vase

## Selected source

The source is The Metropolitan Museum of Art's **Vase with dragon**, accession 29.149.50, object 50899: [Met collection record](https://www.metmuseum.org/art/collection/search/50899). The record dates it to late 18th-century Qing China, identifies the medium as porcelain painted in underglaze cobalt blue (Jingdezhen ware), and gives its height as 18.4 cm. The Met marks the image Public Domain; its Open Access page says public-domain images may be used commercially and noncommercially without permission or fee. The selected photograph is the record's O2 view: [official image URL](https://images.metmuseum.org/CRDImages/as/original/29_149_50_O2_sf.jpg). It is retained unchanged at [met_50899_O2_original.jpg](../../relicweave-synlab/synlab/patterns/resources/bluewhite_20261015/source/met_50899_O2_original.jpg) (2667×4000; 995,155 bytes; SHA-256 `3228f553358887829ef0a3eff0036293f8df6e311bf1e5da0b48c3fe02f2f28b`).

## Motif and context record

The collection title names a dragon. In the O2 view, its large head faces toward the viewer's right; horn-like projections, an eye, muzzle, whisker-like lines, and an open-looking jaw with tooth-like marks are visible. A sinuous scaled body curls to the viewer's left. Cropped fragments at the image edges show that the composition continues around the curved shoulder/body. The whole-object photo also shows a separate neck register with blue scroll-like forms and a geometric meander-like band. The Met record does not name those secondary forms, so they are recorded only as visual observations.

The record supplies no object-specific explanation of the dragon's symbolic meaning and no specific historical service or ritual use. It identifies the object as a vase and classifies it as ceramics; more specific use or symbolism remains unknown here. No auspicious, imperial, cloud, or other symbolic meaning is assigned. See the structured [JSON record](BLUEWHITE_MOTIF_SOURCES_20261015.json) for the observed body-part relations, layout, and unknowns.

## Source-derived extraction under refinement

The lossless [projection crop](../../relicweave-synlab/synlab/patterns/resources/bluewhite_20261015/derived/met_50899_O2_dragon_projection_crop.png) is 2000×1160 and keeps the shoulder's curved front projection and side continuation. The [grayscale cobalt mask](../../relicweave-synlab/synlab/patterns/resources/bluewhite_20261015/derived/met_50899_O2_dragon_cobalt_fired_photo_mask.png) has matching dimensions; black means no detected cobalt chroma and white means stronger cobalt chroma. An optional [high-chroma support mask](../../relicweave-synlab/synlab/patterns/resources/bluewhite_20261015/derived/met_50899_O2_dragon_strong_cobalt_support_proxy.png) keeps only pixels where `B - max(R,G) >= 55`, giving the diffusion step a sharper seed. Both masks come from the same fired-photo projection and neither is historical brush truth. The [reproducible Pillow/NumPy script](../../experiments/continuation_20261015/bluewhite_motif/extract_met_50899_O2_dragon.py) crops source pixels `(300, 2000, 2300, 3160)` and maps `B - max(R,G)` linearly from 6 to 72 RGB units into grayscale mask density. It adds no blur, diffusion, inpainting, morphology, or redraw. The exact output hashes and run metrics are in [extraction_report.json](../../experiments/continuation_20261015/bluewhite_motif/extraction_report.json).

This is a chroma-selected **fired-photo projection**, not a recovered initial brush deposit. The source already contains glaze response, light, camera color, vessel curvature, and photographic softness/compression; the mask preserves those visible effects. It is suitable as a real dragon layout and cobalt-color seed for synthesis, but does not measure pre-firing pigment placement or physical diffusion. The original image is retained only for computational motif reference and extraction, not as a product-display substitute.

The crop and masks are intermediate reference assets. Root has not accepted them
as a finished ornament: side continuation is clipped, the photo projection is not
a calibrated surface unwrap, and no unseen parts have been restored. The user's
requirement that even good imported resources receive actual refinement applies
before final use. Current numerical-transfer refinement preserves the stationary
source detail instead of forcing all brush structure through the coarse transport
grid; this does not by itself finish the composition or establish historical
fidelity. Original and previous derivative hashes remain retained.
