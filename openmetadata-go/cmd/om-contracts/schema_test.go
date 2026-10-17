// SPDX-License-Identifier: Apache-2.0

package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	schema "github.com/rafi566/OpenMetadata-Go/openmetadata-go/internal/schema"
)

func schemaRoot(t *testing.T, docs map[string]string) string {
	t.Helper()
	root := t.TempDir()
	for path, raw := range docs {
		p := filepath.Join(root, path)
		if err := os.MkdirAll(filepath.Dir(p), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(raw), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return root
}

func TestSchemaUsageAndProfiles(t *testing.T) {
	root := schemaRoot(t, map[string]string{"ok.json": `{}`})
	for _, args := range [][]string{nil, {"schema"}, {"contracts"}, {"dev"}, {"schema", "other"}, {"schema", "check"}, {"schema", "check", "--root", root, "extra"}, {"schema", "check", "--root", root, "--profile", "unknown"}, {"schema", "check", "--root", root, "--profile", schema.LegacyProfile}, {"schema", "check", "--unknown"}, {"schema", "generate", "--root", root}} {
		var stdout, stderr bytes.Buffer
		if code := run(args, &stdout, &stderr); code != 1 || stderr.Len() == 0 {
			t.Fatalf("args=%v code=%d stdout=%q stderr=%q", args, code, stdout.String(), stderr.String())
		}
	}
	var out, err bytes.Buffer
	if code := run([]string{"schema", "check", "--root", root}, &out, &err); code != 0 {
		t.Fatalf("generic check: %d %s", code, err.String())
	}
	if strings.Contains(out.String(), "profile") {
		t.Fatal("implicit legacy profile")
	}
}

func TestSchemaCheckDiagnosticsAndPartialCounts(t *testing.T) {
	for _, tc := range []struct {
		name           string
		docs           map[string]string
		code, compiled int
		diagnostic     string
	}{
		{"valid", map[string]string{"ok.json": `{"type":"string"}`}, 0, 1, ""},
		{"invalid", map[string]string{"bad.json": `{"type":42}`}, 1, 0, "bad.json#/type"},
		{"blocked", map[string]string{"blocked.json": `{"minimum":1e10001}`}, 2, 0, "blocked.json#/minimum"},
		{"mixed", map[string]string{"bad.json": `{"type":42}`, "blocked.json": `{"minimum":1e10001}`, "good.json": `{"type":"string"}`}, 2, 1, "blocked.json#/minimum"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var out, err bytes.Buffer
			code := schemaCommand([]string{"check", "--root", schemaRoot(t, tc.docs)}, &out, &err)
			if code != tc.code {
				t.Fatalf("code %d != %d: %s", code, tc.code, err.String())
			}
			var result schema.CheckResult
			if e := json.NewDecoder(&out).Decode(&result); e != nil {
				t.Fatal(e)
			}
			if result.Documents != len(tc.docs) || result.Nodes != len(tc.docs) || result.Compiled != tc.compiled {
				t.Fatalf("partial counts: %+v", result)
			}
			if tc.diagnostic != "" && !strings.Contains(err.String(), tc.diagnostic) {
				t.Fatalf("diagnostic: %s", err.String())
			}
			if code != 0 && strings.Contains(out.String(), "all-node") {
				t.Fatal("partial check claimed completion")
			}
		})
	}
}

type failWriter struct{ remaining int }

func (w *failWriter) Write(p []byte) (int, error) {
	if len(p) <= w.remaining {
		w.remaining -= len(p)
		return len(p), nil
	}
	n := w.remaining
	w.remaining = 0
	return n, errors.New("stream failed")
}

func TestSchemaStreamFailures(t *testing.T) {
	root := schemaRoot(t, map[string]string{"ok.json": `{}`})
	counts, _ := json.Marshal(schema.CheckResult{Documents: 1, Nodes: 1, Compiled: 1})
	for _, limit := range []int{0, len(counts) + 1} {
		var err bytes.Buffer
		if code := schemaCommand([]string{"check", "--root", root}, &failWriter{limit}, &err); code != 1 {
			t.Fatalf("stream failure limit%d returned%d", limit, code)
		}
	}
}

func TestSchemaGenerateOutput(t *testing.T) {
	root := schemaRoot(t, map[string]string{"item.json": `{"type":"string"}`})
	out := filepath.Join(t.TempDir(), "models")
	var stdout, stderr bytes.Buffer
	args := []string{"generate", "--root", root, "--output", out, "--package", "models"}
	if code := schemaCommand(args, &stdout, &stderr); code != 0 {
		t.Fatalf("generate: %d %s", code, stderr.String())
	}
	var paths []string
	if err := json.Unmarshal(stdout.Bytes(), &paths); err != nil {
		t.Fatal(err)
	}
	if len(paths) != 5 || !sort.StringsAreSorted(paths) {
		t.Fatalf("generated paths: %v", paths)
	}
	for _, path := range paths {
		if _, err := os.Stat(filepath.Join(out, path)); err != nil {
			t.Fatal(err)
		}
	}
	before, err := os.ReadFile(filepath.Join(out, "model-index.json"))
	if err != nil {
		t.Fatal(err)
	}
	if code := schemaCommand(args, io.Discard, &stderr); code != 1 {
		t.Fatalf("overwrite returned%d", code)
	}
	after, _ := os.ReadFile(filepath.Join(out, "model-index.json"))
	if !bytes.Equal(before, after) {
		t.Fatal("CLI overwrote existing artifact")
	}
	blocked := schemaRoot(t, map[string]string{"union.json": `{"oneOf":[{},{}]}`})
	out = filepath.Join(t.TempDir(), "blocked")
	if code := schemaCommand([]string{"generate", "--root", blocked, "--output", out, "--package", "models"}, io.Discard, &stderr); code != 2 {
		t.Fatalf("generation blocker returned%d: %s", code, stderr.String())
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Fatal("blocked CLI wrote output")
	}
	out = filepath.Join(t.TempDir(), "stream")
	if code := schemaCommand([]string{"generate", "--root", root, "--output", out, "--package", "models"}, &failWriter{}, &stderr); code != 1 {
		t.Fatalf("generation stream failure returned%d", code)
	}
}
