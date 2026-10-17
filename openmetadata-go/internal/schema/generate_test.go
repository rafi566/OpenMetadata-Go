// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"testing/fstest"
	"time"
)

func generationRegistry(t *testing.T, documents map[string]string) *Registry {
	t.Helper()
	files := fstest.MapFS{}
	for path, raw := range documents {
		files[path] = &fstest.MapFile{Data: []byte(raw)}
	}
	r, err := LoadEmbeddedRegistry(files, "")
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func TestGenerateNamesAndOutputSafety(t *testing.T) {
	for _, paths := range [][]string{{"foo-bar.json", "foo_bar.json"}, {"fooBar.json", "foobar.json"}, {"状态.json", "N状态.json"}} {
		t.Run(strings.Join(paths, "-"), func(t *testing.T) {
			r := generationRegistry(t, map[string]string{paths[0]: `{}`, paths[1]: `{}`})
			out := filepath.Join(t.TempDir(), "output")
			_, err := Generate(r, GenerateOptions{"fixture", out})
			if err == nil || !strings.Contains(err.Error(), paths[0]+"#") || !strings.Contains(err.Error(), paths[1]+"#") {
				t.Fatalf("collision diagnostics: %v", err)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Fatalf("preflight wrote output: %v", err)
			}
		})
	}
	for _, key := range []string{"", "a,b", "a\"b", "a\\b", "line\nb", "\ufffd", string([]byte{0xff})} {
		t.Run("tag-"+key, func(t *testing.T) {
			raw, err := json.Marshal(map[string]any{"properties": map[string]any{key: map[string]any{}}})
			if err != nil {
				t.Fatal(err)
			}
			r := generationRegistry(t, map[string]string{"tag.json": string(raw)})
			out := filepath.Join(t.TempDir(), "output")
			_, err = Generate(r, GenerateOptions{"fixture", out})
			wireKey := strings.ToValidUTF8(key, "\ufffd")
			if !errors.Is(err, ErrBlocked) || !strings.Contains(err.Error(), "tag.json#/properties/"+escape(wireKey)) {
				t.Fatalf("wire tag diagnostic: %v", err)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Fatalf("tag preflight wrote output: %v", err)
			}
		})
	}
	t.Run("symlink-ancestor", func(t *testing.T) {
		root, outside := t.TempDir(), t.TempDir()
		if err := os.Symlink(outside, filepath.Join(root, "link")); err != nil {
			t.Fatal(err)
		}
		_, err := Generate(generationRegistry(t, map[string]string{"simple.json": `{}`}), GenerateOptions{"fixture", filepath.Join(root, "link", "out")})
		if err == nil {
			t.Fatal("generation followed output ancestor symlink")
		}
		entries, e := os.ReadDir(outside)
		if e != nil || len(entries) != 0 {
			t.Fatalf("symlink target changed: %v %v", entries, e)
		}
	})
	t.Run("existing-file", func(t *testing.T) {
		out := t.TempDir()
		p := filepath.Join(out, "registry-manifest.json")
		if err := os.WriteFile(p, []byte("sentinel"), 0600); err != nil {
			t.Fatal(err)
		}
		_, err := Generate(generationRegistry(t, map[string]string{"simple.json": `{}`}), GenerateOptions{"fixture", out})
		if err == nil {
			t.Fatal("existing output accepted")
		}
		raw, _ := os.ReadFile(p)
		entries, _ := os.ReadDir(out)
		if string(raw) != "sentinel" || len(entries) != 1 {
			t.Fatalf("existing output modified: %s %v", raw, entries)
		}
	})
	t.Run("filename-limit", func(t *testing.T) {
		r := generationRegistry(t, map[string]string{strings.Repeat("a", 230) + ".json": `{}`})
		_, err := Generate(r, GenerateOptions{"fixture", filepath.Join(t.TempDir(), "out")})
		if err == nil || !strings.Contains(err.Error(), "240 bytes") {
			t.Fatalf("filename bound: %v", err)
		}
	})
	t.Run("composition-preflight", func(t *testing.T) {
		out := filepath.Join(t.TempDir(), "out")
		_, err := Generate(generationRegistry(t, map[string]string{"union.json": `{"oneOf":[{},{}]}`}), GenerateOptions{"fixture", out})
		if !errors.Is(err, ErrBlocked) || !strings.Contains(err.Error(), "union.json#/oneOf") {
			t.Fatalf("composition blocker: %v", err)
		}
		if _, err := os.Stat(out); !os.IsNotExist(err) {
			t.Fatal("composition preflight wrote files")
		}
	})
}

func independentGeneratedModule(t *testing.T, documents map[string]string, pkg, testSource string) {
	t.Helper()
	moduleRoot, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	copyFile := func(rel string) {
		t.Helper()
		b, e := os.ReadFile(filepath.Join(moduleRoot, rel))
		if e != nil {
			t.Fatal(e)
		}
		dest := filepath.Join(root, rel)
		if e = os.MkdirAll(filepath.Dir(dest), 0700); e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(dest, b, 0600); e != nil {
			t.Fatal(e)
		}
	}
	for _, rel := range []string{"go.mod", "go.sum", "schema/optional.go", "internal/schema/json.go", "internal/schema/value.go", "internal/schema/numbers.go", "internal/schema/registry.go", "internal/schema/resolve.go", "internal/schema/legacy_profile.go", "internal/schema/legacy-profile.json", "internal/schema/regexp.go", "internal/schema/validate.go", "internal/schema/numeric_admission.go", "internal/schema/embedded.go"} {
		copyFile(rel)
	}
	out := filepath.Join(root, pkg)
	paths, err := Generate(generationRegistry(t, documents), GenerateOptions{pkg, out})
	if err != nil {
		t.Fatal(err)
	}
	if !sort.StringsAreSorted(paths) {
		t.Fatal("output paths are not sorted")
	}
	if err = os.WriteFile(filepath.Join(out, "behavior_test.go"), []byte("package "+pkg+"\n"+testSource), 0600); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, "go", "test", "./...", "-count=1")
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "GOWORK=off", "GOTOOLCHAIN=local", "GOPROXY=off", "GOSUMDB=off")
	log, err := cmd.CombinedOutput()
	t.Logf("independent emitted module %s: %s", pkg, log)
	if err != nil {
		t.Fatalf("independent emitted-module tests: %v", err)
	}
}

