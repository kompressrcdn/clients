package kompressr

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

const projectID = "660e8400-e29b-41d4-a716-446655440001"
const userID = "660e8400-e29b-41d4-a716-446655440002"
const keyID = "660e8400-e29b-41d4-a716-446655440003"

var background = context.Background()

func acceptedFixture() map[string]any {
	return map[string]any{"asset_id": 42, "status": "processing", "visibility": "public", "deletion_status": "active", "original_name": "output.png", "original_size": 1024, "asset_type": "image", "cdn_url": "https://cdn.example/accepted.webp"}
}
func assetFixture() map[string]any {
	v := acceptedFixture()
	delete(v, "asset_id")
	v["id"] = 42
	v["status"] = "processed"
	v["cdn_url"] = "https://cdn.example/ready.webp"
	v["kompressd_size"] = 512
	v["savings_percent"] = 50
	v["can_generate_private_url"] = false
	return v
}
func lifecycleFixture() map[string]any {
	return map[string]any{"id": 42, "project_id": projectID, "kind": 1, "source": "upload", "processing_status": 3, "deletion_status": "deleting", "storage_credited_mb": 0}
}
func userFixture() map[string]any {
	return map[string]any{"id": userID, "project_id": projectID, "customer_user_id": "customer-1", "status": "active"}
}
func keyFixture() map[string]any {
	return map[string]any{"id": keyID, "key_id": keyID, "project_id": projectID, "project_user_id": userID, "name": "Runtime", "scopes": []string{"upload", "status", "list", "private_url"}, "allowed_visibility": "private", "expires_at": nil}
}
func envelope(v any) map[string]any { return map[string]any{"success": true, "data": v} }
func respond(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}
func server(t *testing.T, h http.HandlerFunc) *httptest.Server {
	t.Helper()
	s := httptest.NewServer(h)
	t.Cleanup(s.Close)
	return s
}
func files(t *testing.T, h http.HandlerFunc) *Client {
	t.Helper()
	s := server(t, h)
	return at(t, s.URL)
}
func at(t *testing.T, url string) *Client {
	t.Helper()
	retries := 0
	c, e := New(Config{APIKey: "fixture-key", APIBaseURL: url, ProjectID: projectID, MaxReadRetries: &retries})
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(c.CloseIdleConnections)
	return c
}
func mustError(t *testing.T, e error, code string) *Error {
	t.Helper()
	var v *Error
	if !errors.As(e, &v) || v.Code != code {
		t.Fatalf("want error %s, got %#v", code, e)
	}
	return v
}
func TestPublicFileLifecycle(t *testing.T) {
	var order []string
	var got []byte
	var contentLength int64
	upload := server(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/upload" || r.Header.Get("Authorization") != "Bearer fixture-key" {
			t.Error("wrong upload request")
		}
		contentLength = r.ContentLength
		reader, e := r.MultipartReader()
		if e != nil {
			t.Error(e)
			return
		}
		for {
			part, e := reader.NextPart()
			if e == io.EOF {
				break
			}
			if e != nil {
				t.Error(e)
				return
			}
			order = append(order, part.FormName())
			b, _ := io.ReadAll(part)
			if part.FormName() == "file" {
				got = b
				if part.FileName() != "output.png" {
					t.Error(part.FileName())
				}
			}
		}
		respond(w, envelope(acceptedFixture()))
	})
	var polls atomic.Int32
	api := server(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/upload/42/status" {
			t.Error(r.URL.Path)
		}
		v := assetFixture()
		if polls.Add(1) == 1 {
			v["status"] = "pending"
		}
		respond(w, envelope(v))
	})
	c, e := New(Config{APIKey: "fixture-key", APIBaseURL: api.URL, UploadBaseURL: upload.URL})
	if e != nil {
		t.Fatal(e)
	}
	defer c.CloseIdleConnections()
	path := filepath.Join(t.TempDir(), "output.png")
	data := bytes.Repeat([]byte("x"), 4*1024*1024)
	if e = os.WriteFile(path, data, 0600); e != nil {
		t.Fatal(e)
	}
	first, e := c.UploadFile(background, path, UploadOptions{Visibility: Public, Quality: "1080p", PrivateURLExpiresIn: 3600, Data: CustomerData{"owner": "customer-1"}})
	if e != nil {
		t.Fatal(e)
	}
	if first.ID != 42 || first.Status != Processing || !bytes.Equal(data, got) || contentLength <= int64(len(data)) {
		t.Fatal("upload mismatch")
	}
	if !reflect.DeepEqual(order, []string{"visibility", "kmp-quality", "private_url_expires_in", "data", "file"}) {
		t.Fatal(order)
	}
	ready, e := c.WaitUntilReady(background, first.ID, WaitOptions{Timeout: time.Second, PollInterval: time.Millisecond})
	if e != nil || ready.CDNURL != "https://cdn.example/ready.webp" || polls.Load() != 2 {
		t.Fatalf("wait: %v %#v", e, ready)
	}
}
func TestPrivateFileLifecycle(t *testing.T) {
	var methods []string
	c := files(t, func(w http.ResponseWriter, r *http.Request) {
		methods = append(methods, r.Method+" "+r.URL.Path)
		switch r.URL.Path {
		case "/api/upload":
			io.Copy(io.Discard, r.Body)
			v := acceptedFixture()
			v["visibility"] = "private"
			delete(v, "cdn_url")
			v["private_url"] = "https://cdn.example/initial?s=fixture"
			respond(w, envelope(v))
		case "/api/upload/42/status":
			v := assetFixture()
			v["visibility"] = "private"
			delete(v, "cdn_url")
			v["can_generate_private_url"] = true
			respond(w, envelope(v))
		case "/api/upload/42/private-url":
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			if body["expires_in"] != float64(3600) || body["variant"] != "webp" {
				t.Error(body)
			}
			respond(w, envelope(map[string]any{"asset_id": 42, "variant": "webp", "private_url": "https://cdn.example/fresh?s=fixture", "expires_at": "2030-01-01T00:00:00Z", "expires_in": 3600}))
		default:
			t.Error(r.URL.Path)
		}
	})
	accepted, e := c.UploadBytes(background, []byte("abc"), "output.png", UploadOptions{Visibility: Private})
	if e != nil || accepted.CDNURL != "" {
		t.Fatal(e)
	}
	ready, e := c.WaitUntilReady(background, accepted.ID, WaitOptions{})
	if e != nil || !ready.CanGeneratePrivateURL {
		t.Fatal(e)
	}
	link, e := c.GeneratePrivateURL(background, accepted.ID, PrivateURLOptions{})
	if e != nil || !strings.Contains(link.PrivateURL, "/fresh") {
		t.Fatal(e)
	}
	if len(methods) != 3 {
		t.Fatal(methods)
	}
}
func TestUploadBytesSelectedSlice(t *testing.T) {
	var got []byte
	c := files(t, func(w http.ResponseWriter, r *http.Request) {
		m, _ := r.MultipartReader()
		p, _ := m.NextPart()
		got, _ = io.ReadAll(p)
		respond(w, envelope(acceptedFixture()))
	})
	_, e := c.UploadBytes(background, []byte{9, 1, 2, 3, 8}[1:4], "x.png", UploadOptions{})
	if e != nil || !bytes.Equal(got, []byte{1, 2, 3}) {
		t.Fatalf("%v %v", e, got)
	}
}
func TestPaginationAndFilters(t *testing.T) {
	var count atomic.Int32
	c := files(t, func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		n := int(count.Add(1))
		if q.Get("project_id") != projectID || q.Get("data.owner") != "a&b" || q.Get("status") != "3" || q.Get("deletion_status") != "active" || q.Get("page") != fmt.Sprint(n) {
			t.Error(q)
		}
		v := assetFixture()
		v["id"] = 41 + n
		respond(w, map[string]any{"success": true, "data": []any{v}, "page": n, "limit": 1, "total": 2})
	})
	var ids []int64
	for row, e := range c.IterateUploads(background, UploadFilters{PageOptions: PageOptions{Limit: 1}, Status: Processed, Data: map[string]string{"owner": "a&b"}, DeletionStatus: Active}) {
		if e != nil {
			t.Fatal(e)
		}
		ids = append(ids, row.ID)
	}
	if !reflect.DeepEqual(ids, []int64{42, 43}) {
		t.Fatal(ids)
	}
}
func TestIteratorStopsOnBreakAndRejectsBadPage(t *testing.T) {
	for _, bad := range []bool{false, true} {
		t.Run(fmt.Sprint(bad), func(t *testing.T) {
			var count atomic.Int32
			c := files(t, func(w http.ResponseWriter, r *http.Request) {
				count.Add(1)
				page := 1
				if bad {
					page = 2
				}
				respond(w, map[string]any{"success": true, "data": []any{assetFixture()}, "page": page, "limit": 1, "total": 10})
			})
			for _, e := range c.IterateUploads(background, UploadFilters{}) {
				if bad {
					mustError(t, e, "INVALID_RESPONSE")
				} else if e != nil {
					t.Fatal(e)
				}
				break
			}
			if count.Load() != 1 {
				t.Fatal(count.Load())
			}
		})
	}
}
func TestDeletionAndMixedBulk(t *testing.T) {
	var n atomic.Int32
	c := files(t, func(w http.ResponseWriter, r *http.Request) {
		switch n.Add(1) {
		case 1:
			if r.Method != "DELETE" {
				t.Error(r.Method)
			}
			w.WriteHeader(202)
			respond(w, lifecycleFixture())
		case 2:
			v := lifecycleFixture()
			v["deletion_status"] = "deleted"
			v["storage_credited_mb"] = 2
			respond(w, v)
		case 3:
			var body struct {
				IDs []int64 `json:"asset_ids"`
			}
			json.NewDecoder(r.Body).Decode(&body)
			if !reflect.DeepEqual(body.IDs, []int64{42, 42, 43}) {
				t.Error(body)
			}
			respond(w, map[string]any{"results": []any{map[string]any{"id": 42, "status": 202, "accepted": true, "state": lifecycleFixture()}, map[string]any{"id": 43, "status": 404, "accepted": false, "error": "Not found", "code": "ASSET_NOT_FOUND"}}, "counts": map[string]int{"total": 2, "accepted": 1, "failed": 1}})
		}
	})
	v, e := c.DeleteAsset(background, 42, RequestOptions{})
	if e != nil || v.DeletionStatus != Deleting {
		t.Fatal(e)
	}
	v, e = c.GetAsset(background, 42, RequestOptions{})
	if e != nil || v.StorageCreditedMB != 2 {
		t.Fatal(e)
	}
	bulk, e := c.BulkDeleteAssets(background, []int64{42, 42, 43}, RequestOptions{})
	if e != nil || bulk.Counts.Failed != 1 || bulk.Results[1].Accepted {
		t.Fatalf("%v %+v", e, bulk)
	}
}
func TestProjectOnlyRequiredForUploadListing(t *testing.T) {
	c := files(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Has("project_id") {
			t.Error("unexpected project")
		}
		respond(w, map[string]any{"data": []any{lifecycleFixture()}, "page": 1, "limit": 20, "total": 1})
	})
	c.projectID = ""
	_, e := c.ListUploads(background, UploadFilters{})
	mustError(t, e, "INVALID_ARGUMENT")
	p, e := c.ListAssets(background, AssetFilters{})
	if e != nil || len(p.Data) != 1 {
		t.Fatal(e)
	}
}
func TestReadinessStates(t *testing.T) {
	for _, state := range []string{"failed", "unprocessable", "unknown", "deleting", "missing-public-url", "private-not-ready"} {
		t.Run(state, func(t *testing.T) {
			c := files(t, func(w http.ResponseWriter, r *http.Request) {
				v := assetFixture()
				switch state {
				case "deleting":
					v["deletion_status"] = "deleting"
					delete(v, "cdn_url")
				case "missing-public-url":
					delete(v, "cdn_url")
				case "private-not-ready":
					v["visibility"] = "private"
					delete(v, "cdn_url")
				default:
					v["status"] = state
				}
				respond(w, envelope(v))
			})
			_, e := c.WaitUntilReady(background, 42, WaitOptions{})
			code := "PROCESSING_FAILED"
			if state == "deleting" {
				code = "ASSET_DELETED"
			}
			if strings.Contains(state, "url") || state == "private-not-ready" {
				code = "INVALID_RESPONSE"
			}
			failure := mustError(t, e, code)
			if failure.AssetID != 42 {
				t.Fatal(failure)
			}
		})
	}
}
func TestExistingUnnamedAssets(t *testing.T) {
	for _, name := range []any{nil, ""} {
		t.Run(fmt.Sprint(name), func(t *testing.T) {
			c := files(t, func(w http.ResponseWriter, r *http.Request) {
				v := assetFixture()
				if name == nil {
					delete(v, "original_name")
				} else {
					v["original_name"] = name
				}
				if r.URL.Path == "/api/uploads" {
					respond(w, map[string]any{"success": true, "data": []any{v}, "page": 1, "limit": 20, "total": 1})
				} else {
					respond(w, envelope(v))
				}
			})
			if _, e := c.GetUploadStatus(background, 42, RequestOptions{}); e != nil {
				t.Fatal(e)
			}
			if _, e := c.WaitUntilReady(background, 42, WaitOptions{}); e != nil {
				t.Fatal(e)
			}
			if _, e := c.ListUploads(background, UploadFilters{}); e != nil {
				t.Fatal(e)
			}
		})
	}
}
func TestSharedContractFixture(t *testing.T) {
	path := "testdata/file-lifecycle.json"
	raw, e := os.ReadFile(path)

	if e != nil {
		t.Fatal(e)
	}
	if shared, readErr := os.ReadFile("../contracts/fixtures/file-lifecycle.json"); readErr == nil {
		if !bytes.Equal(raw, shared) {
			t.Fatal("bundled fixture differs from shared contract")
		}
	} else if !os.IsNotExist(readErr) {
		t.Fatal(readErr)
	}
	var fixture map[string]json.RawMessage
	if e = json.Unmarshal(raw, &fixture); e != nil {
		t.Fatal(e)
	}
	if _, e = parseUpload(fixture["accepted"], true); e != nil {
		t.Fatal(e)
	}
	if _, e = parseUploadAsset(fixture["processed"]); e != nil {
		t.Fatal(e)
	}
	if _, e = parseAsset(fixture["deletionAccepted"]); e != nil {
		t.Fatal(e)
	}
	if _, e = parseBulk(fixture["bulkDeletion"], []int64{42, 43}); e != nil {
		t.Fatal(e)
	}
}
func TestConcurrentClient(t *testing.T) {
	c := files(t, func(w http.ResponseWriter, r *http.Request) { respond(w, envelope(assetFixture())) })
	var wg sync.WaitGroup
	for range 20 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, e := c.GetUploadStatus(background, 42, RequestOptions{}); e != nil {
				t.Error(e)
			}
		}()
	}
	wg.Wait()
}
