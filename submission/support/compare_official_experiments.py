#!/usr/bin/env python3
"""Compare completed bp_fe official metrics without computing a contest score."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from verify_official_container import digest, write_manifest

REPOSITORY = Path(__file__).resolve().parents[2]


def host_path(value: str) -> Path:
    prefix = '/workspace/Open3DBench'
    if value == prefix or value.startswith(prefix + '/'):
        return REPOSITORY / value[len(prefix):].lstrip('/')
    return Path(value)


def metrics_values(metrics: dict, runtime: float) -> dict:
    keys = ('drc', 'drt_wirelength_um', 'tns_ns', 'wns_ns', 'hbt_count', 'hbt_excess_count')
    if metrics.get('legal') is not True or any(key not in metrics or not math.isfinite(float(metrics[key])) for key in keys):
        raise ValueError('Missing, nonfinite or illegal official metrics')
    if not math.isfinite(runtime) or runtime <= 0: raise ValueError('Invalid fresh entry runtime')
    return {**{key: metrics[key] for key in keys}, 'runtime_seconds': runtime}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, default=REPOSITORY / 'reports/optimization_v3/baseline_reference.json')
    parser.add_argument('--experiment', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-pending', action='store_true')
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())
    proof_path = host_path(reference['verification'])
    if digest(proof_path) != reference['verification_sha256']:
        raise ValueError('Original official v2 verification changed')
    original = json.loads(proof_path.read_text())
    if original.get('status') != 'complete': raise ValueError('Original official verification was not complete')
    rows = {}
    for mode, label in (('baseline', 'v2_MLS_off'), ('mls', 'v2_default')):
        record = original['cases']['bp_fe'][mode]; evaluation = record['evaluation']
        if record['status'] != 'complete' or evaluation.get('full_evaluation_completed') is not True or evaluation.get('actual_drt_end_iter') != 2:
            raise ValueError('Original baseline quality evaluation was incomplete')
        path = host_path(reference['metrics'][mode]['metrics_path'])
        if digest(path) != reference['metrics'][mode]['metrics_sha256']:
            raise ValueError('Original official quality metrics changed')
        raw = json.loads(path.read_text())
        if raw != evaluation['metrics']: raise ValueError('Original official metric record differs from disk')
        rm = host_path(reference['metrics'][mode]['routing_manifest_path'])
        if digest(rm) != reference['metrics'][mode]['routing_manifest_sha256']:
            raise ValueError('Original fresh runtime manifest changed')
        rows[label] = {'status': 'complete', 'values': metrics_values(raw, json.loads(rm.read_text())['runtime_seconds']),
                       'metrics_path': str(path), 'public_binary_sha256': reference['public_binary_sha256']}
    for path in args.experiment:
        experiment = json.loads(path.read_text())
        if experiment['image_id'] != reference['image_id']:
            raise ValueError('Experiment uses a different official image')
        container = experiment['container']
        if container['evaluator_openroad_sha256'] != reference['evaluator_openroad_sha256'] or container['evaluator_sha256'] != reference['evaluator_launcher_sha256']:
            raise ValueError('Experiment uses a different fixed official evaluator')
        if experiment['input_sha256']['bp_fe'] != reference['bp_fe_input_sha256']:
            raise ValueError('Experiment uses different public bp_fe DEF/SDC')
        for label, candidate in experiment['candidates'].items():
            if label in rows: raise ValueError('Duplicate comparison label: ' + label)
            record = candidate['cases']['bp_fe']; evaluation = record.get('evaluation', {})
            if record.get('status') == 'complete_reused' or evaluation.get('status') == 'complete_reused':
                raise ValueError('Historical official metric reuse lacks evaluation-time full platform identity; compare fresh actual evaluations')
            if record.get('status') != 'complete' or evaluation.get('full_evaluation_completed') is not True:
                if not args.allow_pending: raise ValueError('Candidate detailed evaluation not complete: ' + label)
                rows[label] = {'status': 'full_evaluation_pending_or_not_requested', 'experiment': str(path)}
                continue
            if evaluation.get('actual_drt_end_iter') != 2 or record['legality'].get('legal') is not True:
                raise ValueError('Candidate lacks fixed DRT2 or canonical legality')
            directory = host_path(evaluation['report_dir'])
            metrics = json.loads((directory / 'metrics.json').read_text())
            if metrics != evaluation['metrics'] or digest(directory / 'metrics.json') != evaluation['metrics_sha256']:
                raise ValueError('Candidate official metrics changed: ' + label)
            if digest(directory / '6_report.json') != evaluation['final_sta_sha256']:
                raise ValueError('Candidate final STA changed: ' + label)
            for proof in evaluation['fixed_iteration_log_proof'].values():
                if proof['actual_drt_end_iter'] != 2 or digest(host_path(proof['path'])) != proof['sha256']:
                    raise ValueError('Candidate fixed DRT pass evidence changed: ' + label)
            submitted = host_path(record['candidate_dir'])
            if digest(submitted / '5_1_grt.odb') != record['source_odb_sha256']:
                raise ValueError('Candidate submitted ODB changed: ' + label)
            runtime = json.loads((submitted / 'run_manifest.json').read_text())
            if runtime != record['routing_manifest']:
                raise ValueError('Candidate fresh runtime record changed: ' + label)
            row = {'status': 'complete', 'values': metrics_values(metrics, runtime['runtime_seconds']),
                   'metrics_path': str(directory / 'metrics.json'), 'experiment': str(path),
                   'source_zip_sha256': candidate['source_zip_sha256'], 'config_sha256': candidate['config_sha256'],
                   'public_binary_sha256': candidate['public_binary_sha256']}
            row['changes_vs_v2_default'] = {key: value - rows['v2_default']['values'][key] for key, value in row['values'].items()}
            rows[label] = row
    result = {'scope': 'same_fixed_official_bp_fe_metrics_comparison', 'image_id': reference['image_id'],
              'evaluator_openroad_sha256': reference['evaluator_openroad_sha256'], 'actual_drt_end_iter': 2,
              'runtime_note': 'Fresh entry wall times; concurrent workload differed. No weighted contest score is computed.',
              'rows': rows}
    write_manifest(args.output, result)
    lines = ['Official bp_fe experiment comparison', '',
             'Fixed official image/engine, same public DEF/SDC, actual DRT end_iter=2. Fresh entry times came from runs with differing concurrent load.', '',
             '| Candidate | DRC | DRT WL (um) | TNS (ns) | WNS (ns) | HBT / excess | Entry seconds |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for label, row in rows.items():
        if row['status'] != 'complete': lines.append(f'| {label} | pending / not requested | — | — | — | — | — |'); continue
        v = row['values']
        display_label = label
        lines.append(f"| {display_label} | {v['drc']} | {v['drt_wirelength_um']:.2f} | {v['tns_ns']:.2f} | {v['wns_ns']:.5f} | {v['hbt_count']} / {v['hbt_excess_count']} | {v['runtime_seconds']:.3f} |")
    args.output.with_suffix('.md').write_text('\n'.join(lines) + '\n')
    print(args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
