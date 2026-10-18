# frozen_string_literal: true

require 'json'
require 'uri'
require 'time'

module Kompressr
  module Validation
    MAX_SAFE = 9_007_199_254_740_991
    MAX_TIMEOUT = 2_147_483.647
    DELETION = %w[active deleting deleted legacy_deleted].freeze
    PROCESSING = %w[pending processing processed failed unprocessable unknown].freeze
    SCOPES = %w[upload status list private_url delete].freeze
    module_function

    def invalid(message) = raise(Error.new(message, kind: 'validation', code: 'INVALID_ARGUMENT'), cause: nil)
    def bad(message = 'The API returned an invalid response.')
      raise Error.new(message, kind: 'invalid_response', code: 'INVALID_RESPONSE'), cause: nil
    end

    def positive(value, name, maximum = MAX_SAFE)
      invalid("#{name} must be an integer between 1 and #{maximum}.") unless value.instance_of?(Integer) && value.between?(1, maximum)
      value
    end

    def seconds(value, name = 'timeout')
      invalid("#{name} must be positive finite seconds, at most #{MAX_TIMEOUT}.") unless finite?(value) && value.positive? && value <= MAX_TIMEOUT
      value.to_f
    end

    def finite?(value) = (value.instance_of?(Integer) || value.instance_of?(Float)) && value.finite?

    def text(value, name, maximum, empty: false, trim: true)
      utf8 = value.instance_of?(String) ? value.b.force_encoding(Encoding::UTF_8) : nil
      valid = utf8 && value.encoding.ascii_compatible? && utf8.valid_encoding?
      normalized = valid ? (trim ? utf8.strip : utf8) : ''
      invalid("#{name} must contain #{empty ? '0' : '1'}–#{maximum} valid UTF-8 bytes.") unless valid && (empty || !normalized.empty?) && normalized.bytesize <= maximum
      utf8
    end

    def uuid(value, name = 'ID')
      invalid("#{name} must be a UUID.") unless value.instance_of?(String) && value.ascii_only? && /\A[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\z/.match?(value)
      value
    end

    def enum(value, allowed, name)
      invalid("Unsupported #{name}.") unless value.instance_of?(String) && allowed.include?(value)
      value
    end

    def customer_data(value, maximum = 4096)
      invalid('Customer data supports at most five scalar fields.') unless value.instance_of?(Hash) && value.size <= 5
      result = {}
      value.each do |raw_key, item|
        key = text(raw_key, 'Data key', 64).strip
        invalid('Data keys must be unique after trimming.') if result.key?(key)
        if item.instance_of?(String)
          item = text(item, 'Data value', 512, empty: true, trim: false)
        elsif !item.nil? && item != true && item != false
          invalid('Data values must be finite scalars.') unless finite?(item)
        end
        result[key] = item
      end
      invalid("Encoded customer data exceeds #{maximum} bytes.") if JSON.generate(result).bytesize > maximum
      result
    rescue JSON::GeneratorError, EncodingError
      invalid('Customer data must contain valid UTF-8.')
    end

    def origin(value)
      invalid('Base URL must be an HTTP(S) origin without credentials, path, query or fragment.') unless value.instance_of?(String) && !/[\x00-\x20\x7f]/.match?(value)
      uri = URI.parse(value)
      valid = %w[http https].include?(uri.scheme) && uri.host && !uri.userinfo && !uri.query && !uri.fragment && ['', '/'].include?(uri.path)
      valid &&= uri.port.between?(1, 65_535) && !uri.host.include?('%')
      invalid('Base URL must be an HTTP(S) origin without credentials, path, query or fragment.') unless valid
      suffix = uri.port == (uri.scheme == 'https' ? 443 : 80) ? '' : ":#{uri.port}"
      "#{uri.scheme}://#{uri.host.downcase}#{suffix}".freeze
    rescue URI::InvalidURIError, ArgumentError
      invalid('Base URL must be an HTTP(S) origin without credentials, path, query or fragment.')
    end

    def filename(value)
      value = text(value, 'Filename', 4096)
      invalid('Filename must not contain control characters.') if /[\x00-\x1f\x7f]/.match?(value)
      result = value.tr('\\', '/').split('/', -1).last
      invalid('Supply a nonempty filename.') if result.nil? || result.strip.empty?
      result
    end

    def record(value)
      bad unless value.instance_of?(Hash)
      value
    end
    def valid_json_strings?(value)
      case value
      when String then value.valid_encoding?
      when Array then value.all? { |item| valid_json_strings?(item) }
      when Hash then value.all? { |key, item| valid_json_strings?(key) && valid_json_strings?(item) }
      else true
      end
    end
    def string(value)
      bad unless value.instance_of?(String) && !value.strip.empty?
      value
    end
    def integer(value)
      bad unless finite?(value) && value == value.to_i && value.abs <= MAX_SAFE
      value.to_i
    end
    def nonnegative(value)
      n = integer(value)
      bad if n.negative?
      n
    end
    def id(value)
      n = integer(value)
      bad unless n.positive?
      n
    end
    def boolean(value)
      bad unless value == true || value == false
      value
    end
    def member(value, allowed)
      bad unless value.instance_of?(String) && allowed.include?(value)
      value
    end
    def optional_strings(value, names)
      names.each { |name| bad if value.key?(name) && !value[name].instance_of?(String) }
    end
    def select(value, names) = value.select { |name, _| names.include?(name) }
    def metadata_response(value, maximum = 8192)
      customer_data(value, maximum)
    rescue Error
      bad('Invalid customer metadata response.')
    end
    def urls(value)
      %w[cdn_url cdn_url_avif private_url].each do |name|
        next unless value.key?(name)
        url = string(value[name])
        uri = URI.parse(url)
        bad('Invalid delivery URL.') unless %w[http https].include?(uri.scheme) && uri.host && !uri.userinfo && !/[\x00-\x20\x7f]/.match?(url) && uri.port.between?(1, 65_535)
      end
    rescue URI::InvalidURIError, ArgumentError
      bad('Invalid delivery URL.')
    end

    def upload(value, accepted: false)
      v = record(value)
      result = select(v, %w[status visibility deletion_status original_name original_size asset_type deletion_requested_at external_id created_at input_format output_format private_url_expires_at cdn_url cdn_url_avif private_url data options quality warning])
      result['id'] = id(v[accepted ? 'asset_id' : 'id'])
      member(v['status'], PROCESSING)
      member(v['visibility'], %w[public private])
      member(v['deletion_status'], DELETION)
      result['original_size'] = nonnegative(v['original_size'])
      string(v['original_name']) if accepted
      string(v['asset_type'])
      optional_strings(v, %w[original_name deletion_requested_at external_id created_at input_format output_format private_url_expires_at warning])
      urls(v)
      bad('Private asset response contains a public URL.') if v['visibility'] == 'private' && %w[cdn_url cdn_url_avif].any? { |name| v.key?(name) }
      bad('Deleted asset response contains a delivery URL.') if v['deletion_status'] != 'active' && %w[cdn_url cdn_url_avif private_url].any? { |name| v.key?(name) }
      result['data'] = metadata_response(v['data']) if v.key?('data')
      bad if v.key?('options') && record(v['options']).values.any? { |item| !item.instance_of?(String) }
      member(v['quality'], %w[480p 720p 1080p 4k]) if v.key?('quality')
      unless accepted
        result['kompressd_size'] = nonnegative(v['kompressd_size'])
        result['can_generate_private_url'] = boolean(v['can_generate_private_url'])
        bad unless finite?(v['savings_percent'])
        result['savings_percent'] = v['savings_percent']
      end
      result
    end

    def private_url(value)
      v = record(value)
      id(v['asset_id'])
      member(v['variant'], %w[webp avif])
      urls(v)
      string(v['private_url'])
      string(v['expires_at'])
      bad unless integer(v['expires_in']).between?(60, 604_800)
      select(v, %w[asset_id variant private_url expires_at expires_in])
    end

    def asset_state(value)
      v = record(value)
      id(v['id']); id(v['kind']); nonnegative(v['storage_credited_mb'])
      string(v['project_id']); integer(v['processing_status'])
      member(v['deletion_status'], DELETION); member(v['source'], %w[upload origin])
      optional_strings(v, %w[deletion_requested_at])
      member(v['accounting_status'], %w[pending settled unavailable]) if v.key?('accounting_status')
      result = select(v, %w[id project_id kind source processing_status deletion_status storage_credited_mb deletion_requested_at accounting_status])
      if v.key?('last_failure')
        failure = record(v['last_failure'])
        %w[code message at].each { |key| string(failure[key]) }
        result['last_failure'] = select(failure, %w[code message at])
      end
      result
    end

    def page(value, key = 'data', &parse)
      v = record(value)
      bad unless v[key].instance_of?(Array)
      result = { 'data' => v[key].map(&parse), 'page' => id(v['page']), 'limit' => id(v['limit']), 'total' => nonnegative(v['total']) }
      bad if result['limit'] > 100 || result['data'].size > result['limit']
      result
    end

    def bulk(value, expected)
      v = record(value)
      counts = record(v['counts'])
      bad unless v['results'].instance_of?(Array) && v['results'].size == expected.size
      accepted = 0
      rows = v['results'].each_with_index.map do |item, index|
        row = record(item)
        bad unless id(row['id']) == expected[index]
        ok = boolean(row['accepted']); status = integer(row['status'])
        output = select(row, %w[id status accepted code error])
        optional_strings(row, %w[code error])
        if ok
          accepted += 1
          state = asset_state(row['state'])
          bad unless [200, 202].include?(status) && state['id'] == row['id'] && state['deletion_status'] != 'active'
          output['state'] = state
        else
          bad unless status >= 400
          string(row['error'])
        end
        output
      end
      expected_counts = { 'total' => expected.size, 'accepted' => accepted, 'failed' => expected.size - accepted }
      expected_counts.each { |key, n| bad unless integer(counts[key]) == n }
      { 'results' => rows, 'counts' => expected_counts }
    end

    def project_user(value)
      v = record(value)
      %w[id project_id customer_user_id].each { |name| string(v[name]) }
      member(v['status'], %w[active suspended])
      optional_strings(v, %w[display_name created_at last_seen_at last_upload_at last_key_used_at])
      numbers = %w[asset_count storage_bytes active_key_count bandwidth_bytes_current_period requests_current_period]
      numbers.each { |name| nonnegative(v[name]) if v.key?(name) }
      result = select(v, %w[id project_id customer_user_id status display_name created_at last_seen_at last_upload_at last_key_used_at] + numbers)
      result['metadata'] = metadata_response(v['metadata']) if v.key?('metadata')
      result
    end

    def upload_key(value)
      v = record(value)
      %w[id key_id project_id project_user_id name].each { |name| string(v[name]) }
      bad unless v['scopes'].instance_of?(Array) && v['scopes'].all? { |s| SCOPES.include?(s) }
      member(v['allowed_visibility'], %w[public private both])
      if v.key?('allowed_asset_types')
        bad unless v['allowed_asset_types'].instance_of?(Array)
        v['allowed_asset_types'].each { |type| id(type) }
      end
      %w[expires_at revoked_at last_used_at].each { |key| bad if v.key?(key) && !v[key].nil? && !v[key].instance_of?(String) }
      optional_strings(v, %w[created_at])
      select(v, %w[id key_id project_id project_user_id name scopes allowed_visibility allowed_asset_types expires_at revoked_at last_used_at created_at])
    end

    def success(value)
      v = record(value)
      bad unless v['success'] == true
      v
    end
    def data(value)
      v = success(value)
      bad unless v.key?('data')
      v['data']
    end
    def issued(value)
      v = success(value)
      IssuedKey.new(id: string(v['id']), key_id: string(v['key_id']), api_key: string(v['api_key']),
                    upload_key: v.key?('upload_key') ? upload_key(v['upload_key']) : nil)
    end
  end
end
