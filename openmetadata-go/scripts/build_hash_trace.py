# SPDX-License-Identifier: Apache-2.0
"""Bounded selected-Go hash trace parsing; trusted B3 owns raw provenance.

Parser results are private in-memory data, never callback input or wire receipts.
The aggregation owner serializes access to the exact shared three-counter budget.
"""
import hashlib
import re
import unicodedata

MAX_RAW = 32*1024*1024
MAX_CHUNK = 65536
MAX_LINE = 1024*1024  # Includes HASH framing and LF.
MAX_DECODED = 512*1024
SALT = b'go1.27.2'
BUDGET_KEYS = {'named_hash_headers', 'build_blocks', 'active_build_blocks'}
ANCILLARY = {b'moduleIndex', b'gccCompilerID', b'covermeta', b'testResult', b'testInputs',
             b'getenv', b'open', b'stat', b'linkShared', b'testmain'}
ANCILLARY_PREFIXES = (b'vet ', b'link ', b'preprocess PGO profile ')
HEX = b'0123456789abcdefABCDEF'


def _require(ok, message):
    if not ok: raise ValueError(message)


def _uint(value, maximum):
    _require(type(value) is int and 0 <= value <= maximum, 'integer type/bound')


def decode_go_quote(raw: bytes, limit: int) -> bytes:
    _uint(limit, MAX_DECODED)
    _require(type(raw) is bytes and len(raw) <= MAX_LINE, 'quoted encoded bound/type')
    _require(len(raw) >= 2 and raw[:1] == b'"' and raw[-1:] == b'"', 'Go quote framing')
    output = bytearray()
    end = len(raw)-1
    index = 1
    simple = {ord('a'):7, ord('b'):8, ord('f'):12, ord('n'):10, ord('r'):13,
              ord('t'):9, ord('v'):11, ord('\\'):92, ord('"'):34}
    def emit(value):
        _require(len(output)+len(value) <= limit, 'decoded byte bound')
        output.extend(value)
    while index < end:
        value = raw[index]
        if value == 92:
            index += 1
            _require(index < end, 'incomplete Go escape')
            escape = raw[index]
            index += 1
            if escape in simple:
                emit(bytes([simple[escape]]))
                continue
            _require(escape in (ord('x'),ord('u'),ord('U')), 'unsupported Go escape')
            digits = 2 if escape == ord('x') else 4 if escape == ord('u') else 8
            token = raw[index:index+digits]
            _require(index+digits <= end and len(token) == digits and all(c in HEX for c in token), 'incomplete/invalid hex escape')
            index += digits
            scalar = int(token,16)
            if escape == ord('x'):
                emit(bytes([scalar]))
            else:
                _require(scalar <= 0x10ffff and not 0xd800 <= scalar <= 0xdfff, 'invalid Unicode scalar')
                emit(chr(scalar).encode('utf-8'))
            continue
        _require(value != 34, 'trailing/interior quote')
        next_escape = raw.find(b'\\',index,end)
        next_quote = raw.find(b'"',index,end)
        stop = min([end]+[position for position in (next_escape,next_quote) if position >= 0])
        _require(stop-index <= limit-len(output), 'decoded byte bound')
        literal = raw[index:stop]
        try: text = literal.decode('utf-8',errors='strict')
        except UnicodeError as error: raise ValueError('invalid literal UTF-8') from error
        _require(all(unicodedata.category(c) != 'Cc' for c in text), 'literal control byte')
        emit(literal)
        index = stop
    return bytes(output)


def _quote_end(raw, start=0):
    _require(start < len(raw) and raw[start] == 34, 'quoted token expected')
    index = start+1
    while index < len(raw):
        if raw[index] == 34: return index+1
        if raw[index] == 92: index += 1
        index += 1
    raise ValueError('truncated quoted token')


def _name(name):
    _require(name and b'\x00' not in name and b'\r' not in name and b'\n' not in name, 'HASH name')
    if name.startswith(b'build '):
        package = name[6:]
        try: decoded = package.decode('utf-8')
        except UnicodeError as error: raise ValueError('build package encoding') from error
        _require(decoded and not any(c.isspace() for c in decoded) and b'[' not in package and b']' not in package,
                 'build package label')
        return 'build', decoded
    if name in ANCILLARY or any(name.startswith(prefix) and len(name) > len(prefix) for prefix in ANCILLARY_PREFIXES):
        return 'ancillary', None
    raise ValueError('unknown HASH family')


