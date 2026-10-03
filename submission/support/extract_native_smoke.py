#!/usr/bin/env python3
"""Local smoke only: extract the bundled fixed evaluator and its runtime libs.

Does not change the evaluator or substitute it for the submitted public build.
No Docker daemon or root permission is required. The archive is trusted input
from the contest package; tar paths and symbolic links stay inside destination.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shlex
import shutil
import tarfile
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('docker_archive', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.docker_archive, 'r:gz') as archive:
        manifest = json.load(archive.extractfile('manifest.json'))[0]
        config = json.load(archive.extractfile(manifest['Config']))
    history = [h for h in config['history'] if not h.get('empty_layer', False)]
    wanted: dict[str, str] = {}
    for info, layer in zip(history, manifest['Layers']):
        command = info['created_by']
        if ('ADD file:' in command or 'DependencyInstaller.sh -base' in command):
            wanted[layer] = 'runtime'
        elif ('evaluator/payload/' in command or 'mv /opt/contest/evaluator/bin/openroad_eval' in command):
            wanted[layer] = 'engine'
        elif any(token in command for token in ('container/bin/', 'container/lib/', 'config/', 'evaluator/validation/', 'evaluator-flow', 'evaluator/fixed-flow/', 'evaluator/private-template/')):
            wanted[layer] = 'tools'
    with tempfile.TemporaryDirectory(prefix='contest-smoke-layers-') as scratch:
        # Outer members are OCI layer blobs; stream them to disk without holding
        # multi-gigabyte uncompressed layers in memory.
        with tarfile.open(args.docker_archive, 'r|gz') as archive:
            for member in archive:
                if member.name not in wanted:
                    continue
                layer_path = Path(scratch) / Path(member.name).name
                with archive.extractfile(member) as source, layer_path.open('wb') as output:
                    shutil.copyfileobj(source, output)
        for layer, mode in wanted.items():
            with tarfile.open(Path(scratch) / Path(layer).name) as archive:
                for member in archive:
                    name = member.name
                    if mode == 'runtime':
                        select = (name.startswith(('usr/lib/x86_64-linux-gnu/', 'lib/x86_64-linux-gnu/')) and '.so' in name) or name.startswith(('usr/local/lib/', 'opt/or-tools/lib/', 'usr/share/tcltk/'))
                    elif mode == 'engine':
                        select = name.startswith('opt/contest/evaluator/')
                    else:
                        select = name.startswith('opt/contest/')
                    if not select or not (member.isfile() or member.issym()):
                        continue
                    try:
                        archive.extract(member, destination, filter='data')
                    except tarfile.TarError:
                        # Unneeded library aliases pointing outside extracted
                        # runtime are deliberately skipped.
                        if not member.issym():
                            raise
    runtime = shlex.quote(str(destination))
    wrapper = destination / 'openroad-eval-native'
    wrapper.write_text('#!/bin/sh\n' + f'runtime={runtime}\n' +
                       'export TCL_LIBRARY="$runtime/usr/share/tcltk/tcl8.6"\n' +
                       'engine="$runtime/opt/contest/evaluator/bin/openroad_eval.real"\n' +
                       'if [ ! -f "$engine" ]; then engine="$runtime/opt/contest/evaluator/bin/openroad_eval"; fi\n' +
                       'exec "$runtime/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2" --library-path "$runtime/usr/lib/x86_64-linux-gnu:$runtime/usr/local/lib:$runtime/opt/or-tools/lib" "$engine" "$@"\n')
    wrapper.chmod(0o755)
    print(f'Local fixed-evaluator smoke executable: {wrapper}')
    print('This executable is for local integration checks; official routing uses build.sh.')


if __name__ == '__main__':
    main()
