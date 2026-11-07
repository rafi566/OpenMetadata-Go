# Partitioned facade alias aggregation

Status: adopted internal P3 correction after independent design review;
no implementation or Go release.
The full-migration scope, wire/model behavior and legacy generator contract stay
binding. Root selects this technical correction under the existing execution
authorization; it is not a new user-approved product requirement.

## Concrete failure

The accepted recorder permits at most65,536 bytes of compact JSON argv and
rejects response files. Preserved full-a has18,084 promised per-node facade
filenames; their basenames alone encode to1,524,653 bytes, before options or
absolute directories. Selected SDK gc.go161–177 passes every source filename in
one package compilation. Scheduling other packages cannot split that invocation.
The Python toolexec prefix also bypasses the SDK's compiler response-file rewrite.
Retain the existing argument/record/process caps and reject unsupported @ files.

## Approaches and root decision

One facade file per SCC reduces the count, but still repeats approximately a
thousand absolute paths and has no64KiB proof. Removing exported facade aliases
would change the public model API. Select deterministic aggregation of facade
aliases into bounded files instead. This changes physical files only in the
new opt-in partitioned layout. It trades larger generated files for fewer
compiler arguments; it does not establish typechecker/linker memory feasibility.

## Physical layout and complete mapping

Preserve default Generate/GenerateOptions, default paths/index/output bytes and
all existing semantic assertions. In partitioned mode, replace the physical
per-node facade-file promise with `models_aliases_0000.go`, then0001 and so on.
Sort node groups by the existing structured original-document/RFC6901 identity.
Each node group contains its complete facade model/object/enum aliases and
constant forwarders; preserve declaration names, types and implementation targets.
Never omit a declaration or split an SCC. Component implementation remains one
combined Go file per SCC as already specified.

Pack complete node groups greedily in that order. A candidate chunk's size is
its fully rendered/formatted UTF-8 source, including package/import declarations.
Merge and sort imports deterministically. Append while the actual result is
<=16MiB; otherwise close the chunk and retry the same complete group in the next
one. A single group that cannot fit16MiB rejects before any output write. Do not
add an arbitrary1MiB/64-chunk acceptance restriction. Existing256MiB total,
28,000 generated files and30,000 physical/export paths still apply.

Keep the actual model-index fields `path,pointer,name,sha256` and their values;
there is no filename field to change or add. The versioned partition manifest's
existing declaration `facade` field names the actual owned chunk, while its
`implementation` target and structured identity remain complete. Every alias
maps exactly once to an implementation and physical file. Chunk byte/SHA pins
live in the existing `files` table rather than duplicated per declaration.
No extra legacy-filename/ordinal columns are required. No generated ownership is
assigned to Optional, support or tests. The planned partition-manifest v1 name
remains; aggregation changes physical target values, without adding schema keys.

## Argument admission and verification

During generation preflight, compute compact JSON bytes of all unavoidable
absolute generated facade Go filenames and known hand-owned support filenames.
If that lower bound alone exceeds65,536, reject before writing. Passing a lower
bound is not proof of the full invocation. Before launching a Go DRIVER, P4
freezes selected SDK paths/options/cwd and proves a conservative complete
compact-JSON argv upper bound<=65,536 for every permitted compiler/test variant.
Use pinned SDK construction rules, every possible argument/source file, released
runtime temporary-path byte bounds and JSON escaping costs. Randomized work and
test-main paths are bounded, not falsely described as exact preexisting strings.
Missing or unbounded variants reject the release. Immediately before EACH
COMPILER exec, the recorder authenticates and checks its actual exact argv
against65,536. No SDK dry run or response-file exception is introduced. No new
GeneratePartitionedOptions field or inferred SDK command is introduced.
An impossible bounded release remains a typed blocker, not permission
to increase a cap or discard nodes. Full-corpus generation and compilation remain
separate releases.

P3 tests must prove all declarations/targets and identity-to-physical mappings,
shuffled-input determinism, greedy boundary behavior including formatted imports,
no-write oversized group/lower-bound failures and byte-identical legacy output.
Use bounded metadata/size injection for large boundaries. P5 still generates two
complete clean copies and compares every physical path/byte/hash/ownership row,
all source recursion groups and existing semantics. Complete ordinary/race/build
and strongest whole-foundation review remain mandatory.

## Implementation ownership

This amends the dependency-layout paragraph of the existing partition design,
P3 emitter/manifest/tests and P4 argv preflight in the existing partition plan.
It adds no independent runtime subsystem, extra agent or implementation task.
P0B1 remains independent and is not gated on this later correction. Independently
review this design and exact plan delta before P3 code; root records adoption.
