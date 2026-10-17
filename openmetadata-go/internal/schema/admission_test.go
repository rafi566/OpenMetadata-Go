// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestRegistryAdmissionAndIdentity(t *testing.T) {
	for name, raw := range map[string]string{
		"duplicate-anchor":      `{"$defs":{"a":{"$anchor":"same"},"b":{"$anchor":"same"}}}`,
		"duplicate-scoped-id":   `{"$defs":{"a":{"$id":"https://example.test/same"},"b":{"$id":"https://example.test/same"}}}`,
		"invalid-pointer":       `{"$ref":"#/~2"}`,
		"unknown-url":           `{"$ref":"https://unregistered.invalid/no"}`,
		"duplicate-decoded-key": `{"type":"string","\u0074ype":"integer"}`,
		"depth":                 strings.Repeat(`{"items":`, 257) + `true` + strings.Repeat(`}`, 257),
	} {
		t.Run(name, func(t *testing.T) {
			_, err := LoadRegistry(fixture(t, map[string]string{"a.json": raw}))
			var d *Diagnostic
			if err == nil || !errors.As(err, &d) {
				t.Fatalf("unattributed admission: %v", err)
			}
		})
	}
	t.Run("root-symlink", func(t *testing.T) {
		root := fixture(t, map[string]string{"a.json": `true`})
		link := filepath.Join(t.TempDir(), "linked")
		if err := os.Symlink(root, link); err != nil {
			t.Fatal(err)
		}
		if _, err := LoadRegistry(link); err == nil {
			t.Fatal("root symlink accepted")
		}
	})
	t.Run("filename-bound", func(t *testing.T) {
		root := fixture(t, map[string]string{strings.Repeat("a", 241) + ".json": `true`})
		if _, err := LoadRegistry(root); err == nil {
			t.Fatal("filename beyond 240 bytes accepted")
		}
	})
	t.Run("document-bound", func(t *testing.T) {
		files := map[string]string{}
		for i := 0; i < 10001; i++ {
			files[strings.Repeat("a", i/1000)+string(rune(0x1000+i))+".json"] = `true`
		}
		_, err := LoadRegistry(fixture(t, files))
		if err == nil || !strings.Contains(err.Error(), "10000") {
			t.Fatalf("document count bound: %v", err)
		}
	})
	r := load(t, `{"$id":"https://example.test/root","$defs":{"nested":{"$id":"child","$defs":{"a/b~c":{"$anchor":"leaf","type":"integer"}}}}}`)
	for _, ref := range []string{"#leaf", "#/$defs/a~1b~0c"} {
		node, err := r.Resolve("https://example.test/child", ref)
		if err != nil || node.Pointer != "/$defs/nested/$defs/a~1b~0c" {
			t.Fatalf("scoped identity: %+v %v", node, err)
		}
	}
	if _, err := LoadLegacyRegistry(fixture(t, map[string]string{"a.json": `true`})); err == nil {
		t.Fatal("legacy profile drift accepted")
	}
	for _, root := range []string{t.TempDir(), filepath.Join(t.TempDir(), "missing")} {
		if _, err := LoadRegistry(root); err == nil {
			t.Fatal("invalid/missing source accepted")
		}
	}
}

func TestRawMetadataIsolationAfterValidation(t *testing.T) {
	raw := `{"$id":"https://example.test/a","type":"object","properties":{"n":{"type":"integer"}},"default":{"extra":1}}`
	r := load(t, raw)
	nodes := r.Nodes()
	for i := range nodes {
		for j := range nodes[i].Document {
			nodes[i].Document[j] = ' '
		}
	}
	node, err := r.Resolve("https://example.test/a", "#/properties/n")
	if err != nil {
		t.Fatal(err)
	}
	for i := range node.Document {
		node.Document[i] = 'x'
	}
	again, err := r.Resolve("https://example.test/a", "")
	if err != nil || string(again.Document) != raw {
		t.Fatalf("registry metadata mutated: %s %v", again.Document, err)
	}
	if _, err := r.Check(); err != nil {
		t.Fatal("compile changed after returned mutation", err)
	}
	if err := r.Validate("https://example.test/a", []byte(`{"n":1}`)); err != nil {
		t.Fatal(err)
	}
	if err := r.Validate("https://example.test/a", []byte(`{"n":"bad"}`)); err == nil {
		t.Fatal("validation changed after returned mutation")
	}
}

