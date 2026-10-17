// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func TestCheckUnusedSchema(t *testing.T) {
	r := load(t, `{"$id":"https://example.test/a","$defs":{"unused":{"type":"strng"}}}`)
	counts, e := r.Check()
	if e == nil || counts.Compiled == counts.Nodes || !strings.Contains(e.Error(), "a.json#/$defs/unused") {
		t.Fatalf("unused schema not checked: %+v %v", counts, e)
	}
}
func TestInstanceConstraintsAndFormats(t *testing.T) {
	for _, tc := range []struct{ name, schema, valid, invalid string }{
		{"exact-number", `{"type":"integer","minimum":9007199254740993,"maximum":9007199254740993}`, `9007199254740993`, `9007199254740992`},
		{"multiple", `{"type":"number","multipleOf":0.1}`, `0.3`, `0.31`},
		{"enum", `{"enum":[null,0,"A"]}`, `null`, `"a"`},
		{"array", `{"type":"array","items":{"type":"integer"},"uniqueItems":true,"minItems":1}`, `[1,2]`, `[1,1]`},
		{"object", `{"type":"object","required":["x"],"properties":{"x":{"type":"string","minLength":2}},"additionalProperties":false}`, `{"x":"ab"}`, `{"x":null}`},
		{"draft7-format", `{"$schema":"http://json-schema.org/draft-07/schema#","type":"string","format":"email"}`, `"a@example.com"`, `"invalid"`},
		{"union", `{"oneOf":[{"type":"number"},{"minimum":0}]}`, `-1`, `1`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := load(t, tc.schema)
			id := r.Nodes()[0].ID
			if e := r.Validate(id, []byte(tc.valid)); e != nil {
				t.Fatal(e)
			}
			if e := r.Validate(id, []byte(tc.invalid)); e == nil {
				t.Fatal("invalid instance accepted")
			}
		})
	}
	r := load(t, `{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"string","format":"email"}`)
	if e := r.Validate(r.Nodes()[0].ID, []byte(`"invalid"`)); e != nil {
		t.Fatal("annotation asserted", e)
	}
}
func TestRawMetadataIsolation(t *testing.T) {
	raw := `{ "$id": "https://example.test/a", "default": null, "format": "custom", "minimum": 9007199254740993 }`
	r := load(t, raw)
	n := r.Nodes()[0]
	if string(n.Document) != raw {
		t.Fatal("raw source changed")
	}
	n.Document[0] = '!'
	fresh, _ := r.Resolve(n.ID, "")
	if string(fresh.Document) != raw {
		t.Fatal("returned source aliases registry")
	}
}
func corpusRoot(t *testing.T) string {
	t.Helper()
	root := "../../../openmetadata-spec/src/main/resources/json/schema"
	if _, e := os.Stat(root); e != nil {
		t.Fatal(e)
	}
	return root
}
func TestLegacyGraph(t *testing.T) {
	r, e := LoadLegacyRegistry(corpusRoot(t))
	if e != nil {
		t.Fatal(e)
	}
	if len(r.documents) != 1071 || len(r.references) != 6745 {
		t.Fatalf("graph counts: %d %d", len(r.documents), len(r.references))
	}
	n, e := r.Resolve(legacyBase+"api/createBot.json", "")
	if e != nil || n.Path != "api/createBot.json" {
		t.Fatalf("physical priority: %+v %v", n, e)
	}
	n, e = r.Resolve(legacyBase+"entity/services/connections/common/sslConfig.json", "./sslCertPaths.json")
	if e != nil || n.Path != "entity/services/connections/common/sslCertPaths.json" {
		t.Fatalf("physical base: %+v %v", n, e)
	}
	n, e = r.Resolve(legacyBase+"tests/testSuite.json", "#/definitions/testSuiteConnection/resultSummary")
	if e != nil || !bytes.Contains(n.Document, []byte("$ref")) {
		t.Fatalf("unknown container target: %+v %v", n, e)
	}
	if _, ok := r.schemas[n.Path+"#"+n.Pointer]; !ok {
		t.Fatal("direct target omitted from compiler nodes")
	}
}
func TestLegacyHashDrift(t *testing.T) {
	root := fixture(t, map[string]string{"a.json": `{}`})
	if _, e := LoadLegacyRegistry(root); e == nil {
		t.Fatal("unpinned corpus admitted")
	}
}
func TestLegacyCorpusCompilation(t *testing.T) {
	r, e := LoadLegacyRegistry(corpusRoot(t))
	if e != nil {
		t.Fatal(e)
	}
	c, e := r.Check()
	t.Logf("all-node compile: %+v", c)
	if e != nil {
		t.Fatal(e)
	}
	if c.Documents != 1071 || c.References != 6745 || c.Nodes == 0 || c.Compiled != c.Nodes {
		t.Fatalf("incomplete: %+v", c)
	}
}
func TestGenericUnsupportedPattern(t *testing.T) {
	r := load(t, `{"pattern":"(?U)^[\\w]+$"}`)
	_, e := r.Check()
	if !errors.Is(e, ErrBlocked) || !strings.Contains(e.Error(), "a.json#/pattern") {
		t.Fatalf("Java mode accidentally accepted: %v", e)
	}
}
func TestLocalCrossDocumentAlias(t *testing.T) {
	root := fixture(t, map[string]string{"a.json": `{"$id":"https://example.test/a","$ref":"https://example.test/b"}`, "b.json": `{"$id":"https://example.test/b","type":"integer"}`})
	r, e := LoadRegistry(root)
	if e != nil {
		t.Fatal(e)
	}
	if e = r.Validate("https://example.test/a", []byte(`3`)); e != nil {
		t.Fatal(e)
	}
	if e = r.Validate("https://example.test/a", []byte(`"3"`)); e == nil {
		t.Fatal("alias constraint lost")
	}
}

