// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"bytes"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"testing"
)

func requireBlocked(t *testing.T, err error, locator string) {
	t.Helper()
	var d *Diagnostic
	if !errors.Is(err, ErrBlocked) || !errors.As(err, &d) || !strings.Contains(err.Error(), locator) {
		t.Fatalf("want attributed blocker at %s, got %v", locator, err)
	}
}

func TestNumericAdmissionClosure(t *testing.T) {
	// A boolean true dependency returns before numeric arithmetic, making the
	// pre-guard RED safe even for tokens beyond the eventual arithmetic budget.
	r := load(t, `true`)
	id := r.Nodes()[0].ID
	for _, token := range []string{strings.Repeat("1", 10000), "1e10000", "1e-10000"} {
		if err := r.Validate(id, []byte(token)); err != nil {
			t.Fatalf("threshold token length%d: %v", len(token), err)
		}
	}
	for _, token := range []string{strings.Repeat("1", 10001), "1e10001", "1e-10001", "1e999999999999999999999999999999"} {
		err := r.Validate(id, []byte(`{"a/b~c":[`+token+`]}`))
		requireBlocked(t, err, "instance #/a~1b~0c/0")
		v, err := ParseValue([]byte(token))
		if err != nil || !bytes.Equal(v.RawJSON(), []byte(token)) {
			t.Fatal("arithmetic budget narrowed exact storage", err)
		}
	}
	tenk := strings.Repeat("1", 10000)
	for _, n := range []int{100, 101} {
		instance := `[` + strings.TrimSuffix(strings.Repeat(tenk+",", n), ",") + `]`
		err := r.Validate(id, []byte(instance))
		if n == 100 && err != nil {
			t.Fatal(err)
		}
		if n == 101 {
			requireBlocked(t, err, "instance #/100")
		}
	}
}

func TestCardinalityWidth(t *testing.T) {
	for _, tc := range []struct{ keyword, token string }{{"minItems", "18446744073709551616"}, {"maxLength", "9223372036854775808"}} {
		t.Run(tc.keyword, func(t *testing.T) {
			r := load(t, `{"`+tc.keyword+`":`+tc.token+`}`)
			counts, err := r.Check()
			requireBlocked(t, err, "a.json#/"+tc.keyword)
			if counts.Compiled != 0 {
				t.Fatal("blocked node counted compiled", counts)
			}
		})
	}
	max := int64(^uint(0) >> 1)
	r := load(t, fmt.Sprintf(`{"maxItems":%d}`, max))
	if _, err := r.Check(); err != nil {
		t.Fatal("platform int boundary", err)
	}
	if strconv.IntSize == 32 {
		r = load(t, `{"maxItems":2147483648}`)
		_, err := r.Check()
		requireBlocked(t, err, "/maxItems")
	}
	for _, token := range []string{"-1", "1.5"} {
		r := load(t, `{"minItems":`+token+`}`)
		_, err := r.Check()
		var d *Diagnostic
		if err == nil || errors.Is(err, ErrBlocked) || !errors.As(err, &d) {
			t.Fatalf("ordinary metaschema invalid %s: %v", token, err)
		}
	}
	r = load(t, `true`)
	if err := r.Validate(r.Nodes()[0].ID, []byte(`184467440737095516160000`)); err != nil {
		t.Fatal("instance width narrowed", err)
	}
}

