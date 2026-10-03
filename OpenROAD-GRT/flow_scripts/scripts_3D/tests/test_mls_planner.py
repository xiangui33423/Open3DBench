#!/usr/bin/env python3
"""MLS regression tests for contest connectivity, lattice, and resource limits."""

from __future__ import annotations

import copy
import itertools
import json
import re
import shutil
import subprocess
import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from mls_planner import DemandGrid, HbtSites, config_values, hpwl, plan_design, place_pair, tcl_word


def signal_net(name="data[3]", die="bottom", y=25000):
    return {
        "name": name,
        "signal_type": "SIGNAL",
        "special": False,
        "pins": [
            {"inst": "driver_" + name + "_" + die, "pin": "Z", "x": 20000,
             "y": y, "die": die, "io": "OUTPUT", "hbt": False},
            {"inst": "near_" + name + "_" + die, "pin": "A", "x": 22000,
             "y": y, "die": die, "io": "INPUT", "hbt": False},
            {"inst": "far_" + name + "_" + die, "pin": "A", "x": 140000,
             "y": y, "die": die, "io": "INPUT", "hbt": False},
        ],
    }


def manifest(nets=None):
    return {
        "dbu_per_micron": 1000,
        "manufacturing_grid": 5,
        "die_area": [0, 0, 200000, 200000],
        "hbt_master_size": [1000, 1000],
        # Existing origins have the nonzero pitch residue (6400, 12800).
        "hbts": [{"name": "HBT_legacy", "x": 6900, "y": 13300}],
        "nets": nets if nets is not None else [signal_net()],
    }


PERMISSIVE = {"min_score": -1000.0}


