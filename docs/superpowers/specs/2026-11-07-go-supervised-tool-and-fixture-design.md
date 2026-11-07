# Supervised host tool identity and generated test fixtures

Status: proposed P0 composition amendment; no execution release. The v1 source
helpers remain a separate reviewed unit. This document closes two prerequisites
found while tracing the selected Go SDK and the actual test helper. It changes
development verification only, without changing model/wire semantics or the
managed environment configuration.

## Evidence and selected approach

Go's `cmd/go/internal/work/buildid.go` routes CC/CXX identity probes through
`-toolexec`. `exec.go` writes `CC ID ERROR` or `CXX ID ERROR` into action-hash
inputs when those probes fail, allowing the parent command to continue. A
pre-exec recorder therefore cannot guarantee failure propagation. A separate
broker still cannot observe failure before registration; a marker on a failing
filesystem has the same limitation.

Use exact pinned host identity probes with bounded terminal/output evidence,
and independently observe the SDK's action-hash diagnostic stream. The selected
SDK emits those error inputs under `GODEBUG=gocachehash=1`. This is an explicit
per-command diagnostic exception to the previously empty GODEBUG value, requiring
its own reviewed release. Preserve lossless stderr/stdout and existing caps.
Overflow, an error input or an incomplete trace prevents acceptance. Compilation
observations with this diagnostic are not backend performance measurements.

`independentGeneratedModule` creates its fixture immediately before starting
nested Go. Retaining a fixture after the test cannot establish its precheck.
Freeze and verify that freshly created fixture immediately before its nested
command, then compare it after the command. Preserve all semantic assertions,
the existing helper signature and its one-minute child timeout.

## Policy v2 and exact host probe class

Keep v1 policy admission and SDK tool behavior. Add explicit
`om-go-tool-record-policy-v2`, with all v1 fields plus `host_id_probes`.
The new field is an array of zero to two entries with exactly `role`, `language`
and `tool`. `tool` has path/bytes/SHA256/mode plus exact `uid` and `gid`, bounded
at64MiB, canonical regular single-link executable. For the two existing selected
system compilers pin UID0/GID0 and mode0755 explicitly. Their system ownership
is distinct from agent-owned source/evidence; SDK/source/journal admission is
unchanged. Unique sorted pairs
are CC/c and CXX/c++; a host entry cannot also be an SDK tool entry.

The release binds CC and CXX to the existing exact selected compiler paths and
hashes. A host callback must match its role's inherited single-path CC/CXX value,
that tool pin and exactly `[-###,-x,language,-c,-]`, with SDK-forced LC_ALL=C.
It is an identity probe, separately classified from Go compiler concurrency.
Additional options, source files, response files and other languages reject.

Use the same externally pinned policy SHA and exact full toolexec argv. Preserve
all journal/argument/record/resource limits. Version2 requires the diagnostic
GODEBUG value on every Go driver, including nested fixture drivers. The command
release pins that environment and the direct driver-scoped raw capture below.
Verbose outer test output remains useful for test completion records; decorated
t.Log output is not the independent SDK trace source. All compiler/process coverage remains
explicit; no cache invalidation or cold-cache assertion follows from changing
the wrapper path.

## Host terminal evidence and independent failure channel

Record an admitted host attempt durably before spawning its child. Supervise
that exact child under a10-second per-probe bound within the unchanged900-second
outer supervision. Reserve at most64KiB total stdout/stderr per probe. Preserve
each stream's bytes and forward them to their original descriptors while
collecting bounded evidence; retain actual terminal status and tool identity.
The existing controller owns descendant/resource/cleanup authority.

Append a bounded completion event keyed to recorder PID/start identity, with
child identity/terminal status, raw stream bytes/hashes and the observed release
version identity. Preserve journal limits512records/8MiB argument bytes/
128KiB record/16MiB journal; host start/completion events each count. A missing
completion or failed write is not success. Add explicit versioned host-event
schemas; existing SDK records retain their v1 schema and interpretation.

Align release-version parsing with the selected SDK: ignore colon-labelled
configuration fields, find `version` followed by an ASCII-digit-leading token,
and retain that entire observed line. Experimental compiler fallback is outside
this probe class and blocks. Forward bytes and terminal results rather than
fabricating an identity or substituting a previous probe.

