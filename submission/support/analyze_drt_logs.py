#!/usr/bin/env python3
"""Record DRT CPU timers and local log lifecycle wall times from existing runs."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def seconds(value: str) -> int:
    h, m, s = map(int, value.split(':'))
    return h * 3600 + m * 60 + s


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--work-root', action='append', required=True, help='label=/path/to/evaluator-work')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
analysis = {'scope': 'local_log_stage_analysis', 'runs': {}, 'notes': [
    'Final DRT-0267 CPU/elapsed counters describe detailed_route, not the whole OpenROAD process.',
    'Log birth-to-last-write lifecycle approximates process wall time including load and write overhead.',
    'The fixed post-hook process has no set_thread_count; its DRC uses the engine default (one thread).',
]}
for entry in args.work_root:
    label, _, location = entry.partition('=')
    runs = []
    for bottom_log in Path(location).rglob('drt_pass_bottom.log'):
        stages = {}
        for name in ('drt_pass_bottom.log', 'drt_pass_upper.log', 'drt_post_hooks.log', '6_report.log'):
            path = bottom_log.parent / name
            if not path.is_file():
                continue
            content = path.read_text(errors='replace')
            timers = re.findall(r'cpu time = (\d+:\d+:\d+), elapsed time = (\d+:\d+:\d+)', content)
            birth, modified = map(int, subprocess.check_output(['stat', '-c', '%W %Y', str(path)], text=True).split())
            stage = {'log': str(path.resolve()), 'file_lifecycle_seconds': modified - birth if birth > 0 else None}
            if timers:
                cpu, elapsed = (seconds(t) for t in timers[-1])
                stage.update(drt_cpu_seconds=cpu, drt_elapsed_seconds=elapsed,
                             cpu_to_elapsed_ratio=round(cpu / elapsed, 3) if elapsed else None)
            threads = re.search(r'DRT pass threads: (\d+)', content)
            if threads:
                stage['threads'] = int(threads[1])
            stages[name] = stage
        runs.append(stages)
    analysis['runs'][label] = runs
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(analysis, indent=2) + '\n')
print(args.output.resolve())
