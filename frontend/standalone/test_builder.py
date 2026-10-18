#!/usr/bin/env python3
import hashlib
import unittest
from pathlib import Path
from build_patch import HERE, SOURCE_SHA256, make_patch


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.source = (HERE.parent / "spotifytv.js").read_bytes()
        self.shim = (HERE / "standalone-shim.js").read_bytes()

    def test_deterministic_disjoint_exact_edits_and_unchanged_original(self):
        result, manifest, _ = make_patch(self.source, self.shim)
        self.assertEqual((result, manifest), make_patch(self.source, self.shim)[:2])
        self.assertEqual(hashlib.sha256(self.source).hexdigest(), SOURCE_SHA256)
        cursor = output_cursor = 0
        for edit in manifest["edits"]:
            offset = edit["source_byte_offset"]
            unchanged_size = offset - cursor
            self.assertEqual(result[output_cursor:output_cursor + unchanged_size], self.source[cursor:offset])
            output_cursor += unchanged_size + edit["replacement_length"]
            cursor = offset + edit["source_length"]
        self.assertEqual(result[output_cursor:], self.source[cursor:])

    def test_checked_in_payload_edits_are_current(self):
        header = make_patch(self.source, self.shim)[2]
        self.assertEqual(header, (HERE.parents[1] / "payload/ui_patch.h").read_text())

    def test_unknown_version_refused(self):
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            make_patch(self.source + b"\n", self.shim)


if __name__ == "__main__":
    unittest.main()
