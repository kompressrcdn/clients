# Publish the .NET SDK

Publish the `Kompressr.Sdk` package to NuGet.org. Create a [NuGet account](https://www.nuget.org/users/account/LogOn), then create an API key with permission to push this package. For the first release, select the scope that allows **new packages and versions**, with the package glob `Kompressr.Sdk`. For later releases, the publishing account must be an owner.

You can instead use NuGet.org's **Upload** page to upload the verified `.nupkg`, preview its README and metadata, then select **Submit**. This avoids putting an API key in a CLI argument. See the [official publishing guide](https://learn.microsoft.com/en-us/nuget/nuget-org/publish-a-package).

Run the following steps from `sdk-dotnet/` unless otherwise stated. Verification never publishes automatically.

1. Review the source and changelog, select the release version in `src/Kompressr.Sdk/Kompressr.Sdk.csproj`, and update the exact version references in `scripts/verify.sh` and these commands together.
2. Run `sh scripts/verify.sh` with .NET 8. Run `KOMPRESSR_TEST_FRAMEWORK=net10.0 sh scripts/verify.sh` with .NET 10. Both must build, run HTTP regressions and install the archive into the isolated consumer.
3. From the repository root, run the source and archive guards:

   ```sh
   node scripts/check-public-content.mjs
   node scripts/check-distribution.mjs sdk-dotnet/artifacts/Kompressr.Sdk.0.1.0.nupkg
   ```

4. Inspect the `.nupkg` contents and its dependency metadata. It should contain the net8.0 DLL, package metadata and public documentation. It contains no runtime package dependencies, credentials or machine-specific paths. Record the archive's SHA-256 outside the source tree with your release evidence.
5. For CLI publishing, store the API key in your shell's private environment as `KOMPRESSR_NUGET_API_KEY`. Run from the **repository root**. The key is expanded into the CLI argument, so use a trusted machine and disable shell tracing. Publish the already verified file:

   ```sh
   dotnet nuget push sdk-dotnet/artifacts/Kompressr.Sdk.0.1.0.nupkg \
     --source https://api.nuget.org/v3/index.json \
     --api-key "$KOMPRESSR_NUGET_API_KEY"
   ```

6. Once NuGet indexing completes, create a clean application and install that exact version from the public registry. Run the public/private upload, saved-ID resume and scoped-denial checks with a dedicated test project. Inspect and delete the explicit test assets. Do not infer deployed permissions from loopback fixtures.
7. From a new temporary directory, verify public installation using a fresh package cache:

   ```sh
   dotnet new console --name ReleaseCheck --framework net8.0
   cd ReleaseCheck
   export NUGET_PACKAGES="$PWD/.packages"
   dotnet add package Kompressr.Sdk --version 0.1.0 --source https://api.nuget.org/v3/index.json
   dotnet build
   ```

   Inspect the restored package's ID, version and contents. NuGet repository signing can change the archive's bytes, so compare payload files rather than expecting the original upload hash to remain identical. Keep the pre-upload digest for the release record. A source tag, if used, should identify this package's exact release revision.

NuGet publication is separate from committing source or building an archive. A published version cannot be overwritten with different contents; fix issues in a new version. No publish step runs in this package's verifier or CI.
