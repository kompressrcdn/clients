# frozen_string_literal: true

require_relative 'support'
require 'zlib'

class TransportTest < Minitest::Test
  include Fixtures

  def test_get_retries_eligible_statuses_only
    [429, 502, 503, 504].each do |status|
      s = server do |_, _, index|
        index == 1 ? [status, { 'Retry-After' => '0' }, { 'error' => 'Temporarily unavailable.' }] : [200, {}, envelope(asset)]
      end
      assert_equal 41, client(s, max_read_retries: 1).get_upload_status(41)['id']
      assert_equal 2, s.requests.size
    end
  end

  def test_get_network_failure_retries_but_mutation_does_not
    s = server do |_, socket, index|
      if index == 1
        socket.close
        nil
      else
        [200, {}, envelope(asset)]
      end
    end
    assert_equal 41, client(s, max_read_retries: 1).get_upload_status(41)['id']
    assert_equal 2, s.requests.size
    s2 = server { |_, socket| socket.close; nil }
    error = failure('network') { client(s2, max_read_retries: 5).platform.suspend_user(USER) }
    assert error.may_have_succeeded
    assert_equal 1, s2.requests.size
  end

  def test_retry_count_bounds_attempts
    s = server { [503, { 'Retry-After' => '0' }, {}] }
    error = failure('api') { client(s, max_read_retries: 1).get_asset(41) }
    assert_equal 503, error.status
    assert_equal 2, s.requests.size
  end

  def test_huge_retry_after_exhausts_deadline_without_early_retry
    ['9223372036854776', '9' * 400].each do |delay|
      s = server { [503, { 'Retry-After' => delay }, {}] }
      duration, error = elapsed { failure('timeout') { client(s, request_timeout: 0.12, max_read_retries: 2).get_asset(41) } }
      assert_equal 503, error.status
      assert_operator error.retry_after_ms, :>, 1_000_000
      assert_operator duration, :>=, 0.10
      assert_operator duration, :<, 0.5
      assert_equal 1, s.requests.size
    end
  end

  def test_retry_delay_from_body_and_http_date
    responses = [[{ 'Retry-After' => (Time.now + 120).httpdate }, {}], [{}, { 'retry_after' => 120 }]]
    responses.each do |headers, body|
      s = server { [429, headers, body] }
      error = failure('timeout') { client(s, request_timeout: 0.06, max_read_retries: 1).get_asset(41) }
      assert_equal 429, error.status
      assert_operator error.retry_after_ms, :>, 100_000
      assert_equal 1, s.requests.size
    end
  end

  def test_cancellation_during_backoff_retains_retry_metadata
    token = Kompressr::CancellationToken.new
    s = server { [503, { 'Retry-After' => '120' }, {}] }
    watcher = Thread.new { sleep 0.05; token.cancel }
    error = failure('cancelled') { client(s, max_read_retries: 1).get_asset(41, cancel: token) }
    assert_equal 503, error.status
    assert_equal 120_000, error.retry_after_ms
    assert_equal 41, error.asset_id
    assert_equal 1, s.requests.size
  ensure
    watcher&.join
  end

  def test_no_redirect_following_or_replay
    destination = server { [200, {}, envelope(asset)] }
    [301, 302, 307, 308].each do |status|
      s = server { [status, { 'Location' => destination.url }, {}] }
      error = failure('api') { client(s, max_read_retries: 5).delete_asset(41) }
      assert_equal status, error.status
      assert error.may_have_succeeded
      assert_equal 1, s.requests.size
    end
    assert_empty destination.requests
  end

  def test_nonretryable_and_malformed_reads_never_retry
    [[400, {}], [401, {}], [403, {}], [404, {}], [500, {}], [200, {}], [200, '<html>gateway</html>']].each do |status, body|
      s = server { [status, {}, body] }
      failure { client(s, max_read_retries: 5).get_asset(41) }
      assert_equal 1, s.requests.size
    end
  end

  def test_total_deadline_includes_delayed_headers
    s = server do |_, socket|
      socket.write('HTTP/1.1 200')
      sleep 0.5
      nil
    end
    duration, error = elapsed { failure('timeout') { client(s, request_timeout: 0.06).get_asset(41) } }
    assert_equal 'REQUEST_TIMEOUT', error.code
    assert_operator duration, :<, 0.4
  end

  def test_slow_body_deadline_preserves_status_retry_delay_and_write_context
    s = server do |_, socket|
      socket.write("HTTP/1.1 503 Service Unavailable\r\nContent-Length: 100\r\nRetry-After: 5\r\n\r\n{")
      sleep 0.5
      nil
    end
    error = failure('timeout') { client(s, request_timeout: 0.06).delete_asset(41) }
    assert_equal 503, error.status
    assert_equal 5000, error.retry_after_ms
    assert_equal 41, error.asset_id
    assert error.may_have_succeeded
  end

  def test_chunked_response_with_trailers_and_informational_status
    body = JSON.generate(envelope(asset))
    s = server do |_, socket|
      socket.write("HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 103 Early Hints\r\nLink: </asset>\r\n\r\nHTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
      body.bytes.each_slice(17) do |slice|
        text = slice.pack('C*')
        socket.write("#{text.bytesize.to_s(16)};sample=yes\r\n#{text}\r\n")
      end
      socket.write("0\r\nX-Checksum: example\r\n\r\n")
      nil
    end
    assert_equal 41, client(s).get_upload_status(41)['id']
  end

  def test_connection_close_response
    s = server do |_, socket|
      socket.write("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n" + JSON.generate(envelope(asset)))
      nil
    end
    assert_equal 41, client(s).get_upload_status(41)['id']
  end

  def test_ambiguous_and_unsupported_framing_is_rejected
    frames = [
      "Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
      "Content-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
      "Transfer-Encoding: gzip, chunked\r\n\r\n0\r\n\r\n",
      "Content-Length: -1\r\n\r\n{}",
      "Transfer-Encoding: chunked\r\n\r\ninvalid\r\n",
      "Transfer-Encoding: chunked\r\n\r\n2\r\n{}xx",
      "Transfer-Encoding: chunked\r\n\r\n0\r\nContent-Length: 0\r\n\r\n",
      " Bad-Fold: value\r\n\r\n{}",
      "X-Header: bad\nline\r\n\r\n{}"
    ]
    frames.each do |frame|
      s = server { |_, socket| socket.write("HTTP/1.1 200 OK\r\n#{frame}"); nil }
      error = failure('invalid_response') { client(s, max_read_retries: 2).get_asset(41) }
      assert_equal 200, error.status unless frame.start_with?(' Bad-', 'X-Header:')
      assert_equal 1, s.requests.size
    end
  end

  def test_protocol_upgrade_and_unbounded_informational_responses_are_rejected
    ["HTTP/1.1 101 Switching Protocols\r\n\r\n", "HTTP/1.1 100 Continue\r\n\r\n" * 6].each do |frame|
      s = server { |_, socket| socket.write(frame); nil }
      failure('invalid_response') { client(s).get_asset(41) }
    end
  end

  def test_truncated_responses_are_network_failures_with_write_uncertainty
    ["Content-Length: 20\r\n\r\n{}", "Transfer-Encoding: chunked\r\n\r\na\r\n{}", "Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n"].each do |frame|
      s = server { |_, socket| socket.write("HTTP/1.1 200 OK\r\n#{frame}"); nil }
      error = failure('network') { client(s).delete_asset(41) }
      assert error.may_have_succeeded
      assert_equal 41, error.asset_id
      assert_equal 200, error.status
    end
  end

  def test_response_and_header_limits
    frames = ["Content-Length: 2097153\r\n\r\n", "Transfer-Encoding: chunked\r\n\r\n200001\r\n",
              "X-Long: #{'x' * 65_536}\r\n\r\n", "Transfer-Encoding: chunked\r\n\r\n1;#{'x' * 8192}\r\na\r\n0\r\n\r\n"]
    frames.each do |frame|
      s = server { |_, socket| socket.write("HTTP/1.1 200 OK\r\n#{frame}"); nil }
      failure('invalid_response') { client(s).get_asset(41) }
    end
  end

  def test_compressed_body_rejected_before_decompression
    compressed = Zlib.gzip('x' * (32 * 1024 * 1024))
    s = server { [200, { 'Content-Encoding' => 'gzip' }, compressed] }
    error = failure('invalid_response') { client(s).get_asset(41) }
    assert_equal 200, error.status
    assert_includes error.message, 'content encoding'
    assert_operator compressed.bytesize, :<, 40_000
  end

  def test_compressed_error_keeps_status_and_retry_deadline
    s = server { [503, { 'Content-Encoding' => 'gzip', 'Retry-After' => '120' }, Zlib.gzip('unavailable')] }
    error = failure('timeout') { client(s, max_read_retries: 2, request_timeout: 0.06).get_asset(41) }
    assert_equal 503, error.status
    assert_equal 120_000, error.retry_after_ms
    assert_equal 1, s.requests.size
  end

  def test_large_streamed_upload_uses_bounded_live_memory
    s = server(capture: false) { [202, {}, accepted] }
    Tempfile.create(['large', '.bin']) do |file|
      file.truncate(32 * 1024 * 1024); file.flush
      GC.start
      baseline = ObjectSpace.memsize_of_all(String)
      peak = baseline
      running = true
      sampler = Thread.new do
        while running
          GC.start
          peak = [peak, ObjectSpace.memsize_of_all(String)].max
          sleep 0.002
        end
      end
      begin
        assert_equal 41, client(s).upload_file(file.path)['id']
      ensure
        running = false
        sampler.join
      end
      assert_operator s.requests[0][:size], :>, 32 * 1024 * 1024
      assert_operator peak - baseline, :<, 8 * 1024 * 1024
    end
  end

  def test_repeated_cancellation_releases_connections
    baseline = Kompressr::Internal::Capacity.instance_variable_get(:@counts)[:connection]
    s = server { sleep 0.1; [200, {}, envelope(asset)] }
    12.times do
      token = Kompressr::CancellationToken.new
      t = Thread.new { sleep 0.01; token.cancel }
      failure('cancelled') { client(s).get_upload_status(41, cancel: token) }
      t.join
    end
    assert_equal baseline, Kompressr::Internal::Capacity.instance_variable_get(:@counts)[:connection]
  end

  def test_early_upload_denials_preserve_status_without_reading_body
    Tempfile.create(['early', '.bin']) do |file|
      file.truncate(32 * 1024 * 1024); file.flush
      [403, 413, 429].each do |status|
        [false, true].each do |keep_open|
          s = server(read_body: false) do |_, socket|
            body = JSON.generate('success' => false, 'code' => 'UPLOAD_DENIED', 'error' => 'Upload denied.')
            socket.write("HTTP/1.1 #{status} Denied\r\nContent-Length: #{body.bytesize}\r\nRetry-After: 5\r\n\r\n#{body}")
            sleep 0.5 if keep_open
            nil
          end
          duration, error = elapsed { failure('api') { client(s, max_read_retries: 5).upload_file(file.path, timeout: 0.3) } }
          assert_equal status, error.status
          assert_equal 'UPLOAD_DENIED', error.code
          assert_equal 5000, error.retry_after_ms
          refute error.may_have_succeeded
          assert_operator duration, :<, 0.3
          assert_equal 1, s.requests.size
        end
      end
    end
  end

  def test_early_interim_headers_do_not_stop_upload
    s = server(read_body: false) do |request, socket|
      socket.write("HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 103 Early Hints\r\nLink: </example>\r\n\r\n")
      remaining = request[:size]
      while remaining.positive?
        chunk = socket.read([remaining, 65_536].min)
        raise EOFError unless chunk
        remaining -= chunk.bytesize
      end
      [202, {}, accepted]
    end
    Tempfile.create(['continue', '.bin']) do |file|
      file.truncate(4 * 1024 * 1024); file.flush
      assert_equal 41, client(s).upload_file(file.path)['id']
    end
    assert_equal 1, s.requests.size
  end

  def test_partial_early_headers_retain_known_status_and_retry_delay
    s = server(read_body: false) do |_, socket|
      socket.write("HTTP/1.1 429 Denied\r\nRetry-After: 5\r\nX-Pending:")
      sleep 0.5
      nil
    end
    Tempfile.create(['early', '.bin']) do |file|
      file.truncate(32 * 1024 * 1024); file.flush
      error = failure('timeout') { client(s).upload_file(file.path, timeout: 0.06) }
      assert_equal 429, error.status
      assert_equal 5000, error.retry_after_ms
    end
  end
end
