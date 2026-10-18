from __future__ import annotations

import asyncio
import gzip
import io
import json
import socket
import tempfile
import threading
import time
import tracemalloc
import unittest
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from kompressr import AsyncKompressrClient, AsyncPlatformClient, CancellationToken, KompressrCancelledError, KompressrClient, KompressrError, PlatformClient, resolve_endpoints
from support import FIXTURE, ISSUED, KEY, KEY_ID, PROJECT, USER, USER_ID, Server, envelope, processed


def make(server, **kwargs):
    return KompressrClient(api_key='fixture-key', api_base_url=server.origin, project_id=PROJECT, max_read_retries=kwargs.pop('max_read_retries', 0), **kwargs)


def slow_body(handler):
    handler.send_response(200)
    handler.send_header('Content-Length', '1000')
    handler.end_headers()
    handler.wfile.write(b'{"success":true,"data":')
    handler.wfile.flush()
    time.sleep(.6)
    handler.close_connection = True


def disconnect(handler):
    handler.connection.shutdown(socket.SHUT_RDWR)
    handler.connection.close()
    handler.close_connection = True


def retry_context_response(handler, phase, headers_sent, release):
    if phase == 'response_body':
        status, payload, headers = 200, json.dumps(FIXTURE['deletionAccepted']).encode(), {'Retry-After': '5'}
    elif phase == 'compressed_backoff':
        status, payload, headers = 503, gzip.compress(b'{"error":"Try later"}'), {'Retry-After': '5', 'Content-Encoding': 'gzip'}
    else:
        status, payload, headers = 503, b'{"error":"Try later","retry_after":5}', {}
    handler.send_response(status)
    handler.send_header('Content-Length', str(len(payload)))
    for name, value in headers.items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.flush()
    if phase == 'response_body':
        headers_sent.set()
        release.wait(2)
    handler.wfile.write(payload)
    handler.wfile.flush()
    headers_sent.set()


