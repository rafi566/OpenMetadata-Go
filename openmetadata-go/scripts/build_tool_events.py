# SPDX-License-Identifier: Apache-2.0
"""Driver-bound v2 events. The outer controller remains execution authority.

Resolved contexts add only five private in-memory fields. Replay authenticates
immutable controls; callback admission additionally verifies live parent ancestry.
"""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

import record_partitioned_tool as v1
from partitioned_source_guard import (_absolute, _digest, _directory, _identity,
                                      _integer, _json, _relative, _require)

POLICY_LIMIT = 256*1024
EVENT_LIMIT = 128*1024
JOURNAL_LIMIT = 16*1024*1024
ARGUMENT_LIMIT = 8*1024*1024
EVENT_COUNT = 512
HOST_SECONDS = 10
HOST_BYTES = 65536
PRIVATE = {'_path', '_sha256', '_config', '_start', '_policy'}
CONTEXT_KEYS = {'format', 'job_id', 'driver_id', 'config', 'start', 'policy'}
PIN_KEYS = {'path', 'bytes', 'sha256', 'mode'}
HOST_PATHS = {'CC': ('c', '/usr/bin/x86_64-linux-gnu-gcc-14'),
              'CXX': ('c++', '/usr/bin/x86_64-linux-gnu-g++-14')}
CAPS = dict(raw_bytes=33554432, segment_bytes=4194304, response_bytes=4096,
            request_bytes=16777216, pre_seconds=10, run_seconds=60,
            post_seconds=10, outer_seconds=900, cleanup_seconds=20, max_drivers=33)


def _object(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys), label+' keys')


def _text(value, limit, label):
    _require(type(value) is str and '\x00' not in value, label+' type/NUL')
    _require(len(value.encode('utf-8')) <= limit, label+' byte bound')
    return value


def _strict(raw, limit):
    value = _json(raw, limit)
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
        elif type(item) is str:
            _text(item, limit, 'JSON string')
        elif type(item) is float:
            _require(False, 'noninteger JSON number')
    return value


def _id(value):
    _require(type(value) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value), 'ID')
    return value


def _identity_shape(value):
    _object(value, {'pid', 'start_ticks'}, 'identity')
    for number in value.values():
        _integer(number, (1 << 63)-1)
        _require(number >= 1, 'positive identity')
    return value


def _process(pid):
    _integer(pid, (1 << 63)-1)
    raw = Path('/proc') / str(pid) / 'stat'
    data = raw.read_bytes()
    _require(len(data) <= 65536, 'process stat bound')
    fields = data[data.rfind(b')')+2:].split()
    return dict(pid=pid, start_ticks=int(fields[19])), int(fields[1])


def _pin_shape(pin, maximum=64*1024*1024, host=False):
    _object(pin, PIN_KEYS | ({'uid', 'gid'} if host else set()), 'host pin' if host else 'pin')
    _absolute(pin['path'])
    _integer(pin['bytes'], maximum)
    _integer(pin['mode'], 0o777)
    _digest(pin['sha256'])
    if host:
        _require(type(pin['uid']) is int and pin['uid'] == 0 and
                 type(pin['gid']) is int and pin['gid'] == 0 and pin['mode'] == 493, 'host root pin')
    return pin


def _check_pin_stat(info, pin, host=False):
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'pin regular single-link')
    _require(info.st_size == pin['bytes'] and stat.S_IMODE(info.st_mode) == pin['mode'], 'pin size/mode')
    if host:
        _require(info.st_uid == pin['uid'] and info.st_gid == pin['gid'] == 0, 'host owner')
    else:
        _require(info.st_uid == os.geteuid(), 'pin owner')


def _pin_bytes(pin, maximum=64*1024*1024, host=False, control=False):
    _pin_shape(pin, maximum, host)
    path = Path(pin['path'])
    with _directory(path.parent) as parent:
        if control:
            directory = os.fstat(parent)
            _require(directory.st_uid == os.geteuid() and stat.S_IMODE(directory.st_mode) == 0o700
                     and pin['mode'] == 0o600, 'private control')
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _check_pin_stat(before, pin, host)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            _require(_identity(before) == _identity(os.fstat(fd)), 'pin open identity')
            pieces = []
            count = 0
            digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, min(65536, pin['bytes']-count+1))
                if not chunk:
                    break
                count += len(chunk)
                _require(count <= pin['bytes'], 'pin grew')
                digest.update(chunk)
                pieces.append(chunk)
            _require(count == pin['bytes'] and digest.hexdigest() == pin['sha256'], 'pin SHA')
            _require(_identity(before) == _identity(os.fstat(fd)) == _identity(os.stat(
                     path.name, dir_fd=parent, follow_symlinks=False)), 'pin changed')
            return b''.join(pieces)
        finally:
            os.close(fd)


def _verify_host_pin(pin):
    return _pin_bytes(pin, host=True)


