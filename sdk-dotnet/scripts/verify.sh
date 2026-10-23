#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
KOMPRESSR_PACKAGE_ROOT=$(pwd)
KOMPRESSR_TEST_FRAMEWORK=${KOMPRESSR_TEST_FRAMEWORK:-net8.0}
case "$KOMPRESSR_TEST_FRAMEWORK" in
  net8.0|net10.0) ;;
  *) printf '%s\n' 'KOMPRESSR_TEST_FRAMEWORK must be net8.0 or net10.0.' >&2; exit 1 ;;
esac
if [ -f ../contracts/fixtures/file-lifecycle.json ]; then
  cmp ../contracts/fixtures/file-lifecycle.json tests/Kompressr.Sdk.Tests/fixtures/file-lifecycle.json
fi
dotnet build src/Kompressr.Sdk/Kompressr.Sdk.csproj --configuration Release
dotnet run --project tests/Kompressr.Sdk.Tests --configuration Release -p:KompressrTestFramework="$KOMPRESSR_TEST_FRAMEWORK"
dotnet build examples/Kompressr.Examples.csproj --configuration Release -p:KompressrTestFramework="$KOMPRESSR_TEST_FRAMEWORK"
KOMPRESSR_VERSION=$(dotnet msbuild src/Kompressr.Sdk/Kompressr.Sdk.csproj -getProperty:Version)
printf '%s\n' "$KOMPRESSR_VERSION" | LC_ALL=C grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || exit 1
mkdir -p artifacts
dotnet pack src/Kompressr.Sdk/Kompressr.Sdk.csproj --configuration Release --no-build --output artifacts
KOMPRESSR_CONSUMER=$(mktemp -d)
trap 'rm -rf "$KOMPRESSR_CONSUMER"' EXIT HUP INT TERM
mkdir -p "$KOMPRESSR_CONSUMER/tests/fixtures" "$KOMPRESSR_CONSUMER/examples" "$KOMPRESSR_CONSUMER/feed"
cp artifacts/Kompressr.Sdk.$KOMPRESSR_VERSION.nupkg "$KOMPRESSR_CONSUMER/feed/"
cp tests/Kompressr.Sdk.Tests/*.cs "$KOMPRESSR_CONSUMER/tests/"
cp tests/Kompressr.Sdk.Tests/fixtures/file-lifecycle.json "$KOMPRESSR_CONSUMER/tests/fixtures/"
cp examples/Program.cs "$KOMPRESSR_CONSUMER/examples/"
for KOMPRESSR_PROJECT in tests examples; do
  cat > "$KOMPRESSR_CONSUMER/$KOMPRESSR_PROJECT/Consumer.csproj" <<XML
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType><TargetFramework>$KOMPRESSR_TEST_FRAMEWORK</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable><TreatWarningsAsErrors>true</TreatWarningsAsErrors>
  </PropertyGroup>
  <ItemGroup><PackageReference Include="Kompressr.Sdk" Version="$KOMPRESSR_VERSION" /></ItemGroup>
  <ItemGroup><None Include="fixtures/file-lifecycle.json" CopyToOutputDirectory="PreserveNewest" Condition="Exists('fixtures/file-lifecycle.json')" /></ItemGroup>
</Project>
XML
  dotnet restore "$KOMPRESSR_CONSUMER/$KOMPRESSR_PROJECT/Consumer.csproj" --source "$KOMPRESSR_CONSUMER/feed" --packages "$KOMPRESSR_CONSUMER/packages" -p:NuGetAudit=false
  dotnet build "$KOMPRESSR_CONSUMER/$KOMPRESSR_PROJECT/Consumer.csproj" --configuration Release --no-restore
 done
dotnet run --project "$KOMPRESSR_CONSUMER/tests/Consumer.csproj" --configuration Release --no-build --no-restore
printf '%s\n' "Verified source and isolated NuGet consumer; package: artifacts/Kompressr.Sdk.$KOMPRESSR_VERSION.nupkg"
