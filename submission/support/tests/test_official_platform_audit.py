"""Exercise ephemeral platform evidence with real, lightweight child processes."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SUPPORT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = load_module('platform_audit_common', SUPPORT / 'verify_official_container.py')
with patch.dict(sys.modules, {'official_common': common}):
    verifier = load_module('platform_audit_verifier', SUPPORT / 'verify_official_experiments.py')


CHILD = r'''
import json, pathlib, shutil, sys, time
source, target, evidence = map(pathlib.Path, sys.argv[1:4])
mode = sys.argv[4]
if mode == 'missing':
    sys.exit(0)
shutil.copytree(source, target)
if mode == 'different':
    (target / 'rc.rules').write_text('changed resistance')
    (target / 'extra.rules').write_text('additional collateral')
if mode == 'partial':
    print('[INFO][FLOW] Using platform ', end='', flush=True)
    time.sleep(0.2)
    print('directory ' + str(target), flush=True)
else:
    print('[INFO][FLOW] Using platform directory ' + str(target), flush=True)
deadline = time.monotonic() + 5
while not evidence.exists() and time.monotonic() < deadline:
    time.sleep(0.02)
shutil.rmtree(target.parents[3])
if not evidence.exists():
    sys.exit(3)
'''


class OfficialPlatformAuditTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.platform = self.root / 'inputs' / 'nangate45_3D'
        (self.platform / 'lib').mkdir(parents=True)
        (self.platform / 'lib' / 'timing.lib').write_text('timing collateral')
        (self.platform / 'rc.rules').write_text('resistance collateral')

    def run_child(self, mode='identical'):
        work = self.root / 'work'
        materialized = work / 'evaluator-submissions' / 'case_123' / 'OpenROAD-3D' / 'flow' / 'platforms' / self.platform.name
        command = [sys.executable, '-c', CHILD, str(self.platform), str(materialized),
                   str(self.root / 'evaluation_platform.json'), mode]
        stage = verifier.run_evaluation_with_platform_audit(command, os.environ.copy(),
            self.root / 'evaluate.log', self.root, work, self.platform,
            verifier.platform_fingerprint(self.platform))
        evidence = json.loads((self.root / 'evaluation_platform.json').read_text())
        self.assertEqual(stage['command'], command)
        self.assertFalse(materialized.exists())
        return stage, evidence

    def test_evidence_survives_official_style_cleanup(self):
        stage, evidence = self.run_child()
        self.assertEqual(stage['status'], 'complete')
        self.assertTrue(evidence['observed_while_evaluator_running'])
        self.assertEqual(evidence['input_file_sha256'], evidence['materialized_file_sha256'])
        self.assertEqual(evidence['file_count'], 2)
        self.assertEqual(stage['platform_audit']['sha256'],
                         common.digest(self.root / 'evaluation_platform.json'))

    def test_changed_and_additional_collateral_fail_even_with_successful_evaluator(self):
        stage, evidence = self.run_child('different')
        self.assertEqual(stage['exit_code'], 0)
        self.assertEqual(stage['status'], 'failed')
        self.assertEqual(evidence['status'], 'mismatch')
        self.assertEqual(evidence['difference']['changed'], ['rc.rules'])
        self.assertEqual(evidence['difference']['unexpected'], ['extra.rules'])

    def test_missing_live_snapshot_is_not_treated_as_verified(self):
        stage, evidence = self.run_child('missing')
        self.assertEqual(stage['exit_code'], 0)
        self.assertEqual(stage['status'], 'failed')
        self.assertEqual(evidence['status'], 'failed')
        self.assertNotIn('materialized_file_sha256', evidence)

    def test_partial_log_lines_are_reassembled(self):
        stage, evidence = self.run_child('partial')
        self.assertEqual(stage['status'], 'complete')
        self.assertTrue(evidence['matches_input'])

    def test_symlinked_collateral_is_not_silently_omitted(self):
        (self.platform / 'linked-library').symlink_to(self.platform / 'lib', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'non-regular'):
            verifier.platform_fingerprint(self.platform)

    def test_mutation_during_hashing_is_rejected(self):
        original = verifier.digest
        def mutate(path):
            result = original(path)
            if path.name == 'rc.rules':
                path.write_text('mutated after reading')
            return result
        with patch.object(verifier, 'digest', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'changed while'):
                verifier.platform_fingerprint(self.platform)

    def test_full_fingerprint_includes_additional_non_lef_files(self):
        fingerprints = verifier.platform_fingerprint(self.platform)
        self.assertEqual(set(fingerprints), {'lib/timing.lib', 'rc.rules'})
        difference = verifier.platform_difference(fingerprints, {'rc.rules': fingerprints['rc.rules']})
        self.assertEqual(difference['missing'], ['lib/timing.lib'])


if __name__ == '__main__':
    unittest.main()
