"""Pure-Python regression checks for the smooth candidate's hit audit.

This loads only the draft module's Python definitions. It does not import
CadQuery/OCP, construct geometry, render, or read/write CAD artifacts.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_PATH = PROJECT_ROOT / "vesselforge" / "experiments" / "smooth_surface_route_20261004" / "route_source_draft.py"
SPEC = importlib.util.spec_from_file_location("smooth_route_source_candidate", SOURCE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load source module at {SOURCE_PATH}")
SOURCE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SOURCE
SPEC.loader.exec_module(SOURCE)


class HitAuditChecks(unittest.TestCase):
    def test_chained_near_hits_are_preserved_and_refused_as_cuts(self) -> None:
        tolerance = SOURCE.ALL_HIT_NEAR_TOL_MM
        raw = [0.0, 0.75 * tolerance, 1.5 * tolerance]

        audit = SOURCE._audit_all_hit_distances(raw, max_distance_mm=10.0)

        self.assertEqual(audit["status"], "UNKNOWN_RAW_HIT_OR_NEAR_HIT_AMBIGUITY")
        self.assertEqual(audit["raw_hit_values_mm"], raw)
        self.assertEqual(len(audit["near_hit_groups"]), 1)
        self.assertEqual(audit["near_hit_groups"][0]["members_mm"], raw)
        self.assertEqual(audit["near_hit_groups"][0]["span_mm"], [0.0, 1.5 * tolerance])
        self.assertIsNone(audit["usable_hits_mm"])
        self.assertFalse(audit["cuts_use_group_mean"])

    def test_exact_duplicates_are_removed_without_averaging(self) -> None:
        raw = [1.0, 1.0, 2.0, 2.0]

        audit = SOURCE._audit_all_hit_distances(raw, max_distance_mm=10.0)

        self.assertEqual(audit["status"], "PASS_EXACT_DUPLICATES_ONLY")
        self.assertEqual(audit["raw_hit_values_mm"], raw)
        self.assertEqual(audit["exact_duplicate_hit_count"], 2)
        self.assertEqual(audit["usable_hits_mm"], [1.0, 2.0])

    def test_negative_nonfinite_and_out_of_range_hits_refuse_the_ray(self) -> None:
        audit = SOURCE._audit_all_hit_distances([-1.0, math.nan, 11.0], max_distance_mm=10.0)

        self.assertEqual(audit["status"], "UNKNOWN_RAW_HIT_OR_NEAR_HIT_AMBIGUITY")
        self.assertEqual(audit["raw_hit_values_mm"], [-1.0, "NaN", 11.0])
        self.assertIn("raw_hit_0_is_negative", audit["reason_codes"])
        self.assertIn("raw_hit_1_is_nonfinite", audit["reason_codes"])
        self.assertIn("raw_hit_2_is_beyond_query_limit", audit["reason_codes"])
        self.assertIsNone(audit["usable_hits_mm"])

    def test_interval_requires_room_for_a_strict_interior_probe(self) -> None:
        minimum = SOURCE.MIN_STRICT_INTERVAL_WIDTH_MM

        self.assertFalse(SOURCE._interval_has_strict_interior_probe(0.0, 0.75 * minimum))
        self.assertFalse(SOURCE._interval_has_strict_interior_probe(1.0, math.inf))
        self.assertTrue(SOURCE._interval_has_strict_interior_probe(0.0, 2.0 * minimum))


if __name__ == "__main__":
    unittest.main(verbosity=2)
