package kompressr

import (
	"net/http"
	"time"
)

const Version = "0.1.0"
const ProductionAPIURL = "https://kompressr.com"
const ProductionUploadURL = "https://uploads.kompressr.com"
const MaxAssetID int64 = 9007199254740991

type Visibility string

const (
	Public  Visibility = "public"
	Private Visibility = "private"
	Both    Visibility = "both"
)

type DeletionStatus string

const (
	Active        DeletionStatus = "active"
	Deleting      DeletionStatus = "deleting"
	Deleted       DeletionStatus = "deleted"
	LegacyDeleted DeletionStatus = "legacy_deleted"
)

type ProcessingStatus string

const (
	Pending       ProcessingStatus = "pending"
	Processing    ProcessingStatus = "processing"
	Processed     ProcessingStatus = "processed"
	Failed        ProcessingStatus = "failed"
	Unprocessable ProcessingStatus = "unprocessable"
	Unknown       ProcessingStatus = "unknown"
)

type UploadScope string

const (
	ScopeUpload     UploadScope = "upload"
	ScopeStatus     UploadScope = "status"
	ScopeList       UploadScope = "list"
	ScopePrivateURL UploadScope = "private_url"
	ScopeDelete     UploadScope = "delete"
)

// CustomerData permits at most five scalar string, number, bool or nil values.
type CustomerData map[string]any

// Config configures independent management and upload origins. Zero durations
// use defaults. MaxReadRetries is nil for two retries; use a pointer to zero
// to disable retries. HTTPTransport is cloned; redirect and write replay policy
// remain controlled by this package. Do not mutate the supplied transport while New runs.
type Config struct {
	APIKey         string `json:"-"`
	ProjectID      string
	APIBaseURL     string
	UploadBaseURL  string
	RequestTimeout time.Duration
	UploadTimeout  time.Duration
	MaxReadRetries *int
	HTTPTransport  *http.Transport `json:"-"`
}

func (Config) String() string     { return "kompressr.Config{credentials redacted}" }
func (c Config) GoString() string { return c.String() }

type RequestOptions struct{ Timeout time.Duration }
type UploadOptions struct {
	RequestOptions
	Visibility          Visibility
	Quality             string
	Data                CustomerData
	PrivateURLExpiresIn int
}
type WaitOptions struct {
	Timeout      time.Duration
	PollInterval time.Duration
}
type PrivateURLOptions struct {
	RequestOptions
	ExpiresIn int
	Variant   string
}
type PageOptions struct {
	RequestOptions
	Page  int
	Limit int
}
type UploadFilters struct {
	PageOptions
	ProjectID  string
	Visibility Visibility
	ExternalID string
	Data       map[string]string
	Status     ProcessingStatus
	// StatusCode accepts numeric API status filters 1–6, as an alternative to Status.
	StatusCode     int
	DeletionStatus DeletionStatus
}
type AssetFilters struct {
	PageOptions
	DeletionStatus DeletionStatus
}
type Page[T any] struct {
	Data  []T   `json:"data"`
	Page  int   `json:"page"`
	Limit int   `json:"limit"`
	Total int64 `json:"total"`
}

