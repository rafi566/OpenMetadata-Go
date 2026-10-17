// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

var ErrBlocked = errors.New("schema semantics blocked")

type Diagnostic struct {
	Stage, Path, Pointer, Message string
	Cause                         error
}

func (d *Diagnostic) Error() string {
	return fmt.Sprintf("%s#%s: %s: %s", d.Path, d.Pointer, d.Stage, d.Message)
}
func (d *Diagnostic) Unwrap() error { return d.Cause }
func diagnostic(stage, path, pointer string, err error) error {
	return &Diagnostic{stage, path, pointer, err.Error(), err}
}

// Document is the unchanged JSON value at Path/Pointer; callers own its bytes.
type Node struct {
	ID, Path, Pointer string
	Document          json.RawMessage
}
type entry struct {
	Node
	value                           any
	base, resourcePointer, physical string
}
type resource struct{ path, pointer string }
type reference struct {
	source       *entry
	keyword, ref string
	target       *entry
}

// Registry is immutable after loading. Its maps are bounded by the admitted corpus,
// never by request URLs. Compiler state is private to each Check or Validate call.
type Registry struct {
	root       string
	legacy     bool
	documents  map[string]*entry
	entries    map[string]*entry
	schemas    map[string]*entry
	identities map[string]resource
	ambiguous  map[string]bool
	references []reference
}

