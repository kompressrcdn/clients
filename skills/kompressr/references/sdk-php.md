# PHP

64-bit PHP 8.1+, Composer 2 and `ext-curl` with asynchronous DNS. Synchronous calls work in Laravel, Symfony or plain PHP; they occupy the current request/worker until completion.

```sh
composer require kompressr/sdk:^0.1
```

Standalone scripts load Composer's autoloader; framework bootstrapping normally already does so. Integration helper with a persistence callback:

```php
<?php
declare(strict_types=1);
require __DIR__ . '/vendor/autoload.php';

use Kompressr\Client;

function uploadPublic(Client $files, string $path, callable $saveAssetId): string
{
    $accepted = $files->uploadFile($path, ['visibility' => 'public']);
    $saveAssetId($accepted['id']); // Commit before returning.
    $ready = $files->waitUntilReady($accepted['id']);
    return $ready['cdn_url'];
}
```

Create `new Client(['apiKey' => getenv('KOMPRESSR_API_KEY') ?: ''])` in trusted backend code. [Executable examples](https://github.com/kompressrcdn/clients/tree/main/sdk-php/examples) include public/private uploads, receipts and resume.

## Methods and shapes

Results generally use associative arrays: acceptance `['id']`, delivery `['cdn_url']`, signing `['private_url']`. Private flow: `['visibility' => 'private']`, persist ID, wait, authorize, `generatePrivateUrl($id, ['expiresIn' => 3600])`.

Methods: `uploadFile`, `uploadBytes`, `getUploadStatus`, `waitUntilReady`, `generatePrivateUrl`, `listUploads`, `iterateUploads`, `listAssets`, `getAsset`, `deleteAsset`, `bulkDeleteAssets`. Upload listing needs the project UUID. Platform administration is `$files->platform`.

Issued scoped-key objects hide their secret in ordinary formatting/serialization. Explicitly call `revealApiKey()` and store the value securely. Do not assume `api_key` is an array field for these objects.

## Application details

- Options use **milliseconds** (`timeoutMs`); signing `expiresIn` uses seconds. Origins are `apiBaseUrl` and `uploadBaseUrl`.
- Catch `KompressrException` and inspect `errorCode`, not inherited `getCode()`. Other fields include `status`, `assetId`, `retryAfterMs`, `mayHaveSucceeded`.
- `uploadFile` streams a regular file; arbitrary stream resources and wrappers are unsupported. `uploadBytes` accepts a binary string already in memory.
- A `cancel` callback can cooperate with cancellation; it does not make the client asynchronous. Use queues for work longer than your PHP request budget.
- Adapt validated Laravel/Symfony upload objects to a supported regular local path. A request's temporary path cannot be handed to a later job unless preserved durably.

[Full API](https://github.com/kompressrcdn/clients/blob/main/sdk-php/API.md) · [Guide](https://github.com/kompressrcdn/clients/blob/main/sdk-php/README.md)