def _budget(job_budget):
    _require(type(job_budget) is dict and set(job_budget) == BUDGET_KEYS, 'shared budget keys')
    for value in job_budget.values(): _uint(value,30000)
    _require(job_budget['active_build_blocks'] == 0 and
             job_budget['build_blocks'] <= job_budget['named_hash_headers'], 'unclosed/prior failed parser budget')


def parse_hash_trace(chunks, job_budget) -> list[dict]:
    _budget(job_budget)
    results = []
    active = {}
    ordinals = {}
    raw_total = 0
    line = bytearray()
    hash_line = None

    def consume(raw):
        # raw includes the physical LF, charged before any token allocation.
        _require(len(raw) <= MAX_LINE and raw.endswith(b'\n'), 'HASH line bound/framing')
        content = raw[:-1]
        if content.startswith(b'HASH['):
            close = content.find(b']',5)
            _require(close >= 0, 'HASH name closing bracket')
            name = content[5:close]
            tail = content[close+1:]
            header = tail == b''
            if header:
                _require(job_budget['named_hash_headers'] < 30000, 'named HASH header budget')
                job_budget['named_hash_headers'] += 1
            kind, package = _name(name)
            if header:
                if kind == 'build':
                    _require(name not in active, 'overlapping same-name build')
                    _require(job_budget['active_build_blocks'] < 256, 'active build budget')
                    job_budget['active_build_blocks'] += 1
                    ordinal = ordinals.get(name,0)+1
                    ordinals[name] = ordinal
                    active[name] = dict(kind='build',name=name.decode('utf-8'),package=package,
                                        ordinal=ordinal,inputs=[],_hash=hashlib.sha256())
                else:
                    results.append(dict(kind='ancillary',name=name,frame='header'))
                return
            _require(tail.startswith(b': '), 'HASH payload framing')
            token = tail[2:]
            quoted = token.startswith(b'"')
            if quoted:
                payload = decode_go_quote(token,MAX_DECODED)
            else:
                _require(re.fullmatch(b'[0-9a-f]{64}',token) is not None, 'HASH digest framing')
                payload = token.decode('ascii')
            if kind == 'ancillary':
                results.append(dict(kind='ancillary',name=name,frame='input' if quoted else 'digest',
                                    **({'input':payload} if quoted else {'sha256':payload})))
                return
            _require(name in active, 'build payload without active header')
            state = active[name]
            if quoted:
                if not state['inputs']: _require(payload == SALT, 'selected SDK salt must be first input')
                state['inputs'].append(payload)
                state['_hash'].update(payload)
            else:
                _require(state['inputs'], 'build missing salt/input')
                _require(state['_hash'].hexdigest() == payload, 'build digest mismatch')
                del state['_hash']
                state['sha256'] = payload
                results.append(state)
                del active[name]
                job_budget['active_build_blocks'] -= 1
                job_budget['build_blocks'] += 1
            return
        if content.startswith(b'HASH subkey '):
            match = re.match(b'HASH subkey ([0-9a-f]{64}) ',content)
            _require(match is not None, 'subkey parent framing')
            end = _quote_end(content,match.end())
            description = decode_go_quote(content[match.end():end],MAX_DECODED)
            tail = content[end:]
            _require(re.fullmatch(b' = [0-9a-f]{64}',tail) is not None, 'subkey digest framing')
            results.append(dict(kind='subkey',parent=match[1].decode(),description=description,sha256=tail[3:].decode()))
            return
        # FileHash prints an unquoted path and either digest or error text.
        _require(content.startswith(b'HASH ') and b': ' in content[5:], 'unsupported HASH framing')
        path, observation = content[5:].rsplit(b': ',1)
        _require(path and observation and b'\x00' not in path, 'FileHash diagnostic framing')
        # %v errors may contain further ': ' delimiters. Preserve this frame
        # verbatim rather than inventing an unambiguous path/error decomposition.
        results.append(dict(kind='filehash',line=content))

    for chunk in chunks:
        _require(type(chunk) is bytes and len(chunk) <= MAX_CHUNK, 'raw chunk type/bound')
        raw_total += len(chunk)
        _require(raw_total <= MAX_RAW, 'raw stderr stream budget')
        offset = 0
        while offset < len(chunk):
            newline = chunk.find(b'\n',offset)
            stop = len(chunk) if newline < 0 else newline
            piece = memoryview(chunk)[offset:stop]
            if hash_line is None:
                take = min(4-len(line),len(piece))
                line.extend(piece[:take])
                piece = piece[take:]
                if len(line) == 4:
                    hash_line = line == b'HASH'
                    if not hash_line: line.clear()
            if hash_line:
                _require(len(line)+len(piece)+1 <= MAX_LINE, 'encoded HASH line bound')
                line.extend(piece)
            if newline >= 0:
                if hash_line: consume(bytes(line)+b'\n')
                line.clear(); hash_line = None
            offset = stop+1 if newline >= 0 else stop
    _require(not hash_line, 'truncated HASH record without LF')
    _require(not active and job_budget['active_build_blocks'] == 0, 'truncated build block')
    return results


