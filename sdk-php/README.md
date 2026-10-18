# Kompressr PHP SDK

Upload files, wait for optimization, deliver public or private URLs, manage deletion, and provision scoped credentials from your PHP backend. Use it in Laravel, Symfony or plain PHP applications without a framework adapter.

Requires 64-bit PHP 8.1 or later, Composer 2, and `ext-curl` with asynchronous DNS support. Standard PHP packages generally include this cURL capability; the constructor checks it. The client is synchronous: each call blocks its PHP request or worker until it completes, fails or is cancelled.

## Install

```sh
composer require kompressr/sdk:^0.1
```

Load Composer's `vendor/autoload.php` in a standalone script. Laravel and Symfony applications already load it.

## Upload and deliver a file

Create a Kompressr project and obtain its API key in the dashboard. Your subscription must include API uploads; see [current pricing](https://kompressr.com/pricing). Keep this key on your backend and load it from your application's secret store or environment.

```php
<?php
declare(strict_types=1);
require __DIR__ . '/vendor/autoload.php';

use Kompressr\Client;
use Kompressr\KompressrException;

$client = new Client(['apiKey' => getenv('KOMPRESSR_API_KEY') ?: '']);
$accepted = $client->uploadFile(__DIR__ . '/output.png', ['visibility' => 'public']);
$assetId = $accepted['id'];
// Save this ID in your application's durable job record before waiting.
try {
    $ready = $client->waitUntilReady($assetId);
    $publicUrl = $ready['cdn_url'];
} catch (KompressrException $e) {
    // On timeout/cancellation, retain the ID and resume status checks later.
    // Do not upload the same job again just because waiting stopped.
    throw $e;
}
```

An accepted upload may still be processing. Wait before sharing its URL. `uploadFile()` streams a readable regular file using bounded memory; keep that file unchanged during the call. `uploadBytes($bytes, $filename)` accepts a PHP binary string already held in memory. Network filesystems can block file reads outside the network deadline, so use local files. Arbitrary PHP stream resources and stream wrappers are not accepted.

## Private files

```php
$accepted = $client->uploadFile(__DIR__ . '/report.pdf', ['visibility' => 'private']);
$assetId = $accepted['id']; // Persist this before waiting.
$client->waitUntilReady($assetId);
$link = $client->generatePrivateUrl($assetId, ['expiresIn' => 300]);
$privateUrl = $link['private_url'];
```

Private URLs are temporary bearer links. Return one only after your application authorizes the viewer; keep private URLs and complete result arrays out of logs. Signing is explicit, even when an upload response includes a temporary link.

## Errors and recovery

Catch `KompressrException`. Its public fields are `kind`, `errorCode`, `status`, `retryAfterMs`, `assetId` and `mayHaveSucceeded`; `json_encode($error)` gives a redacted summary. `errorCode` holds the API/string code; PHP's inherited `getCode()` is not that field.

- A read may retry network failures or HTTP 429/502/503/504, at most twice by default.
- Writes never retry automatically. If `mayHaveSucceeded` is true, check the operation's outcome before trying again. A malformed upload response may still provide a safely recovered `assetId`.
- `WAIT_TIMEOUT` and `WAIT_CANCELLED` retain the asset ID. Resume with `getUploadStatus()` or `waitUntilReady()`.
- HTTP 401/403 or plan denials preserve the service response. The SDK never switches credentials.

Network deadlines include response bodies and retry delays. Management requests default to 30 seconds, uploads to 10 minutes, and waiting to 2 minutes. Options use **milliseconds**. Configure finite `timeoutMs` values appropriate for your worker's overall lifetime.

For cancellation, pass `['cancel' => function () use (&$applicationShouldStop): bool { return $applicationShouldStop; }]` with a boolean flag owned by your application. Capturing by reference lets a signal handler update the flag. The callback is polled during network activity and delays, approximately every 20 ms. It must be fast, nonblocking, and return a boolean. A cancellation does not undo server work. In ordinary single-threaded PHP, a callback can inspect a clock, signal-updated flag, or another application cancellation source; it does not make the client asynchronous.

## Regular and scoped keys

A project API key administers project users and their scoped upload keys. A scoped key identifies one project user and carries only its configured permissions. Use a stable application tenant/user ID when provisioning a project user. Authenticate your application users and decide which tenant they belong to before selecting credentials.

```php
$created = $client->platform->createUser(['customerUserId' => 'customer-123']);
$issued = $client->platform->createUploadKey($created['project_user']['id'], [
    'name' => 'chat-production',
    'allowedVisibility' => 'private',
]);
$scopedSecret = $issued->revealApiKey(); // Store encrypted; never log or send a master key.
$tenantClient = new Client(['apiKey' => $scopedSecret]);
```

`IssuedKey` hides the one-time secret from JSON, debug output and serialization; retrieve it explicitly with `revealApiKey()`. Scope defaults exclude deletion. Supplying `scopes` replaces the default set. Platform administration requires a project credential and a plan supporting scoped keys; see [pricing](https://kompressr.com/pricing). A scoped client cannot gain more access by calling an administration method.

[API reference](https://github.com/kompressrcdn/clients/blob/main/sdk-php/API.md) covers all methods and result shapes. [Examples](https://github.com/kompressrcdn/clients/blob/main/sdk-php/examples) include durable recovery receipts, private delivery and scoped provisioning. [Parity](https://github.com/kompressrcdn/clients/blob/main/sdk-php/PARITY.md) explains behavior and test coverage. [Contributing](https://github.com/kompressrcdn/clients/blob/main/sdk-php/CONTRIBUTING.md) describes verification.
