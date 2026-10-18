import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_release


class ReleaseTests(unittest.TestCase):
    def test_assets_allowlist_and_checksums(self):
        # Synthetic ELFs make release tests independent of the installed PS5 SDK.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'payload').mkdir()
            for name in ('Spotless.elf', 'Spotless-Restore.elf'):
                (root / 'payload' / name).write_bytes(b'\x7fELFfixture-' + name.encode())
            for name in build_release.FILES:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('test')
            with patch.object(build_release, 'ROOT', root):
                output = root / 'release'
                build_release.publish_release(output)
                metadata = json.loads((output / 'Spotless.meta.json').read_text())
                self.assertEqual(metadata['name'], 'Spotless')
                self.assertEqual(metadata['checksum'], hashlib.sha256((output / 'Spotless.elf').read_bytes()).hexdigest())
                for line in (output / 'SHA256SUMS').read_text().splitlines():
                    checksum, name = line.split('  ', 1)
                    self.assertEqual(checksum, hashlib.sha256((output / name).read_bytes()).hexdigest())
                expected = set(build_release.FILES) | {'Spotless.elf','Spotless-Restore.elf','Spotless.elf.sha256','Spotless-Restore.elf.sha256','Spotless.meta.json','SHA256SUMS'}
                self.assertEqual({str(p.relative_to(output)) for p in output.rglob('*') if p.is_file()}, expected)
                with self.assertRaisesRegex(ValueError, 'empty'):
                    build_release.publish_release(output)

    def test_reject_non_elf(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'bad'; source.write_bytes(b'bad')
            with self.assertRaises(ValueError): build_release.publish_elf(Path(directory) / 'out', source)


if __name__ == '__main__': unittest.main()
