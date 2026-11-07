# SPDX-License-Identifier: Apache-2.0
"""Manually authored SDK-shaped bytes; no Go/host SDK is executed."""
import hashlib
from pathlib import Path
import unittest
from build_hash_trace import decode_go_quote, parse_hash_trace


def budget():
    return dict(named_hash_headers=0, build_blocks=0, active_build_blocks=0)


def block(package=b'example/p', inputs=(b'go1.27.2', b'compile\n')):
    # Independent fixture encoder for ASCII cases, not the implementation decoder.
    quoted = [b'"'+value.replace(b'\\',b'\\\\').replace(b'"',b'\\"').replace(b'\n',b'\\n')+b'"' for value in inputs]
    prefix=b'HASH[build '+package+b']'
    return prefix+b'\n'+b''.join(prefix+b': '+value+b'\n' for value in quoted)+prefix+b': '+hashlib.sha256(b''.join(inputs)).hexdigest().encode()+b'\n'


class TraceTests(unittest.TestCase):
    def test_quote_bytes_and_unicode_are_not_json(self):
        self.assertEqual(decode_go_quote(b'"\\a\\v\\xFF"',512*1024),b'\x07\x0b\xff')

    def test_hash_salt_input_end_digest_and_interleaving(self):
        counts=budget()
        result=parse_hash_trace([block()],counts)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['inputs'],[b'go1.27.2',b'compile\n'])
        self.assertEqual(result[0]['sha256'],'64c7ffabfb3369adbfd0af27af9feb9b13d352be3e36b8fc19762c1d95771daf')
        self.assertEqual(counts,dict(named_hash_headers=1,build_blocks=1,active_build_blocks=0))

    def test_malformed_truncated_overlapping_and_budget_bounds_reject(self):
        with self.assertRaises(ValueError):
            parse_hash_trace([block()[:-1]],budget())


def chunks(raw,size=65536):
    return (raw[index:index+size] for index in range(0,len(raw),size))


