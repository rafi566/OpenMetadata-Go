// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"bytes"
	"encoding/json"
	"errors"
)

// Value owns exact JSON bytes; projections never share mutable storage.
// ADR:2026-10-17-go-schema-reconstruction-preserves-source-semantics
type Value struct{ raw []byte }

func ParseValue(b []byte) (Value, error) {
	if len(b) > maxJSONBytes {
		return Value{}, errors.New("JSON document exceeds 16 MiB")
	}
	owned := bytes.Clone(b)
	if _, err := decode(owned); err != nil {
		return Value{}, err
	}
	return Value{raw: owned}, nil
}
func (v Value) RawJSON() []byte { return bytes.Clone(v.raw) }
func (v Value) MarshalJSON() ([]byte, error) {
	if len(v.raw) == 0 {
		return nil, errors.New("unset value")
	}
	return v.RawJSON(), nil
}
func (v *Value) UnmarshalJSON(b []byte) error {
	parsed, err := ParseValue(b)
	if err != nil {
		return err
	}
	*v = parsed
	return nil
}
func (v Value) IsNull() bool { return bytes.Equal(bytes.TrimSpace(v.raw), []byte("null")) }
func (v Value) StringValue() (string, bool) {
	parsed, err := decode(v.raw)
	s, ok := parsed.(string)
	return s, err == nil && ok
}
func (v Value) BoolValue() (bool, bool) {
	parsed, err := decode(v.raw)
	b, ok := parsed.(bool)
	return b, err == nil && ok
}
func (v Value) NumberValue() (Number, bool) {
	parsed, err := decode(v.raw)
	n, ok := parsed.(json.Number)
	if err != nil || !ok {
		return Number{}, false
	}
	return Number{token: string(n)}, true
}
func (v Value) Object() (map[string]Value, bool) {
	trimmed := bytes.TrimSpace(v.raw)
	if len(trimmed) == 0 || trimmed[0] != '{' {
		return nil, false
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(trimmed, &raw); err != nil {
		return nil, false
	}
	result := make(map[string]Value, len(raw))
	for key, item := range raw {
		result[key] = Value{raw: bytes.Clone(item)}
	}
	return result, true
}
func (v Value) Array() ([]Value, bool) {
	trimmed := bytes.TrimSpace(v.raw)
	if len(trimmed) == 0 || trimmed[0] != '[' {
		return nil, false
	}
	var raw []json.RawMessage
	if err := json.Unmarshal(trimmed, &raw); err != nil {
		return nil, false
	}
	result := make([]Value, len(raw))
	for i, item := range raw {
		result[i] = Value{raw: bytes.Clone(item)}
	}
	return result, true
}