func TestLegacyAliasPolicy(t *testing.T) {
	// The pinned corpus has only physical collision aliases. This isolated policy
	// fixture covers a future ambiguous nonphysical alias without admitting it via
	// the pinned loader or relaxing generic identity rejection.
	r := load(t, `{"$id":"https://example.test/a"}`)
	a := r.documents["a.json"]
	b := *a
	b.Path = "b.json"
	b.physical = legacyBase + "b.json"
	b.value = map[string]any{"$id": "https://example.test/ambiguous"}
	c := b
	c.Path = "c.json"
	c.physical = legacyBase + "c.json"
	r.documents[b.Path] = &b
	r.documents[c.Path] = &c
	r.addLegacyAliases()
	if _, e := r.Resolve(a.ID, "https://example.test/ambiguous"); e == nil || !strings.Contains(e.Error(), "ambiguous") {
		t.Fatalf("ambiguous alias selected: %v", e)
	}
}
func TestConcurrentValidation(t *testing.T) {
	r := load(t, `{"$id":"https://example.test/a","type":"object","properties":{"x":{"type":"integer"}},"required":["x"]}`)
	var group sync.WaitGroup
	for i := 0; i < 12; i++ {
		group.Add(1)
		go func() {
			defer group.Done()
			for j := 0; j < 10; j++ {
				if e := r.Validate("https://example.test/a", []byte(`{"x":7}`)); e != nil {
					t.Error(e)
				}
				if e := r.Validate("https://example.test/a", []byte(`{"x":null}`)); e == nil {
					t.Error("invalid concurrent value accepted")
				}
				r.Nodes()
				r.Resolve("https://example.test/a", "#/properties/x")
			}
		}()
	}
	group.Wait()
}
func TestSourceBoundRegexEligibility(t *testing.T) {
	r, e := LoadLegacyRegistry(corpusRoot(t))
	if e != nil {
		t.Fatal(e)
	}
	n := r.schemas["type/basic.json#/definitions/entityName"]
	if !r.patternEligible(n, n.Pointer+"/pattern", namePattern) {
		t.Fatal("pinned source not eligible")
	}
	if r.patternEligible(n, "/unknown/pattern", namePattern) || r.patternEligible(n, n.Pointer+"/pattern", edgePattern) {
		t.Fatal("pointer/text not bound")
	}
	original := r.documents[n.Path].Document
	r.documents[n.Path].Document = append(bytes.Clone(original), ' ')
	if r.patternEligible(n, n.Pointer+"/pattern", namePattern) {
		t.Fatal("hash drift eligible")
	}
}
func TestLegacyRepresentativeInstances(t *testing.T) {
	r, e := LoadLegacyRegistry(corpusRoot(t))
	if e != nil {
		t.Fatal(e)
	}
	for _, tc := range []struct{ node, valid, invalid string }{{"type/basic.json#/definitions/entityName", `"valid name"`, `"bad::name"`}, {"type/basic.json#/definitions/entityLink", `"<#E::tábles::name>"`, `"<#E::tables::a|b>"`}, {"entity/type.json#/definitions/entityName", `"中文"`, `"bad name"`}, {"type/basic.json#/definitions/uuid", `"not-asserted-by-2020-format"`, `123`}} {
		if e := r.Validate(legacyBase+tc.node, []byte(tc.valid)); e != nil {
			t.Fatalf("%s valid: %v", tc.node, e)
		}
		if e := r.Validate(legacyBase+tc.node, []byte(tc.invalid)); e == nil {
			t.Fatalf("%s invalid accepted", tc.node)
		}
	}
}

