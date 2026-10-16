from __future__ import annotations
import csv, inspect, json
from pathlib import Path
import yaml
from synlab.degrade.registry import AXIS_REGISTRY

ROOT=Path.cwd()
OUT=ROOT/'tmp/review_20261003/implementation/degradation_audit'
spec=yaml.safe_load((ROOT/'configs/a12/next_experiment.yaml').read_text(encoding='utf-8-sig'))
physical=json.loads((ROOT/'configs/a12/physical_recipes.json').read_text(encoding='utf-8-sig'))
by_id={r.get('recipe_id'):r for r in physical.get('recipes',[])}
next_physical=[]
for rid in spec.get('physical',{}).get('recipes',[]):
    r=by_id.get(rid,{})
    next_physical.extend(str(o.get('axis_id')) for o in r.get('operators',[]) if o.get('axis_id'))
paired=[]
for ref in spec.get('degraded_recipe_refs',[]):
    p=ROOT/Path(ref)
    data=yaml.safe_load(p.read_text(encoding='utf-8-sig'))
    paired.extend(str(o.get('axis_id')) for o in data.get('operators',[]) if o.get('axis_id'))
div=yaml.safe_load((ROOT/'configs/a12/degrade_diversity.yaml').read_text(encoding='utf-8-sig'))
probe_status={
    'P02':{'levels':[0,1,4],'evidence':'probe_manifest.json / appearance_probe.json'},
    'P05':{'levels':[0,1,4],'evidence':'appearance_probe.json'},
    'P06':{'levels':[0,1,4],'evidence':'appearance_probe.json'},
    'I03':{'levels':[0,1,4],'evidence':'phone_noise_probe.json'},
}
rows=[]
for axis_id in AXIS_REGISTRY.ids():
    op=AXIS_REGISTRY.get(axis_id)
    _src, start=inspect.getsourcelines(type(op))
    if axis_id.startswith('P'):
        route=('P02/P03/P04 declared narrow-band via _PhysicalAxis.physical_result; '
               'other P axes physical.api.apply_damage')
        route_file='synlab/degrade/axes.py'
    else:
        route=f'{op.STAGE} {op.SUBSTAGE} via {type(op).__name__}._apply'
        route_file='synlab/degrade/axes.py'
    current_obs=probe_status.get(axis_id)
    rows.append({
      'axis_id':axis_id,'class':type(op).__name__,'axis_source':f'synlab/degrade/axes.py:{start}',
      'stage':op.STAGE,'substage':op.SUBSTAGE,'default_variant':op.default_variant,
      'variants':'|'.join(op.variants()),'levels_0_to_4':json.dumps([op.level_parameters(i) for i in op.levels()],ensure_ascii=False),
      'factor_kind':op.factor_kind_for(op.default_variant),
      'accepted_sources':'|'.join(op.ACCEPTED_SOURCES),
      'label_invalidations':'|'.join(op.LABEL_INVALIDATIONS),
      'implemented_current':True,'reachable_api':'synlab.degrade.api.apply_axis',
      'route':route,'route_source':route_file,
      'next_experiment_physical_recipe':axis_id in set(next_physical),
      'next_experiment_degraded_recipe_ref_only':axis_id in set(paired) and axis_id not in set(next_physical),
      'opt_in_diversity_declared':axis_id in {str(a.get('axis_id')) for a in div.get('axes',[])},
      'opt_in_diversity_selection':div.get('per_lineage',{}).get('selection'),
      'observed_in_this_audit':bool(current_obs),
      'observed_levels':','.join(map(str,current_obs['levels'])) if current_obs else '',
      'real_world_validated_by_this_audit':False,
      'evidence':current_obs['evidence'] if current_obs else '',
      'current_status':'FUNCTIONALLY_OBSERVED_SYNTHETIC' if current_obs else 'NOT_RUN_IN_THIS_AUDIT',
    })
with (OUT/'axis_feature_matrix.csv').open('w',newline='',encoding='utf-8-sig') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]))
    writer.writeheader();writer.writerows(rows)
summary={
 'registry_axis_count_current':len(rows),
 'axis_ids_current':[r['axis_id'] for r in rows],
 'next_experiment_physical_recipe_axes':sorted(set(next_physical)),
 'next_experiment_degraded_recipe_ref_axes':sorted(set(paired)),
 'next_experiment_degraded_recipe_ref_axis_count':len(set(paired)),
 'opt_in_diversity_config_enabled':bool(div.get('enabled')),
 'opt_in_diversity_config_declared_axes':[str(a.get('axis_id')) for a in div.get('axes',[])],
 'opt_in_diversity_per_lineage':div.get('per_lineage'),
 'current_probe_axes':probe_status,
 'current_source_lines':{
   'api_dispatch':'synlab/degrade/api.py:203-218',
   'api_parameter_basis_and_apply':'synlab/degrade/api.py:222-303',
   'physical_route':'synlab/degrade/axes.py:291-451',
   'diversity_opt_in':'synlab/pipeline.py:759-781, 1889-1906',
   'degraded_recipe_ref_parse_only':'synlab/config.py:142-148 (search all of synlab for consumers found only schema + config loader)',
 },
 'real_world_validation':'NONE in this audit; all live runs use small synthetic fixtures.',
}
(OUT/'axis_feature_matrix_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(summary,indent=2,ensure_ascii=False))
