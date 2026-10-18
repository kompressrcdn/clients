<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';
if ($argc !== 3) throw new InvalidArgumentException('Usage: php public-upload.php FILE NEW_PRIVATE_RECEIPT');
$client = exampleClient();
$accepted = $client->uploadFile($argv[1], ['visibility' => 'public']);
saveReceipt($argv[2], $accepted['id']);
$ready = $client->waitUntilReady($accepted['id']);
echo $ready['cdn_url'], "\n";
