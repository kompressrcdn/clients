package kompressr

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"math/rand/v2"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

const maxTimeout = time.Duration(2147483647) * time.Millisecond
const maxResponseBytes = 2 * 1024 * 1024

type transport struct {
	key, apiURL, uploadURL        string
	read, write                   *http.Client
	requestTimeout, uploadTimeout time.Duration
	retries                       int
}
type Endpoints struct {
	APIBaseURL    string
	UploadBaseURL string
}

// ResolveEndpoints validates origins without network access. An unknown API
// origin defaults uploads to itself unless an upload origin is supplied.
func ResolveEndpoints(api, upload string) (Endpoints, error) {
	if api == "" {
		api = ProductionAPIURL
	}
	var err error
	if api, err = origin(api); err != nil {
		return Endpoints{}, err
	}
	if upload == "" {
		upload = api
		if api == ProductionAPIURL {
			upload = ProductionUploadURL
		}
	}
	if upload, err = origin(upload); err != nil {
		return Endpoints{}, err
	}
	return Endpoints{api, upload}, nil
}
func origin(s string) (string, error) {
	u, err := url.Parse(s)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil || u.Opaque != "" || (u.Path != "" && u.Path != "/") || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || strings.Contains(s, "#") {
		return "", invalid("Base URL must be an absolute HTTP(S) origin without credentials, path, query or fragment.")
	}
	if u.Hostname() == "" {
		return "", invalid("Base URL must contain a hostname.")
	}
	u.Scheme = strings.ToLower(u.Scheme)
	u.Host = strings.ToLower(u.Host)
	if (u.Scheme == "https" && u.Port() == "443") || (u.Scheme == "http" && u.Port() == "80") {
		u.Host = u.Hostname()
		if strings.Contains(u.Host, ":") {
			u.Host = "[" + u.Host + "]"
		}
	}
	return u.Scheme + "://" + u.Host, nil
}
func timeoutValue(value, fallback time.Duration) (time.Duration, error) {
	if value == 0 {
		return fallback, nil
	}
	if value < 0 || value > maxTimeout {
		return 0, invalid("Timeout must be positive and no greater than 2147483647 milliseconds.")
	}
	return value, nil
}
func newTransport(c Config) (*transport, error) {
	if strings.TrimSpace(c.APIKey) == "" || strings.ContainsAny(c.APIKey, "\r\n") {
		return nil, invalid("Supply a nonempty API key on your trusted backend.")
	}
	for _, r := range c.APIKey {
		if r < 32 || r == 127 {
			return nil, invalid("API key contains an invalid header character.")
		}
	}
	endpoints, err := ResolveEndpoints(c.APIBaseURL, c.UploadBaseURL)
	if err != nil {
		return nil, err
	}
	request, err := timeoutValue(c.RequestTimeout, 30*time.Second)
	if err != nil {
		return nil, err
	}
	upload, err := timeoutValue(c.UploadTimeout, 10*time.Minute)
	if err != nil {
		return nil, err
	}
	retries := 2
	if c.MaxReadRetries != nil {
		retries = *c.MaxReadRetries
	}
	if retries < 0 || retries > 5 {
		return nil, invalid("MaxReadRetries must be between zero and five.")
	}
	var base *http.Transport
	if c.HTTPTransport != nil {
		base = c.HTTPTransport.Clone()
	} else {
		base = http.DefaultTransport.(*http.Transport).Clone()
	}
	write := base.Clone()
	// net/http can replay requests on reused connections and HTTP/2 streams.
	// Writes use fresh HTTP/1 connections, with no rewind function or idempotency
	// header, so transport retries cannot repeat an uncertain mutation.
	write.DisableKeepAlives = true
	write.ForceAttemptHTTP2 = false
	write.TLSNextProto = map[string]func(string, *tls.Conn) http.RoundTripper{}
	write.Protocols = new(http.Protocols)
	write.Protocols.SetHTTP1(true)
	if write.TLSClientConfig != nil {
		write.TLSClientConfig = write.TLSClientConfig.Clone()
		write.TLSClientConfig.NextProtos = []string{"http/1.1"}
	}
	policy := func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	return &transport{key: c.APIKey, apiURL: endpoints.APIBaseURL, uploadURL: endpoints.UploadBaseURL, read: &http.Client{Transport: base, CheckRedirect: policy}, write: &http.Client{Transport: write, CheckRedirect: policy}, requestTimeout: request, uploadTimeout: upload, retries: retries}, nil
}
func (t *transport) close() { t.read.CloseIdleConnections(); t.write.CloseIdleConnections() }

