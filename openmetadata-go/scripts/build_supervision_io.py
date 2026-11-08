# SPDX-License-Identifier: Apache-2.0
"""Shared bounded raw capture and durable reservations."""
from contextlib import contextmanager
import ctypes
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import selectors
import signal
import stat
import struct
import subprocess
import time
import build_tool_events as b1

RAW_LIMIT=33554432
CHUNK=65536
SEGMENT=4194304


def _require(ok,message):
    if not ok:raise ValueError(message)


@contextmanager
def _counter(job_root,label='raw',deadline=None):
    _require(label in ('raw','captures'),'counter label')
    with b1._directory(Path(job_root)) as parent:
        _assert_job(job_root)
        info=os.fstat(parent)
        _require(info.st_uid==os.geteuid() and stat.S_IMODE(info.st_mode)==0o700,'private counter root')
        lock=os.open(label+'-lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=parent)
        fd=None
        try:
            info=os.fstat(lock)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.geteuid()
                     and stat.S_IMODE(info.st_mode)==0o600,'unsafe reservation lock')
            _lock(lock,deadline or time.monotonic_ns()+10_000_000_000)
            try:
                fd=os.open(label+'-reserved',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
                fresh=True
            except FileExistsError:
                fd=os.open(label+'-reserved',os.O_RDWR|os.O_NOFOLLOW,dir_fd=parent);fresh=False
            info=os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.geteuid()
                     and stat.S_IMODE(info.st_mode)==0o600,'unsafe reservation file')
            if fresh:
                _require(os.pwrite(fd,struct.pack('>Q',0),0)==8,'short counter initialization')
                os.fsync(fd);os.fsync(parent)
            _require(os.fstat(fd).st_size==8,'incomplete reservation counter')
            yield fd
        except (ValueError,OSError):
            _poison(job_root,'accounting refused')
            raise
        finally:
            if fd is not None:os.close(fd)
            os.close(lock)


def reserved_raw(job_root):
    with _counter(job_root) as fd:
        return struct.unpack('>Q',os.pread(fd,8,0))[0]


def reserve_raw(job_root: Path, count: int) -> int:
    return _reserve_raw(job_root,count,None)


def _reserve_raw(job_root,count,deadline):
    _require(type(count) is int and 0<=count<=CHUNK,'raw chunk bound/type')
    with _counter(job_root,deadline=deadline) as fd:
        previous=struct.unpack('>Q',os.pread(fd,8,0))[0]
        _require(previous<=RAW_LIMIT and count<=RAW_LIMIT-previous,'shared raw byte budget')
        total=previous+count
        _require(os.pwrite(fd,struct.pack('>Q',total),0)==8,'short reservation write')
        os.fsync(fd)
        return total


