#!/usr/bin/env python3
"""Canonical legality and image-pinned DRT/STA for independent candidate ODBs.

This is local experiment infrastructure. It does not route a candidate, alter
the submission algorithm, modify the fixed evaluator, or calculate a score.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid


REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPOSITORY / 'Open3DBench-offline-20260904/Open3DBench/input/open3dbench_8cases_post_hbt_input_20260724'


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def write_json(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def run(command: list[str], env: dict[str, str], log: Path, cwd: Path | None = None) -> int:
    with log.open('w') as stream:
        process = subprocess.run(command, env=env, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    return process.returncode


def labels(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        label, separator, path = value.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', label) or label in result:
            raise ValueError('Expected distinct label=/path entries with simple labels')
        result[label] = Path(path).resolve(strict=True)
    return result


def verify_runtime(runtime: Path) -> dict:
    contest = runtime / 'opt/contest'
    evaluator = contest / 'evaluator'
    checksums = evaluator / 'checksums.sha256'
    expected = {}
    for line in checksums.read_text().splitlines():
        checksum, name = line.split(maxsplit=1)
        path = evaluator / name.strip().lstrip('*')
        actual = digest(path)
        if actual != checksum:
            raise ValueError(f'Fixed evaluator checksum mismatch: {path}')
        expected[name] = actual
    return {
        'image_manifest': read_json(evaluator / 'manifest.json'),
        'verified_checksums': expected,
        'final_report_sha256': digest(contest / 'evaluator-flow/OpenROAD-3D/flow/scripts/final_report.tcl'),
        'hbt_parasitics_sha256': digest(contest / 'evaluator-flow/OpenROAD-3D/flow/scripts/add_hbt_parasitics.tcl'),
        'legality_validator_sha256': digest(contest / 'validation/validate_submission.py'),
    }


def fingerprint_public_inputs(input_root: Path, case: str) -> dict:
    case_root = input_root / 'cases' / case
    if not case_root.is_dir():
        case_root = input_root / case
    files = {}
    for label, directory in (('case', case_root), ('platforms', input_root / 'platforms')):
        if not directory.is_dir():
            raise ValueError(f'Public input directory missing: {directory}')
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                files[label + '/' + str(path.relative_to(directory))] = digest(path)
    return {'sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            'files': files}


def evaluate(label: str, source: Path, args: argparse.Namespace, provenance: dict, batch: str, reuse: Path | None) -> dict:
    if source.is_dir():
        source = source / '5_1_grt.odb'
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f'Candidate ODB missing or empty: {source}')
    case_root = args.input_root / 'cases' / args.case
    if not case_root.is_dir():
        case_root = args.input_root / args.case
    source_sha = digest(source)
    report = args.output_root / args.case / f'{label}-{source_sha[:12]}' / batch
    canonical = report / 'canonical'
    canonical.mkdir(parents=True)
    copied_source = report / 'input/5_1_grt.odb'
    copied_source.parent.mkdir()
    shutil.copy2(source, copied_source)
    if digest(copied_source) != source_sha:
        raise ValueError('Candidate ODB changed while copying it into the isolated experiment')
    work = REPOSITORY / '.contest/optimization_v2' / args.case / f'{label}-{batch}'
    runtime = args.runtime_root
    contest = runtime / 'opt/contest'
    fixed = contest / 'evaluator-flow/OpenROAD-3D'
    env = dict(os.environ)
    # Keep user routing knobs from changing an otherwise fixed evaluator pass.
    for name in ('GRT_PREPARE_TCL', 'MLS_CONFIG', 'MLS_ENABLE', 'GLOBAL_ROUTE_ARGS', 'GLOBAL_ROUTING_LAYER_ADJUSTMENT', 'OR_SEED', 'OR_K'):
        env.pop(name, None)
    env.update({
        'CONTEST_ROOT': str(REPOSITORY), 'CONTEST_LIB': str(contest / 'lib/common.sh'),
        'CONTEST_CONFIG': str(contest / 'config/contest.env'), 'CONTEST_BIN_ROOT': str(contest / 'bin'),
        'CONTEST_VALIDATION_ROOT': str(contest / 'validation'), 'EVALUATOR_ROOT': str(contest / 'evaluator'),
        'EVALUATOR_OPENROAD_REAL': str(runtime / 'openroad-eval-native'),
        'EVALUATOR_FINAL_REPORT_TCL': str(fixed / 'flow/scripts/final_report.tcl'),
        'EVALUATOR_HBT_PARASITICS_TCL': str(fixed / 'flow/scripts/add_hbt_parasitics.tcl'),
        'EVALUATOR_FIXED_OPEN3D_ROOT': str(fixed), 'CONTEST_EVALUATOR_MODE': '1',
        'CONTEST_EVAL_THREADS': str(args.threads), 'NUM_CORES': str(args.threads),
        'OMP_NUM_THREADS': str(args.threads), 'WORK_ROOT': str(work),
        'MATERIALIZED_OPEN3D': str(work / 'OpenROAD-3D'),
        'FLOW_HOME': str(work / 'OpenROAD-3D/flow'),
        'EVAL_SUBMISSION_ODB': str(copied_source), 'EVAL_SNAPSHOT_DEF': str(canonical / 'submission.def'),
        'EVAL_SNAPSHOT_GUIDE': str(canonical / 'route.guide'), 'EVAL_SNAPSHOT_ODB': str(canonical / '5_1_grt.odb'),
        'BOTTOM_DIE_MIN_LAYER': 'metal2', 'BOTTOM_DIE_MAX_LAYER': 'metal10',
        'BOTTOM_DRT_MIN_LAYER': 'metal1', 'UPPER_DIE_MIN_LAYER': 'metal11', 'UPPER_DIE_MAX_LAYER': 'metal20',
        'HBT_RESISTANCE_OHM': '3.0', 'HBT_CAPACITANCE_FF': '0.6',
    })
    commands = [
        [str(contest / 'evaluator/bin/openroad_eval'), '-exit', '-no_init', str(contest / 'validation/snapshot_submission.tcl')],
        ['python3', str(contest / 'validation/validate_submission.py'), '--reference-def', str(case_root / 'grt_input/4_1_cts.def'),
         '--submission-def', str(canonical / 'submission.def'), '--canonical-guide', str(canonical / 'route.guide'),
         '--die-list-dir', str(canonical / 'die_net_lists'), '--report', str(report / 'legality.json')],
        [str(contest / 'evaluator/bin/evaluate'), '--case', args.case, '--input', str(case_root),
         '--submission', str(canonical / '5_1_grt.odb'), '--guide', str(canonical / 'route.guide'),
         '--report-dir', str(report), '--threads', str(args.threads)],
    ]
    record = {
        'scope': 'local_native_fixed_evaluator_not_official_score', 'case': args.case, 'label': label,
        'source_odb': str(source), 'source_odb_sha256': source_sha, 'report_dir': str(report),
        'work_dir': str(work), 'threads': args.threads, 'end_iter': args.end_iter,
        'official_iteration_setting': args.end_iter == 2, 'provenance': provenance,
        'routing_manifest': read_json(source.parent / 'run_manifest.json'),
        'commands': commands, 'environment': {key: env[key] for key in env if key.startswith(('CONTEST_', 'EVALUATOR_', 'EVAL_', 'WORK_ROOT', 'MATERIALIZED_', 'HBT_', 'BOTTOM_', 'UPPER_', 'NUM_CORES', 'OMP_', 'FLOW_HOME'))},
        'status': 'snapshot_started',
    }
    start = time.monotonic()
    write_json(report / 'experiment.json', record)
    print(f'{label}: canonical snapshot + legality -> {report}', flush=True)
    snapshot_code = run(commands[0], env, report / 'snapshot.log')
    if snapshot_code or not (canonical / '5_1_grt.odb').is_file():
        record.update(status='snapshot_failed', snapshot_exit_code=snapshot_code)
    else:
        validation_code = run(commands[1], env, report / 'validation.log')
        legality = read_json(report / 'legality.json')
        record.update(legal=legality.get('legal', False), legality_exit_code=validation_code)
        if validation_code or legality.get('legal') is not True:
            record['status'] = 'illegal'
        elif args.legality_only:
            record['status'] = 'legal_only'
        elif reuse:
            if args.end_iter != 2:
                raise ValueError('Reuse of first-version full metrics requires --end-iter 2')
            reused_record = read_json(reuse / 'experiment.json')
            if reused_record and (reused_record.get('status') not in ('complete', 'complete_reused')
                                  or reused_record.get('end_iter') != 2):
                raise ValueError('Cached experiment is not a completed final-iteration evaluation')
            prior_provenance = reused_record.get('provenance')
            if prior_provenance and any(prior_provenance.get(key) != provenance.get(key)
                                        for key in ('verified_checksums', 'final_report_sha256', 'hbt_parasitics_sha256')):
                raise ValueError('Cached experiment uses different fixed evaluator sources')
            prior_inputs = (prior_provenance or {}).get('public_input_fingerprint')
            if prior_inputs and prior_inputs != provenance['public_input_fingerprint']:
                raise ValueError('Cached experiment uses different public input/SDC/platform files')
            record['reuse_public_input_identity'] = ('verified_matching_fingerprint' if prior_inputs
                                                       else 'legacy_trusted_unchanged_public_inputs')
            # ODB-side canonical DEF and guides must match. Candidate-side loose
            # route.guide / net-list files are never used as trusted input.
            reused_canonical = reuse / 'canonical' if (reuse / 'canonical').is_dir() else reuse
            for name in ('submission.def', 'route.guide'):
                if digest(canonical / name) != digest(reused_canonical / name):
                    raise ValueError(f'Cached canonical {name} differs: {reuse}')
            metrics = read_json(reuse / 'metrics.json')
            if metrics.get('case') != args.case or metrics.get('legal') is not True:
                raise ValueError('Cached metrics have a different case or are not legal')
            shutil.copy2(reuse / 'metrics.json', report / 'metrics.json')
            for name in ('5_route_drc.rpt', '5_2_route.log', '6_report.json', '6_report.log', 'wirelength.rpt'):
                if (reuse / name).is_file():
                    shutil.copy2(reuse / name, report / name)
            record.update(status='complete_reused', evaluation_reused_from=str(reuse), full_drt_executed=False)
        else:
            if args.end_iter != 2:
                # The private launcher pins the final iteration to 2. A local
                # screening wrapper changes only the make argument; source and
                # evaluator binaries remain byte-identical. Final runs use 2.
                tools = report / 'screening_tools'
                tools.mkdir()
                real_make = shutil.which('make')
                wrapper = tools / 'make'
                wrapper.write_text('#!/usr/bin/env python3\nimport os,sys\n' +
                    f'args=["DETAILED_ROUTE_ARGS=-droute_end_iter {args.end_iter}" if x=="DETAILED_ROUTE_ARGS=-droute_end_iter 2" else x for x in sys.argv[1:]]\n' +
                    f'os.execv({real_make!r},[{real_make!r},*args])\n')
                wrapper.chmod(0o755)
                env['PATH'] = str(tools) + ':' + env['PATH']
                record['screening_make_wrapper'] = {'path': str(wrapper), 'sha256': digest(wrapper)}
            record['status'] = 'evaluation_started'
            write_json(report / 'experiment.json', record)
            print(f'{label}: fixed DRT/STA threads={args.threads}, end_iter={args.end_iter}', flush=True)
            eval_code = run(commands[2], env, report / 'evaluate.log')
            record.update(evaluation_exit_code=eval_code, full_drt_executed=True)
            timing_report = read_json(report / '6_report.json')
            if eval_code or not (report / 'metrics.json').is_file():
                record['status'] = 'evaluation_failed'
            elif not {'finish__timing__setup__tns', 'finish__timing__setup__ws'} <= timing_report.keys():
                record['status'] = 'timing_metrics_missing'
            else:
                augment = ['python3', str(contest / 'validation/augment_metrics.py'), '--metrics', str(report / 'metrics.json'), '--legality', str(report / 'legality.json')]
                augment_code = run(augment, env, report / 'augment.log')
                record['status'] = 'complete' if augment_code == 0 else 'augmentation_failed'
    record['elapsed_seconds'] = round(time.monotonic() - start, 3)
    record['metrics'] = read_json(report / 'metrics.json')
    write_json(report / 'experiment.json', record)
    print(f'{label}: {record["status"]}; elapsed={record["elapsed_seconds"]}s', flush=True)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True)
    parser.add_argument('--candidate', action='append', required=True, help='label=/path/to/ODB or its directory')
    parser.add_argument('--reuse-report', action='append', default=[], help='label=/path/to/complete previous report')
    parser.add_argument('--input-root', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output-root', type=Path, default=REPOSITORY / 'reports/optimization_v2')
    parser.add_argument('--runtime-root', type=Path, default=Path('/tmp/open3dbench-contest-extracted'))
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--end-iter', type=int, default=2)
    parser.add_argument('--legality-only', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.case):
        parser.error('--case must be a simple case name')
    if not 1 <= args.threads <= 32 or args.jobs < 1 or args.threads * args.jobs > 32:
        parser.error('threads must be 1–32 and threads * jobs <= 32')
    if not 0 <= args.end_iter <= 2:
        parser.error('--end-iter must be 0, 1, or 2; final comparison requires 2')
    candidates, reused = labels(args.candidate), labels(args.reuse_report)
    if reused.keys() - candidates.keys():
        parser.error('--reuse-report labels must also be --candidate labels')
    for key in ('input_root', 'output_root', 'runtime_root'):
        setattr(args, key, getattr(args, key).resolve())
    args.output_root.mkdir(parents=True, exist_ok=True)
    provenance = verify_runtime(args.runtime_root)
    provenance['public_input_fingerprint'] = fingerprint_public_inputs(args.input_root, args.case)
    batch = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    summary = {'batch': batch, 'case': args.case, 'threads': args.threads, 'jobs': args.jobs, 'end_iter': args.end_iter, 'candidates': {}}
    failed = False
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(evaluate, label, source, args, provenance, batch, reused.get(label)): label for label, source in candidates.items()}
        for future in as_completed(futures):
            label = futures[future]
            try:
                record = future.result()
            except Exception as error:
                record = {'label': label, 'status': 'infrastructure_error', 'error': str(error)}
            summary['candidates'][label] = record
            failed |= record['status'] not in ('complete', 'complete_reused', 'legal_only')
            write_json(args.output_root / f'batch-{batch}.json', summary)
    print(f'Batch report: {args.output_root / ("batch-" + batch + ".json")}', flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
