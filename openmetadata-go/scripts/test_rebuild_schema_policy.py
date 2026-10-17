# SPDX-License-Identifier: Apache-2.0
"""Admission controls for the source-pinned policy producer."""
from pathlib import Path
import tempfile
import unittest
import rebuild_schema_policy as policy


class InventoryAdmission(unittest.TestCase):
    def rejects(self, content, expected):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'a.json').write_text(content)
            with self.assertRaisesRegex(ValueError, expected):
                policy.inventory(root)

    def test_duplicate_decoded_key(self):
        self.rejects('{"type":true,"\\u0074ype":false}', 'duplicate')

    def test_pinned_manifest_drift(self):
        self.rejects('{}', 'manifest drift')

    def test_container_depth(self):
        self.rejects('{"x":' + '['*256 + ']'*256 + '}', 'structure bounds')

    def test_nonregular_and_symlink(self):
        import os
        for kind in ('symlink', 'fifo'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if kind == 'symlink':
                    (root/'a.json').symlink_to('missing')
                else:
                    os.mkfifo(root/'a.json')
                with self.assertRaisesRegex(ValueError, 'symlink/nonregular'):
                    policy.inventory(root)

    def test_filename_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/('a'*241+'.json')).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'filename'):
                policy.inventory(root)

    def test_document_byte_bound(self):
        self.rejects(' '*(16<<20)+'{}', 'document bounds')


if __name__ == '__main__':
    unittest.main()
