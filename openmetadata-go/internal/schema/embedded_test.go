// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"testing/fstest"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

func embeddedFixture(files map[string]string) fstest.MapFS {
	source := fstest.MapFS{}
	for path, raw := range files {
		source[path] = &fstest.MapFile{Data: []byte(raw)}
	}
	return source
}

func TestEmbeddedParityAndBounds(t *testing.T) {
	t.Run("generic-parity-ownership", func(t *testing.T) {
		files := map[string]string{
			"a.json":                 `{"type":"object","properties":{"a/b~c":{"$ref":"child.json"}},"default":{"n":1e1000000000},"x-target":{"type":"boolean"}}`,
			"child.json":             `{"$id":"child.json","type":"integer"}`,
			"a.json#/$defs/b.json":   `{"type":"string"}`,
			"a.json%23/$defs/b.json": `false`,
			"scoped.json":            `{"$id":"https://example.test/root","$defs":{"nested":{"$id":"child","$anchor":"n","type":"null"}}}`,
		}
		root := fixture(t, files)
		t.Setenv("TMPDIR", filepath.Join(root, "absent-temp-directory"))
		disk, err := LoadRegistry(root)
		if err != nil {
			t.Fatal(err)
		}
		source := embeddedFixture(files)
		embedded, err := LoadEmbeddedRegistry(source, "")
		if err != nil {
			t.Fatal(err)
		}
		diskRoot := (&url.URL{Scheme: "file", Path: filepath.ToSlash(root) + "/"}).String()
		const embeddedRoot = "file:///__openmetadata_embedded__/"
		normalize := func(id string) string { return strings.ReplaceAll(id, diskRoot, embeddedRoot) }
		diskNodes, nodes := disk.Nodes(), embedded.Nodes()
		if len(nodes) != len(diskNodes) {
			t.Fatalf("node parity %d != %d", len(nodes), len(diskNodes))
		}
		for i, node := range nodes {
			want := diskNodes[i]
			want.ID = normalize(want.ID)
			if !reflect.DeepEqual(node, want) {
				t.Fatalf("node parity %+v != %+v", node, want)
			}
			if i > 0 && keyAt(nodes[i-1].Path, nodes[i-1].Pointer) >= keyAt(node.Path, node.Pointer) {
				t.Fatal("nodes unsorted")
			}
			node.Document[0] = '!'
		}
		for _, tc := range []struct{ base, ref, path, pointer, valid, invalid string }{
			{"a.json", "#/properties/a~1b~0c", "a.json", "/properties/a~1b~0c", `1`, `"bad"`},
			{"a.json", "#/x-target", "a.json", "/x-target", `true`, `1`},
			{"a.json", "a.json%23/$defs/b.json", "a.json#/$defs/b.json", "", `"yes"`, `1`},
			{"a.json", "a.json%2523/$defs/b.json", "a.json%23/$defs/b.json", "", "", `1`},
		} {
			d, de := disk.Resolve(diskRoot+tc.base, tc.ref)
			n, ne := embedded.Resolve(embeddedRoot+tc.base, tc.ref)
			d.ID = normalize(d.ID)
			if de != nil || ne != nil || !reflect.DeepEqual(d, n) || n.Path != tc.path || n.Pointer != tc.pointer {
				t.Fatalf("resolve parity %+v %+v %v %v", d, n, de, ne)
			}
			id := embeddedRoot + tc.base
			resolved, err := resolveURL(id, tc.ref)
			if err != nil {
				t.Fatal(err)
			}
			if tc.valid != "" {
				if err := embedded.Validate(resolved.String(), []byte(tc.valid)); err != nil {
					t.Fatal(err)
				}
			}
			if err := embedded.Validate(resolved.String(), []byte(tc.invalid)); err == nil {
				t.Fatal("constraint lost")
			}
			n.Document[0] = '!'
		}
		dc, de := disk.Check()
		ec, ee := embedded.Check()
		if de != nil || ee != nil || dc != ec || ec.Compiled != ec.Nodes {
			t.Fatalf("check parity %+v %v %+v %v", dc, de, ec, ee)
		}
		for path, file := range source {
			file.Data[0] = '!'
			delete(source, path)
		}
		fresh, err := embedded.Resolve(embeddedRoot+"a.json", "")
		if err != nil || string(fresh.Document) != files["a.json"] {
			t.Fatalf("input/output ownership lost: %s %v", fresh.Document, err)
		}
		if err = embedded.Validate(embeddedRoot+"a.json", []byte(`{"a/b~c":1}`)); err != nil {
			t.Fatal(err)
		}
		if _, err := embedded.Resolve(embeddedRoot+"a.json", "https://unregistered.invalid/schema"); err == nil {
			t.Fatal("network fallback")
		}
		if _, err := embedded.Resolve(embeddedRoot+"a.json", "../outside.json"); err == nil {
			t.Fatal("disk fallback")
		}
	})
	t.Run("profiles-and-input", func(t *testing.T) {
		for _, source := range []fs.FS{nil, fstest.MapFS{}} {
			if _, err := LoadEmbeddedRegistry(source, ""); err == nil {
				t.Fatal("empty input admitted")
			}
		}
		for _, profile := range []string{"unknown", LegacyProfile} {
			if _, err := LoadEmbeddedRegistry(embeddedFixture(map[string]string{"a.json": "true"}), profile); err == nil {
				t.Fatal("unknown/unpinned profile admitted")
			}
		}
	})
	t.Run("admission", func(t *testing.T) {
		for name, files := range map[string]map[string]string{
			"duplicate-key":     {"a.json": `{"x":1,"\u0078":2}`},
			"duplicate-id":      {"a.json": `{"$id":"https://example.test/same"}`, "b.json": `{"$id":"https://example.test/same"}`},
			"duplicate-anchor":  {"a.json": `{"$defs":{"a":{"$anchor":"same"},"b":{"$anchor":"same"}}}`},
			"depth":             {"a.json": strings.Repeat(`{"items":`, 257) + `true` + strings.Repeat(`}`, 257)},
			"filename":          {strings.Repeat("a", 236) + ".json": "true"},
			"missing-reference": {"a.json": `{"$ref":"../outside.json"}`},
		} {
			t.Run(name, func(t *testing.T) {
				_, err := LoadEmbeddedRegistry(embeddedFixture(files), "")
				var d *Diagnostic
				if err == nil || !errors.As(err, &d) {
					t.Fatalf("unattributed admission %v", err)
				}
			})
		}
		source := embeddedFixture(map[string]string{strings.Repeat("a", 235) + ".json": "true"})
		if _, err := LoadEmbeddedRegistry(source, ""); err != nil {
			t.Fatalf("240-byte boundary: %v", err)
		}
	})
	t.Run("document-count", func(t *testing.T) {
		source := fstest.MapFS{}
		for i := 0; i < 10000; i++ {
			source[fmt.Sprintf("%05d.json", i)] = &fstest.MapFile{Data: []byte("true")}
		}
		if _, err := LoadEmbeddedRegistry(source, ""); err != nil {
			t.Fatalf("exact document limit: %v", err)
		}
		source["10000.json"] = &fstest.MapFile{Data: []byte("true")}
		if _, err := LoadEmbeddedRegistry(source, ""); err == nil || !strings.Contains(err.Error(), "10000") {
			t.Fatalf("document limit: %v", err)
		}
	})
}

