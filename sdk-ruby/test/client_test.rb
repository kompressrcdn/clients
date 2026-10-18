# frozen_string_literal: true

require_relative 'support'

class ClientTest < Minitest::Test
  include Fixtures

  def test_endpoint_defaults_and_validation
    c = Kompressr::Client.new(api_key: 'example-key')
    assert_equal 'https://kompressr.com', c.api_base_url
    assert_equal 'https://uploads.kompressr.com', c.upload_base_url
    c = Kompressr::Client.new(api_key: 'example-key', api_base_url: 'https://example.com:443/')
    assert_equal 'https://example.com', c.upload_base_url
    %w[ftp://example.com https://user:password@example.com https://example.com/path https://example.com?q=x https://example.com#x].each do |url|
      failure('validation') { Kompressr::Client.new(api_key: 'example-key', api_base_url: url) }
    end
    failure('validation') { Kompressr::Client.new(api_key: "bad\r\nvalue") }
    failure('validation') { Kompressr::Client.new(api_key: 'example-key', request_timeout: Float::INFINITY) }
    failure('validation') { Kompressr::Client.new(api_key: 'example-key', max_read_retries: 6) }
    refute_includes c.inspect, 'example-key'
  end

  def test_upload_fields_precede_file_and_use_separate_origin
    management = server { [500, {}, {}] }
    uploads = server do |request|
      assert_equal '/api/upload', request[:target]
      assert_equal 'POST', request[:method]
      assert_equal 'Bearer example-request-secret', request[:headers]['authorization']
      assert_equal 'identity', request[:headers]['accept-encoding']
      assert_operator request[:body].index('name="data"'), :<, request[:body].index('name="file"')
      assert_operator request[:body].index('name="visibility"'), :<, request[:body].index('name="file"')
      assert_includes request[:body], 'filename="sample.bin"'
      assert_includes request[:body], "\x00\x01\xff".b
      [202, {}, accepted]
    end
    result = client(management, upload_base_url: uploads.url).upload_bytes("\x00\x01\xff".b, 'folder/sample.bin', visibility: 'public', data: { ' chat ' => 'one' }, quality: '720p', private_url_expires_in: 60)
    assert_equal 41, result['id']
    assert_empty management.requests
  end

  def test_regular_file_upload_and_close
    s = server { [202, {}, accepted] }
    Tempfile.create(['sample', '.bin']) do |file|
      file.write('abc'); file.flush
      assert_equal 41, client(s).upload_file(file.path)['id']
      assert_includes s.requests[0][:body], "\r\n\r\nabc\r\n"
    end
  end

  def test_invalid_inputs_send_nothing
    s = server { [500, {}, {}] }
    c = client(s)
    [0, -1, 1.5, '41', true, 9_007_199_254_740_992].each { |id| failure('validation') { c.get_asset(id) } }
    failure('validation') { c.upload_bytes('abc', "bad\nname") }
    failure('validation') { c.upload_bytes('abc', 'file', data: { 'a' => {} }) }
    failure('validation') { c.upload_bytes('abc', 'file', data: { 'x' => 1, ' x ' => 2 }) }
    failure('validation') { c.upload_bytes('abc', 'file', data: { 'x' => 'é' * 257 }) }
    failure('validation') { c.upload_bytes('abc', 'file', visibility: 'other') }
    failure('validation') { c.generate_private_url(41, expires_in: 59) }
    failure('validation') { c.list_uploads(data: { 'x' => 2 }) }
    failure('validation') { c.bulk_delete_assets([]) }
    failure('validation') { c.bulk_delete_assets([41] * 101) }
    failure('validation') { c.list_assets(limit: 101) }
    failure('validation') { c.get_asset(41, cancel: true) }
    failure('validation') { c.get_asset(41, timeout: false) }
    failure('validation') { c.list_uploads(project_id: false) }
    failure('validation') { Kompressr::Client.new(api_key: 'example-key', upload_base_url: false) }
    assert_empty s.requests
  end

  def test_named_pipe_is_rejected_without_blocking
    skip 'FIFO fixture needs POSIX mkfifo.' unless File.respond_to?(:mkfifo)
    Dir.mktmpdir do |directory|
      path = File.join(directory, 'input')
      File.mkfifo(path)
      s = server { [500, {}, {}] }
      duration, = elapsed { failure('validation') { client(s).upload_file(path) } }
      assert_operator duration, :<, 0.2
      assert_empty s.requests
    end
  end

  def test_status_and_exact_case_validation
    s = server { [200, {}, envelope(asset(status: 'failed', Status: 'processed'))] }
    error = failure('processing') { client(s).wait_until_ready(41) }
    assert_equal 'PROCESSING_FAILED', error.code
    s2 = server { [200, {}, envelope(asset.merge('ID' => 99, 'Can_generate_private_url' => true))] }
    result = client(s2).get_upload_status(41)
    assert_equal 41, result['id']
    refute result.key?('ID')
  end

  def test_wait_pending_then_processed
    s = server do |_, _, index|
      [200, {}, envelope(asset(status: index == 1 ? 'processing' : 'processed'))]
    end
    result = client(s).wait_until_ready(41, timeout: 1, poll_interval: 0.01)
    assert_equal 'processed', result['status']
    assert_equal 2, s.requests.size
  end

  def test_private_readiness_then_explicit_signing
    private_asset = asset(visibility: 'private', can_generate_private_url: true).reject { |k, _| k == 'cdn_url' }
    s = server do |request|
      if request[:target].end_with?('/private-url')
        assert_equal({ 'expires_in' => 60, 'variant' => 'avif' }, JSON.parse(request[:body]))
        [200, {}, envelope({ 'asset_id' => 41, 'variant' => 'avif', 'private_url' => 'https://cdn.example/private?token=example', 'expires_at' => '2030-01-01T00:01:00Z', 'expires_in' => 60 })]
      else
        [200, {}, envelope(private_asset)]
      end
    end
    c = client(s)
    assert_equal 'private', c.wait_until_ready(41)['visibility']
    assert_equal 1, s.requests.size
    assert_equal 'avif', c.generate_private_url(41, expires_in: 60, variant: 'avif')['variant']
  end

  def test_wait_terminal_states_and_deletion
    %w[failed unprocessable unknown].each do |status|
      s = server { [200, {}, envelope(asset(status: status))] }
      error = failure('processing') { client(s).wait_until_ready(41) }
      assert_equal 'PROCESSING_FAILED', error.code
      assert_equal 41, error.asset_id
    end
    s = server { [200, {}, envelope(asset(deletion_status: 'deleting').reject { |k, _| k == 'cdn_url' })] }
    assert_equal 'ASSET_DELETED', failure('processing') { client(s).wait_until_ready(41) }.code
  end

  def test_wait_requires_public_url_or_private_signability
    [asset.reject { |k, _| k == 'cdn_url' }, asset(visibility: 'private').reject { |k, _| k == 'cdn_url' }].each do |value|
      s = server { [200, {}, envelope(value)] }
      error = failure('invalid_response') { client(s).wait_until_ready(41, timeout: 0.06, poll_interval: 0.01) }
      assert_equal 'INVALID_RESPONSE', error.code
      assert_equal 41, error.asset_id
      assert_equal 1, s.requests.size
    end
  end

  def test_wait_deadline_bounds_inflight_status
    s = server { sleep 1; [200, {}, envelope(asset)] }
    duration, error = elapsed { failure('timeout') { client(s).wait_until_ready(41, timeout: 0.08) } }
    assert_equal 'WAIT_TIMEOUT', error.code
    assert_equal 41, error.asset_id
    assert_operator duration, :<, 0.4
  end

  def test_shorter_request_deadline_inside_wait_stays_request_timeout
    s = server { sleep 1; [200, {}, envelope(asset)] }
    error = failure('timeout') { client(s, request_timeout: 0.05).wait_until_ready(41, timeout: 1) }
    assert_equal 'REQUEST_TIMEOUT', error.code
    assert_equal 41, error.asset_id
  end

  def test_cancel_before_dispatch_and_wait_cancellation
    token = Kompressr::CancellationToken.new
    token.cancel
    s = server { [200, {}, envelope(asset)] }
    error = failure('cancelled') { client(s).delete_asset(41, cancel: token) }
    refute error.may_have_succeeded
    assert_empty s.requests
    assert_equal 'WAIT_CANCELLED', failure('cancelled') { client(s).wait_until_ready(41, cancel: token) }.code
  end

  def test_cancel_pending_mutation_retains_uncertainty_and_id
    token = Kompressr::CancellationToken.new
    s = server { token.cancel; sleep 0.2; [202, {}, state(deletion_status: 'deleting')] }
    error = failure('cancelled') { client(s).delete_asset(41, cancel: token) }
    assert error.may_have_succeeded
    assert_equal 41, error.asset_id
    assert_equal 1, s.requests.size
  end

  def test_upload_listing_filters_and_lazy_pagination
    s = server do |request|
      query = URI.decode_www_form(URI.parse(request[:target]).query).to_h
      assert_equal PROJECT, query['project_id']
      assert_equal '3', query['status']
      assert_equal 'hello world', query['data.chat']
      page_number = query['page'].to_i
      [200, {}, page([asset(id: 40 + page_number)], page: page_number, limit: 1, total: 2)]
    end
    iterator = client(s).iterate_uploads(limit: 1, status: 'processed', data: { 'chat' => 'hello world' })
    assert_empty s.requests
    assert_equal 41, iterator.next['id']
    assert_equal 1, s.requests.size
    assert_equal 42, iterator.next['id']
    assert_raises(StopIteration) { iterator.next }
    assert_equal 2, s.requests.size
  end

  def test_pagination_rejects_wrong_page
    s = server { [200, {}, page([asset], page: 2)] }
    failure('invalid_response') { client(s).iterate_uploads.to_a }
    assert_equal 1, s.requests.size
  end

  def test_asset_listing_detail_delete_and_partial_bulk
    s = server do |request|
      case request[:target]
      when '/api/assets?page=1&limit=20&deletion_status=active'
        [200, {}, page([state])]
      when '/api/assets/41'
        [200, {}, state(deletion_status: request[:method] == 'DELETE' ? 'deleting' : 'active')]
      when '/api/assets/bulk-delete'
        assert_equal [41, 42, 41], JSON.parse(request[:body])['asset_ids']
        [200, {}, { 'results' => [{ 'id' => 41, 'status' => 202, 'accepted' => true, 'state' => state(deletion_status: 'deleting') },
                                { 'id' => 42, 'status' => 403, 'accepted' => false, 'code' => 'FORBIDDEN', 'error' => 'No permission.' }],
                    'counts' => { 'total' => 2, 'accepted' => 1, 'failed' => 1 } }]
      else
        flunk 'Unexpected request.'
      end
    end
    c = client(s)
    assert_equal 41, c.list_assets(deletion_status: 'active')['data'][0]['id']
    assert_equal 'active', c.get_asset(41)['deletion_status']
    assert_equal 'deleting', c.delete_asset(41)['deletion_status']
    result = c.bulk_delete_assets([41, 42, 41])
    assert_equal 1, result['counts']['failed']
    assert_equal 'FORBIDDEN', result['results'][1]['code']
  end

  def test_malformed_mutation_recovers_safe_id_and_never_replays
    s = server { [202, {}, { 'success' => true, 'data' => { 'asset_id' => 41 } }] }
    error = failure('invalid_response') { client(s, max_read_retries: 5).upload_bytes('abc', 'sample.bin') }
    assert_equal 41, error.asset_id
    assert error.may_have_succeeded
    assert_equal 202, error.status
    assert_equal 1, s.requests.size
  end

  def test_broken_json_and_unsuccessful_envelope_never_recover_upload_id
    ['{"success":true,"data":{"asset_id":41},', { 'success' => false, 'data' => { 'asset_id' => 41 } }, { 'success' => true, 'data' => { 'asset_id' => '41' } }].each do |value|
      s = server { [200, {}, value] }
      error = failure { client(s).upload_bytes('abc', 'sample.bin') }
      assert_nil error.asset_id
      assert error.may_have_succeeded
    end
  end

  def test_malformed_single_and_bulk_mutations_preserve_right_context
    s = server { [202, {}, {}] }
    c = client(s)
    [-> { c.delete_asset(41) }, -> { c.generate_private_url(41) }].each do |call|
      error = failure('invalid_response', &call)
      assert_equal 41, error.asset_id
      assert error.may_have_succeeded
    end
    error = failure('invalid_response') { c.bulk_delete_assets([41, 42]) }
    assert_nil error.asset_id
    assert error.may_have_succeeded
  end

  def test_wrong_ids_and_private_url_leak_are_invalid
    [asset(id: 42), asset(visibility: 'private'), asset(deletion_status: 'deleting'), asset(status: 'unexpected')].each do |value|
      s = server { [200, {}, envelope(value)] }
      failure('invalid_response') { client(s).get_upload_status(41) }
    end
  end

  def test_invalid_utf8_inputs_are_typed_validation_failures
    s = server { [500, {}, {}] }
    c = client(s)
    invalid = "\xff".b.force_encoding(Encoding::UTF_8)
    failure('validation') { c.platform.create_user(invalid) }
    failure('validation') { c.platform.update_user(invalid) }
    failure('validation') { c.platform.create_upload_key(USER, invalid) }
    failure('validation') { c.upload_bytes('x', invalid) }
    failure('validation') { c.upload_file("bad\0path") }
    failure('validation') { Kompressr::Client.new(api_key: invalid) }
    assert_empty s.requests
    assert_equal 'é', Kompressr::Validation.text("\xc3\xa9".b, 'name', 120)
  end

  def test_invalid_json_unicode_preserves_typed_failure_and_ambiguity
    invalid_values = ["\xff".b, '\\uDFFF']
    invalid_values.each do |invalid|
      body = '{"success":true,"data":{"asset_id":41,"original_name":"'.b + invalid.b + '"}}'.b
      s = server { [202, {}, body] }
      error = failure('invalid_response') { client(s).upload_bytes('abc', 'file') }
      assert_equal 202, error.status
      assert error.may_have_succeeded
      assert_nil error.asset_id
      denial = server { [403, {}, '{"error":"'.b + invalid.b + '"}'.b] }
      error = failure('api') { client(denial).get_asset(41) }
      assert_equal 403, error.status
      assert error.message.valid_encoding?
    end
  end
end
