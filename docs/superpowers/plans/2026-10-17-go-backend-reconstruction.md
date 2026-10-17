# Go Backend Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task. Steps use checkbox syntax. Fresh independent SPEC and QUALITY review are required before dependent work.

**Goal:** Fresh verified schema registry/models/full corpus reconstruction.
**Architecture:** internal/schema validates exact values; public schema owns Optional/models. Support/registry never import generated/CLI/application packages.
**Stack:** Go1.27.2, jsonschema/v6 v6.0.3, Python3.11.17 venv, Java21 observer, Node22 hooks.
**Spec:** docs/superpowers/specs/2026-10-17-go-schema-model-reconstruction-design.md in product worktree; recovered Task9 API/map/numeric rulings remain binding.

## Global Constraints

Worktree /workspace/OpenMetadata-Go/.worktrees/full-backend-reconstruction; source2f0d4a4a42663d565b23c6018f098cfb07516fd6/setup BASEd9484f0ea2330bed00154a193a004d47909a9efb. Product paths below start openmetadata-go/. No authoritative schema/SQL/CI/deployment edits, stubs, dependency changes or weaker validation. Generate output only. Full backend/ingestion/connectors/upgrade/rollback/performance remain later mandatory work.
Fresh inventory:1071schemas/6745refs/no dynamicRef or recursiveRef; historical18084nodes/14SCC need audit.
Bounds:16MiB,depth256,10000documents,1000000raw entries,256MiBoutput,240Bfilename. Numeric mantissa10000/|exponent|10000/joint closure+instance1000000; cardinalities fit int64/platformint. ErrBlocked has source/RFC6901/instance pointer. Check continues independent nodes, successful Compile counts only, closure cache<=10000. Arbitrary raw numbers remain exact; full numeric validation remains frontier.
Normal hooks/reviews/commits/root checkpoint each task. No environment/security/cache-clear changes. Record actual exits/hashes; setup errors are not RED; recovered behavior needs fresh evidence.

## Recovery and file/dependency map

R=/workspace/OpenMetadata-Go/work/environment-recovery; read index/manifests/provenance. T8:10exact originals; fix-base5(two overlap), pre-fix registry/tests+patches. T9:3complete transcript texts(no final pins), prior names+patches, numeric/validator excerpts. Never substitute excerpts for full files.

