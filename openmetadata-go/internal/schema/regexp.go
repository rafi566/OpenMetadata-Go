// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"fmt"
	"regexp"
	"regexp/syntax"
	"strings"
	"unicode/utf8"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

const namePattern = `^((?!::)[^>"\x00-\x1f])*$`
const edgePattern = `^(?=$|.*[A-Za-z0-9])[A-Za-z0-9 ._-]*$`

type javaRegexp struct {
	pattern string
	match   func(string) bool
}

func (r javaRegexp) String() string { return r.pattern }
func (r javaRegexp) MatchString(s string) bool {
	if r.match(s) {
		return true
	}
	// Java's default $ may match before one final line terminator; Go's $ is
	// absolute. All pinned patterns are anchored, without multiline mode.
	trimmed := s
	if strings.HasSuffix(s, "\r\n") {
		trimmed = s[:len(s)-2]
	} else {
		last, size := utf8.DecodeLastRuneInString(s)
		if last == '\n' || last == '\r' || last == 0x85 || last == 0x2028 || last == 0x2029 {
			trimmed = s[:len(s)-size]
		}
	}
	return trimmed != s && r.match(trimmed)
}
func legacyRegexp(pattern string) (jsonschema.Regexp, error) {
	var match func(string) bool
	switch pattern {
	case namePattern:
		match = func(s string) bool {
			if strings.Contains(s, "::") {
				return false
			}
			for _, c := range s {
				if c == '>' || c == '"' || c < 32 {
					return false
				}
			}
			return true
		}
	case edgePattern:
		match = func(s string) bool {
			alnum := false
			for _, c := range s {
				a := c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9'
				alnum = alnum || a
				if !a && c != ' ' && c != '.' && c != '_' && c != '-' {
					return false
				}
			}
			return s == "" || alnum
		}
	default:
		adapted := pattern
		if strings.HasPrefix(adapted, "(?U)") {
			var word strings.Builder
			for _, r := range readPolicy().JavaWordRanges {
				fmt.Fprintf(&word, `\x{%X}-\x{%X}`, r[0], r[1])
			}
			adapted = strings.ReplaceAll(strings.TrimPrefix(adapted, "(?U)"), `[\w`, "["+word.String())
			adapted = strings.ReplaceAll(adapted, `\w`, "["+word.String()+"]")
		}
		// Java ASCII whitespace includes vertical tab, unlike Go's Perl class.
		// These substitutions are exact for the finite audited corpus patterns.
		adapted = strings.ReplaceAll(adapted, `[\s\S]`, `(?s:.)`)
		adapted = strings.ReplaceAll(adapted, `[\S.!#$%&’*+/=?^_`+"`"+`{|}~-]`, `[^\t\n\x0B\f\r ]`)
		adapted = strings.ReplaceAll(adapted, `\S`, `[^\t\n\x0B\f\r ]`)
		re, e := regexp.Compile(adapted)
		if e != nil {
			return nil, e
		}
		match = re.MatchString
	}
	return javaRegexp{pattern, match}, nil
}
func genericRegexp(pattern string) (jsonschema.Regexp, error) {
	if strings.Contains(pattern, "(?U)") {
		return nil, fmt.Errorf("%w: Java Unicode mode requires pinned source", ErrBlocked)
	}
	re, e := regexp.Compile(pattern)
	if e != nil {
		if syntaxError, ok := e.(*syntax.Error); ok {
			switch syntaxError.Code {
			case syntax.ErrMissingBracket, syntax.ErrMissingParen, syntax.ErrUnexpectedParen, syntax.ErrTrailingBackslash:
				return nil, e
			}
		}
		return nil, fmt.Errorf("%w: %v", ErrBlocked, e)
	}
	return re, nil
}
