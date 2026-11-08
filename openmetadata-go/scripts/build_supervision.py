# SPDX-License-Identifier: Apache-2.0
"""Released build/fixture supervision; external controller owns acceptance."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import selectors
import stat
import subprocess
import sys
import time
import build_tool_events as b1
import build_hash_trace as trace
import partitioned_source_guard as source
import build_supervision_io as bio

SUPPORT=sorted(['go.mod','go.sum','schema/optional.go','internal/schema/json.go',
    'internal/schema/value.go','internal/schema/numbers.go','internal/schema/registry.go',
    'internal/schema/resolve.go','internal/schema/legacy_profile.go','internal/schema/legacy-profile.json',
    'internal/schema/regexp.go','internal/schema/validate.go','internal/schema/numeric_admission.go','internal/schema/embedded.go'])
CONFIG_KEYS={'format','job_id','module_root','input_manifest','sdk_go','tool_policy',
    'toolexec_argv','environment','roots','root_driver','fixture_slots','coverage','caps'}


def _require(ok,message):
    if not ok:raise ValueError(message)


def _wire(config):
    _require(type(config) is dict and CONFIG_KEYS<=set(config) and
             all(key in CONFIG_KEYS or key.startswith('_') for key in config),'internal config keys')
    return {key:config[key] for key in CONFIG_KEYS}


def _plans(config):
    plans={}
    for row in config['coverage']:
        raw=b1._pin_bytes(row['plan'],256*1024,control=True)
        payload=b1._strict(raw,256*1024)
        trace._coverage_plan(dict(driver_id=row['driver_id'],_config=config),payload)
        plans[row['driver_id']]=payload
    return plans


def load_job(raw: bytes) -> dict:
    config=b1._config(raw)
    for slot in config['fixture_slots']:
        _require(slot['support_paths']==SUPPORT,'exact support inventory')
    env=config['environment']
    _require(env.get('OM_BUILD_JOB_ID')==config['job_id'] and
             env.get('OM_GENERATED_EVIDENCE_DIR')==config['roots']['fixtures'],'released helper environment')
    b1._absolute(env.get('OM_BUILD_LAUNCHER'))
    original=source.load_manifest(b1._pin_bytes(config['input_manifest'],16*1024*1024,control=True))
    _require(original['root']==config['module_root'],'original manifest root')
    b1._pin_bytes(config['sdk_go'])
    policy=b1.load_job_policy(b1._pin_bytes(config['tool_policy'],256*1024,control=True))
    _require(policy['working_directory']==config['module_root'] and
             policy['record_directory']==config['roots']['records'],'root policy binding')
    _plans(config)
    return config


def _publish(directory,name,value,maximum=16*1024*1024):
    source._relative(name)
    _require('/' not in name,'control basename')
    raw=b1.v1._encoded(value)+b'\n'
    _require(len(raw)<=maximum,'control bound')
    with b1._directory(Path(directory)) as parent:
        info=os.fstat(parent)
        _require(info.st_uid==os.geteuid() and stat.S_IMODE(info.st_mode)==0o700,'private control root')
        try:fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
        except FileExistsError as error:raise ValueError('control replay/publication refused') from error
        try:
            count=os.write(fd,raw)
            _require(count==len(raw),'short control write')
            os.fsync(fd)
        finally:os.close(fd)
        os.fsync(parent)
    pin=dict(path=str(Path(directory)/name),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),mode=0o600)
    _require(b1._pin_bytes(pin,maximum,control=True)==raw,'published control differs')
    return pin


def _publish_job(config,directory,name,value,maximum=16*1024*1024):
    try:return _publish(directory,name,value,maximum)
    except (ValueError,OSError):
        bio._poison(Path(config['roots']['drivers']),'control publication refused')
        raise


@contextmanager
def _slot_lock(config,identity):
    b1._id(identity)
    with b1._directory(Path(config['roots']['registrations'])) as parent:
        fd=os.open(identity+'.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=parent)
        try:
            info=os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_uid==os.geteuid() and
                     info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600,'unsafe slot lock')
            bio._lock(fd,time.monotonic_ns()+config['caps']['pre_seconds']*1_000_000_000)
            yield
        finally:os.close(fd)


def _expected_paths(slot,generated):
    _require(type(generated) is list and 1<=len(generated)<=30000,'generated path bound')
    for path in generated:
        source._relative(path,30000)
        _require(len(path.encode('utf-8'))<=4096,'generated path byte bound')
    _require(generated==sorted(set(generated)),'generated paths sorted unique')
    paths=SUPPORT+[slot['package']+'/'+path for path in generated]+[slot['package']+'/behavior_test.go']
    _require(len(paths)==len(set(paths))<=30000,'expected file overlap/bound')
    return sorted(paths)


def _inventory(root,expected):
    # The trie admits component/prefix bounds before scanning or hashing bytes.
    draft=dict(format='om-go-build-inputs-v1',root=str(root),excluded_roots=[],
        files=[dict(path=p,bytes=0,mode=0o600,sha256='0'*64) for p in expected])
    source._admit_manifest(draft)
    directories=set()
    for path in expected:
        parts=path.split('/')
        for i in range(1,len(parts)):directories.add('/'.join(parts[:i]))
    found={};seen=set();stack=[('',root)];physical=0;total=0
    while stack:
        relative,directory=stack.pop()
        with source._directory(directory) as parent:
            before=os.fstat(parent)
            _require(before.st_uid==os.geteuid() and stat.S_IMODE(before.st_mode)==0o700,'private fixture directory')
            with os.scandir(parent) as entries:
                for entry in entries:
                    physical+=1;_require(physical<=30000,'physical fixture entry bound')
                    source._relative(entry.name)
                    path=relative+'/'+entry.name if relative else entry.name
                    info=entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        _require(path in directories,'extra fixture directory')
                        seen.add(path);stack.append((path,root/path))
                    else:
                        _require(path in expected,'extra fixture file')
                        row=dict(path=path,bytes=info.st_size,mode=stat.S_IMODE(info.st_mode),sha256='0'*64)
                        source._check_info(info,row,source.MAX_MEMBER)
                        found[path]=row;total+=row['bytes']
                        _require(total<=source.MAX_TOTAL,'fixture logical byte bound')
            _require(source._identity(before)==source._identity(os.fstat(parent)),'fixture directory changed')
    _require(set(found)==set(expected) and seen==directories,'missing fixture member')
    return found


def _manifest(root,expected):
    metadata=_inventory(root,expected)
    rows=[]
    for path in expected:
        row=metadata[path];digest=hashlib.sha256();count=0
        with source._directory((root/path).parent) as parent:
            fd=os.open((root/path).name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            try:
                before=os.fstat(fd);source._check_info(before,row,source.MAX_MEMBER)
                while True:
                    chunk=os.read(fd,min(65536,row['bytes']-count+1))
                    if not chunk:break
                    count+=len(chunk);_require(count<=row['bytes'],'fixture grew')
                    digest.update(chunk)
                _require(source._identity(before)==source._identity(os.fstat(fd)) and
                         source._identity(before)==source._identity(os.stat((root/path).name,dir_fd=parent,follow_symlinks=False)),
                         'fixture changed while hashing')
            finally:os.close(fd)
        _require(count==row['bytes'],'fixture truncated')
        rows.append(dict(row,sha256=digest.hexdigest()))
    result=dict(format='om-go-build-inputs-v1',root=str(root),excluded_roots=[],files=rows)
    source.verify_manifest(root,result)
    _inventory(root,expected)
    return result


def _expected_digest(paths):
    return hashlib.sha256(b1.v1._encoded(paths)+b'\n').hexdigest()


def _freeze(config,request):
    slots=[s for s in config['fixture_slots'] if s['test_name']==request['test_name']]
    _require(len(slots)==1,'unreleased fixture test')
    slot=slots[0];identity=slot['driver_id'];root=b1._physical(request['root'],True)
    _require(Path(config['roots']['fixtures']) in root.parents,'fixture root containment')
    expected=_expected_paths(slot,request['generated_paths'])
    with _slot_lock(config,identity):
        directory=Path(config['roots']['registrations'])
        _publish_job(config,directory,identity+'.freeze-attempt.json',dict(root=str(root),expected_paths=expected))
        with source._directory(root) as fd:before=os.fstat(fd)
        manifest=_manifest(root,expected)
        template=b1.load_job_policy(b1._pin_bytes(config['tool_policy'],256*1024,control=True))
        effective=dict(template,working_directory=str(root))
        policy_pin=_publish_job(config,directory,identity+'.policy.json',effective,256*1024)
        manifest_pin=_publish_job(config,directory,identity+'.manifest.json',manifest)
        with source._directory(root) as fd:
            after=os.fstat(fd)
            _require((before.st_dev,before.st_ino)==(after.st_dev,after.st_ino),'fixture root replaced')
        registration=dict(format='om-fixture-registration-v1',job_id=config['job_id'],driver_id=identity,
            root=dict(path=str(root),dev=before.st_dev,ino=before.st_ino),manifest=manifest_pin,policy=policy_pin,
            expected_paths_sha256=_expected_digest(expected),pre_pass=True)
        receipt=_publish_job(config,directory,identity+'.registration.json',registration)
        _publish_job(config,directory,identity+'.FROZEN.json',dict(registration=receipt))
    return _response(config,'freeze',identity,receipt)


def _read_control(directory,name,maximum=16*1024*1024):
    path=Path(directory)/name
    pin=_runtime_pin(path)
    _require(pin['mode']==0o600 and pin['bytes']<=maximum,'control mode/byte bound')
    return b1._strict(b1._pin_bytes(pin,maximum,control=True),maximum)


def _fixture_check(config,driver_id):
    _require(driver_id in {slot['driver_id'] for slot in config['fixture_slots']},'unreleased fixture driver')
    directory=Path(config['roots']['registrations'])
    frozen=_read_control(directory,driver_id+'.FROZEN.json')
    b1._object(frozen,{'registration'},'frozen binding')
    _require(frozen['registration']['path']==str(directory/(driver_id+'.registration.json')),'registration control location')
    registration=b1._strict(b1._pin_bytes(frozen['registration'],control=True),256*1024)
    b1._object(registration,{'format','job_id','driver_id','root','manifest','policy','expected_paths_sha256','pre_pass'},'registration')
    _require(registration['format']=='om-fixture-registration-v1' and registration['job_id']==config['job_id'] and
             registration['driver_id']==driver_id and registration['pre_pass'] is True,'registration binding')
    b1._object(registration['root'],{'path','dev','ino'},'registered root')
    for key in ('dev','ino'):source._integer(registration['root'][key],(1<<63)-1)
    root=b1._physical(registration['root']['path'],True)
    _require(Path(config['roots']['fixtures']) in root.parents,'registered fixture containment')
    with source._directory(root) as fd:
        info=os.fstat(fd)
        _require((info.st_dev,info.st_ino)==(registration['root']['dev'],registration['root']['ino']),'original fixture root replaced')
    for key in ('manifest','policy'):
        _require(registration[key]['path']==str(directory/(driver_id+'.'+key+'.json')),'cross-driver registration Pin')
    manifest=source.load_manifest(b1._pin_bytes(registration['manifest'],16*1024*1024,control=True))
    _require(manifest['root']==str(root) and not manifest['excluded_roots'],'fixture original manifest root/exclusions')
    attempt=_read_control(directory,driver_id+'.freeze-attempt.json')
    b1._object(attempt,{'root','expected_paths'},'original freeze expectation')
    expected=attempt['expected_paths']
    _require(attempt['root']==str(root) and type(expected) is list and expected==[row['path'] for row in manifest['files']]
             and _expected_digest(expected)==registration['expected_paths_sha256'],'original expected membership differs')
    template=b1.load_job_policy(b1._pin_bytes(config['tool_policy'],256*1024,control=True))
    effective_raw=b1._pin_bytes(registration['policy'],256*1024,control=True)
    _require(effective_raw==b1.v1._encoded(dict(template,working_directory=str(root)))+b'\n','original cwd-only policy derivation')
    source.verify_manifest(root,manifest)
    _inventory(root,expected)
    with source._directory(root) as fd:
        info=os.fstat(fd)
        _require((info.st_dev,info.st_ino)==(registration['root']['dev'],registration['root']['ino']),'fixture root changed during verification')
    return registration


def _response(config,mode,driver,receipt=None,error=None):
    return dict(format='om-driver-control-v1',job_id=config['job_id'],driver_id=driver,phase=mode,
                status='PASS' if error is None else 'FAIL',receipt=receipt,error=error)


def _request_context(config):
    path=os.environ.get('OM_GO_SUPERVISION_CONTEXT')
    digest=os.environ.get('OM_GO_SUPERVISION_CONTEXT_SHA256')
    try:
        context=b1._resolve_context(path,digest)
        _require(context['_config']==_wire(config) and context['driver_id']==config['root_driver']['driver_id'],
                 'request requires released root context')
        expected=dict(config['environment'],OM_GO_SUPERVISION_CONTEXT=path,
                      OM_GO_SUPERVISION_CONTEXT_SHA256=digest)
        names={name for name in os.environ if name.startswith('OM_')} | {name for name in expected if name.startswith('OM_')}
        _require(all(os.environ.get(name)==expected.get(name) for name in names),'request control environment')
        identity=context['_start']['go_identity'];pid=os.getppid();chain=[]
        deadline=time.monotonic_ns()+10_000_000_000
        while pid>0 and len(chain)<256 and time.monotonic_ns()<deadline:
            current,parent=b1._process(pid)
            chain.append((current,parent))
            if current==identity:
                _require(b1._process_image(pid)==config['sdk_go']['path'],'root ancestor SDK image')
                b1._pin_bytes(config['sdk_go'])
                _require(all(b1._process(row['pid'])==(row,ppid) for row,ppid in chain),'request ancestry changed')
                return context
            _require(current['pid']!=identity['pid'],'root ancestor start changed')
            _require(parent!=pid,'cyclic process ancestry')
            pid=parent
    except (OSError,TypeError) as error:raise ValueError('unavailable request ancestry/context') from error
    raise ValueError('request is outside live root SDK ancestry')


def handle_request(config: dict, mode: str, raw: bytes) -> dict:
    config_pin=config.get('_pin')
    config=load_job(b1.v1._encoded(_wire(config)))
    if config_pin is not None:
        _require(load_job(b1._pin_bytes(config_pin,256*1024,control=True))==config,'request pinned config')
        config['_pin']=config_pin
    _require(mode in ('driver','freeze','run','post'),'control mode')
    request=b1._strict(raw,config['caps']['request_bytes'])
    fields={'format','job_id','test_name','root','generated_paths'} if mode=='freeze' else {'format','job_id','driver_id'}
    b1._object(request,fields,'request')
    prefix='om-root-driver-v1' if mode=='driver' else 'om-fixture-'+mode+'-v1'
    _require(request['format']==prefix and request['job_id']==config['job_id'],'request job/format')
    if mode=='freeze':
        b1._text(request['test_name'],512,'test name')
        b1._absolute(request['root'])
    else:b1._id(request['driver_id'])
    if mode!='driver':_request_context(config)
    if mode=='freeze':return _freeze(config,request)
    if mode=='run':return _run(config,request['driver_id'])
    if mode=='post':return _post(config,request['driver_id'])
    return _root_driver(config,request['driver_id'])


def _root_driver(config,driver_id):
    _require(driver_id==config['root_driver']['driver_id'],'released root driver')
    directory=Path(config['roots']['registrations'])
    with _slot_lock(config,driver_id):
        _publish_job(config,directory,driver_id+'.driver-attempt.json',dict(config=config.get('_pin')))
        try:
            manifest=source.load_manifest(b1._pin_bytes(config['input_manifest'],16*1024*1024,control=True))
            supervise_driver(config,config['root_driver'],manifest)
            receipt=_finalize(config)
            return _response(config,'driver',driver_id,receipt)
        except (ValueError,OSError,subprocess.SubprocessError):
            receipt=_publish_job(config,directory,driver_id+'.driver-failure.json',dict(error='root job refused'))
            return _response(config,'driver',driver_id,receipt,'root job refused')


def _export_budget(config,reserve_paths=0):
    source._integer(reserve_paths,source.MAX_PATHS)
    manifest=source.load_manifest(b1._pin_bytes(config['input_manifest'],16*1024*1024,control=True))
    _,_,prefixes=source._admit_manifest(manifest)
    physical=1+reserve_paths
    nodes=[prefixes]
    while nodes:
        for part,child in nodes.pop().items():
            if part is None or child.get(None)=='excluded':continue
            physical+=1;_require(physical<=source.MAX_PATHS,'aggregate physical path bound')
            nodes.append(child)
    logical=sum(row['bytes'] for row in manifest['files'])
    _require(physical<=source.MAX_PATHS,'aggregate physical path bound')
    _require(logical<=source.MAX_TOTAL,'aggregate logical source bound')
    stack=[]
    for name,path in config['roots'].items():
        physical+=1;stack.append((name,Path(path)))
    while stack:
        kind,directory=stack.pop()
        with source._directory(directory) as parent:
            info=os.fstat(parent)
            _require(info.st_uid==os.geteuid() and stat.S_IMODE(info.st_mode)==0o700,'private export directory')
            with os.scandir(parent) as entries:
                for entry in entries:
                    source._relative(entry.name)
                    physical+=1;_require(physical<=source.MAX_PATHS,'aggregate physical path bound')
                    info=entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):stack.append((kind,directory/entry.name))
                    else:
                        row=dict(bytes=info.st_size,mode=stat.S_IMODE(info.st_mode))
                        source._check_info(info,row,source.MAX_MEMBER)
                        if kind=='fixtures':
                            logical+=info.st_size
                            _require(logical<=source.MAX_TOTAL,'aggregate logical source bound')
    return dict(physical_paths=physical,logical_bytes=logical)


def _finalize(config):
    bio._assert_job(Path(config['roots']['drivers']))
    ids=sorted([config['root_driver']['driver_id']]+[slot['driver_id'] for slot in config['fixture_slots']])
    contexts={identity:_read_context(config,identity) for identity in ids}
    terminals={};directory=Path(config['roots']['registrations'])
    for identity in ids:
        driver_root=Path(config['roots']['drivers'])/identity
        terminal_pin=_runtime_pin(driver_root/'terminal.json')
        terminals[identity]=_local_terminal(config,identity,terminal_pin)
        if identity==config['root_driver']['driver_id']:continue
        _fixture_check(config,identity)
        phase=_read_control(directory,identity+'.POST.json')
        b1._object(phase,{'post'},'post phase')
        _require(phase['post']['path']==str(driver_root/'post.json'),'post driver binding')
        post=b1._strict(b1._pin_bytes(phase['post'],256*1024,control=True),256*1024)
        b1._object(post,{'format','job_id','driver_id','manifest','integrity_pass','run_pass'},'post result')
        _require(post['format']=='om-fixture-post-result-v1' and post['job_id']==config['job_id'] and
                 post['driver_id']==identity and post['manifest']==contexts[identity]['_start']['manifest'] and
                 post['integrity_pass'] is True and post['run_pass'] is True,'required local post failed')
    # Full replay is authenticated once before any per-driver filtering.
    events=b1.read_job_events(Path(config['roots']['records']),contexts)
    plans=_plans(config)
    shared=dict(named_hash_headers=0,build_blocks=0,active_build_blocks=0)
    results=[];persisted=0
    for identity in ids:
        terminal=terminals[identity];driver_root=Path(config['roots']['drivers'])/identity
        bio._reserve_identity(Path(config['roots']['drivers']),contexts[identity]['_start']['go_identity'])
        for row in events:
            if row['driver_id']!=identity:continue
            bio._reserve_identity(Path(config['roots']['drivers']),row['recorder'])
            if row['kind']=='host-complete' and row['data']['child'] is not None:
                bio._reserve_identity(Path(config['roots']['drivers']),row['data']['child'])
        for _ in bio.authenticate_stream(driver_root,'stdout',terminal['stdout']):pass
        blocks=trace.parse_hash_trace(bio.authenticate_stream(driver_root,'stderr',terminal['stderr']),shared)
        rows=[row for row in events if row['driver_id']==identity]
        results.append(trace.reconcile_driver(contexts[identity],terminal,rows,blocks,plans[identity]))
        persisted+=terminal['stdout']['bytes']+terminal['stderr']['bytes']
    budget=_export_budget(config,reserve_paths=1)
    reserved=bio.reserved_raw(Path(config['roots']['drivers']))
    _require(reserved==persisted<=config['caps']['raw_bytes'],'job reservation/persisted gap')
    root_manifest=source.load_manifest(b1._pin_bytes(config['input_manifest'],16*1024*1024,control=True))
    source.verify_manifest(Path(config['module_root']),root_manifest)
    for slot in config['fixture_slots']:_fixture_check(config,slot['driver_id'])
    # Private bounded evidence payload; the public response remains the seven-key wire.
    return _publish_job(config,Path(config['roots']['drivers'])/config['root_driver']['driver_id'],'job-result.json',
                    dict(coverage_results=results,reserved_raw_bytes=reserved,source_pass=True,source_budget=budget))


def _run(config,driver_id):
    _require(driver_id in {slot['driver_id'] for slot in config['fixture_slots']},'unreleased fixture run')
    directory=Path(config['roots']['registrations']);terminal_pin=None;passed=False
    with _slot_lock(config,driver_id):
        frozen=_read_control(directory,driver_id+'.FROZEN.json')
        b1._object(frozen,{'registration'},'run frozen binding')
        _publish_job(config,directory,driver_id+'.RUNNING.json',frozen)
        try:
            _request_context(config)
            registration=_fixture_check(config,driver_id)
            manifest=source.load_manifest(b1._pin_bytes(registration['manifest'],16*1024*1024,control=True))
            supervise_driver(config,dict(driver_id=driver_id,argv=['test','./...','-count=1']),manifest)
            passed=True
        except (ValueError,OSError,subprocess.SubprocessError):
            passed=False
            bio._poison(Path(config['roots']['drivers']),'fixture run refused')
        finally:
            path=Path(config['roots']['drivers'])/driver_id/'terminal.json'
            if path.exists():terminal_pin=_runtime_pin(path)
            _publish_job(config,directory,driver_id+'.TERMINAL.json',dict(terminal=terminal_pin,run_pass=passed))
    return _response(config,'run',driver_id,terminal_pin,None if passed else 'run refused')


def _local_terminal(config,driver_id,pin):
    b1._pin_shape(pin,16*1024*1024)
    _require(pin['path']==str(Path(config['roots']['drivers'])/driver_id/'terminal.json'),'terminal driver path')
    terminal=b1._strict(b1._pin_bytes(pin,16*1024*1024,control=True),16*1024*1024)
    b1._object(terminal,{'format','job_id','driver_id','go_identity','manifest','exit_code','signal',
                       'timed_out','overflow','stdout','stderr','cleanup_complete'},'local terminal')
    _require(terminal['format']=='om-driver-terminal-v1' and terminal['job_id']==config['job_id'] and
             terminal['driver_id']==driver_id,'local terminal binding')
    b1._identity_shape(terminal['go_identity'])
    _require((terminal['exit_code'] is None)!=(terminal['signal'] is None),'terminal exit choice')
    if terminal['exit_code'] is not None:source._integer(terminal['exit_code'],(1<<63)-1)
    if terminal['signal'] is not None:
        source._integer(terminal['signal'],64);_require(terminal['signal']>0,'terminal signal')
    context=_read_context(config,driver_id)
    _require(terminal['go_identity']==context['_start']['go_identity'] and
             terminal['manifest']==context['_start']['manifest'],'local original start/manifest')
    for key in ('timed_out','overflow','cleanup_complete'):
        _require(type(terminal[key]) is bool,'terminal boolean')
    for name in ('stdout','stderr'):trace._stream(terminal[name],name)
    _require(_terminal_ok(terminal),'local terminal not successful')
    _require(not (Path(config['roots']['drivers'])/driver_id/'capture-failure.json').exists(),'capture failure retained')
    return terminal


def _read_context(config,driver_id):
    path=Path(config['roots']['registrations'])/(driver_id+'.context.json')
    pin=_runtime_pin(path)
    _require(pin['mode']==0o600 and pin['bytes']<=16384,'context mode/bound')
    context=b1._resolve_context(pin['path'],pin['sha256'])
    _require(context['driver_id']==driver_id and context['_config']==_wire(config) and
             context['config']==config['_pin'],'driver original config binding')
    return context


def _post(config,driver_id):
    _require(driver_id in {slot['driver_id'] for slot in config['fixture_slots']},'unreleased fixture post')
    directory=Path(config['roots']['registrations'])
    with _slot_lock(config,driver_id):
        phase=_read_control(directory,driver_id+'.TERMINAL.json')
        b1._object(phase,{'terminal','run_pass'},'terminal phase')
        _require(type(phase['run_pass']) is bool,'run phase boolean')
        frozen=_read_control(directory,driver_id+'.FROZEN.json')
        registration=b1._strict(b1._pin_bytes(frozen['registration'],control=True),256*1024)
        integrity=True;run_pass=phase['run_pass']
        try:_fixture_check(config,driver_id)
        except (ValueError,OSError):integrity=False
        try:_local_terminal(config,driver_id,phase['terminal'])
        except (ValueError,OSError,TypeError):run_pass=False
        result=dict(format='om-fixture-post-result-v1',job_id=config['job_id'],driver_id=driver_id,
                    manifest=registration['manifest'],integrity_pass=integrity,run_pass=run_pass)
        driver_root=Path(config['roots']['drivers'])/driver_id
        # A pre-exec refusal can lack a driver directory; evidence remains outside input.
        with b1._directory(Path(config['roots']['drivers'])) as parent:
            try:os.mkdir(driver_id,0o700,dir_fd=parent)
            except FileExistsError:pass
        receipt=_publish_job(config,driver_root,'post.json',result)
        _publish_job(config,directory,driver_id+'.POST.json',dict(post=receipt))
    return _response(config,'post',driver_id,receipt,None if integrity and run_pass else 'post refused')


def _spawn_gated(config,driver,manifest_pin,policy_pin,driver_root):
    job_root=Path(config['roots']['drivers'])
    bio._assert_job(job_root)
    bio.reserve_raw(job_root,0)
    bio._reserve_capture(job_root)
    config_pin=config.get('_pin')
    b1._pin_shape(config_pin,256*1024)
    _require(load_job(b1._pin_bytes(config_pin,256*1024,control=True))==_wire(config),'gate config binding')
    b1._pin_bytes(config['sdk_go'])
    manifest=source.load_manifest(b1._pin_bytes(manifest_pin,16*1024*1024,control=True))
    source.verify_manifest(Path(manifest['root']),manifest)
    _export_budget(config,reserve_paths=3)
    engine=_runtime_pin(Path(__file__).resolve())
    interpreter=_runtime_pin(Path(sys.executable).resolve())
    parent=b1._process(os.getpid())[0]
    ack_read,ack_write=os.pipe();ready_read,ready_write=os.pipe()
    process=None;released=False
    try:
        argv=[interpreter['path'],'-B',engine['path'],'--_gate',str(ack_read),str(ready_write),
              b1.v1._encoded(parent).decode(),b1.v1._encoded(config_pin).decode(),driver['driver_id'],
              b1.v1._encoded(manifest_pin).decode(),b1.v1._encoded(policy_pin).decode()]
        environment=dict(config['environment'],PWD=manifest['root'])
        process=subprocess.Popen(argv,cwd=manifest['root'],env=environment,stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,pass_fds=(ack_read,ready_write))
        process._om_capture_reserved=True
        if config.get('_owner') is not None:
            process._om_owner=config['_owner'];config['_owner'].bind(process)
        os.close(ack_read);ack_read=None;os.close(ready_write);ready_write=None
        _require(_read_pipe(ready_read,16,time.monotonic_ns()+10_000_000_000)==b'R','gate not ready')
        identity=b1._process(process.pid)[0]
        root_id=config['root_driver']['driver_id']
        start=dict(format='om-go-driver-start-v1',job_id=config['job_id'],driver_id=driver['driver_id'],
            parent_driver_id=None if driver['driver_id']==root_id else root_id,go_identity=identity,
            sdk_go=config['sdk_go'],manifest=manifest_pin)
        directory=Path(config['roots']['registrations'])
        start_pin=_publish_job(config,directory,driver['driver_id']+'.start.json',start)
        context=dict(format='om-go-context-v1',job_id=config['job_id'],driver_id=driver['driver_id'],
                     config=config_pin,start=start_pin,policy=policy_pin)
        context_pin=_publish_job(config,directory,driver['driver_id']+'.context.json',context,16384)
        _require(b1._resolve_context(context_pin['path'],context_pin['sha256'])['_start']==start,'gate publication binding')
        for pin in (engine,interpreter,config_pin,config['sdk_go']):b1._pin_bytes(pin)
        _require(b1._process(process.pid)[0]==identity,'gated child identity changed')
        message=b1.v1._encoded(context_pin)+b'\n'
        _require(len(message)<=16384 and os.write(ack_write,message)==len(message),'gate acknowledgement failed')
        released=True
        return process
    finally:
        for fd in (ack_read,ack_write,ready_read,ready_write):
            if fd is not None:os.close(fd)
        if process is not None and not released:
            result=bio.capture_streams(process,Path(config['roots']['drivers']),Path(driver_root),
                                       time.monotonic_ns()+1_000_000_000)
            _publish_job(config,Path(driver_root),'gate-failure.json',result)


def _runtime_pin(path):
    with source._directory(path.parent) as parent:
        before=os.stat(path.name,dir_fd=parent,follow_symlinks=False)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=64*1024*1024,'runtime file bound/type')
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        try:
            info=os.fstat(fd)
            _require(source._identity(before)==source._identity(info),'runtime changed before open')
            digest=hashlib.sha256();size=0
            while True:
                chunk=os.read(fd,65536)
                if not chunk:break
                size+=len(chunk);_require(size<=info.st_size,'runtime grew');digest.update(chunk)
            _require(size==info.st_size and source._identity(info)==source._identity(os.fstat(fd)) and
                     source._identity(info)==source._identity(os.stat(path.name,dir_fd=parent,follow_symlinks=False)),'runtime changed')
        finally:os.close(fd)
    return dict(path=str(path),bytes=size,sha256=digest.hexdigest(),mode=stat.S_IMODE(info.st_mode))


def _read_pipe(fd,limit,deadline):
    result=bytearray();regular=stat.S_ISREG(os.fstat(fd).st_mode)
    if not regular:os.set_blocking(fd,False)
    with selectors.DefaultSelector() as selector:
        if not regular:selector.register(fd,selectors.EVENT_READ)
        while time.monotonic_ns()<deadline:
            if not regular and not selector.select(min(.05,max(0,(deadline-time.monotonic_ns())/1e9))):continue
            try:part=os.read(fd,min(65536,limit-len(result)+1))
            except BlockingIOError:continue
            if not part:return bytes(result)
            _require(len(result)+len(part)<=limit,'gate pipe bound');result.extend(part)
    raise ValueError('gate pipe timeout')


def _gate_entry(argv):
    ack=ready=None
    try:
        _require(len(argv)==7,'private gate arguments')
        ack,ready=int(argv[0]),int(argv[1])
        parent=b1._strict(argv[2].encode(),16384);b1._identity_shape(parent)
        config_pin=b1._strict(argv[3].encode(),16384);b1._pin_shape(config_pin,256*1024)
        driver_id=b1._id(argv[4])
        manifest_pin=b1._strict(argv[5].encode(),16384);b1._pin_shape(manifest_pin,16*1024*1024)
        policy_pin=b1._strict(argv[6].encode(),16384);b1._pin_shape(policy_pin,256*1024)
        _require(os.getppid()==parent['pid'] and b1._process(parent['pid'])[0]==parent,'gate lost parent')
        _require(os.write(ready,b'R')==1,'gate ready write');os.close(ready);ready=None
        message=_read_pipe(ack,16384,time.monotonic_ns()+10_000_000_000)
        _require(message.endswith(b'\n'),'gate lost acknowledgement')
        context_pin=b1._strict(message,16384);b1._pin_shape(context_pin,16384)
        context=b1._resolve_context(context_pin['path'],context_pin['sha256'])
        _require(context['config']==config_pin and context['driver_id']==driver_id and
                 context['policy']==policy_pin and context['_start']['manifest']==manifest_pin and
                 context['_start']['go_identity']==b1._process(os.getpid())[0],'gate context identity')
        config=load_job(b1._pin_bytes(config_pin,256*1024,control=True))
        manifest=source.load_manifest(b1._pin_bytes(manifest_pin,16*1024*1024,control=True))
        source.verify_manifest(Path(manifest['root']),manifest)
        _require(os.getppid()==parent['pid'] and b1._process(parent['pid'])[0]==parent,'gate parent changed')
        argv=config['root_driver']['argv'] if driver_id==config['root_driver']['driver_id'] else ['test','./...','-count=1']
        environment=dict(config['environment'],PWD=manifest['root'],OM_GO_SUPERVISION_CONTEXT=context_pin['path'],
                         OM_GO_SUPERVISION_CONTEXT_SHA256=context_pin['sha256'])
        os.close(ack);ack=None
        os.execve(config['sdk_go']['path'],[config['sdk_go']['path'],*argv],environment)
    except (ValueError,OSError,TypeError):
        try:os.write(2,b'gate refused\n')
        except OSError:pass
        return 1
    finally:
        for fd in (ack,ready):
            if fd is not None:os.close(fd)


def supervise_driver(config: dict, driver: dict, manifest: dict) -> dict:
    b1._object(driver,{'driver_id','argv'},'released driver')
    identity=b1._id(driver['driver_id']);b1._vector(driver['argv'])
    fresh=load_job(b1._pin_bytes(config.get('_pin'),256*1024,control=True))
    _require(fresh==_wire(config),'supervisor pinned config')
    root_driver=identity==config['root_driver']['driver_id']
    if root_driver:
        _require(driver==config['root_driver'],'released root command')
        manifest_pin=config['input_manifest'];policy_pin=config['tool_policy']
    else:
        registration=_fixture_check(config,identity)
        _require(driver['argv']==['test','./...','-count=1'],'released fixture command')
        manifest_pin=registration['manifest'];policy_pin=registration['policy']
    original=source.load_manifest(b1._pin_bytes(manifest_pin,16*1024*1024,control=True))
    _require(manifest==original,'supervisor original manifest binding')
    source.verify_manifest(Path(original['root']),original)
    directory=Path(config['roots']['drivers'])/identity
    with b1._directory(Path(config['roots']['drivers'])) as parent:
        try:os.mkdir(identity,0o700,dir_fd=parent)
        except FileExistsError as error:raise ValueError('driver already consumed') from error
        os.fsync(parent)
    owner=bio._Ownership(Path(config['roots']['drivers']));process=None;complete=False
    try:
        internal=dict(config,_owner=owner)
        process=_spawn_gated(internal,driver,manifest_pin,policy_pin,directory)
        result=bio.capture_streams(process,Path(config['roots']['drivers']),directory,
            time.monotonic_ns()+config['caps']['run_seconds']*1_000_000_000)
        start=_read_control(Path(config['roots']['registrations']),identity+'.start.json')
        terminal=dict(format='om-driver-terminal-v1',job_id=config['job_id'],driver_id=identity,
            go_identity=start['go_identity'],manifest=manifest_pin,
            **{key:value for key,value in result.items() if not key.startswith('_')})
        _publish_job(config,directory,'terminal.json',terminal)
        if result['_io_error']:
            _publish_job(config,directory,'capture-failure.json',dict(error='capture/ownership refused',
                finalization_errors=result.get('_finalization_errors',[])))
        source.verify_manifest(Path(original['root']),original)
        if not root_driver:_fixture_check(config,identity)
        _require(not result['_io_error'],'driver capture/ownership failure')
        _require(_terminal_ok(terminal),'driver terminal failed')
        complete=True
        return terminal
    finally:
        try:
            if not complete and process is not None:
                owner.cancel()
                if process.poll() is None:
                    remaining=max(0,(owner.cleanup_deadline-time.monotonic_ns())/1e9)
                    try:process.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:owner.failed=True
        finally:
            if not owner.finish():raise ValueError('owned driver cleanup incomplete')


def _terminal_ok(terminal):
    return (terminal['exit_code']==0 and terminal['signal'] is None and not terminal['timed_out'] and
            not terminal['overflow'] and terminal['cleanup_complete'] and
            all(stream['eof'] and not stream['loss_unknown'] and stream['observed_discarded_bytes']==0
                for stream in (terminal['stdout'],terminal['stderr'])))


def main(argv: list[str]) -> int:
    config=None;mode=None
    try:
        _require(type(argv) is list and len(argv)==5 and argv[0]=='--config' and
                 argv[2]=='--config-sha256' and argv[4] in ('driver','freeze','run','post'),'launcher arguments')
        path=b1._absolute(argv[1]);source._digest(argv[3]);mode=argv[4]
        raw=b1.v1._read_file(str(path),256*1024)
        _require(hashlib.sha256(raw).hexdigest()==argv[3],'launcher config SHA')
        config=load_job(raw)
        _require(Path(config['roots']['registrations']) in path.parents,'config outside registrations')
        pin=dict(path=str(path),bytes=len(raw),sha256=argv[3],mode=0o600)
        _require(b1._pin_bytes(pin,256*1024,control=True)==raw,'launcher original config')
        config['_pin']=pin
        request=_read_pipe(sys.stdin.fileno(),config['caps']['request_bytes'],
                           time.monotonic_ns()+config['caps']['pre_seconds']*1_000_000_000)
        response=handle_request(config,mode,request)
    except (ValueError,OSError,TypeError,subprocess.SubprocessError):
        if config is None or mode is None:
            try:os.write(2,b'control refused\n')
            except OSError:pass
            return 1
        response=_response(config,mode,config['root_driver']['driver_id'],error='control refused')
    try:
        raw,response=_bounded_reply(response)
        _require(sys.stdout.buffer.write(raw)==len(raw),'control response write')
        sys.stdout.buffer.flush()
    except (ValueError,OSError):return 1
    return 0 if response['status']=='PASS' else 1


def _bounded_reply(response):
    b1._object(response,{'format','job_id','driver_id','phase','status','receipt','error'},'control response')
    _require(response['format']=='om-driver-control-v1' and response['phase'] in ('driver','freeze','run','post')
             and response['status'] in ('PASS','FAIL'),'response format/phase/status')
    b1._id(response['job_id']);b1._id(response['driver_id'])
    if response['receipt'] is not None:b1._pin_shape(response['receipt'],16*1024*1024)
    if response['error'] is not None:b1._text(response['error'],256,'fixed response error')
    _require(response['status']!='PASS' or response['error'] is None and response['receipt'] is not None,'response success evidence')
    raw=b1.v1._encoded(response)+b'\n'
    if len(raw)>4096:
        response=dict(response,status='FAIL',receipt=None,error='response bound refused')
        raw=b1.v1._encoded(response)+b'\n'
    _require(len(raw)<=4096,'response byte bound')
    return raw,response


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--_gate':raise SystemExit(_gate_entry(sys.argv[2:]))
    raise SystemExit(main(sys.argv[1:]))
