// SPDX-License-Identifier: Apache-2.0

package tableread

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/rafi566/OpenMetadata-Go/openmetadata-go/internal/gateway"
)

func TestLivePermissionsAndEnrichment(t *testing.T) {
	if os.Getenv("GO_TABLE_INTEGRATION") != "1" {
		t.Skip("requires the isolated benchmark fixture")
	}
	backend := os.Getenv("JAVA_BACKEND_URL")
	if backend != "http://api:8585" || os.Getenv("PGHOST") != "postgres" || os.Getenv("PGDATABASE") != "openmetadata_benchmark" {
		t.Fatal("mutation test requires the dedicated local fixture")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	store, err := Open(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Pool.Close()
	var smtp string
	if store.Pool.QueryRow(ctx, `SELECT json->>'enableSmtpServer' FROM openmetadata_settings WHERE configtype='emailConfiguration'`).Scan(&smtp) != nil || smtp != "false" {
		t.Fatal("fixture SMTP must be disabled before creating test users")
	}
	proxy, err := gateway.New(backend)
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Transport.(*http.Transport).CloseIdleConnections()
	client := &http.Client{Transport: proxy.Transport, Timeout: 10 * time.Second}
	call := func(method, path, token string, body any) (int, any) {
		t.Helper()
		var raw []byte
		if body != nil {
			raw, err = json.Marshal(body)
			if err != nil {
				t.Fatal(err)
			}
		}
		r, _ := http.NewRequest(method, backend+"/api/v1"+path, bytes.NewReader(raw))
		if token != "" {
			r.Header.Set("Authorization", "Bearer "+token)
		}
		r.Header.Set("Content-Type", "application/json")
		if method == "PATCH" {
			r.Header.Set("Content-Type", "application/json-patch+json")
		}
		response, err := client.Do(r)
		if err != nil {
			t.Fatal("fixture HTTP request failed")
		}
		defer response.Body.Close()
		return response.StatusCode, decodeJSON(t, response.Body)
	}
	login := func(email, password string) string {
		t.Helper()
		status, body := call("POST", "/users/login", "", map[string]any{"email": email, "password": base64.StdEncoding.EncodeToString([]byte(password))})
		if status != 200 {
			t.Fatal("fixture login failed")
		}
		return body.(map[string]any)["accessToken"].(string)
	}
	admin := login("admin@open-metadata.org", "admin")
	post := func(path string, body any) map[string]any {
		t.Helper()
		status, result := call("POST", path, admin, body)
		if status != 201 && status != 200 {
			t.Fatalf("fixture setup failed at %s: %d", path, status)
		}
		return result.(map[string]any)
	}
	suffix := strings.ToLower(rand.Text())
	password := "Aa1!" + rand.Text()
	readerName := "native-reader-" + suffix
	reader := post("/users", map[string]any{"name": readerName, "email": readerName + "@example.invalid", "isAdmin": false, "isBot": false, "createPasswordType": "ADMIN_CREATE", "password": password, "confirmPassword": password})
	readerToken := login(readerName+"@example.invalid", password)
	policyName := "native-deny-" + suffix
	post("/policies", map[string]any{"name": policyName, "rules": []any{map[string]any{"name": "DenyTableReads", "resources": []string{"table"}, "operations": []string{"ViewAll", "ViewBasic"}, "effect": "deny"}}})
	role := post("/roles", map[string]any{"name": "native-denied-" + suffix, "policies": []string{policyName}})
	deniedName := "native-denied-" + suffix
	post("/users", map[string]any{"name": deniedName, "email": deniedName + "@example.invalid", "isAdmin": false, "isBot": false, "roles": []any{role["id"]}, "createPasswordType": "ADMIN_CREATE", "password": password, "confirmPassword": password})
	deniedToken := login(deniedName+"@example.invalid", password)
	origin, _ := url.Parse(backend)
	native, fallback := 0, 0
	h := &Handler{Java: origin, Client: client, Read: func(ctx context.Context, id string) (Snapshot, error) { native++; return store.Read(ctx, id) }, Fallback: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fallback++; proxy.ServeHTTP(w, r) })}
	check := func(token string, wantStatus int, wantFallback bool) map[string]any {
		t.Helper()
		before := fallback
		r := httptest.NewRequest("GET", backend+"/api/v1/tables/"+tableID+"?fields=owners,tags", nil)
		r.Header.Set("Authorization", "Bearer "+token)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		status, expected := call("GET", "/tables/"+tableID+"?fields=owners,tags", token, nil)
		actual := decodeJSON(t, w.Body)
		if w.Code != wantStatus || status != wantStatus || !reflect.DeepEqual(actual, expected) {
			t.Fatalf("Java/Go contract mismatch for expected status %d", wantStatus)
		}
		if (fallback > before) != wantFallback {
			t.Fatal("wrong native/fallback path")
		}
		return actual.(map[string]any)
	}
	check(admin, 200, false)
	if native != 1 {
		t.Fatal("verified admin did not read through Go")
	}
	check(readerToken, 200, true)
	if native != 1 {
		t.Fatal("non-admin reached Go storage")
	}
	check(deniedToken, 403, true)
	patch := func(field string, value any) {
		t.Helper()
		status, _ := call("PATCH", "/tables/"+tableID, admin, []any{map[string]any{"op": "add", "path": "/" + field, "value": value}})
		if status != 200 {
			t.Fatalf("fixture %s patch failed: %d", field, status)
		}
	}
	patch("owners", []any{map[string]any{"id": reader["id"], "type": "user"}})
	defer patch("owners", []any{})
	if len(check(admin, 200, true)["owners"].([]any)) != 1 {
		t.Fatal("owner metadata lost")
	}
	patch("owners", []any{})
	patch("tags", []any{map[string]any{"tagFQN": "PII.Sensitive", "source": "Classification", "labelType": "Manual", "state": "Confirmed"}})
	defer patch("tags", []any{})
	if len(check(admin, 200, true)["tags"].([]any)) != 1 {
		t.Fatal("tag metadata lost")
	}
	patch("tags", []any{})
}
