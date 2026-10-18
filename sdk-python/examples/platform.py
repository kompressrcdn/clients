"""Provision an identity and store its one-time key in a new private file."""
from __future__ import annotations

import argparse
import json
import os
import sys

from kompressr import KompressrClient, KompressrError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('customer_user_id', help='Stable identity from your authenticated application')
    parser.add_argument('--key-file', required=True, help='New private output file outside the repository')
    args = parser.parse_args()
    key = os.environ.get('KOMPRESSR_API_KEY')
    if not key:
        parser.error('Set KOMPRESSR_API_KEY to your project credential on a trusted backend.')
    files = KompressrClient(api_key=key, api_base_url=os.environ.get('KOMPRESSR_API_BASE_URL', 'https://kompressr.com'),
        upload_base_url=os.environ.get('KOMPRESSR_UPLOAD_BASE_URL'))
    # Reserve the secret destination before issuing a nonrecoverable raw key.
    descriptor = os.open(args.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as destination:
        user = files.platform.create_user(args.customer_user_id)['project_user']
        issued = files.platform.create_upload_key(user['id'], 'Application runtime',
            scopes=['upload', 'status', 'list', 'private_url'], allowed_visibility='private')
        json.dump({'project_user_id': user['id'], 'key_record_id': issued['id'], 'api_key': issued['api_key']}, destination)
        destination.flush()
        os.fsync(destination.fileno())
    print('Scoped key saved. Give it only to the authenticated runtime for this identity.')
    # In production use an encrypted credential store instead of a local file.
    # Later: rotated = files.platform.rotate_upload_key(user['id'], issued['id'])
    # Persist rotated['api_key'] securely before switching the runtime to it.
    # To revoke: files.platform.revoke_upload_key(user['id'], issued['id'])
    # To suspend all keys: files.platform.suspend_user(user['id'])
    # Reactivation does not restore revoked keys; create a new key afterwards.


if __name__ == '__main__':
    try:
        main()
    except KompressrError as error:
        print(json.dumps(error.to_dict()), file=sys.stderr)
        sys.exit(1)
