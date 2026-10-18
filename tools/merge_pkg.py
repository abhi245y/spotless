#!/usr/bin/env python3
"""Verify and merge Spotify's FIH + SC retail package pieces without modifying them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile

TITLE = 'PPSA05688'
STEM = 'EP4950-PPSA05688_00-SPOTIFYMUSIC0000'
BLOCK = 65536
TABLE = []
for value in range(256):
    for _ in range(8):
        value = (value >> 1) ^ (0x82F63B78 if value & 1 else 0)
    TABLE.append(value)


def crc32c(data):
    value = 0xffffffff
    for byte in data:
        value = TABLE[(value ^ byte) & 255] ^ (value >> 8)
    return value ^ 0xffffffff


def read_param(path):
    # Retail SC metadata contains a plaintext param.json near its beginning.
    # Bound the scan rather than loading an entire package into RAM.
    with path.open('rb') as stream:
        prefix = stream.read(4 * 1024 * 1024)
    anchor = prefix.find(b'"addcont"')
    start = prefix.rfind(b'{', 0, anchor) if anchor >= 0 else -1
    if start < 0:
        raise ValueError('Unsupported SC metadata: param.json not found in first 4 MiB')
    param, _ = json.JSONDecoder().raw_decode(prefix[start:].decode('utf-8', errors='replace'))
    if param.get('titleId') != TITLE or param.get('contentId') != STEM:
        raise ValueError('Package title/content ID is not supported Spotify PPSA05688')
    if not isinstance(param.get('contentVersion'), str) or not isinstance(param.get('requiredSystemSoftwareVersion'), str):
        raise ValueError('Missing package version or firmware metadata')
    return param


def merge(folder, output, expected_version=None):
    folder, output = Path(folder), Path(output)
    main, sc, checksums = [folder / (STEM + suffix) for suffix in ('.pkg', '_sc.pkg', '.crc')]
    for path in (main, sc, checksums):
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing regular input file: ' + str(path))
    # Unknown multipart layouts must never be merged in guessed filename order.
    # The publisher may also list a -DP.pkg companion. It is not part of
    # the FIH+SC stream described by this CRC file. Keep it, but do not append it.
    companion = folder / (STEM + '-DP.pkg')
    unexpected = set(folder.glob('*.pkg')) - {main, sc, companion}
    if unexpected:
        raise ValueError('Folder contains extra PKGs. Use one clean folder per version')
    report_path = output.with_suffix(output.suffix + '.json')
    if output.exists() or report_path.exists():
        raise ValueError('Output or report already exists; choose another output path')
    with main.open('rb') as stream:
        header = stream.read(0x60)
    with sc.open('rb') as stream:
        magic = stream.read(4)
    if len(header) != 0x60 or header[:4] != b'\x7fFIH' or magic != b'\x7fCNT':
        raise ValueError('Unsupported package layout; expected FIH and CNT pieces')
    offset = struct.unpack_from('<Q', header, 0x58)[0]
    if offset != main.stat().st_size or offset % BLOCK:
        raise ValueError('FIH SC offset does not match an aligned main-piece length')
    param = read_param(sc)
    version = param['contentVersion']
    if expected_version and version != expected_version:
        raise ValueError('Package version mismatch: ' + version)
    size = main.stat().st_size + sc.stat().st_size
    blocks = (size + BLOCK - 1) // BLOCK
    if checksums.stat().st_size != blocks * 4:
        raise ValueError('CRC file length does not match the complete package')
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    pieces = []
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.' + output.name + '.', suffix='.tmp', dir=output.parent, delete=False) as dest:
            temp_path = Path(dest.name)
            with checksums.open('rb') as crc_file:
                index = 0
                for path in (main, sc):
                    piece_hash = hashlib.sha256()
                    count = 0
                    with path.open('rb') as source:
                        while True:
                            data = source.read(BLOCK)
                            if not data:
                                break
                            expected = crc_file.read(4)
                            if len(expected) != 4 or crc32c(data) != struct.unpack('<I', expected)[0]:
                                raise ValueError('CRC32C mismatch at block ' + str(index) + '; redownload inputs')
                            dest.write(data)
                            digest.update(data)
                            piece_hash.update(data)
                            count += len(data)
                            index += 1
                    pieces.append({'file': path.name, 'bytes': count, 'sha256': piece_hash.hexdigest()})
                if index != blocks or crc_file.read(1) or dest.tell() != size:
                    raise ValueError('Input changed or CRC block count mismatch')
            dest.flush()
            os.fsync(dest.fileno())
        report = {'title_id': TITLE, 'version': version,
                  'required_system_software': param['requiredSystemSoftwareVersion'],
                  'bytes': size, 'sha256': digest.hexdigest(), 'crc32c_blocks_verified': blocks,
                  'pieces': pieces, 'modified': False}
        # Exclusive creation: never overwrite an existing user's package or report.
        os.link(temp_path, output)
        try:
            with report_path.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2)
                stream.write('\n')
        except Exception:
            output.unlink()
            raise
        return report
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path, help='One version: main .pkg, _sc.pkg and .crc')
    parser.add_argument('--output', type=Path, required=True, help='New merged .pkg path')
    parser.add_argument('--expect-version', help='Refuse a different content version, e.g. 01.017.000')
    args = parser.parse_args()
    report = merge(args.folder, args.output, args.expect_version)
    print(json.dumps(report, indent=2))
    print('Created:', args.output)
    print('Metadata minimum firmware is not a runtime compatibility guarantee.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit('Merge stopped: ' + str(exc))
