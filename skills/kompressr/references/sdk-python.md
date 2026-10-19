# Python

Python 3.11+. Use `KompressrClient` for synchronous Django views, scripts and workers. Use `AsyncKompressrClient` for FastAPI `async def` or Django async views. The sync client cannot run inside an active asyncio loop; async support requires asyncio, not Trio.

```sh
python -m pip install kompressr-sdk
```

Async integration helper; provide an async `save_asset_id` callback that commits the ID before returning:

```python
import os
from kompressr import AsyncKompressrClient

files = AsyncKompressrClient(api_key=os.environ['KOMPRESSR_API_KEY'])

async def upload_public(path, save_asset_id):
    accepted = await files.upload_file(path, visibility='public')
    await save_asset_id(accepted['id'])
    ready = await files.wait_until_ready(accepted['id'])
    return ready['cdn_url']
```

In a synchronous application, instantiate `KompressrClient`, use a synchronous persistence callback and call those same methods without `await`. Do not call `asyncio.run()` inside an already-running web event loop.

The [runnable upload example](https://github.com/kompressrcdn/clients/blob/main/sdk-python/examples/upload.py) supports local receipts and `--resume`. From a source checkout with the SDK installed:

```sh
python sdk-python/examples/upload.py image.png --receipt receipt.json
python sdk-python/examples/upload.py --resume --receipt receipt.json
```

It defaults to private delivery; use `--public` only for public files. Its output can include a signed URL intended for your local test.

## Methods and shapes

Results use dictionaries, including acceptance `['id']`, status `['cdn_url']` and signing `['private_url']`. Files use `upload_file`; bytes use `upload_bytes`. `upload_stream(stream, filename)` accepts an unmodified `BytesIO`, or a standard `FileIO`/`BufferedReader` backed by a regular binary file. It rewinds to zero and leaves the stream open; custom readers, pipes and sockets are unsupported. For private files, set `visibility='private'`, persist the ID, wait and call `generate_private_url` after application authorization.

Other methods: `get_upload_status`, `wait_until_ready`, `list_uploads`, `iterate_uploads`, `list_assets`, `get_asset`, `delete_asset`, `bulk_delete_assets`. Async methods are awaited; use `async for` for async iteration. Upload listing needs `project_id` through configuration or the call.

Platform methods live under `files.platform` with snake_case names for user/key administration. Use a project/master credential. See [API](https://github.com/kompressrcdn/clients/blob/main/sdk-python/API.md) for exact argument names and result dictionaries rather than translating JS option names literally.

## Application details

- Timeouts and poll intervals are **seconds**. Signing `expires_in` is also seconds. Endpoint options: `api_base_url`, `upload_base_url`.
- `KompressrError` includes `code`, `status`, `asset_id`, `retry_after_ms`, `may_have_succeeded`. Preserve the ID and uncertainty on failure.
- `CancellationToken` is passed as `cancel=`. Native async cancellation preserves `asyncio.CancelledError` semantics; after necessary cleanup, re-raise it.
- Django `UploadedFile` and FastAPI `UploadFile` are not accepted directly. Use supported bytes for small bounded files or copy to a regular local file for streaming. Keep it alive until upload completes.
- Clients create/close HTTP pools per operation, so there is no required `close()`. Local file reads can briefly occupy the calling thread.
- An early large-upload rejection can appear as a network/write error if the HTTP library never exposes the response. Reconcile the outcome rather than assuming the upload failed or retrying it automatically.

[Full API](https://github.com/kompressrcdn/clients/blob/main/sdk-python/API.md) · [Guide](https://github.com/kompressrcdn/clients/blob/main/sdk-python/README.md)
