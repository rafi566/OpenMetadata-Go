// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"bytes"
	"fmt"
	"io"
	"strconv"
	"sync"
	"unicode/utf8"
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
	t.Run("dynamic-preflight", func(t *testing.T) {
		out := filepath.Join(t.TempDir(), "out")
		_, err := Generate(generationRegistry(t, map[string]string{"dynamic.json": `{"$dynamicRef":"#"}`}), GenerateOptions{"fixture", out})
		if !errors.Is(err, ErrBlocked) || !strings.Contains(err.Error(), "dynamic.json#/$dynamicRef") {
			t.Fatalf("dynamic blocker: %v", err)
		}
		if _, err := os.Stat(out); !os.IsNotExist(err) {
			t.Fatal("dynamic preflight wrote files")
		}
	})
}

func independentGeneratedModule(t *testing.T, documents map[string]string, pkg, testSource string) {
	t.Helper()
	control := configuredGeneratedControl(t)
	moduleRoot, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	if retained := os.Getenv("OM_GENERATED_EVIDENCE_DIR"); retained != "" {
		root, err = os.MkdirTemp(retained, "emitted-")
		if err != nil {
			t.Fatal(err)
		}
		t.Logf("retained independent module: %s", root)
	}
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
	if control != nil {
		control.run(t, root, paths)
		return
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

// The unconfigured branch above deliberately keeps its original direct command.
type generatedBuildControl struct { launcher, jobID string }
type generatedBuildPin struct {
	Path string `json:"path"`
	Bytes int64 `json:"bytes"`
	SHA256 string `json:"sha256"`
	Mode int `json:"mode"`
}
type generatedBuildReply struct {
	Format string `json:"format"`
	JobID string `json:"job_id"`
	DriverID string `json:"driver_id"`
	Phase string `json:"phase"`
	Status string `json:"status"`
	Receipt *generatedBuildPin `json:"receipt"`
	Error *string `json:"error"`
}

func generatedBuildID(value string) bool {
	if len(value) < 1 || len(value) > 64 { return false }
	for _, c := range value {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '-') { return false }
	}
	return true
}
func generatedBuildSHA(value string) bool {
	if len(value) != 64 { return false }
	for _, c := range value { if !(c >= 'a' && c <= 'f' || c >= '0' && c <= '9') { return false } }
	return true
}
func generatedBuildPath(value string) bool {
	if !utf8.ValidString(value) || !filepath.IsAbs(value) || filepath.Clean(value) != value || strings.ContainsAny(value, "\\\x00") { return false }
	for _, part := range strings.Split(strings.TrimPrefix(value, "/"), "/") { if part == "" || len(part) > 240 { return false } }
	return true
}
func configuredGeneratedControl(t *testing.T) *generatedBuildControl {
	t.Helper()
	launcher, hasLauncher := os.LookupEnv("OM_BUILD_LAUNCHER")
	job, hasJob := os.LookupEnv("OM_BUILD_JOB_ID")
	if !hasLauncher && !hasJob { return nil }
	if !hasLauncher || !hasJob || !generatedBuildPath(launcher) || !generatedBuildID(job) ||
		!generatedBuildPath(os.Getenv("OM_GENERATED_EVIDENCE_DIR")) ||
		!generatedBuildPath(os.Getenv("OM_GO_SUPERVISION_CONTEXT")) ||
		!generatedBuildSHA(os.Getenv("OM_GO_SUPERVISION_CONTEXT_SHA256")) {
		t.Fatal("invalid configured build supervision environment")
	}
	return &generatedBuildControl{launcher: launcher, jobID: job}
}

// Both copier goroutines share one bound; overflow cancels the actual launcher.
type generatedControlOutput struct {
	mu sync.Mutex
	stdout, stderr bytes.Buffer
	size int
	overflow bool
	cancel context.CancelFunc
}
type generatedControlWriter struct { output *generatedControlOutput; stderr bool }
func (w generatedControlWriter) Write(p []byte) (int, error) {
	w.output.mu.Lock()
	n := len(p)
	if n > 4096-w.output.size { n = 4096-w.output.size }
	if w.stderr { _, _ = w.output.stderr.Write(p[:n]) } else { _, _ = w.output.stdout.Write(p[:n]) }
	w.output.size += n
	overflow := n != len(p)
	if overflow { w.output.overflow = true }
	w.output.mu.Unlock()
	if overflow { w.output.cancel(); return n, io.ErrShortWrite }
	return n, nil
}

// encoding/json otherwise replaces invalid UTF-8/unpaired escaped surrogates.
func generatedStrictStrings(raw []byte) error {
	if !utf8.Valid(raw) { return errors.New("invalid control UTF-8") }
	for i := 0; i < len(raw); i++ {
		if raw[i] != '"' { continue }
		i++
		for ; i < len(raw) && raw[i] != '"'; i++ {
			if raw[i] != '\\' { continue }
			i++
			if i >= len(raw) { return errors.New("truncated control escape") }
			if raw[i] != 'u' { continue }
			if i+5 > len(raw) { return errors.New("truncated control Unicode escape") }
			value, err := strconv.ParseUint(string(raw[i+1:i+5]), 16, 16)
			if err != nil { return err }
			if value >= 0xD800 && value <= 0xDBFF {
				if i+11 > len(raw) || raw[i+5] != '\\' || raw[i+6] != 'u' { return errors.New("unpaired control surrogate") }
				low, e := strconv.ParseUint(string(raw[i+7:i+11]), 16, 16)
				if e != nil || low < 0xDC00 || low > 0xDFFF { return errors.New("invalid control surrogate pair") }
				i += 10
			} else {
				if value >= 0xDC00 && value <= 0xDFFF { return errors.New("unpaired control surrogate") }
				i += 4
			}
		}
		if i >= len(raw) { return errors.New("truncated control string") }
	}
	return nil
}
func generatedStrictReply(raw []byte) (generatedBuildReply, error) {
	var reply generatedBuildReply
	if len(raw) > 4096 { return reply, errors.New("control response overflow") }
	if err := generatedStrictStrings(raw); err != nil { return reply, err }
	decoder := json.NewDecoder(bytes.NewReader(raw)); decoder.UseNumber()
	var inspect func(int) error
	inspect = func(depth int) error {
		if depth > 16 { return errors.New("control response depth") }
		token, err := decoder.Token(); if err != nil { return err }
		if delim, ok := token.(json.Delim); ok {
			if delim != '{' { return errors.New("unexpected control JSON container") }
			seen := map[string]bool{}
			for decoder.More() {
				key, e := decoder.Token(); if e != nil { return e }
				name, ok := key.(string); if !ok || seen[name] { return errors.New("duplicate control key") }
				seen[name] = true
				if len(seen) > 7 { return errors.New("control object bound") }
				if err := inspect(depth+1); err != nil { return err }
			}
			end, e := decoder.Token(); if e != nil { return e }; if end != json.Delim('}') { return errors.New("control JSON close") }
		}
		return nil
	}
	if err := inspect(0); err != nil { return reply, err }
	if _, err := decoder.Token(); err != io.EOF { return reply, errors.New("extra control JSON") }
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil || len(fields) != 7 { return reply, errors.New("control response fields") }
	for _, key := range []string{"format", "job_id", "driver_id", "phase", "status", "receipt", "error"} {
		if _, ok := fields[key]; !ok { return reply, errors.New("noncanonical control response key") }
	}
	decoder = json.NewDecoder(bytes.NewReader(raw)); decoder.DisallowUnknownFields()
	if err := decoder.Decode(&reply); err != nil { return reply, err }
	if reply.Format != "om-driver-control-v1" || !generatedBuildID(reply.JobID) || !generatedBuildID(reply.DriverID) ||
		(reply.Phase != "freeze" && reply.Phase != "run" && reply.Phase != "post") || (reply.Status != "PASS" && reply.Status != "FAIL") {
		return reply, errors.New("control response values")
	}
	if reply.Error != nil && (len(*reply.Error) > 256 || strings.ContainsRune(*reply.Error, 0)) { return reply, errors.New("control diagnostic bound") }
	if reply.Receipt != nil {
		var pinFields map[string]json.RawMessage
		if err := json.Unmarshal(fields["receipt"], &pinFields); err != nil || len(pinFields) != 4 { return reply, errors.New("control receipt fields") }
		for _, key := range []string{"path", "bytes", "sha256", "mode"} {
			if _, ok := pinFields[key]; !ok { return reply, errors.New("noncanonical control receipt key") }
		}
		if bytes.Equal(bytes.TrimSpace(pinFields["bytes"]), []byte("null")) || bytes.Equal(bytes.TrimSpace(pinFields["mode"]), []byte("null")) { return reply, errors.New("null control receipt number") }
		p := reply.Receipt
		if !generatedBuildPath(p.Path) || p.Bytes < 0 || p.Bytes > 16777216 || !generatedBuildSHA(p.SHA256) || p.Mode != 0600 { return reply, errors.New("control receipt values") }
	}
	if reply.Status != "PASS" || reply.Error != nil || reply.Receipt == nil { return reply, errors.New("control phase refused") }
	return reply, nil
}
func (c *generatedBuildControl) call(parent context.Context, mode, driver string, request any) (generatedBuildReply, error) {
	var reply generatedBuildReply
	raw, err := json.Marshal(request)
	if err != nil || len(raw) > 16777216 { return reply, errors.New("control request bound") }
	ctx, cancel := context.WithCancel(parent); defer cancel()
	output := &generatedControlOutput{cancel: cancel}
	cmd := exec.CommandContext(ctx, c.launcher, mode)
	cmd.Stdin = bytes.NewReader(raw)
	cmd.Stdout = generatedControlWriter{output: output}
	cmd.Stderr = generatedControlWriter{output: output, stderr: true}
	cmd.WaitDelay = time.Second
	err = cmd.Run()
	output.mu.Lock()
	stdout := append([]byte(nil), output.stdout.Bytes()...)
	stderr := append([]byte(nil), output.stderr.Bytes()...)
	overflow := output.overflow
	output.mu.Unlock()
	if err != nil || overflow { return reply, fmt.Errorf("control %s failed: %v (stdout=%q stderr=%q)", mode, err, stdout, stderr) }
	reply, err = generatedStrictReply(stdout)
	if err != nil { return reply, err }
	if reply.JobID != c.jobID || reply.Phase != mode || (driver != "" && reply.DriverID != driver) { return reply, errors.New("control response binding") }
	return reply, nil
}
func (c *generatedBuildControl) run(t *testing.T, root string, paths []string) {
	t.Helper()
	pre, preCancel := context.WithTimeout(context.Background(), 10*time.Second)
	freeze, err := c.call(pre, "freeze", "", map[string]any{"format":"om-fixture-freeze-v1", "job_id":c.jobID,
		"test_name":t.Name(), "root":root, "generated_paths":paths})
	preCancel()
	if err != nil { t.Fatalf("independent fixture freeze: %v", err) }
	run, runCancel := context.WithTimeout(context.Background(), time.Minute)
	_, runErr := c.call(run, "run", freeze.DriverID, map[string]any{"format":"om-fixture-run-v1", "job_id":c.jobID, "driver_id":freeze.DriverID})
	runCancel()
	post, postCancel := context.WithTimeout(context.Background(), 10*time.Second)
	_, postErr := c.call(post, "post", freeze.DriverID, map[string]any{"format":"om-fixture-post-v1", "job_id":c.jobID, "driver_id":freeze.DriverID})
	postCancel()
	if runErr != nil { t.Fatalf("independent fixture run: %v (post=%v)", runErr, postErr) }
	if postErr != nil { t.Fatalf("independent fixture post: %v", postErr) }
}

// These source-controlled cases run only in the separately released Go checks.
func TestGeneratedBuildControlReplyContract(t *testing.T) {
	good := `{"format":"om-driver-control-v1","job_id":"job","driver_id":"fix","phase":"post","status":"PASS","receipt":{"path":"/tmp/receipt.json","bytes":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","mode":384},"error":null}`
	if _, err := generatedStrictReply([]byte(good)); err != nil { t.Fatal(err) }
	bad := map[string]string{
		"format-case": strings.Replace(good, `"format":`, `"Format":`, 1),
		"status-case": strings.Replace(good, `"status":`, `"STATUS":`, 1),
		"bytes-case": strings.Replace(good, `"bytes":`, `"Bytes":`, 1),
		"null-bytes": strings.Replace(good, `"bytes":0`, `"bytes":null`, 1),
		"null-mode": strings.Replace(good, `"mode":384`, `"mode":null`, 1),
		"duplicate": strings.Replace(good, `"format":`, `"format":"om-driver-control-v1","format":`, 1),
		"trailing": good+`{}`,
		"unpaired-surrogate": strings.Replace(good, `/tmp/receipt.json`, `/tmp/\ud800`, 1),
	}
	for name, raw := range bad { t.Run(name, func(t *testing.T) { if _, err := generatedStrictReply([]byte(raw)); err == nil { t.Fatal("invalid control reply accepted") } }) }
	paired := strings.Replace(good, `/tmp/receipt.json`, `/tmp/\ud800\udc00`, 1)
	if _, err := generatedStrictReply([]byte(paired)); err != nil { t.Fatal(err) }
}
