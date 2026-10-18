using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;

internal sealed record Request(string Method, string Path, Dictionary<string, string> Headers, byte[] Body, long BodyLength, int ConnectionId);
internal sealed class Reply
{
    internal int Status { get; init; } = 200;
    internal string Body { get; init; } = "{}";
    internal Dictionary<string, string> Headers { get; init; } = new(StringComparer.OrdinalIgnoreCase);
    internal TimeSpan BeforeHeaders { get; init; }
    internal TimeSpan BeforeBody { get; init; }
    internal bool Disconnect { get; init; }
    internal bool Truncate { get; init; }
    internal static Reply Json(object value, int status = 200) => new() { Body = JsonSerializer.Serialize(value), Status = status };
}
internal sealed class FixtureServer : IAsyncDisposable
{
    private readonly TcpListener listener = new(IPAddress.Loopback, 0);
    private readonly CancellationTokenSource stop = new();
    private readonly Task accept;
    private readonly ConcurrentBag<Task> workers = [];
    private readonly Func<Request, Reply> handler;
    private int connections;
    internal ConcurrentQueue<Request> Requests { get; } = new();
    internal string Url { get; }
    internal bool DrainOnly { get; init; }
    internal int Connections => connections;
    internal FixtureServer(Func<Request, Reply> handler)
    {
        this.handler = handler;
        listener.Start();
        Url = "http://127.0.0.1:" + ((IPEndPoint)listener.LocalEndpoint).Port;
        accept = AcceptAsync();
    }
    private async Task AcceptAsync()
    {
        try
        {
            while (!stop.IsCancellationRequested)
            {
                var client = await listener.AcceptTcpClientAsync(stop.Token);
                int id = Interlocked.Increment(ref connections);
                workers.Add(HandleAsync(client, id));
            }
        }
        catch (OperationCanceledException) { }
        catch (SocketException) when (stop.IsCancellationRequested) { }
    }
    private async Task HandleAsync(TcpClient client, int connectionId)
    {
        using (client)
        {
            try
            {
                var stream = client.GetStream();
                using var header = new MemoryStream();
                byte[] one = new byte[1];
                int state = 0;
                while (state != 4)
                {
                    if (await stream.ReadAsync(one, stop.Token) == 0) return;
                    header.WriteByte(one[0]);
                    if (header.Length > 32 * 1024) throw new Exception("Oversized request headers.");
                    state = (state, one[0]) switch { (0, 13) => 1, (1, 10) => 2, (2, 13) => 3, (3, 10) => 4, (_, 13) => 1, _ => 0 };
                }
                string[] lines = Encoding.ASCII.GetString(header.ToArray()).Split("\r\n");
                string[] first = lines[0].Split(' ');
                Dictionary<string, string> headers = new(StringComparer.OrdinalIgnoreCase);
                foreach (string line in lines.Skip(1).Where(line => line.Contains(':')))
                {
                    int colon = line.IndexOf(':');
                    headers[line[..colon]] = line[(colon + 1)..].Trim();
                }
                if (headers.ContainsKey("Transfer-Encoding")) throw new Exception("Multipart must have Content-Length.");
                long length = headers.TryGetValue("Content-Length", out var size) ? long.Parse(size, System.Globalization.CultureInfo.InvariantCulture) : 0;
                using var body = new MemoryStream();
                byte[] buffer = new byte[64 * 1024];
                long remaining = length;
                while (remaining > 0)
                {
                    int count = await stream.ReadAsync(buffer.AsMemory(0, (int)Math.Min(remaining, buffer.Length)), stop.Token);
                    if (count == 0) return;
                    if (!DrainOnly) body.Write(buffer, 0, count);
                    else if (body.Length < 4096) body.Write(buffer, 0, (int)Math.Min(count, 4096 - body.Length));
                    remaining -= count;
                }
                var request = new Request(first[0], first[1], headers, body.ToArray(), length, connectionId);
                Requests.Enqueue(request);
                Reply reply = handler(request);
                if (reply.Disconnect) return;
                if (reply.BeforeHeaders > TimeSpan.Zero) await Task.Delay(reply.BeforeHeaders, stop.Token);
                byte[] payload = Encoding.UTF8.GetBytes(reply.Body);
                var text = new StringBuilder($"HTTP/1.1 {reply.Status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {payload.Length}\r\nConnection: close\r\n");
                foreach (var (name, value) in reply.Headers) text.Append(name).Append(": ").Append(value).Append("\r\n");
                text.Append("\r\n");
                await stream.WriteAsync(Encoding.ASCII.GetBytes(text.ToString()), stop.Token);
                if (reply.BeforeBody > TimeSpan.Zero) await Task.Delay(reply.BeforeBody, stop.Token);
                await stream.WriteAsync(reply.Truncate ? payload.AsMemory(0, Math.Max(1, payload.Length / 2)) : payload, stop.Token);
            }
            catch (Exception error) when (error is OperationCanceledException or IOException or SocketException) { }
        }
    }
    public async ValueTask DisposeAsync()
    {
        stop.Cancel(); listener.Stop();
        await accept;
        await Task.WhenAll(workers);
        stop.Dispose();
    }
}
