// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"fmt"
	"path/filepath"
	"testing"
)

func TestCompositionViews(t *testing.T) {
	for _, keyword := range []string{"oneOf", "anyOf", "allOf"} {
		t.Run(keyword, func(t *testing.T) {
			_, err := Generate(generationRegistry(t, map[string]string{"composition.json": `{"` + keyword + `":[{"type":"number"},{"type":"integer"}]}`}), GenerateOptions{"models", filepath.Join(t.TempDir(), "models")})
			if err != nil {
				t.Fatal(err)
			}
		})
	}
	independentGeneratedModule(t, map[string]string{
		"choice.json":  `{"oneOf":[{"type":"number"},{"type":"integer"},{"type":"string"}]}`,
		"overlap.json": `{"anyOf":[{"type":"object","required":["a"],"properties":{"a":{"type":"integer"}}},{"type":"object","required":["b"],"properties":{"b":{"type":"string"}}}]}`,
		"both.json":    `{"allOf":[{"type":"integer","minimum":2},{"maximum":4}]}`,
	}, "models", `
import("testing";"errors"; support "github.com/rafi566/OpenMetadata-Go/openmetadata-go/internal/schema")
func TestBranches(t *testing.T){
var one ModelChoiceRootValue
for _,bad:=range []string{"true","2"}{if e:=one.UnmarshalJSON([]byte(bad));e==nil{t.Fatal("oneOf accepted zero/two matches",bad)}}
if e:=one.UnmarshalJSON([]byte("2.5"));e!=nil{t.Fatal(e)}
b,ok,e:=one.AsOneOf0();if e!=nil||!ok||b==nil{t.Fatal("matching branch",e)};n,_:=b.NumberValue();if n.String()!="2.5"{t.Fatal("branch number")}
if b,ok,e:=one.AsOneOf1();e!=nil||ok||b!=nil{t.Fatal("nonmatching branch",e)}
if e:=b.UnmarshalJSON([]byte("3.5"));e!=nil{t.Fatal(e)};raw,_:=one.MarshalJSON();if string(raw)!="2.5"{t.Fatal("branch changed parent")}
before:=string(raw);if e:=one.UnmarshalJSON([]byte("2"));e==nil{t.Fatal("invalid reuse")};raw,_=one.MarshalJSON();if string(raw)!=before{t.Fatal("transactional decode")}
invalid,_:=support.ParseValue([]byte("2"));one.value=invalid
if _,_,e:=one.AsOneOf0();e==nil{t.Fatal("branch skipped parent validation")}
var any ModelOverlapRootValue
input:="{\"a\":9007199254740993,\"b\":\"yes\",\"unknown\":[null,-0,1e99]}"
if e:=any.UnmarshalJSON([]byte(input));e!=nil{t.Fatal(e)}
first,ok,e:=any.AsAnyOf0();if e!=nil||!ok{t.Fatal("first overlap",e)};second,ok,e:=any.AsAnyOf1();if e!=nil||!ok{t.Fatal("second overlap",e)}
v,ok,e:=first.Object();if e!=nil||!ok{t.Fatal(e)};a,_:=v.A.Value();n,_=a.NumberValue();if n.String()!="9007199254740993"{t.Fatal("precision")}
if e:=second.UnmarshalJSON([]byte("{\"b\":\"changed\"}"));e!=nil{t.Fatal(e)};raw,_=any.MarshalJSON();if string(raw)!=input{t.Fatal("overlap raw ownership")}
var both ModelBothRootValue
for _,bad:=range []string{"1","5","2.5"}{if e:=both.UnmarshalJSON([]byte(bad));e==nil{t.Fatal("allOf accepted",bad)}}
if e:=both.UnmarshalJSON([]byte("3"));e!=nil{t.Fatal(e)}
if _,ok,e:=both.AsAllOf0();e!=nil||!ok{t.Fatal(e)};if _,ok,e:=both.AsAllOf1();e!=nil||!ok{t.Fatal(e)}
value,_:=support.ParseValue([]byte("1e10001"));if _,ok,e:=modelBranch("file:///__openmetadata_embedded__/both.json#/allOf/0",value);!errors.Is(e,support.ErrBlocked)||ok{t.Fatal("numeric blocker swallowed",e)}
value,_=support.ParseValue([]byte("3"));if _,ok,e:=modelBranch("file:///__openmetadata_embedded__/missing.json",value);e==nil||ok{t.Fatal("load failure swallowed",e)}
if _,ok,e:=modelBranch("file:///__openmetadata_embedded__/both.json",support.Value{});e==nil||ok{t.Fatal("unset swallowed",e)}
}
`)
}