class SDKTests(unittest.TestCase):
    def test_endpoints_and_validation(self):
        self.assertEqual(resolve_endpoints(), {'api_base_url': 'https://kompressr.com', 'upload_base_url': 'https://uploads.kompressr.com'})
        self.assertEqual(resolve_endpoints(api_base_url='https://management.example.test')['upload_base_url'], 'https://management.example.test')
        self.assertEqual(resolve_endpoints(api_base_url='https://KOMPRESSR.COM:443/')['upload_base_url'], 'https://uploads.kompressr.com')
        self.assertEqual(resolve_endpoints(api_base_url='http://[::1]:9000')['upload_base_url'], 'http://[::1]:9000')
        for url in ('https://user:secret@example.test', 'https://example.test/path', 'ftp://example.test', 'https://example.test?x=1', 'https://example.test#x', 'https://example.test:abc', ' https://example.test'):
            with self.subTest(url=url), self.assertRaises(KompressrError):
                resolve_endpoints(api_base_url=url)
        for config in ({'api_key': ''}, {'api_key': 'key\n'}, {'api_key': 'key', 'max_read_retries': True}, {'api_key': 'key', 'request_timeout': float('nan')}):
            with self.subTest(config=config), self.assertRaises(KompressrError):
                KompressrClient(**config)

    def test_real_file_multipart_separate_origins_and_polling(self):
        with Server(lambda r, n: envelope(FIXTURE['accepted'])) as upload, Server(lambda r, n: envelope(processed(status='pending' if n == 1 else 'processed'))) as api, tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'fixture.png'
            path.write_bytes(b'x' * 4 * 1024 * 1024)
            client = make(api, upload_base_url=upload.origin)
            accepted = client.upload_file(path, visibility='public', quality='1080p', data={'owner': 'customer-1'}, private_url_expires_in=120)
            self.assertEqual(accepted['id'], 42)
            self.assertNotEqual(accepted['status'], 'processed')
            request = upload.requests[0]
            mime = BytesParser(policy=default).parsebytes(('Content-Type: ' + request['headers']['Content-Type'] + '\r\n\r\n').encode() + request['body'])
            parts = list(mime.iter_parts())
            self.assertEqual([p.get_param('name', header='content-disposition') for p in parts], ['visibility', 'kmp-quality', 'private_url_expires_in', 'data', 'file'])
            self.assertEqual(parts[-1].get_filename(), 'fixture.png')
            self.assertEqual(len(parts[-1].get_payload(decode=True)), 4 * 1024 * 1024)
            self.assertEqual(request['headers']['Authorization'], 'Bearer fixture-key')
            ready = client.wait_until_ready(accepted['id'], timeout=2, poll_interval=.001)
            self.assertEqual(ready['cdn_url'], FIXTURE['processed']['cdn_url'])
            self.assertEqual(len(upload.requests), 1)
            self.assertEqual(len(api.requests), 2)

    def test_stream_reads_are_bounded_and_caller_retains_ownership(self):
        content = io.BytesIO(b'x' * 1024 * 1024)
        content.seek(40)
        with Server(lambda r, n: envelope(FIXTURE['accepted'])) as server:
            make(server).upload_stream(content, '../folder/fixture.png')
            self.assertFalse(content.closed)
            self.assertGreater(len(server.requests[0]['body']), 1024 * 1024)
            self.assertIn(b'filename="fixture.png"', server.requests[0]['body'])

    def test_large_file_streaming_has_bounded_memory(self):
        size = 32 * 1024 * 1024
        with tempfile.TemporaryDirectory() as temporary, Server(lambda r, n: envelope(FIXTURE['accepted']), capture_body=False) as server:
            path = Path(temporary) / 'large.png'
            with path.open('wb') as handle:
                handle.truncate(size)
            client = make(server)
            tracemalloc.start()
            try:
                client.upload_file(path)
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            self.assertGreater(server.requests[0]['bytes_received'], size)
            self.assertLess(peak, 8 * 1024 * 1024, f'Upload allocated {peak} bytes for a {size}-byte file')

    def test_custom_blocking_stream_is_rejected_without_reading(self):
        class Blocking(io.BytesIO):
            def read(self, n=-1):
                raise AssertionError('Custom read must never execute')
        with Server(lambda r, n: {}) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server).upload_stream(Blocking(b'x'), 'file.png', timeout=.01)
            self.assertEqual(caught.exception.code, 'INVALID_ARGUMENT')
            self.assertEqual(server.requests, [])

    def test_bytes_view_boundaries_and_snapshot(self):
        backing = bytearray(b'xxABCyy')
        view = memoryview(backing)[2:5]
        def respond(request, _):
            backing[:] = b'0000000'
            return envelope(FIXTURE['accepted'])
        with Server(respond) as server:
            make(server).upload_bytes(view, 'fixture.png')
            body = server.requests[0]['body']
            self.assertIn(b'\r\nABC\r\n', body)
            self.assertNotIn(b'xxABCyy', body)

    def test_private_lifecycle_and_signing(self):
        accepted = {k: v for k, v in FIXTURE['accepted'].items() if k != 'cdn_url'}
        accepted.update(visibility='private')
        private = {k: v for k, v in processed(visibility='private', can_generate_private_url=True).items() if k != 'cdn_url'}
        signed = {'asset_id': 42, 'variant': 'avif', 'private_url': 'https://cdn.example/private?signature=fixture', 'expires_at': '2030-01-01T00:00:00Z', 'expires_in': 120}
        responses = [envelope(accepted), envelope(private), envelope(signed)]
        with Server(lambda r, n: responses[n - 1]) as server:
            client = make(server)
            receipt = client.upload_bytes(b'fixture', 'fixture.png', visibility='private')
            self.assertNotIn('cdn_url', receipt)
            self.assertEqual(client.wait_until_ready(42)['visibility'], 'private')
            self.assertEqual(len(server.requests), 2)
            self.assertEqual(client.generate_private_url(42, expires_in=120, variant='avif'), signed)
            self.assertEqual(json.loads(server.requests[-1]['body']), {'expires_in': 120, 'variant': 'avif'})

    def test_pagination_filters_lazy_progression(self):
        def respond(request, count):
            return {'success': True, 'data': [processed(id=41 + count)], 'page': count, 'limit': 1, 'total': 2}
        with Server(respond) as server:
            iterator = make(server).iterate_uploads(limit=1, data={'owner': 'a&b'}, external_id='x/y', status='processed', deletion_status='active')
            self.assertEqual(len(server.requests), 0)
            self.assertEqual(next(iterator)['id'], 42)
            self.assertEqual(len(server.requests), 1)
            self.assertEqual(next(iterator)['id'], 43)
            self.assertEqual(list(iterator), [])
            query = parse_qs(urlsplit(server.requests[1]['path']).query)
            self.assertEqual(query['data.owner'], ['a&b'])
            self.assertEqual(query['status'], ['3'])
            self.assertEqual(query['project_id'], [PROJECT])
            self.assertEqual(query['page'], ['2'])
            self.assertEqual(query['external_id'], ['x/y'])

    def test_invalid_pagination_and_empty_stop(self):
        for response in ({'success': True, 'data': [processed()], 'page': 2, 'limit': 1, 'total': 2}, {'success': True, 'data': [processed(), processed()], 'page': 1, 'limit': 1, 'total': 2}):
            with Server(lambda r, n: response) as server, self.assertRaises(KompressrError):
                list(make(server).iterate_uploads())
        with Server(lambda r, n: {'success': True, 'data': [], 'page': 1, 'limit': 20, 'total': 100}) as server:
            self.assertEqual(list(make(server).iterate_uploads()), [])
            self.assertEqual(len(server.requests), 1)

    def test_deletion_states_and_per_item_bulk_results(self):
        responses = [FIXTURE['deletionAccepted'], {**FIXTURE['deletionAccepted'], 'deletion_status': 'deleted', 'storage_credited_mb': 2}, FIXTURE['bulkDeletion']]
        with Server(lambda r, n: responses[n - 1]) as server:
            client = make(server)
            self.assertEqual(client.delete_asset(42)['deletion_status'], 'deleting')
            self.assertEqual(client.get_asset(42)['storage_credited_mb'], 2)
            batch = client.bulk_delete_assets([42, 42, 43])
            self.assertEqual(batch['counts']['failed'], 1)
            self.assertFalse(batch['results'][1]['accepted'])
            self.assertEqual(json.loads(server.requests[-1]['body']), {'asset_ids': [42, 42, 43]})

    def test_asset_listing_needs_no_project(self):
        with Server(lambda r, n: {'data': [FIXTURE['deletionAccepted']], 'page': 1, 'limit': 20, 'total': 1}) as server:
            client = KompressrClient(api_key='fixture-key', api_base_url=server.origin)
            with self.assertRaises(KompressrError):
                client.list_uploads()
            self.assertEqual(client.list_assets(deletion_status='deleting')['data'][0]['id'], 42)
            self.assertNotIn('project_id', server.requests[0]['path'])

    def test_optional_original_name(self):
        for name in (None, ''):
            row = processed()
            if name is None:
                del row['original_name']
            else:
                row['original_name'] = name
            def respond(request, _):
                return {'success': True, 'data': [row], 'page': 1, 'limit': 20, 'total': 1} if request['path'].startswith('/api/uploads?') else envelope(row)
            with self.subTest(name=name), Server(respond) as server:
                client = make(server)
                self.assertEqual(client.get_upload_status(42)['id'], 42)
                self.assertEqual(client.wait_until_ready(42)['id'], 42)
                self.assertEqual(client.list_uploads()['data'][0]['id'], 42)

    def test_terminal_processing_states_with_url(self):
        for status in ('failed', 'unprocessable', 'unknown'):
            with self.subTest(status=status), Server(lambda r, n: envelope(processed(status=status))) as server:
                with self.assertRaises(KompressrError) as caught:
                    make(server).wait_until_ready(42)
                self.assertEqual(caught.exception.code, 'PROCESSING_FAILED')
                self.assertEqual(caught.exception.asset_id, 42)

    def test_readiness_requires_active_correct_delivery(self):
        deleting = processed(deletion_status='deleting')
        del deleting['cdn_url']
        no_url = processed()
        del no_url['cdn_url']
        private = {**no_url, 'visibility': 'private', 'can_generate_private_url': False}
        for row, code in ((deleting, 'ASSET_DELETED'), (no_url, 'INVALID_RESPONSE'), (private, 'INVALID_RESPONSE'), (processed(visibility='private'), 'INVALID_RESPONSE'), (processed(deletion_status=None), 'INVALID_RESPONSE')):
            with self.subTest(code=code), Server(lambda r, n: envelope(row)) as server:
                with self.assertRaises(KompressrError) as caught:
                    make(server).wait_until_ready(42)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.asset_id, 42)

    def test_wait_timeout_resumes_without_reupload(self):
        with Server(lambda r, n: envelope(processed(status='pending'))) as server:
            client = make(server)
            with self.assertRaises(KompressrError) as caught:
                client.wait_until_ready(42, timeout=.08, poll_interval=.01)
            self.assertEqual(caught.exception.code, 'WAIT_TIMEOUT')
            self.assertEqual(caught.exception.asset_id, 42)
            server.responder = lambda r, n: envelope(processed())
            self.assertEqual(client.wait_until_ready(42)['id'], 42)
            self.assertTrue(all(r['method'] == 'GET' for r in server.requests))

    def test_slow_response_body_has_total_request_deadline(self):
        with Server(lambda r, n: slow_body) as server:
            start = time.monotonic()
            with self.assertRaises(KompressrError) as caught:
                make(server).get_upload_status(42, timeout=.08)
            self.assertEqual(caught.exception.code, 'REQUEST_TIMEOUT')
            self.assertFalse(caught.exception.may_have_succeeded)
            self.assertLess(time.monotonic() - start, .4)

    def test_slow_body_wait_deadline_preserves_id(self):
        with Server(lambda r, n: slow_body) as server:
            start = time.monotonic()
            with self.assertRaises(KompressrError) as caught:
                make(server).wait_until_ready(42, timeout=.08)
            self.assertEqual(caught.exception.code, 'WAIT_TIMEOUT')
            self.assertEqual(caught.exception.asset_id, 42)
            self.assertLess(time.monotonic() - start, .4)

    def test_slow_write_deadline_ambiguity_and_no_replay(self):
        with Server(lambda r, n: slow_body) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server).delete_asset(42, timeout=.08)
            self.assertEqual(caught.exception.code, 'REQUEST_TIMEOUT')
            self.assertTrue(caught.exception.may_have_succeeded)
            self.assertEqual(caught.exception.asset_id, 42)
            self.assertEqual(len(server.requests), 1)

    def test_pre_cancel_sends_nothing(self):
        token = CancellationToken()
        token.cancel()
        with Server(lambda r, n: envelope(FIXTURE['accepted'])) as server:
            client = make(server)
            with self.assertRaises(KompressrError) as caught:
                client.upload_bytes(b'x', 'file.png', cancel=token)
            self.assertEqual(caught.exception.code, 'REQUEST_CANCELLED')
            self.assertFalse(caught.exception.may_have_succeeded)
            with self.assertRaises(KompressrError) as caught:
                client.wait_until_ready(42, cancel=token)
            self.assertEqual(caught.exception.code, 'WAIT_CANCELLED')
            self.assertEqual(caught.exception.asset_id, 42)
            self.assertEqual(server.requests, [])

    def test_cancel_during_write_retains_sync_metadata(self):
        token = CancellationToken()
        with Server(lambda r, n: slow_body) as server:
            thread = threading.Thread(target=lambda: (server.arrived.wait(1), token.cancel()))
            thread.start()
            with self.assertRaises(KompressrError) as caught:
                make(server).delete_asset(42, cancel=token)
            thread.join()
            self.assertEqual(caught.exception.code, 'REQUEST_CANCELLED')
            self.assertTrue(caught.exception.may_have_succeeded)
            self.assertEqual(caught.exception.asset_id, 42)
            self.assertEqual(len(server.requests), 1)

    def test_eligible_read_retries_and_bounded_attempts(self):
        for status in (429, 502, 503, 504):
            with self.subTest(status=status), Server(lambda r, n: (status, {'error': 'Try later'}, {}) if n == 1 else envelope(processed())) as server:
                self.assertEqual(make(server, max_read_retries=1).get_upload_status(42)['id'], 42)
                self.assertEqual(len(server.requests), 2)
        with Server(lambda r, n: (503, {'error': 'Try later'}, {})) as server:
            with self.assertRaises(KompressrError):
                make(server, max_read_retries=1).get_upload_status(42)
            self.assertEqual(len(server.requests), 2)

    def test_network_read_retries_but_writes_do_not(self):
        with Server(lambda r, n: disconnect if n == 1 else envelope(processed())) as server:
            self.assertEqual(make(server, max_read_retries=1).get_upload_status(42)['id'], 42)
            self.assertEqual(len(server.requests), 2)
        for action in (lambda c: c.upload_bytes(b'x', 'file.png'), lambda c: c.platform.create_user('customer-1')):
            with Server(lambda r, n: disconnect) as server, self.assertRaises(KompressrError) as caught:
                action(make(server, max_read_retries=5))
            self.assertEqual(caught.exception.code, 'NETWORK_ERROR')
            self.assertTrue(caught.exception.may_have_succeeded)
            self.assertEqual(len(server.requests), 1)

    def test_retry_after_never_shortened_and_deadline_includes_delay(self):
        for headers, body in (({'Retry-After': '5'}, {'error': 'Rate limited'}), ({}, {'error': 'Rate limited', 'retry_after': 5}), ({'Retry-After': 'Wed, 01 Jan 2031 00:00:00 GMT'}, {})):
            with Server(lambda r, n: (429, body, headers)) as server:
                start = time.monotonic()
                with self.assertRaises(KompressrError) as caught:
                    make(server, max_read_retries=2).get_upload_status(42, timeout=.08)
                self.assertEqual(caught.exception.code, 'REQUEST_TIMEOUT')
                self.assertEqual(len(server.requests), 1)
                self.assertLess(time.monotonic() - start, .4)
        with Server(lambda r, n: (429, {'error': 'Rate limited'}, {'Retry-After': '5'})) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server).get_upload_status(42)
            self.assertEqual(caught.exception.retry_after_ms, 5000)

    def test_retry_delay_survives_deadline_and_token_cancellation(self):
        for phase in ('response_body', 'compressed_backoff', 'json_backoff'):
            for cancelled in (False, True):
                with self.subTest(phase=phase, cancelled=cancelled):
                    headers_sent, release = threading.Event(), threading.Event()
                    token = CancellationToken()
                    def cancel_after_headers():
                        if headers_sent.wait(2):
                            time.sleep(.03)
                            token.cancel()
                    worker = threading.Thread(target=cancel_after_headers) if cancelled else None
                    with Server(lambda r, n: lambda handler: retry_context_response(handler, phase, headers_sent, release)) as server:
                        if worker:
                            worker.start()
                        try:
                            client = make(server, max_read_retries=1)
                            with self.assertRaises(KompressrError) as caught:
                                if phase == 'response_body':
                                    client.delete_asset(42, timeout=1 if cancelled else .15, cancel=token)
                                else:
                                    client.get_upload_status(42, timeout=1 if cancelled else .15, cancel=token)
                        finally:
                            release.set()
                            if worker:
                                worker.join()
                        error = caught.exception
                        self.assertEqual(error.code, 'REQUEST_CANCELLED' if cancelled else 'REQUEST_TIMEOUT')
                        self.assertEqual(error.status, 200 if phase == 'response_body' else 503)
                        self.assertEqual(error.retry_after_ms, 5000)
                        self.assertEqual(error.asset_id, 42 if phase == 'response_body' else None)
                        self.assertEqual(error.may_have_succeeded, phase == 'response_body')
                        self.assertEqual(len(server.requests), 1)

    def test_new_attempt_clears_previous_retry_metadata(self):
        for send_headers in (False, True):
            with self.subTest(send_headers=send_headers):
                release = threading.Event()
                def delayed(handler):
                    if send_headers:
                        handler.send_response(200)
                        handler.send_header('Content-Length', '2')
                        handler.end_headers()
                        handler.wfile.flush()
                    release.wait(2)
                with Server(lambda r, n: (503, {}, {'Retry-After': '0.01'}) if n == 1 else delayed) as server:
                    try:
                        with self.assertRaises(KompressrError) as caught:
                            make(server, max_read_retries=1).get_upload_status(42, timeout=.6)
                    finally:
                        release.set()
                    self.assertEqual(caught.exception.code, 'REQUEST_TIMEOUT')
                    self.assertEqual(caught.exception.status, 200 if send_headers else None)
                    self.assertIsNone(caught.exception.retry_after_ms)
                    self.assertEqual(len(server.requests), 2)

    def test_permission_and_non_retryable_errors_preserve_scope(self):
        for status in (400, 401, 403, 404, 500):
            with Server(lambda r, n: (status, {'code': 'FORBIDDEN', 'error': 'Missing delete scope'}, {})) as server:
                with self.assertRaises(KompressrError) as caught:
                    make(server, max_read_retries=5).get_asset(42)
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(caught.exception.code, 'FORBIDDEN')
                self.assertEqual(len(server.requests), 1)
                self.assertEqual(server.requests[0]['headers']['Authorization'], 'Bearer fixture-key')
        with Server(lambda r, n: (403, {'code': 'FORBIDDEN', 'error': 'Missing delete scope'}, {})) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server).delete_asset(42)
            self.assertFalse(caught.exception.may_have_succeeded)

    def test_redirects_never_follow_or_leak_credentials(self):
        with Server(lambda r, n: envelope(processed())) as target, Server(lambda r, n: (307, {}, {'Location': target.origin + '/capture'})) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server, max_read_retries=5).delete_asset(42)
            self.assertTrue(caught.exception.may_have_succeeded)
            self.assertEqual(caught.exception.asset_id, 42)
            self.assertEqual(target.requests, [])
            self.assertEqual(len(server.requests), 1)

    def test_error_redaction_and_html_exclusion(self):
        error = 'Bearer fixture-key https://cdn.example/private?signature=abc token=secret-value password=hidden'
        with Server(lambda r, n: (403, {'error': error, 'code': error}, {})) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server).get_asset(42)
            safe = json.dumps(caught.exception.to_dict()) + repr(caught.exception)
            for value in ('fixture-key', 'cdn.example', 'secret-value', 'password=hidden', 'signature=abc'):
                self.assertNotIn(value, safe)
        with Server(lambda r, n: (502, b'<html>private diagnostic body</html>', {})) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server).get_asset(42)
            self.assertEqual(caught.exception.status, 502)
            self.assertNotIn('diagnostic', str(caught.exception))

    def test_mutations_invalid_json_and_incomplete_shapes_keep_ambiguity(self):
        operations = [
            ('upload', lambda c: c.upload_bytes(b'x', 'file.png'), None),
            ('sign', lambda c: c.generate_private_url(42), 42),
            ('delete', lambda c: c.delete_asset(42), 42),
            ('bulk', lambda c: c.bulk_delete_assets([42, 43]), None),
            ('create', lambda c: c.platform.create_user('customer-1'), None),
            ('update', lambda c: c.platform.update_user(USER_ID, display_name='Customer'), None),
            ('suspend', lambda c: c.platform.suspend_user(USER_ID), None),
            ('reactivate', lambda c: c.platform.reactivate_user(USER_ID), None),
            ('key', lambda c: c.platform.create_upload_key(USER_ID, 'Runtime'), None),
            ('rotate', lambda c: c.platform.rotate_upload_key(USER_ID, KEY_ID), None),
            ('revoke', lambda c: c.platform.revoke_upload_key(USER_ID, KEY_ID), None),
        ]
        for name, operation, expected in operations:
            for broken in (True, False):
                body = b'{broken' if broken else ({} if name == 'revoke' else {'success': True, 'data': {'asset_id': 42}, 'api_key': 'fixture-one-time'})
                with self.subTest(name=name, broken=broken), Server(lambda r, n: body) as server:
                    with self.assertRaises(KompressrError) as caught:
                        operation(make(server, max_read_retries=5))
                    error = caught.exception
                    self.assertEqual(error.code, 'INVALID_RESPONSE')
                    self.assertEqual(error.status, 200)
                    self.assertTrue(error.may_have_succeeded)
                    self.assertEqual(error.asset_id, 42 if name == 'upload' and not broken else expected)
                    self.assertNotIn('fixture-one-time', json.dumps(error.to_dict()))
                    self.assertEqual(len(server.requests), 1)

    def test_unsafe_upload_ids_are_never_recovered(self):
        for value in (0, -1, 1.5, 9007199254740992, '42', True, None):
            with self.subTest(value=value), Server(lambda r, n: envelope({'asset_id': value})) as server:
                with self.assertRaises(KompressrError) as caught:
                    make(server).upload_bytes(b'x', 'file.png')
                self.assertTrue(caught.exception.may_have_succeeded)
                self.assertIsNone(caught.exception.asset_id)

    def test_integral_numeric_upload_id_can_be_recovered(self):
        with Server(lambda r, n: envelope({'asset_id': 42.0})) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server).upload_bytes(b'x', 'file.png')
            self.assertEqual(caught.exception.asset_id, 42)
            self.assertTrue(caught.exception.may_have_succeeded)

    def test_mismatched_single_asset_response_retains_requested_id(self):
        with Server(lambda r, n: {**FIXTURE['deletionAccepted'], 'id': 43}) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server).delete_asset(42)
            self.assertEqual(caught.exception.asset_id, 42)
            self.assertTrue(caught.exception.may_have_succeeded)
        with Server(lambda r, n: envelope(processed(id=43))) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server).get_upload_status(42)
            self.assertFalse(caught.exception.may_have_succeeded)

    def test_response_size_limit_and_json_nonfinite(self):
        for body in (b'x' * (2 * 1024 * 1024 + 1), b'{"success":true,"data":NaN}'):
            with Server(lambda r, n: body) as server:
                with self.assertRaises(KompressrError) as caught:
                    make(server).get_asset(42)
                self.assertEqual(caught.exception.code, 'INVALID_RESPONSE')

    def test_compressed_responses_are_rejected_with_write_context(self):
        operations = [
            (lambda c: c.get_upload_status(42), envelope(processed()), False, None),
            (lambda c: c.delete_asset(42), FIXTURE['deletionAccepted'], True, 42),
            (lambda c: c.upload_bytes(b'x', 'file.png'), envelope(FIXTURE['accepted']), True, None),
        ]
        for action, payload, uncertain, asset_id in operations:
            for encoding in ('gzip', 'GZip', 'identity, gzip', 'unsupported'):
                body = json.dumps(payload).encode()
                if encoding != 'unsupported':
                    body = gzip.compress(body)
                with self.subTest(encoding=encoding, uncertain=uncertain, asset_id=asset_id), Server(lambda r, n: (200, body, {'Content-Encoding': encoding})) as server:
                    with self.assertRaises(KompressrError) as caught:
                        action(make(server, max_read_retries=5))
                    self.assertEqual(caught.exception.code, 'INVALID_RESPONSE')
                    self.assertEqual(caught.exception.status, 200)
                    self.assertEqual(caught.exception.may_have_succeeded, uncertain)
                    self.assertEqual(caught.exception.asset_id, asset_id)
                    self.assertEqual(len(server.requests), 1)
                    self.assertEqual(server.requests[0]['headers']['Accept-Encoding'], 'identity')

    def test_compression_bomb_is_rejected_before_expansion(self):
        body = gzip.compress(b'x' * (32 * 1024 * 1024))
        self.assertLess(len(body), 64 * 1024)
        with Server(lambda r, n: envelope(processed()) if n == 1 else (200, body, {'Content-Encoding': 'gzip'})) as server:
            client = make(server)
            client.get_upload_status(42)  # Exclude lazy imports from the allocation measurement.
            tracemalloc.start()
            try:
                with self.assertRaises(KompressrError) as caught:
                    client.get_upload_status(42)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertEqual(caught.exception.code, 'INVALID_RESPONSE')
            self.assertLess(peak, 8 * 1024 * 1024, f'Compressed response allocated {peak} bytes')

    def test_identity_response_and_compressed_http_error_metadata(self):
        with Server(lambda r, n: (200, envelope(processed()), {'Content-Encoding': 'Identity'})) as server:
            self.assertEqual(make(server).get_upload_status(42)['id'], 42)
        with Server(lambda r, n: (503, gzip.compress(b'{"error":"untrusted detail"}'), {'Content-Encoding': 'gzip', 'Retry-After': '5'})) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server).delete_asset(42)
            self.assertEqual(caught.exception.kind, 'api')
            self.assertEqual(caught.exception.status, 503)
            self.assertEqual(caught.exception.retry_after_ms, 5000)
            self.assertEqual(caught.exception.asset_id, 42)
            self.assertTrue(caught.exception.may_have_succeeded)
            self.assertNotIn('untrusted detail', str(caught.exception))
            self.assertEqual(len(server.requests), 1)

    def test_invalid_inputs_rejected_before_network(self):
        actions = [lambda c: c.get_asset(9007199254740992), lambda c: c.get_asset(True), lambda c: c.get_asset(1.0),
            lambda c: c.bulk_delete_assets([]), lambda c: c.bulk_delete_assets(list(range(1, 102))),
            lambda c: c.generate_private_url(42, expires_in=60.5), lambda c: c.generate_private_url(42, expires_in=59),
            lambda c: c.upload_bytes(b'x', 'file.png', data={str(i): i for i in range(6)}),
            lambda c: c.upload_bytes(b'x', 'file\n.png'), lambda c: c.upload_bytes(b'x', 'file.png', visibility='invalid'),
            lambda c: c.upload_bytes(b'x', 'file.png', data={'a': float('nan')}),
            lambda c: c.upload_bytes(b'x', 'file.png', data={'a': 10**400}),
            lambda c: c.upload_bytes(b'x', 'file.png', data={'a': 'x' * 513}),
            lambda c: c.upload_bytes(b'x', 'file.png', data={' a': 1, 'a ': 2}),
            lambda c: c.upload_bytes(b'x', 'file.png', data={'x' * 65: 1}),
            lambda c: c.upload_bytes(b'x', 'file.png', data={'a': []}),
            lambda c: c.list_uploads(data={'a': 4}), lambda c: c.list_uploads(project_id='not-a-uuid'),
            lambda c: c.list_uploads(limit=101), lambda c: c.list_uploads(status='unknown'),
            lambda c: c.wait_until_ready(42, poll_interval=31),
            lambda c: c.platform.create_user(''), lambda c: c.platform.create_upload_key(USER_ID, 'Runtime', scopes=['admin']),
            lambda c: c.platform.create_upload_key(USER_ID, 'Runtime', expires_at='2020-01-01T00:00:00Z'),
            lambda c: c.platform.create_upload_key(USER_ID, 'Runtime', allowed_asset_types=[True]),
            lambda c: c.platform.rotate_upload_key(USER_ID, 'not-a-uuid'),
            lambda c: c.upload_stream(io.StringIO('x'), 'file.png')]
        with Server(lambda r, n: {}) as server:
            client = make(server)
            for index, action in enumerate(actions):
                with self.subTest(index=index), self.assertRaises(KompressrError) as caught:
                    action(client)
                self.assertEqual(caught.exception.code, 'INVALID_ARGUMENT')
                self.assertFalse(caught.exception.may_have_succeeded)
            self.assertEqual(server.requests, [])

    def test_platform_all_routes_one_time_secrets_and_no_delete_default(self):
        responses = [
            {'success': True, 'created': True, 'project_user': USER},
            {'success': True, 'project_users': [USER], 'page': 1, 'limit': 20, 'total': 1, 'project_active_count': 1, 'org_active_count': 2, 'usage_period': {'start': '2030-01-01', 'end': '2030-02-01'}},
            {'success': True, 'project_user': {**USER, 'display_name': 'Updated'}},
            ISSUED,
            {'success': True, 'upload_keys': [KEY], 'page': 1, 'limit': 20, 'total': 1},
            {'success': True, 'id': KEY_ID, 'key_id': KEY_ID, 'api_key': 'fixture-replacement'},
            {'success': True},
            {'success': True, 'project_user': {**USER, 'status': 'suspended'}},
            {'success': True, 'project_user': USER},
        ]
        with Server(lambda r, n: responses[n - 1]) as server:
            platform = PlatformClient(api_key='fixture-key', api_base_url=server.origin)
            self.assertTrue(platform.create_user('customer-1', metadata={'tier': 'example'})['created'])
            self.assertEqual(platform.list_users()['org_active_count'], 2)
            self.assertEqual(platform.update_user(USER_ID, display_name='Updated')['display_name'], 'Updated')
            self.assertEqual(platform.create_upload_key(USER_ID, 'Runtime')['api_key'], 'fixture-one-time')
            self.assertEqual(json.loads(server.requests[3]['body']), {'name': 'Runtime'})
            self.assertNotIn('delete', platform.list_upload_keys(USER_ID)['data'][0]['scopes'])
            self.assertEqual(platform.rotate_upload_key(USER_ID, KEY_ID)['api_key'], 'fixture-replacement')
            self.assertIsNone(platform.revoke_upload_key(USER_ID, KEY_ID))
            self.assertEqual(platform.suspend_user(USER_ID)['status'], 'suspended')
            self.assertEqual(platform.reactivate_user(USER_ID)['status'], 'active')
            routes = [r['path'].split('?')[0] for r in server.requests]
            base = '/api/platform/project-users'
            self.assertEqual(routes, [base, base, base + '/' + USER_ID, base + '/' + USER_ID + '/upload-keys', base + '/' + USER_ID + '/upload-keys', base + '/' + USER_ID + '/upload-keys/' + KEY_ID + '/rotate', base + '/' + USER_ID + '/upload-keys/' + KEY_ID + '/revoke', base + '/' + USER_ID + '/suspend', base + '/' + USER_ID + '/reactivate'])
            self.assertEqual([r['method'] for r in server.requests], ['POST', 'GET', 'PATCH', 'POST', 'GET', 'POST', 'POST', 'POST', 'POST'])

    def test_platform_explicit_restrictions_and_counter_validation(self):
        with Server(lambda r, n: ISSUED) as server:
            make(server).platform.create_upload_key(USER_ID, 'Runtime', scopes=['upload', 'status'], allowed_visibility='private', allowed_asset_types=[1], expires_at='2099-01-01T00:00:00Z')
            body = json.loads(server.requests[0]['body'])
            self.assertEqual(body['scopes'], ['upload', 'status'])
            self.assertEqual(body['allowed_visibility'], 'private')
            self.assertEqual(body['allowed_asset_types'], [1])
        with Server(lambda r, n: {'success': True, 'project_users': [], 'page': 1, 'limit': 20, 'total': 0, 'project_active_count': 'wrong', 'org_active_count': 1}) as server:
            with self.assertRaises(KompressrError):
                make(server).platform.list_users()

    def test_empty_scopes_rejected_while_omission_keeps_defaults(self):
        with Server(lambda r, n: ISSUED) as server:
            platform = make(server).platform
            with self.assertRaises(KompressrError) as caught:
                platform.create_upload_key(USER_ID, 'Runtime', scopes=[])
            self.assertEqual(caught.exception.code, 'INVALID_ARGUMENT')
            self.assertFalse(caught.exception.may_have_succeeded)
            self.assertEqual(server.requests, [])
            for options in ({}, {'scopes': None}, {'scopes': ['status']}):
                platform.create_upload_key(USER_ID, 'Runtime', **options)
            self.assertNotIn('scopes', json.loads(server.requests[0]['body']))
            self.assertNotIn('scopes', json.loads(server.requests[1]['body']))
            self.assertEqual(json.loads(server.requests[2]['body'])['scopes'], ['status'])


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_scopes_rejected_before_async_dispatch(self):
        with Server(lambda r, n: ISSUED) as server:
            platform = AsyncPlatformClient(api_key='fixture-key', api_base_url=server.origin)
            with self.assertRaises(KompressrError) as caught:
                await platform.create_upload_key(USER_ID, 'Runtime', scopes=[])
            self.assertEqual(caught.exception.code, 'INVALID_ARGUMENT')
            self.assertFalse(caught.exception.may_have_succeeded)
            self.assertEqual(server.requests, [])

    async def test_native_cancellation_retains_retry_delay(self):
        for phase in ('response_body', 'compressed_backoff', 'json_backoff'):
            with self.subTest(phase=phase):
                headers_sent, release = threading.Event(), threading.Event()
                with Server(lambda r, n: lambda handler: retry_context_response(handler, phase, headers_sent, release)) as server:
                    client = AsyncKompressrClient(api_key='fixture-key', api_base_url=server.origin, max_read_retries=1)
                    task = asyncio.create_task(client.delete_asset(42) if phase == 'response_body' else client.get_upload_status(42))
                    try:
                        async with asyncio.timeout(2):
                            while not headers_sent.is_set():
                                await asyncio.sleep(.005)
                        await asyncio.sleep(.03)
                        task.cancel()
                        with self.assertRaises(KompressrCancelledError) as caught:
                            await task
                    finally:
                        release.set()
                        if not task.done():
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
                    error = caught.exception
                    self.assertEqual(error.code, 'REQUEST_CANCELLED')
                    self.assertEqual(error.status, 200 if phase == 'response_body' else 503)
                    self.assertEqual(error.retry_after_ms, 5000)
                    self.assertEqual(error.asset_id, 42 if phase == 'response_body' else None)
                    self.assertEqual(error.may_have_succeeded, phase == 'response_body')
                    self.assertTrue(task.cancelled())
                    self.assertEqual(len(server.requests), 1)

    async def test_async_methods_and_iteration(self):
        with Server(lambda r, n: {'success': True, 'data': [processed()], 'page': 1, 'limit': 20, 'total': 1}) as server:
            client = AsyncKompressrClient(api_key='fixture-key', api_base_url=server.origin, project_id=PROJECT)
            rows = [row async for row in client.iterate_uploads()]
            self.assertEqual(rows[0]['id'], 42)
        with Server(lambda r, n: envelope(FIXTURE['accepted'])) as server:
            client = AsyncKompressrClient(api_key='fixture-key', api_base_url=server.origin)
            self.assertEqual((await client.upload_bytes(b'x', 'file.png'))['id'], 42)
        with Server(lambda r, n: {'success': True, 'created': True, 'project_user': USER}) as server:
            self.assertTrue((await AsyncPlatformClient(api_key='fixture-key', api_base_url=server.origin).create_user('customer-1'))['created'])

    async def test_native_task_cancel_keeps_cancelled_semantics_and_write_context(self):
        with Server(lambda r, n: slow_body) as server:
            client = AsyncKompressrClient(api_key='fixture-key', api_base_url=server.origin)
            task = asyncio.create_task(client.delete_asset(42))
            while not server.arrived.is_set():
                await asyncio.sleep(.005)
            task.cancel()
            with self.assertRaises(KompressrCancelledError) as caught:
                await task
            self.assertTrue(task.cancelled())
            self.assertTrue(caught.exception.may_have_succeeded)
            self.assertEqual(caught.exception.asset_id, 42)
            self.assertEqual(caught.exception.code, 'REQUEST_CANCELLED')
            self.assertEqual(len(server.requests), 1)

    async def test_native_wait_cancel_has_wait_code(self):
        with Server(lambda r, n: slow_body) as server:
            client = AsyncKompressrClient(api_key='fixture-key', api_base_url=server.origin)
            task = asyncio.create_task(client.wait_until_ready(42))
            while not server.arrived.is_set():
                await asyncio.sleep(.005)
            task.cancel()
            with self.assertRaises(KompressrCancelledError) as caught:
                await task
            self.assertTrue(task.cancelled())
            self.assertEqual(caught.exception.code, 'WAIT_CANCELLED')
            self.assertEqual(caught.exception.asset_id, 42)
            self.assertFalse(caught.exception.may_have_succeeded)

    async def test_sync_inside_event_loop_fails_before_request(self):
        with Server(lambda r, n: {}) as server:
            with self.assertRaises(KompressrError) as caught:
                make(server).get_asset(42)
            self.assertEqual(caught.exception.code, 'INVALID_ARGUMENT')
            self.assertEqual(server.requests, [])


if __name__ == '__main__':
    unittest.main()
