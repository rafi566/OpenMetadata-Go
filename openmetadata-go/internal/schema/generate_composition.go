// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"fmt"
	"strconv"
	"strings"
)

func (g *modelGenerator) compositionViews(body *strings.Builder, name string, shape *entry) error {
	m, _ := shape.value.(map[string]any)
	for _, keyword := range []string{"oneOf", "anyOf", "allOf"} {
		branches, _ := m[keyword].([]any)
		for index := range branches {
			pointer := shape.Pointer + "/" + keyword + "/" + strconv.Itoa(index)
			branch := g.registry.schemas[keyAt(shape.Path, pointer)]
			child := g.names[keyAt(shape.Path, pointer)]
			if branch == nil || child == "" {
				return diagnostic("generate", shape.Path, pointer, fmt.Errorf("missing composition branch"))
			}
			fmt.Fprintf(body, "func(v %s) As%s%d()(*%s,bool,error){if e:=v.Validate();e!=nil{return nil,false,e};next,ok,e:=modelBranch(%q,v.value);if e!=nil||!ok{return nil,ok,e};return &%s{value:next},true,nil}\n", name, identifier(keyword), index, child, g.nodeID(branch), child)
		}
	}
	return nil
}
