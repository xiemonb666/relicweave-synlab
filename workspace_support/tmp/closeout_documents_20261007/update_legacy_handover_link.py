from pathlib import Path
import hashlib

root=Path(r'C:\Users\xiemo\Desktop\ShardForge')
path=root/'relicweave-synlab/docs/a12/HANDOVER.md'
snapshot=root/'tmp/closeout_documents_20261007/A12_HANDOVER_20261002.original.md'
old=b'../../../docs/handover/20261007/HANDOVER.md'
new=b'../handover/20261007/HANDOVER.md'
before=path.read_bytes()
original=snapshot.read_bytes()
if not before.endswith(original): raise SystemExit('Legacy body is not byte-identical to preserved snapshot')
prefix=before[:-len(original)]
if prefix.count(old)!=1: raise SystemExit(f'Expected one old root-relative link in prefix, found {prefix.count(old)}')
after=prefix.replace(old,new,1)+original
path.write_bytes(after)
print('path',path)
print('bytes',len(after))
print('sha256',hashlib.sha256(after).hexdigest())
print('body_bytes',len(original))
print('body_sha256',hashlib.sha256(original).hexdigest())
print('body_unchanged',after.endswith(original))
