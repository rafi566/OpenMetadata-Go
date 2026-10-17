// SPDX-License-Identifier: Apache-2.0

package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	schema "github.com/rafi566/OpenMetadata-Go/openmetadata-go/internal/schema"
	"io"
)

func schemaCommand(args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 || (args[0] != "check" && args[0] != "generate") {
		fmt.Fprintln(stderr, "usage: om-contracts schema {check|generate} --root PATH [--profile openmetadata-2f0d4a4a] [--output PATH --package NAME]")
		return 1
	}
	command := args[0]
	flags := flag.NewFlagSet("schema "+command, flag.ContinueOnError)
	flags.SetOutput(stderr)
	root := flags.String("root", "", "local schema directory")
	profile := flags.String("profile", "", "explicit immutable corpus profile")
	var output, pkg string
	if command == "generate" {
		flags.StringVar(&output, "output", "", "new generated output directory")
		flags.StringVar(&pkg, "package", "", "generated Go package name")
	}
	if err := flags.Parse(args[1:]); err != nil {
		return 1
	}
	if *root == "" || flags.NArg() != 0 || (*profile != "" && *profile != schema.LegacyProfile) || (command == "generate" && (output == "" || pkg == "")) {
		fmt.Fprintln(stderr, "schema "+command+": require --root and a supported explicit profile; generate also requires --output and --package")
		return 1
	}
	var r *schema.Registry
	var err error
	if *profile == schema.LegacyProfile {
		r, err = schema.LoadLegacyRegistry(*root)
	} else {
		r, err = schema.LoadRegistry(*root)
	}
	if err != nil {
		return schemaFailure(err, stderr)
	}
	if command == "generate" {
		paths, err := schema.Generate(r, schema.GenerateOptions{Package: pkg, OutputDir: output})
		if err == nil {
			err = json.NewEncoder(stdout).Encode(paths)
		}
		return schemaFailure(err, stderr)
	}
	if *profile != "" {
		if _, err := fmt.Fprintln(stdout, "pinned raw manifest verified; physical identity profile: "+*profile); err != nil {
			return schemaFailure(err, stderr)
		}
	}
	result, err := r.Check()
	if err = errors.Join(err, json.NewEncoder(stdout).Encode(result)); err != nil {
		return schemaFailure(err, stderr)
	}
	_, err = fmt.Fprintln(stdout, "local graph and all-node schema compilation verified; instance and endpoint parity are separate checks")
	return schemaFailure(err, stderr)
}

func schemaFailure(err error, stderr io.Writer) int {
	if err == nil {
		return 0
	}
	fmt.Fprintln(stderr, err)
	// A blocker takes precedence over invalidity or a failed result stream in
	// mixed outcomes. Counts never turn a partial check into success.
	if errors.Is(err, schema.ErrBlocked) {
		return 2
	}
	return 1
}
