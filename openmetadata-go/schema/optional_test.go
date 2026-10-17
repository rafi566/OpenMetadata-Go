// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"encoding/json"
	"reflect"
	"testing"
)

// These are consumer objects: successful decoding starts fresh before commit.
type presenceObject struct {
	Missing     Optional[string]         `json:"missing,omitzero"`
	Nullable    Optional[string]         `json:"nullable,omitzero"`
	False       Optional[bool]           `json:"false,omitzero"`
	Zero        Optional[int]            `json:"zero,omitzero"`
	EmptyString Optional[string]         `json:"string,omitzero"`
	EmptyArray  Optional[[]int]          `json:"array,omitzero"`
	EmptyMap    Optional[map[string]int] `json:"map,omitzero"`
}

func (p *presenceObject) UnmarshalJSON(b []byte) error {
	type wire presenceObject
	var fresh wire
	if err := json.Unmarshal(b, &fresh); err != nil {
		return err
	}
	*p = presenceObject(fresh)
	return nil
}

func TestOptionalPresence(t *testing.T) {
	input := `{"nullable":null,"false":false,"zero":0,"string":"","array":[],"map":{}}`
	var p presenceObject
	if err := json.Unmarshal([]byte(input), &p); err != nil {
		t.Fatal(err)
	}
	if p.Missing.IsSet() || p.Missing.IsNull() || !p.Missing.IsZero() {
		t.Fatal("missing state")
	}
	if _, ok := p.Missing.Value(); ok {
		t.Fatal("missing has a value")
	}
	if !p.Nullable.IsSet() || !p.Nullable.IsNull() || p.Nullable.IsZero() {
		t.Fatal("null state")
	}
	if _, ok := p.Nullable.Value(); ok {
		t.Fatal("null has a value")
	}
	if value, ok := p.False.Value(); !ok || value || p.False.IsZero() {
		t.Fatal("false not present")
	}
	if value, ok := p.Zero.Value(); !ok || value != 0 || p.Zero.IsZero() {
		t.Fatal("zero not present")
	}
	if value, ok := p.EmptyString.Value(); !ok || value != "" || p.EmptyString.IsZero() {
		t.Fatal("empty string not present")
	}
	if value, ok := p.EmptyArray.Value(); !ok || value == nil || len(value) != 0 {
		t.Fatal("empty array not present")
	}
	if value, ok := p.EmptyMap.Value(); !ok || value == nil || len(value) != 0 {
		t.Fatal("empty map not present")
	}
	b, err := json.Marshal(p)
	if err != nil {
		t.Fatal(err)
	}
	var got, want any
	if err := json.Unmarshal(b, &got); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal([]byte(input), &want); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("omitzero lost presence: %s", b)
	}
	for _, value := range []Optional[string]{{}, Null[string]()} {
		b, err := json.Marshal(value)
		if err != nil || string(b) != "null" {
			t.Fatalf("standalone missing/null: %s, %v", b, err)
		}
	}
	if err := json.Unmarshal([]byte(`{"zero":"bad"}`), &p); err == nil {
		t.Fatal("invalid decode accepted")
	}
	if !p.Nullable.IsNull() || !p.False.IsSet() {
		t.Fatal("failed consumer decode changed receiver")
	}
	if err := json.Unmarshal([]byte(`{}`), &p); err != nil {
		t.Fatal(err)
	}
	b, err = json.Marshal(p)
	if err != nil || string(b) != "{}" {
		t.Fatalf("successful replacement retained omissions/defaults: %s, %v", b, err)
	}
}

func TestOptionalTransactionalDecode(t *testing.T) {
	o := Some(7)
	if err := o.UnmarshalJSON([]byte(`"invalid"`)); err == nil {
		t.Fatal("invalid type accepted")
	}
	if value, ok := o.Value(); !ok || value != 7 {
		t.Fatal("failed decode changed value")
	}
	if err := o.UnmarshalJSON([]byte(` null `)); err != nil || !o.IsNull() {
		t.Fatal("null replacement", err)
	}
	if err := o.UnmarshalJSON([]byte(`0`)); err != nil {
		t.Fatal(err)
	}
	if value, ok := o.Value(); !ok || value != 0 || o.IsNull() {
		t.Fatal("zero replacement")
	}
	bad := Some(make(chan int))
	if _, err := json.Marshal(bad); err == nil {
		t.Fatal("payload marshal error hidden")
	}
}
