package kompressr

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"iter"
	"math/rand/v2"
	"mime/multipart"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"
)

// Client is safe for concurrent use. Reuse it; keep application credentials and
// accepted asset IDs in your own storage. Its zero value is not usable.
type Client struct {
	t         *transport
	projectID string
	Platform  *PlatformClient
}

func New(c Config) (*Client, error) {
	t, e := newTransport(c)
	if e != nil {
		return nil, e
	}
	return &Client{t: t, projectID: c.ProjectID, Platform: &PlatformClient{t: t}}, nil
}
func (c *Client) APIBaseURL() string    { return c.t.apiURL }
func (c *Client) UploadBaseURL() string { return c.t.uploadURL }
func (c *Client) CloseIdleConnections() { c.t.close() }
func (*Client) String() string          { return "kompressr.Client{credentials redacted}" }
func (c *Client) GoString() string      { return c.String() }

// UploadFile streams a regular file without buffering its contents. A successful
// result is acceptance, not readiness. Native file errors can precede dispatch.
func (c *Client) UploadFile(ctx context.Context, path string, o UploadOptions) (UploadAccepted, error) {
	if strings.TrimSpace(path) == "" {
		return UploadAccepted{}, invalid("Supply a file path.")
	}
	// Check before opening: opening a named pipe can block before request
	// cancellation starts. Recheck the opened handle below as well.
	before, e := os.Stat(path)
	if e != nil {
		return UploadAccepted{}, e
	}
	if !before.Mode().IsRegular() {
		return UploadAccepted{}, invalid("UploadFile requires a regular file.")
	}
	f, e := os.Open(path)
	if e != nil {
		return UploadAccepted{}, e
	}
	info, e := f.Stat()
	if e != nil {
		f.Close()
		return UploadAccepted{}, e
	}
	if !info.Mode().IsRegular() {
		f.Close()
		return UploadAccepted{}, invalid("UploadFile requires a regular file.")
	}
	return c.UploadReader(ctx, f, info.Size(), filepath.Base(path), o)
}

// UploadBytes snapshots exactly the supplied slice. Do not concurrently modify
// the slice while this synchronous method copies it.
func (c *Client) UploadBytes(ctx context.Context, b []byte, filename string, o UploadOptions) (UploadAccepted, error) {
	copyBytes := bytes.Clone(b)
	return c.UploadReader(ctx, io.NopCloser(bytes.NewReader(copyBytes)), int64(len(copyBytes)), filename, o)
}

// UploadReader streams exactly size bytes and takes ownership of source, closing
// it on every return path. Close must unblock Read; use a context-aware reader
// for remote/custom sources. The source must remain stable during the call.
func (c *Client) UploadReader(ctx context.Context, source io.ReadCloser, size int64, filename string, o UploadOptions) (UploadAccepted, error) {
	var zero UploadAccepted
	if source == nil {
		return zero, invalid("Supply an upload reader.")
	}
	owner := &onceCloser{ReadCloser: source}
	defer owner.Close()
	if size < 0 || size > MaxAssetID {
		return zero, invalid("Upload size must be a nonnegative safe integer.")
	}
	if strings.TrimSpace(filename) == "" || !utf8.ValidString(filename) || strings.IndexFunc(filename, unicode.IsControl) >= 0 {
		return zero, invalid("Supply a nonempty filename without control characters.")
	}
	var buffer bytes.Buffer
	form := multipart.NewWriter(&buffer)
	if o.Visibility != "" {
		if !validVisibility(o.Visibility) {
			return zero, invalid("Visibility must be public or private.")
		}
		_ = form.WriteField("visibility", string(o.Visibility))
	}
	if o.Quality != "" {
		switch o.Quality {
		case "480p", "720p", "1080p", "4k":
		default:
			return zero, invalid("Unsupported video quality.")
		}
		_ = form.WriteField("kmp-quality", o.Quality)
	}
	if o.PrivateURLExpiresIn != 0 {
		if o.PrivateURLExpiresIn < 60 || o.PrivateURLExpiresIn > 604800 {
			return zero, invalid("Private URL lifetime must be between 60 and 604800 seconds.")
		}
		_ = form.WriteField("private_url_expires_in", strconv.Itoa(o.PrivateURLExpiresIn))
	}
	if o.Data != nil {
		d, e := customerData(o.Data, 4096)
		if e != nil {
			return zero, e
		}
		b, e := encodeJSON(d)
		if e != nil {
			return zero, invalid("Customer data cannot be encoded.")
		}
		_ = form.WriteField("data", string(b))
	}
	if _, e := form.CreateFormFile("file", filepath.Base(filename)); e != nil {
		return zero, invalid("Cannot create multipart file header.")
	}
	prefix := bytes.Clone(buffer.Bytes())
	buffer.Reset()
	if e := form.Close(); e != nil {
		return zero, invalid("Cannot create multipart closing boundary.")
	}
	suffix := bytes.Clone(buffer.Bytes())
	body := &multipartBody{Reader: io.MultiReader(bytes.NewReader(prefix), &exactReader{r: owner, remaining: size}, bytes.NewReader(suffix)), source: owner}
	r := request{method: "POST", path: "/api/upload", body: body, length: size + int64(len(prefix)+len(suffix)), contentType: form.FormDataContentType(), upload: true, recoverID: true, options: o.RequestOptions}
	return perform(ctx, c.t, r, func(raw json.RawMessage) (UploadAccepted, error) {
		m, e := success(raw)
		if e != nil {
			return zero, e
		}
		result, e := parseUpload(m["data"], true)
		if e != nil {
			return zero, e
		}
		if v, ok := m["warning"]; ok {
			var warning string
			if json.Unmarshal(v, &warning) == nil {
				result.Warning = warning
			}
		}
		return result, nil
	})
}