def capture_streams(process: subprocess.Popen, job_root: Path, driver_root: Path, deadline_ns: int) -> dict:
    _require(type(deadline_ns) is int and deadline_ns>0,'capture deadline')
    job_root=b1._physical(str(job_root),True)
    driver_root=b1._physical(str(driver_root),True)
    _require(job_root in driver_root.parents,'capture root containment')
    identity=b1._process(process.pid)[0]
    owner=getattr(process,'_om_owner',None)
    if not getattr(process,'_om_capture_reserved',False):
        try:_reserve_capture(job_root)
        except (ValueError,OSError):
            try:
                until=owner._begin_cleanup() if owner is not None else time.monotonic_ns()+20_000_000_000
                if owner is not None:owner.cancel()
                else:_signal_owned(identity,signal.SIGKILL)
                process.wait(timeout=max(0,(until-time.monotonic_ns())/1e9))
            finally:
                for stream in (process.stdout,process.stderr):
                    if stream is not None:stream.close()
                if owner is not None:owner.finish()
            raise
        process._om_capture_reserved=True
    writers={name:_RawWriter(job_root,driver_root,name,deadline_ns) for name in ('stdout','stderr')}
    streams={name:getattr(process,name) for name in writers}
    eof={name:False for name in writers};lost={name:0 for name in writers}
    timed_out=False;overflow=False;failed=False;stopping=False;cleanup_deadline=None
    finalization_errors=[]
    with selectors.DefaultSelector() as selector:
        try:
            for name,stream in streams.items():
                _require(stream is not None,'capture requires owned pipes')
                os.set_blocking(stream.fileno(),False)
                selector.register(stream,selectors.EVENT_READ,name)
            while selector.get_map() or process.poll() is None:
                now=time.monotonic_ns()
                if not stopping and now>=deadline_ns:timed_out=True;stopping=True
                if failed:_poison(job_root,'capture IO/ownership refused')
                if failed or overflow:stopping=True
                if stopping and cleanup_deadline is None:
                    cleanup_deadline=owner._begin_cleanup() if owner is not None else now+20_000_000_000
                    if owner is not None:owner.cancel()
                    else:_signal_owned(identity,signal.SIGKILL)
                if owner is not None:
                    owner.deadline=owner.cleanup_deadline or deadline_ns
                    try:owner.tick()
                    except (ValueError,OSError):failed=True
                    failed=failed or owner.failed
                if failed and not stopping:
                    stopping=True
                    continue
                if cleanup_deadline is not None and now>=cleanup_deadline:break
                wait_until=cleanup_deadline if stopping else deadline_ns
                for key,_ in selector.select(max(0,min(.05,(wait_until-now)/1e9))):
                    name=key.data
                    try:raw=os.read(key.fd,CHUNK)
                    except BlockingIOError:continue
                    except OSError:
                        failed=True;selector.unregister(key.fileobj);continue
                    if not raw:
                        eof[name]=True;selector.unregister(key.fileobj);continue
                    if failed or overflow:
                        lost[name]+=len(raw);continue
                    before=writers[name].size
                    try:writers[name].feed(raw)
                    except (ValueError,OSError) as error:
                        lost[name]+=len(raw)-(writers[name].size-before)
                        if isinstance(error,ValueError) and str(error)=='shared raw byte budget':overflow=True
                        else:failed=True
            if process.poll() is None:
                if owner is not None:owner.cancel()
                else:_signal_owned(identity,signal.SIGKILL)
            remaining=max(0,((cleanup_deadline or deadline_ns)-time.monotonic_ns())/1e9)
            try:process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:failed=True
        finally:
            for name,stream in streams.items():
                try:
                    if stream is not None:stream.close()
                except (ValueError,OSError) as error:
                    failed=True
                    finalization_errors.append(dict(resource=name+' pipe',error=type(error).__name__,errno=getattr(error,'errno',None)))
            for name,writer in writers.items():
                try:writer.close()
                except (ValueError,OSError) as error:
                    failed=True
                    finalization_errors.append(dict(resource=name+' raw',error=type(error).__name__,errno=getattr(error,'errno',None)))
    cleanup=process.returncode is not None and all(eof.values())
    if owner is not None:
        try:cleanup=owner.finish() and cleanup
        except (ValueError,OSError) as error:
            failed=True;cleanup=False
            finalization_errors.append(dict(resource='ownership',error=type(error).__name__,errno=getattr(error,'errno',None)))
        failed=failed or owner.failed
    if failed:_poison(job_root,'capture IO/ownership refused')
    try:result={name:writer.result(eof[name],lost[name],not eof[name]) for name,writer in writers.items()}
    except (ValueError,OSError):
        _poison(job_root,'capture readback refused')
        raise
    code=process.returncode
    result.update(exit_code=code if code is not None and code>=0 else None,
                  signal=-code if code is not None and code<0 else None,timed_out=timed_out,
                  overflow=overflow,cleanup_complete=cleanup,_io_error=failed,
                  _finalization_errors=finalization_errors)
    return result


def _signal_owned(identity,number):
    try:
        actual=b1._process(identity['pid'])[0]
        _require(actual==identity,'owned PID reused')
        fd=os.pidfd_open(identity['pid'])
        try:
            _require(b1._process(identity['pid'])[0]==identity,'owned PID changed')
            signal.pidfd_send_signal(fd,number)
        finally:os.close(fd)
    except ProcessLookupError:pass
    except FileNotFoundError:pass


