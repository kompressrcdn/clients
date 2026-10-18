package kompressr

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type mutation struct {
	name    string
	knownID int64
	run     func(*Client) error
}

func mutations() []mutation {
	return []mutation{
		{"upload", 0, func(c *Client) error {
			_, e := c.UploadBytes(background, []byte("abc"), "x.png", UploadOptions{})
			return e
		}},
		{"sign", 42, func(c *Client) error { _, e := c.GeneratePrivateURL(background, 42, PrivateURLOptions{}); return e }},
		{"delete", 42, func(c *Client) error { _, e := c.DeleteAsset(background, 42, RequestOptions{}); return e }},
		{"bulk", 0, func(c *Client) error {
			_, e := c.BulkDeleteAssets(background, []int64{42, 43}, RequestOptions{})
			return e
		}},
		{"create-user", 0, func(c *Client) error {
			_, e := c.Platform.CreateUser(background, CreateUserOptions{CustomerUserID: "customer-1"}, RequestOptions{})
			return e
		}},
		{"update-user", 0, func(c *Client) error {
			_, e := c.Platform.UpdateUser(background, userID, UpdateUserOptions{}, RequestOptions{})
			return e
		}},
		{"suspend", 0, func(c *Client) error { _, e := c.Platform.SuspendUser(background, userID, RequestOptions{}); return e }},
		{"reactivate", 0, func(c *Client) error {
			_, e := c.Platform.ReactivateUser(background, userID, RequestOptions{})
			return e
		}},
		{"create-key", 0, func(c *Client) error {
			_, e := c.Platform.CreateUploadKey(background, userID, CreateKeyOptions{Name: "Runtime"}, RequestOptions{})
			return e
		}},
		{"rotate", 0, func(c *Client) error {
			_, e := c.Platform.RotateUploadKey(background, userID, keyID, RequestOptions{})
			return e
		}},
		{"revoke", 0, func(c *Client) error { return c.Platform.RevokeUploadKey(background, userID, keyID, RequestOptions{}) }},
	}
}
func TestMalformedWritesRemainUncertain(t *testing.T) {
	for _, m := range mutations() {
		for _, broken := range []bool{true, false} {
			t.Run(fmt.Sprintf("%s/broken=%t", m.name, broken), func(t *testing.T) {
				var calls atomic.Int32
				c := files(t, func(w http.ResponseWriter, r *http.Request) {
					io.Copy(io.Discard, r.Body)
					calls.Add(1)
					if broken {
						io.WriteString(w, "{broken")
					} else if m.name == "revoke" {
						respond(w, map[string]any{})
					} else {
						respond(w, envelope(map[string]any{"asset_id": 42, "api_key": "one-time-secret"}))
					}
				})
				e := mustError(t, m.run(c), "INVALID_RESPONSE")
				wantID := m.knownID
				if m.name == "upload" && !broken {
					wantID = 42
				}
				if e.Status != 200 || !e.MayHaveSucceeded || e.AssetID != wantID || calls.Load() != 1 || strings.Contains(fmt.Sprintf("%+v", e), "one-time-secret") {
					t.Fatalf("%#v calls=%d", e, calls.Load())
				}
			})
		}
	}
}
func TestUnsafeUploadIDRecovery(t *testing.T) {
	for _, id := range []any{0, -1, 1.5, float64(MaxAssetID + 1), "42", nil} {
		t.Run(fmt.Sprint(id), func(t *testing.T) {
			c := files(t, func(w http.ResponseWriter, r *http.Request) {
				io.Copy(io.Discard, r.Body)
				respond(w, envelope(map[string]any{"asset_id": id}))
			})
			_, err := c.UploadBytes(background, []byte("x"), "x.png", UploadOptions{})
			e := mustError(t, err, "INVALID_RESPONSE")
			if e.AssetID != 0 || !e.MayHaveSucceeded {
				t.Fatal(e)
			}
		})
	}
}
func TestWrongAssetID(t *testing.T) {
	c := files(t, func(w http.ResponseWriter, r *http.Request) { v := lifecycleFixture(); v["id"] = 43; respond(w, v) })
	_, err := c.DeleteAsset(background, 42, RequestOptions{})
	e := mustError(t, err, "INVALID_RESPONSE")
	if e.AssetID != 42 || !e.MayHaveSucceeded {
		t.Fatal(e)
	}
	_, err = c.GetAsset(background, 42, RequestOptions{})
	e = mustError(t, err, "INVALID_RESPONSE")
	if e.MayHaveSucceeded {
		t.Fatal(e)
	}
}
func TestMalformedReadsAndPreDispatchValidation(t *testing.T) {
	var calls atomic.Int32
	c := files(t, func(w http.ResponseWriter, r *http.Request) { calls.Add(1); io.WriteString(w, "{broken") })
	_, err := c.GetUploadStatus(background, 42, RequestOptions{})
	if mustError(t, err, "INVALID_RESPONSE").MayHaveSucceeded {
		t.Fatal(err)
	}
	_, err = c.BulkDeleteAssets(background, nil, RequestOptions{})
	if mustError(t, err, "INVALID_ARGUMENT").MayHaveSucceeded || calls.Load() != 1 {
		t.Fatal(err)
	}
}
func TestPreCancelledRequestDoesNotDispatch(t *testing.T) {
	var calls atomic.Int32
	c := files(t, func(w http.ResponseWriter, r *http.Request) { calls.Add(1) })
	ctx, cancel := context.WithCancel(background)
	cancel()
	_, err := c.UploadBytes(ctx, []byte("x"), "x.png", UploadOptions{})
	e := mustError(t, err, "REQUEST_CANCELLED")
	if e.MayHaveSucceeded || calls.Load() != 0 || !errors.Is(err, context.Canceled) {
		t.Fatal(e)
	}
	_, err = c.WaitUntilReady(ctx, 42, WaitOptions{})
	e = mustError(t, err, "WAIT_CANCELLED")
	if e.AssetID != 42 || calls.Load() != 0 {
		t.Fatal(e)
	}
}
func TestSlowResponseBodiesBounded(t *testing.T) {
	for _, operation := range []string{"read", "wait", "write"} {
		t.Run(operation, func(t *testing.T) {
			var calls atomic.Int32
			c := files(t, func(w http.ResponseWriter, r *http.Request) {
				io.Copy(io.Discard, r.Body)
				calls.Add(1)
				w.Header().Set("Content-Type", "application/json")
				io.WriteString(w, `{"success":true,"data":`)
				w.(http.Flusher).Flush()
				<-r.Context().Done()
			})
			start := time.Now()
			var err error
			switch operation {
			case "read":
				_, err = c.GetUploadStatus(background, 42, RequestOptions{Timeout: 35 * time.Millisecond})
			case "wait":
				_, err = c.WaitUntilReady(background, 42, WaitOptions{Timeout: 35 * time.Millisecond})
			case "write":
				_, err = c.DeleteAsset(background, 42, RequestOptions{Timeout: 35 * time.Millisecond})
			}
			code := "REQUEST_TIMEOUT"
			if operation == "wait" {
				code = "WAIT_TIMEOUT"
			}
			e := mustError(t, err, code)
			if time.Since(start) > time.Second || calls.Load() != 1 || !errors.Is(err, context.DeadlineExceeded) {
				t.Fatalf("unbounded %v", err)
			}
			if e.MayHaveSucceeded != (operation == "write") {
				t.Fatal(e)
			}
			if operation != "read" && e.AssetID != 42 {
				t.Fatal(e)
			}
		})
	}
}
func TestCancellationAfterWriteDispatch(t *testing.T) {
	started := make(chan struct{})
	c := files(t, func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		close(started)
		<-r.Context().Done()
	})
	ctx, cancel := context.WithCancel(background)
	go func() { <-started; cancel() }()
	_, err := c.DeleteAsset(ctx, 42, RequestOptions{})
	e := mustError(t, err, "REQUEST_CANCELLED")
	if !e.MayHaveSucceeded || e.AssetID != 42 {
		t.Fatal(e)
	}
}
func TestWaitTimeoutNeverReuploads(t *testing.T) {
	var calls atomic.Int32
	c := files(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" {
			t.Error(r.Method)
		}
		calls.Add(1)
		v := assetFixture()
		v["status"] = "pending"
		respond(w, envelope(v))
	})
	_, err := c.WaitUntilReady(background, 42, WaitOptions{Timeout: 30 * time.Millisecond, PollInterval: 5 * time.Millisecond})
	e := mustError(t, err, "WAIT_TIMEOUT")
	if e.AssetID != 42 || e.MayHaveSucceeded || calls.Load() == 0 {
		t.Fatal(e)
	}
}
func TestReadRetriesOnlyEligibleFailures(t *testing.T) {
	for _, status := range []int{429, 502, 503, 504, 400, 401, 403, 500} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			var calls atomic.Int32
			s := server(t, func(w http.ResponseWriter, r *http.Request) {
				if calls.Add(1) == 1 {
					w.WriteHeader(status)
					respond(w, map[string]any{"error": "Temporary error"})
				} else {
					respond(w, envelope(assetFixture()))
				}
			})
			retries := 1
			c, err := New(Config{APIKey: "fixture-key", APIBaseURL: s.URL, MaxReadRetries: &retries})
			if err != nil {
				t.Fatal(err)
			}
			defer c.CloseIdleConnections()
			_, err = c.GetUploadStatus(background, 42, RequestOptions{})
			eligible := status == 429 || status == 502 || status == 503 || status == 504
			if eligible {
				if err != nil || calls.Load() != 2 {
					t.Fatal(err, calls.Load())
				}
			} else if mustError(t, err, "API_ERROR").Status != status || calls.Load() != 1 {
				t.Fatal(err, calls.Load())
			}
		})
	}
}
func TestRetryAfterUsesWholeDeadline(t *testing.T) {
	for _, mode := range []string{"seconds", "date", "body"} {
		t.Run(mode, func(t *testing.T) {
			var calls atomic.Int32
			s := server(t, func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				body := map[string]any{"error": "Rate limited"}
				switch mode {
				case "seconds":
					w.Header().Set("Retry-After", "5")
				case "date":
					w.Header().Set("Retry-After", time.Now().Add(time.Hour).UTC().Format(http.TimeFormat))
				case "body":
					body["retry_after"] = 5
				}
				w.WriteHeader(429)
				respond(w, body)
			})
			c, _ := New(Config{APIKey: "fixture", APIBaseURL: s.URL})
			defer c.CloseIdleConnections()
			_, err := c.GetUploadStatus(background, 42, RequestOptions{Timeout: 40 * time.Millisecond})
			mustError(t, err, "REQUEST_TIMEOUT")
			if calls.Load() != 1 {
				t.Fatal(calls.Load())
			}
		})
	}
}
func TestPermissionsAndRedaction(t *testing.T) {
	c := files(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer fixture-key" {
			t.Error("credential changed")
		}
		w.WriteHeader(403)
		respond(w, map[string]any{"code": "FORBIDDEN", "error": "Missing delete scope Bearer fixture-key https://cdn.example/private?signature=fixture token=another-value"})
	})
	_, err := c.DeleteAsset(background, 42, RequestOptions{})
	e := mustError(t, err, "FORBIDDEN")
	encoded, _ := json.Marshal(e)
	if e.Status != 403 || e.MayHaveSucceeded || strings.Contains(string(encoded), "fixture-key") || strings.Contains(string(encoded), "signature=") || strings.Contains(string(encoded), "another-value") {
		t.Fatal(string(encoded))
	}
}
func TestGatewayAndResponseSize(t *testing.T) {
	for _, status := range []int{200, 502} {
		for _, huge := range []bool{false, true} {
			t.Run(fmt.Sprintf("%d/%t", status, huge), func(t *testing.T) {
				c := files(t, func(w http.ResponseWriter, r *http.Request) {
					w.WriteHeader(status)
					if huge {
						io.WriteString(w, `{"error":"`+strings.Repeat("x", maxResponseBytes)+`"}`)
					} else {
						io.WriteString(w, "<html>private-gateway-content</html>")
					}
				})
				_, err := c.GetAsset(background, 42, RequestOptions{})
				code := "INVALID_RESPONSE"
				if status == 502 {
					code = "API_ERROR"
				}
				e := mustError(t, err, code)
				if e.Status != status || strings.Contains(e.Error(), "private-gateway-content") {
					t.Fatal(e)
				}
			})
		}
	}
}
func TestNoMutationReplayOnDisconnect(t *testing.T) {
	for _, m := range mutations() {
		t.Run(m.name, func(t *testing.T) {
			var calls atomic.Int32
			c := files(t, func(w http.ResponseWriter, r *http.Request) {
				io.Copy(io.Discard, r.Body)
				calls.Add(1)
				conn, _, e := w.(http.Hijacker).Hijack()
				if e != nil {
					t.Error(e)
					return
				}
				conn.Close()
			})
			err := m.run(c)
			e := mustError(t, err, "NETWORK_ERROR")
			if !e.MayHaveSucceeded || calls.Load() != 1 {
				t.Fatal(e, calls.Load())
			}
		})
	}
}
func TestNoRedirectsOrCredentialForwarding(t *testing.T) {
	for _, status := range []int{301, 302, 303, 307, 308} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			var targetCalls atomic.Int32
			target := server(t, func(w http.ResponseWriter, r *http.Request) { targetCalls.Add(1) })
			c := files(t, func(w http.ResponseWriter, r *http.Request) {
				io.Copy(io.Discard, r.Body)
				w.Header().Set("Location", target.URL+"/secret")
				w.WriteHeader(status)
			})
			_, err := c.UploadBytes(background, []byte("x"), "x.png", UploadOptions{})
			e := mustError(t, err, "API_ERROR")
			if e.Status != status || !e.MayHaveSucceeded || targetCalls.Load() != 0 {
				t.Fatal(e)
			}
			_, err = c.GetAsset(background, 42, RequestOptions{})
			mustError(t, err, "API_ERROR")
			if targetCalls.Load() != 0 {
				t.Fatal("followed redirect")
			}
		})
	}
}
func TestHTTP2ServerWritesUseFreshHTTP1(t *testing.T) {
	var mu sync.Mutex
	var addresses []string
	s := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		if r.ProtoMajor != 1 {
			t.Error("write used HTTP/2")
		}
		mu.Lock()
		addresses = append(addresses, r.RemoteAddr)
		mu.Unlock()
		respond(w, lifecycleFixture())
	}))
	s.EnableHTTP2 = true
	s.StartTLS()
	defer s.Close()
	transport := s.Client().Transport.(*http.Transport)
	c, e := New(Config{APIKey: "fixture", APIBaseURL: s.URL, HTTPTransport: transport})
	if e != nil {
		t.Fatal(e)
	}
	defer c.CloseIdleConnections()
	for range 3 {
		if _, e = c.DeleteAsset(background, 42, RequestOptions{}); e != nil {
			t.Fatal(e)
		}
	}
	if addresses[0] == addresses[1] || addresses[1] == addresses[2] || addresses[0] == addresses[2] {
		t.Fatal("write connections reused")
	}
	if transport.DisableKeepAlives {
		t.Fatal("modified caller transport")
	}
}

