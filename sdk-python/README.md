# Kompressr for Python

Upload and manage files from Python backends, scripts and asyncio applications. Requires Python 3.11 or later.

## Install

```sh
python -m pip install kompressr-sdk
```

Use `KompressrClient` for synchronous applications, including Django views and background workers. Use `AsyncKompressrClient` in FastAPI async handlers or Django async views. No framework adapter is required.

## Upload a file

Create a Kompressr project and put its API key in your server's `KOMPRESSR_API_KEY` environment variable. Keep project credentials on your backend. API uploads and file types depend on your [plan](https://kompressr.com/pricing).

```python
import os
from kompressr import KompressrClient

files = KompressrClient(api_key=os.environ['KOMPRESSR_API_KEY'])
accepted = files.upload_file('image.png', visibility='public')
# Persist accepted['id'] in your application's database before waiting.
ready = files.wait_until_ready(accepted['id'])
print(ready['cdn_url'])
```

Acceptance means the server has the upload; processing may still be running. Save the numeric asset ID before waiting. If a wait times out, use that saved ID to resume status checks. Reuploading can create another asset.

For private files, use `visibility='private'`, wait for readiness, then call `files.generate_private_url(asset_id)`. The result's `private_url` is an expiring authorization link. Return it only to an authorized user and keep it out of logs. Private readiness does not automatically create a fresh link.

The runnable [upload example](https://github.com/kompressrcdn/clients/blob/main/sdk-python/examples/upload.py) saves a receipt before waiting and supports `--resume` with no second upload:

```sh
python sdk-python/examples/upload.py image.png --receipt receipt.json
python sdk-python/examples/upload.py --resume --receipt receipt.json
```

The example prints a delivery link to your terminal when successful. Treat terminal history and captured output accordingly. Choose `--public` only for files intended for public delivery.

## Asyncio

Use `AsyncKompressrClient` in async applications. Methods and results match the synchronous client; await each call and use `async for` with `iterate_uploads`.

```python
import asyncio
import os
from kompressr import AsyncKompressrClient

async def main():
    files = AsyncKompressrClient(api_key=os.environ['KOMPRESSR_API_KEY'])
    accepted = await files.upload_file('image.png', visibility='public')
    # Save accepted['id'] durably here before waiting.
    ready = await files.wait_until_ready(accepted['id'])
    print(ready['cdn_url'])

asyncio.run(main())
```

The synchronous client cannot run inside an active asyncio event loop; use the async client there. Clients create and close an HTTP connection pool per operation, so no `close()` is required and a sync client can be reused across threads. Async clients require asyncio; Trio is not supported. Regular files are read in bounded chunks; brief local file reads happen on the calling event-loop thread.

## Failures and recovery

```python
from kompressr import KompressrError

try:
    ready = files.wait_until_ready(saved_asset_id, timeout=60)
except KompressrError as error:
    if error.code == 'WAIT_TIMEOUT':
        # Keep error.asset_id and resume checking it later.
        pass
    else:
        raise
```

All timeout values are **seconds**. Management requests default to 30 seconds, uploads to 600 seconds and readiness waiting to 120 seconds. A request deadline includes body reads and retry delays. Eligible GET failures may retry twice; uploads, signing, deletion and administration writes are never automatically replayed. When a write fails with `may_have_succeeded=True`, inspect the saved asset or operation outcome before deciding what to do next. A safely recovered `error.asset_id` may be available even when an upload acceptance response is malformed. Unknown outcomes can require application reconciliation.

Pass a `CancellationToken` using `cancel=` to stop sync or async work cooperatively. Calling `token.cancel()` is thread-safe. Native async task cancellation raises `KompressrCancelledError`, a subclass of `asyncio.CancelledError`, with the same recovery metadata. Catch it only to save necessary state, then re-raise so structured cancellation works. Cancelling an operation cannot roll back server work.

## Scoped keys and administration

A regular project key can operate across that project and administer identities. A scoped key is bound to an identity, allowed actions, visibility and file types. Kompressr enforces those restrictions; the SDK never substitutes a stronger key. Your application still authenticates its users, binds their keys to the correct session, stores keys securely and authorizes conversation access.

Use `files.platform` with a project key to create identities and issue scoped keys. The [platform example](https://github.com/kompressrcdn/clients/blob/main/sdk-python/examples/platform.py) explains secure one-time key storage and explicit key rotation/revocation. Scoped keys require a plan and project type supporting them. Delete permission is opt-in; the SDK leaves omitted scopes to the server's non-destructive defaults. See the [chatbot guide](https://github.com/kompressrcdn/clients/blob/main/guides/chatbot-integration.md) for the application flow.

## More operations

See [API.md](https://github.com/kompressrcdn/clients/blob/main/sdk-python/API.md) for all file and platform methods, options and response fields; [PARITY.md](https://github.com/kompressrcdn/clients/blob/main/sdk-python/PARITY.md) maps behavior to tests. Results are typed dictionaries with API snake_case keys. File uploads stream from regular files; `upload_bytes` supports bytes, bytearray and selected memoryview slices. `upload_stream` supports a standard open regular binary file or BytesIO (custom readers/subclasses are rejected), rewinds to the beginning and leaves ownership with the caller.

List uploads with `project_id` supplied to the constructor or call. `iterate_uploads` fetches pages lazily. Asset list/detail do not require a project ID: the server derives the project from the key. Deletion is permanent and asynchronous; an accepted deletion is not proof that storage cleanup or cache expiry has finished. Bulk deletion keeps each item's outcome even under HTTP 200.

## Development

```sh
cd sdk-python
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/verify.py
```

Verification typechecks, runs local HTTP tests, builds wheel/source distributions, checks archive contents, installs the wheel in a fresh environment and repeats HTTP tests against that installed package. It uses synthetic credentials and no Kompressr account. See [PUBLISHING.md](https://github.com/kompressrcdn/clients/blob/main/sdk-python/PUBLISHING.md) for maintainer release steps.

MIT licensed. Report bugs through the repository's issue tracker and security concerns through [SECURITY.md](https://github.com/kompressrcdn/clients/blob/main/SECURITY.md).