func TestPhysicalPathAndPointerRemainDistinct(t *testing.T) {
	r, err := LoadRegistry(fixture(t, map[string]string{
		"a.json":                 `{"$defs":{"b.json#":{"type":"string"},"b.json%23":{"type":"boolean"},"a/b~c#%":{"type":"null"}}}`,
		"a.json#/$defs/b.json":   `{"type":"integer"}`,
		"a.json%23/$defs/b.json": `false`,
	}))
	if err != nil {
		t.Fatal(err)
	}
	a := r.documents["a.json"]
	target, err := r.Resolve(a.physical, "#/$defs/b.json%23")
	if err != nil || target.Path != "a.json" || target.Pointer != "/$defs/b.json#" || string(target.Document) != `{"type":"string"}` {
		t.Fatalf("physical-path/pointer namespace collision: %+v %v", target, err)
	}
	counts, err := r.Check()
	if err != nil || counts.Nodes != 6 || counts.Compiled != 6 {
		t.Fatalf("distinct source nodes lost: %+v %v", counts, err)
	}
	if err = r.Validate(a.physical+"#/$defs/b.json%23", []byte(`"a"`)); err != nil {
		t.Fatal(err)
	}
	if err = r.Validate(a.physical+"#/$defs/b.json%23", []byte(`1`)); err == nil {
		t.Fatal("wrong physical document supplied reference target")
	}
}

func TestPhysicalPercentPathsAndEscapedPointers(t *testing.T) {
	r, err := LoadRegistry(fixture(t, map[string]string{
		"a.json":                 `{"$defs":{"b.json%23":{"type":"boolean"},"a/b~c#%":{"type":"null"}}}`,
		"a.json#/$defs/b.json":   `{"type":"integer"}`,
		"a.json%23/$defs/b.json": `false`,
	}))
	if err != nil {
		t.Fatal(err)
	}
	a := r.documents["a.json"]
	for _, tc := range []struct{ ref, pointer, valid, invalid string }{
		{"#/$defs/b.json%2523", "/$defs/b.json%23", `true`, `1`},
		{"#/$defs/a~1b~0c%23%25", "/$defs/a~1b~0c#%", `null`, `false`},
	} {
		node, err := r.Resolve(a.physical, tc.ref)
		if err != nil || node.Path != "a.json" || node.Pointer != tc.pointer {
			t.Fatalf("escaped locator %+v %v", node, err)
		}
		if err = r.Validate(a.physical+tc.ref, []byte(tc.valid)); err != nil {
			t.Fatal(err)
		}
		if err = r.Validate(a.physical+tc.ref, []byte(tc.invalid)); err == nil {
			t.Fatal("escaped target constraint lost")
		}
	}
	if err = r.Validate(r.documents["a.json#/$defs/b.json"].physical, []byte(`1`)); err != nil {
		t.Fatal(err)
	}
	if err = r.Validate(r.documents["a.json%23/$defs/b.json"].physical, []byte(`1`)); err == nil {
		t.Fatal("literal percent path aliased hash path")
	}
}

func TestRegistryRawEntryBound(t *testing.T) {
	for _, count := range []int{999998, 999999} {
		t.Run(strconv.Itoa(count), func(t *testing.T) {
			raw := `{"default":[` + strings.TrimSuffix(strings.Repeat("null,", count), ",") + `]}`
			r, err := LoadRegistry(fixture(t, map[string]string{"a.json": raw}))
			if count == 999998 {
				if err != nil || len(r.Nodes()) != 1 {
					t.Fatalf("exact raw-entry threshold rejected: %v", err)
				}
			} else {
				var d *Diagnostic
				if err == nil || !errors.As(err, &d) || d.Stage != "load" || d.Pointer != "/default/999998" || !strings.Contains(err.Error(), "structure limit") {
					t.Fatalf("raw-entry overflow not attributed: %v", err)
				}
			}
		})
	}
}
