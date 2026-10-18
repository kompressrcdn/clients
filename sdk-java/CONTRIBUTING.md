# Contributing to the Java SDK

Use JDK 17 or 21 and Maven 3.9+. From this directory, run `./scripts/verify.sh`. Additional Maven flags, such as `-Dmaven.repo.local=/path/to/cache`, are forwarded to both package and clean-consumer builds. `mvn test` runs the HTTP fixture tests alone. The full verifier builds source/Javadoc artifacts and checks the installed JAR independently of source compilation.

Keep HTTP fixtures synthetic and local. `src/test/resources/file-lifecycle.json` mirrors the shared repository fixture; its consistency test rejects drift when the checkout includes `contracts/`. Changes to wire behavior must stay aligned with the shared contract and [parity matrix](PARITY.md). Tests should establish observable requests, errors, cancellation and actual package consumption.

Runtime HTTP behavior uses [Apache HttpClient](https://hc.apache.org/httpcomponents-client-5.6.x/current/httpclient5/apidocs/org/apache/hc/client5/http/impl/classic/HttpClientBuilder.html), with its automatic retries/redirects disabled. JSON handling uses the maintained [Jackson 2.21 LTS line](https://github.com/FasterXML/jackson/wiki/Jackson-Release-2.21). Upgrade dependencies deliberately and run the complete verifier after transport or serialization changes. Do not enable polymorphic JSON deserialization or include raw exception causes containing response bodies/credentials.

Public credentials, links and one-time keys must not appear in errors or record `toString()` output. Application debug-level HTTP logging is controlled by the host application's logging configuration. SDK source, tests, examples, JARs and release notes must be suitable for public distribution. Publishing requires maintainer authorization and the steps in [PUBLISHING.md](PUBLISHING.md).