type hostileEntry struct {
	fs.DirEntry
	name string
	mode fs.FileMode
}

func (e hostileEntry) Name() string      { return e.name }
func (e hostileEntry) Type() fs.FileMode { return e.mode.Type() }
func (e hostileEntry) IsDir() bool       { return e.mode.IsDir() }
func (e hostileEntry) Info() (fs.FileInfo, error) {
	i, err := e.DirEntry.Info()
	return hostileInfo{i, e.name, e.mode}, err
}

type hostileInfo struct {
	fs.FileInfo
	name string
	mode fs.FileMode
}

func (i hostileInfo) Name() string      { return i.name }
func (i hostileInfo) Mode() fs.FileMode { return i.mode }
func (i hostileInfo) IsDir() bool       { return i.mode.IsDir() }

type hostileFS struct {
	fstest.MapFS
	entries  []fs.DirEntry
	opened   []string
	read     int
	oversize bool
	readErr  bool
	closeErr bool
	statMode fs.FileMode
	rootMode *fs.FileMode
}

func (s *hostileFS) Stat(name string) (fs.FileInfo, error) {
	info, err := fs.Stat(s.MapFS, name)
	if err == nil && name == "." && s.rootMode != nil {
		return hostileInfo{info, ".", *s.rootMode}, nil
	}
	return info, err
}
func (s *hostileFS) ReadDir(name string) ([]fs.DirEntry, error) {
	if name == "." && s.entries != nil {
		return s.entries, nil
	}
	return s.MapFS.ReadDir(name)
}
func (s *hostileFS) Open(name string) (fs.File, error) {
	s.opened = append(s.opened, name)
	f, err := s.MapFS.Open(name)
	if err != nil {
		return nil, err
	}
	if name == "a.json" {
		return &hostileFile{File: f, source: s}, nil
	}
	return f, nil
}

