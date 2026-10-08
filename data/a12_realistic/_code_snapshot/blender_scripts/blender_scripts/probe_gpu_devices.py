"""Probe the Cycles compute devices available to this Blender build (measurement only).

Run::

    & $env:BLENDER_BIN --background --python-exit-code 1 \
        --python blender_scripts/probe_gpu_devices.py

Prints one ``RWS_GPU_PROBE {json}`` line.  The probe *measures* what the build exposes; it
never assumes that a CUDA-capable GPU implies an OptiX-capable build.

Note: ``--factory-startup`` is deliberately **not** used here.  With it, the ``cycles`` addon
is not registered yet, ``preferences.addons['cycles']`` has no ``compute_device_type`` enum
options and the probe would report a false "no GPU backend" (measured).  The probe enables the
addon itself so the reading does not depend on the caller's startup flags.
"""

from __future__ import annotations

import json
import sys

import bpy


def ensure_cycles_addon() -> dict:
    info = {"enabled_before": "cycles" in bpy.context.preferences.addons.keys()}
    if not info["enabled_before"]:
        try:
            bpy.ops.preferences.addon_enable(module="cycles")
        except Exception as exc:  # noqa: BLE001
            info["enable_error"] = f"{type(exc).__name__}: {exc}"
    info["enabled_after"] = "cycles" in bpy.context.preferences.addons.keys()
    return info


def engine_options() -> list[str]:
    try:
        return [i.identifier for i in
                bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    except Exception:  # noqa: BLE001
        return []


def main() -> int:
    out = {"blender_version": bpy.app.version_string,
           "build_hash": (bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash, bytes)
                          else str(bpy.app.build_hash))}
    out.update(ensure_cycles_addon())
    out["engines_registered"] = engine_options()
    out["cycles_engine_present"] = "CYCLES" in out["engines_registered"]

    addon = bpy.context.preferences.addons.get("cycles")
    if addon is None:
        out["error"] = "the cycles addon could not be enabled in this build"
        print("RWS_GPU_PROBE " + json.dumps(out))
        return 1
    prefs = addon.preferences
    out["compute_device_type"] = getattr(prefs, "compute_device_type", None)
    try:
        out["compute_device_type_options"] = [
            item.identifier for item in
            type(prefs).bl_rna.properties["compute_device_type"].enum_items]
    except Exception as exc:  # noqa: BLE001
        out["compute_device_type_options_error"] = f"{type(exc).__name__}: {exc}"

    def snapshot():
        rows = []
        for dev in prefs.devices:
            entry = {"name": dev.name, "type": dev.type, "use": bool(dev.use)}
            for attr in ("id", "has_discrete_memory", "is_primary"):
                if hasattr(dev, attr):
                    try:
                        value = getattr(dev, attr)
                        entry[attr] = value if isinstance(value, (int, float, bool, str)) \
                            else str(value)
                    except Exception:  # noqa: BLE001
                        pass
            rows.append(entry)
        return rows

    try:
        prefs.get_devices()
    except Exception as exc:  # noqa: BLE001
        out["get_devices_error"] = f"{type(exc).__name__}: {exc}"
    out["devices_at_startup"] = snapshot()
    devices = out["devices_at_startup"]

    # ``type(prefs).bl_rna.properties['compute_device_type'].enum_items`` comes back **empty**
    # on this build even though the property accepts OPTIX/CUDA/HIP (measured), so the enum is
    # treated as informational only.  Usability is decided by (a) whether a device of that
    # type is enumerated and (b) whether assigning the property reads back unchanged.
    results = {}
    options = out.get("compute_device_type_options") or []
    for candidate in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL", "NONE"):
        entry = {"enum_available": candidate in options,
                 "devices_present": sorted({d["name"] for d in devices
                                            if d["type"] == candidate})}
        if candidate == "NONE":
            results[candidate] = entry
            continue
        try:
            prefs.compute_device_type = candidate
            readback = str(prefs.compute_device_type)
            entry["selected_ok"] = readback == candidate
            entry["readback"] = readback
            if not entry["selected_ok"]:
                entry["error"] = (f"the build kept compute_device_type={readback!r} instead "
                                  f"of {candidate!r}")
        except Exception as exc:  # noqa: BLE001
            entry["selected_ok"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"
        results[candidate] = entry
    out["backends"] = results
    # a backend is usable when it enumerates a device AND the property accepts it
    out["optix_usable"] = bool(results["OPTIX"].get("devices_present")
                               and results["OPTIX"].get("selected_ok"))
    out["cuda_usable"] = bool(results["CUDA"].get("devices_present")
                              and results["CUDA"].get("selected_ok"))
    out["preferred"] = ("OPTIX" if out["optix_usable"]
                        else "CUDA" if out["cuda_usable"] else "CPU")
    print("RWS_GPU_PROBE " + json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
