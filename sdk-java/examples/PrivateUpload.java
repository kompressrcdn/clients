import com.kompressr.*;
import java.nio.file.*;
import java.time.Duration;

/** Run with the SDK and its dependencies on the classpath. */
public class PrivateUpload {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("Usage: PrivateUpload <file> <new-receipt-path>");
        String key = System.getenv("KOMPRESSR_API_KEY");
        Path receipt = Path.of(args[1]);
        if (Files.exists(receipt)) throw new IllegalArgumentException("Choose a new receipt path.");
        try (var files = KompressrClient.builder(key).build()) {
            var accepted = files.uploadFile(Path.of(args[0]), Options.Upload.privateFile());
            // Save the accepted ID before waiting. Keep this receipt if waiting fails.
            try {
                Files.writeString(receipt, Long.toString(accepted.id()), StandardOpenOption.CREATE_NEW);
            } catch (java.io.IOException e) {
                System.err.println("Accepted asset ID: " + accepted.id() + "; save it before retrying anything.");
                throw e;
            }
            files.waitUntilReady(accepted.id(), new Options.Wait(Duration.ofMinutes(2), null, null));
            var link = files.generatePrivateUrl(accepted.id());
            // This example intentionally prints a secret link for local inspection.
            System.out.println(link.privateUrl());
        } catch (KompressrException e) {
            System.err.println(e.details());
            throw e;
        }
    }
}
