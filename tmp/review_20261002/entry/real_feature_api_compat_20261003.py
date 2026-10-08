from pathlib import Path
from tempfile import mkdtemp
import io, json
import numpy as np
from fastapi.testclient import TestClient
from synlab.storage.store import AssetStore
from synlab.api.integrity import record_integrity
from synlab.api import create_app

source=AssetStore(Path('data/a12_trainable/store'))
real=next(r for r in source.list_assets(role='feature_bundle',limit=2000) if isinstance((r.meta or {}).get('feature_fields'),list))
rel=real.files['arrays']
with np.load(source.root/Path(*rel.replace('\\','/').split('/')),allow_pickle=False) as archive:
    arrays={name: archive[name].copy() for name in archive.files}
tmp=Path(mkdtemp(prefix='real-feature-api-',dir='tmp/review_20261002/entry'))
target=AssetStore(tmp/'store')
copy=target.commit_asset(role=real.role,schema=real.schema,unit=real.unit,frame=real.frame,payload=arrays,meta=dict(real.meta),qa=dict(real.qa),qa_status=real.qa_status,ancestry=real.ancestry,lineage_id=real.lineage_id,split=real.split)
record_integrity(target,copy.asset_id,source='producer')
client=TestClient(create_app(tmp/'store',role='deployment_client'))
try:
    listing=client.get('/api/synlab/assets')
    assert listing.status_code==200, listing.text
    item=next(x for x in listing.json()['items'] if x['asset_id']==copy.asset_id)
    metadata=client.get(f'/api/synlab/assets/{copy.asset_id}')
    assert metadata.status_code==200,metadata.text
    asset=metadata.json()['asset']
    response=client.get(f'/api/synlab/assets/{copy.asset_id}/files/feature_bundle',params={'verify':'false'})
    assert response.status_code==200,response.text
    with np.load(io.BytesIO(response.content),allow_pickle=False) as sent:
        sent_names=sorted(sent.files)
    assert sent_names==sorted(arrays), (sent_names,sorted(arrays))
    assert item['metadata_view']['array_keys']==sent_names
    assert asset['metadata_view']['array_keys']==sent_names
    private=json.dumps({'item':item,'asset':asset},ensure_ascii=False)
    for v in [real.meta.get('run_id'),real.meta.get('observation_id'),real.meta.get('lineage_id'),real.meta.get('split')]:
        if v: assert v not in private, v
    print(json.dumps({'status':'PASS','source_asset':real.asset_id,'copied_asset':copy.asset_id,'schema':real.schema,'array_count':len(sent_names),'array_keys':sent_names,'listing_status':listing.status_code,'metadata_status':metadata.status_code,'download_status':response.status_code,'verify_header':response.headers.get('X-SynLab-Hash-Verified'),'note':'temp copy committed from current trainable asset arrays/meta; source store stayed read-only'},ensure_ascii=False))
finally:
    client.close()
