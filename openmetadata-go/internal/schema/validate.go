// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// CheckResult describes graph admission and compilation only. Compiled counts
// successful requested schema nodes; none of these counts certifies instances.
type CheckResult struct {
	Documents  int `json:"documents"`
	References int `json:"references"`
	Nodes      int `json:"nodes"`
	Compiled   int `json:"compiled"`
}
type localLoader struct{ documents map[string]any }

func (l localLoader) Load(id string) (any, error) {
	if d, ok := l.documents[id]; ok {
		return d, nil
	}
	return nil, fmt.Errorf("unregistered local schema %s", id)
}

func (r *Registry) compiler() (*jsonschema.Compiler, error) {
	c := jsonschema.NewCompiler()
	c.DefaultDraft(jsonschema.Draft2020)
	allowed := map[string]bool{}
	for _, key := range sortedKeys(r.schemas) {
		n := r.schemas[key]
		if m, ok := n.value.(map[string]any); ok {
			if p, ok := m["pattern"].(string); ok && r.patternEligible(n, n.Pointer+"/pattern", p) {
				allowed[p] = true
			}
		}
	}
	c.UseRegexpEngine(func(p string) (jsonschema.Regexp, error) {
		if allowed[p] {
			return legacyRegexp(p)
		}
		return genericRegexp(p)
	})
	documents := map[string]any{}
	for _, path := range sortedKeys(r.documents) {
		d := r.documents[path]
		v := d.value
		if r.legacy {
			// Only identity/reference fields are projected. The raw node tree remains
			// unchanged, and every projection is addressed by its original pointer.
			v, _ = decode(d.Document)
			m := v.(map[string]any)
			m["$id"] = d.physical

		}
		documents[d.physical] = v
		if e := c.AddResource(d.physical, v); e != nil {
			return nil, e
		}
	}
	if r.legacy {
		for _, ref := range r.references {
			setValue(documents[ref.source.physical], ref.source.Pointer+"/"+escape(ref.keyword), ref.target.physical+fragment(ref.target.Pointer))
		}
	}
	if !r.legacy {
		for id, loc := range r.identities {
			if loc.pointer == "" && id == r.documents[loc.path].physical {
				continue
			}
			// Alias retrieval creates a root at its identity URL. Preserve its
			// collected scope while keeping physical compiler inputs unchanged.
			n := r.entries[keyAt(loc.path, loc.pointer)]
			v, _ := decode(n.Document)
			if m, ok := v.(map[string]any); ok {
				draft := r.inheritedDialect(n)
				if draft == "" {
					draft = "https://json-schema.org/draft/2020-12/schema"
				}
				projectMetadataString(m, "$schema", draft)
				if _, ref := m["$ref"]; !ref || !strings.Contains(draft, "draft-07") {
					projectMetadataString(m, "$id", n.base)
				}
			}
			documents[id] = v
		}
	}
	c.UseLoader(localLoader{documents})
	return c, nil
}

func projectMetadataString(object map[string]any, keyword, replacement string) {
	if original, present := object[keyword]; present {
		if _, validType := original.(string); !validType {
			// Malformed metadata must reach canonical validation without repair.
			return
		}
	}
	object[keyword] = replacement
}

// A detached nonstring declaration selects the compiler's default draft rather
// than its collected scope. Reject it canonically before any sibling arithmetic.
// The only source value compiled here is $schema: every supported metaschema
// rejects its nonstring type before traversing or performing arithmetic on it.
func (r *Registry) rejectMalformedDialect(n *entry, fallback string, declaration any) error {
	c := jsonschema.NewCompiler()
	switch {
	case strings.Contains(fallback, "draft-07"):
		c.DefaultDraft(jsonschema.Draft7)
	case strings.Contains(fallback, "2019-09"):
		c.DefaultDraft(jsonschema.Draft2019)
	default:
		c.DefaultDraft(jsonschema.Draft2020)
	}
	if err := c.AddResource(n.physical, map[string]any{"$schema": declaration}); err != nil {
		return diagnostic("compile", n.Path, n.Pointer, err)
	}
	_, err := c.Compile(n.physical)
	if err == nil {
		return diagnostic("compile", n.Path, n.Pointer+"/$schema", errors.New("canonical metaschema unexpectedly accepted nonstring $schema"))
	}
	var meta *jsonschema.SchemaValidationError
	if errors.As(err, &meta) {
		err = &jsonschema.SchemaValidationError{URL: n.physical + fragment(n.Pointer), Err: meta.Err}
	}
	return joinDiagnostics(r.compileDiagnostics(n, err))
}

