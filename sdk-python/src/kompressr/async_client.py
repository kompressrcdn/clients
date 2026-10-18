"""Asyncio clients. Methods never escalate supplied credentials or replay writes."""
from __future__ import annotations

import asyncio
import io
import os
import random
import re
import stat
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Literal, cast
from urllib.parse import urlencode

from . import _validation as v
from ._transport import CancellationToken, Transport, bounded
from .errors import KompressrCancelledError, KompressrError, invalid, invalid_response
from .types import AssetState, BulkDeletion, CreatedUser, CustomerData, IssuedKey, Page, PrivateUrl, ProjectUser, ProjectUserPage, UploadAccepted, UploadAsset, UploadKey, UploadScope, VideoQuality, Visibility, DeletionStatus


def _pagination(page: int, limit: int) -> dict[str, str]:
    return {'page': str(v.positive(page, 'page', 2147483647)), 'limit': str(v.positive(limit, 'limit', 100))}


def _filename(filename: str) -> str:
    if not isinstance(filename, str) or not filename.strip() or any(ord(c) < 32 or ord(c) == 127 for c in filename):
        invalid('Supply a nonempty filename without control characters.')
    try:
        filename.encode('utf-8')
    except UnicodeEncodeError:
        invalid('Filename must contain valid UTF-8.')
    # A caller-supplied path must never become a multipart path.
    name = filename.replace('\\', '/').rsplit('/', 1)[-1]
    if not name.strip():
        invalid('Supply a nonempty filename.')
    return name


