// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// The first controls retain the independent Task2 review's finite probes.
func TestSelectedSchemaOrdinaryControl(t *testing.T) {
	r := load(t, `{"x":{"type":"integer","minimum":2}}`)
	id := r.documents["a.json"].physical + "#/x"
	if err := r.Validate(id, []byte(`2`)); err != nil {
		t.Fatal(err)
	}
	if err := r.Validate(id, []byte(`1`)); err == nil {
		t.Fatal("selected minimum was ignored")
	}
}

func TestSelectedSchemaAdmission(t *testing.T) {
	for _, tc := range []struct{ body, pointer string }{
		{`{"x":{"minimum":1e10001}}`, "/x/minimum"},
		{`{"x":{"maxItems":9223372036854775808}}`, "/x/maxItems"},
		{`{"x":{"required":[1e10001]}}`, "/x/required/0"},
		{`{"x":{"properties":{"a/b~c":{"minimum":1e10001}}}}`, "/x/properties/a~1b~0c/minimum"},
	} {
		r := load(t, tc.body)
		n, err := r.resolve(r.documents["a.json"].physical, "#/x")
		if err != nil {
			t.Fatal(err)
		}
		// Direct admission only until these inputs have a guard. Never use the
		// unadmitted dependency to establish arithmetic RED.
		requireBlocked(t, r.admitNumericInstance(n, nil), "a.json#"+tc.pointer)
		// Integration is reached only after the direct guard succeeds.
		requireBlocked(t, r.Validate(n.physical+fragment(n.Pointer), []byte(`null`)), "a.json#"+tc.pointer)
	}
}

func TestSelectedSchemaIntroducedReferenceAdmission(t *testing.T) {
	for _, body := range []string{`{"minimum":1e10001}`, `{"maxLength":9223372036854775808}`, `{"required":[1e10001]}`} {
		r, err := LoadRegistry(fixture(t, map[string]string{
			"a.json": `{"x":{"$ref":"b.json#/x"}}`,
			"b.json": `{"x":{"allOf":[{"$ref":"c.json#/x"},{"$ref":"a.json#/x"}]}}`,
			"c.json": `{"x":` + body + `}`,
		}))
		if err != nil {
			t.Fatal(err)
		}
		n, err := r.resolve(r.documents["a.json"].physical, "#/x")
		if err != nil {
			t.Fatal(err)
		}
		requireBlocked(t, r.admitNumericInstance(n, nil), "c.json#/x/")
		requireBlocked(t, r.Validate(n.physical+fragment(n.Pointer), []byte(`null`)), "c.json#/x/")
	}
}

func TestSelectedSchemaBudgetAndCache(t *testing.T) {
	digits := strings.Repeat("1", 9999)
	array := `[` + strings.TrimSuffix(strings.Repeat(digits+",", 100), ",") + `]`
	r := load(t, `{"x":{"allOf":[{"$ref":"#/y"},{"$ref":"#/y"}]},"y":{"const":`+array+`},"bad":{"minimum":1e10001}}`)
	cache := map[string]numericAdmission{}
	if a := r.admitNumericClosure(r.documents["a.json"], cache); a.err != nil || a.cost != 0 {
		t.Fatalf("unselected annotation scanned: %+v", a)
	}
	x, err := r.resolve(r.documents["a.json"].physical, "#/x")
	if err != nil {
		t.Fatal(err)
	}
	if a := r.admitNumericClosure(x, cache); a.err != nil || a.cost != 999900 {
		t.Fatalf("selected closure union: %+v", a)
	}
	bad, _ := r.resolve(r.documents["a.json"].physical, "#/bad")
	requireBlocked(t, r.admitNumericClosure(bad, cache).err, "a.json#/bad/minimum")
	for _, size := range []int{100, 101} {
		instance, err := decode([]byte(`{"a/b~c":[` + strings.TrimSuffix(strings.Repeat("1,", size), ",") + `]}`))
		if err != nil {
			t.Fatal(err)
		}
		err = r.admitNumericInstance(x, instance)
		if size == 100 && err != nil {
			t.Fatal("exact joint budget", err)
		}
		if size == 101 {
			requireBlocked(t, err, "instance #/a~1b~0c/100")
		}
	}
	if len(cache) != 1 || cache["a.json"].cost != 0 {
		t.Fatal("selected view poisoned physical cache", cache)
	}
}

func registrySelectionSnapshot(r *Registry) string {
	var out strings.Builder
	fmt.Fprintf(&out, "%v|%v|%v|%v|%d|", sortedKeys(r.schemas), r.identities, r.ambiguous, r.drafts, len(r.references))
	for _, key := range sortedKeys(r.entries) {
		n := r.entries[key]
		fmt.Fprintf(&out, "%s:%s:%s:%s:%s|", key, n.ID, n.base, n.resourcePointer, n.Document)
	}
	return out.String()
}

