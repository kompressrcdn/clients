"""Blocking clients backed by the same validated transport as the asyncio clients."""
from __future__ import annotations
import asyncio
import os
from collections.abc import Coroutine, Iterator
from typing import Any, BinaryIO, Literal, TypeVar
from .async_client import AsyncKompressrClient, AsyncPlatformClient
from ._transport import CancellationToken
from .errors import invalid, invalid_response
from .types import AssetState, BulkDeletion, CreatedUser, CustomerData, IssuedKey, Page, PrivateUrl, ProjectUser, ProjectUserPage, UploadAccepted, UploadAsset, UploadKey, UploadScope, VideoQuality, Visibility, DeletionStatus

T = TypeVar("T")

def _run(operation: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(operation)
    operation.close()
    invalid("Use AsyncKompressrClient or AsyncPlatformClient inside an asyncio event loop.")

class PlatformClient:
    def __init__(self, *, api_key: str, api_base_url: str='https://kompressr.com', upload_base_url: str | None=None, request_timeout: float=30, upload_timeout: float=600, max_read_retries: int=2) -> None:
        self._async = AsyncPlatformClient(api_key=api_key, api_base_url=api_base_url, upload_base_url=upload_base_url, request_timeout=request_timeout, upload_timeout=upload_timeout, max_read_retries=max_read_retries)

    def list_users(self, *, page: int=1, limit: int=20, timeout: float | None=None, cancel: CancellationToken | None=None) -> ProjectUserPage:
        return _run(self._async.list_users(page=page, limit=limit, timeout=timeout, cancel=cancel))

    def create_user(self, customer_user_id: str, *, display_name: str | None=None, metadata: CustomerData | None=None, timeout: float | None=None, cancel: CancellationToken | None=None) -> CreatedUser:
        return _run(self._async.create_user(customer_user_id, display_name=display_name, metadata=metadata, timeout=timeout, cancel=cancel))

    def update_user(self, project_user_id: str, *, display_name: str | None=None, metadata: CustomerData | None=None, timeout: float | None=None, cancel: CancellationToken | None=None) -> ProjectUser:
        return _run(self._async.update_user(project_user_id, display_name=display_name, metadata=metadata, timeout=timeout, cancel=cancel))

    def suspend_user(self, project_user_id: str, *, timeout: float | None=None, cancel: CancellationToken | None=None) -> ProjectUser:
        return _run(self._async.suspend_user(project_user_id, timeout=timeout, cancel=cancel))

    def reactivate_user(self, project_user_id: str, *, timeout: float | None=None, cancel: CancellationToken | None=None) -> ProjectUser:
        return _run(self._async.reactivate_user(project_user_id, timeout=timeout, cancel=cancel))

    def list_upload_keys(self, project_user_id: str, *, page: int=1, limit: int=20, timeout: float | None=None, cancel: CancellationToken | None=None) -> Page[UploadKey]:
        return _run(self._async.list_upload_keys(project_user_id, page=page, limit=limit, timeout=timeout, cancel=cancel))

    def create_upload_key(self, project_user_id: str, name: str, *, scopes: list[UploadScope] | None=None, allowed_visibility: Literal['public', 'private', 'both'] | None=None, allowed_asset_types: list[int] | None=None, expires_at: str | None=None, timeout: float | None=None, cancel: CancellationToken | None=None) -> IssuedKey:
        return _run(self._async.create_upload_key(project_user_id, name, scopes=scopes, allowed_visibility=allowed_visibility, allowed_asset_types=allowed_asset_types, expires_at=expires_at, timeout=timeout, cancel=cancel))

    def rotate_upload_key(self, project_user_id: str, key_id: str, *, timeout: float | None=None, cancel: CancellationToken | None=None) -> IssuedKey:
        return _run(self._async.rotate_upload_key(project_user_id, key_id, timeout=timeout, cancel=cancel))

    def revoke_upload_key(self, project_user_id: str, key_id: str, *, timeout: float | None=None, cancel: CancellationToken | None=None) -> None:
        return _run(self._async.revoke_upload_key(project_user_id, key_id, timeout=timeout, cancel=cancel))

class KompressrClient:
    def __init__(self, *, api_key: str, project_id: str | None=None, api_base_url: str='https://kompressr.com', upload_base_url: str | None=None, request_timeout: float=30, upload_timeout: float=600, max_read_retries: int=2) -> None:
        self._async = AsyncKompressrClient(api_key=api_key, project_id=project_id, api_base_url=api_base_url, upload_base_url=upload_base_url, request_timeout=request_timeout, upload_timeout=upload_timeout, max_read_retries=max_read_retries)
        self.api_base_url = self._async.api_base_url
        self.upload_base_url = self._async.upload_base_url
        self.platform = PlatformClient(api_key=api_key, api_base_url=api_base_url, upload_base_url=upload_base_url, request_timeout=request_timeout, upload_timeout=upload_timeout, max_read_retries=max_read_retries)

    def upload_file(self, path: str | os.PathLike[str], *, visibility: Visibility | None=None, quality: VideoQuality | None=None, data: CustomerData | None=None, private_url_expires_in: int | None=None, timeout: float | None=None, cancel: CancellationToken | None=None) -> UploadAccepted:
        return _run(self._async.upload_file(path, visibility=visibility, quality=quality, data=data, private_url_expires_in=private_url_expires_in, timeout=timeout, cancel=cancel))

    def upload_bytes(self, content: bytes | bytearray | memoryview, filename: str, *, visibility: Visibility | None=None, quality: VideoQuality | None=None, data: CustomerData | None=None, private_url_expires_in: int | None=None, timeout: float | None=None, cancel: CancellationToken | None=None) -> UploadAccepted:
        return _run(self._async.upload_bytes(content, filename, visibility=visibility, quality=quality, data=data, private_url_expires_in=private_url_expires_in, timeout=timeout, cancel=cancel))

    def upload_stream(self, stream: BinaryIO, filename: str, *, visibility: Visibility | None=None, quality: VideoQuality | None=None, data: CustomerData | None=None, private_url_expires_in: int | None=None, timeout: float | None=None, cancel: CancellationToken | None=None) -> UploadAccepted:
        return _run(self._async.upload_stream(stream, filename, visibility=visibility, quality=quality, data=data, private_url_expires_in=private_url_expires_in, timeout=timeout, cancel=cancel))

    def get_upload_status(self, asset_id: int, *, timeout: float | None=None, cancel: CancellationToken | None=None) -> UploadAsset:
        return _run(self._async.get_upload_status(asset_id, timeout=timeout, cancel=cancel))

    def wait_until_ready(self, asset_id: int, *, timeout: float=120, poll_interval: float=2, cancel: CancellationToken | None=None) -> UploadAsset:
        return _run(self._async.wait_until_ready(asset_id, timeout=timeout, poll_interval=poll_interval, cancel=cancel))

    def generate_private_url(self, asset_id: int, *, expires_in: int=3600, variant: Literal['webp', 'avif']='webp', timeout: float | None=None, cancel: CancellationToken | None=None) -> PrivateUrl:
        return _run(self._async.generate_private_url(asset_id, expires_in=expires_in, variant=variant, timeout=timeout, cancel=cancel))

    def list_uploads(self, *, project_id: str | None=None, page: int=1, limit: int=20, visibility: Visibility | None=None, external_id: str | None=None, data: dict[str, str] | None=None, status: str | int | None=None, deletion_status: DeletionStatus | None=None, timeout: float | None=None, cancel: CancellationToken | None=None) -> Page[UploadAsset]:
        return _run(self._async.list_uploads(project_id=project_id, page=page, limit=limit, visibility=visibility, external_id=external_id, data=data, status=status, deletion_status=deletion_status, timeout=timeout, cancel=cancel))

    def iterate_uploads(self, *, project_id: str | None=None, page: int=1, limit: int=20, visibility: Visibility | None=None, external_id: str | None=None, data: dict[str, str] | None=None, status: str | int | None=None, deletion_status: DeletionStatus | None=None, timeout: float | None=None, cancel: CancellationToken | None=None) -> Iterator[UploadAsset]:
        current = page
        while True:
            result = self.list_uploads(project_id=project_id, page=current, limit=limit, visibility=visibility, external_id=external_id, data=data, status=status, deletion_status=deletion_status, timeout=timeout, cancel=cancel)
            if result['page'] != current or len(result['data']) > result['limit']:
                invalid_response('Invalid pagination response.')
            yield from result['data']
            if not result['data'] or result['page'] * result['limit'] >= result['total']:
                return
            current += 1

    def list_assets(self, *, page: int=1, limit: int=20, deletion_status: DeletionStatus | None=None, timeout: float | None=None, cancel: CancellationToken | None=None) -> Page[AssetState]:
        return _run(self._async.list_assets(page=page, limit=limit, deletion_status=deletion_status, timeout=timeout, cancel=cancel))

    def get_asset(self, asset_id: int, *, timeout: float | None=None, cancel: CancellationToken | None=None) -> AssetState:
        return _run(self._async.get_asset(asset_id, timeout=timeout, cancel=cancel))

    def delete_asset(self, asset_id: int, *, timeout: float | None=None, cancel: CancellationToken | None=None) -> AssetState:
        return _run(self._async.delete_asset(asset_id, timeout=timeout, cancel=cancel))

    def bulk_delete_assets(self, asset_ids: list[int], *, timeout: float | None=None, cancel: CancellationToken | None=None) -> BulkDeletion:
        return _run(self._async.bulk_delete_assets(asset_ids, timeout=timeout, cancel=cancel))
