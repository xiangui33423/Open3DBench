#!/usr/bin/env python3
"""Independent tests for monotonic, lattice-preserving HBT relocation."""

from __future__ import annotations

import copy
import itertools
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from hbt_optimizer import optimize_hbts


def pin(inst, name, x, y, die, hbt=False):
    return {"inst": inst, "pin": name, "x": x, "y": y,
            "die": die, "hbt": hbt, "io": "INPUT"}


def net(name, pins, **extra):
    return {"name": name, "pins": pins, "signal_type": "SIGNAL", "special": False, **extra}


def example():
    return {
        "dbu_per_micron": 1000, "manufacturing_grid": 5,
        "die_area": [0, 0, 200000, 200000], "hbt_master_size": [1000, 1000],
        "hbts": [{"name": "HBT_0", "x": 128500, "y": 128500}],
        "nets": [
            net("cross_BOT", [pin("driver_bottom", "Z", 20000, 20000, "bottom"),
                              pin("HBT_0", "BOT", 128500, 128500, "bottom", True)]),
            net("cross_TOP", [pin("sink_upper", "A", 26000, 26000, "upper"),
                              pin("HBT_0", "TOP", 128500, 128500, "upper", True)]),
        ],
    }


def total_hpwl(design):
    return sum(max(p[k] for p in n["pins"]) - min(p[k] for p in n["pins"])
               for n in design["nets"] if n["pins"] for k in ("x", "y"))


