// SPDX-License-Identifier: Apache-2.0

package schema

import (
	"fmt"
	"io/fs"
)

// LoadEmbeddedRegistry shares admission with disk loading while assigning stable
// retrieval identities; source bytes and all graph state become privately owned.
func LoadEmbeddedRegistry(source fs.FS, profile string) (*Registry, error) {
	if profile != "" && profile != LegacyProfile {
		return nil, fmt.Errorf("unknown embedded registry profile %q", profile)
	}
	if source == nil {
		return nil, fmt.Errorf("nil embedded registry filesystem")
	}
	return loadRegistryFS(source, "/__openmetadata_embedded__", profile == LegacyProfile)
}
