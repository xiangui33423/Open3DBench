#!/usr/bin/env python3
"""An empty die queue must not trigger OpenROAD's implicit all-net routing."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("tclsh"), "Tcl interpreter is unavailable")
class EmptyDieTest(unittest.TestCase):
    def test_empty_die_publishes_empty_pass_without_invoking_router(self):
        source = (SCRIPT_DIR / "global_route_single_process.tcl").read_text()
        start = source.index("proc fused_route_pass ")
        stop = source.index("\nset fused_bottom ", start)
        procedure = source[start:stop]
        with tempfile.TemporaryDirectory() as directory:
            guide = Path(directory) / "pass.guide"
            report = Path(directory) / "congestion.rpt"
            # No geometry/layer setup is permitted for an empty pass either.
            script = 'proc unknown {args} {error "Unexpected OpenROAD call: $args"}\n'
            script += procedure + '\n'
            script += f'fused_route_pass {{}} metal2 metal10 {{{guide}}} {{{report}}}\nputs EMPTY_PASS_READY\n'
            result = subprocess.run([shutil.which("tclsh")], input=script, text=True,
                                    capture_output=True, check=True)
            self.assertEqual(result.stdout.strip(), "EMPTY_PASS_READY")
            self.assertEqual(result.stderr, "")
            self.assertTrue(guide.is_file())
            self.assertTrue(report.is_file())
            self.assertEqual(guide.read_bytes(), b"")
            self.assertEqual(report.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
