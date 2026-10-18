"""DNS regressions must exercise caller return and event-loop shutdown, not only coroutine timing."""
from __future__ import annotations

import asyncio
import socket
import threading
import time
import unittest
from unittest.mock import patch

from kompressr import AsyncKompressrClient, CancellationToken, KompressrClient, KompressrError
from support import FIXTURE, Server, envelope


class DNSTests(unittest.TestCase):
    def assert_connection_slots_released(self):
        from kompressr import _network
        acquired = []
        try:
            for _ in range(_network._CONNECTION_LIMIT):
                self.assertTrue(_network._connection_slots.acquire(blocking=False))
                acquired.append(True)
        finally:
            for _ in acquired:
                _network._connection_slots.release()

    def test_sync_dns_timeout_returns_before_os_lookup_finishes_without_late_write(self):
        release = threading.Event()
        finished = threading.Event()
        with Server(lambda r, n: envelope(FIXTURE['accepted'])) as server:
            port = server.server.server_port
            def blocked(*args, **kwargs):
                release.wait(.8)
                finished.set()
                return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', port))]
            try:
                with patch('socket.getaddrinfo', blocked):
                    start = time.monotonic()
                    client = KompressrClient(api_key='fixture-key', api_base_url=f'http://resolver.example.test:{port}', max_read_retries=0)
                    with self.assertRaises(KompressrError) as caught:
                        client.upload_bytes(b'fixture', 'file.png', timeout=.05)
                    elapsed = time.monotonic() - start
                    self.assertEqual(caught.exception.code, 'REQUEST_TIMEOUT')
                    self.assertTrue(caught.exception.may_have_succeeded)
                    self.assertLess(elapsed, .4)
                    self.assertFalse(finished.is_set())
                    release.set()
                    self.assertTrue(finished.wait(1))
                    time.sleep(.03)
                    self.assertEqual(server.requests, [])
            finally:
                release.set()
                finished.wait(1)

    def test_asyncio_run_exits_before_blocked_dns_finishes(self):
        release = threading.Event()
        entered = threading.Event()
        finished = threading.Event()
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(.8)
            finished.set()
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', 1))]
        async def attempt():
            client = AsyncKompressrClient(api_key='fixture-key', api_base_url='http://resolver.example.test:1', max_read_retries=0)
            await client.get_upload_status(42, timeout=.05)
        try:
            with patch('socket.getaddrinfo', blocked):
                start = time.monotonic()
                with self.assertRaises(KompressrError) as caught:
                    asyncio.run(attempt())
                self.assertEqual(caught.exception.code, 'REQUEST_TIMEOUT')
                self.assertLess(time.monotonic() - start, .4)
                self.assertTrue(entered.is_set())
                self.assertFalse(finished.is_set())
        finally:
            release.set()
            finished.wait(1)

    def test_cancel_during_dns_returns_promptly_without_late_request(self):
        release = threading.Event()
        entered = threading.Event()
        finished = threading.Event()
        token = CancellationToken()
        with Server(lambda r, n: envelope(FIXTURE['accepted'])) as server:
            port = server.server.server_port
            def blocked(*args, **kwargs):
                entered.set()
                release.wait(.8)
                finished.set()
                return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', port))]
            canceller = threading.Thread(target=lambda: (entered.wait(1), token.cancel()))
            canceller.start()
            try:
                with patch('socket.getaddrinfo', blocked):
                    client = KompressrClient(api_key='fixture-key', api_base_url=f'http://resolver.example.test:{port}', max_read_retries=0)
                    start = time.monotonic()
                    with self.assertRaises(KompressrError) as caught:
                        client.delete_asset(42, cancel=token)
                    self.assertEqual(caught.exception.code, 'REQUEST_CANCELLED')
                    self.assertEqual(caught.exception.asset_id, 42)
                    self.assertTrue(caught.exception.may_have_succeeded)
                    self.assertLess(time.monotonic() - start, .4)
                    release.set()
                    self.assertTrue(finished.wait(1))
                    time.sleep(.03)
                    self.assertEqual(server.requests, [])
            finally:
                release.set()
                finished.wait(1)
                canceller.join(1)
        self.assert_connection_slots_released()

    def test_dns_capacity_is_bounded_and_waiters_are_cancellable(self):
        from kompressr import _network
        release = threading.Event()
        calls = []
        finished = []
        lock = threading.Lock()
        def blocked(*args, **kwargs):
            with lock:
                calls.append(threading.current_thread())
            release.wait(3)
            with lock:
                finished.append(True)
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', 1))]
        try:
            with patch('socket.getaddrinfo', blocked):
                client = KompressrClient(api_key='fixture-key', api_base_url='http://resolver.example.test:1', max_read_retries=0)
                for _ in range(_network._DNS_LIMIT + 2):
                    start = time.monotonic()
                    with self.assertRaises(KompressrError) as caught:
                        client.get_upload_status(42, timeout=.05)
                    self.assertEqual(caught.exception.code, 'REQUEST_TIMEOUT')
                    self.assertLess(time.monotonic() - start, .4)
                self.assertEqual(len(calls), _network._DNS_LIMIT)
                self.assertTrue(all(worker.daemon for worker in calls))
                release.set()
                for worker in calls:
                    worker.join(1)
                self.assertEqual(len(finished), _network._DNS_LIMIT)
                # Timed-out admission waiters must not start queued lookups later.
                time.sleep(.03)
                self.assertEqual(len(calls), _network._DNS_LIMIT)
        finally:
            release.set()
            for worker in calls:
                worker.join(1)

    def test_multiple_addresses_fall_back_before_sending_http(self):
        with Server(lambda r, n: envelope(FIXTURE['processed'])) as server:
            port = server.server.server_port
            rows = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, port)) for address in ('127.0.0.2', '127.0.0.1')]
            with patch('socket.getaddrinfo', return_value=rows):
                client = KompressrClient(api_key='fixture-key', api_base_url=f'http://resolver.example.test:{port}', max_read_retries=0)
                self.assertEqual(client.get_upload_status(42)['id'], 42)
                self.assertEqual(len(server.requests), 1)
                self.assertEqual(server.requests[0]['headers']['Host'], f'resolver.example.test:{port}')

    def test_https_keeps_original_host_sni_and_certificate_validation(self):
        import datetime
        from pathlib import Path
        import ssl
        import tempfile
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import httpcore

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'resolver.example.test')])
        now = datetime.datetime.now(datetime.timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('resolver.example.test')]), critical=False)
            .sign(key, hashes.SHA256()))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            certificate_path, key_path = directory / 'certificate.pem', directory / 'private.pem'
            certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(certificate_path, key_path)
            names = []
            server_context.set_servername_callback(lambda socket, name, context: names.append(name))
            trusted = ssl.create_default_context(cafile=str(certificate_path))
            server = Server(lambda r, n: envelope(FIXTURE['processed']))
            server.server.socket = server_context.wrap_socket(server.server.socket, server_side=True)
            with server:
                port = server.server.server_port
                rows = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', port))]
                with patch('socket.getaddrinfo', return_value=rows), patch.object(httpcore, 'default_ssl_context', return_value=trusted):
                    client = KompressrClient(api_key='fixture-key', api_base_url=f'https://resolver.example.test:{port}', max_read_retries=0)
                    self.assertEqual(client.get_upload_status(42)['id'], 42)
                    self.assertEqual(names[0], 'resolver.example.test')
                    self.assertEqual(server.requests[0]['headers']['Host'], f'resolver.example.test:{port}')
                    wrong = KompressrClient(api_key='fixture-key', api_base_url=f'https://wrong.example.test:{port}', max_read_retries=0)
                    with self.assertRaises(KompressrError) as caught:
                        wrong.get_upload_status(42)
                    self.assertEqual(caught.exception.code, 'NETWORK_ERROR')
                    self.assertEqual(len(server.requests), 1)
                    self.assertTrue(trusted.check_hostname)
                    self.assertEqual(trusted.verify_mode, ssl.CERT_REQUIRED)
        self.assert_connection_slots_released()

    def test_stalled_first_address_leaves_time_for_healthy_fallback(self):
        import httpcore
        original_connect = httpcore.AnyIOBackend.connect_tcp
        attempted = []
        first_closed = threading.Event()
        async def connect(backend, host, port, timeout=None, local_address=None, socket_options=None):
            attempted.append(host)
            if host == '127.0.0.2':
                try:
                    await asyncio.sleep(2)
                finally:
                    first_closed.set()
            return await original_connect(backend, host, port, timeout, local_address, socket_options)
        with Server(lambda r, n: envelope(FIXTURE['processed'])) as server:
            port = server.server.server_port
            rows = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, port)) for address in ('127.0.0.2', '127.0.0.1')]
            with patch('socket.getaddrinfo', return_value=rows), patch.object(httpcore.AnyIOBackend, 'connect_tcp', connect):
                start = time.monotonic()
                client = KompressrClient(api_key='fixture-key', api_base_url=f'http://resolver.example.test:{port}', max_read_retries=0)
                self.assertEqual(client.get_upload_status(42, timeout=.4)['id'], 42)
                self.assertLess(time.monotonic() - start, .4)
                self.assertEqual(attempted, ['127.0.0.2', '127.0.0.1'])
                self.assertTrue(first_closed.is_set())
                self.assertEqual(len(server.requests), 1)

    def test_connection_admission_and_cancellation_release_slots(self):
        from kompressr import _network
        acquired = []
        try:
            for _ in range(_network._CONNECTION_LIMIT):
                self.assertTrue(_network._connection_slots.acquire(blocking=False))
                acquired.append(True)
            with Server(lambda r, n: envelope(FIXTURE['processed'])) as server:
                client = KompressrClient(api_key='fixture-key', api_base_url=server.origin, max_read_retries=0)
                with self.assertRaises(KompressrError) as caught:
                    client.get_upload_status(42, timeout=.05)
                self.assertEqual(caught.exception.code, 'REQUEST_TIMEOUT')
                self.assertEqual(server.requests, [])
        finally:
            for _ in acquired:
                _network._connection_slots.release()
        # Admission timeout must not acquire a slot after the caller has returned.
        acquired = []
        try:
            for _ in range(_network._CONNECTION_LIMIT):
                self.assertTrue(_network._connection_slots.acquire(blocking=False))
                acquired.append(True)
        finally:
            for _ in acquired:
                _network._connection_slots.release()
