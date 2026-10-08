from __future__ import annotations

import hashlib
import inspect
import json
import pathlib
import sys

import manifold3d
import trimesh


def file_sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


mod_path = pathlib.Path(manifold3d.__file__)
boolean_path = pathlib.Path(trimesh.boolean.__file__)
report = {
    "schema": "a12.mesh64-static-api-evidence.v1",
    "inspection_kind": "static_only_no_mesh_construction_no_boolean",
    "cwd": str(pathlib.Path.cwd()),
    "python_executable": sys.executable,
    "python_version": sys.version,
    "trimesh_version": trimesh.__version__,
    "manifold3d_version": getattr(manifold3d, "__version__", None),
    "Mesh64_init_signature": inspect.getdoc(manifold3d.Mesh64.__init__),
    "Mesh_init_signature": inspect.getdoc(manifold3d.Mesh.__init__),
    "Manifold_init_overloads": inspect.getdoc(manifold3d.Manifold.__init__),
    "Manifold_xor_doc": inspect.getdoc(manifold3d.Manifold.__xor__),
    "Manifold_status_doc": inspect.getdoc(manifold3d.Manifold.status),
    "Manifold_to_mesh64_doc": inspect.getdoc(manifold3d.Manifold.to_mesh64),
    "has_to_mesh64": hasattr(manifold3d.Manifold, "to_mesh64"),
    "trimesh_boolean_module_path": str(boolean_path),
    "trimesh_boolean_module_sha256": file_sha(boolean_path),
    "manifold3d_extension_path": str(mod_path),
    "manifold3d_extension_sha256": file_sha(mod_path),
    "trimesh_boolean_manifold_source": inspect.getsource(trimesh.boolean.boolean_manifold),
    "mesh_construction_count": 0,
    "boolean_call_count": 0,
}
print(json.dumps(report, indent=2, ensure_ascii=False))
