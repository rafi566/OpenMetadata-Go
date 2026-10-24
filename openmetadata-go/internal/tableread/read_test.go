// SPDX-License-Identifier: Apache-2.0

package tableread

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"
)

const tableID = "2e227e5e-0403-45c2-a56f-8479b52c8e67"
const adminSetting = `{"config_type":"openMetadataBaseUrlConfiguration","config_value":{"openMetadataUrl":"https://metadata.example.test"}}`

func plain() Snapshot {
	return Snapshot{
		Entity:  []byte(`{"id":"` + tableID + `","name":"orders","fullyQualifiedName":"svc.db.schema.orders","version":0.2,"deleted":false,"updatedAt":9007199254740993,"processedLineage":false,"entityStatus":"Unprocessed","columns":[{"name":"id","dataType":"BIGINT","children":[]}],"databaseSchema":{"id":"schema-id"},"database":{"id":"db-id"},"serviceType":"Mysql","votes":{"upVotes":0}}`),
		Service: []byte(`{"id":"service-id","name":"svc","type":"databaseService"}`),
		BaseURL: "https://metadata.example.test",
	}
}

func TestResourcePermissionsCannotGrantNativeAdminAccess(t *testing.T) {
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/v1/permissions/") {
			io.WriteString(w, `{"resource":"table","permissions":[{"operation":"ViewBasic","access":"allow"},{"operation":"ViewAll","access":"allow"}]}`)
			return
		}
		w.WriteHeader(403)
	}))
	defer java.Close()
	origin, _ := url.Parse(java.URL)
	h := &Handler{Java: origin, Client: java.Client(), Read: func(context.Context, string) (Snapshot, error) {
		t.Error("non-admin reached a newer SQL snapshot")
		return plain(), nil
	}, Fallback: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(403)
		io.WriteString(w, "current Java policy decision")
	})}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/tables/"+tableID, nil))
	if w.Code != 403 || w.Body.String() != "current Java policy decision" {
		t.Fatal("non-admin authorization was not delegated entirely to Java")
	}
}

func TestNativeConcurrencyIsBounded(t *testing.T) {
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, adminSetting)
	}))
	defer java.Close()
	backend, _ := url.Parse(java.URL)
	entered, release := make(chan struct{}, 4), make(chan struct{})
	var once sync.Once
	unblock := func() { once.Do(func() { close(release) }) }
	defer unblock()
	h := &Handler{Java: backend, Client: java.Client(), Fallback: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(418) }), Read: func(ctx context.Context, _ string) (Snapshot, error) {
		entered <- struct{}{}
		select {
		case <-release:
			return plain(), nil
		case <-ctx.Done():
			return Snapshot{}, ctx.Err()
		}
	}}
	var running sync.WaitGroup
	for range 4 {
		running.Add(1)
		go func() {
			defer running.Done()
			h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/api/v1/tables/"+tableID, nil))
		}()
	}
	defer running.Wait()
	defer unblock()
	for range 4 {
		select {
		case <-entered:
		case <-time.After(3 * time.Second):
			t.Fatal("native requests did not enter")
		}
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/tables/"+tableID, nil))
	if w.Code != 418 {
		t.Fatalf("overflow did not use Java fallback: %d", w.Code)
	}
	if len(entered) != 0 {
		t.Fatal("overflow reached PostgreSQL despite the native limit")
	}
}

