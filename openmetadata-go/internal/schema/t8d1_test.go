// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

func TestT8D1IgnoredRefSiblingPatterns(t *testing.T) {
	for _, tc := range []struct {
		name, draft, ref, pattern, container string
	}{
		{"draft7-pattern", "http://json-schema.org/draft-07/schema#", `"$ref":"#/definitions/target",`, "(?=a)", "pattern"},
		{"draft7-valid-ignored-pattern", "http://json-schema.org/draft-07/schema#", `"$ref":"#/definitions/target",`, "^z", "pattern"},
		{"draft7-patternProperties", "http://json-schema.org/draft-07/schema#", `"$ref":"#/definitions/target",`, "(?=a)", "patternProperties"},
		{"no-ref", "http://json-schema.org/draft-07/schema#", "", "(?=a)", "pattern"},
		{"2020-ref", "https://json-schema.org/draft/2020-12/schema", `"$ref":"#/definitions/target",`, "(?=a)", "pattern"},
		{"draft7-malformed", "http://json-schema.org/draft-07/schema#", `"$ref":"#/definitions/target",`, "[", "pattern"},
		{"active-valid", "http://json-schema.org/draft-07/schema#", "", "^a", "pattern"},
		{"explicit-sibling-target", "http://json-schema.org/draft-07/schema#", `"$ref":"#/patternProperties/a~1b~0c",`, "a/b~c", "patternProperties"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			p, _ := json.Marshal(tc.pattern)
			keyword := `"pattern":` + string(p)
			if tc.container == "patternProperties" {
				keyword = `"patternProperties":{` + string(p) + `:{"type":"string"}}`
			}
			raw := `{"$schema":"` + tc.draft + `",` + tc.ref + `"definitions":{"target":{"type":"string"}},` + keyword + `}`
			v, err := decode([]byte(raw))
			if err != nil {
				t.Fatal(err)
			}
			c := jsonschema.NewCompiler()
			c.UseRegexpEngine(genericRegexp)
			if err = c.AddResource("https://example.test/a", v); err != nil {
				t.Fatal(err)
			}
			compiled, direct := c.Compile("https://example.test/a")
			var directValid, directInvalid error
			if direct == nil {
				directValid = compiled.Validate("a")
				directInvalid = compiled.Validate(2)
			}
			r := load(t, raw)
			counts, checked := r.Check()
			validated := r.Validate(r.Nodes()[0].ID, []byte(`"a"`))
			t.Logf("pinned compile=%v valid=%v invalid=%v registry=%+v check=%v validate=%v", direct, directValid, directInvalid, counts, checked, validated)
			if (direct == nil) != (checked == nil) || (direct == nil && (directValid == nil) != (validated == nil)) {
				t.Fatalf("pinned/registry divergence: compile=%v check=%v validate=%v", direct, checked, validated)
			}
			if tc.name == "active-valid" && (compiled.Validate("z") == nil || r.Validate(r.Nodes()[0].ID, []byte(`"z"`)) == nil) {
				t.Fatal("active valid pattern was ignored")
			}
			if direct == nil && tc.ref != "" && r.Validate(r.Nodes()[0].ID, []byte(`2`)) == nil {
				t.Fatal("referenced string constraint lost")
			}
			if checked != nil {
				var d *Diagnostic
				if !errors.As(checked, &d) || !strings.Contains(checked.Error(), "a.json#/") {
					t.Fatalf("unattributed: %v", checked)
				}
			}
		})
	}
	// An active patternProperties key must retain its escaped RFC6901 locator.
	r := load(t, `{"patternProperties":{"(?=a)/~":{"type":"string"}}}`)
	_, err := r.Check()
	if !errors.Is(err, ErrBlocked) || !strings.Contains(err.Error(), "/patternProperties/(?=a)~1~0") {
		t.Fatalf("escaped source locator: %v", err)
	}
}