func TestLegacyFileSetAndHashDrift(t *testing.T) {
	original := corpusRoot(t)
	copyRoot := t.TempDir()
	for _, d := range readPolicy().Documents {
		p := filepath.Join(copyRoot, filepath.FromSlash(d.Path))
		if e := os.MkdirAll(filepath.Dir(p), 0700); e != nil {
			t.Fatal(e)
		}
		b, e := os.ReadFile(filepath.Join(original, filepath.FromSlash(d.Path)))
		if e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(p, b, 0600); e != nil {
			t.Fatal(e)
		}
	}
	path := "analytics/basic.json"
	file := filepath.Join(copyRoot, filepath.FromSlash(path))
	raw, e := os.ReadFile(file)
	if e != nil {
		t.Fatal(e)
	}
	for _, action := range []string{"changed", "missing", "added"} {
		t.Run(action, func(t *testing.T) {
			t.Cleanup(func() { os.WriteFile(file, raw, 0600); os.Remove(filepath.Join(copyRoot, "unexpected.json")) })
			switch action {
			case "changed":
				e = os.WriteFile(file, append(bytes.Clone(raw), ' '), 0600)
			case "missing":
				e = os.Remove(file)
			case "added":
				e = os.WriteFile(filepath.Join(copyRoot, "unexpected.json"), []byte(`{}`), 0600)
			}
			if e != nil {
				t.Fatal(e)
			}
			_, e = LoadLegacyRegistry(copyRoot)
			want := path
			if action == "added" {
				want = "unexpected.json"
			}
			if e == nil || !strings.Contains(e.Error(), want) {
				t.Fatalf("missing exact %s diagnostic: %v", action, e)
			}
			if action == "added" {
				os.Remove(filepath.Join(copyRoot, "unexpected.json"))
			} else {
				os.WriteFile(file, raw, 0600)
			}
		})
	}
}

func TestMalformedPatternIsInvalidNotBlocked(t *testing.T) {
	r := load(t, `{"pattern":"["}`)
	_, e := r.Check()
	if e == nil || errors.Is(e, ErrBlocked) {
		t.Fatalf("malformed syntax classified as unavailable semantics: %v", e)
	}
}
func TestCheckDiagnosticOrderStable(t *testing.T) {
	r := load(t, `{"$defs":{"a":{"type":"strng"},"b":{"pattern":"(?U)^[\\w]+$"}}}`)
	var first string
	for i := 0; i < 4; i++ {
		c, e := r.Check()
		if e == nil || !errors.Is(e, ErrBlocked) || c.Nodes != 3 || c.Compiled != 0 {
			t.Fatalf("bad mixed outcome %+v %v", c, e)
		}
		if i == 0 {
			first = e.Error()
		} else if first != e.Error() {
			t.Fatal("nondeterministic diagnostics")
		}
	}
}