func TestNumericClosureAndDraftActivity(t *testing.T) {
	huge := strings.Repeat("1", 10001)
	for _, schema := range []string{
		`{"default":` + huge + `,"examples":[` + huge + `],"x-number":` + huge + `}`,
		`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/t","minimum":` + huge + `,"definitions":{"t":true}}`,
		`{"$schema":"http://json-schema.org/draft-07/schema#","minContains":` + huge + `}`,
		`{"additionalItems":{"minimum":` + huge + `}}`,
	} {
		r := load(t, schema)
		if _, err := r.Check(); err != nil {
			t.Fatalf("annotation became arithmetic assertion: %v", err)
		}
	}
	for _, keyword := range []string{"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "const", "enum"} {
		value := huge
		if keyword == "enum" {
			value = `[{"a/b~c":` + huge + `}]`
		}
		r := load(t, `{"`+keyword+`":`+value+`}`)
		_, err := r.Check()
		requireBlocked(t, err, "a.json#/"+keyword)
	}
	tenk := strings.Repeat("1", 10000)
	array := `[` + strings.TrimSuffix(strings.Repeat(tenk+",", 101), ",") + `]`
	root := fixture(t, map[string]string{
		"a.json": `{"$ref":"b.json"}`,
		"b.json": `{"$defs":{"unused":{"$ref":"c.json"}}}`,
		"c.json": `{"const":` + array + `}`,
		"d.json": `true`,
	})
	r, err := LoadRegistry(root)
	if err != nil {
		t.Fatal(err)
	}
	counts, err := r.Check()
	requireBlocked(t, err, "c.json#/const/100")
	if counts.Compiled != 1 || counts.Nodes != 5 {
		t.Fatalf("independent compilation count: %+v", counts)
	}
	requireBlocked(t, r.Validate(r.documents["a.json"].ID, []byte(`0`)), "c.json#/const/100")
	if err = r.Validate(r.documents["d.json"].ID, []byte(`0`)); err != nil {
		t.Fatal("unrelated numeric document blocked validation", err)
	}
	// The schema and instance share one budget, including all numeric descendants.
	array = `[` + strings.TrimSuffix(strings.Repeat(strings.Repeat("1", 9999)+",", 100), ",") + `]`
	r = load(t, `{"const":`+array+`}`)
	for _, size := range []int{100, 101} {
		instance := `{"open":[` + strings.TrimSuffix(strings.Repeat("1,", size), ",") + `]}`
		err = r.Validate(r.Nodes()[0].ID, []byte(instance))
		if size == 100 && errors.Is(err, ErrBlocked) {
			t.Fatal("joint threshold blocked", err)
		}
		if size == 101 {
			requireBlocked(t, err, "instance #/open/100")
		}
	}
}

func TestNumericClosureCacheBounded(t *testing.T) {
	r := load(t, `{"$defs":{"a":{"minimum":1},"b":{"$ref":"#/$defs/a"}},"properties":{"c":{"$ref":"#/$defs/b"}}}`)
	cache := make(map[string]numericAdmission, len(r.documents))
	for i := 0; i < 3; i++ {
		for _, key := range sortedKeys(r.schemas) {
			a := r.admitNumericClosure(r.schemas[key], cache)
			if a.err != nil || a.cost != 1 {
				t.Fatalf("closure admission %+v", a)
			}
		}
	}
	if len(cache) != len(r.documents) || len(cache) > 10000 {
		t.Fatalf("cache not bounded by physical documents: %d", len(cache))
	}
	for _, keyword := range []string{"minItems", "maxItems", "minLength", "maxLength", "minProperties", "maxProperties", "minContains", "maxContains"} {
		r = load(t, `{"contains":true,"`+keyword+`":9223372036854775808}`)
		_, err := r.Check()
		requireBlocked(t, err, "a.json#/"+keyword)
	}
	for _, schema := range []string{
		`{"minContains":9223372036854775808}`,
		`{"$schema":"http://json-schema.org/draft-07/schema#","minContains":9223372036854775808}`,
		`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/t","minItems":9223372036854775808,"definitions":{"t":true}}`,
	} {
		r = load(t, schema)
		if _, err := r.Check(); err != nil {
			t.Fatalf("inactive width guard changed semantics: %v", err)
		}
	}
}

func TestMetaschemaIgnoredAssertionCharacterization(t *testing.T) {
	for _, tc := range []struct {
		name, keyword, token string
		valid                bool
	}{
		{"positive-multiple", "multipleOf", "2", true},
		{"zero-multiple", "multipleOf", "0", false},
		{"negative-multiple", "multipleOf", "-1", false},
		{"fractional-multiple", "multipleOf", "0.5", true},
		{"inactive-wide-cardinality", "minItems", "18446744073709551616", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := load(t, `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/t","definitions":{"t":{"type":"string"}},"`+tc.keyword+`":`+tc.token+`}`)
			counts, err := r.Check()
			if (err == nil) != tc.valid || errors.Is(err, ErrBlocked) {
				t.Fatalf("bounded metaschema characterization: %+v %v", counts, err)
			}
			if tc.valid {
				if err = r.Validate(r.Nodes()[0].ID, []byte(`"a"`)); err != nil {
					t.Fatal("ignored numeric runtime assertion became active", err)
				}
			}
		})
	}
}

