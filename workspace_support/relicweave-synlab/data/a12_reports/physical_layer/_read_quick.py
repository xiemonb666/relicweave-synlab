import json
d = json.load(open('data/a12_reports/physical_layer/fracture_appearance_run.json', encoding='utf-8'))
s = d['stages']['sweep']; f = s['relief_field']
print("roi", d['roi_frame']['roi_id'], "lit", round(d['roi_frame'].get('lit_score', float('nan')),3), "specimen", s['specimen']['vessel_id'], s['specimen']['material_id'])
print("field Ra_unit", round(f['ra_at_unit_mm'],4), "slope_unit", round(f['slope_rms_at_unit_scale'],4), "scale", round(f['amplitude_scale'],4))
for row in s['rows']:
    if row['status']!='OK': print(row); continue
    off=row['relief_off']
    print("mm/px",round(row['mm_per_px_measured'],5),"L",row['long_edge_px'],"| off dn p95p05",round(off['dn']['dn_p95_minus_p05'],1),
          "| facet edge",round(off['facet']['facet_edge_dn_step'],2),"interior",round(off['facet']['interior_dn_step'],3),
          "| lambert unlit",round(off['dn'] and 0,3))
    for a in row['amplitudes']:
        print("     Ra",a['ra_target_mm'],"dDN rms",round(a['difference']['dDN_rms'],3),"p95",round(a['difference']['dDN_p95_abs'],3),
              "| changed>=1",round(a['changed_code_values']['fraction_above_1_dn'],3),
              "| pred",round(a['prediction'].get('dDN_from_measured_slope', float('nan')),3))
u = s.get('unlit_control',{})
print("unlit control:", u.get('vessel_id'), u.get('roi_id'), "lit", round(u.get('lit_score',0),3),
      "dDN rms", round(u.get('difference',{}).get('dDN_rms',-1),4), "unlit_frac", (u.get('lambert') or {}).get('unlit_fraction'))
print("noise control:", round(s['noise_control']['difference_shading']['dDN_rms'],4))

