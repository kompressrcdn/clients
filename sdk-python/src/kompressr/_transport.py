from __future__ import annotations

import asyncio
import math
import random
import threading
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, BinaryIO, TypeVar, cast
from urllib.parse import urlsplit

import httpx

from ._validation import MAX_SAFE, finite, json_text, seconds
from ._network import HTTPTransport
from .errors import KompressrCancelledError, KompressrError, invalid, invalid_response, safe_message

ENDPOINTS = {'production': {'api_base_url': 'https://kompressr.com', 'upload_base_url': 'https://uploads.kompressr.com'}}
T = TypeVar('T')


class CancellationToken:
    """Thread-safe cooperative cancellation for sync and async operations."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()


def _origin(value: str) -> str:
    try:
        if not isinstance(value, str) or any(ord(c) <= 32 for c in value):
            raise ValueError
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError
        port = parsed.port
        host = parsed.hostname.lower()
        if ':' in host:
            host = f'[{host}]'
        suffix = f':{port}' if port and port != (443 if parsed.scheme == 'https' else 80) else ''
        return f'{parsed.scheme}://{host}{suffix}'
    except (ValueError, TypeError):
        invalid('Base URL must be an HTTP(S) origin without credentials, path, query or fragment.')


def resolve_endpoints(*, api_base_url: str = 'https://kompressr.com', upload_base_url: str | None = None) -> dict[str, str]:
    api = _origin(api_base_url)
    upload = upload_base_url if upload_base_url is not None else ('https://uploads.kompressr.com' if api == 'https://kompressr.com' else api)
    return {'api_base_url': api, 'upload_base_url': _origin(upload)}


async def bounded(operation: Awaitable[T], timeout: float, cancel: CancellationToken | None = None) -> T:
    """Include socket I/O, body reads and backoff in one cancellable deadline."""
    task = asyncio.ensure_future(operation)
    watcher: asyncio.Task[None] | None = None

    async def watch() -> None:
        assert cancel is not None
        while not cancel.is_cancelled:
            await asyncio.sleep(0.01)

    deadline = asyncio.timeout(timeout)
    try:
        async with deadline:
            if cancel is None:
                return await task
            watcher = asyncio.create_task(watch())
            await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
            if cancel.is_cancelled:
                raise KompressrError('Operation cancelled.', kind='cancelled', code='REQUEST_CANCELLED')
            return await task
    except asyncio.CancelledError:
        # Python 3.11's Timeout only recognizes the exact CancelledError type.
        # A nested SDK request carries metadata on a subclass, so consult the
        # deadline itself before translating an outer wait cancellation.
        if deadline.expired():
            raise TimeoutError from None
        raise
    finally:
        for pending in (task, watcher):
            if pending is not None and not pending.done():
                pending.cancel()
        await asyncio.gather(*(p for p in (task, watcher) if p is not None), return_exceptions=True)


def retry_after(headers: httpx.Headers, body: Any) -> float | None:
    value = headers.get('retry-after')
    if value is not None:
        try:
            delay = float(value) * 1000
            if value.strip() and math.isfinite(delay) and delay >= 0:
                return delay
        except ValueError:
            pass
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0., (date.timestamp() - time.time()) * 1000)
        except (ValueError, TypeError, OverflowError):
            pass
    value = body.get('retry_after') if isinstance(body, dict) else None
    if finite(value) and value is not None and value >= 0:
        return min(float(value), sys.float_info.max / 1000) * 1000
    return None


class Transport:
    def __init__(self, *, api_key: str, api_base_url: str = 'https://kompressr.com',
                 upload_base_url: str | None = None, request_timeout: float = 30,
                 upload_timeout: float = 600, max_read_retries: int = 2) -> None:
        if not isinstance(api_key, str) or not api_key.strip() or any(ord(c) < 32 or ord(c) > 126 for c in api_key):
            invalid('Supply a nonempty ASCII API key on your trusted backend.')
        self.__key = api_key
        endpoints = resolve_endpoints(api_base_url=api_base_url, upload_base_url=upload_base_url)
        self.api_base_url = endpoints['api_base_url']
        self.upload_base_url = endpoints['upload_base_url']
        self.request_timeout = seconds(request_timeout, 'request_timeout')
        self.upload_timeout = seconds(upload_timeout, 'upload_timeout')
        if type(max_read_retries) is not int or not 0 <= max_read_retries <= 5:
            invalid('max_read_retries must be an integer from 0 to 5.')
        self.retries = max_read_retries

    async def request(self, path: str, *, method: str = 'GET', body: Any = None,
                      fields: dict[str, str] | None = None, file: tuple[str, BinaryIO | bytes] | None = None,
                      parse: Callable[[Any], T], timeout: float | None = None,
                      cancel: CancellationToken | None = None, upload: bool = False,
                      asset_id: int | None = None, recover_upload_id: bool = False) -> T:
        budget = seconds(timeout if timeout is not None else (self.upload_timeout if upload else self.request_timeout))
        if cancel is not None and not isinstance(cancel, CancellationToken):
            invalid('cancel must be a CancellationToken.')
        deadline = asyncio.get_running_loop().time() + budget
        can_retry = method == 'GET'
        dispatched = False
        status: int | None = None
        known_retry_delay: float | None = None
        known_id = asset_id

        def contextual(kind: str) -> KompressrError:
            return KompressrError(
                {'timeout': 'Request timed out; inspect a write outcome before retrying.',
                 'cancelled': 'Request cancelled; accepted server work is not rolled back.',
                 'network': 'Unable to reach Kompressr; check the configured endpoint and connection.'}[kind],
                kind=cast(Any, kind), code={'timeout': 'REQUEST_TIMEOUT', 'cancelled': 'REQUEST_CANCELLED', 'network': 'NETWORK_ERROR'}[kind],
                status=status, retry_after_ms=known_retry_delay if kind in ('timeout', 'cancelled') else None,
                asset_id=known_id, may_have_succeeded=dispatched and not can_retry)

        async def run() -> T:
            nonlocal dispatched, status, known_retry_delay, known_id
            if cancel is not None and cancel.is_cancelled:
                raise contextual('cancelled')
            # Per-phase timeouts cannot bound a slow response. The surrounding
            # asyncio deadline covers the whole operation, including response reads.
            transport = HTTPTransport(deadline)
            async with httpx.AsyncClient(transport=transport, follow_redirects=False, timeout=None, trust_env=False) as client:
                for attempt in range(self.retries + 1):
                    status = None
                    known_retry_delay = None
                    try:
                        if cancel is not None and cancel.is_cancelled:
                            raise contextual('cancelled')
                        kwargs: dict[str, Any] = {}
                        if file is not None:
                            # HTTPX renders data fields before the file and reads
                            # binary files in bounded chunks instead of buffering them.
                            kwargs.update(data=fields or {}, files={'file': (file[0], file[1], 'application/octet-stream')})
                        elif body is not None:
                            kwargs['content'] = json_text(body).encode('utf-8')
                        headers = {'Authorization': f'Bearer {self.__key}', 'Accept': 'application/json', 'Accept-Encoding': 'identity'}
                        if body is not None:
                            headers['Content-Type'] = 'application/json'
                        request = client.build_request(method, (self.upload_base_url if upload else self.api_base_url) + path, headers=headers, **kwargs)
                        if cancel is not None and cancel.is_cancelled:
                            raise contextual('cancelled')
                        dispatched = True
                        response = await client.send(request, stream=True, follow_redirects=False)
                        async with _response(response):
                            status = response.status_code
                            known_retry_delay = retry_after(response.headers, None)
                            ok = 200 <= status < 300
                            parsed: Any = None
                            try:
                                # Identity is requested above. Refuse other encodings before
                                # HTTPX can expand a small response beyond our memory limit.
                                encodings = response.headers.get_list('content-encoding', split_commas=True)
                                if any(encoding.strip().lower() != 'identity' for encoding in encodings):
                                    invalid_response('API response uses an unsupported content encoding.')
                                chunks = bytearray()
                                async for chunk in response.aiter_raw(65536):
                                    if len(chunks) + len(chunk) > 2 * 1024 * 1024:
                                        invalid_response('API response exceeds the supported size.')
                                    chunks.extend(chunk)
                                import json
                                try:
                                    parsed = json.loads(chunks, parse_constant=lambda _: invalid_response())
                                except (ValueError, UnicodeDecodeError, RecursionError):
                                    invalid_response(f'API returned a non-JSON response (HTTP {status}).')
                            except KompressrError:
                                if ok:
                                    raise
                            known_retry_delay = retry_after(response.headers, parsed)
                            if recover_upload_id and ok and isinstance(parsed, dict) and parsed.get('success') is True and isinstance(parsed.get('data'), dict):
                                candidate = parsed['data'].get('asset_id')
                                if type(candidate) in (int, float) and 0 < candidate <= MAX_SAFE and candidate == int(candidate):
                                    known_id = int(candidate)
                            failed = isinstance(parsed, dict) and parsed.get('success') is False
                            if not ok or failed:
                                failure_body = parsed if isinstance(parsed, dict) else {}
                                raise KompressrError(safe_message(failure_body.get('error', f'Kompressr returned HTTP {status}.'), self.__key),
                                    kind='api', code=safe_message(failure_body.get('code'), self.__key) if isinstance(failure_body.get('code'), str) else 'API_ERROR',
                                    status=status, retry_after_ms=known_retry_delay, asset_id=known_id,
                                    may_have_succeeded=not can_retry and (ok or 300 <= status < 400 or status >= 500))
                            try:
                                return parse(parsed)
                            except KompressrError:
                                raise
                            except (ValueError, TypeError, KeyError, OverflowError):
                                invalid_response()
                    except (KompressrError, httpx.HTTPError, OSError) as error:
                        failure = error if isinstance(error, KompressrError) else contextual('network')
                        if failure.kind == 'invalid_response':
                            failure = KompressrError(str(failure), kind='invalid_response', code=failure.code, status=status,
                                asset_id=known_id if known_id is not None else failure.asset_id, may_have_succeeded=dispatched and not can_retry)
                        transient = failure.kind == 'network' or (failure.kind == 'api' and failure.status in (429, 502, 503, 504))
                        if not can_retry or not transient or attempt >= self.retries:
                            raise failure from None
                        await asyncio.sleep(max(min(30, .25 * 2 ** attempt + random.random() * .1), (failure.retry_after_ms or 0) / 1000))
            raise AssertionError('Unreachable retry state')

        try:
            return await bounded(run(), budget, cancel)
        except TimeoutError:
            raise contextual('timeout') from None
        except KompressrError as error:
            if error.kind == 'cancelled':
                raise contextual('cancelled') from None
            raise
        except (httpx.HTTPError, OSError):
            raise contextual('network') from None
        except asyncio.CancelledError:
            raise KompressrCancelledError(status=status, retry_after_ms=known_retry_delay, asset_id=known_id, may_have_succeeded=dispatched and not can_retry) from None


class _response:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    async def __aenter__(self) -> httpx.Response:
        return self.response

    async def __aexit__(self, *args: Any) -> None:
        await self.response.aclose()