def _string(value, label):
    _require(type(value) is str and value and '\x00' not in value, label+' string')
    try:encoded=value.encode('utf-8')
    except UnicodeError as error:raise ValueError(label+' encoding') from error
    _require(len(encoded)<=256*1024,label+' bound')
    return value


def _stream(value,name):
    import build_tool_events as b1
    b1._object(value,{'segments','bytes','sha256','eof','observed_discarded_bytes','loss_unknown'},'terminal stream')
    _uint(value['bytes'],MAX_RAW);b1._digest(value['sha256'])
    _require(type(value['eof']) is bool and value['eof'],'stream missing EOF')
    _uint(value['observed_discarded_bytes'],(1<<63)-1)
    _require(value['observed_discarded_bytes']==0 and type(value['loss_unknown']) is bool and not value['loss_unknown'],'stream loss')
    segments=value['segments']
    _require(type(segments) is list and len(segments)<=30000,'stream segment count')
    total=0;parents=set()
    for index,pin in enumerate(segments,1):
        b1._pin_shape(pin,4*1024*1024)
        path=b1.Path(pin['path'])
        _require(pin['mode']==0o600 and path.name==f'{name}.{index:06d}.raw','ordered stream segment')
        if pin['bytes']==0:_require(pin['sha256']==hashlib.sha256(b'').hexdigest(),'empty segment SHA')
        parents.add(str(path.parent));total+=pin['bytes']
    _require(len(parents)<=1 and total==value['bytes'],'stream segment bytes/directory')
    if value['bytes']==0:_require(value['sha256']==hashlib.sha256(b'').hexdigest(),'empty stream SHA')
    if len(segments)==1:_require(segments[0]['sha256']==value['sha256'],'single-segment SHA')


def _coverage_plan(context,coverage):
    import build_tool_events as b1
    b1._object(coverage,{'format','driver_id','argv','required_packages','action_descriptions','zero_build_diagnostic'},'coverage plan')
    _require(coverage['format']=='om-build-coverage-v1' and coverage['driver_id']==context['driver_id'],'coverage driver')
    _require(len(b1.v1._encoded(coverage))<=256*1024,'coverage payload bound')
    b1._vector(coverage['argv'])
    config=context['_config']
    if context['driver_id']==config['root_driver']['driver_id']:
        expected=config['root_driver']['argv']
    else:
        _require(context['driver_id'] in {slot['driver_id'] for slot in config['fixture_slots']},'unregistered coverage driver')
        expected=['test','./...','-count=1']
    _require(coverage['argv']==expected,'registered coverage argv')
    rows=[row for row in config['coverage'] if row['driver_id']==context['driver_id']]
    _require(len(rows)==1,'unique driver coverage Pin')
    b1._object(rows[0],{'driver_id','plan'},'coverage Pin row')
    b1._pin_shape(rows[0]['plan'],256*1024)
    required=coverage['required_packages'];descriptions=coverage['action_descriptions']
    _require(type(required) is list and len(required)<=30000,'required package bound')
    for package in required:_string(package,'required package')
    _require(required==sorted(set(required)),'required packages sorted unique')
    _require(type(descriptions) is list and len(descriptions)<=30000,'action description bound')
    pairs=[];mapping={}
    for row in descriptions:
        b1._object(row,{'description','import_path'},'action description')
        description=_string(row['description'],'SDK description');package=_string(row['import_path'],'import path')
        _require(description not in mapping,'ambiguous action description')
        mapping[description]=package;pairs.append((description,package))
    _require(pairs==sorted(pairs),'action descriptions sorted')
    _require(type(coverage['zero_build_diagnostic']) is bool,'diagnostic boolean')
    if coverage['zero_build_diagnostic']:
        _require(coverage['argv']==['version'] and not required and not descriptions,'explicit nonsemantic diagnostic only')
    else:
        _require(required and set(required)<=set(mapping.values()),'complete released package/action inventory')
    # B3 authenticates exact plan bytes against this Pin; dict serialization is
    # not a hash oracle and does not substitute for that parent-owned boundary.
    return set(required),mapping,rows[0]['plan']['sha256']


