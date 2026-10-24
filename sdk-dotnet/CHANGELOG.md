# Changelog

## 0.1.1

- Update the packaged contributor guide to describe automatic version detection in the verifier.
- Verify NuGet packages and installed consumers using the declared project version.

## 0.1.0

Initial async .NET SDK for file uploads, delivery, asset lifecycle and platform identity/key administration.

Reject explicit empty key-scope collections before dispatch, preventing accidental use of server default permissions. Omitted or null scopes still use defaults; nonempty selections are preserved.
