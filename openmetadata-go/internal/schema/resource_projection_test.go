// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"fmt"
	"net/url"
	"sync"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// Ported from the independent fix1 re-review's finite relative-resource probe.
func TestCollectorRelativeIDCrossFile(t *testing.T) {
	files := map[string]string{
		"a.json":     `{"$ref":"dir/child"}`,
		"b.json":     `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/pass","definitions":{"pass":true,"target":{"$id":"dir/child","allOf":[{"$ref":"../value.json"}]}}}`,
		"value.json": `{"type":"integer"}`,
	}
	c := jsonschema.NewCompiler()
	for name, raw := range files {
		value, err := decode([]byte(raw))
		if err != nil {
			t.Fatal(err)
		}
		if err = c.AddResource("https://example.test/"+name, value); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := c.Compile("https://example.test/b.json"); err != nil {
		t.Fatal(err)
	}
	direct, err := c.Compile("https://example.test/b.json#/definitions/target")
	if err != nil {
		t.Fatal("pinned ordinary resource", err)
	}
	if direct.Validate(2) != nil || direct.Validate("bad") == nil {
		t.Fatal("pinned integer control")
	}
	r, err := LoadRegistry(fixture(t, files))
	if err != nil {
		t.Fatal(err)
	}
	if err = r.Validate(r.documents["b.json"].physical+"#/definitions/target", []byte(`2`)); err != nil {
		t.Fatal("physical target", err)
	}
	if err = r.Validate(r.documents["a.json"].physical, []byte(`2`)); err != nil {
		t.Fatal("cross-file target changed base", err)
	}
	if err = r.Validate(r.documents["a.json"].physical, []byte(`"bad"`)); err == nil {
		t.Fatal("integer assertion lost")
	}
}

func TestScopedResourceProjectionControls(t *testing.T) {
	const d7 = "http://json-schema.org/draft-07/schema#"
	const d20 = "https://json-schema.org/draft/2020-12/schema"
	for _, tc := range []struct {
		name, root, child         string
		draft                     int
		nested, anchor, directRef bool
	}{
		{"seven", d7, "", 7, false, false, false},
		{"seven-to-twenty", d7, d20, 2020, false, false, false},
		{"twenty-to-seven", d20, d7, 7, false, false, false},
		{"default", "", "", 2020, false, false, false},
		{"ref-fallback-twenty", d20, d7, 2020, false, false, true},
		{"nested-seven", d7, "", 7, true, false, false},
		{"nested-anchor", d20, d20, 2020, true, true, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			id, ref, pointer, selector := "dir/child", "../value.json", "/definitions/a~1b~0c", "dir/child"
			if tc.nested {
				id, ref, pointer, selector = "nested/child", "../../value.json", pointer+"/definitions/a~1b~0c", "dir/nested/child"
			}
			target := `"$id":"` + id + `",`
			if tc.child != "" {
				target += `"$schema":"` + tc.child + `",`
			}
			if tc.anchor {
				target += `"$anchor":"leaf",`
				selector += "#leaf"
			}
			if tc.directRef {
				target += `"$ref":"` + ref + `","additionalItems":"annotation"`
			} else {
				target += `"allOf":[{"$ref":"` + ref + `"},{"$ref":"` + ref + `"}]`
			}
			target = "{" + target + "}"
			if tc.nested {
				target = `{"$id":"dir/parent","definitions":{"a/b~c":` + target + `}}`
			}
			root := ""
			if tc.root != "" {
				root = `"$schema":"` + tc.root + `",`
			}
			files := map[string]string{
				"a#%.json":   `{"$ref":"` + selector + `"}`,
				"b#%.json":   `{` + root + `"$ref":"#/definitions/pass","definitions":{"pass":true,"a/b~c":` + target + `}}`,
				"value.json": `{"type":"integer","minimum":2}`,
			}
			c := jsonschema.NewCompiler()
			for name, raw := range files {
				value, err := decode([]byte(raw))
				if err != nil {
					t.Fatal(err)
				}
				if err = c.AddResource((&url.URL{Scheme: "https", Host: "example.test", Path: "/" + name}).String(), value); err != nil {
					t.Fatal(err)
				}
			}
			physical := (&url.URL{Scheme: "https", Host: "example.test", Path: "/b#%.json"}).String()
			if _, err := c.Compile(physical); err != nil {
				t.Fatal("pinned document", err)
			}
			direct, err := c.Compile(physical + fragment(pointer))
			if err != nil {
				t.Fatal("pinned target", err)
			}
			if direct.DraftVersion != tc.draft {
				t.Fatalf("pinned draft%d want%d", direct.DraftVersion, tc.draft)
			}
			if direct.Validate(2) != nil || direct.Validate(1) == nil || direct.Validate("bad") == nil {
				t.Fatal("pinned constraints")
			}
			r, err := LoadRegistry(fixture(t, files))
			if err != nil {
				t.Fatal(err)
			}
			before := registrySelectionSnapshot(r)
			admission := r.admitNumericClosure(r.documents["a#%.json"], map[string]numericAdmission{})
			if admission.err != nil || admission.cost != 1 {
				t.Fatalf("source target admission/dedup %+v", admission)
			}
			ids := []string{r.documents["b#%.json"].physical + fragment(pointer), r.documents["a#%.json"].physical}
			var group sync.WaitGroup
			problems := make(chan error, 24)
			for repeat := 0; repeat < 4; repeat++ {
				group.Add(1)
				go func() {
					defer group.Done()
					for _, id := range ids {
						for _, instance := range []string{`2`, `1`, `"bad"`} {
							err := r.Validate(id, []byte(instance))
							if (err == nil) != (instance == `2`) {
								problems <- fmt.Errorf("%s instance%s: %v", id, instance, err)
							}
						}
					}
				}()
			}
			group.Wait()
			close(problems)
			for err := range problems {
				t.Error(err)
			}
			if registrySelectionSnapshot(r) != before {
				t.Fatal("projection changed loaded source, IDs or scope")
			}
		})
	}
}

