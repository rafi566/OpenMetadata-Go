# SPDX-License-Identifier: Apache-2.0
"""Strict, streaming full-input checks for separately supervised Go builds."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import stat

MAX_MANIFEST = 16 << 20
MAX_MEMBER = 16 << 20
MAX_TOTAL = 256 << 20
MAX_PATHS = 30000


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _integer(value, maximum):
    _require(type(value) is int and 0 <= value <= maximum, 'integer bound/type')


def _digest(value):
    _require(type(value) is str and len(value) == 64 and
             all(c in '0123456789abcdef' for c in value), 'SHA256 syntax')


def _json(raw, limit):
    _require(type(raw) is bytes and len(raw) <= limit, 'JSON byte bound/type')
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('nonfinite JSON constant')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('invalid JSON encoding/depth') from error


def _relative(value, component_limit=None):
    _require(type(value) is str and value and not value.startswith('/') and
             '\\' not in value and '\x00' not in value, 'relative source path')
    if component_limit is not None:
        _require(value.count('/') < component_limit, 'physical entry bound')
    parts = value.split('/')
    try:
        _require(all(p not in ('', '.', '..') and len(p.encode('utf-8')) <= 240
                     for p in parts), 'path component')
    except UnicodeError as error:
        raise ValueError('invalid path encoding') from error
    return tuple(parts)


def _absolute(value):
    _require(type(value) is str and value.startswith('/') and
             os.path.normpath(value) == value and not value.startswith('//') and
             '\\' not in value and '\x00' not in value, 'canonical absolute path')
    if value != '/':
        _relative(value[1:])
    return Path(value)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_nlink, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextlib.contextmanager
def _directory(path):
    path = _absolute(str(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    opened = []
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=fd)
            opened.append((fd, part, child, os.fstat(child)))
            fd = child
        yield fd
        for parent, name, child, before in opened:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            _require(_identity(current) == _identity(os.fstat(child)) and
                     (current.st_dev, current.st_ino) ==
                     (before.st_dev, before.st_ino), 'directory replaced during use')
    finally:
        for parent, name, child, before in reversed(opened):
            os.close(child)
        os.close(opened[0][0] if opened else fd)


def _check_info(info, row, limit):
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
             info.st_uid == os.geteuid(), 'source must be owned regular single-link file')
    _require(info.st_size == row['bytes'] <= limit and
             stat.S_IMODE(info.st_mode) == row['mode'], 'source size/mode differs')


def _file_at(parent, name, row, limit):
    before_path = os.stat(name, dir_fd=parent, follow_symlinks=False)
    _check_info(before_path, row, limit)
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(fd)
        _require(_identity(before) == _identity(before_path), 'source changed before open')
        h = hashlib.sha256()
        count = 0
        while True:
            chunk = os.read(fd, min(1 << 20, row['bytes'] - count + 1))
            if not chunk:
                break
            count += len(chunk)
            _require(count <= row['bytes'], 'source grew during read')
            h.update(chunk)
        after_path = os.stat(name, dir_fd=parent, follow_symlinks=False)
        _require(_identity(before) == _identity(os.fstat(fd)) ==
                 _identity(after_path), 'source changed during read')
        _require(count == row['bytes'] and h.hexdigest() == row['sha256'],
                 'source bytes/SHA256 differs')
        return {'path': row['path'], 'bytes': count, 'sha256': h.hexdigest(),
                'mode': stat.S_IMODE(before.st_mode)}
    finally:
        os.close(fd)


def _admit_manifest(manifest):
    _require(type(manifest) is dict and set(manifest) ==
             {'format', 'root', 'excluded_roots', 'files'}, 'manifest fields')
    _require(manifest['format'] == 'om-go-build-inputs-v1', 'manifest version')
    root = _absolute(manifest['root'])
    rows = manifest['files']
    _require(type(rows) is list and 1 <= len(rows) <= MAX_PATHS, 'manifest row bound')
    admitted = []
    prefixes = {}
    entries = 0
    total = 0

    def insert(parts, kind):
        nonlocal entries
        node = prefixes
        message = ('exclusion overlaps source or exclusion' if kind == 'excluded'
                   else 'file/directory conflict')
        for i, part in enumerate(parts):
            _require(None not in node, message)
            if part not in node:
                # Excluded leaf roots are outside the walk; their implied
                # ancestors remain physical directories outside exclusions.
                if kind != 'excluded' or i != len(parts) - 1:
                    entries += 1
                    _require(entries <= MAX_PATHS, 'physical entry bound')
                node[part] = {}
            node = node[part]
        _require(not node, message)
        node[None] = kind

    previous = None
    for row in rows:
        _require(type(row) is dict and set(row) == {'path', 'bytes', 'sha256', 'mode'},
                 'source row fields')
        parts = _relative(row['path'], MAX_PATHS)
        _integer(row['bytes'], MAX_MEMBER)
        _integer(row['mode'], 0o777)
        _digest(row['sha256'])
        _require(previous is None or previous < row['path'], 'source rows must be sorted and unique')
        previous = row['path']
        total += row['bytes']
        _require(total <= MAX_TOTAL, 'root byte bound')
        insert(parts, 'file')
        admitted.append(dict(row))
    exclusions = manifest['excluded_roots']
    _require(type(exclusions) is list and len(exclusions) <= 16, 'exclusion bound/type')
    previous = None
    for excluded in exclusions:
        parts = _relative(excluded, MAX_PATHS)
        _require(previous is None or previous < excluded, 'exclusions sorted unique')
        previous = excluded
        insert(parts, 'excluded')
    with _directory(root):
        pass
    for excluded in exclusions:
        try:
            with _directory(root / excluded):
                pass
        except FileNotFoundError:
            pass  # A reviewed output subtree may not have been created yet.
        except OSError as error:
            raise ValueError('excluded root is not a physical directory') from error
    return root, admitted, prefixes


def load_manifest(raw: bytes) -> dict:
    manifest = _json(raw, MAX_MANIFEST)
    _admit_manifest(manifest)
    return manifest


def verify_manifest(root: Path, manifest: dict) -> dict:
    admitted_root, rows, prefixes = _admit_manifest(manifest)
    _require(_absolute(str(root)) == admitted_root, 'root binding differs')
    expected = {r['path']: r for r in rows}
    found = {}
    count = 0
    stack = []
    parts = []

    def frame(fd, node, name):
        before = os.fstat(fd)
        _require(before.st_uid == os.geteuid(), 'foreign source directory owner')
        return (fd, before, os.scandir(fd), node, name)

    try:
        with _directory(admitted_root) as root_fd:
            stack.append(frame(root_fd, prefixes, None))
            try:
                while stack:
                    fd, before, entries, node, name = stack[-1]
                    try:
                        entry = next(entries)
                    except StopIteration:
                        _require(_identity(before) == _identity(os.fstat(fd)),
                                 'directory changed during scan')
                        if name is not None:
                            parent = stack[-2][0]
                            _require(_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) ==
                                     _identity(os.fstat(fd)), 'directory replaced')
                        entries.close()
                        stack.pop()
                        if name is not None:
                            os.close(fd)
                            parts.pop()
                        continue
                    _relative(entry.name)  # Check only the new component, once.
                    info = entry.stat(follow_symlinks=False)
                    child_node = node.get(entry.name, {})
                    if child_node.get(None) == 'excluded':
                        _require(stat.S_ISDIR(info.st_mode), 'excluded path is not a physical directory')
                        continue
                    count += 1
                    _require(count <= MAX_PATHS, 'physical entry bound')
                    if stat.S_ISDIR(info.st_mode):
                        child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY |
                                        os.O_NOFOLLOW, dir_fd=fd)
                        try:
                            _require(_identity(info) == _identity(os.fstat(child)), 'directory raced')
                            child_frame = frame(child, child_node, entry.name)
                        except BaseException:
                            os.close(child)
                            raise
                        stack.append(child_frame)
                        parts.append(entry.name)
                    else:
                        path = '/'.join((*parts, entry.name))
                        _require(path in expected, 'extra source file: ' + path)
                        found[path] = _file_at(fd, entry.name, expected[path], MAX_MEMBER)
            finally:
                for fd, before, entries, node, name in reversed(stack):
                    entries.close()
                    if name is not None:
                        os.close(fd)
    except OSError as error:
        raise ValueError('unsafe/unavailable source filesystem') from error
    _require(set(found) == set(expected), 'missing source files')
    verified = [found[p] for p in sorted(found)]
    digest = hashlib.sha256(json.dumps(verified, sort_keys=True,
                             separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    return {'status': 'VERIFIED', 'files': len(verified),
            'logical_bytes': sum(r['bytes'] for r in verified), 'content_sha256': digest}
