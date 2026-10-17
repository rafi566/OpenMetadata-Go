// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"fmt"
	"strings"
)

// A modern reference does not replace its siblings. Project a local shape when
// present, leaving the original wrapper's validation to enforce both schemas.
func localProjection(m map[string]any) bool {
	for _, keyword := range []string{"type", "properties", "additionalProperties", "items", "enum", "oneOf", "anyOf", "allOf"} {
		if _, present := m[keyword]; present {
			return true
		}
	}
	return false
}

func projectionTypes(m map[string]any) map[string]bool {
	types := map[string]bool{}
	if name, ok := m["type"].(string); ok {
		types[name] = true
	}
	if names, ok := m["type"].([]any); ok {
		for _, item := range names {
			if name, ok := item.(string); ok {
				types[name] = true
			}
		}
	}
	return types
}

// A homogeneous Items view cannot apply a tail schema to tuple prefixes.
// Heterogeneous arrays retain their positional values through JSONValue.Array.
func hasTuplePrefix(m map[string]any, dialect string) bool {
	if strings.Contains(dialect, "draft-07") || strings.Contains(dialect, "2019-09") {
		_, tuple := m["items"].([]any)
		return tuple
	}
	prefix, _ := m["prefixItems"].([]any)
	return len(prefix) > 0
}

func (g *modelGenerator) mapPatterns(n *entry) ([]string, error) {
	m, _ := n.value.(map[string]any)
	patterns, _ := m["patternProperties"].(map[string]any)
	keys := sortedKeys(patterns)
	for _, pattern := range keys {
		pointer := n.Pointer + "/patternProperties/" + escape(pattern)
		// The emitted matcher uses the admitted generic engine without rewriting
		// patterns. A source-bound Java engine needs its own exact projection;
		// neither a matching spelling nor Go compilation establishes equivalence.
		legacy := g.registry.patternEligible(n, pointer, pattern)
		if g.registry.legacy {
			for _, source := range g.registry.schemas {
				schema, _ := source.value.(map[string]any)
				if schema["pattern"] == pattern && g.registry.patternEligible(source, source.Pointer+"/pattern", pattern) {
					legacy = true
				}
			}
		}
		if legacy {
			return nil, diagnostic("generate", n.Path, pointer, fmt.Errorf("%w: source-bound pattern classification is unsupported", ErrBlocked))
		}
		if _, err := genericRegexp(pattern); err != nil {
			return nil, diagnostic("generate", n.Path, pointer, err)
		}
	}
	return keys, nil
}
