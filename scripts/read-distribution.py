"""Read a bounded native package archive for the shared public-content scanner."""
import base64
import io
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile
import zipfile
import zlib

MAX_TOTAL = 64 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_FILES = 20_000


def tar_members(archive):
    for item in archive:
        if item.isdir():
            continue
        if not item.isfile():
            raise ValueError("Distribution contains a link or special file")
        yield item.name, item.size, lambda entry=item: archive.extractfile(entry)


def members(filename):
    if zipfile.is_zipfile(filename):
        with zipfile.ZipFile(filename) as archive:
            for item in archive.infolist():
                mode = stat.S_IFMT(item.external_attr >> 16)
                if mode == stat.S_IFLNK:
                    raise ValueError("Distribution contains a symbolic link")
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError("Distribution contains a special file")
                if not item.is_dir():
                    yield item.filename, item.file_size, lambda entry=item: archive.open(entry)
    else:
        with tarfile.open(filename, "r:*") as archive:
            yield from tar_members(archive)


def read_members(entries):
    files, total, names = [], 0, set()
    for name, size, open_file in entries:
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or name in names:
            raise ValueError("Distribution contains an unsafe or duplicate member path")
        if size > MAX_FILE or total + size > MAX_TOTAL or len(files) >= MAX_FILES:
            raise ValueError("Distribution exceeds inspection limits")
        names.add(name)
        with open_file() as stream:
            data = stream.read(MAX_FILE + 1)
        if len(data) != size:
            raise ValueError("Distribution member size differs from its metadata")
        total += size
        files.append({"path": name, "data": base64.b64encode(data).decode("ascii")})
    if not files:
        raise ValueError("Distribution contains no files")
    return files


def gem_tar(data):
    """Inspect ordinary tar records before any extension can allocate memory.

    RubyGems emits regular ustar records. Reject extension headers rather than
    asking tarfile to interpret PAX/GNU metadata outside the inspection limits.
    Header bytes are returned for content scanning; record padding must be zero.
    """
    if len(data) > MAX_TOTAL or len(data) % 512:
        raise ValueError('Gem tar exceeds inspection limits or is truncated')
    entries, headers, names = [], [], set()
    offset = 0
    while offset < len(data):
        header = data[offset:offset + 512]
        if not any(header):
            if len(data) - offset < 1024 or any(data[offset:]):
                raise ValueError('Gem tar contains missing or nonzero trailing padding')
            return read_members(entries), b''.join(headers)
        if len(headers) >= MAX_FILES:
            raise ValueError('Gem tar exceeds inspection limits')
        item = tarfile.TarInfo.frombuf(header, 'utf-8', 'strict')
        if item.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE):
            raise ValueError('Gem tar contains an extension, link or special file')
        path = PurePosixPath(item.name)
        normalized = str(path)
        if not item.name or normalized == '.' or path.is_absolute() or '..' in path.parts or '\\' in item.name or ':' in item.name or normalized in names:
            raise ValueError('Gem tar contains an unsafe or duplicate member path')
        if item.size < 0 or item.size > MAX_FILE or (item.isdir() and item.size != 0):
            raise ValueError('Gem tar exceeds inspection limits or has an invalid directory')
        names.add(normalized)
        headers.append(header)
        start = offset + 512
        end = start + item.size
        next_record = start + ((item.size + 511) // 512) * 512
        if next_record > len(data) or any(data[end:next_record]):
            raise ValueError('Gem tar contains truncated data or nonzero member padding')
        if item.isfile():
            entries.append((normalized, item.size, lambda begin=start, finish=end: io.BytesIO(data[begin:finish])))
        offset = next_record
    raise ValueError('Gem tar is missing its end records')


def read_gem(filename):
    # Bound the complete outer container before parsing any of its headers.
    # Gems use an uncompressed tar; other archive formats retain their reader.
    with Path(filename).open('rb') as stream:
        files, outer_headers = gem_tar(stream.read(MAX_TOTAL + 1))

    # A gem's outer tar contains gzip-compressed metadata and another tar.
    # Inspect the actual payload without extracting or deserializing its YAML.
    outer = {item['path']: base64.b64decode(item['data']) for item in files}
    components = {'metadata.gz', 'data.tar.gz', 'checksums.yaml.gz'}
    allowed = components | {name + '.sig' for name in components}
    if not {'metadata.gz', 'data.tar.gz'} <= outer.keys() or outer.keys() - allowed:
        raise ValueError('Gem contains missing or unsupported container members')

    def inflate(name, limit):
        compressed = outer[name]
        # Optional gzip filename/comment/extra fields can leak plaintext while
        # disappearing from decompressed output. Native gem builds omit them.
        if len(compressed) < 18 or compressed[:3] != b'\x1f\x8b\x08' or compressed[3] != 0:
            raise ValueError('Gem gzip contains unsupported header metadata')
        decoder = zlib.decompressobj(wbits=31)
        value = decoder.decompress(compressed, limit + 1)
        if len(value) > limit:
            raise ValueError('Gem decompression exceeds inspection limits')
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('Gem gzip contains truncated or trailing data')
        return value

    result = [{'path': 'gem/container-headers', 'data': base64.b64encode(outer_headers).decode('ascii')}]
    for name in sorted(outer.keys() - {'data.tar.gz'}):
        data = inflate(name, MAX_FILE) if name.endswith('.gz') else outer[name]
        result.append({'path': 'gem/' + name.removesuffix('.gz'), 'data': base64.b64encode(data).decode('ascii')})
    payload = inflate('data.tar.gz', MAX_TOTAL)
    payload_files, payload_headers = gem_tar(payload)
    result.append({'path': 'gem/payload-headers', 'data': base64.b64encode(payload_headers).decode('ascii')})
    result.extend({'path': 'data/' + item['path'], 'data': item['data']} for item in payload_files)
    if len(result) > MAX_FILES or sum(len(base64.b64decode(item['data'])) for item in result) > MAX_TOTAL:
        raise ValueError('Gem exceeds inspection limits')
    return result


def read(filename):
    if str(filename).lower().endswith('.gem'):
        return read_gem(filename)
    return read_members(members(filename))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: read-distribution.py ARCHIVE")
    json.dump(read(sys.argv[1]), sys.stdout)
