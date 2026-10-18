from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from support import FIXTURE, ISSUED, USER, Server, envelope, processed

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


def run_example(server, script, *arguments):
    environment = dict(os.environ, KOMPRESSR_API_KEY='fixture-key', KOMPRESSR_API_BASE_URL=server.origin)
    environment.pop('KOMPRESSR_UPLOAD_BASE_URL', None)
    return subprocess.run([sys.executable, str(EXAMPLES / script), *map(str, arguments)], env=environment, capture_output=True, text=True, timeout=5)


class ExampleTests(unittest.TestCase):
    def test_private_receipt_saved_before_wait_and_resume_has_no_upload(self):
        private = {k: value for k, value in processed(visibility='private', can_generate_private_url=True).items() if k != 'cdn_url'}
        signed = {'asset_id': 42, 'variant': 'webp', 'private_url': 'https://cdn.example/private?signature=fixture', 'expires_at': '2030-01-01T00:00:00Z', 'expires_in': 3600}
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'image.png'
            source.write_bytes(b'fixture')
            receipt = Path(temporary) / 'receipt.json'
            def respond(request, _):
                if request['path'] == '/api/upload':
                    return envelope({**{k: value for k, value in FIXTURE['accepted'].items() if k != 'cdn_url'}, 'visibility': 'private'})
                self.assertEqual(json.loads(receipt.read_text())['asset_id'], 42)
                return envelope(signed if request['path'].endswith('/private-url') else private)
            with Server(respond) as server:
                first = run_example(server, 'upload.py', source, '--receipt', receipt)
                self.assertEqual(first.returncode, 0, first.stderr)
                self.assertIn(signed['private_url'], first.stdout)
                self.assertNotIn('private_url', receipt.read_text())
                self.assertNotIn('fixture-key', receipt.read_text())
                second = run_example(server, 'upload.py', '--resume', '--receipt', receipt)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(sum(r['path'] == '/api/upload' for r in server.requests), 1)

    def test_receipt_collision_prevents_upload(self):
        with tempfile.TemporaryDirectory() as temporary, Server(lambda r, n: {}) as server:
            source = Path(temporary) / 'image.png'
            source.write_bytes(b'fixture')
            receipt = Path(temporary) / 'receipt.json'
            receipt.write_text('preserve me')
            result = run_example(server, 'upload.py', source, '--receipt', receipt)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(receipt.read_text(), 'preserve me')
            self.assertEqual(server.requests, [])

    def test_malformed_upload_preserves_safe_id_and_unknown_outcome(self):
        for body, expected in ((envelope({'asset_id': 42}), 42), (b'{broken', None)):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary, Server(lambda r, n: body) as server:
                source = Path(temporary) / 'image.png'
                source.write_bytes(b'fixture')
                receipt = Path(temporary) / 'receipt.json'
                result = run_example(server, 'upload.py', source, '--receipt', receipt)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(receipt.read_text())['asset_id'], expected)
                self.assertEqual(json.loads(receipt.read_text())['state'], 'uncertain')
                self.assertNotIn('fixture-key', result.stderr)
                self.assertEqual(len(server.requests), 1)

    def test_platform_one_time_key_written_without_output(self):
        responses = [{'success': True, 'created': True, 'project_user': USER}, ISSUED]
        with tempfile.TemporaryDirectory() as temporary, Server(lambda r, n: responses[n - 1]) as server:
            destination = Path(temporary) / 'runtime.json'
            result = run_example(server, 'platform.py', 'customer-1', '--key-file', destination)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(destination.read_text())['api_key'], ISSUED['api_key'])
            self.assertNotIn(ISSUED['api_key'], result.stdout + result.stderr)
            self.assertNotIn('delete', json.loads(server.requests[1]['body'])['scopes'])
            if os.name != 'nt':
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
