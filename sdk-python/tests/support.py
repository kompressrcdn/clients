"""A real local HTTP fixture; no account or external service is contacted."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURE = json.loads(Path(__file__).with_name('file-lifecycle.json').read_text())
PROJECT = FIXTURE['projectId']
USER_ID = '660e8400-e29b-41d4-a716-446655440002'
KEY_ID = '660e8400-e29b-41d4-a716-446655440003'
USER = {'id': USER_ID, 'project_id': PROJECT, 'customer_user_id': 'customer-1', 'status': 'active'}
KEY = {'id': KEY_ID, 'key_id': KEY_ID, 'project_id': PROJECT, 'project_user_id': USER_ID,
       'name': 'Runtime', 'scopes': ['upload', 'status', 'list', 'private_url'], 'allowed_visibility': 'both'}
ISSUED = {'success': True, 'id': KEY_ID, 'key_id': KEY_ID, 'api_key': 'fixture-one-time', 'upload_key': KEY}


def envelope(value):
    return {'success': True, 'data': value}


def processed(**changes):
    return {**FIXTURE['processed'], **changes}


class Server:
    def __init__(self, responder, *, capture_body=True):
        self.requests = []
        self.errors = []
        self.responder = responder
        self.arrived = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_):
                pass

            def handle_request(self):
                try:
                    size = int(self.headers.get('Content-Length', 0))
                    if capture_body:
                        body = self.rfile.read(size)
                    else:
                        remaining = size
                        while remaining:
                            chunk = self.rfile.read(min(65536, remaining))
                            if not chunk:
                                raise RuntimeError('Truncated request')
                            remaining -= len(chunk)
                        body = b''
                    request = {'method': self.command, 'path': self.path, 'headers': self.headers, 'body': body, 'bytes_received': size}
                    outer.requests.append(request)
                    outer.arrived.set()
                    response = outer.responder(request, len(outer.requests))
                    if callable(response):
                        response(self)
                        return
                    status, payload, headers = response if isinstance(response, tuple) else (200, response, {})
                    payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(payload)))
                    for key, value in headers.items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(payload)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as error:
                    outer.errors.append(error)
                    self.close_connection = True

            do_GET = handle_request
            do_POST = handle_request
            do_DELETE = handle_request
            do_PATCH = handle_request

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        if self.errors:
            raise self.errors[0]
