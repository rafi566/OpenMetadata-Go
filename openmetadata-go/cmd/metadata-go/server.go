// SPDX-License-Identifier: Apache-2.0

package main

import (
	"context"
	"errors"
	"net"
	"net/http"
	"sync"
	"time"
)

func serve(ctx context.Context, listener net.Listener, handler http.Handler, shutdownTimeout time.Duration) error {
	ctx, stop := context.WithCancel(ctx)
	defer stop()
	requests, cancelRequests := context.WithCancel(context.Background())
	defer cancelRequests()
	var active sync.WaitGroup
	server := &http.Server{
		Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			active.Add(1)
			defer active.Done()
			handler.ServeHTTP(w, r)
		}),
		BaseContext:       func(net.Listener) context.Context { return requests },
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       90 * time.Second,
	}
	stopped := make(chan error, 1)
	go func() {
		<-ctx.Done()
		deadline, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
		defer cancel()
		err := server.Shutdown(deadline)
		// Shutdown omits hijacked WebSockets; their proxy handlers must drain too.
		if err == nil {
			drained := make(chan struct{})
			go func() {
				active.Wait()
				close(drained)
			}()
			select {
			case <-drained:
			case <-deadline.Done():
				err = deadline.Err()
			}
		}
		if err != nil {
			cancelRequests()
			_ = server.Close()
		}
		stopped <- err
	}()
	err := server.Serve(listener)
	if !errors.Is(err, http.ErrServerClosed) {
		stop()
		<-stopped
		return err
	}
	return <-stopped
}
