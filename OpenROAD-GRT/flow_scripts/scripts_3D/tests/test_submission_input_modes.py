#!/usr/bin/env python3
"""Exercise direct-input guards and the real Tcl collateral loading contract."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[4]
SUBMISSION = REPOSITORY / "submission"


class SubmissionInputModeTest(unittest.TestCase):
    def test_invalid_modes_fail_before_any_input_or_build_access(self) -> None:
        cases = [
            ({"GRT_PROCESS_MODE": "typo"}, "GRT_PROCESS_MODE must be"),
            ({"GRT_INPUT_MODE": "typo"}, "GRT_INPUT_MODE must be"),
            ({"GRT_PROCESS_MODE": "isolated", "GRT_INPUT_MODE": "def"},
             "Direct DEF input requires"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes):
                environment = dict(os.environ, GRT_PROCESS_MODE="single", GRT_INPUT_MODE="auto")
                environment.update(changes)
                result = subprocess.run([
                    sys.executable, str(SUBMISSION / "src/run_router.py"),
                    "/nonexistent_input", "/nonexistent_output", "/nonexistent_platform", "1",
                ], env=environment, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)
                self.assertNotIn("Traceback", result.stderr)


@unittest.skipUnless(shutil.which("tclsh"), "Tcl interpreter unavailable")
class DirectLoaderContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.loader = self.root / "load.tcl"
        shutil.copy2(SUBMISSION / "support/load.tcl", self.loader)
        shutil.copy2(REPOSITORY / "OpenROAD-3D/flow/scripts/sdc_compat.tcl",
                     self.root / "sdc_compat.tcl")
        self.collateral = self.root / "collateral.tcl"
        self.collateral.write_text(
            "set submission_libs [list a.lib {b library.lib}]\n"
            "set submission_lefs [list tech.lef {normal cells.lef}]\n")
        (self.root / "derate.tcl").write_text("lappend ::calls derate\n")
        (self.root / "setRC.tcl").write_text("lappend ::calls rc\n")

    def invoke(self, design: str, *, clamp: bool = True) -> subprocess.CompletedProcess[str]:
        script = """set calls {}
proc set_thread_count {count} {lappend ::calls [list threads $count]}
foreach name {read_liberty read_lef read_def read_db read_sdc} {
  proc $name {args} "lappend ::calls \[list $name {*}\$args\]"
}
proc get_ports {args} {}
namespace eval sta {proc get_ports {args} {}}
"""
        if clamp:
            script += "proc set_net_routing_layers {args} {}\n"
        script += """source $::env(TEST_LOADER)
if {[catch {load_design $::env(TEST_DESIGN) 4_cts.sdc test} message]} {
  puts stderr $message
  puts [join $::calls "\n"]
  exit 1
}
puts [join $::calls "\n"]
"""
        environment = dict(os.environ, NUM_CORES="1", TEST_LOADER=str(self.loader),
                           TEST_DESIGN=design, SUBMISSION_COLLATERAL_TCL=str(self.collateral),
                           RESULTS_DIR="/fixture/results", PLATFORM_DIR=str(self.root))
        return subprocess.run(["tclsh"], input=script, env=environment,
                              capture_output=True, text=True, check=False)

    def test_def_path_loads_exact_collateral_sdc_derate_and_rc_in_order(self) -> None:
        result = self.invoke("4_1_cts.def")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "SUBMISSION_LAYER_CLAMP_READY", "threads 1", "read_liberty a.lib",
            "read_liberty {b library.lib}", "read_lef tech.lef",
            "read_lef {normal cells.lef}", "read_def /fixture/results/4_1_cts.def",
            "read_sdc /fixture/results/4_cts.sdc", "derate", "rc",
        ])

    def test_odb_fallback_preserves_original_collateral_sdc_derate_and_rc(self) -> None:
        result = self.invoke("4_cts.odb")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "SUBMISSION_LAYER_CLAMP_READY", "threads 1", "read_liberty a.lib",
            "read_liberty {b library.lib}", "read_db /fixture/results/4_cts.odb",
            "read_sdc /fixture/results/4_cts.sdc", "derate", "rc",
        ])

    def test_missing_hard_layer_clamp_aborts_before_loading_design(self) -> None:
        result = self.invoke("4_1_cts.def", clamp=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Required set_net_routing_layers is unavailable", result.stderr)
        self.assertEqual(result.stdout, "threads 1\n")


if __name__ == "__main__":
    unittest.main()