type onceCloser struct {
	io.ReadCloser
	once sync.Once
	err  error
}

func (c *onceCloser) Close() error { c.once.Do(func() { c.err = c.ReadCloser.Close() }); return c.err }

type multipartBody struct {
	io.Reader
	source io.Closer
}

func (b *multipartBody) Close() error { return b.source.Close() }

type exactReader struct {
	r         io.Reader
	remaining int64
}

func (r *exactReader) Read(p []byte) (int, error) {
	if r.remaining == 0 {
		return 0, io.EOF
	}
	if int64(len(p)) > r.remaining {
		p = p[:r.remaining]
	}
	n, e := r.r.Read(p)
	r.remaining -= int64(n)
	if e == io.EOF && r.remaining > 0 {
		e = io.ErrUnexpectedEOF
	}
	return n, e
}
func (c *Client) GetUploadStatus(ctx context.Context, id int64, o RequestOptions) (UploadAsset, error) {
	if e := checkID(id); e != nil {
		return UploadAsset{}, e
	}
	return perform(ctx, c.t, request{method: "GET", path: fmt.Sprintf("/api/upload/%d/status", id), options: o}, func(raw json.RawMessage) (UploadAsset, error) {
		d, e := dataEnvelope(raw)
		if e != nil {
			return UploadAsset{}, e
		}
		v, e := parseUploadAsset(d)
		if e == nil && v.ID != id {
			e = badResponse()
		}
		return v, e
	})
}