class MlsPlannerTest(unittest.TestCase):
    def assert_contract(self, design, result):
        """Check the contract independently, including directed signal flow."""
        originals = {net["name"]: net for net in design["nets"]}
        original_positions = [(h["x"], h["y"]) for h in design["hbts"]]
        added_positions = []
        all_names = {h["name"] for h in design["hbts"]}
        for entry in result["selected"]:
            original = originals[entry["original"]]
            self.assertEqual(len(entry["subnets"]), 3)
            self.assertEqual(len(entry["hbts"]), 2)
            hnames = {h["name"] for h in entry["hbts"]}
            actual = Counter((p["inst"], p["pin"])
                             for s in entry["subnets"] for p in s["pins"]
                             if p["inst"] not in hnames)
            expected = Counter((p["inst"], p["pin"]) for p in original["pins"])
            self.assertEqual(actual, expected)
            subnets = {s["name"]: s for s in entry["subnets"]}
            self.assertEqual(len(subnets), 3)
            original_pins = {(p["inst"], p["pin"]): p for p in original["pins"]}
            ids = set()
            hbt_endpoints = defaultdict(list)
            for subnet in entry["subnets"]:
                match = re.fullmatch(re.escape(original["name"])
                                     + r"__MLS__S(\d+)__(BOT|TOP)", subnet["name"])
                self.assertIsNotNone(match)
                ids.add(int(match[1]))
                self.assertEqual(subnet["die"], "bottom" if match[2] == "BOT" else "upper")
                self.assertGreaterEqual(len(subnet["pins"]), 2)
                for pin in subnet["pins"]:
                    key = (pin["inst"], pin["pin"])
                    if pin["inst"] in hnames:
                        hbt_endpoints[pin["inst"]].append((subnet["name"], pin["pin"]))
                        self.assertEqual(pin["pin"], match[2])
                    else:
                        self.assertEqual(original_pins[key]["die"], subnet["die"])
            self.assertEqual(len(ids), 3)
            adjacency = defaultdict(set)
            directed = defaultdict(list)
            indegree = Counter()
            for hbt in entry["hbts"]:
                self.assertRegex(hbt["name"], r"^LS_HBT_\d+$")
                self.assertNotIn(hbt["name"], all_names)
                all_names.add(hbt["name"])
                endpoints = hbt_endpoints[hbt["name"]]
                self.assertEqual(len(endpoints), 2)
                self.assertEqual({pin for _, pin in endpoints}, {"BOT", "TOP"})
                endpoint_map = dict(endpoints)
                source, target = hbt["from_subnet"], hbt["to_subnet"]
                self.assertEqual({source, target}, set(endpoint_map))
                source_pin = "BOT" if hbt["master"] == "HBT_BOTIN" else "TOP"
                self.assertIn(hbt["master"], ("HBT_BOTIN", "HBT_TOPIN"))
                self.assertEqual(endpoint_map[source], source_pin)
                self.assertNotEqual(endpoint_map[target], source_pin)
                adjacency[source].add(target)
                adjacency[target].add(source)
                directed[source].append(target)
                indegree[target] += 1
                self.assertEqual(hbt["origin_x"], hbt["x"] - 500)
                self.assertEqual(hbt["origin_y"], hbt["y"] - 500)
                for axis, lower, upper in (("x", design["die_area"][0], design["die_area"][2]),
                                           ("y", design["die_area"][1], design["die_area"][3])):
                    origin = hbt["origin_" + axis]
                    self.assertGreaterEqual(origin, lower)
                    self.assertLessEqual(origin + 1000, upper)
                    self.assertEqual(origin % design["manufacturing_grid"], 0)
                    reference_origin = design["hbts"][0][axis] - 500
                    self.assertEqual(origin % 6400, reference_origin % 6400)
                added_positions.append((hbt["x"], hbt["y"]))
            driver = next(p for p in original["pins"] if p["io"] == "OUTPUT")
            driver_key = {"inst": driver["inst"], "pin": driver["pin"]}
            source = next(s["name"] for s in entry["subnets"] if driver_key in s["pins"])
            self.assertEqual(indegree[source], 0)
            reached, pending = set(), [source]
            while pending:
                node = pending.pop()
                if node not in reached:
                    reached.add(node)
                    pending.extend(directed[node])
            self.assertEqual(reached, set(subnets))
        for a, b in itertools.combinations(original_positions + added_positions, 2):
            self.assertTrue(abs(a[0] - b[0]) >= 6400 or abs(a[1] - b[1]) >= 6400)
        self.assertEqual(result["stats"]["new_hbts"], len(added_positions))
        self.assertLessEqual(len(added_positions), result["stats"]["new_hbt_budget"])
        if added_positions:
            self.assertLessEqual(len(design["hbts"]) + len(added_positions),
                                 result["stats"]["hbt_limit"])

    def test_bottom_and_upper_round_trip_preserve_pins_and_driver(self):
        for die in ("bottom", "upper"):
            with self.subTest(die=die):
                design = manifest([signal_net(die=die)])
                result = plan_design(design, PERMISSIVE)
                self.assertEqual(len(result["selected"]), 1)
                self.assert_contract(design, result)
                expected = ("HBT_BOTIN", "HBT_TOPIN") if die == "bottom" else ("HBT_TOPIN", "HBT_BOTIN")
                self.assertEqual(tuple(h["master"] for h in result["selected"][0]["hbts"]), expected)

    def test_deterministic_and_does_not_change_input_placement_or_nets(self):
        design = manifest([signal_net("a", y=25000), signal_net("b", y=65000)])
        before = copy.deepcopy(design)
        first = plan_design(design, PERMISSIVE)
        self.assertEqual(first, plan_design(design, PERMISSIVE))
        self.assertEqual(design, before)
        self.assertEqual(len(first["selected"]), 2)
        self.assert_contract(design, first)

    def test_preserves_nonzero_reference_origin_lattice(self):
        design = manifest()
        design["hbts"] = [{"name": "HBT_0", "x": 2500, "y": 3700},
                          {"name": "HBT_1", "x": 8900, "y": 10100}]
        result = plan_design(design, PERMISSIVE)
        self.assertEqual(len(result["selected"]), 1)
        self.assert_contract(design, result)
        for hbt in result["selected"][0]["hbts"]:
            self.assertEqual(hbt["origin_x"] % 6400, 2000)
            self.assertEqual(hbt["origin_y"] % 6400, 3200)

    def test_existing_hbt_names_and_subnet_names_do_not_collide(self):
        design = manifest()
        design["hbts"][0]["name"] = "LS_HBT_0"
        result = plan_design(design, PERMISSIVE)
        self.assertEqual(len(result["selected"]), 1)
        self.assert_contract(design, result)
        collision = {"name": "data[3]__MLS__S1__TOP", "pins": [], "signal_type": "SIGNAL"}
        design["nets"].append(collision)
        self.assertEqual(plan_design(design, PERMISSIVE)["selected"], [])

    def test_unsupported_nets_are_excluded(self):
        mutations = {
            "clock": lambda n: n.update(signal_type="CLOCK"),
            "power": lambda n: n.update(signal_type="POWER"),
            "ground": lambda n: n.update(signal_type="GROUND"),
            "special": lambda n: n.update(special=True),
            "mixed_dies": lambda n: n["pins"][1].update(die="upper"),
            "unknown_die": lambda n: n["pins"][1].update(die=None),
            "package_pin": lambda n: n["pins"][1].update(inst="PIN"),
            "hbt_pin": lambda n: n["pins"][1].update(hbt=True),
            "hbt_name": lambda n: n["pins"][1].update(inst="HBT_any"),
            "mls_hbt_name": lambda n: n["pins"][1].update(inst="LS_HBT_42"),
            "two_drivers": lambda n: n["pins"][1].update(io="OUTPUT"),
            "no_driver": lambda n: n["pins"][0].update(io="INPUT"),
            "inout": lambda n: n["pins"][1].update(io="INOUT"),
            "unknown_io": lambda n: n["pins"][1].update(io="UNKNOWN"),
            "existing_bottom": lambda n: n.update(name="data_BOT"),
            "existing_top": lambda n: n.update(name="data_TOP"),
            "already_mls": lambda n: n.update(name="data__MLS__S0__BOT"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                net = signal_net()
                mutate(net)
                self.assertEqual(plan_design(manifest([net]), PERMISSIVE)["selected"], [])

    def test_small_span_and_high_fanout_are_excluded(self):
        net = signal_net()
        for pin in net["pins"]:
            pin["x"] = 20000
        self.assertEqual(plan_design(manifest([net]), PERMISSIVE)["selected"], [])
        self.assertEqual(plan_design(manifest(), {**PERMISSIVE, "max_fanout": 2})["selected"], [])

    def test_missing_nearby_sites_does_not_emit_partial_family(self):
        design = manifest()
        design["hbts"] = [{"name": "HBT_0", "x": 19700, "y": 26100},
                          {"name": "HBT_1", "x": 141300, "y": 26100}]
        result = plan_design(design, {**PERMISSIVE, "search_radius": 0})
        self.assertEqual(result["selected"], [])
        self.assertEqual(result["stats"]["new_hbts"], 0)
        self.assertEqual(result["stats"]["skipped"].get("no_legal_site"), 1)

    def test_budget_requires_two_available_hbts(self):
        design = manifest([signal_net("a"), signal_net("b", y=75000)])
        for overrides, expected in (({"max_new_hbts": 1}, 0),
                                    ({"max_new_hbts": 3}, 1),
                                    ({"max_shared_nets": 1}, 1),
                                    ({"capacity_fraction": 0.0}, 0),
                                    ({"enabled": False}, 0)):
            with self.subTest(overrides=overrides):
                result = plan_design(design, {**PERMISSIVE, **overrides})
                self.assertEqual(len(result["selected"]), expected)
                self.assert_contract(design, result)

    def test_thirty_percent_limit_includes_existing_hbts(self):
        design = manifest()
        design["die_area"] = [0, 0, 64000, 64000]
        design["hbts"] = [{"name": f"HBT_{i}", "x": 500 + (i % 10) * 6400,
                          "y": 500 + (i // 10) * 6400} for i in range(29)]
        result = plan_design(design, PERMISSIVE)
        self.assertEqual(result["stats"]["capacity"], 100)
        self.assertEqual(result["stats"]["hbt_limit"], 30)
        self.assertEqual(result["stats"]["new_hbt_budget"], 1)
        self.assertEqual(result["selected"], [])

    def test_timing_guard_respects_provided_slack(self):
        design = manifest()
        for slack in (-0.1, float("nan"), float("inf")):
            with self.subTest(slack=slack):
                design["nets"][0]["slack_ns"] = slack
                result = plan_design(design, PERMISSIVE)
                self.assertEqual(result["selected"], [])
                self.assertEqual(result["stats"]["timing_source"], "provided_slack")
        design["nets"][0]["slack_ns"] = 0.2
        self.assertEqual(len(plan_design(design, PERMISSIVE)["selected"]), 1)
        self.assertEqual(plan_design(design, {**PERMISSIVE, "min_slack_ns": 0.3})["selected"], [])

    def test_inconsistent_reference_lattice_is_rejected(self):
        design = manifest()
        design["hbts"].append({"name": "HBT_bad", "x": 14000, "y": 13300})
        with self.assertRaisesRegex(ValueError, "pitch lattice"):
            plan_design(design, PERMISSIVE)

    def test_demand_updates_match_rebuilt_grid(self):
        design = manifest([signal_net("a"), signal_net("b", y=65000)])
        demand = DemandGrid(design["die_area"], 16, design["nets"], 1000)
        moved = copy.deepcopy(design["nets"][0])
        demand.adjust("bottom", moved["pins"], -1, 1000)
        for pin in moved["pins"]:
            pin["die"] = "upper"
        demand.adjust("upper", moved["pins"], 1, 1000)
        rebuilt = DemandGrid(design["die_area"], 16, [moved, design["nets"][1]], 1000)
        for die in ("bottom", "upper"):
            for bounds in ([0, 0, 200000, 200000], [10000, 20000, 50000, 80000],
                           [50000, 10000, 150000, 35000]):
                self.assertAlmostEqual(demand.mean(die, bounds), rebuilt.mean(die, bounds))

    def test_joint_placement_reduces_chain_detour(self):
        design = manifest()
        net = signal_net()
        # The near group has a wide flat bbox optimum. Moving its HBT toward
        # the second group avoids unnecessary travel back to the median.
        net["pins"][1]["x"] = 100000
        a, b = net["pins"][:2], net["pins"][2:]
        sites = HbtSites(design["die_area"], [1000, 1000], 6400, 5, design["hbts"])
        old = place_pair(sites, a, b, (20000, 25000), (140000, 25000), 8, False)
        new = place_pair(sites, a, b, (20000, 25000), (140000, 25000), 8, True)
        def chain(points):
            p0, p1 = points
            return (hpwl(a + [{"x": p0[0], "y": p0[1]}]) +
                    abs(p0[0] - p1[0]) + abs(p0[1] - p1[1]) +
                    hpwl(b + [{"x": p1[0], "y": p1[1]}]))
        self.assertLess(chain(new), chain(old))
        self.assertTrue(sites.legal(new[1], [new[0]]))

    def test_configuration_cannot_weaken_pitch_or_capacity(self):
        for overrides in ({"pitch_um": 3.2}, {"capacity_fraction": 0.31},
                          {"max_new_hbts": -1}, {"enabled": "false"},
                          {"unknown_key": 1}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    plan_design(manifest(), overrides)

    @unittest.skipUnless(shutil.which("tclsh"), "Tcl interpreter is unavailable")
    def test_manifest_json_encoder_preserves_names_and_all_control_bytes(self):
        definitions = (SCRIPT_DIR / "prepare_mls.tcl").read_text().rsplit("mls_prepare::run", 1)[0]
        names = ['icache_1/_21919_', 'data[3]$name"\\next',
                 ''.join(chr(i) for i in range(32)), '层共享/信号']
        script = definitions + "\n"
        for name in names:
            script += 'set value [encoding convertfrom utf-8 [binary decode hex ' + name.encode().hex() + ']]\n'
            script += 'puts [mls_prepare::json_string $value]\n'
        result = subprocess.run([shutil.which("tclsh")], input=script, text=True,
                                capture_output=True, check=True)
        self.assertEqual([json.loads(line) for line in result.stdout.splitlines()], names)

    @unittest.skipUnless(shutil.which("tclsh"), "Tcl interpreter is unavailable")
    def test_tcl_names_are_data_and_do_not_execute_substitutions(self):
        value = 'data[3]$secret\\path"; [set injected 1]\nnext'
        script = "set injected 0\nset captured " + tcl_word(value) + "\n"
        script += "puts [binary encode hex [encoding convertto utf-8 $captured]]\nputs $injected\n"
        result = subprocess.run([shutil.which("tclsh")], input=script, text=True,
                                capture_output=True, check=True)
        lines = result.stdout.splitlines()
        self.assertEqual(lines, [value.encode("utf-8").hex(), "0"])


if __name__ == "__main__":
    unittest.main()
