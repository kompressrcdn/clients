# frozen_string_literal: true

require_relative 'support'

class PlatformTest < Minitest::Test
  include Fixtures

  def test_all_nine_platform_methods_and_wire_shapes
    s = server do |request|
      path = request[:target]
      case [request[:method], path]
      when ['GET', '/api/platform/project-users?page=1&limit=20']
        [200, {}, page([user], key: 'project_users').merge('project_active_count' => 1, 'org_active_count' => 2, 'usage_period' => { 'start' => '2026-10-01', 'end' => '2026-11-01' })]
      when ['POST', '/api/platform/project-users']
        assert_equal({ 'customer_user_id' => 'customer-1', 'display_name' => 'Chat user', 'metadata' => { 'segment' => nil } }, JSON.parse(request[:body]))
        [201, {}, { 'success' => true, 'created' => true, 'project_user' => user }]
      when ['PATCH', "/api/platform/project-users/#{USER}"]
        assert_equal({ 'display_name' => '', 'metadata' => {} }, JSON.parse(request[:body]))
        [200, {}, { 'success' => true, 'project_user' => user }]
      when ['POST', "/api/platform/project-users/#{USER}/suspend"]
        [200, {}, { 'success' => true, 'project_user' => user(status: 'suspended') }]
      when ['POST', "/api/platform/project-users/#{USER}/reactivate"]
        [200, {}, { 'success' => true, 'project_user' => user }]
      when ['GET', "/api/platform/project-users/#{USER}/upload-keys?page=1&limit=20"]
        [200, {}, page([key], key: 'upload_keys')]
      when ['POST', "/api/platform/project-users/#{USER}/upload-keys"]
        body = JSON.parse(request[:body])
        assert_equal %w[upload status private_url], body['scopes']
        assert_equal 'private', body['allowed_visibility']
        assert_equal [1, 2], body['allowed_asset_types']
        assert_equal '2099-01-01T00:00:00Z', body['expires_at']
        [201, {}, issued]
      when ['POST', "/api/platform/project-users/#{USER}/upload-keys/#{KEY}/rotate"]
        [200, {}, issued(api_key: 'example-rotated-secret')]
      when ['POST', "/api/platform/project-users/#{USER}/upload-keys/#{KEY}/revoke"]
        [200, {}, { 'success' => true }]
      else
        flunk 'Unexpected platform request.'
      end
    end
    p = client(s).platform
    assert_equal 2, p.list_users['org_active_count']
    assert p.create_user('customer-1', display_name: 'Chat user', metadata: { 'segment' => nil })['created']
    assert_equal USER, p.update_user(USER, display_name: '', metadata: {})['id']
    assert_equal 'suspended', p.suspend_user(USER)['status']
    assert_equal 'active', p.reactivate_user(USER)['status']
    assert_equal KEY, p.list_upload_keys(USER)['data'][0]['id']
    result = p.create_upload_key(USER, 'Chat', scopes: %w[upload status private_url], allowed_visibility: 'private', allowed_asset_types: [1, 2], expires_at: '2099-01-01T00:00:00Z')
    assert_equal 'example-issued-secret', result.reveal_api_key
    assert_equal 'example-rotated-secret', p.rotate_upload_key(USER, KEY).reveal_api_key
    assert_nil p.revoke_upload_key(USER, KEY)
    assert_equal 9, s.requests.size
  end

  def test_empty_scopes_rejected_but_omission_selects_defaults
    s = server do |request|
      refute JSON.parse(request[:body]).key?('scopes')
      [201, {}, issued]
    end
    p = client(s).platform
    error = failure('validation') { p.create_upload_key(USER, 'Chat', scopes: []) }
    refute error.may_have_succeeded
    assert_empty s.requests
    assert_equal KEY, p.create_upload_key(USER, 'Chat').id
    assert_equal 1, s.requests.size
  end

  def test_platform_invalid_inputs_send_nothing
    s = server { [500, {}, {}] }
    p = client(s).platform
    failure('validation') { p.create_upload_key(USER, 'Chat', scopes: ['other']) }
    failure('validation') { p.create_upload_key(USER, 'Chat', allowed_asset_types: [true]) }
    failure('validation') { p.create_upload_key(USER, 'Chat', expires_at: '2020-01-01T00:00:00Z') }
    failure('validation') { p.create_upload_key(USER, 'Chat', expires_at: '2099-01-01T00:00:00') }
    failure('validation') { p.create_upload_key(USER, 'Chat', expires_at: 'invalid') }
    failure('validation') { p.create_user('') }
    failure('validation') { p.update_user('invalid') }
    failure('validation') { p.rotate_upload_key(USER, 'invalid') }
    failure('validation') { p.revoke_upload_key(USER, 'invalid') }
    assert_empty s.requests
  end

  def test_issued_keys_hide_secrets_and_drop_unknown_nested_fields
    s = server { [201, {}, issued(upload_key: key(api_key: 'example-nested-secret', ApiKey: 'example-case-secret'))] }
    p = client(s).platform
    result = p.create_upload_key(USER, 'Chat')
    assert_equal 'example-issued-secret', result.reveal_api_key
    [result.inspect, result.to_s, JSON.generate(result), result.to_h.inspect, p.inspect].each do |logged|
      refute_includes logged, 'example-issued-secret'
      refute_includes logged, 'example-nested-secret'
      refute_includes logged, 'example-case-secret'
      refute_includes logged, 'example-request-secret'
    end
    copy = result.reveal_api_key
    copy.clear
    assert_equal 'example-issued-secret', result.reveal_api_key
  end

  def test_permission_denial_does_not_escalate_or_retry
    s = server { [403, {}, { 'success' => false, 'code' => 'FORBIDDEN', 'error' => 'Project authority required.' }] }
    error = failure('api') { client(s, max_read_retries: 5).platform.list_users }
    assert_equal 403, error.status
    assert_equal 'FORBIDDEN', error.code
    refute error.may_have_succeeded
    assert_equal 1, s.requests.size
  end

  def test_every_platform_mutation_retains_ambiguity_on_malformed_success
    s = server { [200, {}, {}] }
    p = client(s, max_read_retries: 5).platform
    calls = [-> { p.create_user('customer-1') }, -> { p.update_user(USER) }, -> { p.suspend_user(USER) },
             -> { p.reactivate_user(USER) }, -> { p.create_upload_key(USER, 'Chat') },
             -> { p.rotate_upload_key(USER, KEY) }, -> { p.revoke_upload_key(USER, KEY) }]
    calls.each do |call|
      error = failure('invalid_response', &call)
      assert error.may_have_succeeded
      assert_equal 200, error.status
      assert_nil error.asset_id
    end
    assert_equal calls.size, s.requests.size
  end

  def test_error_messages_redact_credentials_and_delivery_urls
    s = server do
      [403, {}, { 'success' => false, 'code' => 'FORBIDDEN', 'error' => 'Denied example-request-secret Bearer example-other https://cdn.example/private?token=example secret=example-value' }]
    end
    error = failure('api') { client(s).platform.list_users }
    logged = error.inspect + JSON.generate(error)
    %w[example-request-secret example-other https://cdn.example example-value].each { |secret| refute_includes logged, secret }
    assert_includes error.message, 'Denied'
  end
end
