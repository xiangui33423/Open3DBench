#!/usr/bin/env python3
"""Exercise the actual Tcl native scan dispatch and unchanged snapshot guard."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

SOURCE = Path(os.environ.get("MLS_TEST_SCRIPT_DIR", Path(__file__).resolve().parents[1])) / "prepare_mls.tcl"

def definitions():
    return SOURCE.read_text().rsplit("mls_prepare::run", 1)[0]

def run_tcl(body):
    script = definitions() + r"""
proc assert_equal {value expected} {
  if {$value ne $expected} {error "Unexpected value: <$value> != <$expected>"}
}
proc main {} {
""" + body + "\n}\nif {[catch {main} message]} {puts stderr $message; exit 1}\nputs PASS\n"
    result = subprocess.run([shutil.which("tclsh")], input=script, text=True, capture_output=True)
    if result.returncode or result.stderr:
        raise AssertionError(result.stdout + result.stderr)
    if result.stdout.strip() != "PASS":
        raise AssertionError(result.stdout)

@unittest.skipUnless(shutil.which("tclsh"), "Tcl interpreter unavailable")
class NativePrepareInterfaces(unittest.TestCase):
    def test_auto_missing_command_uses_portable_path(self):
        run_tcl('assert_equal [mls_prepare::use_native_scan ::absent] 0')

    def test_native_required_missing_command_is_an_error(self):
        run_tcl(r"""
set ::env(MLS_PREPARE_SCAN) native
assert_equal [catch {mls_prepare::use_native_scan ::absent} message] 1
assert_equal $message {Native MLS scan unavailable: ::absent}
""")

    def test_tcl_forces_fallback_when_native_exists(self):
        run_tcl(r"""
proc ::test_native {} {error "must not call"}
set ::env(MLS_PREPARE_SCAN) tcl
assert_equal [mls_prepare::use_native_scan ::test_native] 0
""")

    def test_invalid_mode_is_rejected(self):
        run_tcl(r"""
set ::env(MLS_PREPARE_SCAN) unsafe
assert_equal [catch {mls_prepare::inst_snapshot block} message] 1
assert_equal $message {Invalid MLS_PREPARE_SCAN 'unsafe'}
""")

    def test_native_fields_are_values_and_keep_original_dict_format(self):
        run_tcl(r"""
namespace eval ::grt {}
proc ::grt::mls_instance_snapshot {} {
 return [list {inst[1] $x; [error injected]} {master two} -17 0 MY FIRM 名称 带空格 14 -8 R90 COVER]
}
set expected [dict create {inst[1] $x; [error injected]} [list {master two} {-17 0} MY FIRM] 名称 [list 带空格 {14 -8} R90 COVER]]
assert_equal [mls_prepare::inst_snapshot unused] $expected
""")

    def test_incomplete_native_record_is_rejected(self):
        run_tcl(r"""
namespace eval ::grt {}
proc ::grt::mls_instance_snapshot {} {return {name master 0 1 R0}}
assert_equal [catch {mls_prepare::inst_snapshot unused} message] 1
assert_equal $message {Malformed native MLS component snapshot}
""")

    def test_native_error_does_not_skip_guard_or_fall_back(self):
        run_tcl(r"""
namespace eval ::grt {}
proc ::grt::mls_instance_snapshot {} {error {native query failure}}
assert_equal [catch {mls_prepare::inst_snapshot unused} message] 1
assert_equal $message {native query failure}
""")

    def test_each_snapshot_rereads_changed_fields_and_guard_rejects_them(self):
        run_tcl(r"""
namespace eval ::grt {}
proc ::grt::mls_instance_snapshot {} {return $::records}
set original {cell master 0 0 R0 PLACED}
set ::records $original
set before [mls_prepare::inst_snapshot unused]
foreach {index value} {1 replacement 2 -1 3 2 4 R90 5 FIRM} {
 set ::records [lreplace $original $index $index $value]
 set after [mls_prepare::inst_snapshot unused]
 assert_equal [catch {mls_prepare::check_snapshot $before $after components}] 1
}
set ::records $original
mls_prepare::check_snapshot $before [mls_prepare::inst_snapshot unused] components
""")

    def test_add_remove_and_rename_are_detected(self):
        run_tcl(r"""
namespace eval ::grt {}
proc ::grt::mls_instance_snapshot {} {return $::records}
set ::records {cell master 0 0 R0 PLACED}
set before [mls_prepare::inst_snapshot unused]
foreach records {{} {other master 0 0 R0 PLACED} {cell master 0 0 R0 PLACED extra master 0 0 R0 FIRM}} {
 set ::records $records
 assert_equal [catch {mls_prepare::check_snapshot $before [mls_prepare::inst_snapshot unused] components}] 1
}
""")

    def test_empty_native_snapshot_is_an_empty_dict(self):
        run_tcl(r"""
namespace eval ::grt {}
proc ::grt::mls_instance_snapshot {} {return {}}
assert_equal [dict size [mls_prepare::inst_snapshot unused]] 0
""")

if __name__ == "__main__":
    unittest.main()