def load_job_policy(raw: bytes) -> dict:
    policy = _strict(raw, POLICY_LIMIT)
    _object(policy, v1.KEYS | {'host_id_probes'}, 'v2 policy')
    _require(policy['format'] == 'om-go-tool-record-policy-v2', 'v2 policy format')
    old = {k: value for k, value in policy.items() if k != 'host_id_probes'}
    old['format'] = 'om-go-tool-record-policy-v1'
    v1.load_policy(v1._encoded(old))
    hosts = policy['host_id_probes']
    _require(type(hosts) is list and len(hosts) <= 2, 'host count')
    roles = []
    for host in hosts:
        _object(host, {'role', 'language', 'tool'}, 'host')
        role = host['role']
        _require(type(role) is str and role in HOST_PATHS, 'host role')
        language, path = HOST_PATHS[role]
        _pin_shape(host['tool'], host=True)
        _require(host['language'] == language and host['tool']['path'] == path, 'host role/path/language')
        _require(path not in [tool['path'] for tool in policy['tools']], 'host/SDK overlap')
        _verify_host_pin(host['tool'])
        roles.append(role)
    _require(roles == sorted(set(roles)), 'host order/duplicates')
    return policy


def _vector(value, count=32, byte_bound=16384):
    _require(type(value) is list and 1 <= len(value) <= count, 'argv count')
    for item in value:
        _text(item, byte_bound, 'argument')
    _require(len(v1._encoded(value)) <= byte_bound, 'argv bytes')
    return value


def _environment(value, count, byte_bound):
    _require(type(value) is dict and len(value) <= count, 'environment count')
    for key, item in value.items():
        _text(key, byte_bound, 'environment key')
        _require(key and '=' not in key, 'environment key')
        _text(item, byte_bound, 'environment value')
    _require(len(v1._encoded(value)) <= byte_bound, 'environment bytes')


def _physical(path, private=False):
    value = _absolute(path)
    with _directory(value) as fd:
        info = os.fstat(fd)
        if private:
            _require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700, 'private root')
    return value