class AsyncPlatformClient:
    """Project identity and key administration using server-enforced authority."""

    def __init__(self, *, api_key: str, api_base_url: str = 'https://kompressr.com',
                 upload_base_url: str | None = None, request_timeout: float = 30,
                 upload_timeout: float = 600, max_read_retries: int = 2) -> None:
        self._transport = Transport(api_key=api_key, api_base_url=api_base_url, upload_base_url=upload_base_url,
            request_timeout=request_timeout, upload_timeout=upload_timeout, max_read_retries=max_read_retries)

    async def list_users(self, *, page: int = 1, limit: int = 20, timeout: float | None = None,
                         cancel: CancellationToken | None = None) -> ProjectUserPage:
        def parse(value: Any) -> ProjectUserPage:
            response = v.success(value)
            result: Any = v.page(response, v.project_user, 'project_users')
            for key in ('project_active_count', 'org_active_count'):
                count = v.integer(response.get(key))
                if count < 0:
                    invalid_response()
                result[key] = count
            if 'usage_period' in response:
                period = v.record(response['usage_period'])
                if any(not re.fullmatch(r'\d{4}-\d{2}-\d{2}', v.string(period.get(k))) for k in ('start', 'end')):
                    invalid_response()
                result['usage_period'] = period
            return cast(ProjectUserPage, result)
        return await self._transport.request('/api/platform/project-users?' + urlencode(_pagination(page, limit)), parse=parse, timeout=timeout, cancel=cancel)

    async def create_user(self, customer_user_id: str, *, display_name: str | None = None,
                          metadata: CustomerData | None = None, timeout: float | None = None,
                          cancel: CancellationToken | None = None) -> CreatedUser:
        v.text_input(customer_user_id, 'customer_user_id', 256)
        body = {'customer_user_id': customer_user_id, **self._user_fields(display_name, metadata)}
        def parse(value: Any) -> CreatedUser:
            response = v.success(value)
            if type(response.get('created')) is not bool:
                invalid_response()
            return {'created': response['created'], 'project_user': v.project_user(response.get('project_user'))}
        return await self._transport.request('/api/platform/project-users', method='POST', body=body, parse=parse, timeout=timeout, cancel=cancel)

    async def update_user(self, project_user_id: str, *, display_name: str | None = None,
                          metadata: CustomerData | None = None, timeout: float | None = None,
                          cancel: CancellationToken | None = None) -> ProjectUser:
        return await self._transport.request(self._path(project_user_id), method='PATCH', body=self._user_fields(display_name, metadata),
            parse=lambda x: v.project_user(v.success(x).get('project_user')), timeout=timeout, cancel=cancel)

    async def suspend_user(self, project_user_id: str, *, timeout: float | None = None,
                           cancel: CancellationToken | None = None) -> ProjectUser:
        return await self._transport.request(self._path(project_user_id) + '/suspend', method='POST',
            parse=lambda x: v.project_user(v.success(x).get('project_user')), timeout=timeout, cancel=cancel)

    async def reactivate_user(self, project_user_id: str, *, timeout: float | None = None,
                              cancel: CancellationToken | None = None) -> ProjectUser:
        return await self._transport.request(self._path(project_user_id) + '/reactivate', method='POST',
            parse=lambda x: v.project_user(v.success(x).get('project_user')), timeout=timeout, cancel=cancel)

    async def list_upload_keys(self, project_user_id: str, *, page: int = 1, limit: int = 20,
                               timeout: float | None = None, cancel: CancellationToken | None = None) -> Page[UploadKey]:
        return await self._transport.request(self._path(project_user_id) + '/upload-keys?' + urlencode(_pagination(page, limit)),
            parse=lambda x: v.page(v.success(x), v.upload_key, 'upload_keys'), timeout=timeout, cancel=cancel)

    async def create_upload_key(self, project_user_id: str, name: str, *, scopes: list[UploadScope] | None = None,
                                allowed_visibility: Literal['public', 'private', 'both'] | None = None,
                                allowed_asset_types: list[int] | None = None, expires_at: str | None = None,
                                timeout: float | None = None, cancel: CancellationToken | None = None) -> IssuedKey:
        v.text_input(name, 'name', 120)
        body: dict[str, Any] = {'name': name}
        if scopes is not None:
            if scopes == []:
                invalid('scopes must not be empty; omit scopes to use server defaults.')
            if not isinstance(scopes, list) or any(s not in v.SCOPES for s in scopes):
                invalid('Unsupported upload scope.')
            body['scopes'] = scopes
        if allowed_visibility is not None:
            body['allowed_visibility'] = v.enum_input(allowed_visibility, ('public', 'private', 'both'), 'allowed_visibility')
        if allowed_asset_types is not None:
            if not isinstance(allowed_asset_types, list):
                invalid('allowed_asset_types must be a list of positive integers.')
            for item in allowed_asset_types:
                v.positive(item, 'asset type')
            body['allowed_asset_types'] = allowed_asset_types
        if expires_at is not None:
            try:
                expiry = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                    raise ValueError
            except (TypeError, ValueError, AttributeError):
                invalid('expires_at must be a future ISO timestamp with a timezone.')
            body['expires_at'] = expires_at
        return await self._transport.request(self._path(project_user_id) + '/upload-keys', method='POST', body=body,
            parse=self._issued, timeout=timeout, cancel=cancel)

    async def rotate_upload_key(self, project_user_id: str, key_id: str, *, timeout: float | None = None,
                                cancel: CancellationToken | None = None) -> IssuedKey:
        return await self._transport.request(self._path(project_user_id) + '/upload-keys/' + v.uuid(key_id, 'key_id') + '/rotate', method='POST',
            parse=self._issued, timeout=timeout, cancel=cancel)

    async def revoke_upload_key(self, project_user_id: str, key_id: str, *, timeout: float | None = None,
                                cancel: CancellationToken | None = None) -> None:
        def parse(value: Any) -> None:
            v.success(value)
        await self._transport.request(self._path(project_user_id) + '/upload-keys/' + v.uuid(key_id, 'key_id') + '/revoke', method='POST',
            parse=parse, timeout=timeout, cancel=cancel)

    @staticmethod
    def _path(project_user_id: str) -> str:
        return '/api/platform/project-users/' + v.uuid(project_user_id, 'project_user_id')

    @staticmethod
    def _user_fields(display_name: str | None, metadata: CustomerData | None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if display_name is not None:
            body['display_name'] = v.text_input(display_name, 'display_name', 120, empty=True)
        if metadata is not None:
            body['metadata'] = v.customer_data(metadata, 8192)
        return body

    @staticmethod
    def _issued(value: Any) -> IssuedKey:
        response = v.success(value)
        result: IssuedKey = {'id': v.string(response.get('id')), 'key_id': v.string(response.get('key_id')), 'api_key': v.string(response.get('api_key'))}
        if 'upload_key' in response:
            result['upload_key'] = v.upload_key(response['upload_key'])
        return result


class AsyncKompressrClient:
    """Async file client. Timeout values use seconds; results are typed dictionaries."""

    def __init__(self, *, api_key: str, project_id: str | None = None,
                 api_base_url: str = 'https://kompressr.com', upload_base_url: str | None = None,
                 request_timeout: float = 30, upload_timeout: float = 600, max_read_retries: int = 2) -> None:
        self._transport = Transport(api_key=api_key, api_base_url=api_base_url, upload_base_url=upload_base_url,
            request_timeout=request_timeout, upload_timeout=upload_timeout, max_read_retries=max_read_retries)
        self.api_base_url = self._transport.api_base_url
        self.upload_base_url = self._transport.upload_base_url
        self._project_id = project_id
        self.platform = AsyncPlatformClient(api_key=api_key, api_base_url=api_base_url, upload_base_url=upload_base_url,
            request_timeout=request_timeout, upload_timeout=upload_timeout, max_read_retries=max_read_retries)

    async def upload_file(self, path: str | os.PathLike[str], *, visibility: Visibility | None = None,
                          quality: VideoQuality | None = None, data: CustomerData | None = None,
                          private_url_expires_in: int | None = None, timeout: float | None = None,
                          cancel: CancellationToken | None = None) -> UploadAccepted:
        if not isinstance(path, (str, os.PathLike)) or not str(path).strip():
            invalid('Supply a file path.')
        # Only regular files have predictable local reads and a known length.
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError('Upload path must name a regular file.')
        with file_path.open('rb') as stream:
            return await self.upload_stream(stream, file_path.name, visibility=visibility, quality=quality, data=data,
                private_url_expires_in=private_url_expires_in, timeout=timeout, cancel=cancel)

    async def upload_bytes(self, content: bytes | bytearray | memoryview, filename: str, *,
                           visibility: Visibility | None = None, quality: VideoQuality | None = None,
                           data: CustomerData | None = None, private_url_expires_in: int | None = None,
                           timeout: float | None = None, cancel: CancellationToken | None = None) -> UploadAccepted:
        if not isinstance(content, (bytes, bytearray, memoryview)):
            invalid('content must be bytes, bytearray or memoryview.')
        return await self.upload_stream(io.BytesIO(bytes(content)), filename, visibility=visibility, quality=quality,
            data=data, private_url_expires_in=private_url_expires_in, timeout=timeout, cancel=cancel)

    async def upload_stream(self, stream: BinaryIO, filename: str, *, visibility: Visibility | None = None,
                            quality: VideoQuality | None = None, data: CustomerData | None = None,
                            private_url_expires_in: int | None = None, timeout: float | None = None,
                            cancel: CancellationToken | None = None) -> UploadAccepted:
        name = _filename(filename)
        if type(stream) not in (io.BytesIO, io.BufferedReader, io.FileIO):
            invalid('stream must be an unmodified BytesIO or a standard regular binary file; custom readers are unsupported.')
        try:
            if type(stream) is not io.BytesIO and not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                invalid('stream must be a regular file; pipes and sockets are unsupported.')
            if not stream.seekable() or not isinstance(stream.read(0), bytes):
                invalid('stream must be a seekable binary file or BytesIO.')
            stream.seek(0)
        except (OSError, ValueError, TypeError):
            invalid('stream must be an open seekable binary file or BytesIO.')
        fields: dict[str, str] = {}
        if visibility is not None:
            fields['visibility'] = v.enum_input(visibility, ('public', 'private'), 'visibility')
        if quality is not None:
            fields['kmp-quality'] = v.enum_input(quality, ('480p', '720p', '1080p', '4k'), 'quality')
        if private_url_expires_in is not None:
            ttl = v.positive(private_url_expires_in, 'private_url_expires_in', 604800)
            if ttl < 60:
                invalid('Private URL lifetime must be at least 60 seconds.')
            fields['private_url_expires_in'] = str(ttl)
        if data is not None:
            fields['data'] = v.json_text(v.customer_data(data))
        def parse(value: Any) -> UploadAccepted:
            response = v.success(value)
            result = v.upload_accepted(response.get('data'))
            if isinstance(response.get('warning'), str):
                result['warning'] = response['warning']
            return result
        return await self._transport.request('/api/upload', method='POST', fields=fields, file=(name, stream), parse=parse,
            upload=True, recover_upload_id=True, timeout=timeout, cancel=cancel)

    async def get_upload_status(self, asset_id: int, *, timeout: float | None = None,
                                cancel: CancellationToken | None = None) -> UploadAsset:
        v.positive(asset_id, 'asset_id')
        def parse(value: Any) -> UploadAsset:
            result = v.upload_asset(v.data(value))
            if result['id'] != asset_id:
                invalid_response('API returned a different asset ID.')
            return result
        return await self._transport.request(f'/api/upload/{asset_id}/status', parse=parse, timeout=timeout, cancel=cancel)

    async def wait_until_ready(self, asset_id: int, *, timeout: float = 120, poll_interval: float = 2,
                               cancel: CancellationToken | None = None) -> UploadAsset:
        v.positive(asset_id, 'asset_id')
        v.seconds(timeout)
        v.seconds(poll_interval, 'poll_interval')
        if poll_interval > 30:
            invalid('poll_interval must not exceed 30 seconds.')
        if cancel is not None and not isinstance(cancel, CancellationToken):
            invalid('cancel must be a CancellationToken.')
        async def poll() -> UploadAsset:
            while True:
                result = await self.get_upload_status(asset_id, cancel=cancel)
                if result['deletion_status'] != 'active':
                    raise KompressrError('The asset is being deleted or has been deleted.', kind='processing', code='ASSET_DELETED', asset_id=asset_id)
                if result['status'] == 'processed':
                    if result['visibility'] == 'public' and not result.get('cdn_url'):
                        invalid_response('Processed public asset has no delivery URL.')
                    if result['visibility'] == 'private' and not result['can_generate_private_url']:
                        invalid_response('Processed private asset cannot generate a delivery link.')
                    return result
                if result['status'] not in ('pending', 'processing'):
                    raise KompressrError(f"Asset processing ended with status {result['status']}.", kind='processing', code='PROCESSING_FAILED', asset_id=asset_id)
                await asyncio.sleep(min(30, poll_interval + random.random() * min(poll_interval * .1, .25)))
        try:
            return await bounded(poll(), timeout, cancel)
        except TimeoutError:
            raise KompressrError('Waiting timed out; resume status checks with the saved asset ID.', kind='timeout', code='WAIT_TIMEOUT', asset_id=asset_id) from None
        except KompressrError as error:
            error.asset_id = asset_id
            if error.kind == 'cancelled':
                error.code = 'WAIT_CANCELLED'
            raise
        except asyncio.CancelledError:
            raise KompressrCancelledError(code='WAIT_CANCELLED', asset_id=asset_id) from None

    async def generate_private_url(self, asset_id: int, *, expires_in: int = 3600,
                                   variant: Literal['webp', 'avif'] = 'webp', timeout: float | None = None,
                                   cancel: CancellationToken | None = None) -> PrivateUrl:
        v.positive(asset_id, 'asset_id')
        v.positive(expires_in, 'expires_in', 604800)
        if expires_in < 60:
            invalid('Private URL lifetime must be at least 60 seconds.')
        v.enum_input(variant, ('webp', 'avif'), 'variant')
        def parse(value: Any) -> PrivateUrl:
            result = v.private_url(v.data(value))
            if result['asset_id'] != asset_id:
                invalid_response('API returned a different asset ID.')
            return result
        return await self._transport.request(f'/api/upload/{asset_id}/private-url', method='POST',
            body={'expires_in': expires_in, 'variant': variant}, parse=parse, asset_id=asset_id, timeout=timeout, cancel=cancel)

    async def list_uploads(self, *, project_id: str | None = None, page: int = 1, limit: int = 20,
                           visibility: Visibility | None = None, external_id: str | None = None,
                           data: dict[str, str] | None = None, status: str | int | None = None,
                           deletion_status: DeletionStatus | None = None, timeout: float | None = None,
                           cancel: CancellationToken | None = None) -> Page[UploadAsset]:
        params = _pagination(page, limit)
        project = project_id if project_id is not None else self._project_id
        if not project:
            invalid('Upload listing requires project_id; other file operations need only an API key.')
        params['project_id'] = v.uuid(project, 'project_id')
        if visibility is not None:
            params['visibility'] = v.enum_input(visibility, ('public', 'private'), 'visibility')
        if deletion_status is not None:
            params['deletion_status'] = v.enum_input(deletion_status, v.DELETION, 'deletion_status')
        if status is not None:
            states = {'pending': 1, 'processing': 2, 'processed': 3, 'failed': 4, 'unprocessable': 5}
            selected = states.get(status) if isinstance(status, str) else status
            params['status'] = str(v.positive(selected, 'status', 6))
        if external_id is not None:
            try:
                valid_external_id = isinstance(external_id, str) and len(external_id.encode('utf-8')) <= 512
            except UnicodeEncodeError:
                valid_external_id = False
            if not valid_external_id:
                invalid('external_id supports at most 512 valid UTF-8 bytes.')
            params['external_id'] = external_id
        if data is not None:
            for key, item in v.customer_data(data).items():
                if not isinstance(item, str):
                    invalid('Data filter values must be strings.')
                params['data.' + key] = item
        return await self._transport.request('/api/uploads?' + urlencode(params),
            parse=lambda x: v.page(v.success(x), v.upload_asset), timeout=timeout, cancel=cancel)

    async def iterate_uploads(self, *, project_id: str | None = None, page: int = 1, limit: int = 20,
                              visibility: Visibility | None = None, external_id: str | None = None,
                              data: dict[str, str] | None = None, status: str | int | None = None,
                              deletion_status: DeletionStatus | None = None, timeout: float | None = None,
                              cancel: CancellationToken | None = None) -> AsyncIterator[UploadAsset]:
        current = page
        while True:
            result = await self.list_uploads(project_id=project_id, page=current, limit=limit, visibility=visibility,
                external_id=external_id, data=data, status=status, deletion_status=deletion_status, timeout=timeout, cancel=cancel)
            if result['page'] != current or len(result['data']) > result['limit']:
                invalid_response('Invalid pagination response.')
            for row in result['data']:
                yield row
            if not result['data'] or result['page'] * result['limit'] >= result['total']:
                return
            current += 1

    async def list_assets(self, *, page: int = 1, limit: int = 20, deletion_status: DeletionStatus | None = None,
                          timeout: float | None = None, cancel: CancellationToken | None = None) -> Page[AssetState]:
        params = _pagination(page, limit)
        if deletion_status is not None:
            params['deletion_status'] = v.enum_input(deletion_status, v.DELETION, 'deletion_status')
        return await self._transport.request('/api/assets?' + urlencode(params), parse=lambda x: v.page(x, v.asset_state), timeout=timeout, cancel=cancel)

    async def get_asset(self, asset_id: int, *, timeout: float | None = None,
                        cancel: CancellationToken | None = None) -> AssetState:
        v.positive(asset_id, 'asset_id')
        def parse(value: Any) -> AssetState:
            result = v.asset_state(value)
            if result['id'] != asset_id:
                invalid_response('API returned a different asset ID.')
            return result
        return await self._transport.request(f'/api/assets/{asset_id}', parse=parse, timeout=timeout, cancel=cancel)

    async def delete_asset(self, asset_id: int, *, timeout: float | None = None,
                           cancel: CancellationToken | None = None) -> AssetState:
        v.positive(asset_id, 'asset_id')
        def parse(value: Any) -> AssetState:
            result = v.asset_state(value)
            if result['id'] != asset_id or result['deletion_status'] == 'active':
                invalid_response('Deletion was not accepted for the requested asset.')
            return result
        return await self._transport.request(f'/api/assets/{asset_id}', method='DELETE', parse=parse, asset_id=asset_id, timeout=timeout, cancel=cancel)

    async def bulk_delete_assets(self, asset_ids: list[int], *, timeout: float | None = None,
                                cancel: CancellationToken | None = None) -> BulkDeletion:
        if not isinstance(asset_ids, list) or not 1 <= len(asset_ids) <= 100:
            invalid('Select 1 to 100 explicit asset IDs.')
        for asset_id in asset_ids:
            v.positive(asset_id, 'asset_id')
        expected = list(dict.fromkeys(asset_ids))
        return await self._transport.request('/api/assets/bulk-delete', method='POST', body={'asset_ids': asset_ids},
            parse=lambda x: v.bulk(x, expected), timeout=timeout, cancel=cancel)
