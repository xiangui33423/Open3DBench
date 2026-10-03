#!/usr/bin/env python3
"""Refresh the self-contained overlay and create a ZIP with run.sh at its root."""
from __future__ import annotations
import argparse
import shutil
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent
repository = root.parent
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=repository / 'submission.zip')
args = parser.parse_args()
flow = root / 'flow_scripts'
shutil.copytree(repository / 'OpenROAD-GRT/flow_scripts', flow, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', 'tests'))
for name in ('load.tcl',):
    shutil.copy2(root / 'support' / name, flow / 'scripts' / name)
for name in ('sdc_compat.tcl', 'write_ref_sdc.tcl'):
    shutil.copy2(repository / 'OpenROAD-3D/flow/scripts' / name, flow / 'scripts' / name)
overlay = root / 'openroad_overlay'
shutil.copytree(repository / 'OpenROAD-GRT/openroad_src', overlay, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', 'build', '.git', '.DS_Store'))
for required in ('prepare_mls.tcl', 'mls_config.json'):
    if not (flow / 'scripts_3D' / required).is_file():
        raise SystemExit(f'Missing source file: {required}')
algorithm_doc = repository / 'OpenROAD-GRT/ALGORITHM.md'
if algorithm_doc.is_file():
    shutil.copy2(algorithm_doc, root / 'ALGORITHM.md')
destination = args.output.resolve()
destination.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob('*')):
        if not path.is_file() or set(path.relative_to(root).parts) & {'.build', '__pycache__', 'test_output'} or path == destination:
            continue
        archive.write(path, str(path.relative_to(root)))
print(f'Packaged: {destination} ({destination.stat().st_size} bytes)')