def _config(raw):
    config = _strict(raw, POLICY_LIMIT)
    _object(config, {'format', 'job_id', 'module_root', 'input_manifest', 'sdk_go', 'tool_policy',
                    'toolexec_argv', 'environment', 'roots', 'root_driver', 'fixture_slots', 'coverage', 'caps'}, 'config')
    _require(config['format'] == 'om-build-job-v1', 'config format')
    _id(config['job_id'])
    module = _physical(config['module_root'])
    for key, maximum in [('input_manifest', 16*1024*1024), ('sdk_go', 64*1024*1024), ('tool_policy', POLICY_LIMIT)]:
        _pin_shape(config[key], maximum)
    argv = _vector(config['toolexec_argv'])
    _require(len(argv) == 7 and argv[1] == '-B' and argv[3] == '--policy' and
             argv[4] == config['tool_policy']['path'] and argv[5] == '--policy-sha256' and
             argv[6] == config['tool_policy']['sha256'], 'template toolexec token')
    _absolute(argv[0]); _absolute(argv[2])
    _environment(config['environment'], 64, 65536)
    for key in ('GOMODCACHE', 'GOTMPDIR', 'TMPDIR'):
        _require(key in config['environment'], 'released callback root')
        _physical(config['environment'][key])
    _require(config['environment'].get('GODEBUG') == 'gocachehash=1', 'gocachehash environment')
    _object(config['roots'], {'fixtures', 'records', 'drivers', 'registrations'}, 'roots')
    roots = [_physical(value, True) for value in config['roots'].values()]
    _require(len(set(roots)) == 4 and len({p.parent for p in roots}) == 1, 'sibling roots')
    _require(all(p != module and module not in p.parents and p not in module.parents for p in roots), 'roots/source overlap')
    _object(config['root_driver'], {'driver_id', 'argv'}, 'root driver')
    driver = _id(config['root_driver']['driver_id'])
    _vector(config['root_driver']['argv'])
    slots = config['fixture_slots']
    _require(type(slots) is list and len(slots) <= 32, 'fixture slots')
    ids = {driver}
    names = set()
    for slot in slots:
        _object(slot, {'driver_id', 'test_name', 'package', 'support_paths'}, 'fixture slot')
        identity = _id(slot['driver_id'])
        _require(identity not in ids, 'duplicate driver')
        ids.add(identity)
        _text(slot['test_name'], 512, 'test name')
        _require(slot['test_name'] and slot['test_name'] not in names, 'duplicate test name')
        names.add(slot['test_name'])
        _require(type(slot['package']) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', slot['package']), 'package')
        paths = slot['support_paths']
        _require(type(paths) is list and len(paths) <= 30000, 'support paths')
        for path in paths: _relative(path, 30000)
        _require(paths == sorted(set(paths)), 'support path order')
    coverage = config['coverage']
    _require(type(coverage) is list and len(coverage) == len(ids), 'coverage count')
    coverage_ids = []
    for row in coverage:
        _object(row, {'driver_id', 'plan'}, 'coverage')
        coverage_ids.append(_id(row['driver_id']))
        _pin_shape(row['plan'], POLICY_LIMIT)
    _require(coverage_ids == sorted(ids), 'coverage drivers')
    _object(config['caps'], CAPS, 'caps')
    _require(all(type(config['caps'][key]) is int and config['caps'][key] == value
                 for key, value in CAPS.items()), 'fixed caps')
    return config


def _process_image(pid):
    return os.readlink('/proc/'+str(pid)+'/exe')


def _parent_sdk(recorder_pid, start, config):
    recorder, parent = _process(recorder_pid)
    actual_parent, _ = _process(parent)
    _require(actual_parent == start['go_identity'], 'registered parent identity')
    image = _process_image(parent)
    _require(image == config['sdk_go']['path'], 'parent SDK executable')
    _pin_bytes(config['sdk_go'])
    # Recheck PID/start after executable admission; never accept PID alone.
    _require(_process(parent)[0] == actual_parent and _process(recorder_pid) == (recorder, parent), 'parent changed')
    return recorder


def _resolve_context(path, expected_sha256, *, recorder_pid=None):
    path = _absolute(str(path))
    _digest(expected_sha256)
    raw = v1._read_file(str(path), 16384)
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'context SHA')
    context = _strict(raw, 16384)
    _object(context, CONTEXT_KEYS, 'context')
    _require(context['format'] == 'om-go-context-v1', 'context format')
    _id(context['job_id']); _id(context['driver_id'])
    # Root-owned controls are outside fixture outputs; all control bytes are pinned.
    _pin_bytes(dict(path=str(path), bytes=len(raw), sha256=expected_sha256, mode=0o600), 16384, control=True)
    config = _config(_pin_bytes(context['config'], POLICY_LIMIT, control=True))
    start = _strict(_pin_bytes(context['start'], POLICY_LIMIT, control=True), POLICY_LIMIT)
    _object(start, {'format', 'job_id', 'driver_id', 'parent_driver_id', 'go_identity', 'sdk_go', 'manifest'}, 'start')
    _require(start['format'] == 'om-go-driver-start-v1' and start['job_id'] == context['job_id'] == config['job_id']
             and start['driver_id'] == context['driver_id'], 'start/context binding')
    _identity_shape(start['go_identity'])
    _require(start['sdk_go'] == config['sdk_go'], 'start SDK binding')
    _pin_bytes(start['sdk_go'])
    _pin_shape(start['manifest'], 16*1024*1024)
    from partitioned_source_guard import load_manifest
    manifest = load_manifest(_pin_bytes(start['manifest'], 16*1024*1024, control=True))
    template_raw = _pin_bytes(config['tool_policy'], POLICY_LIMIT, control=True)
    template = load_job_policy(template_raw)
    effective_raw = _pin_bytes(context['policy'], POLICY_LIMIT, control=True)
    effective = load_job_policy(effective_raw)
    _require(template['record_directory'] == config['roots']['records'], 'shared records binding')
    _require(config['environment'].get('GOROOT') in (None, '', template['toolchain_root']), 'released SDK root')
    if context['driver_id'] == config['root_driver']['driver_id']:
        _require(start['parent_driver_id'] is None and context['policy'] == config['tool_policy']
                 and effective_raw == template_raw and effective['working_directory'] == config['module_root']
                 and start['manifest'] == config['input_manifest']
                 and manifest['root'] == config['module_root'], 'root context binding')
    else:
        _require(context['driver_id'] in {slot['driver_id'] for slot in config['fixture_slots']}
                 and start['parent_driver_id'] == config['root_driver']['driver_id'], 'fixture slot/parent')
        root = _physical(manifest['root'])
        _require(Path(config['roots']['fixtures']) in root.parents and
                 effective['working_directory'] == str(root), 'fixture manifest root')
        derived = dict(template, working_directory=str(root))
        _require(effective == derived and effective_raw == v1._encoded(derived)+b'\n', 'derived policy')
    source_root = Path(effective['working_directory'])
    for control in (dict(path=str(path)), context['config'], context['start'], context['policy'], start['manifest']):
        control_path = Path(control['path'])
        _require(control_path != source_root and source_root not in control_path.parents, 'control inside input')
        _require(Path(config['roots']['registrations']) in control_path.parents, 'control outside registrations')
    if recorder_pid is not None:
        _parent_sdk(recorder_pid, start, config)
    return context | dict(_path=str(path), _sha256=expected_sha256, _config=config, _start=start, _policy=effective)


def load_driver_context(path: Path, expected_sha256: str) -> dict:
    return _resolve_context(path, expected_sha256, recorder_pid=os.getpid())


def _resolved(context, live):
    _require(type(context) is dict and set(context) in (CONTEXT_KEYS | PRIVATE,
             CONTEXT_KEYS | {'_path', '_sha256'}), 'resolved context keys')
    _absolute(context['_path']); _digest(context['_sha256'])
    result = _resolve_context(context['_path'], context['_sha256'],
                              recorder_pid=os.getpid() if live else None)
    _require(all(context[key] == result[key] for key in CONTEXT_KEYS), 'context locator binding')
    return result


