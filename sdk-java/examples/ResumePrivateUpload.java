import com.kompressr.*;

public class ResumePrivateUpload {
    public static void main(String[] args) {
        if (args.length != 1) throw new IllegalArgumentException("Usage: ResumePrivateUpload <saved-asset-id>");
        long id = Long.parseLong(args[0]);
        try (var files = KompressrClient.builder(System.getenv("KOMPRESSR_API_KEY")).build()) {
            files.waitUntilReady(id);
            System.out.println(files.generatePrivateUrl(id).privateUrl());
        }
    }
}
