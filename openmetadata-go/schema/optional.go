// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"bytes"
	"encoding/json"
)

// Optional preserves wire presence independently of the Go payload's zero value.
// ADR:2026-10-17-go-schema-reconstruction-preserves-source-semantics
// A containing model must decode into fresh state to clear omitted fields on reuse.
type Optional[T any] struct {
	value     T
	set, null bool
}

func Some[T any](v T) Optional[T]      { return Optional[T]{value: v, set: true} }
func Null[T any]() Optional[T]         { return Optional[T]{set: true, null: true} }
func (o Optional[T]) IsSet() bool      { return o.set }
func (o Optional[T]) IsNull() bool     { return o.set && o.null }
func (o Optional[T]) IsZero() bool     { return !o.set }
func (o Optional[T]) Value() (T, bool) { return o.value, o.set && !o.null }
func (o Optional[T]) MarshalJSON() ([]byte, error) {
	if !o.set || o.null {
		return []byte("null"), nil
	}
	return json.Marshal(o.value)
}
func (o *Optional[T]) UnmarshalJSON(b []byte) error {
	if bytes.Equal(bytes.TrimSpace(b), []byte("null")) {
		*o = Null[T]()
		return nil
	}
	var v T
	if err := json.Unmarshal(b, &v); err != nil {
		return err
	}
	*o = Some(v)
	return nil
}
