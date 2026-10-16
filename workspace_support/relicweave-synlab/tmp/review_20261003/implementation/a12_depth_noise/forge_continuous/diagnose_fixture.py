from pathlib import Path
import runpy, numpy as np
ns=runpy.run_path('tests/a12/integrations/test_forge_asset.py')
tmp=Path('tmp/review_20261003/implementation/a12_depth_noise/forge_continuous/diag-fixture')
asset=ns['load_forge_asset'](ns['_write_package'](tmp/'pkg', continuous_recipe=True, sloped_region_1=True))
spec=ns['RenderSpec'](supersample=1,near_mm=1,far_mm=100,max_pixels=4096)
out=ns['render_forge_asset_preview'](asset, ns['_frame'](), light=ns['_light'](), spec=spec,allow_prototype_preview=True)
mask=out.id_map==0
print('hits',mask.sum(),'colors',np.unique(out.rgb_linear[mask],axis=0)[:20])
print('coords',np.argwhere(mask))
angle=np.deg2rad(24); pose=np.array([[1,0,0,0],[0,np.cos(angle),-np.sin(angle),0],[0,np.sin(angle),np.cos(angle),0],[0,0,0,1]],float)
out2=ns['render_forge_asset_preview'](asset,ns['_frame'](),light=ns['_light'](),spec=spec,allow_prototype_preview=True,object_pose=pose)
print('posed hits',np.sum(out2.id_map==0),'coords',np.argwhere(out2.id_map==0))
