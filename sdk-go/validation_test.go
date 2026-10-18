package kompressr

import (
	"context"
	"encoding/json"
	"io"
	"math"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestInputsRejectedBeforeDispatch(t *testing.T) {
	var count atomic.Int32
	c := files(t, func(w http.ResponseWriter, r *http.Request) { count.Add(1) })
	expired := time.Now().Add(-time.Hour)
	cases := map[string]func() error{
		"unsafe-id":  func() error { _, e := c.GetAsset(background, MaxAssetID+1, RequestOptions{}); return e },
		"zero-id":    func() error { _, e := c.GetAsset(background, 0, RequestOptions{}); return e },
		"bulk-empty": func() error { _, e := c.BulkDeleteAssets(background, nil, RequestOptions{}); return e },
		"bulk-limit": func() error { _, e := c.BulkDeleteAssets(background, make([]int64, 101), RequestOptions{}); return e },
		"ttl":        func() error { _, e := c.GeneratePrivateURL(background, 42, PrivateURLOptions{ExpiresIn: 59}); return e },
		"variant": func() error {
			_, e := c.GeneratePrivateURL(background, 42, PrivateURLOptions{Variant: "png"})
			return e
		},
		"metadata-count": func() error {
			_, e := c.UploadBytes(background, []byte{}, "x.png", UploadOptions{Data: CustomerData{"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}})
			return e
		},
		"metadata-array": func() error {
			_, e := c.UploadBytes(background, []byte{}, "x.png", UploadOptions{Data: CustomerData{"a": []string{"x"}}})
			return e
		},
		"metadata-nan": func() error {
			_, e := c.UploadBytes(background, []byte{}, "x.png", UploadOptions{Data: CustomerData{"a": math.NaN()}})
			return e
		},
		"metadata-duplicate": func() error {
			_, e := c.UploadBytes(background, []byte{}, "x.png", UploadOptions{Data: CustomerData{"a": 1, " a ": 2}})
			return e
		},
		"metadata-utf8": func() error {
			_, e := c.UploadBytes(background, []byte{}, "x.png", UploadOptions{Data: CustomerData{"a": strings.Repeat("é", 257)}})
			return e
		},
		"filename-control": func() error { _, e := c.UploadBytes(background, []byte{}, "x\n.png", UploadOptions{}); return e },
		"visibility": func() error {
			_, e := c.UploadBytes(background, []byte{}, "x.png", UploadOptions{Visibility: Both})
			return e
		},
		"quality": func() error {
			_, e := c.UploadBytes(background, []byte{}, "x.png", UploadOptions{Quality: "8k"})
			return e
		},
		"timeout":     func() error { _, e := c.GetAsset(background, 42, RequestOptions{Timeout: -time.Second}); return e },
		"nil-context": func() error { _, e := c.GetAsset(nil, 42, RequestOptions{}); return e },
		"wait-interval": func() error {
			_, e := c.WaitUntilReady(background, 42, WaitOptions{PollInterval: time.Minute})
			return e
		},
		"project": func() error { _, e := c.ListUploads(background, UploadFilters{ProjectID: "not-a-project"}); return e },
		"pagination": func() error {
			_, e := c.ListAssets(background, AssetFilters{PageOptions: PageOptions{Limit: 101}})
			return e
		},
		"status": func() error { _, e := c.ListUploads(background, UploadFilters{Status: Unknown}); return e },
		"status-conflict": func() error {
			_, e := c.ListUploads(background, UploadFilters{Status: Processed, StatusCode: 3})
			return e
		},
		"deletion": func() error { _, e := c.ListAssets(background, AssetFilters{DeletionStatus: "removed"}); return e },
		"identity": func() error {
			_, e := c.Platform.CreateUser(background, CreateUserOptions{CustomerUserID: " "}, RequestOptions{})
			return e
		},
		"uuid": func() error {
			_, e := c.Platform.UpdateUser(background, "bad", UpdateUserOptions{}, RequestOptions{})
			return e
		},
		"key-name": func() error {
			_, e := c.Platform.CreateUploadKey(background, userID, CreateKeyOptions{}, RequestOptions{})
			return e
		},
		"key-scope": func() error {
			_, e := c.Platform.CreateUploadKey(background, userID, CreateKeyOptions{Name: "Runtime", Scopes: []UploadScope{"admin"}}, RequestOptions{})
			return e
		},
		"key-expiry": func() error {
			_, e := c.Platform.CreateUploadKey(background, userID, CreateKeyOptions{Name: "Runtime", ExpiresAt: &expired}, RequestOptions{})
			return e
		},
		"key-asset-type": func() error {
			_, e := c.Platform.CreateUploadKey(background, userID, CreateKeyOptions{Name: "Runtime", AllowedAssetTypes: []int{0}}, RequestOptions{})
			return e
		},
	}
	for name, run := range cases {
		t.Run(name, func(t *testing.T) {
			e := mustError(t, run(), "INVALID_ARGUMENT")
			if e.MayHaveSucceeded {
				t.Fatal(e)
			}
		})
	}
	if count.Load() != 0 {
		t.Fatal("validation dispatched requests", count.Load())
	}
}
func TestStrictResponseValidation(t *testing.T) {
	cases := map[string]func(map[string]any){
		"null-name": func(v map[string]any) { v["original_name"] = nil }, "null-bool": func(v map[string]any) { v["can_generate_private_url"] = nil }, "missing-bool": func(v map[string]any) { delete(v, "can_generate_private_url") }, "missing-size": func(v map[string]any) { delete(v, "original_size") }, "unsafe-id": func(v map[string]any) { v["id"] = MaxAssetID + 1 }, "negative-size": func(v map[string]any) { v["kompressd_size"] = -1 }, "private-public-url": func(v map[string]any) { v["visibility"] = "private" }, "deleted-url": func(v map[string]any) { v["deletion_status"] = "deleted" }, "credential-url": func(v map[string]any) { v["cdn_url"] = "https://user:fixture@cdn.example/file" }, "unsafe-scheme": func(v map[string]any) { v["cdn_url"] = "file:///file" }, "null-metadata": func(v map[string]any) { v["data"] = nil }, "array-metadata": func(v map[string]any) { v["data"] = []any{} }, "null-options": func(v map[string]any) { v["options"] = nil }, "numeric-options": func(v map[string]any) { v["options"] = map[string]any{"x": 1} }, "null-optional": func(v map[string]any) { v["created_at"] = nil },
	}
	for name, edit := range cases {
		t.Run(name, func(t *testing.T) {
			v := assetFixture()
			edit(v)
			c := files(t, func(w http.ResponseWriter, r *http.Request) { respond(w, envelope(v)) })
			_, e := c.GetUploadStatus(background, 42, RequestOptions{})
			mustError(t, e, "INVALID_RESPONSE")
		})
	}
}
func TestEndpointsAndConfiguration(t *testing.T) {
	ep, e := ResolveEndpoints("", "")
	if e != nil || ep.APIBaseURL != ProductionAPIURL || ep.UploadBaseURL != ProductionUploadURL {
		t.Fatal(ep, e)
	}
	ep, e = ResolveEndpoints("http://localhost:1234/", "")
	if e != nil || ep.UploadBaseURL != "http://localhost:1234" {
		t.Fatal(ep, e)
	}
	ep, e = ResolveEndpoints("https://kompressr.com:443", "")
	if e != nil || ep.UploadBaseURL != ProductionUploadURL {
		t.Fatal(ep, e)
	}
	for _, origin := range []string{"https://user:password@example.test", "https://example.test/path", "https://example.test?query=1", "https://example.test#", "file:///example/file", "://bad", "https:///"} {
		t.Run(origin, func(t *testing.T) { _, e := ResolveEndpoints(origin, ""); mustError(t, e, "INVALID_ARGUMENT") })
	}
	for _, key := range []string{"", " ", "key\nvalue", "key\x00value"} {
		_, e := New(Config{APIKey: key})
		mustError(t, e, "INVALID_ARGUMENT")
	}
	n := 6
	_, e = New(Config{APIKey: "fixture", MaxReadRetries: &n})
	mustError(t, e, "INVALID_ARGUMENT")
	_, e = New(Config{APIKey: "fixture", RequestTimeout: -time.Second})
	mustError(t, e, "INVALID_ARGUMENT")
}
func TestReaderClosedAndExactSize(t *testing.T) {
	for _, short := range []bool{false, true} {
		t.Run(map[bool]string{false: "exact", true: "short"}[short], func(t *testing.T) {
			var closes atomic.Int32
			reader := &countedReader{Reader: strings.NewReader("abc"), closes: &closes}
			c := files(t, func(w http.ResponseWriter, r *http.Request) {
				_, e := io.Copy(io.Discard, r.Body)
				if e == nil {
					respond(w, envelope(acceptedFixture()))
				}
			})
			size := int64(3)
			if short {
				size = 10
			}
			_, err := c.UploadReader(background, reader, size, "x.png", UploadOptions{})
			if short {
				if !mustError(t, err, "NETWORK_ERROR").MayHaveSucceeded {
					t.Fatal(err)
				}
			} else if err != nil {
				t.Fatal(err)
			}
			if closes.Load() != 1 {
				t.Fatal("source not closed exactly once", closes.Load())
			}
		})
	}
	var closes atomic.Int32
	c, _ := New(Config{APIKey: "fixture"})
	defer c.CloseIdleConnections()
	_, e := c.UploadReader(background, &countedReader{Reader: strings.NewReader("a"), closes: &closes}, 1, "\n", UploadOptions{})
	mustError(t, e, "INVALID_ARGUMENT")
	if closes.Load() != 1 {
		t.Fatal(closes.Load())
	}
}

type countedReader struct {
	io.Reader
	closes *atomic.Int32
}

func (c *countedReader) Close() error { c.closes.Add(1); return nil }
func TestPlatformMetadataNullRejected(t *testing.T) {
	u := userFixture()
	u["metadata"] = nil
	b, _ := json.Marshal(u)
	_, e := parseUser(b)
	mustError(t, e, "INVALID_RESPONSE")
}
func TestNativeContextDeadline(t *testing.T) {
	c := files(t, func(w http.ResponseWriter, r *http.Request) { <-r.Context().Done() })
	ctx, cancel := context.WithTimeout(background, 20*time.Millisecond)
	defer cancel()
	_, e := c.GetAsset(ctx, 42, RequestOptions{})
	mustError(t, e, "REQUEST_TIMEOUT")
}

func TestBulkResponseMustPreserveOutcomes(t *testing.T) {
	for _, variant := range []string{"missing-row", "wrong-order", "wrong-count", "active-state", "missing-error"} {
		t.Run(variant, func(t *testing.T) {
			good := map[string]any{"id": 42, "accepted": true, "status": 202, "state": lifecycleFixture()}
			bad := map[string]any{"id": 43, "accepted": false, "status": 404, "error": "Not found"}
			rows := []any{good, bad}
			counts := map[string]any{"total": 2, "accepted": 1, "failed": 1}
			switch variant {
			case "missing-row":
				rows = rows[:1]
			case "wrong-order":
				rows = []any{bad, good}
			case "wrong-count":
				counts["accepted"] = 2
			case "active-state":
				good["state"].(map[string]any)["deletion_status"] = "active"
			case "missing-error":
				delete(bad, "error")
			}
			c := files(t, func(w http.ResponseWriter, r *http.Request) {
				io.Copy(io.Discard, r.Body)
				respond(w, map[string]any{"results": rows, "counts": counts})
			})
			_, err := c.BulkDeleteAssets(background, []int64{42, 43}, RequestOptions{})
			e := mustError(t, err, "INVALID_RESPONSE")
			if !e.MayHaveSucceeded || e.AssetID != 0 {
				t.Fatal(e)
			}
		})
	}
}
