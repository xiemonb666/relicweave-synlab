import json
d=json.load(open('data/a12_reports/physical_layer/fracture_appearance_run.json',encoding='utf-8'))
f=d['stages']['facets']
print("mm/px", round(f['mm_per_px_measured'],5), "geom unchanged", f['geometry_unchanged'], f['geometry_unchanged_in_every_variant'])
for k,v in f['variants'].items():
    for src in ('per_face_palette','constant_material_albedo'):
        m=v[src]
        print(f"  {k:15s} {src:26s} edge={m['facet']['facet_edge_dn_step']:7.2f} interior={m['facet']['interior_dn_step']:6.3f} ratio={m['facet']['facet_contrast_ratio']:7.2f} p95p05={m['dn']['dn_p95_minus_p05']:6.1f}")
md=f['mesh_density']; inv=md['inverse_solve']
print("patch", md['patch_edges']['n_faces'], "faces", round(md['patch_edges']['area_mm2'],1), "mm2 edge med", round(md['patch_edges']['edge_median_mm'],4))
print("solve", inv['lambda_min_mm'], "->", round(inv['required_edge_mm'],4), "mm,", round(inv['required_triangles']), "tri,", round(inv['required_cells_equivalent']), "cells, factor", round(inv['density_factor'],1))
im=d['stages']['images']
for v in im['views']:
    print("IMG", v['path'].split(chr(92))[-1], "L",v['long_edge_px'], "mm/px", round(v['mm_per_px_measured'],5), "Ra",v['ra_mm'], "dDN rms", round(v['dDN']['dDN_rms'],2), "p95", round(v['dDN']['dDN_p95_abs'],2), "facet off/on/smooth", round(v['facet_edge_step_relief_off'],2), round(v['facet_edge_step_relief_on'],2), round(v['facet_edge_step_smooth'],2))
gl=d['stages']['glaze']
print("glaze strip:", {k: (round(v,3) if isinstance(v,float) else v) for k,v in gl['relief_damping_strip'].items() if k in ('strip_width_mm','strip_width_px','ratio','changed_pixel_fraction')}, "dDN rms", round(gl['relief_damping_strip']['difference']['dDN_rms'],3))
print("stages", list(d['stages']), "timing", {k: round(v,1) for k,v in d['timing'].items()})
