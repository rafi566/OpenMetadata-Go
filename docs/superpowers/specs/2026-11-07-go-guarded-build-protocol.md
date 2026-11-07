# Guarded Go build inputs and tool records

P0 contract for the partitioned model plan. New helpers are migration development
tools, not a Python production runtime. This protocol grants no Go execution;
every actual command still requires reviewed, checkpointed source and release.
The existing controller and its resource, source, identity, capture and output
limits remain unchanged.

## Strict full-input manifest

`load_manifest(raw: bytes) -> dict` accepts at most16MiB before JSON parsing,
rejects duplicate keys at every level and requires exactly these top-level keys:

```json
{"format":"om-go-build-inputs-v1","root":"/absolute/root","excluded_roots":[],"files":[{"path":"go.mod","bytes":1,"sha256":"64 lower-case hex digits","mode":384}]}
```

This is a shape example, not a valid byte/hash fixture. Require exact field
types (bool is not int), UTF-8 JSON, finite integers, no extra fields, a
canonical absolute physical root, and1..30000 file rows sorted by relative path.
Root must exist; no symlink at it or any ancestor. Each row has exactly path,
bytes, sha256 and mode. Sizes are0..16MiB, total<=256MiB; mode is a recorded
integer permission value in0..0777, without special bits. SHA is lowercase
hex length64. Relative paths have no empty, dot, dotdot, backslash or NUL
components and no absolute prefix; components are at most240 UTF-8 bytes.
Reject duplicate paths and file/directory conflicts before filesystem reads.

`excluded_roots` is a sorted unique list of at most16 relative directory paths,
using the same lexical admission. Exclusions may not overlap each other or any
source row in either direction. An excluded root cannot equal the input root.
They declare only reviewed output/temp/private-work directories, never source
inputs or build support. The exact list is pinned in the command release.
Excluded output directories may be absent initially. Reject an excluded root
that exists as a link/non-directory; never treat an excluded path as a prefix
string match for unrelated siblings. Protected helpers and policy files are
always included in a pinned input manifest or the narrow controller inputs.
Product-module private `work/` may be excluded explicitly; copied clean modules
normally have no exclusion. Generation-only output roots may be excluded for
that phase because they are not compiled until separately frozen as inputs.
An exclusion grants no permission to follow a link or redirect an included path.

`verify_manifest(root: Path, manifest: dict) -> dict` revalidates the admitted
structure, requires its root to equal the supplied canonical root, and streams
the exact physical membership outside exclusions. Reject links/nonregular files,
unknown/missing/changed paths, hardlinked source files, wrong modes, owners,
sizes/hashes and unstable reads. Open ancestors/files without following links;
compare descriptor and path identity before/after reading. Bound traversal,
reads and totals before allocation. Do not load whole source payloads in memory.
Bound the complete physical walk to30,000 entries (files and directories) outside
exclusions; stream directory enumeration before sorting so excess empty
directories cannot evade the file bound.
Return `status="VERIFIED"`, `files`, `logical_bytes` and `content_sha256` over
the actual verified row list encoded as UTF-8 JSON with sorted keys, compact
separators and no trailing newline. The caller separately binds the exact input
manifest bytes/SHA; a dict API does not claim to detect duplicate JSON itself.

## One closed tool policy

`load_policy(raw: bytes) -> dict` accepts at most256KiB, with duplicate/type/
unknown-field rejection. Its exact keys are: `format`, `module`, `mode`,
`working_directory`, `toolchain_root`, `tools`, `record_directory`,
`compile_scope`, `response_files`, `max_records`, `max_argument_bytes`,
`max_record_bytes`, `max_journal_bytes` and `required_go_flags`.

- format=`om-go-tool-record-policy-v1`; module is the original module path;
  mode is `normal` or `race`. Working directory and toolchain root are exact
  canonical physical paths selected in the release.
- `tools` is a sorted array of1..16 entries with exactly `path`, `bytes`,
  `sha256` and `mode`, without duplicate paths. These identify exact absolute
  tool paths, byte sizes, SHA256 and executable modes. Only regular nofollow binaries directly under the
  selected SDK's pkg/tool/linux_amd64 directory are admitted; each<=64MiB.
  Verify pins before exec. Do not infer authority from basename/PATH alone.