func LoadRegistry(root string) (*Registry, error) { return loadRegistry(root, false) }
func loadRegistry(root string, legacy bool) (*Registry, error) {
	abs, e := filepath.Abs(root)
	if e != nil {
		return nil, e
	}
	info, e := os.Lstat(abs)
	if e != nil {
		return nil, diagnostic("load", root, "", e)
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, diagnostic("load", root, "", errors.New("root must be a physical directory"))
	}
	abs, e = filepath.EvalSymlinks(abs)
	if e != nil {
		return nil, diagnostic("load", root, "", e)
	}
	r := &Registry{root: abs, legacy: legacy, documents: map[string]*entry{}, entries: map[string]*entry{}, schemas: map[string]*entry{}, identities: map[string]resource{}, ambiguous: map[string]bool{}}
	e = filepath.WalkDir(abs, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel, _ := filepath.Rel(abs, path)
		rel = filepath.ToSlash(rel)
		if d.Type()&os.ModeSymlink != 0 {
			return diagnostic("load", rel, "", errors.New("symlinks are not admitted"))
		}
		if len([]byte(d.Name())) > 240 {
			return diagnostic("load", rel, "", errors.New("filename exceeds 240 bytes"))
		}
		if !d.IsDir() {
			info, e := d.Info()
			if e != nil {
				return diagnostic("load", rel, "", e)
			}
			if !info.Mode().IsRegular() {
				return diagnostic("load", rel, "", errors.New("nonregular files are not admitted"))
			}
		}
		if d.IsDir() || !strings.HasSuffix(rel, ".json") {
			return nil
		}
		if len(r.documents) >= 10000 {
			return diagnostic("load", rel, "", errors.New("document limit 10000 exceeded"))
		}
		f, e := os.Open(path)
		if e != nil {
			return e
		}
		b, e := io.ReadAll(io.LimitReader(f, (16<<20)+1))
		f.Close()
		if e != nil {
			return e
		}
		if len(b) > 16<<20 {
			return diagnostic("load", rel, "", errors.New("document exceeds 16 MiB"))
		}
		v, e := decode(b)
		if e != nil {
			return diagnostic("load", rel, "", e)
		}
		physical := (&url.URL{Scheme: "file", Path: path}).String()
		if legacy {
			physical = legacyBase + rel
		}
		rootEntry := &entry{Node: Node{ID: physical, Path: rel, Document: bytes.Clone(b)}, value: v, base: physical, physical: physical}
		r.documents[rel] = rootEntry
		return r.indexRaw(rootEntry, "", json.RawMessage(b), physical, 0)
	})
	if e != nil {
		return nil, e
	}
	if len(r.documents) == 0 {
		return nil, diagnostic("load", root, "", errors.New("no JSON documents"))
	}
	if legacy {
		if e := r.checkLegacy(); e != nil {
			return nil, e
		}
	}
	for _, path := range sortedKeys(r.documents) {
		d := r.documents[path]
		if e := r.addIdentity(d.physical, resource{path, ""}); e != nil {
			return nil, e
		}
	}
	for _, path := range sortedKeys(r.documents) {
		d := r.documents[path]
		if e := r.markSchema(d, d.physical, "", 0); e != nil {
			return nil, e
		}
	}
	if legacy {
		r.addLegacyAliases()
	}
	// References beneath unknown vocabulary containers are part of the pinned
	// legacy graph. They do not turn those containers into instance properties.
	if legacy {
		for _, key := range sortedKeys(r.entries) {
			n := r.entries[key]
			m, ok := n.value.(map[string]any)
			if !ok {
				continue
			}
			if _, ok = m["$ref"]; ok {
				if _, known := r.schemas[key]; !known {
					if e := r.markSchema(n, n.physical, "", 0); e != nil {
						return nil, e
					}
				}
			}
		}
	}
	for i := 0; i < len(r.references); i++ {
		ref := &r.references[i]
		target, e := r.resolve(ref.source.base, ref.ref)
		if e != nil {
			return nil, diagnostic("resolve", ref.source.Path, ref.source.Pointer+"/"+escape(ref.keyword), e)
		}
		ref.target = target
		if _, ok := r.schemas[keyOf(target)]; !ok {
			if e := r.markSchema(target, r.scopeFor(target).base, r.scopeFor(target).resourcePointer, 0); e != nil {
				return nil, e
			}
		}
	}
	return r, nil
}
func keyOf(n *entry) string { return n.Path + "#" + n.Pointer }
func sortedKeys[T any](m map[string]T) []string {
	k := make([]string, 0, len(m))
	for s := range m {
		k = append(k, s)
	}
	sort.Strings(k)
	return k
}
func (r *Registry) indexRaw(doc *entry, p string, raw json.RawMessage, physical string, depth int) error {
	if depth > 256 || len(r.entries) >= 1000000 {
		return diagnostic("load", doc.Path, p, errors.New("schema structure limit exceeded"))
	}
	v, e := decode(raw)
	if e != nil {
		return diagnostic("load", doc.Path, p, e)
	}
	n := &entry{Node: Node{ID: physical + fragment(p), Path: doc.Path, Pointer: p, Document: bytes.Clone(raw)}, value: v, base: physical, physical: physical}
	if p == "" {
		n = doc
	}
	r.entries[keyOf(n)] = n
	switch v.(type) {
	case map[string]any:
		var fields map[string]json.RawMessage
		json.Unmarshal(raw, &fields)
		for _, k := range sortedKeys(fields) {
			if e := r.indexRaw(doc, p+"/"+escape(k), fields[k], physical, depth+1); e != nil {
				return e
			}
		}
	case []any:
		var fields []json.RawMessage
		json.Unmarshal(raw, &fields)
		for i, b := range fields {
			if e := r.indexRaw(doc, fmt.Sprintf("%s/%d", p, i), b, physical, depth+1); e != nil {
				return e
			}
		}
	}
	return nil
}
func fragment(p string) string {
	if p == "" {
		return ""
	}
	u := url.URL{Fragment: p}
	return u.String()
}
func (r *Registry) addIdentity(id string, loc resource) error {
	if old, ok := r.identities[id]; ok && old != loc {
		return diagnostic("load", loc.path, loc.pointer+"/$id", fmt.Errorf("duplicate identity %s (also %s#%s)", id, old.path, old.pointer))
	}
	r.identities[id] = loc
	return nil
}
func (r *Registry) markSchema(n *entry, base, resourcePointer string, depth int) error {
	if _, ok := r.schemas[keyOf(n)]; ok {
		return nil
	}
	if depth > 256 {
		return diagnostic("load", n.Path, n.Pointer, errors.New("schema depth exceeded"))
	}
	m, object := n.value.(map[string]any)
	if !object {
		if _, ok := n.value.(bool); !ok {
			return diagnostic("load", n.Path, n.Pointer, errors.New("schema must be object or boolean"))
		}
	}
	if draft, ok := m["$schema"].(string); ok && draft != "https://json-schema.org/draft/2020-12/schema" && draft != "http://json-schema.org/draft-07/schema#" && draft != "http://json-schema.org/draft-07/schema" && draft != "https://json-schema.org/draft/2019-09/schema" {
		return diagnostic("load", n.Path, n.Pointer+"/$schema", fmt.Errorf("%w: unsupported dialect %s", ErrBlocked, draft))
	}
	dialect := r.inheritedDialect(n)
	modern := !strings.Contains(dialect, "draft-07")
	latest := modern && !strings.Contains(dialect, "2019-09")
	_, hasRef := m["$ref"]
	if id, ok := m["$id"].(string); ok && !r.legacy && (modern || !hasRef) {
		u, e := resolveURL(base, id)
		if e != nil {
			return diagnostic("load", n.Path, n.Pointer+"/$id", e)
		}
		if u.Fragment != "" {
			return diagnostic("load", n.Path, n.Pointer+"/$id", fmt.Errorf("%w: nonempty $id fragments", ErrBlocked))
		}
		base = u.String()
		resourcePointer = n.Pointer
		if e := r.addIdentity(base, resource{n.Path, n.Pointer}); e != nil {
			return e
		}
	}
	n.base = base
	n.resourcePointer = resourcePointer
	n.ID = base + fragment(strings.TrimPrefix(n.Pointer, resourcePointer))
	r.schemas[keyOf(n)] = n
	for _, k := range []string{"$anchor", "$dynamicAnchor"} {
		if !modern || (k == "$dynamicAnchor" && !latest) {
			continue
		}
		if a, ok := m[k].(string); ok {
			if e := r.addIdentity(base+"#"+a, resource{n.Path, n.Pointer}); e != nil {
				return e
			}
		}
	}
	for _, k := range []string{"$ref", "$dynamicRef", "$recursiveRef"} {
		if (k == "$dynamicRef" && !latest) || (k == "$recursiveRef" && (!modern || latest)) {
			continue
		}
		if value, ok := m[k]; ok {
			ref, ok := value.(string)
			if !ok {
				return diagnostic("resolve", n.Path, n.Pointer+"/"+k, errors.New("reference must be string"))
			}
			r.references = append(r.references, reference{source: n, keyword: k, ref: ref})
		}
	}
	for _, p := range schemaChildren(m, n.Pointer, r.inheritedDialect(n)) {
		child := r.entries[n.Path+"#"+p]
		if child == nil {
			continue
		}
		if e := r.markSchema(child, base, resourcePointer, depth+1); e != nil {
			return e
		}
	}
	return nil
}
func schemaChildren(m map[string]any, p, dialect string) []string {
	modern := !strings.Contains(dialect, "draft-07")
	latest := modern && !strings.Contains(dialect, "2019-09")
	if _, hasRef := m["$ref"]; hasRef && !modern {
		// Draft7 reference-object siblings are metadata. Explicit reference
		// targets are admitted separately by the graph closure worklist.
		return nil
	}
	var out []string
	for _, k := range []string{"$defs", "definitions", "properties", "patternProperties", "dependentSchemas"} {
		if !modern && (k == "$defs" || k == "dependentSchemas") {
			continue
		}
		if values, ok := m[k].(map[string]any); ok {
			for _, name := range sortedKeys(values) {
				out = append(out, p+"/"+k+"/"+escape(name))
			}
		}
	}
	for _, k := range []string{"additionalProperties", "unevaluatedProperties", "propertyNames", "contains", "additionalItems", "unevaluatedItems", "not", "if", "then", "else", "contentSchema"} {
		if k == "additionalItems" && latest {
			continue
		}
		if !modern && (k == "unevaluatedProperties" || k == "unevaluatedItems" || k == "contentSchema") {
			continue
		}
		if _, ok := m[k]; ok {
			out = append(out, p+"/"+k)
		}
	}
	for _, k := range []string{"allOf", "anyOf", "oneOf", "prefixItems", "items"} {
		if k == "prefixItems" && !latest {
			continue
		}
		if v, ok := m[k]; ok {
			if a, ok := v.([]any); ok {
				for i := range a {
					out = append(out, fmt.Sprintf("%s/%s/%d", p, k, i))
				}
			} else if k == "items" {
				out = append(out, p+"/"+k)
			}
		}
	}
	if values, ok := m["dependencies"].(map[string]any); ok {
		for _, name := range sortedKeys(values) {
			if _, array := values[name].([]any); !array {
				out = append(out, p+"/dependencies/"+escape(name))
			}
		}
	}
	return out
}
func (r *Registry) Nodes() []Node {
	out := make([]Node, 0, len(r.schemas))
	for _, k := range sortedKeys(r.schemas) {
		out = append(out, copyNode(r.schemas[k]))
	}
	return out
}
func copyNode(n *entry) Node { v := n.Node; v.Document = bytes.Clone(v.Document); return v }

func (r *Registry) scopeFor(n *entry) *entry {
	p := n.Pointer
	for {
		if parent := r.schemas[n.Path+"#"+p]; parent != nil {
			return parent
		}
		i := strings.LastIndex(p, "/")
		if i < 0 {
			break
		}
		p = p[:i]
	}
	return r.documents[n.Path]
}
