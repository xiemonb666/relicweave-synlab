"""Mesh payload serialisation for the asset store (plan 23.2).

Face-level semantics (surface tag, source triangle, interface id, side, material id)
travel with the mesh as ``face__<name>`` arrays so that no semantic information is
silently dropped when an asset is written and read back.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import trimesh

FACE_PREFIX = "face__"


def mesh_arrays(mesh: Any, face_attrs: dict[str, np.ndarray] | None = None) -> dict[str, np.ndarray]:
    """Serialise a trimesh mesh plus its face attributes to a flat array mapping."""
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"expected trimesh.Trimesh, got {type(mesh)!r}")
    out: dict[str, np.ndarray] = {
        "vertices": np.ascontiguousarray(mesh.vertices, dtype=np.float64),
        "faces": np.ascontiguousarray(mesh.faces, dtype=np.int32),
    }
    attrs: dict[str, np.ndarray] = {}
    meta_attrs = (mesh.metadata or {}).get("face_attr_arrays") if mesh.metadata else None
    if isinstance(meta_attrs, dict):
        attrs.update({str(k): np.asarray(v) for k, v in meta_attrs.items()})
    if face_attrs:
        attrs.update({str(k): np.asarray(v) for k, v in face_attrs.items()})
    for name, arr in attrs.items():
        arr = np.asarray(arr)
        if arr.shape[0] != len(mesh.faces):
            raise ValueError(f"face attribute {name} has {arr.shape[0]} entries, "
                             f"mesh has {len(mesh.faces)} faces")
        out[FACE_PREFIX + name] = np.ascontiguousarray(arr)
    return out


def arrays_to_mesh(arrays: dict[str, np.ndarray]) -> tuple[trimesh.Trimesh, dict[str, np.ndarray]]:
    """Rebuild a mesh and its face attributes from a stored array mapping."""
    if "vertices" not in arrays or "faces" not in arrays:
        raise ValueError("mesh payload requires 'vertices' and 'faces'")
    vertices = np.asarray(arrays["vertices"], dtype=np.float64)
    faces = np.asarray(arrays["faces"], dtype=np.int32)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    attrs = {k[len(FACE_PREFIX):]: np.asarray(v) for k, v in arrays.items() if k.startswith(FACE_PREFIX)}
    mesh.metadata = dict(mesh.metadata or {})
    mesh.metadata["face_attr_arrays"] = attrs
    return mesh, attrs


def with_face_attrs(mesh: trimesh.Trimesh, **attrs: np.ndarray) -> trimesh.Trimesh:
    """Attach authoritative face-level semantics to a mesh in place."""
    mesh.metadata = dict(mesh.metadata or {})
    current = dict(mesh.metadata.get("face_attr_arrays") or {})
    for name, value in attrs.items():
        arr = np.asarray(value)
        if arr.shape[0] != len(mesh.faces):
            raise ValueError(f"face attribute {name} length {arr.shape[0]} != faces {len(mesh.faces)}")
        current[name] = arr
    mesh.metadata["face_attr_arrays"] = current
    return mesh


def face_attrs(mesh: trimesh.Trimesh) -> dict[str, np.ndarray]:
    return dict((mesh.metadata or {}).get("face_attr_arrays") or {})
