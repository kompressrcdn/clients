# frozen_string_literal: true

require 'socket'
require 'openssl'
require 'ipaddr'
require 'securerandom'

module Kompressr
  module Internal
    # Only DNS runs in background threads. A worker never owns a connection or a
    # credential, and cannot dispatch a request after its caller has left.
    module Capacity
      @mutex = Mutex.new
      @pid = Process.pid
      @counts = { dns: 0, connection: 0 }
      LIMITS = { dns: 8, connection: 64 }.freeze
      module_function

      def acquire(kind, context)
        loop do
          context.check!
          taken = @mutex.synchronize do
            if @pid != Process.pid
              @pid = Process.pid
              @counts = { dns: 0, connection: 0 }
            end
            if @counts[kind] < LIMITS[kind]
              @counts[kind] += 1
              true
            end
          end
          return if taken
          context.pause(0.01)
        end
      end

      def release(kind) = @mutex.synchronize { @counts[kind] -= 1 }
    end

    class Context
      attr_accessor :status, :retry_after_ms, :asset_id, :dispatched
      attr_reader :deadline

      def initialize(timeout, cancel, write, asset_id)
        @deadline = self.class.now + timeout
        @cancel, @write, @asset_id = cancel, write, asset_id
        @dispatched = false
      end

      def self.now = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      def remaining = @deadline - self.class.now
      def error(kind)
        code, message = {
          'timeout' => ['REQUEST_TIMEOUT', 'Request timed out; inspect a write outcome before retrying.'],
          'cancelled' => ['REQUEST_CANCELLED', 'Request cancelled; accepted server work is not rolled back.'],
          'network' => ['NETWORK_ERROR', 'Unable to reach Kompressr; check the endpoint and connection.']
        }.fetch(kind)
        Error.new(message, kind: kind, code: code, status: @status, retry_after_ms: @retry_after_ms,
                  asset_id: @asset_id, may_have_succeeded: @write && @dispatched)
      end

      def check!
        raise error('cancelled'), cause: nil if @cancel&.cancelled?
        raise error('timeout'), cause: nil if remaining <= 0
      end

      def pause(seconds)
        # Compare remaining time before adding a potentially enormous retry delay.
        stop = self.class.now + [seconds, [remaining, 0].max].min
        loop do
          check!
          left = stop - self.class.now
          break if left <= 0
          sleep([left, 0.01].min)
        end
        check!
      end

      def wait(io, direction, phase_deadline = @deadline, also_read: false)
        check!
        left = [remaining, phase_deadline - self.class.now].min
        raise PhaseTimeout if left <= 0
        delay = [left, 0.01].min
        if direction == :wait_readable
          IO.select([io], nil, nil, delay)
        else
          IO.select(also_read ? [io] : nil, [io], nil, delay)
        end
        check!
      end
    end

    class PhaseTimeout < StandardError; end

    module Network
      module_function

      def addresses(hostname, port, context)
        begin
          IPAddr.new(hostname)
          return Addrinfo.getaddrinfo(hostname, port, nil, Socket::SOCK_STREAM, nil, Socket::AI_NUMERICHOST)
        rescue IPAddr::InvalidAddressError
          # Domain lookup is isolated from the request thread and its sockets.
        end
        Capacity.acquire(:dns, context)
        result = Queue.new
        begin
          Thread.new do
            Thread.current.report_on_exception = false
            begin
              result << [:ok, Addrinfo.getaddrinfo(hostname, port, nil, Socket::SOCK_STREAM)]
            rescue StandardError
              result << [:error, nil]
            ensure
              Capacity.release(:dns)
            end
          end
        rescue StandardError
          Capacity.release(:dns)
          raise
        end
        loop do
          context.check!
          begin
            state, value = result.pop(true)
            raise SocketError, 'DNS lookup failed.' unless state == :ok
            return value
          rescue ThreadError
            context.pause(0.01)
          end
        end
      end

      def connect(uri, context)
        addresses = addresses(uri.hostname, uri.port, context).uniq(&:to_sockaddr)
        raise SocketError, 'No addresses returned.' if addresses.empty?
        addresses.each_with_index do |address, index|
          context.check!
          socket = Socket.new(address.afamily, Socket::SOCK_STREAM, 0)
          keep = false
          begin
            phase_deadline = Context.now + context.remaining / (addresses.size - index)
            loop do
              context.check!
              result = socket.connect_nonblock(address.to_sockaddr, exception: false)
              break if result == 0
              context.wait(socket, result, phase_deadline)
            rescue Errno::EISCONN
              break
            end
            context.check!
            if uri.scheme == 'https'
              ssl_context = OpenSSL::SSL::SSLContext.new
              ssl_context.set_params(verify_mode: OpenSSL::SSL::VERIFY_PEER,
                                     min_version: OpenSSL::SSL::TLS1_2_VERSION)
              ssl = OpenSSL::SSL::SSLSocket.new(socket, ssl_context)
              ssl.sync_close = true
              ssl.hostname = uri.hostname
              socket = ssl
              loop do
                context.check!
                result = socket.connect_nonblock(exception: false)
                break unless result == :wait_readable || result == :wait_writable
                context.wait(socket, result, phase_deadline)
              end
              socket.post_connection_check(uri.hostname)
            end
            context.check!
            keep = true
            return socket
          rescue PhaseTimeout, SystemCallError, IOError
            raise if index == addresses.size - 1
          ensure
            socket.close unless keep || socket.closed?
          end
        end
        raise SocketError, 'Connection failed.'
      end
    end

    class Body
      attr_reader :content_type, :length
      def initialize(content)
        @content = content.b.freeze
        @length = @content.bytesize
        @content_type = 'application/json'
      end
      def each
        offset = 0
        while offset < @length
          yield @content.byteslice(offset, 65_536)
          offset += 65_536
        end
      end
    end

    class Multipart
      attr_reader :content_type, :length
      def initialize(source, size, filename, fields)
        @source, @size = source, size
        boundary = "kompressr-#{SecureRandom.hex(24)}"
        @content_type = "multipart/form-data; boundary=#{boundary}"
        @prefix = fields.map { |name, value| "--#{boundary}\r\nContent-Disposition: form-data; name=\"#{name}\"\r\n\r\n#{value}\r\n" }.join.b
        escaped = filename.gsub('"', '%22')
        @prefix << "--#{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"#{escaped}\"\r\nContent-Type: application/octet-stream\r\n\r\n".b
        @suffix = "\r\n--#{boundary}--\r\n".b
        @length = @prefix.bytesize + @size + @suffix.bytesize
      end
      def each
        yield @prefix
        offset = 0
        while offset < @size
          chunk = @source.instance_of?(String) ? @source.byteslice(offset, [65_536, @size - offset].min) : @source.read([65_536, @size - offset].min)
          raise IOError, 'Upload source changed while reading.' if chunk.nil? || chunk.empty?
          yield chunk
          offset += chunk.bytesize
        end
        yield @suffix
      end
    end

    # One fresh HTTP/1.1 connection per attempt. Identity bodies only, with strict
    # framing and bounded headers/body; no redirect or native-library replay path.
    class Wire
      MAX_BODY = 2 * 1024 * 1024
      MAX_HEADER = 65_536
      TOKEN = /\A[!#$%&'*+.^_`|~0-9A-Za-z-]+\z/

      def initialize(socket, context)
        @socket, @context = socket, context
        @buffer = ''.b
        @informational = 0
        @eof = false
      end
      def write(bytes, watch_response: false)
        offset = 0
        while offset < bytes.bytesize
          @context.check!
          return :early_response if watch_response && poll_response
          @context.dispatched = true
          result = @socket.write_nonblock(bytes.byteslice(offset, bytes.bytesize - offset), exception: false)
          if result == :wait_readable || result == :wait_writable
            @context.wait(@socket, result, also_read: watch_response)
          else
            raise IOError, 'Socket write stopped.' unless result.positive?
            offset += result
          end
        end
        nil
      rescue SystemCallError, IOError, OpenSSL::SSL::SSLError
        # A server can send a complete denial and close while the client writes.
        # Read its pending response before classifying a body-write failure.
        return :early_response if watch_response
        raise
      end

      def poll_response
        loop do
          @context.check!
          if (line_end = @buffer.index("\r\n"))
            status = parse_status(@buffer.byteslice(0, line_end))
            # Once a final status line is available, stop sending the body and
            # finish reading its bounded headers/body, even if they arrive slowly.
            return true if status >= 200
            if @buffer.include?("\r\n\r\n")
              read_head
              next
            end
          end
          Validation.bad('API response headers exceed the supported size.') if @buffer.bytesize > MAX_HEADER + 8192
          result = @socket.read_nonblock(16_384, exception: false)
          return false if result == :wait_readable || result == :wait_writable
          if result.nil?
            @eof = true
            return true
          end
          @buffer << result
        end
      end
      def read_chunk
        return nil if @eof
        loop do
          @context.check!
          result = @socket.read_nonblock(16_384, exception: false)
          if result == :wait_readable || result == :wait_writable
            @context.wait(@socket, result)
          else
            return result
          end
        end
      end
      def line(maximum = MAX_HEADER)
        loop do
          @context.check!
          if (index = @buffer.index("\r\n"))
            Validation.bad('API response headers exceed the supported size.') if index + 2 > maximum
            result = @buffer.slice!(0, index + 2)
            return result.byteslice(0, result.bytesize - 2)
          end
          Validation.bad('API response headers exceed the supported size.') if @buffer.bytesize >= maximum
          chunk = read_chunk
          raise EOFError, 'Truncated HTTP response.' if chunk.nil?
          @buffer << chunk
        end
      end
      def exact(length)
        while @buffer.bytesize < length
          chunk = read_chunk
          raise EOFError, 'Truncated HTTP response.' if chunk.nil?
          @buffer << chunk
        end
        @buffer.slice!(0, length)
      end
      def headers(track_response: false)
        result = Hash.new { |h, k| h[k] = [] }
        consumed = 0
        loop do
          row = line(MAX_HEADER - consumed)
          consumed += row.bytesize + 2
          break if row.empty?
          name, value = row.split(':', 2)
          Validation.bad('Malformed HTTP response headers.') unless name && TOKEN.match?(name) && value && !/[\x00-\x08\x0a-\x1f\x7f]/.match?(value)
          result[name.downcase] << value.strip
          @context.retry_after_ms = Transport.retry_after(result, nil) if track_response && name.downcase == 'retry-after'
        end
        result
      end
      def parse_status(status_line)
        Validation.bad('API response status exceeds the supported size.') if status_line.bytesize + 2 > 8192
        match = /\AHTTP\/1\.[01] ([1-5][0-9]{2})(?: [\x20-\x7e\t]*)?\z/.match(status_line)
        Validation.bad('Malformed HTTP response status.') unless match
        match[1].to_i
      end
      def read_head
        status = parse_status(line(8192))
        @context.status = status if status >= 200
        head = headers(track_response: status >= 200)
        if status < 200
          @informational += 1
          Validation.bad('Unsupported HTTP protocol upgrade or informational response.') if status == 101 || @informational > 5 || head.key?('content-length') || head.key?('transfer-encoding')
        end
        [status, head]
      end
      def response
        loop do
          status, head = read_head
          if status < 200
            next
          end
          @context.retry_after_ms = Transport.retry_after(head, nil)
          return [status, head, body(status, head)]
        end
      end
      def body(status, head)
        encodings = head.fetch('content-encoding', []).flat_map { |value| value.split(',', -1) }
        Validation.bad('API response uses an unsupported content encoding.') if encodings.any? { |value| value.strip.downcase != 'identity' }
        lengths = head.fetch('content-length', [])
        transfers = head.fetch('transfer-encoding', []).flat_map { |value| value.split(',', -1).map { |v| v.strip.downcase } }
        Validation.bad('Ambiguous HTTP response framing.') if lengths.size > 1 || (!lengths.empty? && !transfers.empty?)
        Validation.bad('Unsupported HTTP transfer encoding.') unless transfers.empty? || transfers == ['chunked']
        length = nil
        unless lengths.empty?
          Validation.bad('Invalid response Content-Length.') unless /\A[0-9]+\z/.match?(lengths.first)
          length = lengths.first.to_i
          Validation.bad('API response exceeds the supported size.') if length > MAX_BODY
        end
        return ''.b if status == 204 || status == 304
        return exact(length) if length
        output = ''.b
        if transfers == ['chunked']
          loop do
            chunk_line = line(8192)
            match = /\A([0-9a-fA-F]+)(?:;[\x20-\x7e\t]*)?\z/.match(chunk_line)
            Validation.bad('Invalid chunked response.') unless match
            size = match[1].to_i(16)
            if size.zero?
              trailers = headers
              Validation.bad('Invalid response trailers.') if %w[content-length transfer-encoding content-encoding host].any? { |name| trailers.key?(name) }
              break
            end
            Validation.bad('API response exceeds the supported size.') if size > MAX_BODY - output.bytesize
            output << exact(size)
            Validation.bad('Invalid chunked response.') unless exact(2) == "\r\n"
          end
        else
          output << @buffer
          @buffer = ''.b
          loop do
            Validation.bad('API response exceeds the supported size.') if output.bytesize > MAX_BODY
            chunk = read_chunk
            break if chunk.nil?
            Validation.bad('API response exceeds the supported size.') if chunk.bytesize > MAX_BODY - output.bytesize
            output << chunk
          end
        end
        output
      end
    end

    class Transport
      attr_reader :api_base_url, :upload_base_url, :request_timeout

      def initialize(api_key:, api_base_url: 'https://kompressr.com', upload_base_url: nil,
                     request_timeout: 30, upload_timeout: 600, max_read_retries: 2)
        Validation.invalid('Supply a nonempty ASCII API key on your trusted backend.') unless api_key.instance_of?(String) && api_key.ascii_only? && !api_key.strip.empty? && /\A[\x20-\x7e]+\z/.match?(api_key)
        @key = api_key.dup.freeze
        @api_base_url = Validation.origin(api_base_url)
        @upload_base_url = Validation.origin(upload_base_url.nil? ? (@api_base_url == 'https://kompressr.com' ? 'https://uploads.kompressr.com' : @api_base_url) : upload_base_url)
        @request_timeout = Validation.seconds(request_timeout, 'request_timeout')
        @upload_timeout = Validation.seconds(upload_timeout, 'upload_timeout')
        Validation.invalid('max_read_retries must be an integer from zero to five.') unless max_read_retries.instance_of?(Integer) && max_read_retries.between?(0, 5)
        @retries = max_read_retries
      end
      def inspect = '#<Kompressr::Internal::Transport credentials redacted>'
      alias to_s inspect

      def self.retry_after(headers, parsed)
        value = headers.fetch('retry-after', []).first
        if value
          if /\A[0-9]+(?:\.[0-9]+)?\z/.match?(value)
            return [value.to_f, Float::MAX / 1000].min * 1000
          end
          begin
            return [0, (Time.httpdate(value) - Time.now) * 1000].max
          rescue ArgumentError
            # An invalid header allows the documented JSON fallback.
          end
        end
        value = parsed['retry_after'] if parsed.instance_of?(Hash)
        return unless Validation.finite?(value) && value >= 0
        [value.to_f, Float::MAX / 1000].min * 1000
      end

      def safe_message(value)
        return 'Kompressr request failed.' unless value.instance_of?(String)
        result = value.gsub(@key, '[redacted]').gsub(/Bearer\s+\S+/i, 'Bearer [redacted]')
        result = result.gsub(%r{https?://[^\s<>"']+}i, '[URL redacted]')
        result = result.gsub(/\b(?:api_key|password|token|secret|signature)\s*[=:]\s*\S+/i, '[credential redacted]')
        result.gsub(/[\x00-\x1f\x7f]/, ' ')[0, 500]
      end

      def request(path, method: 'GET', body: nil, multipart: nil, upload: false, timeout: nil, cancel: nil,
                  asset_id: nil, recover_upload_id: false, &parse)
        Validation.invalid('cancel must be a CancellationToken.') unless cancel.nil? || cancel.instance_of?(CancellationToken)
        budget = Validation.seconds(timeout.nil? ? (upload ? @upload_timeout : @request_timeout) : timeout)
        payload = multipart || (body.nil? ? nil : Body.new(JSON.generate(body)))
        context = Context.new(budget, cancel, method != 'GET', asset_id)
        uri = URI.parse(upload ? @upload_base_url : @api_base_url)
        attempt = 0
        loop do
          context.check!
          context.status = nil
          context.retry_after_ms = nil
          begin
            parsed = nil
            status = nil
            Capacity.acquire(:connection, context)
            begin
              socket = Network.connect(uri, context)
              wire = Wire.new(socket, context)
              host = uri.host + (uri.port == (uri.scheme == 'https' ? 443 : 80) ? '' : ":#{uri.port}")
              headers = "#{method} #{path} HTTP/1.1\r\nHost: #{host}\r\nAuthorization: Bearer #{@key}\r\nAccept: application/json\r\nAccept-Encoding: identity\r\nConnection: close\r\nUser-Agent: kompressr-ruby/#{VERSION}\r\n"
              headers << "Content-Type: #{payload.content_type}\r\n" if payload
              headers << "Content-Length: #{payload ? payload.length : 0}\r\n" if payload || method != 'GET'
              wire.write(headers + "\r\n")
              payload&.each do |chunk|
                context.check!
                break if wire.write(chunk, watch_response: true) == :early_response
              end
              begin
                status, head, raw = wire.response
                raw.force_encoding(Encoding::UTF_8)
                Validation.bad('API returned invalid UTF-8 JSON.') unless raw.valid_encoding?
                parsed = JSON.parse(raw, max_nesting: 100, allow_nan: false)
                Validation.bad('API returned invalid Unicode JSON.') unless Validation.valid_json_strings?(parsed)
              rescue JSON::ParserError, EncodingError
                parsed = nil
                Validation.bad('API returned a non-JSON response.') if context.status && context.status.between?(200, 299)
              rescue Error => error
                raise unless error.kind == 'invalid_response' && context.status && !context.status.between?(200, 299)
                parsed = nil
              end
              status = context.status
              Validation.bad unless status
              context.retry_after_ms = self.class.retry_after(head, parsed) if head
              context.check!
              if recover_upload_id && status.between?(200, 299) && parsed.instance_of?(Hash) && parsed['success'] == true && parsed['data'].instance_of?(Hash)
                candidate = parsed['data']['asset_id']
                context.asset_id = candidate.to_i if Validation.finite?(candidate) && candidate.positive? && candidate <= Validation::MAX_SAFE && candidate == candidate.to_i
              end
              failed = parsed.instance_of?(Hash) && parsed['success'] == false
              unless status.between?(200, 299) && !failed
                data = parsed.instance_of?(Hash) ? parsed : {}
                code = data['code']
                code = 'API_ERROR' unless code.instance_of?(String) && /\A[A-Z][A-Z0-9_]{0,99}\z/.match?(code) && !code.include?(@key)
                raise Error.new(safe_message(data['error'] || "Kompressr returned HTTP #{status}."), kind: 'api', code: code,
                                status: status, retry_after_ms: context.retry_after_ms, asset_id: context.asset_id,
                                may_have_succeeded: method != 'GET' && (status < 400 || status >= 500)), cause: nil
              end
              result = parse.call(parsed)
              context.check!
              return result
            ensure
              socket.close if socket && !socket.closed?
              Capacity.release(:connection)
            end
          rescue Error, SystemCallError, IOError, SocketError, OpenSSL::SSL::SSLError, PhaseTimeout => error
            failure = if error.instance_of?(Error)
                        error
                      else
                        context.check!
                        context.error('network')
                      end
            if failure.kind == 'invalid_response'
              failure = Error.new(failure.message, kind: failure.kind, code: failure.code, status: context.status,
                                  retry_after_ms: context.retry_after_ms, asset_id: context.asset_id,
                                  may_have_succeeded: method != 'GET' && context.dispatched)
            end
            transient = failure.kind == 'network' || (failure.kind == 'api' && [429, 502, 503, 504].include?(failure.status))
            raise failure, cause: nil unless method == 'GET' && transient && attempt < @retries
            context.pause([0.25 * (2**attempt) + rand * 0.1, (failure.retry_after_ms || 0) / 1000].max)
            attempt += 1
          end
        end
      end
    end
  end
end