func TestCompositionDraftSemantics(t *testing.T) {
	cases := []struct {
		name, schema   string
		valid, invalid []string
		views          string
	}{
		{"if", `{"if":{"type":"string"}}`, []string{`1`, `"a"`}, nil, ""},
		{"then", `{"then":false}`, []string{`1`, `null`}, nil, ""},
		{"else", `{"else":false}`, []string{`1`, `null`}, nil, ""},
		{"conditional", `{"if":{"type":"string"},"then":{"minLength":2},"else":{"type":"number","minimum":5}}`, []string{`"ab"`, `5`}, []string{`"a"`, `4`, `false`}, ""},
		{"not", `{"not":{"type":"string"}}`, []string{`1`, `null`}, []string{`"a"`}, ""},
		{"ref-pattern", `{"$ref":"#/$defs/value","pattern":"a","$defs":{"value":{"type":"string"}}}`, []string{`"cat"`}, []string{`"dog"`, `1`}, `if s,ok:=v.StringValue();!ok||s!="cat"{t.Fatal("reference string view")}`},
		{"dependentSchemas", `{"type":"object","dependentSchemas":{"a":{"required":["b"],"properties":{"b":{"type":"integer"}}}}}`, []string{`{}`, `{"a":true,"b":1}`}, []string{`{"a":true}`, `{"a":true,"b":"x"}`}, ""},
		{"types", `{"type":["string","number","boolean","object","array","null"],"properties":{"a":{"type":"integer"}},"items":{"type":"integer"}}`, []string{`"text"`, `9007199254740993`, `true`, `null`, `{"a":1}`, `[1,2]`}, []string{`{"a":"bad"}`, `["bad"]`}, `
if e:=v.UnmarshalJSON([]byte("\"text\""));e!=nil{t.Fatal(e)};if s,ok:=v.StringValue();!ok||s!="text"{t.Fatal("string type view")}
if e:=v.UnmarshalJSON([]byte("true"));e!=nil{t.Fatal(e)};if b,ok:=v.BoolValue();!ok||!b{t.Fatal("boolean type view")}
if e:=v.UnmarshalJSON([]byte("9007199254740993"));e!=nil{t.Fatal(e)};if n,ok:=v.NumberValue();!ok||n.String()!="9007199254740993"{t.Fatal("number type view")}
if e:=v.UnmarshalJSON([]byte("[1,2]"));e!=nil{t.Fatal(e)};if a,ok,e:=v.Items();e!=nil||!ok||len(a)!=2{t.Fatal("array type view",e)}
`},
		{"ref-siblings", `{"$defs":{"base":{"type":"object","required":["base"]}},"$ref":"#/$defs/base","type":"object","properties":{"local":{"type":"integer"}},"required":["local"]}`, []string{`{"base":true,"local":1}`}, []string{`{"base":true}`, `{"local":1}`, `{"base":true,"local":"x"}`}, `view,ok,e:=v.Object();if e!=nil||!ok||!view.Local.IsSet(){t.Fatal("reference sibling shape",e)}`},
		{"ref-composition", `{"$defs":{"base":{"type":"integer"}},"$ref":"#/$defs/base","anyOf":[{"minimum":2},{"maximum":0}]}`, []string{`3`, `-1`}, []string{`1`, `"x"`}, `if e:=v.UnmarshalJSON([]byte("3"));e!=nil{t.Fatal(e)};for method,want:=range map[string]bool{"AsAnyOf0":true,"AsAnyOf1":false}{m:=reflect.ValueOf(v).MethodByName(method);if !m.IsValid(){t.Fatal("missing reference sibling branch",method)};out:=m.Call(nil);if out[1].Bool()!=want||!out[2].IsNil(){t.Fatal("reference sibling branch match",method)}}`},
		{"tuple-seven", `{"$schema":"http://json-schema.org/draft-07/schema#","type":"array","items":[{"type":"string"},{"type":"integer"}],"additionalItems":false}`, []string{`[]`, `["a",1]`}, []string{`[1]`, `["a","b"]`, `["a",1,2]`}, ""},
		{"tuple-nineteen", `{"$schema":"https://json-schema.org/draft/2019-09/schema","type":"array","items":[{"type":"string"}],"additionalItems":{"type":"integer"}}`, []string{`["a",1]`}, []string{`["a","b"]`}, ""},
		{"prefixItems", `{"type":"array","prefixItems":[{"type":"string"}],"items":{"type":"integer"}}`, []string{`["a",1]`, `[]`}, []string{`[1]`, `["a","b"]`}, `if e:=v.UnmarshalJSON([]byte("[\"a\",1]"));e!=nil{t.Fatal(e)};a,ok:=v.JSONValue().Array();if !ok||len(a)!=2{t.Fatal("tuple raw view")}`},
		{"contains", `{"type":"array","contains":{"type":"integer"},"minContains":2,"maxContains":2}`, []string{`[1,"a",2]`}, []string{`[1]`, `[1,2,3]`}, ""},
		{"unevaluatedProperties", `{"type":"object","anyOf":[{"properties":{"a":{"type":"integer"}}},{"properties":{"b":{"type":"string"}}}],"unevaluatedProperties":false}`, []string{`{"a":1,"b":"x"}`}, []string{`{"a":1,"extra":true}`}, ""},
		{"unevaluatedItems", `{"type":"array","unevaluatedItems":false}`, []string{`[]`}, []string{`[1]`}, ""},
		{"unevaluatedItems-combined", `{"type":"array","prefixItems":[{"type":"string"}],"contains":{"type":"integer"},"unevaluatedItems":false}`, []string{`["a",1,2]`}, []string{`["a",1,true]`}, ""},
		{"ignored-seven", `{"$schema":"http://json-schema.org/draft-07/schema#","definitions":{"value":{"type":"string"}},"$ref":"#/definitions/value","type":"number","oneOf":[{},{}],"dependentSchemas":{"a":false},"prefixItems":[false],"unevaluatedProperties":false}`, []string{`"kept"`}, []string{`1`}, ""},
		{"ignored-additionalItems", `{"type":"array","items":{"type":"integer"},"additionalItems":false}`, []string{`[1,2]`}, []string{`["a"]`}, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			code := fmt.Sprintf(`import("testing";"reflect")
func TestDraft(t *testing.T){var v ModelCaseRootValue;_ = reflect.ValueOf(v)
for _,raw:=range %#v {if e:=v.UnmarshalJSON([]byte(raw));e!=nil{t.Fatalf("valid %%s: %%v",raw,e)};out,e:=v.MarshalJSON();if e!=nil||string(out)!=raw{t.Fatal("raw value changed",e)}}
for _,raw:=range %#v {before,_:=v.MarshalJSON();if e:=v.UnmarshalJSON([]byte(raw));e==nil{t.Fatalf("invalid accepted: %%s",raw)};after,_:=v.MarshalJSON();if string(before)!=string(after){t.Fatal("failed decode changed parent")}}
%s
}`, tc.valid, tc.invalid, tc.views)
			independentGeneratedModule(t, map[string]string{"case.json": tc.schema}, "models", code)
		})
	}
}
