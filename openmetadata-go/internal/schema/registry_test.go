// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

func fixture(t *testing.T, files map[string]string) string {
	t.Helper()
	dir := t.TempDir()
	for p, s := range files {
		p = filepath.Join(dir, p)
		if err := os.MkdirAll(filepath.Dir(p), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(s), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return dir
}
func load(t *testing.T, s string) *Registry {
	t.Helper()
	r, e := LoadRegistry(fixture(t, map[string]string{"a.json": s}))
	if e != nil {
		t.Fatal(e)
	}
	return r
}
func TestRecursiveReferenceTerminates(t *testing.T) {
	r := load(t, `{"$id":"https://example.test/a","type":"object","properties":{"next":{"$ref":"#"}}}`)
	n, e := r.Resolve("https://example.test/a", "#/properties/next")
	if e != nil || n.Pointer != "/properties/next" {
		t.Fatalf("recursive target: %+v %v", n, e)
	}
	if e := r.Validate("https://example.test/a", []byte(`{"next":{"next":2}}`)); e == nil {
		t.Fatal("recursive constraint ignored")
	}
}
func TestJSONPointerEscaping(t *testing.T) {
	r := load(t, `{"$id":"https://example.test/a","$defs":{"a/b~c":{"type":"integer"}}}`)
	n, e := r.Resolve("https://example.test/a", "#/$defs/a~1b~0c")
	if e != nil || n.Pointer != "/$defs/a~1b~0c" {
		t.Fatalf("escaped target: %+v %v", n, e)
	}
}
func TestUnknownURLNeverFetches(t *testing.T) {
	var calls atomic.Int64
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls.Add(1) }))
	defer s.Close()
	_, e := LoadRegistry(fixture(t, map[string]string{"a.json": `{"$ref":"` + s.URL + `/unknown"}`}))
	if e == nil {
		t.Error("unknown remote schema resolved")
	}
	if calls.Load() != 0 {
		t.Fatal("schema resolution used network")
	}
}
func TestDuplicateIDRejected(t *testing.T) {
	_, e := LoadRegistry(fixture(t, map[string]string{"a.json": `{"$id":"https://example.test/same"}`, "b.json": `{"$id":"https://example.test/same"}`}))
	if e == nil {
		t.Fatal("duplicate identity accepted")
	}
}
func TestPathCannotEscapeRoot(t *testing.T) {
	_, e := LoadRegistry(fixture(t, map[string]string{"a.json": `{"$ref":"../outside.json"}`}))
	if e == nil {
		t.Fatal("escape accepted")
	}
}
func TestMalformedRefHasSourcePointer(t *testing.T) {
	_, e := LoadRegistry(fixture(t, map[string]string{"a.json": `{"properties":{"x":{"$ref":"#/%GG"}}}`}))
	if e == nil || !strings.Contains(e.Error(), "a.json#/properties/x/$ref") {
		t.Fatalf("missing source: %v", e)
	}
}
func TestScopedIdentityAndConflicts(t *testing.T) {
	r := load(t, `{"$id":"https://example.test/root","$defs":{"nested":{"$id":"child","type":"string","$defs":{"n":{"type":"integer"}},"properties":{"a":{"$ref":"#/$defs/n"}}}}}`)
	n, e := r.Resolve("https://example.test/child", "#/$defs/n")
	if e != nil || n.Pointer != "/$defs/nested/$defs/n" {
		t.Fatalf("scoped target: %+v %v", n, e)
	}
	_, e = LoadRegistry(fixture(t, map[string]string{"a.json": `{"$id":"https://example.test/a","$defs":{"a":{"$id":"same"},"b":{"$id":"same"}}}`}))
	if e == nil {
		t.Fatal("nested identity collision accepted")
	}
}
func TestValidationDoesNotApplyDefaults(t *testing.T) {
	r := load(t, `{"$id":"https://example.test/a","type":"object","properties":{"x":{"type":"integer","default":7}},"required":["x"]}`)
	b := []byte(`{}`)
	if e := r.Validate("https://example.test/a", b); e == nil {
		t.Fatal("missing required field accepted/default inserted")
	}
	if string(b) != "{}" {
		t.Fatal("input mutated")
	}
}

