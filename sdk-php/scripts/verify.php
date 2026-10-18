<?php
declare(strict_types=1);
// Native verification: real HTTP tests, Composer archive, installed consumer tests.
$root = dirname(__DIR__);
chdir($root);
$composer = getenv('KOMPRESSR_COMPOSER') ?: 'composer';
$version = trim(file_get_contents($root . '/VERSION'));
if (!preg_match('/^\d+\.\d+\.\d+$/D', $version)) throw new RuntimeException('Invalid VERSION.');
putenv('COMPOSER_ROOT_VERSION=' . $version);
$composerCommand = str_ends_with($composer, '.phar') ? [PHP_BINARY, $composer] : [$composer];
function run(array $command, string $directory, ?array $env = null): void
{
    $process = proc_open($command, [0 => STDIN, 1 => STDOUT, 2 => STDERR], $pipes, $directory, $env);
    if (!is_resource($process) || proc_close($process) !== 0) throw new RuntimeException('Verification command failed: ' . basename($command[0]));
}
function removeTree(string $path): void
{
    if (is_dir($path) && !is_link($path)) { foreach (new FilesystemIterator($path) as $item) removeTree($item->getPathname()); rmdir($path); }
    else unlink($path);
}
$consumer = null;
$exitCode = 0;
try {
    run([...$composerCommand, 'validate', '--strict'], $root);
    run([...$composerCommand, 'install', '--no-interaction', '--no-scripts', '--no-plugins'], $root);
    foreach (['src', 'tests', 'scripts', 'examples'] as $directory) {
        foreach (new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root . '/' . $directory, FilesystemIterator::SKIP_DOTS)) as $file) {
            if ($file->getExtension() === 'php') run([PHP_BINARY, '-l', $file->getPathname()], $root);
        }
    }
    run([PHP_BINARY, '-d', 'error_reporting=E_ALL', 'tests/run.php'], $root);
    if (!is_dir($root . '/dist')) mkdir($root . '/dist');
    $name = 'kompressr-sdk-' . $version;
    $archive = $root . '/dist/' . $name . '.tar';
    if (is_file($archive)) unlink($archive);
    run([...$composerCommand, 'archive', '--format=tar', '--file=' . $name, '--dir=dist'], $root);
    $distribution = new PharData($archive);
    foreach (new RecursiveIteratorIterator($distribution) as $file) {
        $relative = str_replace('phar://' . $archive . '/', '', $file->getPathname());
        if (preg_match('~(^|/)(vendor|dist|\.git|\.env)(/|$)~', $relative) || $file->isLink()) throw new RuntimeException('Unexpected distribution member.');
    }
    $consumer = sys_get_temp_dir() . '/kompressr-php-consumer-' . bin2hex(random_bytes(8));
    mkdir($consumer, 0700);
    $manifest = json_decode(file_get_contents($root . '/composer.json'), true, flags: JSON_THROW_ON_ERROR);
    $package = $manifest; $package['version'] = $version;
    $package['dist'] = ['type' => 'tar', 'url' => $archive, 'shasum' => sha1_file($archive)];
    unset($package['scripts'], $package['archive']);
    file_put_contents($consumer . '/composer.json', json_encode(['name' => 'example/kompressr-consumer', 'require' => ['kompressr/sdk' => $version], 'repositories' => [['type' => 'package', 'package' => $package], ['packagist.org' => false]]], JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR));
    run([...$composerCommand, 'install', '--no-interaction', '--no-scripts', '--no-plugins', '--no-cache'], $consumer);
    $installed = $consumer . '/vendor/kompressr/sdk';
    if (is_link($installed)) throw new RuntimeException('Consumer must install the distribution, not a source link.');
    $env = getenv(); $env['KOMPRESSR_TEST_AUTOLOAD'] = $consumer . '/vendor/autoload.php';
    run([PHP_BINARY, '-d', 'error_reporting=E_ALL', $installed . '/tests/run.php'], $consumer, $env);
    foreach (glob($installed . '/examples/*.php') as $example) run([PHP_BINARY, '-l', $example], $consumer);
    echo "Verified installed Composer archive: ", basename($archive), "\nSHA-256: ", hash_file('sha256', $archive), "\n";
} catch (Throwable $e) { fwrite(STDERR, $e->getMessage() . "\n"); $exitCode = 1; }
finally { if ($consumer !== null && is_dir($consumer)) removeTree($consumer); }

exit($exitCode);
