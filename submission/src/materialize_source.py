#!/usr/bin/env python3
import hashlib
import shutil
import sys
from pathlib import Path


def source_fingerprint(overlay: Path) -> str:
    digest = hashlib.sha256()
    for source in sorted(overlay.rglob('*')):
        if source.is_file():
            digest.update(str(source.relative_to(overlay)).encode())
            digest.update(b'\0')
            digest.update(source.read_bytes())
    return digest.hexdigest()


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == '--fingerprint':
        print(source_fingerprint(Path(sys.argv[2])))
        return
    base, overlay, destination = map(Path, sys.argv[1:])
    if not (destination / 'CMakeLists.txt').is_file():
        shutil.copytree(base, destination, ignore=shutil.ignore_patterns('.git', 'build', '__pycache__'), dirs_exist_ok=True)
    for source in overlay.rglob('*'):
        if source.is_file():
            target = destination / source.relative_to(overlay)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


if __name__ == '__main__':
    main()