func setValue(v any, pointer string, value any) {
	parts := splitPointer(pointer)
	for _, part := range parts[:len(parts)-1] {
		switch x := v.(type) {
		case map[string]any:
			v = x[part]
		case []any:
			var i int
			fmt.Sscanf(part, "%d", &i)
			v = x[i]
		}
	}
	v.(map[string]any)[parts[len(parts)-1]] = value
}
func (r *Registry) patternDiagnostics() []error {
	var out []error
	for _, key := range sortedKeys(r.schemas) {
		n := r.schemas[key]
		m, ok := n.value.(map[string]any)
		if !ok {
			continue
		}
		patterns := map[string]string{}
		if p, ok := m["pattern"].(string); ok {
			patterns[n.Pointer+"/pattern"] = p
		}
		if p, ok := m["patternProperties"].(map[string]any); ok {
			for name := range p {
				patterns[n.Pointer+"/patternProperties/"+escape(name)] = name
			}
		}
		for _, pointer := range sortedKeys(patterns) {
			p := patterns[pointer]
			var e error
			if r.patternEligible(n, pointer, p) {
				_, e = legacyRegexp(p)
			} else {
				_, e = genericRegexp(p)
			}
			if e != nil {
				out = append(out, diagnostic("compile", n.Path, pointer, e))
			}
		}
	}
	return out
}
func (r *Registry) Check() (CheckResult, error) {
	result := CheckResult{Documents: len(r.documents), References: len(r.references), Nodes: len(r.schemas)}
	problems := r.patternDiagnostics()
	c, e := r.compiler()
	if e != nil {
		return result, e
	}
	numericAdmissions := make(map[string]numericAdmission, len(r.documents))
	for _, key := range sortedKeys(r.schemas) {
		n := r.schemas[key]
		if admission := r.admitNumericClosure(n, numericAdmissions); admission.err != nil {
			problems = append(problems, admission.err)
			continue
		}
		_, e = c.Compile(n.physical + fragment(n.Pointer))
		if e != nil {
			problems = append(problems, r.compileDiagnostics(n, e)...)
			c, e = r.compiler()
			if e != nil {
				return result, errors.Join(append(problems, e)...)
			}
			continue
		}
		result.Compiled++
	}
	return result, joinDiagnostics(problems)
}
func (r *Registry) Validate(id string, document []byte) error {
	n, e := r.resolve(id, "")
	if e != nil {
		return diagnostic("validate", id, "", e)
	}
	r, n, e = r.selectedSchema(n)
	if e != nil {
		return e
	}
	v, e := decode(document)
	if e != nil {
		return diagnostic("validate", n.Path, n.Pointer, e)
	}
	if e := r.admitNumericInstance(n, v); e != nil {
		return e
	}
	if problems := r.patternDiagnostics(); len(problems) > 0 {
		return errors.Join(problems...)
	}
	c, e := r.compiler()
	if e != nil {
		return e
	}
	s, e := c.Compile(n.physical + fragment(n.Pointer))
	if e != nil {
		return joinDiagnostics(r.compileDiagnostics(n, e))
	}
	if e = s.Validate(v); e != nil {
		return diagnostic("validate", n.Path, n.Pointer, e)
	}
	return nil
}

func (r *Registry) inheritedDialect(n *entry) string {
	for pointer := n.Pointer; ; pointer = parentPointer(pointer) {
		if dialect, known := r.drafts[keyAt(n.Path, pointer)]; known {
			if pointer == n.Pointer {
				return dialect
			}
			return declaredResourceDialect(n, dialect)
		}
		if pointer == "" {
			return declaredResourceDialect(n, "")
		}
	}
}

func (r *Registry) compileDiagnostics(n *entry, err error) []error {
	var meta *jsonschema.SchemaValidationError
	if !errors.As(err, &meta) {
		return []error{diagnostic("compile", n.Path, n.Pointer, err)}
	}
	source, e := r.resolve(meta.URL, "")
	if e != nil {
		source = n
	}
	var problems []error
	var visit func(*jsonschema.ValidationError)
	visit = func(v *jsonschema.ValidationError) {
		if len(v.Causes) > 0 {
			for _, child := range v.Causes {
				visit(child)
			}
			return
		}
		pointer := source.Pointer
		for _, part := range v.InstanceLocation {
			pointer += "/" + escape(part)
		}
		problems = append(problems, &Diagnostic{Stage: "compile", Path: source.Path, Pointer: pointer, Message: v.Error(), Cause: err})
	}
	if v, ok := meta.Err.(*jsonschema.ValidationError); ok {
		visit(v)
	} else {
		problems = append(problems, diagnostic("compile", source.Path, source.Pointer, err))
	}
	return problems
}
func joinDiagnostics(problems []error) error {
	sort.SliceStable(problems, func(i, j int) bool { return problems[i].Error() < problems[j].Error() })
	unique := problems[:0]
	for _, e := range problems {
		if len(unique) == 0 || e.Error() != unique[len(unique)-1].Error() {
			unique = append(unique, e)
		}
	}
	return errors.Join(unique...)
}
