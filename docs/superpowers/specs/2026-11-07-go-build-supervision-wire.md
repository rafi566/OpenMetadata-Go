# Build supervision wire contract

Status: design adopted after scoped integration/SDK review and two corrections.
Implements the supervised tool/fixture design; no Go execution authority.
The accepted v1 helper unit is
unchanged until the separately reviewed implementation tasks below land.

## Shared admission and authority

All JSON is strict UTF-8 with duplicate/unknown keys, nonfinite numbers,
bool-as-int and NUL rejected. IDs match `[A-Za-z0-9_-]{1,64}`; digests are64
lowercase hex. Identity is exactly `{pid,start_ticks}`, each1..2^63-1.
Pin is exactly `{path,bytes,sha256,mode}`: canonical absolute path, bounded
stable regular single-link file, nofollow ancestry and mode0..0777. Agent-owned
source/evidence and SDK admission retain their v1 ownership rules. Host pins
alone add `uid,gid` and explicitly admit the two selected root-owned compilers.
Immutable controls are exclusively created with mode0600 in private0700 roots.
No overwrite, merge, shell, PATH shim or cache/environment policy modification.

The external command release pins the complete release JSON and exact launcher
invocation. Release JSON<=256KiB has exactly `format,job_id,config,launcher,
engine,interpreter,controller,authorized`; format=`om-build-release-v1`,
authorized=true; config/launcher/engine/interpreter/controller are Pins.
The private launcher embeds config path/SHA and engine/interpreter pins, never
its own hash or the release hash. Config contains launcher path as a string;
external release pins its bytes. This ordering has no self-hash cycle.
Release authorization is supplied by the root controller, not inferred from an
untrusted helper request or a JSON boolean alone.

Config<=256KiB has exactly `format,job_id,module_root,input_manifest,sdk_go,
tool_policy,toolexec_argv,environment,roots,root_driver,fixture_slots,coverage,caps`.
Format=`om-build-job-v1`; input_manifest/sdk_go/tool_policy are Pins.
module_root is canonical absolute. toolexec_argv is the exact approved Python
`-B`, recorder path, policy path and external policy SHA, <=32 strings/16KiB.
environment is the complete approved map<=64 entries/64KiB, including flags,
offline settings, normal SDK/cache settings, GODEBUG=gocachehash=1, launcher and
retention values. Driver environment is constructed from it with PWD set to that
registered driver's cwd and its immutable context variables. Callback environment
is bounded as a map<=128 entries/128KiB, not equal to that launch map. Verified
selected SDK parent may add its source-defined action environment, cwd-derived
PWD and TOOLEXEC_IMPORTPATH=p.Desc(), and LC_ALL=C for host identity probes.
Preserve those additions unchanged. GOFLAGS/GODEBUG/CC/CXX/PKG_CONFIG/SDK/cache/
offline values and every OM_* control value remain exact released values;
immutable context values are the only per-driver override. Reject any protected
override. Check actual callback cwd/PWD is canonical and within the registered
driver's input root, SDK src, released GOMODCACHE or released GOTMPDIR/TMPDIR
descendants; all roots are canonical and explicitly present in approved config
environment. Bind importpath as bounded actual SDK description. Empty
importpath is admitted for SDK/host version probes only. Callback parent must
still be actual registered Go PID/start with executable matching sdk_go.

roots has exactly `fixtures,records,drivers,registrations`: fresh0700 siblings
outside every source root. Config/launcher remain outside outputs. Controls
live under registrations; fixture contents become inputs at freeze.
root_driver has exactly `driver_id,argv`; cwd=module_root and argv are released
Go arguments, including -v for test commands. fixture_slots<=32 have exactly `driver_id,test_name,
package,support_paths`; unique IDs distinct from root, test_name<=512B, package
is a Go identifier, support_paths are exact relative copied files. Every
released slot must complete once. No discovery can create additional slots.

coverage is a sorted array of exactly one `{driver_id,plan}` per root/fixture
slot, plan a Pin<=256KiB. Plan has exactly `format,driver_id,argv,
required_packages,action_descriptions,zero_build_diagnostic`, format=
om-build-coverage-v1. argv equals registered SDK arguments; required_packages
is sorted unique<=30000 exact ImportPath strings. action_descriptions is sorted
unique<=30000 `{description,import_path}` rows from released source/action
inventory: description is exact SDK p.Desc(), import_path exact p.ImportPath.
Normal packages have equal values; test/main variants follow selected load/pkg.go
Desc rules and are explicitly represented. No equality between bracketed
description and hash label is assumed. zero_build_diagnostic=true permits only
explicit `version` argv with no package/action/host expectations, never
test/build/generate; false requires complete build/package coverage. Engine
authenticates plans before exec and binds driver/argv; no request override,
observed-output inference or cross-driver substitution. Reconciliation receipt
is exactly `{format,job_id,driver_id,coverage_sha256,build_blocks,
covered_packages,host_completions,pass}`, format=om-build-coverage-result-v1;
counts nonnegative, covered_packages sorted unique, pass boolean.

