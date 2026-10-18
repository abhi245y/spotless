import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import cleanup_console as cleanup
import merge_pkg


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        main = bytearray(65536)
        main[:4] = b'\x7fFIH'
        struct.pack_into('<Q', main, 0x58, len(main))
        param = {'addcont': {}, 'titleId': merge_pkg.TITLE, 'contentId': merge_pkg.STEM,
                 'contentVersion': '01.017.000', 'requiredSystemSoftwareVersion': '0x1200000000000000'}
        sc = b'\x7fCNT' + bytes(60) + json.dumps(param).encode() + bytes(70000)
        self.data = bytes(main) + sc
        self.main = self.inputs / (merge_pkg.STEM + '.pkg')
        self.sc = self.inputs / (merge_pkg.STEM + '_sc.pkg')
        self.crc = self.inputs / (merge_pkg.STEM + '.crc')
        self.main.write_bytes(main)
        self.sc.write_bytes(sc)
        self.crc.write_bytes(b''.join(struct.pack('<I', merge_pkg.crc32c(self.data[i:i+65536])) for i in range(0, len(self.data), 65536)))
        self.output = self.root / 'merged.pkg'

    def test_castagnoli_known_vector(self):
        self.assertEqual(merge_pkg.crc32c(b'123456789'), 0xe3069283)

    def test_merge_exact_bytes_and_metadata(self):
        (self.inputs / (merge_pkg.STEM + '-DP.pkg')).write_bytes(b'optional companion')
        result = merge_pkg.merge(self.inputs, self.output, '01.017.000')
        self.assertEqual(self.output.read_bytes(), self.data)
        self.assertEqual(result['sha256'], hashlib.sha256(self.data).hexdigest())
        self.assertFalse(result['modified'])
        self.assertEqual(json.loads(self.output.with_suffix('.pkg.json').read_text()), result)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            merge_pkg.merge(self.inputs, self.output)

    def test_corruption_does_not_publish_partial_output(self):
        data = bytearray(self.sc.read_bytes()); data[-1] ^= 1; self.sc.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'CRC32C mismatch'):
            merge_pkg.merge(self.inputs, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_wrong_version_missing_piece_extra_piece_and_bad_offset(self):
        with self.assertRaisesRegex(ValueError, 'version mismatch'):
            merge_pkg.merge(self.inputs, self.output, '01.999.000')
        extra = self.inputs / 'extra.pkg'; extra.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'extra PKGs'):
            merge_pkg.merge(self.inputs, self.output)
        extra.unlink()
        data = bytearray(self.main.read_bytes()); struct.pack_into('<Q', data, 0x58, 1); self.main.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'SC offset'):
            merge_pkg.merge(self.inputs, self.output)
        self.sc.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing regular'):
            merge_pkg.merge(self.inputs, self.output)


class FakeFTP:
    def __init__(self):
        self.tree = {'/': {'data': 'd'}, '/data': {'spotless': 'd'},
                     '/data/spotless': {'watcher.log': '-', 'keep.pkg': '-'}}
        self.commands = []
    def retrlines(self, command, callback):
        for name, kind in self.tree[command[5:]].items():
            callback(kind + 'rw------- 1 1 1 12 Jan 01 00:00 ' + name)
    def voidcmd(self, command):
        self.commands.append(command)
        path = command[5:]
        parent, name = path.rsplit('/', 1)
        del self.tree[parent][name]
        return '226 Success'


