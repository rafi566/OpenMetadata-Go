# SPDX-License-Identifier: Apache-2.0
"""Real filesystem contracts for the partitioned build-input guard."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from partitioned_source_guard import load_manifest, verify_manifest


class SourceGuardTests(unittest.TestCase):
    def test_actual_tampered_file_cannot_get_a_verified_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / 'source.go'
            p.write_bytes(b'original')
            p.chmod(0o600)
            manifest = {'format': 'om-go-build-inputs-v1', 'root': d,
                        'excluded_roots': [], 'files': [{'path': 'source.go',
                        'bytes': 8, 'sha256': hashlib.sha256(b'original').hexdigest(),
                        'mode': 0o600}]}
            p.write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                verify_manifest(root, manifest)

class FullSourceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / 'a.go'
        self.file.write_bytes(b'x')
        self.file.chmod(0o600)
        self.manifest = {'format': 'om-go-build-inputs-v1', 'root': str(self.root),
                         'excluded_roots': [], 'files': [{'path': 'a.go', 'bytes': 1,
                         'sha256': hashlib.sha256(b'x').hexdigest(), 'mode': 0o600}]}

    def test_complete_receipt_binds_actual_sorted_rows(self):
        result = verify_manifest(self.root, load_manifest(json.dumps(self.manifest).encode()))
        assert result['status'] == 'VERIFIED'
        assert result['files'] == 1 and result['logical_bytes'] == 1
        raw = ('[{"bytes":1,"mode":384,"path":"a.go","sha256":"'
               '2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"}]').encode()
        assert result['content_sha256'] == hashlib.sha256(raw).hexdigest()

    def test_extra_and_missing_files_fail(self):
        (self.root / 'extra').write_bytes(b'new')
        with self.assertRaises(ValueError): verify_manifest(self.root, self.manifest)
        (self.root / 'extra').unlink()
        self.file.unlink()
        with self.assertRaises(ValueError): verify_manifest(self.root, self.manifest)

    def test_single_link_control_and_external_hardlink_rejection(self):
        import os
        self.assertEqual(verify_manifest(self.root, self.manifest)['status'], 'VERIFIED')
        with tempfile.TemporaryDirectory() as outside:
            os.link(self.file, Path(outside) / 'target')
            self.assertEqual(list(self.root.iterdir()), [self.file])
            with self.assertRaisesRegex(ValueError, 'owned regular single-link file'):
                verify_manifest(self.root, self.manifest)
        self.assertEqual(verify_manifest(self.root, self.manifest)['status'], 'VERIFIED')

    def test_external_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'target'
            target.write_bytes(b'x')
            target.chmod(0o600)
            self.file.unlink()
            self.file.symlink_to(target)
            self.assertEqual(list(self.root.iterdir()), [self.file])
            with self.assertRaisesRegex(ValueError, 'owned regular single-link file'):
                verify_manifest(self.root, self.manifest)

    def test_wrong_mode_rejection(self):
        self.file.chmod(0o640)
        with self.assertRaisesRegex(ValueError, 'size/mode differs'):
            verify_manifest(self.root, self.manifest)

    def test_complete_duplicate_top_level_and_nested_objects(self):
        raw = json.dumps(self.manifest).encode()
        self.assertEqual(load_manifest(raw), self.manifest)
        for key, value in [(b'"format":', b'"format":"om-go-build-inputs-v1","format":'),
                           (b'"mode":', b'"mode":384,"mode":')]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                load_manifest(raw.replace(key, value, 1))

    def test_path_component_budget_before_large_prefix_allocation(self):
        import sys
        import partitioned_source_guard as guard
        self.manifest['files'][0]['path'] = 'a/' * 1000000 + 'f'
        raw = json.dumps(self.manifest).encode()
        work = 0
        previous = sys.gettrace()
        def bound_work(frame, event, arg):
            nonlocal work
            if event == 'line' and frame.f_code.co_filename == guard.__file__:
                work += 1
                if work > 5000:
                    raise AssertionError('admission exceeded finite line-work budget')
            return bound_work
        try:
            sys.settrace(bound_work)
            with self.assertRaisesRegex(ValueError, 'physical entry bound'):
                load_manifest(raw)
        finally:
            sys.settrace(previous)

    def test_unique_implied_directories_share_the_existing_entry_budget(self):
        row = self.manifest['files'][0]
        self.manifest['files'] = [dict(row, path=f'd{i:05}/nested/f') for i in range(10001)]
        with self.assertRaisesRegex(ValueError, 'physical entry bound'):
            load_manifest(json.dumps(self.manifest).encode())

    def test_exact_entry_budget_and_shared_prefix_boundary(self):
        path = 'd/' * 29999 + 'f'
        row = dict(self.manifest['files'][0], path=path)
        self.manifest['files'] = [row]
        self.assertEqual(load_manifest(json.dumps(self.manifest).encode()), self.manifest)
        self.manifest['files'].append(dict(row, path=path[:-1] + 'g'))
        with self.assertRaisesRegex(ValueError, 'physical entry bound'):
            load_manifest(json.dumps(self.manifest).encode())

    def test_deep_admitted_walk_uses_no_python_recursion(self):
        import sys
        self.file.unlink()
        directories = []
        parent = self.root
        for _ in range(150):
            parent = parent / 'd'
            parent.mkdir()
            directories.append(parent)
        leaf = parent / 'a.go'
        leaf.write_bytes(b'x')
        leaf.chmod(0o600)
        self.manifest['files'][0]['path'] = 'd/' * 150 + 'a.go'
        previous = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(100)
            self.assertEqual(verify_manifest(self.root, self.manifest)['status'], 'VERIFIED')
        finally:
            sys.setrecursionlimit(previous)
            leaf.unlink()
            for directory in reversed(directories):
                directory.rmdir()

    def test_excluded_subtree_does_not_hide_sibling(self):
        self.manifest['excluded_roots'] = ['work']
        (self.root / 'work').mkdir()
        (self.root / 'work' / 'output').write_bytes(b'ignored')
        assert verify_manifest(self.root, self.manifest)['files'] == 1
        (self.root / 'worker').write_bytes(b'extra')
        with self.assertRaises(ValueError): verify_manifest(self.root, self.manifest)

    def test_excluded_link_and_overlap_fail(self):
        self.manifest['excluded_roots'] = ['work']
        (self.root / 'work').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): verify_manifest(self.root, self.manifest)
        self.manifest['excluded_roots'] = ['a.go']
        with self.assertRaises(ValueError): load_manifest(json.dumps(self.manifest).encode())

    def test_strict_shapes_types_paths_and_bounds(self):
        import copy
        cases = []
        for key, value in [('bytes', True), ('mode', True), ('mode', 0o1000),
                           ('bytes', 16 * 1024**2 + 1), ('path', '../a.go'),
                           ('path', 'a//b'), ('path', 'x' * 241), ('sha256', 'A' * 64)]:
            m = copy.deepcopy(self.manifest); m['files'][0][key] = value; cases.append(m)
        m = copy.deepcopy(self.manifest); m['files'].append(dict(m['files'][0])); cases.append(m)
        m = copy.deepcopy(self.manifest); m['extra'] = 1; cases.append(m)
        for m in cases:
            with self.subTest(m=m), self.assertRaises(ValueError): load_manifest(json.dumps(m).encode())
        with self.assertRaises(ValueError): load_manifest(b' ' * (16 * 1024**2 + 1))

    def test_physical_directory_bound_cannot_be_hidden_by_file_count(self):
        from unittest.mock import patch
        import partitioned_source_guard as guard
        (self.root / 'empty1').mkdir(); (self.root / 'empty2').mkdir()
        with patch.object(guard, 'MAX_PATHS', 2):
            with self.assertRaises(ValueError): verify_manifest(self.root, self.manifest)

    def test_ancestor_symlink_is_rejected(self):
        alias = self.root.parent / (self.root.name + '-alias')
        alias.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(alias.unlink)
        self.manifest['root'] = str(alias)
        with self.assertRaises(OSError): load_manifest(json.dumps(self.manifest).encode())

    def test_changed_file_during_real_read_is_rejected(self):
        from unittest.mock import patch
        import os
        import partitioned_source_guard as guard
        original = os.read
        changed = False
        def read_then_mutate(fd, n):
            nonlocal changed
            raw = original(fd, n)
            if raw and not changed:
                changed = True
                self.file.write_bytes(b'y')
            return raw
        with patch.object(guard.os, 'read', side_effect=read_then_mutate):
            with self.assertRaises(ValueError): verify_manifest(self.root, self.manifest)

    def test_loader_rejects_existing_exclusion_links_and_non_directories(self):
        excluded = self.root / 'work'
        self.manifest['excluded_roots'] = ['work']
        excluded.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            load_manifest(json.dumps(self.manifest).encode())
        excluded.unlink()
        excluded.write_bytes(b'not a directory')
        with self.assertRaises(ValueError):
            load_manifest(json.dumps(self.manifest).encode())
        excluded.unlink()
        self.manifest['excluded_roots'] = ['absent/nested']
        self.assertEqual(load_manifest(json.dumps(self.manifest).encode()), self.manifest)
