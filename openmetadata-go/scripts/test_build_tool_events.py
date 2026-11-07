# SPDX-License-Identifier: Apache-2.0
"""Owned Python toys; root host pin/image metadata and launcher are injected.

No selected SDK/host compiler executes. Parent PID/start binding and spawned toy
I/O, terminal status, timeout, durable journal and locks are real observations.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import unittest
from unittest.mock import patch
import build_tool_events as events
import record_partitioned_tool as v1
import test_record_partitioned_tool as fixtures


class EventTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RecorderTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base = self.fixture.root
        self.source = self.fixture.source
        (self.fixture.sdk/'src').mkdir()
        self.roots = dict(records=str(self.fixture.records))
        for key in ('fixtures', 'drivers', 'registrations'):
            path = self.base/key
            path.mkdir(mode=0o700)
            self.roots[key] = str(path)
        self.serial = 0
        self.host_script = self.base/'toy-host.py'
        self.host_body("import sys\nsys.stderr.buffer.write(b'gcc version 14.2.0 (Toy)\\n')\n")
        self.controls()

    def pin(self, path):
        raw = path.read_bytes()
        return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), mode=path.stat().st_mode & 0o777)

    def write(self, label, value, canonical=True):
        self.serial += 1
        path = Path(self.roots['registrations'])/(label+str(self.serial)+'.json')
        raw = v1._encoded(value)+b'\n' if canonical else json.dumps(value).encode()
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
        return self.pin(path)

    def host_body(self, body):
        prefix = '#!'+sys.executable+' -B\nfrom pathlib import Path\nimport os,json\n'
        prefix += "rows=Path(os.environ['TOY_JOURNAL']).read_text().splitlines()\nassert any(json.loads(row)['kind']=='host-start' and json.loads(row)['recorder']['pid']==os.getppid() for row in rows)\nPath(os.environ['TOY_MARKER']).write_text('started')\n"
        self.host_script.write_text(prefix+body)
        self.host_script.chmod(0o755)
        self.host_pin = self.pin(self.host_script) | dict(path='/usr/bin/x86_64-linux-gnu-gcc-14', mode=493, uid=0, gid=0)

    def manifest(self, root):
        path = root/'a.go'
        if not path.exists():
            path.write_bytes(b'x'); path.chmod(0o600)
        return self.write('manifest', dict(format='om-go-build-inputs-v1', root=str(root), excluded_roots=[],
            files=[dict(path='a.go', bytes=1, sha256=hashlib.sha256(b'x').hexdigest(), mode=0o600)]))

    def controls(self, fixture=False, hosts=True, parent_pid=None, effective_override=None,
                 start_override=None, manifest_root=None, driver_environment=None):
        policy = dict(self.fixture.policy, format='om-go-tool-record-policy-v2',
            host_id_probes=[dict(role='CC', language='c', tool=self.host_pin)] if hosts else [])
        template = self.write('template', policy, canonical=False)
        self.env = dict(GOFLAGS=' '.join(policy['required_go_flags']), GODEBUG='gocachehash=1',
            CC=self.host_pin['path'], CXX='/usr/bin/x86_64-linux-gnu-g++-14', PKG_CONFIG='/usr/bin/pkg-config',
            GOROOT=str(self.fixture.sdk), OM_BUILD_JOB_ID='job', TOY_MARKER=str(self.fixture.marker),
            TOY_JOURNAL=str(self.fixture.journal))
        for name in ('GOMODCACHE', 'GOTMPDIR', 'TMPDIR'):
            path = self.base/name
            path.mkdir(exist_ok=True)
            self.env[name] = str(path)
        for name, value in (driver_environment or {}).items():
            if value is None: self.env.pop(name, None)
            else: self.env[name] = value
        root_manifest = self.manifest(self.source)
        sdk = self.pin(Path(sys.executable).resolve())
        slots = [dict(driver_id='fix', test_name='TestToy', package='toy', support_paths=['go.mod'])] if fixture else []
        plan = self.write('coverage', {})  # P0B3, not this API, authenticates plan contents.
        config = dict(format='om-build-job-v1', job_id='job', module_root=str(self.source),
            input_manifest=root_manifest, sdk_go=sdk, tool_policy=template,
            toolexec_argv=[sys.executable, '-B', str(fixtures.RECORDER), '--policy', template['path'], '--policy-sha256', template['sha256']],
            environment=self.env, roots=self.roots, root_driver=dict(driver_id='root', argv=['version']),
            fixture_slots=slots, coverage=[dict(driver_id=driver, plan=plan) for driver in (['fix','root'] if fixture else ['root'])], caps=events.CAPS)
        config_pin = self.write('config', config)
        identity = events._process(os.getppid() if parent_pid is None else parent_pid)[0]
        self.config, self.template, self.template_pin = config, policy, template
        self.contexts, self.starts = {}, {}
        def context_for(driver, manifest, effective_pin, parent):
            start = dict(format='om-go-driver-start-v1', job_id='job', driver_id=driver, parent_driver_id=parent,
                         go_identity=identity, sdk_go=sdk, manifest=manifest)
            if start_override and driver == ('fix' if fixture else 'root'): start.update(start_override)
            start_pin = self.write('start', start)
            wire = dict(format='om-go-context-v1', job_id='job', driver_id=driver,
                        config=config_pin, start=start_pin, policy=effective_pin)
            context_pin = self.write('context', wire)
            self.starts[driver] = start
            self.contexts[driver] = wire | dict(_path=context_pin['path'], _sha256=context_pin['sha256'])
        context_for('root', root_manifest, template, None)
        self.policy = policy
        if fixture:
            root = Path(self.roots['fixtures'])/'one'
            root.mkdir(exist_ok=True)
            manifest = self.manifest(root if manifest_root is None else manifest_root)
            effective = dict(policy, working_directory=str(root))
            if effective_override: effective.update(effective_override)
            context_for('fix', manifest, self.write('effective', effective), 'root')
            self.policy = effective
        self.context = self.contexts['fix' if fixture else 'root']
        return self.context

    def verify_toy_host(self, pin):
        # Explicit host UID0/path metadata injection. Actual bytes/mode/owner of
        # the owned toy are still checked, and the selected host is never read/run.
        self.assertEqual(pin, self.host_pin)
        translated = {key:pin[key] for key in events.PIN_KEYS}
        translated['path'] = str(self.host_script)
        return events._pin_bytes(translated)

    @contextlib.contextmanager
    def active(self, importpath='', cwd=None, overrides=None):
        env = dict(self.env, PWD=str(cwd or Path(self.policy['working_directory'])), LC_ALL='C',
                   TOOLEXEC_IMPORTPATH=importpath, OM_GO_SUPERVISION_CONTEXT=self.context['_path'],
                   OM_GO_SUPERVISION_CONTEXT_SHA256=self.context['_sha256'])
        for name, value in (overrides or {}).items():
            if value is None: env.pop(name, None)
            else: env[name] = value
        if importpath and 'LC_ALL' not in self.env: env.pop('LC_ALL', None)
        previous = Path.cwd()
        try:
            os.chdir(cwd or self.policy['working_directory'])
            with patch.dict(os.environ, env, clear=True), patch.object(events, '_verify_host_pin', self.verify_toy_host), \
                 patch.object(events, '_process_image', return_value=self.config['sdk_go']['path']), \
                 patch.object(events, '_spawn_host', side_effect=lambda argv: subprocess.Popen(
                     [str(self.host_script), *argv[1:]], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, start_new_session=True)):
                yield
        finally:
            os.chdir(previous)

    def argv(self): return [self.host_pin['path'], '-###', '-x', 'c', '-c', '-']
    def rows(self): return [json.loads(line) for line in self.fixture.journal.read_bytes().splitlines()]
    def host_start(self): return dict(role='CC', language='c', tool=self.host_pin, argv=self.argv(), importpath='', cwd=os.getcwd())

    def sdk_data(self, context=None):
        context = context or self.context
        identity = events._process(os.getpid())[0]
        return dict(format='om-go-tool-record-v1', policy_sha256=context['policy']['sha256'],
            pid=identity['pid'], start_ticks=identity['start_ticks'], argv=[str(self.fixture.tool), '-c=1'],
            importpath=fixtures.MODULE, tool=self.policy['tools'][0], classification='module-compile',
            compiler_c='1', cwd=self.policy['working_directory'])

    def fill_sdk(self, count):
        data = self.sdk_data()
        rows = [dict(format='om-go-tool-event-v2', seq=i+1, kind='sdk', job_id='job', driver_id='root',
            parent_go=self.starts['root']['go_identity'], recorder=events._process(os.getpid())[0],
            policy_sha256=self.contexts['root']['policy']['sha256'], data=data) for i in range(count)]
        self.fixture.journal.write_bytes(b''.join(v1._encoded(row)+b'\n' for row in rows))

    def test_v1_is_unchanged(self):
        result = self.fixture.command(['-c=1'])
        self.assertEqual(result.returncode, 37, result.stderr)
        row, = self.rows()
        self.assertEqual(set(row), v1.ROW_KEYS)
        self.assertEqual(row['format'], 'om-go-tool-record-v1')

    def test_host_requires_exact_role_argv_and_root_pin(self):
        bad = dict(self.template, host_id_probes=[dict(role='CC', language='c', tool=dict(self.host_pin, uid=True))])
        with self.assertRaisesRegex(ValueError, 'host'):
            events.load_job_policy(json.dumps(bad).encode())
        with self.active():
            for argv in [self.argv()+['source.c'], self.argv()[:-1], [self.host_pin['path'], '-v']]:
                with self.subTest(argv=argv), self.assertRaisesRegex(ValueError, 'exact host probe argv'):
                    events.run_host_probe(self.policy, self.context, argv, '')
            with self.assertRaisesRegex(ValueError, 'protected environment override: CC'):
                with patch.dict(os.environ, CC=self.host_pin['path']+' -flag'):
                    events.run_host_probe(self.policy, self.context, self.argv(), '')
        self.assertFalse(self.fixture.marker.exists())
        self.assertEqual(self.rows(), [])

    def test_context_rejects_wrong_parent_or_derived_policy(self):
        self.controls(start_override=dict(go_identity=events._process(os.getpid())[0]))
        with self.active(), self.assertRaisesRegex(ValueError, 'registered parent identity'):
            events.load_driver_context(Path(self.context['_path']), self.context['_sha256'])
        self.controls(fixture=True, effective_override=dict(required_go_flags=list(reversed(self.template['required_go_flags']))))
        with self.active(), self.assertRaisesRegex(ValueError, 'derived policy'):
            events.load_driver_context(Path(self.context['_path']), self.context['_sha256'])
        self.controls(fixture=True, manifest_root=self.source)
        with self.active(), self.assertRaisesRegex(ValueError, 'fixture manifest root'):
            events.load_driver_context(Path(self.context['_path']), self.context['_sha256'])
        self.controls(fixture=True, start_override=dict(parent_driver_id='wrong'))
        with self.active(), self.assertRaisesRegex(ValueError, 'fixture slot/parent'):
            events.load_driver_context(Path(self.context['_path']), self.context['_sha256'])

    def test_start_is_durable_before_child_and_completion_is_reserved(self):
        with self.active(), patch.object(events, '_forward'):
            self.assertEqual(events.run_host_probe(self.policy, self.context, self.argv(), ''), 0)
            self.assertEqual([row['kind'] for row in self.rows()], ['host-start', 'host-complete'])
            self.assertEqual(len(events.read_job_events(self.fixture.records, self.contexts)), 2)
        self.fixture.journal.write_bytes(b'')
        self.fixture.marker.unlink()
        self.fill_sdk(511)
        with self.active(), self.assertRaisesRegex(ValueError, 'event/reservation count'):
            events.run_host_probe(self.policy, self.context, self.argv(), '')
        self.assertFalse(self.fixture.marker.exists())
        self.assertEqual(len(self.rows()), 511)

    def test_host_forwards_original_stderr_and_status(self):
        self.host_body("import sys\nsys.stderr.buffer.write(b'raw error\\n')\nraise SystemExit(37)\n")
        self.controls()
        self.controls(parent_pid=os.getpid())
        result = self.callback(self.argv()[1:], host=True, overrides=dict(LC_ALL='C', TOOLEXEC_IMPORTPATH=''))
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(result.stderr, b'raw error\n')
        row = self.rows()[-1]['data']
        self.assertEqual(row['terminal'], dict(exit_code=37, signal=None))
        self.assertEqual(row['outcome'], 'exit_nonzero')
        self.assertFalse(Path('/proc/'+str(row['child']['pid'])).exists())

    def test_nonzero_unparseable_and_nonempty_stdout_fail(self):
        for body in ["import sys\nsys.stderr.write('not a version\\n')\n",
                     "import sys\nsys.stdout.write('unexpected')\nsys.stderr.write('gcc version 14.2.0\\n')\n",
                     "import sys\nsys.stderr.write('gcc version 14.2.0 (experimental)\\n')\n"]:
            with self.subTest(body=body):
                self.fixture.journal.write_bytes(b'')
                self.host_body(body); self.controls()
                with self.active(), patch.object(events, '_forward'), self.assertRaisesRegex(ValueError, 'parse_error'):
                    events.run_host_probe(self.policy, self.context, self.argv(), '')
                result = self.rows()[-1]['data']
                self.assertEqual(result['terminal'], dict(exit_code=0, signal=None))
                self.assertEqual(result['outcome'], 'parse_error')

    def test_timeout_overflow_shortwrite_and_missing_completion_fail(self):
        with self.active():
            events.append_event(self.policy, self.context, 'host-start', self.host_start())
            with self.assertRaisesRegex(ValueError, 'missing host completion'):
                events.read_job_events(self.fixture.records, self.contexts)
        self.fixture.journal.write_bytes(b'')
        self.host_body("import sys\nsys.stderr.buffer.write(b'x'*70000)\nsys.stderr.flush()\n")
        self.controls()
        with self.active(), patch.object(events, '_forward'):
            try:
                status = events.run_host_probe(self.policy, self.context, self.argv(), '')
            except ValueError as error:
                self.assertIn('overflow', str(error))
                self.assertEqual(self.rows()[-1]['data']['terminal'], dict(exit_code=0, signal=None))
            else:
                terminal = self.rows()[-1]['data']['terminal']
                self.assertNotEqual(status, 0)
                self.assertEqual(status, -terminal['signal'] if terminal['signal'] is not None else terminal['exit_code'])
        self.assertEqual(self.rows()[-1]['data']['outcome'], 'overflow')
        self.fixture.journal.write_bytes(b'')
        self.host_body("import time\ntime.sleep(30)\n"); self.controls()
        with self.active(), patch.object(events, '_forward'):
            self.assertEqual(events.run_host_probe(self.policy, self.context, self.argv(), ''), -signal.SIGKILL)
        terminal = self.rows()[-1]['data']
        self.assertEqual(terminal['outcome'], 'timeout')
        self.assertFalse(Path('/proc/'+str(terminal['child']['pid'])).exists())
        self.assertGreaterEqual(terminal['elapsed_ns'], 10*1000000000)
        self.fixture.journal.write_bytes(b'')
        original = os.write
        with self.active(), patch.object(events.os, 'write', side_effect=lambda fd, raw: original(fd, raw[:7])):
            row = events.append_event(self.policy, self.context, 'host-start', self.host_start())
        self.assertEqual(row, self.rows()[0])

    def callback(self, args, cwd=None, overrides=None, host=False):
        env = dict(self.env, PWD=str(cwd or Path(self.policy['working_directory'])), TOOLEXEC_IMPORTPATH=fixtures.MODULE,
                   OM_GO_SUPERVISION_CONTEXT=self.context['_path'], OM_GO_SUPERVISION_CONTEXT_SHA256=self.context['_sha256'])
        for name, value in (overrides or {}).items():
            if value is None: env.pop(name, None)
            else: env[name] = value
        cli = ['--policy', self.template_pin['path'], '--policy-sha256', self.template_pin['sha256'],
               self.host_pin['path'] if host else str(self.fixture.tool), *args]
        command = [sys.executable, '-B', str(fixtures.RECORDER), *cli]
        if host:
            prefix = 'import sys;sys.path.insert(0,'+repr(str(fixtures.RECORDER.parent))+');import build_tool_events as e;import record_partitioned_tool as r\n'
            prefix += 'e._verify_host_pin=lambda pin:e._pin_bytes('+repr(self.pin(self.host_script))+')\n'
            prefix += 'e._spawn_host=lambda argv:e.subprocess.Popen(['+repr(str(self.host_script))+',*argv[1:]],stdin=e.subprocess.DEVNULL,stdout=e.subprocess.PIPE,stderr=e.subprocess.PIPE,start_new_session=True)\n'
            prefix += 'raise SystemExit(r.main(sys.argv[1:]))'
            command = [sys.executable, '-B', '-c', prefix, *cli]
        return subprocess.run(command, cwd=cwd or self.policy['working_directory'], env=env, capture_output=True, timeout=15)

    def test_template_token_and_derived_policy_dispatch(self):
        self.controls(fixture=True, hosts=False, parent_pid=os.getpid())
        result = self.callback(['-c=1'])
        self.assertEqual(result.returncode, 37, result.stderr)
        row, = self.rows()
        self.assertEqual(row['driver_id'], 'fix')
        self.assertEqual(row['policy_sha256'], self.context['policy']['sha256'])
        self.assertNotEqual(row['policy_sha256'], self.template_pin['sha256'])
        self.assertEqual(self.fixture.marker.read_text(), self.policy['working_directory'])
        self.fixture.marker.unlink(); self.fixture.journal.write_bytes(b'')
        self.template_pin = self.context['policy']
        result = self.callback(['-c=1'])
        self.assertNotEqual(result.returncode, 37)
        self.assertIn(b'root template token', result.stderr)
        self.assertFalse(self.fixture.marker.exists())

    def test_sdk_callback_pwd_test_description_and_protected_override(self):
        self.controls(hosts=False, parent_pid=os.getpid())
        nested = self.source/'pkg'; nested.mkdir()
        description = fixtures.MODULE+'/pkg ['+fixtures.MODULE+'/pkg.test]'
        result = self.callback(['-c=1'], cwd=nested, overrides=dict(TOOLEXEC_IMPORTPATH=description, CGO_CFLAGS='-O2'))
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(self.rows()[0]['data']['cwd'], str(nested))
        self.assertEqual(self.rows()[0]['data']['importpath'], description)
        self.fixture.marker.unlink()
        for override in [dict(GOFLAGS='-p=8'), dict(PWD=str(self.source)), dict(OM_UNKNOWN='bad'), dict(LC_ALL='unreleased')]:
            with self.subTest(override=override):
                result = self.callback(['-c=1'], cwd=nested, overrides=override)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(self.fixture.marker.exists())
        self.assertEqual(len(self.rows()), 1)
        result = self.callback(['-V=full'], overrides=dict(TOOLEXEC_IMPORTPATH=''))
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(self.rows()[-1]['data']['classification'], 'version-probe')
        self.assertEqual(self.rows()[-1]['data']['importpath'], '')

    def test_signal_forwarding_and_parent_exit_replay_with_locator_map(self):
        self.host_body('import os,signal\nos.kill(os.getpid(),signal.SIGTERM)\n')
        self.controls(parent_pid=os.getpid())
        result = self.callback(self.argv()[1:], host=True, overrides=dict(LC_ALL='C', TOOLEXEC_IMPORTPATH=''))
        self.assertEqual(result.returncode, -signal.SIGTERM, result.stderr)
        self.assertEqual(self.rows()[-1]['data']['terminal'], dict(exit_code=None, signal=signal.SIGTERM))
        self.fixture.journal.write_bytes(b'')
        code = "import json,subprocess,sys;request=json.load(sys.stdin);r=subprocess.run(request['argv'],cwd=request['cwd'],env=request['env'],capture_output=True);sys.stdout.buffer.write(r.stdout);sys.stderr.buffer.write(r.stderr);raise SystemExit(r.returncode)"
        driver = subprocess.Popen([sys.executable, '-B', '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.controls(hosts=False, parent_pid=driver.pid)
            env = dict(self.env, PWD=self.policy['working_directory'], TOOLEXEC_IMPORTPATH=fixtures.MODULE,
                       OM_GO_SUPERVISION_CONTEXT=self.context['_path'], OM_GO_SUPERVISION_CONTEXT_SHA256=self.context['_sha256'])
            cli = [sys.executable, '-B', str(fixtures.RECORDER), '--policy', self.template_pin['path'], '--policy-sha256',
                   self.template_pin['sha256'], str(self.fixture.tool), '-c=1']
            stdout, stderr = driver.communicate(json.dumps(dict(argv=cli, cwd=self.policy['working_directory'], env=env)).encode(), timeout=15)
            self.assertEqual(driver.returncode, 37, stderr)
        finally:
            if driver.poll() is None: driver.kill()
            driver.communicate(timeout=5)
        with self.active(importpath=fixtures.MODULE):
            self.assertEqual(len(events.read_job_events(self.fixture.records, self.contexts)), 1)
            with self.assertRaisesRegex(ValueError, 'registered parent identity'):
                events.load_driver_context(Path(self.context['_path']), self.context['_sha256'])
            with self.assertRaisesRegex(ValueError, 'registered parent identity'):
                events.append_event(self.policy, self.context, 'sdk', self.sdk_data())
            resolved = events._resolved(self.context, False)
            resolved.update(_config={'untrusted':True}, _policy={'untrusted':True}, _start={'untrusted':True})
            self.assertEqual(len(events.read_job_events(self.fixture.records, {'root':resolved})), 1)

    def test_foreign_rows_are_bounded_and_final_contexts_authenticate_pins(self):
        self.controls(fixture=True)
        fake_sha = '0'*64
        identity = events._process(os.getpid())[0]
        data = self.sdk_data(self.contexts['root'])
        data.update(policy_sha256=fake_sha, cwd=str(self.source))
        foreign = dict(format='om-go-tool-event-v2', seq=1, kind='sdk', job_id='job', driver_id='root',
            parent_go=self.starts['root']['go_identity'], recorder=identity, policy_sha256=fake_sha, data=data)
        self.fixture.journal.write_bytes(v1._encoded(foreign)+b'\n')
        with self.active(importpath=fixtures.MODULE):
            events.append_event(self.policy, self.context, 'sdk', self.sdk_data())
            with self.assertRaisesRegex(ValueError, 'event context binding'):
                events.read_job_events(self.fixture.records, self.contexts)
            foreign['data']['extra'] = True
            self.fixture.journal.write_bytes(v1._encoded(foreign)+b'\n')
            with self.assertRaisesRegex(ValueError, 'record keys'):
                events.append_event(self.policy, self.context, 'sdk', self.sdk_data())

    def test_concurrent_start_completion_share_fixed_job_budgets(self):
        self.controls(parent_pid=os.getpid())
        env = dict(self.env, PWD=self.policy['working_directory'], TOOLEXEC_IMPORTPATH='', LC_ALL='C',
            OM_GO_SUPERVISION_CONTEXT=self.context['_path'], OM_GO_SUPERVISION_CONTEXT_SHA256=self.context['_sha256'])
        prefix = 'import sys;sys.path.insert(0,'+repr(str(fixtures.RECORDER.parent))+');import build_tool_events as e\n'
        prefix += 'e._verify_host_pin=lambda pin:e._pin_bytes('+repr(self.pin(self.host_script))+')\n'
        prefix += 'e._spawn_host=lambda argv:e.subprocess.Popen(['+repr(str(self.host_script))+',*argv[1:]],stdin=e.subprocess.DEVNULL,stdout=e.subprocess.PIPE,stderr=e.subprocess.PIPE,start_new_session=True)\n'
        prefix += 'c=e.load_driver_context(e.Path('+repr(self.context['_path'])+'),'+repr(self.context['_sha256'])+');raise SystemExit(e.run_host_probe(c["_policy"],c,'+repr(self.argv())+',""))'
        children = []
        try:
            for _ in range(4):
                children.append(subprocess.Popen([sys.executable, '-B', '-c', prefix], cwd=self.policy['working_directory'], env=env,
                                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            for child in children:
                stdout, stderr = child.communicate(timeout=15)
                self.assertEqual(child.returncode, 0, stderr)
        finally:
            for child in children:
                if child.poll() is None: child.kill()
                child.communicate(timeout=5)
        with self.active():
            rows = events.read_job_events(self.fixture.records, self.contexts)
        self.assertEqual(len(rows), 8)
        self.assertEqual([row['seq'] for row in rows], list(range(1,9)))
        self.assertEqual({row['recorder']['pid'] for row in rows}, {child.pid for child in children})
        for row in rows:
            if row['kind']=='host-complete':
                self.assertFalse(Path('/proc/'+str(row['data']['child']['pid'])).exists())

    def test_failed_start_or_completion_persistence_never_claims_success(self):
        with self.active(), patch.object(events.os, 'fsync', side_effect=OSError('injected start persistence')):
            with self.assertRaises(OSError): events.run_host_probe(self.policy, self.context, self.argv(), '')
        self.assertFalse(self.fixture.marker.exists())
        self.fixture.journal.write_bytes(b'')
        original = os.fsync
        count = 0
        def fail_second(fd):
            nonlocal count
            count += 1
            if count==2: raise OSError('injected completion persistence')
            original(fd)
        with self.active(), patch.object(events, '_forward'), patch.object(events.os, 'fsync', side_effect=fail_second):
            with self.assertRaises(OSError): events.run_host_probe(self.policy, self.context, self.argv(), '')
        self.assertTrue(self.fixture.marker.exists())
        self.assertFalse(Path('/proc/'+str(self.rows()[-1]['data']['child']['pid'])).exists())

    def test_host_ownership_stat_fixture_is_explicit(self):
        from types import SimpleNamespace
        actual = self.host_script.stat()
        events._check_pin_stat(actual, self.pin(self.host_script))
        if actual.st_uid != 0 or actual.st_gid != 0:
            with self.assertRaisesRegex(ValueError, 'host owner'):
                events._check_pin_stat(actual, self.host_pin, host=True)
        else:
            events._check_pin_stat(actual, self.host_pin, host=True)
        fixture = dict(st_mode=actual.st_mode, st_nlink=1, st_uid=0, st_gid=0, st_size=actual.st_size)
        events._check_pin_stat(SimpleNamespace(**fixture), self.host_pin, host=True)
        for key, value in [('st_uid',1),('st_gid',1),('st_nlink',2),('st_mode',0o100700)]:
            with self.subTest(injected_stat=key), self.assertRaises(ValueError):
                events._check_pin_stat(SimpleNamespace(**dict(fixture, **{key:value})), self.host_pin, host=True)

    def test_strict_v2_duplicate_controls_and_unreleased_slot(self):
        with self.active():
            raw = json.dumps(self.template).encode()
            self.assertEqual(events.load_job_policy(raw), self.template)
            for key, value in [(b'"format":',b'"format":"om-go-tool-record-policy-v2","format":'),
                               (b'"uid":',b'"uid":0,"uid":')]:
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                    events.load_job_policy(raw.replace(key,value,1))
        self.controls(fixture=True)
        wire = {key:self.context[key] for key in events.CONTEXT_KEYS}
        start = dict(self.starts['fix'], driver_id='unreleased')
        wire.update(driver_id='unreleased',start=self.write('unknown-start',start))
        pin = self.write('unknown-context',wire)
        with self.active(), self.assertRaisesRegex(ValueError, 'fixture slot/parent'):
            events.load_driver_context(Path(pin['path']),pin['sha256'])

    def test_host_pin_change_after_durable_start_prevents_spawn(self):
        original = os.fsync
        changed = False
        def change_after_start(fd):
            nonlocal changed
            original(fd)
            if not changed:
                changed = True
                raw = self.host_script.read_bytes()
                self.host_script.write_bytes(raw.replace(b'(Toy)',b'(Bad)'))
        with self.active(), patch.object(events.os, 'fsync', side_effect=change_after_start):
            with self.assertRaisesRegex(ValueError, 'pin SHA'):
                events.run_host_probe(self.policy, self.context, self.argv(), '')
        self.assertFalse(self.fixture.marker.exists())
        self.assertEqual([row['kind'] for row in self.rows()], ['host-start'])

    def test_gcc_identifier_exact_sdk_whitespace_and_first_line_rules(self):
        line = 'gcc\u2003version\u008514.2.0 (Toy)'.encode()
        self.assertEqual(events._gcc_id(b'ignored: version 999\n'+line+b'\nversion 99'), line)
        for raw in [b'ignored: version 14', 'gcc version ١٤'.encode(), b'gcc\x1cversion 14',
                    b'gcc version 14 (experimental)\nversion 15']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                events._gcc_id(raw)

    def test_overflow_proven_signal_is_preserved(self):
        self.host_body("import sys,time\nsys.stderr.buffer.write(b'x'*70000)\nsys.stderr.flush()\ntime.sleep(30)\n")
        self.controls()
        with self.active(), patch.object(events, '_forward'):
            try:
                status = events.run_host_probe(self.policy, self.context, self.argv(), '')
            except ValueError as error:
                self.fail('proven child signal was replaced by wrapper refusal: '+str(error))
        self.assertEqual(status, -signal.SIGKILL)
        completion = self.rows()[-1]['data']
        self.assertEqual(completion['terminal'], dict(exit_code=None, signal=signal.SIGKILL))
        self.assertEqual(completion['outcome'], 'overflow')

    def test_protected_go_controls_and_exact_native_sdk_additions(self):
        released = dict(GOMAXPROCS='4', GOMEMLIMIT='15GiB', GOGC='100', GOAMD64='v1',
                        HOME=str(self.base), PATH='/usr/bin:/bin', XDG_CACHE_HOME=str(self.base), TMP=str(self.base))
        self.controls(hosts=False, parent_pid=os.getpid(), driver_environment=released)
        invalid = [('GOMAXPROCS','8'), ('GOMEMLIMIT','8GiB'), ('GOGC','200'), ('GOAMD64','v2'),
                   ('GO_UNKNOWN','unreleased'), ('HOME','/tmp'), ('PATH','/bin'), ('TMP','/tmp'), ('GOGC',None)]
        for name,value in invalid:
            with self.subTest(name=name):
                result = self.callback(['-c=1'],overrides={name:value})
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertIn(b'protected environment override',result.stderr)
                self.assertFalse(self.fixture.marker.exists())
        result = self.callback(['-c=1'],overrides=dict(GOOS='linux',GOARCH='amd64',CGO_LDFLAGS='-Wl,toy'))
        self.assertEqual(result.returncode,37,result.stderr)
        self.assertIn(b'TOY stdout',result.stdout)
        self.fixture.marker.unlink();self.fixture.journal.write_bytes(b'')
        self.controls(hosts=False,parent_pid=os.getpid(),driver_environment=dict(GOROOT=None,GOOS='',GOARCH=''))
        result = self.callback(['-c=1'],overrides=dict(GOROOT=str(self.fixture.sdk),GOOS='linux',GOARCH='amd64'))
        self.assertEqual(result.returncode,37,result.stderr)
        self.fixture.marker.unlink()
        for override in [dict(GOOS='windows'),dict(GOARCH='arm64'),dict(GOROOT='/tmp'),dict(GOAMD64='v1')]:
            with self.subTest(native_override=override):
                result = self.callback(['-c=1'],overrides=override)
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertFalse(self.fixture.marker.exists())

    def test_event_pin_bool_cannot_equal_an_admitted_integer(self):
        with self.active():
            data = self.host_start()
            data['tool'] = dict(data['tool'],uid=False)
            with self.assertRaisesRegex(ValueError,'host root pin'):
                events.append_event(self.policy,self.context,'host-start',data)
        self.assertEqual(self.rows(),[])

    def test_unproven_host_child_cannot_masquerade_as_failed_spawn(self):
        with self.active():
            start = events.append_event(self.policy,self.context,'host-start',self.host_start())
            data = dict(start_seq=start['seq'],child=None,terminal=dict(exit_code=37,signal=None),elapsed_ns=1,
                stdout=events._make_blob(b'',eof=True,lost_bytes=0),stderr=events._make_blob(b'',eof=True,lost_bytes=0),
                release_id=None,outcome='exit_nonzero')
            with self.assertRaisesRegex(ValueError,'missing host child identity'):
                events.append_event(self.policy,self.context,'host-complete',data)


class BackpressureTests(unittest.TestCase):
    """Real downstream pipes; only host metadata/path launch are fixture-bound."""
    def setUp(self):
        self._prior_subreaper = self.subreaper()
        self.subreaper(1)
        self.addCleanup(lambda:self.subreaper(self._prior_subreaper))
        self.case = EventTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def worker(self, write_fd, body, fault=None):
        case = self.case
        case.host_body(body)
        case.controls(parent_pid=os.getpid())
        env = dict(case.env, PWD=case.policy['working_directory'], LC_ALL='C', TOOLEXEC_IMPORTPATH='',
                   OM_GO_SUPERVISION_CONTEXT=case.context['_path'], OM_GO_SUPERVISION_CONTEXT_SHA256=case.context['_sha256'])
        prefix = 'import sys;sys.path.insert(0,'+repr(str(fixtures.RECORDER.parent))+');import build_tool_events as e;import record_partitioned_tool as r\n'
        prefix += 'e._verify_host_pin=lambda pin:e._pin_bytes('+repr(case.pin(case.host_script))+')\n'
        receipt=case.base/'independent-host.json'
        pending=case.base/'independent-host.pending'
        acknowledgement=case.base/'observer-ack'
        prefix += 'import os,time,json\ndef spawn(argv):\n c=e.subprocess.Popen(['+repr(str(case.host_script))+',*argv[1:]],stdin=e.subprocess.DEVNULL,stdout=e.subprocess.PIPE,stderr=e.subprocess.PIPE,start_new_session=True)\n'
        creation=case.base/'publication-created'
        release=case.base/'publication-release'
        prefix += ' identity,parent=e._process(c.pid)\n'
        if fault in ('publication_missing','publication_error','publication_invalid'):
            prefix += ' until=time.monotonic()+3\n while not e.Path('+repr(str(case.fixture.marker))+').exists() and time.monotonic()<until:time.sleep(.005)\n'
            prefix += ' if not e.Path('+repr(str(case.fixture.marker))+').exists():raise ValueError("owned host startup missing")\n'
        prefix += ' fd=os.open('+repr(str(pending))+',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)\n'
        if fault=='delay_publish':
            prefix += ' e.Path('+repr(str(creation))+').touch(exist_ok=False)\n until=time.monotonic()+3\n while not e.Path('+repr(str(release))+').exists() and time.monotonic()<until:time.sleep(.005)\n'
            prefix += ' if not e.Path('+repr(str(release))+').exists():raise ValueError("publication release missing")\n'
        if fault=='publication_missing':prefix += ' os._exit(43)\n'
        if fault=='publication_error':prefix += ' raise OSError("injected publication failure")\n'
        prefix += ' data=dict(host=identity,worker=e._process(os.getpid())[0])\n'
        if fault=='publication_invalid':prefix += ' data["worker"]["start_ticks"]+=1\n'
        prefix += ' with os.fdopen(fd,"w") as f:json.dump(data,f);f.flush();os.fsync(f.fileno())\n'
        prefix += ' os.link('+repr(str(pending))+','+repr(str(receipt))+')\n os.unlink('+repr(str(pending))+')\n'
        prefix += ' until=time.monotonic()+3\n while not e.Path('+repr(str(acknowledgement))+').exists() and time.monotonic()<until:time.sleep(.005)\n'
        prefix += ' if not e.Path('+repr(str(acknowledgement))+').exists():\n  c.kill();c.wait();raise ValueError("observer acknowledgement missing")\n'
        if fault=='exit':prefix += ' os._exit(42)\n'
        if fault=='wedge':prefix += ' while True:time.sleep(.1)\n'
        prefix += ' return c\ne._spawn_host=spawn\n'
        import textwrap
        begin=prefix.index(' identity,parent=')
        end=prefix.index('e._spawn_host=spawn')
        prefix=prefix[:begin]+' try:\n'+textwrap.indent(prefix[begin:end],' ')+' except BaseException:\n  c.kill();c.wait();raise\n'+prefix[end:]
        prefix += 'raise SystemExit(r.main(sys.argv[1:]))'
        cli = ['--policy',case.template_pin['path'],'--policy-sha256',case.template_pin['sha256'],*case.argv()]
        baseline=self.observer_children()
        worker=subprocess.Popen([sys.executable,'-B','-c',prefix,*cli],cwd=case.policy['working_directory'],env=env,
                                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=write_fd)
        worker.fixture_worker_identity=events._process(worker.pid)[0]
        worker.fixture_host_identity=None
        worker.fixture_baseline=baseline
        self.addCleanup(self.safety_reap,worker)  # Covers validation/ack failures too.
        self.last_fixture_worker=worker
        import time
        until=time.monotonic()+4
        while not receipt.exists() and worker.poll() is None and time.monotonic()<until:
            if fault=='delay_publish' and creation.exists() and not release.exists():
                self.assertFalse(acknowledgement.exists(),'ack preceded complete publication')
                fd=os.open(release,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
            time.sleep(.005)
        if not receipt.exists():
            self.discover_owned_host(worker)
            self.safety_reap(worker)
            self.fail('independent host receipt missing')
        data=json.loads(receipt.read_bytes())
        self.assertEqual(data['worker'],worker.fixture_worker_identity,'independent worker identity mismatch')
        identity,parent=events._process(data['host']['pid'])
        self.assertEqual(identity,data['host'])
        self.assertEqual(parent,worker.pid)
        self.assertEqual(events._process(worker.pid),(worker.fixture_worker_identity,os.getpid()))
        worker.fixture_host_identity=identity
        fd=os.open(acknowledgement,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        os.close(fd)
        return worker

    def pipe(self, full):
        import fcntl
        read_fd, write_fd = os.pipe()
        self.track_fd(read_fd);self.track_fd(write_fd)
        original = fcntl.fcntl(write_fd,fcntl.F_GETFL)
        if full:
            os.set_blocking(write_fd,False)
            try:
                while True: os.write(write_fd,b'P'*4096)
            except BlockingIOError:
                pass
            fcntl.fcntl(write_fd,fcntl.F_SETFL,original)
        return read_fd,write_fd,original

    def drain_cleanup(self, worker, read_fd, write_fd):
        import time
        os.set_blocking(read_fd,False)
        until=time.monotonic()+1
        try:
            while worker.poll() is None and time.monotonic()<until:
                try:os.read(read_fd,65536)
                except BlockingIOError:pass
                time.sleep(.01)
            # Independent pre-bound identity; never rely on a completion row.
            self.safety_reap(worker)
        finally:
            os.close(read_fd);os.close(write_fd)

    def blocked(self, exits):
        import fcntl,time
        case=self.case
        read_fd,write_fd,original=self.pipe(True)
        pidfile=case.base/'host-child-pid'
        body='import sys,time\nPath('+repr(str(pidfile))+').write_text(str(os.getpid()))\nsys.stderr.write("gcc version 14.2.0 (Toy)\\n")\nsys.stderr.flush()\n'
        body += 'raise SystemExit(0)\n' if exits else 'time.sleep(30)\n'
        worker=self.worker(write_fd,body)
        try:
            started=time.monotonic()
            while not pidfile.exists() and time.monotonic()-started<3:
                if worker.poll() is not None: break
                time.sleep(.01)
            self.assertTrue(pidfile.exists(),'owned toy did not start')
            child=int(pidfile.read_text())
            # Independent11.25s watchdog, never used as a production deadline.
            until=started+11.25
            while worker.poll() is None and time.monotonic()<until:
                self.assertEqual(fcntl.fcntl(write_fd,fcntl.F_GETFL),original)
                time.sleep(.02)
            self.assertIsNotNone(worker.poll(),'full downstream pipe disabled fixed10s supervision')
            self.assertEqual(worker.returncode,1 if exits else -signal.SIGKILL)
            self.assertEqual(fcntl.fcntl(write_fd,fcntl.F_GETFL),original)
            self.assertFalse(Path('/proc/'+str(child)).exists(),'owned host child survived/reaping missing')
            data=case.rows()[-1]['data']
            self.assertEqual(data['outcome'],'timeout')
            self.assertLess(data['elapsed_ns'],11*1000000000)
            self.assertTrue(data['stderr']['eof'])
            self.assertEqual(data['stderr']['lost_bytes'],0)
            self.assertEqual(events._blob(data['stderr'],65536,True),b'gcc version 14.2.0 (Toy)\n')
            self.assertEqual(data['terminal'],dict(exit_code=0,signal=None) if exits else dict(exit_code=None,signal=signal.SIGKILL))
        finally:
            # Even RED drains only AFTER the deadline assertion, unblocking old
            # code so it can kill/wait its child; observer then waits its worker.
            self.drain_cleanup(worker,read_fd,write_fd)

    def test_full_pipe_does_not_disable_host_deadline(self):
        self.blocked(exits=False)

    def test_full_pipe_does_not_block_main_failure_diagnostic(self):
        self.blocked(exits=True)

    def test_draining_pipe_preserves_original_bytes_and_descriptor_flags(self):
        import fcntl,time
        raw=b'diagnostic detail\n'*600+b'gcc version 14.2.0 (Toy)\n'
        read_fd,write_fd,original=self.pipe(False)
        worker=self.worker(write_fd,'import sys\nsys.stderr.buffer.write('+repr(raw)+')\nsys.stderr.flush()\n')
        observed=bytearray()
        try:
            os.set_blocking(read_fd,False)
            until=time.monotonic()+5
            while worker.poll() is None and time.monotonic()<until:
                try: observed.extend(os.read(read_fd,65536))
                except BlockingIOError: pass
                self.assertEqual(fcntl.fcntl(write_fd,fcntl.F_GETFL),original)
                time.sleep(.005)
            self.assertEqual(worker.wait(timeout=1),0)
            while True:
                try:
                    chunk=os.read(read_fd,65536)
                    if not chunk: break
                    observed.extend(chunk)
                except BlockingIOError: break
            self.assertEqual(bytes(observed),raw)
            self.assertEqual(fcntl.fcntl(write_fd,fcntl.F_GETFL),original)
            self.assertEqual(self.case.rows()[-1]['data']['outcome'],'ok')
        finally:
            self.drain_cleanup(worker,read_fd,write_fd)


    def test_nonpipe_forwarding_fails_closed_without_changing_flags(self):
        import fcntl
        target=self.case.base/'unsupported-output'
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        self.track_fd(fd)
        flags=fcntl.fcntl(fd,fcntl.F_GETFL)
        worker=self.worker(fd,'import sys\nsys.stderr.write("gcc version 14.2.0 (Toy)\\n")\nsys.stderr.flush()\n')
        try:
            stdout,stderr=worker.communicate(timeout=5)
            self.assertNotEqual(worker.returncode,0)
            self.assertEqual(target.read_bytes(),b'')
            self.assertEqual(fcntl.fcntl(fd,fcntl.F_GETFL),flags)
            row=self.case.rows()[-1]['data']
            self.assertEqual(row['outcome'],'io_error')
            self.assertFalse(Path('/proc/'+str(row['child']['pid'])).exists())
        finally:
            if worker.poll() is None:worker.kill()
            worker.communicate(timeout=4)
            os.close(fd)


    @staticmethod
    def subreaper(value=None):
        # Process-local test observer only; restored after all owned fixtures.
        import ctypes
        libc=ctypes.CDLL(None,use_errno=True)
        current=ctypes.c_int()
        if libc.prctl(37,ctypes.byref(current),0,0,0)!=0:
            raise OSError(ctypes.get_errno(),'PR_GET_CHILD_SUBREAPER')
        if value is not None and libc.prctl(36,value,0,0,0)!=0:
            raise OSError(ctypes.get_errno(),'PR_SET_CHILD_SUBREAPER')
        return current.value

    def owned_host_exists(self,worker):
        if worker.fixture_host_identity is None:return False
        try:identity,parent=events._process(worker.fixture_host_identity['pid'])
        except FileNotFoundError:return False
        if identity!=worker.fixture_host_identity:return False
        self.assertIn(parent,(worker.pid,os.getpid()),'unowned parent; refuse guessed PID cleanup')
        return True

    @staticmethod
    def observer_children(pid=None):
        # Some proc implementations omit task/*/children. Enumerate actual
        # stat PPIDs instead; absence of that optional file is not an empty tree.
        import errno,time
        parent=os.getpid() if pid is None else pid
        children=set()
        deadline=time.monotonic()+.25  # Within the existing3s/4s fixture bounds.
        count=0
        with os.scandir('/proc') as entries:
            for entry in entries:
                if not entry.name.isascii() or not entry.name.isdecimal():continue
                count+=1
                if count>4096 or time.monotonic()>=deadline:
                    raise AssertionError('incomplete owned-process census: entry/time bound')
                try:
                    fd=os.open('/proc/'+entry.name+'/stat',os.O_RDONLY|os.O_NOFOLLOW)
                    try:raw=os.read(fd,65537)
                    finally:os.close(fd)
                except OSError as error:
                    if error.errno in (errno.ENOENT,errno.ESRCH):continue
                    raise AssertionError('unreadable owned-process census') from error
                if len(raw)>65536 or time.monotonic()>=deadline:
                    raise AssertionError('incomplete owned-process census: stat/time bound')
                try:
                    fields=raw[raw.rfind(b')')+2:].split()
                    actual=int(raw.split(b' ',1)[0]);ppid=int(fields[1]);start=int(fields[19])
                    if actual!=int(entry.name) or actual<1 or ppid<0 or start<1:raise ValueError()
                except (ValueError,IndexError) as error:
                    raise AssertionError('invalid owned-process census stat') from error
                if ppid==parent:children.add(actual)
        return children

    def discover_owned_host(self,worker):
        try:current_worker,_=events._process(worker.pid)
        except FileNotFoundError:current_worker=None
        candidates=self.observer_children(worker.pid) if current_worker==worker.fixture_worker_identity else set()
        candidates|=self.observer_children()-worker.fixture_baseline-{worker.pid}
        self.assertLessEqual(len(candidates),1,'unexpected owned fixture descendants')
        if candidates:
            pid=candidates.pop()
            identity,parent=events._process(pid)
            self.assertIn(parent,(worker.pid,os.getpid()))
            worker.fixture_host_identity=identity

    def terminate_identity(self,identity,parents):
        # pidfd binds the signal even if a PID is concurrently reaped/reused.
        try:fd=os.pidfd_open(identity['pid'])
        except ProcessLookupError:return False
        try:
            try:current,parent=events._process(identity['pid'])
            except FileNotFoundError:return False
            if current!=identity:return False
            self.assertIn(parent,parents,'unowned process; refuse signal')
            signal.pidfd_send_signal(fd,signal.SIGKILL)
            return True
        except ProcessLookupError:return False
        finally:os.close(fd)

    def safety_reap(self,worker):
        import time
        # Adoption was installed BEFORE spawning. Kill the host first, then a
        # wedged owner; the observer can wait the adopted host without a journal.
        if worker.fixture_host_identity is None:self.discover_owned_host(worker)
        receipt=dict(worker=worker.fixture_worker_identity,host=worker.fixture_host_identity,
                     host_signal=False,worker_signal=False,host_reaped_by='worker')
        if self.owned_host_exists(worker):
            receipt['host_signal']=self.terminate_identity(worker.fixture_host_identity,(worker.pid,os.getpid()))
        if worker.poll() is None:
            receipt['worker_signal']=self.terminate_identity(worker.fixture_worker_identity,(os.getpid(),))
        worker.communicate(timeout=3)
        until=time.monotonic()+3
        while self.owned_host_exists(worker) and time.monotonic()<until:
            try:pid,status=os.waitpid(worker.fixture_host_identity['pid'],os.WNOHANG)
            except ChildProcessError:pid=0
            if pid:
                receipt.update(host_reaped_by='observer',host_wait_status=status)
                break
            time.sleep(.01)
        self.assertFalse(self.owned_host_exists(worker),'adopted host was not terminated/reaped')
        receipt.update(worker_returncode=worker.returncode,host_survives=False)
        worker.fixture_cleanup_receipt=receipt

    def cleanup_fault(self,fault):
        import time
        read_fd,write_fd,flags=self.pipe(True)
        worker=self.worker(write_fd,'import time\ntime.sleep(30)\n',fault=fault)
        closed=False
        try:
            if fault=='exit':self.assertEqual(worker.wait(timeout=2),42)
            else:time.sleep(.05);self.assertIsNone(worker.poll())
            self.assertEqual([row['kind'] for row in self.case.rows()],['host-start'])
            self.assertTrue(self.owned_host_exists(worker))
            self.drain_cleanup(worker,read_fd,write_fd);closed=True
            self.assertFalse(self.owned_host_exists(worker),'watchdog abandoned host without completion')
            self.assertEqual(worker.fixture_cleanup_receipt['host_reaped_by'],'observer')
            print('OWNED_CLEANUP',json.dumps(dict(fault=fault,**worker.fixture_cleanup_receipt),sort_keys=True))
        finally:
            # RED is independently contained even when the cleanup under test
            # fails: terminate/reap exact pre-bound identities, never guessed PIDs.
            self.safety_reap(worker)
            if not closed:
                for fd in (read_fd,write_fd):
                    try:os.close(fd)
                    except OSError:pass

    def test_cleanup_contains_worker_exit_before_completion(self):
        self.cleanup_fault('exit')

    def test_cleanup_contains_wedged_worker_before_completion(self):
        self.cleanup_fault('wedge')


    def test_delayed_publication_waits_for_complete_receipt(self):
        read_fd,write_fd,flags=self.pipe(False)
        worker=None
        try:
            try:
                worker=self.worker(write_fd,'import sys\nsys.stderr.write("gcc version 14.2.0 (Toy)\\n")\n',fault='delay_publish')
            except json.JSONDecodeError:
                self.fail('observer decoded a receipt before publication completed')
            worker.communicate(timeout=4)
            self.assertEqual(worker.returncode,0)
            self.assertTrue((self.case.base/'observer-ack').exists())
        finally:
            if worker is not None:self.safety_reap(worker)
            for fd in (read_fd,write_fd):
                try:os.close(fd)
                except OSError:pass


    def track_fd(self,fd):
        import fcntl,stat
        info=os.fstat(fd)
        binding=(info.st_dev,info.st_ino,stat.S_IFMT(info.st_mode),fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE)
        self.addCleanup(self.close_bound_fd,fd,binding)

    @staticmethod
    def close_bound_fd(fd,binding):
        import errno,fcntl,stat
        try:
            info=os.fstat(fd)
            current=(info.st_dev,info.st_ino,stat.S_IFMT(info.st_mode),fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE)
        except OSError as error:
            if error.errno==errno.EBADF:return
            raise
        if current==binding:os.close(fd)  # Never close an unrelated reused FD.

    def publication_fault(self,fault,expected):
        import errno,fcntl
        nested=BackpressureTests()
        nested.setUp()
        self.addCleanup(nested.doCleanups)
        prior=nested._prior_subreaper
        read_fd,write_fd,flags=nested.pipe(True)
        with self.assertRaises(expected) as failure:
            nested.worker(write_fd,'import time\ntime.sleep(30)\n',fault=fault)
        self.assertIn('independent worker identity mismatch' if fault=='publication_invalid' else 'independent host receipt missing',str(failure.exception))
        worker=nested.last_fixture_worker
        cleanup_before=getattr(worker,'fixture_cleanup_receipt',None)
        self.assertEqual(fcntl.fcntl(write_fd,fcntl.F_GETFL),flags)
        self.assertTrue(nested.doCleanups(),'nested cleanup failed')  # Never hide cleanup errors.
        self.assertIsNotNone(worker.returncode)
        self.assertFalse(nested.owned_host_exists(worker))
        self.assertEqual(self.subreaper(),prior)
        for fd in (read_fd,write_fd):
            with self.assertRaises(OSError) as caught:os.fstat(fd)
            self.assertEqual(caught.exception.errno,errno.EBADF)
        observation=cleanup_before or worker.fixture_cleanup_receipt
        if fault!='publication_error':
            self.assertIsNotNone(observation['host'])
            self.assertEqual(observation['host_reaped_by'],'observer')
            self.assertEqual(observation['host_wait_status'],9)
        print('PUBLICATION_CLEANUP',json.dumps(dict(fault=fault,**observation),sort_keys=True))

    def test_missing_publication_reaps_fixture_and_closes_early_pipe_fds(self):
        self.publication_fault('publication_missing',AssertionError)

    def test_failed_publication_reaps_fixture_and_closes_early_pipe_fds(self):
        self.publication_fault('publication_error',AssertionError)

    def test_invalid_publication_closes_early_pipe_fds_after_validation_failure(self):
        self.publication_fault('publication_invalid',AssertionError)


    def test_stat_census_retains_owned_host_when_task_children_is_unavailable(self):
        read_fd,write_fd,flags=self.pipe(True)
        worker=self.worker(write_fd,'import time\ntime.sleep(30)\n',fault='wedge')
        original=Path.read_text
        def unavailable(path,*args,**kwargs):
            if str(path).startswith('/proc/') and str(path).endswith('/children'):
                raise FileNotFoundError('task children unavailable fixture')
            return original(path,*args,**kwargs)
        try:
            with patch.object(Path,'read_text',unavailable):
                self.assertIn(worker.fixture_host_identity['pid'],self.observer_children(worker.pid))
        finally:
            self.drain_cleanup(worker,read_fd,write_fd)
