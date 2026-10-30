"""Regression coverage for the current contest's two-HBT MLS contract."""
import copy
import json
from pathlib import Path
import unittest

from test_mls_planner import manifest, PERMISSIVE
import mls_planner as planner


class HbtCountLimitTest(unittest.TestCase):
    def test_both_shipped_policies_generate_only_two_hbt_families(self):
        directory = Path(planner.__file__).parent
        for name in ("mls_config.json", "mls_fallback_config.json"):
            with self.subTest(policy=name):
                config = json.loads((directory / name).read_text())
                self.assertFalse(config["multi_branch_enabled"])
                design = manifest()
                plan = planner.plan_design(design, {**config, **PERMISSIVE})
                self.assertTrue(plan["selected"])
                for entry in plan["selected"]:
                    self.assertEqual(len(entry["hbts"]), 2)
                    self.assertEqual(len(entry["subnets"]), 3)
                planner.validate_plan(design, plan)

    def test_overrides_cannot_reenable_incompatible_branch_topology(self):
        with self.assertRaisesRegex(ValueError, "exactly two HBTs"):
            planner.config_values({"multi_branch_enabled": True})

    def test_validator_rejects_one_or_three_hbt_families(self):
        design = manifest()
        original = planner.plan_design(design, PERMISSIVE)
        self.assertTrue(original["selected"])
        for count in (1, 3):
            with self.subTest(count=count):
                plan = copy.deepcopy(original)
                entry = plan["selected"][0]
                entry["hbts"] = [copy.deepcopy(entry["hbts"][0]) for _ in range(count)]
                with self.assertRaisesRegex(ValueError, "exactly two HBTs"):
                    planner.validate_plan(design, plan)


if __name__ == "__main__":
    unittest.main()