func TestMetaschemaArithmeticAdmission(t *testing.T) {
	huge := "1e10001"
	for _, draft := range []string{"http://json-schema.org/draft-07/schema#", "https://json-schema.org/draft/2019-09/schema", "https://json-schema.org/draft/2020-12/schema"} {
		for _, size := range []int{2, 21} {
			array := `[` + strings.TrimSuffix(strings.Repeat(huge+",", size), ",") + `]`
			keywords := map[string]string{"multipleOf": huge, "minItems": huge, "required": array, "type": array, "dependencies": `{"a/b~c":` + array + `}`}
			if strings.Contains(draft, "draft-07") {
				keywords["enum"] = array
			} else {
				keywords["dependentRequired"] = `{"a/b~c":` + array + `}`
			}
			for keyword, value := range keywords {
				t.Run(draft+"/"+keyword+"/"+strconv.Itoa(size), func(t *testing.T) {
					ref := `"$ref":"#/definitions/t",`
					if !strings.Contains(draft, "draft-07") {
						ref = ""
					}
					r := load(t, `{"$schema":"`+draft+`",`+ref+`"definitions":{"t":true},"`+keyword+`":`+value+`}`)
					// This RED calls only our admission helper, never dependent arithmetic.
					admission := r.admitNumericClosure(r.documents["a.json"], map[string]numericAdmission{})
					requireBlocked(t, admission.err, "a.json#/"+keyword)
					if !strings.Contains(admission.err.Error(), "compiler-metaschema") {
						t.Fatalf("missing distinct metaschema attribution: %v", admission.err)
					}
				})
			}
		}
	}
	t.Run("ignored-nested-escaped-location", func(t *testing.T) {
		r := load(t, `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/t","definitions":{"t":true},"properties":{"a/b~c":{"multipleOf":`+huge+`}}}`)
		admission := r.admitNumericClosure(r.documents["a.json"], map[string]numericAdmission{})
		requireBlocked(t, admission.err, "a.json#/properties/a~1b~0c/multipleOf")
	})
	t.Run("ignored-custom-metaschema", func(t *testing.T) {
		r := load(t, `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/t","definitions":{"t":true},"properties":{"n":{"$schema":"https://unregistered.invalid/custom","$vocabulary":{"https://unregistered.invalid/arithmetic":true}}}}`)
		admission := r.admitNumericClosure(r.documents["a.json"], map[string]numericAdmission{})
		requireBlocked(t, admission.err, "a.json#/properties/n/$schema")
	})
}

func TestMetaschemaGuardedIntegration(t *testing.T) {
	for _, keyword := range []string{"multipleOf", "minItems", "required", "type", "enum", "dependencies"} {
		t.Run(keyword, func(t *testing.T) {
			value := `1e10001`
			if keyword == "required" || keyword == "type" || keyword == "enum" {
				value = `[1e10001,2]`
			}
			if keyword == "dependencies" {
				value = `{"a/b~c":[1e10001,2]}`
			}
			raw := `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/t","definitions":{"t":true},"` + keyword + `":` + value + `}`
			r, err := LoadRegistry(fixture(t, map[string]string{"a.json": raw, "independent.json": `true`}))
			if err != nil {
				t.Fatal(err)
			}
			before := r.Nodes()
			references := len(r.references)
			counts, err := r.Check()
			requireBlocked(t, err, "a.json#/"+keyword)
			if counts.Compiled != 1 || counts.Nodes != 3 {
				t.Fatalf("independent partial compilation %+v", counts)
			}
			requireBlocked(t, r.Validate(r.documents["a.json"].ID, []byte(`null`)), "a.json#/"+keyword)
			after := r.Nodes()
			if len(before) != len(after) || len(r.references) != references {
				t.Fatal("metaschema admission changed graph membership")
			}
			for i := range before {
				if before[i].ID != after[i].ID || !bytes.Equal(before[i].Document, after[i].Document) {
					t.Fatal("metaschema traversal changed raw node identity/data")
				}
			}
		})
	}
	for _, keyword := range []string{"required", "type", "dependencies", "dependentRequired"} {
		value := `[1,2]`
		if keyword == "dependencies" || keyword == "dependentRequired" {
			value = `{"x":[1,2]}`
		}
		r := load(t, `{"`+keyword+`":`+value+`}`)
		_, err := r.Check()
		if err == nil || errors.Is(err, ErrBlocked) {
			t.Fatalf("ordinary invalid %s changed classification: %v", keyword, err)
		}
	}
}

