// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"encoding/json"
	"os"
	"strconv"
	"strings"
	"testing"
)

func TestFreshJavaRegexSearchParity(t *testing.T) {
	var input struct{ Patterns, Samples []string }
	raw, err := os.ReadFile("../../testdata/schemas/regex-input.json")
	if err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(raw, &input); err != nil {
		t.Fatal(err)
	}
	raw, err = os.ReadFile("../../testdata/schemas/java-regex.tsv")
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	if len(lines) != len(input.Patterns)*len(input.Samples) {
		t.Fatal("incomplete Cartesian observations")
	}
	for i, line := range lines {
		fields := strings.Split(line, "\t")
		if len(fields) != 4 {
			t.Fatal("invalid observer row", line)
		}
		pi, e1 := strconv.Atoi(fields[0])
		si, e2 := strconv.Atoi(fields[1])
		find, e3 := strconv.ParseBool(fields[2])
		_, e4 := strconv.ParseBool(fields[3])
		if e1 != nil || e2 != nil || e3 != nil || e4 != nil || pi != i/len(input.Samples) || si != i%len(input.Samples) {
			t.Fatal("unordered/malformed observer row", line)
		}
		pattern, err := legacyRegexp(input.Patterns[pi])
		if err != nil {
			t.Fatal(err)
		}
		if got := pattern.MatchString(input.Samples[si]); got != find {
			t.Errorf("pattern%d sample%d search=%v Java find=%v: %q %q", pi, si, got, find, input.Patterns[pi], input.Samples[si])
		}
	}
	t.Logf("compared%d Go searches/Java find observations; Java matches retained separately", len(lines))
}

func TestFreshReferenceTargets(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/schemas/reference-targets.json")
	if err != nil {
		t.Fatal(err)
	}
	var rows []struct {
		Path, Pointer, Value string
		TargetPath           string `json:"target_path"`
		TargetPointer        string `json:"target_pointer"`
	}
	if err = json.Unmarshal(raw, &rows); err != nil {
		t.Fatal(err)
	}
	r, err := LoadLegacyRegistry(corpusRoot(t))
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != len(r.references) {
		t.Fatal("reference inventory length differs")
	}
	for _, row := range rows {
		n, err := r.Resolve(legacyBase+row.Path, row.Value)
		if err != nil || n.Path != row.TargetPath || n.Pointer != row.TargetPointer {
			t.Fatalf("%s#%s target %+v: %v", row.Path, row.Pointer, n, err)
		}
	}
}
