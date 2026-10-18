# frozen_string_literal: true

require 'kompressr'
require 'minitest/autorun'
require 'tempfile'
require 'tmpdir'
require 'digest'
require 'objspace'

module Fixtures
  PROJECT = '00000000-0000-4000-8000-000000000001'
  USER = '00000000-0000-4000-8000-000000000002'
  KEY = '00000000-0000-4000-8000-000000000003'

  def asset(**changes)
    { 'id' => 41, 'status' => 'processed', 'deletion_status' => 'active', 'visibility' => 'public',
      'original_name' => 'sample.bin', 'original_size' => 3, 'asset_type' => 'image', 'kompressd_size' => 2,
      'savings_percent' => 33.3, 'can_generate_private_url' => false, 'cdn_url' => 'https://cdn.example/sample.webp' }.merge(changes.transform_keys(&:to_s))
  end
  def accepted(**changes)
    v = asset(**changes)
    v['asset_id'] = v.delete('id')
    v.delete('kompressd_size'); v.delete('savings_percent'); v.delete('can_generate_private_url')
    { 'success' => true, 'data' => v }
  end
  def state(**changes)
    { 'id' => 41, 'project_id' => PROJECT, 'kind' => 1, 'source' => 'upload', 'processing_status' => 3,
      'deletion_status' => 'active', 'storage_credited_mb' => 0 }.merge(changes.transform_keys(&:to_s))
  end
  def user(**changes)
    { 'id' => USER, 'project_id' => PROJECT, 'customer_user_id' => 'customer-1', 'status' => 'active' }.merge(changes.transform_keys(&:to_s))
  end
  def key(**changes)
    { 'id' => KEY, 'key_id' => KEY, 'project_id' => PROJECT, 'project_user_id' => USER, 'name' => 'Chat',
      'scopes' => %w[upload status list private_url], 'allowed_visibility' => 'private' }.merge(changes.transform_keys(&:to_s))
  end
  def issued(**changes)
    { 'success' => true, 'id' => KEY, 'key_id' => KEY, 'api_key' => 'example-issued-secret', 'upload_key' => key }.merge(changes.transform_keys(&:to_s))
  end
  def envelope(value) = { 'success' => true, 'data' => value }
  def page(rows, page: 1, limit: 20, total: rows.size, key: 'data')
    { 'success' => true, key => rows, 'page' => page, 'limit' => limit, 'total' => total }
  end
  def client(server, **options)
    Kompressr::Client.new(api_key: 'example-request-secret', api_base_url: server.url, project_id: PROJECT,
                          max_read_retries: 0, request_timeout: 2, **options)
  end
  def failure(kind = nil)
    error = assert_raises(Kompressr::Error) { yield }
    assert_equal kind, error.kind if kind
    assert_nil error.cause
    error
  end
  def elapsed
    started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    result = yield
    [Process.clock_gettime(Process::CLOCK_MONOTONIC) - started, result]
  end

  class Server
    attr_reader :url, :requests
    def initialize(capture: true, tls: nil, read_body: true, &handler)
      @listener = TCPServer.new('127.0.0.1', 0)
      @url = "#{tls ? 'https' : 'http'}://127.0.0.1:#{@listener.addr[1]}"
      @requests, @workers, @sockets = [], [], []
      @errors = Queue.new
      @mutex = Mutex.new
      @acceptor = Thread.new do
        Thread.current.report_on_exception = false
        loop do
          socket = @listener.accept
          @sockets << socket
          @workers << Thread.new(socket) do |connection|
            Thread.current.report_on_exception = false
            begin
              if tls
                connection = OpenSSL::SSL::SSLSocket.new(connection, tls)
                connection.sync_close = true
                connection.accept
              end
              request_line = connection.gets("\r\n")
              next unless request_line
              headers = {}
              while (line = connection.gets("\r\n")) && line != "\r\n"
                name, value = line.split(':', 2)
                headers[name.downcase] = value.strip
              end
              size = headers.fetch('content-length', '0').to_i
              body, digest = ''.b, Digest::SHA256.new
              remaining = size
              while read_body && remaining.positive?
                chunk = connection.read([remaining, 65_536].min)
                raise EOFError if chunk.nil?
                body << chunk if capture
                digest.update(chunk)
                remaining -= chunk.bytesize
              end
              method, target = request_line.split(' ', 3)
              request = { method: method, target: target, headers: headers, body: body, size: size, digest: digest.hexdigest }
              index = @mutex.synchronize { @requests << request; @requests.size }
              response = handler.call(request, connection, index)
              if response
                status, response_headers, value = response
                content = value.instance_of?(String) ? value.b : JSON.generate(value).b
                response_headers ||= {}
                default_headers = { 'Content-Type' => 'application/json', 'Content-Length' => content.bytesize.to_s, 'Connection' => 'close' }
                connection.write("HTTP/1.1 #{status || 200} Response\r\n" + default_headers.merge(response_headers).map { |k, v| "#{k}: #{v}\r\n" }.join + "\r\n" + content)
              end
            rescue IOError, SystemCallError, OpenSSL::SSL::SSLError
              # Client timeout/cancellation and negative TLS tests close sockets.
            rescue Exception => error # Also propagate assertions from handler threads.
              @errors << error
            ensure
              connection.close unless connection.closed?
            end
          end
        end
      rescue IOError, SystemCallError
        nil
      end
    end
    def close
      @listener.close unless @listener.closed?
      @acceptor.join(1)
      @sockets.each { |socket| socket.close unless socket.closed? }
      @workers.each { |thread| thread.join(0.05); thread.kill if thread.alive?; thread.join }
      raise @errors.pop unless @errors.empty?
    end
    def self.open(**options, &handler)
      new(**options, &handler)
    end
  end

  def server(**options, &handler)
    @servers ||= []
    value = Server.new(**options, &handler)
    @servers << value
    value
  end
  def teardown
    @servers&.each(&:close)
  end
end
