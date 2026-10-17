// SPDX-License-Identifier: Apache-2.0

package main

import (
	"fmt"
	"io"
	"os"
)

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

func run(args []string, stdout, stderr io.Writer) int {
	if len(args) > 0 && args[0] == "schema" {
		return schemaCommand(args[1:], stdout, stderr)
	}
	fmt.Fprintln(stderr, "usage: om-contracts schema {check|generate} [flags]")
	return 1
}
