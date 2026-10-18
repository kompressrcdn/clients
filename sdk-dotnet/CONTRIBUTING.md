# Contributing to the .NET SDK

Use the .NET 8 SDK for the minimum target, or the .NET 10 SDK with `KOMPRESSR_TEST_FRAMEWORK=net10.0`. From this directory, run `sh scripts/verify.sh`.

The verifier uses only the .NET SDK and ordinary shell tools. It builds the library with warnings as errors, runs the real HTTP console test harness, compiles examples and packs a NuGet archive. It then installs that archive into a temporary, isolated consumer and repeats the HTTP suite. `dotnet run --project tests/Kompressr.Sdk.Tests --configuration Release` runs source tests alone; this dependency-free harness exits nonzero on a failed assertion and prints its runtime version.

Add regressions at actual HTTP boundaries for behavior changes. Keep mutation ambiguity, bounded waits, safe secrets, per-item bulk results and cancellation intact. Do not substitute mocked handlers for transport replay/deadline tests. The 32 MiB file test checks bounded managed allocation while a server drains the body; do not buffer that fixture at either end.

Keep API documentation, examples and publishing metadata aligned with shipped behavior. The package version and verifier's exact package references must be updated together. Build outputs belong in ignored `bin`, `obj` and `artifacts` directories. Run the repository's public-content and distribution guards before release. No live account is required for local verification.
