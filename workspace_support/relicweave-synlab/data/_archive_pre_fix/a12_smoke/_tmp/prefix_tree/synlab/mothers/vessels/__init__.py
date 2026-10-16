"""Vessel construction families.

Importing this package registers every vessel entry point (V01..V24) in
``synlab.registry.REGISTRY``.  Each module owns one construction family and the
pydantic parameter models of the vessels it registers; the shared thick-profile,
extrusion and boolean kernels live one level up in ``synlab.mothers``.
"""

from __future__ import annotations

from . import group_composite, group_extrude, group_revolve, group_sheet  # noqa: F401

__all__ = ["group_revolve", "group_extrude", "group_sheet", "group_composite"]
