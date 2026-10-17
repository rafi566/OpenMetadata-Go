// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"encoding/json"
	"testing"
)

func TestNumberExactTokens(t *testing.T) {
	for _, token := range []string{"9007199254740993", "18446744073709551615", "18446744073709551616", "-9223372036854775808", "-0", "1e1000000000"} {
		n, err := ParseNumber(token)
		if err != nil {
			t.Fatalf("%s: %v", token, err)
		}
		b, err := json.Marshal(n)
		if err != nil || string(b) != token || n.String() != token {
			t.Fatalf("%s lost exact token: %s, %v", token, b, err)
		}
	}
	for _, token := range []string{"", " 1", "1 ", "01", "+1", "1.", ".1", "NaN", "1e", "1e+", "--1", "null", "true", "1 2"} {
		if _, err := ParseNumber(token); err == nil {
			t.Errorf("accepted %q", token)
		}
	}
	var zero Number
	if _, err := json.Marshal(zero); err == nil {
		t.Error("unset number serialized")
	}
	if _, err := zero.Int64(); err == nil {
		t.Error("unset int64 accepted")
	}
	if _, err := zero.Uint64(); err == nil {
		t.Error("unset uint64 accepted")
	}
	if zero.IsInteger() {
		t.Error("unset number is integer")
	}
}

func TestExactNumbersAndCheckedViews(t *testing.T) {
	for _, tc := range []struct {
		token         string
		integer       bool
		signed        int64
		unsigned      uint64
		intOK, uintOK bool
	}{
		{"9007199254740993", true, 9007199254740993, 9007199254740993, true, true},
		{"18446744073709551615", true, 0, 18446744073709551615, false, true},
		{"18446744073709551616", true, 0, 0, false, false},
		{"-9223372036854775808", true, -9223372036854775808, 0, true, false},
		{"9223372036854775808", true, 0, 9223372036854775808, false, true},
		{"-9223372036854775809", true, 0, 0, false, false},
		{"1.00", true, 1, 1, true, true}, {"12.3e1", true, 123, 123, true, true},
		{"1200e-2", true, 12, 12, true, true}, {"1e-1", false, 0, 0, false, false},
		{"1.01", false, 0, 0, false, false}, {"-0", true, 0, 0, true, true},
		{"1e1000000000", true, 0, 0, false, false}, {"1e-1000000000", false, 0, 0, false, false},
		{"0e1000000000", true, 0, 0, true, true}, {"-0.000e-1000000000", true, 0, 0, true, true},
		{"1e999999999999999999999999", true, 0, 0, false, false},
		{"1e-999999999999999999999999", false, 0, 0, false, false},
	} {
		t.Run(tc.token, func(t *testing.T) {
			n, err := ParseNumber(tc.token)
			if err != nil {
				t.Fatal(err)
			}
			if n.IsInteger() != tc.integer {
				t.Errorf("IsInteger = %v, want %v", n.IsInteger(), tc.integer)
			}
			i, err := n.Int64()
			if (err == nil) != tc.intOK || (tc.intOK && i != tc.signed) {
				t.Errorf("Int64 = %d, %v", i, err)
			}
			u, err := n.Uint64()
			if (err == nil) != tc.uintOK || (tc.uintOK && u != tc.unsigned) {
				t.Errorf("Uint64 = %d, %v", u, err)
			}
		})
	}
	n, _ := ParseNumber("1.00")
	for _, bad := range []string{"null", "01", "2 3"} {
		if err := n.UnmarshalJSON([]byte(bad)); err == nil || n.String() != "1.00" {
			t.Errorf("failed decode changed number for %q", bad)
		}
	}
	if err := n.UnmarshalJSON([]byte("-0")); err != nil || n.String() != "-0" {
		t.Fatalf("replacement: %s, %v", n.String(), err)
	}
}
