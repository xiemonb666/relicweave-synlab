from pathlib import Path
from PIL import Image
import hashlib,json
import sys
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path(r'C:\Users\xiemo\Desktop\ShardForge\tmp\closeout_documents_20261007\master_v147_render')
files=sorted(root.glob('page-*.png'),key=lambda p:int(p.stem.split('-')[1]))
dims={}; zero=[]
for p in files:
 if p.stat().st_size==0: zero.append(p.name); continue
 with Image.open(p) as im: dims[str(im.size)]=dims.get(str(im.size),0)+1
for p in [root.with_suffix('.log'),root/'RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.pdf']:
 if p.exists():
  h=hashlib.sha256(p.read_bytes()).hexdigest(); print(p.name,p.stat().st_size,h)
print('png_count',len(files),'zero_bytes',zero,'dimensions',dims)
print('first',files[0].name if files else None,'last',files[-1].name if files else None)
