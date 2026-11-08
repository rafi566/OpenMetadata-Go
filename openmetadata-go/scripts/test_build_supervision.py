# SPDX-License-Identifier: Apache-2.0
"""Owned Python toys and isolated files; never selected Go/SDK execution."""
from pathlib import Path
import tempfile
import unittest
import hashlib
import copy
import json
from unittest.mock import patch
import build_supervision as engine
import build_tool_events as b1
import build_supervision_io as capture_io
import test_build_tool_events as control_fixtures
import os
import subprocess
import signal
import sys
import time
from build_supervision_io import capture_streams, reserved_raw
from build_supervision import load_job
from build_supervision_io import reserve_raw


class AdmissionTests(unittest.TestCase):
    def test_invalid_job_is_refused_before_effects(self):
        for raw in [b'{}',b'{"format":"om-build-job-v1","format":"om-build-job-v1"}',b'{"x":NaN}',b'\xff']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):load_job(raw)


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)

    def test_job_counter_is_shared_durable_and_never_reclaimed(self):
        self.assertEqual(reserve_raw(self.root,3),3)
        self.assertEqual(reserve_raw(self.root,5),8)
        with self.assertRaises(ValueError):reserve_raw(self.root,True)
        with self.assertRaises(ValueError):reserve_raw(self.root,65537)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.driver=self.root/'root';self.driver.mkdir(mode=0o700)

    def child(self,body):
        process=subprocess.Popen([sys.executable,'-B','-c',body],stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        def reap():
            if process.poll() is None:process.kill()
            process.wait(timeout=3)
            process.stdout.close();process.stderr.close()
        self.addCleanup(reap)
        return process

    def test_stdout_and_stderr_are_persisted_and_charged_to_one_counter(self):
        child=self.child("import sys;sys.stdout.buffer.write(b'ab');sys.stderr.buffer.write(b'cde')")
        result=capture_streams(child,self.root,self.driver,time.monotonic_ns()+3_000_000_000)
        self.assertEqual(result.get('stdout',{}).get('bytes'),2)
        self.assertEqual(result.get('stderr',{}).get('bytes'),3)
        self.assertEqual(reserved_raw(self.root),5)
        self.assertEqual(result['stdout']['sha256'],hashlib.sha256(b'ab').hexdigest())
        self.assertEqual(result['stderr']['sha256'],hashlib.sha256(b'cde').hexdigest())
        self.assertTrue(result['stdout']['eof'] and result['stderr']['eof'])
        self.assertEqual(child.returncode,0)
        self.assertTrue(result['cleanup_complete'])

    def test_deadline_kills_and_reaps_owned_child(self):
        child=self.child('import time;time.sleep(3)')
        result=capture_streams(child,self.root,self.driver,time.monotonic_ns()+50_000_000)
        self.assertTrue(result.get('timed_out'))
        self.assertIsNotNone(child.returncode)
        self.assertTrue(result['cleanup_complete'])


SUPPORT=sorted(['go.mod','go.sum','schema/optional.go','internal/schema/json.go',
    'internal/schema/value.go','internal/schema/numbers.go','internal/schema/registry.go',
    'internal/schema/resolve.go','internal/schema/legacy_profile.go','internal/schema/legacy-profile.json',
    'internal/schema/regexp.go','internal/schema/validate.go','internal/schema/numeric_admission.go','internal/schema/embedded.go'])


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.controls=control_fixtures.EventTests();self.controls.setUp()
        self.addCleanup(lambda:self.assertTrue(self.controls.doCleanups()))
        self.controls.controls(hosts=False)
        self.config=copy.deepcopy(self.controls.config)
        self.config['environment'].update(OM_BUILD_LAUNCHER=str(self.controls.base/'launcher'),
            OM_GENERATED_EVIDENCE_DIR=self.controls.roots['fixtures'])
        self.config['fixture_slots']=[dict(driver_id='fix',test_name='TestToy',package='toy',support_paths=SUPPORT)]
        self.config['coverage']=[]
        for driver,argv in [('fix',['test','./...','-count=1']),('root',['version'])]:
            plan=dict(format='om-build-coverage-v1',driver_id=driver,argv=argv,
                required_packages=['example/p'] if driver=='fix' else [],
                action_descriptions=[dict(description='example/p',import_path='example/p')] if driver=='fix' else [],
                zero_build_diagnostic=driver=='root')
            self.config['coverage'].append(dict(driver_id=driver,plan=self.controls.write('b3-plan',plan)))
        self.root=Path(self.controls.roots['fixtures'])/'emitted-one';self.root.mkdir(mode=0o700)
        for path in SUPPORT+['toy/models.go','toy/behavior_test.go']:
            dest=self.root/path;dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            dest.write_bytes(b'fixture bytes');dest.chmod(0o600)
        self.request=dict(format='om-fixture-freeze-v1',job_id='job',test_name='TestToy',root=str(self.root),generated_paths=['models.go'])

    def freeze(self,request=None):
        # Semantic fixture admission tests inject only inherited live ancestry.
        # Dedicated gate/ancestry tests exercise actual processes separately.
        with patch.object(engine,'_request_context',return_value=None):
            return engine.handle_request(engine.load_job(b1.v1._encoded(self.config)), 'freeze', b1.v1._encoded(self.request if request is None else request))

    def test_freeze_exact_expected_membership_and_cwd_only_policy(self):
        reply=self.freeze()
        self.assertEqual(reply.get('status'),'PASS')
        registration=json.loads(b1._pin_bytes(reply['receipt'],control=True))
        self.assertEqual(registration['driver_id'],'fix')
        manifest=json.loads(b1._pin_bytes(registration['manifest'],16*1024*1024,control=True))
        self.assertEqual([row['path'] for row in manifest['files']],sorted(SUPPORT+['toy/models.go','toy/behavior_test.go']))
        effective=json.loads(b1._pin_bytes(registration['policy'],control=True))
        template=json.loads(b1._pin_bytes(self.config['tool_policy'],control=True))
        self.assertEqual(effective,dict(template,working_directory=str(self.root)))
        with self.assertRaises(ValueError):self.freeze()

    def test_observed_only_expectation_and_inexact_support_are_refused(self):
        (self.root/'toy/extra.go').write_bytes(b'not released')
        with self.assertRaises(ValueError):self.freeze()
        (self.root/'toy/extra.go').unlink()
        self.config['fixture_slots'][0]['support_paths']=SUPPORT[:-1]
        with self.assertRaises(ValueError):self.freeze()

    def test_unexpected_empty_directory_is_rejected_before_freeze(self):
        (self.root/'toy/empty-extra').mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError,'extra fixture directory'):self.freeze()

    def test_actual_coverage_bytes_are_authenticated_before_freeze(self):
        plan=Path(self.config['coverage'][0]['plan']['path'])
        plan.write_bytes(plan.read_bytes()+b' ')
        with self.assertRaises(ValueError):self.freeze()


class RequestAncestryTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    def root_context(self,identity=None):
        config_pin=self.controls.write('b3-inherited-config',self.config)
        start=dict(format='om-go-driver-start-v1',job_id='job',driver_id='root',parent_driver_id=None,
            go_identity=b1._process(os.getppid())[0] if identity is None else identity,
            sdk_go=self.config['sdk_go'],manifest=self.config['input_manifest'])
        start_pin=self.controls.write('b3-inherited-start',start)
        wire=dict(format='om-go-context-v1',job_id='job',driver_id='root',config=config_pin,
            start=start_pin,policy=self.config['tool_policy'])
        return self.controls.write('b3-inherited-context',wire)

    def inherited(self,pin):
        return patch.dict(os.environ,dict(self.config['environment'],
            OM_GO_SUPERVISION_CONTEXT=pin['path'],OM_GO_SUPERVISION_CONTEXT_SHA256=pin['sha256']),clear=True)

    def test_actual_parent_ancestry_is_admitted_after_nonlive_pin_authentication(self):
        pin=self.root_context()
        with self.inherited(pin):
            try:
                result=engine._request_context(self.config)
                admitted=result is not None and result['driver_id']=='root'
            except ValueError:admitted=False
        self.assertTrue(admitted,'real Python parent/SDK identity with authenticated controls was refused')

    def test_forged_start_and_wrong_environment_are_refused(self):
        identity=b1._process(os.getppid())[0];identity['start_ticks']+=1
        with self.inherited(self.root_context(identity)):
            with self.assertRaises(ValueError):engine._request_context(self.config)
        with self.inherited(self.root_context()),patch.dict(os.environ,{'OM_BUILD_JOB_ID':'wrong'}):
            with self.assertRaises(ValueError):engine._request_context(self.config)