class HbtOptimizerTest(unittest.TestCase):
    def assert_preserved(self, before, after, relocations, stats):
        self.assertEqual({h["name"] for h in before["hbts"]}, {h["name"] for h in after["hbts"]})
        self.assertEqual(before["die_area"], after["die_area"])
        self.assertEqual(len(before["nets"]), len(after["nets"]))
        hnames = {h["name"] for h in before["hbts"]}
        by_name = {h["name"]: h for h in before["hbts"]}
        after_names = {h["name"]: h for h in after["hbts"]}
        for original, updated in zip(before["nets"], after["nets"]):
            self.assertEqual(original["name"], updated["name"])
            self.assertEqual(original["signal_type"], updated["signal_type"])
            self.assertEqual([(p["inst"], p["pin"]) for p in original["pins"]],
                             [(p["inst"], p["pin"]) for p in updated["pins"]])
            for p, q in zip(original["pins"], updated["pins"]):
                if p["inst"] not in hnames:
                    self.assertEqual(p, q)
                else:
                    name = p["inst"]
                    for axis in ("x", "y"):
                        self.assertEqual(q[axis] - p[axis], after_names[name][axis] - by_name[name][axis])
                    self.assertEqual({k: v for k, v in p.items() if k not in ("x", "y")},
                                     {k: v for k, v in q.items() if k not in ("x", "y")})
        self.assertLessEqual(total_hpwl(after), total_hpwl(before))
        self.assertAlmostEqual(stats["saved_hpwl_um"], (total_hpwl(before) - total_hpwl(after)) / 1000)
        self.assertEqual(stats["moved_hbts"], len(relocations))
        self.assertEqual(len({r["name"] for r in relocations}), len(relocations))
        for r in relocations:
            self.assertEqual(r["before_x"], by_name[r["name"]]["x"])
            self.assertEqual(r["before_y"], by_name[r["name"]]["y"])
            self.assertEqual(r["x"], after_names[r["name"]]["x"])
            self.assertEqual(r["y"], after_names[r["name"]]["y"])
            for axis, lo, hi in (("x", before["die_area"][0], before["die_area"][2]),
                                  ("y", before["die_area"][1], before["die_area"][3])):
                self.assertEqual(r["origin_" + axis], r[axis] - 500)
                self.assertEqual(r[axis] % 6400, by_name[r["name"]][axis] % 6400)
                self.assertEqual(r["origin_" + axis] % 5, 0)
                self.assertGreaterEqual(r["origin_" + axis], lo)
                self.assertLessEqual(r["origin_" + axis] + 1000, hi)
        for a, b in itertools.combinations(after["hbts"], 2):
            self.assertTrue(abs(a["x"] - b["x"]) >= 6400 or abs(a["y"] - b["y"]) >= 6400)

    def test_reduces_both_die_nets_preserving_all_other_state(self):
        design = example()
        untouched = copy.deepcopy(design)
        after, moves, stats = optimize_hbts(design)
        self.assertEqual(design, untouched)
        self.assertEqual(len(moves), 1)
        self.assertGreater(stats["saved_hpwl_um"], 400)
        self.assert_preserved(design, after, moves, stats)

    def test_copy_on_write_copies_incident_pins_and_shares_only_read_only_nets(self):
        design = example()
        design["nets"].append(net("local_BOT", [
            pin("local_driver", "Z", 40000, 40000, "bottom"),
            pin("local_sink", "A", 45000, 45000, "bottom")]))
        untouched = copy.deepcopy(design)
        after, moves, stats = optimize_hbts(design)
        self.assertEqual(design, untouched)
        self.assertIsNot(after, design)
        self.assertIsNot(after["hbts"], design["hbts"])
        self.assertIsNot(after["hbts"][0], design["hbts"][0])
        self.assertIsNot(after["nets"], design["nets"])
        self.assertIs(after["nets"][2], design["nets"][2])
        for before_net, after_net in zip(design["nets"][:2], after["nets"][:2]):
            self.assertIsNot(after_net, before_net)
            self.assertIsNot(after_net["pins"], before_net["pins"])
            for before_pin, after_pin in zip(before_net["pins"], after_net["pins"]):
                self.assertIsNot(after_pin, before_pin)
        self.assert_preserved(design, after, moves, stats)
        # Moving or changing any copied incident pin cannot write back into
        # the source, including the non-HBT pins copied alongside HBT pins.
        after["hbts"][0]["x"] += 1
        after["nets"][0]["pins"][0]["x"] += 1
        after["nets"][0]["pins"][1]["x"] += 1
        self.assertEqual(design, untouched)

    def test_occupied_optimal_site_is_avoided(self):
        design = example()
        design["hbts"].append({"name": "HBT_protected", "x": 26100, "y": 26100})
        after, moves, stats = optimize_hbts(design)
        self.assertEqual(after["hbts"][1], design["hbts"][1])
        self.assertNotEqual((moves[0]["x"], moves[0]["y"]), (26100, 26100))
        self.assert_preserved(design, after, moves, stats)

    def test_shared_hbt_net_uses_updated_coordinates_and_counts_hpwl_once(self):
        design = example()
        design["hbts"] = [{"name": "HBT_0", "x": 70900, "y": 102900},
                          {"name": "HBT_1", "x": 141300, "y": 38900}]
        design["nets"] = [
            net("source_BOT", [pin("driver_bottom", "Z", 20000, 20000, "bottom"),
                               pin("HBT_0", "BOT", 70900, 102900, "bottom", True)]),
            net("trunk_TOP", [pin("HBT_0", "TOP", 70900, 102900, "upper", True),
                              pin("HBT_1", "TOP", 141300, 38900, "upper", True)]),
            net("sink_BOT", [pin("HBT_1", "BOT", 141300, 38900, "bottom", True),
                             pin("sink_bottom", "A", 180000, 20000, "bottom")]),
        ]
        after, moves, stats = optimize_hbts(design, {"passes": 3})
        self.assertGreaterEqual(len(moves), 1)
        self.assertGreater(stats["saved_hpwl_um"], 100)
        self.assert_preserved(design, after, moves, stats)

    def test_clock_special_and_package_connections_protect_entire_hbt(self):
        for change in (lambda n: n.update(signal_type="CLOCK"),
                       lambda n: n.update(signal_type="POWER"),
                       lambda n: n.update(special=True),
                       lambda n: n.update(bterms=True),
                       lambda n: n["pins"][0].update(inst="PIN")):
            design = example()
            change(design["nets"][0])
            after, moves, stats = optimize_hbts(design)
            self.assertEqual(after, design)
            self.assertEqual(moves, [])
            self.assertEqual(stats["eligible_hbts"], 0)

    def test_optimal_flat_region_and_minimum_improvement_prevent_spurious_moves(self):
        design = example()
        design["nets"][0]["pins"][0].update(x=10000, y=10000)
        design["nets"][1]["pins"][0].update(x=180000, y=180000)
        after, moves, stats = optimize_hbts(design)
        self.assertEqual(after, design)
        self.assertEqual(moves, [])
        self.assertEqual(stats["saved_hpwl_um"], 0)
        self.assertEqual(optimize_hbts(example(), {"min_improvement_um": 1000})[1], [])

    def test_preserves_offsets_of_every_connected_hbt_pin(self):
        design = example()
        design["nets"][0]["pins"][1]["x"] += 50
        design["nets"][1]["pins"][1]["y"] -= 100
        after, moves, stats = optimize_hbts(design)
        self.assertGreater(len(moves), 0)
        self.assert_preserved(design, after, moves, stats)

    def test_disabled_empty_and_move_budget(self):
        for config in ({"enabled": False}, {"passes": 0}, {"max_moves": 0}):
            after, moves, stats = optimize_hbts(example(), config)
            self.assertEqual(after, example())
            self.assertEqual(moves, [])
        empty = example()
        empty["hbts"] = []
        self.assertEqual(optimize_hbts(empty)[1], [])
        after, moves, stats = optimize_hbts(example(), {"max_moves": 1})
        self.assertEqual(stats["accepted_moves"], 1)
        self.assertEqual(len(moves), 1)
        self.assert_preserved(example(), after, moves, stats)

    def test_deterministic(self):
        self.assertEqual(optimize_hbts(example()), optimize_hbts(example()))

    def test_complete_path_guard_keeps_hpwl_gain_without_stretching_a_sink_path(self):
        design = example()
        design["hbts"][0].update(x=96500, y=96500)
        driver = pin("driver_bottom", "Z", 70000, 161000, "bottom")
        driver["io"] = "OUTPUT"
        design["nets"] = [
            net("cross_BOT", [driver,
                pin("local_bottom", "A", 149000, 43000, "bottom"),
                pin("HBT_0", "BOT", 96500, 96500, "bottom", True)]),
            net("cross_TOP", [pin("HBT_0", "TOP", 96500, 96500, "upper", True),
                pin("sink0_upper", "A", 104000, 164000, "upper"),
                pin("sink1_upper", "A", 131000, 170000, "upper"),
                pin("sink2_upper", "A", 158000, 26000, "upper")]),
        ]
        def paths(design):
            first, second = design["nets"]
            source = first["pins"][0]
            hin, hout = first["pins"][-1], second["pins"][0]
            dist = lambda a, b: abs(a["x"] - b["x"]) + abs(a["y"] - b["y"])
            return [dist(source, hin) + dist(hout, sink) for sink in second["pins"][1:]]
        original = paths(design)
        legacy, _moves, legacy_stats = optimize_hbts(design)
        self.assertTrue(any(a > b for a, b in zip(paths(legacy), original)))
        for reversed_hbt_io in (False, True):
            # Original public HBT master directions can disagree with their
            # ordinary terminals; the latter define the signal direction.
            if reversed_hbt_io:
                design["nets"][0]["pins"][-1]["io"] = "OUTPUT"
                design["nets"][1]["pins"][0]["io"] = "INPUT"
            guarded, moves, stats = optimize_hbts(design, {"path_max_growth_fraction": 0.0})
            self.assertTrue(all(a <= b for a, b in zip(paths(guarded), original)))
            self.assertEqual(stats["saved_hpwl_um"], legacy_stats["saved_hpwl_um"])
            self.assertEqual(stats["path_guard"]["guarded_paths"], 3)
            self.assertGreater(stats["path_guard"]["rejected_candidates"], 0)
            self.assert_preserved(design, guarded, moves, stats)

    def test_path_guard_protects_ambiguous_direction_and_shared_hbt_topology(self):
        design = example()  # The generic geometry fixture has no OUTPUT.
        result, moves, stats = optimize_hbts(design, {"path_max_growth_fraction": 0.0})
        self.assertEqual(result, design)
        self.assertEqual(moves, [])
        self.assertEqual(stats["skipped"]["ambiguous_cross_die_path"], 1)
        design["nets"][0]["pins"][0]["io"] = "OUTPUT"
        design["hbts"].append({"name": "HBT_extra", "x": 70900, "y": 70900})
        design["nets"][1]["pins"].append(pin("HBT_extra", "TOP", 70900, 70900, "upper", True))
        self.assertEqual(optimize_hbts(design, {"path_max_growth_fraction": 0.0})[1], [])

    def test_disabled_path_guard_retains_legacy_geometry(self):
        self.assertEqual(optimize_hbts(example()),
                         optimize_hbts(example(), {"path_max_growth_fraction": None,
                                                   "path_max_growth_um": 17.0}))

    @unittest.skipUnless(shutil.which("tclsh"), "Tcl interpreter is unavailable")
    def test_emitted_relocation_unlocks_cover_instance_before_moving(self):
        # OpenDB refuses setOrigin on COVER instances (ODB-0359). Exercise
        # the generated commands against that stateful contract, including
        # the final placement state, without requiring an OpenROAD install.
        from mls_planner import emit_tcl

        relocation = {"name": "HBT_0", "x": 26100, "y": 26100,
                      "origin_x": 25600, "origin_y": 25600,
                      "before_x": 128500, "before_y": 128500}
        commands = emit_tcl({"relocations": [relocation], "selected": [],
                             "stats": {"new_hbts": 0}})
        mock = """
set status COVER
set origin {128000 128000}
namespace eval ord {
  proc get_db_block {} { return mock_block }
  proc get_db {} { return mock_db }
}
proc mock_block {method args} {
  if {$method ne "findInst"} { error "Unexpected dbBlock mutation" }
  return mock_inst
}
proc mock_inst {method args} {
  global status origin
  switch -- $method {
    setPlacementStatus { set status [lindex $args 0] }
    setOrigin {
      if {$status eq "COVER" || $status eq "FIRM" || $status eq "LOCKED"} {
        error "ODB-0359: Cannot move a fixed instance"
      }
      set origin $args
    }
    setOrient { }
    default { error "Unexpected HBT connectivity/master mutation" }
  }
}
"""
        script = mock + "if {[catch {\n" + commands + "} message]} {puts stderr $message; exit 1}\n"
        script += 'puts "RESULT $status $origin"\n'
        result = subprocess.run([shutil.which("tclsh")], input=script, text=True,
                                capture_output=True, check=True)
        self.assertEqual(result.stderr, "")
        self.assertIn("RESULT FIRM 25600 25600", result.stdout)

    def test_invalid_lattices_and_configuration_fail_closed(self):
        design = example()
        design["hbts"].append({"name": "HBT_bad", "x": 11000, "y": 12000})
        with self.assertRaisesRegex(ValueError, "pitch lattice"):
            optimize_hbts(design)
        for config in ({"passes": -1}, {"max_moves": True}, {"enabled": "false"},
                       {"min_improvement_um": float("nan")}, {"unknown_key": 1},
                       {"path_max_growth_fraction": -0.1}, {"path_max_growth_fraction": True},
                       {"path_max_growth_um": float("inf")}, {"path_max_growth_um": None}):
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    optimize_hbts(example(), config)


if __name__ == "__main__":
    unittest.main()