def _under(path, root):
    path, root = _absolute(path), _absolute(root)
    return path == root or root in path.parents


def _cwd(context, cwd, foreign=False):
    _absolute(cwd)
    config, policy = context['_config'], context['_policy']
    roots = [policy['working_directory'], policy['toolchain_root']+'/src']
    for key in ('GOMODCACHE', 'GOTMPDIR', 'TMPDIR'):
        _require(key in config['environment'], 'released callback root')
        _absolute(config['environment'][key])
        roots.append(config['environment'][key])
    if foreign:
        roots.extend([config['roots']['fixtures'], config['module_root']])
    _require(any(_under(cwd, root) for root in roots), 'callback cwd outside released roots')


PROTECTED = {'HOME', 'XDG_CACHE_HOME', 'PATH', 'TMP', 'GOFLAGS', 'GODEBUG', 'CC', 'CXX', 'PKG_CONFIG', 'GOROOT', 'GOTOOLDIR',
             'GOPATH', 'GOCACHE', 'GOMODCACHE', 'GOTMPDIR', 'TMPDIR', 'GOTOOLCHAIN',
             'GOPROXY', 'GOSUMDB', 'GONOSUMDB', 'GONOPROXY', 'GOPRIVATE', 'GOVCS',
             'GOENV', 'GO111MODULE', 'CGO_ENABLED', 'GOOS', 'GOARCH', 'GOEXPERIMENT'}


def _callback(context, importpath, probe=False, host=False):
    actual = dict(os.environ)
    _environment(actual, 128, 128*1024)
    expected = dict(context['_config']['environment'])
    expected['OM_GO_SUPERVISION_CONTEXT'] = context['_path']
    expected['OM_GO_SUPERVISION_CONTEXT_SHA256'] = context['_sha256']
    _require(expected.get('OM_BUILD_JOB_ID') == context['job_id'], 'job environment binding')
    for name, native in (('GOOS', 'linux'), ('GOARCH', 'amd64'),
                         ('GOROOT', context['_policy']['toolchain_root'])):
        if expected.get(name) in (None, '') and actual.get(name) == native:
            expected[name] = native
    for name in set(actual) | set(expected):
        if name in PROTECTED or name.startswith('GO') or name.startswith('OM_'):
            _require(name in expected and name in actual and actual[name] == expected[name],
                     'protected environment override: '+name)
    if not host:
        _require(('LC_ALL' in actual) == ('LC_ALL' in expected) and
                 actual.get('LC_ALL') == expected.get('LC_ALL'), 'released SDK LC_ALL')
    cwd = os.getcwd()
    _physical(cwd)
    _require(actual.get('PWD') == cwd, 'actual callback PWD')
    _cwd(context, cwd)
    _text(importpath, 128*1024, 'SDK description')
    _require(actual.get('TOOLEXEC_IMPORTPATH', '') == importpath, 'actual SDK description')
    _require(importpath or probe, 'empty SDK description outside probe')
    return cwd


def _host_admission(policy, argv):
    v1._argument_bytes(argv)
    for host in policy['host_id_probes']:
        if argv[0] == host['tool']['path']:
            _require(argv == [host['tool']['path'], '-###', '-x', host['language'], '-c', '-'],
                     'exact host probe argv')
            return host
    raise ValueError('unreleased host tool')