type hostileFile struct {
	fs.File
	source *hostileFS
}

func (f *hostileFile) Read(p []byte) (int, error) {
	if f.source.readErr {
		return 0, errors.New("hostile read")
	}
	if f.source.oversize {
		remaining := (16 << 20) + 4096 - f.source.read
		if remaining <= 0 {
			return 0, io.EOF
		}
		n := min(len(p), remaining)
		for i := range p[:n] {
			p[i] = ' '
		}
		f.source.read += n
		return n, nil
	}
	return f.File.Read(p)
}
func (f *hostileFile) Stat() (fs.FileInfo, error) {
	i, err := f.File.Stat()
	if f.source.statMode != 0 {
		return hostileInfo{i, "a.json", f.source.statMode}, err
	}
	return i, err
}
func (f *hostileFile) Close() error {
	err := f.File.Close()
	if f.source.closeErr {
		return errors.New("hostile close")
	}
	return err
}

func TestEmbeddedHostileFilesystem(t *testing.T) {
	base := embeddedFixture(map[string]string{"a.json": "true"})
	entries, err := base.ReadDir(".")
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"../outside.json", "/outside.json", "a/b.json", ".", "..", "bad\x00.json"} {
		t.Run(name, func(t *testing.T) {
			source := &hostileFS{MapFS: base, entries: []fs.DirEntry{hostileEntry{entries[0], name, 0}}}
			_, err := LoadEmbeddedRegistry(source, "")
			if err == nil {
				t.Fatal("invalid entry accepted")
			}
			for _, path := range source.opened {
				if path != "." {
					t.Fatalf("invalid entry opened: %q", path)
				}
			}
		})
	}
	for _, mode := range []fs.FileMode{fs.ModeSymlink, fs.ModeNamedPipe, fs.ModeSocket, fs.ModeDevice, fs.ModeIrregular} {
		t.Run(mode.String(), func(t *testing.T) {
			source := &hostileFS{MapFS: base, entries: []fs.DirEntry{hostileEntry{entries[0], "a.json", mode}}}
			if _, err := LoadEmbeddedRegistry(source, ""); err == nil {
				t.Fatal("nonregular entry admitted")
			}
		})
	}
	t.Run("duplicate-path", func(t *testing.T) {
		source := &hostileFS{MapFS: base, entries: []fs.DirEntry{entries[0], entries[0]}}
		if _, err := LoadEmbeddedRegistry(source, ""); err == nil {
			t.Fatal("duplicate physical path admitted")
		}
	})
	for _, tc := range []struct {
		name    string
		source  hostileFS
		message string
	}{
		{"bounded-read", hostileFS{MapFS: base, oversize: true}, "16 MiB"},
		{"read-error", hostileFS{MapFS: base, readErr: true}, "hostile read"},
		{"close-error", hostileFS{MapFS: base, closeErr: true}, "hostile close"},
		{"opened-file-type", hostileFS{MapFS: base, statMode: fs.ModeSymlink}, "nonregular"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, err := LoadEmbeddedRegistry(&tc.source, "")
			if err == nil || !strings.Contains(err.Error(), tc.message) {
				t.Fatalf("hostile filesystem: %v", err)
			}
			if tc.source.read > (16<<20)+1 {
				t.Fatalf("unbounded read %d", tc.source.read)
			}
		})
	}
}

