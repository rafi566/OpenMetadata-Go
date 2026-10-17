// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

func TestDeclaredDraftUsesResourceScope(t *testing.T) {
	const draft7 = "http://json-schema.org/draft-07/schema#"
	const draft20 = "https://json-schema.org/draft/2020-12/schema"
	for _, tc := range []struct {
		name, root, child, id, items, additional, valid, invalid string
		draft, nodes                                             int
	}{
		{"7-to-20-no-id", draft7, draft20, "", `[{"type":"integer"}]`, `{"type":"string"}`, `{"n":[1,"two"]}`, `{"n":[1,2]}`, 7, 4},
		{"7-to-20-resource", draft7, draft20, `"$id":"child",`, `{"type":"integer"}`, `"annotation"`, `{"n":[1,2]}`, `{"n":[1,"two"]}`, 2020, 3},
		{"20-to-7-no-id", draft20, draft7, "", `{"type":"integer"}`, `"annotation"`, `{"n":[1,2]}`, `{"n":[1,"two"]}`, 2020, 3},
		{"20-to-7-resource", draft20, draft7, `"$id":"child",`, `[{"type":"integer"}]`, `{"type":"string"}`, `{"n":[1,"two"]}`, `{"n":[1,2]}`, 7, 4},
	} {
		t.Run(tc.name, func(t *testing.T) {
			raw := `{"$schema":"` + tc.root + `","properties":{"n":{"$schema":"` + tc.child + `",` + tc.id + `"items":` + tc.items + `,"additionalItems":` + tc.additional + `}}}`
			value, err := decode([]byte(raw))
			if err != nil {
				t.Fatal(err)
			}
			c := jsonschema.NewCompiler()
			c.UseRegexpEngine(genericRegexp)
			if err = c.AddResource("https://example.test/root", value); err != nil {
				t.Fatal(err)
			}
			pinned, err := c.Compile("https://example.test/root")
			if err != nil {
				t.Fatalf("bounded pinned control failed: %v", err)
			}
			if pinned.Properties["n"].DraftVersion != tc.draft {
				t.Fatalf("pinned child draft=%d want%d", pinned.Properties["n"].DraftVersion, tc.draft)
			}
			r, err := LoadRegistry(fixture(t, map[string]string{"a.json": raw}))
			if err != nil {
				t.Fatalf("registry rejected pinned-valid resource scope: %v", err)
			}
			counts, err := r.Check()
			if err != nil || counts.Nodes != tc.nodes || counts.Compiled != tc.nodes {
				t.Fatalf("registry/pinned graph activity diverged: %+v %v; want%d", counts, err, tc.nodes)
			}
			for _, instance := range []string{tc.valid, tc.invalid} {
				value, err := decode([]byte(instance))
				if err != nil {
					t.Fatal(err)
				}
				direct := pinned.Validate(value)
				checked := r.Validate(r.documents["a.json"].physical, []byte(instance))
				if (direct == nil) != (checked == nil) || (instance == tc.valid && direct != nil) || (instance == tc.invalid && direct == nil) {
					t.Fatalf("instance%s pinned=%v registry=%v", instance, direct, checked)
				}
			}
		})
	}
}

func TestDraftScopeIgnoredReferenceIDsAndMetadata(t *testing.T) {
	const d7 = "http://json-schema.org/draft-07/schema#"
	const d20 = "https://json-schema.org/draft/2020-12/schema"
	for _, tc := range []struct {
		name, raw, valid, invalid string
		draft, nodes              int
	}{
		{"id-ignored-under-seven-ref", `{"$schema":"` + d7 + `","definitions":{"t":{"type":"integer"}},"properties":{"n":{"$schema":"` + d7 + `","$id":"ignored","$ref":"#/definitions/t"}}}`, `{"n":1}`, `{"n":"one"}`, 7, 3},
		{"seven-ref-falls-back-to-twenty-resource", `{"$schema":"` + d20 + `","properties":{"n":{"$schema":"` + d7 + `","$id":"child","$ref":"#/$defs/t","$defs":{"t":{"type":"integer"}},"additionalItems":"annotation"}}}`, `{"n":1}`, `{"n":"one"}`, 2020, 3},
		{"metadata-cannot-select-resource-draft", `{"$schema":"` + d20 + `","$ref":"#/x-container/target","x-container":{"$id":"ignored","$schema":"` + d7 + `","target":{"items":{"type":"integer"},"additionalItems":"annotation"}}}`, `[1]`, `["one"]`, 2020, 3},
	} {
		t.Run(tc.name, func(t *testing.T) {
			value, err := decode([]byte(tc.raw))
			if err != nil {
				t.Fatal(err)
			}
			c := jsonschema.NewCompiler()
			c.UseRegexpEngine(genericRegexp)
			if err = c.AddResource("https://example.test/root", value); err != nil {
				t.Fatal(err)
			}
			pinned, err := c.Compile("https://example.test/root")
			if err != nil {
				t.Fatal(err)
			}
			child := pinned.Properties["n"]
			if child == nil {
				child = pinned.Ref
			}
			if child.DraftVersion != tc.draft {
				t.Fatalf("pinned scope%d want%d", child.DraftVersion, tc.draft)
			}
			r := load(t, tc.raw)
			counts, err := r.Check()
			if err != nil || counts.Nodes != tc.nodes || counts.Compiled != tc.nodes {
				t.Fatalf("graph scope %+v %v", counts, err)
			}
			for _, instance := range []string{tc.valid, tc.invalid} {
				value, _ := decode([]byte(instance))
				direct := pinned.Validate(value)
				checked := r.Validate(r.documents["a.json"].physical, []byte(instance))
				if (direct == nil) != (checked == nil) || (instance == tc.valid && direct != nil) || (instance == tc.invalid && direct == nil) {
					t.Fatalf("pinned=%v registry=%v", direct, checked)
				}
			}
			if string(r.documents["a.json"].Document) != tc.raw {
				t.Fatal("raw schema changed")
			}
		})
	}
}

func TestExplicitTargetMetaschemaUsesCollectedResourceDraft(t *testing.T) {
	raw := `{"$schema":"https://json-schema.org/draft/2020-12/schema","$ref":"#/additionalItems/x-container/t","additionalItems":{"$schema":"http://json-schema.org/draft-07/schema#","$id":"child","x-container":{"t":{"minContains":9223372036854775808}}}}`
	value, err := decode([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	c := jsonschema.NewCompiler()
	c.UseRegexpEngine(genericRegexp)
	if err = c.AddResource("https://example.test/root", value); err != nil {
		t.Fatal(err)
	}
	pinned, err := c.Compile("https://example.test/root")
	if err != nil {
		t.Fatal(err)
	}
	if pinned.Ref.DraftVersion != 7 {
		t.Fatalf("pinned explicit target draft%d", pinned.Ref.DraftVersion)
	}
	r := load(t, raw)
	admission := r.admitNumericClosure(r.documents["a.json"], map[string]numericAdmission{})
	if admission.err != nil || admission.cost != 0 {
		t.Fatalf("annotation in target's collected Draft7 resource acquired arithmetic: %+v", admission)
	}
}
