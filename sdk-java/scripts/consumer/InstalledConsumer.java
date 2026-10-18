import com.kompressr.*;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.io.OutputStream;
import java.util.concurrent.atomic.AtomicInteger;

/** Compiled in a clean project against the installed JAR, with a small heap. */
public class InstalledConsumer {
    public static void main(String[] args) throws Exception {
        AtomicInteger writes = new AtomicInteger();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", x -> {
            boolean upload = x.getRequestMethod().equals("POST");
            long bytes = x.getRequestBody().transferTo(OutputStream.nullOutputStream());
            if (upload && bytes < 32 * 1024 * 1024) throw new AssertionError("File was truncated");
            if (upload) writes.incrementAndGet();
            String asset = "\"status\":\"processed\",\"visibility\":\"public\",\"deletion_status\":\"active\",\"original_name\":\"fixture.png\",\"original_size\":33554432,\"asset_type\":\"image\",\"cdn_url\":\"https://cdn.example/ready.webp\"";
            String data = upload ? "{\"asset_id\":42," + asset + "}" : "{\"id\":42," + asset + ",\"kompressd_size\":1024,\"savings_percent\":99,\"can_generate_private_url\":false}";
            byte[] response = ("{\"success\":true,\"data\":" + data + "}").getBytes(StandardCharsets.UTF_8);
            x.sendResponseHeaders(200, response.length); try (var out = x.getResponseBody()) { out.write(response); }
        });
        server.start(); Path file = Files.createTempFile("sdk-consumer", ".png");
        try {
            try (var out = Files.newOutputStream(file)) { byte[] block = new byte[8192]; for (int i = 0; i < 4096; i++) out.write(block); }
            try (var client = KompressrClient.builder("fixture-only").apiBaseUrl("http://127.0.0.1:" + server.getAddress().getPort()).build()) {
                var accepted = client.uploadFile(file, Options.Upload.publicFile());
                if (accepted.id() != 42 || writes.get() != 1) throw new AssertionError("Acceptance mismatch");
                if (!client.waitUntilReady(accepted.id()).cdnUrl().equals("https://cdn.example/ready.webp")) throw new AssertionError("Readiness mismatch");
                if (!KompressrClient.class.getProtectionDomain().getCodeSource().getLocation().toString().endsWith(".jar")) throw new AssertionError("Not installed from JAR");
            }
            System.out.println("Installed JAR consumer passed; streamed 32 MiB with a 64 MiB heap.");
        } finally { server.stop(0); Files.deleteIfExists(file); }
    }
}