func TestEmbeddedLegacyParity(t *testing.T) {
	root := corpusRoot(t)
	disk, err := LoadLegacyRegistry(root)
	if err != nil {
		t.Fatal(err)
	}
	embedded, err := LoadEmbeddedRegistry(os.DirFS(root), LegacyProfile)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(disk.Nodes(), embedded.Nodes()) {
		t.Fatal("legacy path/raw/identity/node parity lost")
	}
	if len(disk.references) != len(embedded.references) {
		t.Fatal("reference count differs")
	}
	for _, ref := range disk.references {
		node, err := embedded.Resolve(ref.source.base, ref.ref)
		if err != nil || !reflect.DeepEqual(node, copyNode(ref.target)) {
			t.Fatalf("legacy target %s#%s %v", ref.source.Path, ref.source.Pointer, err)
		}
	}
	for _, tc := range []struct{ node, valid, invalid string }{
		{"type/basic.json#/definitions/entityName", `"valid name"`, `"bad::name"`},
		{"type/basic.json#/definitions/entityLink", `"<#E::tábles::name>"`, `"<#E::tables::a|b>"`},
		{"type/basic.json#/definitions/uuid", `"not-asserted-by-2020-format"`, `123`},
	} {
		for _, registry := range []*Registry{disk, embedded} {
			if err := registry.Validate(legacyBase+tc.node, []byte(tc.valid)); err != nil {
				t.Fatalf("valid legacy value %s: %v", tc.node, err)
			}
			if err := registry.Validate(legacyBase+tc.node, []byte(tc.invalid)); err == nil {
				t.Fatalf("invalid legacy value %s admitted", tc.node)
			}
		}
	}
}

func TestEmbeddedExactByteAndRawEntryBounds(t *testing.T) {
	t.Run("bytes", func(t *testing.T) {
		raw := "true" + strings.Repeat(" ", maxJSONBytes-4)
		r, err := LoadEmbeddedRegistry(embeddedFixture(map[string]string{"a.json": raw}), "")
		if err != nil {
			t.Fatalf("exact byte limit rejected: %v", err)
		}
		n, err := r.Resolve("file:///__openmetadata_embedded__/a.json", "")
		if err != nil || string(n.Document) != raw {
			t.Fatal("exact-limit raw source lost", err)
		}
	})
	for _, count := range []int{999998, 999999} {
		t.Run(fmt.Sprint(count), func(t *testing.T) {
			raw := `{"default":[` + strings.TrimSuffix(strings.Repeat("null,", count), ",") + `]}`
			r, err := LoadEmbeddedRegistry(embeddedFixture(map[string]string{"a.json": raw}), "")
			if count == 999998 {
				if err != nil || len(r.entries) != 1000000 {
					t.Fatalf("exact raw-entry limit rejected: %v", err)
				}
			} else {
				var d *Diagnostic
				if err == nil || !errors.As(err, &d) || d.Path != "a.json" || d.Pointer != "/default/999998" {
					t.Fatalf("raw-entry overflow attribution: %v", err)
				}
			}
		})
	}
}

