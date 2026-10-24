// SPDX-License-Identifier: Apache-2.0

package tableread

import (
	"compress/gzip"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"
)

type Snapshot struct {
	Entity, Service []byte
	BaseURL         string
	Enriched        bool
}

type Handler struct {
	Java     *url.URL
	Client   *http.Client
	Fallback http.Handler
	Read     func(context.Context, string) (Snapshot, error)
	once     sync.Once
	slots    chan struct{}
}

var tablePath = regexp.MustCompile(`^/api/v1/tables/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$`)

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	id := eligible(r)
	if id != "" {
		h.once.Do(func() { h.slots = make(chan struct{}, 4) })
		select {
		case h.slots <- struct{}{}:
			defer func() { <-h.slots }()
		default:
			h.Fallback.ServeHTTP(w, r)
			return
		}
		if headers, baseURL, ok := h.authorizeAdmin(r); ok {
			ctx, cancel := context.WithTimeout(r.Context(), 250*time.Millisecond)
			snapshot, err := h.Read(ctx, id)
			cancel()
			if err == nil {
				snapshot.BaseURL = baseURL
				if body, supported := project(snapshot, r.URL.Query().Get("fields")); supported {
					for key, values := range headers {
						w.Header()[key] = values
					}
					for _, key := range []string{"Content-Length", "Content-Encoding", "Transfer-Encoding", "Connection"} {
						w.Header().Del(key)
					}
					w.Header().Set("Content-Type", "application/json")
					w.Header().Add("Vary", "Accept-Encoding")
					compressed, _ := acceptsGzip(r.Header)
					if compressed && len(body) >= 256 {
						w.Header().Set("Content-Encoding", "gzip")
						writer := gzip.NewWriter(w)
						_, _ = writer.Write(body)
						_ = writer.Close()
					} else {
						_, _ = w.Write(body)
					}
					return
				}
			}
		}
	}
	h.Fallback.ServeHTTP(w, r)
}

func eligible(r *http.Request) string {
	if r.Method != "GET" || r.ContentLength != 0 || r.URL.RawPath != "" {
		return ""
	}
	for _, key := range []string{"X-OpenMetadata-Persona", "X-Impersonate-User", "Range", "If-None-Match", "If-Modified-Since"} {
		if len(r.Header.Values(key)) != 0 {
			return ""
		}
	}
	if accept := r.Header.Get("Accept"); accept != "" && accept != "application/json" && accept != "*/*" {
		return ""
	}
	if _, supported := acceptsGzip(r.Header); !supported {
		return ""
	}
	query, err := url.ParseQuery(r.URL.RawQuery)
	if err != nil {
		return ""
	}
	for key, values := range query {
		if key != "fields" || len(values) != 1 {
			return ""
		}
		if values[0] != "" {
			for _, field := range strings.Split(values[0], ",") {
				if field != "owners" && field != "tags" {
					return ""
				}
			}
		}
	}
	match := tablePath.FindStringSubmatch(r.URL.Path)
	if len(match) != 2 {
		return ""
	}
	return match[1]
}

// shortcut: quality values and uncommon encodings retain Java negotiation.
func acceptsGzip(headers http.Header) (bool, bool) {
	compressed := false
	for _, value := range headers.Values("Accept-Encoding") {
		for _, encoding := range strings.Split(value, ",") {
			switch strings.ToLower(strings.TrimSpace(encoding)) {
			case "gzip":
				compressed = true
			case "", "identity", "br", "deflate", "zstd":
			default:
				return false, false
			}
		}
	}
	return compressed, true
}

func (h *Handler) authorizeAdmin(r *http.Request) (http.Header, string, bool) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	// This non-secret setting is admin-only in the pinned Java source; resource permissions
	// cannot authorize a later SQL snapshot under data-dependent non-admin policies.
	target := h.Java.ResolveReference(&url.URL{Path: "/api/v1/system/settings/openMetadataBaseUrlConfiguration"})
	request, err := http.NewRequestWithContext(ctx, "GET", target.String(), nil)
	if err != nil {
		return nil, "", false
	}
	for _, key := range []string{"Authorization", "Cookie", "Origin"} {
		request.Header[key] = r.Header.Values(key)
	}
	request.Header.Set("Accept", "application/json")
	request.Host = r.Host
	response, err := h.Client.Do(request)
	if err != nil {
		return nil, "", false
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return nil, "", false
	}
	var setting struct {
		Type  string `json:"config_type"`
		Value struct {
			URL string `json:"openMetadataUrl"`
		} `json:"config_value"`
	}
	if json.NewDecoder(io.LimitReader(response.Body, 16*1024)).Decode(&setting) != nil || setting.Type != "openMetadataBaseUrlConfiguration" || len(setting.Value.URL) > 8192 {
		return nil, "", false
	}
	return response.Header.Clone(), setting.Value.URL, true
}

