// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"encoding/json"
	"fmt"
	"maps"
	"strconv"
	"strings"
)

// Raw Number ownership is independent of this dependency arithmetic boundary.
// ADR:2026-10-17-go-schema-reconstruction-preserves-source-semantics
type numericLocation struct{ path, pointer string }

type numericBudget struct {
	cost   int
	source string
	seen   map[numericLocation]bool
}

func (b *numericBudget) number(token string) error {
	mantissa, exponent := token, ""
	if i := strings.IndexAny(token, "eE"); i >= 0 {
		mantissa, exponent = token[:i], token[i+1:]
	}
	digits := 0
	for _, c := range mantissa {
		if c >= '0' && c <= '9' {
			digits++
		}
	}
	if digits > 10000 {
		return fmt.Errorf("%w: numeric mantissa exceeds 10000 digits", ErrBlocked)
	}
	shift := 0
	for _, c := range exponent {
		if c == '+' || c == '-' {
			continue
		}
		shift = shift*10 + int(c-'0')
		if shift > 10000 {
			return fmt.Errorf("%w: absolute numeric exponent exceeds 10000", ErrBlocked)
		}
	}
	b.cost += digits + shift
	if b.cost > 1000000 {
		return fmt.Errorf("%w: aggregate numeric arithmetic budget exceeds 1000000", ErrBlocked)
	}
	return nil
}
func (b *numericBudget) walk(v any, pointer string) (string, error) {
	switch value := v.(type) {
	case json.Number:
		location := numericLocation{b.source, pointer}
		if b.seen[location] {
			return "", nil
		}
		if err := b.number(string(value)); err != nil {
			return pointer, err
		}
		if b.seen == nil {
			b.seen = map[numericLocation]bool{}
		}
		b.seen[location] = true
	case map[string]any:
		for _, key := range sortedKeys(value) {
			if p, err := b.walk(value[key], pointer+"/"+escape(key)); err != nil {
				return p, err
			}
		}
	case []any:
		for i, item := range value {
			if p, err := b.walk(item, pointer+"/"+strconv.Itoa(i)); err != nil {
				return p, err
			}
		}
	}
	return "", nil
}

type numericAdmission struct {
	cost int
	err  error
}

// A Check owns this cache, with only admitted physical paths as keys (<=10000).
// Successful admissions retain cost so Validate can share the budget with input.
func (r *Registry) admitNumericClosure(n *entry, cache map[string]numericAdmission) numericAdmission {
	if admission, ok := cache[n.Path]; ok {
		return admission
	}
	budget := numericBudget{}
	edges := make(map[string][]string, len(r.documents))
	for _, ref := range r.references {
		edges[ref.source.Path] = append(edges[ref.source.Path], ref.target.Path)
	}
	documents := map[string]bool{n.Path: true}
	queue := []string{n.Path}
	for i := 0; i < len(queue); i++ {
		for _, target := range edges[queue[i]] {
			if !documents[target] {
				documents[target] = true
				queue = append(queue, target)
			}
		}
	}
	var err error
	metaScopes := make(map[numericLocation]string)
	for _, path := range sortedKeys(documents) {
		if err = r.admitNumericMetaschema(r.documents[path], "", &budget, metaScopes); err != nil {
			break
		}
	}
	for _, key := range sortedKeys(r.schemas) {
		if err != nil {
			break
		}
		node := r.schemas[key]
		if !documents[node.Path] {
			continue
		}
		// Explicit reference targets can be beneath unrecognized containers.
		if _, checked := metaScopes[numericLocation{node.Path, node.Pointer}]; !checked {
			// Collector resource scope can cross containers that this metaschema
			// treats as annotations, such as additionalItems in 2020-12.
			fallback := r.inheritedDialect(node)
			if err = r.admitNumericMetaschema(node, fallback, &budget, metaScopes); err != nil {
				break
			}
		}
		if err = r.admitNumericSchema(node, &budget); err != nil {
			break
		}
	}
	admission := numericAdmission{budget.cost, err}
	cache[n.Path] = admission
	return admission
}
func (r *Registry) admitNumericSchema(n *entry, budget *numericBudget) error {
	budget.source = n.Path
	m, ok := n.value.(map[string]any)
	if !ok {
		return nil
	}
	modern := !strings.Contains(r.inheritedDialect(n), "draft-07")
	if _, hasRef := m["$ref"]; hasRef && !modern {
		return nil
	}
	for _, keyword := range []string{"const", "enum", "exclusiveMaximum", "exclusiveMinimum", "maximum", "maxContains", "maxItems", "maxLength", "maxProperties", "minimum", "minContains", "minItems", "minLength", "minProperties", "multipleOf"} {
		if (keyword == "minContains" || keyword == "maxContains") && !modern {
			continue
		}
		value, exists := m[keyword]
		if !exists {
			continue
		}
		if keyword == "enum" {
			if _, ok := value.([]any); !ok {
				continue
			}
		}
		if keyword != "enum" && keyword != "const" {
			if _, ok := value.(json.Number); !ok {
				continue
			}
		}
		if pointer, err := budget.walk(value, n.Pointer+"/"+keyword); err != nil {
			return diagnostic("compile", n.Path, pointer, err)
		}
		switch keyword {
		case "minItems", "maxItems", "minLength", "maxLength", "minProperties", "maxProperties", "minContains", "maxContains":
			if keyword == "minContains" || keyword == "maxContains" {
				if _, active := m["contains"]; !active {
					continue
				}
			}
			number := Number{token: string(value.(json.Number))}
			digits, _, negative := number.decimal()
			if !number.IsInteger() || (negative && digits != "0") {
				continue
			}
			integer, err := number.Int64()
			if err != nil || (strconv.IntSize == 32 && integer > 1<<31-1) {
				return diagnostic("compile", n.Path, n.Pointer+"/"+keyword, fmt.Errorf("%w: cardinality exceeds validator platform-int range", ErrBlocked))
			}
		}
	}
	return nil
}
func (r *Registry) admitNumericInstance(n *entry, instance any) error {
	admission := r.admitNumericClosure(n, make(map[string]numericAdmission, len(r.documents)))
	if admission.err != nil {
		return admission.err
	}
	budget := numericBudget{cost: admission.cost}
	if pointer, err := budget.walk(instance, ""); err != nil {
		return diagnostic("validate", n.Path, n.Pointer, fmt.Errorf("%w at instance #%s", err, pointer))
	}
	return nil
}

