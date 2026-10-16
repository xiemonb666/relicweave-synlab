import importlib.metadata as md
import importlib.util
import shutil, sys
from synlab.api.capabilities import env_report
mods=['numpy','scipy','skimage','cv2','PIL','pyarrow','pandas','pydantic','fastapi','trimesh','manifold3d','shapely','svgpathtools','torch','gmsh','open3d','pycolmap','faiss','bpy']
for name in mods:
    try:
        spec=importlib.util.find_spec(name)
        exists=spec is not None
    except Exception as e:
        exists=f'probe-error:{type(e).__name__}'
    dist_name={'PIL':'pillow','cv2':'opencv-python-headless','skimage':'scikit-image','faiss':'faiss-cpu','pycolmap':'pycolmap','bpy':'bpy'}.get(name,name)
    try: version=md.version(dist_name)
    except md.PackageNotFoundError: version=None
    print(f'{name}: importable={exists} dist_version={version}')
print('python',sys.version.split()[0])
for exe in ['blender','gmsh','colmap']:
    print('binary',exe,shutil.which(exe))
print('env_report',env_report())
