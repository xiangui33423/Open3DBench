"""High-fanout sharing must preserve receivers, local paths, and the HBT cap."""
import unittest

import test_mls_planner as fixture
from mls_planner import config_values, plan_design, validate_plan


def design():
    net = {'name': 'long_control', 'signal_type': 'SIGNAL', 'special': False,
           'pins': [{'inst': 'driver', 'pin': 'Q', 'io': 'OUTPUT', 'die': 'bottom',
                     'x': 25000, 'y': 25000, 'hbt': False}]}
    for i in range(16 + 128):
        near = i < 16
        net['pins'].append({'inst': ('near' if near else 'far') + str(i),
            'pin': 'A', 'io': 'INPUT', 'die': 'bottom', 'hbt': False,
            'x': (30000 if near else 800000) + i % 8 * 100,
            'y': (25000 if near else 500000) + i % 7 * 100})
    result = fixture.manifest([net])
    result['die_area'] = [0, 0, 1200000, 1200000]
    return result


CFG = {'single_trunk_enabled': True, 'relocation_enabled': False,
       'post_refine_passes': 0}


class SingleTrunkTest(unittest.TestCase):
    def test_one_remote_cluster_has_two_hbts_and_preserves_all_original_pins(self):
        data = design()
        result = plan_design(data, CFG)
        self.assertEqual(len(result['selected']), 1)
        fixture.MlsPlannerTest().assert_contract(data, result)
        validate_plan(data, result)
        local = {p['inst'] for p in result['selected'][0]['subnets'][0]['pins']}
        remote = {p['inst'] for p in result['selected'][0]['subnets'][2]['pins']}
        self.assertTrue(all('near' + str(i) in local for i in range(16)))
        self.assertTrue(all('far' + str(i) in remote for i in range(16, 144)))

    def test_single_trunk_is_opt_in_and_old_multi_branch_remains_rejected(self):
        self.assertFalse(config_values()['single_trunk_enabled'])
        self.assertEqual(plan_design(design(), {'relocation_enabled': False})['selected'], [])
        with self.assertRaisesRegex(ValueError, 'exactly two HBTs'):
            config_values({**CFG, 'multi_branch_enabled': True})
        with self.assertRaisesRegex(ValueError, 'JSON boolean'):
            config_values({'single_trunk_enabled': 'true'})

    def test_user_branch_group_cap_cannot_increase_single_trunk_hbt_count(self):
        data = design()
        for limit in (2, 8):
            result = plan_design(data, {**CFG, 'multi_branch_max_groups': limit})
            self.assertEqual([len(e['hbts']) for e in result['selected']], [2])
            fixture.MlsPlannerTest().assert_contract(data, result)

    def test_protected_clock_upper_and_package_nets_are_not_borrowed(self):
        changes = [lambda n: n.update(protected=True),
                   lambda n: n.update(signal_type='CLOCK'),
                   lambda n: n.update(bterms=True),
                   lambda n: n['pins'][1].update(pin='CK'),
                   lambda n: n['pins'][1].update(inst='PIN'),
                   lambda n: n['pins'][1].update(die='upper')]
        for change in changes:
            data = design()
            change(data['nets'][0])
            self.assertEqual(plan_design(data, CFG)['selected'], [])

    def test_guard_is_enforced_even_if_legacy_branch_guard_is_disabled(self):
        data = design()
        result = plan_design(data, {**CFG, 'multi_branch_sink_guard': False})
        entry = result['selected'][0]
        near = next(p for p in entry['subnets'][0]['pins'] if p['inst'] == 'near0')
        entry['subnets'][0]['pins'].remove(near)
        entry['subnets'][2]['pins'].append(near)
        with self.assertRaisesRegex(ValueError, 'individual path guard'):
            validate_plan(data, result)

    def test_global_budget_can_disable_or_limit_high_fanout_sharing(self):
        for budget in (0, 1):
            self.assertEqual(plan_design(design(), {**CFG, 'max_new_hbts': budget})['selected'], [])
        result = plan_design(design(), {**CFG, 'max_new_hbts': 2})
        self.assertEqual(len(result['selected']), 1)
        self.assertEqual(result['stats']['new_hbts'], 2)


if __name__ == '__main__':
    unittest.main()