func TestValidationFailuresKeepAttribution(t *testing.T) {
	r := load(t, `{"$id":"https://example.test/a","type":"integer"}`)
	for _, doc := range []string{`{`, `1 2`, `"bad"`} {
		e := r.Validate("https://example.test/a", []byte(doc))
		var d *Diagnostic
		if !errors.As(e, &d) || d.Path != "a.json" || d.Stage != "validate" {
			t.Fatalf("bad validation diagnostic: %v", e)
		}
	}
	if e := r.Validate("https://missing.test/a", []byte(`1`)); e == nil {
		t.Fatal("unknown validation identity accepted")
	}
	bad := load(t, `{"type":"strng"}`)
	if e := bad.Validate(bad.Nodes()[0].ID, []byte(`1`)); e == nil {
		t.Fatal("invalid schema accepted for validation")
	}
}
func TestPatternPropertiesAndUnsupportedSearch(t *testing.T) {
	r := load(t, `{"type":"object","patternProperties":{"^a":{"type":"integer"}},"additionalProperties":false}`)
	if e := r.Validate(r.Nodes()[0].ID, []byte(`{"abc":1}`)); e != nil {
		t.Fatal(e)
	}
	if e := r.Validate(r.Nodes()[0].ID, []byte(`{"abc":"bad"}`)); e == nil {
		t.Fatal("pattern property constraint lost")
	}
	r = load(t, `{"pattern":"(?=a)a"}`)
	if _, e := r.Check(); !errors.Is(e, ErrBlocked) {
		t.Fatalf("lookahead unsupported not blocked: %v", e)
	}
	if e := r.Validate(r.Nodes()[0].ID, []byte(`"a"`)); !errors.Is(e, ErrBlocked) {
		t.Fatal(e)
	}
}
func TestPinnedIdentityInventory(t *testing.T) {
	var p struct {
		Baseline   string
		Documents  []policyDocument
		Mismatches []policyDocument
		Collisions []struct {
			ID               string
			Members          []policyDocument
			PhysicalPriority string `json:"physical_priority"`
		}
	}
	if e := json.Unmarshal(legacyPolicyJSON, &p); e != nil {
		t.Fatal(e)
	}
	if p.Baseline != "2f0d4a4a42663d565b23c6018f098cfb07516fd6" || len(p.Documents) != 1071 || len(p.Mismatches) != 122 || len(p.Collisions) != 12 {
		t.Fatal("policy inventory differs")
	}
	union := map[string]bool{}
	for _, d := range p.Mismatches {
		if d.ID == d.Physical {
			t.Fatal("not an identity mismatch")
		}
		union[d.Path] = true
	}
	members := 0
	for _, g := range p.Collisions {
		for _, d := range g.Members {
			if d.ID != g.ID || d.SHA256 == "" {
				t.Fatal("collision not source-bound")
			}
			union[d.Path] = true
			members++
		}
		if g.PhysicalPriority == "" {
			t.Fatal("physical collision priority absent")
		}
	}
	if members != 27 || len(union) != 134 {
		t.Fatal("identity defect totals differ")
	}
}

func TestLegacyAliasUsesPhysicalBase(t *testing.T) {
	r, e := LoadLegacyRegistry(corpusRoot(t))
	if e != nil {
		t.Fatal(e)
	}
	n, e := r.Resolve(legacyBase+"analytics/aggregatedCostAnalysisReportData.json", "../../type/basic.json#/definitions/uuid")
	if e != nil || n.Path != "type/basic.json" || n.Pointer != "/definitions/uuid" {
		t.Fatalf("alias ref not rebased to physical source: %+v %v", n, e)
	}
}

