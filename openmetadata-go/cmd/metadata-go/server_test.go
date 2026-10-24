// SPDX-License-Identifier: Apache-2.0

package main

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/rafi566/OpenMetadata-Go/openmetadata-go/internal/gateway"
)

type observedListener struct {
	net.Listener
	closed chan struct{}
	once   sync.Once
}

func (l *observedListener) Close() error {
	err := l.Listener.Close()
	l.once.Do(func() { close(l.closed) })
	return err
}

func TestShutdownDrainsAndClosesUpgradedConnections(t *testing.T) {
	for _, keepOpen := range []bool{false, true} {
		t.Run(fmt.Sprintf("keepOpen=%t", keepOpen), func(t *testing.T) {
			backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				connection, buffered, err := w.(http.Hijacker).Hijack()
				if err != nil {
					t.Error(err)
					return
				}
				defer connection.Close()
				_, _ = io.WriteString(buffered, "HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n")
				_ = buffered.Flush()
				_, _ = io.Copy(io.Discard, connection)
			}))
			defer backend.Close()
			proxy, err := gateway.New(backend.URL)
			if err != nil {
				t.Fatal(err)
			}
			defer proxy.Transport.(*http.Transport).CloseIdleConnections()
			listener, err := net.Listen("tcp", "127.0.0.1:0")
			if err != nil {
				t.Fatal(err)
			}
			tracked := &observedListener{Listener: listener, closed: make(chan struct{})}
			defer tracked.Close()
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			stopped := make(chan error, 1)
			go func() { stopped <- serve(ctx, tracked, proxy, 100*time.Millisecond) }()
			connection, err := net.DialTimeout("tcp", listener.Addr().String(), time.Second)
			if err != nil {
				t.Fatal(err)
			}
			defer connection.Close()
			_ = connection.SetDeadline(time.Now().Add(2 * time.Second))
			_, _ = fmt.Fprintf(connection, "GET /api/v1/push/feed/test HTTP/1.1\r\nHost: %s\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n", listener.Addr())
			reader := bufio.NewReader(connection)
			response, err := http.ReadResponse(reader, nil)
			if err != nil || response.StatusCode != http.StatusSwitchingProtocols {
				t.Fatalf("upgrade failed: %v, %v", response, err)
			}
			cancel()
			select {
			case <-tracked.closed:
			case <-time.After(2 * time.Second):
				t.Fatal("shutdown did not stop accepting connections")
			}
			if !keepOpen {
				_ = connection.Close()
			}
			select {
			case err := <-stopped:
				if keepOpen && !errors.Is(err, context.DeadlineExceeded) || !keepOpen && err != nil {
					t.Fatalf("shutdown ignored upgraded connection: keepOpen=%t error=%v", keepOpen, err)
				}
			case <-time.After(2 * time.Second):
				t.Fatal("shutdown exceeded its deadline")
			}
			if keepOpen {
				if _, err := reader.ReadByte(); !errors.Is(err, io.EOF) {
					t.Fatalf("upgrade was not closed at the deadline: %v", err)
				}
			}
		})
	}
}