func TestGETNetworkRecovery(t *testing.T) {
	var calls atomic.Int32
	s := server(t, func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) == 1 {
			conn, _, err := w.(http.Hijacker).Hijack()
			if err != nil {
				t.Error(err)
				return
			}
			conn.Close()
			return
		}
		respond(w, envelope(assetFixture()))
	})
	n := 1
	c, err := New(Config{APIKey: "fixture", APIBaseURL: s.URL, MaxReadRetries: &n})
	if err != nil {
		t.Fatal(err)
	}
	defer c.CloseIdleConnections()
	if _, err = c.GetUploadStatus(background, 42, RequestOptions{}); err != nil || calls.Load() != 2 {
		t.Fatal(err, calls.Load())
	}
}
func TestRetryAfterIsNotShortened(t *testing.T) {
	var calls atomic.Int32
	var first time.Time
	s := server(t, func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) == 1 {
			first = time.Now()
			w.Header().Set("Retry-After", "1")
			w.WriteHeader(429)
			respond(w, map[string]string{"error": "Rate limited"})
			return
		}
		if time.Since(first) < time.Second {
			t.Error("retried before Retry-After")
		}
		respond(w, envelope(assetFixture()))
	})
	c, err := New(Config{APIKey: "fixture", APIBaseURL: s.URL})
	if err != nil {
		t.Fatal(err)
	}
	defer c.CloseIdleConnections()
	if _, err = c.GetUploadStatus(background, 42, RequestOptions{Timeout: 2 * time.Second}); err != nil || calls.Load() != 2 {
		t.Fatal(err, calls.Load())
	}
}