func TestScopedResourceProjectionAdmissionAttribution(t *testing.T) {
	for _, tc := range []struct{ body, pointer string }{
		{`{"minimum":1e10001}`, "/minimum"},
		{`{"maxItems":9223372036854775808}`, "/maxItems"},
		{`{"required":[1e10001]}`, "/required/0"},
	} {
		r, err := LoadRegistry(fixture(t, map[string]string{
			"a.json":     `{"$ref":"dir/child"}`,
			"b.json":     `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/pass","definitions":{"pass":true,"target":{"$id":"dir/child","allOf":[{"$ref":"../value.json"}]}}}`,
			"value.json": tc.body,
		}))
		if err != nil {
			t.Fatal(err)
		}
		n := r.documents["a.json"]
		before := registrySelectionSnapshot(r)
		// Unsafe dependency integration cannot be reached if admission regresses.
		requireBlocked(t, r.admitNumericInstance(n, nil), "value.json#"+tc.pointer)
		requireBlocked(t, r.Validate(n.physical, []byte(`null`)), "value.json#"+tc.pointer)
		if registrySelectionSnapshot(r) != before {
			t.Fatal("blocked projection changed registry")
		}
	}
}

// Ported from the controller-authorized finite frozen-source root-alias probe.
func TestRootAliasEffectiveBase(t *testing.T) {
	files := map[string]string{
		"a.json":     `{"$ref":"dir/root"}`,
		"b.json":     `{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"dir/root","$ref":"../value.json"}`,
		"value.json": `{"type":"integer","minimum":2}`,
	}
	c := jsonschema.NewCompiler()
	for name, raw := range files {
		value, err := decode([]byte(raw))
		if err != nil {
			t.Fatal(err)
		}
		if err = c.AddResource("https://example.test/"+name, value); err != nil {
			t.Fatal(err)
		}
	}
	direct, err := c.Compile("https://example.test/b.json")
	if err != nil {
		t.Fatal("pinned physical compile", err)
	}
	if direct.Validate(2) != nil || direct.Validate(1) == nil || direct.Validate("bad") == nil {
		t.Fatal("pinned controls")
	}
	t.Log("pinned physical root accepts2/rejects1/string")
	r, err := LoadRegistry(fixture(t, files))
	if err != nil {
		t.Fatal("registry load", err)
	}
	physical := r.documents["b.json"].physical
	if err = r.Validate(physical, []byte(`2`)); err != nil {
		t.Fatal("physical root", err)
	}
	if err = r.Validate(physical, []byte(`1`)); err == nil {
		t.Fatal("physical minimum ignored")
	}
	t.Log("registry physical root accepts2/rejects1")
	admission := r.admitNumericClosure(r.documents["a.json"], map[string]numericAdmission{})
	if admission.err != nil || admission.cost != 1 {
		t.Fatalf("intended source admission: %+v", admission)
	}
	t.Log("collected source admission addresses value.json minimum2 once")
	if err = r.Validate(r.documents["a.json"].physical, []byte(`2`)); err != nil {
		t.Fatal("cross-file root alias changed effective base", err)
	}
	if err = r.Validate(r.documents["a.json"].physical, []byte(`1`)); err == nil {
		t.Fatal("cross-file minimum ignored")
	}
}

