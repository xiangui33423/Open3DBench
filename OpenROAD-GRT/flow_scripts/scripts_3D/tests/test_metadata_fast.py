#!/usr/bin/env python3
"""Run actual fused Tcl procedures against stateful OpenDB/STA command stubs."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

SCRIPT_DIR = Path(os.environ.get('MLS_TEST_SCRIPT_DIR', Path(__file__).resolve().parents[1]))
SOURCE = (SCRIPT_DIR / 'global_route_single_process.tcl').read_text()
FUNCTIONS = SOURCE[SOURCE.index('proc fused_stage '):SOURCE.index('set fused_started [clock milliseconds]')]
RESTORE = SOURCE[SOURCE.index('fused_stage restore_sigtypes {'):SOURCE.index('\ngrt::clear_net_routing_layers', SOURCE.index('fused_stage restore_sigtypes {'))]
RESET = SOURCE[SOURCE.index('set fused_reset_mode '):SOURCE.index('\nputs "GRT_STAGE reset_pass_ms=')]
PASS = SOURCE[SOURCE.index('proc fused_route_pass '):SOURCE.index('\nset fused_bottom [')]
ASSERT = '''
proc assert {condition message} {
  if {![uplevel 1 [list expr $condition]]} {error $message}
}
'''
METADATA_MOCK = '''
namespace eval sta {}
namespace eval grt {}
namespace eval odb {proc dbGuide_destroy {guide} {incr ::destroyed_guides}}
array set types {clk_signal SIGNAL clk_clock CLOCK clk_reset RESET data SIGNAL special POWER}
array set special {clk_signal 0 clk_clock 0 clk_reset 0 data 0 special 1}
set all_nets {clk_signal clk_clock clk_reset data special}
set clock_nets {clk_signal clk_clock clk_reset}
set full_scans 0
set reads {}
set writes {}
set destroyed_guides 0
set query_calls 0
proc net_command {name method args} {
  switch -- $method {
    getSigType {lappend ::reads $name; return $::types($name)}
    setSigType {lappend ::writes $name; set ::types($name) [lindex $args 0]}
    getName {return $name}
    isSpecial {return $::special($name)}
    setSpecial {set ::special($name) 1}
    clearSpecial {set ::special($name) 0}
    getGuides {return [list guide_$name]}
    default {error "Unexpected net operation $method"}
  }
}
foreach name $all_nets {interp alias {} $name {} net_command $name}
proc block {method} {
  assert {$method eq "getNets"} "Unexpected block method"
  incr ::full_scans
  return $::all_nets
}
proc promote_clocks {} {foreach net $::clock_nets {$net setSigType CLOCK}}
proc check_restored {} {
  assert {$::types(clk_signal) eq "SIGNAL"} "Originally SIGNAL clock not restored"
  assert {$::types(clk_clock) eq "CLOCK"} "Original CLOCK changed"
  assert {$::types(clk_reset) eq "RESET"} "Original RESET clock not restored"
  assert {$::types(data) eq "SIGNAL"} "Data type changed"
  assert {$::types(special) eq "POWER"} "Supply type changed"
}
'''


@unittest.skipUnless(shutil.which('tclsh'), 'Tcl interpreter unavailable')
class MetadataSnapshotTest(unittest.TestCase):
    def run_tcl(self, body):
        env = dict(os.environ)
        for key in ('GRT_METADATA_SNAPSHOT', 'GRT_LAYER_DISPATCH', 'GRT_PASS_RESET'):
            env.pop(key, None)
        result = subprocess.run(['tclsh'], input=ASSERT + FUNCTIONS + METADATA_MOCK + '\nif {[catch {\n' + body + '\n} error]} {puts stderr $error; exit 1}\nputs PASS\n', text=True, capture_output=True, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS\n', result.stdout)
        return result.stdout

    def test_clock_subset_restores_original_signal_clock_and_reset(self):
        output = self.run_tcl('''
proc sta::find_all_clk_nets {} {incr ::query_calls; return $::clock_nets}
set fused_net_sigtypes [fused_snapshot_sigtypes block]
assert {$full_scans == 0 && $reads eq $clock_nets} "Fast path enumerated nonclock nets"
promote_clocks
promote_clocks
''' + RESTORE + '''
check_restored
assert {$query_calls == 1} "Repeated clock query"
''')
        self.assertIn('mode=clock_nets count=3', output)

    def test_missing_error_and_partial_query_fall_back_to_complete_snapshot(self):
        queries = ['', 'proc sta::find_all_clk_nets {} {error "No linked clock network"}',
                   'proc sta::find_all_clk_nets {} {return {clk_signal stale_pointer}}']
        for query in queries:
            with self.subTest(query=query):
                output = self.run_tcl(query + '''
set fused_net_sigtypes [fused_snapshot_sigtypes block]
assert {$full_scans == 1 && [llength $fused_net_sigtypes] == 5} "Incomplete fallback"
promote_clocks
data setSigType CLOCK
''' + RESTORE + '\ncheck_restored\n')
                self.assertIn('mode=all_nets count=5', output)

    def test_successful_empty_query_does_not_trigger_full_scan(self):
        self.run_tcl('''
proc sta::find_all_clk_nets {} {return {}}
set fused_net_sigtypes [fused_snapshot_sigtypes block]
assert {$full_scans == 0 && [llength $fused_net_sigtypes] == 0} "Empty clock set changed behavior"
''' + RESTORE + '\ncheck_restored\n')

    def test_forced_full_snapshot_skips_native_query(self):
        self.run_tcl('''
set ::env(GRT_METADATA_SNAPSHOT) all
proc sta::find_all_clk_nets {} {error "Must not call native query"}
set fused_net_sigtypes [fused_snapshot_sigtypes block]
assert {$full_scans == 1 && [llength $fused_net_sigtypes] == 5} "Full mode omitted nets"
''')

    def test_legacy_reset_restores_only_temporary_special_flags(self):
        self.run_tcl('''
proc sta::find_all_clk_nets {} {return $::clock_nets}
set fused_net_sigtypes [fused_snapshot_sigtypes block]
promote_clocks
set ::env(GRT_PASS_RESET) legacy
set fused_block block
set fused_bottom {data}
set fused_upper $clock_nets
set fused_bottom_guide ignored.guide
proc read_guides {path} {
  assert {$::special(clk_signal) && !$::special(data)} "Legacy mask not applied"
  assert {$::types(clk_signal) eq "CLOCK"} "Legacy reset changed SigType"
}
''' + RESET + '''
foreach net $clock_nets {assert {!$special($net)} "Temporary special flag leaked"}
assert {$special(special) && !$special(data)} "Original special flags changed"
assert {$destroyed_guides == 5} "Legacy guide cleanup was skipped"
promote_clocks
''' + RESTORE + '\ncheck_restored\n')

    def test_legacy_reset_error_still_clears_temporary_flags(self):
        self.run_tcl('''
set ::env(GRT_PASS_RESET) legacy
set fused_block block
set fused_bottom {data}
set fused_upper $clock_nets
set fused_bottom_guide ignored.guide
proc read_guides {path} {error "injected guide error"}
set failed [catch {
''' + RESET + '''
} message]
assert {$failed && $message eq "injected guide error"} "Reset swallowed error"
foreach net $clock_nets {assert {!$special($net)} "Failed reset leaked special flag"}
assert {$special(special) && !$special(data)} "Failed reset changed original flags"
check_restored
''')


LAYER_MOCK = '''
namespace eval ord {
  proc get_db_tech {} {return tech}
  proc get_db_block {} {return block}
}
namespace eval grt {
  proc parse_layer_name {name} {
    incr ::parse_calls
    set layer [tech findLayer $name]
    if {$layer eq "NULL"} {error "Unknown layer $name"}
    return [$layer getRoutingLevel]
  }
  proc add_net_to_route {net} {lappend ::events [list QUEUE $net]}
  proc clear_net_resistance_aware {} {lappend ::events CLEAR_SELECTION}
}
namespace eval grt_capacity {proc apply {args} {}}
set ::fused_block block
set ::fused_adjustment 0.5
set ::fused_args {}
set ::grt_layer_hints {}
set ::fused_hints_policy layers
set events {}
set parse_calls 0
set lookups 0
set invalid_native 0
proc set_routing_layers {args} {}
proc set_global_routing_layer_adjustment {args} {}
proc set_net_resistance_aware {name} {lappend ::events [list RESISTANCE $name]}
proc global_route {args} {lappend ::events ROUTED}
proc layer {level method} {
  switch -- $method {
    getRoutingLevel {return $level}
    getName {return metal$level}
    default {error "Unexpected layer method $method"}
  }
}
for {set i 1} {$i <= 20} {incr i} {interp alias {} layer$i {} layer $i}
proc tech {method value} {
  if {$method eq "findLayer"} {
    if {![regexp {^metal([0-9]+)$} $value -> level]} {return NULL}
  } else {set level $value}
  if {$level < 1 || $level > 20} {return NULL}
  return layer$level
}
proc block {method name} {
  incr ::lookups
  if {$name eq "missing"} {return NULL}
  return $name
}
proc net {name method} {
  if {$method eq "getSigType"} {return [expr {$name eq "clock_net" ? "CLOCK" : "SIGNAL"}]}
  if {$method eq "getITerms"} {return [expr {$name eq "protected" ? "clock_iterm" : "signal_iterm"}]}
  error "Unexpected net method"
}
foreach name {data other clock_net protected} {interp alias {} $name {} net $name}
proc clock_iterm {method} {return clock_mterm}
proc signal_iterm {method} {return signal_mterm}
proc clock_mterm {method} {return CLOCK}
proc signal_mterm {method} {return SIGNAL}
proc mock_native {net lo hi} {
  if {$::invalid_native || $net eq "NULL" || $lo < 1 || $lo > $hi || $hi > 20} {error "Native range rejected"}
  lappend ::events [list CLAMP $net $lo $hi]
}
# Compatibility wrapper: same dbNet lookup and numeric parses as the public
# wrapper, independent of whether its direct native command is exposed.
proc set_net_routing_layers {name lo hi} {
  set net [block findNet $name]
  if {$net eq "NULL"} {error "Missing net"}
  set lo [grt::parse_layer_name $lo]
  set hi [grt::parse_layer_name $hi]
  if {$lo > $hi} {error "Reversed range"}
  mock_native $net $lo $hi
}
'''


@unittest.skipUnless(shutil.which('tclsh'), 'Tcl interpreter unavailable')
class LayerDispatchTest(unittest.TestCase):
    def invoke(self, body, native=True):
        program = ASSERT + LAYER_MOCK + PASS
        if native:
            program += '\nproc grt::set_net_routing_layers {net lo hi} {mock_native $net $lo $hi}\n'
        env = dict(os.environ)
        for key in ('GRT_LAYER_DISPATCH', 'MACRO_EXTENSION'):
            env.pop(key, None)
        return subprocess.run(['tclsh'], input=program + '\nif {[catch {\n' + body + '\n} error]} {puts stderr $error; exit 1}\nputs PASS\n', text=True, capture_output=True, env=env)

    def checked(self, body, native=True):
        result = self.invoke(body, native)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS\n', result.stdout)
        return result.stdout

    def test_native_and_legacy_enqueue_identical_nets_and_ranges(self):
        self.checked('''
set ::env(GRT_LAYER_DISPATCH) legacy
fused_route_pass {data other} metal2 metal10 ignore ignore
set expected $events
set events {}
set lookups 0
set parse_calls 0
set ::env(GRT_LAYER_DISPATCH) auto
fused_route_pass {data other} metal2 metal10 ignore ignore
assert {$events eq $expected} "Native dispatch changed routes or ordering"
assert {$lookups == 2 && $parse_calls == 2} "Native path repeated name/layer parses"
''')

    def test_missing_native_interface_falls_back_to_wrapper(self):
        output = self.checked('''
fused_route_pass {data other} metal2 metal10 ignore ignore
assert {$lookups == 4 && $parse_calls == 4} "Compatibility wrapper was bypassed"
assert {$events eq "{CLAMP data 2 10} {QUEUE data} {CLAMP other 2 10} {QUEUE other} ROUTED"} "Wrong fallback sequence"
''', native=False)
        self.assertIn('GRT_LAYER_DISPATCH native=0', output)

    def test_hint_intersection_and_clock_master_protection(self):
        self.checked('''
set ::grt_layer_hints {data {metal4 metal20} clock_net {metal4 metal20} protected {metal4 metal20}}
fused_route_pass {data clock_net protected} metal2 metal10 ignore ignore
assert {[lindex $events 0] eq "CLAMP data 4 10"} "Hint not clamped"
assert {[lindex $events 2] eq "CLAMP clock_net 2 10"} "Clock net changed"
assert {[lindex $events 4] eq "CLAMP protected 2 10"} "Clock terminal not protected"
''')

    def test_bad_net_layers_hint_and_native_rejection_fail_before_routing(self):
        cases = [('fused_route_pass {missing} metal2 metal10 ignore ignore', ''),
                 ('fused_route_pass {data} metal99 metal10 ignore ignore', ''),
                 ('fused_route_pass {data} metal10 metal2 ignore ignore', ''),
                 ('fused_route_pass {data} metal2 metal10 ignore ignore', 'set ::grt_layer_hints {data {metal11 metal20}}'),
                 ('fused_route_pass {data} metal2 metal10 ignore ignore', 'set invalid_native 1')]
        for command, setup in cases:
            with self.subTest(command=command, setup=setup):
                self.checked(setup + '\nset failed [catch {' + command + '''} message]
assert {$failed} "Invalid input was accepted"
assert {[lsearch -exact $events ROUTED] == -1} "Router ran after invalid input"
''')

    def test_resistance_policy_preserves_selection_and_full_window(self):
        self.checked('''
set ::grt_layer_hints {data {metal4 metal20}}
set ::fused_hints_policy resistance
fused_route_pass {data} metal2 metal10 ignore ignore
assert {$events eq "CLEAR_SELECTION {RESISTANCE data} {CLAMP data 2 10} {QUEUE data} ROUTED"} "Resistance policy changed"
''')


if __name__ == '__main__':
    unittest.main()
