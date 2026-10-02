"""Print the per-hop detail of one end-to-end measurement report (read-only)."""
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                    else "data/a12/reports/fracture_surface_signal/end_to_end.json")
doc = json.loads(path.read_text(encoding="utf-8"))
for lineage, entry in doc["measured"].items():
    print("=" * 78)
    print(lineage)
    for asset_id, row in entry["physical"].items():
        print(f"-- physical[{row['role']}] {asset_id} faces={row.get('faces')} "
              f"origin={row.get('origin_kind_histogram')} iface_ids={row.get('interface_id_histogram')}")
        print(f"   array keys with face__: {row.get('face_channel_keys')}")
        prov = row.get("face_provenance_meta") or {}
        own = prov.get("component") or {}
        if own:
            print(f"   tol={prov.get('tol_mm')} band={prov.get('roi_band_mm')} "
                  f"mapped={own.get('mapped_fraction')} born_in_roi={own.get('born_in_declared_roi')}")
    for asset_id, row in entry["observation"].items():
        print(f"-- obs {asset_id} frag={row['fragment_id']} source={row['surface_tag_source']} "
              f"pixels={row['pixels_total']} object={row['object_pixels']} rim={row['rim_pixels']} "
              f"rim/object={row['rim_fraction_of_object']:.5f} hist={row['histogram']}")
        for view, v in row["views"].items():
            print(f"     {view}: pixels={v['pixels']} object={v['object_pixels']} rim={v['rim_pixels']}"
                  f" ({v['rim_fraction_of_object']:.5f}) hist={v['histogram']}")
    for asset_id, row in entry["truth"].items():
        print(f"-- truth[{row['role']}] {asset_id}")
        print(f"   iface arrays: {row['iface_array_keys']}")
        print(f"   iface meta keys: {row['iface_meta_keys']}")
        for key in ("iface_new_faces_total", "iface_new_area_total_mm2", "iface_origin_kind_faces",
                    "iface_rim_pixels", "iface_rim_visible", "iface_rim_pixels_per_view",
                    "iface_visible_samples_by_id", "interface_count_meta"):
            if key in row:
                print(f"   {key}: {json.dumps(row[key])[:300]}")
        for key in ("iface_new_faces", "iface_new_area_mm2", "iface_visible_samples",
                    "iface_corr_samples"):
            if key in row:
                print(f"   {key}: total={row[key]['total']} values={row[key]['values'][:12]}")