def _flag_arrays(raw,count):
    _require(raw.endswith(b'\n'),'compiler config LF')
    end=len(raw)-1;index=0;first=[]
    for array_index in range(count):
        _require(index<end and raw[index:index+1]==b'[','compiler flag array')
        index+=1;items=0
        while index<end and raw[index:index+1]!=b']':
            if items:
                _require(raw[index:index+1]==b' ','compiler flag separator');index+=1
            stop=_quote_end(raw,index)
            value=decode_go_quote(raw[index:stop],MAX_DECODED)
            if array_index==0:
                first.append(value)
                _require(len(first)<=1,'single pinned compiler command')
            items+=1;index=stop
        _require(index<end and raw[index:index+1]==b']','compiler flag array close')
        index+=1
        if array_index<count-1:
            _require(raw[index:index+1]==b' ','compiler array separator');index+=1
    _require(index==end,'compiler config trailing tokens')
    _require(len(first)==1,'single pinned compiler command')
    return first[0]


def _host_requirements(block,policy):
    configured={};identities=[];seen_ids=set()
    hosts={host['role']:host for host in policy['host_id_probes']}
    for raw in block['inputs']:
        _require(type(raw) is bytes and len(raw)<=MAX_DECODED,'private parsed input')
        if raw.startswith((b'FC=',b'FC ID')):raise ValueError('FC identity is not released')
        for role in ('CC','CXX'):
            prefix=role.encode()
            error=prefix+b' ID ERROR='
            identity=prefix+b' ID='
            if raw.startswith(error):
                _require(raw.endswith(b'\n'),'host error LF')
                decode_go_quote(raw[len(error):-1],MAX_DECODED)
                raise ValueError(role+' ID ERROR in build trace')
            if raw.startswith(prefix+b'='):
                _require(role in hosts,'unreleased compiler role')
                tool=_flag_arrays(raw[len(prefix)+1:],4 if role=='CC' else 2)
                expected=hosts[role]['tool']['path'].encode('utf-8')
                _require(tool==expected,'compiler config pinned tool')
                configured[role]=hosts[role]
            elif raw.startswith(identity):
                _require(raw.endswith(b'\n') and role in configured,'host ID without compiler config')
                value=decode_go_quote(raw[len(identity):-1],4096)
                host=configured[role]
                identities.append((role,host['language'],host['tool']['path'],value))
                seen_ids.add(role)
    _require(set(configured)<=seen_ids,'compiler configuration missing ID input')
    return identities


