// SPDX-License-Identifier: Apache-2.0

//go:build unix

package schema

import (
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func TestRegistryRejectsFIFOWithoutOpening(t *testing.T) {
	root := fixture(t, map[string]string{"a.json": `true`})
	if err := syscall.Mkfifo(filepath.Join(root, "b.json"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadRegistry(root); err == nil || !strings.Contains(err.Error(), "nonregular") {
		t.Fatalf("nonregular input guard: %v", err)
	}
}