// UploadAccepted means the server accepted work, not that delivery is ready.
type UploadAccepted struct {
	ID                  int64             `json:"id"`
	Status              ProcessingStatus  `json:"status"`
	DeletionStatus      DeletionStatus    `json:"deletion_status"`
	DeletionRequestedAt string            `json:"deletion_requested_at,omitempty"`
	Visibility          Visibility        `json:"visibility"`
	OriginalName        string            `json:"original_name,omitempty"`
	OriginalSize        int64             `json:"original_size"`
	AssetType           string            `json:"asset_type"`
	CDNURL              string            `json:"cdn_url,omitempty"`
	CDNURLAVIF          string            `json:"cdn_url_avif,omitempty"`
	PrivateURL          string            `json:"private_url,omitempty"`
	PrivateURLExpiresAt string            `json:"private_url_expires_at,omitempty"`
	Data                CustomerData      `json:"data,omitempty"`
	ExternalID          string            `json:"external_id,omitempty"`
	Options             map[string]string `json:"options,omitempty"`
	Quality             string            `json:"quality,omitempty"`
	Warning             string            `json:"warning,omitempty"`
}
type UploadAsset struct {
	UploadAccepted
	KompressdSize         int64   `json:"kompressd_size"`
	SavingsPercent        float64 `json:"savings_percent"`
	CanGeneratePrivateURL bool    `json:"can_generate_private_url"`
	InputFormat           string  `json:"input_format,omitempty"`
	OutputFormat          string  `json:"output_format,omitempty"`
	CreatedAt             string  `json:"created_at,omitempty"`
}
type PrivateURL struct {
	AssetID    int64  `json:"asset_id"`
	Variant    string `json:"variant"`
	PrivateURL string `json:"private_url"`
	ExpiresAt  string `json:"expires_at"`
	ExpiresIn  int    `json:"expires_in"`
}
type AssetFailure struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	At      string `json:"at"`
}
type AssetState struct {
	ID                  int64          `json:"id"`
	ProjectID           string         `json:"project_id"`
	Kind                int64          `json:"kind"`
	Source              string         `json:"source"`
	ProcessingStatus    int64          `json:"processing_status"`
	DeletionStatus      DeletionStatus `json:"deletion_status"`
	StorageCreditedMB   int64          `json:"storage_credited_mb"`
	DeletionRequestedAt string         `json:"deletion_requested_at,omitempty"`
	AccountingStatus    string         `json:"accounting_status,omitempty"`
	LastFailure         *AssetFailure  `json:"last_failure,omitempty"`
}
type DeletionResult struct {
	ID       int64       `json:"id"`
	Status   int         `json:"status"`
	Accepted bool        `json:"accepted"`
	State    *AssetState `json:"state,omitempty"`
	Code     string      `json:"code,omitempty"`
	Error    string      `json:"error,omitempty"`
}
type DeletionCounts struct {
	Total    int `json:"total"`
	Accepted int `json:"accepted"`
	Failed   int `json:"failed"`
}
type BulkDeletion struct {
	Results []DeletionResult `json:"results"`
	Counts  DeletionCounts   `json:"counts"`
}
type ProjectUser struct {
	ID                          string       `json:"id"`
	ProjectID                   string       `json:"project_id"`
	CustomerUserID              string       `json:"customer_user_id"`
	Status                      string       `json:"status"`
	DisplayName                 string       `json:"display_name,omitempty"`
	Metadata                    CustomerData `json:"metadata,omitempty"`
	AssetCount                  *int64       `json:"asset_count,omitempty"`
	StorageBytes                *int64       `json:"storage_bytes,omitempty"`
	ActiveKeyCount              *int64       `json:"active_key_count,omitempty"`
	BandwidthBytesCurrentPeriod *int64       `json:"bandwidth_bytes_current_period,omitempty"`
	RequestsCurrentPeriod       *int64       `json:"requests_current_period,omitempty"`
	LastSeenAt                  string       `json:"last_seen_at,omitempty"`
	LastUploadAt                string       `json:"last_upload_at,omitempty"`
	LastKeyUsedAt               string       `json:"last_key_used_at,omitempty"`
	CreatedAt                   string       `json:"created_at,omitempty"`
}
type UsagePeriod struct {
	Start string `json:"start"`
	End   string `json:"end"`
}
type ProjectUserPage struct {
	Page[ProjectUser]
	ProjectActiveCount int64        `json:"project_active_count"`
	OrgActiveCount     int64        `json:"org_active_count"`
	UsagePeriod        *UsagePeriod `json:"usage_period,omitempty"`
}
type UploadKey struct {
	ID                string        `json:"id"`
	KeyID             string        `json:"key_id"`
	ProjectID         string        `json:"project_id"`
	ProjectUserID     string        `json:"project_user_id"`
	Name              string        `json:"name"`
	Scopes            []UploadScope `json:"scopes"`
	AllowedVisibility Visibility    `json:"allowed_visibility"`
	AllowedAssetTypes []int         `json:"allowed_asset_types,omitempty"`
	ExpiresAt         *string       `json:"expires_at,omitempty"`
	RevokedAt         *string       `json:"revoked_at,omitempty"`
	LastUsedAt        *string       `json:"last_used_at,omitempty"`
	CreatedAt         string        `json:"created_at,omitempty"`
}
type CreateUserOptions struct {
	CustomerUserID string
	DisplayName    *string
	Metadata       CustomerData
}
type UpdateUserOptions struct {
	DisplayName *string
	Metadata    CustomerData
}

// Nil scopes mean server defaults; an explicit nonempty slice replaces defaults.
// An empty scope slice is invalid. Delete permission is never added by the SDK.
// Nil/empty asset types mean all supported.
type CreateKeyOptions struct {
	Name              string
	Scopes            []UploadScope
	AllowedVisibility Visibility
	AllowedAssetTypes []int
	ExpiresAt         *time.Time
}
type CreatedUser struct {
	Created     bool        `json:"created"`
	ProjectUser ProjectUser `json:"project_user"`
}

// IssuedKey contains a one-time secret. Store APIKey securely; list methods do not
// return it. Formatting redacts it; deliberate JSON encoding includes it.
type IssuedKey struct {
	ID        string     `json:"id"`
	KeyID     string     `json:"key_id"`
	APIKey    string     `json:"api_key"`
	UploadKey *UploadKey `json:"upload_key,omitempty"`
}

func (IssuedKey) String() string     { return "kompressr.IssuedKey{credentials redacted}" }
func (v IssuedKey) GoString() string { return v.String() }
