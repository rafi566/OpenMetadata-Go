// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"bytes"
	"encoding/json"
	"fmt"
	"runtime"
	"strings"
	"testing"
)

func TestValueOwnershipAndTransactionalDecode(t *testing.T) {
	source := []byte(` {"kept":9007199254740993,"array":[{"x":-0}],"string":"ok","bool":false} `)
	want := string(source)
	v, err := ParseValue(source)
	if err != nil {
		t.Fatal(err)
	}
	source[2] = '!'
	raw := v.RawJSON()
	raw[2] = '!'
	encoded, err := v.MarshalJSON()
	if err != nil {
		t.Fatal(err)
	}
	encoded[2] = '!'
	obj, ok := v.Object()
	if !ok {
		t.Fatal("object view missing")
	}
	n, ok := obj["kept"].NumberValue()
	if !ok || n.String() != "9007199254740993" {
		t.Fatal("exact number view lost")
	}
	items, ok := obj["array"].Array()
	if !ok || len(items) != 1 {
		t.Fatal("array view missing")
	}
	child, ok := items[0].Object()
	if !ok {
		t.Fatal("nested object view missing")
	}
	if n, ok := child["x"].NumberValue(); !ok || n.String() != "-0" {
		t.Fatal("negative zero lost")
	}
	child["x"], _ = ParseValue([]byte(`99`))
	items[0], _ = ParseValue([]byte(`null`))
	delete(obj, "kept")
	obj["new"], _ = ParseValue([]byte(`true`))
	if string(v.RawJSON()) != want {
		t.Fatal("mutation changed original raw bytes")
	}
	fresh, _ := v.Object()
	if _, ok := fresh["kept"]; !ok {
		t.Fatal("object mutation leaked")
	}
	a, _ := fresh["array"].Array()
	if string(a[0].RawJSON()) != `{"x":-0}` {
		t.Fatal("array mutation leaked")
	}
	if s, ok := fresh["string"].StringValue(); !ok || s != "ok" {
		t.Fatal("string view")
	}
	if b, ok := fresh["bool"].BoolValue(); !ok || b {
		t.Fatal("bool view")
	}
	for _, bad := range []string{`{"a":1,"a":2}`, `{} []`, `{"broken":`} {
		if err := v.UnmarshalJSON([]byte(bad)); err == nil {
			t.Errorf("accepted %q", bad)
		}
		if string(v.RawJSON()) != want {
			t.Errorf("failed decode changed receiver: %s", bad)
		}
	}
	if err := v.UnmarshalJSON([]byte(`{"replacement":null}`)); err != nil {
		t.Fatal(err)
	}
	fresh, _ = v.Object()
	if len(fresh) != 1 || !fresh["replacement"].IsNull() {
		t.Fatal("replacement retained omissions")
	}
}

func TestValueKindsAndUnset(t *testing.T) {
	for _, token := range []string{`null`, `""`, `false`, `0`, `{}`, `[]`, `1e1000000000`} {
		v, err := ParseValue([]byte(token))
		if err != nil {
			t.Fatal(err)
		}
		encoded, err := json.Marshal(v)
		if err != nil || string(encoded) != token {
			t.Fatalf("%s: %s, %v", token, encoded, err)
		}
		_, str := v.StringValue()
		_, boolean := v.BoolValue()
		_, num := v.NumberValue()
		obj, object := v.Object()
		arr, array := v.Array()
		if str != (token == `""`) || boolean != (token == `false`) || num != (token == `0` || token == `1e1000000000`) || object != (token == `{}`) || array != (token == `[]`) || v.IsNull() != (token == `null`) {
			t.Fatalf("wrong kind: %s", token)
		}
		if object && obj == nil || array && arr == nil {
			t.Fatalf("empty collection is nil: %s", token)
		}
	}
	var unset Value
	if _, err := json.Marshal(unset); err == nil {
		t.Fatal("unset value serialized")
	}
	if unset.RawJSON() != nil || unset.IsNull() {
		t.Fatal("unset confused with null")
	}
}