| Task/files | Depends/produces |
|---|---|
| T1 go.mod/scripts/env.sh (go.sum starts in T2); internal/schema/{json,value,numbers}.go; schema/optional.go | exact support |
| T2 internal/schema/{registry,resolve,legacy_profile,regexp,validate,numeric_admission}.go,legacy-profile.json; scripts/rebuild_schema_policy.py; testdata/schemas/* | T1; bounded registry/profile |
| T3 internal/schema/embedded.go; registry.go refactor | T2; fs.FS parity |
| T4 internal/schema/{names,generate}.go; cmd/om-contracts/{main,schema}.go | T1–3; generator/CLI |
| T5 internal/schema/{generate_composition,generate_views}.go | T4; compositions/maps |
| T6 scripts/schema_graph.py; internal/schema/corpus_test.go; schema/corpus_test.go; schema/{models_*.go,models_registry.go,model-index.json,registry-manifest.json,registry/**} | T5; full corpus |

## Review Focus

- Reused receivers preserve prior state on failed decode and clear omitted fields on successful replacement (Tasks 1/4).
- Draft7 ignored ref siblings and unknown schema-looking annotations cannot gain assertions (Tasks 2/5).
- Declared and pattern-matched map keys cannot become additionalProperties entries (Task 5).
- A blocked numeric reference closure cannot hide successful independent node compilation (Task 2).
- Unicode symbols, malformed wire tags, and existing output paths cannot rename fields or overwrite files silently (Task 4).

Sibling tests; private work/schema/reconstruction.

### Task 1: Exact values/presence with consuming module

**Files:** T1/tests; repository docs/decisions/2026-10-17-go-schema-reconstruction-preserves-source-semantics.md cites spec. Replace Optional/generator dangling ADR citations; originals private.
**Interfaces:** module `github.com/rafi566/OpenMetadata-Go/openmetadata-go`; private `decode([]byte)(any,error)` uses json.Number and rejects duplicates/trailing JSON/size/depth overflow. `Value`: ParseValue([]byte)(Value,error), RawJSON()[]byte, MarshalJSON/UnmarshalJSON, IsNull()bool, StringValue()(string,bool), BoolValue()(bool,bool), NumberValue()(Number,bool), Object()(map[string]Value,bool), Array()([]Value,bool). `Number`: ParseNumber(string)(Number,error), String()string, Int64()(int64,error), Uint64()(uint64,error), IsInteger()bool, JSON methods. Public Optional[T]: Some(T)Optional[T], Null[T]()Optional[T], IsSet/IsNull/IsZero()bool, Value()(T,bool), JSON methods. Private ownership, ingress/egress copies, no cache; unset Value/Number serialization errors.

- [ ] TestValueOwnershipAndTransactionalDecode: mutate ingress/egress/Object/Array copies; original tokens unchanged. Failed duplicate/trailing decode preserves receiver; successful replacement removes omissions. Test escaped duplicate pointers and bounds+1.
- [ ] TestExactNumbersAndCheckedViews: preserve 9007199254740993, 18446744073709551615/16, -9223372036854775808, fractional/exponent integers, -0, 1e1000000000; checked overflow/noninteger/invalid grammar/unset errors without huge powers.
- [ ] TestOptionalPresence distinguishes missing/null/false/0/empty collections/string; omitzero omits only missing, no defaults. Restore Optional; reconstruct Value/Number; extract decoder once. Behavioral RED/GREEN in compilable implementation; `go test ./internal/schema ./schema -count=1`; review/commit.

scripts/env.sh resolves itself; OM_GO_ROOT/OM_PYTHON_VENV/OM_CACHE_ROOT default checkout work; fail if absent. Set PATH/GOTOOLCHAIN=local/GOCACHE/GOMODCACHE/PRE_COMMIT_HOME. Current overrides: main-root work/tools/go, work/reference-python, work/cache (not worktree). Activate venv before Python; verify versions. Add validator with T2 consumer.

### Task 2: Source-bound registry, drafts and bounded validation

**Files:** T2/tests; FIX_BASE registry/validate/test, original resolve/regexp/legacy_profile/five fixtures; extend T1 ADR.
**Interfaces:** Node{ID,Path,Pointer string; Document json.RawMessage}; LoadRegistry(string)(*Registry,error); LoadLegacyRegistry(string)(*Registry,error); Registry.Nodes()[]Node, Resolve(baseID,ref string)(Node,error), Check()(CheckResult,error), Validate(id string,document []byte)error. CheckResult{Documents,References,Nodes,Compiled int}; Diagnostic{Stage,Path,Pointer,Message string; Cause error}; ErrBlocked. LegacyProfile="openmetadata-2f0d4a4a". Generic identities strict; explicit legacy physical root https://open-metadata.org/schema/; immutable copies/local loader/no fetch.

- [ ] `scripts/rebuild_schema_policy.py --root ../openmetadata-spec/src/main/resources/json/schema --output work/schema/reconstruction/policy`: bounded sorted path/SHA/id/dialect/pattern/ref inventory, baseline/script hash. Reject duplicates/symlinks/nonregulars/bounds. Manifest must equal bc57fb1ceb163f2c724aa0436d70698388a879c4d4b5ba7f2cf46fab3a6b7584; never silently re-pin/run old policy.py with lost inputs.
- [ ] Exact observer copied to work/schema/reconstruction/RegexObserver.java. Fresh `java -Xmx256m work/schema/reconstruction/RegexObserver.java word` and same command `PATTERNS SAMPLES`: timeout120s/output64MiB; record Java21/version/source/input/outputSHA/exits. Sweep0..0x10ffff; <=1000patterns/512samples/4096codepoints each, including Unicode/combining/astral/control/VT/CRLF/NEL/LS/PS/trailing terminators/forbidden/adversarial strings.
- [ ] `--finalize OBSERVER_DIR` emits policy plus testdata/schemas/{regex-input.json,regex-patterns.b64,regex-samples.b64,java-regex.tsv,java-word-ranges.tsv,regex-provenance.json,reference-targets.json}. Compare every Go search/Java find; retain matches separately. New evidence, no endpoint claim/runtime Java.
- [ ] Restore compilable registry/policy/T1decoder/pinned dependency. Apply retained fix1 tests/patch by context: Draft7 ref siblings ignored;2020-12 additionalItems annotation; earlier draft activity preserved. Behavioral RED/GREEN/gofmt.
- [ ] TestRegistryAdmissionAndIdentity covers scoped/duplicate/ambiguous IDs/anchors/refs/pointers/physical priority/no fetch, profile drift, invalid/missing files, bounds. TestRawMetadataIsolation proves returned byte mutations cannot change registry. Restore excerpted tests with provenance.
- [ ] **T8-D1:** TestT8D1IgnoredRefSiblingPatterns compares pinned Compile+Validate versus registry Check+Validate for Draft7 ref with ignored pattern `(?=a)`/patternProperties; target=string. Controls: no ref, 2020-12 ref, malformed bracket, valid active pattern, explicitly referenced sibling target. Characterize before judging defect; if registry blocks compiler-ignored sibling, capture RED/fix only effective-keyword diagnostics. Assert escaped source locators.
- [ ] TestNumericAdmissionClosure: threshold/+1 mantissa/exponent/joint cost; physical-document transitive closure+instance descendants; numeric enum/const; draft-aware ignored annotations; independent node Compiled count; bounded cache; errors.Is ErrBlocked/errors.As Diagnostic+instancepointer. Guard before risky Compile; no unsafe dependent probe just for RED.
- [ ] TestCardinalityWidth: minItems18446744073709551616/maxLength9223372036854775808 source-keyword blockers; platformint boundary; negative/fractional metaschema errors; huge instance numbers unchanged. Reconstruct missing closure/cache/width guards from ruling, not partial excerpt alone.
- [ ] `go test ./internal/schema -count=1`; `go test -race ./internal/schema -count=1`; review/commit. Graph/instance results distinct.

### Task 3: Embedded parity

**Files:** embedded.go/embedded_test.go; registry.go shared loader.
**Interfaces:** LoadEmbeddedRegistry(source fs.FS,profile string)(*Registry,error); private loadRegistryFS(source fs.FS,root string,legacy bool)(*Registry,error). Empty/LegacyProfile only; generic file:///__openmetadata_embedded__/, legacy unchanged.
- [ ] TestEmbeddedParityAndBounds: disk/embedded path/pointer/raw/identity/resolution/validation parity modulo root; hostile fs.FS nil/escaping/symlink/nonregular/profile/limits/duplicates; copied ownership/sorting/no temp/network.
- [ ] Restore transcript/shared loader; parity RED/GREEN; `go test ./internal/schema -run 'TestEmbedded|TestRegistry|TestLegacy' -count=1`; review/commit.

### Task 4: Subset generator and independently buildable CLI

**Files:** T4+sibling tests. Restore names+Unicode patch/generator transcript; fix lost ADR citation.
**Interfaces:** GoName(Node)(string,error); GenerateOptions{Package,OutputDir string}; Generate(*Registry,GenerateOptions)([]string,error), sorted paths. Name owns support.Value: JSON methods, Validate()error, JSONValue()support.Value, primitive accessors; NameObject exact-tag/omitzero Optional[*Child], Object()(NameObject,bool,error), Items()([]*Item,bool,error), AdditionalProperties()(map[string]*Child,bool,error). False=nonobject, empty object=non-nil empty map, allowed null=non-nil child wrapper. Unconstrained maps use JSONValue().Object(); original serializes unknowns, detached projections do not.

- [ ] TestGeneratedPresenceAndFreshDecode/UnknownPrecisionAndMaps/EnumsAndReferences: missing-required-nullable rejects/null accepts; optional zeros/null/missing/defaultabsence; decode transaction/reuse; unknown/open/nonobject precision; invalid map child/declared exclusion; enum/ref views. Independent emitted-package compile.
- [ ] TestGenerateNamesAndOutputSafety: foo-bar/foo_bar, fooBar/foobar, 状态/N状态 collisions name both sources; uncased exported exact keys; malformed tags block. Existing path/symlink no overwrite; semantic preflight no writes; output/filename caps. All output via generator.
- [ ] Restore schemaCommand(args []string,stdout,stderr io.Writer)int excerpt/minimal main. Check --root/--profile returns0success/1invalid/2blocked (mixed prefer2), partial counts/no implicit fallback. New generate --root/--profile/--output/--package calls Generate. Missing contracts/dev commands stay missing.
- [ ] CLI tests usage/profile/diagnostics/stream failure/output; `go test ./cmd/om-contracts ./internal/schema ./schema -count=1`; `go build ./cmd/om-contracts`. Composition blockers remain until T5; review/commit.

### Task 5: Composition/map/recursive views

**Files:** T5 row/sibling tests; generate.go. **New interfaces:** AsOneOfN/AsAnyOfN/AsAllOfN()(*BranchN,bool,error), N=branch index; local modelBranch(id string,v support.Value)(support.Value,bool,error). Validate parent then static branch; only instance invalidity means nonmatch, blockers/load errors propagate. Preserve modelDecode/modelValidate and original raw wrapper.

- [ ] TestCompositionViews: oneOf0/2rejects/1projects; anyOf overlaps expose all matching views/raw; allOf enforces every constraint; if/then/else/not/dependentSchemas/type arrays/modern ref siblings/tuple/contains/unevaluated obey draft. Never flatten away constraints.
- [ ] TestMapPatternOverlap: explicit keys and any pattern-matched keys excluded from additionalProperties; all applicable patterns constrain values, null/precise numbers survive. Emit matcher consistent with source-bound policy; unsupported classification blocks precisely.
- [ ] TestRecursiveViewsAndUnknownContainers: one-level pointers traverse bounded recursive data, invalid nested data fails, generation terminates cycles. tests/testSuite.json#/definitions/testSuiteConnection/resultSummary remains referenced schema shape, not invented instanceproperty; misplaced `.{1,}` maps unconstrained. Dynamic-scope projections remain frontier, absent baseline keywords do not certify generic support.
- [ ] `go test ./internal/schema -run 'Test(Composition|MapPattern|RecursiveViews|Generate)' -count=1`, independent fixture compile; remove each blocker only with behavioral RED/GREEN; review/commit.

### Task 6: Full corpus acceptance

**Files:** T6; new testdata/models/{create-table,table,connection,entity-reference,odcs,rdf}.json plus invalid controls; generated testdata/schemas/reference-graph.json. Venv script records reference locators/targets, containment/type edges/SCCs; cross-check Resolve.

- [ ] TestFullCorpusGraph:1071exact documents/every ref/required node/model-index entry; no unresolved/dropped/colliding nodes. Audit all14SCC member sets plus traversable recursive typed shape per SCC; no-shape cycles block acceptance. Record fresh References/Nodes/Compiled, never copy18084.
- [ ] TestFullCorpusSemantics: CreateTable/Table/nestedcolumns/connections/entityrefs/extensions/timestamps preserve values and reject bad required/enum/constraints; direct entity/datacontract/odcs/odcsDataContract.json vendor fields; recursive api/rdf/sparqlTripleTerm.json + sparqlResponse.json#/definitions/rdfTerm. At metadataIngestion/workflow.json#/definitions/sourceConfig/properties/config, `{}` freshly matches17/rejects; `{"type":"AutoClassification"}` matches3/rejects. No default/discriminator coercion; full-output nullable/defaultabsence/typearray/anyOf/allOf/conditional controls.
- [ ] Twice clean generation: `go run ./cmd/om-contracts schema generate --root ../openmetadata-spec/src/main/resources/json/schema --profile openmetadata-2f0d4a4a --package schema --output work/schema/reconstruction/full-a/schema` (repeat full-b). Each separate temporary module keeps original module path and copied support-only/dependency files/semantic tests; independently `go test ./... -count=1` inside each, no live generated import. Compare sorted relative path/SHA manifests; no self-import; alternate package fixture uses public Optional.
- [ ] Final schema output through clean staging/generator, replace only manifest-owned files preserving Optional/tests. `go test ./... -count=1`; `go test -race ./... -count=1`; `go build ./cmd/om-contracts`; `go run ./cmd/om-contracts schema check --root ../openmetadata-spec/src/main/resources/json/schema --profile openmetadata-2f0d4a4a`; normal hooks/review/commit/checkpoint. Any blocked corpus node prevents full acceptance.

## Gaps/self-review

| Missing/frontier | Owner |
|---|---|
| Old modules/contracts/harness/reports | T1/T4 minimal reconstruction; contracts later |
| Policy/regex evidence | T2 new bounded observations |
| Six Task9 test names/model ADR | New named assertions/reachable attributed ADR |
| Value/Number/embedded helper | T1/T3 exact accepted API |
| SCC inventory/composition API | T5 adopted branch views/T6 all14 audit |
| Arbitrary numeric/dynamic scope | Explicit blocker, no semantic waiver |
| Toolchain/durability | Root/explicit overrides |

Self-review: APIs/provenance/coverage checked; T8-D1 open, all1071/allrefs/all14 required. Commands planned only; no product/tests/observer/build/install/network/Git. Force-add public docs by exact path. Models do not prove endpoint/SDK/native/full migration/performance parity.


## Adoption and sequencing

Root adopted this focused reconstruction against the reachable specification after reading the complete advisory and source provenance. Execution starts at the actual committed BASE recorded in the private ledger, not at historical d9484f0. The new composition branch-view signatures in Task 5 are adopted; exact static source locators and original parent validation remain authoritative. Unsupported dynamic scope is explicit, not a full-migration semantic waiver.

Root created the initial public reconstruction ADR with this plan. Task 1 implements its consumed value/presence requirements; Task 2 extends that reachable record with attributed legacy/numeric decisions instead of blindly installing old records with missing references. Original byte-matched private files remain unchanged. Task 4 uses the reachable citation. No invented historical ADR or evidence is permitted.

After each stable implementation milestone, the implementer reports a closed-file checkpoint and its current test/review status. Root saves and verifies private source/evidence externally before dependent work. Reviewed source commits are pushed normally to the dedicated branch and checked by remote SHA. Continue the full migration after this foundation through subsequent concrete source-grounded plans; do not mark the full goal complete here.