caps has exactly these values: raw_bytes33554432, segment_bytes4194304,
response_bytes4096, request_bytes16777216, pre_seconds10, run_seconds60,
post_seconds10, outer_seconds900, cleanup_seconds20, max_drivers33.
All root/nested Go stdout/stderr share ONE32MiB budget. These are ceilings;
the existing256 lifetime identities/128 captures and resource limits still bind.

## Driver context and gate

Before Go exec, the parent publishes an immutable start record using a positive
PID/start-ticks identity from the actual gated child. Use an already-executed
Python gate with inherited FDs and parent acknowledgement; do not block in a
Popen preexec_fn, because its exec-error pipe would deadlock parent admission.
The gate preserves PID through exec. Recheck selected SDK/config before release.
Lost parent, unacknowledged gate or failed durable registration prevents exec.

The start record is exactly `format,job_id,driver_id,parent_driver_id,go_identity,
sdk_go,manifest`; format=`om-go-driver-start-v1`. parent_driver_id=null for root;
fixtures bind root through actual controller ancestry. manifest is a Pin.
The child receives OM_GO_SUPERVISION_CONTEXT as an absolute context path and
OM_GO_SUPERVISION_CONTEXT_SHA256 as its external digest. Context<=16KiB has
exactly `format,job_id,driver_id,config,start,policy`; format=`om-go-context-v1`,
config/start/policy are Pins. It is parent-written before gate acknowledgement.
Every v2 callback verifies context/config/start/policy bytes and recorder's
actual PPID/start against registered go_identity. No caller-supplied PID can
replace attribution. Derived per-driver variables are the only environment
control additions; SDK callback additions follow the bounded rule above.
Helper requests cannot choose a command, SDK, policy, coverage or context.

## Fixture control and membership

Launcher CLI modes are `driver|freeze|run|post`; one JSON stdin, no trailing
data. Requests are <=16MiB; helper readers enforce <=4KiB stdout+stderr responses.
Reply stdout contains one JSON object, stderr is bounded diagnostics. Refusal
exits nonzero. No unbounded CombinedOutput in the configured helper branch.

Driver request: exactly `{format,job_id,driver_id}`, format=om-root-driver-v1.
Execute only root_driver with full pre/post source verification inside outer
supervision. Root raw capture uses the same engine as fixtures.

Freeze request: exactly `{format,job_id,test_name,root,generated_paths}`,
format=om-fixture-freeze-v1. test_name=t.Name(), <=512 UTF-8 bytes, matches
exactly one released slot and determines its immutable driver_id. Slot fixes
package/test/support. job_id comes from released OM_BUILD_JOB_ID. generated_paths
is the unchanged sorted unique Generate return, <=30000 entries/4096B each.
Expected files are support_paths UNION package/generated_paths UNION
package/behavior_test.go. Reject overlaps, escapes, forbidden components and
file/directory conflicts. Exact physical membership and all ancestor directories
are checked before hashing. Existing16MiB/member,30000 paths,256MiB input bounds
apply. Fixture is freshly created below fixtures using umask077/private modes;
never chmod inputs for acceptance. Manifest is exclusively created outside it.

Registration has exactly `format,job_id,driver_id,root,manifest,policy,
expected_paths_sha256,pre_pass`; format=om-fixture-registration-v1,
root={path,dev,ino}, dev/ino nonnegative integers, pre_pass=true. It binds
verified original root identity and exact expected paths, not discovered files.
policy is a Pin. Derive its v2 bytes from config.tool_policy by changing ONLY
working_directory to this registered fixture root. All other fields, including
the shared job record_directory, remain equivalent JSON values. Canonical derived
bytes are sorted-key compact ensure_ascii=false UTF-8 JSON plus one LF. Root uses the
original policy. Validate this derivation against pinned config at every callback;
context.policy is that driver's resulting Pin. No caller chooses policy fields.
The unchanged toolexec argv path/SHA always authenticates the ROOT TEMPLATE,
matching config.tool_policy. V2 then separately authenticates effective
context.policy and proves the exact derivation, using effective SHA/cwd for
admission and events. Root effective policy is identical to template. V1 still
authenticates argv policy directly and retains its previous behavior. GOFLAGS
is never rewritten to substitute a fixture-specific policy token.

