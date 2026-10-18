"""Upload privately by default, save the ID, then print an authorized delivery link."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from kompressr import KompressrClient, KompressrError


def save(handle, client, asset_id, state):
    handle.seek(0)
    json.dump({'asset_id': asset_id, 'api_base_url': client.api_base_url, 'state': state}, handle)
    handle.truncate()
    handle.flush()
    os.fsync(handle.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', nargs='?', type=Path)
    parser.add_argument('--receipt', required=True, type=Path, help='New receipt path for upload, existing path for resume')
    parser.add_argument('--resume', action='store_true', help='Check the saved ID without uploading')
    parser.add_argument('--public', action='store_true', help='Upload for public delivery instead of private delivery')
    args = parser.parse_args()
    if args.resume == bool(args.file):
        parser.error('Supply a file for a new upload, or --resume with no file.')
    key = os.environ.get('KOMPRESSR_API_KEY')
    if not key:
        parser.error('Set KOMPRESSR_API_KEY in your server environment.')
    files = KompressrClient(api_key=key, api_base_url=os.environ.get('KOMPRESSR_API_BASE_URL', 'https://kompressr.com'),
        upload_base_url=os.environ.get('KOMPRESSR_UPLOAD_BASE_URL'))
    if args.resume:
        receipt = json.loads(args.receipt.read_text())
        asset_id = receipt.get('asset_id')
        if type(asset_id) is not int or asset_id < 1 or receipt.get('api_base_url') != files.api_base_url:
            parser.error('The receipt needs a saved asset ID and the same configured management origin.')
    else:
        # Reserve storage before a write so a receipt cannot overwrite an older upload.
        descriptor = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as handle:
            save(handle, files, None, 'not_accepted')
            try:
                accepted = files.upload_file(args.file, visibility='public' if args.public else 'private')
            except KompressrError as error:
                save(handle, files, error.asset_id, 'uncertain' if error.may_have_succeeded else 'failed')
                raise
            asset_id = accepted['id']
            save(handle, files, asset_id, 'accepted')
    ready = files.wait_until_ready(asset_id)
    # This is intentional terminal output; do not route private links into routine logs.
    link = files.generate_private_url(asset_id)['private_url'] if ready['visibility'] == 'private' else ready['cdn_url']
    print(link)


if __name__ == '__main__':
    try:
        main()
    except KompressrError as error:
        print(json.dumps(error.to_dict()), file=sys.stderr)
        sys.exit(1)
