<?php
declare(strict_types=1);
namespace Kompressr\Internal;
use Kompressr\KompressrException;

/** @internal */
final class Validate
{
    public const MAX_ID = 9007199254740991;
    public const DELETION = ['active', 'deleting', 'deleted', 'legacy_deleted'];
    public const SCOPES = ['upload', 'status', 'list', 'private_url', 'delete'];
    public static function invalid(string $message): never { throw new KompressrException($message, 'validation', 'INVALID_ARGUMENT'); }
    public static function response(string $message = 'The API returned an invalid response.'): never { throw new KompressrException($message, 'invalid_response', 'INVALID_RESPONSE'); }
    public static function positive(mixed $value, string $name, int $max = 2147483647): int
    {
        if (!is_int($value) || $value < 1 || $value > $max) self::invalid("$name must be a positive integer no greater than $max.");
        return $value;
    }
    public static function id(mixed $value): int { return self::positive($value, 'assetId', self::MAX_ID); }
    public static function uuid(mixed $value): string
    {
        if (!is_string($value) || !preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iD', $value)) self::invalid('Use a UUID identifier.');
        return $value;
    }
    public static function text(mixed $value, int $max, string $name, bool $nonempty = false): string
    {
        if (!is_string($value) || preg_match('//u', $value) !== 1 || strlen(trim($value)) > $max || ($nonempty && trim($value) === '')) self::invalid("$name must be valid UTF-8, at most $max bytes" . ($nonempty ? ' and nonempty.' : '.'));
        return $value;
    }
    public static function choice(mixed $value, array $choices, string $name): string
    {
        if (!is_string($value) || !in_array($value, $choices, true)) self::invalid("Unsupported $name.");
        return $value;
    }
    public static function data(#[\SensitiveParameter] mixed $value, int $max = 4096): \stdClass
    {
        if ((!is_array($value) && !$value instanceof \stdClass) || (is_array($value) && $value !== [] && array_is_list($value))) self::invalid('Customer data must be an object of scalar fields.');
        $fields = (array) $value;
        if (count($fields) > 5) self::invalid('Customer data supports at most five fields.');
        $result = new \stdClass();
        foreach ($fields as $key => $item) {
            $key = trim((string) $key);
            if ($key === '' || strlen($key) > 64 || preg_match('//u', $key) !== 1 || property_exists($result, $key)) self::invalid('Customer data keys must be unique and contain 1–64 UTF-8 bytes.');
            if (is_string($item)) { if (strlen($item) > 512 || preg_match('//u', $item) !== 1) self::invalid('Customer data strings support at most 512 UTF-8 bytes.'); }
            elseif ($item !== null && !is_bool($item) && !is_int($item) && !(is_float($item) && is_finite($item))) self::invalid('Customer data values must be finite scalar values.');
            $result->{$key} = $item;
        }
        if (strlen(self::json($result)) > $max) self::invalid('Encoded customer data is too large.');
        return $result;
    }
    public static function json(#[\SensitiveParameter] mixed $value): string
    {
        try { return json_encode($value, JSON_THROW_ON_ERROR | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES); }
        catch (\JsonException) { self::invalid('Input cannot be encoded as JSON.'); }
    }
    public static function object(#[\SensitiveParameter] mixed $value): \stdClass
    {
        if (!$value instanceof \stdClass) self::response();
        return $value;
    }
    public static function string(#[\SensitiveParameter] mixed $value): string
    {
        if (!is_string($value) || trim($value) === '') self::response();
        return $value;
    }
    public static function number(mixed $value, bool $integer = false): int|float
    {
        if ((!is_int($value) && !is_float($value)) || !is_finite((float) $value) || ($integer && (!is_int($value) || abs($value) > self::MAX_ID))) self::response();
        return $value;
    }
    public static function outId(mixed $value): int
    {
        if (self::number($value, true) < 1) self::response();
        return $value;
    }
    public static function optionalStrings(#[\SensitiveParameter] \stdClass $v, array $names): void
    {
        foreach ($names as $name) if (property_exists($v, $name) && !is_string($v->{$name})) self::response();
    }
    public static function urls(#[\SensitiveParameter] \stdClass $v): void
    {
        foreach (['cdn_url', 'cdn_url_avif', 'private_url'] as $name) {
            if (!property_exists($v, $name)) continue;
            $url = parse_url(self::string($v->{$name}));
            if (!$url || !in_array($url['scheme'] ?? '', ['http', 'https'], true) || empty($url['host']) || isset($url['user']) || isset($url['pass']) || preg_match('/[\x00-\x20\x7f]/', $v->{$name})) self::response('Invalid delivery URL.');
        }
    }
    public static function deletion(mixed $value): string
    {
        if (!in_array($value, self::DELETION, true)) self::response('Missing or invalid deletion status.');
        return $value;
    }
    public static function upload(#[\SensitiveParameter] mixed $value, bool $accepted = false): array
    {
        $v = self::object($value);
        $id = self::outId($v->{$accepted ? 'asset_id' : 'id'} ?? null);
        if (!in_array($v->status ?? null, ['pending', 'processing', 'processed', 'failed', 'unprocessable', 'unknown'], true) || !in_array($v->visibility ?? null, ['public', 'private'], true)) self::response();
        self::deletion($v->deletion_status ?? null);
        if (self::number($v->original_size ?? null, true) < 0) self::response();
        if ($accepted) self::string($v->original_name ?? null);
        self::optionalStrings($v, ['original_name', 'deletion_requested_at', 'external_id', 'created_at', 'input_format', 'output_format', 'private_url_expires_at']);
        self::string($v->asset_type ?? null); self::urls($v);
        if ($v->visibility === 'private' && (property_exists($v, 'cdn_url') || property_exists($v, 'cdn_url_avif'))) self::response('Private asset response contains a public URL.');
        if ($v->deletion_status !== 'active' && (property_exists($v, 'cdn_url') || property_exists($v, 'cdn_url_avif') || property_exists($v, 'private_url'))) self::response('Deleted asset response contains a delivery URL.');
        if (property_exists($v, 'data')) { try { self::data($v->data, 8192); } catch (KompressrException) { self::response('Invalid customer data response.'); } }
        if (property_exists($v, 'options')) foreach (self::object($v->options) as $item) if (!is_string($item)) self::response();
        if (!$accepted) {
            if (self::number($v->kompressd_size ?? null, true) < 0 || !is_bool($v->can_generate_private_url ?? null)) self::response();
            self::number($v->savings_percent ?? null);
        }
        $out = self::array($v); unset($out['asset_id']); $out['id'] = $id; return $out;
    }
    public static function privateUrl(#[\SensitiveParameter] mixed $value): array
    {
        $v = self::object($value); self::outId($v->asset_id ?? null);
        if (!in_array($v->variant ?? null, ['webp', 'avif'], true)) self::response();
        self::urls($v); self::string($v->private_url ?? null); self::string($v->expires_at ?? null);
        $ttl = self::number($v->expires_in ?? null, true); if ($ttl < 60 || $ttl > 604800) self::response();
        return self::array($v);
    }
    public static function asset(#[\SensitiveParameter] mixed $value): array
    {
        $v = self::object($value); self::outId($v->id ?? null);
        if (self::number($v->kind ?? null, true) < 1 || self::number($v->storage_credited_mb ?? null, true) < 0) self::response();
        self::string($v->project_id ?? null); self::number($v->processing_status ?? null, true); self::deletion($v->deletion_status ?? null);
        if (!in_array($v->source ?? null, ['upload', 'origin'], true)) self::response();
        self::optionalStrings($v, ['deletion_requested_at']);
        if (property_exists($v, 'accounting_status') && !in_array($v->accounting_status, ['pending', 'settled', 'unavailable'], true)) self::response();
        if (property_exists($v, 'last_failure')) { $f = self::object($v->last_failure); foreach (['code', 'message', 'at'] as $key) self::string($f->{$key} ?? null); }
        return self::array($v);
    }
    public static function page(#[\SensitiveParameter] mixed $value, callable $parse, string $key = 'data'): array
    {
        $v = self::object($value);
        if (!is_array($v->{$key} ?? null) || self::number($v->page ?? null, true) < 1 || self::number($v->limit ?? null, true) < 1 || self::number($v->total ?? null, true) < 0) self::response();
        return ['data' => array_map($parse, $v->{$key}), 'page' => $v->page, 'limit' => $v->limit, 'total' => $v->total];
    }
    public static function bulk(#[\SensitiveParameter] mixed $value, array $expected): array
    {
        $v = self::object($value); $counts = self::object($v->counts ?? null);
        if (!is_array($v->results ?? null) || count($v->results) !== count($expected)) self::response();
        $accepted = 0;
        foreach ($v->results as $index => $row) {
            $item = self::object($row);
            if (($item->id ?? null) !== $expected[$index] || !is_bool($item->accepted ?? null)) self::response();
            self::number($item->status ?? null, true);
            if ($item->accepted) {
                $state = self::asset($item->state ?? null);
                if (!in_array($item->status, [200, 202], true) || $state['id'] !== $item->id || $state['deletion_status'] === 'active') self::response();
                $accepted++;
            } else { if ($item->status < 400) self::response(); self::string($item->error ?? null); }
        }
        if (($counts->total ?? null) !== count($expected) || ($counts->accepted ?? null) !== $accepted || ($counts->failed ?? null) !== count($expected) - $accepted) self::response();
        return self::array($v);
    }
    public static function user(#[\SensitiveParameter] mixed $value): array
    {
        $v = self::object($value);
        foreach (['id', 'project_id', 'customer_user_id'] as $key) self::string($v->{$key} ?? null);
        if (!in_array($v->status ?? null, ['active', 'suspended'], true)) self::response();
        self::optionalStrings($v, ['display_name', 'created_at', 'last_seen_at', 'last_upload_at', 'last_key_used_at']);
        foreach (['asset_count', 'storage_bytes', 'active_key_count', 'bandwidth_bytes_current_period', 'requests_current_period'] as $key) if (property_exists($v, $key) && self::number($v->{$key}, true) < 0) self::response();
        if (property_exists($v, 'metadata')) { try { self::data($v->metadata, 8192); } catch (KompressrException) { self::response('Invalid project user metadata.'); } }
        return self::array($v);
    }
    public static function key(#[\SensitiveParameter] mixed $value): array
    {
        $v = self::object($value);
        foreach (['id', 'key_id', 'project_id', 'project_user_id', 'name'] as $key) self::string($v->{$key} ?? null);
        if (!is_array($v->scopes ?? null) || !in_array($v->allowed_visibility ?? null, ['public', 'private', 'both'], true)) self::response();
        foreach ($v->scopes as $scope) if (!in_array($scope, self::SCOPES, true)) self::response();
        if (property_exists($v, 'allowed_asset_types')) {
            if (!is_array($v->allowed_asset_types)) self::response();
            foreach ($v->allowed_asset_types as $kind) self::outId($kind);
        }
        foreach (['expires_at', 'revoked_at', 'last_used_at'] as $name) if (property_exists($v, $name) && $v->{$name} !== null && !is_string($v->{$name})) self::response();
        self::optionalStrings($v, ['created_at']);
        // Key metadata must not propagate an unexpected plaintext credential into routine debug output.
        return array_intersect_key(self::array($v), array_flip(['id', 'key_id', 'project_id', 'project_user_id', 'name', 'scopes', 'allowed_visibility', 'allowed_asset_types', 'expires_at', 'revoked_at', 'last_used_at', 'created_at']));
    }
    public static function success(#[\SensitiveParameter] mixed $value): \stdClass
    {
        $v = self::object($value); if (($v->success ?? null) !== true) self::response(); return $v;
    }
    public static function array(#[\SensitiveParameter] mixed $value): mixed
    {
        if ($value instanceof \stdClass) $value = (array) $value;
        return is_array($value) ? array_map(self::array(...), $value) : $value;
    }
}
