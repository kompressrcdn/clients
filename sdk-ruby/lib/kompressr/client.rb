# frozen_string_literal: true

module Kompressr
  # A synchronous, framework-independent client. Results use string-keyed hashes.
  class Client
    attr_reader :api_base_url, :upload_base_url, :platform

    def initialize(project_id: nil, **configuration)
      @project_id = project_id.nil? ? nil : Validation.uuid(project_id, 'project_id').dup.freeze
      @transport = Internal::Transport.new(**configuration)
      @api_base_url, @upload_base_url = @transport.api_base_url, @transport.upload_base_url
      @platform = PlatformClient.new(**configuration)
    end
    def inspect = '#<Kompressr::Client credentials redacted>'
    alias to_s inspect

    def upload_file(path, **options)
      Validation.invalid('Supply a local file path.') unless (path.instance_of?(String) || path.respond_to?(:to_path)) && !path.to_s.empty?
      path = path.to_path if path.respond_to?(:to_path)
      Validation.invalid('Supply a local file path without null bytes.') unless path.instance_of?(String) && !path.b.include?("\0")
      filename = Validation.filename(File.basename(path))
      Validation.invalid('Upload path must name a regular local file.') unless File.stat(path).file?
      # NONBLOCK avoids a raced replacement with a FIFO blocking open. fstat then
      # rejects anything other than the regular file the SDK owns and closes.
      flags = File::RDONLY | File::NONBLOCK
      File.open(path, flags) do |file|
        file.binmode
        Validation.invalid('Upload path must name a regular local file.') unless file.stat.file?
        upload_source(file, file.stat.size, filename, **options)
      end
    end

    def upload_bytes(content, filename, **options)
      Validation.invalid('content must be a Ruby String containing the file bytes.') unless content.instance_of?(String)
      snapshot = content.b.dup.freeze
      upload_source(snapshot, snapshot.bytesize, Validation.filename(filename), **options)
    end

    def get_upload_status(asset_id, timeout: nil, cancel: nil)
      Validation.positive(asset_id, 'asset_id')
      @transport.request("/api/upload/#{asset_id}/status", timeout: timeout, cancel: cancel, asset_id: asset_id) do |value|
        result = Validation.upload(Validation.data(value))
        Validation.bad('API returned a different asset ID.') unless result['id'] == asset_id
        result
      end
    end

    def wait_until_ready(asset_id, timeout: 120, poll_interval: 2, cancel: nil)
      Validation.positive(asset_id, 'asset_id')
      duration = Validation.seconds(timeout)
      interval = Validation.seconds(poll_interval, 'poll_interval')
      Validation.invalid('poll_interval must not exceed 30 seconds.') if interval > 30
      Validation.invalid('cancel must be a CancellationToken.') unless cancel.nil? || cancel.instance_of?(CancellationToken)
      context = Internal::Context.new(duration, cancel, false, asset_id)
      loop do
        context.check!
        request_budget = [context.remaining, @transport.request_timeout].min
        begin
          result = get_upload_status(asset_id, timeout: request_budget, cancel: cancel)
        rescue Error => error
          context.status, context.retry_after_ms = error.status, error.retry_after_ms
          raise
        end
        context.check!
        if result['deletion_status'] != 'active'
          raise Error.new('Asset deletion has been requested.', kind: 'processing', code: 'ASSET_DELETED', asset_id: asset_id), cause: nil
        end
        if %w[failed unprocessable unknown].include?(result['status'])
          raise Error.new('Asset processing did not succeed.', kind: 'processing', code: 'PROCESSING_FAILED', asset_id: asset_id), cause: nil
        end
        if result['status'] == 'processed'
          return result if result['visibility'] == 'private' ? result['can_generate_private_url'] : result.key?('cdn_url')
          raise Error.new('Processed asset is not deliverable; verify server compatibility.', kind: 'invalid_response',
                          code: 'INVALID_RESPONSE', asset_id: asset_id), cause: nil
        end
        context.pause(interval)
      end
    rescue Error => error
      if error.kind == 'cancelled' || (error.kind == 'timeout' && context && context.remaining <= 0.001)
        code = error.kind == 'cancelled' ? 'WAIT_CANCELLED' : 'WAIT_TIMEOUT'
        raise Error.new('Readiness wait stopped; keep the asset ID and check again later.', kind: error.kind, code: code,
                        status: error.status, retry_after_ms: error.retry_after_ms, asset_id: asset_id), cause: nil
      end
      raise
    end

    def generate_private_url(asset_id, expires_in: 3600, variant: 'webp', timeout: nil, cancel: nil)
      Validation.positive(asset_id, 'asset_id')
      ttl(expires_in)
      Validation.enum(variant, %w[webp avif], 'variant')
      @transport.request("/api/upload/#{asset_id}/private-url", method: 'POST', body: { 'expires_in' => expires_in, 'variant' => variant }, timeout: timeout, cancel: cancel, asset_id: asset_id) do |value|
        result = Validation.private_url(Validation.data(value))
        Validation.bad('API returned a different asset ID.') unless result['asset_id'] == asset_id
        result
      end
    end

    def list_uploads(project_id: nil, page: 1, limit: 20, visibility: nil, external_id: nil, data: nil,
                     status: nil, deletion_status: nil, timeout: nil, cancel: nil)
      query = pagination(page, limit)
      project = project_id.nil? ? @project_id : project_id
      Validation.invalid('Upload listing requires project_id from the client or this call.') if project.nil?
      query['project_id'] = Validation.uuid(project, 'project_id')
      query['visibility'] = Validation.enum(visibility, %w[public private], 'visibility') unless visibility.nil?
      query['deletion_status'] = Validation.enum(deletion_status, Validation::DELETION, 'deletion_status') unless deletion_status.nil?
      unless status.nil?
        selected = status.instance_of?(String) ? { 'pending' => 1, 'processing' => 2, 'processed' => 3, 'failed' => 4, 'unprocessable' => 5 }[status] : status
        query['status'] = Validation.positive(selected, 'status', 6)
      end
      query['external_id'] = Validation.text(external_id, 'external_id', 512, empty: true, trim: false) unless external_id.nil?
      unless data.nil?
        Validation.customer_data(data).each do |key, value|
          Validation.invalid('Data filter values must be strings.') unless value.instance_of?(String)
          query["data.#{key}"] = value
        end
      end
      @transport.request("/api/uploads?#{URI.encode_www_form(query)}", timeout: timeout, cancel: cancel) do |value|
        Validation.page(Validation.success(value)) { |row| Validation.upload(row) }
      end
    end

    def iterate_uploads(**options)
      Enumerator.new do |output|
        current = options.fetch(:page, 1)
        loop do
          result = list_uploads(**options.merge(page: current))
          Validation.bad('Invalid pagination response.') unless result['page'] == current
          result['data'].each { |row| output << row }
          break if result['data'].empty? || result['page'] * result['limit'] >= result['total']
          current += 1
        end
      end
    end

    def list_assets(page: 1, limit: 20, deletion_status: nil, timeout: nil, cancel: nil)
      query = pagination(page, limit)
      query['deletion_status'] = Validation.enum(deletion_status, Validation::DELETION, 'deletion_status') unless deletion_status.nil?
      @transport.request("/api/assets?#{URI.encode_www_form(query)}", timeout: timeout, cancel: cancel) do |value|
        Validation.page(value) { |row| Validation.asset_state(row) }
      end
    end

    def get_asset(asset_id, timeout: nil, cancel: nil)
      Validation.positive(asset_id, 'asset_id')
      @transport.request("/api/assets/#{asset_id}", timeout: timeout, cancel: cancel, asset_id: asset_id) do |value|
        result = Validation.asset_state(value)
        Validation.bad('API returned a different asset ID.') unless result['id'] == asset_id
        result
      end
    end

    def delete_asset(asset_id, timeout: nil, cancel: nil)
      Validation.positive(asset_id, 'asset_id')
      @transport.request("/api/assets/#{asset_id}", method: 'DELETE', timeout: timeout, cancel: cancel, asset_id: asset_id) do |value|
        result = Validation.asset_state(value)
        Validation.bad('Deletion was not accepted for the requested asset.') unless result['id'] == asset_id && result['deletion_status'] != 'active'
        result
      end
    end

    def bulk_delete_assets(asset_ids, timeout: nil, cancel: nil)
      Validation.invalid('Select 1 to 100 explicit asset IDs.') unless asset_ids.instance_of?(Array) && asset_ids.size.between?(1, 100)
      asset_ids.each { |id| Validation.positive(id, 'asset_id') }
      expected = asset_ids.uniq
      @transport.request('/api/assets/bulk-delete', method: 'POST', body: { 'asset_ids' => asset_ids }, timeout: timeout, cancel: cancel) do |value|
        Validation.bulk(value, expected)
      end
    end

    private

    def pagination(page, limit)
      { 'page' => Validation.positive(page, 'page', 2_147_483_647), 'limit' => Validation.positive(limit, 'limit', 100) }
    end
    def ttl(value)
      Validation.positive(value, 'expires_in', 604_800)
      Validation.invalid('Private URL lifetime must be at least 60 seconds.') if value < 60
    end
    def upload_source(source, size, name, visibility: nil, quality: nil, data: nil, private_url_expires_in: nil, timeout: nil, cancel: nil)
      fields = {}
      fields['visibility'] = Validation.enum(visibility, %w[public private], 'visibility') unless visibility.nil?
      fields['kmp-quality'] = Validation.enum(quality, %w[480p 720p 1080p 4k], 'quality') unless quality.nil?
      fields['data'] = JSON.generate(Validation.customer_data(data)) unless data.nil?
      unless private_url_expires_in.nil?
        ttl(private_url_expires_in)
        fields['private_url_expires_in'] = private_url_expires_in.to_s
      end
      body = Internal::Multipart.new(source, size, name, fields)
      @transport.request('/api/upload', method: 'POST', multipart: body, upload: true, timeout: timeout, cancel: cancel, recover_upload_id: true) do |value|
        response = Validation.success(value)
        result = Validation.upload(response['data'], accepted: true)
        result['warning'] = response['warning'] if response['warning'].instance_of?(String)
        result
      end
    end
  end
end
