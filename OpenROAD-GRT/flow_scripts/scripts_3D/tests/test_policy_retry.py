"""Behavioral checks for the frozen, bounded routing policy retry.

These tests import the actual submission entry point. Two subprocess tests exercise
the real run_openroad launcher with a small deterministic executable, so that
the retry contract is checked beyond a mocked return value. They validate
process/input isolation, not real OpenROAD route legality or timing.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get("POLICY_RETRY_SOURCE", str(HERE.parents[3] / "submission"))).resolve()
sys.path.insert(0, str(SOURCE / "src"))
SPEC = importlib.util.spec_from_file_location("frozen_safe_router", SOURCE / "src/run_router.py")
assert SPEC is not None and SPEC.loader is not None
ROUTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUTER)
# Pinned original v15 configuration identity; ordinary tests do not require
# the ignored historical reports directory to be present.
VALIDATED_V15_CONFIG_SHA256 = "60bfc59a0064f58869050fb6b0f1cedc10cc44accec140ad4a74f192429259d3"


class PolicyRetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "submission"
        self.config_dir = self.root / "flow_scripts/scripts_3D"
        self.config_dir.mkdir(parents=True)
        self.requested = self.config_dir / "mls_config.json"
        self.fallback = self.config_dir / "mls_fallback_config.json"
        self.requested.write_bytes((SOURCE / "flow_scripts/scripts_3D/mls_config.json").read_bytes())
        self.fallback.write_bytes((SOURCE / "flow_scripts/scripts_3D/mls_fallback_config.json").read_bytes())
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.log = self.logs / "global_route.log"
        self.env = {"MLS_CONFIG": str(self.requested),
                    "GRT_INITIAL_DESIGN": "4_1_cts.def",
                    "GRT_PROCESS_MODE": "single",
                    "IMMUTABLE_ORIGINAL": "preserve-me"}

    def invoke(self):
        return ROUTER.route_with_policy_retry("/fixture/openroad", self.root, self.env, self.logs)

    def failure(self, code: str, extra: str = ""):
        message = "First route diagnostic\n[ERROR GRT-" + code + "] native invariant\n" + extra
        self.log.write_text(message)
        return RuntimeError("OpenROAD exited 1:\n" + message)

    def test_success_does_not_change_policy_or_archive_error(self) -> None:
        before = dict(self.env)
        with patch.object(ROUTER, "run_openroad", return_value=1.125) as run:
            elapsed, retry = self.invoke()
        self.assertEqual((elapsed, retry), (1.125, None))
        self.assertEqual(self.env, before)
        self.assertEqual(run.call_count, 1)
        self.assertFalse((self.logs / "grt_failed_policy.log").exists())

    def test_both_known_invariants_retry_once_and_include_first_attempt_time(self) -> None:
        for code in ("0228", "0254"):
            with self.subTest(code=code):
                self.env["MLS_CONFIG"] = str(self.requested)
                original_env = dict(self.env)
                error = self.failure(code)
                failed_log = self.log.read_bytes()
                calls = []

                def run(exe, script, env, log):
                    calls.append((exe, script, dict(env), log))
                    if len(calls) == 1:
                        raise error
                    log.write_text("Second route completed\n")
                    return 2.0

                with patch.object(ROUTER, "run_openroad", side_effect=run), \
                     patch.object(ROUTER.time, "monotonic", side_effect=[10.0, 17.0126]):
                    elapsed, retry = self.invoke()
                self.assertEqual(elapsed, 7.013)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0][2], original_env)
                second_env = dict(original_env, MLS_CONFIG=str(self.fallback))
                self.assertEqual(calls[1][2], second_env)
                self.assertEqual(calls[0][1], calls[1][1])
                self.assertEqual(calls[0][1], self.root / "flow_scripts/scripts/global_route_die_by_die.tcl")
                self.assertEqual((self.logs / "grt_failed_policy.log").read_bytes(), failed_log)
                self.assertEqual(retry, {
                    "error_code": "GRT-" + code,
                    "requested_config_sha256": hashlib.sha256(self.requested.read_bytes()).hexdigest(),
                    "fallback_config_sha256": hashlib.sha256(self.fallback.read_bytes()).hexdigest(),
                    "fresh_process_from_original_cts": True,
                })

    def test_custom_config_keeps_failure_even_if_contents_equal_default(self) -> None:
        custom = self.config_dir / "user_config.json"
        custom.write_bytes(self.requested.read_bytes())
        self.env["MLS_CONFIG"] = str(custom)
        error = self.failure("0228")
        with patch.object(ROUTER, "run_openroad", side_effect=error) as run:
            with self.assertRaises(RuntimeError) as raised:
                self.invoke()
        self.assertIs(raised.exception, error)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.env["MLS_CONFIG"], str(custom))
        self.assertFalse((self.logs / "grt_failed_policy.log").exists())

    def test_missing_config_selection_keeps_failure(self) -> None:
        self.env.pop("MLS_CONFIG")
        error = self.failure("0254")
        with patch.object(ROUTER, "run_openroad", side_effect=error) as run:
            with self.assertRaises(RuntimeError) as raised:
                self.invoke()
        self.assertIs(raised.exception, error)
        self.assertEqual(run.call_count, 1)
        self.assertNotIn("MLS_CONFIG", self.env)

    def test_missing_fallback_does_not_attempt_retry(self) -> None:
        self.fallback.unlink()
        error = self.failure("0228")
        with patch.object(ROUTER, "run_openroad", side_effect=error) as run:
            with self.assertRaises(RuntimeError) as raised:
                self.invoke()
        self.assertIs(raised.exception, error)
        self.assertEqual(run.call_count, 1)

    def test_unrelated_runtime_error_is_not_suppressed(self) -> None:
        error = self.failure("0300")
        before = dict(self.env)
        with patch.object(ROUTER, "run_openroad", side_effect=error) as run:
            with self.assertRaises(RuntimeError) as raised:
                self.invoke()
        self.assertIs(raised.exception, error)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.env, before)

    def test_embedded_code_without_native_error_line_does_not_trigger_retry(self) -> None:
        for message in ("fixture mentions [ERROR GRT-0228] in text",
                        "[WARNING GRT-0254] route warning",
                        "[ERROR GRT-02280] unrelated longer code"):
            with self.subTest(message=message):
                error = RuntimeError(message)
                with patch.object(ROUTER, "run_openroad", side_effect=error) as run:
                    with self.assertRaises(RuntimeError) as raised:
                        self.invoke()
                self.assertIs(raised.exception, error)
                self.assertEqual(run.call_count, 1)

    def test_second_native_failure_is_terminal_and_first_log_is_retained(self) -> None:
        first = self.failure("0228")
        first_log = self.log.read_bytes()
        second = RuntimeError("OpenROAD exited 1:\n[ERROR GRT-0254] second invariant")

        def run(exe, script, env, log):
            if env["MLS_CONFIG"] == str(self.requested):
                raise first
            log.write_text("[ERROR GRT-0254] second invariant\n")
            raise second

        with patch.object(ROUTER, "run_openroad", side_effect=run) as mocked:
            with self.assertRaises(RuntimeError) as raised:
                self.invoke()
        self.assertIs(raised.exception, second)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual((self.logs / "grt_failed_policy.log").read_bytes(), first_log)
        self.assertIn("second invariant", self.log.read_text())

    def test_non_runtime_exception_is_not_retried(self) -> None:
        error = OSError("launch failed")
        with patch.object(ROUTER, "run_openroad", side_effect=error) as run:
            with self.assertRaises(OSError) as raised:
                self.invoke()
        self.assertIs(raised.exception, error)
        self.assertEqual(run.call_count, 1)

    def fake_executable(self, *, fail_fallback: bool = False):
        results = self.root / "results"
        results.mkdir()
        original = results / "4_1_cts.def"
        original.write_text("Immutable CTS source fixture\n")
        record = self.root / "processes.jsonl"
        executable = self.root / "fake-openroad"
        executable.write_text("""#!/usr/bin/env python3
