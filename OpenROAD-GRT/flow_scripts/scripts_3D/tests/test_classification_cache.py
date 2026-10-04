#!/usr/bin/env python3
"""Regression tests for exact-DEF classification reuse and safe fallback."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from check_2d_net_guide_layers import check, classify_net_from_def, main as check_main
from die_net_common import (
    classification_payload_sha256,
    def_sha256,
    read_classification_cache,
    iter_classification_json,
    write_classification_cache,
)
from export_die_net_lists import main as export_main


class ClassificationCacheTest(unittest.TestCase):
    DEF = """COMPONENTS 2 ;
- u_bottom BUF_bottom + PLACED ( 1 2 ) N ;
- u_upper BUF_upper + PLACED ( 3 4 ) N ;
END COMPONENTS
NETS 2 ;
- bad ( u_bottom A ) ( u_bottom Y ) ;
- upper ( u_upper A ) ( u_upper Y ) ;
END NETS
"""
    GUIDE = """bad
(
0 0 4200 4200 metal11
)
upper
(
0 0 4200 4200 metal10
)
"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.def_path, self.guide_path = root / "design.def", root / "route.guide"
        self.cache = root / "classification.json"
        self.def_path.write_text(self.DEF, encoding="utf-8")
        self.guide_path.write_text(self.GUIDE, encoding="utf-8")
        self.classification = classify_net_from_def(self.def_path)
        self.expected = check(self.guide_path, self.def_path)
        write_classification_cache(self.cache, self.def_path, self.classification)

    def test_valid_cache_keeps_full_map_order_violations_and_cli_output(self) -> None:
        cached = read_classification_cache(self.cache, self.def_path)
        self.assertEqual(cached, self.classification)
        self.assertEqual(list(cached), list(self.classification))
        self.assertEqual(check(self.guide_path, self.def_path, self.cache), self.expected)
        reports = []
        for extra in ([], ["--classification-cache", str(self.cache)]):
            output = io.StringIO()
            with patch.object(sys, "argv", ["check", str(self.guide_path),
                                           str(self.def_path), *extra]):
                with contextlib.redirect_stdout(output):
                    with self.assertRaises(SystemExit) as error:
                        check_main()
            self.assertEqual(error.exception.code, 1)
            reports.append(output.getvalue())
        self.assertEqual(reports[0], reports[1])

    def test_stale_def_reparses_new_cross_die_violation(self) -> None:
        # The cached upper-only net becomes bottom-only, making metal11 illegal.
        self.def_path.write_text(self.DEF.replace("( u_upper", "( u_bottom"), encoding="utf-8")
        self.guide_path.write_text(self.GUIDE.replace("metal10", "metal11"), encoding="utf-8")
        self.assertIsNone(read_classification_cache(self.cache, self.def_path))
        fresh = check(self.guide_path, self.def_path)
        self.assertEqual(fresh[1], {"bad": [11], "upper": [11]})
        self.assertEqual(check(self.guide_path, self.def_path, self.cache), fresh)

    def test_corrupt_payload_does_not_hide_cross_die_violations(self) -> None:
        record = json.loads(self.cache.read_text())
        record["classification"]["bad"] = "3d"
        self.cache.write_text(json.dumps(record), encoding="utf-8")
        self.assertIsNone(read_classification_cache(self.cache, self.def_path))
        self.assertEqual(check(self.guide_path, self.def_path, self.cache), self.expected)

    def test_invalid_schema_payload_types_and_fingerprints_fall_back(self) -> None:
        original = json.loads(self.cache.read_text())
        changes = [
            ("schema_version", 0), ("schema_version", True),
            ("def_sha256", "0" * 64), ("def_sha256", 0),
            ("payload_sha256", "0" * 64), ("payload_sha256", None),
            ("classification", []),
            ("classification", {"bad": 1}),
            ("classification", {"bad": "not-a-classification"}),
        ]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                record = {**original, field: value}
                self.cache.write_text(json.dumps(record), encoding="utf-8")
                self.assertIsNone(read_classification_cache(self.cache, self.def_path))
                self.assertEqual(check(self.guide_path, self.def_path, self.cache), self.expected)
        for text in ("{", "[]", "null", "\xff"):
            with self.subTest(text=text):
                self.cache.write_bytes(text.encode("latin-1"))
                self.assertIsNone(read_classification_cache(self.cache, self.def_path))
                self.assertEqual(check(self.guide_path, self.def_path, self.cache), self.expected)
        self.cache.unlink()
        self.assertEqual(check(self.guide_path, self.def_path, self.cache), self.expected)

    def test_changed_def_while_exporting_is_rejected_before_cache_publish(self) -> None:
        before = def_sha256(self.def_path)
        self.def_path.write_text(self.DEF + "\n# changed\n", encoding="utf-8")
        untouched = self.cache.read_bytes()
        with self.assertRaisesRegex(ValueError, "DEF changed"):
            write_classification_cache(self.cache, self.def_path, self.classification,
                                       expected_def_sha256=before)
        self.assertEqual(self.cache.read_bytes(), untouched)

    def test_export_optional_cache_preserves_all_three_lists_and_stdout(self) -> None:
        paths = [Path(self.temp.name) / "plain", Path(self.temp.name) / "cached"]
        output = []
        for path, extra in zip(paths, ([], ["--classification-cache", str(self.cache)])):
            capture = io.StringIO()
            with patch.object(sys, "argv", ["export", str(self.def_path), str(path), *extra]):
                with contextlib.redirect_stdout(capture):
                    self.assertEqual(export_main(), 0)
            output.append(capture.getvalue().replace(str(path), "<output_dir>"))
        self.assertEqual(output[0], output[1])
        for name in ("bottom_2d.txt", "upper_2d.txt", "special.txt"):
            self.assertEqual((paths[0] / name).read_bytes(), (paths[1] / name).read_bytes())
        record = json.loads(self.cache.read_text())
        self.assertEqual(record["classification"], self.classification)
        self.assertEqual(record["payload_sha256"], classification_payload_sha256(self.classification))

    def test_batched_cache_encoding_matches_previous_bytes_at_batch_boundaries(self) -> None:
        for count in (0, 1, 4095, 4096, 4097, 8200):
            with self.subTest(count=count):
                labels = ("2d_bottom", "2d_upper", "3d", "unknown")
                classification = {
                    f'网路_{index}_\\"\n\t': labels[index % len(labels)]
                    for index in range(count)
                }
                expected = json.dumps(classification, ensure_ascii=True,
                                      separators=(",", ":"))
                self.assertEqual("".join(iter_classification_json(classification)), expected)
                self.assertEqual(classification_payload_sha256(classification),
                                 hashlib.sha256(expected.encode()).hexdigest())
                write_classification_cache(self.cache, self.def_path, classification)
                record = {
                    "schema_version": 1,
                    "def_sha256": def_sha256(self.def_path),
                    "payload_sha256": hashlib.sha256(expected.encode()).hexdigest(),
                    "classification": classification,
                }
                self.assertEqual(self.cache.read_text(),
                                 json.dumps(record, ensure_ascii=True,
                                            separators=(",", ":")) + "\n")
                self.assertEqual(read_classification_cache(self.cache, self.def_path),
                                 classification)


if __name__ == "__main__":
    unittest.main()
