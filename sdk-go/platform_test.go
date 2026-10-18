package kompressr

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestPlatformCompleteLifecycle(t *testing.T) {
	var requests []string
	var keyBodies []map[string]any
	c := files(t, func(w http.ResponseWriter, r *http.Request) {
		requests = append(requests, r.Method+" "+r.URL.Path)
		if !strings.HasPrefix(r.URL.Path, "/api/platform/project-users") {
			t.Error(r.URL.Path)
		}
		user := userFixture()
		switch {
		case r.Method == "GET" && strings.HasSuffix(r.URL.Path, "upload-keys"):
			respond(w, map[string]any{"success": true, "upload_keys": []any{keyFixture()}, "page": 1, "limit": 20, "total": 1})
		case r.Method == "GET":
			respond(w, map[string]any{"success": true, "project_users": []any{user}, "page": 1, "limit": 20, "total": 1, "project_active_count": 1, "org_active_count": 2, "usage_period": map[string]string{"start": "2030-01-01", "end": "2030-02-01"}})
		case strings.HasSuffix(r.URL.Path, "/upload-keys"):
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			keyBodies = append(keyBodies, body)
			respond(w, map[string]any{"success": true, "id": keyID, "key_id": keyID, "api_key": "one-time-fixture", "upload_key": keyFixture()})
		case strings.HasSuffix(r.URL.Path, "/rotate"):
			respond(w, map[string]any{"success": true, "id": keyID, "key_id": keyID, "api_key": "replacement-fixture"})
		case strings.HasSuffix(r.URL.Path, "/revoke"):
			respond(w, map[string]any{"success": true})
		case strings.HasSuffix(r.URL.Path, "/suspend"):
			user["status"] = "suspended"
			respond(w, map[string]any{"success": true, "project_user": user})
		case strings.HasSuffix(r.URL.Path, "/reactivate"):
			respond(w, map[string]any{"success": true, "project_user": user})
		case r.Method == "PATCH":
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			if body["display_name"] != "New name" {
				t.Error(body)
			}
			user["display_name"] = "New name"
			respond(w, map[string]any{"success": true, "project_user": user})
		default:
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			if body["customer_user_id"] != "customer-1" {
				t.Error(body)
			}
			respond(w, map[string]any{"success": true, "created": true, "project_user": user})
		}
	})
	p := c.Platform
	created, e := p.CreateUser(background, CreateUserOptions{CustomerUserID: "customer-1", Metadata: CustomerData{"role": "member"}}, RequestOptions{})
	if e != nil || !created.Created || created.ProjectUser.DisplayName != "" {
		t.Fatal(e)
	}
	page, e := p.ListUsers(background, PageOptions{})
	if e != nil || page.OrgActiveCount != 2 || page.UsagePeriod.Start != "2030-01-01" || len(page.Data) != 1 {
		t.Fatal(e)
	}
	name := "New name"
	updated, e := p.UpdateUser(background, userID, UpdateUserOptions{DisplayName: &name}, RequestOptions{})
	if e != nil || updated.DisplayName != name {
		t.Fatal(e)
	}
	key, e := p.CreateUploadKey(background, userID, CreateKeyOptions{Name: "Runtime"}, RequestOptions{})
	if e != nil || key.APIKey != "one-time-fixture" {
		t.Fatal(e)
	}
	if !reflect.DeepEqual(keyBodies[0], map[string]any{"name": "Runtime"}) {
		t.Fatal(keyBodies)
	}
	future := time.Now().Add(time.Hour)
	_, e = p.CreateUploadKey(background, userID, CreateKeyOptions{Name: "Private runtime", Scopes: []UploadScope{ScopeUpload, ScopeStatus, ScopePrivateURL}, AllowedVisibility: Private, AllowedAssetTypes: []int{}, ExpiresAt: &future}, RequestOptions{})
	if e != nil {
		t.Fatal(e)
	}
	if keyBodies[1]["allowed_visibility"] != "private" || keyBodies[1]["expires_at"] == nil || keyBodies[1]["allowed_asset_types"] == nil {
		t.Fatal(keyBodies)
	}
	keys, e := p.ListUploadKeys(background, userID, PageOptions{})
	if e != nil || len(keys.Data) != 1 || keys.Data[0].ExpiresAt != nil {
		t.Fatal(e)
	}
	rotated, e := p.RotateUploadKey(background, userID, keyID, RequestOptions{})
	if e != nil || rotated.APIKey != "replacement-fixture" || rotated.UploadKey != nil {
		t.Fatal(e)
	}
	if e = p.RevokeUploadKey(background, userID, keyID, RequestOptions{}); e != nil {
		t.Fatal(e)
	}
	user, e := p.SuspendUser(background, userID, RequestOptions{})
	if e != nil || user.Status != "suspended" {
		t.Fatal(e)
	}
	user, e = p.ReactivateUser(background, userID, RequestOptions{})
	if e != nil || user.Status != "active" {
		t.Fatal(e)
	}
	if len(requests) != 10 {
		t.Fatal(requests)
	}
	for _, value := range []any{key, rotated, c, Config{APIKey: "one-time-fixture"}} {
		for _, format := range []string{"%v", "%+v", "%#v"} {
			if strings.Contains(fmt.Sprintf(format, value), "one-time-fixture") || strings.Contains(fmt.Sprintf(format, value), "replacement-fixture") {
				t.Fatal("credential exposed by formatting")
			}
		}
	}
}
func TestPlatformScopedKeyDenied(t *testing.T) {
	var count atomic.Int32
	c := files(t, func(w http.ResponseWriter, r *http.Request) {
		count.Add(1)
		io.Copy(io.Discard, r.Body)
		w.WriteHeader(403)
		respond(w, map[string]any{"code": "FORBIDDEN", "error": "Project authority required"})
	})
	_, err := c.Platform.CreateUser(background, CreateUserOptions{CustomerUserID: "customer-1"}, RequestOptions{})
	e := mustError(t, err, "FORBIDDEN")
	if e.MayHaveSucceeded || count.Load() != 1 {
		t.Fatal(e)
	}
}
func TestPlatformMalformedLists(t *testing.T) {
	cases := map[string]any{"missing-active": map[string]any{"success": true, "project_users": []any{}, "page": 1, "limit": 20, "total": 0, "org_active_count": 2}, "wrong-count": map[string]any{"success": true, "project_users": []any{}, "page": 1, "limit": 20, "total": 0, "project_active_count": "1", "org_active_count": 2}, "null-period": map[string]any{"success": true, "project_users": []any{}, "page": 1, "limit": 20, "total": 0, "project_active_count": 1, "org_active_count": 2, "usage_period": nil}}
	for name, v := range cases {
		t.Run(name, func(t *testing.T) {
			c := files(t, func(w http.ResponseWriter, r *http.Request) { respond(w, v) })
			_, e := c.Platform.ListUsers(background, PageOptions{})
			mustError(t, e, "INVALID_RESPONSE")
		})
	}
}
