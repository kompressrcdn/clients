<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';
if ($argc !== 2) throw new InvalidArgumentException('Usage: php resume.php PRIVATE_RECEIPT');
$receipt = json_decode(file_get_contents($argv[1]), true, flags: JSON_THROW_ON_ERROR);
$client = exampleClient();
$ready = $client->waitUntilReady($receipt['asset_id'] ?? null);
if ($ready['visibility'] === 'public') echo $ready['cdn_url'], "\n";
else {
    $link = $client->generatePrivateUrl($ready['id'], ['expiresIn' => 300]);
    // Authorize the viewer before returning $link['private_url'].
    echo 'Private asset is ready; an expiring link has been generated.', "\n";
}