func TestGeneratedPresenceAndFreshDecode(t *testing.T) {
	independentGeneratedModule(t, map[string]string{"presence.json": `{"type":"object","required":["required"],"properties":{"required":{"type":["string","null"]},"flag":{"type":"boolean"},"count":{"type":"integer"},"text":{"type":"string","default":"default"},"list":{"type":"array","items":{"type":"integer"}},"nullable":{"type":["string","null"]},"状态":{"type":"string"}}}`}, "schema", `
import("encoding/json";"testing")
func TestPresence(t *testing.T){
var v ModelPresenceRootValue
if e:=v.UnmarshalJSON([]byte("{}"));e==nil{t.Fatal("missing required nullable accepted")}
raw:=[]byte("{\"required\":null,\"flag\":false,\"count\":0,\"text\":\"\",\"list\":[],\"nullable\":null,\"状态\":\"kept\",\"unknown\":9007199254740993}")
if e:=v.UnmarshalJSON(raw);e!=nil{t.Fatal(e)}
raw[0]='x'
view,ok,e:=v.Object();if e!=nil||!ok{t.Fatal(e)}
if !view.Required.IsNull()||!view.Nullable.IsNull()||!view.Flag.IsSet()||!view.Count.IsSet()||!view.Text.IsSet()||!view.List.IsSet(){t.Fatal("presence lost")}
flag,_:=view.Flag.Value();if b,ok:=flag.BoolValue();!ok||b{t.Fatal("false lost")}
count,_:=view.Count.Value();if n,ok:=count.NumberValue();!ok||n.String()!="0"{t.Fatal("zero lost")}
list,_:=view.List.Value();if a,ok,e:=list.Items();e!=nil||!ok||a==nil||len(a)!=0{t.Fatal("empty array lost")}
b,e:=json.Marshal(view);if e!=nil{t.Fatal(e)};var projection map[string]json.RawMessage;if e=json.Unmarshal(b,&projection);e!=nil{t.Fatal(e)}
if string(projection["状态"])!="\"kept\""||projection["unknown"]!=nil{t.Fatalf("detached projection: %s",b)}
before,_:=v.MarshalJSON()
for _,bad:=range []string{"{}","{\"required\":null,\"count\":\"bad\"}","{\"required\":null,\"required\":null}","{} {}"}{if e:=v.UnmarshalJSON([]byte(bad));e==nil{t.Fatal("invalid decode accepted",bad)};after,_:=v.MarshalJSON();if string(after)!=string(before){t.Fatal("failed decode changed receiver")}}
copyRaw:=v.JSONValue().RawJSON();copyRaw[0]='x';after,_:=v.MarshalJSON();if string(after)!=string(before){t.Fatal("egress alias")}
if e:=v.UnmarshalJSON([]byte("{\"required\":null}"));e!=nil{t.Fatal(e)};view,_,_=v.Object();if view.Flag.IsSet()||view.Count.IsSet()||view.Text.IsSet()||view.List.IsSet()||view.Nullable.IsSet(){t.Fatal("reuse retained omissions/default")}
if e:=v.Validate();e!=nil{t.Fatal(e)}
var unset ModelPresenceRootValue;if _,e:=unset.MarshalJSON();e==nil{t.Fatal("unset serialized")}
}

`)
}

