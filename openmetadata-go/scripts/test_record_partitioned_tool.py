# SPDX-License-Identifier: Apache-2.0
"""Real owned toy Python tools, never Go SDK executables."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from record_partitioned_tool import load_policy

MODULE = "github.com/rafi566/OpenMetadata-Go/openmetadata-go"
RECORDER = Path(__file__).with_name("record_partitioned_tool.py")


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.sdk = self.root / "sdk"
        self.tools = self.sdk / "pkg/tool/linux_amd64"
        self.tools.mkdir(parents=True)
        self.tool = self.tools / "compile"
        self.tool.write_text("#!" + sys.executable + " -B\nimport os,sys\nfrom pathlib import Path\nPath(os.environ['TOY_MARKER']).write_text(os.getcwd())\nprint('TOY stdout', repr(sys.argv[1:]))\nprint('TOY stderr',file=sys.stderr)\nraise SystemExit(37)\n")
        self.tool.chmod(0o700)
        self.records = self.root / "records"
        self.records.mkdir(mode=0o700)
        self.journal = self.records / "records.jsonl"
        self.journal.touch(mode=0o600)
        self.marker = self.root / "executed"
        self.policy_path = self.root / "policy.json"
        self.policy = dict(format="om-go-tool-record-policy-v1", module=MODULE,
            mode="normal", working_directory=str(self.source), toolchain_root=str(self.sdk),
            tools=[dict(path=str(self.tool), bytes=self.tool.stat().st_size,
                        sha256=hashlib.sha256(self.tool.read_bytes()).hexdigest(), mode=0o700)],
            record_directory=str(self.records), compile_scope=MODULE+"/...", response_files="reject",
            max_records=512, max_argument_bytes=8*1024*1024, max_record_bytes=128*1024,
            max_journal_bytes=16*1024*1024,
            required_go_flags=["-p=1", "-mod=readonly", "-gcflags="+MODULE+"/...=-c=1"])

    def command(self, args, importpath=MODULE, cwd=None, policy_raw=None, expected_sha=None, prefix=None):
        raw = json.dumps(self.policy).encode() if policy_raw is None else policy_raw
        self.policy_path.write_bytes(raw)
        self.policy_path.chmod(0o600)
        env = dict(os.environ, TOOLEXEC_IMPORTPATH=importpath, TOY_MARKER=str(self.marker))
        cli = ["--policy", str(self.policy_path), "--policy-sha256",
               expected_sha or hashlib.sha256(raw).hexdigest(), str(self.tool), *args]
        command = [sys.executable, "-B", str(RECORDER), *cli]
        if prefix:
            command = [sys.executable, "-B", "-c", prefix, *cli]
        return subprocess.run(command, cwd=cwd or self.source, env=env,
                              capture_output=True, timeout=10)

    def rows(self):
        return [json.loads(line) for line in self.journal.read_text().splitlines()]

    def refused(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(result.returncode, 37)
        self.assertFalse(self.marker.exists(), result.stderr)

    def test_exact_child_exit_output_argv_and_identity(self):
        result = self.command(["-c=1", "space argument"])
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertIn(b"TOY stdout", result.stdout)
        self.assertEqual(result.stderr, b"TOY stderr\n")
        row, = self.rows()
        self.assertEqual(row["argv"], [str(self.tool), "-c=1", "space argument"])
        self.assertEqual(row["importpath"], MODULE)
        self.assertEqual(row["classification"], "module-compile")
        self.assertGreater(row["pid"], 0)
        self.assertGreater(row["start_ticks"], 0)
        self.assertEqual(row["tool"], self.policy["tools"][0])

    def test_c_last_value_and_test_variant(self):
        good = self.command(["-c=7", "-c", "1"], MODULE+"/schema ["+MODULE+"/schema.test]")
        self.assertEqual(good.returncode, 37, good.stderr)
        self.marker.unlink()
        self.refused(self.command(["-c=1", "-c", "2"]))
        self.assertEqual(len(self.rows()), 1)

    def test_stdlib_probe_and_actual_nested_cwd(self):
        nested = self.source / "nested"
        nested.mkdir()
        result = self.command(["-c=8"], "encoding/json", cwd=nested)
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(self.marker.read_text(), str(nested))
        self.assertEqual(self.rows()[0]["cwd"], str(nested))
        self.assertEqual(self.rows()[0]["classification"], "external-compile")
        self.marker.unlink()
        result = self.command(["-V=full"], "")
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(self.rows()[1]["classification"], "version-probe")

    def test_response_oversize_unknown_compile_and_nonexact_probe_refused(self):
        for args, scope in [(["@args", "-c=1"], MODULE), (["x"*65536], MODULE),
                            (["-c=1"], ""), (["-V=full", "extra"], "")]:
            with self.subTest(args=args[0][:40]):
                self.refused(self.command(args, scope))
        self.assertEqual(self.journal.read_bytes(), b"")

    def test_policy_hash_tool_bytes_and_unpinned_path_refused(self):
        self.refused(self.command(["-c=1"], expected_sha="0"*64))
        self.tool.write_text(self.tool.read_text()+"#changed\n")
        self.refused(self.command(["-c=1"]))
        self.assertEqual(self.journal.read_bytes(), b"")

    def test_missing_linked_wrong_mode_and_malformed_journal_refused(self):
        self.journal.unlink()
        self.refused(self.command(["-c=1"]))
        self.assertFalse(self.journal.exists())
        other = self.root / "other"
        other.touch(mode=0o600)
        self.journal.symlink_to(other)
        self.refused(self.command(["-c=1"]))
        self.journal.unlink()
        os.link(other, self.journal)
        self.refused(self.command(["-c=1"]))
        self.journal.unlink()
        self.journal.touch(mode=0o644)
        self.journal.chmod(0o644)
        self.refused(self.command(["-c=1"]))
        self.journal.chmod(0o600)
        self.journal.write_bytes(b'{"partial":')
        self.refused(self.command(["-c=1"]))

    def test_persistence_failure_blocks_real_child(self):
        prefix = "import sys;sys.path.insert(0,"+repr(str(RECORDER.parent))+");import record_partitioned_tool as r\ndef fail(fd): raise OSError('injected fsync failure')\nr.os.fsync=fail\nraise SystemExit(r.main(sys.argv[1:]))"
        self.refused(self.command(["-c=1"], prefix=prefix))
        self.assertGreater(self.journal.stat().st_size, 0)

    def test_policy_strict_types_paths_flags_and_duplicate_keys(self):
        raw = json.dumps(self.policy).encode()
        self.assertEqual(load_policy(raw), self.policy)
        for key, value in [(b'"format":', b'"format":"om-go-tool-record-policy-v1","format":'),
                           (b'"sha256":', ('"sha256":"'+self.policy['tools'][0]['sha256']+'","sha256":').encode())]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                load_policy(raw.replace(key, value, 1))
        variants = [("max_records", True), ("max_records", 513), ("extra", 0),
                    ("required_go_flags", ["-p=1"]), ("compile_scope", "all"),
                    ("record_directory", str(self.source/"records"))]
        for key, value in variants:
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_policy(json.dumps(dict(self.policy, **{key:value})).encode())
        with self.assertRaises(ValueError):
            load_policy(b" "*(256*1024+1))

    def test_journal_budget_and_tampered_existing_record(self):
        result = self.command(["-c=1"])
        self.assertEqual(result.returncode, 37, result.stderr)
        self.marker.unlink()
        first = self.journal.read_bytes()
        self.journal.write_bytes(first*512)
        self.refused(self.command(["-c=1"]))
        row = json.loads(first)
        row["classification"] = "version-probe"
        self.journal.write_text(json.dumps(row)+"\n")
        self.refused(self.command(["-c=1"]))

    def test_concurrent_owned_children_serialize_complete_records(self):
        raw = json.dumps(self.policy).encode()
        self.policy_path.write_bytes(raw)
        self.policy_path.chmod(0o600)
        cli = [sys.executable, "-B", str(RECORDER), "--policy", str(self.policy_path),
               "--policy-sha256", hashlib.sha256(raw).hexdigest(), str(self.tool), "-c=1"]
        children = []
        try:
            for _ in range(4):
                children.append(subprocess.Popen(cli, cwd=self.source,
                    env=dict(os.environ, TOOLEXEC_IMPORTPATH=MODULE, TOY_MARKER=str(self.marker)),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            for child in children:
                stdout, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 37, stderr)
                self.assertIn(b"TOY stdout", stdout)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=10)
        rows = self.rows()
        self.assertEqual(len(rows), 4)
        self.assertEqual({r["pid"] for r in rows}, {c.pid for c in children})

    def test_complete_short_writes_and_posthash_tool_change(self):
        prefix = "import sys;sys.path.insert(0,"+repr(str(RECORDER.parent))+");import record_partitioned_tool as r;write=r.os.write\ndef short(fd,data): return write(fd,data[:7])\nr.os.write=short\nraise SystemExit(r.main(sys.argv[1:]))"
        result = self.command(["-c=1"], prefix=prefix)
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(len(self.rows()), 1)
        self.marker.unlink()
        prefix = "import sys;sys.path.insert(0,"+repr(str(RECORDER.parent))+");import record_partitioned_tool as r;sync=r.os.fsync\ndef mutate(fd):\n sync(fd)\n p=r.Path("+repr(str(self.tool))+")\n p.write_bytes(p.read_bytes().replace(b'TOY stdout',b'BAD stdout'))\nr.os.fsync=mutate\nraise SystemExit(r.main(sys.argv[1:]))"
        self.refused(self.command(["-c=1"], prefix=prefix))

    def test_unpinned_selected_path_symlink_and_special_tool_mode(self):
        pinned = self.tool
        self.tool = self.tools / "other"
        self.tool.write_bytes(pinned.read_bytes())
        self.tool.chmod(0o700)
        self.refused(self.command(["-c=1"]))
        self.tool.unlink()
        self.tool = pinned
        destination = self.root / "original-tool"
        pinned.rename(destination)
        pinned.symlink_to(destination)
        self.refused(self.command(["-c=1"]))
        pinned.unlink()
        destination.rename(pinned)
        pinned.chmod(0o4700)
        self.refused(self.command(["-c=1"]))

    def test_journal_argument_total_and_per_record_bounds(self):
        result = self.command(["-c=1", "x"*20000])
        self.assertEqual(result.returncode, 37, result.stderr)
        self.marker.unlink()
        self.journal.write_bytes(self.journal.read_bytes()*420)
        self.refused(self.command(["-c=1"]))
        self.journal.write_bytes(b"x"*(128*1024+1)+b"\n")
        self.refused(self.command(["-c=1"]))