Run request: exactly `{format,job_id,driver_id}`, format=om-fixture-run-v1.
Consume FROZEN once, recheck manifest, run exact sdk_go arguments
`test ./... -count=1` at registered cwd under closed environment. Engine owns
pipes and60s child bound. Timeout/signal fails. Locks enforce
NEW->FROZEN->RUNNING->TERMINAL->POST and reject replay/stale configuration.

Post request: exactly `{format,job_id,driver_id}`, format=om-fixture-post-v1.
Helper invokes it after any run outcome and before Fatal, using a separate10s
context. Verify original manifest plus parent-owned terminal, with result keys
`format,job_id,driver_id,manifest,integrity_pass,run_pass` and format
om-fixture-post-result-v1. Both booleans must be true. Missing post fails.

Response keys are exactly `format,job_id,driver_id,phase,status,receipt,error`;
format=om-driver-control-v1, phase=invoked mode, status=PASS|FAIL, receipt=Pin|null,
error=null or fixed diagnostic<=256 UTF-8 bytes. Raw output stays in sidefiles.
Configured helper keeps existing signature, Generate calls, assertions and
one-minute child timeout. Without guard environment its direct Go branch is
unchanged. Freeze returns the fixed driver_id for subsequent run/post requests.
Test name does not authorize a new slot or alter expected files.

## Raw capture and terminal

Per driver: start.json, stdout.000001.raw, stderr.000001.raw and further ordered
4MiB segments, terminal.json, post.json. Names derive only from admitted IDs.
Use <=64KiB buffers; one job-owned locked counter reserves every chunk before
writing across ALL drivers/both streams, fsyncs reservation, then writes fully.
Reservations never reclaimed. Acceptance requires reserved bytes equal persisted
segment totals. Partial writes/crashes fail. Overflow stops owned processes,
drains/reaps inside remaining20s cleanup, retaining partial bytes and observed
discard count/unknown future loss. Never accept silently truncated output.

Terminal has exactly `format,job_id,driver_id,go_identity,manifest,exit_code,
signal,timed_out,overflow,stdout,stderr,cleanup_complete`;
format=om-driver-terminal-v1. Exactly one exit_code/signal is nonnull, with
nonnegative exit/positive signal; both null only for unproven terminal, which
fails. Each stream is exactly `segments,bytes,sha256,eof,
observed_discarded_bytes,loss_unknown`, segments are ordered Pins. Success
requires exit0, no timeout/overflow/loss, both EOF, cleanup_complete and independent
controller no-survivor proof. All logs, failed outcomes and reservations remain.

## Policy v2 and bounded host events

Policy<=256KiB preserves every v1 field and adds only host_id_probes;
format=om-go-tool-record-policy-v2. host_id_probes has0..2 sorted unique rows
`{role,language,tool}` with CC/c or CXX/c++. Tool keys are exactly
`path,bytes,sha256,mode,uid,gid`: canonical selected
/usr/bin/x86_64-linux-gnu-gcc-14 or g++-14, <=64MiB, mode493,uid=gid=0,
nofollow stable regular nlink1 and pre-spawn hash/identity recheck. SDK/source
ownership is unchanged. Host entries cannot be SDK entries.
Admit only `[tool.path,-###,-x,language,-c,-]` with matching inherited single-path
CC/CXX and LC_ALL=C. No source compilation, other options or languages.

ONE private locked job journal:512 events,8MiB argument bytes,128KiB/event
including LF,16MiB journal. Compact sorted-key JSON+LF. Envelope keys exactly
`format,seq,kind,job_id,driver_id,parent_go,recorder,policy_sha256,data`;
format=om-go-tool-event-v2, seq contiguous1..512, identities bind context.

kind=sdk: data is the unchanged om-go-tool-record-v1 row. Preserve exact v1
keys/classification/last-c behavior; identity/SHA equal envelope. Charge argv
once, <=64KiB encoded. Version probe is not compilation. Aggregation dispatches
policy by registered driver instead of applying one cwd/policy to the job.

kind=host-start: data exactly `role,language,tool,argv,importpath,cwd`.
Charge argv once. Durably append before spawn. Each unmatched start reserves
one event and128KiB of remaining journal for its completion. Locked replay
counts written plus reserved budgets; only matching completion consumes reserve.