class GateTests(unittest.TestCase):
    setUp=FixtureTests.setUp

    def prepare(self):
        body="import os;raw=open('/proc/self/stat').read();fields=raw[raw.rfind(')')+2:].split();print('EXEC',os.getpid(),fields[19],flush=True)"
        argv=['-B','-c',body]
        self.config['root_driver']['argv']=argv
        plan=dict(format='om-build-coverage-v1',driver_id='root',argv=argv,required_packages=['example/p'],
            action_descriptions=[dict(description='example/p',import_path='example/p')],zero_build_diagnostic=False)
        self.config['coverage'][1]['plan']=self.controls.write('b3-toy-root-plan',plan)
        self.config['_pin']=self.controls.write('b3-gate-config',self.config)
        self.driver=Path(self.controls.roots['drivers'])/'root';self.driver.mkdir(mode=0o700)
        return self.config['root_driver']

    def test_exec_preserves_real_gated_pid_and_start_ticks(self):
        driver=self.prepare()
        process=engine._spawn_gated(self.config,driver,self.config['input_manifest'],self.config['tool_policy'],self.driver)
        self.assertIsNotNone(process,'gate did not release an executed owned Python child')
        try:
            start=json.loads((Path(self.config['roots']['registrations'])/'root.start.json').read_bytes())
            result=capture_streams(process,Path(self.config['roots']['drivers']),self.driver,time.monotonic_ns()+3_000_000_000)
            raw=b''.join(Path(pin['path']).read_bytes() for pin in result['stdout']['segments'])
            self.assertEqual(raw,('EXEC '+str(start['go_identity']['pid'])+' '+str(start['go_identity']['start_ticks'])+'\n').encode())
            self.assertEqual(process.returncode,0)
            self.assertTrue(result['cleanup_complete'])
        finally:
            if process.poll() is None:process.kill()
            process.wait(timeout=3)
            process.stdout.close();process.stderr.close()

    def test_failed_publication_or_lost_ack_prevents_exec(self):
        driver=self.prepare()
        publish=engine._publish
        def fail_start(directory,name,value,maximum=16*1024*1024):
            if name=='root.start.json':raise ValueError('forced publication failure')
            return publish(directory,name,value,maximum)
        with patch.object(engine,'_publish',side_effect=fail_start):
            with self.assertRaises(ValueError):
                engine._spawn_gated(self.config,driver,self.config['input_manifest'],self.config['tool_policy'],self.driver)
        self.assertFalse((self.driver/'stdout.000001.raw').exists())
        self.assertTrue((self.driver/'gate-failure.json').exists())
        receipt=json.loads((self.driver/'gate-failure.json').read_bytes())
        self.assertTrue(receipt['cleanup_complete'])
        self.assertEqual(receipt['stdout']['bytes'],0)
        self.assertNotEqual(receipt['exit_code'],0)


class OwnershipTests(unittest.TestCase):
    def owned_tree(self,lose_launcher=False):
        safety=control_fixtures.BackpressureTests()
        previous=safety.subreaper(1)
        self.addCleanup(lambda:safety.subreaper(previous))
        baseline=safety.observer_children()
        owner=capture_io._Ownership()
        child_body="import time;time.sleep(10)"
        body="import subprocess,sys,time;subprocess.Popen([sys.executable,'-B','-c',"+repr(child_body)+"]);time.sleep(10)"
        process=subprocess.Popen([sys.executable,'-B','-c',body],stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        process.fixture_worker_identity=b1._process(process.pid)[0]
        process.fixture_host_identity=None;process.fixture_baseline=baseline
        def cleanup():
            for name in ('stdout','stderr'):
                stream=getattr(process,name)
                if stream is not None and stream.closed:setattr(process,name,None)
            safety.safety_reap(process)
            receipt=dict(process.fixture_cleanup_receipt)
            for wait in getattr(owner,'waits',[]):
                if wait['identity']==process.fixture_host_identity:
                    receipt.update(host_reaped_by='B3_owner',host_wait_status=wait['status'])
            print('OWNERSHIP_CLEANUP '+json.dumps(receipt,sort_keys=True),flush=True)
        self.addCleanup(cleanup)
        until=time.monotonic()+2
        while process.fixture_host_identity is None and time.monotonic()<until:
            safety.discover_owned_host(process)
            if process.fixture_host_identity is None:time.sleep(.005)
        self.assertIsNotNone(process.fixture_host_identity,'real pipe-holding descendant did not start')
        owner.bind(process);owner.tick()
        self.assertIn(process.fixture_host_identity,owner.identities)
        if lose_launcher:
            safety.terminate_identity(process.fixture_worker_identity,(os.getpid(),))
            until=time.monotonic()+2
            while time.monotonic()<until:
                if b1._process(process.fixture_host_identity['pid'])[1]==os.getpid():break
                time.sleep(.005)
            self.assertEqual(b1._process(process.fixture_host_identity['pid'])[1],os.getpid())
            owner.tick()
            self.assertTrue(owner.failed,'launcher loss left a known adopted pipe-holder admitted')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);driver=root/'root';driver.mkdir(mode=0o700)
            process._om_owner=owner
            result=capture_streams(process,root,driver,time.monotonic_ns()+50_000_000)
            self.assertEqual(result['timed_out'],not lose_launcher)
            self.assertEqual(result['_io_error'],lose_launcher)
            self.assertTrue(result['cleanup_complete'])
            self.assertTrue(result['stdout']['eof'] and result['stderr']['eof'])
            self.assertFalse(Path('/proc/'+str(process.fixture_host_identity['pid'])).exists())
            self.assertIsNotNone(process.returncode)
            self.assertTrue(owner.waits,'adopted descendant has no actual wait receipt')

    def test_stat_census_tracks_and_reaps_actual_pipe_holding_descendant(self):
        self.owned_tree()

    def test_launcher_loss_cancels_known_adopted_pipe_holder(self):
        self.owned_tree(lose_launcher=True)


class RawAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);self.driver=self.root/'root';self.driver.mkdir(mode=0o700)
        self.pins=[]
        for i,raw in enumerate([b'ab',b'cd'],1):
            path=self.driver/('stderr.'+str(i).zfill(6)+'.raw')
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:f.write(raw)
            self.pins.append(dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),mode=0o600))
        self.stream=dict(segments=self.pins,bytes=4,sha256=hashlib.sha256(b'abcd').hexdigest(),eof=True,
            observed_discarded_bytes=0,loss_unknown=False)

    def test_original_ordered_bytes_are_authenticated_not_dict_hashed(self):
        self.assertEqual(b''.join(capture_io.authenticate_stream(self.driver,'stderr',self.stream)),b'abcd')

    def test_retained_mutation_reorder_substitution_and_truncation_reject(self):
        path=Path(self.pins[0]['path'])
        path.write_bytes(b'xy')
        with self.assertRaises(ValueError):list(capture_io.authenticate_stream(self.driver,'stderr',self.stream))
        path.write_bytes(b'ab')
        stream=copy.deepcopy(self.stream);stream['segments'].reverse()
        with self.assertRaises(ValueError):list(capture_io.authenticate_stream(self.driver,'stderr',stream))
        other=self.root/'other';other.mkdir(mode=0o700);other_path=other/path.name;other_path.write_bytes(b'ab');other_path.chmod(0o600)
        stream=copy.deepcopy(self.stream);stream['segments'][0]['path']=str(other_path)
        with self.assertRaises(ValueError):list(capture_io.authenticate_stream(self.driver,'stderr',stream))
        path.write_bytes(b'a')
        with self.assertRaises(ValueError):list(capture_io.authenticate_stream(self.driver,'stderr',self.stream))

    def test_missing_eof_and_observed_loss_reject(self):
        for key,value in [('eof',False),('loss_unknown',True),('observed_discarded_bytes',1)]:
            stream=dict(self.stream,**{key:value})
            with self.subTest(key=key),self.assertRaises(ValueError):list(capture_io.authenticate_stream(self.driver,'stderr',stream))


class FrozenIntegrityTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    freeze=FixtureTests.freeze

    def test_frozen_original_members_and_root_identity_are_rechecked(self):
        self.freeze()
        result=engine._fixture_check(self.config,'fix')
        self.assertEqual(result.get('driver_id'),'fix')
        path=self.root/'toy/models.go';path.write_bytes(b'changed bytes')
        with self.assertRaises(ValueError):engine._fixture_check(self.config,'fix')

    def test_extra_and_missing_after_freeze_refuse(self):
        self.freeze()
        extra=self.root/'toy/extra.go';extra.write_bytes(b'extra')
        with self.assertRaises(ValueError):engine._fixture_check(self.config,'fix')
        extra.unlink();(self.root/'toy/models.go').unlink()
        with self.assertRaises(ValueError):engine._fixture_check(self.config,'fix')

    def test_unexpected_empty_directory_is_rejected_after_freeze(self):
        self.freeze()
        (self.root/'toy/empty-extra').mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError,'extra fixture directory'):engine._fixture_check(self.config,'fix')

    def test_replaced_root_inode_refuses_even_with_identical_bytes(self):
        import shutil
        self.freeze()
        original=self.root.with_name('original-root');self.root.rename(original)
        shutil.copytree(original,self.root)
        with self.assertRaises(ValueError):engine._fixture_check(self.config,'fix')


class DriverSupervisionTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    prepare=GateTests.prepare

    def test_root_owned_toy_driver_has_original_terminal_and_no_survivors(self):
        driver=self.prepare()
        # The supervisor creates its own fresh driver directory.
        self.driver.rmdir()
        manifest=source_manifest=json.loads(b1._pin_bytes(self.config['input_manifest'],16*1024*1024,control=True))
        try:terminal=engine.supervise_driver(self.config,driver,manifest)
        except ValueError:terminal={}
        self.assertEqual(terminal.get('format'),'om-driver-terminal-v1')
        self.assertEqual(terminal['exit_code'],0)
        self.assertTrue(terminal['cleanup_complete'])
        self.assertTrue(terminal['stdout']['eof'] and terminal['stderr']['eof'])
        self.assertFalse(terminal['timed_out'] or terminal['overflow'])
        self.assertEqual(terminal['manifest'],self.config['input_manifest'])
        self.assertFalse(Path('/proc/'+str(terminal['go_identity']['pid'])).exists())

    def test_changed_original_source_refuses_before_exec(self):
        driver=self.prepare();self.driver.rmdir()
        manifest=json.loads(b1._pin_bytes(self.config['input_manifest'],16*1024*1024,control=True))
        (Path(manifest['root'])/'a.go').write_bytes(b'changed')
        with self.assertRaises(ValueError):engine.supervise_driver(self.config,driver,manifest)
        self.assertFalse((self.driver/'stdout.000001.raw').exists())


class LifecycleTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    freeze=FixtureTests.freeze

    def prepare_sdk(self,exit_code=0):
        # Explicit owned Python script stands in for SDK execution metadata.
        # No SDK callbacks/image behavior or actual Go result is asserted here.
        path=self.controls.base/'owned-python-sdk'
        raw=('#!'+sys.executable+' -B\nimport sys\nsys.stderr.write("owned Python fixture\\n")\nraise SystemExit('+str(exit_code)+')\n').encode()
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o700)
        with os.fdopen(fd,'wb') as f:f.write(raw)
        self.config['sdk_go']=self.controls.pin(path)
        self.freeze()
        self.config['_pin']=self.controls.write('b3-lifecycle-config',self.config)

    def call(self,mode):
        with patch.object(engine,'_request_context',return_value=None):
            return engine.handle_request(self.config,mode,b1.v1._encoded(dict(format='om-fixture-'+mode+'-v1',job_id='job',driver_id='fix')))

    def test_frozen_run_terminal_post_and_single_consumption(self):
        self.prepare_sdk()
        try:reply=self.call('run')
        except ValueError:reply={}
        self.assertEqual(reply.get('status'),'PASS')
        terminal=json.loads(b1._pin_bytes(reply['receipt'],control=True))
        self.assertEqual(terminal['exit_code'],0)
        post=self.call('post');self.assertEqual(post['status'],'PASS')
        result=json.loads(b1._pin_bytes(post['receipt'],control=True))
        self.assertEqual((result['integrity_pass'],result['run_pass']),(True,True))
        with self.assertRaises(ValueError):self.call('run')
        with self.assertRaises(ValueError):self.call('post')

    def test_actual_child_failure_still_has_post_and_unchanged_terminal(self):
        self.prepare_sdk(exit_code=7)
        try:reply=self.call('run')
        except ValueError:reply={}
        self.assertEqual(reply.get('status'),'FAIL')
        terminal=json.loads(b1._pin_bytes(reply['receipt'],control=True))
        self.assertEqual((terminal['exit_code'],terminal['signal']),(7,None))
        post=self.call('post');self.assertEqual(post['status'],'FAIL')
        result=json.loads(b1._pin_bytes(post['receipt'],control=True))
        self.assertTrue(result['integrity_pass']);self.assertFalse(result['run_pass'])


class JobAggregationTests(unittest.TestCase):
    setUp=FixtureTests.setUp

    def prepare_root_job(self,trace_bytes):
        argv=['-B','-c','import sys;sys.stderr.buffer.write('+repr(trace_bytes)+')']
        self.config['root_driver']['argv']=argv;self.config['fixture_slots']=[]
        plan=dict(format='om-build-coverage-v1',driver_id='root',argv=argv,required_packages=['example/p'],
            action_descriptions=[dict(description='example/p',import_path='example/p')],zero_build_diagnostic=False)
        self.config['coverage']=[dict(driver_id='root',plan=self.controls.write('b3-root-coverage',plan))]
        self.config['_pin']=self.controls.write('b3-root-job-config',self.config)

    def root_request(self):
        return engine.handle_request(self.config,'driver',b1.v1._encoded(dict(format='om-root-driver-v1',job_id='job',driver_id='root')))

    def test_root_final_replays_complete_job_and_reconciles_retained_original_trace(self):
        raw=(b'HASH[build example/p]\nHASH[build example/p]: "go1.27.2"\n'
             b'HASH[build example/p]: "compile\\n"\n'
             b'HASH[build example/p]: 64c7ffabfb3369adbfd0af27af9feb9b13d352be3e36b8fc19762c1d95771daf\n')
        self.prepare_root_job(raw)
        try:reply=self.root_request()
        except ValueError:reply={}
        self.assertEqual(reply.get('status'),'PASS')
        result=json.loads(b1._pin_bytes(reply['receipt'],16*1024*1024,control=True))
        self.assertEqual(result['reserved_raw_bytes'],len(raw))
        self.assertEqual(result['coverage_results'][0]['coverage_sha256'],self.config['coverage'][0]['plan']['sha256'])
        self.assertEqual(result['coverage_results'][0]['covered_packages'],['example/p'])

    def test_missing_trace_is_not_a_zero_build_diagnostic(self):
        self.prepare_root_job(b'')
        try:reply=self.root_request()
        except ValueError:reply={}
        self.assertEqual(reply.get('status'),'FAIL')
        self.assertTrue((Path(self.config['roots']['drivers'])/'root/terminal.json').exists())


