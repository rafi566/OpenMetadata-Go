// SPDX-License-Identifier: Apache-2.0

package schema

import "strings"

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
