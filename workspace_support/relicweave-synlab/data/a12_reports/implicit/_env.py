import importlib, sys
print("python", sys.version)
for name in ("numpy","scipy","trimesh","shapely","manifold3d","gmsh","skimage","torch","PIL","matplotlib","cv2","pytest","pydantic","yaml"):
    try:
        m = importlib.import_module(name)
        print(f"{name:12s} {getattr(m,'__version__','?')}")
    except Exception as e:
        print(f"{name:12s} MISSING {type(e).__name__}: {e}")
import torch
print("cuda", torch.cuda.is_available(), torch.version.cuda)
