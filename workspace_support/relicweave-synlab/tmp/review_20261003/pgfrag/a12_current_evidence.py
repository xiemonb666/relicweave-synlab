from __future__ import annotations
import json, sqlite3, zipfile
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / 'data' / 'a12_trainable' / 'store'
DB = STORE / 'metadata.sqlite'
conn = sqlite3.connect('file:' + DB.as_posix() + '?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT asset_id, role, schema, unit, frame, qa_status, lineage_id, split, files_json, meta_json, ancestry_json FROM assets ORDER BY role, asset_id').fetchall()
runs = conn.execute('SELECT run_id,status,scope,profile FROM runs ORDER BY run_id').fetchall()
conn.close()

roles = Counter(r['role'] for r in rows)
role_by_asset_id = {r['asset_id']: r['role'] for r in rows}
files_by_role = defaultdict(Counter)
bytes_by_role = Counter()
arrays_by_role = defaultdict(Counter)
shapes_by_role_channel = defaultdict(lambda: defaultdict(Counter))
size_meta_by_role = defaultdict(Counter)
image_size_by_role = defaultdict(Counter)
camera_by_role = defaultdict(Counter)
run_by_role = defaultdict(Counter)
truth_roles = {'clean_truth','physical_truth','visible_labels','label_bundle'}
truth_array_keys = defaultdict(Counter)
ancestry_by_role = defaultdict(Counter)
asset_sizes=[]
npz_bytes_by_role=Counter()
npz_count_by_role=Counter()
errors=[]

for r in rows:
    role = r['role']
    files=json.loads(r['files_json'] or '{}')
    meta=json.loads(r['meta_json'] or '{}')
    ancestry=json.loads(r['ancestry_json'] or '{}')
    for key,rel in files.items():
        files_by_role[role][key]+=1
        p=STORE.joinpath(*str(rel).replace('\\','/').split('/'))
        try:
            n=p.stat().st_size
        except OSError as e:
            errors.append({'asset_id':r['asset_id'],'path':str(p),'error':repr(e)})
            continue
        bytes_by_role[role]+=n
        if key in {'arrays','mesh','data'}:
            asset_sizes.append(n)
        if key=='arrays' and p.suffix.lower()=='.npz':
            npz_count_by_role[role]+=1
            npz_bytes_by_role[role]+=n
            try:
                with zipfile.ZipFile(p) as zf:
                    for member in zf.namelist():
                        with zf.open(member) as f:
                            ver=np.lib.format.read_magic(f)
                            read_header = { (1, 0): np.lib.format.read_array_header_1_0,
                                            (2, 0): np.lib.format.read_array_header_2_0,
                                            (3, 0): np.lib.format.read_array_header_2_0 }.get(ver)
                            if read_header is None:
                                raise ValueError(f'unsupported NPY header version {ver}')
                            shape, fortran, dtype = read_header(f)
                        channel=member.rsplit('/',1)[-1]
                        channel=channel[:-4] if channel.endswith('.npy') else channel
                        descriptor=(str(tuple(int(x) for x in shape)), np.dtype(dtype).name)
                        arrays_by_role[role][channel]+=1
                        shapes_by_role_channel[role][channel][json.dumps(descriptor)]+=1
                        if role in truth_roles:
                            truth_array_keys[role][channel]+=1
            except Exception as e:
                errors.append({'asset_id':r['asset_id'],'array_path':str(p),'error':repr(e)})
    if isinstance(meta,dict):
        for key in ('image_size','output_size','render_grid','delivered_grid'):
            value=meta.get(key)
            if value is not None:
                image_size_by_role[role][json.dumps(value,sort_keys=True)]+=1
        for key in ('camera_model','profile_id','calibration_status','mask_semantics','obs_semantics','registry_version'):
            value=meta.get(key)
            if value is not None:
                camera_by_role[f'{role}:{key}'][str(value)]+=1
        if meta.get('run_id') is not None:
            run_by_role[role][str(meta['run_id'])]+=1
    anc_roles=[]
    refs=ancestry if isinstance(ancestry,list) else (
        ancestry.get('parents',ancestry.get('inputs',[])) if isinstance(ancestry,dict) else [])
    if isinstance(refs,list):
        for parent in refs:
            if isinstance(parent,dict):
                parent_id=parent.get('asset_id') or parent.get('ref')
                anc_roles.append(str(parent.get('role') or role_by_asset_id.get(parent_id,'unknown')))
            elif isinstance(parent,str):
                anc_roles.append(str(role_by_asset_id.get(parent,'unresolved_asset_ref')))
            else:
                anc_roles.append('untyped_ref')
    ancestry_by_role[role].update(anc_roles)

