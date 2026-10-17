// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"encoding/json"
	"errors"
	"strconv"
	"strings"
)

// Number retains a JSON numeric token without a floating-point conversion.
// ADR:2026-10-17-go-schema-reconstruction-preserves-source-semantics
type Number struct{ token string }

func ParseNumber(token string) (Number, error) {
	if token == "" || strings.TrimSpace(token) != token {
		return Number{}, errors.New("expected a JSON number token")
	}
	v, err := decode([]byte(token))
	if err != nil {
		return Number{}, err
	}
	if _, ok := v.(json.Number); !ok {
		return Number{}, errors.New("expected a JSON number token")
	}
	return Number{token: token}, nil
}
func (n Number) String() string { return n.token }
func (n Number) MarshalJSON() ([]byte, error) {
	if n.token == "" {
		return nil, errors.New("unset number")
	}
	return []byte(n.token), nil
}
func (n *Number) UnmarshalJSON(b []byte) error {
	parsed, err := ParseNumber(string(b))
	if err != nil {
		return err
	}
	*n = parsed
	return nil
}

// Saturating the exponent above token length preserves integrality and width
// decisions without ever materializing an attacker-controlled power of ten.
func (n Number) decimal() (digits string, shift int, negative bool) {
	s := n.token
	negative = strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	exponent := 0
	if i := strings.IndexAny(s, "eE"); i >= 0 {
		exp := s[i+1:]
		s = s[:i]
		limit := len(n.token) + 32
		parsed, err := strconv.ParseInt(exp, 10, 64)
		if err != nil || parsed > int64(limit) || parsed < -int64(limit) {
			exponent = limit
			if strings.HasPrefix(exp, "-") {
				exponent = -limit
			}
		} else {
			exponent = int(parsed)
		}
	}
	fraction := 0
	if i := strings.IndexByte(s, '.'); i >= 0 {
		fraction = len(s) - i - 1
		s = s[:i] + s[i+1:]
	}
	digits = strings.TrimLeft(s, "0")
	if digits == "" {
		return "0", 0, negative
	}
	trimmed := strings.TrimRight(digits, "0")
	shift = exponent - fraction + len(digits) - len(trimmed)
	return trimmed, shift, negative
}
func (n Number) IsInteger() bool {
	if n.token == "" {
		return false
	}
	_, shift, _ := n.decimal()
	return shift >= 0
}
func (n Number) integerToken() (string, error) {
	if n.token == "" {
		return "", errors.New("unset number")
	}
	digits, shift, negative := n.decimal()
	if shift < 0 {
		return "", errors.New("number is not a mathematical integer")
	}
	if len(digits)+shift > 20 {
		return "", errors.New("integer exceeds fixed-width range")
	}
	s := digits + strings.Repeat("0", shift)
	if negative && s != "0" {
		s = "-" + s
	}
	return s, nil
}
func (n Number) Int64() (int64, error) {
	s, err := n.integerToken()
	if err != nil {
		return 0, err
	}
	return strconv.ParseInt(s, 10, 64)
}
func (n Number) Uint64() (uint64, error) {
	s, err := n.integerToken()
	if err != nil {
		return 0, err
	}
	return strconv.ParseUint(s, 10, 64)
}
