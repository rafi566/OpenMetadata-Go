// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"maps"
	"net/url"
	"os"
	"path"
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
	drafts     map[string]string
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
	if len(info.Name()) > 240 {
		return nil, diagnostic("load", ".", "", errors.New("filename exceeds 240 bytes"))
	}
	abs, e = filepath.EvalSymlinks(abs)
	if e != nil {
		return nil, diagnostic("load", root, "", e)
	}
	return loadRegistryFS(os.DirFS(abs), filepath.ToSlash(abs), legacy)
}

func loadRegistryFS(source fs.FS, root string, legacy bool) (*Registry, error) {
	if source == nil {
		return nil, diagnostic("load", root, "", errors.New("nil registry filesystem"))
	}
	r := &Registry{root: root, legacy: legacy, documents: map[string]*entry{}, entries: map[string]*entry{}, schemas: map[string]*entry{}, drafts: map[string]string{}, identities: map[string]resource{}, ambiguous: map[string]bool{}}
	info, err := fs.Stat(source, ".")
	if err != nil {
		return nil, diagnostic("load", root, "", err)
	}
	if !info.IsDir() || info.Mode().Type() != fs.ModeDir {
		return nil, diagnostic("load", root, "", errors.New("root must be a physical directory"))
	}
	if err := r.ingestDirectory(source, ".", 0); err != nil {
		return nil, err
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
		if e := r.collectResources(d, d.physical, "", "", 0); e != nil {
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

func (r *Registry) ingestDirectory(source fs.FS, dir string, depth int) error {
	if depth > 256 {
		return diagnostic("load", dir, "", errors.New("filesystem depth exceeds 256"))
	}
	children, err := fs.ReadDir(source, dir)
	if err != nil {
		return diagnostic("load", dir, "", err)
	}
	sort.Slice(children, func(i, j int) bool { return children[i].Name() < children[j].Name() })
	previous := ""
	for _, child := range children {
		name := child.Name()
		if !fs.ValidPath(name) || name == "." || strings.ContainsAny(name, "/\x00") {
			return diagnostic("load", dir, "", fmt.Errorf("invalid filesystem entry name %q", name))
		}
		rel := path.Join(dir, name)
		if name == previous {
			return diagnostic("load", rel, "", errors.New("duplicate physical path"))
		}
		previous = name
		if len(name) > 240 {
			return diagnostic("load", rel, "", errors.New("filename exceeds 240 bytes"))
		}
		info, err := child.Info()
		if err != nil {
			return diagnostic("load", rel, "", err)
		}
		if info.Name() != name || child.Type() != info.Mode().Type() || child.IsDir() != info.IsDir() {
			return diagnostic("load", rel, "", errors.New("inconsistent filesystem entry metadata"))
		}
		if info.Mode()&fs.ModeSymlink != 0 {
			return diagnostic("load", rel, "", errors.New("symlinks are not admitted"))
		}
		if info.IsDir() {
			if info.Mode().Type() != fs.ModeDir {
				return diagnostic("load", rel, "", errors.New("nonregular directories are not admitted"))
			}
			if err := r.ingestDirectory(source, rel, depth+1); err != nil {
				return err
			}
			continue
		}
		if !info.Mode().IsRegular() {
			return diagnostic("load", rel, "", errors.New("nonregular files are not admitted"))
		}
		if !strings.HasSuffix(rel, ".json") {
			continue
		}
		if err := r.ingestDocument(source, rel); err != nil {
			return err
		}
	}
	return nil
}

func (r *Registry) ingestDocument(source fs.FS, rel string) error {
	if len(r.documents) >= 10000 {
		return diagnostic("load", rel, "", errors.New("document limit 10000 exceeded"))
	}
	f, err := source.Open(rel)
	if err != nil {
		return diagnostic("load", rel, "", err)
	}
	info, statErr := f.Stat()
	if statErr != nil || !info.Mode().IsRegular() {
		f.Close()
		if statErr == nil {
			statErr = errors.New("opened nonregular file is not admitted")
		}
		return diagnostic("load", rel, "", statErr)
	}
	b, readErr := io.ReadAll(io.LimitReader(f, maxJSONBytes+1))
	closeErr := f.Close()
	if err := errors.Join(readErr, closeErr); err != nil {
		return diagnostic("load", rel, "", err)
	}
	if len(b) > maxJSONBytes {
		return diagnostic("load", rel, "", errors.New("document exceeds 16 MiB"))
	}
	v, err := decode(b)
	if err != nil {
		return diagnostic("load", rel, "", err)
	}
	physical := (&url.URL{Scheme: "file", Path: path.Join(r.root, rel)}).String()
	if r.legacy {
		physical = legacyBase + rel
	}
	rootEntry := &entry{Node: Node{ID: physical, Path: rel, Document: bytes.Clone(b)}, value: v, base: physical, physical: physical}
	r.documents[rel] = rootEntry
	return r.indexRaw(rootEntry, "", json.RawMessage(b), physical, 0)
}

// Escape the physical-path delimiter without changing raw paths or pointers.
func keyAt(path, pointer string) string {
	return strings.ReplaceAll(strings.ReplaceAll(path, "%", "%25"), "#", "%23") + "#" + pointer
}
func keyOf(n *entry) string { return keyAt(n.Path, n.Pointer) }
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
	if _, collected := r.drafts[keyOf(n)]; !collected {
		if err := r.collectResources(n, base, resourcePointer, dialect, depth); err != nil {
			return err
		}
	}
	base, resourcePointer = n.base, n.resourcePointer
	r.schemas[keyOf(n)] = n
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
		child := r.entries[keyAt(n.Path, p)]
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
		if _, collected := r.drafts[keyAt(n.Path, p)]; collected {
			return r.entries[keyAt(n.Path, p)]
		}
		i := strings.LastIndex(p, "/")
		if i < 0 {
			break
		}
		p = p[:i]
	}
	return r.documents[n.Path]
}

func declaredResourceDialect(n *entry, fallback string) string {
	m, ok := n.value.(map[string]any)
	if !ok {
		return fallback
	}
	declared, ok := m["$schema"].(string)
	if !ok {
		return fallback
	}
	id, _ := m["$id"].(string)
	_, ref := m["$ref"]
	if n.Pointer == "" || (id != "" && !(strings.Contains(declared, "draft-07") && ref)) {
		return declared
	}
	return fallback
}

// The pinned collector discovers resources below ref siblings and retains
// additionalItems as a resource container even in 2020-12. Resource discovery
// uses these children without adding active graph nodes or references.
func compilerResourceChildren(m map[string]any, pointer, dialect string) []string {
	projection := m
	if _, ref := m["$ref"]; ref && strings.Contains(dialect, "draft-07") {
		projection = maps.Clone(m)
		delete(projection, "$ref")
	}
	children := schemaChildren(projection, pointer, dialect)
	if !strings.Contains(dialect, "draft-07") && !strings.Contains(dialect, "2019-09") {
		if _, present := m["additionalItems"]; present {
			children = append(children, pointer+"/additionalItems")
		}
	}
	return children
}

// Resource collection is distinct from active assertions: ignored ref siblings
// can contain applicable IDs without activating their assertions or references.
func (r *Registry) collectResources(n *entry, base, resourcePointer, fallback string, depth int) error {
	if _, collected := r.drafts[keyOf(n)]; collected {
		return nil
	}
	if depth > 256 {
		return diagnostic("load", n.Path, n.Pointer, errors.New("schema depth exceeded"))
	}
	m, _ := n.value.(map[string]any)
	dialect := declaredResourceDialect(n, fallback)
	modern := !strings.Contains(dialect, "draft-07")
	latest := modern && !strings.Contains(dialect, "2019-09")
	_, hasRef := m["$ref"]
	if id, ok := m["$id"].(string); ok && id != "" && !r.legacy && (modern || !hasRef) {
		u, err := resolveURL(base, id)
		if err != nil {
			return diagnostic("load", n.Path, n.Pointer+"/$id", err)
		}
		if u.Fragment != "" {
			return diagnostic("load", n.Path, n.Pointer+"/$id", fmt.Errorf("%w: nonempty $id fragments", ErrBlocked))
		}
		base, resourcePointer = u.String(), n.Pointer
		if err = r.addIdentity(base, resource{n.Path, n.Pointer}); err != nil {
			return err
		}
	}
	n.base, n.resourcePointer = base, resourcePointer
	n.ID = base + fragment(strings.TrimPrefix(n.Pointer, resourcePointer))
	r.drafts[keyOf(n)] = dialect
	for _, keyword := range []string{"$anchor", "$dynamicAnchor"} {
		if !modern || (keyword == "$dynamicAnchor" && !latest) {
			continue
		}
		if anchor, ok := m[keyword].(string); ok {
			if err := r.addIdentity(base+"#"+anchor, resource{n.Path, n.Pointer}); err != nil {
				return err
			}
		}
	}
	for _, pointer := range compilerResourceChildren(m, n.Pointer, dialect) {
		if child := r.entries[keyAt(n.Path, pointer)]; child != nil {
			if err := r.collectResources(child, base, resourcePointer, dialect, depth+1); err != nil {
				return err
			}
		}
	}
	return nil
}

// Previously unselected raw pointers receive a bounded, isolated graph view.
// Entry metadata is copied because schema marking assigns base/ID fields; raw
// bytes and decoded values remain immutable and shared with the loaded corpus.
func (r *Registry) selectedSchema(n *entry) (*Registry, *entry, error) {
	if r.schemas[keyOf(n)] != nil {
		return r, n, nil
	}
	view := *r
	view.entries = make(map[string]*entry, len(r.entries))
	for key, original := range r.entries {
		copied := *original
		view.entries[key] = &copied
	}
	view.documents = make(map[string]*entry, len(r.documents))
	for path, original := range r.documents {
		view.documents[path] = view.entries[keyOf(original)]
	}
	view.schemas = make(map[string]*entry, len(r.schemas))
	for key := range r.schemas {
		view.schemas[key] = view.entries[key]
	}
	view.drafts = maps.Clone(r.drafts)
	view.identities, view.ambiguous = maps.Clone(r.identities), maps.Clone(r.ambiguous)
	view.references = make([]reference, len(r.references))
	for i, ref := range r.references {
		view.references[i] = ref
		view.references[i].source = view.entries[keyOf(ref.source)]
		view.references[i].target = view.entries[keyOf(ref.target)]
	}
	selected := view.entries[keyOf(n)]
	scope := view.scopeFor(selected)
	if err := view.markSchema(selected, scope.base, scope.resourcePointer, 0); err != nil {
		return nil, nil, err
	}
	for i := len(r.references); i < len(view.references); i++ {
		ref := &view.references[i]
		target, err := view.resolve(ref.source.base, ref.ref)
		if err != nil {
			return nil, nil, diagnostic("resolve", ref.source.Path, ref.source.Pointer+"/"+escape(ref.keyword), err)
		}
		ref.target = target
		scope := view.scopeFor(target)
		if err = view.markSchema(target, scope.base, scope.resourcePointer, 0); err != nil {
			return nil, nil, err
		}
	}
	return &view, selected, nil
}