func project(snapshot Snapshot, fields string) ([]byte, bool) {
	if snapshot.Enriched || len(snapshot.Entity)+len(snapshot.Service) > 256*1024 {
		return nil, false
	}
	base, err := url.Parse(snapshot.BaseURL)
	if err != nil || base.Host == "" || (base.Scheme != "http" && base.Scheme != "https") || base.User != nil || base.RawQuery != "" || base.Fragment != "" {
		return nil, false
	}
	var entity map[string]json.RawMessage
	if json.Unmarshal(snapshot.Entity, &entity) != nil || string(entity["deleted"]) != "false" {
		return nil, false
	}
	for _, key := range []string{"id", "name", "fullyQualifiedName", "version", "columns", "serviceType", "processedLineage", "entityStatus"} {
		if entity[key] == nil || string(entity[key]) == "null" {
			return nil, false
		}
	}
	for key := range entity {
		if string(entity[key]) == "null" {
			return nil, false
		}
		switch key {
		case "id", "name", "fullyQualifiedName", "description", "displayName", "version", "updatedAt", "updatedBy", "createdAt", "createdBy", "columns", "databaseSchema", "database", "serviceType", "changeDescription", "incrementalChangeDescription", "deleted", "processedLineage", "entityStatus", "votes":
		default:
			return nil, false
		}
	}
	for _, key := range []string{"changeDescription", "incrementalChangeDescription"} {
		if raw := entity[key]; raw != nil && !completeHistory(raw) {
			return nil, false
		}
	}
	delete(entity, "votes")
	for _, field := range strings.Split(fields, ",") {
		if field == "owners" || field == "tags" {
			entity[field] = json.RawMessage(`[]`)
		}
	}
	var columns []map[string]json.RawMessage
	if json.Unmarshal(entity["columns"], &columns) != nil || !plainColumns(columns, 0) {
		return nil, false
	}
	entity["columns"], err = json.Marshal(columns)
	if err != nil {
		return nil, false
	}
	root := strings.TrimRight(snapshot.BaseURL, "/") + "/api/v1"
	for key, path := range map[string]string{"databaseSchema": "databaseSchemas", "database": "databases", "service": "services/databaseServices"} {
		var ref map[string]json.RawMessage
		data := entity[key]
		if key == "service" {
			data = snapshot.Service
		}
		if json.Unmarshal(data, &ref) != nil {
			return nil, false
		}
		for key, value := range ref {
			if string(value) == "null" {
				return nil, false
			}
			switch key {
			case "id", "type", "name", "fullyQualifiedName", "description", "displayName", "deleted", "href":
			default:
				return nil, false
			}
		}
		var id string
		if json.Unmarshal(ref["id"], &id) != nil || id == "" {
			return nil, false
		}
		ref["href"], _ = json.Marshal(root + "/" + path + "/" + url.PathEscape(id))
		entity[key], _ = json.Marshal(ref)
	}
	var id string
	if json.Unmarshal(entity["id"], &id) != nil || id == "" {
		return nil, false
	}
	entity["href"], _ = json.Marshal(root + "/tables/" + url.PathEscape(id))
	body, err := json.Marshal(entity)
	return body, err == nil && len(body) <= 256*1024
}

func completeHistory(raw json.RawMessage) bool {
	var history map[string]json.RawMessage
	if json.Unmarshal(raw, &history) != nil || len(history) < 4 || len(history) > 5 {
		return false
	}
	for key, value := range history {
		switch key {
		case "previousVersion":
			var version float64
			if json.Unmarshal(value, &version) != nil || version < 0.1 {
				return false
			}
		case "fieldsAdded", "fieldsUpdated", "fieldsDeleted":
			var changes []map[string]json.RawMessage
			if string(value) == "null" || json.Unmarshal(value, &changes) != nil {
				return false
			}
			for _, change := range changes {
				if change == nil {
					return false
				}
				for field, data := range change {
					if string(data) == "null" {
						return false
					}
					switch field {
					case "name":
						var name string
						if json.Unmarshal(data, &name) != nil {
							return false
						}
					case "oldValue", "newValue":
					default:
						return false
					}
				}
			}
		case "changeSummary":
			var summaries map[string]map[string]json.RawMessage
			if string(value) == "null" || json.Unmarshal(value, &summaries) != nil {
				return false
			}
			for _, summary := range summaries {
				if summary == nil {
					return false
				}
				for field, data := range summary {
					if string(data) == "null" {
						return false
					}
					switch field {
					case "changedBy", "changeSource":
						var text string
						if json.Unmarshal(data, &text) != nil {
							return false
						}
						if field == "changeSource" && text != "Manual" && text != "Propagated" && text != "Automated" && text != "Derived" && text != "Ingested" && text != "Suggested" {
							return false
						}
					case "changedAt":
						var timestamp int64
						if json.Unmarshal(data, &timestamp) != nil {
							return false
						}
					default:
						return false
					}
				}
			}
		default:
			return false
		}
	}
	for _, key := range []string{"fieldsAdded", "fieldsUpdated", "fieldsDeleted", "previousVersion"} {
		if history[key] == nil || string(history[key]) == "null" {
			return false
		}
	}
	return true
}

func plainColumns(columns []map[string]json.RawMessage, depth int) bool {
	if depth > 64 || len(columns) > 4096 {
		return false
	}
	for _, column := range columns {
		if column["children"] == nil || string(column["children"]) == "null" {
			return false
		}
		for key := range column {
			if string(column[key]) == "null" {
				return false
			}
			switch key {
			case "name", "displayName", "dataType", "dataLength", "dataTypeDisplay", "description", "fullyQualifiedName", "children", "tags":
			default:
				return false
			}
		}
		if tags := column["tags"]; tags != nil && string(tags) != "[]" && string(tags) != "null" {
			return false
		}
		column["tags"] = json.RawMessage(`[]`)
		children := []map[string]json.RawMessage{}
		if raw := column["children"]; raw != nil && string(raw) != "null" {
			if json.Unmarshal(raw, &children) != nil {
				return false
			}
		}
		if !plainColumns(children, depth+1) {
			return false
		}
		column["children"], _ = json.Marshal(children)
	}
	return true
}