import hashlib, json, os
from pathlib import Path
import sys
input_path = Path(os.environ['RESULTS_DIR']) / os.environ['GRT_INITIAL_DESIGN']
row = {'pid': os.getpid(), 'argv': sys.argv[1:],
       'config': os.environ['MLS_CONFIG'],
       'input_sha256': hashlib.sha256(input_path.read_bytes()).hexdigest()}
with open(os.environ['TEST_PROCESS_RECORD'], 'a') as out:
    out.write(json.dumps(row) + '\\n')
partial = Path(os.environ['RESULTS_DIR']) / 'partial.odb'
if Path(os.environ['MLS_CONFIG']).name == 'mls_config.json':
    partial.write_text('The first process had partial router state')
    print('[ERROR GRT-0228] native invariant', flush=True)
    sys.exit(1)
assert input_path.name == '4_1_cts.def'
assert input_path.read_text() == 'Immutable CTS source fixture\\n'
if os.environ.get('TEST_FALLBACK_FAILURE') == '1':
    print('[ERROR GRT-0254] native retry invariant', flush=True)
    sys.exit(1)
print('Fresh input route completed', flush=True)
""")
        executable.chmod(0o755)
        self.env.update(os.environ)
        self.env.update({"MLS_CONFIG": str(self.requested),
                         "GRT_INITIAL_DESIGN": "4_1_cts.def",
                         "RESULTS_DIR": str(results),
                         "TEST_PROCESS_RECORD": str(record),
                         "TEST_FALLBACK_FAILURE": "1" if fail_fallback else "0"})
        return executable, original, record

    def test_real_launcher_uses_two_distinct_processes_same_original_input(self) -> None:
        executable, original, record = self.fake_executable()
        original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
        elapsed, retry = ROUTER.route_with_policy_retry(str(executable), self.root, self.env, self.logs)
        rows = [json.loads(line) for line in record.read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["pid"], rows[1]["pid"])
        self.assertEqual(rows[0]["argv"], rows[1]["argv"])
        self.assertEqual(rows[0]["argv"][:2], ["-exit", "-no_init"])
        self.assertEqual([row["config"] for row in rows], [str(self.requested), str(self.fallback)])
        self.assertEqual([row["input_sha256"] for row in rows], [original_sha, original_sha])
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), original_sha)
        self.assertGreaterEqual(elapsed, 0.0)
        self.assertEqual(retry["error_code"], "GRT-0228")
        self.assertIn("[ERROR GRT-0228]", (self.logs / "grt_failed_policy.log").read_text())
        self.assertEqual(self.log.read_text(), "Fresh input route completed\n")

    def test_real_launcher_double_failure_returns_failure_without_third_process(self) -> None:
        executable, original, record = self.fake_executable(fail_fallback=True)
        with self.assertRaisesRegex(RuntimeError, r"GRT-0254"):
            ROUTER.route_with_policy_retry(str(executable), self.root, self.env, self.logs)
        rows = [json.loads(line) for line in record.read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["pid"], rows[1]["pid"])
        self.assertEqual(original.read_text(), "Immutable CTS source fixture\n")
        self.assertIn("GRT-0228", (self.logs / "grt_failed_policy.log").read_text())
        self.assertIn("GRT-0254", self.log.read_text())

    def test_packaged_fallback_is_exact_validated_v15_configuration(self) -> None:
        self.assertEqual(hashlib.sha256(self.fallback.read_bytes()).hexdigest(),
                         VALIDATED_V15_CONFIG_SHA256)
        requested = json.loads(self.requested.read_text())
        fallback = json.loads(self.fallback.read_text())
        self.assertEqual(requested["multi_branch_max_groups"], 2)
        self.assertFalse(requested["multi_branch_adaptive_groups"])
        self.assertFalse(requested["multi_branch_tree_guard"])
        self.assertTrue(fallback["multi_branch_adaptive_groups"])
        self.assertTrue(fallback["multi_branch_tree_guard"])
        for key in set(requested) | set(fallback):
            if key not in {"multi_branch_max_groups", "multi_branch_adaptive_groups", "multi_branch_tree_guard"}:
                self.assertEqual(requested.get(key), fallback.get(key), key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
