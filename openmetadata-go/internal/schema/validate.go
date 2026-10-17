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
			if loc.pointer == "" {
				documents[id] = documents[r.documents[loc.path].physical]
			} else {
				// A scoped resource is locally retrievable by its own identity.
				// Preserve its inherited dialect when loaded independently.
				n := r.entries[keyAt(loc.path, loc.pointer)]
				v, _ := decode(n.Document)
				if m, ok := v.(map[string]any); ok {
					if _, declared := m["$schema"]; !declared {
						if draft := r.inheritedDialect(n); draft != "" {
							m["$schema"] = draft
						}
					}
				}
				documents[id] = v
			}
		}
	}
	c.UseLoader(localLoader{documents})
	return c, nil
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
	root := r.documents[n.Path]
	dialect := declaredResourceDialect(root, "")
	if n.Pointer == "" {
		return dialect
	}
	// Most source documents declare a dialect only at the root. Avoid traversing
	// their schema children when no ancestor can select another resource draft.
	scoped := false
	for p := n.Pointer; p != ""; p = parentPointer(p) {
		if entry := r.entries[keyAt(n.Path, p)]; entry != nil {
			if m, ok := entry.value.(map[string]any); ok {
				_, declared := m["$schema"].(string)
				id, _ := m["$id"].(string)
				if declared && id != "" {
					scoped = true
					break
				}
			}
		}
	}
	if !scoped {
		return dialect
	}
	current := root
	for current.Pointer != n.Pointer {
		m, ok := current.value.(map[string]any)
		if !ok {
			return declaredResourceDialect(n, dialect)
		}
		var next *entry
		for _, pointer := range compilerResourceChildren(m, current.Pointer, dialect) {
			if pointer == n.Pointer || strings.HasPrefix(n.Pointer, pointer+"/") {
				next = r.entries[keyAt(n.Path, pointer)]
				break
			}
		}
		if next == nil {
			return declaredResourceDialect(n, dialect)
		}
		dialect = declaredResourceDialect(next, dialect)
		current = next
	}
	return dialect
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
