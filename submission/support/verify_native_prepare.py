#!/usr/bin/env python3
"""Check batched read-only scans against the released Tcl on real OpenDB."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('[', '\\[').replace(']', '\\]') + '"'


def definitions(path, namespace):
    text = path.read_text().rsplit('\nmls_prepare::run', 1)[0]
    start = text.index('    set protected_path ')
    end = text.index('    close $protected_fp', start) + len('    close $protected_fp')
    scan = text[start:end]
    return (text.replace('namespace eval mls_prepare {', 'namespace eval ' + namespace + ' {', 1)
            + '\nproc ' + namespace + '::probe_protected {block} {\n' + scan + '\n}\n')


PROBE = r"""
proc fail {message} {error $message}
proc compare_state {label} {
  global block probe_output
  set ::env(MLS_PREPARE_SCAN) native
  set start [clock microseconds]
  set actual [mls_prepare::inst_snapshot $block]
  set native_us [expr {[clock microseconds] - $start}]
  set start [clock microseconds]
  set expected [v6_prepare::inst_snapshot $block]
  set legacy_us [expr {[clock microseconds] - $start}]
  if {$actual ne $expected} {fail "component snapshot mismatch: $label"}
  mls_prepare::check_snapshot $expected $actual components
  foreach ns {mls_prepare v6_prepare} {
    set ::env(RESULTS_DIR) [file join $probe_output $label $ns]
    file mkdir $::env(RESULTS_DIR)
    ${ns}::probe_protected $block
    set fp [open [file join $::env(RESULTS_DIR) mls_protected_nets.json] rb]
    set protected($ns) [read $fp]
    close $fp
  }
  if {$protected(mls_prepare) ne $protected(v6_prepare)} {fail "protected JSON mismatch: $label"}
  set fp [open [file join $probe_output $label snapshot.tcl] w]
  puts -nonewline $fp $actual
  close $fp
  puts "V7_SCAN_PASS $label [dict size $actual] $native_us $legacy_us"
  return $actual
}
set block [ord::get_db_block]
set db [ord::get_db]
set base [compare_state original]
set special_name "V7_quoted\"\\\n\r\t\u4e2d\u6587\$\[x\]"
# Loading the fixture library through LEF creates both DB masters and their
# corresponding STA cells, which are required by swapMaster's callback.
set fixture_lef [file join $probe_output fixture.lef]
set fp [open $fixture_lef w]
puts $fp {VERSION 5.8 ;}
foreach type {SIGNAL CLOCK POWER GROUND RESET ANALOG SCAN TIEOFF} {
  puts $fp "MACRO V7_SCAN_MASTER_$type\n  CLASS CORE ;\n  ORIGIN 0 0 ;\n  SIZE 0.01 BY 0.015 ;\n  PIN A\n    DIRECTION INPUT ;\n    USE SIGNAL ;\n  END A\nEND V7_SCAN_MASTER_$type"
}
puts $fp {END LIBRARY}
close $fp
read_lef $fixture_lef
set masters {}
foreach type {SIGNAL CLOCK POWER GROUND RESET ANALOG SCAN TIEOFF} {
  set master [$db findMaster V7_SCAN_MASTER_$type]
  set term [$master findMTerm A]
  $term setSigType $type
  set inst [odb::dbInst_create $block $master ${special_name}_$type]
  $inst setOrigin -17 -21
  $inst setOrient MY
  $inst setPlacementStatus FIRM
  set net [odb::dbNet_create $block ${special_name}_net_$type]
  foreach pin [$inst getITerms] {$pin connect $net}
  dict set masters $type [list $master $term $inst $net]
}
# Special and non-SIGNAL nets short-circuit before examining ordinary pins.
foreach type {CLOCK POWER GROUND RESET} {
  set net [odb::dbNet_create $block V7_scan_sig_$type]
  $net setSigType $type
}
set net [odb::dbNet_create $block V7_scan_special]
$net setSpecial
set hbti [odb::dbInst_create $block [lindex [dict get $masters SIGNAL] 0] LS_HBT_V7_scan]
$hbti setOrigin -4 -8
$hbti setPlacementStatus PLACED
set before [compare_state boundaries]
set signal_term [lindex [dict get $masters SIGNAL] 1]
$signal_term setSigType CLOCK
compare_state changed_master_signal_type
$signal_term setSigType SIGNAL
set instance [lindex [dict get $masters SIGNAL] 2]
proc restore_instance {instance master} {
  # OpenDB rejects moving/rotating FIRM components. Unlock only the fixture,
  # then restore all original fields before each independent guard check.
  $instance setPlacementStatus PLACED
  $instance swapMaster $master
  $instance setOrigin -17 -21
  $instance setOrient MY
  $instance setPlacementStatus FIRM
}
# Query again after each mutation: no stale snapshot/cache is allowed.
foreach {kind command} [list origin [list $instance setOrigin 15 -21] orientation [list $instance setOrient R90] status [list $instance setPlacementStatus PLACED] master [list $instance swapMaster [lindex [dict get $masters RESET] 0]]] {
  restore_instance $instance [lindex [dict get $masters SIGNAL] 0]
  $instance setPlacementStatus PLACED
  {*}$command
  if {$kind ne "status"} {$instance setPlacementStatus FIRM}
  set after [compare_state mutation_$kind]
  if {![catch {mls_prepare::check_snapshot $before $after components}]} {fail "modified ordinary component escaped guard"}
}
restore_instance $instance [lindex [dict get $masters SIGNAL] 0]
set extra [odb::dbInst_create $block [lindex [dict get $masters SIGNAL] 0] V7_extra_component]
set after [compare_state extra_component]
if {![catch {mls_prepare::check_snapshot $before $after components}]} {fail "added ordinary component escaped guard"}
odb::dbInst_destroy $extra
compare_state after_destroy
puts V7_SCAN_ALL_PASS
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openroad', type=Path, required=True)
    parser.add_argument('--odb', type=Path, required=True)
    parser.add_argument('--hook', type=Path, required=True)
    parser.add_argument('--baseline-hook', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    inputs = [p.resolve() for p in (args.openroad, args.odb, args.hook, args.baseline_hook, Path(__file__))]
    before = {str(p): digest(p) for p in inputs}
    script = definitions(args.hook, 'mls_prepare') + definitions(args.baseline_hook, 'v6_prepare')
    script += '\nread_db ' + quote(args.odb.resolve()) + '\nset probe_output ' + quote(args.output.resolve()) + '\n' + PROBE
    tcl = args.output / 'verify.tcl'; tcl.write_text(script)
    log = args.output / 'openroad.log'
    with log.open('w') as stream:
        result = subprocess.run([str(args.openroad), '-exit', '-no_init', str(tcl)], stdout=stream, stderr=subprocess.STDOUT)
    content = log.read_text()
    rows = re.findall(r'^V7_SCAN_PASS (\S+) (\d+) (\d+) (\d+)$', content, re.M)
    stable = before == {str(p): digest(p) for p in inputs}
    passed = result.returncode == 0 and '\nV7_SCAN_ALL_PASS\n' in content and len(rows) == 9 and stable
    artifacts = [tcl, log] + sorted(args.output.glob('*/snapshot.tcl')) + sorted(args.output.glob('*/*/mls_protected_nets.json'))
    report = {'status': 'PASS' if passed else 'FAIL', 'exit_code': result.returncode,
              'source_sha256': {**before, **{str(p.resolve()): digest(p) for p in artifacts}},
              'input_files_stable_during_run': stable,
              'checks': [{'state': n, 'components': int(c), 'native_snapshot_seconds': int(a)/1e6,
                          'v6_snapshot_seconds': int(b)/1e6} for n,c,a,b in rows],
              'scope': 'Actual OpenDB native/Tcl component dictionaries and protected JSON byte parity, changed master signal types, component mutations and count guards; no routing or quality claim.'}
    (args.output / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'states': len(rows), 'exit_code': result.returncode}))
    return 0 if passed else 1

if __name__ == '__main__':
    raise SystemExit(main())