func TestScopedCrossDocumentAndUnknownTarget(t *testing.T) {
	root := fixture(t, map[string]string{"a.json": `{"$id":"https://example.test/root","$defs":{"child":{"$id":"child","$defs":{"number":{"type":"integer"}},"x-container":{"target":{"$ref":"#/$defs/number"}},"$ref":"#/x-container/target"}}}`, "b.json": `{"$id":"https://example.test/b","$ref":"https://example.test/child"}`})
	r, e := LoadRegistry(root)
	if e != nil {
		t.Fatal(e)
	}
	if e = r.Validate("https://example.test/b", []byte(`2`)); e != nil {
		t.Fatal(e)
	}
	if e = r.Validate("https://example.test/b", []byte(`"two"`)); e == nil {
		t.Fatal("scoped target constraint lost")
	}
}
func TestMetadataDoesNotDeclareIdentity(t *testing.T) {
	r := load(t, `{"$id":"https://example.test/a","default":{"$id":"https://example.test/a","$ref":"https://outside.test/no"}}`)
	if _, e := r.Check(); e != nil {
		t.Fatal(e)
	}
}
func TestFalseSchemaAndAnchors(t *testing.T) {
	r := load(t, `{"$id":"https://example.test/a","$defs":{"never":false,"n":{"$anchor":"number","type":"integer"}},"$ref":"#number"}`)
	if e := r.Validate("https://example.test/a", []byte(`1`)); e != nil {
		t.Fatal(e)
	}
	if e := r.Validate("https://example.test/a#/$defs/never", []byte(`null`)); e == nil {
		t.Fatal("false schema ignored")
	}
}
func TestStrictLegacyIdentityRejection(t *testing.T) {
	if _, e := LoadRegistry(corpusRoot(t)); e == nil || !strings.Contains(e.Error(), "duplicate identity") {
		t.Fatalf("legacy silently admitted: %v", e)
	}
}

func TestNamedFixtures(t *testing.T) {
	for _, tc := range []struct {
		name  string
		valid bool
	}{{"recursive.json", true}, {"pointer-escaping.json", true}, {"external-ref.json", false}, {"invalid-ref.json", false}, {"duplicate-id.json", false}} {
		t.Run(tc.name, func(t *testing.T) {
			b, e := os.ReadFile("../../testdata/schemas/" + tc.name)
			if e != nil {
				t.Fatal(e)
			}
			_, e = LoadRegistry(fixture(t, map[string]string{tc.name: string(b)}))
			if (e == nil) != tc.valid {
				t.Fatalf("valid=%v: %v", tc.valid, e)
			}
		})
	}
}

func TestDuplicateJSONKeysRejected(t *testing.T) {
	_, e := LoadRegistry(fixture(t, map[string]string{"a.json": `{"type":"integer","type":"string"}`}))
	if e == nil {
		t.Fatal("duplicate constraint silently replaced")
	}
}

func TestMalformedSchemaInputs(t *testing.T) {
	for name, body := range map[string]string{
		"truncated": `{"type":`, "trailing": `{} true`, "bad-key": `{1:true}`, "bad-array": `[true,]`, "scalar": `42`, "null": `null`, "bad-ref": `{"$ref":2}`, "unknown-draft": `{"$schema":"https://unregistered.invalid/draft"}`, "bad-id": `{"$id":"http://[bad"}`, "fragment-id": `{"$id":"https://example.test/a#foo"}`, "missing-anchor": `{"$ref":"#missing"}`, "bad-pointer-escape": `{"$ref":"#/~2"}`, "query": `{"$ref":"a.json?query"}`, "deep": strings.Repeat(`{"items":`, 258) + `true` + strings.Repeat(`}`, 258),
	} {
		t.Run(name, func(t *testing.T) {
			if _, e := LoadRegistry(fixture(t, map[string]string{"a.json": body})); e == nil {
				t.Fatal("malformed/unsupported schema accepted")
			}
		})
	}
	if _, e := LoadRegistry(t.TempDir()); e == nil {
		t.Fatal("empty root accepted")
	}
	if _, e := LoadRegistry(filepath.Join(t.TempDir(), "missing")); e == nil {
		t.Fatal("missing root accepted")
	}
}
func TestResolveRejectsUnknownBaseAndFragments(t *testing.T) {
	r := load(t, `{"$id":"https://example.test/a"}`)
	for _, tc := range [][2]string{{"relative", "#"}, {"http://[bad", "#"}, {"https://example.test/a", "#/~"}, {"https://example.test/a", "#/absent"}, {"https://example.test/a", "https://user@example.test/a"}} {
		if _, e := r.Resolve(tc[0], tc[1]); e == nil {
			t.Fatalf("bad reference accepted: %v", tc)
		}
	}
}
func TestDocumentSizeBound(t *testing.T) {
	_, e := LoadRegistry(fixture(t, map[string]string{"a.json": `{"description":"` + strings.Repeat("a", 16<<20) + `"}`}))
	if e == nil || !strings.Contains(e.Error(), "16 MiB") {
		t.Fatalf("missing document bound: %v", e)
	}
}

