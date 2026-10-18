"""Bound DNS work outside per-call asyncio executors; preserve native TLS origins."""
from __future__ import annotations

import asyncio
import concurrent.futures
import ipaddress
import os
import socket
import ssl
import threading
from collections.abc import AsyncIterator, Iterable
from typing import Any

import httpcore
import httpx

# OS resolver calls cannot be interrupted. They retain a slot until they actually
# finish; cancellation never creates a replacement worker or queues another lookup.
_DNS_LIMIT = 8
_CONNECTION_LIMIT = 64
_dns_slots = threading.BoundedSemaphore(_DNS_LIMIT)
_connection_slots = threading.BoundedSemaphore(_CONNECTION_LIMIT)


def _after_fork() -> None:
    global _dns_slots, _connection_slots
    _dns_slots = threading.BoundedSemaphore(_DNS_LIMIT)
    _connection_slots = threading.BoundedSemaphore(_CONNECTION_LIMIT)


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


async def _acquire(slots: threading.BoundedSemaphore) -> None:
    while not slots.acquire(blocking=False):
        await asyncio.sleep(.01)


async def _resolve(host: str, port: int) -> list[str]:
    if '%' in host:
        raise httpcore.ConnectError('Scoped IPv6 origins are unsupported.')
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    slots = _dns_slots
    await _acquire(slots)
    future: concurrent.futures.Future[list[str]] = concurrent.futures.Future()

    def resolve() -> None:
        try:
            if not future.set_running_or_notify_cancel():
                return
            rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses = list(dict.fromkeys(str(row[4][0]) for row in rows if row[0] in (socket.AF_INET, socket.AF_INET6)))
            if not addresses:
                raise OSError('No TCP address is available.')
            # Passing numeric IPs to AnyIO avoids its event-loop DNS executor.
            for address in addresses:
                if '%' in address:
                    raise OSError('Scoped IPv6 addresses are unsupported.')
                ipaddress.ip_address(address)
            future.set_result(addresses)
        except Exception:
            if not future.done():
                future.set_exception(httpcore.ConnectError('Unable to resolve the configured host.'))
        finally:
            slots.release()

    try:
        threading.Thread(target=resolve, name='kompressr-dns', daemon=True).start()
    except Exception:
        slots.release()
        raise httpcore.ConnectError('Unable to start a resolver worker.') from None
    # Cancellation cancels the await, not the OS lookup. The daemon owns its slot
    # until completion, and concurrent.futures safely discards late loop delivery.
    return await asyncio.wrap_future(future)


class _Stream(httpcore.AsyncNetworkStream):
    def __init__(self, stream: httpcore.AsyncNetworkStream, slots: threading.BoundedSemaphore) -> None:
        self._stream = stream
        self._slots = slots
        self._closed = False

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return await self._stream.read(max_bytes, timeout)

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        await self._stream.write(buffer, timeout)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._stream.aclose()
        finally:
            self._slots.release()

    async def start_tls(self, ssl_context: ssl.SSLContext, server_hostname: str | None = None,
                        timeout: float | None = None) -> httpcore.AsyncNetworkStream:
        try:
            self._stream = await self._stream.start_tls(ssl_context, server_hostname, timeout)
            return self
        except BaseException:
            await self.aclose()
            raise

    def get_extra_info(self, info: str) -> Any:
        return self._stream.get_extra_info(info)


class _Backend(httpcore.AsyncNetworkBackend):
    def __init__(self, deadline: float) -> None:
        self._deadline = deadline
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                          local_address: str | None = None,
                          socket_options: Iterable[Any] | None = None) -> httpcore.AsyncNetworkStream:
        slots = _connection_slots
        await _acquire(slots)
        transferred = False
        try:
            addresses = await _resolve(host, port)
            failure: Exception | None = None
            # Sequential fallback performs at most one connection attempt at a
            # time and never sends HTTP bytes until one connection succeeds.
            for index, address in enumerate(addresses):
                remaining = self._deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise httpcore.ConnectTimeout('Connection deadline expired.')
                # Reserve a fair share for later addresses, so a stalled IPv6
                # address cannot consume the IPv4 fallback's entire budget.
                allowance = remaining / (len(addresses) - index)
                if timeout is not None:
                    allowance = min(allowance, timeout)
                try:
                    async with asyncio.timeout(allowance):
                        stream = await self._backend.connect_tcp(address, port, allowance, local_address, socket_options)
                except TimeoutError:
                    failure = httpcore.ConnectTimeout('Address connection timed out.')
                    continue
                except (httpcore.ConnectError, httpcore.ConnectTimeout) as error:
                    failure = error
                    continue
                transferred = True
                return _Stream(stream, slots)
            assert failure is not None
            raise failure
        finally:
            if not transferred:
                slots.release()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, response: httpcore.Response) -> None:
        self._response = response

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._response.aiter_stream():
                yield chunk
        except Exception:
            raise httpx.TransportError('Unable to read the HTTP response.') from None

    async def aclose(self) -> None:
        try:
            await self._response.aclose()
        except Exception:
            raise httpx.TransportError('Unable to close the HTTP response.') from None


class HTTPTransport(httpx.AsyncBaseTransport):
    """Bridge documented HTTPX and HTTPcore extension APIs without private patches."""

    def __init__(self, deadline: float) -> None:
        self._pool = httpcore.AsyncConnectionPool(network_backend=_Backend(deadline), retries=0,
            ssl_context=httpcore.default_ssl_context(), max_connections=1, max_keepalive_connections=1)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert isinstance(request.stream, httpx.AsyncByteStream)
        # Keep the original URL: HTTPcore uses its hostname for Host and TLS SNI
        # and certificate verification, while the backend only resolves TCP IPs.
        core_request = httpcore.Request(method=request.method, url=httpcore.URL(
            scheme=request.url.raw_scheme, host=request.url.raw_host, port=request.url.port, target=request.url.raw_path),
            headers=request.headers.raw, content=request.stream, extensions=request.extensions)
        try:
            response = await self._pool.handle_async_request(core_request)
        except Exception:
            raise httpx.TransportError('Unable to complete the HTTP request.') from None
        return httpx.Response(response.status, headers=response.headers, stream=_ResponseStream(response), extensions=response.extensions)

    async def aclose(self) -> None:
        try:
            await self._pool.aclose()
        except Exception:
            raise httpx.TransportError('Unable to close the HTTP transport.') from None
