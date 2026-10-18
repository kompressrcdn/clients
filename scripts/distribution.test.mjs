import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const scanner = fileURLToPath(new URL('./check-distribution.mjs', import.meta.url));
test('checks native archives without extracting unsafe members', () => {
  const root = mkdtempSync(join(tmpdir(), 'kompressr-archive-check-'));
  try {
    const program = `
import io, pathlib, stat, sys, tarfile, zipfile
root = pathlib.Path(sys.argv[1])
for name, path, content in [('clean.whl','kompressr/client.py','value = 42'), ('secret.nupkg','lib/secret.txt','npm_' + 'x' * 36), ('private.jar','.env','fixture'), ('escape.zip','../outside','fixture')]:
    with zipfile.ZipFile(root / name, 'w') as archive: archive.writestr(path, content)
with zipfile.ZipFile(root / 'link.zip', 'w') as archive:
    item = zipfile.ZipInfo('link'); item.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive.writestr(item, 'outside')
with zipfile.ZipFile(root / 'device.zip', 'w') as archive:
    item = zipfile.ZipInfo('device'); item.external_attr = (stat.S_IFCHR | 0o600) << 16
    archive.writestr(item, '')
with tarfile.open(root / 'clean.tar.gz', 'w:gz') as archive:
    content = b'fixture'; item = tarfile.TarInfo('package/README.md'); item.size = len(content)
    archive.addfile(item, io.BytesIO(content))
`;
    execFileSync(process.env.KOMPRESSR_PYTHON || 'python3', ['-c', program, root]);
    const run = filename => spawnSync(process.execPath, [scanner, join(root, filename)], { encoding: 'utf8' });
    for (const name of ['clean.whl', 'clean.tar.gz']) assert.equal(run(name).status, 0, name);
    for (const [name, reason] of [['secret.nupkg', /Credential-like/], ['private.jar', /Private configuration/], ['escape.zip', /unsafe/], ['link.zip', /symbolic link/], ['device.zip', /special file/]]) {
      const result = run(name); assert.notEqual(result.status, 0, name); assert.match(result.stderr, reason);
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('inspects gem metadata and nested payloads with bounded decompression', () => {
  const root = mkdtempSync(join(tmpdir(), 'kompressr-gem-check-'));
  try {
    const program = `
import gzip, io, pathlib, sys, tarfile
root = pathlib.Path(sys.argv[1])
def tar(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        for path, content, link in entries:
            item = tarfile.TarInfo(path)
            if link: item.type = tarfile.SYMTYPE; item.linkname = 'outside'
            else: item.size = len(content)
            archive.addfile(item, None if link else io.BytesIO(content))
    return output.getvalue()
def gem(name, path='lib/kompressr.rb', content=b'value = 42', metadata=b'name: kompressr-sdk', link=False, extra=False, duplicate=False):
    payload = tar([(path, content, link)])
    entries = [('metadata.gz', gzip.compress(metadata), False), ('data.tar.gz', gzip.compress(payload), False)]
    if extra: entries.append(('unknown.gz', gzip.compress(b'ignored secret'), False))
    if duplicate: entries.append(entries[0])
    (root / name).write_bytes(tar(entries))
gem('clean.gem')
gem('secret.gem', content=('npm_' + 'x'*36).encode())
gem('metadata-secret.gem', metadata=('token: npm_' + 'x'*36).encode())
gem('private.gem', path='.env')
gem('escape.gem', path='../outside')
gem('link.gem', link=True)
gem('unknown.gem', extra=True)
gem('duplicate.gem', duplicate=True)
gem('metadata-bomb.gem', metadata=b'x' * (16*1024*1024+1))
gem('payload-bomb.gem', content=b'x' * (64*1024*1024+1))
`;
    execFileSync(process.env.KOMPRESSR_PYTHON || 'python3', ['-c', program, root]);
    const run = name => spawnSync(process.execPath, [scanner, join(root, name)], { encoding: 'utf8' });
    assert.equal(run('clean.gem').status, 0);
    for (const [name, reason] of [
      ['secret.gem', /Credential-like/], ['metadata-secret.gem', /Credential-like/],
      ['private.gem', /Private configuration/], ['escape.gem', /unsafe/], ['link.gem', /link or special/],
      ['unknown.gem', /unsupported container/], ['duplicate.gem', /duplicate/],
      ['metadata-bomb.gem', /decompression exceeds/], ['payload-bomb.gem', /decompression exceeds/],
    ]) {
      const result = run(name); assert.notEqual(result.status, 0, name); assert.match(result.stderr, reason, name);
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('rejects hidden gem headers, extension records and trailing data', () => {
  const root = mkdtempSync(join(tmpdir(), 'kompressr-gem-boundaries-'));
  try {
    const program = `
import gzip, io, pathlib, sys, tarfile
root = pathlib.Path(sys.argv[1])
secret = ('npm_' + 'x'*36).encode()
def tar(entries, pax=None, owner=''):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT, pax_headers=pax) as archive:
        for name, content in entries:
            item = tarfile.TarInfo(name); item.size = len(content); item.uname = owner
            archive.addfile(item, io.BytesIO(content))
    return output.getvalue()
payload = tar([('lib/fixture.rb', b'value = 42')])
metadata = gzip.compress(b'name: kompressr-sdk')
def gem(name, meta=metadata, body=payload, outer_pax=None, owner='', extra=b''):
    data = tar([('metadata.gz', meta), ('data.tar.gz', gzip.compress(body))], pax=outer_pax, owner=owner)
    (root / name).write_bytes(data + extra)
def header(flag, field):
    return metadata[:3] + bytes([flag]) + metadata[4:10] + field + metadata[10:]
gem('filename.gem', meta=header(8, secret + b'\\0'))
gem('filename.GEM', meta=header(8, secret + b'\\0'))
gem('comment.gem', meta=header(16, secret + b'\\0'))
gem('extra.gem', meta=header(4, len(secret).to_bytes(2, 'little') + secret))
gem('gzip-trailer.gem', meta=metadata + secret)
gem('gzip-concatenated.gem', meta=metadata + gzip.compress(secret))
gem('outer-trailer.gem', extra=secret.ljust(512, b'\\0'))
gem('payload-trailer.gem', body=payload + secret.ljust(512, b'\\0'))
padded = bytearray(payload); padded[522:522+len(secret)] = secret
gem('payload-padding.gem', body=bytes(padded))
gem('outer-pax.gem', outer_pax={'comment': 'x' * (16*1024*1024+1)})
gem('payload-pax.gem', body=tar([('lib/fixture.rb', b'value = 42')], pax={'comment': secret.decode()}))
gem('normalized-duplicate.gem', body=tar([('lib/fixture.rb', b'a'), ('./lib/fixture.rb', b'b')]))
# Owner strings are valid ordinary tar metadata and must also be scanned.
gem('owner-path.gem', owner='/' + '/'.join(['home', 'example']))
gem('payload-owner-path.gem', body=tar([('lib/fixture.rb', b'value = 42')], owner='/' + '/'.join(['home', 'example'])))
# Stricter gem handling must not reject ordinary gzip/tar distributions.
with tarfile.open(root / 'ordinary-pax.tar.gz', 'w:gz', pax_headers={'comment': 'standard metadata'}) as archive:
    data = b'fixture'; item = tarfile.TarInfo('package/README.md'); item.size = len(data)
    archive.addfile(item, io.BytesIO(data))
`;
    execFileSync(process.env.KOMPRESSR_PYTHON || 'python3', ['-c', program, root]);
    const run = name => spawnSync(process.execPath, [scanner, join(root, name)], { encoding: 'utf8' });
    for (const [name, reason] of [
      ['filename.gem', /unsupported header metadata/], ['filename.GEM', /unsupported header metadata/],
      ['comment.gem', /unsupported header metadata/],
      ['extra.gem', /unsupported header metadata/], ['gzip-trailer.gem', /trailing data/],
      ['gzip-concatenated.gem', /trailing data/], ['outer-trailer.gem', /trailing padding/],
      ['payload-trailer.gem', /trailing padding/], ['payload-padding.gem', /member padding/],
      ['outer-pax.gem', /extension/], ['payload-pax.gem', /extension/],
      ['normalized-duplicate.gem', /duplicate/], ['owner-path.gem', /Machine-specific/],
      ['payload-owner-path.gem', /Machine-specific/],
    ]) {
      const result = run(name); assert.notEqual(result.status, 0, name); assert.match(result.stderr, reason, name);
    }
    assert.equal(run('ordinary-pax.tar.gz').status, 0);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