type request struct {
	method, path      string
	body              io.ReadCloser
	length            int64
	contentType       string
	upload, recoverID bool
	assetID           int64
	options           RequestOptions
}

func jsonRequest(method, path string, value any, options RequestOptions) (request, error) {
	r := request{method: method, path: path, options: options}
	if value != nil {
		b, err := encodeJSON(value)
		if err != nil {
			return r, invalid("Request data cannot be encoded as JSON.")
		}
		r.body = io.NopCloser(bytes.NewReader(b))
		r.length = int64(len(b))
		r.contentType = "application/json"
	}
	return r, nil
}
func success(raw json.RawMessage) (map[string]json.RawMessage, error) {
	m, err := object(raw)
	if err != nil {
		return nil, err
	}
	if string(m["success"]) != "true" {
		return nil, badResponse()
	}
	return m, nil
}
func dataEnvelope(raw json.RawMessage) (json.RawMessage, error) {
	m, err := success(raw)
	if err != nil {
		return nil, err
	}
	d, ok := m["data"]
	if !ok {
		return nil, badResponse()
	}
	return d, nil
}
func perform[T any](parent context.Context, t *transport, r request, parse func(json.RawMessage) (T, error)) (zero T, err error) {
	if parent == nil {
		if r.body != nil {
			r.body.Close()
		}
		return zero, invalid("Supply a non-nil context.")
	}
	if r.body != nil {
		defer r.body.Close()
	}
	fallback := t.requestTimeout
	if r.upload {
		fallback = t.uploadTimeout
	}
	timeout, err := timeoutValue(r.options.Timeout, fallback)
	if err != nil {
		return zero, err
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()
	// Close streaming sources as soon as cancellation fires, including readers
	// currently blocked inside Read. Waiting until Do returns can deadlock on a
	// source whose Close is required to unblock its active Read.
	if r.body != nil {
		stopClose := context.AfterFunc(ctx, func() { _ = r.body.Close() })
		defer stopClose()
	}
	isRead := r.method == "GET"
	dispatched := false
	status := 0
	assetID := r.assetID
	contextual := func(kind ErrorKind) *Error {
		code, message := "NETWORK_ERROR", "Unable to reach Kompressr. Check the configured endpoint and connection."
		if kind == KindTimeout {
			code, message = "REQUEST_TIMEOUT", "Request timed out; inspect a write's outcome before retrying."
		}
		if kind == KindCancelled {
			code, message = "REQUEST_CANCELLED", "Request cancelled."
		}
		return &Error{Kind: kind, Code: code, Message: message, Status: status, AssetID: assetID, MayHaveSucceeded: dispatched && !isRead}
	}
	stopped := func() *Error {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return contextual(KindTimeout)
		}
		return contextual(KindCancelled)
	}
	for attempt := 0; ; attempt++ {
		status = 0
		if ctx.Err() != nil {
			return zero, stopped()
		}
		origin := t.apiURL
		if r.upload {
			origin = t.uploadURL
		}
		req, reqErr := http.NewRequestWithContext(ctx, r.method, origin+r.path, r.body)
		if reqErr != nil {
			return zero, invalid("Could not construct request.")
		}
		req.GetBody = nil
		req.ContentLength = r.length
		req.Header.Set("Authorization", "Bearer "+t.key)
		req.Header.Set("Accept", "application/json")
		req.Header.Set("User-Agent", "kompressr-go/"+Version)
		if r.contentType != "" {
			req.Header.Set("Content-Type", r.contentType)
		}
		if ctx.Err() != nil {
			return zero, stopped()
		}
		dispatched = true
		httpClient := t.write
		if isRead {
			httpClient = t.read
		}
		resp, doErr := httpClient.Do(req)
		var failure *Error
		if doErr != nil {
			failure = contextual(KindNetwork)
		} else {
			status = resp.StatusCode
			raw, readErr := io.ReadAll(io.LimitReader(resp.Body, maxResponseBytes+1))
			resp.Body.Close()
			if ctx.Err() != nil {
				return zero, stopped()
			}
			if readErr != nil {
				failure = contextual(KindNetwork)
			} else {
				ok := status >= 200 && status < 300
				valid := len(raw) <= maxResponseBytes && json.Valid(raw)
				var env map[string]json.RawMessage
				if valid {
					env, _ = object(raw)
				}
				if r.recoverID && ok && env != nil && string(env["success"]) == "true" {
					if d, e := object(env["data"]); e == nil {
						var id int64
						if json.Unmarshal(d["asset_id"], &id) == nil && validID(id) {
							assetID = id
						}
					}
				}
				if !ok || (env != nil && string(env["success"]) == "false") {
					var message, code string
					if env != nil {
						_ = json.Unmarshal(env["error"], &message)
						_ = json.Unmarshal(env["code"], &code)
					}
					failure = httpFailure(status, message, code, t.key)
					failure.AssetID = assetID
					failure.MayHaveSucceeded = !isRead && (ok || status >= 500)
					failure.RetryAfter = retryAfter(resp.Header.Get("Retry-After"), env)
					// A redirect may follow an accepted write; never follow or replay it.
					if status >= 300 && status < 400 {
						failure.MayHaveSucceeded = !isRead
					}
				} else if !valid {
					failure = badResponse()
				} else {
					var parsed T
					parsed, err = parse(raw)
					if err == nil {
						if ctx.Err() != nil {
							return zero, stopped()
						}
						return parsed, nil
					}
					if !errors.As(err, &failure) {
						failure = badResponse()
					}
				}
			}
		}
		if ctx.Err() != nil {
			return zero, stopped()
		}
		if failure.Kind == KindInvalidResponse {
			failure.Status = status
			failure.AssetID = assetID
			failure.MayHaveSucceeded = dispatched && !isRead
		}
		transient := failure.Kind == KindNetwork || failure.Kind == KindAPI && (status == 429 || status == 502 || status == 503 || status == 504)
		if !isRead || !transient || attempt >= t.retries {
			return zero, failure
		}
		backoff := time.Duration(250*(1<<attempt))*time.Millisecond + time.Duration(rand.IntN(100))*time.Millisecond
		if failure.RetryAfter > backoff {
			backoff = failure.RetryAfter
		}
		if waitContext(ctx, backoff) != nil {
			return zero, stopped()
		}
	}
}
func waitContext(ctx context.Context, d time.Duration) error {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
func retryAfter(header string, env map[string]json.RawMessage) time.Duration {
	if header != "" {
		if n, err := strconv.ParseFloat(strings.TrimSpace(header), 64); err == nil && n >= 0 && !math.IsNaN(n) && !math.IsInf(n, 0) {
			return secondsDuration(n)
		}
		if t, err := http.ParseTime(header); err == nil {
			d := time.Until(t)
			if d < 0 {
				return 0
			}
			return d
		}
	}
	var seconds float64
	if v, ok := env["retry_after"]; ok && json.Unmarshal(v, &seconds) == nil && seconds >= 0 {
		return secondsDuration(seconds)
	}
	return 0
}
func secondsDuration(n float64) time.Duration {
	if n >= float64(math.MaxInt64)/float64(time.Second) {
		return time.Duration(math.MaxInt64)
	}
	return time.Duration(n * float64(time.Second))
}
func (t *transport) String() string { return fmt.Sprintf("kompressr transport (%s)", t.apiURL) }
