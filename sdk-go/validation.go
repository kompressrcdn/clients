package kompressr

import (
	"bytes"
	"encoding/json"
	"math"
	"net/url"
	"reflect"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"
)

var uuidPattern = regexp.MustCompile(`(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

func validID(id int64) bool { return id >= 1 && id <= MaxAssetID }
func checkID(id int64) error {
	if !validID(id) {
		return invalid("Use a positive safe integer asset ID.")
	}
	return nil
}
func checkUUID(id string) error {
	if !uuidPattern.MatchString(id) {
		return invalid("Identifier must be a UUID.")
	}
	return nil
}
func validDeletion(v DeletionStatus) bool {
	return v == Active || v == Deleting || v == Deleted || v == LegacyDeleted
}
func validScope(v UploadScope) bool {
	return v == ScopeUpload || v == ScopeStatus || v == ScopeList || v == ScopePrivateURL || v == ScopeDelete
}
func validVisibility(v Visibility) bool { return v == Public || v == Private }
func object(raw json.RawMessage) (map[string]json.RawMessage, error) {
	var m map[string]json.RawMessage
	if json.Unmarshal(raw, &m) != nil || m == nil {
		return nil, badResponse()
	}
	return m, nil
}

// decodeExact populates response models from their exact JSON tags. The
// standard decoder also accepts case-insensitive aliases, which would let an
// unvalidated field such as "Status" overwrite validated "status". Unknown
// fields remain ignored, and map keys (customer metadata/options) stay intact.
func decodeExact(raw json.RawMessage, destination any) error {
	target := reflect.ValueOf(destination)
	if target.Kind() != reflect.Pointer || target.IsNil() {
		return badResponse()
	}
	return decodeExactValue(raw, target.Elem())
}

// An already parsed object is also used when a wire field needs normalization.
func decodeExactObject(fields map[string]json.RawMessage, target reflect.Value) error {
	shape := target.Type()
	for i := 0; i < shape.NumField(); i++ {
		field := shape.Field(i)
		if field.PkgPath != "" { // Unexported fields are not response data.
			continue
		}
		name := strings.Split(field.Tag.Get("json"), ",")[0]
		if name == "-" {
			continue
		}
		if field.Anonymous && name == "" {
			embedded := target.Field(i)
			if embedded.Kind() != reflect.Struct {
				return badResponse()
			}
			if err := decodeExactObject(fields, embedded); err != nil {
				return err
			}
			continue
		}
		if name == "" { // Response models require an explicit wire name.
			continue
		}
		if value, exists := fields[name]; exists {
			if err := decodeExactValue(value, target.Field(i)); err != nil {
				return err
			}
		}
	}
	return nil
}

func decodeExactValue(raw json.RawMessage, target reflect.Value) error {
	switch target.Kind() {
	case reflect.Pointer:
		if !nonnull(raw) {
			target.SetZero()
			return nil
		}
		target.Set(reflect.New(target.Type().Elem()))
		return decodeExactValue(raw, target.Elem())
	case reflect.Struct:
		fields, err := object(raw)
		if err != nil {
			return err
		}
		return decodeExactObject(fields, target)
	case reflect.Slice, reflect.Array:
		var items []json.RawMessage
		if json.Unmarshal(raw, &items) != nil {
			return badResponse()
		}
		if target.Kind() == reflect.Slice {
			if items == nil {
				target.SetZero()
				return nil
			}
			target.Set(reflect.MakeSlice(target.Type(), len(items), len(items)))
		} else if len(items) != target.Len() {
			return badResponse()
		}
		for i, item := range items {
			if err := decodeExactValue(item, target.Index(i)); err != nil {
				return err
			}
		}
		return nil
	case reflect.Map:
		if !nonnull(raw) {
			target.SetZero()
			return nil
		}
		fields, err := object(raw)
		if err != nil || target.Type().Key().Kind() != reflect.String {
			return badResponse()
		}
		target.Set(reflect.MakeMapWithSize(target.Type(), len(fields)))
		for name, rawValue := range fields {
			key := reflect.New(target.Type().Key()).Elem()
			key.SetString(name)
			value := reflect.New(target.Type().Elem()).Elem()
			if err := decodeExactValue(rawValue, value); err != nil {
				return err
			}
			target.SetMapIndex(key, value)
		}
		return nil
	default:
		if json.Unmarshal(raw, target.Addr().Interface()) != nil {
			return badResponse()
		}
		return nil
	}
}

func nonnull(v json.RawMessage) bool {
	return len(v) > 0 && !bytes.Equal(bytes.TrimSpace(v), []byte("null"))
}
func required(m map[string]json.RawMessage, names ...string) error {
	for _, n := range names {
		if !nonnull(m[n]) {
			return badResponse()
		}
	}
	return nil
}
func stringFields(m map[string]json.RawMessage, nonempty bool, names ...string) error {
	for _, n := range names {
		v, ok := m[n]
		if !ok {
			if nonempty {
				return badResponse()
			}
			continue
		}
		var s string
		if !nonnull(v) || json.Unmarshal(v, &s) != nil || (nonempty && strings.TrimSpace(s) == "") {
			return badResponse()
		}
	}
	return nil
}
func integerFields(m map[string]json.RawMessage, optional bool, min int64, names ...string) error {
	for _, n := range names {
		v, ok := m[n]
		if !ok && optional {
			continue
		}
		var i int64
		if !nonnull(v) || json.Unmarshal(v, &i) != nil || i < min || i > MaxAssetID {
			return badResponse()
		}
	}
	return nil
}
func booleanField(m map[string]json.RawMessage, n string) error {
	var b bool
	if !nonnull(m[n]) || json.Unmarshal(m[n], &b) != nil {
		return badResponse()
	}
	return nil
}
func customerData(data CustomerData, max int) (CustomerData, error) {
	if data == nil || len(data) > 5 {
		return nil, invalid("Customer data supports at most five scalar fields.")
	}
	out := CustomerData{}
	for raw, val := range data {
		key := strings.TrimSpace(raw)
		if key == "" || len(key) > 64 || !utf8.ValidString(key) {
			return nil, invalid("Data keys must contain 1–64 UTF-8 bytes.")
		}
		if _, ok := out[key]; ok {
			return nil, invalid("Data keys must be unique after trimming.")
		}
		if val != nil {
			switch v := val.(type) {
			case string:
				if len(v) > 512 || !utf8.ValidString(v) {
					return nil, invalid("Data strings support at most 512 UTF-8 bytes.")
				}
			case bool:
			case json.Number:
				f, e := v.Float64()
				if e != nil || math.IsInf(f, 0) || math.IsNaN(f) {
					return nil, invalid("Data numbers must be finite.")
				}
			default:
				rv := reflect.ValueOf(val)
				switch rv.Kind() {
				case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64, reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
				case reflect.Float32, reflect.Float64:
					if math.IsInf(rv.Float(), 0) || math.IsNaN(rv.Float()) {
						return nil, invalid("Data numbers must be finite.")
					}
				default:
					return nil, invalid("Data values must be scalar strings, numbers, booleans or nil.")
				}
			}
		}
		out[key] = val
	}
	b, err := encodeJSON(out)
	if err != nil || len(b) > max {
		return nil, invalid("Encoded customer data exceeds the supported size.")
	}
	return out, nil
}

// Disable HTML escaping so UTF-8/JSON size limits match the wire encoding.
func encodeJSON(v any) ([]byte, error) {
	var b bytes.Buffer
	e := json.NewEncoder(&b)
	e.SetEscapeHTML(false)
	if err := e.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(b.Bytes(), []byte("\n")), nil
}
func validateDataResponse(m map[string]json.RawMessage, key string) error {
	v, ok := m[key]
	if !ok {
		return nil
	}
	var data CustomerData
	decoder := json.NewDecoder(bytes.NewReader(v))
	decoder.UseNumber()
	if decoder.Decode(&data) != nil {
		return badResponse()
	}
	if _, err := customerData(data, 8192); err != nil {
		return badResponse()
	}
	return nil
}
func validURL(s string) bool {
	u, err := url.Parse(s)
	return err == nil && (u.Scheme == "https" || u.Scheme == "http") && u.Host != "" && u.User == nil
}
func validateURLs(m map[string]json.RawMessage) error {
	for _, n := range []string{"cdn_url", "cdn_url_avif", "private_url"} {
		if v, ok := m[n]; ok {
			var s string
			if json.Unmarshal(v, &s) != nil || !validURL(s) {
				return badResponse()
			}
		}
	}
	return nil
}
func parseUpload(raw json.RawMessage, accepted bool) (UploadAccepted, error) {
	var out UploadAccepted
	m, err := object(raw)
	if err != nil {
		return out, err
	}
	idName := "id"
	if accepted {
		idName = "asset_id"
	}
	if err = integerFields(m, false, 1, idName); err != nil {
		return out, err
	}
	if err = integerFields(m, false, 0, "original_size"); err != nil {
		return out, err
	}
	if err = stringFields(m, true, "status", "visibility", "deletion_status", "asset_type"); err != nil {
		return out, err
	}
	if err = stringFields(m, accepted, "original_name"); err != nil {
		return out, err
	}
	if err = stringFields(m, false, "deletion_requested_at", "external_id", "created_at", "input_format", "output_format", "private_url_expires_at", "quality", "warning"); err != nil {
		return out, err
	}
	// Acceptance uses asset_id on the wire. Ignore any unrelated id extension;
	// both accepted and existing upload records decode through the canonical ID.
	m["id"] = m[idName]
	if decodeExactObject(m, reflect.ValueOf(&out).Elem()) != nil {
		return out, badResponse()
	}
	if !validVisibility(out.Visibility) || !validDeletion(out.DeletionStatus) {
		return out, badResponse()
	}
	switch out.Status {
	case Pending, Processing, Processed, Failed, Unprocessable, Unknown:
	default:
		return out, badResponse()
	}
	if err = validateURLs(m); err != nil {
		return out, err
	}
	_, cdn := m["cdn_url"]
	_, avif := m["cdn_url_avif"]
	_, private := m["private_url"]
	if out.Visibility == Private && (cdn || avif) || out.DeletionStatus != Active && (cdn || avif || private) {
		return out, badResponse()
	}
	if err = validateDataResponse(m, "data"); err != nil {
		return out, err
	}
	if v, ok := m["options"]; ok {
		opts, e := object(v)
		if e != nil {
			return out, e
		}
		for _, v := range opts {
			var s string
			if !nonnull(v) || json.Unmarshal(v, &s) != nil {
				return out, badResponse()
			}
		}
	}
	return out, nil
}
func parseUploadAsset(raw json.RawMessage) (UploadAsset, error) {
	var out UploadAsset
	base, err := parseUpload(raw, false)
	if err != nil {
		return out, err
	}
	m, _ := object(raw)
	if err = integerFields(m, false, 0, "kompressd_size"); err != nil {
		return out, err
	}
	if err = required(m, "savings_percent"); err != nil {
		return out, err
	}
	if err = booleanField(m, "can_generate_private_url"); err != nil {
		return out, err
	}
	if decodeExact(raw, &out) != nil || math.IsNaN(out.SavingsPercent) || math.IsInf(out.SavingsPercent, 0) {
		return out, badResponse()
	}
	out.UploadAccepted = base
	return out, nil
}
func parsePrivateURL(raw json.RawMessage) (PrivateURL, error) {
	var out PrivateURL
	m, e := object(raw)
	if e != nil {
		return out, e
	}
	if e = integerFields(m, false, 1, "asset_id", "expires_in"); e != nil {
		return out, e
	}
	if e = stringFields(m, true, "variant", "private_url", "expires_at"); e != nil {
		return out, e
	}
	if decodeExact(raw, &out) != nil || !validURL(out.PrivateURL) || (out.Variant != "webp" && out.Variant != "avif") || out.ExpiresIn < 60 || out.ExpiresIn > 604800 {
		return out, badResponse()
	}
	return out, nil
}
func parseAsset(raw json.RawMessage) (AssetState, error) {
	var out AssetState
	m, e := object(raw)
	if e != nil {
		return out, e
	}
	if e = integerFields(m, false, 1, "id", "kind"); e != nil {
		return out, e
	}
	if e = integerFields(m, false, 0, "storage_credited_mb"); e != nil {
		return out, e
	}
	if e = integerFields(m, false, -MaxAssetID, "processing_status"); e != nil {
		return out, e
	}
	if e = stringFields(m, true, "project_id", "source", "deletion_status"); e != nil {
		return out, e
	}
	if e = stringFields(m, false, "deletion_requested_at", "accounting_status"); e != nil {
		return out, e
	}
	if decodeExact(raw, &out) != nil || !validDeletion(out.DeletionStatus) || (out.Source != "upload" && out.Source != "origin") {
		return out, badResponse()
	}
	if _, ok := m["accounting_status"]; ok && out.AccountingStatus != "pending" && out.AccountingStatus != "settled" && out.AccountingStatus != "unavailable" {
		return out, badResponse()
	}
	if f, ok := m["last_failure"]; ok {
		fm, err := object(f)
		if err != nil {
			return out, err
		}
		if e = stringFields(fm, true, "code", "message", "at"); e != nil {
			return out, e
		}
	}
	return out, nil
}
func parsePage[T any](raw json.RawMessage, key string, parse func(json.RawMessage) (T, error)) (Page[T], error) {
	var out Page[T]
	m, e := object(raw)
	if e != nil {
		return out, e
	}
	if e = integerFields(m, false, 1, "page", "limit"); e != nil {
		return out, e
	}
	if e = integerFields(m, false, 0, "total"); e != nil {
		return out, e
	}
	var rows []json.RawMessage
	if !nonnull(m[key]) || json.Unmarshal(m[key], &rows) != nil {
		return out, badResponse()
	}
	// Page rows may live under data, project_users or upload_keys. Decode only
	// the validated pagination fields, then parse the selected rows explicitly.
	if json.Unmarshal(m["page"], &out.Page) != nil || json.Unmarshal(m["limit"], &out.Limit) != nil || json.Unmarshal(m["total"], &out.Total) != nil {
		return out, badResponse()
	}
	out.Data = make([]T, 0, len(rows))
	for _, row := range rows {
		v, err := parse(row)
		if err != nil {
			return out, err
		}
		out.Data = append(out.Data, v)
	}
	return out, nil
}
func parseBulk(raw json.RawMessage, expected []int64) (BulkDeletion, error) {
	var out BulkDeletion
	m, e := object(raw)
	if e != nil {
		return out, e
	}
	var rows []json.RawMessage
	if !nonnull(m["results"]) || json.Unmarshal(m["results"], &rows) != nil || len(rows) != len(expected) {
		return out, badResponse()
	}
	counts, e := object(m["counts"])
	if e != nil {
		return out, e
	}
	if e = integerFields(counts, false, 0, "total", "accepted", "failed"); e != nil {
		return out, e
	}
	if decodeExact(raw, &out) != nil {
		return out, badResponse()
	}
	accepted := 0
	for i, v := range rows {
		item, e := object(v)
		if e != nil {
			return out, e
		}
		if e = integerFields(item, false, 1, "id", "status"); e != nil {
			return out, e
		}
		if e = booleanField(item, "accepted"); e != nil {
			return out, e
		}
		r := &out.Results[i]
		if r.ID != expected[i] {
			return out, badResponse()
		}
		if e = stringFields(item, false, "code", "error"); e != nil {
			return out, e
		}
		if r.Accepted {
			state, e := parseAsset(item["state"])
			if e != nil {
				return out, e
			}
			if (r.Status != 200 && r.Status != 202) || state.ID != r.ID || state.DeletionStatus == Active {
				return out, badResponse()
			}
			r.State = &state
			accepted++
		} else {
			if r.Status < 400 || strings.TrimSpace(r.Error) == "" {
				return out, badResponse()
			}
		}
	}
	if out.Counts.Total != len(rows) || out.Counts.Accepted != accepted || out.Counts.Failed != len(rows)-accepted {
		return out, badResponse()
	}
	return out, nil
}
func parseUser(raw json.RawMessage) (ProjectUser, error) {
	var out ProjectUser
	m, e := object(raw)
	if e != nil {
		return out, e
	}
	if e = stringFields(m, true, "id", "project_id", "customer_user_id", "status"); e != nil {
		return out, e
	}
	if e = stringFields(m, false, "display_name", "created_at", "last_seen_at", "last_upload_at", "last_key_used_at"); e != nil {
		return out, e
	}
	if e = integerFields(m, true, 0, "asset_count", "storage_bytes", "active_key_count", "bandwidth_bytes_current_period", "requests_current_period"); e != nil {
		return out, e
	}
	if e = validateDataResponse(m, "metadata"); e != nil {
		return out, e
	}
	if decodeExact(raw, &out) != nil || (out.Status != "active" && out.Status != "suspended") {
		return out, badResponse()
	}
	return out, nil
}
func parseUploadKey(raw json.RawMessage) (UploadKey, error) {
	var out UploadKey
	m, e := object(raw)
	if e != nil {
		return out, e
	}
	if e = stringFields(m, true, "id", "key_id", "project_id", "project_user_id", "name", "allowed_visibility"); e != nil {
		return out, e
	}
	if e = required(m, "scopes"); e != nil {
		return out, e
	}
	if decodeExact(raw, &out) != nil || (!validVisibility(out.AllowedVisibility) && out.AllowedVisibility != Both) {
		return out, badResponse()
	}
	for _, scope := range out.Scopes {
		if !validScope(scope) {
			return out, badResponse()
		}
	}
	if v, ok := m["allowed_asset_types"]; ok {
		if !nonnull(v) {
			return out, badResponse()
		}
		for _, n := range out.AllowedAssetTypes {
			if n < 1 || int64(n) > MaxAssetID {
				return out, badResponse()
			}
		}
	}
	if e = stringFields(m, false, "created_at"); e != nil {
		return out, e
	}
	return out, nil
}
func parseIssued(raw json.RawMessage) (IssuedKey, error) {
	var out IssuedKey
	m, e := success(raw)
	if e != nil {
		return out, e
	}
	if e = stringFields(m, true, "id", "key_id", "api_key"); e != nil {
		return out, e
	}
	if decodeExact(raw, &out) != nil {
		return out, badResponse()
	}
	if v, ok := m["upload_key"]; ok {
		k, e := parseUploadKey(v)
		if e != nil {
			return out, e
		}
		out.UploadKey = &k
	}
	return out, nil
}
func pagination(o PageOptions) (url.Values, error) {
	page, limit := o.Page, o.Limit
	if page == 0 {
		page = 1
	}
	if limit == 0 {
		limit = 20
	}
	if page < 1 || page > 2147483647 || limit < 1 || limit > 100 {
		return nil, invalid("Page must be positive and limit must be between 1 and 100.")
	}
	return url.Values{"page": {strconv.Itoa(page)}, "limit": {strconv.Itoa(limit)}}, nil
}