func TestSelectedSchemaImmutableConcurrent(t *testing.T) {
	r := load(t, `{"a/b~c":{"$id":"child","$schema":"http://json-schema.org/draft-07/schema#","properties":{"n":{"type":"integer"}},"minContains":9223372036854775808},"bad":{"minimum":1e10001},"missing":{"$ref":"https://unregistered.invalid/no"}}`)
	before := registrySelectionSnapshot(r)
	id := r.documents["a.json"].physical
	bad, _ := r.resolve(id, "#/bad")
	requireBlocked(t, r.admitNumericInstance(bad, nil), "a.json#/bad/minimum")
	var group sync.WaitGroup
	problems := make(chan error, 32)
	for i := 0; i < 8; i++ {
		group.Add(1)
		go func() {
			defer group.Done()
			if err := r.Validate(id+"#/a~1b~0c", []byte(`{"n":1}`)); err != nil {
				problems <- err
			}
			if err := r.Validate(id+"#/a~1b~0c", []byte(`{"n":"wrong"}`)); err == nil {
				problems <- fmt.Errorf("selected descendant ignored")
			}
			if err := r.Validate(id+"#/bad", []byte(`null`)); !errors.Is(err, ErrBlocked) {
				problems <- fmt.Errorf("selected blocker: %v", err)
			}
			if err := r.Validate(id+"#/missing", []byte(`null`)); err == nil {
				problems <- fmt.Errorf("unknown reference fetched or ignored")
			}
		}()
	}
	group.Wait()
	close(problems)
	for err := range problems {
		t.Error(err)
	}
	if after := registrySelectionSnapshot(r); after != before {
		t.Fatal("selected success/failure changed registry metadata or raw bytes")
	}
	if _, err := r.Resolve(id, "child"); err == nil {
		t.Fatal("selected identity escaped request")
	}
	counts, err := r.Check()
	if err != nil || counts.Nodes != 1 || counts.References != 0 || counts.Compiled != 1 {
		t.Fatalf("selection changed Check: %+v %v", counts, err)
	}
}

func TestCollectorIdentityControls(t *testing.T) {
	const d7 = `"$schema":"http://json-schema.org/draft-07/schema#"`
	r, err := LoadRegistry(fixture(t, map[string]string{
		"a#%.json": `{` + d7 + `,"$id":"https://ignored.invalid/root","$ref":"child"}`,
		"b.json":   `{` + d7 + `,"$ref":"#/definitions/pass","definitions":{"pass":true,"a/b~c":{"$id":"child","type":"integer"},"unused":{"$id":"ignored","$ref":"https://unregistered.invalid/no"}},"x":{"$id":"annotation"}}`,
	}))
	if err != nil {
		t.Fatal(err)
	}
	id := r.documents["a#%.json"].physical
	node, err := r.Resolve(id, "child")
	if err != nil || node.Path != "b.json" || node.Pointer != "/definitions/a~1b~0c" {
		t.Fatalf("cross-file collector target: %+v %v", node, err)
	}
	if err = r.Validate(id, []byte(`2`)); err != nil {
		t.Fatal(err)
	}
	if err = r.Validate(id, []byte(`"wrong"`)); err == nil {
		t.Fatal("cross-file target ignored")
	}
	for _, ref := range []string{"ignored", "annotation", "https://ignored.invalid/root"} {
		if _, err = r.Resolve(id, ref); err == nil {
			t.Fatal("ignored/annotation identity registered", ref)
		}
	}
	_, err = LoadRegistry(fixture(t, map[string]string{"a.json": `{` + d7 + `,"$ref":"child","definitions":{"a":{"$id":"child"},"b":{"$id":"child"}}}`}))
	if err == nil || !strings.Contains(err.Error(), "duplicate identity") {
		t.Fatal("duplicate collector identities admitted", err)
	}
}

func TestCollectorCrossFileInheritedDraft(t *testing.T) {
	r, err := LoadRegistry(fixture(t, map[string]string{
		"a.json": `{"$ref":"https://example.test/child"}`,
		"b.json": `{"$schema":"https://json-schema.org/draft/2020-12/schema","properties":{"n":{"$schema":"http://json-schema.org/draft-07/schema#","$id":"https://example.test/child","$ref":"#/$defs/t","$defs":{"t":{"type":"integer"}},"additionalItems":"annotation"}}}`,
	}))
	if err != nil {
		t.Fatal(err)
	}
	if err := r.Validate(r.documents["b.json"].physical, []byte(`{"n":2}`)); err != nil {
		t.Fatal("physical resource control", err)
	}
	if err := r.Validate(r.documents["a.json"].physical, []byte(`2`)); err != nil {
		t.Fatal("cross-file resource changed inherited draft", err)
	}
	if err := r.Validate(r.documents["a.json"].physical, []byte(`"wrong"`)); err == nil {
		t.Fatal("cross-file resource lost assertion")
	}
}

func TestCollectorIgnoredSiblingResourceIdentity(t *testing.T) {
	raw := `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"child","definitions":{"target":{"$id":"child","type":"integer"},"unused":{"$ref":"https://unregistered.invalid/ignored"}}}`
	value, err := decode([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	c := jsonschema.NewCompiler()
	if err = c.AddResource("https://example.test/a.json", value); err != nil {
		t.Fatal(err)
	}
	direct, err := c.Compile("https://example.test/a.json")
	if err != nil {
		t.Fatal("pinned ordinary compile", err)
	}
	if direct.Validate(2) != nil || direct.Validate("wrong") == nil {
		t.Fatal("pinned integer target")
	}
	r := load(t, raw)
	if err = r.Validate(r.documents["a.json"].physical, []byte(`2`)); err != nil {
		t.Fatal(err)
	}
	if err = r.Validate(r.documents["a.json"].physical, []byte(`"wrong"`)); err == nil {
		t.Fatal("target integer ignored")
	}
	counts, err := r.Check()
	if err != nil || counts.Nodes != 2 || counts.References != 1 || counts.Compiled != 2 {
		t.Fatalf("ignored siblings activated: %+v %v", counts, err)
	}
}
