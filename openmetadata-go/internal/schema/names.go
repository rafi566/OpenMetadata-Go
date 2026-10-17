// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"fmt"
	"io/fs"
	"strings"
	"unicode"
)

// GoName identifies the physical source and exact schema location, never its title.
// Normalization is deliberately followed by final collision rejection in Generate.
// ADR:2026-10-17-go-schema-reconstruction-preserves-source-semantics
func GoName(n Node) (string, error) {
	if !fs.ValidPath(n.Path) || n.Path == "." || !strings.HasSuffix(n.Path, ".json") || strings.Contains(n.Path, "\\") || n.Pointer != "" && !strings.HasPrefix(n.Pointer, "/") {
		return "", diagnostic("generate", n.Path, n.Pointer, fmt.Errorf("invalid source locator"))
	}
	name := "Model" + identifier(strings.TrimSuffix(n.Path, ".json"))
	if n.Pointer == "" {
		name += "Root"
	} else {
		name += "At" + identifier(n.Pointer)
	}
	return name + "Value", nil
}
func identifier(s string) string {
	var b strings.Builder
	upper := true
	for _, r := range s {
		if !unicode.IsLetter(r) && !unicode.IsDigit(r) {
			upper = true
			continue
		}
		if upper {
			r = unicode.ToUpper(r)
		}
		// Uncased letters are legal identifiers but do not export Go fields.
		if b.Len() == 0 && !unicode.IsUpper(r) {
			b.WriteByte('N')
		}
		b.WriteRune(r)
		upper = false
	}
	if b.Len() == 0 {
		return "Empty"
	}
	return b.String()
}

// encoding/json treats commas as options and invalid/empty names as the Go field
// name. Reject those projections rather than expose tags that rename wire keys.
func jsonFieldTagName(name string) bool {
	if name == "" {
		return false
	}
	for _, r := range name {
		if !unicode.IsLetter(r) && !unicode.IsDigit(r) && !strings.ContainsRune("!#$%&()*+-./:;<=>?@[]^_{|}~ ", r) {
			return false
		}
	}
	return true
}
