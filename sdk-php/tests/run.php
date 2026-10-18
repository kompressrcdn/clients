<?php
declare(strict_types=1);
require getenv('KOMPRESSR_TEST_AUTOLOAD') ?: dirname(__DIR__) . '/vendor/autoload.php';
use Kompressr\Client;
use Kompressr\IssuedKey;
use Kompressr\KompressrException;

$fixture = json_decode(file_get_contents(__DIR__ . '/fixtures/file-lifecycle.json'), true, flags: JSON_THROW_ON_ERROR);
$tests = 0;
function check(bool $ok, string $message = 'Assertion failed'): void { if (!$ok) throw new RuntimeException($message); }
function test(string $name, callable $work): void { global $tests; $work(); $tests++; echo "PASS $name\n"; }
function failure(callable $work, string $kind, ?bool $ambiguous = null, ?int $id = null): KompressrException
{
    try { $work(); } catch (KompressrException $e) {
        check($e->kind === $kind, "Expected $kind, got {$e->kind}: {$e->getMessage()}");
        if ($ambiguous !== null) check($e->mayHaveSucceeded === $ambiguous, 'Ambiguity differs');
        check($e->assetId === $id, 'Recovery asset ID differs'); return $e;
    }
    throw new RuntimeException("Expected $kind failure");
}
final class FixtureServer
{
    private $process;
    private array $pipes = [];
    private string $config;
    private string $log;
    public readonly string $url;
    public function __construct(array $replies)
    {
        $this->config = tempnam(sys_get_temp_dir(), 'kompressr-fixture-');
        $this->log = tempnam(sys_get_temp_dir(), 'kompressr-requests-');
        file_put_contents($this->config, json_encode($replies, JSON_THROW_ON_ERROR));
        $this->process = proc_open([PHP_BINARY, __DIR__ . '/server.php', $this->config, $this->log], [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $this->pipes);
        stream_set_timeout($this->pipes[1], 5); $port = trim((string) fgets($this->pipes[1]));
        if (!ctype_digit($port)) throw new RuntimeException('HTTP fixture failed to start.');
        $this->url = 'http://127.0.0.1:' . $port;
    }
    public function client(array $options = []): Client { return new Client(array_replace(['apiKey' => 'fixture-credential', 'apiBaseUrl' => $this->url, 'projectId' => '660e8400-e29b-41d4-a716-446655440001', 'maxReadRetries' => 0], $options)); }
    public function requests(): array
    {
        $rows = file($this->log, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        return array_map(static function ($row) { $v = json_decode($row, true, flags: JSON_THROW_ON_ERROR); $v['body'] = base64_decode($v['body']); return $v; }, $rows);
    }
    public function __destruct()
    {
        if (is_resource($this->process)) { proc_terminate($this->process); foreach ($this->pipes as $pipe) fclose($pipe); proc_close($this->process); }
        @unlink($this->config); @unlink($this->log);
    }
}
function fixtureServer(array $json, int $status = 200): FixtureServer { return new FixtureServer([['json' => $json, 'status' => $status]]); }

try {
    test('file upload streams 32 MiB under bounded PHP allocation', function () use ($fixture): void {
        // Run first in this fresh process: PHP 8.1 cannot reset peak usage.
        $path = tempnam(sys_get_temp_dir(), 'kompressr-stream-'); $f = fopen($path, 'wb'); ftruncate($f, 32 * 1024 * 1024); fclose($f);
        try {
            $s = fixtureServer(['success' => true, 'data' => $fixture['accepted']]);
            $before = memory_get_peak_usage(true);
            check($before < 8 * 1024 * 1024, 'Memory regression needs a fresh process with a low baseline');
            check($s->client()->uploadFile($path)['id'] === 42); $growth = memory_get_peak_usage(true) - $before;
            check($growth < 8 * 1024 * 1024, 'File upload buffered the file in PHP memory'); check($s->requests()[0]['size'] > 32 * 1024 * 1024);
        } finally { unlink($path); }
    });
    test('SDK exception traces omit credentials and payloads with argument capture enabled', function (): void {
        $original = ini_set('zend.exception_ignore_args', '0');
        try {
            check(ini_get('zend.exception_ignore_args') === '0');
            $errors = [];
            $errors[] = failure(fn() => new Client(['apiKey' => 'fixture-trace-secret', 'requestTimeoutMs' => 0]), 'validation');
            $s = fixtureServer(['success' => false, 'error' => 'Permission denied.'], 403);
            $errors[] = failure(fn() => $s->client(['apiKey' => 'fixture-trace-secret'])->uploadBytes('fixture-private-payload', 'secret.txt', ['data' => ['tenant' => 'fixture-private-metadata']]), 'api', false);
            foreach ($errors as $error) {
                check(count($error->getTrace()) > 0, 'Keep useful call sites');
                foreach ($error->getTrace() as $frame) check(!isset($frame['args']) && !isset($frame['object']), 'Trace must not retain arguments or objects');
                $rendered = (string) $error . $error->getTraceAsString() . json_encode($error->getTrace(), JSON_THROW_ON_ERROR) . json_encode($error, JSON_THROW_ON_ERROR);
                foreach (['fixture-trace-secret', 'fixture-private-payload', 'fixture-private-metadata'] as $secret) check(!str_contains($rendered, $secret), 'SDK exception leaked sensitive input');
            }
            check(ini_get('zend.exception_ignore_args') === '0', 'SDK must not change process-wide settings');
        } finally { if ($original !== false) ini_set('zend.exception_ignore_args', $original); }
    });
    test('shared fixture matches repository snapshot', function (): void {
        $root = dirname(__DIR__, 2) . '/contracts/fixtures/file-lifecycle.json';
        if (is_file($root)) check(hash_file('sha256', $root) === hash_file('sha256', __DIR__ . '/fixtures/file-lifecycle.json'));
    });
    test('separate upload origin, multipart order and accepted ID', function () use ($fixture): void {
        $upload = fixtureServer(['success' => true, 'data' => $fixture['accepted']]);
        $api = fixtureServer(['success' => true, 'data' => $fixture['processed']]);
        $client = $api->client(['uploadBaseUrl' => $upload->url]);
        $out = $client->uploadBytes('hello file', 'folder/output.png', ['visibility' => 'public', 'quality' => '720p', 'privateUrlExpiresIn' => 90, 'data' => ['tenant' => 'example']]);
        check($out['id'] === 42 && $out['status'] === 'processing'); check($client->getUploadStatus(42)['status'] === 'processed');
        $r = $upload->requests()[0]; check($r['line'] === 'POST /api/upload HTTP/1.1'); check($r['headers']['authorization'] === 'Bearer fixture-credential');
        foreach (['visibility', 'kmp-quality', 'private_url_expires_in', 'data'] as $name) check(strpos($r['body'], 'name="' . $name . '"') < strpos($r['body'], 'name="file"'));
        check(str_contains($r['body'], 'filename="output.png"')); check(str_contains($r['body'], 'hello file'));
        check(!isset($r['headers']['transfer-encoding'])); check(count($api->requests()) === 1);
    });
    test('custom endpoint defaults both origins and production uses upload origin', function (): void {
        $c = new Client(['apiKey' => 'fixture-credential']); check($c->apiBaseUrl === 'https://kompressr.com'); check($c->uploadBaseUrl === 'https://uploads.kompressr.com');
        $c = new Client(['apiKey' => 'fixture-credential', 'apiBaseUrl' => 'https://example.test:443/']); check($c->uploadBaseUrl === 'https://example.test');
    });
    test('ready public and private signing', function () use ($fixture): void {
        $server = fixtureServer(['success' => true, 'data' => $fixture['processed']]); check($server->client()->waitUntilReady(42)['cdn_url'] === $fixture['processed']['cdn_url']);
        $private = $fixture['processed']; unset($private['cdn_url']); $private['visibility'] = 'private'; $private['can_generate_private_url'] = true;
        $link = ['asset_id' => 42, 'variant' => 'webp', 'private_url' => 'https://cdn.example/private?signature=fixture', 'expires_at' => '2030-01-01T00:00:00Z', 'expires_in' => 60];
        $server = new FixtureServer([['json' => ['success' => true, 'data' => $private]], ['json' => ['success' => true, 'data' => $link]]]);
        $c = $server->client(); check($c->waitUntilReady(42)['visibility'] === 'private'); check($c->generatePrivateUrl(42, ['expiresIn' => 60]) === $link);
        check(json_decode($server->requests()[1]['body'], true) === ['expires_in' => 60, 'variant' => 'webp']);
    });
    test('list filters and lazy page iteration', function () use ($fixture): void {
        $second = $fixture['processed']; $second['id'] = 43;
        $server = new FixtureServer([['json' => ['success' => true, 'data' => [$fixture['processed']], 'page' => 1, 'limit' => 1, 'total' => 2]], ['json' => ['success' => true, 'data' => [$second], 'page' => 2, 'limit' => 1, 'total' => 2]]]);
        $iterator = $server->client()->iterateUploads(['limit' => 1, 'visibility' => 'public', 'status' => 'processed', 'externalId' => 'conversation 1', 'data' => ['tenant' => 'example'], 'deletionStatus' => 'active']);
        check(count($server->requests()) === 0); $rows = iterator_to_array($iterator, false); check(array_column($rows, 'id') === [42, 43]);
        $first = $server->requests()[0]['line']; check(str_contains($first, 'status=3') && str_contains($first, 'data.tenant=example') && str_contains($first, 'external_id=conversation%201')); check(str_contains($server->requests()[1]['line'], 'page=2'));
    });
    test('pagination cannot repeat a page', function () use ($fixture): void {
        $s = fixtureServer(['success' => true, 'data' => [$fixture['processed']], 'page' => 1, 'limit' => 1, 'total' => 3]);
        failure(fn() => iterator_to_array($s->client()->iterateUploads(['limit' => 1]), false), 'invalid_response'); check(count($s->requests()) === 2);
    });
    test('asset list/detail/deletion and bulk partial outcomes', function () use ($fixture): void {
        $state = $fixture['deletionAccepted']; $active = $state; $active['deletion_status'] = 'active';
        $s = new FixtureServer([['json' => ['data' => [$active], 'page' => 1, 'limit' => 20, 'total' => 1]], ['json' => $active], ['json' => $state, 'status' => 202], ['json' => $fixture['bulkDeletion']]]);
        $c = $s->client(); check($c->listAssets()['data'][0]['id'] === 42); check($c->getAsset(42)['deletion_status'] === 'active'); check($c->deleteAsset(42)['deletion_status'] === 'deleting');
        $bulk = $c->bulkDeleteAssets([42, 42, 43]); check($bulk['counts'] === ['total' => 2, 'accepted' => 1, 'failed' => 1]); check($bulk['results'][1]['status'] === 404);
        check($s->requests()[2]['line'] === 'DELETE /api/assets/42 HTTP/1.1'); check(json_decode($s->requests()[3]['body'], true)['asset_ids'] === [42, 42, 43]);
    });
    test('oversized Retry-After never retries before the request deadline', function () use ($fixture): void {
        $s = new FixtureServer([
            ['status' => 429, 'headers' => ['Retry-After' => '9223372036854776'], 'json' => ['success' => false]],
            ['json' => $fixture['deletionAccepted']],
        ]);
        $start = hrtime(true);
        $e = failure(fn() => $s->client(['maxReadRetries' => 2])->getAsset(42, ['timeoutMs' => 800]), 'timeout');
        $elapsed = (hrtime(true) - $start) / 1000000;
        check($e->status === 429 && $e->retryAfterMs === PHP_INT_MAX, 'Retry-After must saturate before integer conversion');
        check($elapsed >= 750 && $elapsed < 1600, 'The request deadline must bound the delay');
        check(count($s->requests()) === 1, 'A large Retry-After must not cause an early retry');
    });
    test('Retry-After preserves finite values, dates and body fallback while saturating overflow', function (): void {
        $cases = [
            [['Retry-After' => '9223372036854776'], ['retry_after' => 1], PHP_INT_MAX],
            [['Retry-After' => '1e308'], [], PHP_INT_MAX],
            [[], ['retry_after' => 9223372036854776], PHP_INT_MAX],
            [[], ['retry_after' => 1e308], PHP_INT_MAX],
            [['Retry-After' => '0'], ['retry_after' => 10], 0],
            [['Retry-After' => '0.0001'], [], 1],
            [['Retry-After' => '1.25'], ['retry_after' => 9], 1250],
            [['Retry-After' => 'not-a-date'], ['retry_after' => 2.5], 2500],
            [['Retry-After' => '1e309'], ['retry_after' => 2.5], 2500],
            [[], ['retry_after' => '2'], null],
            [[], ['retry_after' => -1], null],
            [['Retry-After' => 'Thu, 01 Jan 1970 00:00:00 GMT'], [], 0],
        ];
        foreach ($cases as [$headers, $body, $expected]) {
            $s = new FixtureServer([['status' => 429, 'headers' => $headers, 'json' => ['success' => false] + $body]]);
            $e = failure(fn() => $s->client()->getAsset(42), 'api');
            check($e->retryAfterMs === $expected, 'Retry-After value or saturation differs');
            check(count($s->requests()) === 1);
        }
        $s = new FixtureServer([['status' => 429, 'raw' => '{"success":false,"retry_after":1e309}']]);
        check(failure(fn() => $s->client()->getAsset(42), 'api')->retryAfterMs === null, 'Nonfinite body delays must be ignored');
        $date = gmdate('D, d M Y H:i:s \G\M\T', time() + 20);
        $s = new FixtureServer([['status' => 429, 'headers' => ['Retry-After' => $date], 'json' => ['success' => false, 'retry_after' => 1]]]);
        $delay = failure(fn() => $s->client()->getAsset(42), 'api')->retryAfterMs;
        check($delay >= 18000 && $delay <= 20000, 'HTTP-date must take priority over a body retry hint');
    });
    test('empty key scopes fail before HTTP while omission keeps defaults', function (): void {
        $uid = '660e8400-e29b-41d4-a716-446655440002'; $kid = '660e8400-e29b-41d4-a716-446655440003';
        $s = fixtureServer(['success' => true, 'id' => $kid, 'key_id' => $kid, 'api_key' => 'fixture-one-time']);
        $p = $s->client()->platform;
        $e = failure(fn() => $p->createUploadKey($uid, ['name' => 'empty', 'scopes' => []]), 'validation', false);
        check($e->errorCode === 'INVALID_ARGUMENT' && count($s->requests()) === 0);
        failure(fn() => $p->createUploadKey($uid, ['name' => 'null', 'scopes' => null]), 'validation', false);
        check(count($s->requests()) === 0, 'Explicit null remains an invalid PHP scopes value');
        $p->createUploadKey($uid, ['name' => 'defaults']);
        $p->createUploadKey($uid, ['name' => 'status only', 'scopes' => ['status']]);
        $requests = $s->requests(); check(count($requests) === 2);
        check(!array_key_exists('scopes', json_decode($requests[0]['body'], true)));
        check(json_decode($requests[1]['body'], true)['scopes'] === ['status']);
    });
    test('all platform operations, omitted defaults and secret redaction', function () use ($fixture): void {
        $uid = '660e8400-e29b-41d4-a716-446655440002'; $kid = '660e8400-e29b-41d4-a716-446655440003';
        $user = ['id' => $uid, 'project_id' => $fixture['projectId'], 'customer_user_id' => 'customer-1', 'status' => 'active'];
        $key = ['id' => $kid, 'key_id' => $kid, 'project_id' => $fixture['projectId'], 'project_user_id' => $uid, 'name' => 'example', 'scopes' => ['upload', 'status', 'list', 'private_url'], 'allowed_visibility' => 'private'];
        $issued = ['success' => true, 'id' => $kid, 'key_id' => $kid, 'api_key' => 'one-time-fixture-credential', 'upload_key' => $key + ['api_key' => 'unexpected-nested-fixture-secret']];
        $s = new FixtureServer([
            ['json' => ['success' => true, 'project_users' => [$user], 'page' => 1, 'limit' => 20, 'total' => 1, 'project_active_count' => 1, 'org_active_count' => 1, 'usage_period' => ['start' => '2030-01-01', 'end' => '2030-02-01']]],
            ['json' => ['success' => true, 'created' => true, 'project_user' => $user]], ['json' => ['success' => true, 'project_user' => $user]],
            ['json' => ['success' => true, 'project_user' => array_replace($user, ['status' => 'suspended'])]], ['json' => ['success' => true, 'project_user' => $user]],
            ['json' => ['success' => true, 'upload_keys' => [$key], 'page' => 1, 'limit' => 20, 'total' => 1]], ['json' => $issued], ['json' => $issued], ['json' => ['success' => true]],
        ]);
        $p = $s->client()->platform;
        check($p->listUsers()['org_active_count'] === 1); check($p->createUser(['customerUserId' => 'customer-1', 'metadata' => ['tier' => 'example']])['created']);
        check($p->updateUser($uid, ['displayName' => 'Example'])['id'] === $uid); check($p->suspendUser($uid)['status'] === 'suspended'); check($p->reactivateUser($uid)['status'] === 'active');
        check($p->listUploadKeys($uid)['data'][0]['name'] === 'example'); $created = $p->createUploadKey($uid, ['name' => 'example']);
        check($created instanceof IssuedKey && $created->revealApiKey() === $issued['api_key']); check(!str_contains(json_encode($created), $issued['api_key']));
        ob_start(); var_dump($created, $s->client(), $p); $debug = ob_get_clean(); check(!str_contains($debug, $issued['api_key']) && !str_contains($debug, 'fixture-credential') && !str_contains($debug, 'unexpected-nested-fixture-secret'));
        check($p->rotateUploadKey($uid, $kid)->keyId === $kid); $p->revokeUploadKey($uid, $kid);
        $requests = $s->requests(); check(count($requests) === 9); check(!array_key_exists('scopes', json_decode($requests[6]['body'], true))); check(str_starts_with($requests[2]['line'], 'PATCH '));
    });
    test('permission and plan denials preserve supplied credential', function (): void {
        $s = fixtureServer(['success' => false, 'code' => 'SCOPE_FORBIDDEN', 'error' => 'Permission denied'], 403);
        $e = failure(fn() => $s->client(['maxReadRetries' => 5])->deleteAsset(42), 'api', false, 42); check($e->status === 403 && $e->errorCode === 'SCOPE_FORBIDDEN'); check(count($s->requests()) === 1);
        failure(fn() => $s->client()->platform->listUsers(), 'api', false); check($s->requests()[1]['headers']['authorization'] === 'Bearer fixture-credential');
    });
    test('safe errors remove credentials, URLs and unsafe gateway text', function (): void {
        $s = fixtureServer(['success' => false, 'error' => 'fixture-credential Bearer sample https://cdn.example/private?signature=secret token=sample', 'code' => 'fixture-credential'], 401);
        $e = failure(fn() => $s->client()->getAsset(42), 'api'); $json = json_encode($e); check(!str_contains($json, 'fixture-credential') && !str_contains($json, 'cdn.example') && !str_contains($json, 'token=sample'));
        $unicode = fixtureServer(['success' => false, 'error' => str_repeat('€', 200)], 400);
        $unicodeError = failure(fn() => $unicode->client()->getAsset(42), 'api'); check(is_string(json_encode($unicodeError, JSON_THROW_ON_ERROR)));
        $s = new FixtureServer([['status' => 502, 'raw' => '<html>raw private gateway details</html>']]);
        $e = failure(fn() => $s->client()->getAsset(42), 'api'); check(!str_contains($e->getMessage(), 'gateway details'));
    });
    foreach ([429, 502, 503, 504] as $status) test("eligible read retry $status", function () use ($fixture, $status): void {
        $s = new FixtureServer([['status' => $status, 'json' => ['success' => false]], ['json' => $fixture['deletionAccepted']]]);
        check($s->client(['maxReadRetries' => 1])->getAsset(42)['id'] === 42); check(count($s->requests()) === 2);
    });
    test('GET disconnected response retries, write disconnect never replays', function () use ($fixture): void {
        $s = new FixtureServer([['close' => true], ['json' => $fixture['deletionAccepted']]]);
        check($s->client(['maxReadRetries' => 2])->getAsset(42)['id'] === 42); check(count($s->requests()) === 2);
        $s = new FixtureServer([['close' => true]]); failure(fn() => $s->client(['maxReadRetries' => 5])->deleteAsset(42), 'network', true, 42); check(count($s->requests()) === 1);
    });
    test('write HTTP failures never retry and retain uncertainty', function (): void {
        foreach ([200, 503] as $status) {
            $s = fixtureServer(['success' => false, 'code' => 'FIXTURE_FAILURE', 'error' => 'Operation outcome unavailable'], $status);
            $e = failure(fn() => $s->client(['maxReadRetries' => 5])->deleteAsset(42), 'api', true, 42);
            check($e->status === $status && count($s->requests()) === 1);
        }
    });
    test('Retry-After cannot be shortened by backoff', function (): void {
        $s = new FixtureServer([['status' => 429, 'headers' => ['Retry-After' => '2'], 'json' => ['success' => false]]]);
        $start = hrtime(true); $e = failure(fn() => $s->client(['maxReadRetries' => 2])->getAsset(42, ['timeoutMs' => 120]), 'timeout');
        check($e->status === 429 && $e->retryAfterMs === 2000); check((hrtime(true) - $start) / 1000000 < 500); check(count($s->requests()) === 1);
    });
    test('deadline includes delayed response bodies and preserves mutation context', function () use ($fixture): void {
        $s = new FixtureServer([['json' => $fixture['deletionAccepted'], 'bodyDelayMs' => 400]]);
        $start = hrtime(true); $e = failure(fn() => $s->client()->deleteAsset(42, ['timeoutMs' => 60]), 'timeout', true, 42); check($e->status === 200); check((hrtime(true) - $start) / 1000000 < 250);
    });
    test('cancellation before dispatch sends nothing', function (): void {
        $s = fixtureServer([]); failure(fn() => $s->client()->uploadBytes('x', 'x.txt', ['cancel' => fn() => true]), 'cancelled', false); check(count($s->requests()) === 0);
    });
    test('cancellation interrupts delayed bodies with ambiguity', function () use ($fixture): void {
        $s = new FixtureServer([['json' => $fixture['deletionAccepted'], 'bodyDelayMs' => 500]]); $stop = hrtime(true) + 60000000;
        failure(fn() => $s->client()->deleteAsset(42, ['cancel' => fn() => hrtime(true) >= $stop]), 'cancelled', true, 42); check(count($s->requests()) === 1);
    });
    test('one-shot cancellation remains cancelled before and after dispatch', function () use ($fixture): void {
        foreach ([1, 2] as $at) {
            $s = fixtureServer([]); $calls = 0;
            failure(fn() => $s->client()->deleteAsset(42, ['cancel' => function () use (&$calls, $at): bool { return ++$calls === $at; }]), 'cancelled', false, 42);
            check(count($s->requests()) === 0);
        }
        $s = new FixtureServer([['json' => $fixture['deletionAccepted'], 'bodyDelayMs' => 500]]); $stop = hrtime(true) + 60000000; $fired = false;
        failure(fn() => $s->client()->deleteAsset(42, ['cancel' => function () use (&$fired, $stop): bool { if (!$fired && hrtime(true) >= $stop) { $fired = true; return true; } return false; }]), 'cancelled', true, 42);
    });
    test('callback failure after dispatch preserves mutation uncertainty', function () use ($fixture): void {
        foreach (['throw', 'type'] as $mode) {
            $s = new FixtureServer([['json' => $fixture['deletionAccepted'], 'bodyDelayMs' => 500]]); $stop = hrtime(true) + 60000000;
            $e = failure(fn() => $s->client()->deleteAsset(42, ['cancel' => function () use ($stop, $mode) { if (hrtime(true) >= $stop) { if ($mode === 'throw') throw new RuntimeException('private callback details'); return null; } return false; }]), 'validation', true, 42);
            check(!str_contains($e->getMessage(), 'private callback details')); check($e->status === 200);
        }
    });
    test('wait preserves a shorter configured request deadline', function () use ($fixture): void {
        $s = new FixtureServer([['json' => ['success' => true, 'data' => $fixture['processed']], 'bodyDelayMs' => 500]]);
        $start = hrtime(true); $e = failure(fn() => $s->client(['requestTimeoutMs' => 40])->waitUntilReady(42, ['timeoutMs' => 1000]), 'timeout', false, 42);
        check($e->errorCode === 'REQUEST_TIMEOUT'); check((hrtime(true) - $start) / 1000000 < 250);
    });
    test('redirects never forward credentials or replay writes', function (): void {
        $target = fixtureServer([]); $s = new FixtureServer([['status' => 307, 'headers' => ['Location' => $target->url . '/capture'], 'json' => []]]);
        $e = failure(fn() => $s->client()->deleteAsset(42), 'api', true, 42); check($e->status === 307); check(count($target->requests()) === 0 && count($s->requests()) === 1);
    });
    test('read malformed response is not retried', function (): void {
        $s = new FixtureServer([['raw' => '{']]); failure(fn() => $s->client(['maxReadRetries' => 5])->getAsset(42), 'invalid_response'); check(count($s->requests()) === 1);
    });
    test('response size is bounded', function (): void {
        $s = new FixtureServer([['large' => 2097153]]); failure(fn() => $s->client()->deleteAsset(42), 'invalid_response', true, 42); check(count($s->requests()) === 1);
    });
    $malformed = [
        ['success' => true, 'data' => ['asset_id' => 42]],
        ['success' => true, 'data' => array_replace($fixture['accepted'], ['asset_id' => '42'])],
        ['success' => true, 'data' => array_replace($fixture['accepted'], ['asset_id' => true])],
        ['success' => true, 'data' => array_replace($fixture['accepted'], ['asset_id' => 9007199254740992])],
        ['success' => true, 'data' => array_replace($fixture['accepted'], ['visibility' => 'private'])],
        ['success' => true, 'data' => array_replace($fixture['accepted'], ['deletion_status' => 'deleted'])],
        ['success' => true, 'data' => array_replace($fixture['accepted'], ['original_size' => '1024'])],
        ['success' => true, 'data' => array_replace($fixture['accepted'], ['status' => 'future'])],
        ['success' => true, 'data' => array_replace($fixture['accepted'], ['cdn_url' => 'javascript:alert(1)'])],
        ['success' => true, 'data' => array_replace($fixture['accepted'], ['data' => ['nested' => ['value' => 1]]])],
    ];
    foreach ($malformed as $i => $value) test("malformed accepted upload $i retains safe recovery context", function () use ($value): void {
        $s = fixtureServer($value); $wireId = $value['data']['asset_id']; $id = is_int($wireId) && $wireId > 0 && $wireId <= 9007199254740991 ? $wireId : null;
        failure(fn() => $s->client()->uploadBytes('x', 'x.txt'), 'invalid_response', true, $id); check(count($s->requests()) === 1);
    });
    test('truncated JSON never guesses an upload ID', function (): void {
        $s = new FixtureServer([['raw' => '{"success":true,"data":{"asset_id":42,']]); failure(fn() => $s->client()->uploadBytes('x', 'x.txt'), 'invalid_response', true);
    });
    test('malformed signing/deletion/bulk/platform mutations retain uncertainty', function () use ($fixture): void {
        $s = fixtureServer(['success' => true, 'data' => []]); failure(fn() => $s->client()->generatePrivateUrl(42), 'invalid_response', true, 42);
        $active = $fixture['deletionAccepted']; $active['deletion_status'] = 'active'; $s = fixtureServer($active); failure(fn() => $s->client()->deleteAsset(42), 'invalid_response', true, 42);
        $bulk = $fixture['bulkDeletion']; $bulk['counts']['accepted'] = 2; $s = fixtureServer($bulk); failure(fn() => $s->client()->bulkDeleteAssets([42, 43]), 'invalid_response', true);
        $s = fixtureServer(['success' => true, 'created' => 'yes']); failure(fn() => $s->client()->platform->createUser(['customerUserId' => 'example']), 'invalid_response', true);
        $s = fixtureServer(['success' => true, 'api_key' => 'one-time-fixture-credential']); $e = failure(fn() => $s->client()->platform->createUploadKey('660e8400-e29b-41d4-a716-446655440002', ['name' => 'example']), 'invalid_response', true); check(!str_contains((string) $e, 'one-time-fixture-credential'));
    });
    test('wait processing/deletion failures retain asset ID', function () use ($fixture): void {
        foreach (['failed', 'unprocessable', 'unknown'] as $status) {
            $row = array_replace($fixture['processed'], ['status' => $status]); $s = fixtureServer(['success' => true, 'data' => $row]);
            $e = failure(fn() => $s->client()->waitUntilReady(42), 'processing', false, 42); check($e->errorCode === 'PROCESSING_FAILED');
        }
        $row = $fixture['processed']; unset($row['cdn_url']); $row['deletion_status'] = 'deleting'; $s = fixtureServer(['success' => true, 'data' => $row]);
        check(failure(fn() => $s->client()->waitUntilReady(42), 'processing', false, 42)->errorCode === 'ASSET_DELETED');
    });
    test('wait timeout and cancellation are resumable', function () use ($fixture): void {
        $row = array_replace($fixture['processed'], ['status' => 'processing']); $s = fixtureServer(['success' => true, 'data' => $row]);
        check(failure(fn() => $s->client()->waitUntilReady(42, ['timeoutMs' => 80, 'pollIntervalMs' => 10]), 'timeout', false, 42)->errorCode === 'WAIT_TIMEOUT');
        check(failure(fn() => $s->client()->waitUntilReady(42, ['cancel' => fn() => true]), 'cancelled', false, 42)->errorCode === 'WAIT_CANCELLED');
        $s = fixtureServer(['success' => true, 'data' => $fixture['processed']]); check($s->client()->waitUntilReady(42)['id'] === 42); check(str_starts_with($s->requests()[0]['line'], 'GET '));
    });
    test('wait cannot return an unusable public or private asset', function () use ($fixture): void {
        $row = $fixture['processed']; unset($row['cdn_url']); $s = fixtureServer(['success' => true, 'data' => $row]); failure(fn() => $s->client()->waitUntilReady(42), 'invalid_response', false, 42);
        $row['visibility'] = 'private'; $s = fixtureServer(['success' => true, 'data' => $row]); failure(fn() => $s->client()->waitUntilReady(42), 'invalid_response', false, 42);
    });
    test('strict IDs, options, metadata and origins fail before dispatch', function (): void {
        $s = fixtureServer([]); $c = $s->client();
        foreach ([0, -1, 42.0, '42', true, 9007199254740992] as $id) failure(fn() => $c->getAsset($id), 'validation');
        foreach ([['visibility' => 'other'], ['quality' => 'auto'], ['privateUrlExpiresIn' => 59], ['timeoutMs' => 0], ['data' => ['one' => []]], ['data' => ['x' => str_repeat('é', 257)]], ['data' => [' x' => 1, 'x' => 2]], ['data' => ['x' => "\xff"]]] as $options) failure(fn() => $c->uploadBytes('x', 'x.txt', $options), 'validation');
        failure(fn() => $c->uploadBytes('x', "a\r\nb.txt"), 'validation'); failure(fn() => $c->uploadFile('php://memory'), 'validation');
        failure(fn() => $c->bulkDeleteAssets([]), 'validation'); failure(fn() => $c->listAssets(['limit' => 101]), 'validation');
        failure(fn() => $c->platform->createUser(['customerUserId' => str_repeat('é', 129)]), 'validation');
        failure(fn() => $c->platform->createUploadKey('660e8400-e29b-41d4-a716-446655440002', ['name' => 'x', 'scopes' => ['admin']]), 'validation');
        foreach (['https://user:pass@example.test', 'https://example.test/path', 'https://example.test?key=sample', 'file:///example', "https://example.test\n"] as $origin) failure(fn() => new Client(['apiKey' => 'fixture', 'apiBaseUrl' => $origin]), 'validation');
        check(count($s->requests()) === 0);
    });
    echo "$tests tests passed on PHP ", PHP_VERSION, "\n";
} catch (Throwable $e) { fwrite(STDERR, "FAIL: " . $e->getMessage() . "\n" . $e->getTraceAsString() . "\n"); exit(1); }