kind=host-complete: data exactly `start_seq,child,terminal,elapsed_ns,stdout,
stderr,release_id,outcome`. One completion per same-driver/recorder start.
child=Identity|null if spawn failed. terminal=null or `{exit_code,signal}`,
exactly one nonnull exit0..255/signal1..64. elapsed_ns nonnegative; success<=10s.
Streams exactly `{bytes,sha256,base64,eof,lost_bytes}`; canonical padded base64
matches bytes/hash; eof bool; lost_bytes nonnegative or null if unknowable.
Stored stdout+stderr<=65536 bytes, combined base64<=87384 bytes; enforce actual
encoded event bound before append. No argv duplication. release_id=null or
`{bytes,sha256,base64}` containing unmodified observed version line without LF,
<=4096 bytes. outcome is ok|spawn_error|exit_nonzero|signal|timeout|overflow|
io_error|parse_error. Only ok/exit0/bothEOF/zero-loss/validID succeeds.
Failed completion persistence fails whole job even if SDK continues.

Successful selected GCC ID probes additionally require empty stdout, preserving
the SDK CombinedOutput ordering through stderr-only forwarding; retain/fail
nonempty stdout. Parse stderr using Unicode White_Space fields in SDK order;
colon-suffixed token stops that line's search, first version plus ASCII-digit-
leading token selects entire raw line. Missing/experimental version rejects.
This extra admission restriction must be checked by later SDK characterization.
Forward original bytes and actual terminal; never fabricate previous ID results.

## Independent SDK trace reconciliation

Use each registered driver's original stderr, before test-log decoration.
Require direct terminal/EOF/bytes/hashes/loss proof. Parse incrementally with
<=64KiB buffers,1MiB encoded HASH line,512KiB decoded input,30000 cumulative
named HASH headers/job across BOTH build and ancillary families,256 simultaneously
active build blocks. Charge every named header before admission using a shared
job counter that passes through all parsers and is never reset per driver.
Build coverage counts are separate and cannot waive that cap. Bound every length
before allocation; all ancillary observations also remain within raw32MiB.
Selected SDK forms: HASH[name] header, HASH[name]: Go-quoted payload, HASH[name]:
64-lowercase-hex digest. For `build <p.ImportPath>` ONLY, use complete
header/input/final lifecycle, sequential occurrence ordinals and no overlapping
same-name build blocks. Recompute SHA256 over decoded Write payloads including
initial salt; match final Sum. Missing build header/input/end, malformed build
framing or ambiguous build attribution rejects. Bind recorder descriptions
through released action_descriptions, never invent test suffixes on hash names.
Selected ancillary names are moduleIndex, gccCompilerID, covermeta, testResult,
testInputs, getenv, open, stat, linkShared, testmain and prefixes `vet `,
`link `, `preprocess PGO profile `. Retain individually bounded header/quoted/
digest diagnostic frames, without assigning ambiguous lifecycles or discharging
coverage. moduleIndex may interleave same names or omit Sum; gccCompilerID may
Sum, append more input and Sum again. Those are valid ancillary observations.
Unknown HASH family or malformed framing rejects. FileHash/subkey diagnostics
are retained separate source-defined forms and cannot prove action input.

Go %q is bytes, not JSON: accept double-quoted valid UTF-8 literals and only
backslash, quote, a/b/f/n/r/t/v, xHH, uHHHH, UHHHHHHHH escapes. x emits one byte;
Unicode requires scalar then UTF-8. Reject raw controls, invalid UTF-8, surrogate,
out-of-range, incomplete/unknown/octal/backtick escapes and trailing tokens.
Nested quoted identity/error strings receive a second bounded decode.

In build-package action blocks, every CC/CXX ID ERROR rejects even on Go0.
CC/CXX config arrays must name pinned tool; boundedly parse quoted flag arrays.
FC identity rejects. Positive IDs require successful same-driver/role/language/
tool/ID completion. One cached completion may support many matching inputs in
that same driver; all repeated completions must succeed/agree. gccCompilerID-
only probes may lack build-ID rows; retain/classify, not compilation.
Build/test requires >=1 complete build block and released package/action
coverage. Zero-build exception requires explicitly released nonsemantic argv,
no expected compile/host action and verified environment/terminal/raw completion.
Never infer exemption from absent events. Missing trace, error, unmatched start,
rejected invocation, missing post, loss or incomplete attribution blocks success.

## Implementation and execution boundaries

Implement as P0B1 events/host admission, P0B2 trace parser/reconciliation,
P0B3 driver engine/fixture harness, then P0B4 finite SDK characterization in the
existing partition plan/workspace. Each code unit has independent review and
normal source commit/push. Python toy fixtures are not Go evidence. P0B4 has its
own reviewed exact source/controller/environment/action inventory and verified
external checkpoint BEFORE first Go. Generation A/B and later full compilation
still require separate releases. Never raise old resource/evidence/export caps.
4MiB raw segments fit8MiB capture/member constraints; split backup capsules at
durable indexed boundaries if needed, preserving every failed observation.
No full-P0, model, server, connector, state or performance acceptance is implied.