def _blob(value, maximum, stream=False):
    keys = {'bytes', 'sha256', 'base64'} | ({'eof', 'lost_bytes'} if stream else set())
    _object(value, keys, 'stream' if stream else 'release ID')
    _integer(value['bytes'], maximum); _digest(value['sha256'])
    _text(value['base64'], 87384, 'base64')
    try:
        raw = base64.b64decode(value['base64'], validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError('invalid base64') from error
    _require(base64.b64encode(raw).decode('ascii') == value['base64'] and
             len(raw) == value['bytes'] and hashlib.sha256(raw).hexdigest() == value['sha256'], 'blob bytes/SHA')
    if stream:
        _require(type(value['eof']) is bool, 'stream EOF')
        if value['lost_bytes'] is not None: _integer(value['lost_bytes'], (1 << 63)-1)
    return raw


WHITE_SPACE = re.compile('[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+')


def _gcc_id(stderr):
    for raw in stderr.split(b'\n'):
        fields = [value for value in WHITE_SPACE.split(raw.decode('utf-8', errors='replace')) if value]
        for index, value in enumerate(fields):
            if value.endswith(':'):
                break
            if value == 'version' and index+1 < len(fields) and fields[index+1][:1] in '0123456789':
                _require(b'experimental' not in raw.lower() and len(raw) <= 4096, 'experimental/oversize GCC ID')
                return raw
    raise ValueError('missing GCC version')


def _data(kind, data, envelope, policy, context, foreign):
    if kind == 'sdk':
        _pin_shape(data.get('tool') if type(data) is dict else None)
        v1._validate_record(data, policy, envelope['policy_sha256'])
        _require(dict(pid=data['pid'], start_ticks=data['start_ticks']) == envelope['recorder'], 'SDK recorder identity')
        _cwd(context, data['cwd'], foreign)
        _text(data['importpath'], 128*1024, 'SDK description')
        _require(data['importpath'] or data['classification'] == 'version-probe', 'empty SDK description')
        return v1._argument_bytes(data['argv'])
    if kind == 'host-start':
        _object(data, {'role', 'language', 'tool', 'argv', 'importpath', 'cwd'}, 'host start')
        _pin_shape(data['tool'], host=True)
        host = _host_admission(policy, data['argv'])
        _require({key: data[key] for key in ('role', 'language', 'tool')} == host, 'host start binding')
        _text(data['importpath'], 128*1024, 'host description')
        _cwd(context, data['cwd'], foreign)
        return v1._argument_bytes(data['argv'])
    _require(kind == 'host-complete', 'unknown event kind')
    _object(data, {'start_seq', 'child', 'terminal', 'elapsed_ns', 'stdout', 'stderr', 'release_id', 'outcome'}, 'host completion')
    _integer(data['start_seq'], EVENT_COUNT); _require(data['start_seq'] > 0, 'start seq')
    _integer(data['elapsed_ns'], (1 << 63)-1)
    _require(data['outcome'] in ('ok', 'spawn_error', 'exit_nonzero', 'signal', 'timeout', 'overflow', 'io_error', 'parse_error'), 'host outcome')
    if data['child'] is not None: _identity_shape(data['child'])
    terminal = data['terminal']
    if terminal is not None:
        _object(terminal, {'exit_code', 'signal'}, 'host terminal')
        _require((terminal['exit_code'] is None) != (terminal['signal'] is None), 'terminal choice')
        if terminal['exit_code'] is not None: _integer(terminal['exit_code'], 255)
        if terminal['signal'] is not None:
            _integer(terminal['signal'], 64); _require(terminal['signal'] > 0, 'terminal signal')
    _require(data['child'] is not None or (data['outcome'] == 'spawn_error' and terminal is None),
             'missing host child identity')
    out = _blob(data['stdout'], HOST_BYTES, True)
    err = _blob(data['stderr'], HOST_BYTES, True)
    _require(len(out)+len(err) <= HOST_BYTES and
             len(data['stdout']['base64'])+len(data['stderr']['base64']) <= 87384, 'combined host stream bound')
    release = data['release_id']
    if release is not None:
        raw = _blob(release, 4096)
        _require(b'\n' not in raw and raw == _gcc_id(err), 'observed release ID')
    if data['outcome'] == 'ok':
        _require(data['child'] is not None and terminal == dict(exit_code=0, signal=None)
                 and data['elapsed_ns'] <= HOST_SECONDS*1000000000 and not out and release is not None
                 and all(data[name]['eof'] and data[name]['lost_bytes'] == 0 for name in ('stdout', 'stderr')), 'successful host completion')
    elif data['outcome'] == 'spawn_error':
        _require(data['child'] is None and terminal is None and release is None, 'spawn failure terminal')
    elif data['outcome'] == 'exit_nonzero':
        _require(terminal is not None and terminal['exit_code'] is not None and terminal['exit_code'] > 0, 'nonzero terminal')
    elif data['outcome'] == 'signal':
        _require(terminal is not None and terminal['signal'] is not None, 'signal terminal')
    return 0


ENVELOPE = {'format', 'seq', 'kind', 'job_id', 'driver_id', 'parent_go', 'recorder', 'policy_sha256', 'data'}


def _replay(rows, context, contexts=None, final=False):
    config = context['_config']
    ids = {config['root_driver']['driver_id']} | {slot['driver_id'] for slot in config['fixture_slots']}
    pending = {}
    arguments = journal_bytes = 0
    parents = {}
    for seq, row in enumerate(rows, 1):
        _object(row, ENVELOPE, 'event')
        _require(row['format'] == 'om-go-tool-event-v2' and type(row['seq']) is int and row['seq'] == seq, 'event sequence')
        _require(row['job_id'] == config['job_id'] and row['driver_id'] in ids, 'released event driver')
        _identity_shape(row['parent_go']); _identity_shape(row['recorder']); _digest(row['policy_sha256'])
        driver = row['driver_id']
        _require(driver not in parents or parents[driver] == row['parent_go'], 'inconsistent driver parent')
        parents[driver] = row['parent_go']
        authenticated = context if driver == context['driver_id'] else None
        if contexts is not None:
            _require(driver in contexts, 'missing authenticated driver context')
            authenticated = contexts[driver]
        if authenticated is not None:
            _require(authenticated['job_id'] == row['job_id'] and authenticated['driver_id'] == driver
                     and row['parent_go'] == authenticated['_start']['go_identity']
                     and row['policy_sha256'] == authenticated['policy']['sha256'], 'event context binding')
            active = authenticated
        else:
            active = context
        arguments += _data(row['kind'], row['data'], row, active['_policy'], active, authenticated is None)
        if row['kind'] == 'host-start':
            pending[seq] = row
        elif row['kind'] == 'host-complete':
            start_seq = row['data']['start_seq']
            _require(start_seq in pending, 'missing/duplicate host start')
            start = pending.pop(start_seq)
            _require(all(row[key] == start[key] for key in ('driver_id', 'recorder', 'parent_go', 'policy_sha256')), 'completion/start binding')
        encoded_bytes = len(v1._encoded(row))+1
        _require(encoded_bytes <= EVENT_LIMIT, 'event bytes')
        journal_bytes += encoded_bytes
        _require(seq+len(pending) <= EVENT_COUNT, 'event/reservation count')
        _require(journal_bytes+len(pending)*EVENT_LIMIT <= JOURNAL_LIMIT, 'journal/reservation bytes')
        _require(arguments <= ARGUMENT_LIMIT, 'job argument budget')
    if final: _require(not pending, 'missing host completion')
    return arguments, journal_bytes, pending


@contextlib.contextmanager
def _journal(record_directory):
    path = _physical(str(record_directory), True)
    with _directory(path) as parent:
        fd = os.open('records.jsonl', os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            info = v1._journal_info(fd, parent)
            _require(info.st_size <= JOURNAL_LIMIT, 'journal bytes')
            yield fd, parent, info
        finally:
            os.close(fd)


def _read_rows(fd, info, parent):
    rows = []
    total = 0
    os.lseek(fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(fd), 'rb') as stream:
        while True:
            line = stream.readline(EVENT_LIMIT+1)
            if not line: break
            _require(len(rows) < EVENT_COUNT and len(line) <= EVENT_LIMIT and line.endswith(b'\n'), 'event framing/count')
            total += len(line)
            _require(total <= JOURNAL_LIMIT, 'journal bytes')
            row = _strict(line, EVENT_LIMIT)
            _require(v1._encoded(row)+b'\n' == line, 'canonical event encoding')
            rows.append(row)
    _require(total == info.st_size and _identity(info) == _identity(v1._journal_info(fd, parent)), 'journal changed')
    return rows


def _write_all(fd, data):
    remaining = memoryview(data)
    while remaining:
        count = os.write(fd, remaining)
        _require(count > 0, 'short event write')
        remaining = remaining[count:]


def append_event(policy: dict, context: dict, kind: str, data: dict) -> dict:
    context = _resolved(context, True)
    _require(policy == context['_policy'], 'effective policy binding')
    if kind in ('sdk', 'host-start'):
        _require(type(data) is dict, 'event data')
        cwd = _callback(context, data.get('importpath'), probe=(kind == 'host-start' or data.get('classification') == 'version-probe'), host=kind == 'host-start')
        _require(data.get('cwd') == cwd, 'actual event cwd')
        if kind == 'host-start':
            host = _host_admission(policy, data.get('argv'))
            _require(os.environ.get(host['role']) == host['tool']['path'] and os.environ.get('LC_ALL') == 'C', 'host role environment')
    recorder = _process(os.getpid())[0]
    with _journal(policy['record_directory']) as (fd, parent, info):
        rows = _read_rows(fd, info, parent)
        row = dict(format='om-go-tool-event-v2', seq=len(rows)+1, kind=kind, job_id=context['job_id'],
                   driver_id=context['driver_id'], parent_go=context['_start']['go_identity'],
                   recorder=recorder, policy_sha256=context['policy']['sha256'], data=data)
        _replay(rows+[row], context)
        encoded = v1._encoded(row)+b'\n'
        os.lseek(fd, 0, os.SEEK_END)
        _write_all(fd, encoded)
        os.fsync(fd)
        _require(v1._journal_info(fd, parent).st_size == info.st_size+len(encoded), 'event persistence')
        return row


def read_job_events(record_directory: Path, contexts: dict[str, dict]) -> list[dict]:
    _require(type(contexts) is dict and contexts, 'complete context map')
    resolved = {}
    for driver, context in contexts.items():
        current = _resolved(context, False)
        _require(driver == current['driver_id'], 'context map driver')
        resolved[driver] = current
    first = next(iter(resolved.values()))
    expected_ids = {first['_config']['root_driver']['driver_id']} | {slot['driver_id'] for slot in first['_config']['fixture_slots']}
    _require(set(resolved) == expected_ids, 'complete released context map')
    for current in resolved.values():
        _require(current['config'] == first['config'] and current['job_id'] == first['job_id']
                 and current['_policy']['record_directory'] == str(record_directory), 'job context map binding')
    with _journal(record_directory) as (fd, parent, info):
        rows = _read_rows(fd, info, parent)
        _replay(rows, first, resolved, final=True)
    return rows


def _make_blob(raw, **extra):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                base64=base64.b64encode(raw).decode('ascii'), **extra)


def _spawn_host(argv):
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)


