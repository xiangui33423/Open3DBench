"""Verify published source/evidence integrity; does not run the physical evaluator."""
import hashlib
import json
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = read(HERE / 'source_manifest.json')
    report = read(HERE / 'results.json')
    for name, expected in manifest['source_sha256'].items():
        assert sha(ROOT / manifest['source_directory'] / name) == expected, name
    assert report['submission_sha256'] == manifest['archive_sha256']
    baseline = {r['case']: r for r in read(HERE / report['baseline'])['cases']}
    completed = []
    failed = []
    for row in report['cases']:
        if row['status'] == 'failed':
            failed.append(row)
            assert row['metrics'] is None and row['reduction_percent'] is None
            failure = read(HERE / row['failure_report'])
            assert failure['exit_code'] != 0 and not failure['evaluation_started']
            for attempt in failure['attempts']:
                assert sha(HERE / attempt['log']) == attempt['log_sha256']
            continue
        assert row['status'] == 'complete'
        completed.append(row)
        metrics = read(HERE / row['metrics_file'])
        assert sha(HERE / row['metrics_file']) == row['metrics_sha256']
        assert metrics == row['metrics']
        legality = read(HERE / row['legality_file'])
        assert metrics['legal'] and metrics['legality_error_count'] == 0
        assert legality['legal'] and not legality['errors']
        assert metrics['hbt_excess_count'] == 0
        for key, recorded in row['reduction_percent'].items():
            reference = baseline[row['case']][key]
            assert row['baseline'][key] == reference
            reduction = 100 * (abs(reference) - abs(metrics[key])) / abs(reference)
            assert abs(reduction - recorded) < 1e-10
    assert len(completed) == report['completed_cases'] == 7
    assert len(failed) == report['failed_cases'] == 1
    assert len(completed) + len(failed) == report['total_cases'] == 8
    assert not report['all_cases_passed']
    assert report['overall_eight_case_improvement'] is None
    for key, recorded in report['successful_case_subset']['equal_case_mean_reduction_percent'].items():
        assert abs(mean(r['reduction_percent'][key] for r in completed) - recorded) < 1e-10
    print(f"Verified {len(manifest['source_sha256'])} source files and all 8 recorded outcomes.")
    print('Physical evaluation outcomes: 7 successful, bp_quad failed (GRT-0228).')
    print('This integrity check is not a fresh physical evaluation.')


if __name__ == '__main__':
    main()
