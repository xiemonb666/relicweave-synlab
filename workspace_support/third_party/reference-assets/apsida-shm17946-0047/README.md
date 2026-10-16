# Apsida SHM 17946:0047 — source model package

This directory retains the publicly linked technical OBJ package for the real archaeological vessel **SHM 17946:0047, “Footed bowl.”** Source record: [Apsida item 49281](https://apsida.cut.ac.cy/items/show/49281). The object record attributes the collection to Medelhavsmuseet / Världskulturmuseerna Database and is hosted by the Digital Heritage Research Lab / Apsida.

## Attribution and license

The item page states **CC BY-SA 4.0**. Attribute as: “Medelhavsmuseet, SHM 17946:0047; via Apsida / Digital Heritage Research Lab,” with links to the [item record](https://apsida.cut.ac.cy/items/show/49281) and [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Share adaptations under the same license and preserve attribution. This applies to the supplied model data and scan-derived outputs in the companion audit directory.

The museum record describes a C.G. III vessel (850–700 BC), earthenware/clay/pottery, with reported height 11.9 cm, base diameter 7.0 cm, and rim diameter 16.0 cm. Its description identifies a slightly convex conical foot with a conical cavity underneath, a tapering stem, convex lower body, a ridge between the middle and upper body, a near-cylindrical upper body, a sharp rim, and two horizontal round handles. Those measurements and shape labels are museum/database facts; they are not scale values inferred from the OBJ.

## Download and retained files

Direct source package: [Footed_Bowl_SHM_17946_0047_Obj06.zip](https://apsida.cut.ac.cy/files/original/529/49281/Footed_Bowl_SHM_17946_0047_Obj06.zip), retrieved 2026-10-15.

| File | Bytes | SHA-256 | Notes |
|---|---:|---|---|
| `Footed_Bowl_SHM_17946_0047_Obj06.zip` | 21,934,200 | `7977FE145179160EBA1F560F09C75302FCBC9C501E2460B7817311B1860FE35B` | Source archive retained unchanged; contains OBJ, MTL, and a JPG texture/photo member. |
| `Footed_Bowl_SHM_17946_0047.obj` | 78,060,594 | `C03413172398AE5280FAE3D1759F505B38BC97A1561E510FCFB4B99D97C57232` | Extracted model geometry, unchanged. |
| `Footed_Bowl_SHM_17946_0047.mtl` | 236 | `2EF05540C8671BD8A2DB1474783DA63533A230A874D9C84C535C975C98D3214F` | Extracted material file, unchanged; it references the JPG texture in the ZIP. |
| `LICENSE-CC-BY-SA-4.0.html` | 51,645 | `47C0A954C88D793BDEFE92FB007AE3C038FB3807F1A27083433D01AA7542C0D8` | Official Creative Commons legal-code page saved as HTML from the linked license URL. |

The ZIP has exactly three members: `Footed_Bowl_SHM_17946_0047.jpg` (7,450,447 B), `.mtl` (236 B), and `.obj` (78,060,594 B), totaling 85,511,277 uncompressed bytes. The JPG was not extracted or used in the mesh audit. The OBJ `v` rows contain per-vertex RGB values, so geometry can be loaded without the external JPG; the MTL texture reference will be unresolved if opened without extracting that ZIP member.

The OBJ header says `Generated with Agisoft Metashape`; the item metadata does not identify capture hardware or method. The OBJ does **not** declare a coordinate unit. See the companion [mesh audit](../../../vesselforge/experiments/continuation_20261015/scanned_anchor_audit/README.md) for scale candidates, topology, views, and limitations.
