from pathlib import Path
import numpy as np
from synlab.storage.store import AssetStore
from synlab.api.routers.assets import _DEPLOYMENT_FEATURE_ARRAY_KEYS
from synlab.observe.features import assert_no_leakage
s=AssetStore(Path('data/a12_trainable/store'))
rs=s.list_assets(role='feature_bundle',limit=2000)
for r in rs:
    declared=(r.meta or {}).get('feature_fields')
    if not isinstance(declared,(list,tuple)):
        continue
    rel=r.files.get('arrays')
    path=s.root/Path(*rel.replace('\\','/').split('/'))
    with np.load(path,allow_pickle=False) as z:
        names=sorted(z.files)
    unknown=sorted(set(names)-_DEPLOYMENT_FEATURE_ARRAY_KEYS)
    undeclared=sorted(set(names)-set(declared))
    try:
        assert_no_leakage({'feature_arrays':{n:None for n in names},'declared_feature_fields':{n:None for n in declared}},path=f'feature_bundle[{r.asset_id}]')
        leak='ok'
    except Exception as e:
        leak=type(e).__name__+': '+str(e)[:100]
    print(r.asset_id,'declared=',len(declared),'arrays=',len(names),'unknown=',unknown,'undeclared=',undeclared,'leak=',leak)
    print(' DECL', sorted(declared))
    print(' ARR ', names)
    print(' META id-like', {k:r.meta.get(k) for k in ('run_id','lineage_id','split','mother_id','fragment_id','observation_id') if k in r.meta})