func TestEmbeddedAcceptedSemantics(t *testing.T) {
	// These are fresh characterizations of the accepted shared Task2 semantics.
	for name, files := range map[string]map[string]string{
		"relative-collector": {
			"a.json":     `{"$ref":"dir/child"}`,
			"b.json":     `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/pass","definitions":{"pass":true,"target":{"$id":"dir/child","allOf":[{"$ref":"../value.json"}]}}}`,
			"value.json": `{"type":"integer"}`,
		},
		"draft7-siblings":         {"a.json": `{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/t","type":"string","definitions":{"t":{"type":"integer"}}}`},
		"removed-additionalItems": {"a.json": `{"type":"integer","additionalItems":{"$ref":"https://unregistered.invalid/ignored"}}`},
	} {
		t.Run(name, func(t *testing.T) {
			r, err := LoadEmbeddedRegistry(embeddedFixture(files), "")
			if err != nil {
				t.Fatal(err)
			}
			if err = r.Validate("file:///__openmetadata_embedded__/a.json", []byte(`2`)); err != nil {
				t.Fatal(err)
			}
			if err = r.Validate("file:///__openmetadata_embedded__/a.json", []byte(`"bad"`)); err == nil {
				t.Fatal("integer assertion lost")
			}
			c, err := r.Check()
			if err != nil || c.Compiled != c.Nodes {
				t.Fatalf("independent compilation %+v %v", c, err)
			}
		})
	}
	t.Run("selected-numeric", func(t *testing.T) {
		r, err := LoadEmbeddedRegistry(embeddedFixture(map[string]string{"a.json": `{"x":{"minimum":1e10001}}`}), "")
		if err != nil {
			t.Fatal(err)
		}
		id := "file:///__openmetadata_embedded__/a.json"
		n, err := r.resolve(id, "#/x")
		if err != nil {
			t.Fatal(err)
		}
		requireBlocked(t, r.admitNumericInstance(n, nil), "a.json#/x/minimum")
		requireBlocked(t, r.Validate(id+"#/x", []byte(`null`)), "a.json#/x/minimum")
		c, err := r.Check()
		if err != nil || c.Nodes != 1 || c.Compiled != 1 {
			t.Fatalf("selection changed independent graph %+v %v", c, err)
		}
	})
	t.Run("canonical-metadata-and-independent-check", func(t *testing.T) {
		r, err := LoadEmbeddedRegistry(embeddedFixture(map[string]string{
			"a.json": `{"$schema":42,"type":"integer"}`,
			"b.json": `{"type":"integer"}`,
		}), "")
		if err != nil {
			t.Fatal(err)
		}
		var native *jsonschema.SchemaValidationError
		if err = r.Validate("file:///__openmetadata_embedded__/a.json", []byte(`2`)); err == nil || errors.Is(err, ErrBlocked) || !errors.As(err, &native) {
			t.Fatalf("ordinary metadata invalidity repaired/blocked: %v", err)
		}
		c, err := r.Check()
		if err == nil || errors.Is(err, ErrBlocked) || c.Compiled != 1 || c.Nodes != 2 {
			t.Fatalf("truthful independent compile %+v %v", c, err)
		}
	})
}

func TestEmbeddedFilesystemTraversal(t *testing.T) {
	t.Run("unsorted-source", func(t *testing.T) {
		source := &hostileFS{MapFS: embeddedFixture(map[string]string{"a.json": "true", "z.json": "false"})}
		entries, err := source.MapFS.ReadDir(".")
		if err != nil {
			t.Fatal(err)
		}
		source.entries = []fs.DirEntry{entries[1], entries[0]}
		r, err := LoadEmbeddedRegistry(source, "")
		if err != nil {
			t.Fatal(err)
		}
		nodes := r.Nodes()
		if len(nodes) != 2 || nodes[0].Path != "a.json" || nodes[1].Path != "z.json" {
			t.Fatal("source order leaked into nodes", nodes)
		}
		documents := []string{}
		for _, path := range source.opened {
			if path != "." {
				documents = append(documents, path)
			}
		}
		if !reflect.DeepEqual(documents, []string{"a.json", "z.json"}) {
			t.Fatal("ingestion not sorted", documents)
		}
	})
	t.Run("root-mode", func(t *testing.T) {
		for _, mode := range []fs.FileMode{0, fs.ModeSymlink, fs.ModeDir | fs.ModeSymlink} {
			source := &hostileFS{MapFS: embeddedFixture(map[string]string{"a.json": "true"}), rootMode: &mode}
			if _, err := LoadEmbeddedRegistry(source, ""); err == nil {
				t.Fatalf("nonphysical directory root %s admitted", mode)
			}
		}
	})
	t.Run("directory-depth", func(t *testing.T) {
		for _, depth := range []int{256, 257} {
			source := embeddedFixture(map[string]string{strings.Repeat("d/", depth) + "a.json": "true"})
			_, err := LoadEmbeddedRegistry(source, "")
			if (err == nil) != (depth == 256) {
				t.Fatalf("filesystem depth %d: %v", depth, err)
			}
		}
	})
	t.Run("non-json-special-entry", func(t *testing.T) {
		source := fstest.MapFS{"a.json": &fstest.MapFile{Data: []byte("true")}, "ignored.txt": &fstest.MapFile{Mode: fs.ModeNamedPipe}}
		if _, err := LoadEmbeddedRegistry(source, ""); err == nil {
			t.Fatal("nonregular non-json entry admitted")
		}
	})
}

func TestRegistryRootFilenameBound(t *testing.T) {
	root := filepath.Join(t.TempDir(), strings.Repeat("a", 241))
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "a.json"), []byte("true"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadRegistry(root); err == nil || !strings.Contains(err.Error(), "240") {
		t.Fatalf("disk root filename bound lost: %v", err)
	}
}
