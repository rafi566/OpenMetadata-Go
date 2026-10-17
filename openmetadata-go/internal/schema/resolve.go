// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"fmt"
	"net/url"
	"strings"
)

func resolveURL(base, ref string) (*url.URL, error) {
	b, e := url.Parse(base)
	if e != nil {
		return nil, e
	}
	v, e := url.Parse(ref)
	if e != nil {
		return nil, e
	}
	if !b.IsAbs() {
		return nil, fmt.Errorf("base identity must be absolute: %s", base)
	}
	u := b.ResolveReference(v)
	if u.RawQuery != "" || u.User != nil {
		return nil, fmt.Errorf("query/userinfo schema references unsupported")
	}
	return u, nil
}
func (r *Registry) resolve(base, ref string) (*entry, error) {
	if r.legacy {
		b, e := url.Parse(base)
		if e != nil {
			return nil, e
		}
		originalFragment := b.Fragment
		b.Fragment = ""
		b.RawFragment = ""
		id := b.String()
		if r.ambiguous[id] {
			return nil, fmt.Errorf("ambiguous declared alias %s", id)
		}
		if loc, ok := r.identities[id]; ok {
			base = r.documents[loc.path].physical + fragment(originalFragment)
		}
	}
	u, e := resolveURL(base, ref)
	if e != nil {
		return nil, e
	}
	full := u.String()
	if r.ambiguous[full] {
		return nil, fmt.Errorf("ambiguous declared alias %s", full)
	}
	if loc, ok := r.identities[full]; ok {
		return r.entries[keyAt(loc.path, loc.pointer)], nil
	}
	pointer := u.Fragment
	u.Fragment = ""
	u.RawFragment = ""
	id := u.String()
	if r.ambiguous[id] {
		return nil, fmt.Errorf("ambiguous declared alias %s", id)
	}
	loc, ok := r.identities[id]
	if !ok {
		return nil, fmt.Errorf("unregistered local identity %s (no network or filesystem fallback)", id)
	}
	if pointer != "" && !strings.HasPrefix(pointer, "/") {
		return nil, fmt.Errorf("unknown anchor %s", pointer)
	}
	// Reject malformed RFC6901 escapes instead of accepting an accidental key.
	for i := 0; i < len(pointer); i++ {
		if pointer[i] == '~' {
			if i+1 >= len(pointer) || (pointer[i+1] != '0' && pointer[i+1] != '1') {
				return nil, fmt.Errorf("invalid JSON pointer %s", pointer)
			}
			i++
		}
	}
	n := r.entries[keyAt(loc.path, loc.pointer+pointer)]
	if n == nil {
		return nil, fmt.Errorf("missing JSON pointer %s#%s", loc.path, loc.pointer+pointer)
	}
	return n, nil
}
func (r *Registry) Resolve(baseID, ref string) (Node, error) {
	n, e := r.resolve(baseID, ref)
	if e != nil {
		return Node{}, diagnostic("resolve", baseID, "", e)
	}
	return copyNode(n), nil
}
func splitPointer(p string) []string {
	parts := strings.Split(strings.TrimPrefix(p, "/"), "/")
	for i, s := range parts {
		parts[i] = strings.ReplaceAll(strings.ReplaceAll(s, "~1", "/"), "~0", "~")
	}
	return parts
}
