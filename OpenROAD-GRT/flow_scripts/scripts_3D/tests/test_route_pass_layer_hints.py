#!/usr/bin/env python3
"""Exercise the actual Tcl pass's hint clamps and protected-net guards."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("tclsh"), "Tcl is not installed")
class RoutePassLayerHintsTest(unittest.TestCase):
    def invoke(self, names, hints, *, interval=(2, 10), sigtype="SIGNAL", mterm="SIGNAL",
               policy="layers", resistance_api=True):
        source = (SCRIPT_DIR / "global_route_single_process.tcl").read_text()
        start = source.index("proc fused_route_pass {")
        stop = source.index("\nset fused_bottom [", start)
        function = source[start:stop]
        program = r'''
namespace eval ord {proc get_db_tech {} {return tech}}
namespace eval grt {proc add_net_to_route {net} {}}
proc set_routing_layers {args} {}
proc set_global_routing_layer_adjustment {args} {}
proc set_net_routing_layers {args} {puts "CLAMP $args"}
proc global_route {args} {puts ROUTED}
proc tech {method value} {
  if {$method eq "findLayer"} {
    if {![regexp {^metal([0-9]+)$} $value -> level] || $level < 1 || $level > 20} {
      return NULL
    }
  } else {set level $value}
  return layer$level
}
proc layer {level method} {
  if {$method eq "getRoutingLevel"} {return $level}
  if {$method eq "getName"} {return metal$level}
  error "Unexpected layer method $method"
}
for {set i 1} {$i <= 20} {incr i} {interp alias {} layer$i {} layer $i}
proc block {method name} {return net}
proc net {method} {
  if {$method eq "getSigType"} {return $::env(TEST_SIGTYPE)}
  if {$method eq "getITerms"} {return iterm}
  error "Unexpected net method $method"
}
proc iterm {method} {return mterm}
proc mterm {method} {return $::env(TEST_MTERM)}
set ::fused_block block
set ::fused_adjustment 0.5
set ::fused_args {}
set ::grt_layer_hints $::env(TEST_HINTS)
set ::fused_hints_policy $::env(TEST_POLICY)
if {$::env(TEST_RESISTANCE_API)} {
  proc grt::clear_net_resistance_aware {} {puts CLEAR_SELECTION}
  proc set_net_resistance_aware {name} {puts "SELECT $name"}
}
'''
        program += (SCRIPT_DIR / "routing_capacity.tcl").read_text()
        program += function
        program += r'''
if {[catch {
  fused_route_pass $::env(TEST_NAMES) $::env(TEST_MIN) $::env(TEST_MAX) \
    $::env(TEST_GUIDE) $::env(TEST_REPORT)
} message]} {puts stderr $message; exit 1}
'''
        with tempfile.TemporaryDirectory() as temp:
            guide, report = Path(temp) / "route.guide", Path(temp) / "congestion.rpt"
            environment = dict(os.environ, TEST_NAMES=" ".join(names), TEST_HINTS=hints,
                               TEST_SIGTYPE=sigtype, TEST_MTERM=mterm,
                               TEST_POLICY=policy, TEST_RESISTANCE_API=str(int(resistance_api)),
                               TEST_MIN=f"metal{interval[0]}", TEST_MAX=f"metal{interval[1]}",
                               TEST_GUIDE=str(guide), TEST_REPORT=str(report))
            environment.pop("MACRO_EXTENSION", None)
            environment.pop("GRT_LAYER_ADJUSTMENTS", None)
            result = subprocess.run(["tclsh"], input=program, env=environment,
                                    text=True, capture_output=True, check=False)
            empty_files = guide.exists() and report.exists() and not guide.read_bytes() and not report.read_bytes()
        return result, empty_files

    def test_hint_intersects_bottom_and_upper_die_bounds(self):
        for interval, hint, expected in [((2, 10), "metal4 metal20", "metal4 metal10"),
                                         ((11, 20), "metal1 metal17", "metal11 metal17")]:
            with self.subTest(interval=interval):
                result, _ = self.invoke(["ordinary"], f"ordinary {{{hint}}}", interval=interval)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"CLAMP ordinary {expected}\n", result.stdout)
                self.assertIn("GRT_LAYER_HINTS applied=1", result.stdout)

    def test_empty_hint_map_keeps_full_interval(self):
        result, _ = self.invoke(["ordinary"], "")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLAMP ordinary metal2 metal10\n", result.stdout)
        self.assertIn("GRT_LAYER_HINTS applied=0", result.stdout)

    def test_net_use_and_mterm_clock_power_ground_keep_full_interval(self):
        for sigtype, mterm in [("CLOCK", "SIGNAL"), ("POWER", "SIGNAL"),
                              ("GROUND", "SIGNAL"), ("SIGNAL", "CLOCK"),
                              ("SIGNAL", "POWER"), ("SIGNAL", "GROUND")]:
            with self.subTest(sigtype=sigtype, mterm=mterm):
                result, _ = self.invoke(["protected"], "protected {metal4 metal10}",
                                        sigtype=sigtype, mterm=mterm)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("CLAMP protected metal2 metal10\n", result.stdout)
                self.assertIn("GRT_LAYER_HINTS applied=0", result.stdout)

    def test_unknown_or_disjoint_layer_hint_aborts_before_routing(self):
        for hint, error in [("metal4 imaginary", "Unknown hinted routing layer"),
                            ("metal11 metal17", "no legal die layer")]:
            with self.subTest(hint=hint):
                result, _ = self.invoke(["ordinary"], f"ordinary {{{hint}}}")
                self.assertEqual(result.returncode, 1)
                self.assertIn(error, result.stderr)
                self.assertNotIn("ROUTED", result.stdout)

    def test_empty_pass_writes_empty_files_without_routing_all_nets(self):
        result, empty_files = self.invoke([], "unused {unknown unknown}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(empty_files)
        self.assertNotIn("CLAMP", result.stdout)
        self.assertNotIn("ROUTED", result.stdout)

    def test_resistance_policy_preserves_full_die_range(self):
        result, _ = self.invoke(["ordinary"], "ordinary {metal4 metal10}", policy="resistance")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.stdout.index("CLEAR_SELECTION"), result.stdout.index("SELECT ordinary"))
        self.assertIn("CLAMP ordinary metal2 metal10\n", result.stdout)
        self.assertIn("GRT_LAYER_HINTS applied=0", result.stdout)
        self.assertIn("GRT_RESISTANCE_HINTS applied=1", result.stdout)

    def test_unselected_second_die_clears_previous_selection(self):
        result, _ = self.invoke(["upper"], "bottom {metal4 metal10}",
                                interval=(11, 20), policy="resistance")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLEAR_SELECTION", result.stdout)
        self.assertNotIn("SELECT upper", result.stdout)
        self.assertIn("CLAMP upper metal11 metal20", result.stdout)
        self.assertIn("GRT_RESISTANCE_HINTS applied=0", result.stdout)

    def test_resistance_policy_protects_clock_and_power_pins(self):
        for sigtype, mterm in [("CLOCK", "SIGNAL"), ("SIGNAL", "CLOCK"),
                              ("SIGNAL", "POWER"), ("SIGNAL", "GROUND")]:
            with self.subTest(sigtype=sigtype, mterm=mterm):
                result, _ = self.invoke(["protected"], "protected {metal4 metal10}",
                                        sigtype=sigtype, mterm=mterm, policy="resistance")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("SELECT protected", result.stdout)
                self.assertIn("GRT_RESISTANCE_HINTS applied=0", result.stdout)

    def test_missing_resistance_api_fails_before_routing(self):
        result, _ = self.invoke(["ordinary"], "ordinary {metal4 metal10}",
                                policy="resistance", resistance_api=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires the matching submitted GRT binary", result.stderr)
        self.assertNotIn("ROUTED", result.stdout)


if __name__ == "__main__":
    unittest.main()
