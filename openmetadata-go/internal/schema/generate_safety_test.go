// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestGenerateDeferredSemantics(t *testing.T) {
	for _, tc := range []struct{ name, raw, pointer string }{
		{"tuple", `{"$schema":"http://json-schema.org/draft-07/schema#","type":"array","items":[{}]}`, "/items"},
		{"contains", `{"type":"array","contains":{}}`, "/contains"},
		{"unevaluated-properties", `{"unevaluatedProperties":false}`, "/unevaluatedProperties"},
		{"unevaluated-items", `{"unevaluatedItems":false}`, "/unevaluatedItems"},
		{"ref-sibling", `{"$ref":"#/$defs/value","pattern":"a","$defs":{"value":{"type":"string"}}}`, "/pattern"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			out := filepath.Join(t.TempDir(), "out")
			_, err := Generate(generationRegistry(t, map[string]string{"deferred.json": tc.raw}), GenerateOptions{"models", out})
			if !errors.Is(err, ErrBlocked) || !strings.Contains(err.Error(), "deferred.json#"+tc.pointer) {
				t.Fatalf("missing precise deferred blocker: %v", err)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Fatal("deferred semantic preflight wrote files")
			}
		})
	}
}

func TestGenerateMapOnlyView(t *testing.T) {
	out := t.TempDir()
	_, err := Generate(generationRegistry(t, map[string]string{"map.json": `{"additionalProperties":{"type":["integer","null"]}}`}), GenerateOptions{"models", out})
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join(out, "models_modelmaprootvalue.go"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(raw, []byte("AdditionalProperties()")) {
		t.Fatal("schema-valued additionalProperties without type/properties has no typed map view")
	}
}

func TestGenerateDeterministicAndSafePaths(t *testing.T) {
	r := generationRegistry(t, map[string]string{"nested/a.json": `{"type":"string"}`, "b.json": `{"$ref":"nested/a.json"}`})
	a, b := t.TempDir(), t.TempDir()
	pa, err := Generate(r, GenerateOptions{"models", a})
	if err != nil {
		t.Fatal(err)
	}
	pb, err := Generate(r, GenerateOptions{"models", b})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(pa, pb) {
		t.Fatalf("path nondeterminism: %v %v", pa, pb)
	}
	for _, p := range pa {
		x, e := os.ReadFile(filepath.Join(a, p))
		if e != nil {
			t.Fatal(e)
		}
		y, e := os.ReadFile(filepath.Join(b, p))
		if e != nil {
			t.Fatal(e)
		}
		if !bytes.Equal(x, y) {
			t.Fatalf("byte nondeterminism: %s", p)
		}
	}
	for _, name := range []string{"leaf", "registry", "registry/nested"} {
		t.Run(name, func(t *testing.T) {
			out, target := t.TempDir(), t.TempDir()
			link := filepath.Join(out, name)
			if name == "leaf" {
				link = filepath.Join(out, "model-index.json")
			}
			if err := os.MkdirAll(filepath.Dir(link), 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(target, link); err != nil {
				t.Fatal(err)
			}
			if _, err := Generate(r, GenerateOptions{"models", out}); err == nil {
				t.Fatal("symlink accepted")
			}
			entries, err := os.ReadDir(target)
			if err != nil || len(entries) != 0 {
				t.Fatalf("target modified: %v %v", entries, err)
			}
			if _, err := os.Stat(filepath.Join(out, "model-index.json")); name != "leaf" && !os.IsNotExist(err) {
				t.Fatal("wrote output before preflighting all paths")
			}
		})
	}
}

func TestGenerateSymbolCollisions(t *testing.T) {
	for _, docs := range []map[string]string{
		{"enum.json": `{"enum":["foo-bar","foo_bar"]}`},
		{"field.json": `{"type":"object","properties":{"foo-bar":{},"foo_bar":{}}}`},
	} {
		out := filepath.Join(t.TempDir(), "out")
		_, err := Generate(generationRegistry(t, docs), GenerateOptions{"models", out})
		if err == nil || !strings.Contains(err.Error(), "collision") {
			t.Fatalf("symbol collision accepted: %v", err)
		}
		if _, err := os.Stat(out); !os.IsNotExist(err) {
			t.Fatal("collision wrote output")
		}
	}
}

func TestGenerateOutputBudget(t *testing.T) {
	// Shared payloads exercise the real output preflight at 256 MiB without
	// requiring a 256 MiB fixture or writing hundreds of MiB into test storage.
	chunk := make([]byte, 1<<20)
	files := map[string][]byte{}
	for i := 0; i < 256; i++ {
		files[fmt.Sprintf("chunk-%03d", i)] = chunk
	}
	out := filepath.Join(t.TempDir(), "out")
	if err := preflightGeneratedFiles(out, files); err != nil {
		t.Fatalf("exact output limit rejected: %v", err)
	}
	files["overflow"] = []byte("x")
	if _, err := writeGeneratedFiles(out, files); err == nil || !strings.Contains(err.Error(), "256 MiB") {
		t.Fatalf("output cap: %v", err)
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Fatal("output budget failure wrote files")
	}
}

func TestGeneratedMapOnlyAndIgnoredKeywords(t *testing.T) {
	independentGeneratedModule(t, map[string]string{
		"map.json":     `{"additionalProperties":{"type":["integer","null"]}}`,
		"ignored.json": `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/value","oneOf":[{},{}],"pattern":"^a","definitions":{"value":{"type":"string"}}}`,
	}, "models", `
import "testing"
func TestViews(t *testing.T){
var m ModelMapRootValue;if e:=m.UnmarshalJSON([]byte("{\"large\":9007199254740993,\"nil\":null}"));e!=nil{t.Fatal(e)}
v,ok,e:=m.AdditionalProperties();if e!=nil||!ok||len(v)!=2||v["nil"]==nil||!v["nil"].JSONValue().IsNull(){t.Fatal("map-only view",e)}
n,ok:=v["large"].NumberValue();if !ok||n.String()!="9007199254740993"{t.Fatal("precision")}
var ignored ModelIgnoredRootValue;if e:=ignored.UnmarshalJSON([]byte("\"b\""));e!=nil{t.Fatal(e)};if s,ok:=ignored.StringValue();!ok||s!="b"{t.Fatal("ignored ref siblings acquired assertions")}
}
`)
}
