package kompressr

import (
	"context"
	"fmt"
	"regexp"
	"strings"
	"time"
)

type ErrorKind string

const (
	KindValidation      ErrorKind = "validation"
	KindAPI             ErrorKind = "api"
	KindNetwork         ErrorKind = "network"
	KindTimeout         ErrorKind = "timeout"
	KindCancelled       ErrorKind = "cancelled"
	KindInvalidResponse ErrorKind = "invalid_response"
	KindProcessing      ErrorKind = "processing"
)

// Error contains safe diagnostic fields, never raw response bodies or credentials.
// Status and AssetID are zero when unknown. MayHaveSucceeded does not imply a
// write succeeded; inspect its outcome before deciding to repeat it.
type Error struct {
	Kind             ErrorKind     `json:"kind"`
	Code             string        `json:"code"`
	Message          string        `json:"message"`
	Status           int           `json:"status,omitempty"`
	RetryAfter       time.Duration `json:"retry_after,omitempty"`
	AssetID          int64         `json:"asset_id,omitempty"`
	MayHaveSucceeded bool          `json:"may_have_succeeded"`
}

func (e *Error) Error() string    { return e.Code + ": " + e.Message }
func (e *Error) GoString() string { return e.Error() }
func (e *Error) Is(target error) bool {
	return e.Kind == KindTimeout && target == context.DeadlineExceeded || e.Kind == KindCancelled && target == context.Canceled
}
func invalid(message string) *Error {
	return &Error{Kind: KindValidation, Code: "INVALID_ARGUMENT", Message: message}
}
func badResponse() *Error {
	return &Error{Kind: KindInvalidResponse, Code: "INVALID_RESPONSE", Message: "The API returned an invalid response."}
}

var bearerPattern = regexp.MustCompile(`(?i)Bearer\s+\S+`)
var urlPattern = regexp.MustCompile(`(?i)https?://[^\s<>"']+`)
var credentialPattern = regexp.MustCompile(`(?i)\b(?:api_key|password|token|secret|signature)\s*[=:]\s*\S+`)

func safeMessage(s, secret string) string {
	if secret != "" {
		s = strings.ReplaceAll(s, secret, "[redacted]")
	}
	s = bearerPattern.ReplaceAllString(s, "Bearer [redacted]")
	s = urlPattern.ReplaceAllString(s, "[URL redacted]")
	s = credentialPattern.ReplaceAllString(s, "[credential redacted]")
	s = strings.Map(func(r rune) rune {
		if r < 32 && r != '\n' && r != '\t' {
			return ' '
		}
		return r
	}, s)
	r := []rune(s)
	if len(r) > 500 {
		s = string(r[:500])
	}
	return s
}
func httpFailure(status int, message, code, secret string) *Error {
	if message == "" {
		message = fmt.Sprintf("Kompressr returned HTTP %d.", status)
	}
	if code == "" {
		code = "API_ERROR"
	}
	return &Error{Kind: KindAPI, Code: safeMessage(code, secret), Message: safeMessage(message, secret), Status: status}
}
