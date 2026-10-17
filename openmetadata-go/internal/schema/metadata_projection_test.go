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
	for _, kind := range []string{"root-schema", "nested-schema", "anchored-id"} {
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
				if admission := r.admitNumericClosure(r.documents["a.json"], map[string]numericAdmission{}); admission.err != nil || admission.cost != 0 {
					t.Fatalf("ordinary metadata became arithmetic/unsupported: %+v", admission)
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
