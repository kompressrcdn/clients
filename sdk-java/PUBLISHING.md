# Publishing the Java SDK

Publish `com.kompressr:kompressr-sdk` to Maven Central. Java releases are independent of the other SDKs. Use JDK 17+ and Maven 3.9+.

## One-time account setup

1. Register a [Central Portal account](https://central.sonatype.org/register/central-portal/).
2. Add and verify the `com.kompressr` namespace using ownership of `kompressr.com`, following [namespace verification](https://central.sonatype.org/register/namespace/). Give the publishing account access to that namespace.
3. Prepare a GPG signing key and publish its public key according to [Central's signing requirements](https://central.sonatype.org/publish/requirements/gpg/). Keep private key material outside the repository.
4. Generate a Portal token. Store its username and password in the `central` server entry of your private Maven settings file. See the [official Maven publisher guide](https://central.sonatype.org/publish/publish-portal-maven/). Never put a token in the POM, command arguments, examples or committed files.

The Maven server ID must be `central`, matching the release profile in `pom.xml`. Add this server entry inside `<servers>` in your private `~/.m2/settings.xml`, preserving any existing settings:

```xml
<server>
  <id>central</id>
  <username>${env.KOMPRESSR_CENTRAL_USERNAME}</username>
  <password>${env.KOMPRESSR_CENTRAL_PASSWORD}</password>
</server>
```

Supply the Portal-generated token username and password through your private environment. These are token credentials, not your web login. Check `gpg --list-secret-keys --keyid-format LONG`; if you have multiple signing keys, select the release key with Maven's `-Dgpg.keyname=KEY_FINGERPRINT`. Confirm its public key is discoverable as required by Central.

## Prepare a version

From `sdk-java/`, choose an unused version, update `pom.xml`, the consumer POM, examples and changelog together, then run on JDK 17 and 21:

```sh
./scripts/verify.sh
```

The verifier builds `target/kompressr-sdk-0.1.0.jar`, `target/kompressr-sdk-0.1.0-sources.jar` and `target/kompressr-sdk-0.1.0-javadoc.jar`, installs them locally, and uses the installed main JAR in a fresh consumer. Inspect every archive entry and its contents for unexpected credentials, fixtures, private paths and unwanted files. The main JAR should contain SDK classes, MIT license and Maven metadata. Source/Javadoc JARs contain the corresponding public source/reference. Confirm the prepared revision and complete the dedicated-project live lifecycle/permission checks before release.

## Sign, upload and publish

With your GPG agent and private Maven settings configured:

```sh
mvn -Prelease clean deploy
```

This invokes the opt-in release profile, generates signatures and uploads a bundle to the Central Portal. `autoPublish` is false: inspect validation results and artifacts in the Portal, then explicitly publish there when approved. The release profile is not used by ordinary builds or `scripts/verify.sh`. Version contents cannot be overwritten after publication. Recheck the [current publisher documentation](https://central.sonatype.org/publish/publish-portal-maven/) before releasing if Portal requirements change.

## Verify the published package

Use a new local Maven repository so a previously installed candidate cannot mask a missing public release:

```sh
release_check=$(mktemp -d)
mvn -Dmaven.repo.local="$release_check" org.apache.maven.plugins:maven-dependency-plugin:3.8.1:get -Dartifact=com.kompressr:kompressr-sdk:0.1.0 -Dtransitive=true
```

Compare the downloaded JAR's SHA-256 with the approved release artifact. Create a fresh application using the published dependency and run the public/private upload examples with a dedicated test project. Verify readiness, fresh signing, denied sibling-user access, expiry, opt-in deletion and cleanup. Keep credentials out of output; retain asset IDs for cleanup.