Independently consume the lossless SDK action-hash trace. Bind its exact format
to the selected `cmd/go/internal/cache/hash.go`, distinguishing build hash input
records from arbitrary test prose. Any CC/CXX ID ERROR input, malformed relevant
record, truncation or missing trace prevents acceptance even if Go exits0.
Positive CC/CXX ID records must reconcile with admitted probe completions and
their observed identities. This covers the otherwise invisible failure before
recorder registration. Probe completions alone do not establish that coverage.

The first characterization release must demonstrate the actual selected SDK's
normal, swallowed-failure and diagnostic behavior under existing limits. It is
an experiment, not semantic acceptance. Before that release, Python fixtures
exercise an explicitly labelled parent that ignores child failures and emits
the SDK-shaped trace; those tests are not represented as Go observations.

## Generated fixture lifecycle

Amend P1's test-support ownership to permit reviewed lifecycle calls in
`internal/schema/generate_test.go` in addition to the presence copy allowlist.
Keep every existing semantic assertion, Generate call and helper signature.
The lifecycle is mandatory in the released verification environment; ordinary
developer tests retain their existing behavior when that environment is absent.

Use a root-controlled private fixture guard command, pinned in the release and
selected through a single explicit test environment value. After all copied
support, generated files and behavior_test.go are written, call it to create an
exclusive strict full-input manifest outside the fixture, verify that snapshot,
and register its identity with the outer job. Only then launch nested Go through
the same pinned guard launcher's `run` mode, which replaces direct nested Go
execution in the released test-harness branch. Ordinary unconfigured developer
tests keep their existing direct execution behavior.

The private launcher owns nested Go's actual pipes. Stream raw stdout/stderr to
separate driver-scoped evidence files under the unchanged32MiB combined output
cap, with bounded buffers, byte/hash accounting and terminal/EOF/cleanup proof.
Root aggregation reads those original streams before any t.Log decoration.
On overflow stop the owned command, drain/reap within cleanup bounds, retain
partial bytes/loss counts and fail; never build an unbounded CombinedOutput
buffer. The launcher emits only a bounded4KiB control response to the helper.
This is a verification-harness change, preserving the exact SDK Go args and
semantic assertions; no substitute tool result is accepted.

After terminal completion, the helper invokes `post` even on child failure,
using a separate bounded context after the unchanged one-minute child context.
Verify the original manifest and retain it plus all raw logs. Reserve at most
10seconds each for pre and post inside the outer900seconds; a missing post,
lost launcher, overflow or timeout cannot become semantic success. The outer
controller still owns final descendant cleanup and no-survivor acceptance.

Allocate retained fixture roots and tool-record roots as separate private sibling
directories. Records must remain outside every input root. The outer wrapper
closes their permitted parent roots and bounded dynamic-registration schema in
its release. A registration identifies exact fixture root, manifest bytes/SHA,
owner phase and pre/post outcomes. Count all extra guard/recorder children under
the unchanged lifetime256 identities/128 compiler captures.

Preserve the existing helper's inherited GOFLAGS/offline environment wiring.
Freeze the complete quoted toolexec token and its externally supplied policy
hash; use the corrected module/scripts recorder path. Set
OM_GENERATED_EVIDENCE_DIR to the released retained fixture parent. New fixture
inputs are derived writes until frozen; afterward they are guarded immutable
inputs, not an open output exclusion during compilation.

## Ordering and proof

1. Fix and independently accept the four-file v1 source-helper unit.
2. Review this amendment and the precise host-event/fixture-registration/wrapper
   wire schemas before implementing the new composition. Commit source decisions.
3. Add meaningful Python RED/GREEN for swallowed nonzero, unparseable exit0,
   pre-registration failure, persistence/short-write/output loss, exact positive
   host forwarding, and fixture tamper/extra/missing before and after the child.
4. Independently review and checkpoint exact source, policies, source manifests,
   controller inputs, environment exceptions and a finite characterization
   command release. Keep all actual failed outcomes.
5. Characterize selected SDK behavior, then separately release finite P1 tests.
   Full generation A/B and their later compilation schedule still have distinct
   releases. Final ordinary/race/build/schema checks remain mandatory.

Keep four CPUs,16GiB hard/15GiB observed stop,900seconds,20seconds cleanup,
normal inherited caches and every source/output/journal/export limit. A trace
that cannot fit fails the bounded protocol; it cannot justify a limit increase.
No server, connector, state or performance acceptance follows from these tools.