type blockingSource struct {
	closed chan struct{}
	once   sync.Once
}

func (b *blockingSource) Read([]byte) (int, error) { <-b.closed; return 0, io.ErrClosedPipe }
func (b *blockingSource) Close() error             { b.once.Do(func() { close(b.closed) }); return nil }
func TestUploadCancellationClosesBlockedSource(t *testing.T) {
	c := files(t, func(w http.ResponseWriter, r *http.Request) { io.Copy(io.Discard, r.Body) })
	source := &blockingSource{closed: make(chan struct{})}
	start := time.Now()
	_, err := c.UploadReader(background, source, 100, "blocked.bin", UploadOptions{RequestOptions: RequestOptions{Timeout: 40 * time.Millisecond}})
	e := mustError(t, err, "REQUEST_TIMEOUT")
	if !e.MayHaveSucceeded || time.Since(start) > time.Second {
		t.Fatal(e)
	}
	select {
	case <-source.closed:
	default:
		t.Fatal("source not closed")
	}
}

func TestUploadFileRejectsNamedPipeBeforeOpen(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix named-pipe fixture")
	}
	mkfifo, err := exec.LookPath("mkfifo")
	if err != nil {
		t.Skip("mkfifo is not available")
	}
	path := filepath.Join(t.TempDir(), "source.pipe")
	if err := exec.Command(mkfifo, path).Run(); err != nil {
		t.Fatal(err)
	}
	c := files(t, func(w http.ResponseWriter, r *http.Request) { t.Error("invalid source reached HTTP") })
	done := make(chan error, 1)
	go func() { _, err := c.UploadFile(background, path, UploadOptions{}); done <- err }()
	select {
	case err := <-done:
		mustError(t, err, "INVALID_ARGUMENT")
	case <-time.After(time.Second):
		// Unblock a faulty implementation before reporting failure.
		unblock, err := os.OpenFile(path, os.O_RDWR, 0)
		if err == nil {
			defer unblock.Close()
			<-done
		}
		t.Fatal("UploadFile blocked opening a named pipe")
	}
}
