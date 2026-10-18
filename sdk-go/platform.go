package kompressr

import (
	"context"
	"encoding/json"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

// PlatformClient administers identities and keys. The server requires project
// authority; constructing this client never elevates a scoped credential.
type PlatformClient struct{ t *transport }

func NewPlatform(c Config) (*PlatformClient, error) {
	t, e := newTransport(c)
	if e != nil {
		return nil, e
	}
	return &PlatformClient{t: t}, nil
}
func (p *PlatformClient) CloseIdleConnections() { p.t.close() }
func (*PlatformClient) String() string          { return "kompressr.PlatformClient{credentials redacted}" }
func (p *PlatformClient) GoString() string      { return p.String() }
func userPath(id string) (string, error) {
	if e := checkUUID(id); e != nil {
		return "", e
	}
	return "/api/platform/project-users/" + id, nil
}
func userFields(display *string, metadata CustomerData) (map[string]any, error) {
	out := map[string]any{}
	if display != nil {
		if len(strings.TrimSpace(*display)) > 120 || !utf8.ValidString(*display) {
			return nil, invalid("DisplayName supports at most 120 UTF-8 bytes.")
		}
		out["display_name"] = *display
	}
	if metadata != nil {
		d, e := customerData(metadata, 8192)
		if e != nil {
			return nil, e
		}
		out["metadata"] = d
	}
	return out, nil
}
func platformWrite[T any](ctx context.Context, p *PlatformClient, path, method string, body any, o RequestOptions, parse func(json.RawMessage) (T, error)) (zero T, err error) {
	r, e := jsonRequest(method, path, body, o)
	if e != nil {
		return zero, e
	}
	return perform(ctx, p.t, r, func(raw json.RawMessage) (T, error) {
		if _, e := success(raw); e != nil {
			return zero, e
		}
		return parse(raw)
	})
}
func userEnvelope(raw json.RawMessage) (ProjectUser, error) {
	m, e := success(raw)
	if e != nil {
		return ProjectUser{}, e
	}
	return parseUser(m["project_user"])
}

var datePattern = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)

