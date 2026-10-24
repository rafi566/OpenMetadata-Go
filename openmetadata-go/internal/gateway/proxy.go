// SPDX-License-Identifier: Apache-2.0

package gateway

import (
	"errors"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
)

// New keeps the Java API available while individual paths are migrated to Go.
func New(backend string) (*httputil.ReverseProxy, error) {
	target, err := url.Parse(backend)
	if err != nil || target.Host == "" || (target.Scheme != "http" && target.Scheme != "https") ||
		target.User != nil || target.RawQuery != "" || target.Fragment != "" ||
		(target.Path != "" && target.Path != "/") {
		return nil, errors.New("configure a Java backend HTTP(S) origin without credentials, query or path")
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	// Match the original server's 64 active-request budget and bound its connection pool.
	transport.MaxConnsPerHost = 64
	transport.MaxIdleConns = 64
	transport.MaxIdleConnsPerHost = 64
	transport.DisableCompression = true
	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.Transport = transport
	proxy.ErrorHandler = func(w http.ResponseWriter, _ *http.Request, _ error) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		_, _ = io.WriteString(w, `{"code":502,"message":"Java backend unavailable"}`)
	}
	return proxy, nil
}
