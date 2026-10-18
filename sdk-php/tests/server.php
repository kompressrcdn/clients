<?php
declare(strict_types=1);
// Local HTTP boundary fixture. Bodies are drained with bounded memory.
$config = json_decode(file_get_contents($argv[1]), true, flags: JSON_THROW_ON_ERROR);
$server = stream_socket_server('tcp://127.0.0.1:0', $errno, $error);
if (!$server) exit(2);
echo substr(strrchr(stream_socket_get_name($server, false), ':'), 1), "\n"; flush();
$index = 0;
while ($socket = @stream_socket_accept($server, 10)) {
    stream_set_timeout($socket, 5);
    $first = fgets($socket); if ($first === false) { fclose($socket); continue; }
    $headers = [];
    while (($line = fgets($socket)) !== false && trim($line) !== '') {
        if (str_contains($line, ':')) { [$name, $value] = explode(':', $line, 2); $headers[strtolower($name)] = trim($value); }
    }
    $remaining = (int) ($headers['content-length'] ?? 0); $size = 0; $prefix = '';
    while ($remaining > 0 && !feof($socket)) {
        $chunk = fread($socket, min(65536, $remaining)); if ($chunk === false || $chunk === '') break;
        $size += strlen($chunk); $remaining -= strlen($chunk);
        if (strlen($prefix) < 65536) $prefix .= substr($chunk, 0, 65536 - strlen($prefix));
    }
    file_put_contents($argv[2], json_encode(['line' => trim($first), 'headers' => $headers, 'body' => base64_encode($prefix), 'size' => $size]) . "\n", FILE_APPEND);
    $reply = $config[min($index++, count($config) - 1)];
    if (!empty($reply['close'])) { fclose($socket); continue; }
    if (!empty($reply['headerDelayMs'])) usleep($reply['headerDelayMs'] * 1000);
    $status = $reply['status'] ?? 200;
    $body = isset($reply['large']) ? str_repeat('x', $reply['large']) : ($reply['raw'] ?? json_encode($reply['json'] ?? new stdClass(), JSON_THROW_ON_ERROR));
    $wire = "HTTP/1.1 $status Fixture\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " . strlen($body) . "\r\n";
    foreach ($reply['headers'] ?? [] as $name => $value) $wire .= "$name: $value\r\n";
    @fwrite($socket, $wire . "\r\n"); fflush($socket);
    if (!empty($reply['bodyDelayMs'])) usleep($reply['bodyDelayMs'] * 1000);
    @fwrite($socket, $body); fclose($socket);
}
fclose($server);
