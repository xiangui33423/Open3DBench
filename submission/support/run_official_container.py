#!/usr/bin/env python3
"""Launch a fresh submission build and evaluation in the official Docker image."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


def save(path: Path, data: dict) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='gaocr/3dbench-contest:20260914')
    parser.add_argument('--zip', dest='archive', type=Path)
    parser.add_argument('--input-root', type=Path)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--cases', nargs='+', default=['bp_fe', 'bp_be'])
    parser.add_argument('--evaluate-cases', nargs='*', default=['bp_fe'])
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--build-threads', type=int, default=8)
    parser.add_argument('--evaluation-jobs', type=int, default=2)
    parser.add_argument('--pull', action='store_true', help='Pull the selected official image if absent locally')
    args = parser.parse_args()
    if not 1 <= args.threads <= 32 or not 1 <= args.build_threads <= 32:
        parser.error('threads and build-threads must be 1..32')
    if args.evaluation_jobs < 1 or args.evaluation_jobs * args.threads > 32:
        parser.error('evaluation-jobs * threads must be at most 32')
    if set(args.evaluate_cases) - set(args.cases):
        parser.error('evaluate-cases must be a subset of cases')
    if not args.image.startswith('gaocr/3dbench-contest:'):
        parser.error('--image must name an official gaocr/3dbench-contest tag')
    repository = Path(__file__).resolve().parents[2]
    archive = (args.archive or repository / 'submission.zip').resolve(strict=True)
    inputs = (args.input_root or repository / 'Open3DBench-offline-20260904/Open3DBench/input/open3dbench_8cases_post_hbt_input_20260724').resolve(strict=True)
    driver = repository / 'submission/support/verify_official_container.py'
    if not driver.is_file():
        parser.error(f'Container driver missing: {driver}')
    # All read-only inputs remain under the single repository mount.
    for path in (archive, inputs):
        if not path.is_relative_to(repository):
            parser.error(f'Input must be inside the repository: {path}')
    output_parent = (args.output_root or repository / 'reports/official_container').resolve()
    if not output_parent.is_relative_to(repository):
        parser.error('--output-root must be inside the repository')
    batch = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    run = output_parent / ('host-' + batch)
    run.mkdir(parents=True)
    (run / 'home').mkdir()
    captured_archive = run / 'host_submission.zip'
    shutil.copy2(archive, captured_archive)
    manifest_path = run / 'host_verification.json'
    manifest = {'scope': 'official_docker_container_validation', 'status': 'preflight',
                'image_reference': args.image, 'archive': str(archive),
                'captured_archive': str(captured_archive),
                'archive_sha256': sha256(captured_archive), 'input_root': str(inputs),
                'container_started': False, 'report_root': str(run)}
    revision = subprocess.run(['git', '-C', str(repository), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True)
    manifest['source_commit'] = revision.stdout.strip()
    save(manifest_path, manifest)
    print(f'Host record: {manifest_path}', flush=True)
    try:
        version = subprocess.run(['docker', 'version', '--format', '{{json .}}'],
                                 capture_output=True, text=True)
        (run / 'docker_preflight.log').write_text(version.stdout + version.stderr)
        if version.returncode:
            manifest.update(status='blocked_docker_access', error=version.stderr.strip())
            save(manifest_path, manifest)
            print(version.stderr.strip(), file=sys.stderr)
            return 2
        manifest['docker_version'] = json.loads(version.stdout)
        context = subprocess.run(['docker', 'context', 'show'], capture_output=True, text=True)
        manifest['docker_context'] = context.stdout.strip()
        inspect_command = ['docker', 'image', 'inspect', args.image]
        inspection = subprocess.run(inspect_command, capture_output=True, text=True)
        if inspection.returncode and args.pull:
            print(f'Pulling official image: {args.image}', flush=True)
            with (run / 'docker_pull.log').open('w') as log:
                pulled = subprocess.run(['docker', 'pull', args.image], stdout=log, stderr=subprocess.STDOUT)
            if pulled.returncode:
                raise RuntimeError(f'Official image pull failed; see {run / "docker_pull.log"}')
            inspection = subprocess.run(inspect_command, capture_output=True, text=True)
        if inspection.returncode:
            raise RuntimeError(f'Official image unavailable: {inspection.stderr.strip()}. Load the supplied image or use --pull.')
        image = json.loads(inspection.stdout)[0]
        manifest['image'] = {key: image.get(key) for key in
                             ('Id', 'RepoTags', 'RepoDigests', 'Created', 'Architecture', 'Os')}
        save(run / 'image_metadata.json', manifest['image'])
        if args.image.endswith(':20260724') and image['Id'] != 'sha256:2ecd5c5d8e77af0f436c13120703bf4af323215c637dc919cd1a481569c08834':
            raise RuntimeError('Offline official tag has an unexpected image ID')
        container_root = Path('/workspace/Open3DBench')
        container_run = container_root / run.relative_to(repository)
        container_driver = container_root / driver.relative_to(repository)
        driver_command = ['python3', str(container_driver), '--repository', str(container_root),
                          '--zip', str(container_root / captured_archive.relative_to(repository)),
                          '--input-root', str(container_root / inputs.relative_to(repository)),
                          '--run-dir', str(container_run), '--image-reference', args.image,
                          '--expected-zip-sha256', manifest['archive_sha256'],
                          '--image-id', image['Id'], '--threads', str(args.threads),
                          '--build-threads', str(args.build_threads),
                          '--evaluation-jobs', str(args.evaluation_jobs),
                          '--cases', *args.cases, '--evaluate-cases', *args.evaluate_cases]
        command = ['docker', 'run', '--rm', '--init', '--name', 'open3dbench-verify-' + batch.lower(),
                   '--user', f'{os.getuid()}:{os.getgid()}', '--ulimit', 'stack=-1:-1',
                   '-e', 'HOME=' + str(container_run / 'home'),
                   '-e', 'CONTEST_ROOT=' + str(container_root),
                   '-v', f'{repository}:{container_root}:ro',
                   '-v', f'{run}:{container_run}:rw', '-w', str(container_root),
                   '--entrypoint', '/usr/bin/python3', image['Id'], *driver_command[1:]]
        # Run the inspected immutable image ID. No host evaluator environment,
        # daemon socket, or /opt/contest replacement enters the container.
        manifest.update(status='container_running', command=command)
        save(manifest_path, manifest)
        print(f'Image: {args.image} ({image["Id"]})', flush=True)
        print(f'Container log: {run / "docker_run.log"}', flush=True)
        with (run / 'docker_run.log').open('w') as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1)
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end='', flush=True)
            returncode = process.wait()
        records = [run / 'verification.json'] if (run / 'verification.json').is_file() else []
        manifest['container_started'] = bool(records)
        manifest['container_records'] = [str(path) for path in records]
        manifest['docker_exit_code'] = returncode
        verified = returncode == 0 and len(records) == 1 and json.loads(records[0].read_text()).get('status') == 'complete'
        manifest['status'] = 'complete' if verified else 'failed'
        save(manifest_path, manifest)
        return 0 if verified else (returncode or 1)
    except (OSError, ValueError, RuntimeError) as error:
        manifest.update(status='failed', error=str(error))
        save(manifest_path, manifest)
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
