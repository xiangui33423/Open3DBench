#!/usr/bin/env python3
"""Build the submitted ZIP and validate it inside the official Docker image.

This driver never calls Docker, a host OpenROAD, or a native extracted engine.
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
import stat
import subprocess
import time
import uuid
import zipfile


OFFICIAL = Path('/opt/contest')
BASE = OFFICIAL / 'openroad-base'
CONTEST = OFFICIAL / 'bin/contest'
EVALUATOR = OFFICIAL / 'evaluator'
VALIDATION = OFFICIAL / 'validation'
FIXED_FLOW = OFFICIAL / 'evaluator-flow/OpenROAD-3D'


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(data)
    return sha.hexdigest()


def write_manifest(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def clean_environment() -> dict[str, str]:
    # Keep no host/native evaluator, fake make, routing knob or library override.
    env = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME', 'TZ') if key in os.environ}
    env.update(PATH='/opt/contest/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
               LANG='C.UTF-8', LC_ALL='C.UTF-8')
    return env


def run_stage(command: list[str], env: dict[str, str], log: Path, cwd: Path) -> dict:
    print(f'Start: {command[0]} {command[1]} -> {log}', flush=True)
    start = time.monotonic()
    with log.open('w') as output:
        result = subprocess.run(command, env=env, cwd=cwd, stdout=output, stderr=subprocess.STDOUT)
    return {'command': command, 'log': str(log), 'exit_code': result.returncode,
            'wall_seconds': round(time.monotonic() - start, 3),
            'status': 'complete' if result.returncode == 0 else 'failed'}


def unpack_zip(archive: Path, destination: Path) -> None:
    destination.mkdir()
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination) or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f'Unsafe ZIP member: {member.filename}')
            source.extract(member, destination)
            if not member.is_dir():
                mode = (member.external_attr >> 16) & 0o777
                if mode:
                    target.chmod(mode & 0o755)
    for filename in ('build.sh', 'run.sh', 'openroad_overlay/src/grt/src/GlobalRouter.cpp'):
        if not (destination / filename).is_file():
            raise ValueError(f'ZIP lacks {filename} at its root')


def verify_official_image(env: dict[str, str], log: Path, cwd: Path) -> dict:
    if not Path('/.dockerenv').is_file():
        raise RuntimeError('Run this script inside the supplied official Docker image')
    for path in (BASE / 'CMakeLists.txt', CONTEST, EVALUATOR / 'bin/evaluate',
                 EVALUATOR / 'bin/openroad_eval.real', EVALUATOR / 'checksums.sha256',
                 VALIDATION / 'snapshot_submission.tcl', VALIDATION / 'validate_submission.py',
                 FIXED_FLOW / 'flow/scripts/final_report.tcl'):
        if not path.is_file():
            raise FileNotFoundError(f'Official image file missing: {path}')
    check = run_stage(['sha256sum', '-c', 'checksums.sha256'], env, log, EVALUATOR)
    if check['exit_code']:
        raise RuntimeError('Official evaluator checksum verification failed')
    revision = subprocess.run(['git', '-c', 'safe.directory=' + str(BASE), '-C', str(BASE), 'rev-parse', 'HEAD'],
                              env=env, text=True, capture_output=True)
    base_version = OFFICIAL / 'openroad-base.version'
    return {'docker_marker': True, 'base_source': str(BASE),
            'base_source_version_file': str(base_version),
            'base_source_version': base_version.read_text().strip() if base_version.is_file() else None,
            'base_git_commit': revision.stdout.strip() if revision.returncode == 0 else None,
            'checksum_check': check, 'evaluator_manifest': read_json(EVALUATOR / 'manifest.json'),
            'evaluator_sha256': digest(EVALUATOR / 'bin/evaluate'),
            'evaluator_openroad_sha256': digest(EVALUATOR / 'bin/openroad_eval.real'),
            'fixed_final_report_sha256': digest(FIXED_FLOW / 'flow/scripts/final_report.tcl')}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path('/workspace/Open3DBench'))
    parser.add_argument('--zip', dest='archive', type=Path)
    parser.add_argument('--input-root', type=Path)
    parser.add_argument('--platform-dir', type=Path)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--run-dir', type=Path, help='Host-prepared report directory; existing host metadata/home are allowed, driver artifacts are not')
    parser.add_argument('--expected-zip-sha256', help='SHA256 captured by the host launcher before starting Docker')
    parser.add_argument('--cases', nargs='+', default=['bp_fe', 'bp_be'])
    parser.add_argument('--evaluate-cases', nargs='*', default=['bp_fe'])
    parser.add_argument('--modes', nargs='+', choices=('mls', 'baseline'), default=['mls', 'baseline'])
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--build-threads', type=int, default=8)
    parser.add_argument('--evaluation-jobs', type=int, default=2)
    parser.add_argument('--image-reference', default='official image selected by host launcher')
    parser.add_argument('--image-id', help='Host docker inspect image ID, recorded as caller-supplied provenance')
    args = parser.parse_args()
    if not 1 <= args.threads <= 32 or not 1 <= args.build_threads <= 32:
        parser.error('threads and build-threads must be 1..32')
    if args.evaluation_jobs < 1 or args.evaluation_jobs * args.threads > 32:
        parser.error('evaluation-jobs * threads must be at most 32')
    if len(set(args.cases)) != len(args.cases) or len(set(args.modes)) != len(args.modes):
        parser.error('cases and modes must not contain duplicates')
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', case) for case in args.cases):
        parser.error('case names must use letters, numbers, underscore, dot or hyphen')
    if set(args.evaluate_cases) - set(args.cases):
        parser.error('evaluate-cases must be a subset of cases')
    repository = args.repository.resolve()
    archive = (args.archive or repository / 'submission.zip').resolve()
    inputs = (args.input_root or repository / 'Open3DBench-offline-20260904/Open3DBench/input/open3dbench_8cases_post_hbt_input_20260724').resolve()
    platform = (args.platform_dir or inputs / 'platforms/nangate45_3D').resolve()
    output = (args.output_root or repository / 'reports/official_container').resolve()
    if any('\n' in str(path) or '\r' in str(path) for path in (repository, archive, inputs, platform, output)):
        parser.error('paths must not contain newlines')
    batch = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    run = args.run_dir.resolve() if args.run_dir else output / batch
    if any((run / name).exists() for name in ('verification.json', 'unpacked_submission', 'fresh_build', 'cases')):
        parser.error('Run directory contains driver artifacts; choose a fresh run directory')
    run.mkdir(parents=True, exist_ok=True)
    manifest_path = run / 'verification.json'
    manifest = {'scope': 'official_docker_container_validation', 'batch': batch, 'status': 'initializing',
                'image_reference': args.image_reference, 'caller_supplied_image_id': args.image_id,
                'repository': str(repository), 'archive': str(archive), 'input_root': str(inputs),
                'platform_dir': str(platform), 'threads': args.threads, 'build_threads': args.build_threads,
                'evaluation_jobs': args.evaluation_jobs, 'expected_fixed_drt_end_iter': 2,
                'build': {'status': 'not_started'}, 'cases': {case: {} for case in args.cases}}
    write_manifest(manifest_path, manifest)
    env = clean_environment()
    try:
        if (run / 'image_metadata.json').is_file():
            manifest['host_image_metadata'] = read_json(run / 'image_metadata.json')
        manifest['container'] = verify_official_image(env, run / 'image_checksums.log', repository)
        if not archive.is_file() or not platform.is_dir():
            raise FileNotFoundError('Submission ZIP or platform input missing')
        cases = {}
        for case in args.cases:
            case_root = inputs / 'cases' / case
            if not case_root.is_dir():
                case_root = inputs / case
            for filename in ('4_1_cts.def', '4_cts.sdc'):
                if not (case_root / 'grt_input' / filename).is_file():
                    raise FileNotFoundError(case_root / 'grt_input' / filename)
            cases[case] = case_root
        manifest['input_sha256'] = {case: {filename: digest(path / 'grt_input' / filename)
                                             for filename in ('4_1_cts.def', '4_cts.sdc')}
                                    for case, path in cases.items()}
        captured_archive = run / 'source_submission.zip'
        shutil.copy2(archive, captured_archive)
        manifest['archive_sha256'] = digest(captured_archive)
        if args.expected_zip_sha256 and manifest['archive_sha256'] != args.expected_zip_sha256:
            raise ValueError('Submission ZIP SHA256 differs from the host launcher snapshot')
        submission = run / 'unpacked_submission'
        unpack_zip(captured_archive, submission)
        build_root = run / 'fresh_build'
        if build_root.exists():
            raise RuntimeError('Refusing a pre-existing build directory')
        build_env = dict(env, OPENROAD_BASE_ROOT=str(BASE), SUBMISSION_BUILD_DIR=str(build_root))
        manifest.update(status='building', build={'status': 'running', 'build_root': str(build_root), 'fresh_build': True})
        write_manifest(manifest_path, manifest)
        build = run_stage(['bash', str(submission / 'build.sh'), str(args.build_threads)], build_env, run / 'build.log', repository)
        binary = build_root / 'openroad-build/bin/openroad'
        build.update(build_root=str(build_root), fresh_build=True)
        manifest['build'] = build
        if build['exit_code'] or not binary.is_file() or not os.access(binary, os.X_OK):
            raise RuntimeError('Fresh public source compilation failed; no fallback executable is allowed')
        build.update(binary=str(binary), binary_sha256=digest(binary))
        manifest['status'] = 'routing_and_legality'
        write_manifest(manifest_path, manifest)
        successful = []
        for case in args.cases:
            for mode in args.modes:
                directory = run / 'cases' / case / mode
                directory.mkdir(parents=True)
                candidate = directory / 'submission'
                candidate.mkdir()
                public_env = dict(build_env, OPENROAD_EXE=str(binary))
                if mode == 'baseline':
                    public_env['MLS_ENABLE'] = '0'
                record = {'status': 'routing', 'candidate_dir': str(candidate)}
                manifest['cases'][case][mode] = record
                write_manifest(manifest_path, manifest)
                route = run_stage(['bash', str(submission / 'run.sh'), str(cases[case] / 'grt_input'),
                                   str(candidate), str(platform), str(args.threads)],
                                  public_env, directory / 'grt.log', repository)
                record['grt'] = route
                if route['exit_code'] or not (candidate / 'run_manifest.json').is_file() or not (candidate / '5_1_grt.odb').is_file():
                    record.update(status='grt_failed', evaluation={'status': 'skipped_grt_failed'})
                    write_manifest(manifest_path, manifest)
                    continue
                record['routing_manifest'] = read_json(candidate / 'run_manifest.json')
                record['source_odb_sha256'] = digest(candidate / '5_1_grt.odb')
                canonical = directory / 'canonical'
                canonical.mkdir()
                snapshot_env = dict(env, EVAL_SUBMISSION_ODB=str(candidate / '5_1_grt.odb'),
                                    EVAL_SNAPSHOT_DEF=str(canonical / 'submission.def'),
                                    EVAL_SNAPSHOT_GUIDE=str(canonical / 'route.guide'),
                                    EVAL_SNAPSHOT_ODB=str(canonical / '5_1_grt.odb'))
                snapshot = run_stage([str(EVALUATOR / 'bin/openroad_eval'), '-exit', '-no_init', str(VALIDATION / 'snapshot_submission.tcl')],
                                     snapshot_env, directory / 'snapshot.log', repository)
                record['snapshot'] = snapshot
                if snapshot['exit_code']:
                    record.update(status='snapshot_failed', evaluation={'status': 'skipped_snapshot_failed'})
                    write_manifest(manifest_path, manifest)
                    continue
                legality_path = directory / 'legality.json'
                legality = run_stage(['python3', str(VALIDATION / 'validate_submission.py'),
                                      '--reference-def', str(cases[case] / 'grt_input/4_1_cts.def'),
                                      '--submission-def', str(canonical / 'submission.def'),
                                      '--canonical-guide', str(canonical / 'route.guide'),
                                      '--die-list-dir', str(canonical / 'die_net_lists'), '--report', str(legality_path)],
                                     env, directory / 'legality.log', repository)
                record['legality_stage'] = legality
                record['legality'] = read_json(legality_path) if legality_path.is_file() else {}
                legal = legality['exit_code'] == 0 and record['legality'].get('legal') is True
                record['status'] = 'legal' if legal else 'illegal'
                record['evaluation'] = {'status': 'queued' if legal and case in args.evaluate_cases else 'not_requested' if legal else 'skipped_illegal'}
                if legal and case in args.evaluate_cases:
                    successful.append((case, mode, directory, candidate))
                write_manifest(manifest_path, manifest)

        def evaluate(item: tuple) -> tuple:
            case, mode, directory, candidate = item
            work = directory / 'official_evaluator_work'
            reports = directory / 'evaluation'
            reports.mkdir()
            eval_env = dict(env, CONTEST_ROOT=str(repository), WORK_ROOT=str(work),
                            MATERIALIZED_OPEN3D=str(work / 'OpenROAD-3D'), CONTEST_EVAL_THREADS=str(args.threads))
            result = run_stage([str(CONTEST), 'evaluate', case, str(inputs), str(candidate), str(reports)],
                               eval_env, directory / 'evaluate.log', repository)
            result.update(work_root=str(work), report_dir=str(reports), evaluator_invoked=True,
                          full_evaluation_completed=False)
            if result['exit_code'] == 0:
                try:
                    metrics = read_json(reports / 'metrics.json')
                    timing = read_json(reports / '6_report.json')
                    required = {'drc', 'drt_wirelength_um', 'tns_ns', 'wns_ns', 'legal', 'hbt_count'}
                    if not required <= metrics.keys() or metrics['legal'] is not True:
                        raise ValueError('Official evaluator returned missing or illegal metrics')
                    if not {'finish__timing__setup__tns', 'finish__timing__setup__ws'} <= timing.keys():
                        raise ValueError('Official final STA metrics are missing')
                    proof = {}
                    for filename in ('drt_pass_bottom.log', 'drt_pass_upper.log'):
                        logs = list(work.rglob(filename))
                        if len(logs) != 1:
                            raise ValueError('Expected one official DRT pass log: ' + filename)
                        content = logs[0].read_text(errors='replace')
                        match = re.search(r'detailed_route arguments:[^\n]*-droute_end_iter\s+(\d+)\b', content)
                        if match is None or int(match.group(1)) != 2:
                            raise ValueError('Official DRT did not confirm final iteration 2')
                        proof[filename] = {'path': str(logs[0]), 'sha256': digest(logs[0]), 'actual_drt_end_iter': int(match.group(1))}
                    result.update(metrics=metrics, fixed_iteration_log_proof=proof, actual_drt_end_iter=2,
                                  full_evaluation_completed=True)
                except Exception as error:
                    result.update(status='failed', error=str(error))
            return case, mode, result

        manifest['status'] = 'evaluating'
        write_manifest(manifest_path, manifest)
        with ThreadPoolExecutor(max_workers=args.evaluation_jobs) as pool:
            futures = {pool.submit(evaluate, item): item[:2] for item in successful}
            for future in as_completed(futures):
                case, mode = futures[future]
                try:
                    _, _, result = future.result()
                except Exception as error:
                    result = {'status': 'failed', 'error': str(error)}
                record = manifest['cases'][case][mode]
                record['evaluation'] = result
                record['status'] = 'complete' if result['status'] == 'complete' else 'evaluation_failed'
                write_manifest(manifest_path, manifest)
        failed = any(record['status'] not in ('legal', 'complete') for modes in manifest['cases'].values() for record in modes.values())
        manifest['status'] = 'failed' if failed else 'complete'
        write_manifest(manifest_path, manifest)
        print(f'Official container report: {manifest_path}', flush=True)
        return int(failed)
    except Exception as error:
        manifest.update(status='failed', error=str(error))
        write_manifest(manifest_path, manifest)
        print(f'Official container validation failed: {error}; report: {manifest_path}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
