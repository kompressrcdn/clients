package kompressr

import (
	"encoding/json"
	"io"
	"net/http"
	"reflect"
	"sync/atomic"
	"testing"
)

// Put unknown aliases after the canonical keys so encoding/json's default
// case-insensitive struct matching cannot accidentally hide the regression.
func withResponseAliases(t *testing.T, value any, aliases string) json.RawMessage {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return append(append(raw[:len(raw)-1], ','), []byte(aliases+"}")...)
}
func rawResponse(w http.ResponseWriter, raw json.RawMessage) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write(raw)
}

func TestExplicitEmptyScopesRejectedBeforeDispatch(t *testing.T) {
	var calls atomic.Int32
	c := files(t, func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		var payload map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Error(err)
		}
		if _, exists := payload["scopes"]; exists {
			t.Error("omitted scopes must preserve server defaults")
		}
		respond(w, map[string]any{"success": true, "id": keyID, "key_id": keyID, "api_key": "one-time-fixture"})
	})
	_, err := c.Platform.CreateUploadKey(background, userID, CreateKeyOptions{Name: "Runtime", Scopes: []UploadScope{}}, RequestOptions{})
	failure := mustError(t, err, "INVALID_ARGUMENT")
	if failure.MayHaveSucceeded || calls.Load() != 0 {
		t.Fatal("empty scopes dispatched a key creation")
	}
	if _, err = c.Platform.CreateUploadKey(background, userID, CreateKeyOptions{Name: "Runtime"}, RequestOptions{}); err != nil {
		t.Fatal(err)
	}
	if calls.Load() != 1 {
		t.Fatal("nil scopes should send one default-scoped request")
	}
}

func TestExactFieldsPreventFalseReadiness(t *testing.T) {
	row := assetFixture()
	row["status"] = "failed"
	raw := withResponseAliases(t, row, `"Status":"processed"`)
	c := files(t, func(w http.ResponseWriter, r *http.Request) { respond(w, envelope(raw)) })
	_, err := c.WaitUntilReady(background, 42, WaitOptions{})
	failure := mustError(t, err, "PROCESSING_FAILED")
	if failure.AssetID != 42 {
		t.Fatal("terminal state lost its asset ID")
	}
}

