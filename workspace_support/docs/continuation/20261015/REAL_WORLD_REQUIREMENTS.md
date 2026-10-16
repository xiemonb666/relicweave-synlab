# Reality requirements for all vessel families

User direction, 2026-10-15: everyday utensils and archaeological vessels are both required. Every existing and future vessel family must remain consistent with real objects. Passing a solver or producing a watertight solid does not satisfy this requirement.

## Current correction

The 24 mm diameter, 4 mm thick hemispherical specimen and the earlier small handled prototype are numerical/engineering controls. Keep their immutable geometry, native results, failures and receipts. They are not the main realistic-vessel corpus and must not be presented as representative everyday bowls, archaeological reconstructions, or physically qualified training samples. Existing successful native computations remain useful for testing the reusable solver and data interfaces.

## Shared requirements

1. Bind each candidate family to identified real-object references. Keep everyday and archaeological context explicit; preserve object IDs, primary URLs, reported dimensions, material/process descriptions and access/license information.
2. Record source measurements, visual interpretation, and generator assumptions separately. A nominal catalogue diameter is not a measured internal mouth diameter. Packaging weight is not specimen mass. Photographs alone do not establish numerical wall thickness, a complete section or mechanical parameters.
3. Build the actual relevant form: outside and inside profiles, rim section, base or foot, neck/shoulder, handles, spout and joints where present. A footring is appropriate only for a subtype/reference that supports it; it is not mandatory for every archaeological bowl. Uniform scaling of an arbitrary analytic shape is insufficient.
4. Use reference-specific plausible parameter domains and manufacturing constraints. Preserve open cavities, coherent wall/base transitions, connected feet/handles, feasible thickness, and intended resting/contact surfaces. Do not shrink specimens while retaining full-size wall thickness to reduce solver cost.
5. Check dimensional and geometric measurements independently: complete solid/surface topology, positive volume, exterior/interior and cavity, thickness evidence, component joints, STEP roundtrip, source surface ancestry, and mesh approximation. Mark finite samples as finite evidence, not global certificates.
6. Compare rendered side, top, bottom and section views with the reference evidence before accepting the candidate for the main corpus. A metadata declaration or a geometry PASS cannot replace that comparison. Start with plain material so decoration does not hide an incorrect silhouette.
7. Bind ornament to the corresponding surface/process and reference context. Distinguish painted, incised, molded relief and glaze; do not infer archaeological attribution from arbitrary bands. Mechanics remain separately uncalibrated until supported by actual material evidence.
8. Keep numerical-control, reference-guided synthetic, and measured/reconstructed specimens distinguishable through VF, PG-Frag and A12. Synthetic assumptions may support exploratory development but cannot silently become measured truth or production PRETRAIN eligibility.
9. Reuse the existing CAD kernel, mesh tooling, native physics, closed-fragment extraction and observation renderer. Re-evaluate mesh, time step, loading, material and qualification on the new full-size geometry. A previous specimen's numerical acceptance cannot be transferred to a different vessel by changing its name.

## Initial implementation scope

Audit all current VF/A12 families, not only the bowl. Build a reusable smooth meridian/section adapter first, with a daily bowl and an archaeological bowl as the first reviewed examples. Follow with referenced cups/beakers, jars and handled vessels; use scanned meshes or technical sections where available rather than rebuilding existing suitable data. Further types inherit the same requirements. The full goal remains open.

Reference research and the first corrected geometry candidates are in progress. No new reality-alignment or archaeological-reconstruction PASS is established by this document.
