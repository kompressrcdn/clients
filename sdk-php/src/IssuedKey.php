<?php
declare(strict_types=1);
namespace Kompressr;

/** A one-time provisioning secret. Store revealApiKey() securely; do not log it. */
final class IssuedKey implements \JsonSerializable
{
    public function __construct(
        public readonly string $id,
        public readonly string $keyId,
        #[\SensitiveParameter] private readonly string $apiKey,
        public readonly ?array $uploadKey = null,
    ) {}
    public function revealApiKey(): string { return $this->apiKey; }
    public function jsonSerialize(): array
    {
        return ['id' => $this->id, 'key_id' => $this->keyId, 'api_key' => '[redacted]', 'upload_key' => $this->uploadKey];
    }
    public function __debugInfo(): array { return $this->jsonSerialize(); }
    public function __serialize(): array { throw new \LogicException('Issued keys cannot be serialized; store the secret explicitly.'); }
}
