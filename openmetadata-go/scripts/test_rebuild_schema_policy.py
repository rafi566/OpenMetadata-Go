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

class ObserverFinalization(unittest.TestCase):
    def test_rejects_unpinned_observer_receipts(self):
        import hashlib
        import json
        import shutil
        from unittest.mock import patch
        checkout = Path(__file__).resolve().parents[2]
        actual = checkout/'openmetadata-go/work/schema/reconstruction'
        for kind in ('java', 'source', 'limits', 'ranges'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                observer = base/'observer'
                observer.mkdir()
                for name in ('RegexObserver.java', 'regex-patterns.b64', 'regex-samples.b64',
                             'java-word-ranges.tsv', 'java-regex.tsv', 'observer-receipt.json'):
                    shutil.copyfile(actual/name, observer/name)
                receipt = json.loads((observer/'observer-receipt.json').read_text())
                expected = {'java': 'Java', 'source': 'observer source',
                            'limits': 'observer limits', 'ranges': 'word ranges'}[kind]
                if kind == 'java':
                    receipt['java_sha256'] = '0'*64
                elif kind == 'source':
                    (observer/'RegexObserver.java').write_text('unrelated observer')
                    receipt['sha256']['RegexObserver.java'] = hashlib.sha256(
                        (observer/'RegexObserver.java').read_bytes()).hexdigest()
                elif kind == 'limits':
                    receipt['heap_mib'] = 512
                else:
                    (observer/'java-word-ranges.tsv').write_text('200\t100\n')
                    receipt['sha256']['java-word-ranges.tsv'] = hashlib.sha256(
                        (observer/'java-word-ranges.tsv').read_bytes()).hexdigest()
                (observer/'observer-receipt.json').write_text(json.dumps(receipt))
                script = base/'module/scripts/rebuild_schema_policy.py'
                script.parent.mkdir(parents=True)
                shutil.copyfile(policy.__file__, script)
                argv = ['rebuild', '--root', str(checkout/'openmetadata-spec/src/main/resources/json/schema'),
                        '--output', str(base/'policy'), '--finalize', str(observer)]
                with patch.object(policy, '__file__', str(script)), patch('sys.argv', argv):
                    with self.assertRaisesRegex(ValueError, expected):
                        policy.main()


if __name__ == '__main__':
    unittest.main()
