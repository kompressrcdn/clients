# Kompressr Java SDK

Upload, optimize and deliver files from Java backends. Requires Java 17 or later. Use the client in plain Java, Spring applications or background jobs; no framework adapter is required.

## Install

Add this dependency to your Maven application's `pom.xml`:

```xml
<dependency>
  <groupId>com.kompressr</groupId>
  <artifactId>kompressr-sdk</artifactId>
  <version>0.1.0</version>
</dependency>
```

Create a project in the [Kompressr dashboard](https://kompressr.com/dashboard/projects), copy its API key into your backend's `KOMPRESSR_API_KEY` environment variable, and select a plan with API uploads. Check the [current plan comparison](https://kompressr.com/pricing#file-support) for formats and scoped-key access. Keep project credentials out of browser/mobile applications and source control.

## Your first upload

```java
import com.kompressr.*;
import java.nio.file.*;

try (var files = KompressrClient.builder(System.getenv("KOMPRESSR_API_KEY")).build()) {
    var accepted = files.uploadFile(Path.of("image.png"), Options.Upload.publicFile());
    // Save this ID in your application's database before waiting.
    long assetId = accepted.id();
    var ready = files.waitUntilReady(assetId);
    System.out.println(ready.cdnUrl());
}
```

An upload response means the file was accepted. `waitUntilReady` checks processing before returning a public delivery URL or a private file ready for signing. For a long-running application, reuse one client and close it on shutdown. Calls block the calling thread; use your application's executor when integrating into asynchronous code.

## Private files and recovery

Use `Options.Upload.privateFile()`, save the accepted ID, wait for readiness, then call `generatePrivateUrl(id)`. A private link grants temporary access: return it only after your application checks the requesting user's access, and keep it out of logs. Expired links can be replaced without reuploading.

The runnable [private-upload example](https://github.com/kompressrcdn/clients/blob/main/sdk-java/examples/PrivateUpload.java) saves a receipt before waiting. To run the repository examples, clone the repository and run these commands from `sdk-java/`:

```sh
mvn package
mvn dependency:build-classpath -Dmdep.outputFile=target/runtime-classpath.txt -DincludeScope=runtime
java -cp "target/kompressr-sdk-0.1.0.jar:$(cat target/runtime-classpath.txt)" examples/PrivateUpload.java ./image.png ./new-upload-receipt.txt
```

The example intentionally prints the private link for local testing. If waiting times out, keep the receipt and resume with the saved ID:

```sh
java -cp "target/kompressr-sdk-0.1.0.jar:$(cat target/runtime-classpath.txt)" examples/ResumePrivateUpload.java 42
```

Replace `42` with your receipt's ID. No upload occurs during resume.

## Errors, deadlines and cancellation

```java
var cancel = new CancellationToken();
try {
    files.getUploadStatus(42, new Options.Request(java.time.Duration.ofSeconds(10), cancel));
} catch (KompressrException error) {
    System.err.println(error.details()); // Structured, sanitized fields.
    // Preserve error.assetId() when available. Investigate mayHaveSucceeded()
    // before deciding whether an interrupted write should be retried.
}
// Another thread may call cancel.cancel() to stop the request.
```

Every HTTP call has a finite total deadline, including response-body reads and read retries. Thread interruption also cancels active HTTP work and preserves the interrupt flag. `waitUntilReady` has its own total deadline and returns `WAIT_TIMEOUT` or `WAIT_CANCELLED` with the ID so checking can resume. Cancellation cannot undo a write accepted by the server.

Only eligible GET failures retry automatically. Uploads, signing, deletion and platform mutations are never automatically replayed. An interrupted or malformed successful write returns `mayHaveSucceeded=true`; safely recoverable upload IDs are retained. A missing ID is not proof that an upload failed. See [API.md](https://github.com/kompressrcdn/clients/blob/main/sdk-java/API.md) for exact limits and [PARITY.md](https://github.com/kompressrcdn/clients/blob/main/sdk-java/PARITY.md) for regression coverage.

## Scoped keys and platform administration

A regular project key can access the project's files and administer platform identities where the plan permits it. A scoped key is restricted to its identity, visibility and allowed actions; the API enforces these rules. The SDK never substitutes a more powerful credential. Scoped keys require a plan with that feature.

Use `files.platform()` with a project/master key to create a user, issue a scoped key, rotate/revoke keys, or suspend/reactivate users. [ScopedKeys.java](https://github.com/kompressrcdn/clients/blob/main/sdk-java/examples/ScopedKeys.java) creates a stable customer identity and writes a private-file key to a new, permission-restricted file for local testing. It explicitly omits delete permission. In production, store keys in your secret store and derive the customer identity from your authenticated session. A raw key is returned only once; retain its record ID for rotation/revocation.

## Build and verify

```sh
./scripts/verify.sh
```

This runs local HTTP fixtures, builds main/source/Javadoc JARs, installs the package locally, and compiles/runs a separate consumer against the installed JAR. The consumer uploads a 32 MiB file with a 64 MiB heap to verify file streaming. No live account is needed. JDK 17 and 21 are the CI targets. See [CONTRIBUTING.md](https://github.com/kompressrcdn/clients/blob/main/sdk-java/CONTRIBUTING.md) for development prerequisites.

Runtime dependencies are Apache HttpClient 5 and Jackson 2.21 LTS. HttpClient's automatic retries, redirects and cookies are disabled; the SDK controls retries and cancellation. HttpClient uses SLF4J: configure your application's normal logging provider if desired, and avoid enabling HTTP wire/header logging with real credentials.

See [changelog](https://github.com/kompressrcdn/clients/blob/main/sdk-java/CHANGELOG.md) and [MIT license](https://github.com/kompressrcdn/clients/blob/main/sdk-java/LICENSE).