func TestExactFieldsAcrossFileResponses(t *testing.T) {
	t.Run("upload acceptance", func(t *testing.T) {
		row := acceptedFixture()
		row["status"] = "failed"
		row["id"] = "unknown extension; asset_id remains authoritative"
		raw := withResponseAliases(t, row, `"Status":"processed","ORIGINAL_SIZE":999,"Warning":"unvalidated warning"`)
		c := files(t, func(w http.ResponseWriter, r *http.Request) { io.Copy(io.Discard, r.Body); respond(w, envelope(raw)) })
		v, e := c.UploadBytes(background, []byte("x"), "x.png", UploadOptions{})
		if e != nil || v.Status != Failed || v.OriginalSize != 1024 || v.Warning != "" {
			t.Fatalf("response aliases overrode acceptance: %#v %v", v, e)
		}
	})
	t.Run("private upload status", func(t *testing.T) {
		row := assetFixture()
		row["visibility"] = "private"
		delete(row, "cdn_url")
		row["can_generate_private_url"] = false
		row["data"] = map[string]any{"Status": "application metadata", "nullable": nil}
		row["options"] = map[string]string{"Quality": "application option"}
		raw := withResponseAliases(t, row, `"CDN_URL":"https://cdn.example/unvalidated","CAN_GENERATE_PRIVATE_URL":true,"KOMPRESSD_SIZE":999,"SAVINGS_PERCENT":99`)
		c := files(t, func(w http.ResponseWriter, r *http.Request) { respond(w, envelope(raw)) })
		v, e := c.GetUploadStatus(background, 42, RequestOptions{})
		if e != nil || v.CDNURL != "" || v.CanGeneratePrivateURL || v.KompressdSize != 512 || v.SavingsPercent != 50 {
			t.Fatalf("response aliases overrode private state: %#v %v", v, e)
		}
		if v.Data["Status"] != "application metadata" || v.Data["nullable"] != nil || v.Options["Quality"] != "application option" {
			t.Fatal("case-sensitive application map keys changed")
		}
	})
	t.Run("private signing", func(t *testing.T) {
		raw := withResponseAliases(t, map[string]any{"asset_id": 42, "variant": "webp", "private_url": "https://cdn.example/canonical", "expires_at": "2030-01-01T00:00:00Z", "expires_in": 3600}, `"PRIVATE_URL":"https://cdn.example/unvalidated","Expires_In":60`)
		c := files(t, func(w http.ResponseWriter, r *http.Request) { io.Copy(io.Discard, r.Body); respond(w, envelope(raw)) })
		v, e := c.GeneratePrivateURL(background, 42, PrivateURLOptions{})
		if e != nil || v.PrivateURL != "https://cdn.example/canonical" || v.ExpiresIn != 3600 {
			t.Fatalf("response aliases overrode signing: %#v %v", v, e)
		}
	})
	t.Run("asset state and nested failure", func(t *testing.T) {
		row := lifecycleFixture()
		row["last_failure"] = withResponseAliases(t, map[string]string{"code": "CLEANUP_PENDING", "message": "Cleanup pending", "at": "2030-01-01"}, `"Code":"SUCCESS","Message":"Done","At":"2035-01-01"`)
		raw := withResponseAliases(t, row, `"Deletion_Status":"deleted","Storage_Credited_Mb":999`)
		c := files(t, func(w http.ResponseWriter, r *http.Request) { rawResponse(w, raw) })
		v, e := c.GetAsset(background, 42, RequestOptions{})
		if e != nil || v.DeletionStatus != Deleting || v.StorageCreditedMB != 0 || v.LastFailure == nil || v.LastFailure.Code != "CLEANUP_PENDING" || v.LastFailure.Message != "Cleanup pending" || v.LastFailure.At != "2030-01-01" {
			t.Fatalf("response aliases overrode lifecycle: %#v %v", v, e)
		}
	})
	t.Run("pagination", func(t *testing.T) {
		raw := withResponseAliases(t, map[string]any{"success": true, "data": []any{assetFixture()}, "page": 1, "limit": 20, "total": 1}, `"Page":2,"Limit":0,"Total":0,"Data":[null]`)
		c := files(t, func(w http.ResponseWriter, r *http.Request) { rawResponse(w, raw) })
		v, e := c.ListUploads(background, UploadFilters{})
		if e != nil || v.Page != 1 || v.Limit != 20 || v.Total != 1 || len(v.Data) != 1 || v.Data[0].ID != 42 {
			t.Fatalf("response aliases overrode page: %#v %v", v, e)
		}
	})
	t.Run("bulk outcomes and counts", func(t *testing.T) {
		row := withResponseAliases(t, map[string]any{"id": 42, "status": 403, "accepted": false, "error": "Missing delete scope", "state": lifecycleFixture()}, `"Accepted":true,"Status":202,"Error":""`)
		counts := withResponseAliases(t, map[string]int{"total": 1, "accepted": 0, "failed": 1}, `"Accepted":1,"Failed":0`)
		c := files(t, func(w http.ResponseWriter, r *http.Request) {
			io.Copy(io.Discard, r.Body)
			respond(w, map[string]any{"results": []any{row}, "counts": counts})
		})
		v, e := c.BulkDeleteAssets(background, []int64{42}, RequestOptions{})
		if e != nil || v.Counts.Accepted != 0 || v.Counts.Failed != 1 || len(v.Results) != 1 || v.Results[0].Accepted || v.Results[0].Status != 403 || v.Results[0].Error != "Missing delete scope" {
			t.Fatalf("response aliases changed a bulk failure into acceptance: %#v %v", v, e)
		}
	})
}

