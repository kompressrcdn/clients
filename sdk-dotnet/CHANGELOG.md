# Changelog

## 0.1.0

Initial async .NET SDK for file uploads, delivery, asset lifecycle and platform identity/key administration.

Reject explicit empty key-scope collections before dispatch, preventing accidental use of server default permissions. Omitted or null scopes still use defaults; nonempty selections are preserved.
