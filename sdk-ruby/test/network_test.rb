# frozen_string_literal: true

require_relative 'support'
require 'open3'
require 'rbconfig'

class NetworkTest < Minitest::Test
  include Fixtures

  def test_dns_deadline_cancellation_and_no_late_mutation
    s = server { [200, {}, { 'success' => true, 'project_user' => user }] }
    release = Queue.new
    entered = Queue.new
    original = Addrinfo.method(:getaddrinfo)
    Addrinfo.define_singleton_method(:getaddrinfo) do |*args|
      if args[0] == 'slow.example'
        entered << true
        release.pop
        original.call('127.0.0.1', *args.drop(1))
      else
        original.call(*args)
      end
    end
    c = Kompressr::Client.new(api_key: 'example-key', api_base_url: s.url.sub('127.0.0.1', 'slow.example'), request_timeout: 0.06)
    duration, error = elapsed { failure('timeout') { c.platform.suspend_user(USER) } }
    assert_operator duration, :<, 0.3
    refute error.may_have_succeeded
    assert_equal 1, entered.size
    assert_empty s.requests
    release << true
    sleep 0.04
    assert_empty s.requests
    token = Kompressr::CancellationToken.new
    canceller = Thread.new { sleep 0.02; token.cancel }
    error = failure('cancelled') { c.platform.suspend_user(USER, cancel: token) }
    refute error.may_have_succeeded
    canceller.join
    release << true
    sleep 0.04
    assert_empty s.requests
  ensure
    release << true if release
    Addrinfo.define_singleton_method(:getaddrinfo, original) if original
  end

  def test_dns_worker_slots_are_bounded_and_numeric_hosts_bypass_queue
    s = server { [200, {}, envelope(asset)] }
    release = Queue.new
    entered = Queue.new
    original = Addrinfo.method(:getaddrinfo)
    Addrinfo.define_singleton_method(:getaddrinfo) do |*args|
      if args[0] == 'blocked.example'
        entered << true
        release.pop
        original.call('127.0.0.1', *args.drop(1))
      else
        original.call(*args)
      end
    end
    c = Kompressr::Client.new(api_key: 'example-key', api_base_url: s.url.sub('127.0.0.1', 'blocked.example'), request_timeout: 0.08, max_read_retries: 0)
    threads = 12.times.map do
      Thread.new do
        begin
          c.get_upload_status(41)
        rescue Kompressr::Error => error
          error
        end
      end
    end
    errors = threads.map(&:value)
    assert errors.all? { |error| error.kind == 'timeout' }
    assert_equal 8, entered.size
    assert_equal 41, client(s).get_upload_status(41)['id']
    8.times { release << true }
    sleep 0.05
    assert_equal 0, Kompressr::Internal::Capacity.instance_variable_get(:@counts)[:dns]
    assert_equal 1, s.requests.size
  ensure
    12.times { release << true } if release
    threads&.each { |thread| thread.join(0.2) }
    Addrinfo.define_singleton_method(:getaddrinfo, original) if original
  end

  def test_dns_workers_do_not_hold_process_open_after_timeout
    script = <<~'RUBY'
      require 'kompressr'
      Addrinfo.define_singleton_method(:getaddrinfo) { |*| sleep 60 }
      begin
        Kompressr::Client.new(api_key: 'example-key', api_base_url: 'http://blocked.example', request_timeout: 0.03, max_read_retries: 0).get_asset(41)
      rescue Kompressr::Error => error
        abort 'Wrong error' unless error.kind == 'timeout'
      end
    RUBY
    duration, result = elapsed { Open3.capture3(RbConfig.ruby, '-I', File.expand_path('../lib', __dir__), '-e', script) }
    assert result[2].success?, result[1]
    assert_operator duration, :<, 1.5
  end

  def certificate(trust: true)
    signing_key = OpenSSL::PKey::RSA.new(2048)
    ca = OpenSSL::X509::Certificate.new
    ca.version = 2
    ca.serial = rand(1..1_000_000)
    ca.subject = OpenSSL::X509::Name.parse("/CN=Kompressr SDK fixture authority #{ca.serial}")
    ca.issuer = ca.subject
    ca.public_key = signing_key.public_key
    ca.not_before = Time.now - 60
    ca.not_after = Time.now + 3600
    factory = OpenSSL::X509::ExtensionFactory.new
    factory.subject_certificate = ca
    factory.issuer_certificate = ca
    ca.add_extension(factory.create_extension('basicConstraints', 'CA:TRUE', true))
    ca.add_extension(factory.create_extension('keyUsage', 'keyCertSign,cRLSign', true))
    ca.sign(signing_key, OpenSSL::Digest::SHA256.new)
    leaf_key = OpenSSL::PKey::RSA.new(2048)
    leaf = OpenSSL::X509::Certificate.new
    leaf.version = 2
    leaf.serial = rand(1..1_000_000)
    leaf.subject = OpenSSL::X509::Name.parse('/CN=localhost')
    leaf.issuer = ca.subject
    leaf.public_key = leaf_key.public_key
    leaf.not_before = Time.now - 60
    leaf.not_after = Time.now + 3600
    factory.subject_certificate = leaf
    leaf.add_extension(factory.create_extension('subjectAltName', 'DNS:localhost'))
    leaf.add_extension(factory.create_extension('extendedKeyUsage', 'serverAuth'))
    leaf.sign(signing_key, OpenSSL::Digest::SHA256.new)
    OpenSSL::SSL::SSLContext::DEFAULT_CERT_STORE.add_cert(ca) if trust
    context = OpenSSL::SSL::SSLContext.new
    context.cert, context.key = leaf, leaf_key
    context
  end

  def test_tls_verifies_ca_and_original_hostname_with_sni
    context = certificate
    names = Queue.new
    context.servername_cb = proc { |_, name| names << name; nil }
    s = server(tls: context) { [200, {}, envelope(asset)] }
    c = Kompressr::Client.new(api_key: 'example-key', api_base_url: s.url.sub('127.0.0.1', 'localhost'), max_read_retries: 0)
    assert_equal 41, c.get_upload_status(41)['id']
    assert_equal 'localhost', names.pop
    assert_match(/^localhost:/, s.requests[0][:headers]['host'])
  end

  def test_tls_rejects_hostname_mismatch_and_untrusted_authority_before_dispatch
    trusted = server(tls: certificate) { [200, {}, envelope(asset)] }
    error = failure('network') { client(trusted).delete_asset(41) }
    refute error.may_have_succeeded
    assert_empty trusted.requests
    untrusted = server(tls: certificate(trust: false)) { [200, {}, envelope(asset)] }
    c = Kompressr::Client.new(api_key: 'example-key', api_base_url: untrusted.url.sub('127.0.0.1', 'localhost'), max_read_retries: 0)
    error = failure('network') { c.delete_asset(41) }
    refute error.may_have_succeeded
    assert_empty untrusted.requests
  end

  def test_tls_handshake_remains_inside_deadline
    listener = TCPServer.new('127.0.0.1', 0)
    socket = nil
    worker = Thread.new { socket = listener.accept; sleep 1 }
    c = Kompressr::Client.new(api_key: 'example-key', api_base_url: "https://127.0.0.1:#{listener.addr[1]}", request_timeout: 0.06, max_read_retries: 0)
    duration, error = elapsed { failure('timeout') { c.delete_asset(41) } }
    refute error.may_have_succeeded
    assert_operator duration, :<, 0.4
  ensure
    socket&.close
    listener&.close
    worker&.kill
    worker&.join
  end

  def test_early_tls_upload_denial_is_read_without_finishing_upload
    s = server(tls: certificate, read_body: false) do |_, socket|
      body = JSON.generate('success' => false, 'code' => 'FORBIDDEN', 'error' => 'Denied.')
      socket.write("HTTP/1.1 403 Denied\r\nContent-Length: #{body.bytesize}\r\nRetry-After: 5\r\n\r\n#{body}")
      sleep 0.4
      nil
    end
    c = Kompressr::Client.new(api_key: 'example-key', api_base_url: s.url.sub('127.0.0.1', 'localhost'), max_read_retries: 5)
    Tempfile.create(['tls-early', '.bin']) do |file|
      file.truncate(32 * 1024 * 1024); file.flush
      error = failure('api') { c.upload_file(file.path, timeout: 0.3) }
      assert_equal 403, error.status
      assert_equal 5000, error.retry_after_ms
      refute error.may_have_succeeded
      assert_equal 1, s.requests.size
    end
  end

  def test_concurrent_clients_and_calls_keep_credentials_separate
    s = server do |request|
      id = request[:target].split('/')[3].to_i
      assert_equal "Bearer example-user-#{id}", request[:headers]['authorization']
      [200, {}, envelope(asset(id: id))]
    end
    clients = (100..107).map do |id|
      key = "example-user-#{id}"
      c = Kompressr::Client.new(api_key: key, api_base_url: s.url, max_read_retries: 0)
      key.replace('example-modified-after-construction')
      [id, c]
    end
    threads = clients.flat_map do |id, c|
      2.times.map { Thread.new { c.get_upload_status(id) } }
    end
    assert_equal (100..107).flat_map { |id| [id, id] }, threads.map { |thread| thread.value.fetch('id') }
    assert_equal 16, s.requests.size
  end

  def test_connection_admission_limits_requests_and_is_cancellable
    entered = Queue.new
    release = Queue.new
    token = Kompressr::CancellationToken.new
    s = server do
      entered << true
      release.pop
      nil
    end
    c = client(s, request_timeout: 5)
    threads = 64.times.map do
      Thread.new do
        begin
          c.delete_asset(41, cancel: token)
        rescue Kompressr::Error => error
          error
        end
      end
    end
    deadline = Process.clock_gettime(Process::CLOCK_MONOTONIC) + 3
    sleep 0.005 while entered.size < 64 && Process.clock_gettime(Process::CLOCK_MONOTONIC) < deadline
    assert_equal 64, entered.size
    error = failure('timeout') { c.delete_asset(41, timeout: 0.04) }
    refute error.may_have_succeeded
    waiting_token = Kompressr::CancellationToken.new
    canceller = Thread.new { sleep 0.02; waiting_token.cancel }
    error = failure('cancelled') { c.delete_asset(41, cancel: waiting_token) }
    refute error.may_have_succeeded
    canceller.join
    assert_equal 64, s.requests.size
    token.cancel
    errors = threads.map(&:value)
    assert errors.all? { |value| value.kind == 'cancelled' && value.may_have_succeeded }
    64.times { release << true }
    recovered = server { [200, {}, envelope(asset)] }
    assert_equal 41, client(recovered).get_upload_status(41)['id']
  ensure
    token&.cancel
    64.times { release << true } if release
    threads&.each { |thread| thread.join(1) }
    canceller&.join
  end
end