class _RawWriter:
    def __init__(self,job_root,driver_root,name,deadline=None):
        self.job_root=job_root;self.driver_root=driver_root;self.name=name;self.deadline=deadline
        self.fd=None;self.segment_size=0;self.size=0;self.paths=[]

    def feed(self,raw):
        _reserve_raw(self.job_root,len(raw),self.deadline)
        offset=0
        while offset<len(raw):
            if self.fd is None:
                path=self.driver_root/(self.name+'.'+str(len(self.paths)+1).zfill(6)+'.raw')
                with b1._directory(self.driver_root) as parent:
                    self.fd=os.open(path.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
                    os.fsync(parent)
                self.paths.append(path);self.segment_size=0
            part=raw[offset:offset+min(len(raw)-offset,SEGMENT-self.segment_size)]
            count=os.write(self.fd,part)
            self.size+=count;self.segment_size+=count;offset+=count
            _require(count==len(part),'short raw write')
            if self.segment_size==SEGMENT:self.close()

    def close(self):
        if self.fd is not None:
            fd=self.fd;self.fd=None
            try:os.fsync(fd)
            finally:os.close(fd)

    def result(self,eof,lost,unknown):
        import partitioned_source_guard as source
        pins=[];digest=hashlib.sha256();total=0
        for path in self.paths:
            with b1._directory(self.driver_root) as parent:
                before=os.stat(path.name,dir_fd=parent,follow_symlinks=False)
                _require(stat.S_ISREG(before.st_mode) and before.st_uid==os.geteuid() and before.st_nlink==1
                         and stat.S_IMODE(before.st_mode)==0o600 and before.st_size<=SEGMENT,'unsafe raw file')
                fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
                try:
                    info=os.fstat(fd)
                    _require(source._identity(before)==source._identity(info),'raw file changed before open')
                    segment_hash=hashlib.sha256();count=0
                    while True:
                        raw=os.read(fd,min(CHUNK,info.st_size-count+1))
                        if not raw:break
                        count+=len(raw);_require(count<=info.st_size,'raw file grew')
                        segment_hash.update(raw);digest.update(raw)
                    _require(count==info.st_size and source._identity(info)==source._identity(os.fstat(fd)) and
                             source._identity(info)==source._identity(os.stat(path.name,dir_fd=parent,follow_symlinks=False)),
                             'raw file changed')
                finally:os.close(fd)
            pins.append(dict(path=str(path),bytes=count,sha256=segment_hash.hexdigest(),mode=0o600))
            total+=count
        _require(total==self.size,'persisted raw byte count')
        return dict(segments=pins,bytes=total,sha256=digest.hexdigest(),eof=eof,
                    observed_discarded_bytes=lost,loss_unknown=unknown)


class _Ownership:
    def __init__(self,job_root=None):
        self.libc=ctypes.CDLL(None,use_errno=True)
        previous=ctypes.c_int()
        _require(self.libc.prctl(37,ctypes.byref(previous),0,0,0)==0,'read subreaper status')
        _require(self.libc.prctl(36,1,0,0,0)==0,'install owned subreaper')
        self.previous=previous.value;self.parent=os.getpid();self.job_root=job_root
        self.identities=[];self.known={};self.waits=[];self.process=None
        self.failed=False;self.cancelling=False;self.deadline=None;self.cleanup_deadline=None
        self.baseline={pid for pid,row in _proc_snapshot().items() if row['ppid']==self.parent}

    def bind(self,process):
        identity,parent=b1._process(process.pid)
        _require(parent==self.parent,'capture child is not owned')
        self.process=process;self.root=identity
        self._add(identity)

    def _add(self,identity):
        key=(identity['pid'],identity['start_ticks'])
        if key not in self.known:
            _require(len(self.known)<256,'lifetime owned identity bound')
            self.known[key]=dict(identity);self.identities.append(dict(identity))
            if self.job_root is not None:_reserve_identity(self.job_root,identity,self.deadline)

    def tick(self):
        snapshot=_proc_snapshot(self.deadline)
        parents={identity['pid'] for identity in self.identities}
        for identity in self.identities:
            row=snapshot.get(identity['pid'])
            _require(row is None or row['start_ticks']==identity['start_ticks'],'owned PID reuse')
        changed=True
        while changed:
            changed=False
            for pid,row in snapshot.items():
                direct=row['ppid']==self.parent and pid not in self.baseline
                if row['ppid'] not in parents and not direct:continue
                key=(pid,row['start_ticks'])
                if key in self.known:
                    if direct and self.known[key]!=self.root and not self.cancelling:self.failed=True
                    continue
                identity=dict(pid=pid,start_ticks=row['start_ticks'])
                try:current,parent=b1._process(pid)
                except (FileNotFoundError,ProcessLookupError):continue
                _require(current==identity and parent==row['ppid'],'ownership census changed')
                self._add(identity);parents.add(pid);changed=True
                if direct and identity!=self.root and not self.cancelling:self.failed=True
        for identity in self.identities:
            row=snapshot.get(identity['pid'])
            if row is None or row['state']!='Z' or row['ppid']!=self.parent:continue
            if identity==self.root:continue
            _require(b1._process(identity['pid'])[0]==identity,'adopted identity changed')
            try:pid,status=os.waitpid(identity['pid'],os.WNOHANG)
            except ChildProcessError:raise ValueError('adopted child wait ownership lost')
            if pid:self.waits.append(dict(identity=identity,status=status))

    def _begin_cleanup(self):
        if self.cleanup_deadline is None:self.cleanup_deadline=time.monotonic_ns()+20_000_000_000
        self.deadline=self.cleanup_deadline
        return self.cleanup_deadline

    def cancel(self):
        self._begin_cleanup();self.cancelling=True
        try:self.tick()
        except (ValueError,OSError):self.failed=True
        parents={identity['pid'] for identity in self.identities}|{self.parent}
        for identity in reversed(self.identities):
            try:
                current,parent=b1._process(identity['pid'])
                _require(current==identity and parent in parents,'cancel identity/ownership changed')
                _signal_owned(identity,signal.SIGKILL)
            except (FileNotFoundError,ProcessLookupError):pass

    def finish(self):
        deadline=self._begin_cleanup();quiet=0
        while time.monotonic_ns()<deadline:
            try:
                self.tick()
                present=[]
                for identity in self.identities:
                    try:current,_=b1._process(identity['pid'])
                    except (FileNotFoundError,ProcessLookupError):continue
                    _require(current==identity,'finish identity reused')
                    present.append(identity)
                if not present:
                    quiet+=1
                    if quiet==2:
                        _require(self.libc.prctl(36,self.previous,0,0,0)==0,'restore subreaper status')
                        return True
                else:
                    quiet=0;self.failed=True;self.cancel()
            except (ValueError,OSError):self.failed=True;return False
            time.sleep(.005)
        self.failed=True
        return False


def _proc_snapshot(deadline=None):
    until=min(time.monotonic_ns()+250_000_000,deadline) if deadline is not None else time.monotonic_ns()+250_000_000
    rows={};count=0
    with os.scandir('/proc') as entries:
        for entry in entries:
            if not entry.name.isascii() or not entry.name.isdecimal():continue
            count+=1
            _require(count<=30000 and time.monotonic_ns()<until,'incomplete process census bound')
            try:
                fd=os.open('/proc/'+entry.name+'/stat',os.O_RDONLY|os.O_NOFOLLOW)
                try:raw=os.read(fd,65537)
                finally:os.close(fd)
            except OSError as error:
                if error.errno in (errno.ENOENT,errno.ESRCH):continue
                raise ValueError('unreadable process census') from error
            _require(len(raw)<=65536 and time.monotonic_ns()<until,'incomplete process stat/time bound')
            try:
                fields=raw[raw.rfind(b')')+2:].split()
                pid=int(raw.split(b' ',1)[0]);parent=int(fields[1]);start=int(fields[19])
                _require(pid==int(entry.name) and pid>0 and parent>=0 and start>0,'process stat identity')
                rows[pid]=dict(ppid=parent,start_ticks=start,state=fields[0].decode('ascii'))
            except (ValueError,IndexError,UnicodeError) as error:raise ValueError('invalid process stat') from error
    return rows


def authenticate_stream(driver_root,name,stream):
    import build_hash_trace as trace
    import partitioned_source_guard as source
    _require(name in ('stdout','stderr'),'stream name')
    driver_root=b1._physical(str(driver_root),True)
    trace._stream(stream,name)
    aggregate=hashlib.sha256();total=0
    for index,pin in enumerate(stream['segments'],1):
        expected=driver_root/(name+'.'+str(index).zfill(6)+'.raw')
        _require(pin['path']==str(expected) and pin['mode']==0o600,'raw stream driver/name binding')
        try:
            with source._directory(driver_root) as parent:
                fd=os.open(expected.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
                try:
                    before=os.fstat(fd);b1._check_pin_stat(before,pin)
                    digest=hashlib.sha256();count=0
                    while True:
                        chunk=os.read(fd,min(CHUNK,pin['bytes']-count+1))
                        if not chunk:break
                        count+=len(chunk);total+=len(chunk)
                        _require(count<=pin['bytes'] and total<=RAW_LIMIT,'raw segment grew/stream bound')
                        digest.update(chunk);aggregate.update(chunk)
                        yield chunk
                    _require(count==pin['bytes'] and digest.hexdigest()==pin['sha256'],'raw segment bytes/SHA mismatch')
                    _require(source._identity(before)==source._identity(os.fstat(fd)) and
                             source._identity(before)==source._identity(os.stat(expected.name,dir_fd=parent,follow_symlinks=False)),
                             'raw segment changed/replaced during read')
                finally:os.close(fd)
        except OSError as error:raise ValueError('unavailable/unsafe retained stream') from error
    _require(total==stream['bytes'] and aggregate.hexdigest()==stream['sha256'],'raw aggregate bytes/SHA mismatch')


def _reserve_capture(job_root):
    with _counter(job_root,'captures') as fd:
        previous=struct.unpack('>Q',os.pread(fd,8,0))[0]
        _require(previous<128,'capture bound')
        _require(os.pwrite(fd,struct.pack('>Q',previous+1),0)==8,'short capture reservation')
        os.fsync(fd)
        return previous+1


def _reserve_identity(job_root,identity,deadline=None):
    b1._identity_shape(identity)
    _assert_job(job_root)
    with b1._directory(Path(job_root)) as parent:
        fd=os.open('identities',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=parent)
        try:
            info=os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.geteuid() and
                     stat.S_IMODE(info.st_mode)==0o600 and info.st_size<=65536,'identity ledger bound/type')
            _lock(fd,deadline or time.monotonic_ns()+10_000_000_000)
            raw=os.read(fd,65537);_require(len(raw)<=65536,'identity ledger bytes')
            rows=[];seen=set()
            for line in raw.splitlines(keepends=True):
                row=b1._strict(line,256);b1._identity_shape(row)
                _require(b1.v1._encoded(row)+b'\n'==line,'identity ledger encoding')
                key=(row['pid'],row['start_ticks']);_require(key not in seen,'duplicate identity ledger')
                seen.add(key);rows.append(row)
                _require(len(rows)<=256,'lifetime identity bound')
            key=(identity['pid'],identity['start_ticks'])
            if key in seen:return len(rows)
            _require(len(rows)<256,'lifetime identity bound')
            encoded=b1.v1._encoded(identity)+b'\n'
            _require(os.write(fd,encoded)==len(encoded),'short identity reservation')
            os.fsync(fd);os.fsync(parent)
            return len(rows)+1
        except (ValueError,OSError):
            _poison(job_root,'identity accounting refused')
            raise
        finally:os.close(fd)


def _assert_job(job_root):
    with b1._directory(Path(job_root)) as parent:
        try:os.stat('job-failed',dir_fd=parent,follow_symlinks=False)
        except FileNotFoundError:return
    raise ValueError('job previously failed')


def _poison(job_root,reason):
    with b1._directory(Path(job_root)) as parent:
        try:fd=os.open('job-failed',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
        except FileExistsError:return
        try:
            raw=b1.v1._encoded(dict(error=reason))+b'\n'
            _require(os.write(fd,raw)==len(raw),'short failure evidence write')
            os.fsync(fd)
        finally:os.close(fd)
        os.fsync(parent)


def _lock(fd,deadline_ns):
    while time.monotonic_ns()<deadline_ns:
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return
        except BlockingIOError:
            time.sleep(min(.005,max(0,(deadline_ns-time.monotonic_ns())/1e9)))
    raise ValueError('accounting/control lock deadline')
