#!/usr/bin/env python3
"""Archive this frozen release without importing files from another checkout."""
from pathlib import Path
import argparse
import zipfile
root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
destination = parser.parse_args().output.resolve()
if destination.exists():
    raise SystemExit('Refusing to overwrite an existing archive')
with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob('*')):
        if path.is_file() and path != destination and not set(path.relative_to(root).parts) & {'.build', '__pycache__', 'test_output'}:
            archive.write(path, str(path.relative_to(root)))
print(destination)
