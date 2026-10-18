# frozen_string_literal: true

require_relative 'support'
require_relative '../examples/private_upload'
require_relative '../examples/rails_service'
require 'rbconfig'

class ExamplesTest < Minitest::Test
  include Fixtures

  Record = Struct.new(:kompressr_asset_id) do
    def update!(kompressr_asset_id:)
      self.kompressr_asset_id = kompressr_asset_id
    end
  end

  def private_fixture
    asset(visibility: 'private', can_generate_private_url: true).reject { |key, _| key == 'cdn_url' }
  end

  def private_acceptance
    result = accepted(visibility: 'private')
    result.fetch('data').delete('cdn_url')
    result
  end

  def upload_path
    Tempfile.create(['example', '.png']) do |file|
      file.write('abc')
      file.flush
      yield file.path
    end
  end

  def signed_response(expires_in)
    envelope({ 'asset_id' => 41, 'variant' => 'webp', 'private_url' => 'https://cdn.example/private?token=example',
               'expires_at' => '2030-01-01T00:00:00Z', 'expires_in' => expires_in })
  end

  def test_private_example_persists_before_wait_and_signs
    saved = []
    fixture = server do |request|
      case request[:target]
      when '/api/upload'
        assert_includes request[:body], "name=\"visibility\"\r\n\r\nprivate"
        [202, {}, private_acceptance]
      when '/api/upload/41/status'
        assert_equal [41], saved
        [200, {}, envelope(private_fixture)]
      when '/api/upload/41/private-url'
        assert_equal [41], saved
        assert_equal 3600, JSON.parse(request[:body]).fetch('expires_in')
        [200, {}, signed_response(3600)]
      else
        flunk "Unexpected request #{request[:target]}"
      end
    end
    upload_path do |path|
      result = KompressrExamples.private_upload(client(fixture), path, save_asset_id: ->(id) { saved << id })
      assert_equal 'https://cdn.example/private?token=example', result.fetch('private_url')
    end
    assert_equal 3, fixture.requests.size
  end

  def test_rails_service_runs_without_rails_and_persists_before_preparing
    record = Record.new
    fixture = server do |request|
      case request[:target]
      when '/api/upload'
        [202, {}, private_acceptance]
      when '/api/upload/41/status'
        assert_equal 41, record.kompressr_asset_id
        [200, {}, envelope(private_fixture)]
      when '/api/upload/41/private-url'
        assert_equal 900, JSON.parse(request[:body]).fetch('expires_in')
        [200, {}, signed_response(900)]
      else
        flunk "Unexpected request #{request[:target]}"
      end
    end
    service = KompressrAttachmentService.new(files: client(fixture))
    upload_path { |path| assert_equal 41, service.upload(path, attachment_record: record).fetch('id') }
    assert_equal 41, record.kompressr_asset_id
    assert_equal 'processed', service.prepare(record.kompressr_asset_id).fetch('status')
    assert_equal 'https://cdn.example/private?token=example', service.download_url(record.kompressr_asset_id)
    refute Object.const_defined?(:Rails)
    refute_includes service.inspect, 'example-request-secret'
    assert_equal 3, fixture.requests.size
  end

  def test_both_examples_preserve_a_recovered_id_without_reuploading
    saved = []
    first = server { [202, {}, { 'success' => true, 'data' => { 'asset_id' => 41 } }] }
    upload_path do |path|
      error = failure('invalid_response') { KompressrExamples.private_upload(client(first), path, save_asset_id: ->(id) { saved << id }) }
      assert error.may_have_succeeded
    end
    assert_equal [41], saved
    assert_equal 1, first.requests.size

    record = Record.new
    second = server { [202, {}, { 'success' => true, 'data' => { 'asset_id' => 41 } }] }
    service = KompressrAttachmentService.new(files: client(second))
    upload_path do |path|
      error = failure('invalid_response') { service.upload(path, attachment_record: record) }
      assert error.may_have_succeeded
    end
    assert_equal 41, record.kompressr_asset_id
    assert_equal 1, second.requests.size
  end

  def run_cli(directory, fixture, input, record)
    bootstrap = File.join(directory, 'local_endpoint.rb')
    File.write(bootstrap, <<~RUBY)
      require 'kompressr'
      module ExampleTestEndpoint
        def new(**options)
          super(**options.merge(api_base_url: ENV.fetch('KOMPRESSR_EXAMPLE_TEST_URL'), request_timeout: 2, max_read_retries: 0))
        end
      end
      Kompressr::Client.singleton_class.prepend(ExampleTestEndpoint)
    RUBY
    env = { 'KOMPRESSR_API_KEY' => 'example-request-secret', 'KOMPRESSR_EXAMPLE_TEST_URL' => fixture.url }
    script = File.expand_path('../examples/private_upload.rb', __dir__)
    output = IO.popen([env, RbConfig.ruby, '-r', bootstrap, script, input, record], err: [:child, :out], &:read)
    [output, $?.success?]
  end

  def test_cli_reserves_private_recovery_file_before_upload_and_never_overwrites_it
    Dir.mktmpdir do |directory|
      record = File.join(directory, 'asset-id.txt')
      fixture = server do |request|
        case request[:target]
        when '/api/upload'
          assert File.file?(record)
          assert_equal '', File.read(record)
          assert_equal 0o600, File.stat(record).mode & 0o777
          [202, {}, private_acceptance]
        when '/api/upload/41/status'
          assert_equal "41\n", File.read(record)
          [200, {}, envelope(private_fixture)]
        when '/api/upload/41/private-url'
          [200, {}, signed_response(3600)]
        else
          flunk "Unexpected request #{request[:target]}"
        end
      end
      upload_path do |path|
        output, success = run_cli(directory, fixture, path, record)
        assert success, output
        assert_equal "41\n", File.read(record)
        refute_includes output, 'cdn.example'
        refute_includes output, 'example-request-secret'
        assert_equal 3, fixture.requests.size

        _, success = run_cli(directory, fixture, path, record)
        refute success
        assert_equal "41\n", File.read(record)
        assert_equal 3, fixture.requests.size
      end
    end
  end

  def test_cli_persists_recovered_id_and_exits_unsuccessfully_for_uncertain_upload
    Dir.mktmpdir do |directory|
      record = File.join(directory, 'asset-id.txt')
      fixture = server { [202, {}, { 'success' => true, 'data' => { 'asset_id' => 41 } }] }
      upload_path do |path|
        output, success = run_cli(directory, fixture, path, record)
        refute success
        assert_equal "41\n", File.read(record)
        assert_includes output, 'INVALID_RESPONSE'
        assert_includes output, 'Resume using asset 41'
        refute_includes output, 'example-request-secret'
      end
      assert_equal 1, fixture.requests.size
    end
  end
end
