import importlib.metadata as md, importlib.util, shutil
mods=['cadquery','OCP','xatlas','igl','openvdb','meshio','tetgen','pymeshfix','pymeshlab','taichi','pychrono','chrono','mpi4py','fenics','dolfinx','pyvista','vtk','pygalmesh','peridynamics']
for name in mods:
    try: ok=importlib.util.find_spec(name) is not None
    except Exception as e: ok=f'probe-error:{type(e).__name__}'
    try: ver=md.version({'OCP':'cadquery-ocp','igl':'libigl','pychrono':'pychrono'}.get(name,name))
    except md.PackageNotFoundError: ver=None
    print(f'{name}: importable={ok} version={ver}')
for exe in ['julia','radioss','openradioss','chrono','mpiexec','cmake','ninja','blender']:
    print(f'{exe}: {shutil.which(exe)}')