- `compile_scope` is exactly `<module>/...`, not `all`; `response_files` is
  exactly `reject`. Any tool argument beginning `@` fails before exec. Full
  argument capture and admitted single implementation files avoid an assumed
  response-file expansion. A changed real tool requirement needs new review.
- `record_directory` is exact private0700 root outside input sources. The
  wrapper exclusively creates its0600 `records.jsonl` before Go starts. No
  existing journal, symlink, hardlink or foreign-owned record destination.
- Fixed bounds: max_records512, max_argument_bytes8MiB,
  max_record_bytes128KiB, max_journal_bytes16MiB. Count UTF-8 JSON argv bytes;
  require each argv representation<=64KiB. These are new recorder bounds,
  not changes to the controller's256 identities/128 compiler captures/8MiB
  passive argument budget. Reserve the complete journal allowance externally.
- `required_go_flags` is a string array without duplicate entries and contains
  only `-p=1`, `-mod=readonly`, `-gcflags=<module>/...=-c=1`, and `-race` only for
  race mode. The complete absolute Python/recorder/policy `-toolexec` argv,
  policy SHA256 and complete GOFLAGS encoding are pinned externally in the
  immutable command release. Do not put the policy's own hash or the full
  toolexec command containing that hash inside the hashed policy. Nested fixture Go
  must inherit these flags/recorder or receive exact reviewed propagation.

Recorder invocation is absolute activated-venv Python, `-B`, recorder path,
`--policy`, policy path, `--policy-sha256`, the closed policy SHA256, then the
exact tool path and its arguments. Bound/read/hash the policy before parsing;
the expected hash is supplied by the immutable wrapper/Go flags, never read
from the policy itself. It parses
the policy strictly, rejects unpinned tools/paths/arguments, and records before
`os.execv` without rewriting tool arguments or stdout. Validate before exec
under one lock on the already-created regular journal: bounded parse/count,
budget admission, one compact JSON record plus LF, complete write and fsync.
Record current PID/start identity, exact argv, TOOLEXEC_IMPORTPATH, tool pin and
version-probe classification. Failed validation/persistence exits nonzero and
does not exec. Fault tests exercise real filesystem writes and owned children.

For compile invocations whose TOOLEXEC_IMPORTPATH equals the module or begins
`<module>/`, compute the last effective `-c` value from expanded argv and require
1; both `-c=1` and `-c 1` spellings are admitted. Test variants retain this scope.
Record standard library/dependency compiler arguments separately without claiming
their `-c` is covered. Exact selected-tool `-V=full` probes are forwarded and
recorded as probes; they do not masquerade as compilations. Wrapper/policy
participation in Go action/cache identity and actual probe behavior must be
characterized before the full schedule is frozen.

## Supervised composition and aggregation

The unchanged controller watches its narrow immutable code and starts one
reviewed Python wrapper. The wrapper verifies all full input manifests before
starting the Go child, then executes the exact closed Go argv/environment and
checks full inputs and the record journal after terminal wait. All those steps
are inside the same900-second resource supervision, including cleanup reserve.
It never launches Go after a failed precheck or converts an exception into
success. The controller remains the subreaper/ownership/EOF/resource authority;
wrapper fault tests prove child wait and controller-owned descendant cleanup.

Final aggregation requires every full source check, tool record/journal budget,
semantic outcome, terminal/wait4/EOF/no-survivor, resource, source and cleanup
gate. A missing record, unknown package, changed scope/flags, output loss or
incomplete attribution blocks acceptance. Record counts are reconciled against
the actual owned compiler identities/captures, distinguishing cache reuse and
version probes. Passive sampling alone is not complete invocation proof.

Generation-only release creates new A/B outputs without compiling them. Freeze,
audit and compare their actual manifests first. A second release closes the
dependency-first normal/race compilation schedules from those outputs. Final
all-package tests remain; unexpected cold actions stop for review, not retry.
Maintain four CPUs,16GiB hard/15GiB stop/900s/20s cleanup, inherited caches and
existing raw/telemetry limits. Reserve aggregate lossless evidence before each
command and externally checkpoint finite phases before capsule limits.
