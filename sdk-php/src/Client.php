<?php
declare(strict_types=1);
namespace Kompressr;
use Kompressr\Internal\Transport;
use Kompressr\Internal\Validate as V;

/** Synchronous backend client. Options use camelCase; result fields use API snake_case. */
final class Client
{
    public readonly PlatformClient $platform;
    public readonly string $apiBaseUrl;
    public readonly string $uploadBaseUrl;
    private readonly Transport $transport;
    private readonly ?string $projectId;

    /** @param array{apiKey:string,projectId?:string,apiBaseUrl?:string,uploadBaseUrl?:string,requestTimeoutMs?:int,uploadTimeoutMs?:int,maxReadRetries?:int} $options */
    public function __construct(#[\SensitiveParameter] array $options)
    {
        $this->transport = new Transport($options);
        $this->projectId = isset($options['projectId']) ? V::uuid($options['projectId']) : null;
        $this->apiBaseUrl = $this->transport->apiBaseUrl; $this->uploadBaseUrl = $this->transport->uploadBaseUrl;
        $this->platform = new PlatformClient($options);
    }
    public function __debugInfo(): array { return ['apiBaseUrl' => $this->apiBaseUrl, 'uploadBaseUrl' => $this->uploadBaseUrl, 'apiKey' => '[redacted]']; }
    public function __serialize(): array { throw new \LogicException('Clients cannot be serialized.'); }
    public function uploadFile(#[\SensitiveParameter] string $path, #[\SensitiveParameter] array $options = []): array
    {
        if ($path === '' || str_contains($path, "\0") || str_contains($path, '://')) V::invalid('Supply a readable regular file path.');
        $real = realpath($path);
        if ($real === false || !is_file($real) || !is_readable($real)) V::invalid('Supply a readable regular file path.');
        return $this->upload(new \CURLFile($real, 'application/octet-stream', self::filename(basename($real))), $options);
    }
    public function uploadBytes(#[\SensitiveParameter] string $bytes, string $filename, #[\SensitiveParameter] array $options = []): array
    {
        return $this->upload(new \CURLStringFile($bytes, self::filename($filename), 'application/octet-stream'), $options);
    }
    private static function filename(string $name): string
    {
        if (trim($name) === '' || preg_match('/[\x00-\x1f\x7f]/', $name) || preg_match('//u', $name) !== 1) V::invalid('Supply a nonempty UTF-8 filename without control characters.');
        $name = basename(str_replace('\\', '/', $name));
        if ($name === '' || $name === '.' || $name === '..') V::invalid('Supply a filename.');
        return $name;
    }
    private function upload(#[\SensitiveParameter] \CURLFile|\CURLStringFile $file, #[\SensitiveParameter] array $options): array
    {
        $fields = [];
        if (array_key_exists('visibility', $options)) $fields['visibility'] = V::choice($options['visibility'], ['public', 'private'], 'visibility');
        if (array_key_exists('quality', $options)) $fields['kmp-quality'] = V::choice($options['quality'], ['480p', '720p', '1080p', '4k'], 'quality');
        if (array_key_exists('privateUrlExpiresIn', $options)) {
            $ttl = V::positive($options['privateUrlExpiresIn'], 'privateUrlExpiresIn', 604800);
            if ($ttl < 60) V::invalid('Private URL lifetime must be at least 60 seconds.');
            $fields['private_url_expires_in'] = (string) $ttl;
        }
        if (array_key_exists('data', $options)) $fields['data'] = V::json(V::data($options['data']));
        $fields['file'] = $file; // Multipart metadata must precede the file.
        return $this->transport->request('/api/upload', 'POST', $fields, $options, static function (#[\SensitiveParameter] $value): array {
            $v = V::success($value); $out = V::upload($v->data ?? null, true);
            if (is_string($v->warning ?? null)) $out['warning'] = $v->warning;
            return $out;
        }, upload: true, recoverUploadId: true);
    }
    public function getUploadStatus(mixed $id, #[\SensitiveParameter] array $options = []): array
    {
        $id = V::id($id);
        return $this->transport->request("/api/upload/$id/status", options: $options, parse: static function (#[\SensitiveParameter] $value) use ($id): array {
            $v = V::success($value); $out = V::upload($v->data ?? null);
            if ($out['id'] !== $id) V::response('API returned a different asset ID.'); return $out;
        });
    }
    public function waitUntilReady(mixed $id, #[\SensitiveParameter] array $options = []): array
    {
        $id = V::id($id); $timeout = V::positive($options['timeoutMs'] ?? 120000, 'timeoutMs');
        $interval = V::positive($options['pollIntervalMs'] ?? 2000, 'pollIntervalMs', 30000);
        $deadline = Transport::now() + $timeout;
        $stopped = static function (bool $cancelled) use ($id): KompressrException {
            return new KompressrException('Waiting ' . ($cancelled ? 'cancelled' : 'timed out') . '; resume with the saved asset ID.', $cancelled ? 'cancelled' : 'timeout', $cancelled ? 'WAIT_CANCELLED' : 'WAIT_TIMEOUT', assetId: $id);
        };
        try {
            while (true) {
                if (Transport::cancelled($options)) throw $stopped(true);
                if (Transport::now() >= $deadline) throw $stopped(false);
                $request = $options; $request['timeoutMs'] = min($this->transport->requestTimeoutMs(), max(1, (int) ceil($deadline - Transport::now())));
                $out = $this->getUploadStatus($id, $request);
                if (Transport::cancelled($options)) throw $stopped(true);
                if (Transport::now() >= $deadline) throw $stopped(false);
                if ($out['deletion_status'] !== 'active') throw new KompressrException('The asset is being deleted or has been deleted.', 'processing', 'ASSET_DELETED', assetId: $id);
                if ($out['status'] === 'processed') {
                    if ($out['visibility'] === 'public' && empty($out['cdn_url'])) V::response('Processed public asset has no delivery URL.');
                    if ($out['visibility'] === 'private' && !$out['can_generate_private_url']) V::response('Processed private asset cannot generate a delivery link.');
                    return $out;
                }
                if (!in_array($out['status'], ['pending', 'processing'], true)) throw new KompressrException('Asset processing failed.', 'processing', 'PROCESSING_FAILED', assetId: $id);
                Transport::sleep(min(30000, $interval + random_int(0, (int) min(250, $interval / 10))), $deadline, $options);
            }
        } catch (KompressrException $e) {
            if (Transport::cancelled($options) || $e->kind === 'cancelled') throw $stopped(true);
            if (Transport::now() >= $deadline) throw $stopped(false);
            throw new KompressrException($e->getMessage(), $e->kind, $e->errorCode, $e->status, $e->retryAfterMs, $id, $e->mayHaveSucceeded);
        }
    }
    public function generatePrivateUrl(mixed $id, #[\SensitiveParameter] array $options = []): array
    {
        $id = V::id($id); $ttl = V::positive($options['expiresIn'] ?? 3600, 'expiresIn', 604800);
        if ($ttl < 60) V::invalid('Private URL lifetime must be at least 60 seconds.');
        $variant = V::choice($options['variant'] ?? 'webp', ['webp', 'avif'], 'variant');
        return $this->transport->request("/api/upload/$id/private-url", 'POST', V::json(['expires_in' => $ttl, 'variant' => $variant]), $options, static function (#[\SensitiveParameter] $value) use ($id): array {
            $out = V::privateUrl(V::success($value)->data ?? null);
            if ($out['asset_id'] !== $id) V::response('API returned a different asset ID.'); return $out;
        }, assetId: $id);
    }
    public function listUploads(#[\SensitiveParameter] array $options = []): array
    {
        $params = self::pagination($options);
        $project = $options['projectId'] ?? $this->projectId;
        if ($project === null) V::invalid('Upload listing requires projectId.');
        $params['project_id'] = V::uuid($project);
        if (array_key_exists('visibility', $options)) $params['visibility'] = V::choice($options['visibility'], ['public', 'private'], 'visibility');
        if (array_key_exists('deletionStatus', $options)) $params['deletion_status'] = V::choice($options['deletionStatus'], V::DELETION, 'deletionStatus');
        if (array_key_exists('status', $options)) {
            $states = ['pending' => 1, 'processing' => 2, 'processed' => 3, 'failed' => 4, 'unprocessable' => 5];
            $status = is_string($options['status']) ? ($states[$options['status']] ?? null) : $options['status'];
            $params['status'] = V::positive($status, 'status', 6);
        }
        if (array_key_exists('externalId', $options)) {
            V::text($options['externalId'], 512, 'externalId');
            if (strlen($options['externalId']) > 512) V::invalid('externalId supports at most 512 UTF-8 bytes.');
            $params['external_id'] = $options['externalId'];
        }
        if (array_key_exists('data', $options)) foreach (V::data($options['data']) as $key => $value) {
            if (!is_string($value)) V::invalid('Data filter values must be strings.'); $params['data.' . $key] = $value;
        }
        return $this->transport->request('/api/uploads?' . self::query($params), options: $options, parse: static fn(#[\SensitiveParameter] $value) => V::page(V::success($value), V::upload(...)));
    }
    public function iterateUploads(#[\SensitiveParameter] array $options = []): \Generator
    {
        $next = V::positive($options['page'] ?? 1, 'page');
        while (true) {
            $page = $this->listUploads(array_replace($options, ['page' => $next]));
            if ($page['page'] !== $next || count($page['data']) > $page['limit']) V::response('Invalid pagination response.');
            foreach ($page['data'] as $row) yield $row;
            if ($page['data'] === [] || $page['page'] * $page['limit'] >= $page['total']) return;
            $next++;
        }
    }
    public function listAssets(#[\SensitiveParameter] array $options = []): array
    {
        $params = self::pagination($options);
        if (array_key_exists('deletionStatus', $options)) $params['deletion_status'] = V::choice($options['deletionStatus'], V::DELETION, 'deletionStatus');
        return $this->transport->request('/api/assets?' . self::query($params), options: $options, parse: static fn(#[\SensitiveParameter] $value) => V::page($value, V::asset(...)));
    }
    public function getAsset(mixed $id, #[\SensitiveParameter] array $options = []): array
    {
        $id = V::id($id);
        return $this->transport->request("/api/assets/$id", options: $options, parse: static function (#[\SensitiveParameter] $value) use ($id): array {
            $out = V::asset($value); if ($out['id'] !== $id) V::response('API returned a different asset ID.'); return $out;
        });
    }
    public function deleteAsset(mixed $id, #[\SensitiveParameter] array $options = []): array
    {
        $id = V::id($id);
        return $this->transport->request("/api/assets/$id", 'DELETE', options: $options, parse: static function (#[\SensitiveParameter] $value) use ($id): array {
            $out = V::asset($value); if ($out['id'] !== $id || $out['deletion_status'] === 'active') V::response('Deletion was not accepted for the requested asset.'); return $out;
        }, assetId: $id);
    }
    public function bulkDeleteAssets(array $ids, #[\SensitiveParameter] array $options = []): array
    {
        if (!array_is_list($ids) || count($ids) < 1 || count($ids) > 100) V::invalid('Select 1 to 100 explicit asset IDs.');
        foreach ($ids as $id) V::id($id);
        $expected = array_values(array_unique($ids, SORT_NUMERIC));
        return $this->transport->request('/api/assets/bulk-delete', 'POST', V::json(['asset_ids' => $ids]), $options, static fn(#[\SensitiveParameter] $value) => V::bulk($value, $expected));
    }
    /** @internal */
    public static function pagination(array $options): array { return ['page' => V::positive($options['page'] ?? 1, 'page'), 'limit' => V::positive($options['limit'] ?? 20, 'limit', 100)]; }
    /** @internal */
    public static function query(array $params): string { return http_build_query($params, '', '&', PHP_QUERY_RFC3986); }
}
