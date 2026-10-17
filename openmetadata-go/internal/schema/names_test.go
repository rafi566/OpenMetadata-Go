// SPDX-License-Identifier: Apache-2.0
package schema

import (
	"encoding/json"
	"go/ast"
	"reflect"
	"strconv"
	"testing"
)

func TestGoNameUsesPhysicalSourceIdentity(t *testing.T) {
	a, _ := GoName(Node{Path: "type/basic.json", Pointer: "/definitions/name"})
	b, _ := GoName(Node{Path: "api/basic.json", Pointer: "/definitions/name"})
	c, _ := GoName(Node{Path: "type/basic.json", Pointer: "/properties/name"})
	if a == b || a == c || a != "ModelTypeBasicAtDefinitionsNameValue" {
		t.Fatalf("source identities collapsed: %s %s %s", a, b, c)
	}
	for _, n := range []Node{{Path: "../bad.json"}, {Path: "/bad.json"}, {Path: "a.json", Pointer: "bad"}} {
		if _, e := GoName(n); e == nil {
			t.Fatalf("invalid locator accepted: %+v", n)
		}
	}
}

func TestProjectionIdentifiersExportUncasedLetters(t *testing.T) {
	for _, key := range []string{"状态", "日本語", "123", "xml:lang"} {
		t.Run(key, func(t *testing.T) {
			name := identifier(key)
			if !ast.IsExported(name) {
				t.Fatalf("projection identifier %q is unexported for JSON key %q", name, key)
			}
			typ := reflect.StructOf([]reflect.StructField{{Name: name, Type: reflect.TypeOf(""), Tag: reflect.StructTag("json:" + strconv.Quote(key+",omitzero"))}})
			value := reflect.New(typ).Elem()
			value.Field(0).SetString("kept")
			encoded, err := json.Marshal(value.Interface())
			if err != nil {
				t.Fatal(err)
			}
			var got map[string]string
			if err := json.Unmarshal(encoded, &got); err != nil {
				t.Fatal(err)
			}
			if len(got) != 1 || got[key] != "kept" {
				t.Fatalf("projection renamed or dropped %q: %s", key, encoded)
			}
		})
	}
}
