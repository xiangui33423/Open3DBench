#!/usr/bin/env python3
"""Regression tests for strict split-net guide diagnostics."""

from __future__ import annotations

import random
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from die_net_common import iter_nets, parse_nets
from diagnose_guide_connectivity import (
    GCELL_STEP,
    GuideRect,
    build_net_pins,
    diagnose_net,
    guide_components_3d,
    is_hbt_split_net,
    parse_components_multiline,
    parse_guides,
    pin_component_count,
    pin_covered,
    run_diagnosis,
    same_layer_components,
    strict_failure,
)


def reference_components(rects: list[GuideRect], three_d: bool) -> list[int]:
    """Small brute-force oracle independent of the production union-find."""
    adjacency = [set() for _ in rects]
    for i, a in enumerate(rects):
        for j, b in enumerate(rects[:i]):
            if three_d:
                if not (a.layer.lower().startswith("metal")
                        and b.layer.lower().startswith("metal")):
                    continue
                try:
                    la, lb = int(a.layer.lower()[5:]), int(b.layer.lower()[5:])
                except ValueError:
                    continue
                distance = abs(la - lb)
                if distance > 1:
                    continue
                margin = 1 if distance == 0 else 0
            else:
                if a.layer != b.layer:
                    continue
                margin = 1
            if (a.x2 + margin >= b.x1 and b.x2 + margin >= a.x1
                    and a.y2 + margin >= b.y1 and b.y2 + margin >= a.y1):
                adjacency[i].add(j)
                adjacency[j].add(i)
    components = [-1] * len(rects)
    for start in range(len(rects)):
        if components[start] != -1:
            continue
        stack = [start]
        components[start] = start
        while stack:
            for other in adjacency[stack.pop()]:
                if components[other] == -1:
                    components[other] = start
                    stack.append(other)
    return components


class GuideGeometryTest(unittest.TestCase):
    def test_same_layer_margin_and_case_semantics(self) -> None:
        a = GuideRect("metal9", 0, 0, 10, 10)
        for gap, connected in ((0, True), (1, True), (2, False)):
            with self.subTest(gap=gap):
                b = GuideRect("metal9", 10 + gap, 0, 20 + gap, 10)
                self.assertEqual(same_layer_components([a, b]), 1 if connected else 2)
        b = GuideRect("METAL9", 0, 0, 10, 10)
        self.assertEqual(same_layer_components([a, b]), 2)
        self.assertEqual(len(set(guide_components_3d([a, b]))), 1)

    def test_adjacent_layers_require_xy_contact(self) -> None:
        a = GuideRect("metal9", 0, 0, 10, 10)
        for layer, gap, expected in (("metal10", 0, 1), ("metal10", 1, 2),
                                     ("metal11", 0, 2)):
            with self.subTest(layer=layer, gap=gap):
                b = GuideRect(layer, 10 + gap, 0, 20 + gap, 10)
                self.assertEqual(len(set(guide_components_3d([a, b]))), expected)

    def test_coverage_margin_is_inclusive(self) -> None:
        rects = [GuideRect("metal10", 0, 0, 10, 10)]
        margin = GCELL_STEP // 2
        self.assertEqual(margin, 2100)
        self.assertTrue(pin_covered(10 + margin, -margin, rects, margin))
        self.assertFalse(pin_covered(11 + margin, -margin, rects, margin))

    def test_component_assignment_uses_first_covering_rectangle(self) -> None:
        # Coverage expansion can overlap although the guides are disconnected.
        rects = [GuideRect("metal9", 0, 0, 10, 10),
                 GuideRect("metal9", 30, 0, 40, 10)]
        pins = [("overlap", 20, 0), ("right_only", 40, 0)]
        self.assertEqual(pin_component_count(rects, pins, margin=10), 2)
        self.assertEqual(pin_component_count(list(reversed(rects)), pins, margin=10), 1)

    def test_random_geometry_matches_graph_oracle(self) -> None:
        rng = random.Random(1729)
        for _ in range(100):
            rects = []
            for _ in range(rng.randrange(25)):
                x, y = rng.randrange(20), rng.randrange(20)
                rects.append(GuideRect(rng.choice(("metal9", "metal10", "METAL10",
                                                  "metal11", "metal13", "via1")),
                                       x, y, x + rng.randrange(8), y + rng.randrange(8)))
            actual = guide_components_3d(rects)
            expected = reference_components(rects, three_d=True)
            self.assertEqual([[a == b for b in actual] for a in actual],
                             [[a == b for b in expected] for a in expected])
            self.assertEqual(same_layer_components(rects),
                             len(set(reference_components(rects, three_d=False))))

    def test_strict_failure_keeps_ordinary_pin_connectivity(self) -> None:
        rects = [GuideRect("metal9", 0, 0, 10, 10),
                 GuideRect("metal9", 10000, 0, 10010, 10)]
        pins = [("ordinary_bottom", 0, 0), ("other_bottom", 10000, 0),
                ("LS_HBT_1", 0, 0)]
        diag = diagnose_net("signal_BOT", rects, pins, set(), None, 2100, 5000)
        self.assertEqual((diag.uncovered_pins, diag.hbt_uncovered, diag.pin_components),
                         (0, 0, 2))
        self.assertTrue(strict_failure(diag))

    def test_all_strict_failure_conditions_and_existing_cc_limit(self) -> None:
        diag = diagnose_net("signal_TOP", [GuideRect("metal11", 0, 0, 10, 10)],
                            [("HBT_1", 0, 0)], set(), None, 2100, 5000)
        self.assertFalse(strict_failure(diag))
        for field, value in (("guide_rects", 0), ("illegal_layers", 1),
                             ("hbt_uncovered", 1), ("pin_components", 2)):
            with self.subTest(field=field):
                failed = replace(diag, **{field: value})
                self.assertTrue(strict_failure(failed))
                self.assertFalse(strict_failure(replace(failed, net="ordinary")))
        self.assertFalse(strict_failure(replace(diag, uncovered_pins=5)))
        skipped = diagnose_net("signal_TOP", [GuideRect("metal11", 0, 0, 10, 10)],
                               [("HBT_1", 0, 0)], set(), None, 2100, 0)
        self.assertEqual((skipped.same_layer_components, skipped.pin_components), (0, -1))


