# SPDX-License-Identifier: Apache-2.0
"""Fail-closed selected-tool admission and durable pre-exec records.

The supervising wrapper owns job cwd, source checks, complete flags and child
attribution. This recorder preserves the selected tool's cwd/environment/I/O.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from partitioned_source_guard import (_absolute, _check_info, _digest, _directory,
    _file_at, _identity, _integer, _json, _require)

MODULE = "github.com/rafi566/OpenMetadata-Go/openmetadata-go"
POLICY_LIMIT = 256 * 1024
ARG_LIMIT = 64 * 1024
TOOL_LIMIT = 64 * 1024 * 1024
BOUNDS = dict(max_records=512, max_argument_bytes=8*1024*1024,
              max_record_bytes=128*1024, max_journal_bytes=16*1024*1024)
KEYS = {"format", "module", "mode", "working_directory", "toolchain_root", "tools",
        "record_directory", "compile_scope", "response_files", "required_go_flags", *BOUNDS}
ROW_KEYS = {"format", "policy_sha256", "pid", "start_ticks", "argv", "importpath",
            "tool", "classification", "compiler_c", "cwd"}


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def load_policy(raw: bytes) -> dict:
    policy = _json(raw, POLICY_LIMIT)
    _require(type(policy) is dict and set(policy) == KEYS, "policy keys")
    _require(policy["format"] == "om-go-tool-record-policy-v1", "policy format")
    _require(policy["module"] == MODULE and policy["mode"] in ("normal", "race"), "module/mode")
    for key in BOUNDS:
        _require(type(policy[key]) is int and policy[key] == BOUNDS[key], "fixed budget")
    _require(policy["compile_scope"] == MODULE+"/..." and policy["response_files"] == "reject", "scope")
    required = {"-p=1", "-mod=readonly", "-gcflags="+MODULE+"/...=-c=1"}
    if policy["mode"] == "race":
        required.add("-race")
    flags = policy["required_go_flags"]
    _require(type(flags) is list and all(type(x) is str for x in flags)
             and len(flags) == len(required) and set(flags) == required, "required flags")
    paths = {key: _absolute(policy[key]) for key in
             ("working_directory", "toolchain_root", "record_directory")}
    source, records = paths["working_directory"], paths["record_directory"]
    _require(source != records and source not in records.parents and records not in source.parents,
             "records must be outside sources")
    for key in paths:
        with _directory(paths[key]) as fd:
            info = os.fstat(fd)
            _require(info.st_uid == os.getuid(), "directory owner")
            if key == "record_directory":
                _require(stat.S_IMODE(info.st_mode) == 0o700, "record directory mode")
    tools = policy["tools"]
    _require(type(tools) is list and 1 <= len(tools) <= 16, "tool count")
    names = []
    parent = paths["toolchain_root"] / "pkg/tool/linux_amd64"
    for row in tools:
        _require(type(row) is dict and set(row) == {"path", "bytes", "sha256", "mode"}, "tool keys")
        tool = _absolute(row["path"])
        _require(tool.parent == parent, "SDK tool parent")
        _integer(row["bytes"], TOOL_LIMIT)
        _integer(row["mode"], 0o777)
        _digest(row["sha256"])
        _require(row["mode"] & 0o111, "tool executable mode")
        with _directory(parent) as fd:
            _check_info(os.stat(tool.name, dir_fd=fd, follow_symlinks=False), row, TOOL_LIMIT)
        names.append(row["path"])
    _require(names == sorted(set(names)), "tool order/duplicates")
    return policy


def _classification(tool, args, importpath):
    _require(type(importpath) is str and "\x00" not in importpath, "import path")
    _require(all(type(arg) is str and "\x00" not in arg and not arg.startswith("@") for arg in args),
             "response file/argument")
    if args == ["-V=full"]:
        return "version-probe", None
    if Path(tool).name != "compile":
        return "tool", None
    # cmd/go appends a bracketed test variant to the original import path.
    package = importpath.split(" [", 1)[0]
    _require(package and not any(c.isspace() for c in package), "unknown compile package")
    value = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-c":
            i += 1
            _require(i < len(args), "missing -c value")
            value = args[i]
        elif arg.startswith("-c="):
            value = arg[3:]
        i += 1
    if package == MODULE or package.startswith(MODULE+"/"):
        _require(value == "1", "module compiler requires last -c=1")
        return "module-compile", value
    return "external-compile", value


def _argument_bytes(argv):
    _require(type(argv) is list and argv and all(type(x) is str for x in argv), "argv shape")
    count = len(_encoded(argv))
    _require(count <= ARG_LIMIT, "argv budget")
    return count


def _validate_record(row, policy, policy_sha):
    _require(type(row) is dict and set(row) == ROW_KEYS, "record keys")
    _require(row["format"] == "om-go-tool-record-v1" and row["policy_sha256"] == policy_sha, "record policy")
    _require(type(row["pid"]) is int and row["pid"] > 0
             and type(row["start_ticks"]) is int and row["start_ticks"] > 0, "record identity")
    size = _argument_bytes(row["argv"])
    _require(row["tool"] in policy["tools"] and row["argv"][0] == row["tool"]["path"], "record tool")
    classification, c = _classification(row["argv"][0], row["argv"][1:], row["importpath"])
    _require(row["classification"] == classification and row["compiler_c"] == c, "record classification")
    _absolute(row["cwd"])
    return size


def _read_file(path, limit):
    path = _absolute(path)
    with _directory(path.parent) as parent:
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                 and before.st_uid == os.getuid() and before.st_size <= limit, "policy file")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            _require(_identity(before) == _identity(os.fstat(fd)), "policy identity")
            pieces = []
            total = 0
            while True:
                data = os.read(fd, min(65536, limit-total+1))
                if not data:
                    break
                total += len(data)
                _require(total <= limit, "policy byte bound")
                pieces.append(data)
            _require(_identity(before) == _identity(os.fstat(fd)) ==
                     _identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)), "changed policy")
            return b"".join(pieces)
        finally:
            os.close(fd)


def _start_ticks():
    # /proc stat comm can contain spaces and parentheses; fields after its last ')'.
    raw = Path("/proc/self/stat").read_text()
    return int(raw[raw.rfind(")")+2:].split()[19])


def _journal_info(fd, parent):
    info = os.fstat(fd)
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
             and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600, "journal metadata")
    _require(_identity(info) == _identity(os.stat("records.jsonl", dir_fd=parent, follow_symlinks=False)),
             "journal identity")
    return info


def _record_and_exec(policy, policy_sha, tool, argv):
    args_bytes = _argument_bytes(argv)
    classification, c = _classification(tool["path"], argv[1:], os.environ.get("TOOLEXEC_IMPORTPATH", ""))
    row = dict(format="om-go-tool-record-v1", policy_sha256=policy_sha, pid=os.getpid(),
               start_ticks=_start_ticks(), argv=argv, importpath=os.environ.get("TOOLEXEC_IMPORTPATH", ""),
               tool=tool, classification=classification, compiler_c=c, cwd=os.getcwd())
    encoded = _encoded(row)+b"\n"
    _require(len(encoded) <= policy["max_record_bytes"], "record byte bound")
    with _directory(Path(policy["record_directory"])) as parent:
        directory = os.fstat(parent)
        _require(directory.st_uid == os.getuid() and stat.S_IMODE(directory.st_mode) == 0o700, "record directory")
        fd = os.open("records.jsonl", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            info = _journal_info(fd, parent)
            _require(info.st_size + len(encoded) <= policy["max_journal_bytes"], "journal byte bound")
            count = total = read_bytes = 0
            # A duplicate FD shares the locked description and offset. readline is bounded.
            with os.fdopen(os.dup(fd), "rb") as stream:
                while True:
                    line = stream.readline(policy["max_record_bytes"]+1)
                    if not line:
                        break
                    read_bytes += len(line)
                    _require(len(line) <= policy["max_record_bytes"] and line.endswith(b"\n"), "record framing")
                    count += 1
                    _require(count < policy["max_records"], "record count")
                    total += _validate_record(_json(line, policy["max_record_bytes"]), policy, policy_sha)
                    _require(total + args_bytes <= policy["max_argument_bytes"], "argument total")
            _require(read_bytes == info.st_size and _identity(info) == _identity(_journal_info(fd, parent)), "changed journal")
            with _directory(Path(tool["path"]).parent) as tool_parent:
                tool_before = os.stat(Path(tool["path"]).name, dir_fd=tool_parent, follow_symlinks=False)
                _file_at(tool_parent, Path(tool["path"]).name, tool, TOOL_LIMIT)
                os.lseek(fd, 0, os.SEEK_END)
                remaining = memoryview(encoded)
                while remaining:
                    written = os.write(fd, remaining)
                    _require(written > 0, "short journal write")
                    remaining = remaining[written:]
                os.fsync(fd)
                _require(_journal_info(fd, parent).st_size == info.st_size+len(encoded), "journal persistence")
                _require(_identity(tool_before) == _identity(os.stat(Path(tool["path"]).name,
                         dir_fd=tool_parent, follow_symlinks=False)), "tool changed after hashing")
                # Reopen all canonical ancestors immediately before exec; successful
                # exec does not return through context-manager exit checks.
                for directory_path, held in ((Path(tool["path"]).parent, tool_parent),
                                             (Path(policy["record_directory"]), parent)):
                    with _directory(directory_path) as current:
                        _require(_identity(os.fstat(current)) == _identity(os.fstat(held)),
                                 "exec ancestry replaced")
                # Python descriptors are close-on-exec: lock remains through admission,
                # and is released by successful exec (or finally on any failure).
                os.execv(tool["path"], argv)
        finally:
            os.close(fd)


def main(argv: list[str]) -> int:
    v2 = False
    try:
        _require(len(argv) >= 5 and argv[0] == "--policy" and argv[2] == "--policy-sha256", "invocation")
        _digest(argv[3])
        raw = _read_file(argv[1], POLICY_LIMIT)
        _require(hashlib.sha256(raw).hexdigest() == argv[3], "policy SHA mismatch")
        parsed = _json(raw, POLICY_LIMIT)
        if type(parsed) is dict and parsed.get('format') == 'om-go-tool-record-policy-v2':
            v2 = True
            from build_tool_events import dispatch_v2
            status = dispatch_v2(raw, argv[1], argv[3], argv[4:])
            if status < 0:
                import signal
                signum = -status
                if signum not in (signal.SIGKILL, signal.SIGSTOP):
                    signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)
                return 1
            return status
        policy = load_policy(raw)
        selected = next((row for row in policy["tools"] if row["path"] == argv[4]), None)
        _require(selected is not None, "unpinned tool")
        _record_and_exec(policy, argv[3], selected, argv[4:])
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        if v2:
            from build_tool_events import _refusal_diagnostic
            _refusal_diagnostic(error)
        else:
            print("tool recorder refused: "+str(error), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
