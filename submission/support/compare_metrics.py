#!/usr/bin/env python3
"""Compare real metrics without treating evaluator wall time as GRT runtime."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def read_report(path: Path) -> tuple[dict, dict]:
    if path.is_file():
        metrics = json.loads(path.read_text())
        path = path.parent
    else:
        metrics = json.loads((path / 'metrics.json').read_text())
    experiment = path / 'experiment.json'
    metadata = json.loads(experiment.read_text()) if experiment.is_file() else {}
    return metrics, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', action='append', required=True, help='label=/path/to/report')
    parser.add_argument('--baseline-run-manifest', type=Path)
    parser.add_argument('--candidate-run-manifest', action='append', default=[], help='label=/path/to/runtime manifest; adjacent ODB must match evaluated bytes')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline, baseline_metadata = read_report(args.baseline)
    if baseline_metadata and baseline_metadata.get('status') not in ('complete', 'complete_reused'):
        raise ValueError('Baseline evaluation is not complete')
    if baseline_metadata.get('end_iter', 2) != 2:
        raise ValueError('Baseline uses screening iterations rather than final iteration 2')
    baseline_runtime_attribution = 'experiment_routing_manifest'
    if args.baseline_run_manifest:
        expected = baseline_metadata.get('source_odb_sha256')
        if expected:
            if digest(args.baseline_run_manifest.parent / '5_1_grt.odb') != expected:
                raise ValueError('Baseline runtime override ODB differs from the evaluated ODB')
            baseline_runtime_attribution = 'explicit_manifest_with_verified_source_odb_digest'
        else:
            baseline_runtime_attribution = 'legacy_trusted_manifest_without_source_odb_digest'
    baseline_run = json.loads(args.baseline_run_manifest.read_text()) if args.baseline_run_manifest else baseline_metadata.get('routing_manifest', {})
    runtime_overrides = {}
    for entry in args.candidate_run_manifest:
        label, _, location = entry.partition('=')
        runtime_overrides[label] = Path(location)
    comparisons = {}
    for entry in args.candidate:
        label, _, location = entry.partition('=')
        metrics, metadata = read_report(Path(location))
        if metrics.get('case') != baseline.get('case'):
            raise ValueError('Comparison case differs')
        if metrics.get('legal') is not True or baseline.get('legal') is not True:
            raise ValueError('Cannot compare illegal or unvalidated metrics')
        if metadata and metadata.get('status') not in ('complete', 'complete_reused'):
            raise ValueError('Candidate evaluation is not complete')
        if metadata.get('end_iter', 2) != 2 or baseline_metadata.get('end_iter', 2) != 2:
            raise ValueError('Screening iteration metrics cannot be compared to final iteration 2')
        baseline_provenance, candidate_provenance = baseline_metadata.get('provenance', {}), metadata.get('provenance', {})
        for key in ('verified_checksums', 'final_report_sha256', 'hbt_parasitics_sha256', 'public_input_fingerprint'):
            if key in baseline_provenance and key in candidate_provenance and baseline_provenance[key] != candidate_provenance[key]:
                raise ValueError(f'Comparison uses different fixed evaluator or public inputs: {key}')
        fields = {}
        for field in ('tns_ns', 'wns_ns', 'drc', 'drt_wirelength_um', 'hbt_count', 'hbt_excess_count'):
            old, new = baseline[field], metrics[field]
            old_loss, new_loss = (max(0.0, -old), max(0.0, -new)) if field in ('tns_ns', 'wns_ns') else (old, new)
            fields[field] = {'baseline': old, 'candidate': new, 'delta': new - old,
                             'improvement_pct': 100 * (old_loss - new_loss) / old_loss if old_loss else None}
        candidate_run = metadata.get('routing_manifest', {})
        if label in runtime_overrides:
            runtime_path = runtime_overrides[label]
            if digest(runtime_path.parent / '5_1_grt.odb') != metadata.get('source_odb_sha256'):
                raise ValueError('Runtime override ODB differs from the evaluated ODB')
            candidate_run = json.loads(runtime_path.read_text())
        if 'runtime_seconds' in baseline_run and 'runtime_seconds' in candidate_run:
            old, new = baseline_run['runtime_seconds'], candidate_run['runtime_seconds']
            fields['algorithm_runtime_seconds'] = {'baseline': old, 'candidate': new, 'delta': new - old,
                                                   'improvement_pct': 100 * (old - new) / old if old else None,
                                                   'same_thread_count': baseline_run.get('threads') == candidate_run.get('threads')}
        comparisons[label] = {'report_dir': location, 'fields': fields,
                              'evaluator_runtime_seconds': metrics.get('evaluator_runtime_seconds'),
                              'evaluation_reused_from': metadata.get('evaluation_reused_from'),
                              'runtime_override_manifest': str(runtime_overrides[label].resolve()) if label in runtime_overrides else None}
    result = {'scope': 'local_native_fixed_evaluator_not_official_score', 'case': baseline['case'],
              'baseline_report': str(args.baseline.resolve()), 'comparisons': comparisons,
              'baseline_runtime_attribution': baseline_runtime_attribution,
              'baseline_runtime_manifest': str(args.baseline_run_manifest.resolve()) if args.baseline_run_manifest else None,
              'notes': ['Positive improvement_pct means lower loss; negative timing slack is converted to positive loss.',
                        'Zero baseline loss gives null improvement_pct.',
                        'Evaluator runtime is separate from algorithm runtime; no weighted contest score is inferred.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