func parentPointer(pointer string) string {
	if i := strings.LastIndex(pointer, "/"); i >= 0 {
		return pointer[:i]
	}
	return ""
}

// Canonical metaschemas perform arithmetic before ignoring ref assertions or
// rejecting malformed uniqueness-array elements. This walk changes no graph or
// compiler input; source locations share the assertion budget exactly once.
func (r *Registry) admitNumericMetaschema(n *entry, fallback string, budget *numericBudget, scopes map[numericLocation]string) error {
	location := numericLocation{n.Path, n.Pointer}
	if _, checked := scopes[location]; checked {
		return nil
	}
	m, object := n.value.(map[string]any)
	if !object {
		scopes[location] = fallback
		return nil
	}
	dialect := fallback
	if declared, ok := m["$schema"].(string); ok {
		switch declared {
		case "http://json-schema.org/draft-07/schema#", "http://json-schema.org/draft-07/schema", "https://json-schema.org/draft/2019-09/schema", "https://json-schema.org/draft/2020-12/schema":
		default:
			return diagnostic("compile", n.Path, n.Pointer+"/$schema", fmt.Errorf("%w: compiler-metaschema admission supports canonical drafts only: %s", ErrBlocked, declared))
		}
		dialect = declaredResourceDialect(n, fallback)
	}
	scopes[location] = dialect
	modern := !strings.Contains(dialect, "draft-07")
	budget.source = n.Path
	walk := func(value any, pointer string) error {
		if p, err := budget.walk(value, pointer); err != nil {
			return diagnostic("compile", n.Path, p, fmt.Errorf("compiler-metaschema arithmetic admission: %w", err))
		}
		return nil
	}
	for _, keyword := range []string{"multipleOf", "minItems", "maxItems", "minLength", "maxLength", "minProperties", "maxProperties", "minContains", "maxContains"} {
		if !modern && (keyword == "minContains" || keyword == "maxContains") {
			continue
		}
		if value, ok := m[keyword].(json.Number); ok {
			if err := walk(value, n.Pointer+"/"+keyword); err != nil {
				return err
			}
		}
	}
	for _, keyword := range []string{"required", "type", "enum"} {
		if keyword == "enum" && modern {
			continue
		}
		if value, ok := m[keyword].([]any); ok {
			if err := walk(value, n.Pointer+"/"+keyword); err != nil {
				return err
			}
		}
	}
	for _, keyword := range []string{"dependencies", "dependentRequired"} {
		if keyword == "dependentRequired" && !modern {
			continue
		}
		if values, ok := m[keyword].(map[string]any); ok {
			for _, name := range sortedKeys(values) {
				if value, ok := values[name].([]any); ok {
					if err := walk(value, n.Pointer+"/"+keyword+"/"+escape(name)); err != nil {
						return err
					}
				}
			}
		}
	}
	projection := m
	if _, ref := m["$ref"]; ref && !modern {
		projection = maps.Clone(m)
		delete(projection, "$ref")
	}
	for _, pointer := range schemaChildren(projection, n.Pointer, dialect) {
		if child := r.entries[keyAt(n.Path, pointer)]; child != nil {
			if err := r.admitNumericMetaschema(child, dialect, budget, scopes); err != nil {
				return err
			}
		}
	}
	return nil
}