class CLITests(unittest.TestCase):
    setUp=FixtureTests.setUp
    prepare_root_job=JobAggregationTests.prepare_root_job

    def invoke_cli(self,request):
        self.prepare_root_job(b'HASH[build example/p]\nHASH[build example/p]: "go1.27.2"\n'
            b'HASH[build example/p]: "compile\\n"\nHASH[build example/p]: 64c7ffabfb3369adbfd0af27af9feb9b13d352be3e36b8fc19762c1d95771daf\n')
        safety=control_fixtures.BackpressureTests();previous=safety.subreaper(1)
        try:
            baseline=safety.observer_children()
            pin=self.config['_pin']
            process=subprocess.Popen([sys.executable,'-B',str(Path(engine.__file__)), '--config',pin['path'],
                '--config-sha256',pin['sha256'],'driver'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            process.fixture_worker_identity=b1._process(process.pid)[0]
            process.fixture_host_identity=None;process.fixture_baseline=baseline
            try:
                stdout,stderr=process.communicate(request,timeout=30)
                return process.returncode,stdout,stderr
            finally:safety.safety_reap(process)
        finally:safety.subreaper(previous)

    def test_cli_bound_config_executes_only_registered_driver_and_returns_wire(self):
        code,stdout,stderr=self.invoke_cli(b'{"format":"om-root-driver-v1","job_id":"job","driver_id":"root"}')
        self.assertEqual(code,0)
        self.assertLessEqual(len(stdout)+len(stderr),4096)
        reply=b1._strict(stdout,4096)
        self.assertEqual(set(reply),{'format','job_id','driver_id','phase','status','receipt','error'})
        self.assertEqual((reply['phase'],reply['status'],reply['job_id']),('driver','PASS','job'))

    def test_cli_unknown_request_keys_refuse_without_any_driver_exec(self):
        code,stdout,stderr=self.invoke_cli(b'{"format":"om-root-driver-v1","job_id":"job","driver_id":"root","argv":["anything"]}')
        self.assertNotEqual(code,0)
        self.assertLessEqual(len(stdout)+len(stderr),4096)
        self.assertTrue(stdout,'known config/mode refusal must return a bounded wire response')
        reply=b1._strict(stdout,4096);self.assertEqual(reply['status'],'FAIL')
        self.assertFalse((Path(self.config['roots']['drivers'])/'root').exists())


class GlobalAccountingTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)

    def test_capture_quota_is_durable_across_callers_and_stops_at_128(self):
        for value in range(1,129):self.assertEqual(capture_io._reserve_capture(self.root),value)
        with self.assertRaises(ValueError):capture_io._reserve_capture(self.root)

    def test_identity_quota_deduplicates_exact_pid_start_and_stops_at_256(self):
        for value in range(1,257):
            identity=dict(pid=value,start_ticks=1000+value)
            self.assertEqual(capture_io._reserve_identity(self.root,identity),value)
            self.assertEqual(capture_io._reserve_identity(self.root,identity),value)
        with self.assertRaises(ValueError):capture_io._reserve_identity(self.root,dict(pid=257,start_ticks=1257))

    def test_short_counter_write_poisons_job_even_when_old_counter_still_parses(self):
        reserve_raw(self.root,0)
        original=os.pwrite
        def partial(fd,raw,offset):return original(fd,raw[:1],offset)
        with patch.object(capture_io.os,'pwrite',side_effect=partial):
            with self.assertRaises(ValueError):reserve_raw(self.root,43)
        with self.assertRaisesRegex(ValueError,'job previously failed'):reserve_raw(self.root,1)


class ConcurrentBudgetTests(unittest.TestCase):
    def test_two_actual_drivers_share_root_stdout_stderr_budget(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);read_fd,write_fd=os.pipe();processes=[];identities=[]
            safety=control_fixtures.BackpressureTests();barrier=threading.Barrier(3)
            pool=ThreadPoolExecutor(max_workers=2)
            futures=[]
            try:
                for name,output in [('root',1),('fixture',2)]:
                    driver=root/name;driver.mkdir(mode=0o700)
                    body='import os;os.read('+str(read_fd)+',1);os.close('+str(read_fd)+');data=b"x"*65536;'+ '\nfor _ in range(272): os.write('+str(output)+',data)'
                    process=subprocess.Popen([sys.executable,'-B','-c',body],stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,pass_fds=(read_fd,))
                    processes.append(process);identities.append(b1._process(process.pid)[0])
                    def capture(process=process,driver=driver):
                        barrier.wait(timeout=3)
                        return capture_streams(process,root,driver,time.monotonic_ns()+5_000_000_000)
                    futures.append(pool.submit(capture))
                os.close(read_fd);read_fd=None
                barrier.wait(timeout=3)
                self.assertEqual(os.write(write_fd,b'GG'),2);os.close(write_fd);write_fd=None
                results=[future.result(timeout=28) for future in futures]
                observed=[];persisted=0;discarded=0
                for result in results:
                    size=sum(result[name]['bytes']+result[name]['observed_discarded_bytes'] for name in ('stdout','stderr'))
                    observed.append(size);self.assertLess(size,32*1024*1024)
                    persisted+=sum(result[name]['bytes'] for name in ('stdout','stderr'))
                    discarded+=sum(result[name]['observed_discarded_bytes'] for name in ('stdout','stderr'))
                    self.assertTrue(result['cleanup_complete'])
                self.assertGreater(sum(observed),32*1024*1024)
                self.assertTrue(any(result['overflow'] for result in results))
                counter=(root/'raw-reserved').read_bytes()
                self.assertEqual(len(counter),8)
                self.assertEqual(int.from_bytes(counter,'big'),persisted)
                self.assertLessEqual(persisted,32*1024*1024)
                self.assertGreater(discarded,0)
                self.assertGreater(results[0]['stdout']['bytes'],0)
                self.assertGreater(results[1]['stderr']['bytes'],0)
                print('CONCURRENT_RAW '+json.dumps(dict(identities=identities,observed=observed,persisted=persisted,
                    discarded=discarded,terminals=[dict(exit_code=r['exit_code'],signal=r['signal'],overflow=r['overflow'],cleanup_complete=r['cleanup_complete']) for r in results]),sort_keys=True),flush=True)
            finally:
                for fd in (read_fd,write_fd):
                    if fd is not None:os.close(fd)
                for process,identity in zip(processes,identities):
                    if process.poll() is None:safety.terminate_identity(identity,(os.getpid(),))
                    process.wait(timeout=5)
                pool.shutdown(wait=True,cancel_futures=True)
                for process in processes:
                    process.stdout.close();process.stderr.close()
                for identity in identities:
                    try:current,_=b1._process(identity['pid'])
                    except FileNotFoundError:continue
                    self.assertNotEqual(current,identity,'owned concurrent driver survived')


class ControlBoundaryTests(unittest.TestCase):
    def test_regular_file_request_is_read_with_the_same_bounded_framing(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(b'{"job_id":"job"}');stream.seek(0)
            try:raw=engine._read_pipe(stream.fileno(),4096,time.monotonic_ns()+1_000_000_000)
            except PermissionError:raw=None
            self.assertEqual(raw,b'{"job_id":"job"}')
            stream.seek(0)
            with self.assertRaises(ValueError):engine._read_pipe(stream.fileno(),4,time.monotonic_ns()+1_000_000_000)

    def test_oversized_wire_receipt_refuses_without_truncating_or_claiming_pass(self):
        # Pure response metadata boundary, not authentication of a retained file.
        path='/'+'/'.join(['p'*230]*17)
        pin=dict(path=path,bytes=0,sha256=hashlib.sha256(b'').hexdigest(),mode=0o600)
        response=engine._response({'job_id':'job'},'driver','root',pin)
        raw,bounded=engine._bounded_reply(response)
        self.assertLessEqual(len(raw),4096)
        self.assertEqual(b1._strict(raw,4096),bounded)
        self.assertEqual(bounded['status'],'FAIL')
        self.assertIsNone(bounded['receipt'])


class LockDeadlineTests(unittest.TestCase):
    def test_real_contended_lock_refuses_before_holder_releases(self):
        import fcntl,threading
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'lock'
            first=os.open(path,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
            second=os.open(path,os.O_RDWR);entered=threading.Event();done=threading.Event();outcome=[]
            fcntl.flock(first,fcntl.LOCK_EX)
            def contender():
                entered.set()
                try:capture_io._lock(second,time.monotonic_ns()+50_000_000);outcome.append('admitted')
                except ValueError:outcome.append('refused')
                finally:done.set()
            worker=threading.Thread(target=contender);worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(done.wait(2),'lock wait outlived deadline while owner still held it')
                self.assertEqual(outcome,['refused'])
            finally:
                fcntl.flock(first,fcntl.LOCK_UN);worker.join(2)
                os.close(second);os.close(first)
                self.assertFalse(worker.is_alive())


class AllFixtureTests(unittest.TestCase):
    setUp=FixtureTests.setUp

    def prepare_complete_job(self,ancillary_headers=0):
        trace_bytes=(b'HASH[moduleIndex]\n'*ancillary_headers+
            b'HASH[build example/p]\nHASH[build example/p]: "go1.27.2"\n'
            b'HASH[build example/p]: "compile\\n"\n'
            b'HASH[build example/p]: 64c7ffabfb3369adbfd0af27af9feb9b13d352be3e36b8fc19762c1d95771daf\n')
        scripts=str(Path(engine.__file__).parent)
        bootstrap=('import os,sys\nsys.path.insert(0,'+repr(scripts)+')\n'
            'from pathlib import Path\nimport build_tool_events as b1,build_supervision as engine\n'
            'ctx=b1._resolve_context(os.environ["OM_GO_SUPERVISION_CONTEXT"],os.environ["OM_GO_SUPERVISION_CONTEXT_SHA256"])\n'
            'identity=ctx["_start"]["go_identity"];actual_image=b1._process_image\n'
            'def toy_image(pid):\n'
            ' if pid==identity["pid"]:\n'
            '  assert b1._process(pid)[0]==identity\n'
            '  assert actual_image(pid)==str(Path(sys.executable).resolve())\n'
            '  return ctx["_config"]["sdk_go"]["path"]\n'
            ' return actual_image(pid)\n'
            'b1._process_image=toy_image\n'
            'raise SystemExit(engine.main(["--config",sys.argv[1],"--config-sha256",sys.argv[2],sys.argv[3]]))\n')
        # Image-only metadata translation exists solely in this owned test CLI.
        # Actual PID/start/PPID/ancestry and every control Pin remain real.
        body=('#!'+sys.executable+' -B\nimport os,sys,json,subprocess\nsys.path.insert(0,'+repr(scripts)+')\n'
            'import build_tool_events as b1\n'
            'raw='+repr(trace_bytes)+'\nbootstrap='+repr(bootstrap)+'\n'
            'if sys.argv[1:]==["root"]:\n'
            ' ctx=b1._resolve_context(os.environ["OM_GO_SUPERVISION_CONTEXT"],os.environ["OM_GO_SUPERVISION_CONTEXT_SHA256"])\n'
            ' pin=ctx["config"];driver=None\n'
            ' for mode in ("freeze","run","post"):\n'
            '  req=dict(format="om-fixture-"+mode+"-v1",job_id="job")\n'
            '  if mode=="freeze":req.update(test_name="TestToy",root='+repr(str(self.root))+',generated_paths=["models.go"])\n'
            '  else:req["driver_id"]=driver\n'
            '  cp=subprocess.run([sys.executable,"-B","-c",bootstrap,pin["path"],pin["sha256"],mode],input=b1.v1._encoded(req),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12)\n'
            '  if cp.returncode:sys.stderr.buffer.write(cp.stdout+cp.stderr);raise SystemExit(23)\n'
            '  driver=json.loads(cp.stdout)["driver_id"]\n'
            'else:\n assert sys.argv[1:]==["test","./...","-count=1"]\n'
            'sys.stderr.buffer.write(raw)\n')
        path=self.controls.base/'owned-complete-python-sdk'
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o700)
        with os.fdopen(fd,'w') as f:f.write(body)
        self.config['sdk_go']=self.controls.pin(path)
        self.config['root_driver']['argv']=['root']
        plan=dict(format='om-build-coverage-v1',driver_id='root',argv=['root'],required_packages=['example/p'],
            action_descriptions=[dict(description='example/p',import_path='example/p')],zero_build_diagnostic=False)
        self.config['coverage'][1]['plan']=self.controls.write('b3-complete-root-plan',plan)
        self.config['_pin']=self.controls.write('b3-complete-config',self.config)

    def run_job(self):
        return engine.handle_request(self.config,'driver',b1.v1._encoded(dict(format='om-root-driver-v1',job_id='job',driver_id='root')))

    def test_complete_root_nested_fixture_tree_and_final_shared_reconciliation(self):
        self.prepare_complete_job()
        before=len(os.listdir('/proc/self/fd'))
        reply=self.run_job();self.assertEqual(reply['status'],'PASS')
        result=json.loads(b1._pin_bytes(reply['receipt'],16*1024*1024,control=True))
        self.assertEqual([row['driver_id'] for row in result['coverage_results']],['fix','root'])
        self.assertEqual([row['build_blocks'] for row in result['coverage_results']],[1,1])
        self.assertEqual([row['coverage_sha256'] for row in result['coverage_results']],[row['plan']['sha256'] for row in self.config['coverage']])
        self.assertEqual(len(os.listdir('/proc/self/fd')),before)
        print('ALL_FIXTURE '+json.dumps(dict(status=reply['status'],results=result['coverage_results'],
            raw_bytes=result['reserved_raw_bytes'],image_translation='test-only root script image to pinned script; actual Python image checked'),sort_keys=True),flush=True)

    def test_job_header_budget_is_not_reset_for_second_driver(self):
        self.prepare_complete_job(ancillary_headers=15000)
        before=len(os.listdir('/proc/self/fd'))
        reply=self.run_job();self.assertEqual(reply['status'],'FAIL')
        for identity in ('root','fix'):
            terminal=json.loads((Path(self.config['roots']['drivers'])/identity/'terminal.json').read_bytes())
            self.assertEqual(terminal['exit_code'],0)
        post=json.loads((Path(self.config['roots']['drivers'])/'fix/post.json').read_bytes())
        self.assertTrue(post['integrity_pass'] and post['run_pass'])
        self.assertEqual(len(os.listdir('/proc/self/fd')),before)


class ExportBudgetTests(unittest.TestCase):
    setUp=FixtureTests.setUp

    def test_original_source_and_all_four_output_roots_share_budget(self):
        result=engine._export_budget(self.config)
        self.assertGreater(result.get('physical_paths',0),16)
        self.assertGreater(result.get('logical_bytes',0),16)

    def test_scope_roots_are_counted_consistently_with_physical_descendants(self):
        # Independent positive filesystem census: input root/a.go plus four scopes.
        expected=2+4
        for root in self.config['roots'].values():
            for _,directories,files in os.walk(root):expected+=len(directories)+len(files)
        self.assertEqual(engine._export_budget(self.config)['physical_paths'],expected)

    def test_reviewed_exclusion_ancestors_keep_original_prefix_accounting(self):
        before=engine._export_budget(self.config)['physical_paths']
        manifest=json.loads(b1._pin_bytes(self.config['input_manifest'],16*1024*1024,control=True))
        manifest['excluded_roots']=['outputs/skip']
        self.config['input_manifest']=self.controls.write('b3-excluded-manifest',manifest)
        # One new retained control + one implied outputs ancestor; excluded leaf
        # remains outside source admission exactly as the accepted guard defines.
        self.assertEqual(engine._export_budget(self.config)['physical_paths'],before+2)

    def test_aggregate_logical_limit_is_checked_before_reading_sparse_bodies(self):
        root=self.root
        for i in range(17):
            fd=os.open(root/('sparse-'+str(i)),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:os.ftruncate(fd,16*1024*1024)
            finally:os.close(fd)
        with self.assertRaisesRegex(ValueError,'aggregate logical'):engine._export_budget(self.config)

    def test_physical_bound_counts_empty_output_directories(self):
        root=Path(self.config['roots']['drivers'])
        for i in range(30001):(root/('empty-'+str(i))).mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError,'aggregate physical'):engine._export_budget(self.config)


class AdmissionFailureTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    freeze=FixtureTests.freeze
    prepare=GateTests.prepare

    def test_actual_partial_control_write_poisons_the_job(self):
        original=os.write
        def partial(fd,raw):
            target=os.readlink('/proc/self/fd/'+str(fd))
            return original(fd,raw[:1] if target.endswith('/fix.policy.json') else raw)
        with patch.object(engine.os,'write',side_effect=partial):
            with self.assertRaises(ValueError):self.freeze()
        self.assertEqual((Path(self.config['roots']['registrations'])/'fix.policy.json').stat().st_size,1)
        self.assertTrue((Path(self.config['roots']['drivers'])/'job-failed').exists())
        driver=self.prepare()
        with self.assertRaisesRegex(ValueError,'job previously failed'):
            engine._spawn_gated(self.config,driver,self.config['input_manifest'],self.config['tool_policy'],self.driver)
        self.assertFalse((Path(self.config['roots']['registrations'])/'root.start.json').exists())

    def test_corrupt_raw_counter_refuses_before_any_sdk_exec(self):
        driver=self.prepare();job=Path(self.config['roots']['drivers'])
        reserve_raw(job,0);(job/'raw-reserved').write_bytes(b'x')
        process=None;refused=False
        try:
            try:process=engine._spawn_gated(self.config,driver,self.config['input_manifest'],self.config['tool_policy'],self.driver)
            except ValueError:refused=True
        finally:
            if process is not None:
                try:stdout,stderr=process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    identity=b1._process(process.pid)[0]
                    control_fixtures.BackpressureTests().terminate_identity(identity,(os.getpid(),))
                    stdout,stderr=process.communicate(timeout=3)
                print('CORRUPT_ACCOUNTING_ADMITTED '+json.dumps(dict(returncode=process.returncode,stdout=stdout.decode(),stderr=stderr.decode())),flush=True)
        self.assertTrue(refused,'invalid durable accounting admitted the SDK exec gate')
        self.assertFalse((Path(self.config['roots']['registrations'])/'root.start.json').exists())

    def test_exhausted_capture_quota_refuses_before_publication(self):
        driver=self.prepare();job=Path(self.config['roots']['drivers'])
        for _ in range(128):capture_io._reserve_capture(job)
        with self.assertRaises(ValueError):engine._spawn_gated(self.config,driver,self.config['input_manifest'],self.config['tool_policy'],self.driver)
        self.assertFalse((Path(self.config['roots']['registrations'])/'root.start.json').exists())


class RawShortWriteTests(unittest.TestCase):
    setUp=CaptureTests.setUp
    child=CaptureTests.child

    def test_real_partial_segment_retains_bytes_gap_loss_and_original_terminal(self):
        process=self.child("import sys;sys.stdout.buffer.write(b'abcdef')")
        identity=b1._process(process.pid)[0]
        original=os.write
        def partial(fd,raw):
            target=os.readlink('/proc/self/fd/'+str(fd))
            return original(fd,raw[:2] if target.endswith('/stdout.000001.raw') else raw)
        with patch.object(capture_io.os,'write',side_effect=partial):
            result=capture_streams(process,self.root,self.driver,time.monotonic_ns()+3_000_000_000)
        print('RAW_PARTIAL '+json.dumps(dict(identity=identity,result=result,actual_returncode=process.returncode),sort_keys=True),flush=True)
        self.assertEqual(result['stdout']['bytes'],2)
        self.assertEqual(result['stdout']['observed_discarded_bytes'],4)
        self.assertEqual((self.driver/'stdout.000001.raw').read_bytes(),b'ab')
        self.assertTrue(result['_io_error'] and result['cleanup_complete'])
        self.assertEqual(int.from_bytes((self.root/'raw-reserved').read_bytes(),'big'),6)
        self.assertEqual(result['exit_code'],process.returncode if process.returncode>=0 else None)
        self.assertEqual(result['signal'],-process.returncode if process.returncode<0 else None)
        self.assertTrue((self.root/'job-failed').exists())


class MetadataFailureRemainderTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)

    def test_fresh_counter_initialization_short_write_is_durable_failure(self):
        original=os.pwrite
        with patch.object(capture_io.os,'pwrite',side_effect=lambda fd,raw,offset:original(fd,raw[:1],offset)):
            with self.assertRaises(ValueError):reserve_raw(self.root,0)
        self.assertEqual((self.root/'raw-reserved').stat().st_size,1)
        with self.assertRaisesRegex(ValueError,'job previously failed'):reserve_raw(self.root,0)

    def test_partial_identity_append_preserves_bad_tail_and_poison(self):
        # Synthetic identity metadata, never an observed process or signal target.
        capture_io._reserve_identity(self.root,dict(pid=101,start_ticks=201))
        original=os.write
        def partial(fd,raw):
            path=os.readlink('/proc/self/fd/'+str(fd))
            return original(fd,raw[:1] if path.endswith('/identities') else raw)
        with patch.object(capture_io.os,'write',side_effect=partial):
            with self.assertRaises(ValueError):capture_io._reserve_identity(self.root,dict(pid=102,start_ticks=202))
        self.assertTrue((self.root/'identities').read_bytes().endswith(b'\n{'))
        with self.assertRaisesRegex(ValueError,'job previously failed'):capture_io._reserve_identity(self.root,dict(pid=103,start_ticks=203))


class LiveFailureRemainderTests(unittest.TestCase):
    setUp=CaptureTests.setUp
    child=CaptureTests.child

    def test_live_child_capture_quota_refusal_waits_and_closes_owned_pipes(self):
        for _ in range(128):capture_io._reserve_capture(self.root)
        before=len(os.listdir('/proc/self/fd'))
        process=self.child('import time;time.sleep(5)');identity=b1._process(process.pid)[0]
        with self.assertRaises(ValueError):capture_streams(process,self.root,self.driver,time.monotonic_ns()+1_000_000_000)
        self.assertEqual(process.returncode,-9)
        self.assertTrue(process.stdout.closed and process.stderr.closed)
        self.assertEqual(len(os.listdir('/proc/self/fd')),before)
        self.assertFalse(Path('/proc/'+str(identity['pid'])).exists())
        print('LIVE_QUOTA '+json.dumps(dict(identity=identity,returncode=process.returncode,pipes_closed=True)),flush=True)

    def test_stale_start_identity_never_signals_the_actual_owned_child(self):
        process=self.child('import time;time.sleep(5)');identity=b1._process(process.pid)[0]
        stale=dict(identity,start_ticks=identity['start_ticks']+1)
        with self.assertRaises(ValueError):capture_io._signal_owned(stale,signal.SIGKILL)
        self.assertIsNone(process.poll())
        control_fixtures.BackpressureTests().terminate_identity(identity,(os.getpid(),))
        process.wait(timeout=3)
        print('STALE_START_REFUSED '+json.dumps(dict(actual=identity,stale=stale,actual_cleanup_returncode=process.returncode)),flush=True)

    def test_incomplete_census_is_failure_then_independent_cleanup_recovers(self):
        owner=capture_io._Ownership()
        process=self.child('import time;time.sleep(5)');identity=b1._process(process.pid)[0]
        owner.bind(process);process._om_owner=owner
        try:
            with patch.object(capture_io,'_proc_snapshot',side_effect=PermissionError('forced unreadable census')):
                result=capture_streams(process,self.root,self.driver,time.monotonic_ns()+1_000_000_000)
            self.assertTrue(result['_io_error']);self.assertFalse(result['cleanup_complete'])
            self.assertEqual(process.returncode,-9)
            print('CENSUS_REFUSAL '+json.dumps(dict(identity=identity,actual_returncode=process.returncode,original_cleanup_complete=result['cleanup_complete'])),flush=True)
        finally:
            if process.poll() is None:control_fixtures.BackpressureTests().terminate_identity(identity,(os.getpid(),))
            process.wait(timeout=3)
            self.assertTrue(owner.finish(),'post-injection actual census/wait cleanup did not recover')


class GateIdentityRemainderTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    prepare=GateTests.prepare

    def test_forged_start_record_is_refused_before_ack_and_exec(self):
        driver=self.prepare();publish=engine._publish
        def forged(directory,name,value,maximum=16*1024*1024):
            if name=='root.start.json':value=dict(value,go_identity=dict(value['go_identity'],start_ticks=value['go_identity']['start_ticks']+1))
            return publish(directory,name,value,maximum)
        with patch.object(engine,'_publish',side_effect=forged):
            with self.assertRaises(ValueError):engine._spawn_gated(self.config,driver,self.config['input_manifest'],self.config['tool_policy'],self.driver)
        failed=json.loads((self.driver/'gate-failure.json').read_bytes())
        self.assertEqual(failed['stdout']['bytes'],0)
        self.assertNotEqual(failed['exit_code'],0)
        self.assertTrue(failed['cleanup_complete'])


class FinalGapRemainderTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    prepare_root_job=JobAggregationTests.prepare_root_job
    root_request=JobAggregationTests.root_request

    def test_unbacked_reservation_is_not_reconciled_from_terminal_metadata(self):
        raw=(b'HASH[build example/p]\nHASH[build example/p]: "go1.27.2"\n'
             b'HASH[build example/p]: "compile\\n"\n'
             b'HASH[build example/p]: 64c7ffabfb3369adbfd0af27af9feb9b13d352be3e36b8fc19762c1d95771daf\n')
        self.prepare_root_job(raw)
        self.assertEqual(self.root_request()['status'],'PASS')
        reserve_raw(Path(self.config['roots']['drivers']),1)
        with self.assertRaisesRegex(ValueError,'reservation/persisted gap'):engine._finalize(self.config)


class DriverMapRemainderTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    prepare_complete_job=AllFixtureTests.prepare_complete_job
    run_job=AllFixtureTests.run_job

    def test_missing_extra_and_cross_driver_coverage_pins_refuse_before_exec(self):
        variants=[]
        missing=copy.deepcopy(self.config);missing['coverage'].pop();variants.append(missing)
        extra=copy.deepcopy(self.config);extra['coverage'].append(copy.deepcopy(extra['coverage'][0]));variants.append(extra)
        crossed=copy.deepcopy(self.config);crossed['coverage'][0]['plan'],crossed['coverage'][1]['plan']=crossed['coverage'][1]['plan'],crossed['coverage'][0]['plan'];variants.append(crossed)
        for value in variants:
            with self.assertRaises(ValueError):engine.load_job(b1.v1._encoded(value))
        self.assertFalse((Path(self.config['roots']['drivers'])/'root').exists())

    def test_missing_cross_driver_context_and_post_are_not_final_success(self):
        self.prepare_complete_job();self.assertEqual(self.run_job()['status'],'PASS')
        directory=Path(self.config['roots']['registrations']);context=directory/'fix.context.json'
        saved=context.read_bytes();context.unlink()
        try:
            with self.assertRaises(FileNotFoundError) as caught:engine._finalize(self.config)
            self.assertEqual(Path(caught.exception.filename).name,context.name)
        finally:context.write_bytes(saved);context.chmod(0o600)
        context.write_bytes((directory/'root.context.json').read_bytes())
        try:
            with self.assertRaisesRegex(ValueError,'driver original config binding'):engine._read_context(self.config,'fix')
        finally:context.write_bytes(saved)
        post=directory/'fix.POST.json';saved_post=post.read_bytes();post.unlink()
        try:
            with self.assertRaises(FileNotFoundError) as caught:engine._finalize(self.config)
            self.assertEqual(Path(caught.exception.filename).name,post.name)
        finally:post.write_bytes(saved_post);post.chmod(0o600)
        root_terminal=self.controls.pin(Path(self.config['roots']['drivers'])/'root/terminal.json')
        post.write_bytes(b1.v1._encoded(dict(post=root_terminal))+b'\n')
        try:
            with self.assertRaisesRegex(ValueError,'post driver binding'):engine._finalize(self.config)
        finally:post.write_bytes(saved_post)
        contexts={identity:engine._read_context(self.config,identity) for identity in ('fix','root')}
        contexts['rogue']=contexts['root']
        with self.assertRaises(ValueError):b1.read_job_events(Path(self.config['roots']['records']),contexts)


class ParentBeforeAckTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    prepare=GateTests.prepare

    def test_parent_death_before_ack_never_executes_sdk_and_adopted_gate_is_waited(self):
        driver=self.prepare();marker=self.controls.base/'sdk-executed'
        self.config.pop('_pin')
        argv=['-B','-c','from pathlib import Path;Path('+repr(str(marker))+').write_bytes(b"EXEC")']
        self.config['root_driver']['argv']=argv
        plan=dict(format='om-build-coverage-v1',driver_id='root',argv=argv,required_packages=['example/p'],
            action_descriptions=[dict(description='example/p',import_path='example/p')],zero_build_diagnostic=False)
        self.config['coverage'][1]['plan']=self.controls.write('parent-loss-plan',plan)
        pin=self.controls.write('parent-loss-config',self.config)
        ready_read,ready_write=os.pipe();wait_read,wait_write=os.pipe()
        safety=control_fixtures.BackpressureTests();previous=safety.subreaper(1)
        baseline=safety.observer_children();worker=None
        code=('import os,sys,json\nsys.path.insert(0,'+repr(str(Path(engine.__file__).parent))+')\n'
            'from pathlib import Path\nimport build_supervision as e,build_tool_events as b1\n'
            'pin=json.loads(sys.argv[1]);cfg=e.load_job(b1._pin_bytes(pin,control=True));cfg["_pin"]=pin\n'
            'publish=e._publish\n'
            'def pause(directory,name,value,maximum=16777216):\n'
            ' result=publish(directory,name,value,maximum)\n'
            ' if name=="root.start.json":os.write(int(sys.argv[2]),b"P");os.close(int(sys.argv[2]));os.read(int(sys.argv[3]),1)\n'
            ' return result\n'
            'e._publish=pause\n'
            'e._spawn_gated(cfg,cfg["root_driver"],cfg["input_manifest"],cfg["tool_policy"],Path(cfg["roots"]["drivers"])/"root")\n')
        try:
            worker=subprocess.Popen([sys.executable,'-B','-c',code,json.dumps(pin),str(ready_write),str(wait_read)],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,pass_fds=(ready_write,wait_read))
            worker.fixture_worker_identity=b1._process(worker.pid)[0]
            worker.fixture_host_identity=None;worker.fixture_baseline=baseline
            os.close(ready_write);ready_write=None;os.close(wait_read);wait_read=None
            self.assertEqual(engine._read_pipe(ready_read,1,time.monotonic_ns()+3_000_000_000),b'P')
            safety.discover_owned_host(worker);self.assertIsNotNone(worker.fixture_host_identity)
            safety.terminate_identity(worker.fixture_worker_identity,(os.getpid(),))
            worker.communicate(timeout=3);self.assertEqual(worker.returncode,-9)
            until=time.monotonic()+3;waited=0;status=None
            while time.monotonic()<until:
                waited,status=os.waitpid(worker.fixture_host_identity['pid'],os.WNOHANG)
                if waited:break
                time.sleep(.005)
            self.assertEqual(waited,worker.fixture_host_identity['pid'])
            self.assertTrue(os.WIFEXITED(status));self.assertEqual(os.WEXITSTATUS(status),1)
            self.assertFalse(marker.exists())
            print('PARENT_BEFORE_ACK '+json.dumps(dict(worker=worker.fixture_worker_identity,
                gate=worker.fixture_host_identity,worker_returncode=worker.returncode,gate_wait_status=status,sdk_exec_marker=False),sort_keys=True),flush=True)
        finally:
            for fd in (ready_read,ready_write,wait_read,wait_write):
                if fd is not None:os.close(fd)
            if worker is not None:safety.safety_reap(worker)
            safety.subreaper(previous)


class NestedLauncherLossTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    prepare_complete_job=AllFixtureTests.prepare_complete_job
    run_job=AllFixtureTests.run_job

    def test_root_supervisor_cancels_adopts_and_waits_sdk_after_nested_launcher_death(self):
        self.prepare_complete_job()
        sdk=Path(self.config['sdk_go']['path']);body=sdk.read_text()
        body=body.replace('import os,sys,json,subprocess\n','import os,sys,json,subprocess,time,signal\n',1)
        ready=Path(self.config['roots']['drivers'])/'fix/fixture-exec-ready'
        call='  cp=subprocess.run([sys.executable,"-B","-c",bootstrap,pin["path"],pin["sha256"],mode],input=b1.v1._encoded(req),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12)\n'
        replaced=('  if mode=="run":\n'
            '   cp=subprocess.Popen([sys.executable,"-B","-c",bootstrap,pin["path"],pin["sha256"],mode],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)\n'
            '   identity=b1._process(cp.pid)[0];cp.stdin.write(b1.v1._encoded(req));cp.stdin.close();cp.stdin=None\n'
            '   until=time.monotonic()+3\n'
            '   while not os.path.exists('+repr(str(ready))+') and time.monotonic()<until:time.sleep(.005)\n'
            '   assert os.path.exists('+repr(str(ready))+')\n'
            '   fd=os.pidfd_open(cp.pid)\n'
            '   assert b1._process(cp.pid)[0]==identity\n'
            '   signal.pidfd_send_signal(fd,signal.SIGKILL);os.close(fd);cp.communicate(timeout=3)\n'
            '   time.sleep(5);raise SystemExit(33)\n'
            '  cp=subprocess.run([sys.executable,"-B","-c",bootstrap,pin["path"],pin["sha256"],mode],input=b1.v1._encoded(req),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12)\n')
        self.assertEqual(body.count(call),1);body=body.replace(call,replaced,1)
        tail='else:\n assert sys.argv[1:]==["test","./...","-count=1"]\n'
        asleep=tail+' fd=os.open('+repr(str(ready))+',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.write(fd,b"R");os.close(fd);time.sleep(5)\n'
        self.assertEqual(body.count(tail),1);body=body.replace(tail,asleep,1)
        sdk.write_text(body);self.config['sdk_go']=self.controls.pin(sdk)
        self.config.pop('_pin');self.config['_pin']=self.controls.write('nested-loss-config',self.config)
        before=len(os.listdir('/proc/self/fd'))
        reply=self.run_job();self.assertEqual(reply['status'],'FAIL')
        terminal=json.loads((Path(self.config['roots']['drivers'])/'root/terminal.json').read_bytes())
        self.assertEqual((terminal['exit_code'],terminal['signal']),(None,9))
        self.assertFalse(terminal['timed_out']);self.assertTrue(terminal['cleanup_complete'])
        start=json.loads((Path(self.config['roots']['registrations'])/'fix.start.json').read_bytes())
        self.assertFalse(Path('/proc/'+str(start['go_identity']['pid'])).exists())
        self.assertFalse((Path(self.config['roots']['drivers'])/'fix/terminal.json').exists())
        self.assertFalse((Path(self.config['roots']['registrations'])/'fix.POST.json').exists())
        self.assertEqual(len(os.listdir('/proc/self/fd')),before)
        print('NESTED_LAUNCHER_LOSS '+json.dumps(dict(root=start['parent_driver_id'],fixture=start['go_identity'],
            root_terminal=dict(identity=terminal['go_identity'],signal=terminal['signal'],cleanup_complete=terminal['cleanup_complete']),
            no_fabricated_fixture_terminal=True,fd_count_restored=True),sort_keys=True),flush=True)


class LocalTerminalSchemaTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    prepare_root_job=JobAggregationTests.prepare_root_job
    root_request=JobAggregationTests.root_request

    def completed(self):
        raw=(b'HASH[build example/p]\nHASH[build example/p]: "go1.27.2"\n'
             b'HASH[build example/p]: "compile\\n"\n'
             b'HASH[build example/p]: 64c7ffabfb3369adbfd0af27af9feb9b13d352be3e36b8fc19762c1d95771daf\n')
        self.prepare_root_job(raw);self.assertEqual(self.root_request()['status'],'PASS')
        path=Path(self.config['roots']['drivers'])/'root/terminal.json'
        terminal=json.loads(path.read_bytes())
        self.assertEqual(engine._local_terminal(self.config,'root',self.controls.pin(path)),terminal)
        return path,terminal

    def test_bool_or_float_exit_zero_cannot_be_successful_terminal_integer(self):
        path,terminal=self.completed();saved=path.read_bytes()
        try:
            for code in (False,0.0):
                path.write_bytes(b1.v1._encoded(dict(terminal,exit_code=code))+b'\n')
                with self.subTest(code=code),self.assertRaises(ValueError):engine._local_terminal(self.config,'root',self.controls.pin(path))
        finally:path.write_bytes(saved)

    def test_terminal_pin_cannot_select_an_unrelated_control_path(self):
        _,terminal=self.completed()
        copied=self.controls.write('copied-terminal',terminal)
        with self.assertRaises(ValueError):engine._local_terminal(self.config,'root',copied)


class PersistedHashBufferTests(unittest.TestCase):
    setUp=CaptureTests.setUp
    child=CaptureTests.child

    def test_persisted_raw_hash_reads_never_request_more_than_64k(self):
        process=self.child("import sys;sys.stdout.buffer.write(b'bytes')")
        original=os.read;requests=[]
        def observed(fd,count):
            target=os.readlink('/proc/self/fd/'+str(fd))
            if target.endswith('.raw'):requests.append(count)
            return original(fd,count)
        with patch.object(capture_io.os,'read',side_effect=observed):
            result=capture_streams(process,self.root,self.driver,time.monotonic_ns()+3_000_000_000)
        self.assertEqual(result['stdout']['sha256'],hashlib.sha256(b'bytes').hexdigest())
        self.assertTrue(requests)
        self.assertLessEqual(max(requests),65536)

    def test_hashing_does_not_treat_read_atime_as_content_mutation(self):
        writer=capture_io._RawWriter(self.root,self.driver,'stdout')
        writer.feed(b'bytes');writer.close()
        path=self.driver/'stdout.000001.raw';os.utime(path,ns=(1,path.stat().st_mtime_ns))
        try:result=writer.result(True,0,False)
        except ValueError:result=None
        self.assertIsNotNone(result,'read-atime changed while content/identity stayed stable')
        self.assertEqual(result['sha256'],hashlib.sha256(b'bytes').hexdigest())




class NonregularReadTests(unittest.TestCase):
    setUp=CaptureTests.setUp

    def fifo_refusal(self,kind):
        path=self.driver/('runtime.json' if kind=='runtime' else 'stdout.000001.raw')
        os.mkfifo(path,0o600)
        code=("import sys;from pathlib import Path;sys.path.insert(0,"+repr(str(Path(engine.__file__).parent))+
              ");import build_supervision as engine,build_supervision_io as bio\n"
              "path=Path(sys.argv[1])\n"
              "try:\n"
              " if sys.argv[2]=='runtime':engine._runtime_pin(path)\n"
              " else:\n"
              "  w=bio._RawWriter(path.parent.parent,path.parent,'stdout');w.paths=[path];w.result(True,0,False)\n"
              "except (ValueError,OSError):print('REFUSED',flush=True)\n"
              "else:print('ADMITTED',flush=True)\n")
        before=len(os.listdir('/proc/self/fd'))
        process=subprocess.Popen([sys.executable,'-B','-c',code,str(path),kind],
                                 stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        identity=b1._process(process.pid)[0];blocked=False
        try:
            try:stdout,stderr=process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                blocked=True;capture_io._signal_owned(identity,signal.SIGKILL)
                stdout,stderr=process.communicate(timeout=2)
        finally:
            if process.poll() is None:
                capture_io._signal_owned(identity,signal.SIGKILL);process.wait(timeout=2)
            process.stdout.close();process.stderr.close()
        self.assertEqual(len(os.listdir('/proc/self/fd')),before)
        print('FIFO_REFUSAL '+json.dumps(dict(kind=kind,identity=identity,blocked=blocked,
              returncode=process.returncode,fd_restored=True,stdout=stdout.decode(),stderr=stderr.decode())))
        self.assertFalse(blocked,'nofollow read blocked on an owned no-writer FIFO before type admission')
        self.assertEqual(process.returncode,0,stderr.decode())
        self.assertEqual(stdout,b'REFUSED\n')

    def test_runtime_fifo_is_refused_without_waiting_for_a_writer(self):
        self.fifo_refusal('runtime')

    def test_raw_result_fifo_is_refused_without_waiting_for_a_writer(self):
        self.fifo_refusal('raw')

    def test_regular_runtime_and_raw_files_keep_exact_pins(self):
        path=self.driver/'runtime.json';path.write_bytes(b'control');path.chmod(0o600)
        self.assertEqual(engine._runtime_pin(path),dict(path=str(path),bytes=7,
                         sha256=hashlib.sha256(b'control').hexdigest(),mode=0o600))
        writer=capture_io._RawWriter(self.root,self.driver,'stdout')
        try:writer.feed(b'bytes')
        finally:writer.close()
        result=writer.result(True,0,False)
        self.assertEqual(result['segments'],[dict(path=str(self.driver/'stdout.000001.raw'),bytes=5,
                         sha256=hashlib.sha256(b'bytes').hexdigest(),mode=0o600)])
        self.assertEqual(result['bytes'],5);self.assertTrue(result['eof'])




class FinalizationFailureTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    prepare=GateTests.prepare

    def run_two_streams(self,fail):
        driver=self.prepare();self.driver.rmdir()
        driver['argv'][2]+=";os.write(2,b'err')"
        plan=json.loads(b1._pin_bytes(self.config['coverage'][1]['plan'],control=True));plan['argv']=driver['argv']
        self.config['coverage'][1]['plan']=self.controls.write('fsync-plan',plan)
        self.config['_pin']=self.controls.write('fsync-config',engine._wire(self.config))
        manifest=json.loads(b1._pin_bytes(self.config['input_manifest'],16*1024*1024,control=True))
        before=len(os.listdir('/proc/self/fd'));original=os.fsync;injected=[];error=None;terminal=None
        def sync(fd):
            if fail and os.readlink('/proc/self/fd/'+str(fd)).endswith('/stdout.000001.raw') and not injected:
                injected.append(fd);raise OSError(5,'owned final stdout fsync EIO')
            return original(fd)
        try:
            with patch.object(capture_io.os,'fsync',side_effect=sync):
                try:terminal=engine.supervise_driver(self.config,driver,manifest)
                except (ValueError,OSError) as exception:error=exception
        finally:
            # Repair only fixture-owned leaked regular FDs after recording them, so RED cannot leak.
            leaked=[]
            for fdname in os.listdir('/proc/self/fd'):
                try:
                    fd=int(fdname);target=os.readlink('/proc/self/fd/'+fdname)
                    if target not in [str(self.driver/(name+'.000001.raw')) for name in ('stdout','stderr')]:continue
                    named=os.stat(target,follow_symlinks=False);opened=os.fstat(fd)
                    if (opened.st_dev,opened.st_ino)==(named.st_dev,named.st_ino):leaked.append(fd)
                except FileNotFoundError:continue
            observed=len(os.listdir('/proc/self/fd'))
            for fd in leaked:os.close(fd)
        path=self.driver/'terminal.json';terminal=json.loads(path.read_bytes()) if path.exists() else terminal
        print('FINAL_FSYNC '+json.dumps(dict(injected=bool(injected),error=str(error) if error else None,
              fd_before=before,fd_after_capture=observed,owned_leaked_fds=leaked,fd_after_repair=len(os.listdir('/proc/self/fd')),
              terminal=terminal,poison=(Path(self.config['roots']['drivers'])/'job-failed').exists())),flush=True)
        self.assertEqual(len(os.listdir('/proc/self/fd')),before)
        self.assertEqual(leaked,[],'final fsync exception skipped another owned raw FD')
        self.assertIsNotNone(terminal,'actual completed child terminal was lost at writer finalization')
        self.assertEqual((terminal['exit_code'],terminal['signal']),(0,None))
        self.assertTrue(terminal['cleanup_complete'])
        start=json.loads((Path(self.config['roots']['registrations'])/'root.start.json').read_bytes())
        self.assertEqual(terminal['go_identity'],start['go_identity'])
        expected=('EXEC '+str(start['go_identity']['pid'])+' '+str(start['go_identity']['start_ticks'])+'\n').encode()
        for name,raw in [('stdout',expected),('stderr',b'err')]:
            stream=terminal[name];self.assertEqual(stream['bytes'],len(raw));self.assertEqual(stream['sha256'],hashlib.sha256(raw).hexdigest())
            self.assertTrue(stream['eof']);self.assertFalse(stream['loss_unknown']);self.assertEqual(stream['observed_discarded_bytes'],0)
        job=Path(self.config['roots']['drivers'])
        self.assertEqual(int.from_bytes((job/'raw-reserved').read_bytes(),'big'),len(expected)+3)
        if fail:
            self.assertTrue(injected);self.assertIsInstance(error,ValueError)
            self.assertTrue((job/'job-failed').exists());self.assertTrue((self.driver/'capture-failure.json').exists())
            failure=json.loads((self.driver/'capture-failure.json').read_bytes())
            self.assertEqual(failure['finalization_errors'],[dict(resource='stdout raw',error='OSError',errno=5)])
            with self.assertRaisesRegex(ValueError,'job previously failed'):
                engine._spawn_gated(self.config,driver,self.config['input_manifest'],self.config['tool_policy'],self.driver)
            self.assertEqual(json.loads(path.read_bytes()),terminal)
        else:
            self.assertIsNone(error);self.assertFalse((job/'job-failed').exists())

    def test_stdout_final_fsync_eio_preserves_terminal_closes_stderr_and_poisons_job(self):
        self.run_two_streams(True)

    def test_successful_two_stream_finalization_keeps_exact_terminal_and_closes_every_fd(self):
        self.run_two_streams(False)




class SingleCleanupDeadlineTests(unittest.TestCase):
    setUp=FixtureTests.setUp
    prepare=GateTests.prepare

    def supervisor_failure_after_cleanup(self,elapsed):
        # Only clock and process/capture failure boundaries are simulated; no live child exists.
        driver=self.prepare();self.driver.rmdir()
        manifest=json.loads(b1._pin_bytes(self.config['input_manifest'],16*1024*1024,control=True))
        owner=capture_io._Ownership();clock=[100_000_000_000];waits=[];started=[]
        class ClockOnlyProcess:
            returncode=None
            def poll(self):return self.returncode
            def wait(self,timeout):waits.append(timeout);self.returncode=0;return 0
        process=ClockOnlyProcess()
        def expired_capture(*args):
            owner.cancel();started.append(owner.deadline)
            clock[0]+=elapsed*1_000_000_000
            raise ValueError('clock-only capture cleanup failure')
        before=len(os.listdir('/proc/self/fd'))
        try:
            with patch.object(engine.bio,'_Ownership',return_value=owner), \
                 patch.object(engine,'_spawn_gated',return_value=process), \
                 patch.object(engine.bio,'capture_streams',side_effect=expired_capture), \
                 patch.object(time,'monotonic_ns',side_effect=lambda:clock[0]):
                with self.assertRaises(ValueError):engine.supervise_driver(self.config,driver,manifest)
        finally:
            self.assertEqual(owner.libc.prctl(36,owner.previous,0,0,0),0)
        self.assertEqual(len(os.listdir('/proc/self/fd')),before)
        print('CLOCK_ONLY_CLEANUP '+json.dumps(dict(elapsed=elapsed,started=started,
              final_deadline=owner.deadline,wait_timeouts=waits,failed=owner.failed,no_child_created=True)),flush=True)
        self.assertEqual(started,[120_000_000_000])
        self.assertEqual(owner.deadline,120_000_000_000,'supervisor renewed an already-started cleanup window')
        self.assertEqual(waits,[max(0,20-elapsed)])
        if elapsed>=20:self.assertTrue(owner.failed,'expired cleanup cannot become complete')

    def test_expired_cleanup_deadline_is_not_renewed_by_supervisor(self):
        self.supervisor_failure_after_cleanup(21)

    def test_wait_uses_only_remaining_cleanup_budget(self):
        self.supervisor_failure_after_cleanup(5)


if __name__=='__main__':unittest.main()
