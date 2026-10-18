// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"
)

type corpusGraph struct {
	Documents  []struct{ Path, SHA256 string }
	References []struct {
		Path, Pointer, Keyword, Value string
		TargetPath                    string `json:"target_path"`
		TargetPointer                 string `json:"target_pointer"`
	}
	Nodes []struct {
		Path, Pointer string
		Types         []string
	}
	Edges      []struct{ Source, Target, Kind, Keyword string }
	Components [][]string `json:"recursive_components"`
}

func readCorpusGraph(t *testing.T) corpusGraph {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "schemas", "reference-graph.json"))
	if err != nil {
		t.Fatal(err)
	}
	var graph corpusGraph
	if err = json.Unmarshal(raw, &graph); err != nil {
		t.Fatal(err)
	}
	return graph
}

func TestFullCorpusGraph(t *testing.T) {
	graph := readCorpusGraph(t)
	r, err := LoadLegacyRegistry(corpusRoot(t))
	if err != nil {
		t.Fatal(err)
	}
	if len(graph.Documents) != 1071 || len(graph.Documents) != len(r.documents) {
		t.Fatal("document coverage", len(graph.Documents), len(r.documents))
	}
	seenDocuments := map[string]bool{}
	for _, doc := range graph.Documents {
		actual := r.documents[doc.Path]
		if actual == nil || seenDocuments[doc.Path] {
			t.Fatal("missing/duplicate document", doc.Path)
		}
		seenDocuments[doc.Path] = true
		if fmt.Sprintf("%x", sha256.Sum256(actual.Document)) != doc.SHA256 {
			t.Fatal("source drift", doc.Path)
		}
	}
	if len(graph.References) != len(r.references) {
		t.Fatal("reference coverage", len(graph.References), len(r.references))
	}
	refs := map[string]reference{}
	for _, ref := range r.references {
		refs[ref.source.Path+"#"+ref.source.Pointer+"/"+ref.keyword] = ref
	}
	for _, ref := range graph.References {
		locator := ref.Path + "#" + ref.Pointer
		actual, exists := refs[locator]
		if !exists || actual.ref != ref.Value || actual.keyword != ref.Keyword {
			t.Fatal("missing/changed reference", locator)
		}
		target, err := r.Resolve(legacyBase+ref.Path, ref.Value)
		if err != nil || target.Path != ref.TargetPath || target.Pointer != ref.TargetPointer {
			t.Fatalf("reference %s: %+v %v", locator, target, err)
		}
		delete(refs, locator)
	}
	if len(refs) != 0 {
		t.Fatal("unaccounted references", len(refs))
	}
	if len(graph.Nodes) != len(r.Nodes()) {
		t.Fatal("node coverage", len(graph.Nodes), len(r.Nodes()))
	}
	nodes, names := map[string]bool{}, map[string]string{}
	for _, node := range graph.Nodes {
		locator := node.Path + "#" + node.Pointer
		actual := r.schemas[keyAt(node.Path, node.Pointer)]
		if actual == nil || nodes[locator] {
			t.Fatal("missing/duplicate node", locator)
		}
		nodes[locator] = true
		name, err := GoName(actual.Node)
		if err != nil {
			t.Fatal(err)
		}
		if previous := names[name]; previous != "" {
			t.Fatal("model collision", previous, locator)
		}
		names[name] = locator
	}
	wantEdges := map[string]bool{}
	adjacent := map[string][]string{}
	for _, node := range r.schemas {
		locator := node.Path + "#" + node.Pointer
		value, _ := node.value.(map[string]any)
		for _, child := range schemaChildren(value, node.Pointer, r.inheritedDialect(node)) {
			target := node.Path + "#" + child
			wantEdges[locator+"\x00"+target+"\x00containment"] = true
			adjacent[locator] = append(adjacent[locator], target)
		}
	}
	for _, ref := range r.references {
		source, target := ref.source.Path+"#"+ref.source.Pointer, ref.target.Path+"#"+ref.target.Pointer
		wantEdges[source+"\x00"+target+"\x00reference"] = true
		adjacent[source] = append(adjacent[source], target)
	}
	for _, edge := range graph.Edges {
		key := edge.Source + "\x00" + edge.Target + "\x00" + edge.Kind
		if !wantEdges[key] || !nodes[edge.Source] || !nodes[edge.Target] {
			t.Fatal("unexpected/duplicate edge", edge)
		}
		delete(wantEdges, key)
	}
	if len(wantEdges) != 0 {
		t.Fatal("missing edges", len(wantEdges))
	}
	actualComponents := recursiveComponents(nodes, adjacent)
	if len(actualComponents) != 14 || !reflect.DeepEqual(actualComponents, graph.Components) {
		t.Fatalf("recursive member-set mismatch: %v", actualComponents)
	}
	for _, component := range actualComponents {
		shapes := 0
		for _, locator := range component {
			path, pointer, _ := strings.Cut(locator, "#")
			shape, err := (&modelGenerator{registry: r}).shape(r.schemas[keyAt(path, pointer)])
			if err != nil {
				t.Fatal("recursive projection blocked", locator, err)
			}
			value, _ := shape.value.(map[string]any)
			if types := projectionTypes(value); types["object"] || types["array"] {
				shapes++
			}
		}
		if shapes == 0 {
			t.Fatal("recursive component has no typed shape", component)
		}
	}
	result, err := r.Check()
	t.Logf("fresh corpus counts: %+v; recursive components=%d", result, len(actualComponents))
	if err != nil || result.Compiled != len(graph.Nodes) {
		t.Fatalf("incomplete compilation: %+v %v", result, err)
	}
}

