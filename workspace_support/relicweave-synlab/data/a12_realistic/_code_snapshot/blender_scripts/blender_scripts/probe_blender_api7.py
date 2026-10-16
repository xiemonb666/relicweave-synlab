"""Seventh probe: how does the 5.2 compositor node group declare its output?

Run::

    & $env:BLENDER_BIN --background --python blender_scripts/probe_blender_api7.py
"""

from __future__ import annotations

import json
import sys

import bpy


def main() -> int:
    out: dict = {}
    out["types_with_composite_or_output"] = sorted(
        n for n in dir(bpy.types) if ("Composite" in n or "GroupOutput" in n
                                     or "GroupInput" in n) and n.startswith("Compositor"))
    out["all_compositor_types_tail"] = sorted(n for n in dir(bpy.types)
                                              if n.startswith("CompositorNode"))[-6:]
    tree = bpy.data.node_groups.new(name="rws_probe7", type="CompositorNodeTree")
    out["tree_attrs"] = [a for a in dir(tree) if "interface" in a or "output" in a.lower()]
    try:
        iface = tree.interface
        out["interface_attrs"] = [a for a in dir(iface) if not a.startswith("_")]
        item = iface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        out["new_socket"] = {"ok": True, "name": item.name}
    except Exception as exc:  # noqa: BLE001
        out["new_socket"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    for tname in ("CompositorNodeComposite", "CompositorNodeViewer", "NodeGroupOutput",
                  "NodeGroupInput", "CompositorNodeGroup"):
        try:
            node = tree.nodes.new(tname)
            out.setdefault("node_new", {})[tname] = {
                "ok": True, "inputs": [s.name for s in node.inputs],
                "outputs": [s.name for s in node.outputs]}
        except Exception as exc:  # noqa: BLE001
            out.setdefault("node_new", {})[tname] = {"ok": False,
                                                     "error": f"{type(exc).__name__}: {exc}"}
    # CombineColor sockets
    try:
        cc = tree.nodes.new("CompositorNodeCombineColor")
        out["combine_color"] = {
            "inputs": [s.name for s in cc.inputs], "outputs": [s.name for s in cc.outputs],
            "modes": [i.identifier for i in
                      type(cc).bl_rna.properties["mode"].enum_items]
            if "mode" in type(cc).bl_rna.properties else None}
    except Exception as exc:  # noqa: BLE001
        out["combine_color"] = f"{type(exc).__name__}: {exc}"
    print("PROBE7_JSON_BEGIN")
    print(json.dumps(out, indent=2, default=str))
    print("PROBE7_JSON_END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
