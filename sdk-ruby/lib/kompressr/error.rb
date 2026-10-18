# frozen_string_literal: true

module Kompressr
  # Safe recovery metadata. Raw response bodies and request credentials are absent.
  class Error < StandardError
    attr_reader :kind, :code, :status, :retry_after_ms, :asset_id, :may_have_succeeded

    def initialize(message, kind:, code:, status: nil, retry_after_ms: nil, asset_id: nil, may_have_succeeded: false)
      super(message)
      @kind, @code, @status = kind, code, status
      @retry_after_ms, @asset_id, @may_have_succeeded = retry_after_ms, asset_id, may_have_succeeded
    end

    def to_h
      { 'message' => message, 'kind' => kind, 'code' => code, 'status' => status,
        'retry_after_ms' => retry_after_ms, 'asset_id' => asset_id, 'may_have_succeeded' => may_have_succeeded }
    end

    def to_json(*args) = to_h.to_json(*args)
    def inspect = "#<Kompressr::Error #{to_h.inspect}>"
  end

  # Thread-safe cooperative cancellation. Cancellation never rolls back server work.
  class CancellationToken
    def initialize
      @mutex = Mutex.new
      @cancelled = false
    end

    def cancel = @mutex.synchronize { @cancelled = true }
    def cancelled? = @mutex.synchronize { @cancelled }
    def inspect = "#<Kompressr::CancellationToken cancelled=#{cancelled?}>"
  end

  # Provisioning secrets require explicit access and are excluded from normal logs.
  class IssuedKey
    attr_reader :id, :key_id, :upload_key

    def initialize(id:, key_id:, api_key:, upload_key: nil)
      @id, @key_id, @api_key, @upload_key = id, key_id, api_key, upload_key
    end

    def reveal_api_key = @api_key.dup
    def to_h = { 'id' => id, 'key_id' => key_id, 'upload_key' => upload_key, 'api_key' => '[redacted]' }
    def to_json(*args) = to_h.to_json(*args)
    def inspect = "#<Kompressr::IssuedKey #{to_h.inspect}>"
    alias to_s inspect
  end
end
