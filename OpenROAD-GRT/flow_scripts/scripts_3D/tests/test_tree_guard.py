"""Tree-guard regressions retained from the validated v14 experiment."""
import os
from pathlib import Path
import random
import sys
import unittest

SCRIPT_DIR = Path(os.environ.get('MLS_TEST_SCRIPT_DIR', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(SCRIPT_DIR))
import mls_planner as planner


def dense_prim(points):
    """Independent complete-graph oracle for the sparse Manhattan kernel."""
    points = sorted(set(points))
    if not points:
        return 0
    costs = [float('inf')] * len(points)
    used = set()
    costs[0] = 0
    total = 0
    for _ in points:
        i = min((i for i in range(len(points)) if i not in used), key=lambda i: (costs[i], i))
        used.add(i)
        total += costs[i]
        for j in range(len(points)):
            if j not in used:
                distance = abs(points[i][0] - points[j][0]) + abs(points[i][1] - points[j][1])
                costs[j] = min(costs[j], distance)
    return total


class TreeGuardTest(unittest.TestCase):
    def tearDown(self):
        planner._tree_reset_cache()

    def test_sparse_kernel_matches_independent_complete_graph(self):
        rng = random.Random(20261014)
        fixtures = [[], [(0, 0)], [(i, 0) for i in range(40)],
                    [(i, -i) for i in range(-20, 20)],
                    [(10**15 + i, -10**15 + i) for i in range(20)]]
        fixtures += [[(rng.randrange(-12, 13), rng.randrange(-12, 13))
                      for _ in range(rng.randrange(2, 65))] for _ in range(100)]
        for points in fixtures:
            self.assertEqual(planner._tree_rmst(points)['weight_dbu'], dense_prim(points))

    def test_invalid_geometry_rejected_before_duplicates(self):
        for points in ([(True, 1), (1, 1)], [(float('inf'), 0)], [(1.0, 0)], [(float('nan'), 0)]):
            with self.assertRaises(ValueError):
                planner._tree_rmst(points)

    def test_cache_bounded_and_oversized_not_stored(self):
        old = planner._TREE_RMST_MAX_POINTS, planner._TREE_RMST_MAX_ENTRIES
        planner._tree_reset_cache()
        try:
            planner._TREE_RMST_MAX_POINTS, planner._TREE_RMST_MAX_ENTRIES = 8, 2
            for offset in range(20):
                planner._tree_rmst([(offset, 0), (offset + 1, 1), (offset + 2, 3)])
                self.assertLessEqual(planner._TREE_RMST_POINTS, 8)
                self.assertLessEqual(len(planner._TREE_RMST_CACHE), 2)
            before = planner._TREE_RMST_POINTS
            planner._tree_rmst([(i, i) for i in range(20)])
            self.assertEqual(planner._TREE_RMST_POINTS, before)
            planner._tree_reset_cache()
            self.assertEqual(planner._TREE_RMST_POINTS, 0)
        finally:
            planner._TREE_RMST_MAX_POINTS, planner._TREE_RMST_MAX_ENTRIES = old

    def test_tree_guard_requires_original_eight_group_fallback(self):
        self.assertIs(planner.DEFAULT_CONFIG['multi_branch_tree_guard'], False)
        for config in ({'multi_branch_tree_guard': 1}, {'multi_branch_tree_guard': True},
                       {'multi_branch_tree_guard': True, 'multi_branch_adaptive_groups': True,
                        'multi_branch_sink_guard': False},
                       {'multi_branch_tree_guard': True, 'multi_branch_adaptive_groups': True,
                        'multi_branch_max_groups': 4}):
            with self.assertRaises(ValueError):
                planner.config_values(config)


if __name__ == '__main__':
    unittest.main()
