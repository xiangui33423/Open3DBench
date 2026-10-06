#!/usr/bin/env python3
"""Protected-net scan rules against actual Tcl and stateful native-API stubs.

Place in scripts_3D/tests for standard unittest discovery, or set
MLS_TEST_SCRIPT_DIR to check an isolated scripts_3D implementation.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT_DIR = Path(os.environ.get("MLS_TEST_SCRIPT_DIR", Path(__file__).resolve().parents[1]))
SOURCE = SCRIPT_DIR / "prepare_mls.tcl"


def tcl_text(value):
    return "[encoding convertfrom utf-8 [binary decode hex {" + value.encode().hex() + "}]]"


def actual_scan():
    source = SOURCE.read_text()
    definitions = source.rsplit("mls_prepare::run", 1)[0]
    start = source.index("    set protected_path ")
    stop = source.index("    close $protected_fp", start) + len("    close $protected_fp")
    # Keep the real scan in procedure scope, as in mls_prepare::run. Do not
    # reconstruct the protection algorithm in the fixture or cache expectations.
    return (definitions + "\nnamespace eval mls_prepare {\nproc extracted_scan {block} {\n"
            + source[start:stop] + "\n}\n}\n")


STUBS = r'''
set all_nets {}
set events {}
set sig_queries 0
set mterm_queries 0
set injected 0
array set net_types {}
array set net_special {}
array set net_names {}
array set net_pins {}
array set pin_mterms {}
array set mterm_types {}
proc block {method} {
  if {$method ne "getNets"} {error "Unexpected block write/read $method"}
  lappend ::events BLOCK_NETS
  return $::all_nets
}
proc net_stub {handle method} {
  lappend ::events [list $method $handle]
  switch -- $method {
    getSigType {return $::net_types($handle)}
    isSpecial {return $::net_special($handle)}
    getITerms {return $::net_pins($handle)}
    getName {return $::net_names($handle)}
    default {error "Unexpected net write/read $method"}
  }
}
proc iterm_stub {handle method} {
  if {$method ne "getMTerm"} {error "Unexpected ITerm write/read $method"}
  incr ::mterm_queries
  lappend ::events [list getMTerm $handle]
  set value $::pin_mterms($handle)
  if {$value eq "__GET_MTERM_ERROR__"} {error "injected getMTerm failure"}
  return $value
}
proc mterm_stub {handle method} {
  if {$method ne "getSigType"} {error "Unexpected MTerm write/read $method"}
  incr ::sig_queries
  lappend ::events [list MTERM_SIG $handle]
  set value $::mterm_types($handle)
  if {$value eq "__SIG_ERROR__"} {error "injected getSigType failure"}
  return $value
}
proc output_hex {} {
  set fp [open $::env(RESULTS_DIR)/mls_protected_nets.json rb]
  set data [read $fp]
  close $fp
  return [binary encode hex $data]
}
proc report {key value} {
  puts "$key [binary encode hex [encoding convertto utf-8 $value]]"
}
'''


def run_scan(nets, types, *, changed_types=None):
    setup = []
    for handle, kind in types.items():
        setup += [f"set handle {tcl_text(handle)}",
                  f"set mterm_types($handle) {tcl_text(kind)}",
                  "interp alias {} $handle {} mterm_stub $handle"]
    for index, net in enumerate(nets):
        handle = f"net_{index}"
        setup += [f"lappend all_nets {handle}",
                  f"set net_types({handle}) {tcl_text(net.get('sig', 'SIGNAL'))}",
                  f"set net_special({handle}) {int(net.get('special', False))}",
                  f"set net_names({handle}) {tcl_text(net.get('name', handle))}",
                  f"set net_pins({handle}) {{}}",
                  f"interp alias {{}} {handle} {{}} net_stub {handle}"]
        for pin_index, mterm in enumerate(net.get("terms", [])):
            pin = f"iterm_{index}_{pin_index}"
            setup += [f"lappend net_pins({handle}) {pin}",
                      f"set pin_mterms({pin}) {tcl_text(mterm)}",
                      f"interp alias {{}} {pin} {{}} iterm_stub {pin}"]
    body = """
set status [catch {mls_prepare::extracted_scan block} message]
report status $status
report message $message
report output_hex [output_hex]
report events [join $events "\n"]
report sig_queries $sig_queries
report mterm_queries $mterm_queries
report injected $injected
"""
    if changed_types is not None:
        for handle, kind in changed_types.items():
            body += f"set handle {tcl_text(handle)}\nset mterm_types($handle) {tcl_text(kind)}\n"
        body += """
