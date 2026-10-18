<?php
declare(strict_types=1);
namespace Kompressr;
use Kompressr\Internal\Transport;
use Kompressr\Internal\Validate as V;

/** Project-user and scoped-key administration; requires a project credential. */
final class PlatformClient
{
    private readonly Transport $transport;
    public function __construct(#[\SensitiveParameter] array $options) { $this->transport = new Transport($options); }
    public function __debugInfo(): array { return ['apiKey' => '[redacted]']; }
    public function __serialize(): array { throw new \LogicException('Clients cannot be serialized.'); }
    public function listUsers(array $options = []): array
    {
        return $this->transport->request('/api/platform/project-users?' . Client::query(Client::pagination($options)), options: $options, parse: static function (#[\SensitiveParameter] $value): array {
            $v = V::success($value); $out = V::page($v, V::user(...), 'project_users');
            foreach (['project_active_count', 'org_active_count'] as $key) { if (V::number($v->{$key} ?? null, true) < 0) V::response(); $out[$key] = $v->{$key}; }
            if (property_exists($v, 'usage_period')) {
                $period = V::object($v->usage_period);
                foreach (['start', 'end'] as $key) if (!preg_match('/^\d{4}-\d{2}-\d{2}$/D', V::string($period->{$key} ?? null))) V::response();
                $out['usage_period'] = V::array($period);
            }
            return $out;
        });
    }
    public function createUser(#[\SensitiveParameter] array $input, array $options = []): array
    {
        $body = ['customer_user_id' => V::text($input['customerUserId'] ?? null, 256, 'customerUserId', true)] + self::userFields($input);
        return $this->write('/api/platform/project-users', 'POST', (object) $body, static function (#[\SensitiveParameter] $v): array {
            if (!is_bool($v->created ?? null)) V::response();
            return ['created' => $v->created, 'project_user' => V::user($v->project_user ?? null)];
        }, $options);
    }
    public function updateUser(mixed $id, #[\SensitiveParameter] array $input, array $options = []): array
    {
        return $this->write(self::path($id), 'PATCH', (object) self::userFields($input), static fn(#[\SensitiveParameter] $v) => V::user($v->project_user ?? null), $options);
    }
    public function suspendUser(mixed $id, array $options = []): array { return $this->userAction($id, 'suspend', $options); }
    public function reactivateUser(mixed $id, array $options = []): array { return $this->userAction($id, 'reactivate', $options); }
    public function listUploadKeys(mixed $id, array $options = []): array
    {
        return $this->transport->request(self::path($id) . '/upload-keys?' . Client::query(Client::pagination($options)), options: $options, parse: static fn(#[\SensitiveParameter] $v) => V::page(V::success($v), V::key(...), 'upload_keys'));
    }
    public function createUploadKey(mixed $id, #[\SensitiveParameter] array $input, array $options = []): IssuedKey
    {
        $body = ['name' => V::text($input['name'] ?? null, 120, 'name', true)];
        if (array_key_exists('scopes', $input)) {
            if (!is_array($input['scopes']) || !array_is_list($input['scopes']) || $input['scopes'] === []) V::invalid('scopes must be a nonempty list; omit scopes to use the server defaults.');
            foreach ($input['scopes'] as $scope) V::choice($scope, V::SCOPES, 'scope');
            $body['scopes'] = $input['scopes'];
        }
        if (array_key_exists('allowedVisibility', $input)) $body['allowed_visibility'] = V::choice($input['allowedVisibility'], ['public', 'private', 'both'], 'allowedVisibility');
        if (array_key_exists('allowedAssetTypes', $input)) {
            if (!is_array($input['allowedAssetTypes']) || !array_is_list($input['allowedAssetTypes'])) V::invalid('allowedAssetTypes must be a list.');
            foreach ($input['allowedAssetTypes'] as $kind) V::positive($kind, 'asset type', V::MAX_ID);
            $body['allowed_asset_types'] = $input['allowedAssetTypes'];
        }
        if (array_key_exists('expiresAt', $input)) {
            if (!is_string($input['expiresAt']) || !preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/D', $input['expiresAt']) || ($time = strtotime($input['expiresAt'])) === false || $time <= time()) V::invalid('expiresAt must be a future RFC 3339 timestamp.');
            $body['expires_at'] = $input['expiresAt'];
        }
        return $this->write(self::path($id) . '/upload-keys', 'POST', (object) $body, self::issued(...), $options);
    }
    public function rotateUploadKey(mixed $id, mixed $keyId, array $options = []): IssuedKey
    {
        return $this->write(self::path($id) . '/upload-keys/' . V::uuid($keyId) . '/rotate', 'POST', null, self::issued(...), $options);
    }
    public function revokeUploadKey(mixed $id, mixed $keyId, array $options = []): void
    {
        $this->write(self::path($id) . '/upload-keys/' . V::uuid($keyId) . '/revoke', 'POST', null, static fn($v) => null, $options);
    }
    private static function path(mixed $id): string { return '/api/platform/project-users/' . V::uuid($id); }
    private static function userFields(#[\SensitiveParameter] array $input): array
    {
        $body = [];
        if (array_key_exists('displayName', $input)) $body['display_name'] = V::text($input['displayName'], 120, 'displayName');
        if (array_key_exists('metadata', $input)) $body['metadata'] = V::data($input['metadata'], 8192);
        return $body;
    }
    private static function issued(#[\SensitiveParameter] \stdClass $v): IssuedKey
    {
        return new IssuedKey(V::string($v->id ?? null), V::string($v->key_id ?? null), V::string($v->api_key ?? null), property_exists($v, 'upload_key') ? V::key($v->upload_key) : null);
    }
    private function write(string $path, string $method, #[\SensitiveParameter] mixed $body, callable $parse, array $options): mixed
    {
        return $this->transport->request($path, $method, $body === null ? null : V::json($body), $options, static fn(#[\SensitiveParameter] $value) => $parse(V::success($value)));
    }
    private function userAction(mixed $id, string $action, array $options): array
    {
        return $this->write(self::path($id) . '/' . $action, 'POST', null, static fn(#[\SensitiveParameter] $v) => V::user($v->project_user ?? null), $options);
    }
}
