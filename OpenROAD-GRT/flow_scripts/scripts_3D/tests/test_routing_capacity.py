#!/usr/bin/env python3
"""Run the shipped Tcl parser and routing entry points with OpenDB stubs."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
TECH_STUB = r'''
namespace eval ord {proc get_db_tech {} {return tech}}
proc tech {method name} {
  if {$name eq "via2"} {return cut}
  if {![regexp {^metal([1-9][0-9]*)$} $name -> level] || $level > 20} {return NULL}
  return layer$level
}
proc cut {method} {return CUT}
proc layer {level method} {
  switch -- $method {
    getRoutingLevel {return $level}
    getName {return metal$level}
    getType {return ROUTING}
    default {error "Unexpected layer method $method"}
  }
}
for {set i 1} {$i <= 20} {incr i} {interp alias {} layer$i {} layer $i}
proc set_global_routing_layer_adjustment {args} {puts "ADJUST $args"}
proc set_routing_layers {args} {puts "WINDOW $args"}
'''


@unittest.skipUnless(shutil.which("tclsh"), "Tcl interpreter unavailable")
class RoutingCapacityTest(unittest.TestCase):
    def invoke(self, body, spec=None, prefix=TECH_STUB, env=None):
        environment = dict(os.environ)
        environment.pop("GRT_LAYER_ADJUSTMENTS", None)
        environment.pop("MACRO_EXTENSION", None)
        if spec is not None:
            environment["GRT_LAYER_ADJUSTMENTS"] = spec
        if env:
            environment.update(env)
        program = prefix + (SCRIPT_DIR / "routing_capacity.tcl").read_text()
        program += "\nif {[catch {\n" + body + "\n} message]} {puts stderr $message; exit 1}\n"
        return subprocess.run(["tclsh"], input=program, env=environment, text=True,
                              capture_output=True, check=False)

    def test_missing_or_blank_spec_does_not_query_database_or_change_settings(self):
        for spec in (None, "", " \t "):
            with self.subTest(spec=spec):
                result = self.invoke("grt_capacity::apply metal2 metal10", spec, prefix="")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_overrides_replace_uniform_after_window_and_only_current_die(self):
        result = self.invoke('''
set_routing_layers -signal metal2-metal10
set_global_routing_layer_adjustment metal2-metal10 0.5
grt_capacity::apply metal2 metal10
''', "metal12=0.9, metal3 = .60,metal2=7e-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "WINDOW -signal metal2-metal10", "ADJUST metal2-metal10 0.5",
            "ADJUST metal2 0.7", "GRT_CAPACITY layer=metal2 adjustment=0.7 die=metal2-metal10",
            "ADJUST metal3 0.6", "GRT_CAPACITY layer=metal3 adjustment=0.6 die=metal2-metal10",
        ])

    def test_upper_pass_does_not_apply_bottom_overrides(self):
        result = self.invoke("grt_capacity::apply metal11 metal20", "metal2=0.7,metal12=0.9")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ADJUST metal2", result.stdout)
        self.assertIn("GRT_CAPACITY layer=metal12 adjustment=0.9 die=metal11-metal20", result.stdout)

    def test_valid_other_die_entry_is_silent(self):
        result = self.invoke("grt_capacity::apply metal2 metal10", "metal11=0.9")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_zero_and_complete_reduction_follow_native_endpoints(self):
        result = self.invoke("grt_capacity::apply metal2 metal10", "metal2=0,metal3=1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ADJUST metal2 0.0", result.stdout)
        self.assertIn("ADJUST metal3 1.0", result.stdout)

    def test_invalid_values_fail_before_any_override(self):
        for value in ("NaN", "Inf", "-Inf", "1e999", "-0.01", "1.01", "0.5+0.1", "0x1"):
            with self.subTest(value=value):
                result = self.invoke("grt_capacity::apply metal2 metal10", f"metal2=0.7,metal3={value}")
                self.assertEqual(result.returncode, 1)
                self.assertIn("finite and in [0,1]", result.stderr)
                self.assertNotIn("ADJUST", result.stdout)

    def test_unknown_nonrouting_and_range_names_fail_even_outside_current_die(self):
        for name in ("metal99", "via2", "metal2-metal3", "imaginary"):
            with self.subTest(name=name):
                result = self.invoke("grt_capacity::apply metal11 metal20", f"metal2=0.7,{name}=0.6")
                self.assertEqual(result.returncode, 1)
                self.assertIn("unknown routing layer", result.stderr)
                self.assertNotIn("ADJUST", result.stdout)

    def test_duplicate_and_malformed_entries_fail_atomically(self):
        for spec in ("metal2=0.7,metal2=0.6", "metal2=0.7,", ",metal2=0.7",
                     "metal2", "metal2=", "=0.7", "metal2=0.7=0.8"):
            with self.subTest(spec=spec):
                result = self.invoke("grt_capacity::apply metal2 metal10", spec)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn("ADJUST", result.stdout)

    def test_invalid_pass_window_aborts(self):
        for window in ("metal10 metal2", "imaginary metal10", "metal2 via2"):
            with self.subTest(window=window):
                result = self.invoke(f"grt_capacity::apply {window}", "metal2=0.7")
                self.assertEqual(result.returncode, 1)
                self.assertIn("Invalid routing capacity die window", result.stderr)
                self.assertNotIn("ADJUST", result.stdout)

    def test_isolated_configure_calls_same_overrides_after_active_window(self):
        for filename in ("global_route_single_pass.tcl", "global_route_die_by_die.tcl"):
            with self.subTest(filename=filename):
                source = (SCRIPT_DIR / filename).read_text()
                begin = source.index("proc configure_die_routing_layers {")
                end = source.index("\nproc read_net_list", begin)
                body = source[begin:end] + "\nconfigure_die_routing_layers metal2 metal10"
                result = self.invoke(body, "metal2=0.7,metal12=0.9")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertLess(result.stdout.index("WINDOW"), result.stdout.index("ADJUST metal2 0.7"))
                self.assertNotIn("ADJUST metal12", result.stdout)

    def test_isolated_empty_single_pass_skips_routing_and_capacity_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "load.tcl").write_text("")
            (directory / "nets.txt").write_text("")
            env = {"SCRIPTS_DIR": temp, "REPORTS_DIR": temp,
                   "GRT_PASS_NET_LIST": str(directory / "nets.txt"),
                   "GRT_PASS_GUIDE_OUT": str(directory / "empty.guide"),
                   "GRT_PASS_MIN_LAYER": "metal2", "GRT_PASS_MAX_LAYER": "metal10"}
            prefix = '''
namespace eval utl {proc set_metrics_stage {args} {}}
proc load_design {args} {}
proc global_route {args} {error "Empty queue reached router"}
'''
            result = self.invoke(f"source {{{SCRIPT_DIR / 'global_route_single_pass.tcl'}}}",
                                 "metal2=0.7", prefix=prefix, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((directory / "empty.guide").read_bytes(), b"")
            self.assertEqual((directory / "congestion_upper.rpt").read_bytes(), b"")
            self.assertNotIn("GRT_CAPACITY", result.stdout)

    def test_isolated_empty_upper_pass_does_not_launch_subprocess(self):
        source = (SCRIPT_DIR / "global_route_die_by_die.tcl").read_text()
        begin = source.index("proc route_pass_subprocess {")
        end = source.index("\nproc merge_route_guide_files", begin)
        with tempfile.TemporaryDirectory() as temp:
            guide = Path(temp) / "empty.guide"
            body = source[begin:end] + f"\nroute_pass_subprocess unused {{{guide}}} metal11 metal20 upper"
            result = self.invoke(body, "metal12=0.9", prefix="proc read_net_list {path} {return {}}\n",
                                 env={"REPORTS_DIR": temp})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(guide.read_bytes(), b"")
            self.assertEqual((Path(temp) / "congestion_upper.rpt").read_bytes(), b"")
            self.assertNotIn("GRT_CAPACITY", result.stdout)


if __name__ == "__main__":
    unittest.main()
