// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"errors"
	"fmt"
	"net/url"
	"strings"
	"sync"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

func requireMetadataRejection(t *testing.T, err error, path, pointer string) {
	t.Helper()
	if !metadataRejectedAt(err, path, pointer) {
		t.Fatalf("want canonical metadata rejection at %s#%s, got %v", path, pointer, err)
	}
}

func metadataRejectedAt(err error, path, pointer string) bool {
	var diagnostic *Diagnostic
	return err != nil && !errors.Is(err, ErrBlocked) && errors.As(err, &diagnostic) && diagnostic.Path == path && diagnostic.Pointer == pointer && strings.Contains(err.Error(), "want string")
}

func TestMalformedMetadataProjectionControls(t *testing.T) {
	for _, kind := range []string{"root-schema", "nested-schema", "root-id", "anchored-id"} {
		for _, token := range []string{"42", "null", "false", "[]", "{}"} {
			t.Run(kind+"/"+token, func(t *testing.T) {
				const childPointer = "/$defs/a~1b~0c"
				var raw, selector, pointer, target string
				switch kind {
				case "root-schema":
					raw = `{"$id":"dir/root","$schema":` + token + `,"type":"integer"}`
					selector, pointer = "dir/root", "/$schema"
				case "nested-schema":
					raw = `{"$schema":"https://json-schema.org/draft/2020-12/schema","$defs":{"a/b~c":{"$id":"dir/child","$schema":` + token + `,"type":"integer"}}}`
					selector, pointer, target = "dir/child", childPointer+"/$schema", childPointer
				case "anchored-id":
					raw = `{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"dir/root","$defs":{"a/b~c":{"$anchor":"leaf","$id":` + token + `,"type":"integer"}}}`
					selector, pointer, target = "dir/root#leaf", childPointer+"/$id", childPointer
				case "root-id":
					raw = `{"$id":` + token + `,"type":"integer"}`
					selector, pointer = "b%23%25.json", "/$id"
				}
				value, err := decode([]byte(raw))
				if err != nil {
					t.Fatal(err)
				}
				c := jsonschema.NewCompiler()
				physical := (&url.URL{Scheme: "https", Host: "example.test", Path: "/b#%.json"}).String()
				if err = c.AddResource(physical, value); err != nil {
					t.Fatal(err)
				}
				if _, err = c.Compile(physical + fragment(target)); err == nil || !strings.Contains(err.Error(), "want string") {
					t.Fatal("pinned canonical metadata control", err)
				}
				r, err := LoadRegistry(fixture(t, map[string]string{
					"a.json": `{"$ref":"` + selector + `"}`, "b#%.json": raw, "c.json": `true`,
				}))
				if err != nil {
					t.Fatal(err)
				}
				before := registrySelectionSnapshot(r)
				admission := r.admitNumericClosure(r.documents["a.json"], map[string]numericAdmission{})
				if admission.cost != 0 || errors.Is(admission.err, ErrBlocked) {
					t.Fatalf("ordinary metadata became arithmetic/unsupported: %+v", admission)
				}
				if strings.HasSuffix(kind, "schema") {
					requireMetadataRejection(t, admission.err, "b#%.json", pointer)
				} else if admission.err != nil {
					t.Fatal(admission.err)
				}
				ids := []string{r.documents["b#%.json"].physical + fragment(target), r.documents["a.json"].physical}
				var group sync.WaitGroup
				problems := make(chan error, 6)
				for repeat := 0; repeat < 3; repeat++ {
					group.Add(1)
					go func() {
						defer group.Done()
						for _, id := range ids {
							err := r.Validate(id, []byte(`2`))
							if !metadataRejectedAt(err, "b#%.json", pointer) {
								problems <- fmt.Errorf("%s expected%s canonical error: %v", id, pointer, err)
							}
						}
					}()
				}
				group.Wait()
				close(problems)
				for err := range problems {
					t.Error(err)
				}
				counts, err := r.Check()
				requireMetadataRejection(t, err, "b#%.json", pointer)
				if counts.Compiled != 1 {
					t.Fatalf("invalid metadata counted or independent node skipped: %+v", counts)
				}
				if registrySelectionSnapshot(r) != before {
					t.Fatal("canonical metadata rejection mutated source/identity/scope")
				}
			})
		}
	}
}

