#!/usr/bin/env python3
"""Ensure concurrent checks retain both real validators and their failures."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]


class ParallelGuideChecksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # The strict diagnostic resolves its matching log from a results path.
        self.results = Path(self.temp.name) / "results"
        self.results.mkdir()
        self.def_path = self.results / "design.def"
        self.def_path.write_text("""COMPONENTS 2 ;
- HBT_one HBT_BOTIN + PLACED ( 10 10 ) N ;
- cell_bottom BUF_bottom + PLACED ( 10 10 ) N ;
END COMPONENTS
NETS 1 ;
- split_BOT ( HBT_one BOT ) ( cell_bottom A ) ;
END NETS
""", encoding="utf-8")
        self.guide = self.results / "route.guide"

    def run_both_modes(self, guide: str) -> list[subprocess.CompletedProcess[str]]:
        self.guide.write_text(guide, encoding="utf-8")
        environment = dict(os.environ)
        environment.pop("WORK_HOME", None)
        result = []
        for mode in ("serial", "parallel"):
            result.append(subprocess.run([
                sys.executable, str(SCRIPT_DIR / "validate_die_guides.py"),
                str(self.results), "--def-file", str(self.def_path), "--mode", mode,
            ], capture_output=True, text=True, env=environment, check=False))
        def report(text: str) -> str:
            return re.sub(r"^GRT_(?:STAGE|CHECK_MODE).*\n", "", text, flags=re.MULTILINE)
        self.assertEqual(result[0].returncode, result[1].returncode)
        self.assertEqual(report(result[0].stdout), report(result[1].stdout))
        self.assertEqual(result[0].stderr, result[1].stderr)
        for completed in result:
            self.assertIn("GRT_STAGE check_guide_layers_ms=", completed.stdout)
            self.assertIn("GRT_STAGE check_guide_connectivity_ms=", completed.stdout)
            self.assertIn("GRT_STAGE check_guides_ms=", completed.stdout)
        return result

    def test_both_validators_pass(self) -> None:
        for result in self.run_both_modes("split_BOT\n(\n0 0 100 100 metal10\n)\n"):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PASS: no cross-die", result.stdout)
            self.assertIn("STRICT PASS", result.stdout)

    def test_layer_failure_still_runs_strict_check_and_propagates_both_failures(self) -> None:
        for result in self.run_both_modes("split_BOT\n(\n0 0 100 100 metal11\n)\n"):
            self.assertEqual(result.returncode, 1)
            self.assertIn("FAIL: 1 nets", result.stdout)
            self.assertIn("STRICT FAIL: 1 HBT", result.stdout)
            self.assertIn("check_guide_layers failed", result.stderr)
            self.assertIn("check_guide_connectivity failed", result.stderr)

    def test_connectivity_failure_cannot_be_hidden_by_layer_success(self) -> None:
        for result in self.run_both_modes("split_BOT\n(\n10000 10000 11000 11000 metal10\n)\n"):
            self.assertEqual(result.returncode, 1)
            self.assertIn("PASS: no cross-die", result.stdout)
            self.assertIn("STRICT FAIL", result.stdout)
            self.assertNotIn("check_guide_layers failed", result.stderr)
            self.assertIn("check_guide_connectivity failed", result.stderr)

    def test_single_core_budget_uses_serial_even_if_parallel_requested(self) -> None:
        self.guide.write_text("split_BOT\n(\n0 0 100 100 metal10\n)\n", encoding="utf-8")
        environment = dict(os.environ, NUM_CORES="1")
        environment.pop("WORK_HOME", None)
        result = subprocess.run([
            sys.executable, str(SCRIPT_DIR / "validate_die_guides.py"),
            str(self.results), "--def-file", str(self.def_path), "--mode", "parallel",
        ], capture_output=True, text=True, env=environment, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GRT_CHECK_MODE serial", result.stdout)
        self.assertNotIn("GRT_CHECK_MODE parallel", result.stdout)


if __name__ == "__main__":
    unittest.main()