func TestGeneratedUnknownPrecisionAndMaps(t *testing.T) {
	independentGeneratedModule(t, map[string]string{
		"map.json":  `{"properties":{"declared":{"type":"string"}},"additionalProperties":{"type":["number","null"]}}`,
		"open.json": `{}`,
	}, "models", `
import("testing";support "github.com/rafi566/OpenMetadata-Go/openmetadata-go/internal/schema")
func TestMaps(t *testing.T){
var unset ModelMapRootValue
if _,_,e:=unset.AdditionalProperties();e==nil{t.Fatal("map view did not validate unset parent")}
var v ModelMapRootValue
raw:="{\"declared\":\"kept\",\"large\":9007199254740993,\"exponent\":1e999,\"null\":null}"
if e:=v.UnmarshalJSON([]byte(raw));e!=nil{t.Fatal(e)}
values,ok,e:=v.AdditionalProperties();if e!=nil||!ok||len(values)!=3||values["declared"]!=nil{t.Fatalf("map classification: %v %v %v",values,ok,e)}
if values["null"]==nil||!values["null"].JSONValue().IsNull(){t.Fatal("null map child lost")}
for key,want:=range map[string]string{"large":"9007199254740993","exponent":"1e999"}{n,ok:=values[key].NumberValue();if !ok||n.String()!=want{t.Fatal("map precision",key,n.String())}}
if e:=values["large"].UnmarshalJSON([]byte("1"));e!=nil{t.Fatal(e)};after,_:=v.MarshalJSON();if string(after)!=raw{t.Fatal("map child aliases parent")}
if e:=v.UnmarshalJSON([]byte("{\"bad\":\"string\"}"));e==nil{t.Fatal("invalid map child accepted")}
if e:=v.UnmarshalJSON([]byte("{}"));e!=nil{t.Fatal(e)};values,ok,e=v.AdditionalProperties();if e!=nil||!ok||values==nil||len(values)!=0{t.Fatal("empty object map")}
if e:=v.UnmarshalJSON([]byte("42"));e!=nil{t.Fatal(e)};values,ok,e=v.AdditionalProperties();if e!=nil||ok||values!=nil{t.Fatal("nonobject map")}
// Validate the original parent even if a same-package caller constructs a raw wrapper.
invalid,_:=support.ParseValue([]byte("{\"declared\":0}"));v.value=invalid
if _,_,e:=v.AdditionalProperties();e==nil{t.Fatal("map view ignored declared-property parent constraint")}
var open ModelOpenRootValue
for _,raw:=range []string{"{\"nested\":[9007199254740993,-0,1e999]}","[18446744073709551616]","null","true","\"text\"","1.00e2"}{if e:=open.UnmarshalJSON([]byte(raw));e!=nil{t.Fatal(e)};b,e:=open.MarshalJSON();if e!=nil||string(b)!=raw{t.Fatal("open precision",string(b),e)}}
if e:=open.UnmarshalJSON([]byte("{\"unknown\":9007199254740993}"));e!=nil{t.Fatal(e)};obj,ok:=open.JSONValue().Object();if !ok{t.Fatal("unconstrained object")};n,_:=obj["unknown"].NumberValue();if n.String()!="9007199254740993"{t.Fatal("unknown rounded")}
}
`)
}

func TestGeneratedEnumsAndReferences(t *testing.T) {
	independentGeneratedModule(t, map[string]string{
		"enum.json":          `{"type":"string","enum":["in-progress","done"]}`,
		"alias.json":         `{"$ref":"enum.json"}`,
		"array.json":         `{"type":"array","items":{"$ref":"enum.json"}}`,
		"hash#percent%.json": `{"type":"object","properties":{"key":{"type":"string"}}}`,
	}, "models", `
import "testing"
func TestReferences(t *testing.T){
var v ModelAliasRootValue
if e:=v.UnmarshalJSON([]byte("\"in-progress\""));e!=nil{t.Fatal(e)};s,ok:=v.StringValue();if !ok||s!=ModelEnumRootValueEnumInProgress{t.Fatal("enum view")};if s!=ModelAliasRootValueEnumInProgress{t.Fatal("alias enum view")}
if e:=v.UnmarshalJSON([]byte("\"invalid\""));e==nil{t.Fatal("invalid enum accepted")}
var a ModelArrayRootValue;if e:=a.UnmarshalJSON([]byte("[\"done\"]"));e!=nil{t.Fatal(e)};items,ok,e:=a.Items();if e!=nil||!ok||len(items)!=1{t.Fatal("items",e)};s,ok=items[0].StringValue();if !ok||s!=ModelEnumRootValueEnumDone{t.Fatal("reference items")}
var escaped ModelHashPercentRootValue;if e:=escaped.UnmarshalJSON([]byte("{\"key\":\"kept\"}"));e!=nil{t.Fatal(e)};view,ok,e:=escaped.Object();if e!=nil||!ok||!view.Key.IsSet(){t.Fatal("escaped physical identity",e)}
}
`)
}