// Ported from the independent fix2 re-review's finite malformed-dialect probe.
func TestRootAliasMalformedDialect(t *testing.T) {
	raw := `{"$id":"dir/root","$schema":42,"type":"integer"}`
	value, err := decode([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	c := jsonschema.NewCompiler()
	if err = c.AddResource("https://example.test/b.json", value); err != nil {
		t.Fatal(err)
	}
	if _, err = c.Compile("https://example.test/b.json"); err == nil {
		t.Fatal("pinned physical source accepted malformed $schema")
	} else {
		t.Log("pinned physical rejects", err)
	}
	r, err := LoadRegistry(fixture(t, map[string]string{"a.json": `{"$ref":"dir/root"}`, "b.json": raw}))
	if err != nil {
		t.Fatal(err)
	}
	requireMetadataRejection(t, r.Validate(r.documents["b.json"].physical, []byte(`2`)), "b.json", "/$schema")
	requireMetadataRejection(t, r.Validate(r.documents["a.json"].physical, []byte(`2`)), "b.json", "/$schema")
}

// Ported from the independent fix3 review. The ordinary probe established that
// alias retrieval changed the compiler's metaschema arithmetic domain to 2020.
func malformedSevenResource(t *testing.T, numbers string) *Registry {
	t.Helper()
	r, err := LoadRegistry(fixture(t, map[string]string{
		"a.json": `{"$ref":"dir/child"}`,
		"b.json": `{"$schema":"http://json-schema.org/draft-07/schema#","definitions":{"target":{"$id":"dir/child","$schema":42,"dependentRequired":{"x":[` + numbers + `]}}}}`,
	}))
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func TestMalformedResourceOrdinaryDraft(t *testing.T) {
	r := malformedSevenResource(t, "1,2")
	for _, id := range []string{r.documents["b.json"].physical + "#/definitions/target", r.documents["a.json"].physical} {
		err := r.Validate(id, []byte(`2`))
		t.Logf("%s: %v", id, err)
		requireMetadataRejection(t, err, "b.json", "/definitions/target/$schema")
		if strings.Contains(err.Error(), "dependentRequired") {
			t.Fatal("alias evaluated Draft2020 arithmetic despite collected Draft7 scope")
		}
	}
}

func TestMalformedResourceAdmission(t *testing.T) {
	r := malformedSevenResource(t, "1e10001,2")
	// Direct preflight only: never Compile/Validate this source to establish RED.
	admission := r.admitNumericClosure(r.documents["a.json"], map[string]numericAdmission{})
	if admission.err == nil {
		t.Fatalf("compiler-visible arithmetic admitted without guard: cost=%d", admission.cost)
	}
	requireMetadataRejection(t, admission.err, "b.json", "/definitions/target/$schema")
}

func TestMalformedResourceGuardedIntegration(t *testing.T) {
	for _, draft := range []string{"", "http://json-schema.org/draft-07/schema#", "https://json-schema.org/draft/2019-09/schema", "https://json-schema.org/draft/2020-12/schema"} {
		for _, token := range []string{"42", "null", "false", "[]", "{}", "[1e10001,2]", `{"number":1e10001}`} {
			t.Run(draft+"/"+token, func(t *testing.T) {
				declaration := ""
				if draft != "" {
					declaration = `"$schema":"` + draft + `",`
				}
				r, err := LoadRegistry(fixture(t, map[string]string{
					"a.json":   `{"$ref":"dir/child"}`,
					"b#%.json": `{` + declaration + `"definitions":{"a/b~c":{"$id":"dir/child","$schema":` + token + `,"dependentRequired":{"x":[1e10001,2]}}}}`,
					"c.json":   `{"type":"integer"}`,
				}))
				if err != nil {
					t.Fatal(err)
				}
				const pointer = "/definitions/a~1b~0c/$schema"
				before := registrySelectionSnapshot(r)
				// Both direct entry points must reject canonically BEFORE any public
				// integration; a guard regression stops this test at the safe boundary.
				for _, path := range []string{"a.json", "b#%.json"} {
					admission := r.admitNumericClosure(r.documents[path], map[string]numericAdmission{})
					requireMetadataRejection(t, admission.err, "b#%.json", pointer)
					if admission.cost != 0 {
						t.Fatalf("malformed declaration reached sibling arithmetic: %+v", admission)
					}
					var meta *jsonschema.SchemaValidationError
					var validation *jsonschema.ValidationError
					if !errors.As(admission.err, &meta) || !errors.As(meta.Err, &validation) {
						t.Fatalf("lost native canonical error: %v", admission.err)
					}
					wantDraft := draft
					if wantDraft == "" {
						wantDraft = "https://json-schema.org/draft/2020-12/schema"
					}
					if strings.TrimSuffix(validation.SchemaURL, "#") != strings.TrimSuffix(wantDraft, "#") {
						t.Fatalf("canonical rejection draft %q, want %q", validation.SchemaURL, wantDraft)
					}
				}
				var group sync.WaitGroup
				problems := make(chan error, 9)
				for repeat := 0; repeat < 3; repeat++ {
					group.Add(1)
					go func() {
						defer group.Done()
						for _, id := range []string{r.documents["a.json"].physical, r.documents["b#%.json"].physical + "#/definitions/a~1b~0c"} {
							if err := r.Validate(id, []byte(`2`)); !metadataRejectedAt(err, "b#%.json", pointer) {
								problems <- fmt.Errorf("lost guarded canonical rejection: %v", err)
							}
						}
						if err := r.Validate(r.documents["c.json"].physical, []byte(`2`)); err != nil {
							problems <- err
						}
					}()
				}
				group.Wait()
				close(problems)
				for err := range problems {
					t.Error(err)
				}
				counts, err := r.Check()
				requireMetadataRejection(t, err, "b#%.json", pointer)
				if counts.Compiled != 1 {
					t.Fatalf("independent successful Compile count: %+v", counts)
				}
				if registrySelectionSnapshot(r) != before {
					t.Fatal("early rejection mutated source/identity/graph")
				}
			})
		}
	}
}
