# frozen_string_literal: true

module Kompressr
  # Project authority is checked by the service, never inferred by this client.
  class PlatformClient
    def initialize(**configuration)
      @transport = Internal::Transport.new(**configuration)
    end
    def inspect = '#<Kompressr::PlatformClient credentials redacted>'
    alias to_s inspect

    def list_users(page: 1, limit: 20, timeout: nil, cancel: nil)
      query = pagination(page, limit)
      @transport.request("/api/platform/project-users?#{URI.encode_www_form(query)}", timeout: timeout, cancel: cancel) do |value|
        response = Validation.success(value)
        result = Validation.page(response, 'project_users') { |row| Validation.project_user(row) }
        %w[project_active_count org_active_count].each { |key| result[key] = Validation.nonnegative(response[key]) }
        if response.key?('usage_period')
          period = Validation.record(response['usage_period'])
          %w[start end].each { |key| Validation.bad unless /\A\d{4}-\d{2}-\d{2}\z/.match?(Validation.string(period[key])) }
          result['usage_period'] = Validation.select(period, %w[start end])
        end
        result
      end
    end

    def create_user(customer_user_id, display_name: nil, metadata: nil, timeout: nil, cancel: nil)
      customer_user_id = Validation.text(customer_user_id, 'customer_user_id', 256)
      body = user_fields(display_name, metadata).merge('customer_user_id' => customer_user_id)
      @transport.request('/api/platform/project-users', method: 'POST', body: body, timeout: timeout, cancel: cancel) do |value|
        response = Validation.success(value)
        { 'created' => Validation.boolean(response['created']), 'project_user' => Validation.project_user(response['project_user']) }
      end
    end

    def update_user(project_user_id, display_name: nil, metadata: nil, timeout: nil, cancel: nil)
      body = user_fields(display_name, metadata)
      @transport.request(user_path(project_user_id), method: 'PATCH', body: body, timeout: timeout, cancel: cancel) do |value|
        Validation.project_user(Validation.success(value)['project_user'])
      end
    end

    def suspend_user(project_user_id, timeout: nil, cancel: nil)
      mutate_user(project_user_id, 'suspend', timeout, cancel)
    end
    def reactivate_user(project_user_id, timeout: nil, cancel: nil)
      mutate_user(project_user_id, 'reactivate', timeout, cancel)
    end

    def list_upload_keys(project_user_id, page: 1, limit: 20, timeout: nil, cancel: nil)
      query = URI.encode_www_form(pagination(page, limit))
      @transport.request("#{user_path(project_user_id)}/upload-keys?#{query}", timeout: timeout, cancel: cancel) do |value|
        Validation.page(Validation.success(value), 'upload_keys') { |row| Validation.upload_key(row) }
      end
    end

    def create_upload_key(project_user_id, name, scopes: nil, allowed_visibility: nil, allowed_asset_types: nil,
                          expires_at: nil, timeout: nil, cancel: nil)
      path = user_path(project_user_id)
      name = Validation.text(name, 'name', 120)
      body = { 'name' => name }
      unless scopes.nil?
        Validation.invalid('Supply at least one scope, or omit scopes to use server defaults.') unless scopes.instance_of?(Array) && !scopes.empty?
        scopes.each { |scope| Validation.enum(scope, Validation::SCOPES, 'upload scope') }
        body['scopes'] = scopes
      end
      body['allowed_visibility'] = Validation.enum(allowed_visibility, %w[public private both], 'allowed_visibility') unless allowed_visibility.nil?
      unless allowed_asset_types.nil?
        Validation.invalid('allowed_asset_types must be an array of positive integer IDs.') unless allowed_asset_types.instance_of?(Array)
        allowed_asset_types.each { |type| Validation.positive(type, 'asset type') }
        body['allowed_asset_types'] = allowed_asset_types
      end
      unless expires_at.nil?
        begin
          Validation.invalid('expires_at must be a future ISO timestamp with a timezone.') unless expires_at.instance_of?(String) && expires_at.ascii_only? && /(?:Z|[+-]\d{2}:\d{2})\z/.match?(expires_at) && Time.iso8601(expires_at) > Time.now
        rescue ArgumentError
          Validation.invalid('expires_at must be a future ISO timestamp with a timezone.')
        end
        body['expires_at'] = expires_at
      end
      @transport.request("#{path}/upload-keys", method: 'POST', body: body, timeout: timeout, cancel: cancel) { |v| Validation.issued(v) }
    end

    def rotate_upload_key(project_user_id, key_id, timeout: nil, cancel: nil)
      path = "#{user_path(project_user_id)}/upload-keys/#{Validation.uuid(key_id, 'key_id')}/rotate"
      @transport.request(path, method: 'POST', timeout: timeout, cancel: cancel) { |v| Validation.issued(v) }
    end

    def revoke_upload_key(project_user_id, key_id, timeout: nil, cancel: nil)
      path = "#{user_path(project_user_id)}/upload-keys/#{Validation.uuid(key_id, 'key_id')}/revoke"
      @transport.request(path, method: 'POST', timeout: timeout, cancel: cancel) { |v| Validation.success(v); nil }
    end

    private

    def pagination(page, limit)
      { 'page' => Validation.positive(page, 'page', 2_147_483_647), 'limit' => Validation.positive(limit, 'limit', 100) }
    end
    def user_path(id) = "/api/platform/project-users/#{Validation.uuid(id, 'project_user_id')}"
    def user_fields(display_name, metadata)
      body = {}
      body['display_name'] = Validation.text(display_name, 'display_name', 120, empty: true) unless display_name.nil?
      body['metadata'] = Validation.customer_data(metadata, 8192) unless metadata.nil?
      body
    end
    def mutate_user(id, action, timeout, cancel)
      @transport.request("#{user_path(id)}/#{action}", method: 'POST', timeout: timeout, cancel: cancel) do |value|
        Validation.project_user(Validation.success(value)['project_user'])
      end
    end
  end
end
