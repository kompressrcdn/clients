export type ErrorKind = 'validation' | 'api' | 'network' | 'timeout' | 'cancelled' | 'invalid_response' | 'processing';
export interface ErrorDetails {
  kind: ErrorKind; code: string; status?: number; retryAfterMs?: number;
  assetId?: number; mayHaveSucceeded?: boolean;
}
export class KompressrError extends Error {
  readonly kind: ErrorKind;
  readonly code: string;
  readonly status?: number;
  readonly retryAfterMs?: number;
  readonly assetId?: number;
  readonly mayHaveSucceeded: boolean;
  constructor(message: string, details: ErrorDetails) {
    super(message);
    this.name = 'KompressrError';
    this.kind = details.kind; this.code = details.code; this.status = details.status;
    this.retryAfterMs = details.retryAfterMs; this.assetId = details.assetId;
    this.mayHaveSucceeded = details.mayHaveSucceeded ?? false;
  }
  toJSON() {
    return { name: this.name, message: this.message, kind: this.kind, code: this.code,
      status: this.status, retryAfterMs: this.retryAfterMs, assetId: this.assetId,
      mayHaveSucceeded: this.mayHaveSucceeded };
  }
}
export function invalid(message: string): never {
  throw new KompressrError(message, { kind: 'validation', code: 'INVALID_ARGUMENT' });
}
export function invalidResponse(message = 'The API returned an invalid response.'): never {
  throw new KompressrError(message, { kind: 'invalid_response', code: 'INVALID_RESPONSE' });
}
export function safeMessage(message: unknown, secret = ''): string {
  if (typeof message !== 'string') return 'Kompressr request failed.';
  let value = secret ? message.split(secret).join('[redacted]') : message;
  value = value.replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
    .replace(/https?:\/\/[^\s<>"']+/g, '[URL redacted]')
    .replace(/\b(?:api_key|password|token|secret|signature)\s*[=:]\s*\S+/gi, '[credential redacted]');
  return value.slice(0, 500);
}
