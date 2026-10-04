#!/usr/bin/env python3
"""Dependency-free guarded multi-branch MLS planner regressions.

After merge this file lives in flow_scripts/scripts_3D/tests. The optional
MLS_TEST_SCRIPT_DIR override is only for validating a candidate before merge.
"""
import copy
import os
import shutil
import subprocess
from pathlib import Path
import sys
import unittest

SCRIPT_DIR = Path(os.environ.get("MLS_TEST_SCRIPT_DIR", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(SCRIPT_DIR))
import mls_planner as planner

def fixture():
    pins = [{'inst': 'source_bottom', 'pin': 'Z', 'x': 24000, 'y': 24000,
             'die': 'bottom', 'io': 'OUTPUT', 'hbt': False}]
    for i in range(256):
        pins.append({'inst': f'sink{i}_bottom', 'pin': 'A',
                     'x': 600000 + (i % 16) * 10000, 'y': 180000 + (i // 16) * 10000,
                     'die': 'bottom', 'io': 'INPUT', 'hbt': False})
    return {'dbu_per_micron': 1000, 'manufacturing_grid': 5,
            'die_area': [0, 0, 1000000, 1000000], 'hbt_master_size': [1000, 1000],
            'hbts': [{'name': 'HBT_legacy', 'x': 6900, 'y': 13300}],
            'nets': [{'name': 'literal[3]$data', 'signal_type': 'SIGNAL',
                      'special': False, 'bterms': False, 'pins': pins}]}

CONFIG = {'multi_branch_enabled': True, 'relocation_enabled': False}


class MultiBranchTest(unittest.TestCase):
    def test_deterministic_preserves_all_terminals_and_input(self):
        design = fixture(); before = copy.deepcopy(design)
        first = planner.plan_design(design, CONFIG)
        self.assertEqual(first, planner.plan_design(design, CONFIG))
        self.assertEqual(design, before)
        planner.validate_plan(design, first)
        self.assertLess(first['selected'][0]['path_proxy']['native_path_mean_um'],
                        first['selected'][0]['path_proxy']['baseline_direct_mean_um'])

    def test_budget_does_not_partially_create_family(self):
        result = planner.plan_design(fixture(), {**CONFIG, 'max_new_hbts': 4})
        self.assertEqual(result['selected'], [])
        self.assertEqual(result['stats']['new_hbts'], 0)

    def test_max_eight_sink_groups(self):
        design = fixture()
        result = planner.plan_design(design, {**CONFIG, 'multi_branch_target_sinks': 2})
        self.assertEqual(len(result['selected'][0]['hbts']), 9)
        self.assertEqual(len(result['selected'][0]['subnets']), 10)

    def test_excludes_protected_and_nonordinary_nets(self):
        mutations = [lambda n: n.update(protected=True), lambda n: n.update(signal_type='CLOCK'),
                     lambda n: n.update(special=True), lambda n: n.update(bterms=True),
                     lambda n: n['pins'][1].update(io='OUTPUT'),
                     lambda n: n['pins'][1].update(inst='PIN'),
                     lambda n: n['pins'][1].update(hbt=True),
                     lambda n: n['pins'][1].update(die='upper'),
                     lambda n: n.update(name='old__MLS__S1__TOP')]
        for mutate in mutations:
            design = fixture(); mutate(design['nets'][0])
            self.assertEqual(planner.plan_design(design, CONFIG)['selected'], [])

    def test_reversed_hbt_fails_directed_single_driver_check(self):
        design = fixture(); plan = planner.plan_design(design, CONFIG)
        h = plan['selected'][0]['hbts'][1]
        h['from_subnet'], h['to_subnet'] = h['to_subnet'], h['from_subnet']
        h['master'] = 'HBT_BOTIN'
        with self.assertRaisesRegex(ValueError, 'directed tree'):
            planner.validate_plan(design, plan)

    def test_missing_terminal_and_unknown_hbt_fail(self):
        design = fixture(); plan = planner.plan_design(design, CONFIG)
        bad = copy.deepcopy(plan); bad['selected'][0]['subnets'][2]['pins'].pop()
        with self.assertRaisesRegex(ValueError, 'terminal set'):
            planner.validate_plan(design, bad)
        bad = copy.deepcopy(plan)
        bad['selected'][0]['subnets'][1]['pins'].append({'inst': 'LS_HBT_999', 'pin': 'TOP'})
        with self.assertRaisesRegex(ValueError, 'Unknown or unused'):
            planner.validate_plan(design, bad)

    def test_fake_stats_cannot_raise_physical_budget(self):
        design = fixture(); plan = planner.plan_design(design, CONFIG)
        plan['config']['max_new_hbts'] = 4
        plan['stats']['new_hbt_budget'] = 99999
        with self.assertRaisesRegex(ValueError, 'budget exceeded'):
            planner.validate_plan(design, plan)

    def test_duplicate_subnet_numeric_identifier_fails(self):
        design = fixture(); plan = planner.plan_design(design, CONFIG)
        entry = plan['selected'][0]
        old = entry['subnets'][2]['name']
        new = old.replace('__S2__', '__S1__')
        entry['subnets'][2]['name'] = new
        for h in entry['hbts']:
            if h['to_subnet'] == old: h['to_subnet'] = new
        with self.assertRaisesRegex(ValueError, 'duplicate MLS subnet identifier'):
            planner.validate_plan(design, plan)

    def test_bad_group_and_proxy_config_rejected(self):
        for key, values in {
            "multi_branch_max_groups": [True, 1, 9, 2.5],
            "multi_branch_min_fanout": [True, 1, 2.5],
            "multi_branch_target_sinks": [True, 1, 2.5],
            "multi_branch_min_hpwl_um": [True, -1, float("nan")],
            "multi_branch_access_cost_um": [True, -1, float("inf")],
            "multi_branch_borrowed_r_ratio": [True, 0, 1, float("nan")],
            "multi_branch_min_proxy_gain": [True, 0, 1, float("inf")],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    planner.config_values({key: value})

    def test_zero_budget_or_disabled_branch_keeps_no_high_fanout_plan(self):
        for overrides in ({"multi_branch_enabled": False}, {"max_new_hbts": 0}):
            self.assertEqual(planner.plan_design(fixture(), {**CONFIG, **overrides})["selected"], [])

    def test_multi_branch_has_one_root_one_shared_trunk_and_leaf_groups(self):
        plan = planner.plan_design(fixture(), CONFIG)
        entry = plan["selected"][0]
        source, trunk, *leaves = entry["subnets"]
        self.assertEqual((source["die"], trunk["die"]), ("bottom", "upper"))
        self.assertEqual(len(source["pins"]), 2 + entry["path_proxy"]["source_local_sink_count"])
        self.assertEqual(len(trunk["pins"]), len(leaves) + 1)
        self.assertEqual(entry["hbts"][0]["master"], "HBT_BOTIN")
        self.assertEqual(entry["hbts"][0]["from_subnet"], source["name"])
        self.assertEqual(entry["hbts"][0]["to_subnet"], trunk["name"])
        for hbt, leaf in zip(entry["hbts"][1:], leaves):
            self.assertEqual(hbt["master"], "HBT_TOPIN")
            self.assertEqual(hbt["from_subnet"], trunk["name"])
            self.assertEqual(hbt["to_subnet"], leaf["name"])
            self.assertEqual(leaf["die"], "bottom")


def outlier_fixture():
    design=fixture()
    design['nets'][0]['pins'].append({'inst':'outlier_bottom','pin':'A','x':300000,'y':600000,
                                    'die':'bottom','io':'INPUT','hbt':False})
    return design


class SinkGuardTest(unittest.TestCase):
    def test_outlier_that_passes_mean_gain_stays_on_source_subnet(self):
        design=outlier_fixture()
        key={'inst':'outlier_bottom','pin':'A'}
        unguarded=planner.plan_design(design,{**CONFIG,'multi_branch_sink_guard':False})
        guarded=planner.plan_design(design,CONFIG)
        self.assertNotIn(key,unguarded['selected'][0]['subnets'][0]['pins'])
        self.assertIn(key,guarded['selected'][0]['subnets'][0]['pins'])
        self.assertGreater(guarded['selected'][0]['path_proxy']['source_local_sink_count'],0)
        planner.validate_plan(design,guarded)

    def test_every_remote_sink_meets_weighted_and_full_geometric_limits(self):
        design=outlier_fixture();plan=planner.plan_design(design,CONFIG);entry=plan['selected'][0]
        pins={(p['inst'],p['pin']):p for p in design['nets'][0]['pins']}
        source=next(p for p in pins.values() if p['io']=='OUTPUT');root=entry['hbts'][0]
        dist=lambda a,b:(abs(a['x']-b['x'])+abs(a['y']-b['y']))/design['dbu_per_micron']
        remote_count=0
        for subnet in entry['subnets'][2:]:
            leaf=next(h for h in entry['hbts'] if h['to_subnet']==subnet['name'])
            for ref in subnet['pins']:
                sink=pins.get((ref['inst'],ref['pin']))
                if sink is None:continue
                remote_count+=1;direct=dist(source,sink);native=dist(source,root)+dist(leaf,sink);borrowed=dist(root,leaf)
                self.assertLessEqual(native+borrowed,1.05*direct+6.4+1e-9)
                self.assertLessEqual(native+.1*borrowed+25.6,direct+1e-9)
        self.assertEqual(remote_count,entry['path_proxy']['remote_sink_count'])
        self.assertEqual(remote_count+entry['path_proxy']['source_local_sink_count'],len(pins)-1)

    def test_validator_rejects_forced_remote_outlier_even_with_valid_tree(self):
        design=outlier_fixture();plan=planner.plan_design(design,{**CONFIG,'multi_branch_sink_guard':False})
        plan['config']['multi_branch_sink_guard']=True
        with self.assertRaisesRegex(ValueError,'individual path guard'):
            planner.validate_plan(design,plan)

    def test_all_remote_groups_rejected_produces_no_family(self):
        design=outlier_fixture()
        result=planner.plan_design(design,{**CONFIG,'multi_branch_access_cost_um':1000000})
        self.assertEqual(result['selected'],[])
        self.assertEqual(result['stats']['new_hbts'],0)

    def test_one_remote_group_is_a_legal_two_hbt_tree(self):
        design=outlier_fixture();config=planner.config_values(CONFIG);dbu=design['dbu_per_micron']
        sites=planner.HbtSites(design['die_area'],design['hbt_master_size'],6400,5,design['hbts'])
        choice=planner.branch_candidate(design['nets'][0],config,dbu,sites)
        self.assertIsNotNone(choice)
        # Move all but one valid remote group to the source subnet; this tests
        # the general emitter/validator contract, not a duplicated generator.
        for group in choice['groups'][1:]:choice['local_sinks'].extend(group)
        choice['groups']=choice['groups'][:1];choice['positions']=choice['positions'][:2]
        entry=planner.build_branch_entry(design['nets'][0],choice,['LS_HBT_0','LS_HBT_1'],dbu,design['hbt_master_size'])
        plan={'config':config,'selected':[entry],'relocations':[],
              'stats':{'new_hbts':2,'new_hbt_budget':384,'selected_nets':1}}
        planner.validate_plan(design,plan)

        self.assertEqual(len(entry['subnets']),3)
        self.assertEqual(len(entry['hbts']),2)

    def test_guard_configuration_is_finite_and_nonnegative(self):
        for key in ['multi_branch_max_path_growth_fraction','multi_branch_max_path_growth_um']:
            for value in [-1,True,float('nan'),float('inf'),'0']:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    planner.config_values({key:value})


class LiteralNameTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("tclsh"), "Tcl interpreter unavailable")
    def test_full_emitted_tcl_treats_original_and_subnet_names_literally(self):
        design = fixture()
        literal = 'data[set ::pwned 1]$variable;[3]'
        design["nets"][0]["name"] = literal
        plan = planner.plan_design(design, CONFIG)
        script = r"""
set ::pwned 0
set ::variable substituted
set ::found_nets {}
set ::created_nets {}
namespace eval ord {
    proc get_db_block {} { return ::block }
    proc get_db {} { return ::object }
}
proc ::object {args} { return ::object }
proc ::block {method args} {
    if {$method eq "findNet"} { lappend ::found_nets [lindex $args 0] }
    return ::object
}
namespace eval odb {
    proc dbNet_create {block name} { lappend ::created_nets $name; return ::object }
    proc dbInst_create {args} { return ::object }
    proc dbNet_destroy {args} {}
}
""" + planner.emit_tcl(plan)
        script += "\nif {$::pwned != 0} {error {name evaluated as Tcl}}\n"
        script += "if {$::found_nets ne [list " + planner.tcl_word(literal) + "]} {error {original name changed}}\n"
        for subnet in plan["selected"][0]["subnets"]:
            script += "if {[lsearch -exact $::created_nets " + planner.tcl_word(subnet["name"]) + "] < 0} {error {subnet name changed}}\n"
        script += "puts NAME_SAFETY_PASS\n"
        completed = subprocess.run(["tclsh"], input=script, text=True, capture_output=True, check=True)
        self.assertEqual(completed.stderr, "")
        self.assertIn("NAME_SAFETY_PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
