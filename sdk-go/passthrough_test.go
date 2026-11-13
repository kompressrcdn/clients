package kompressr

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestPassthroughConfirmation(t *testing.T) {
	for _, ack := range []any{true, false, nil, "true"} {
		calls := 0
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			calls++
			if r.URL.String() != "/api/upload?passthrough=true" {
				t.Errorf("query: %s", r.URL)
			}
			io.Copy(io.Discard, r.Body)
			data := acceptedFixture()
			data["status"] = "processed"
			data["asset_type"] = "file"
			if ack != nil {
				data["passthrough"] = ack
			}
			json.NewEncoder(w).Encode(map[string]any{"success": true, "data": data})
		}))
		c, e := New(Config{APIKey: "fixture", APIBaseURL: server.URL})
		if e != nil {
			t.Fatal(e)
		}
		flag := true
		result, e := c.UploadBytes(background, nil, "empty", UploadOptions{Passthrough: &flag})
		if ack == true {
			if e != nil || result.Passthrough == nil || !*result.Passthrough {
				t.Fatalf("confirmation: %v", e)
			}
		} else {
			var failure *Error
			if !errors.As(e, &failure) || failure.Code != "INVALID_RESPONSE" || failure.AssetID != 42 || !failure.MayHaveSucceeded {
				t.Fatalf("recovery: %#v", e)
			}
		}
		if calls != 1 {
			t.Fatalf("replayed %d", calls)
		}
		c.CloseIdleConnections()
		server.Close()
	}
}

func TestPartialUploadErrorRecovery(t *testing.T) {
	for _, status := range []int{403, 409, 500} {
		for _, id := range []any{42, 0, -1, 1.5, "42", nil, int64(9007199254740992)} {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				io.Copy(io.Discard, r.Body)
				w.WriteHeader(status)
				json.NewEncoder(w).Encode(map[string]any{"success": false, "code": "PASSTHROUGH_NOT_READY", "data": map[string]any{"asset_id": id}})
			}))
			c, err := New(Config{APIKey: "fixture", APIBaseURL: server.URL})
			if err != nil {
				t.Fatal(err)
			}
			flag := true
			_, err = c.UploadBytes(background, nil, "empty", UploadOptions{Passthrough: &flag})
			var failure *Error
			expected := int64(0)
			if id == 42 {
				expected = 42
			}
			if !errors.As(err, &failure) || failure.AssetID != expected || failure.MayHaveSucceeded != (expected == 42 || status >= 500) || failure.Status != status {
				t.Fatalf("status=%d id=%v failure=%#v", status, id, err)
			}
			if calls != 1 {
				t.Fatal("upload replayed")
			}
			c.CloseIdleConnections()
			server.Close()
		}
	}
}