@contextlib.contextmanager
def _forward_endpoint(name):
    # dup() shares O_NONBLOCK with other inherited users. Linux /proc reopening
    # a pipe creates an independent open description; never alter shared flags.
    original = 1 if name == 'stdout' else 2
    before = os.fstat(original)
    flags = fcntl.fcntl(original, fcntl.F_GETFL)
    if not stat.S_ISFIFO(before.st_mode) or flags & os.O_ACCMODE == os.O_RDONLY:
        raise OSError('host forwarding requires a writable pipe')
    fd = os.open('/proc/self/fd/'+str(original), os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        after = os.fstat(fd)
        current = os.fstat(original)
        if not (stat.S_ISFIFO(after.st_mode) and
                (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino) ==
                (current.st_dev, current.st_ino) and
                fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_NONBLOCK and
                fcntl.fcntl(original, fcntl.F_GETFL) == flags):
            raise OSError('host forwarding endpoint changed')
        yield fd
    finally:
        os.close(fd)


def _forward(name, raw, *, deadline=None):
    if deadline is None:
        deadline = time.monotonic_ns()+HOST_SECONDS*1000000000
    with _forward_endpoint(name) as fd, selectors.DefaultSelector() as ready:
        ready.register(fd, selectors.EVENT_WRITE)
        remaining = memoryview(raw)
        while remaining:
            now = time.monotonic_ns()
            if now >= deadline:
                raise TimeoutError('host forwarding deadline')
            try:
                count = os.write(fd, remaining)
            except BlockingIOError:
                ready.select(min(.05, (deadline-now)/1000000000))
                continue
            if count <= 0:
                raise OSError('short host forwarding write')
            remaining = remaining[count:]


def _refusal_diagnostic(message):
    # A failed probe may leave its consumer permanently blocked. Diagnostics
    # are best effort, one nonblocking attempt, independent of v1 reporting.
    raw = ('tool recorder refused: '+str(message)+'\n').encode('utf-8', errors='replace')[:4096]
    try:
        with _forward_endpoint('stderr') as fd:
            os.write(fd, raw)
    except OSError:
        pass


def _kill_host(child):
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _capture_host(child, started):
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    eof = dict(stdout=False, stderr=False)
    lost = dict(stdout=0, stderr=0)
    overflow = timed_out = io_error = False
    deadline = started + HOST_SECONDS*1000000000
    cleanup_deadline = None
    selector = selectors.DefaultSelector()
    try:
        for name in buffers:
            pipe = getattr(child, name)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while selector.get_map() or child.poll() is None:
            now = time.monotonic_ns()
            if now >= deadline and cleanup_deadline is None:
                timed_out = True
                _kill_host(child)
                cleanup_deadline = now + 20*1000000000
            if cleanup_deadline is not None and now >= cleanup_deadline:
                io_error = True
                break
            wait_until = cleanup_deadline if cleanup_deadline is not None else deadline
            ready = selector.select(min(0.05, max(0, (wait_until-now)/1000000000)))
            for key, mask in ready:
                name = key.data
                try:
                    raw = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                except OSError:
                    io_error = True
                    lost[name] = None
                    selector.unregister(key.fileobj)
                    _kill_host(child)
                    if cleanup_deadline is None: cleanup_deadline = time.monotonic_ns()+20*1000000000
                    continue
                if not raw:
                    eof[name] = True
                    selector.unregister(key.fileobj)
                    continue
                available = HOST_BYTES-sum(len(value) for value in buffers.values())
                kept = raw[:available]
                buffers[name].extend(kept)
                discarded = len(raw)-len(kept)
                if lost[name] is not None: lost[name] += discarded
                if discarded:
                    overflow = True
                    _kill_host(child)
                    if cleanup_deadline is None: cleanup_deadline = time.monotonic_ns()+20*1000000000
                if kept:
                    try:
                        _forward(name, kept, deadline=deadline)
                    except OSError as error:
                        if isinstance(error, TimeoutError): timed_out = True
                        io_error = True
                        _kill_host(child)
                        if cleanup_deadline is None: cleanup_deadline = time.monotonic_ns()+20*1000000000
        if child.poll() is None:
            _kill_host(child)
            remaining = max(0, ((cleanup_deadline or (time.monotonic_ns()+20*1000000000))-time.monotonic_ns())/1000000000)
            try:
                child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                io_error = True
        else:
            child.wait()
    except (OSError, ValueError):
        io_error = True
        _kill_host(child)
        try: child.wait(timeout=20)
        except subprocess.TimeoutExpired: pass
    finally:
        selector.close()
        for name in buffers:
            getattr(child, name).close()
            if not eof[name]: lost[name] = None
    # Per-stream padding can add four bytes compared with one combined blob.
    # Retain only the declared budget, explicitly accounting any discarded bytes.
    while sum(4*((len(value)+2)//3) for value in buffers.values()) > 87384:
        name = 'stderr' if buffers['stderr'] else 'stdout'
        buffers[name].pop()
        if lost[name] is not None: lost[name] += 1
        overflow = True
    streams = {name: _make_blob(bytes(value), eof=eof[name], lost_bytes=lost[name])
               for name, value in buffers.items()}
    return child.returncode, streams, dict(timeout=timed_out, overflow=overflow, io_error=io_error)


def run_host_probe(policy: dict, context: dict, argv: list[str], importpath: str) -> int:
    context = _resolved(context, True)
    _require(policy == context['_policy'], 'effective policy binding')
    host = _host_admission(policy, argv)
    cwd = _callback(context, importpath, probe=True, host=True)
    _require(os.environ.get(host['role']) == host['tool']['path'] and os.environ.get('LC_ALL') == 'C', 'host role environment')
    _verify_host_pin(host['tool'])
    start = append_event(policy, context, 'host-start', dict(**host, argv=argv, importpath=importpath, cwd=cwd))
    started = time.monotonic_ns()
    child = None
    identity = terminal = release = None
    streams = {name: _make_blob(b'', eof=False, lost_bytes=None) for name in ('stdout', 'stderr')}
    outcome = 'io_error'
    spawn_attempted = False
    status = None
    try:
        # Repeat root-owned pin verification after durable reservation, before spawn.
        _verify_host_pin(host['tool'])
        _parent_sdk(os.getpid(), context['_start'], context['_config'])
        spawn_attempted = True
        child = _spawn_host(argv)
        identity, parent = _process(child.pid)
        _require(parent == os.getpid(), 'owned host child')
        status, streams, flags = _capture_host(child, started)
        if status is not None:
            terminal = dict(exit_code=status if status >= 0 else None,
                            signal=-status if status < 0 else None)
        if flags['timeout']: outcome = 'timeout'
        elif flags['overflow']: outcome = 'overflow'
        elif flags['io_error'] or status is None: outcome = 'io_error'
        elif status < 0: outcome = 'signal'
        elif status != 0: outcome = 'exit_nonzero'
        else:
            try:
                raw_id = _gcc_id(base64.b64decode(streams['stderr']['base64']))
                release = _make_blob(raw_id)
                _require(streams['stdout']['bytes'] == 0, 'nonempty host stdout')
                _require(all(streams[name]['eof'] and streams[name]['lost_bytes'] == 0
                             for name in streams), 'host capture loss')
                outcome = 'ok'
            except ValueError:
                outcome = 'parse_error'
    except (OSError, ValueError):
        if child is None:
            outcome = 'spawn_error' if spawn_attempted else 'io_error'
        if child is not None:
            _kill_host(child)
            try: status = child.wait(timeout=20)
            except subprocess.TimeoutExpired: status = None
            if status is not None:
                terminal = dict(exit_code=status if status >= 0 else None,
                                signal=-status if status < 0 else None)
            outcome = 'io_error'
    finally:
        if child is not None:
            for name in ('stdout', 'stderr'):
                getattr(child, name).close()
    elapsed = time.monotonic_ns()-started
    completion = dict(start_seq=start['seq'], child=identity, terminal=terminal, elapsed_ns=elapsed,
                      stdout=streams['stdout'], stderr=streams['stderr'], release_id=release, outcome=outcome)
    append_event(policy, context, 'host-complete', completion)
    if outcome == 'ok':
        return 0
    if status is not None and status != 0:
        return status
    raise ValueError('host probe '+outcome)


def dispatch_v2(template_raw, template_path, template_sha, argv):
    template = load_job_policy(template_raw)
    context_path = os.environ.get('OM_GO_SUPERVISION_CONTEXT', '')
    context_sha = os.environ.get('OM_GO_SUPERVISION_CONTEXT_SHA256', '')
    context = load_driver_context(Path(context_path), context_sha)
    _require(context['_config']['tool_policy']['path'] == template_path and
             context['_config']['tool_policy']['sha256'] == template_sha, 'root template token')
    _require(template == load_job_policy(_pin_bytes(context['_config']['tool_policy'], POLICY_LIMIT, control=True)), 'root template policy')
    policy = context['_policy']
    _require(type(argv) is list and argv, 'selected argv')
    selected = next((tool for tool in policy['tools'] if tool['path'] == argv[0]), None)
    importpath = os.environ.get('TOOLEXEC_IMPORTPATH', '')
    if selected is None:
        return run_host_probe(policy, context, argv, importpath)
    cwd = _callback(context, importpath, probe=argv[1:] == ['-V=full'])
    classification, c = v1._classification(argv[0], argv[1:], importpath)
    _pin_bytes(selected)
    before = os.stat(selected['path'], follow_symlinks=False)
    identity = _process(os.getpid())[0]
    data = dict(format='om-go-tool-record-v1', policy_sha256=context['policy']['sha256'],
                pid=identity['pid'], start_ticks=identity['start_ticks'], argv=argv,
                importpath=importpath, tool=selected, classification=classification, compiler_c=c, cwd=cwd)
    append_event(policy, context, 'sdk', data)
    _pin_bytes(selected)
    _require(_identity(before) == _identity(os.stat(selected['path'], follow_symlinks=False)), 'SDK changed before exec')
    _parent_sdk(os.getpid(), context['_start'], context['_config'])
    os.execv(selected['path'], argv)
    raise ValueError('SDK exec returned')