func TestFullCorpusFixtureValidation(t *testing.T) {
	r, err := LoadLegacyRegistry(corpusRoot(t))
	if err != nil {
		t.Fatal(err)
	}
	fixtures := map[string]string{
		"create-table":     "api/data/createTable.json",
		"table":            "entity/data/table.json",
		"connection":       "entity/services/connections/database/mysqlConnection.json",
		"entity-reference": "type/entityReference.json",
		"odcs":             "entity/datacontract/odcs/odcsDataContract.json",
		"rdf":              "api/rdf/sparqlTripleTerm.json",
		"test-suite":       "tests/testSuite.json",
	}
	for _, name := range sortedKeys(fixtures) {
		t.Run(name, func(t *testing.T) {
			root := filepath.Join("..", "..", "testdata", "models")
			raw, err := os.ReadFile(filepath.Join(root, name+".json"))
			if err != nil {
				t.Fatal(err)
			}
			if err = r.Validate(legacyBase+fixtures[name], raw); err != nil {
				t.Fatal("valid fixture", err)
			}
			raw, err = os.ReadFile(filepath.Join(root, name+"-invalid.json"))
			if err != nil {
				t.Fatal(err)
			}
			var invalid []json.RawMessage
			if err = json.Unmarshal(raw, &invalid); err != nil {
				t.Fatal(err)
			}
			for _, bad := range invalid {
				if err = r.Validate(legacyBase+fixtures[name], bad); err == nil {
					t.Fatalf("invalid fixture accepted: %s", bad)
				}
			}
		})
	}
}

// Tarjan is independent of the Python producer's two-pass Kosaraju walk.
func recursiveComponents(nodes map[string]bool, edges map[string][]string) [][]string {
	next := 0
	indices, low, onStack := map[string]int{}, map[string]int{}, map[string]bool{}
	var stack []string
	var result [][]string
	var visit func(string)
	visit = func(node string) {
		next++
		indices[node] = next
		low[node] = next
		stack = append(stack, node)
		onStack[node] = true
		self := false
		for _, child := range edges[node] {
			if child == node {
				self = true
			}
			if indices[child] == 0 {
				visit(child)
				low[node] = min(low[node], low[child])
			} else if onStack[child] {
				low[node] = min(low[node], indices[child])
			}
		}
		if low[node] != indices[node] {
			return
		}
		var group []string
		for {
			last := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			onStack[last] = false
			group = append(group, last)
			if last == node {
				break
			}
		}
		if len(group) > 1 || self {
			sort.Strings(group)
			result = append(result, group)
		}
	}
	for _, node := range sortedKeys(nodes) {
		if indices[node] == 0 {
			visit(node)
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i][0] < result[j][0] })
	return result
}
