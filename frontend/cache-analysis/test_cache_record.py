"""Offline checks using synthetic cache metadata and a public test salt."""
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from cache_record import (RecordError, decode_metadata, rebuild_record,
                          salted_sha1, validate_record)

ROOT = Path(__file__).resolve().parent
ORIGINAL = ROOT / "spotifytv-record.original"
SALT = ROOT / "test-salt.bin"
ORIGINAL_SHA256 = "8ccb74225febb30370d5930551b974c8e38b9760211667862b700e5b76465ae3"


def correct_metadata_checksum(record):
    changed = bytearray(record)
    metadata = decode_metadata(changed, verify=False)
    changed[metadata.checksum_offset:metadata.header_offset] = metadata.checksum
    return bytes(changed)


def synthetic_record(salt):
    """Independent encoder fixture exercises UTF-16, empty and null strings."""
    chunks, checksum_chunks = [], []

    def field(raw, tag):
        chunks.append(raw)
        checksum_chunks.extend((struct.pack("<I", tag), raw))

    def string(value, wide=False):
        if value is None:
            field(struct.pack("<I", 0xffffffff), 11)
        else:
            raw = value.encode("utf-16-le" if wide else "latin1")
            field(struct.pack("<I", len(raw) // (2 if wide else 1)), 11)
            field(bytes([not wide]), 3)
            field(raw, 101)

    header, body = b"opaque HTTP and certificate header\x00", b"test body"
    field(struct.pack("<I", 16), 11)
    string("")
    string("Resource")
    string("https://example.test/\u03c0", wide=True)
    string(None)
    field(bytes(range(20)), 101)
    field(bytes(range(20, 40)), 101)
    field(struct.pack("<d", 123456.25), 29)
    field(salted_sha1(header, salt), 101)
    field(struct.pack("<Q", len(header)), 13)
    field(salted_sha1(body, salt), 101)
    field(struct.pack("<Q", len(body)), 13)
    field(b"\x01", 3)
    return b"".join(chunks) + hashlib.sha1(b"".join(checksum_chunks)).digest() + header + body


class MetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = ORIGINAL.read_bytes()

    def test_synthetic_fixture_metadata_checksum_and_identity(self):
        self.assertEqual(hashlib.sha256(self.original).hexdigest(), ORIGINAL_SHA256)
        metadata = decode_metadata(self.original)
        self.assertEqual(metadata.checksum.hex(), "c93d0b8c5867335f22c02eec9141529b15b3cc71")
        self.assertEqual(metadata.identifier, "https://tv.scdn.co/ps5/v2/f1b1b7e/js/spotifytv.js")
        self.assertEqual((metadata.header_offset, metadata.header_size, metadata.body_offset,
                          metadata.body_size), (205, 4853, 5058, 2144073))
        self.assertEqual((metadata.body_hash_offset, metadata.body_size_offset,
                          metadata.checksum_offset), (0x9c, 0xb0, 0xb9))

    def test_metadata_corruption_and_truncation_rejected(self):
        for length in (0, 3, 13, 80, 128, 184, 204):
            with self.subTest(length=length), self.assertRaises(RecordError):
                decode_metadata(self.original[:length])
        changed = bytearray(self.original)
        changed[0x78] ^= 1
        with self.assertRaisesRegex(RecordError, "typed checksum"):
            decode_metadata(changed)

    def test_unsupported_version_and_boolean_rejected(self):
        changed = bytearray(self.original)
        changed[0] = 17
        with self.assertRaisesRegex(RecordError, "format 16"):
            decode_metadata(changed)
        changed = bytearray(self.original)
        changed[0xb8] = 2
        with self.assertRaisesRegex(RecordError, "boolean"):
            decode_metadata(changed)

    def test_null_empty_utf16_keys_and_nonfixed_offsets(self):
        salt = b"independent test salt"
        record = synthetic_record(salt)
        metadata = validate_record(record, salt)
        self.assertIsNone(metadata.byte_range)
        self.assertEqual(metadata.partition, "")
        self.assertEqual(metadata.identifier, "https://example.test/\u03c0")
        self.assertNotEqual(metadata.header_offset, 205)
        result = rebuild_record(record, b"replacement", salt)
        self.assertEqual(result[validate_record(result, salt).body_offset:], b"replacement")


class SaltedCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SALT.exists():
            raise unittest.SkipTest("console test-salt.bin not acquired")
        cls.original = ORIGINAL.read_bytes()
        cls.salt = SALT.read_bytes()
        cls.metadata = validate_record(cls.original, cls.salt)

    def test_original_validates_and_noop_is_identical(self):
        self.assertEqual(rebuild_record(self.original, self.original[self.metadata.body_offset:],
                                        self.salt), self.original)

    def test_different_body_lengths_preserve_header_and_other_fields(self):
        for body in (b"", b"x", self.original[self.metadata.body_offset:] + b"\n// offline test\n"):
            with self.subTest(length=len(body)):
                result = rebuild_record(self.original, body, self.salt)
                updated = validate_record(result, self.salt)
                self.assertEqual(result[updated.body_offset:], body)
                self.assertEqual(result[updated.header_offset:updated.body_offset],
                                 self.original[self.metadata.header_offset:self.metadata.body_offset])
                changed_ranges = ((self.metadata.body_hash_offset, self.metadata.body_hash_offset + 20),
                                  (self.metadata.body_size_offset, self.metadata.body_size_offset + 8),
                                  (self.metadata.checksum_offset, self.metadata.header_offset))
                for index in range(self.metadata.body_offset):
                    if not any(start <= index < end for start, end in changed_ranges):
                        self.assertEqual(result[index], self.original[index])

    def test_bad_salt_header_body_and_tail_rejected(self):
        with self.assertRaisesRegex(RecordError, "salted header"):
            validate_record(self.original, self.salt + b"wrong")
        for offset, expected in ((self.metadata.header_offset, "salted header"),
                                 (self.metadata.body_offset, "salted body")):
            changed = bytearray(self.original)
            changed[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaisesRegex(RecordError, expected):
                rebuild_record(changed, b"replacement", self.salt)
        for changed in (self.original[:-1], self.original + b"extra"):
            with self.assertRaisesRegex(RecordError, "body size"):
                validate_record(changed, self.salt)

    def test_external_blob_and_oversized_header_rejected(self):
        changed = bytearray(self.original)
        changed[0xb8] = 0
        with self.assertRaisesRegex(RecordError, "external blob"):
            validate_record(correct_metadata_checksum(changed), self.salt)
        changed = bytearray(self.original)
        struct.pack_into("<Q", changed, 0x94, len(changed) + 1)
        with self.assertRaisesRegex(RecordError, "header size"):
            validate_record(correct_metadata_checksum(changed), self.salt)

    def test_cli_exclusive_output_and_inputs_preserved(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            body = directory / "body.js"
            output = directory / "rebuilt.record"
            body.write_bytes(b"// offline replacement\n")
            command = [sys.executable, "-B", str(ROOT / "cache_record.py"), str(ORIGINAL),
                       "--salt", str(SALT), "--body", str(body), "--output", str(output)]
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            saved = output.read_bytes()
            self.assertEqual(validate_record(saved, self.salt).body_size, body.stat().st_size)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            again = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(output.read_bytes(), saved)
            protected = subprocess.run(command[:-1] + [str(ORIGINAL)], capture_output=True, text=True)
            self.assertNotEqual(protected.returncode, 0)
            self.assertEqual(hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(), ORIGINAL_SHA256)


if __name__ == "__main__":
    unittest.main(verbosity=2)