set status2 [catch {mls_prepare::extracted_scan block} message2]
report status2 $status2
report output2_hex [output_hex]
report sig_queries2 $sig_queries
report mterm_queries2 $mterm_queries
"""
    with tempfile.TemporaryDirectory(prefix="protected-scan-test-") as directory:
        script = (actual_scan() + STUBS + "\n".join(setup)
                  + "\nset ::env(RESULTS_DIR) " + tcl_text(directory) + "\n" + body)
        result = subprocess.run([shutil.which("tclsh")], input=script, text=True,
                                capture_output=True, check=True)
        if result.stderr:
            raise AssertionError(result.stderr)
        return {key: bytes.fromhex(value).decode()
                for key, value in (line.split(" ", 1) for line in result.stdout.splitlines())}


@unittest.skipUnless(shutil.which("tclsh"), "Tcl interpreter unavailable")
class ProtectedMTermCacheTest(unittest.TestCase):
    def check_names(self, result, expected):
        self.assertEqual(result["status"], "0", result["message"])
        expected_bytes = (json.dumps(expected, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        self.assertEqual(bytes.fromhex(result["output_hex"]), expected_bytes)
        self.assertEqual(result["injected"], "0")

    def test_protected_terminal_types_and_net_short_circuits(self):
        nets = [{"name": kind.lower(), "terms": ["m_" + kind]}
                for kind in ("CLOCK", "POWER", "GROUND")]
        nets += [{"name": "reset-net", "sig": "RESET", "terms": ["__GET_MTERM_ERROR__"]},
                 {"name": "special-net", "special": True, "terms": ["__GET_MTERM_ERROR__"]},
                 {"name": "ordinary", "terms": ["m_" + kind for kind in
                                                 ("SIGNAL", "ANALOG", "RESET", "SCAN", "TIEOFF")]}]
        types = {"m_" + kind: kind for kind in
                 ("CLOCK", "POWER", "GROUND", "SIGNAL", "ANALOG", "RESET", "SCAN", "TIEOFF")}
        result = run_scan(nets, types)
        self.check_names(result, ["clock", "power", "ground", "reset-net", "special-net"])
        self.assertEqual(result["mterm_queries"], "8")
        self.assertNotIn("getITerms net_3", result["events"])
        self.assertNotIn("getITerms net_4", result["events"])
        self.assertNotIn("isSpecial net_3", result["events"])

    def test_mixed_cache_hits_preserve_iterm_order_and_first_protection_break(self):
        result = run_scan([{"name": "first", "terms": ["s", "s", "c", "__GET_MTERM_ERROR__"]},
                           {"name": "second", "terms": ["s", "c", "__GET_MTERM_ERROR__"]}],
                          {"s": "SIGNAL", "c": "CLOCK"})
        self.check_names(result, ["first", "second"])
        self.assertEqual([line for line in result["events"].splitlines() if line.startswith("getMTerm ")],
                         ["getMTerm iterm_0_0", "getMTerm iterm_0_1", "getMTerm iterm_0_2",
                          "getMTerm iterm_1_0", "getMTerm iterm_1_1"])
        self.assertEqual(result["mterm_queries"], "5")
        self.assertEqual(result["sig_queries"], "2")

    def test_same_pin_name_in_different_masters_keeps_distinct_handles(self):
        result = run_scan([{"name": "data", "terms": ["master1_A", "master1_A"]},
                           {"name": "clock", "terms": ["master2_A"]},
                           {"name": "mixed", "terms": ["master1_A", "master2_A"]}],
                          {"master1_A": "SIGNAL", "master2_A": "CLOCK"})
        self.check_names(result, ["clock", "mixed"])
        self.assertEqual(result["sig_queries"], "2")
        self.assertEqual(result["mterm_queries"], "5")

    def test_json_and_opaque_handle_metacharacters_are_data(self):
        names = ['data[3]$secret"\\path;[set injected 1]',
                 ''.join(chr(i) for i in range(32)), '层共享/信号', 'two words']
        handle = "::master[3]$suffix;[set injected 1]"
        result = run_scan([{"name": name, "terms": [handle]} for name in names], {handle: "GROUND"})
        self.check_names(result, names)
        self.assertEqual(result["sig_queries"], "1")

    def test_lookup_failures_and_invalid_handles_propagate(self):
        cases = [(["s", "s", "__GET_MTERM_ERROR__"], {"s": "SIGNAL"}, "injected getMTerm failure"),
                 (["bad"], {"bad": "__SIG_ERROR__"}, "injected getSigType failure"),
                 (["NULL"], {}, 'invalid command name "NULL"'),
                 (["stale_pointer"], {}, 'invalid command name "stale_pointer"')]
        for terms, types, message in cases:
            with self.subTest(terms=terms):
                result = run_scan([{"terms": terms}], types)
                self.assertEqual(result["status"], "1")
                self.assertEqual(result["message"], message)
                self.assertEqual(result["injected"], "0")
                if terms[0] == "s":
                    self.assertEqual(result["mterm_queries"], "3")
                    self.assertEqual(result["sig_queries"], "1")

    def test_repeated_unprotected_mterms_resolve_every_iterm_once(self):
        result = run_scan([{"terms": ["m0", "m1", "m2", "m3"] * 25} for _ in range(3)],
                          {"m0": "SIGNAL", "m1": "SIGNAL", "m2": "SIGNAL", "m3": "SIGNAL"})
        self.check_names(result, [])
        self.assertEqual(result["mterm_queries"], "300")
        self.assertEqual(result["sig_queries"], "4")

    def test_cache_is_reset_when_a_second_scan_sees_changed_types(self):
        result = run_scan([{"name": "changed-between-runs", "terms": ["m", "m"]}],
                          {"m": "SIGNAL"}, changed_types={"m": "CLOCK"})
        self.check_names(result, [])
        self.assertEqual(result["status2"], "0")
        self.assertEqual(bytes.fromhex(result["output2_hex"]), b'["changed-between-runs"]\n')
        self.assertEqual(result["sig_queries"], "1")
        self.assertEqual(result["sig_queries2"], "2")
        self.assertEqual(result["mterm_queries2"], "3")

    def test_empty_design_and_unconnected_signal_net_produce_empty_json(self):
        for nets in ([], [{"name": "unconnected", "terms": []}]):
            with self.subTest(nets=nets):
                result = run_scan(nets, {})
                self.check_names(result, [])
                self.assertEqual(result["sig_queries"], "0")
                self.assertEqual(result["mterm_queries"], "0")


if __name__ == "__main__":
    unittest.main()
