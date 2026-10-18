import com.kompressr.*;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.List;

/** Local administration example. The output directory must already be private to your account. */
public class ScopedKeys {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("Usage: ScopedKeys <stable-customer-id> <new-key-file>");
        Path keyFile = Path.of(args[1]);
        // Reserve a private destination before issuing a one-time secret. This example requires POSIX permissions.
        Files.createFile(keyFile, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        try (var client = KompressrClient.builder(System.getenv("KOMPRESSR_API_KEY")).build()) {
            var user = client.platform().createUser(new Options.CreateUser(args[0], null, null)).projectUser();
            var issued = client.platform().createUploadKey(user.id(), new Options.CreateKey("Chat runtime", List.of("upload", "status", "list", "private_url"), "private", null, null));
            try { Files.writeString(keyFile, issued.apiKey()); }
            catch (java.io.IOException failure) {
                System.err.println("Key was issued. Revoke key record " + issued.id() + " for user " + user.id() + " before issuing a replacement.");
                throw failure;
            }
            System.out.println("Saved scoped key for user " + user.id() + ". Key record: " + issued.id());
        }
    }
}
