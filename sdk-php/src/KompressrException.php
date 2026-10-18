<?php
declare(strict_types=1);
namespace Kompressr;

/** A safe, structured failure. errorCode is separate from Exception's numeric code. */
final class KompressrException extends \RuntimeException implements \JsonSerializable
{
    public function __construct(
        string $message,
        public readonly string $kind,
        public readonly string $errorCode,
        public readonly ?int $status = null,
        public readonly ?int $retryAfterMs = null,
        public readonly ?int $assetId = null,
        public readonly bool $mayHaveSucceeded = false,
    ) {
        parent::__construct($message);
        // PHP 8.1 does not implement SensitiveParameter. Remove trace arguments
        // on every runtime so SDK errors stay safe when argument capture is enabled.
        // Keep call sites, without changing the application's PHP configuration.
        $trace = [];
        foreach ($this->getTrace() as $frame) {
            unset($frame['args'], $frame['object']);
            $trace[] = $frame;
        }
        (new \ReflectionProperty(\Exception::class, 'trace'))->setValue($this, $trace);
    }

    public function jsonSerialize(): array
    {
        return ['message' => $this->getMessage(), 'kind' => $this->kind, 'code' => $this->errorCode,
            'status' => $this->status, 'retryAfterMs' => $this->retryAfterMs,
            'assetId' => $this->assetId, 'mayHaveSucceeded' => $this->mayHaveSucceeded];
    }
    public function __debugInfo(): array { return $this->jsonSerialize(); }
}