// WaitUntilReady polls only status. Cancellation never reuploads or rolls back.
func (c *Client) WaitUntilReady(parent context.Context, id int64, o WaitOptions) (UploadAsset, error) {
	var zero UploadAsset
	if e := checkID(id); e != nil {
		return zero, e
	}
	if parent == nil {
		return zero, invalid("Supply a non-nil context.")
	}
	timeout, e := timeoutValue(o.Timeout, 2*time.Minute)
	if e != nil {
		return zero, e
	}
	interval := o.PollInterval
	if interval == 0 {
		interval = 2 * time.Second
	}
	if interval < 0 || interval > 30*time.Second {
		return zero, invalid("PollInterval must be positive and no greater than 30 seconds.")
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()
	stopped := func() *Error {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return &Error{Kind: KindTimeout, Code: "WAIT_TIMEOUT", Message: "Waiting timed out; resume status checks with the saved asset ID.", AssetID: id}
		}
		return &Error{Kind: KindCancelled, Code: "WAIT_CANCELLED", Message: "Waiting cancelled; resume status checks with the saved asset ID.", AssetID: id}
	}
	for {
		if ctx.Err() != nil {
			return zero, stopped()
		}
		asset, e := c.GetUploadStatus(ctx, id, RequestOptions{})
		if ctx.Err() != nil {
			return zero, stopped()
		}
		if e != nil {
			var sdkError *Error
			if errors.As(e, &sdkError) {
				copy := *sdkError
				copy.AssetID = id
				return zero, &copy
			}
			return zero, e
		}
		if asset.DeletionStatus != Active {
			return zero, &Error{Kind: KindProcessing, Code: "ASSET_DELETED", Message: "The asset is being deleted or has been deleted.", AssetID: id}
		}
		if asset.Status == Processed {
			if asset.Visibility == Public && asset.CDNURL == "" || asset.Visibility == Private && !asset.CanGeneratePrivateURL {
				e := badResponse()
				e.AssetID = id
				return zero, e
			}
			return asset, nil
		}
		if asset.Status != Pending && asset.Status != Processing {
			return zero, &Error{Kind: KindProcessing, Code: "PROCESSING_FAILED", Message: "Asset processing ended with status " + string(asset.Status) + ".", AssetID: id}
		}
		jitter := min(interval/10, 250*time.Millisecond)
		delay := min(30*time.Second, interval+time.Duration(rand.Int64N(max(int64(jitter), 1))))
		if waitContext(ctx, delay) != nil {
			return zero, stopped()
		}
	}
}
func (c *Client) GeneratePrivateURL(ctx context.Context, id int64, o PrivateURLOptions) (PrivateURL, error) {
	var zero PrivateURL
	if e := checkID(id); e != nil {
		return zero, e
	}
	ttl := o.ExpiresIn
	if ttl == 0 {
		ttl = 3600
	}
	variant := o.Variant
	if variant == "" {
		variant = "webp"
	}
	if ttl < 60 || ttl > 604800 || (variant != "webp" && variant != "avif") {
		return zero, invalid("Use a supported variant and lifetime from 60 to 604800 seconds.")
	}
	r, e := jsonRequest("POST", fmt.Sprintf("/api/upload/%d/private-url", id), map[string]any{"expires_in": ttl, "variant": variant}, o.RequestOptions)
	if e != nil {
		return zero, e
	}
	r.assetID = id
	return perform(ctx, c.t, r, func(raw json.RawMessage) (PrivateURL, error) {
		d, e := dataEnvelope(raw)
		if e != nil {
			return zero, e
		}
		v, e := parsePrivateURL(d)
		if e == nil && v.AssetID != id {
			e = badResponse()
		}
		return v, e
	})
}
func (c *Client) ListUploads(ctx context.Context, o UploadFilters) (Page[UploadAsset], error) {
	var zero Page[UploadAsset]
	params, e := pagination(o.PageOptions)
	if e != nil {
		return zero, e
	}
	project := o.ProjectID
	if project == "" {
		project = c.projectID
	}
	if project == "" {
		return zero, invalid("Upload listing requires ProjectID; uploads and asset management need only an API key.")
	}
	if e = checkUUID(project); e != nil {
		return zero, e
	}
	params.Set("project_id", project)
	if o.Visibility != "" {
		if !validVisibility(o.Visibility) {
			return zero, invalid("Invalid visibility filter.")
		}
		params.Set("visibility", string(o.Visibility))
	}
	if o.DeletionStatus != "" {
		if !validDeletion(o.DeletionStatus) {
			return zero, invalid("Invalid deletion filter.")
		}
		params.Set("deletion_status", string(o.DeletionStatus))
	}
	if o.Status != "" || o.StatusCode != 0 {
		if o.Status != "" && o.StatusCode != 0 {
			return zero, invalid("Supply either Status or StatusCode.")
		}
		n := o.StatusCode
		if o.Status != "" {
			n = map[ProcessingStatus]int{Pending: 1, Processing: 2, Processed: 3, Failed: 4, Unprocessable: 5}[o.Status]
		}
		if n < 1 || n > 6 {
			return zero, invalid("Invalid processing status filter.")
		}
		params.Set("status", strconv.Itoa(n))
	}
	if len(o.ExternalID) > 512 || !utf8.ValidString(o.ExternalID) {
		return zero, invalid("ExternalID supports at most 512 UTF-8 bytes.")
	}
	if o.ExternalID != "" {
		params.Set("external_id", o.ExternalID)
	}
	if o.Data != nil {
		data := CustomerData{}
		for k, v := range o.Data {
			data[k] = v
		}
		data, e = customerData(data, 4096)
		if e != nil {
			return zero, e
		}
		for k, v := range data {
			params.Set("data."+k, v.(string))
		}
	}
	return perform(ctx, c.t, request{method: "GET", path: "/api/uploads?" + params.Encode(), options: o.RequestOptions}, func(raw json.RawMessage) (Page[UploadAsset], error) {
		if _, e := success(raw); e != nil {
			return zero, e
		}
		return parsePage(raw, "data", parseUploadAsset)
	})
}