store_files=[]
for p in STORE.rglob('*'):
    if p.is_file():
        try: store_files.append(p.stat().st_size)
        except OSError: pass

report={
 'scope':'read-only metadata + NPZ headers; no image/depth array payload decompressed; no store writes',
 'store_root':str(STORE),
 'asset_total':len(rows),
 'run_records':{'n':len(runs),'statuses':dict(Counter(r['status'] for r in runs)),'rows':[dict(r) for r in runs]},
 'roles':dict(sorted(roles.items())),
 'qa_by_role':{role:dict(Counter(r['qa_status'] for r in rows if r['role']==role)) for role in sorted(roles)},
 'schema_by_role':{role:dict(Counter(r['schema'] for r in rows if r['role']==role)) for role in sorted(roles)},
 'file_refs_by_role':{role:dict(sorted(c.items())) for role,c in sorted(files_by_role.items())},
 'asset_files_bytes_by_role':dict(sorted(bytes_by_role.items())),
 'npz':{
   'archive_count_by_role':dict(sorted(npz_count_by_role.items())),
   'archive_compressed_bytes_by_role':dict(sorted(npz_bytes_by_role.items())),
   'channels_by_role':{role:dict(sorted(c.items())) for role,c in sorted(arrays_by_role.items())},
   'shape_dtype_by_role_channel':{role:{ch:dict(sorted(cnt.items())) for ch,cnt in sorted(channels.items())} for role,channels in sorted(shapes_by_role_channel.items())},
   'truth_related_channel_counts':{role:dict(sorted(c.items())) for role,c in sorted(truth_array_keys.items())},
 },
 'view_size_metadata_by_role':{role:dict(sorted(c.items())) for role,c in sorted(image_size_by_role.items())},
 'metadata_semantics_by_role_field':{field:dict(sorted(c.items())) for field,c in sorted(camera_by_role.items())},
 'run_id_by_role':{role:dict(sorted(c.items())) for role,c in sorted(run_by_role.items())},
 'ancestry_parent_roles_by_role':{role:dict(sorted(c.items())) for role,c in sorted(ancestry_by_role.items())},
 'store_total_bytes_recursive':sum(store_files),
 'selected_asset_payload_size_bytes':{'min':min(asset_sizes) if asset_sizes else None,'median':int(np.median(asset_sizes)) if asset_sizes else None,'p95':int(np.percentile(asset_sizes,95)) if asset_sizes else None,'max':max(asset_sizes) if asset_sizes else None,'n':len(asset_sizes)},
 'errors':errors,
 'limitations':['NPZ array values (including RGB/depth pixels) were not loaded; shapes/dtypes and stored byte counts only.', 'Asset QA statuses are recorded states, not independent acceptance of external realism.']
}
out=Path(__file__).resolve().parent/'a12_current_evidence.json'
out.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
print(json.dumps({'output':str(out),'asset_total':len(rows),'roles':dict(sorted(roles.items())),'store_bytes':report['store_total_bytes_recursive'],'npz_count_by_role':report['npz']['archive_count_by_role'],'npz_bytes_by_role':report['npz']['archive_compressed_bytes_by_role'],'errors':len(errors)},ensure_ascii=False,indent=2))
