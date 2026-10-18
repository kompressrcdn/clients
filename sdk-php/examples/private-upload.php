<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';
if ($argc !== 3) throw new InvalidArgumentException('Usage: php private-upload.php FILE NEW_PRIVATE_RECEIPT');
$client = exampleClient();
$accepted = $client->uploadFile($argv[1], ['visibility' => 'private']);
saveReceipt($argv[2], $accepted['id']);
$client->waitUntilReady($accepted['id']);
$link = $client->generatePrivateUrl($accepted['id'], ['expiresIn' => 300]);
// Return $link['private_url'] only to an authorized viewer; never log it.
echo 'Private asset is ready; an expiring link has been generated.', "\n";
