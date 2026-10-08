from pathlib import Path
from collections import Counter
import numpy as np
from synlab.storage.store import AssetStore
p=Path('data/a12_trainable/store')
print('exists', p.exists(), p.resolve())
s=AssetStore(p)
rs=s.list_assets(role='feature_bundle', limit=2000)
print('count', len(rs))
print('schemas', Counter(r.schema for r in rs))
print('feature_fields types', Counter(type((r.meta or {}).get('feature_fields')).__name__ for r in rs))
for r in rs[:16]:
    print('ASSET', r.asset_id, 'schema', r.schema, 'file_keys', sorted(r.files), 'decl', len((r.meta or {}).get('feature_fields') or []), 'meta_keys', sorted((r.meta or {}).keys())[:18])
    try:
        fp=s.root/'assets'/r.asset_id/'arrays.npz'
        with np.load(fp, allow_pickle=False) as z:
            print(' ARRAY_KEYS', sorted(z.files))
    except Exception as e:
        print(' ARRAY_ERROR', type(e).__name__, str(e)[:160])