class FilteredDesignTest(unittest.TestCase):
    DEF = """VERSION 5.8 ;
COMPONENTS 5 ;
- unrelated BUF + PLACED ( 123 456 ) N ;
- u_bottom BUF_bottom
  + PLACED ( 10000 10000 ) N ;
- other_bottom BUF_bottom + FIXED ( 30000 10000 ) N ;
- HBT_1 HBT + FIXED ( 10000 10000 ) N ;
- u_upper BUF_upper + PLACED ( 10000 10000 ) N ;
END COMPONENTS
NETS 4 ;
- regular ( unrelated A ) ( PIN external ) ;
- target_BOT ( u_bottom A )
  ( HBT_1 BOT ) ( other_bottom Y ) ( PIN external ) ;
- target_TOP ( HBT_1 TOP ) ( u_upper Y ) ;
- missing_BOT ( u_bottom Y ) ;
END NETS
END DESIGN
"""
    GUIDE = """regular
(
0 0 4200 4200 metal1
)
target_BOT (
10000 10000 10010 10010 metal9
30000 10000 30010 10010 metal9
)
target_TOP
(
10000 10000 10010 10010 metal11
)
lowercase_bot
(
1 1 2 2 metal1
)
"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.results = Path(self.temp.name) / "results"
        self.results.mkdir()
        self.def_path = self.results / "4_1_cts.def"
        self.def_path.write_text(self.DEF, encoding="utf-8")
        self.guide_path = self.results / "route.guide"
        self.guide_path.write_text(self.GUIDE, encoding="utf-8")
        (self.results / "route_upper.guide").write_text(
            "target_TOP\n(\n10000 10000 10010 10010 metal10\n)\n", encoding="utf-8")
        logs = self.results.parent / "logs"
        logs.mkdir()
        (logs / "grt_finalize.log").write_text(
            "Missing route to pin u_bottom/A in net target_BOT.\n", encoding="utf-8")

    def test_streamed_and_filtered_nets_preserve_all_connections(self) -> None:
        full = parse_nets(self.def_path)
        self.assertEqual(list(iter_nets(self.def_path)), full)
        selected = list(iter_nets(self.def_path, net_name_filter=is_hbt_split_net))
        self.assertEqual(selected, [net for net in full if is_hbt_split_net(net.name)])
        self.assertEqual([(pin.inst, pin.pin) for pin in selected[0].pins],
                         [("u_bottom", "A"), ("HBT_1", "BOT"),
                          ("other_bottom", "Y"), ("PIN", "external")])

    def test_filtered_guides_keep_rectangles_and_order(self) -> None:
        full = parse_guides(self.guide_path)
        self.assertEqual(parse_guides(self.guide_path, split_only=True),
                         {name: rects for name, rects in full.items()
                          if is_hbt_split_net(name)})

    def test_filtered_component_locations_and_net_pins_equal_full_subset(self) -> None:
        full_locations = parse_components_multiline(self.def_path)
        wanted = {"u_bottom", "HBT_1", "not_present"}
        self.assertEqual(parse_components_multiline(self.def_path, wanted),
                         {name: loc for name, loc in full_locations.items() if name in wanted})
        full_pins = build_net_pins(self.def_path)
        filtered = build_net_pins(self.def_path, split_only=True)
        self.assertEqual(filtered, {name: pins for name, pins in full_pins.items()
                                    if is_hbt_split_net(name)})
        self.assertEqual(len(filtered["target_BOT"]), 3)

    def test_strict_diagnostics_equal_split_subset_of_complete_run(self) -> None:
        full = run_diagnosis(self.results, 5000, 1000000, def_path=self.def_path)
        strict = run_diagnosis(self.results, 5000, 1000000, split_only=True,
                               def_path=self.def_path)
        self.assertEqual(strict, [diag for diag in full if is_hbt_split_net(diag.net)])
        by_name = {diag.net: diag for diag in strict}
        self.assertTrue(strict_failure(by_name["missing_BOT"]))
        self.assertTrue(strict_failure(by_name["target_BOT"]))
        self.assertEqual(by_name["target_BOT"].grt_missing_pins, 1)
        self.assertTrue(by_name["target_TOP"].m10_removed_by_scrub)


if __name__ == "__main__":
    unittest.main()