def reconcile_driver(context: dict, terminal: dict, events: list[dict], blocks: list[dict], coverage: dict) -> dict:
    import build_tool_events as b1
    context=b1._resolved(context,False)
    b1._object(terminal,{'format','job_id','driver_id','go_identity','manifest','exit_code','signal',
                        'timed_out','overflow','stdout','stderr','cleanup_complete'},'driver terminal')
    _require(terminal['format']=='om-driver-terminal-v1' and terminal['job_id']==context['job_id'] and
             terminal['driver_id']==context['driver_id'],'terminal driver binding')
    b1._identity_shape(terminal['go_identity']);b1._pin_shape(terminal['manifest'],16*1024*1024)
    _require(terminal['go_identity']==context['_start']['go_identity'] and terminal['manifest']==context['_start']['manifest'],'terminal start/manifest binding')
    _require((terminal['exit_code'] is None)!=(terminal['signal'] is None),'terminal exit choice')
    if terminal['exit_code'] is not None:_uint(terminal['exit_code'],(1<<63)-1)
    if terminal['signal'] is not None:
        _uint(terminal['signal'],64);_require(terminal['signal']>0,'terminal signal')
    for key in ('timed_out','overflow','cleanup_complete'):_require(type(terminal[key]) is bool,'terminal flag type')
    _require(terminal['exit_code']==0 and terminal['signal'] is None and not terminal['timed_out']
             and not terminal['overflow'] and terminal['cleanup_complete'],'driver terminal not successful')
    _stream(terminal['stdout'],'stdout');_stream(terminal['stderr'],'stderr')
    required,mapping,coverage_sha=_coverage_plan(context,coverage)
    _require(type(blocks) is list,'private parser result list')
    builds=[row for row in blocks if row.get('kind')=='build']
    _require(all(row.get('kind') in ('build','ancillary','filehash','subkey') for row in blocks),'private parser result kind')
    built={row['package'] for row in builds}
    needs=[]
    for row in builds:needs.extend(_host_requirements(row,context['_policy']))
    _require(type(events) is list and len(events)<=512,'filtered event bound')
    starts={};host_ids={};completions=0;previous=0;sdk_packages=[];nonprobe=False
    for row in events:
        b1._object(row,b1.ENVELOPE,'filtered event')
        _uint(row['seq'],512);_require(row['seq']>previous,'filtered global sequence order');previous=row['seq']
        _require(row['format']=='om-go-tool-event-v2' and row['job_id']==context['job_id'] and
                 row['driver_id']==context['driver_id'] and row['parent_go']==context['_start']['go_identity'] and
                 row['policy_sha256']==context['policy']['sha256'],'filtered event context binding')
        b1._identity_shape(row['parent_go']);b1._identity_shape(row['recorder'])
        b1._data(row['kind'],row['data'],row,context['_policy'],context,False)
        data=row['data']
        if row['kind']=='sdk':
            if data['importpath']:_require(data['importpath'] in mapping,'unknown SDK action description')
            if data['classification']!='version-probe':
                nonprobe=True
                sdk_packages.append(mapping[data['importpath']])
        elif row['kind']=='host-start':
            nonprobe=True;starts[row['seq']]=row
            if data['importpath']:_require(data['importpath'] in mapping,'unknown host action description')
        else:
            _require(data['start_seq'] in starts,'unmatched/duplicate host completion')
            start=starts.pop(data['start_seq'])
            _require(all(row[key]==start[key] for key in ('driver_id','parent_go','recorder','policy_sha256')),'host completion identity binding')
            _require(data['outcome']=='ok','failed host completion despite parent status')
            release=b1._blob(data['release_id'],4096)
            key=(start['data']['role'],start['data']['language'],start['data']['tool']['path'])
            _require(key not in host_ids or host_ids[key]==release,'inconsistent repeated host identity')
            host_ids[key]=release;completions+=1
    _require(not starts,'unmatched host start')
    for role,language,tool,identity in needs:
        _require(host_ids.get((role,language,tool))==identity,'missing same-driver matching host identity')
    if coverage['zero_build_diagnostic']:
        _require(not builds and not nonprobe and completions==0,'diagnostic has semantic/host action')
    else:
        _require(builds,'missing complete build trace')
        _require(required<=built,'missing required package coverage')
        _require(built<=set(mapping.values()),'unreleased build package/action')
        _require(all(package in built for package in sdk_packages),'SDK action lacks build trace')
    return dict(format='om-build-coverage-result-v1',job_id=context['job_id'],driver_id=context['driver_id'],
                coverage_sha256=coverage_sha,build_blocks=len(builds),covered_packages=sorted(built),
                host_completions=completions,**{'pass':True})
