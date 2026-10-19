# Java

Java 17+. Works in plain Java, Spring applications and workers. Calls are blocking; use an appropriate application executor for asynchronous handlers.

Add to Maven dependencies:

```xml
<dependency>
  <groupId>com.kompressr</groupId>
  <artifactId>kompressr-sdk</artifactId>
  <version>0.1.0</version>
</dependency>
```

Gradle equivalent: `implementation("com.kompressr:kompressr-sdk:0.1.0")`.

Integration helper; the `saveAssetId` callback must commit the ID before returning:

```java
import com.kompressr.KompressrClient;
import com.kompressr.Options;
import java.io.IOException;
import java.nio.file.Path;
import java.util.function.LongConsumer;

public final class Attachments {
    public static String uploadPublic(KompressrClient files, Path path,
                                      LongConsumer saveAssetId) throws IOException {
        var accepted = files.uploadFile(path, Options.Upload.publicFile());
        saveAssetId.accept(accepted.id());
        return files.waitUntilReady(accepted.id()).cdnUrl();
    }
}
```

Create the client with `KompressrClient.builder(System.getenv("KOMPRESSR_API_KEY")).build()`. Reuse it in a service and close on shutdown; short CLI programs can use try-with-resources. [Executable examples](https://github.com/kompressrcdn/clients/tree/main/sdk-java/examples) and the [README](https://github.com/kompressrcdn/clients/blob/main/sdk-java/README.md) provide build/run commands and durable upload receipts.

## Methods and shapes

Use `Options.Upload.privateFile()` for private uploads; persist `accepted.id()`, wait and call `generatePrivateUrl(id)` after authorization. Results are typed records, not JavaScript dictionaries. Consult the [API reference](https://github.com/kompressrcdn/clients/blob/main/sdk-java/API.md) for record accessors and overloads.

File families: `uploadFile`, `uploadBytes`, `getUploadStatus`, `waitUntilReady`, `generatePrivateUrl`, `listUploads`, `iterateUploads`, `listAssets`, `getAsset`, `deleteAsset`, `bulkDeleteAssets`. Platform administration is under `files.platform()` and requires project authority.

## Application details

- Durations use `java.time.Duration`. Requests can take `Options.Request` and a `CancellationToken`; another thread can cancel it. Interrupted threads keep their interruption state.
- Catch `KompressrException`; retain `assetId()`, `mayHaveSucceeded()` and safe error details. A timeout after dispatch is not proof of no mutation.
- Upload a regular local `Path` or documented byte input. Adapt Spring multipart wrappers; do not assume arbitrary `InputStream` support.
- Keep long processing off a request thread when the application cannot wait. Resume saved IDs in a job.
- Runtime dependencies include the package's declared HTTP/JSON libraries. Do not enable HTTP header/wire logging with real credentials.

[Full API](https://github.com/kompressrcdn/clients/blob/main/sdk-java/API.md) · [Guide](https://github.com/kompressrcdn/clients/blob/main/sdk-java/README.md)