func TestRootAliasProjectionControls(t *testing.T) {
	for _, tc := range []struct {
		name, prefix, body, selector string
		draft                        int
	}{
		{"seven", `"$schema":"http://json-schema.org/draft-07/schema#",`, `"allOf":[{"$ref":"../value.json"},{"$ref":"../value.json"}]`, "dir/root", 7},
		{"twenty", `"$schema":"https://json-schema.org/draft/2020-12/schema",`, `"$ref":"../value.json"`, "dir/root", 2020},
		{"default", "", `"$ref":"../value.json"`, "dir/root", 2020},
		{"nested-anchors", `"$schema":"https://json-schema.org/draft/2020-12/schema",`, `"$anchor":"parent","$ref":"nested/child#leaf","$defs":{"a/b~c":{"$id":"nested/child","$anchor":"leaf","allOf":[{"$ref":"../../value.json"},{"$ref":"../../value.json"}]}}`, "dir/root#parent", 2020},
	} {
		t.Run(tc.name, func(t *testing.T) {
			files := map[string]string{
				"a#%.json":   `{"$ref":"` + tc.selector + `"}`,
				"b#%.json":   `{` + tc.prefix + `"$id":"dir/root",` + tc.body + `}`,
				"value.json": `{"type":"integer","minimum":2}`,
			}
			c := jsonschema.NewCompiler()
			for name, raw := range files {
				value, err := decode([]byte(raw))
				if err != nil {
					t.Fatal(err)
				}
				if err = c.AddResource((&url.URL{Scheme: "https", Host: "example.test", Path: "/" + name}).String(), value); err != nil {
					t.Fatal(err)
				}
			}
			physical := (&url.URL{Scheme: "https", Host: "example.test", Path: "/b#%.json"}).String()
			direct, err := c.Compile(physical)
			if err != nil {
				t.Fatal("pinned physical root", err)
			}
			if direct.DraftVersion != tc.draft || direct.Validate(2) != nil || direct.Validate(1) == nil || direct.Validate("bad") == nil {
				t.Fatal("pinned draft/instance control")
			}
			r, err := LoadRegistry(fixture(t, files))
			if err != nil {
				t.Fatal(err)
			}
			before := registrySelectionSnapshot(r)
			if a := r.admitNumericClosure(r.documents["a#%.json"], map[string]numericAdmission{}); a.err != nil || a.cost != 1 {
				t.Fatalf("root alias admission targets/dedup %+v", a)
			}
			ids := []string{r.documents["a#%.json"].physical, r.documents["b#%.json"].physical}
			var group sync.WaitGroup
			problems := make(chan error, 24)
			for repeat := 0; repeat < 4; repeat++ {
				group.Add(1)
				go func() {
					defer group.Done()
					for _, id := range ids {
						for _, instance := range []string{`2`, `1`, `"bad"`} {
							err := r.Validate(id, []byte(instance))
							if (err == nil) != (instance == `2`) {
								problems <- fmt.Errorf("root%s instance%s: %v", id, instance, err)
							}
						}
					}
				}()
			}
			group.Wait()
			close(problems)
			for err := range problems {
				t.Error(err)
			}
			if registrySelectionSnapshot(r) != before {
				t.Fatal("root alias changed source or identities")
			}
		})
	}
	ignored := load(t, `{"$schema":"http://json-schema.org/draft-07/schema#","$id":"dir/ignored","$ref":"#/definitions/value","definitions":{"value":{"type":"integer"}}}`)
	id := ignored.documents["a.json"].physical
	if _, err := ignored.Resolve(id, "dir/ignored"); err == nil {
		t.Fatal("Draft7 ref-object root ID activated")
	}
	if err := ignored.Validate(id, []byte(`2`)); err != nil {
		t.Fatal("ignored root ID changed physical base", err)
	}
}

func TestRootAliasAdmissionAttribution(t *testing.T) {
	r, err := LoadRegistry(fixture(t, map[string]string{
		"a.json":     `{"$ref":"dir/root"}`,
		"b.json":     `{"$id":"dir/root","$ref":"../value.json"}`,
		"value.json": `{"minimum":1e10001}`,
	}))
	if err != nil {
		t.Fatal(err)
	}
	before := registrySelectionSnapshot(r)
	n := r.documents["a.json"]
	requireBlocked(t, r.admitNumericInstance(n, nil), "value.json#/minimum")
	requireBlocked(t, r.Validate(n.physical, []byte(`2`)), "value.json#/minimum")
	if registrySelectionSnapshot(r) != before {
		t.Fatal("blocked root alias changed registry")
	}
}