func TestTableReadDelegatesPermissionsAndPreservesNumbers(t *testing.T) {
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/system/settings/openMetadataBaseUrlConfiguration" || r.Header.Get("Authorization") != "Bearer test" {
			t.Errorf("wrong authorization request: %s", r.URL.Path)
			w.WriteHeader(401)
			return
		}
		w.Header().Set("X-Content-Type-Options", "nosniff")
		io.WriteString(w, adminSetting)
	}))
	defer java.Close()
	backend, _ := url.Parse(java.URL)
	h := &Handler{Java: backend, Client: java.Client(), Fallback: http.NotFoundHandler(), Read: func(context.Context, string) (Snapshot, error) { return plain(), nil }}
	r := httptest.NewRequest("GET", "/api/v1/tables/"+tableID+"?fields=owners,tags", nil)
	r.Header.Set("Authorization", "Bearer test")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != 200 || !bytes.Contains(w.Body.Bytes(), []byte(`9007199254740993`)) || !bytes.Contains(w.Body.Bytes(), []byte(`"tags":[]`)) {
		t.Fatalf("native response: %d %s", w.Code, w.Body.String())
	}
	var body map[string]json.RawMessage
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if _, ok := body["votes"]; ok {
		t.Fatal("unrequested votes leaked")
	}
	if string(body["owners"]) != "[]" || string(body["tags"]) != "[]" {
		t.Fatal("requested empty relationships omitted")
	}
	if string(body["href"]) != `"https://metadata.example.test/api/v1/tables/`+tableID+`"` || w.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatal("links or security headers differ")
	}
}

func TestUnsupportedOrUnprivilegedCasesUseOriginalJavaRequest(t *testing.T) {
	for _, scenario := range []string{"denied", "conditional", "malformed", "db-error", "enriched", "unknown-field", "unknown-reference", "missing-service-type", "legacy-column", "stored-service", "incomplete-history", "unknown-history", "unknown-change", "oversized-service", "oversized-output", "encoding-quality", "encoding-wildcard", "unknown-query", "persona", "impersonation", "persona-empty-first", "impersonation-empty-first", "bad-id", "post"} {
		t.Run(scenario, func(t *testing.T) {
			java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if scenario == "oversized-output" {
					io.WriteString(w, strings.Replace(adminSetting, "https://metadata.example.test", "https://metadata.example.test/"+strings.Repeat("x", 4000), 1))
					return
				}
				if scenario == "denied" {
					w.WriteHeader(403)
					return
				}
				if scenario == "malformed" {
					io.WriteString(w, "{}")
					return
				}
				if scenario == "conditional" {
					io.WriteString(w, `{"resource":"table","permissions":[{"operation":"ViewAll","access":"conditional-allow"}]}`)
					return
				}
				io.WriteString(w, adminSetting)
			}))
			defer java.Close()
			backend, _ := url.Parse(java.URL)
			r := httptest.NewRequest("GET", "/api/v1/tables/"+tableID+"?fields=owners,tags", nil)
			if scenario == "encoding-quality" {
				r.Header.Set("Accept-Encoding", "gzip;q=0")
			}
			if scenario == "encoding-wildcard" {
				r.Header.Set("Accept-Encoding", "*")
			}
			if scenario == "post" {
				r.Method = "POST"
				r.Body = io.NopCloser(strings.NewReader("original body"))
			}
			if scenario == "bad-id" {
				r.URL.Path += "/versions"
			}
			if scenario == "unknown-query" {
				r.URL.RawQuery += "&include=deleted"
			}
			if scenario == "persona" {
				r.Header.Set("X-OpenMetadata-Persona", "test")
			}
			if scenario == "impersonation" {
				r.Header.Set("X-Impersonate-User", "test")
			}
			if scenario == "persona-empty-first" {
				r.Header.Add("X-OpenMetadata-Persona", "")
				r.Header.Add("X-OpenMetadata-Persona", "test")
			}
			if scenario == "impersonation-empty-first" {
				r.Header.Add("X-Impersonate-User", "")
				r.Header.Add("X-Impersonate-User", "test")
			}
			originalURI := r.URL.String()
			h := &Handler{Java: backend, Client: java.Client(), Read: func(context.Context, string) (Snapshot, error) {
				if scenario == "db-error" {
					return Snapshot{}, errors.New("private database error")
				}
				s := plain()
				switch scenario {
				case "stored-service":
					s.Entity = bytes.Replace(s.Entity, []byte(`"votes":`), []byte(`"service":{"id":"old-service","displayName":"stored name"},"votes":`), 1)
				case "incomplete-history", "unknown-history", "unknown-change":
					history := `{}`
					if scenario == "unknown-history" {
						history = `{"fieldsAdded":[],"fieldsUpdated":[],"fieldsDeleted":[],"previousVersion":0.1,"futureField":true}`
					}
					if scenario == "unknown-change" {
						history = `{"fieldsAdded":[{"name":"description","futureField":true}],"fieldsUpdated":[],"fieldsDeleted":[],"previousVersion":0.1}`
					}
					s.Entity = bytes.Replace(s.Entity, []byte(`"votes":`), []byte(`"changeDescription":`+history+`,"votes":`), 1)
				case "oversized-service":
					s.Service = []byte(`{"id":"service-id","displayName":"` + strings.Repeat("x", 256*1024) + `"}`)
				case "oversized-output":
					s.Entity = bytes.Replace(s.Entity, []byte(`"votes":`), []byte(`"description":"`+strings.Repeat("x", 254*1024)+`","votes":`), 1)
					s.BaseURL = "https://metadata.example.test/" + strings.Repeat("x", 4000)
				}
				if scenario == "enriched" {
					s.Enriched = true
				}
				if scenario == "unknown-field" {
					s.Entity = bytes.Replace(s.Entity, []byte(`"votes":`), []byte(`"newSchemaField":`), 1)
				}
				if scenario == "unknown-reference" {
					s.Service = []byte(`{"id":"service-id","newSchemaField":"private"}`)
				}
				if scenario == "missing-service-type" {
					s.Entity = bytes.Replace(s.Entity, []byte(`,"serviceType":"Mysql"`), nil, 1)
				}
				if scenario == "legacy-column" {
					s.Entity = bytes.Replace(s.Entity, []byte(`"children":[]`), []byte(`"children":null`), 1)
				}
				return s, nil
			}, Fallback: http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
				if request.URL.String() != originalURI {
					t.Error("fallback request changed")
				}
				if scenario == "post" {
					data, _ := io.ReadAll(request.Body)
					if string(data) != "original body" {
						t.Error("fallback body changed")
					}
				}
				w.WriteHeader(418)
				io.WriteString(w, "original Java response")
			})}
			w := httptest.NewRecorder()
			h.ServeHTTP(w, r)
			if w.Code != 418 || w.Body.String() != "original Java response" {
				t.Fatalf("fallback lost: status=%d body_bytes=%d", w.Code, w.Body.Len())
			}
		})
	}
}