func TestDraft7RefIgnoresSchemaSiblings(t *testing.T) {
	var calls atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { calls.Add(1) }))
	defer server.Close()
	for _, ignoredURL := range []string{"https://unregistered.invalid/ignored", server.URL + "/ignored"} {
		t.Run(ignoredURL, func(t *testing.T) {
			raw := `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/value","definitions":{"value":{"type":"integer"}},"properties":{"ignored":{"$ref":"` + ignoredURL + `"}}}`
			r := load(t, raw)
			nodes := r.Nodes()
			if len(nodes) != 2 || string(nodes[0].Document) != raw {
				t.Fatalf("ignored siblings admitted or raw metadata changed: %+v", nodes)
			}
			target, err := r.Resolve(nodes[0].ID, "#/definitions/value")
			if err != nil || target.Pointer != "/definitions/value" || string(target.Document) != `{"type":"integer"}` {
				t.Fatalf("required target missing: %+v %v", target, err)
			}
			counts, err := r.Check()
			if err != nil || counts != (CheckResult{Documents: 1, References: 1, Nodes: 2, Compiled: 2}) {
				t.Fatalf("reference-object check: %+v %v", counts, err)
			}
			if err := r.Validate(nodes[0].ID, []byte(`1`)); err != nil {
				t.Fatal(err)
			}
			if err := r.Validate(nodes[0].ID, []byte(`"one"`)); err == nil {
				t.Fatal("required integer target constraint lost")
			}
		})
	}
	if calls.Load() != 0 {
		t.Fatal("ignored reference used network")
	}
}

func TestDraft7RefTargetClosure(t *testing.T) {
	r := load(t, `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/value","definitions":{"value":{"$ref":"#/definitions/actual","properties":{"ignored":{"$ref":"https://unregistered.invalid/ignored"}}},"actual":{"type":"integer","definitions":{"unused":{"type":"strng"}}},"ignored":{"type":"strng"}}}`)
	counts, err := r.Check()
	if counts.Nodes != 4 || counts.References != 2 || err == nil || !strings.Contains(err.Error(), "/definitions/actual/definitions/unused/type") {
		t.Fatalf("required target's unused child not checked: %+v %v", counts, err)
	}
	for _, raw := range []string{
		`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/properties/required","properties":{"required":{"$ref":"https://unregistered.invalid/required"}}}`,
		`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/value","definitions":{"value":"annotation"}}`,
	} {
		if _, err := LoadRegistry(fixture(t, map[string]string{"a.json": raw})); err == nil {
			t.Fatal("explicit target beneath ignored sibling escaped closure")
		}
	}
}

func TestModernRefSchemaSiblingsRemainActive(t *testing.T) {
	for _, draft := range []string{"https://json-schema.org/draft/2019-09/schema", "https://json-schema.org/draft/2020-12/schema"} {
		t.Run(draft, func(t *testing.T) {
			raw := `{"$schema":"` + draft + `","$ref":"#/$defs/value","$defs":{"value":{"type":"integer"}},"properties":{"active":{"$ref":"https://unregistered.invalid/active"}}}`
			if _, err := LoadRegistry(fixture(t, map[string]string{"a.json": raw})); err == nil || !strings.Contains(err.Error(), "/properties/active/$ref") {
				t.Fatalf("active sibling reference ignored: %v", err)
			}
			r := load(t, `{"$schema":"`+draft+`","$ref":"#/$defs/value","$defs":{"value":{"type":"integer"}},"minimum":2}`)
			if _, err := r.Check(); err != nil {
				t.Fatal(err)
			}
			if err := r.Validate(r.Nodes()[0].ID, []byte(`2`)); err != nil {
				t.Fatal(err)
			}
			if err := r.Validate(r.Nodes()[0].ID, []byte(`1`)); err == nil {
				t.Fatal("active sibling constraint lost")
			}
		})
	}
}
