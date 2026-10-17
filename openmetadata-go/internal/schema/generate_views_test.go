// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestMapPatternOverlap(t *testing.T) {
	independentGeneratedModule(t, map[string]string{
		"map.json":    `{"properties":{"declared":{"type":"string"},"x_declared":{"type":"number","minimum":2}},"patternProperties":{"^x":{"type":"integer"},"end$":{"minimum":5}},"additionalProperties":{"type":["number","null"]}}`,
		"search.json": `{"patternProperties":{"mid":{"type":"string"},"^z$":{"type":"string"}},"additionalProperties":{"type":["number","null"]}}`,
	}, "models", `
import("testing";support "github.com/rafi566/OpenMetadata-Go/openmetadata-go/internal/schema")
func TestMapClassification(t *testing.T){
var v ModelMapRootValue
input:="{\"declared\":\"yes\",\"x_declared\":2,\"x_end\":5,\"weekend\":6,\"large\":9007199254740993,\"nil\":null,\"exponent\":1e99}"
if e:=v.UnmarshalJSON([]byte(input));e!=nil{t.Fatal(e)}
items,ok,e:=v.AdditionalProperties();if e!=nil||!ok||len(items)!=3{t.Fatal("classification",items,ok,e)}
for _,key:=range []string{"declared","x_declared","x_end","weekend"}{if _,present:=items[key];present{t.Fatal("declared/pattern key treated as additional",key)}}
if items["nil"]==nil||!items["nil"].JSONValue().IsNull(){t.Fatal("null child lost")}
for key,want:=range map[string]string{"large":"9007199254740993","exponent":"1e99"}{n,ok:=items[key].NumberValue();if !ok||n.String()!=want{t.Fatal("numeric token changed",key)}}
if e:=items["large"].UnmarshalJSON([]byte("1"));e!=nil{t.Fatal(e)};raw,_:=v.MarshalJSON();if string(raw)!=input{t.Fatal("detached child modified parent")}
for _,bad:=range []string{"{\"x_end\":3}","{\"x_end\":5.5}","{\"x_declared\":1}","{\"x_declared\":2.5}","{\"x_declared\":\"bad\"}","{\"ordinary\":\"bad\"}"}{if e:=v.UnmarshalJSON([]byte(bad));e==nil{t.Fatal("applicable constraint skipped",bad)}}
bad,_:=support.ParseValue([]byte("{\"x_end\":3}"));v.value=bad;if _,_,e:=v.AdditionalProperties();e==nil{t.Fatal("map parent validation skipped")}
if e:=v.UnmarshalJSON([]byte("{}"));e!=nil{t.Fatal(e)};items,ok,e=v.AdditionalProperties();if e!=nil||!ok||items==nil||len(items)!=0{t.Fatal("empty map contract")}
if e:=v.UnmarshalJSON([]byte("null"));e!=nil{t.Fatal(e)};items,ok,e=v.AdditionalProperties();if e!=nil||ok||items!=nil{t.Fatal("nonobject map contract")}
var search ModelSearchRootValue
if e:=search.UnmarshalJSON([]byte("{\"amidb\":\"kept\",\"z\":\"kept\",\"z\\n\":7,\"other\":null}"));e!=nil{t.Fatal(e)}
extra,ok,e:=search.AdditionalProperties();if e!=nil||!ok||len(extra)!=2||extra["z\n"]==nil||extra["other"]==nil{t.Fatal("search/absolute end semantics",extra,e)}
}
`)
}

func TestMapPatternUnsupportedClassification(t *testing.T) {
	for _, pattern := range []string{`(?=a)`, `(?U)\w+`, namePattern, edgePattern} {
		t.Run(pattern, func(t *testing.T) {
			raw, err := json.Marshal(map[string]any{"patternProperties": map[string]any{pattern: map[string]any{}}, "additionalProperties": map[string]any{"type": "integer"}})
			if err != nil {
				t.Fatal(err)
			}
			out := filepath.Join(t.TempDir(), "out")
			_, err = Generate(generationRegistry(t, map[string]string{"pattern.json": string(raw)}), GenerateOptions{"models", out})
			if !errors.Is(err, ErrBlocked) || !strings.Contains(err.Error(), "pattern.json#/patternProperties/"+escape(pattern)) {
				t.Fatalf("unsupported pattern needs exact source pointer: %v", err)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Fatal("unsupported classification wrote output")
			}
		})
	}
}

