from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from typing import Any, TypeVar, cast
from urllib.parse import urlsplit

from .errors import invalid, invalid_response
from .types import AssetState, BulkDeletion, CustomerData, Page, PrivateUrl, ProjectUser, UploadAccepted, UploadAsset, UploadKey

MAX_SAFE = 9007199254740991
MAX_TIMEOUT = 2147483.647
DELETION = ('active', 'deleting', 'deleted', 'legacy_deleted')
SCOPES = ('upload', 'status', 'list', 'private_url', 'delete')
T = TypeVar('T')


def record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        invalid_response()
    return value


def string(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        invalid_response()
    return value


def finite(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def number(value: Any, integer: bool = False) -> int | float:
    if not finite(value):
        invalid_response()
    if integer and (value != int(value) or abs(value) > MAX_SAFE):
        invalid_response()
    return cast('int | float', value)


def integer(value: Any) -> int:
    return int(number(value, True))


def positive(value: Any, name: str, maximum: int = MAX_SAFE) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        invalid(f'{name} must be an integer between 1 and {maximum}.')
    return value


def seconds(value: Any, name: str = 'timeout') -> float:
    if not finite(value) or not 0 < value <= MAX_TIMEOUT:
        invalid(f'{name} must be a finite positive number of seconds no greater than {MAX_TIMEOUT}.')
    return float(value)


def uuid(value: Any, name: str = 'ID') -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value):
        invalid(f'{name} must be a UUID.')
    return value


def text_input(value: Any, name: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        invalid(f'{name} must be a string with at most {maximum} UTF-8 bytes.')
    try:
        if len(value.strip().encode('utf-8')) > maximum:
            invalid(f'{name} exceeds {maximum} UTF-8 bytes.')
    except UnicodeEncodeError:
        invalid(f'{name} must contain valid UTF-8.')
    return value


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def customer_data(value: Any, maximum: int = 4096) -> CustomerData:
    if not isinstance(value, dict) or len(value) > 5:
        invalid('Customer data supports at most five scalar fields.')
    result: CustomerData = {}
    for raw_key, item in value.items():
        if not isinstance(raw_key, str):
            invalid('Data keys must be strings.')
        key = raw_key.strip()
        text_input(key, 'Data key', 64)
        if key in result:
            invalid('Data keys must be unique after trimming.')
        if isinstance(item, str):
            try:
                if len(item.encode('utf-8')) > 512:
                    invalid('Data string values support at most 512 UTF-8 bytes.')
            except UnicodeEncodeError:
                invalid('Data string values must contain valid UTF-8.')
        elif item is not None and type(item) is not bool:
            try:
                finite = type(item) in (int, float) and math.isfinite(item)
            except OverflowError:
                finite = False
            if not finite:
                invalid('Data values must be finite scalars.')
        result[key] = item
    if len(json_text(result).encode()) > maximum:
        invalid(f'Encoded customer data exceeds {maximum} bytes.')
    return result


def enum_input(value: Any, allowed: tuple[str, ...], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        invalid(f'Unsupported {name}.')
    return value


def optional_strings(value: dict[str, Any], names: tuple[str, ...]) -> None:
    for name in names:
        if name in value and not isinstance(value[name], str):
            invalid_response()


def safe_urls(value: dict[str, Any]) -> None:
    for key in ('cdn_url', 'cdn_url_avif', 'private_url'):
        if key not in value:
            continue
        text = string(value[key])
        try:
            parsed = urlsplit(text)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or any(ord(c) <= 32 for c in text):
                invalid_response('Invalid delivery URL.')
            parsed.port
        except ValueError:
            invalid_response('Invalid delivery URL.')


def deletion(value: Any) -> str:
    if value not in DELETION or not isinstance(value, str):
        invalid_response('Missing or invalid deletion status; verify server compatibility.')
    return value


def upload(value: Any, *, accepted: bool = False) -> dict[str, Any]:
    v = record(value)
    asset_id = integer(v.get('asset_id' if accepted else 'id'))
    if asset_id < 1:
        invalid_response()
    if string(v.get('status')) not in ('pending', 'processing', 'processed', 'failed', 'unprocessable', 'unknown'):
        invalid_response('Unknown processing status.')
    if string(v.get('visibility')) not in ('public', 'private') or integer(v.get('original_size')) < 0:
        invalid_response()
    deletion(v.get('deletion_status'))
    if accepted:
        string(v.get('original_name'))
    else:
        optional_strings(v, ('original_name',))
    string(v.get('asset_type'))
    optional_strings(v, ('deletion_requested_at', 'external_id', 'created_at', 'input_format', 'output_format', 'private_url_expires_at'))
    safe_urls(v)
    if v['visibility'] == 'private' and any(k in v for k in ('cdn_url', 'cdn_url_avif')):
        invalid_response('Private asset response contains a public URL.')
    if v['deletion_status'] != 'active' and any(k in v for k in ('cdn_url', 'cdn_url_avif', 'private_url')):
        invalid_response('Deleted asset response contains a delivery URL.')
    if 'data' in v:
        try:
            customer_data(v['data'], 8192)
        except Exception:
            invalid_response('Invalid customer data response.')
    if 'options' in v and any(not isinstance(x, str) for x in record(v['options']).values()):
        invalid_response()
    if 'quality' in v and v['quality'] not in ('480p', '720p', '1080p', '4k'):
        invalid_response()
    optional_strings(v, ('warning',))
    return {**{k: x for k, x in v.items() if k != 'asset_id'}, 'id': asset_id}


def upload_accepted(value: Any) -> UploadAccepted:
    return cast(UploadAccepted, upload(value, accepted=True))


def upload_asset(value: Any) -> UploadAsset:
    v = upload(value)
    if integer(v.get('kompressd_size')) < 0 or type(v.get('can_generate_private_url')) is not bool:
        invalid_response()
    number(v.get('savings_percent'))
    return cast(UploadAsset, v)


def private_url(value: Any) -> PrivateUrl:
    v = record(value)
    if integer(v.get('asset_id')) < 1 or string(v.get('variant')) not in ('webp', 'avif'):
        invalid_response()
    safe_urls(v)
    string(v.get('private_url'))
    string(v.get('expires_at'))
    if not 60 <= integer(v.get('expires_in')) <= 604800:
        invalid_response()
    return cast(PrivateUrl, v)


def asset_state(value: Any) -> AssetState:
    v = record(value)
    if integer(v.get('id')) < 1 or integer(v.get('kind')) < 1 or integer(v.get('storage_credited_mb')) < 0:
        invalid_response()
    string(v.get('project_id'))
    integer(v.get('processing_status'))
    deletion(v.get('deletion_status'))
    if string(v.get('source')) not in ('upload', 'origin'):
        invalid_response()
    optional_strings(v, ('deletion_requested_at',))
    if 'accounting_status' in v and v['accounting_status'] not in ('pending', 'settled', 'unavailable'):
        invalid_response()
    if 'last_failure' in v:
        f = record(v['last_failure'])
        for key in ('code', 'message', 'at'):
            string(f.get(key))
    return cast(AssetState, v)


def page(value: Any, parse: Callable[[Any], T], key: str = 'data') -> Page[T]:
    v = record(value)
    if not isinstance(v.get(key), list) or integer(v.get('page')) < 1 or integer(v.get('limit')) < 1 or integer(v.get('total')) < 0:
        invalid_response()
    return {'data': [parse(x) for x in v[key]], 'page': integer(v['page']), 'limit': integer(v['limit']), 'total': integer(v['total'])}


def bulk(value: Any, expected: list[int]) -> BulkDeletion:
    v = record(value)
    counts = record(v.get('counts'))
    if not isinstance(v.get('results'), list) or len(v['results']) != len(expected):
        invalid_response()
    accepted = 0
    for index, row in enumerate(v['results']):
        item = record(row)
        if integer(item.get('id')) != expected[index] or type(item.get('accepted')) is not bool:
            invalid_response()
        status = integer(item.get('status'))
        if item['accepted']:
            accepted += 1
            state = asset_state(item.get('state'))
            if status not in (200, 202) or state['id'] != item['id'] or state['deletion_status'] == 'active':
                invalid_response()
        elif status < 400:
            invalid_response()
        else:
            string(item.get('error'))
        optional_strings(item, ('code', 'error'))
    for key, number_expected in (('total', len(expected)), ('accepted', accepted), ('failed', len(expected) - accepted)):
        if integer(counts.get(key)) != number_expected:
            invalid_response()
    return cast(BulkDeletion, v)


def project_user(value: Any) -> ProjectUser:
    v = record(value)
    for key in ('id', 'project_id', 'customer_user_id'):
        string(v.get(key))
    if string(v.get('status')) not in ('active', 'suspended'):
        invalid_response()
    optional_strings(v, ('display_name', 'created_at', 'last_seen_at', 'last_upload_at', 'last_key_used_at'))
    for key in ('asset_count', 'storage_bytes', 'active_key_count', 'bandwidth_bytes_current_period', 'requests_current_period'):
        if key in v and integer(v[key]) < 0:
            invalid_response()
    if 'metadata' in v:
        try:
            customer_data(v['metadata'], 8192)
        except Exception:
            invalid_response('Invalid project user metadata.')
    return cast(ProjectUser, v)


def upload_key(value: Any) -> UploadKey:
    v = record(value)
    for key in ('id', 'key_id', 'project_id', 'project_user_id', 'name'):
        string(v.get(key))
    if not isinstance(v.get('scopes'), list) or any(x not in SCOPES for x in v['scopes']):
        invalid_response()
    if string(v.get('allowed_visibility')) not in ('public', 'private', 'both'):
        invalid_response()
    if 'allowed_asset_types' in v and (not isinstance(v['allowed_asset_types'], list) or any(integer(x) < 1 for x in v['allowed_asset_types'])):
        invalid_response()
    for key in ('expires_at', 'revoked_at', 'last_used_at'):
        if key in v and v[key] is not None and not isinstance(v[key], str):
            invalid_response()
    optional_strings(v, ('created_at',))
    return cast(UploadKey, v)


def success(value: Any) -> dict[str, Any]:
    v = record(value)
    if v.get('success') is not True:
        invalid_response()
    return v


def data(value: Any) -> Any:
    v = success(value)
    if 'data' not in v:
        invalid_response()
    return v['data']