func TestExactFieldsAcrossPlatformResponses(t *testing.T) {
	t.Run("user", func(t *testing.T) {
		row := userFixture()
		row["status"] = "suspended"
		row["asset_count"] = 0
		row["metadata"] = map[string]any{"Status": "application metadata", "nullable": nil}
		raw := withResponseAliases(t, row, `"Status":"active","Asset_Count":99,"Display_Name":"unvalidated"`)
		c := files(t, func(w http.ResponseWriter, r *http.Request) {
			respond(w, map[string]any{"success": true, "project_user": raw})
		})
		v, e := c.Platform.SuspendUser(background, userID, RequestOptions{})
		if e != nil || v.Status != "suspended" || v.AssetCount == nil || *v.AssetCount != 0 || v.DisplayName != "" || v.Metadata["Status"] != "application metadata" {
			t.Fatalf("response aliases overrode user: %#v %v", v, e)
		}
	})
	t.Run("user page and nested period", func(t *testing.T) {
		period := withResponseAliases(t, map[string]string{"start": "2030-01-01", "end": "2030-02-01"}, `"Start":"2035-01-01","End":"2035-02-01"`)
		raw := withResponseAliases(t, map[string]any{"success": true, "project_users": []any{userFixture()}, "page": 1, "limit": 20, "total": 1, "project_active_count": 1, "org_active_count": 2, "usage_period": period}, `"Project_Active_Count":99,"Org_Active_Count":100,"data":false`)
		c := files(t, func(w http.ResponseWriter, r *http.Request) { rawResponse(w, raw) })
		v, e := c.Platform.ListUsers(background, PageOptions{})
		if e != nil || v.ProjectActiveCount != 1 || v.OrgActiveCount != 2 || len(v.Data) != 1 || v.UsagePeriod == nil || v.UsagePeriod.Start != "2030-01-01" || v.UsagePeriod.End != "2030-02-01" {
			t.Fatalf("response aliases overrode user page: %#v %v", v, e)
		}
	})
	t.Run("key restrictions and nullable timestamps", func(t *testing.T) {
		row := keyFixture()
		row["scopes"] = []string{"status"}
		row["allowed_asset_types"] = []int{}
		row["revoked_at"] = "2030-01-01"
		row["last_used_at"] = nil
		raw := withResponseAliases(t, row, `"Scopes":["delete"],"Allowed_Visibility":"both","Allowed_Asset_Types":[1],"Expires_At":"2035-01-01","Revoked_At":null,"Last_Used_At":"2035-01-01"`)
		c := files(t, func(w http.ResponseWriter, r *http.Request) {
			respond(w, map[string]any{"success": true, "upload_keys": []any{raw}, "page": 1, "limit": 20, "total": 1})
		})
		v, e := c.Platform.ListUploadKeys(background, userID, PageOptions{})
		if e != nil || len(v.Data) != 1 {
			t.Fatal(e)
		}
		key := v.Data[0]
		if !reflect.DeepEqual(key.Scopes, []UploadScope{ScopeStatus}) || key.AllowedVisibility != Private || key.AllowedAssetTypes == nil || len(key.AllowedAssetTypes) != 0 || key.ExpiresAt != nil || key.RevokedAt == nil || *key.RevokedAt != "2030-01-01" || key.LastUsedAt != nil {
			t.Fatalf("response aliases overrode restrictions: %#v", key)
		}
	})
	t.Run("one-time key and nested key", func(t *testing.T) {
		nested := withResponseAliases(t, keyFixture(), `"Scopes":["delete"],"Allowed_Visibility":"both"`)
		raw := withResponseAliases(t, map[string]any{"success": true, "id": keyID, "key_id": keyID, "api_key": "canonical-fixture", "upload_key": nested}, `"API_KEY":"unvalidated-fixture","Key_Id":"unvalidated-id"`)
		c := files(t, func(w http.ResponseWriter, r *http.Request) { rawResponse(w, raw) })
		v, e := c.Platform.RotateUploadKey(background, userID, keyID, RequestOptions{})
		if e != nil || v.APIKey != "canonical-fixture" || v.KeyID != keyID || v.UploadKey == nil || v.UploadKey.AllowedVisibility != Private || len(v.UploadKey.Scopes) != 4 {
			t.Fatal("response aliases overrode issued key fields", e)
		}
	})
}