// IterateUploads lazily retrieves one bounded page at a time. Breaking the range
// stops requests. Concurrent server changes can affect offset pagination.
func (c *Client) IterateUploads(ctx context.Context, o UploadFilters) iter.Seq2[UploadAsset, error] {
	return func(yield func(UploadAsset, error) bool) {
		page := o.Page
		if page == 0 {
			page = 1
		}
		for {
			o.Page = page
			result, e := c.ListUploads(ctx, o)
			if e != nil {
				yield(UploadAsset{}, e)
				return
			}
			if result.Page != page || len(result.Data) > result.Limit {
				yield(UploadAsset{}, badResponse())
				return
			}
			for _, row := range result.Data {
				if !yield(row, nil) {
					return
				}
			}
			if len(result.Data) == 0 || int64(result.Page) >= (result.Total+int64(result.Limit)-1)/int64(result.Limit) {
				return
			}
			page++
		}
	}
}
func (c *Client) ListAssets(ctx context.Context, o AssetFilters) (Page[AssetState], error) {
	var zero Page[AssetState]
	params, e := pagination(o.PageOptions)
	if e != nil {
		return zero, e
	}
	if o.DeletionStatus != "" {
		if !validDeletion(o.DeletionStatus) {
			return zero, invalid("Invalid deletion filter.")
		}
		params.Set("deletion_status", string(o.DeletionStatus))
	}
	return perform(ctx, c.t, request{method: "GET", path: "/api/assets?" + params.Encode(), options: o.RequestOptions}, func(raw json.RawMessage) (Page[AssetState], error) { return parsePage(raw, "data", parseAsset) })
}
func (c *Client) GetAsset(ctx context.Context, id int64, o RequestOptions) (AssetState, error) {
	if e := checkID(id); e != nil {
		return AssetState{}, e
	}
	return perform(ctx, c.t, request{method: "GET", path: fmt.Sprintf("/api/assets/%d", id), options: o}, func(raw json.RawMessage) (AssetState, error) {
		v, e := parseAsset(raw)
		if e == nil && v.ID != id {
			e = badResponse()
		}
		return v, e
	})
}
func (c *Client) DeleteAsset(ctx context.Context, id int64, o RequestOptions) (AssetState, error) {
	if e := checkID(id); e != nil {
		return AssetState{}, e
	}
	return perform(ctx, c.t, request{method: "DELETE", path: fmt.Sprintf("/api/assets/%d", id), options: o, assetID: id}, func(raw json.RawMessage) (AssetState, error) {
		v, e := parseAsset(raw)
		if e == nil && (v.ID != id || v.DeletionStatus == Active) {
			e = badResponse()
		}
		return v, e
	})
}
func (c *Client) BulkDeleteAssets(ctx context.Context, ids []int64, o RequestOptions) (BulkDeletion, error) {
	var zero BulkDeletion
	if len(ids) < 1 || len(ids) > 100 {
		return zero, invalid("Select 1 to 100 explicit asset IDs.")
	}
	expected := []int64{}
	seen := map[int64]bool{}
	for _, id := range ids {
		if e := checkID(id); e != nil {
			return zero, e
		}
		if !seen[id] {
			seen[id] = true
			expected = append(expected, id)
		}
	}
	r, e := jsonRequest("POST", "/api/assets/bulk-delete", map[string]any{"asset_ids": ids}, o)
	if e != nil {
		return zero, e
	}
	return perform(ctx, c.t, r, func(raw json.RawMessage) (BulkDeletion, error) { return parseBulk(raw, expected) })
}
