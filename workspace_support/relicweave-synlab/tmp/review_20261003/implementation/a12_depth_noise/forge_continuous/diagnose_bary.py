from pathlib import Path
import runpy, numpy as np
ns=runpy.run_path('tests/a12/integrations/test_forge_asset.py')
tmp=Path('tmp/review_20261003/implementation/a12_depth_noise/forge_continuous/diag-fixture2')
asset=ns['load_forge_asset'](ns['_write_package'](tmp/'pkg', continuous_recipe=True, sloped_region_1=True))
spec=ns['RenderSpec'](supersample=1,near_mm=1,far_mm=100,max_pixels=4096)
frame=ns['_frame'](); out=ns['render_forge_asset_preview'](asset,frame,light=ns['_light'](),spec=spec,allow_prototype_preview=True)
tri=asset.vertices_mm[asset.faces[0]]; origin=frame.T_WC[:3,3]
for row,col in zip(*np.nonzero(out.id_map==0)):
 d=frame.T_WC[:3,:3]@np.array([(col-frame.K[0,2])/frame.K[0,0],(row-frame.K[1,2])/frame.K[1,1],1.])
 q=ns['_ray_barycentric_world'](origin,d,tri)
 if q:
  dist,bary=q; z=bary@asset.vertices_material_xyz_mm[asset.faces[0],2]
  print(row,col,bary,z,out.rgb_linear[row,col].tolist())
