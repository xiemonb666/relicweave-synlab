"""Debug: inspect what run_voronoi_event produces before the interfaces are linked."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from synlab.mothers.api import create_mother, default_params, ensure_registered
    from synlab.mothers.measure import thickness_samples
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.fracture.impact import BodyStats, MaterialStats
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture import voronoi_event as VE

    ensure_registered()
    cfg = load_physics_config()
    vessel, material_id = "V13", "M01"
    mother = create_mother(vessel, material_id, default_params(vessel),
                           np.random.default_rng(20261002))
    mesh = mother.mesh
    th = thickness_samples(mesh, np.arange(len(mesh.faces)), max_probes=200)
    profile = build_material_profile(material_id, default_material_params(material_id),
                                     np.random.default_rng(11))
    stats = profile.get("stats", {})
    body = BodyStats(vessel_id=vessel, volume_mm3=float(abs(mesh.volume)),
                     area_mm2=float(mesh.area), extents_mm=tuple(float(x) for x in mesh.extents),
                     thickness_min_mm=th["min_mm"], thickness_p05_mm=th["p05_mm"],
                     thickness_median_mm=th["median_mm"], thickness_max_mm=th["max_mm"])
    material = MaterialStats(material_id=material_id, density_g_cm3=2.2,
                             grain_size_mm=float(stats.get("grain_scale_mm", 0.05)))

    captured: dict = {}
    original = VE._link_voronoi_interfaces

    def spy(fragments, records, partition, fields, polygons, normals, **kwargs):
        captured["records"] = records
        captured["fields"] = fields
        captured["partition"] = partition
        return original(fragments, records, partition, fields, polygons, normals, **kwargs)

    VE._link_voronoi_interfaces = spy
    try:
        result = VE.run_voronoi_event(mother, event_id="DBG", config=cfg,
                                      rng=np.random.default_rng(2024), body=body,
                                      material=material, target_pieces=4)
    finally:
        VE._link_voronoi_interfaces = original

    for record in captured.get("records", []):
        counts = {k: len(v) for k, v in record.facet_faces.items()}
        cl = record.classification
        print("cell", record.cell_index, "faces", len(np.asarray(record.tagged.mesh.faces)),
              "facet_faces", counts,
              "iface_faces_total", cl.get("interface_faces_total"),
              "unattributed", cl.get("unattributed_interface_faces"),
              "mesh_id_range", np.unique(np.asarray(cl["vertex_mesh_id"])).tolist()[:6])
    print("interfaces", len(result.interfaces))
    for patch in result.interfaces:
        print("  patch", patch.interface_id, "area", patch.area_mm2, "gap", patch.gap_p95_mm,
              "meta_keys", sorted(patch.meta.keys())[:8])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