func (p *PlatformClient) ListUsers(ctx context.Context, o PageOptions) (ProjectUserPage, error) {
	var zero ProjectUserPage
	q, e := pagination(o)
	if e != nil {
		return zero, e
	}
	return perform(ctx, p.t, request{method: "GET", path: "/api/platform/project-users?" + q.Encode(), options: o.RequestOptions}, func(raw json.RawMessage) (ProjectUserPage, error) {
		m, e := success(raw)
		if e != nil {
			return zero, e
		}
		page, e := parsePage(raw, "project_users", parseUser)
		if e != nil {
			return zero, e
		}
		if e = integerFields(m, false, 0, "project_active_count", "org_active_count"); e != nil {
			return zero, e
		}
		result := ProjectUserPage{Page: page}
		if json.Unmarshal(m["project_active_count"], &result.ProjectActiveCount) != nil || json.Unmarshal(m["org_active_count"], &result.OrgActiveCount) != nil {
			return zero, badResponse()
		}
		if v, ok := m["usage_period"]; ok {
			period, e := object(v)
			if e != nil {
				return zero, e
			}
			if e = stringFields(period, true, "start", "end"); e != nil {
				return zero, e
			}
			if decodeExact(v, &result.UsagePeriod) != nil || result.UsagePeriod == nil || !datePattern.MatchString(result.UsagePeriod.Start) || !datePattern.MatchString(result.UsagePeriod.End) {
				return zero, badResponse()
			}
		}
		return result, nil
	})
}
func (p *PlatformClient) CreateUser(ctx context.Context, input CreateUserOptions, o RequestOptions) (CreatedUser, error) {
	var zero CreatedUser
	if strings.TrimSpace(input.CustomerUserID) == "" || len(strings.TrimSpace(input.CustomerUserID)) > 256 || !utf8.ValidString(input.CustomerUserID) {
		return zero, invalid("CustomerUserID must contain 1–256 UTF-8 bytes.")
	}
	body, e := userFields(input.DisplayName, input.Metadata)
	if e != nil {
		return zero, e
	}
	body["customer_user_id"] = input.CustomerUserID
	return platformWrite(ctx, p, "/api/platform/project-users", "POST", body, o, func(raw json.RawMessage) (CreatedUser, error) {
		m, e := success(raw)
		if e != nil {
			return zero, e
		}
		if e = booleanField(m, "created"); e != nil {
			return zero, e
		}
		user, e := parseUser(m["project_user"])
		if e != nil {
			return zero, e
		}
		var created bool
		_ = json.Unmarshal(m["created"], &created)
		return CreatedUser{Created: created, ProjectUser: user}, nil
	})
}
func (p *PlatformClient) UpdateUser(ctx context.Context, id string, input UpdateUserOptions, o RequestOptions) (ProjectUser, error) {
	path, e := userPath(id)
	if e != nil {
		return ProjectUser{}, e
	}
	body, e := userFields(input.DisplayName, input.Metadata)
	if e != nil {
		return ProjectUser{}, e
	}
	return platformWrite(ctx, p, path, "PATCH", body, o, userEnvelope)
}
func (p *PlatformClient) SuspendUser(ctx context.Context, id string, o RequestOptions) (ProjectUser, error) {
	return p.mutateUser(ctx, id, "suspend", o)
}
func (p *PlatformClient) ReactivateUser(ctx context.Context, id string, o RequestOptions) (ProjectUser, error) {
	return p.mutateUser(ctx, id, "reactivate", o)
}
func (p *PlatformClient) mutateUser(ctx context.Context, id, action string, o RequestOptions) (ProjectUser, error) {
	path, e := userPath(id)
	if e != nil {
		return ProjectUser{}, e
	}
	return platformWrite(ctx, p, path+"/"+action, "POST", nil, o, userEnvelope)
}
func (p *PlatformClient) ListUploadKeys(ctx context.Context, id string, o PageOptions) (Page[UploadKey], error) {
	var zero Page[UploadKey]
	path, e := userPath(id)
	if e != nil {
		return zero, e
	}
	q, e := pagination(o)
	if e != nil {
		return zero, e
	}
	return perform(ctx, p.t, request{method: "GET", path: path + "/upload-keys?" + q.Encode(), options: o.RequestOptions}, func(raw json.RawMessage) (Page[UploadKey], error) {
		if _, e := success(raw); e != nil {
			return zero, e
		}
		return parsePage(raw, "upload_keys", parseUploadKey)
	})
}
func (p *PlatformClient) CreateUploadKey(ctx context.Context, id string, input CreateKeyOptions, o RequestOptions) (IssuedKey, error) {
	var zero IssuedKey
	path, e := userPath(id)
	if e != nil {
		return zero, e
	}
	if strings.TrimSpace(input.Name) == "" || len(strings.TrimSpace(input.Name)) > 120 || !utf8.ValidString(input.Name) {
		return zero, invalid("Key name must contain 1–120 UTF-8 bytes.")
	}
	body := map[string]any{"name": input.Name}
	if input.Scopes != nil {
		if len(input.Scopes) == 0 {
			return zero, invalid("Supply at least one scope, or omit scopes to use server defaults.")
		}
		for _, scope := range input.Scopes {
			if !validScope(scope) {
				return zero, invalid("Unsupported upload scope.")
			}
		}
		body["scopes"] = input.Scopes
	}
	if input.AllowedVisibility != "" {
		if !validVisibility(input.AllowedVisibility) && input.AllowedVisibility != Both {
			return zero, invalid("Invalid allowed visibility.")
		}
		body["allowed_visibility"] = input.AllowedVisibility
	}
	if input.AllowedAssetTypes != nil {
		for _, n := range input.AllowedAssetTypes {
			if n < 1 || int64(n) > MaxAssetID {
				return zero, invalid("Asset types must be positive safe integers.")
			}
		}
		body["allowed_asset_types"] = input.AllowedAssetTypes
	}
	if input.ExpiresAt != nil {
		if !input.ExpiresAt.After(time.Now()) {
			return zero, invalid("ExpiresAt must be a future timestamp.")
		}
		body["expires_at"] = input.ExpiresAt.UTC().Format(time.RFC3339Nano)
	}
	return platformWrite(ctx, p, path+"/upload-keys", "POST", body, o, parseIssued)
}
func (p *PlatformClient) RotateUploadKey(ctx context.Context, id, keyID string, o RequestOptions) (IssuedKey, error) {
	path, e := userPath(id)
	if e != nil {
		return IssuedKey{}, e
	}
	if e = checkUUID(keyID); e != nil {
		return IssuedKey{}, e
	}
	return platformWrite(ctx, p, path+"/upload-keys/"+keyID+"/rotate", "POST", nil, o, parseIssued)
}
func (p *PlatformClient) RevokeUploadKey(ctx context.Context, id, keyID string, o RequestOptions) error {
	path, e := userPath(id)
	if e != nil {
		return e
	}
	if e = checkUUID(keyID); e != nil {
		return e
	}
	_, e = platformWrite(ctx, p, path+"/upload-keys/"+keyID+"/revoke", "POST", nil, o, func(json.RawMessage) (struct{}, error) { return struct{}{}, nil })
	return e
}
