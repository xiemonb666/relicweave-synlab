"""Named, pure helpers shared by the A12 degradation operator tests."""

from __future__ import annotations

FAMILY_OF = {axis_id: axis_id[0] for axis_id in
             [f"P{i:02d}" for i in range(1, 9)] + [f"I{i:02d}" for i in range(1, 11)]
             + [f"G{i:02d}" for i in range(1, 9)] + [f"X{i:02d}" for i in range(1, 6)]}

ALL_AXES = tuple(sorted(FAMILY_OF))
