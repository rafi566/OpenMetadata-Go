// SPDX-License-Identifier: Apache-2.0

package main

import (
	"context"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/rafi566/OpenMetadata-Go/openmetadata-go/internal/gateway"
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
	return serve(ctx, listener, proxy, 30*time.Second)
}