func TestNativeGzipPreservesJSONAndNegotiation(t *testing.T) {
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, adminSetting)
	}))
	defer java.Close()
	origin, _ := url.Parse(java.URL)
	h := &Handler{Java: origin, Client: java.Client(), Read: func(context.Context, string) (Snapshot, error) { return plain(), nil }, Fallback: http.NotFoundHandler()}
	for _, encoding := range []string{"", "identity", "gzip", "br, gzip, deflate"} {
		t.Run(encoding, func(t *testing.T) {
			r := httptest.NewRequest("GET", "/api/v1/tables/"+tableID, nil)
			r.Header.Set("Accept-Encoding", encoding)
			w := httptest.NewRecorder()
			h.ServeHTTP(w, r)
			var body io.Reader = w.Body
			if strings.Contains(encoding, "gzip") {
				if w.Header().Get("Content-Encoding") != "gzip" || !strings.Contains(w.Header().Get("Vary"), "Accept-Encoding") {
					t.Fatal("gzip negotiation headers missing")
				}
				reader, err := gzip.NewReader(w.Body)
				if err != nil {
					t.Fatal(err)
				}
				defer reader.Close()
				body = reader
			} else if w.Header().Get("Content-Encoding") != "" {
				t.Fatal("identity response was compressed")
			}
			data, err := io.ReadAll(body)
			if w.Code != 200 || err != nil || !bytes.Contains(data, []byte(`9007199254740993`)) {
				t.Fatal("negotiated JSON differs")
			}
		})
	}
}