func TestRecursiveViewsAndUnknownContainers(t *testing.T) {
	// The synthetic TestSuite fixture isolates the baseline's unusual placement:
	// resultSummary is selected by a reference outside the properties container.
	// The connection-argument fixture below uses the actual unmodified source.
	connection, err := os.ReadFile(filepath.Join(corpusRoot(t), "entity/services/connections/connectionBasicType.json"))
	if err != nil {
		t.Fatal(err)
	}
	independentGeneratedModule(t, map[string]string{
		"node.json":            `{"type":["object","null"],"properties":{"value":{"type":"integer"},"next":{"$ref":"#"}},"required":["value"],"additionalProperties":false}`,
		"tree.json":            `{"type":"array","items":{"anyOf":[{"type":"integer"},{"$ref":"#"}]}}`,
		"tests/testSuite.json": `{"definitions":{"testSuiteConnection":{"type":"object","properties":{"config":{"type":"null"}},"resultSummary":{"properties":{"testCaseName":{"type":"string"},"status":{"enum":["Success","Failed"]},"timestamp":{"type":"integer"}}}}},"type":"object","properties":{"connection":{"$ref":"#/definitions/testSuiteConnection"},"testCaseResultSummary":{"type":"array","items":{"$ref":"#/definitions/testSuiteConnection/resultSummary"}}}}`,
		"entity/services/connections/connectionBasicType.json": string(connection),
	}, "models", `
import("testing";"strings";"reflect")
func TestRecursivePointers(t *testing.T){
var v ModelNodeRootValue
prefix:="{\"value\":9007199254740993,\"next\":"
raw:=strings.Repeat(prefix,24)+"null"+strings.Repeat("}",24)
if e:=v.UnmarshalJSON([]byte(raw));e!=nil{t.Fatal(e)}
first,ok,e:=v.Object();if e!=nil||!ok{t.Fatal(e)};next,ok:=first.Next.Value();if !ok||next==nil{t.Fatal("first pointer")}
count:=1
for next!=nil{view,ok,e:=next.Object();if e!=nil||!ok{t.Fatal("recursive object",e)};value,_:=view.Value.Value();n,ok:=value.NumberValue();if !ok||n.String()!="9007199254740993"{t.Fatal("recursive precision")};count++;if view.Next.IsNull(){next=nil}else{next,ok=view.Next.Value();if !ok{t.Fatal("recursive presence")}}}
if count!=24{t.Fatal("recursive traversal",count)}
for _,bad:=range []string{strings.Repeat(prefix,23)+"{\"value\":\"bad\"}"+strings.Repeat("}",23),strings.Repeat(prefix,257)+"null"+strings.Repeat("}",257)}{if e:=v.UnmarshalJSON([]byte(bad));e==nil{t.Fatal("invalid/deep recursive data accepted")};after,_:=v.MarshalJSON();if string(after)!=raw{t.Fatal("failed recursive decode mutated receiver")}}
if e:=v.UnmarshalJSON([]byte("{\"value\":1}"));e!=nil{t.Fatal(e)};view,_,_:=v.Object();if view.Next.IsSet(){t.Fatal("recursive replacement retained next")}
var tree ModelTreeRootValue;if e:=tree.UnmarshalJSON([]byte("[1,[2,[3]]]"));e!=nil{t.Fatal(e)}
items,ok,e:=tree.Items();if e!=nil||!ok||len(items)!=2{t.Fatal(e)};branch,ok,e:=items[1].AsAnyOf1();if e!=nil||!ok{t.Fatal("recursive branch",e)};nested,ok,e:=branch.Items();if e!=nil||!ok||len(nested)!=2{t.Fatal("recursive array",e)};leaf,ok,e:=nested[0].AsAnyOf0();if e!=nil||!ok{t.Fatal(e)};n,ok:=leaf.NumberValue();if !ok||n.String()!="2"{t.Fatal("recursive leaf")}
if e:=tree.UnmarshalJSON([]byte("[1,[2,[\"bad\"]]]"));e==nil{t.Fatal("invalid recursive union child accepted")}
}
func TestUnknownContainerReference(t *testing.T){
var v ModelTestsTestSuiteRootValue
raw:="{\"connection\":{\"config\":null,\"resultSummary\":17},\"testCaseResultSummary\":[{\"testCaseName\":\"case\",\"status\":\"Success\",\"timestamp\":9007199254740993,\"unknown\":true}]}"
if e:=v.UnmarshalJSON([]byte(raw));e!=nil{t.Fatal(e)};view,ok,e:=v.Object();if e!=nil||!ok{t.Fatal(e)}
connection,_:=view.Connection.Value();cv,ok,e:=connection.Object();if e!=nil||!ok||!cv.Config.IsNull(){t.Fatal("connection shape",e)};if _,invented:=reflect.TypeOf(cv).FieldByName("ResultSummary");invented{t.Fatal("unknown schema container became instance property")}
summaries,_:=view.TestCaseResultSummary.Value();items,ok,e:=summaries.Items();if e!=nil||!ok||len(items)!=1{t.Fatal("referenced unknown target",e)};summary,ok,e:=items[0].Object();if e!=nil||!ok{t.Fatal(e)};stamp,_:=summary.Timestamp.Value();n,ok:=stamp.NumberValue();if !ok||n.String()!="9007199254740993"{t.Fatal("referenced target shape")}
after,_:=v.MarshalJSON();if string(after)!=raw{t.Fatal("unknown data lost")}
if e:=v.UnmarshalJSON([]byte("{\"testCaseResultSummary\":[{\"timestamp\":\"bad\"}]}"));e==nil{t.Fatal("referenced unknown target constraint skipped")}
}
func TestMisplacedMapAnnotation(t *testing.T){
var v ModelEntityServicesConnectionsConnectionBasicTypeAtDefinitionsConnectionArgumentsValue
raw:="{\"number\":9007199254740993,\"nested\":{\"anything\":[true,1e99]},\"nil\":null,\"\":false}"
if e:=v.UnmarshalJSON([]byte(raw));e!=nil{t.Fatal("misplaced annotation acquired constraints",e)};items,ok,e:=v.AdditionalProperties();if e!=nil||!ok||len(items)!=4{t.Fatal("unconstrained map",e)};if !items["nil"].JSONValue().IsNull(){t.Fatal("annotation null")};n,ok:=items["number"].JSONValue().NumberValue();if !ok||n.String()!="9007199254740993"{t.Fatal("annotation precision")};after,_:=v.MarshalJSON();if string(after)!=raw{t.Fatal("annotation raw owner")}
}
`)
}
