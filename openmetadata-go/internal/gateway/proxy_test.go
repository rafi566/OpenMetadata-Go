// SPDX-License-Identifier: Apache-2.0

package gateway

import (
	"bufio"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestFallbackPreservesAPIRequestAndResponse(t *testing.T) {
	for _, status := range []int{http.StatusOK, http.StatusUnauthorized, http.StatusForbidden, http.StatusNotFound} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			const path = "/api/v1/tables/name/database.%22quoted%22.table?fields=owners%2Ctags&include=all"
			const patch = `[{"op":"add","path":"/extension/exact","value":9007199254740993}]`
			const body = `{"code":123,"exact":9007199254740993,"zero":0,"null":null}`
			observed := make(chan bool, 1)
			backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				data, err := io.ReadAll(r.Body)
				observed <- err == nil && string(data) == patch && r.Method == http.MethodPatch &&
					r.RequestURI == path && r.Header.Get("Authorization") == "Bearer test-token" &&
					r.Header.Get("Content-Type") == "application/json-patch+json" &&
					r.Header.Get("Accept-Encoding") == "" &&
					r.Header.Get("X-Impersonate-User") == "test-user" &&
					r.Header.Get("X-OpenMetadata-Persona") == "test-persona"
				w.Header().Set("Content-Type", "application/json")
				w.Header().Set("Cache-Control", "no-store")
				w.Header().Add("Set-Cookie", "session=test; HttpOnly; SameSite=Strict")
				w.WriteHeader(status)
				_, _ = io.WriteString(w, body)
			}))
			defer backend.Close()
			proxy, err := New(backend.URL)
			if err != nil {
				t.Fatal(err)
			}
			defer proxy.Transport.(*http.Transport).CloseIdleConnections()
			front := httptest.NewServer(proxy)
			defer front.Close()
			request, err := http.NewRequest(http.MethodPatch, front.URL+path, strings.NewReader(patch))
			if err != nil {
				t.Fatal(err)
			}
			request.Header.Set("Authorization", "Bearer test-token")
			request.Header.Set("Content-Type", "application/json-patch+json")
			request.Header.Set("X-Impersonate-User", "test-user")
			request.Header.Set("X-OpenMetadata-Persona", "test-persona")
			clientTransport := http.DefaultTransport.(*http.Transport).Clone()
			clientTransport.DisableCompression = true
			defer clientTransport.CloseIdleConnections()
			client := &http.Client{Timeout: 5 * time.Second, Transport: clientTransport}
			response, err := client.Do(request)
			if err != nil {
				t.Fatal(err)
			}
			defer response.Body.Close()
			data, err := io.ReadAll(response.Body)
			if err != nil || response.StatusCode != status || string(data) != body ||
				response.Header.Get("Cache-Control") != "no-store" ||
				response.Header.Get("Set-Cookie") != "session=test; HttpOnly; SameSite=Strict" {
				t.Fatalf("fallback changed response: status=%d headers=%v body=%s error=%v", response.StatusCode, response.Header, data, err)
			}
			if !<-observed {
				t.Fatal("fallback changed the method, encoded URI, body or authorization context")
			}
		})
	}
}

func TestFallbackStreamsEventsBeforeBackendCompletes(t *testing.T) {
	release := make(chan struct{})
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "data: first\n\n")
		w.(http.Flusher).Flush()
		select {
		case <-release:
		case <-r.Context().Done():
		}
	}))
	defer backend.Close()
	defer close(release)
	proxy, err := New(backend.URL)
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Transport.(*http.Transport).CloseIdleConnections()
	front := httptest.NewServer(proxy)
	defer front.Close()
	client := &http.Client{Timeout: 2 * time.Second}
	response, err := client.Get(front.URL + "/api/v1/events/subscribe")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	line, err := bufio.NewReader(response.Body).ReadString('\n')
	if err != nil || line != "data: first\n" {
		t.Fatalf("event was buffered until completion: %q, %v", line, err)
	}
}

func TestInvalidBackendIsRejected(t *testing.T) {
	for _, target := range []string{"", "/api", "file:///tmp/backend", "http://", "http://user:password@backend", "http://backend?token=secret", "http://backend#fragment", "http://backend/prefix"} {
		if _, err := New(target); err == nil {
			t.Errorf("accepted invalid backend %q", target)
		}
	}
}

func TestUnavailableBackendDoesNotExposeRequestOrTarget(t *testing.T) {
	backend := httptest.NewServer(http.NotFoundHandler())
	backend.Close()
	proxy, err := New(backend.URL)
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Transport.(*http.Transport).CloseIdleConnections()
	front := httptest.NewServer(proxy)
	defer front.Close()
	client := &http.Client{Timeout: 2 * time.Second}
	response, err := client.Get(front.URL + "/api/v1/search/query?q=private-query-value")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil || response.StatusCode != http.StatusBadGateway ||
		strings.Contains(string(body), "private-query-value") || strings.Contains(string(body), backend.URL) {
		t.Fatalf("unsafe backend error: status=%d body=%s error=%v", response.StatusCode, body, err)
	}
}