func TestMetaschemaUnionBudgetAndAnnotations(t *testing.T) {
	definitions := make([]string, 100)
	for i := range definitions {
		definitions[i] = fmt.Sprintf(`"n%d":{"multipleOf":1e9999}`, i)
	}
	r := load(t, `{"$defs":{`+strings.Join(definitions, ",")+`}}`)
	admission := r.admitNumericClosure(r.documents["a.json"], map[string]numericAdmission{})
	if admission.err != nil || admission.cost != 1000000 {
		t.Fatalf("source counted twice in metaschema/assertion union: %+v", admission)
	}
	if err := r.Validate(r.Nodes()[0].ID, []byte(`false`)); err != nil {
		t.Fatal("joint threshold rejected", err)
	}
	requireBlocked(t, r.Validate(r.Nodes()[0].ID, []byte(`1`)), "instance #")
	r, err := LoadRegistry(fixture(t, map[string]string{"a.json": `{"$ref":"b.json","multipleOf":1e9999}`, "b.json": `{"multipleOf":1e9999}`}))
	if err != nil {
		t.Fatal(err)
	}
	admission = r.admitNumericClosure(r.documents["a.json"], map[string]numericAdmission{})
	if admission.err != nil || admission.cost != 20000 {
		t.Fatalf("distinct physical source locations merged: %+v", admission)
	}
	huge := `1e999999999999999999999999999999`
	for _, raw := range []string{
		`{"default":{"required":[` + huge + `,` + huge + `]},"examples":[{"multipleOf":` + huge + `}],"x-data":{"type":[` + huge + `,` + huge + `]}}`,
		`{"$schema":"http://json-schema.org/draft-07/schema#","dependentRequired":{"x":[` + huge + `,` + huge + `]},"$defs":{"x":{"multipleOf":` + huge + `}}}`,
		`{"additionalItems":{"multipleOf":` + huge + `,"required":[` + huge + `,` + huge + `]}}`,
	} {
		r = load(t, raw)
		before := string(r.documents["a.json"].Document)
		if _, err := r.Check(); err != nil {
			t.Fatalf("raw annotation acquired arithmetic obligations: %v", err)
		}
		if string(r.documents["a.json"].Document) != before {
			t.Fatal("raw annotation changed")
		}
	}
	for _, draft := range []string{"http://json-schema.org/draft-07/schema#", "https://json-schema.org/draft/2019-09/schema", "https://json-schema.org/draft/2020-12/schema"} {
		r = load(t, `{"$schema":"`+draft+`","$vocabulary":{"https://unregistered.invalid/vocabulary":true},"x-number":`+huge+`}`)
		if _, err := r.Check(); err != nil {
			t.Fatalf("own canonical-schema vocabulary declaration selected a custom metaschema: %v", err)
		}
	}
}

func TestMetaschemaResourceDraftScope(t *testing.T) {
	// Without a nested ID the compiler keeps its resource's inherited dialect.
	// With an ID the nested declaration selects the resource's own canonical draft.
	for _, tc := range []struct {
		name, id string
		blocked  bool
	}{
		{"inherited-draft", ``, true},
		{"scoped-2020", `"$id":"child",`, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			raw := `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/t","definitions":{"t":true},"properties":{"nested":{` + tc.id + `"$schema":"https://json-schema.org/draft/2020-12/schema","additionalItems":{"multipleOf":1e10001}}}}`
			r := load(t, raw)
			admission := r.admitNumericClosure(r.documents["a.json"], map[string]numericAdmission{})
			if tc.blocked {
				requireBlocked(t, admission.err, "/properties/nested/additionalItems/multipleOf")
			} else if admission.err != nil {
				t.Fatal(admission.err)
			}
		})
	}
}
