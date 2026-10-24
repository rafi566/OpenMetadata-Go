// SPDX-License-Identifier: Apache-2.0

package tableread

import (
	"compress/gzip"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/rafi566/OpenMetadata-Go/openmetadata-go/internal/gateway"
)

func TestLiveStoreRejectsOversizedServiceReference(t *testing.T) {
	if os.Getenv("GO_TABLE_INTEGRATION") != "1" {
		t.Skip("requires the isolated benchmark fixture")
	}
	if os.Getenv("PGHOST") != "postgres" || os.Getenv("PGDATABASE") != "openmetadata_benchmark" {
		t.Fatal("mutation test requires the dedicated local fixture")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	store, err := Open(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Pool.Close()
	tx, err := store.Pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(context.Background())
	_, err = tx.Exec(ctx, `UPDATE dbservice_entity SET json=jsonb_set(json::jsonb, '{displayName}', to_jsonb($1::text)) WHERE name='test-service-distributed'`, strings.Repeat("x", 256*1024))
	if err != nil {
		t.Fatal(err)
	}
	var snapshot Snapshot
	err = tx.QueryRow(ctx, plainTableSQL, tableID).Scan(&snapshot.Entity, &snapshot.Service, &snapshot.Enriched)
	if !errors.Is(err, pgx.ErrNoRows) {
		t.Fatalf("oversized service reference was transferred: error=%v service_bytes=%d", err, len(snapshot.Service))
	}
}

func TestLiveTableReadMatchesJava(t *testing.T) {
	if os.Getenv("GO_TABLE_INTEGRATION") != "1" {
		t.Skip("requires the isolated benchmark fixture")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	store, err := Open(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Pool.Close()
	snapshot, err := store.Read(ctx, tableID)
	if err != nil {
		t.Fatal(err)
	}
	if snapshot.Enriched {
		t.Fatal("plain fixture unexpectedly classified as enriched")
	}
	if _, err = store.Pool.Exec(ctx, "CREATE TEMP TABLE native_must_be_read_only (id int)"); err == nil {
		t.Fatal("Go connection was allowed to write")
	}
	backend := os.Getenv("JAVA_BACKEND_URL")
	proxy, err := gateway.New(backend)
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Transport.(*http.Transport).CloseIdleConnections()
	client := &http.Client{Transport: proxy.Transport, Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	login, err := client.Post(backend+"/api/v1/users/login", "application/json", strings.NewReader(`{"email":"admin@open-metadata.org","password":"YWRtaW4="}`))
	if err != nil {
		t.Fatal(err)
	}
	var credentials struct {
		AccessToken string `json:"accessToken"`
	}
	err = json.NewDecoder(login.Body).Decode(&credentials)
	login.Body.Close()
	if err != nil || login.StatusCode != 200 || credentials.AccessToken == "" {
		t.Fatal("fixture login failed")
	}
	origin, _ := url.Parse(backend)
	reads := 0
	handler := &Handler{Java: origin, Client: client, Fallback: proxy, Read: func(ctx context.Context, id string) (Snapshot, error) { reads++; return store.Read(ctx, id) }}
	for _, query := range []string{"", "?fields=owners,tags"} {
		for _, encoding := range []string{"", "gzip"} {
			r := httptest.NewRequest("GET", backend+"/api/v1/tables/"+tableID+query, nil)
			r.Header.Set("Authorization", "Bearer "+credentials.AccessToken)
			r.Header.Set("Accept-Encoding", encoding)
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, r)
			request, _ := http.NewRequest("GET", r.URL.String(), nil)
			request.Header = r.Header.Clone()
			direct, err := client.Do(request)
			if err != nil {
				t.Fatal(err)
			}
			var actualBody io.Reader = w.Body
			var expectedBody io.Reader = direct.Body
			if encoding == "gzip" {
				if w.Header().Get("Content-Encoding") != "gzip" || direct.Header.Get("Content-Encoding") != "gzip" {
					t.Fatal("native/Java gzip negotiation differs")
				}
				actualReader, err := gzip.NewReader(w.Body)
				if err != nil {
					t.Fatal(err)
				}
				defer actualReader.Close()
				expectedReader, err := gzip.NewReader(direct.Body)
				if err != nil {
					t.Fatal(err)
				}
				defer expectedReader.Close()
				actualBody, expectedBody = actualReader, expectedReader
			}
			actual := decodeJSON(t, actualBody)
			expected := decodeJSON(t, expectedBody)
			direct.Body.Close()
			if w.Code != 200 || direct.StatusCode != 200 || !reflect.DeepEqual(actual, expected) {
				actualBytes, _ := json.Marshal(actual)
				expectedBytes, _ := json.Marshal(expected)
				t.Fatalf("native response differs\nGo: %s\nJava: %s", actualBytes, expectedBytes)
			}
		}
	}
	if reads != 4 {
		t.Fatal("live requests did not execute the Go store")
	}
	for _, token := range []string{"", "invalid"} {
		r := httptest.NewRequest("GET", backend+"/api/v1/tables/"+tableID, nil)
		if token != "" {
			r.Header.Set("Authorization", "Bearer "+token)
		}
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		if w.Code != 401 {
			t.Fatalf("unauthorized table read returned %d", w.Code)
		}
	}
	if reads != 4 {
		t.Fatal("unauthorized request reached Go storage")
	}
}

func decodeJSON(t *testing.T, r io.Reader) any {
	t.Helper()
	decoder := json.NewDecoder(r)
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		t.Fatal(err)
	}
	return value
}
