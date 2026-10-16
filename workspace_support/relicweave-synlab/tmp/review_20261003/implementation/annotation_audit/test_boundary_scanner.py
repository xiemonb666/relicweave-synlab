import unittest

from audit_artifacts import (
    SEMANTIC_ALIAS_KEYS,
    classify_metadata_key,
    run_boundary_self_checks,
    scan_tree,
)


class BoundaryScannerTests(unittest.TestCase):
    def test_lineage_id_in_dict_key_is_detected_without_value_match(self):
        keys, hits = scan_tree({"LIN0042_V03_M07_PAT11_E02": {"index": 0}})
        self.assertIn("LIN0042_V03_M07_PAT11_E02", [item["key"] for item in keys])
        self.assertEqual(["key"], [item["source"] for item in hits])

    def test_semantic_alias_names_are_sensitive_metadata(self):
        aliases = {"lineage", "mother", "fragment", "query_id", "historical_n_g"}
        keys, _ = scan_tree({name: "fixture" for name in aliases})
        actual = {item["key"].lower() for item in keys}
        self.assertTrue(aliases.issubset(actual))
        self.assertTrue(aliases.issubset(SEMANTIC_ALIAS_KEYS))
        self.assertTrue(all(classify_metadata_key(name, "queries.parquet") == "sensitive_semantic_metadata"
                            for name in aliases))

    def test_zarr_level_is_storage_metadata_not_ground_truth(self):
        keys, _ = scan_tree({"zarr_format": 3, "node_type": "array", "attributes": {"level": 0}})
        level = next(item for item in keys if item["key"] == "level")
        self.assertEqual("zarr_storage_metadata", classify_metadata_key(level["key"], "deploy/scale/zarr.json"))
        self.assertEqual("ordinary_metadata", classify_metadata_key(level["key"], "queries.json"))

    def test_embedded_v2_self_checks_pass(self):
        self.assertTrue(run_boundary_self_checks()["all_pass"])


if __name__ == "__main__":
    unittest.main()
