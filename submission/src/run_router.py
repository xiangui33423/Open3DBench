#!/usr/bin/env python3
"""Isolated contest entry point: DEF -> prepared ODB -> two GRT passes -> ODB."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from materialize_source import source_fingerprint


def tcl_quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('[', '\\[').replace(']', '\\]') + '"'


def select_collateral(def_path: Path, platform: Path) -> tuple[list[Path], list[Path]]:
    """Load exact normal-size masters used by this DEF, avoiding shrink copies."""
    text = def_path.read_text()
    section = re.search(r'\bCOMPONENTS\s+\d+\s*;(.*?)\bEND COMPONENTS\b', text, re.S)
    if section is None:
        raise ValueError('DEF has no COMPONENTS section')
    masters = set(re.findall(r'^\s*-\s+\S+\s+(\S+)', section.group(1), re.M))
    lef_files = [platform / 'lef/NangateOpenCellLibrary.tech.lef']
    cell_lefs = sorted((platform / 'lef_bottom').glob('*.lef')) + sorted((platform / 'lef_upper').glob('*.lef'))
    covered: set[str] = set()
    for lef in cell_lefs:
        names = set(re.findall(r'^\s*MACRO\s+(\S+)', lef.read_text(), re.M))
        if names & masters:
            lef_files.append(lef)
            covered.update(names)
    if masters - covered:
        raise ValueError(f'Platform LEFs lack masters: {sorted(masters - covered)[:20]}')
    lib_files: list[Path] = []
    for lib in sorted((platform / 'lib_bottom').glob('*.lib')) + sorted((platform / 'lib_upper').glob('*.lib')):
        if ' copy.' in lib.name:
            continue
        names = set(re.findall(r'\bcell\s*\(\s*"?([^\s)\"]+)"?\s*\)', lib.read_text()))
        if names & masters:
            lib_files.append(lib)
    for path in lef_files + lib_files:
        if not path.is_file():
            raise FileNotFoundError(path)
    if not lib_files:
        raise ValueError('No matching Liberty files in platform')
    return lef_files, lib_files


def resolve_executable(root: Path, threads: int) -> str:
    explicit = os.environ.get('OPENROAD_EXE')
    build_root = Path(os.environ.get('SUBMISSION_BUILD_DIR', str(Path(tempfile.gettempdir()) / f'open3dbench-grt-build-{os.getuid()}')))
    candidates = [explicit] if explicit else [str(root / 'bin/openroad')]
    if not explicit:
        stamp = build_root / '.submission-source-sha256'
        if stamp.is_file() and stamp.read_text().strip() == source_fingerprint(root / 'openroad_overlay'):
            candidates.append(str(build_root / 'openroad-build/bin/openroad'))
    for candidate in candidates:
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return str(Path(shutil.which(candidate) or candidate).absolute())
    if explicit:
        raise FileNotFoundError(f'OPENROAD_EXE is not executable: {explicit}')
    subprocess.run(['bash', str(root / 'build.sh'), str(threads)], check=True)
    binary = build_root / 'openroad-build/bin/openroad'
    if not binary.is_file():
        raise RuntimeError('build.sh did not produce bin/openroad')
    return str(binary)


def run_openroad(exe: str, script: Path, env: dict[str, str], log: Path) -> None:
    print(f'OpenROAD: {script.name}; log: {log}', flush=True)
    with log.open('w') as output:
        result = subprocess.run([exe, '-exit', '-no_init', str(script)], env=env, stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        tail = log.read_text(errors='replace').splitlines()[-30:]
        raise RuntimeError(f'OpenROAD exited {result.returncode}:\n' + '\n'.join(tail))


def atomic_copy(source: Path, destination: Path) -> None:
    temporary = destination.with_name(destination.name + '.tmp')
    shutil.copy2(source, temporary)
    temporary.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description='3D-IC MLS global router')
    parser.add_argument('input_dir', type=Path)
    parser.add_argument('output_dir', type=Path)
    parser.add_argument('platform_dir', type=Path)
    parser.add_argument('threads', type=int, nargs='?', default=32)
    args = parser.parse_args()
    if not 1 <= args.threads <= 32:
        parser.error('threads must be an integer between 1 and 32')
    root = Path(__file__).resolve().parents[1]
    input_dir = args.input_dir.resolve(strict=True)
    platform = args.platform_dir.resolve(strict=True)
    if any('\n' in str(path) or '\r' in str(path) for path in (root, input_dir, args.output_dir, platform)):
        parser.error('paths must not contain newline characters')
    def_path, sdc_path = input_dir / '4_1_cts.def', input_dir / '4_cts.sdc'
    if not def_path.is_file() or not sdc_path.is_file():
        parser.error('input_dir must contain 4_1_cts.def and 4_cts.sdc')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # An error must not leave a previous submission looking like this run's result.
    for name in ('5_1_grt.odb', 'route.guide', 'run_manifest.json', 'submission.def', 'mls_plan.json'):
        (output / name).unlink(missing_ok=True)
    lefs, libs = select_collateral(def_path, platform)
    exe = resolve_executable(root, args.threads)
    env = dict(os.environ)
    started = time.monotonic()
    work = Path(tempfile.mkdtemp(prefix='.grt-work-', dir=output))
    results, logs, reports = (work / p for p in ('results', 'logs', 'reports'))
    for directory in (results, logs, reports):
        directory.mkdir()
    shutil.copy2(def_path, results / '4_1_cts.def')
    shutil.copy2(sdc_path, results / '4_cts.sdc')
    env.update({
        'SCRIPTS_DIR': str(root / 'flow_scripts/scripts'),
        'RESULTS_DIR': str(results), 'LOG_DIR': str(logs), 'REPORTS_DIR': str(reports),
        'PLATFORM_DIR': str(platform), 'OPENROAD_EXE': exe,
        'NUM_CORES': str(args.threads), 'OMP_NUM_THREADS': str(args.threads),
        'MIN_ROUTING_LAYER': 'metal2', 'MAX_ROUTING_LAYER': 'metal20',
        'FASTROUTE_TCL': str(platform / 'fastroute.tcl'),
        'SUBMISSION_COLLATERAL_TCL': str(work / 'collateral.tcl'),
    })
    (work / 'collateral.tcl').write_text(
        'set submission_lefs [list ' + ' '.join(tcl_quote(str(p)) for p in lefs) + ']\n' +
        'set submission_libs [list ' + ' '.join(tcl_quote(str(p)) for p in libs) + ']\n')
    env.setdefault('VALIDATE_DIE_GUIDES', '1')
    # Public case configs allow overflow for the fixed detailed-route evaluator.
    env.setdefault('GLOBAL_ROUTE_ARGS', '-allow_congestion -congestion_iterations 2 -congestion_report_iter_step 5 -verbose')
    if env.get('MLS_ENABLE', '1') != '0':
        hook = root / 'flow_scripts/scripts_3D/prepare_mls.tcl'
        if not hook.is_file():
            raise FileNotFoundError(f'Missing packaged MLS hook: {hook}; run package.py')
        env['GRT_PREPARE_TCL'] = str(hook)
        env.setdefault('MLS_CONFIG', str(root / 'flow_scripts/scripts_3D/mls_config.json'))
    else:
        env.pop('GRT_PREPARE_TCL', None)
    probe = work / 'probe.tcl'
    probe.write_text('if {[info commands set_net_routing_layers] eq ""} {error "Required set_net_routing_layers is unavailable; compile the submitted GRT overlay with build.sh"}\nputs "SUBMISSION_LAYER_CLAMP_READY"\n')
    run_openroad(exe, probe, env, logs / 'probe.log')
    if 'SUBMISSION_LAYER_CLAMP_READY' not in (logs / 'probe.log').read_text():
        raise RuntimeError('OpenROAD initialization or layer-clamp probe failed')
    run_openroad(exe, root / 'src/load_input.tcl', env, logs / 'load_input.log')
    if not (results / '4_cts.odb').is_file():
        raise RuntimeError('Input conversion did not create 4_cts.odb')
    run_openroad(exe, root / 'flow_scripts/scripts/global_route_die_by_die.tcl', env, logs / 'global_route.log')
    odb, guide, marker = results / '5_1_grt.odb', results / 'route.guide', results / '.grt_finalize_complete'
    if not marker.is_file() or not odb.is_file() or not odb.stat().st_size or not guide.is_file() or not guide.stat().st_size:
        raise RuntimeError(f'Routing did not publish complete output; inspect {logs}')
    # Re-open the freshly written ODB with the same executable before publishing.
    verify = work / 'verify.tcl'
    verify.write_text(f'read_db {tcl_quote(str(odb))}\nwrite_def {tcl_quote(str(results / "submission.def"))}\nputs "SUBMISSION_ODB_READABLE"\n')
    run_openroad(exe, verify, env, logs / 'verify.log')
    if 'SUBMISSION_ODB_READABLE' not in (logs / 'verify.log').read_text():
        raise RuntimeError('Fresh ODB failed reopen verification')
    atomic_copy(odb, output / '5_1_grt.odb')
    atomic_copy(guide, output / 'route.guide')
    atomic_copy(results / 'submission.def', output / 'submission.def')
    for plan in results.glob('mls*.json'):
        atomic_copy(plan, output / plan.name)
    shutil.copytree(results / 'die_net_lists', output / 'die_net_lists', dirs_exist_ok=True)
    manifest = {
        'input_sha256': hashlib.sha256(def_path.read_bytes()).hexdigest(),
        'openroad_exe': exe, 'threads': args.threads,
        'mls_enabled': env.get('MLS_ENABLE', '1') != '0',
        'runtime_seconds': round(time.monotonic() - started, 3),
        'odb_bytes': odb.stat().st_size, 'work_dir': str(work),
    }
    (output / 'run_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'完成: {output / "5_1_grt.odb"} ({odb.stat().st_size} bytes)', flush=True)


if __name__ == '__main__':
    main()
