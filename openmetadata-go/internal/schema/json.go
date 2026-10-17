// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
)

const maxJSONBytes = 16 << 20

func decode(b []byte) (any, error) {
	if len(b) > maxJSONBytes {
		return nil, errors.New("JSON document exceeds 16 MiB")
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	v, e := readJSONValue(d, "", 0)
	if e != nil {
		return nil, e
	}
	if _, e = d.Token(); e != io.EOF {
		return nil, errors.New("expected one JSON value")
	}
	return v, nil
}
func readJSONValue(d *json.Decoder, pointer string, depth int) (any, error) {
	token, e := d.Token()
	if e != nil {
		return nil, e
	}
	delimiter, ok := token.(json.Delim)
	if !ok {
		return token, nil
	}
	if depth >= 256 {
		return nil, fmt.Errorf("JSON depth exceeds 256 at %s", pointer)
	}
	switch delimiter {
	case '{':
		value := map[string]any{}
		for d.More() {
			key, e := d.Token()
			if e != nil {
				return nil, e
			}
			name, ok := key.(string)
			if !ok {
				return nil, errors.New("object key must be string")
			}
			p := pointer + "/" + escape(name)
			if _, exists := value[name]; exists {
				return nil, fmt.Errorf("duplicate JSON key at %s", p)
			}
			item, e := readJSONValue(d, p, depth+1)
			if e != nil {
				return nil, e
			}
			value[name] = item
		}
		if _, e := d.Token(); e != nil {
			return nil, e
		}
		return value, nil
	case '[':
		value := []any{}
		for d.More() {
			item, e := readJSONValue(d, fmt.Sprintf("%s/%d", pointer, len(value)), depth+1)
			if e != nil {
				return nil, e
			}
			value = append(value, item)
		}
		if _, e := d.Token(); e != nil {
			return nil, e
		}
		return value, nil
	default:
		return nil, errors.New("unexpected JSON delimiter")
	}
}
func escape(s string) string { return strings.ReplaceAll(strings.ReplaceAll(s, "~", "~0"), "/", "~1") }
