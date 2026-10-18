<?php
declare(strict_types=1);
require getenv('KOMPRESSR_AUTOLOAD') ?: dirname(__DIR__) . '/vendor/autoload.php';
use Kompressr\Client;

function exampleClient(): Client
{
    return new Client(['apiKey' => getenv('KOMPRESSR_API_KEY') ?: '', ...((getenv('KOMPRESSR_PROJECT_ID') ?: '') !== '' ? ['projectId' => getenv('KOMPRESSR_PROJECT_ID')] : [])]);
}
function saveReceipt(string $path, int $id): void
{
    // Use a private directory outside the checkout. Existing receipts are never overwritten.
    $old = umask(0077);
    try { $file = @fopen($path, 'x'); } finally { umask($old); }
    if ($file === false) throw new RuntimeException("Upload accepted as asset $id; receipt creation failed. Save this ID before retrying anything.");
    try {
        $json = json_encode(['asset_id' => $id], JSON_THROW_ON_ERROR) . "\n";
        if (fwrite($file, $json) !== strlen($json) || !fflush($file) || !fsync($file)) throw new RuntimeException("Upload accepted as asset $id; receipt write failed. Save this ID before retrying anything.");
    } finally { fclose($file); }
}