func TestDecodeStrictBoundsAndPointers(t *testing.T) {
	for _, bad := range []string{`{"a~/":{"x":1,"x":2}}`, `{"a":1,"\u0061":2}`, `{"a":[{"~b/":1,"~b/":2}]}`} {
		_, err := decode([]byte(bad))
		pointer := "/a"
		if strings.Contains(bad, "x") {
			pointer = "/a~0~1/x"
		}
		if strings.Contains(bad, "~b") {
			pointer = "/a/0/~0b~1"
		}
		if err == nil || !strings.Contains(err.Error(), pointer) {
			t.Fatalf("duplicate %s: %v", pointer, err)
		}
	}
	for _, bad := range []string{`1 2`, `{} garbage`, ``, `[1,]`, `{"a":}`} {
		if _, err := decode([]byte(bad)); err == nil {
			t.Errorf("accepted %q", bad)
		}
	}
	atSize := append([]byte(`0`), bytes.Repeat([]byte(" "), (16<<20)-1)...)
	if _, err := decode(atSize); err != nil {
		t.Fatalf("size boundary: %v", err)
	}
	if _, err := decode(append(atSize, ' ')); err == nil {
		t.Fatal("size+1 accepted")
	}
	atDepth := strings.Repeat("[", 256) + "0" + strings.Repeat("]", 256)
	if _, err := decode([]byte(atDepth)); err != nil {
		t.Fatalf("depth boundary: %v", err)
	}
	if _, err := decode([]byte("[" + atDepth + "]")); err == nil {
		t.Fatal("depth+1 accepted")
	}
	v, err := decode([]byte(`9007199254740993`))
	if n, ok := v.(json.Number); err != nil || !ok || string(n) != "9007199254740993" {
		t.Fatalf("decoder rounded number: %v, %v", v, err)
	}
}

func TestValueContainerDepthBoundary(t *testing.T) {
	for _, wrapper := range []struct{ name, open, close string }{
		{"array", "[", "]"}, {"object", `{"x":`, "}"},
	} {
		for _, leaf := range []struct {
			name, json string
			containers int
		}{
			{"scalar", "0", 0}, {"emptyArray", "[]", 1}, {"emptyObject", "{}", 1},
		} {
			for _, depth := range []int{256, 257} {
				name := fmt.Sprintf("%s/%s/%d", wrapper.name, leaf.name, depth)
				t.Run(name, func(t *testing.T) {
					wrappers := depth - leaf.containers
					input := []byte(strings.Repeat(wrapper.open, wrappers) + leaf.json + strings.Repeat(wrapper.close, wrappers))
					_, decodeErr := decode(input)
					_, parseErr := ParseValue(input)
					if depth == 256 {
						if decodeErr != nil || parseErr != nil {
							t.Fatalf("depth 256 rejected: decode=%v ParseValue=%v", decodeErr, parseErr)
						}
					} else if decodeErr == nil || parseErr == nil {
						t.Fatalf("depth 257 accepted: decode=%v ParseValue=%v", decodeErr, parseErr)
					}
				})
			}
		}
	}
}

func TestValueIngressSizeBoundary(t *testing.T) {
	atLimit := bytes.Repeat([]byte(" "), 16<<20)
	atLimit[0] = '0'
	v, err := ParseValue(atLimit)
	if err != nil {
		t.Fatalf("exactly 16 MiB rejected: %v", err)
	}
	if !bytes.Equal(v.RawJSON(), atLimit) {
		t.Fatal("exact-limit raw value changed")
	}
	overLimit := append(atLimit, ' ')
	if _, err := ParseValue(overLimit); err == nil || !strings.Contains(err.Error(), "exceeds 16 MiB") {
		t.Fatalf("limit+1 ParseValue: %v", err)
	}
	prior, err := ParseValue([]byte(`{"kept":9007199254740993}`))
	if err != nil {
		t.Fatal(err)
	}
	if err := prior.UnmarshalJSON(overLimit); err == nil || !strings.Contains(err.Error(), "exceeds 16 MiB") {
		t.Fatalf("limit+1 UnmarshalJSON: %v", err)
	}
	if string(prior.RawJSON()) != `{"kept":9007199254740993}` {
		t.Fatal("over-limit decode changed receiver")
	}
}

func TestValueRejectsOversizeBeforeCopy(t *testing.T) {
	rejected := make([]byte, 17<<20)
	prior, err := ParseValue([]byte(`{"kept":9007199254740993}`))
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name string
		call func() error
	}{
		{"ParseValue", func() error { _, err := ParseValue(rejected); return err }},
		{"UnmarshalJSON", func() error { return prior.UnmarshalJSON(rejected) }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			runtime.GC()
			var before, after runtime.MemStats
			runtime.ReadMemStats(&before)
			err := tc.call()
			runtime.ReadMemStats(&after)
			allocated := after.TotalAlloc - before.TotalAlloc
			t.Logf("rejected input=%d allocated=%d error=%v", len(rejected), allocated, err)
			if err == nil || !strings.Contains(err.Error(), "exceeds 16 MiB") {
				t.Fatalf("oversized value not rejected by size gate: %v", err)
			}
			// A generous ceiling tolerates runtime bookkeeping but catches a copy
			// of the caller-owned 17 MiB slice allocated outside this measurement.
			if allocated > 1<<20 {
				t.Errorf("rejected input allocated %d bytes; ceiling is 1 MiB", allocated)
			}
			if string(prior.RawJSON()) != `{"kept":9007199254740993}` {
				t.Fatal("oversized decode changed receiver")
			}
		})
	}
}