class ParserBoundaryTests(unittest.TestCase):
    def test_complete_quote_oracles_and_rejections(self):
        good=[(b'""',b''),(b'"\\x00"',b'\x00'),(b'"\\b\\f\\n\\r\\t"',bytes([8,12,10,13,9])),
              (b'"\\\\"',b'\\'),(b'"\\\""',b'"'),('"é"'.encode(),b'\xc3\xa9'),
              (b'"\\u00e9"',b'\xc3\xa9'),(b'"\\U0001f600"',b'\xf0\x9f\x98\x80')]
        for raw,want in good:
            with self.subTest(raw=raw):self.assertEqual(decode_go_quote(raw,512*1024),want)
        bad=[b'"\xff"',b'"a\n"',b'"\t"',b'"\\q"',b'"\\xF"',b'"\\uD800"',b'"\\U00110000"',
             b'"\\377"',b'`raw`',b'"ok"junk',b'"\\u123"',b'"\\"',b'"a""b"']
        for raw in bad:
            with self.subTest(raw=raw),self.assertRaises(ValueError):decode_go_quote(raw,512*1024)
        self.assertEqual(decode_go_quote(b'"ab"',2),b'ab')
        with self.assertRaises(ValueError):decode_go_quote(b'"ab"',1)
        with self.assertRaises(ValueError):decode_go_quote(b'""',True)

    def test_salt_and_digest_causal_mutants(self):
        for inputs in [(b'compile\n',),(b'go1.27.1',b'compile\n')]:
            # Final SHA is independently correct for the wrong/missing salt.
            with self.subTest(inputs=inputs),self.assertRaisesRegex(ValueError,'salt'):
                parse_hash_trace(chunks(block(inputs=inputs)),budget())
        raw=block()
        final=raw.rfind(b': ')+2
        changed=raw[:final]+(b'0' if raw[final:final+1]!=b'0' else b'1')+raw[final+1:]
        with self.assertRaisesRegex(ValueError,'digest mismatch'):parse_hash_trace(chunks(changed),budget())

    def test_bytewise_unicode_escapes_and_interleaved_ordinals(self):
        raw=block(inputs=(b'go1.27.2','é'.encode(),b'compile\n'))
        self.assertEqual(parse_hash_trace(chunks(raw,1),budget()),parse_hash_trace(chunks(raw),budget()))
        a=block(b'example/a').splitlines(keepends=True);b=block(b'example/b').splitlines(keepends=True)
        interleaved=a[0]+b[0]+a[1]+b[1]+b[2]+b[3]+a[2]+a[3]
        parsed=parse_hash_trace(chunks(interleaved),budget())
        self.assertEqual([row['package'] for row in parsed],['example/b','example/a'])
        repeated=parse_hash_trace(chunks(block()+block()),budget())
        self.assertEqual([row['ordinal'] for row in repeated],[1,2])
        with self.assertRaisesRegex(ValueError,'overlapping'):
            parse_hash_trace(chunks(a[0]+a[0]),budget())

    def test_unknown_malformed_and_missing_lifecycles(self):
        raw=block();lines=raw.splitlines(keepends=True)
        bad=[b'HASH[unknown]\n',b'HASH[build example/p]oops\n',b'HASH[build example/p\n',
             b''.join(lines[1:]),b''.join(lines[:-1]),lines[0]+lines[-1],raw+lines[1],
             raw[:-1],raw[:-1]+b' trailing\n',b'HASH subkey bad "x" = bad\n']
        for value in bad:
            with self.subTest(value=value[:80]),self.assertRaises(ValueError):parse_hash_trace(chunks(value),budget())

    def test_ancillary_moduleindex_interleaving_and_gcc_double_sum(self):
        salt=b'go1.27.2'
        first=hashlib.sha256(salt).hexdigest().encode()
        second=hashlib.sha256(salt+b'more\n').hexdigest().encode()
        ancillary=(b'HASH[moduleIndex]\nHASH[moduleIndex]: "go1.27.2"\n'*2+
            b'HASH[gccCompilerID]\nHASH[gccCompilerID]: "go1.27.2"\nHASH[gccCompilerID]: '+first+b'\n'+
            b'HASH[gccCompilerID]: "more\\n"\nHASH[gccCompilerID]: '+second+b'\n')
        counts=budget();rows=parse_hash_trace(chunks(ancillary+block()),counts)
        self.assertEqual(counts,dict(named_hash_headers=4,build_blocks=1,active_build_blocks=0))
        self.assertEqual(sum(row['kind']=='build' for row in rows),1)
        self.assertTrue(all('ordinal' not in row for row in rows if row['kind']=='ancillary'))
        names=[b'covermeta',b'testResult',b'testInputs',b'getenv',b'open',b'stat',b'linkShared',b'testmain',
               b'vet example/p',b'link example/p',b'preprocess PGO profile /tmp/profile']
        for name in names:
            self.assertEqual(parse_hash_trace([b'HASH['+name+b']\n'],budget())[0]['kind'],'ancillary')

    def test_shared_named_header_exact30000_and30001(self):
        counts=budget()
        parse_hash_trace(chunks(b'HASH[moduleIndex]\n'*30000),counts)
        self.assertEqual(counts['named_hash_headers'],30000)
        with self.assertRaisesRegex(ValueError,'header budget'):
            parse_hash_trace([b'HASH[moduleIndex]\n'],counts)
        self.assertEqual(counts['named_hash_headers'],30000)
        shared=budget()
        parse_hash_trace(chunks(b'HASH[moduleIndex]\n'*20000),shared)
        parse_hash_trace(chunks(b'HASH[gccCompilerID]\n'*9999+block()),shared)
        self.assertEqual(shared,dict(named_hash_headers=30000,build_blocks=1,active_build_blocks=0))
        with self.assertRaisesRegex(ValueError,'header budget'):parse_hash_trace([b'HASH[build extra]\n'],shared)

    def test_active_build_exact256_and257(self):
        salt_sha=hashlib.sha256(b'go1.27.2').hexdigest().encode()
        starts=b''.join(b'HASH[build p'+str(i).encode()+b']\n' for i in range(256))
        inputs=b''.join(b'HASH[build p'+str(i).encode()+b']: "go1.27.2"\n' for i in range(256))
        ends=b''.join(b'HASH[build p'+str(i).encode()+b']: '+salt_sha+b'\n' for i in range(256))
        counts=budget();self.assertEqual(len(parse_hash_trace(chunks(starts+inputs+ends),counts)),256)
        self.assertEqual(counts['active_build_blocks'],0)
        failed=budget()
        with self.assertRaisesRegex(ValueError,'active build budget'):
            parse_hash_trace(chunks(starts+b'HASH[build extra]\n'),failed)
        self.assertEqual(failed['active_build_blocks'],256)
        with self.assertRaisesRegex(ValueError,'prior failed'):parse_hash_trace(chunks(block()),failed)

    def test_line_decoded_raw_and_chunk_bounds(self):
        decoded=512*1024
        parse_hash_trace(chunks(b'HASH[open]\nHASH[open]: "'+b'a'*decoded+b'"\n'),budget())
        with self.assertRaisesRegex(ValueError,'decoded'):
            parse_hash_trace(chunks(b'HASH[open]\nHASH[open]: "'+b'a'*(decoded+1)+b'"\n'),budget())
        prefix=b'HASH[open]: "';room=1024*1024-len(prefix)-2
        body=b'\\x41'*(room//4)+b'a'*(room%4)
        self.assertEqual(len(prefix+body+b'"\n'),1024*1024)
        parse_hash_trace(chunks(prefix+body+b'"\n'),budget())
        with self.assertRaisesRegex(ValueError,'line bound'):
            parse_hash_trace(chunks(prefix+body+b'a"\n'),budget())
        with self.assertRaisesRegex(ValueError,'chunk'):parse_hash_trace([b'x'*65537],budget())
        self.assertEqual(parse_hash_trace((b'x'*65536 for _ in range(512)),budget()),[])
        with self.assertRaisesRegex(ValueError,'raw stderr'):
            parse_hash_trace((b'x'*65536 for _ in range(513)),budget())


# Semantic fixtures explicitly stand at B3's authenticated control/raw boundary.
# These are data identities/pins, not observed Go processes or retained files.
import copy
from unittest.mock import patch
import build_tool_events as b1
from build_hash_trace import reconcile_driver


def fake_pin(path,digest='1'*64,size=1,mode=0o600):
    return dict(path=path,bytes=size,sha256=digest,mode=mode)


def semantic_fixture(argv=None,diagnostic=False):
    argv=argv or ['test','./...','-v']
    manifest=fake_pin('/fixture/manifest.json','4'*64)
    policy_pin=fake_pin('/fixture/policy.json','5'*64)
    sdk=fake_pin('/fixture/sdk/pkg/tool/linux_amd64/compile',mode=0o755)
    host=fake_pin('/usr/bin/x86_64-linux-gnu-gcc-14','2'*64,mode=0o755)|dict(uid=0,gid=0)
    plan_pin=fake_pin('/fixture/coverage.json','3'*64)
    policy=dict(tools=[sdk],host_id_probes=[dict(role='CC',language='c',tool=host)],
                working_directory='/fixture/source',toolchain_root='/fixture/sdk')
    config=dict(job_id='job',module_root='/fixture/source',input_manifest=manifest,
                root_driver=dict(driver_id='root',argv=argv),fixture_slots=[],
                coverage=[dict(driver_id='root',plan=plan_pin)],
                environment=dict(GOMODCACHE='/fixture/cache',GOTMPDIR='/fixture/tmp',TMPDIR='/fixture/tmp'))
    start=dict(format='om-go-driver-start-v1',job_id='job',driver_id='root',parent_driver_id=None,
               go_identity=dict(pid=101,start_ticks=201),manifest=manifest,sdk_go=fake_pin('/fixture/sdk/bin/go'))
    context=dict(format='om-go-context-v1',job_id='job',driver_id='root',config=fake_pin('/fixture/config.json'),
                 start=fake_pin('/fixture/start.json'),policy=policy_pin,_path='/fixture/context.json',
                 _sha256='6'*64,_config=config,_start=start,_policy=policy)
    coverage=dict(format='om-build-coverage-v1',driver_id='root',argv=argv,
                  required_packages=[] if diagnostic else ['example/p'],
                  action_descriptions=[] if diagnostic else [dict(description='example/p',import_path='example/p')],
                  zero_build_diagnostic=diagnostic)
    return context,coverage


def terminal_for(context,stderr=b'',stdout=b''):
    def stream(raw,name):
        digest=hashlib.sha256(raw).hexdigest()
        segments=[fake_pin('/fixture/raw/'+name+'.000001.raw',digest,len(raw))] if raw else []
        return dict(segments=segments,bytes=len(raw),sha256=digest,eof=True,observed_discarded_bytes=0,loss_unknown=False)
    return dict(format='om-driver-terminal-v1',job_id=context['job_id'],driver_id=context['driver_id'],
                go_identity=context['_start']['go_identity'],manifest=context['_start']['manifest'],
                exit_code=0,signal=None,timed_out=False,overflow=False,stdout=stream(stdout,'stdout'),
                stderr=stream(stderr,'stderr'),cleanup_complete=True)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.context,self.coverage=semantic_fixture()

    def invoke(self,raw=None,events=None,context=None,coverage=None,terminal=None):
        context=self.context if context is None else context
        raw=block() if raw is None else raw
        # Only resolver/authentication is injected, explicitly representing B3.
        with patch.object(b1,'_resolved',side_effect=lambda supplied,live:copy.deepcopy(context)):
            return reconcile_driver(context,terminal_for(context,raw) if terminal is None else terminal,[] if events is None else events,
                                    parse_hash_trace(chunks(raw),budget()),self.coverage if coverage is None else coverage)

    def test_test_description_mapping_and_shared_job_block_budget(self):
        self.assertEqual(self.invoke(),dict(format='om-build-coverage-result-v1',job_id='job',driver_id='root',
            coverage_sha256='3'*64,build_blocks=1,covered_packages=['example/p'],host_completions=0,**{'pass':True}))


    def host_rows(self,context=None,identity=b'gcc version 14.2.0 (toy)',seq=1):
        context=self.context if context is None else context
        host=context['_policy']['host_id_probes'][0]
        def envelope(number,kind,data):
            return dict(format='om-go-tool-event-v2',seq=number,kind=kind,job_id=context['job_id'],
                driver_id=context['driver_id'],parent_go=context['_start']['go_identity'],
                recorder=dict(pid=102,start_ticks=202),policy_sha256=context['policy']['sha256'],data=data)
        start=envelope(seq,'host-start',dict(**host,argv=[host['tool']['path'],'-###','-x',host['language'],'-c','-'],
                                           importpath='',cwd=context['_policy']['working_directory']))
        complete=envelope(seq+1,'host-complete',dict(start_seq=seq,child=dict(pid=103,start_ticks=203),
            terminal=dict(exit_code=0,signal=None),elapsed_ns=1000,
            stdout=b1._make_blob(b'',eof=True,lost_bytes=0),stderr=b1._make_blob(identity+b'\n',eof=True,lost_bytes=0),
            release_id=b1._make_blob(identity),outcome='ok'))
        return [start,complete]

    def host_trace(self,error=None):
        config=b'CC=["/usr/bin/x86_64-linux-gnu-gcc-14"] [] [] []\n'
        identity=b'CC ID="gcc version 14.2.0 (toy)"\n' if error is None else b'CC ID ERROR='+error+b'\n'
        return block(inputs=(b'go1.27.2',b'compile\n',config,identity))

    def sdk_event(self,description='example/p',seq=7):
        tool=self.context['_policy']['tools'][0]
        data=dict(format='om-go-tool-record-v1',policy_sha256=self.context['policy']['sha256'],pid=102,start_ticks=202,
            argv=[tool['path'],'-c=1'],importpath=description,tool=tool,classification='external-compile',compiler_c='1',
            cwd=self.context['_policy']['working_directory'])
        return dict(format='om-go-tool-event-v2',seq=seq,kind='sdk',job_id='job',driver_id='root',
                    parent_go=self.context['_start']['go_identity'],recorder=dict(pid=102,start_ticks=202),
                    policy_sha256=self.context['policy']['sha256'],data=data)

    def version_probe(self,description,seq=8):
        event=self.sdk_event(description=description,seq=seq)
        data=event['data']
        data.update(argv=[data['tool']['path'],'-V=full'],classification='version-probe',compiler_c=None)
        return event

    def test_unknown_nonempty_version_probe_description_rejects(self):
        compile_event=self.sdk_event()
        self.assertTrue(self.invoke(events=[compile_event])['pass'])
        probe=self.version_probe('example/unreleased [example/unreleased.test]')
        with self.assertRaisesRegex(ValueError,'unknown SDK action description'):
            self.invoke(events=[compile_event,probe])

    def test_empty_and_released_version_probe_descriptions_remain_valid(self):
        bracketed='example/p [example/p.test]'
        self.coverage['action_descriptions'].append(dict(description=bracketed,import_path='example/p'))
        for description in ['', 'example/p', bracketed]:
            with self.subTest(description=description):
                result=self.invoke(events=[self.sdk_event(),self.version_probe(description)])
                self.assertEqual(result['covered_packages'],['example/p'])
                self.assertEqual(result['build_blocks'],1)

    def test_known_version_probe_never_supplies_build_or_compilation_coverage(self):
        probe=self.version_probe('example/p')
        with self.assertRaisesRegex(ValueError,'missing complete build trace'):
            self.invoke(raw=b'',events=[probe])
        self.coverage['action_descriptions'].append(dict(description='example/q',import_path='example/q'))
        with self.assertRaisesRegex(ValueError,'missing required package coverage'):
            self.invoke(raw=block(package=b'example/q'),events=[probe])
        # A probe for a different released package is not a compile action:
        # it neither creates coverage nor requires an associated build block.
        self.coverage['required_packages']=['example/q']
        result=self.invoke(raw=block(package=b'example/q'),events=[probe])
        self.assertEqual(result['covered_packages'],['example/q'])

    def test_failure_before_journal_registration_is_seen_in_trace(self):
        for error in [b'"refused"',b'"line\\n\\"quoted\\""']:
            with self.subTest(error=error),self.assertRaisesRegex(ValueError,'CC ID ERROR'):
                self.invoke(raw=self.host_trace(error),events=[])
        cxx=copy.deepcopy(self.context['_policy']['host_id_probes'][0])
        cxx.update(role='CXX',language='c++');cxx['tool']['path']='/usr/bin/x86_64-linux-gnu-g++-14'
        self.context['_policy']['host_id_probes'].append(cxx)
        raw=block(inputs=(b'go1.27.2',b'CXX=["/usr/bin/x86_64-linux-gnu-g++-14"] []\n',b'CXX ID ERROR="refused"\n'))
        with self.assertRaisesRegex(ValueError,'CXX ID ERROR'):self.invoke(raw=raw,events=[])

    def test_sdk_shaped_swallowed_error_rejects_even_parent_exit_zero(self):
        import subprocess,sys
        raw=self.host_trace(b'"refused"')
        code='import subprocess,sys;r=subprocess.run(['+repr(sys.executable)+',"-B","-c","raise SystemExit(7)"],capture_output=True,timeout=3);sys.stdout.write("TOY swallowed child="+str(r.returncode));sys.stderr.buffer.write('+repr(raw)+');raise SystemExit(0)'
        parent=subprocess.Popen([sys.executable,'-B','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            actual_identity=b1._process(parent.pid)[0]
            stdout,stderr=parent.communicate(timeout=5)
            self.assertEqual(parent.returncode,0)
            self.assertEqual(stdout,b'TOY swallowed child=7')
            self.context['_start']['go_identity']=actual_identity
            terminal=terminal_for(self.context,stderr,stdout)
            with self.assertRaisesRegex(ValueError,'CC ID ERROR'):
                self.invoke(raw=stderr,terminal=terminal,events=[])
        finally:
            if parent.poll() is None:parent.kill()
            parent.communicate(timeout=3)

    def test_cached_id_reuse_is_same_driver_only(self):
        raw=self.host_trace()
        self.assertEqual(hashlib.sha256(b'go1.27.2compile\nCC=["/usr/bin/x86_64-linux-gnu-gcc-14"] [] [] []\nCC ID="gcc version 14.2.0 (toy)"\n').hexdigest(),
                         '3ad9d79433cd266958fa36c42169624b704410b9fce2d156ae7ac917fa2380fe')
        rows=self.host_rows()
        result=self.invoke(raw=raw+raw,events=rows)
        self.assertEqual(result['build_blocks'],2);self.assertEqual(result['host_completions'],1)
        for key,value in [('driver_id','other'),('policy_sha256','0'*64),('parent_go',dict(pid=999,start_ticks=999))]:
            foreign=copy.deepcopy(rows)
            for row in foreign:row[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.invoke(raw=raw,events=foreign)
        with self.assertRaisesRegex(ValueError,'matching host identity'):
            self.invoke(raw=raw,events=self.host_rows(identity=b'gcc version 99 (toy)'))
        with self.assertRaisesRegex(ValueError,'unmatched host start'):self.invoke(events=rows[:1])
        repeated=self.host_rows(seq=4)
        repeated[-1]['data'].update(outcome='exit_nonzero',terminal=dict(exit_code=1,signal=None),release_id=None)
        with self.assertRaisesRegex(ValueError,'failed host completion'):self.invoke(raw=raw,events=rows+repeated)
        wrong=copy.deepcopy(rows);wrong[0]['data']['language']='c++'
        with self.assertRaises(ValueError):self.invoke(raw=raw,events=wrong)
        wrong=copy.deepcopy(rows);wrong[0]['data']['tool']['sha256']='0'*64
        with self.assertRaises(ValueError):self.invoke(raw=raw,events=wrong)
        incomplete=block(inputs=(b'go1.27.2',b'CC=["/usr/bin/x86_64-linux-gnu-gcc-14"] [] [] []\n'))
        with self.assertRaisesRegex(ValueError,'missing ID'):self.invoke(raw=incomplete,events=rows)
        malformed=block(inputs=(b'go1.27.2',b'CC=["/usr/bin/x86_64-linux-gnu-gcc-14" "-flag"] [] [] []\n'))
        with self.assertRaisesRegex(ValueError,'single pinned'):self.invoke(raw=malformed,events=rows)

    def test_zero_build_requires_explicit_nonsemantic_coverage(self):
        with self.assertRaisesRegex(ValueError,'missing complete build trace'):self.invoke(raw=b'')
        context,coverage=semantic_fixture(argv=['version'],diagnostic=True)
        result=self.invoke(raw=b'',context=context,coverage=coverage)
        self.assertEqual(result['covered_packages'],[]);self.assertEqual(result['build_blocks'],0)
        coverage['argv']=['test','./...']
        with self.assertRaisesRegex(ValueError,'registered coverage argv'):self.invoke(raw=b'',context=context,coverage=coverage)
        coverage['argv']=['version']
        with self.assertRaisesRegex(ValueError,'diagnostic has semantic'):
            self.invoke(raw=b'',context=context,coverage=coverage,events=self.host_rows(context=context))
        with self.assertRaisesRegex(ValueError,'missing complete build trace'):
            self.invoke(raw=b'HASH[gccCompilerID]\n',events=self.host_rows())

    def test_terminal_stream_shapes_identity_loss_and_package_gates(self):
        base=terminal_for(self.context,block())
        changes=[('exit_code',1),('exit_code',False),('timed_out',True),('overflow',True),('cleanup_complete',False),
                 ('go_identity',dict(pid=999,start_ticks=999)),('manifest',fake_pin('/wrong','4'*64))]
        for key,value in changes:
            terminal=copy.deepcopy(base);terminal[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.invoke(terminal=terminal)
        for key,value in [('eof',False),('loss_unknown',True),('observed_discarded_bytes',1),('sha256','invalid'),('bytes',32*1024*1024+1)]:
            terminal=copy.deepcopy(base);terminal['stderr'][key]=value
            with self.subTest(stream=key),self.assertRaises(ValueError):self.invoke(terminal=terminal)
        terminal=copy.deepcopy(base);terminal['stderr']['segments'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'segment SHA'):self.invoke(terminal=terminal)
        coverage=copy.deepcopy(self.coverage);coverage['extra']=True
        with self.assertRaisesRegex(ValueError,'coverage plan keys'):self.invoke(coverage=coverage)
        coverage=copy.deepcopy(self.coverage);coverage['driver_id']='other'
        with self.assertRaisesRegex(ValueError,'coverage driver'):self.invoke(coverage=coverage)
        coverage=copy.deepcopy(self.coverage);coverage['required_packages']=['example/missing']
        coverage['action_descriptions'].append(dict(description='example/missing',import_path='example/missing'))
        coverage['action_descriptions'].sort(key=lambda row:row['description'])
        with self.assertRaisesRegex(ValueError,'missing required package'):self.invoke(coverage=coverage)

    def test_released_test_description_mapping_and_filtered_gaps(self):
        description='example/p [example/p.test]'
        event=self.sdk_event(description=description,seq=19)
        self.coverage['action_descriptions'].append(dict(description=description,import_path='example/p'))
        self.assertTrue(self.invoke(events=[event])['pass'])
        missing=copy.deepcopy(self.coverage);missing['action_descriptions']=missing['action_descriptions'][:1]
        with self.assertRaisesRegex(ValueError,'unknown SDK action description'):self.invoke(events=[event],coverage=missing)
        wrong=copy.deepcopy(self.coverage);wrong['action_descriptions'][-1]['import_path']='example/wrong'
        with self.assertRaisesRegex(ValueError,'lacks build trace'):self.invoke(events=[event],coverage=wrong)


class RealControlTests(unittest.TestCase):
    def test_nonlive_authenticator_uses_real_controls_and_rebuilds_private_values(self):
        import test_build_tool_events as fixtures
        import subprocess,sys
        fixture=fixtures.EventTests();fixture.setUp()
        self.addCleanup(lambda:self.assertTrue(fixture.doCleanups()))
        child=subprocess.Popen([sys.executable,'-B','-c','pass'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            fixture.controls(hosts=False,parent_pid=child.pid)
            child.communicate(timeout=3)
            self.assertEqual(child.returncode,0)
        finally:
            if child.poll() is None:child.kill()
            child.communicate(timeout=3)
        _,coverage=semantic_fixture()
        plan=fixture.write('b2-real-coverage',coverage)
        config=copy.deepcopy(fixture.config);config['root_driver']['argv']=coverage['argv']
        config['coverage']=[dict(driver_id='root',plan=plan)]
        config_pin=fixture.write('b2-real-config',config)
        wire={key:fixture.context[key] for key in b1.CONTEXT_KEYS};wire['config']=config_pin
        context_pin=fixture.write('b2-real-context',wire)
        locator=wire|dict(_path=context_pin['path'],_sha256=context_pin['sha256'])
        resolved=b1._resolved(locator,False)
        raw=block();terminal=terminal_for(resolved,raw)
        result=reconcile_driver(locator,terminal,[],parse_hash_trace(chunks(raw),budget()),coverage)
        self.assertEqual(result['coverage_sha256'],plan['sha256'])
        poisoned=resolved|dict(_config={'untrusted':True},_start={'untrusted':True},_policy={'untrusted':True})
        self.assertEqual(reconcile_driver(poisoned,terminal,[],parse_hash_trace(chunks(raw),budget()),coverage),result)
        for key,value in [('_sha256','0'*64),('job_id','wrong')]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                reconcile_driver(dict(locator,**{key:value}),terminal,[],parse_hash_trace(chunks(raw),budget()),coverage)
        path=Path(config_pin['path']);saved=path.read_bytes()
        path.write_bytes(bytes([saved[0]^1])+saved[1:])
        with self.assertRaisesRegex(ValueError,'pin SHA'):
            reconcile_driver(locator,terminal,[],parse_hash_trace(chunks(raw),budget()),coverage)


class SourceDiagnosticTests(unittest.TestCase):
    def test_filehash_and_subkey_are_diagnostics_not_build_coverage(self):
        parent=bytes.fromhex('11'*32);description=b'stdout'
        digest=hashlib.sha256(b'subkey:'+parent+description).hexdigest().encode()
        filehash=b'HASH /fixture/a.go: open /fixture/a.go: permission denied\n'
        subkey=b'HASH subkey '+parent.hex().encode()+b' "stdout" = '+digest+b'\n'
        counts=budget();rows=parse_hash_trace(chunks(filehash+subkey+block()),counts)
        self.assertEqual(rows[0],dict(kind='filehash',line=filehash[:-1]))
        self.assertEqual(rows[1]['kind'],'subkey');self.assertEqual(rows[1]['description'],description)
        self.assertEqual(rows[1]['sha256'],digest.decode())
        self.assertEqual(counts,dict(named_hash_headers=1,build_blocks=1,active_build_blocks=0))
        context,coverage=semantic_fixture()
        raw=filehash+subkey
        with patch.object(b1,'_resolved',return_value=context),self.assertRaisesRegex(ValueError,'missing complete build trace'):
            reconcile_driver(context,terminal_for(context,raw),[],parse_hash_trace(chunks(raw),budget()),coverage)


class StreamShapeTests(unittest.TestCase):
    def test_ordered_short_and_empty_segments_do_not_invent_eight_cap(self):
        case=ReconciliationTests();case.setUp()
        raw=block();terminal=terminal_for(case.context,raw)
        pieces=[b'']+[raw[i:i+1] for i in range(9)]+[raw[9:]]
        terminal['stderr']['segments']=[fake_pin('/fixture/raw/stderr.'+f'{i:06d}'+'.raw',hashlib.sha256(piece).hexdigest(),len(piece)) for i,piece in enumerate(pieces,1)]
        self.assertTrue(case.invoke(raw=raw,terminal=terminal)['pass'])
        terminal['stderr']['segments'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'empty segment SHA'):case.invoke(raw=raw,terminal=terminal)

    def test_empty_stream_may_have_ordered_empty_pins(self):
        case=ReconciliationTests();case.setUp()
        context,coverage=semantic_fixture(argv=['version'],diagnostic=True)
        terminal=terminal_for(context)
        terminal['stderr']['segments']=[fake_pin('/fixture/raw/stderr.'+f'{i:06d}'+'.raw',hashlib.sha256(b'').hexdigest(),0) for i in range(1,4)]
        self.assertTrue(case.invoke(raw=b'',context=context,coverage=coverage,terminal=terminal)['pass'])
        terminal['stderr']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'empty stream SHA'):case.invoke(raw=b'',context=context,coverage=coverage,terminal=terminal)
