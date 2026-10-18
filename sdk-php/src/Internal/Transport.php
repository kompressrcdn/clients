<?php
declare(strict_types=1);
namespace Kompressr\Internal;
use Kompressr\KompressrException;

/** @internal */
final class Transport
{
    public readonly string $apiBaseUrl;
    public readonly string $uploadBaseUrl;
    private string $key;
    private int $requestTimeout;
    private int $uploadTimeout;
    private int $retries;

    public function __construct(#[\SensitiveParameter] array $options)
    {
        if (PHP_INT_SIZE < 8 || !extension_loaded('curl') || !(curl_version()['features'] & CURL_VERSION_ASYNCHDNS)) Validate::invalid('Use 64-bit PHP with ext-curl and asynchronous DNS support.');
        $key = $options['apiKey'] ?? null;
        if (!is_string($key) || trim($key) === '' || preg_match('/[\x00-\x20\x7f]/', $key)) Validate::invalid('Supply a nonempty API key without whitespace or control characters.');
        if (array_key_exists('environment', $options)) Validate::invalid('Use explicit apiBaseUrl and uploadBaseUrl options.');
        $this->key = $key;
        $this->apiBaseUrl = self::origin($options['apiBaseUrl'] ?? 'https://kompressr.com');
        $this->uploadBaseUrl = self::origin($options['uploadBaseUrl'] ?? ($this->apiBaseUrl === 'https://kompressr.com' ? 'https://uploads.kompressr.com' : $this->apiBaseUrl));
        $this->requestTimeout = Validate::positive($options['requestTimeoutMs'] ?? 30000, 'requestTimeoutMs');
        $this->uploadTimeout = Validate::positive($options['uploadTimeoutMs'] ?? 600000, 'uploadTimeoutMs');
        $retries = $options['maxReadRetries'] ?? 2;
        if (!is_int($retries) || $retries < 0 || $retries > 5) Validate::invalid('maxReadRetries must be an integer from 0 to 5.');
        $this->retries = $retries;
    }
    public function __debugInfo(): array { return ['apiBaseUrl' => $this->apiBaseUrl, 'uploadBaseUrl' => $this->uploadBaseUrl, 'apiKey' => '[redacted]']; }
    public function __serialize(): array { throw new \LogicException('Clients cannot be serialized.'); }
    private static function origin(mixed $value): string
    {
        if (!is_string($value) || preg_match('/[\x00-\x20\x7f\\\\]/', $value)) Validate::invalid('Base URL must be an absolute HTTP(S) origin.');
        $v = parse_url($value);
        if (!$v || !in_array($v['scheme'] ?? '', ['http', 'https'], true) || empty($v['host']) || isset($v['user']) || isset($v['pass']) || isset($v['query']) || isset($v['fragment']) || !in_array($v['path'] ?? '', ['', '/'], true)) Validate::invalid('Base URL must have no credentials, path, query or fragment.');
        return strtolower($v['scheme'] . '://' . $v['host']) . (isset($v['port']) && !(($v['scheme'] === 'https' && $v['port'] === 443) || ($v['scheme'] === 'http' && $v['port'] === 80)) ? ':' . $v['port'] : '');
    }
    public function requestTimeoutMs(): int { return $this->requestTimeout; }
    public static function now(): float { return hrtime(true) / 1000000; }
    public static function cancelled(#[\SensitiveParameter] array $options): bool
    {
        if (!isset($options['cancel'])) return false;
        if (!is_callable($options['cancel'])) Validate::invalid('cancel must be a nonblocking callback returning bool.');
        try { $result = ($options['cancel'])(); } catch (\Throwable) { Validate::invalid('Cancellation callback failed.'); }
        if (!is_bool($result)) Validate::invalid('Cancellation callback must return bool.');
        return $result;
    }
    public static function sleep(float $ms, float $deadline, #[\SensitiveParameter] array $options): void
    {
        $end = min(self::now() + $ms, $deadline);
        do {
            if (self::cancelled($options)) throw new KompressrException('Request cancelled.', 'cancelled', 'REQUEST_CANCELLED');
            $remaining = $end - self::now();
            if ($remaining > 0) usleep((int) min(20000, ceil($remaining * 1000)));
        } while ($remaining > 0);
    }
    private function safe(#[\SensitiveParameter] mixed $value): string
    {
        if (!is_string($value)) return 'Kompressr request failed.';
        $value = str_replace($this->key, '[redacted]', $value);
        $value = preg_replace(['~Bearer\s+\S+~i', '~https?://[^\s<>"\x27]+~i', '~\b(?:api_key|password|token|secret|signature)\s*[=:]\s*\S+~i'], ['Bearer [redacted]', '[URL redacted]', '[credential redacted]'], $value);
        $value = substr($value ?? 'Kompressr request failed.', 0, 500);
        while ($value !== '' && preg_match('//u', $value) !== 1) $value = substr($value, 0, -1);
        return $value;
    }
    private static function retryDelay(array $headers, #[\SensitiveParameter] mixed $body): ?int
    {
        $delay = null;
        if (isset($headers['retry-after'])) {
            $header = trim($headers['retry-after']);
            if (is_numeric($header) && is_finite((float) $header) && (float) $header >= 0) $delay = (float) $header * 1000;
            elseif (($date = strtotime($header)) !== false) $delay = max(0, ($date - microtime(true)) * 1000);
        }
        if ($delay === null && $body instanceof \stdClass && (is_int($body->retry_after ?? null) || is_float($body->retry_after ?? null)) && is_finite((float) $body->retry_after) && $body->retry_after >= 0) $delay = $body->retry_after * 1000;
        if ($delay === null) return null;
        // PHP_INT_MAX rounds up when promoted to float on 64-bit PHP. Saturate
        // before casting, including overflow from converting seconds to milliseconds.
        if ($delay >= PHP_INT_MAX) return PHP_INT_MAX;
        return (int) ceil($delay);
    }
    public function request(string $path, string $method = 'GET', #[\SensitiveParameter] mixed $body = null, #[\SensitiveParameter] array $options = [], ?callable $parse = null, bool $upload = false, ?int $assetId = null, bool $recoverUploadId = false): mixed
    {
        $timeout = Validate::positive($options['timeoutMs'] ?? ($upload ? $this->uploadTimeout : $this->requestTimeout), 'timeoutMs');
        $deadline = self::now() + $timeout;
        $write = $method !== 'GET'; $dispatched = false; $status = null; $retryAfter = null;
        $context = static function (string $kind) use (&$dispatched, $write, &$status, &$assetId, &$retryAfter): KompressrException {
            return new KompressrException($kind === 'timeout' ? 'Request timed out. Inspect a possible write before retrying.' : ($kind === 'cancelled' ? 'Request cancelled.' : 'Unable to reach Kompressr. Check the configured endpoint and connection.'), $kind, match ($kind) {'timeout' => 'REQUEST_TIMEOUT', 'cancelled' => 'REQUEST_CANCELLED', default => 'NETWORK_ERROR'}, $status, $retryAfter, $assetId, $write && $dispatched);
        };
        for ($attempt = 0; ; $attempt++) {
            try {
                if (self::cancelled($options)) throw $context('cancelled');
                if (self::now() >= $deadline) throw $context('timeout');
                $status = null; $retryAfter = null;
                $result = $this->transfer($path, $method, $body, $options, $deadline, $upload, $dispatched, $status);
                [$status, $headers, $raw, $failure] = $result;
                if ($failure === 'cancelled' || self::cancelled($options)) throw $context('cancelled');
                if (self::now() >= $deadline || $failure === 'timeout') throw $context('timeout');
                if ($failure === 'network') throw $context('network');
                $ok = $status >= 200 && $status < 300;
                $decoded = null;
                if ($failure !== 'large') {
                    try { $decoded = json_decode($raw, false, 128, JSON_THROW_ON_ERROR); }
                    catch (\JsonException) { if ($ok) Validate::response('API returned a non-JSON response.'); }
                } elseif ($ok) Validate::response('API response exceeds the supported size.');
                if ($recoverUploadId && $ok && $decoded instanceof \stdClass && ($decoded->success ?? null) === true && ($decoded->data ?? null) instanceof \stdClass && is_int($decoded->data->asset_id ?? null) && $decoded->data->asset_id > 0 && $decoded->data->asset_id <= Validate::MAX_ID) $assetId = $decoded->data->asset_id;
                if (!$ok || ($decoded instanceof \stdClass && ($decoded->success ?? null) === false)) {
                    $retryAfter = self::retryDelay($headers, $decoded);
                    throw new KompressrException($this->safe($decoded instanceof \stdClass ? ($decoded->error ?? "Kompressr returned HTTP $status.") : "Kompressr returned HTTP $status."), 'api', $this->safe($decoded instanceof \stdClass ? ($decoded->code ?? 'API_ERROR') : 'API_ERROR'), $status, $retryAfter, $assetId, $write && ($ok || $status >= 500 || ($status >= 300 && $status < 400)));
                }
                try { $parsed = $parse ? $parse($decoded) : $decoded; }
                catch (KompressrException $e) { throw $e; }
                catch (\Throwable) { Validate::response(); }
                if (self::cancelled($options)) throw $context('cancelled');
                if (self::now() >= $deadline) throw $context('timeout');
                return $parsed;
            } catch (KompressrException $e) {
                if (self::now() >= $deadline) throw $context('timeout');
                if ($e->kind === 'invalid_response' || ($e->kind === 'validation' && $dispatched)) $e = new KompressrException($e->getMessage(), $e->kind, $e->errorCode, $status, $retryAfter, $assetId ?? $e->assetId, $write && $dispatched);
                $transient = $e->kind === 'network' || ($e->kind === 'api' && in_array($e->status, [429, 502, 503, 504], true));
                if ($write || !$transient || $attempt >= $this->retries) throw $e;
                try { self::sleep(max(250 * (2 ** $attempt) + random_int(0, 100), $e->retryAfterMs ?? 0), $deadline, $options); }
                catch (KompressrException $delayError) { if ($delayError->kind === 'cancelled') throw $context('cancelled'); throw $delayError; }
                if (self::now() >= $deadline) throw $context('timeout');
            }
        }
    }
    /** Fresh easy/multi handles prohibit stale-connection replay; HTTP/1.1 avoids HTTP/2 stream replay. */
    private function transfer(string $path, string $method, #[\SensitiveParameter] mixed $body, #[\SensitiveParameter] array $options, float $deadline, bool $upload, bool &$dispatched, ?int &$observedStatus): array
    {
        $curl = curl_init(); $multi = curl_multi_init();
        $headers = []; $status = &$observedStatus; $status = null; $raw = ''; $tooLarge = false; $headerSize = 0;
        $requestHeaders = ['Authorization: Bearer ' . $this->key, 'Accept: application/json', 'Expect:'];
        if (is_string($body)) $requestHeaders[] = 'Content-Type: application/json';
        $settings = [CURLOPT_URL => ($upload ? $this->uploadBaseUrl : $this->apiBaseUrl) . $path,
            CURLOPT_CUSTOMREQUEST => $method, CURLOPT_HTTPHEADER => $requestHeaders,
            CURLOPT_FOLLOWLOCATION => false, CURLOPT_MAXREDIRS => 0,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
            CURLOPT_HTTP_VERSION => CURL_HTTP_VERSION_1_1, CURLOPT_FRESH_CONNECT => true, CURLOPT_FORBID_REUSE => true,
            CURLOPT_NOSIGNAL => true, CURLOPT_TIMEOUT_MS => max(1, (int) ceil($deadline - self::now())),
            CURLOPT_HEADERFUNCTION => static function ($handle, #[\SensitiveParameter] string $line) use (&$headers, &$status, &$headerSize, &$tooLarge): int {
                $headerSize += strlen($line); if ($headerSize > 65536) { $tooLarge = true; return 0; }
                if (preg_match('~^HTTP/\S+\s+(\d{3})~', $line, $matches)) { $status = (int) $matches[1]; $headers = []; }
                elseif (str_contains($line, ':')) { [$name, $value] = explode(':', $line, 2); $headers[strtolower(trim($name))] = trim($value); }
                return strlen($line);
            },
            CURLOPT_WRITEFUNCTION => static function ($handle, #[\SensitiveParameter] string $chunk) use (&$raw, &$tooLarge): int {
                if (strlen($raw) + strlen($chunk) > 2097152) { $tooLarge = true; return 0; }
                $raw .= $chunk; return strlen($chunk);
            }];
        if ($body !== null) $settings[CURLOPT_POSTFIELDS] = $body;
        try {
            if (!curl_setopt_array($curl, $settings)) Validate::invalid('Unable to configure cURL.');
            if (self::cancelled($options)) return [$status, $headers, $raw, 'cancelled'];
            if (self::now() >= $deadline) return [$status, $headers, $raw, 'timeout'];
            curl_multi_add_handle($multi, $curl); $dispatched = true;
            do {
                if (self::cancelled($options)) return [$status, $headers, $raw, 'cancelled'];
                if (self::now() >= $deadline) return [$status, $headers, $raw, 'timeout'];
                $code = curl_multi_exec($multi, $running);
                if ($code !== CURLM_OK) return [$status, $headers, $raw, 'network'];
                if ($running) { $selected = curl_multi_select($multi, min(0.02, max(0.001, ($deadline - self::now()) / 1000))); if ($selected === -1) usleep(1000); }
            } while ($running);
            $info = curl_multi_info_read($multi); $errno = $info['result'] ?? CURLE_OK;
            $failure = $tooLarge ? 'large' : ($errno === CURLE_OPERATION_TIMEDOUT ? 'timeout' : ($errno !== CURLE_OK ? 'network' : null));
            return [$status ?? ((int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE) ?: null), $headers, $raw, $failure];
        } finally {
            curl_multi_remove_handle($multi, $curl);
            // Unsetting handles closes them on all supported PHP versions without deprecated curl_close().
            unset($curl); curl_multi_close($multi);
        }
    }
}
