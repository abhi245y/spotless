#!/usr/bin/env python3
"""Publish standalone release assets from an explicit allowlist; no archives."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
FILES = ('INSTALL.md', 'tools/cleanup_console.py', 'tools/merge_pkg.py',
         'docs/PACKAGES.md', 'docs/TROUBLESHOOTING.md')


def publish_elf(output, source=None):
    payload = (source or ROOT / 'payload/Spotless.elf').read_bytes()
    if not payload.startswith(b'\x7fELF'):
        raise ValueError('Build the native ELF first')
    if b'spotifytv.js.LICENSE.txt' in payload:
        raise ValueError('ELF embeds Spotify frontend code; rebuild from the edit table')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    output.with_name(output.name + '.sha256').write_text(checksum + '  ' + output.name + '\n')


def publish_release(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Refuse stale assets instead of silently shipping files from an older release.
    if any(directory.iterdir()):
        raise ValueError('Output directory must be empty; choose a fresh release directory')
    for name in ('Spotless.elf', 'Spotless-Restore.elf'):
        publish_elf(directory / name, ROOT / 'payload' / name)
    for name in FILES:
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    metadata = {'schema': 2, 'kind': 'local', 'filename': 'Spotless.elf', 'name': 'Spotless',
                'version': '0.2.0-beta', 'description': 'Standalone Spotify UI patch. Stock Spotify sign-in.',
                'checksum': hashlib.sha256((directory / 'Spotless.elf').read_bytes()).hexdigest()}
    (directory / 'Spotless.meta.json').write_text(json.dumps(metadata, indent=2) + '\n')
    manifest = {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(directory.rglob('*')) if path.is_file()}
    (directory / 'SHA256SUMS').write_text(''.join(value + '  ' + name + '\n' for name, value in manifest.items()))
    print('Created standalone assets:', directory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist/release')
    args = parser.parse_args()
    publish_release(args.output_dir)
