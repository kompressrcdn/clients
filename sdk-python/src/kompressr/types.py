"""Typed wire results. Fields retain their API snake_case names."""
from __future__ import annotations

from typing import Generic, Literal, NotRequired, TypedDict, TypeVar

Visibility = Literal['public', 'private']
VideoQuality = Literal['480p', '720p', '1080p', '4k']
DeletionStatus = Literal['active', 'deleting', 'deleted', 'legacy_deleted']
ProcessingStatus = Literal['pending', 'processing', 'processed', 'failed', 'unprocessable', 'unknown']
UploadScope = Literal['upload', 'status', 'list', 'private_url', 'delete']
CustomerData = dict[str, str | int | float | bool | None]
T = TypeVar('T')


class UploadAccepted(TypedDict):
    id: int
    status: ProcessingStatus
    deletion_status: DeletionStatus
    visibility: Visibility
    original_name: str
    original_size: int
    asset_type: str
    deletion_requested_at: NotRequired[str]
    cdn_url: NotRequired[str]
    cdn_url_avif: NotRequired[str]
    private_url: NotRequired[str]
    private_url_expires_at: NotRequired[str]
    data: NotRequired[CustomerData]
    external_id: NotRequired[str]
    options: NotRequired[dict[str, str]]
    quality: NotRequired[VideoQuality]
    warning: NotRequired[str]


class UploadAsset(TypedDict):
    id: int
    status: ProcessingStatus
    deletion_status: DeletionStatus
    visibility: Visibility
    original_size: int
    asset_type: str
    kompressd_size: int
    savings_percent: float
    can_generate_private_url: bool
    original_name: NotRequired[str]
    deletion_requested_at: NotRequired[str]
    cdn_url: NotRequired[str]
    cdn_url_avif: NotRequired[str]
    private_url: NotRequired[str]
    private_url_expires_at: NotRequired[str]
    data: NotRequired[CustomerData]
    external_id: NotRequired[str]
    options: NotRequired[dict[str, str]]
    quality: NotRequired[VideoQuality]
    input_format: NotRequired[str]
    output_format: NotRequired[str]
    created_at: NotRequired[str]


class PrivateUrl(TypedDict):
    asset_id: int
    variant: Literal['webp', 'avif']
    private_url: str
    expires_at: str
    expires_in: int


class Page(TypedDict, Generic[T]):
    data: list[T]
    page: int
    limit: int
    total: int


class AssetFailure(TypedDict):
    code: str
    message: str
    at: str


class AssetState(TypedDict):
    id: int
    project_id: str
    kind: int
    source: Literal['upload', 'origin']
    processing_status: int
    deletion_status: DeletionStatus
    storage_credited_mb: int
    deletion_requested_at: NotRequired[str]
    accounting_status: NotRequired[Literal['pending', 'settled', 'unavailable']]
    last_failure: NotRequired[AssetFailure]


class BulkItem(TypedDict):
    id: int
    status: int
    accepted: bool
    state: NotRequired[AssetState]
    code: NotRequired[str]
    error: NotRequired[str]


class BulkCounts(TypedDict):
    total: int
    accepted: int
    failed: int


class BulkDeletion(TypedDict):
    results: list[BulkItem]
    counts: BulkCounts


class ProjectUser(TypedDict):
    id: str
    project_id: str
    customer_user_id: str
    status: Literal['active', 'suspended']
    display_name: NotRequired[str]
    metadata: NotRequired[CustomerData]
    asset_count: NotRequired[int]
    storage_bytes: NotRequired[int]
    active_key_count: NotRequired[int]
    bandwidth_bytes_current_period: NotRequired[int]
    requests_current_period: NotRequired[int]
    last_seen_at: NotRequired[str]
    last_upload_at: NotRequired[str]
    last_key_used_at: NotRequired[str]
    created_at: NotRequired[str]


class UsagePeriod(TypedDict):
    start: str
    end: str


class ProjectUserPage(Page[ProjectUser]):
    project_active_count: int
    org_active_count: int
    usage_period: NotRequired[UsagePeriod]


class CreatedUser(TypedDict):
    created: bool
    project_user: ProjectUser


class UploadKey(TypedDict):
    id: str
    key_id: str
    project_id: str
    project_user_id: str
    name: str
    scopes: list[UploadScope]
    allowed_visibility: Literal['public', 'private', 'both']
    allowed_asset_types: NotRequired[list[int]]
    expires_at: NotRequired[str | None]
    revoked_at: NotRequired[str | None]
    last_used_at: NotRequired[str | None]
    created_at: NotRequired[str]


class IssuedKey(TypedDict):
    id: str
    key_id: str
    api_key: str
    upload_key: NotRequired[UploadKey]
