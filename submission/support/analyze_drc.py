#!/usr/bin/env python3
"""Count final fixed-evaluator DRC reports and compare layers, types and nets."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def count(records: list[dict], key: str) -> dict[str, int]:
    return dict(sorted(collections.Counter(record[key] for record in records).items()))


def summarize(records: list[dict]) -> dict:
    return {'total': len(records), 'by_layer': count(records, 'layer'),
            'by_type': count(records, 'type'), 'by_type_layer': count(records, 'type_layer')}


def read_records(report: Path) -> list[dict]:
    text = (report / '5_route_drc.rpt').read_text()
    records = []
    for block in re.split(r'^violation type:\s*', text, flags=re.M)[1:]:
        lines = block.splitlines()
        source = re.search(r'^\s*srcs:\s*(.*)$', block, re.M)
        bounds = re.search(r'bbox = \(([-\d.]+), ([-\d.]+)\) - '
                           r'\(([-\d.]+), ([-\d.]+)\) on Layer (\S+)', block)
        if source is None or bounds is None:
            raise ValueError(f'Unrecognized DRC block: {block[:200]}')
        layer = bounds.group(5)
        records.append({'type': lines[0].strip(), 'layer': layer,
                        'type_layer': lines[0].strip() + '|' + layer,
                        'nets': sorted(set(re.findall(r'net:(\S+)', source.group(1)))),
                        'sources': source.group(1),
                        'bbox_um': [float(value) for value in bounds.groups()[:4]]})
    metrics = json.loads((report / 'metrics.json').read_text())
    if len(records) != metrics['drc']:
        raise ValueError(f'DRC report count {len(records)} differs from metrics {metrics["drc"]}')
    return records


def differences(old: dict, new: dict) -> dict:
    return {key: new.get(key, 0) - old.get(key, 0) for key in sorted(set(old) | set(new))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, action='append', help='label=/report/directory')
    parser.add_argument('--compare', action='append', default=[], help='old_label:new_label')
    parser.add_argument('--selected-plan', type=Path, help='MLS plan for attributing merged original nets')
    parser.add_argument('--placement-def', type=Path, help='DEF supplies DBU scale for selected HBT locations')
    parser.add_argument('--relocation-reference-plan', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    selected_nets = set()
    selected_sites = {}
    plan_metadata = None
    if args.selected_plan:
        plan = json.loads(args.selected_plan.read_text())
        selected_nets = {item['original'] for item in plan['selected']}
        plan_metadata = {'path': str(args.selected_plan.resolve()), 'sha256': sha256(args.selected_plan),
                         'selected_nets': sorted(selected_nets), 'stats': plan['stats']}
        if args.placement_def:
            match = re.search(r'UNITS DISTANCE MICRONS (\d+)', args.placement_def.read_text())
            if match is None:
                raise ValueError('Placement DEF is missing DBU scale')
            dbu = int(match.group(1))
            plan_metadata['dbu_per_um'] = dbu
            selected_sites = {item['original']: [(hbt['x'] / dbu, hbt['y'] / dbu)
                                                  for hbt in item['hbts']] for item in plan['selected']}
        if args.relocation_reference_plan:
            other = json.loads(args.relocation_reference_plan.read_text())
            plan_metadata['relocation_reference_plan'] = str(args.relocation_reference_plan.resolve())
            plan_metadata['relocation_reference_plan_sha256'] = sha256(args.relocation_reference_plan)
            plan_metadata['existing_hbt_relocations_identical'] = plan['relocations'] == other['relocations']

    reports = {}
    for entry in args.report:
        label, separator, location = entry.partition('=')
        if not separator or label in reports:
            raise ValueError('Reports require unique label=path entries')
        report = Path(location)
        records = read_records(report)
        selected = [record for record in records if selected_nets.intersection(record['nets'])]
        rest = [record for record in records if not selected_nets.intersection(record['nets'])]
        ns_sites = []
        for record in selected:
            if record['type'] != 'NS Metal' or not selected_sites:
                continue
            x1, y1, x2, y2 = record['bbox_um']
            x, y = (x1 + x2) / 2, (y1 + y2) / 2
            closest = min((math.hypot(x - hx, y - hy), net, hx, hy)
                          for net in set(record['nets']) & selected_sites.keys()
                          for hx, hy in selected_sites[net])
            ns_sites.append({'record': record, 'own_new_hbt_site_distance_um': closest[0],
                             'original_net': closest[1], 'new_hbt_site_um': list(closest[2:])})
        reports[label] = {'report_dir': str(report.resolve()),
                          'drc_report_sha256': sha256(report / '5_route_drc.rpt'),
                          **summarize(records), 'involving_selected_original_nets': summarize(selected),
                          'other_nets': summarize(rest), 'selected_net_ns_metal_sites': ns_sites}
    comparisons = {}
    for pair in args.compare:
        old, new = pair.split(':', 1)
        result = {'old': old, 'new': new, 'total_delta': reports[new]['total'] - reports[old]['total']}
        for scope in ('all', 'involving_selected_original_nets', 'other_nets'):
            first, second = (reports[old], reports[new]) if scope == 'all' else (reports[old][scope], reports[new][scope])
            result[scope] = {field + '_delta': differences(first[field], second[field])
                             for field in ('by_layer', 'by_type', 'by_type_layer')}
            result[scope]['total_delta'] = second['total'] - first['total']
        comparisons[pair] = result
    output = {'scope': 'local_native_fixed_evaluator_not_official_score',
              'selected_plan': plan_metadata, 'reports': reports, 'comparisons': comparisons,
              'notes': ['One final DRC block counts once, even when it involves multiple nets.',
                        'Final evaluator merges MLS subnets into original net names; selected attribution uses those names.',
                        'A per-layer count delta is measured behavior, not proof of a specific routing cause.',
                        'Own-HBT distance uses the DEF DBU scale and the DRC bounding-box center.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + '\n')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
