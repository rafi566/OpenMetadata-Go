// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
)

// Raw Number ownership is independent of this dependency arithmetic boundary.
// ADR:2026-10-17-go-schema-reconstruction-preserves-source-semantics
type numericBudget struct{ cost int }

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
		if err := b.number(string(value)); err != nil {
			return pointer, err
		}
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
	for _, key := range sortedKeys(r.schemas) {
		node := r.schemas[key]
		if !documents[node.Path] {
			continue
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
