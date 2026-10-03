#!/usr/bin/env python3
"""Run discovered public inputs with one generic router; optionally evaluate."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def main() -> int:
    parser = argparse.ArgumentParser(description='批量运行公开输入，可比较同一入口的 baseline / MLS')
    parser.add_argument('input_root', type=Path)
    parser.add_argument('output_root', type=Path)
    parser.add_argument('--platform-dir', type=Path)
    parser.add_argument('--cases', nargs='+', help='默认发现输入目录中的全部 case')
    parser.add_argument('--threads', type=int, default=32)
    parser.add_argument('--mode', choices=('mls', 'baseline', 'both'), default='mls')
    parser.add_argument('--evaluate', action='store_true', help='每次运行后调用官方 contest evaluate')
    parser.add_argument('--contest-exe', default='contest')
    args = parser.parse_args()
    if not 1 <= args.threads <= 32:
        parser.error('--threads must be between 1 and 32')
    if args.evaluate and not shutil.which(args.contest_exe):
        parser.error(f'Official evaluator command not found: {args.contest_exe}')
    root = Path(__file__).resolve().parent
    inputs = args.input_root.resolve(strict=True)
    outputs = args.output_root.resolve()
    cases_root = inputs / 'cases' if (inputs / 'cases').is_dir() else inputs
    platform = (args.platform_dir or inputs / 'platforms/nangate45_3D').resolve(strict=True)
    available = {path.name: path for path in cases_root.iterdir() if (path / 'grt_input/4_1_cts.def').is_file()}
    cases = args.cases or sorted(available)
    if not cases or any(name not in available for name in cases):
        parser.error(f'Unknown or absent cases; available: {", ".join(sorted(available))}')
    outputs.mkdir(parents=True, exist_ok=True)
    summary = {'threads': args.threads, 'mode': args.mode, 'evaluated': args.evaluate, 'cases': {}}
    failed = False
    variants = ['baseline', 'mls'] if args.mode == 'both' else [args.mode]
    for case in cases:
        summary['cases'][case] = {}
        for variant in variants:
            destination = outputs / case / variant
            destination.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, MLS_ENABLE='0' if variant == 'baseline' else '1', CONTEST_EVAL_THREADS=str(args.threads))
            log = destination / 'entry.log'
            command = ['bash', str(root / 'run.sh'), str(available[case] / 'grt_input'), str(destination), str(platform), str(args.threads)]
            print(f'{case}/{variant}: {destination}', flush=True)
            start = time.monotonic()
            with log.open('w') as stream:
                result = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT)
            record = {'exit_code': result.returncode, 'elapsed_seconds': round(time.monotonic() - start, 3), 'log': str(log)}
            if result.returncode == 0:
                record['run'] = load_json(destination / 'run_manifest.json')
                record['plan'] = load_json(destination / 'mls_plan.json').get('stats', {})
                if args.evaluate:
                    reports = outputs / case / f'{variant}_reports'
                    eval_log = destination / 'evaluate.log'
                    reports.mkdir(parents=True, exist_ok=True)
                    # A failed run must not report metrics from an older run.
                    (reports / 'metrics.json').unlink(missing_ok=True)
                    with eval_log.open('w') as stream:
                        evaluation = subprocess.run([args.contest_exe, 'evaluate', case, str(inputs), str(destination), str(reports)], env=env, stdout=stream, stderr=subprocess.STDOUT)
                    record['evaluation_exit_code'] = evaluation.returncode
                    record['metrics'] = load_json(reports / 'metrics.json') if evaluation.returncode == 0 else {}
                    if evaluation.returncode == 0 and not record['metrics']:
                        record['evaluation_error'] = 'Evaluator succeeded without fresh metrics.json'
                        failed = True
                    record['evaluation_log'] = str(eval_log)
                    failed |= evaluation.returncode != 0
            else:
                failed = True
            summary['cases'][case][variant] = record
            (outputs / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
            print(f'  exit={result.returncode}; elapsed={record["elapsed_seconds"]}s', flush=True)
    print(f'批量结果: {outputs / "summary.json"}', flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
