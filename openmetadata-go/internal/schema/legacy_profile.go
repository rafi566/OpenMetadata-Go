// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"crypto/sha256"
	_ "embed"
	"encoding/json"
	"fmt"
	"strings"
)

// ADR:2026-10-17-go-schema-reconstruction-preserves-source-semantics
const legacyBase = "https://open-metadata.org/schema/"
const LegacyProfile = "openmetadata-2f0d4a4a"

//go:embed legacy-profile.json
var legacyPolicyJSON []byte

type policyDocument struct{ Path, SHA256, ID, Physical, Dialect string }
type policyPattern struct{ Path, Pointer, SHA256, Value string }
type legacyPolicy struct {
	Baseline       string
	ManifestSHA256 string `json:"manifest_sha256"`
	Documents      []policyDocument
	Patterns       []policyPattern
	JavaWordRanges [][2]rune `json:"java_word_ranges"`
}

var pinnedPolicy = parsePolicy()

func readPolicy() legacyPolicy { return pinnedPolicy }
func parsePolicy() legacyPolicy {
	var p legacyPolicy
	if e := json.Unmarshal(legacyPolicyJSON, &p); e != nil {
		panic("invalid embedded legacy policy: " + e.Error())
	}
	return p
}
func LoadLegacyRegistry(root string) (*Registry, error) { return loadRegistry(root, true) }
func (r *Registry) checkLegacy() error {
	policy := readPolicy()
	expectedPaths := map[string]bool{}
	for _, d := range policy.Documents {
		expectedPaths[d.Path] = true
	}
	for _, path := range sortedKeys(r.documents) {
		if !expectedPaths[path] {
			return diagnostic("load", path, "", fmt.Errorf("document not in pinned legacy profile"))
		}
	}
	var manifest strings.Builder
	for _, expected := range policy.Documents {
		actual := r.documents[expected.Path]
		if actual == nil {
			return diagnostic("load", expected.Path, "", fmt.Errorf("pinned document missing"))
		}
		hash := fmt.Sprintf("%x", sha256.Sum256(actual.Document))
		if hash != expected.SHA256 {
			return diagnostic("load", expected.Path, "", fmt.Errorf("legacy raw SHA256 differs: %s", hash))
		}
		m, ok := actual.value.(map[string]any)
		if !ok || m["$id"] != expected.ID || m["$schema"] != expected.Dialect || actual.physical != expected.Physical {
			return diagnostic("load", expected.Path, "", fmt.Errorf("legacy source metadata differs"))
		}
		fmt.Fprintf(&manifest, "%s  %s\n", hash, expected.Path)
	}
	if fmt.Sprintf("%x", sha256.Sum256([]byte(manifest.String()))) != policy.ManifestSHA256 {
		return diagnostic("load", r.root, "", fmt.Errorf("legacy raw manifest differs"))
	}
	return nil
}
func (r *Registry) addLegacyAliases() {
	aliases := map[string][]string{}
	for _, p := range sortedKeys(r.documents) {
		if id, ok := r.documents[p].value.(map[string]any)["$id"].(string); ok {
			aliases[id] = append(aliases[id], p)
		}
	}
	for _, id := range sortedKeys(aliases) {
		paths := aliases[id]
		if _, physical := r.identities[id]; physical {
			continue
		}
		if len(paths) == 1 {
			r.identities[id] = resource{paths[0], ""}
		} else {
			r.ambiguous[id] = true
		}
	}
}
func (r *Registry) patternEligible(n *entry, pointer, pattern string) bool {
	if !r.legacy {
		return false
	}
	hash := fmt.Sprintf("%x", sha256.Sum256(r.documents[n.Path].Document))
	for _, p := range readPolicy().Patterns {
		if p.Path == n.Path && p.Pointer == pointer && p.SHA256 == hash && p.Value == pattern {
			return true
		}
	}
	return false
}
