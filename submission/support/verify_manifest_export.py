#!/usr/bin/env python3
"""Differential test of native/Tcl geometry exporters in the official image.

Runs on an actual prepared input ODB, then adds boundary fixtures for escaping,
negative half coordinates, missing geometry, ambiguous dies and BPin averaging.
The streaming comparison retains every net and pin and checks their order.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import re
import subprocess
from pathlib import Path


def quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('[', '\\[').replace(']', '\\]') + '"'


def records(path: Path):
    with path.open() as stream:
        prefix = ''
        for line in stream:
            if line.strip() == '],"nets":[':
                yield json.loads(prefix + ']}')
                break
            prefix += line
        else:
            raise ValueError(f'Missing nets array in {path}')
        for line in stream:
            if line.strip() == ']}':
                if stream.read().strip():
                    raise ValueError(f'Trailing data in {path}')
                return
            yield json.loads(line.lstrip(','))
        raise ValueError(f'Incomplete nets array in {path}')


FIXTURE = r'''
set lib [lindex [$db getLibs] 0]
foreach master_name {fixture_plain fixture_upper} {
  set m [odb::dbMaster_create $lib $master_name]
  $m setWidth 3
  $m setHeight 5
  $m setType CORE
  foreach pin {A BOT TOP} { odb::dbMTerm_create $m $pin INPUT }
  $m setFrozen
}
set weird "literal\"\\\n\r\t[format %c 1]\u4e2d\u6587\$\[x\]"
set net [odb::dbNet_create $block "fixture_$weird"]
$net setSigType CLOCK
$net setSpecial
foreach {name master_name} [list "cell_${weird}_bottom" fixture_upper unknown fixture_plain HBT_fixture fixture_plain] {
  set inst [odb::dbInst_create $block [$db findMaster $master_name] $name]
  $inst setOrigin -10 -20
  $inst setPlacementStatus PLACED
  foreach term [$inst getITerms] { $term connect $net }
}
odb::dbTechLayer_create [ord::get_db_tech] fixture_layer ROUTING
foreach {name layers} {mixed {metal10 metal11} single {metal10 metal10} unknown {fixture_layer} empty {}} {
  set term [odb::dbBTerm_create $net "fixture_${name}_$weird"]
  $term setIoType INPUT
  foreach layer $layers {
    set pin [odb::dbBPin_create $term]
    odb::dbBox_create $pin [[ord::get_db_tech] findLayer $layer] -10 -20 -7 -15
  }
}
# Include a net with no terminals and a package pin without any BPin geometry.
odb::dbNet_create $block "fixture_empty_$weird"
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--openroad', type=Path, required=True)
    p.add_argument('--odb', type=Path, required=True)
    p.add_argument('--hook', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--skip-fixtures', action='store_true')
    p.add_argument('--reference-json', type=Path, help='Previously captured Tcl export of this exact ODB (requires --skip-fixtures)')
    args = p.parse_args()
    if args.reference_json and not args.skip_fixtures:
        p.error('--reference-json requires --skip-fixtures')
    args.output.mkdir(parents=True, exist_ok=True)
    # Source only the real exporter definitions, without running the planner.
    definitions = args.hook.read_text().rsplit('\nmls_prepare::run', 1)[0]
    script = definitions + '\nread_db ' + quote(str(args.odb.resolve())) + '\n'
    script += 'set db [ord::get_db]\nset block [ord::get_db_block]\nset master [$db findMaster HBT_BOTIN]\n'
    variants = ['original'] if args.skip_fixtures else ['original', 'boundaries']
    for variant in variants:
        if variant == 'boundaries':
            script += FIXTURE
        for exporter in (('native',) if args.reference_json else ('native', 'tcl')):
            path = args.output / f'{variant}.{exporter}.json'
            script += (f'set ::env(MLS_MANIFEST_EXPORTER) {exporter}\n'
                       'set started [clock microseconds]\n'
                       f'mls_prepare::export_manifest {quote(str(path.resolve()))} $db $block $master\n'
                       f'puts "EXPORT_TIME {variant}.{exporter} [expr {{([clock microseconds] - $started) / 1e6}}]"\n')
    script_path = args.output / 'verify.tcl'
    script_path.write_text(script)
    with (args.output / 'openroad.log').open('w') as log:
        subprocess.run([str(args.openroad), '-exit', '-no_init', str(script_path)], stdout=log, stderr=subprocess.STDOUT, check=True)
    timings = {name: float(value) for name, value in re.findall(r'^EXPORT_TIME (\S+) (\S+)$', (args.output / 'openroad.log').read_text(), re.M)}
    report = {'odb': str(args.odb), 'timings_seconds': timings, 'comparisons': {}}
    missing = object()
    for variant in variants:
        digest = hashlib.sha256()
        net_count = 0
        pin_count = 0
        legacy_path = args.reference_json or args.output / f'{variant}.tcl.json'
        for i, (native, legacy) in enumerate(itertools.zip_longest(records(args.output / f'{variant}.native.json'), records(legacy_path), fillvalue=missing)):
            if native != legacy:
                raise AssertionError(f'{variant} record {i} differs: {native!r} != {legacy!r}')
            digest.update(json.dumps(native, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode())
            digest.update(b'\n')
            if i:
                net_count += 1
                pin_count += len(native['pins'])
                if variant == 'boundaries' and native['name'].startswith('fixture_literal'):
                    assert len(native['pins']) == 13, native
                    assert native['signal_type'] == 'CLOCK' and native['special'] and native['bterms']
                    for pin in native['pins']:
                        expected_die = None
                        expected_xy = (-9, -18)
                        if pin['inst'].endswith('_bottom'):
                            expected_die = 'bottom'
                        elif pin['inst'] == 'HBT_fixture':
                            expected_die = {'BOT': 'bottom', 'TOP': 'upper'}.get(pin['pin'])
                        elif pin['inst'] == 'PIN':
                            if pin['pin'].startswith('fixture_single_'):
                                expected_die = 'bottom'
                            if pin['pin'].startswith('fixture_empty_'):
                                expected_xy = (0, 0)
                        assert pin['die'] == expected_die and (pin['x'], pin['y']) == expected_xy, pin
        report['comparisons'][variant] = {'equal': True, 'nets': net_count, 'pins': pin_count, 'canonical_sha256': digest.hexdigest(), 'reference_json': str(legacy_path)}
    (args.output / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
