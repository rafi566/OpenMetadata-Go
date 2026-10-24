// SPDX-License-Identifier: Apache-2.0

package main

import (
	"context"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/rafi566/OpenMetadata-Go/openmetadata-go/internal/gateway"
	"github.com/rafi566/OpenMetadata-Go/openmetadata-go/internal/tableread"
)

func main() {
	if err := run(); err != nil {
		slog.Error("gateway stopped", "error", err)
		os.Exit(1)
	}
}

func run() error {
	proxy, err := gateway.New(os.Getenv("JAVA_BACKEND_URL"))
	if err != nil {
		return err
	}
	defer proxy.Transport.(*http.Transport).CloseIdleConnections()
	var handler http.Handler = proxy
	if os.Getenv("GO_TABLE_READS_ENABLED") == "true" {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		store, err := tableread.Open(ctx)
		cancel()
		if err != nil {
			return err
		}
		defer store.Pool.Close()
		origin, _ := url.Parse(os.Getenv("JAVA_BACKEND_URL"))
		handler = &tableread.Handler{
			Java:     origin,
			Client:   &http.Client{Transport: proxy.Transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }},
			Fallback: proxy, Read: store.Read,
		}
	}
	address := os.Getenv("HTTP_ADDR")
	if address == "" {
		address = ":8585"
	}
	listener, err := net.Listen("tcp", address)
	if err != nil {
		return err
	}
	defer listener.Close()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	return serve(ctx, listener, handler, 30*time.Second)
}
