<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';
if ($argc !== 2) throw new InvalidArgumentException('Usage: php scoped-key.php CUSTOMER_USER_ID');
// Load a project credential into KOMPRESSR_API_KEY on your trusted backend.
$project = exampleClient();
$user = $project->platform->createUser(['customerUserId' => $argv[1]]);
$issued = $project->platform->createUploadKey($user['project_user']['id'], [
    'name' => 'application', 'allowedVisibility' => 'private',
    // Omitted scopes use the service default, which excludes deletion.
]);
$scopedSecret = $issued->revealApiKey();
// Persist $scopedSecret in your application's secret store for this tenant.
// This standalone example keeps it only in memory and never prints it.
$tenant = new Kompressr\Client(['apiKey' => $scopedSecret]);
echo 'Scoped key created for the selected project user.', "\n";