func TestDraft7UnknownAnchorAndReferenceKeywords(t *testing.T) {
	r := load(t, `{"$schema":"http://json-schema.org/draft-07/schema#","$id":"https://example.test/a","$dynamicRef":"https://unregistered.invalid/annotation","properties":{"a":{"$anchor":"same"},"b":{"$anchor":"same"}}}`)
	if _, e := r.Check(); e != nil {
		t.Fatal(e)
	}
}
func TestDraft7RefSiblingIDDoesNotChangeBase(t *testing.T) {
	root := fixture(t, map[string]string{"a.json": `{"$schema":"http://json-schema.org/draft-07/schema#","$id":"https://unregistered.invalid/ignored","$ref":"b.json"}`, "b.json": `{"type":"integer"}`})
	r, e := LoadRegistry(root)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = r.Check(); e != nil {
		t.Fatal(e)
	}
}

func TestAdditionalItems2020Metadata(t *testing.T) {
	for _, declaration := range []string{`"$schema":"https://json-schema.org/draft/2020-12/schema",`, ""} {
		for _, metadata := range []string{`"annotation"`, `{"$ref":"https://unregistered.invalid/annotation"}`} {
			raw := `{` + declaration + `"additionalItems":` + metadata + `,"type":"integer"}`
			t.Run(raw, func(t *testing.T) {
				r := load(t, raw)
				counts, err := r.Check()
				if err != nil || counts != (CheckResult{Documents: 1, Nodes: 1, Compiled: 1}) {
					t.Fatalf("annotation treated as schema: %+v %v", counts, err)
				}
				root := r.Nodes()[0]
				if string(root.Document) != raw {
					t.Fatal("raw annotation changed")
				}
				if err := r.Validate(root.ID, []byte(`1`)); err != nil {
					t.Fatal(err)
				}
				if err := r.Validate(root.ID, []byte(`"one"`)); err == nil {
					t.Fatal("integer constraint lost")
				}
			})
		}
	}
}

func TestAdditionalItemsOlderDraftConstraint(t *testing.T) {
	for _, draft := range []string{"http://json-schema.org/draft-07/schema#", "https://json-schema.org/draft/2019-09/schema"} {
		t.Run(draft, func(t *testing.T) {
			r := load(t, `{"$schema":"`+draft+`","type":"array","items":[{"type":"integer"}],"additionalItems":{"type":"string"}}`)
			counts, err := r.Check()
			if err != nil || counts.Nodes != 3 || counts.Compiled != 3 {
				t.Fatalf("applicable additionalItems not checked: %+v %v", counts, err)
			}
			if err := r.Validate(r.Nodes()[0].ID, []byte(`[1,"two"]`)); err != nil {
				t.Fatal(err)
			}
			if err := r.Validate(r.Nodes()[0].ID, []byte(`[1,2]`)); err == nil {
				t.Fatal("applicable additionalItems constraint lost")
			}
		})
	}
}

func TestAdditionalItemsExplicitTargetClosure(t *testing.T) {
	r := load(t, `{"$schema":"https://json-schema.org/draft/2020-12/schema","$ref":"#/additionalItems","additionalItems":{"type":"integer"}}`)
	counts, err := r.Check()
	if err != nil || counts != (CheckResult{Documents: 1, References: 1, Nodes: 2, Compiled: 2}) {
		t.Fatalf("explicit target not compiled: %+v %v", counts, err)
	}
	if err := r.Validate(r.Nodes()[0].ID, []byte(`1`)); err != nil {
		t.Fatal(err)
	}
	if err := r.Validate(r.Nodes()[0].ID, []byte(`"one"`)); err == nil {
		t.Fatal("explicit target constraint lost")
	}
	for _, target := range []string{`"annotation"`, `{"$ref":"https://unregistered.invalid/required"}`} {
		_, err := LoadRegistry(fixture(t, map[string]string{"a.json": `{"$schema":"https://json-schema.org/draft/2020-12/schema","$ref":"#/additionalItems","additionalItems":` + target + `}`}))
		if err == nil || !strings.Contains(err.Error(), "a.json#/additionalItems") {
			t.Fatalf("explicit target escaped validation: %v", err)
		}
	}
}