class CleanupTests(unittest.TestCase):
    def test_running_process_and_incomplete_inventory_refused(self):
        cleanup.require_closed({'truncated': False, 'processes': []})
        for process in ({'title_id': 'PPSA05688'}, {'title_id': 'NPXS40201'},
                        {'name': 'CustomMusicCore'}, {'name': 'Spotless'}):
            with self.assertRaises(cleanup.CleanupError):
                cleanup.require_closed({'truncated': False, 'processes': [process]})
        for result in ({}, {'truncated': True, 'processes': []}):
            with self.assertRaises(cleanup.CleanupError): cleanup.require_closed(result)

    def test_deletion_scoped_and_226_accepted(self):
        ftp = FakeFTP()
        cleanup.remove_tree(ftp, '/data/spotless/watcher.log', '-')
        self.assertNotIn('watcher.log', ftp.tree['/data/spotless'])
        self.assertIn('keep.pkg', ftp.tree['/data/spotless'])
        for path in ('/data', '/user/app/OTHER', '/data/spotless/keep.pkg', '/system_ex/app/NPXS40201'):
            with self.assertRaises(cleanup.CleanupError): cleanup.remove_tree(ftp, path, 'd')
        with self.assertRaises(cleanup.CleanupError):
            cleanup.remove_tree(ftp, '/data/spotless/original.record', 'l')

    def test_preview_does_not_call_uninstall(self):
        with patch.object(cleanup.ftplib, 'FTP') as factory, patch.object(cleanup, 'targets', return_value=[]), patch.object(cleanup, 'api', return_value={'truncated': False, 'processes': []}) as api:
            with contextlib.redirect_stdout(io.StringIO()), patch('builtins.input') as prompt:
                cleanup.main(['--host', '192.0.2.1', '--dry-run'])
                prompt.assert_not_called()
            api.assert_not_called()
            factory.return_value.__enter__.return_value.voidcmd.assert_not_called()

    def test_default_prompt_decline_never_contacts_management_or_deletes(self):
        for answer in ('', 'n', 'no', 'NO', 'not sure'):
            with self.subTest(answer=answer), patch.object(cleanup.ftplib, 'FTP') as factory, patch.object(cleanup, 'targets', return_value=[]), patch.object(cleanup, 'api') as api, patch('builtins.input', return_value=answer) as prompt, patch.object(cleanup, 'remove_tree') as remove:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    cleanup.main(['--host', '192.0.2.1'])
                prompt.assert_called_once()
                self.assertIn('[y/N]', prompt.call_args.args[0])
                self.assertIn('192.0.2.1', prompt.call_args.args[0])
                self.assertIn(cleanup.TITLE, prompt.call_args.args[0])
                self.assertIn('No changes made', output.getvalue())
                self.assertEqual(factory.call_count, 1)
                api.assert_not_called()
                remove.assert_not_called()

    def test_unavailable_input_or_interrupt_cancels_safely(self):
        for error in (EOFError, KeyboardInterrupt):
            with self.subTest(error=error), patch.object(cleanup.ftplib, 'FTP'), patch.object(cleanup, 'targets', return_value=[]), patch.object(cleanup, 'api') as api, patch('builtins.input', side_effect=error):
                with contextlib.redirect_stdout(io.StringIO()):
                    cleanup.main(['--host', '192.0.2.1'])
                api.assert_not_called()

    def test_confirmed_engine_failure_never_deletes(self):
        with patch.object(cleanup.ftplib, 'FTP'), patch.object(cleanup, 'targets', return_value=[]), patch.object(cleanup, 'api', side_effect=cleanup.CleanupError('Engine unavailable')) as api, patch('builtins.input', return_value='YES'), patch.object(cleanup, 'remove_tree') as remove:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(cleanup.CleanupError, 'Engine unavailable'):
                cleanup.main(['--host', '192.0.2.1'])
            self.assertEqual(api.call_count, 1)
            self.assertEqual(api.call_args.args[1], 'process/list')
            remove.assert_not_called()

    def test_engine_connection_error_identifies_missing_dependency(self):
        import urllib.error
        with patch.object(cleanup.urllib.request, 'urlopen', side_effect=urllib.error.URLError(ConnectionRefusedError(111, 'Connection refused'))):
            with self.assertRaisesRegex(cleanup.CleanupError, 'Cannot reach PS5Upload engine at http://127.0.0.1:19113') as error:
                cleanup.api('http://127.0.0.1:19113', 'process/list', '192.0.2.1:9111')
            self.assertIn('--engine-url', str(error.exception))
            self.assertIn('FTP-only preview', str(error.exception))

    def test_success_reenumerates_after_verified_uninstall(self):
        closed = {'truncated': False, 'processes': []}
        responses = [closed, {'ok': True, 'sony_uninstall_refused': False,
                     'sony_uninstall_rc': '0x00000000'}, {'ok': True, 'rows': []}, closed]
        old = [('/user/download/PPSA05688', 'd')]
        residual = [('/data/spotless/watcher.log', '-')]
        with patch.object(cleanup.ftplib, 'FTP'), patch.object(cleanup, 'targets', side_effect=[old, residual, []]), patch.object(cleanup, 'api', side_effect=responses), patch('builtins.input', return_value='yes'), patch.object(cleanup, 'remove_tree') as remove:
            with contextlib.redirect_stdout(io.StringIO()):
                cleanup.main(['--host', '192.0.2.1'])
            self.assertEqual(remove.call_count, 1)
            self.assertEqual(remove.call_args.args[1:], residual[0])

    def test_registration_verification_failure_stops_deletion(self):
        closed = {'truncated': False, 'processes': []}
        responses = [closed, {'ok': True, 'sony_uninstall_refused': False,
                     'sony_uninstall_rc': '0x00000000'}, {'ok': True, 'rows': [{'titleId': cleanup.TITLE}]}]
        with patch.object(cleanup.ftplib, 'FTP'), patch.object(cleanup, 'targets', return_value=[]), patch.object(cleanup, 'api', side_effect=responses), patch('builtins.input', return_value='yes'), patch.object(cleanup, 'remove_tree') as remove:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(cleanup.CleanupError):
                cleanup.main(['--host', '192.0.2.1'])
            remove.assert_not_called()

    def test_uninstall_refusal_stops_deletion(self):
        results = [{'truncated': False, 'processes': []}] + [
            {'ok': True, 'sony_uninstall_refused': True, 'sony_uninstall_rc': '0x12345678'}]
        with patch.object(cleanup.ftplib, 'FTP'), patch.object(cleanup, 'targets', return_value=[]), patch.object(cleanup, 'api', side_effect=results), patch('builtins.input', return_value='yes'), patch.object(cleanup, 'remove_tree') as remove:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(cleanup.CleanupError):
                cleanup.main(['--host', '192.0.2.1'])
            remove.assert_not_called()


if __name__ == '__main__': unittest.main()
