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
