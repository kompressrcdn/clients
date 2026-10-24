"""Release declared versions from verified main commits; no implicit version bumps.

Registry writes are deliberately separate from preparation. A retained release
record must have trusted GitHub provenance before a retry can use its artifacts.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile

CONTROL_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get('RELEASE_SOURCE', CONTROL_ROOT)).resolve()
SIGNER = 'kompressrcdn/clients/.github/workflows/publish.yml'
REPO = 'kompressrcdn/clients'
KEYS = ('sdk-js', 'mcp-server', 'python', 'go', 'java', 'dotnet', 'php', 'ruby')
STABLE = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z')
SHA = re.compile(r'[a-f0-9]{40}\Z')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(*args, cwd=ROOT, env=None, capture=False, input=None):
    # Never print arguments: signing and authentication commands can contain secrets.
    return subprocess.run(args, cwd=cwd, env=env, input=input, text=True,
                          stdout=subprocess.PIPE if capture else None, check=True).stdout


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def output(name, value):
    value = json.dumps(value, separators=(',', ':')) if not isinstance(value, str) else value
    require('\n' not in value, 'Invalid workflow output')
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'{name}={value}\n')
    else:
        print(f'{name}={value}')


def request(url, *, method='GET', data=None, headers=None, missing=False):
    require(url.startswith('https://'), 'HTTPS required')
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'User-Agent': 'kompressr-release', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        e.close()
        if missing and e.code == 404:
            return None
        # Do not expose response bodies or credentials in diagnostics.
        raise RuntimeError(f'HTTP {e.code} from {urllib.parse.urlsplit(url).hostname}') from None


def get_json(url, **kwargs):
    raw = request(url, **kwargs)
    return None if raw is None else json.loads(raw)


def github(path, *, missing=False, data=None):
    token = os.environ['GH_TOKEN']
    return get_json('https://api.github.com/repos/' + REPO + '/' + path,
                    missing=missing, method='GET' if data is None else 'POST',
                    data=None if data is None else json.dumps(data).encode(),
                    headers={'Authorization': 'Bearer ' + token,
                             'Accept': 'application/vnd.github+json'})


def versions(root=ROOT):
    def match(path, pattern):
        values = re.findall(pattern, (root / path).read_text(), re.M)
        require(len(values) == 1, f'Ambiguous version in {path}')
        return values[0]
    result = {k: read_json(root / k / 'package.json')['version'] for k in KEYS[:2]}
    result['python'] = tomllib.loads((root / 'sdk-python/pyproject.toml').read_text())['project']['version']
    require(result['python'] == match('sdk-python/src/kompressr/__init__.py', r"^__version__ = ['\"]([^'\"]+)"), 'Python versions differ')
    result['go'] = match('sdk-go/types.go', r'^const Version = "([^"]+)"')
    result['java'] = ET.parse(root / 'sdk-java/pom.xml').findtext('{*}version')
    result['dotnet'] = ET.parse(root / 'sdk-dotnet/src/Kompressr.Sdk/Kompressr.Sdk.csproj').findtext('.//Version')
    result['php'] = (root / 'sdk-php/VERSION').read_text().strip()
    result['ruby'] = match('sdk-ruby/lib/kompressr/version.rb', r"^\s*VERSION = ['\"]([^'\"]+)")
    for key, version in result.items():
        require(isinstance(version, str) and STABLE.fullmatch(version), f'{key}: expected stable x.y.z version')
    for key in KEYS[:2]:
        lock = read_json(root / key / 'package-lock.json')
        require(lock['version'] == result[key] == lock['packages']['']['version'], f'{key}: lockfile version differs')
    mcp = read_json(root / 'mcp-server/package.json')
    lock = read_json(root / 'mcp-server/package-lock.json')
    require(mcp['dependencies']['@kompressr/sdk'] == result['sdk-js'], 'MCP must depend on the declared exact SDK version')
    require(lock['packages']['']['dependencies']['@kompressr/sdk'] == result['sdk-js'] == lock['packages']['node_modules/@kompressr/sdk']['version'], 'MCP SDK lock differs')
    require(read_json(root / 'mcp-server/server.json')['version'] == result['mcp-server'] == read_json(root / 'smithery/manifest.json')['version'], 'MCP metadata versions differ')
    return result


def tag(key, version):
    return f'mcp-server-v{version}' if key == 'mcp-server' else f'{key if key == "sdk-js" else "sdk-" + key}/v{version}'


def registry(key, version):
    if key in KEYS[:2]:
        name = '@kompressr/sdk' if key == 'sdk-js' else '@kompressr/mcp-server'
        value = get_json(f'https://registry.npmjs.org/{urllib.parse.quote(name, safe="")}/{version}', missing=True)
        if value is not None:
            require(value['name'] == name and value['version'] == version and value['dist']['integrity'], 'Invalid npm metadata')
        return value
    if key == 'python':
        value = get_json(f'https://pypi.org/pypi/kompressr-sdk/{version}/json', missing=True)
        if value is not None:
            require(value['info']['version'] == version and len(value['urls']) > 0, 'Invalid PyPI metadata')
        return value
    if key == 'go':
        # GitHub is authoritative for existence; a proxy cache miss is not permission to retag.
        return github('git/ref/tags/' + urllib.parse.quote(tag(key, version), safe=''), missing=True)
    if key == 'java':
        return request(f'https://repo.maven.apache.org/maven2/com/kompressr/kompressr-sdk/{version}/kompressr-sdk-{version}.pom', missing=True)
    if key == 'dotnet':
        value = request(f'https://api.nuget.org/v3-flatcontainer/kompressr.sdk/{version}/kompressr.sdk.nuspec', missing=True)
        if value is not None:
            require(ET.fromstring(value).findtext('.//{*}version') == version, 'Invalid NuGet metadata')
        return value
    if key == 'php':
        value = get_json('https://repo.packagist.org/p2/kompressr/sdk.json', missing=True)
        if value is None:
            return None
        return next((p for p in value['packages']['kompressr/sdk'] if p['version'].lstrip('v') == version), None)
    value = get_json(f'https://rubygems.org/api/v2/rubygems/kompressr-sdk/versions/{version}.json', missing=True)
    if value is not None:
        require(value['version'] == version and value['sha'], 'Invalid RubyGems metadata')
    return value


def release(key, version):
    # The tag endpoint excludes drafts. Callers need contents:write for draft
    # visibility; isolated builds/consumers use Actions artifacts instead.
    matches = []
    page = 1
    while True:
        values = github(f'releases?per_page=100&page={page}')
        require(isinstance(values, list), 'Invalid release listing')
        matches.extend(value for value in values if value['tag_name'] == tag(key, version))
        require(len(matches) <= 1, 'Multiple releases use this version tag; reconcile manually')
        if len(values) < 100:
            break
        page += 1
    if not matches:
        return None
    release_id = matches[0]['id']
    require(type(release_id) is int and release_id > 0, 'Invalid release ID')
    value = github(f'releases/{release_id}')
    require(value['id'] == release_id and value['tag_name'] == tag(key, version), 'Release identity changed')
    return value


def asset_names(rel):
    return {a['name'] for a in rel['assets']}


def validate_run(value, sha):
    require(value['repository']['full_name'] == REPO and value['head_repository']['full_name'] == REPO,
            'Verification must belong to this repository')
    require(value['path'] == '.github/workflows/verify.yml' and value['event'] == 'push' and
            value['head_branch'] == 'main' and value['head_sha'] == sha and
            value['status'] == 'completed' and value['conclusion'] == 'success',
            'Expected successful Verify clients push run for this exact main commit')


def repository_controls():
    require(github('branches/main')['protected'], 'Protect main before enabling publication')
    # Reserve tags must survive deletion of a mutable draft. Protect all version
    # tags against updates and deletions, while allowing Actions to create tags.
    rulesets = github('rulesets?per_page=100')
    for ruleset in rulesets:
        if ruleset['target'] != 'tag' or ruleset['enforcement'] != 'active':
            continue
        rules = github('rulesets/' + str(int(ruleset['id'])))
        refs = rules.get('conditions', {}).get('ref_name', {})
        if refs.get('include') == ['~ALL'] and not refs.get('exclude') and {'update', 'deletion'} <= {r['type'] for r in rules['rules']}:
            return
    raise RuntimeError('An active all-tags ruleset must prohibit tag updates and deletions')


def plan():
    require(os.environ['GITHUB_REPOSITORY'] == REPO and os.environ['GITHUB_REF'] == 'refs/heads/main', 'Only upstream main may release')
    repository_controls()
    event = read_json(os.environ['GITHUB_EVENT_PATH'])
    if os.environ['GITHUB_EVENT_NAME'] == 'workflow_run':
        checked = github('actions/runs/' + str(int(event['workflow_run']['id'])))
        sha = checked['head_sha']
    else:
        sha = event.get('inputs', {}).get('sha') or run('git', 'rev-parse', 'origin/main', capture=True).strip()
        require(SHA.fullmatch(sha), 'Retry SHA must be a full commit hash')
        runs = github(f'actions/workflows/verify.yml/runs?event=push&branch=main&head_sha={sha}&per_page=100')['workflow_runs']
        require(bool(runs), 'No Verify clients push run for that commit')
        # A more recent failed rerun must not be hidden by an older successful run.
        checked = max(runs, key=lambda r: r['id'])
    require(SHA.fullmatch(sha), 'Invalid source commit')
    validate_run(checked, sha)
    run('git', 'merge-base', '--is-ancestor', sha, 'origin/main')
    run('git', 'checkout', '--detach', sha)
    configured = os.environ.get('RELEASE_PACKAGES', '')
    selected = {p.strip() for p in configured.split(',') if p.strip()}
    require(selected <= set(KEYS), 'Unknown RELEASE_PACKAGES entry')
    current = run('git', 'rev-parse', 'origin/main', capture=True).strip() == sha == os.environ['GITHUB_SHA']
    pending = []
    builds = []
    for key, version in versions().items():
        if key not in selected:
            continue
        rel = release(key, version)
        if rel is not None and 'release.json' in asset_names(rel):
            with tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                record = download(key, version, directory)
                if complete(directory, record) and not rel['draft']:
                    require(rel.get('immutable') is True, 'Published GitHub release must be immutable')
                    verify_public(key, directory, record)
                    if key != 'mcp-server' or mcp_matches(directory, record) is not None:
                        continue
                require(record['sha'] == sha, f'{key}: resume the original source SHA {record["sha"]}')
                pending.append(key)
        elif registry(key, version) is None:
            if not current:
                print(f'Skipping {key}: no authenticated retained release for this older source commit')
                continue
            require(rel is None, f'{key}: existing release needs manual reconciliation')
            pending.append(key)
            builds.append(key)
    output('builds', builds)
    output('sha', sha)
    output('sdk', str('sdk-js' in pending).lower())
    output('mcp', str('mcp-server' in pending).lower())
    output('packages', [k for k in pending if k not in KEYS[:2]])
    print('Pending packages: ' + (', '.join(pending) or 'none'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gh(*args):
    return run('gh', *args, '--repo', REPO)


def check_tag(key, version, sha):
    ref = github('git/ref/tags/' + urllib.parse.quote(tag(key, version), safe=''), missing=True)
    if ref:
        obj = ref['object']
        for _ in range(5):
            if obj['type'] == 'commit':
                break
            require(obj['type'] == 'tag', 'Unexpected Git object')
            obj = github('git/tags/' + obj['sha'])['object']
        require(obj['type'] == 'commit' and obj['sha'] == sha, 'Release tag points to a different source commit')
    return ref is not None


def validate_record(record, key, version, sha, directory, *, files=True):
    require(SHA.fullmatch(sha) and record['schema'] == 2 and record['package'] == key and record['version'] == version and record['sha'] == sha,
            'Retained release belongs to another source commit; retry its original SHA')
    require(bool(record['files']), 'Empty release record')
    for name, checksum in record['files'].items():
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name) and name not in METADATA and
                re.fullmatch(r'[a-f0-9]{64}', checksum), 'Invalid release asset')
        if files:
            require(not (directory / name).is_symlink() and (directory / name).is_file() and
                    digest(directory / name) == checksum, 'Retained artifact is missing or changed: ' + name)
    if files:
        require(all(p.name in record['files'] or p.name in METADATA for p in directory.iterdir()), 'Unexpected release file')
        require(all(p.is_file() and not p.is_symlink() for p in directory.iterdir()), 'Release assets must be regular files')


def sign_java(directory, version):
    with tempfile.TemporaryDirectory() as temp:
        signing = Path(temp)
        env = {**os.environ, 'GNUPGHOME': temp}
        run('gpg', '--batch', '--import', env=env, input=os.environ['MAVEN_GPG_PRIVATE_KEY'], capture=True)
        key = os.environ['MAVEN_GPG_FINGERPRINT']
        require(re.fullmatch(r'[A-Fa-f0-9]{40,64}', key), 'Expected full GPG fingerprint')
        bundle = signing / 'bundle' / 'com/kompressr/kompressr-sdk' / version
        bundle.mkdir(parents=True)
        for file in java_inputs(directory, version):
            target = bundle / file.name
            shutil.copyfile(file, target)
            run('gpg', '--batch', '--yes', '--pinentry-mode', 'loopback', '--passphrase-fd', '0',
                '--local-user', key, '--armor', '--detach-sign', str(target), env=env,
                input=os.environ['MAVEN_GPG_PASSPHRASE'] + '\n')
        for file in list(bundle.iterdir()):
            for algorithm in ('md5', 'sha1', 'sha256', 'sha512'):
                (bundle / (file.name + '.' + algorithm)).write_text(hashlib.new(algorithm, file.read_bytes()).hexdigest())
        with zipfile.ZipFile(directory / 'central-bundle.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in bundle.iterdir():
                archive.write(file, file.relative_to(signing / 'bundle'))


def sdk_dependency():
    lock = read_json(ROOT / 'mcp-server/package-lock.json')['packages']['node_modules/@kompressr/sdk']
    data = registry('sdk-js', lock['version'])
    require(data is not None and data['dist']['integrity'] == lock['integrity'], 'MCP needs the exact SDK lockfile artifact on public npm')


def build(key, version, directory):
    extra = {}
    if key in KEYS[:2]:
        run('npm', '--prefix', 'sdk-js', 'ci', '--ignore-scripts')
        run('node', 'scripts/verify.mjs')
        if key == 'mcp-server':
            sdk_dependency()
            run('node', 'scripts/build-mcp-release.mjs', str(directory))
        else:
            run('npm', 'pack', '--pack-destination', str(directory), cwd=ROOT / 'sdk-js')
    else:
        run('node', 'scripts/verify-all.mjs', key)
        patterns = {'python': ['sdk-python/dist/*.whl', 'sdk-python/dist/*.tar.gz'],
                    'java': [f'sdk-java/target/kompressr-sdk-{version}*.jar'],
                    'dotnet': [f'sdk-dotnet/artifacts/Kompressr.Sdk.{version}.nupkg'],
                    'php': [f'sdk-php/dist/kompressr-sdk-{version}.tar'],
                    'ruby': [f'sdk-ruby/pkg/kompressr-sdk-{version}.gem'], 'go': []}
        for pattern in patterns[key]:
            files = list(ROOT.glob(pattern))
            require(bool(files), 'No artifact for ' + pattern)
            for file in files:
                shutil.copyfile(file, directory / file.name)
        if key == 'java':
            shutil.copyfile(ROOT / 'sdk-java/pom.xml', directory / f'kompressr-sdk-{version}.pom')
        if key == 'php':
            extra['mirror_sha'] = run('git', 'subtree', 'split', '--prefix=sdk-php', 'HEAD', capture=True).strip()
            require(SHA.fullmatch(extra['mirror_sha']), 'Invalid PHP subtree commit')
        if key == 'go':
            # Go's registry artifact is derived from the immutable Git tag.
            (directory / 'module.txt').write_text(f'github.com/{REPO}/sdk-go v{version}\n')
    return extra


METADATA = {'release.json', 'release.intoto.jsonl', 'published.json', 'published.intoto.jsonl',
            'central-deployment.json', 'central-upload-started.json', 'candidate.json'}


def source_sha():
    return run('git', 'rev-parse', 'HEAD', capture=True).strip()


def verify_attestation(path, *, sha=None):
    bundle = path.with_name(path.stem + '.intoto.jsonl')
    require(path.is_file() and bundle.is_file() and not path.is_symlink() and not bundle.is_symlink(),
            'Missing authenticated release record; reconcile manually')
    args = ['gh', 'attestation', 'verify', str(path), '--bundle', str(bundle), '--repo', REPO,
            '--signer-workflow', SIGNER, '--source-ref', 'refs/heads/main',
            '--deny-self-hosted-runners', '--predicate-type', 'https://slsa.dev/provenance/v1']
    if sha is not None:
        args += ['--source-digest', sha]
    run(*args, cwd=CONTROL_ROOT)


def authenticated(key, directory, *, sha=None):
    record = read_json(directory / 'release.json')
    require(SHA.fullmatch(record['sha']), 'Invalid retained source commit')
    verify_attestation(directory / 'release.json', sha=record['sha'])
    validate_record(record, key, versions()[key], sha or source_sha(), directory)
    return record


def download_asset(rel, name, directory):
    matches = [asset for asset in rel['assets'] if asset['name'] == name]
    require(len(matches) == 1, 'Missing or duplicate release asset: ' + name)
    asset_id = matches[0]['id']
    require(type(asset_id) is int and asset_id > 0, 'Invalid release asset ID')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name), 'Invalid asset filename')
    with (directory / name).open('xb') as file:
        subprocess.run(['gh', 'api', f'repos/{REPO}/releases/assets/{asset_id}',
                        '--header', 'Accept: application/octet-stream'],
                       cwd=CONTROL_ROOT, stdout=file, check=True)


def download(key, version, directory):
    # Authenticate metadata before it can select filenames or affect publication.
    rel = release(key, version)
    require(rel is not None and {'release.json', 'release.intoto.jsonl'} <= asset_names(rel),
            'Existing release has no authenticated record; reconcile it manually')
    for name in ('release.json', 'release.intoto.jsonl'):
        download_asset(rel, name, directory)
    record = read_json(directory / 'release.json')
    require(SHA.fullmatch(record['sha']), 'Invalid retained source commit')
    verify_attestation(directory / 'release.json', sha=record['sha'])
    validate_record(record, key, version, record['sha'], directory, files=False)
    for name in record['files']:
        download_asset(rel, name, directory)
    for name in ('published.json', 'published.intoto.jsonl', 'central-deployment.json', 'central-upload-started.json'):
        if name in asset_names(rel):
            download_asset(rel, name, directory)
    validate_record(record, key, version, record['sha'], directory)
    check_tag(key, version, record['sha'])
    return record


def inspect(key, directory):
    directory.mkdir(parents=True)
    version = versions()[key]
    rel = release(key, version)
    if rel is not None:
        record = download(key, version, directory)
        require(record['sha'] == source_sha(), 'Retry must use the retained source commit')
    else:
        require(source_sha() == os.environ['GITHUB_SHA'], 'New releases must use the workflow source commit')
        require(not check_tag(key, version, source_sha()), 'Tag exists without authenticated release state; reconcile manually')
        require(registry(key, version) is None, 'Version appeared in registry; re-plan before building')
    output('resume', str(rel is not None).lower())


def build_candidate(key, directory):
    require(not any(directory.iterdir()), 'Build directory must be empty')
    version = versions()[key]
    extra = build(key, version, directory)
    record = {'schema': 2, 'package': key, 'version': version, 'sha': source_sha(),
              'files': {p.name: digest(p) for p in directory.iterdir()}, **extra}
    validate_record(record, key, version, source_sha(), directory)
    write_json(directory / 'candidate.json', record)


def java_inputs(directory, version):
    names = [f'kompressr-sdk-{version}{suffix}' for suffix in ('.jar', '-sources.jar', '-javadoc.jar', '.pom')]
    require(all((directory / n).is_file() for n in names), 'Missing Java release input')
    return [directory / n for n in names]


def seal(key, directory):
    version, sha = versions()[key], source_sha()
    if (directory / 'release.json').exists():
        authenticated(key, directory)
        output('fresh', 'false')
    else:
        require(release(key, version) is None, 'Restore the authenticated retained release before sealing a candidate')
        require(sha == os.environ['GITHUB_SHA'], 'Only the workflow source commit may create provenance')
        record = read_json(directory / 'candidate.json')
        validate_record(record, key, version, sha, directory)
        (directory / 'candidate.json').unlink()
        if key == 'java':
            sign_java(directory, version)
        files = {p.name: digest(p) for p in directory.iterdir() if p.name != 'SHA256SUMS'}
        (directory / 'SHA256SUMS').write_text(''.join(f'{v}  {k}\n' for k, v in sorted(files.items())))
        record['files'] = {**files, 'SHA256SUMS': digest(directory / 'SHA256SUMS')}
        write_json(directory / 'release.json', record)
        output('fresh', 'true')


def retain(key, directory):
    record = authenticated(key, directory)
    version, sha = record['version'], record['sha']
    check_tag(key, version, sha)
    rel = release(key, version)
    if rel is None:
        require(not check_tag(key, version, sha), 'Tag exists without authenticated release state; reconcile manually')
        require(registry(key, version) is None, 'Version appeared in registry; stop and reconcile')
        gh('release', 'create', tag(key, version), '--draft', '--latest=false', '--target', sha,
           '--title', f'{key} {version}', '--notes', f'{key} {version}\n\nSource: {sha}')
        gh('release', 'upload', tag(key, version), *[str(directory / name) for name in record['files']],
           str(directory / 'release.intoto.jsonl'))
        gh('release', 'upload', tag(key, version), str(directory / 'release.json'))
    else:
        with tempfile.TemporaryDirectory() as temp:
            remote = Path(temp)
            download(key, version, remote)
            require((remote / 'release.json').read_bytes() == (directory / 'release.json').read_bytes(),
                    'Remote release record changed')
    # Reserve the version after retaining files. Protected tags prevent a deleted
    # draft from authorizing a rebuild or replay of an ambiguous registry upload.
    if not check_tag(key, version, sha):
        github('git/refs', data={'ref': 'refs/tags/' + tag(key, version), 'sha': sha})
    output('fresh', str(rel is None).lower())
    output('upload', str(needs_upload(key, version, record)).lower())
    if key == 'python':
        packages = directory.parent / 'pypi-dist'
        packages.mkdir()
        for name in record['files']:
            if name.endswith(('.whl', '.tar.gz')):
                shutil.copyfile(directory / name, packages / name)


def handoff(key, directory):
    record = authenticated(key, directory)
    destination = directory.parent / 'consumer-artifacts'
    destination.mkdir()
    names = set(record['files']) | {'release.json', 'release.intoto.jsonl'}
    for name in names:
        shutil.copyfile(directory / name, destination / name)
    authenticated(key, destination)


def completion(record, directory):
    return {'schema': 1, 'package': record['package'], 'version': record['version'],
            'sha': record['sha'], 'release_sha256': digest(directory / 'release.json')}


def complete(directory, record):
    if not (directory / 'published.json').exists():
        return False
    verify_attestation(directory / 'published.json')
    require(read_json(directory / 'published.json') == completion(record, directory), 'Completion receipt differs')
    return True


def needs_upload(key, version, record):
    data = registry(key, version)
    if data is None:
        return True
    if key == 'python':
        expected = {n: h for n, h in record['files'].items() if n.endswith(('.whl', '.tar.gz'))}
        present = {u['filename']: u['digests']['sha256'] for u in data['urls']}
        require(all(name in expected and expected[name] == checksum for name, checksum in present.items()),
                'Existing PyPI files differ from the retained release')
        return set(present) != set(expected)
    return False


def wait_for(function, description, attempts=30):
    for attempt in range(attempts):
        result = function()
        if result is not None:
            return result
        if attempt + 1 < attempts:
            time.sleep(20)
    raise RuntimeError('Timed out waiting for ' + description + '; retry the same release')


def central(directory, record):
    version = record['version']
    credentials = base64.b64encode((os.environ['MAVEN_CENTRAL_USERNAME'] + ':' + os.environ['MAVEN_CENTRAL_PASSWORD']).encode()).decode()
    headers = {'Authorization': 'Bearer ' + credentials}
    state = directory / 'central-deployment.json'
    marker = directory / 'central-upload-started.json'
    if state.exists():
        deployment = read_json(state)['id']
    else:
        # If the request succeeded but its response was lost, inspect Central before retrying.
        require(os.environ.get('RELEASE_FRESH') == 'true' and not marker.exists(), 'Central upload outcome is unknown. Recover its deployment ID from Central into central-deployment.json before retrying; deleting markers never authorizes another upload.')
        write_json(marker, {'sha': record['sha']})
        gh('release', 'upload', tag('java', version), str(marker))
        boundary = 'kompressr-' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="bundle"; filename="central-bundle.zip"\r\nContent-Type: application/zip\r\n\r\n'.encode() +
                (directory / 'central-bundle.zip').read_bytes() + f'\r\n--{boundary}--\r\n'.encode())
        raw = request('https://central.sonatype.com/api/v1/publisher/upload?publishingType=AUTOMATIC&name=kompressr-sdk-' + version,
                      method='POST', data=body, headers={**headers, 'Content-Type': 'multipart/form-data; boundary=' + boundary})
        deployment = raw.decode().strip().strip('"')
        require(re.fullmatch(r'[a-fA-F0-9-]{36}', deployment), 'Invalid Central deployment ID')
        write_json(state, {'id': deployment})
        gh('release', 'upload', tag('java', version), str(state))
    require(re.fullmatch(r'[a-fA-F0-9-]{36}', deployment), 'Invalid retained Central deployment ID')
    def status():
        data = get_json('https://central.sonatype.com/api/v1/publisher/status?id=' + deployment, method='POST', headers=headers)
        require(data['deploymentState'] in ('PENDING', 'VALIDATING', 'VALIDATED', 'PUBLISHING', 'PUBLISHED'), 'Central deployment failed; inspect its validation report')
        return data if data['deploymentState'] == 'PUBLISHED' else None
    wait_for(status, 'Central publication', attempts=90)


def php_push(record):
    expected = record['mirror_sha']
    require(SHA.fullmatch(expected), 'Invalid mirror commit')
    split = run('git', 'subtree', 'split', '--prefix=sdk-php', 'HEAD', capture=True).strip()
    require(split == expected, 'PHP split changed')
    with tempfile.TemporaryDirectory() as temp:
        askpass = Path(temp) / 'askpass'
        askpass.write_text('#!/bin/sh\ncase "$1" in *Username*) echo x-access-token;; *) printf "%s\\n" "$PHP_MIRROR_TOKEN";; esac\n')
        askpass.chmod(0o700)
        env = {**os.environ, 'GIT_ASKPASS': str(askpass), 'GIT_TERMINAL_PROMPT': '0'}
        url = 'https://github.com/kompressrcdn/sdk-php.git'
        existing = run('git', 'ls-remote', url, 'refs/tags/v' + record['version'], capture=True, env=env).strip()
        if existing:
            require(existing.split()[0] == split, 'PHP mirror tag already points to different contents')
        else:
            # Atomic, non-forcing update: divergent mirror edits must be reconciled by a maintainer.
            run('git', 'push', '--atomic', url, f'{split}:refs/heads/main', f'{split}:refs/tags/v{record["version"]}', env=env)


def npm_version_must_advance(key, version):
    name = '@kompressr/sdk' if key == 'sdk-js' else '@kompressr/mcp-server'
    data = get_json('https://registry.npmjs.org/' + urllib.parse.quote(name, safe=''), missing=True)
    if data is not None:
        stable = [tuple(map(int, v.split('.'))) for v in data['versions'] if STABLE.fullmatch(v)]
        require(not stable or tuple(map(int, version.split('.'))) > max(stable),
                'A new npm release must advance the highest stable version; do not move latest backwards')


def publish(key, directory):
    record = authenticated(key, directory)
    version = record['version']
    if registry(key, version) is not None:
        return
    if key in KEYS[:2]:
        require(record['sha'] == os.environ['GITHUB_SHA'], 'An unpublished npm artifact must be uploaded by rerunning its original workflow so npm provenance keeps the original commit')
        tarballs = [directory / name for name in record['files'] if name.endswith('.tgz')]
        require(len(tarballs) == 1, 'Expected one npm package')
        npm_version_must_advance(key, version)
        run('npm', 'publish', str(tarballs[0]), '--registry=https://registry.npmjs.org', '--access', 'public', '--tag', 'latest', '--provenance', '--ignore-scripts', cwd=directory)
    elif key == 'java':
        central(directory, record)
    elif key == 'dotnet':
        run('dotnet', 'nuget', 'push', str(directory / f'Kompressr.Sdk.{version}.nupkg'), '--source', 'https://api.nuget.org/v3/index.json', '--api-key', os.environ['NUGET_API_KEY'], cwd=directory)
    elif key == 'ruby':
        run('gem', 'push', str(directory / f'kompressr-sdk-{version}.gem'), cwd=directory)
    elif key == 'php':
        php_push(record)
    elif key == 'go':
        check_tag(key, version, record['sha'])
        github('git/refs', data={'ref': 'refs/tags/' + tag(key, version), 'sha': record['sha']})
    else:
        require(key == 'python', 'Unknown package')  # PyPI's official action publishes the prepared files.


def compare_zip(expected, actual):
    def members(raw):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            require(len(names) == len(set(names)), 'Duplicate ZIP entries')
            return {n: archive.read(n) for n in names if n != '.signature.p7s' and not n.endswith('/')}
    require(members(expected) == members(actual), 'NuGet package payload differs from the prepared artifact')


def verify_public(key, directory, record):
    version = record['version']
    # NuGet validates and signs accepted uploads asynchronously before download.
    # Poll for roughly 30 minutes; the consumer job has a hard 45-minute limit.
    data = wait_for(lambda: registry(key, version), key + ' registry metadata',
                    attempts=91 if key == 'dotnet' else 30)
    if key in KEYS[:2]:
        raw = request(data['dist']['tarball'])
        expected = next(directory.glob('*.tgz')).read_bytes()
        require(raw == expected, 'Public npm artifact differs')
    elif key == 'python':
        expected = {n: h for n, h in record['files'].items() if n.endswith(('.whl', '.tar.gz'))}
        require({u['filename'] for u in data['urls']} == set(expected), 'PyPI release files differ')
        for file in data['urls']:
            require(hashlib.sha256(request(file['url'])).hexdigest() == expected[file['filename']], 'Public PyPI artifact differs')
    elif key == 'ruby':
        require(hashlib.sha256(request(f'https://rubygems.org/downloads/kompressr-sdk-{version}.gem')).hexdigest() == record['files'][f'kompressr-sdk-{version}.gem'], 'Public gem differs')
    elif key == 'dotnet':
        raw = request(f'https://api.nuget.org/v3-flatcontainer/kompressr.sdk/{version}/kompressr.sdk.{version}.nupkg')
        compare_zip((directory / f'Kompressr.Sdk.{version}.nupkg').read_bytes(), raw)
    elif key == 'java':
        for name, checksum in record['files'].items():
            if name.endswith(('.jar', '.pom')):
                raw = request(f'https://repo.maven.apache.org/maven2/com/kompressr/kompressr-sdk/{version}/{name}')
                require(hashlib.sha256(raw).hexdigest() == checksum, 'Public Maven artifact differs')
    elif key == 'php':
        require(data.get('source', {}).get('reference') == record['mirror_sha'], 'Packagist source reference differs')
    else:
        check_tag(key, version, record['sha'])


def normalized_mcp_packages(packages):
    # Input defaults from the 2025-12-11 MCP schema. Registry serialization can
    # omit them; all other package fields must remain identical.
    packages = json.loads(json.dumps(packages))

    def normalize_input(value, *, argument=False):
        for key, default in (('isRequired', False), ('isSecret', False), ('format', 'string')):
            value.setdefault(key, default)
        if argument:
            value.setdefault('isRepeated', False)
        for nested in value.get('variables', {}).values():
            normalize_input(nested)

    for package in packages:
        for value in package.get('environmentVariables', []):
            normalize_input(value)
        for field in ('packageArguments', 'runtimeArguments'):
            for value in package.get(field, []):
                normalize_input(value, argument=True)
        transport = package.get('transport', {})
        for value in transport.get('headers', []):
            normalize_input(value)
        for value in transport.get('variables', {}).values():
            normalize_input(value)
    # JSON equality retains the distinction between booleans and integers.
    return json.dumps(packages, sort_keys=True, separators=(',', ':'))


def mcp_matches(directory, record):
    url = 'https://registry.modelcontextprotocol.io/v0.1/servers/com.kompressr%2Fkompressr/versions/' + record['version']
    expected = read_json(directory / 'server.json')
    data = get_json(url, missing=True)
    if data is not None:
        actual = data['server']
        require(actual['name'] == expected['name'] and actual['version'] == expected['version'] and
                normalized_mcp_packages(actual['packages']) == normalized_mcp_packages(expected['packages']),
                'Published MCP metadata differs')
    return data


def mcp_registry(directory, record):
    if mcp_matches(directory, record) is None:
        run('mcp-publisher', 'login', 'dns', '--domain', 'kompressr.com', '--private-key', os.environ['MCP_REGISTRY_PRIVATE_KEY'], cwd=directory)
        run('mcp-publisher', 'publish', str(directory / 'server.json'), cwd=directory)
        wait_for(lambda: mcp_matches(directory, record), 'MCP Registry')


def consume(key, directory):
    record = authenticated(key, directory)
    verify_public(key, directory, record)
    run(sys.executable, str(CONTROL_ROOT / 'scripts/release/consumer.py'), key, record['version'],
        env=consumer_environment())


def consumer_environment():
    # The runner boundary is primary. This allowlist also protects manual invocations.
    allowed = ('PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'JAVA_HOME', 'DOTNET_ROOT',
               'SYSTEMROOT', 'RELEASE_SOURCE')
    return {key: os.environ[key] for key in allowed if key in os.environ}


def receipt(key, directory):
    record = authenticated(key, directory)
    check_tag(key, record['version'], record['sha'])
    verify_public(key, directory, record)
    if complete(directory, record):
        output('fresh', 'false')
    else:
        write_json(directory / 'published.json', completion(record, directory))
        if (directory / 'published.intoto.jsonl').exists():
            require(complete(directory, record), 'Partial completion receipt is invalid')
            output('fresh', 'false')
        else:
            output('fresh', 'true')


def finish(key, directory):
    record = authenticated(key, directory)
    require(complete(directory, record), 'Authenticated consumer completion required')
    version = record['version']
    # Re-read the remote draft immediately before making its assets public.
    with tempfile.TemporaryDirectory() as temp:
        remote = Path(temp)
        download(key, version, remote)
        require((remote / 'release.json').read_bytes() == (directory / 'release.json').read_bytes(), 'Remote record changed')
        if not complete(remote, record):
            if (remote / 'published.intoto.jsonl').exists():
                shutil.copyfile(directory / 'published.json', remote / 'published.json')
                require(complete(remote, record), 'Partial remote completion is invalid')
            else:
                gh('release', 'upload', tag(key, version), str(directory / 'published.intoto.jsonl'))
            gh('release', 'upload', tag(key, version), str(directory / 'published.json'))
    if release(key, version)['draft']:
        gh('release', 'edit', tag(key, version), '--draft=false', '--latest=false')
    # The settings endpoint requires Administration:read, which GITHUB_TOKEN
    # deliberately lacks. Check the public release property instead.
    require(release(key, version).get('immutable') is True, 'GitHub release is not immutable; stop and reconcile before registry admission')
    if key == 'mcp-server':
        mcp_registry(directory, record)
    print(f'Published and checked {key} {version} from {record["sha"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('versions', 'plan', 'inspect', 'build_candidate', 'seal', 'retain', 'publish', 'handoff', 'authenticated', 'consume', 'receipt', 'finish'))
    parser.add_argument('package', nargs='?', choices=KEYS)
    parser.add_argument('directory', nargs='?', type=Path)
    args = parser.parse_args()
    if args.command == 'versions':
        print(json.dumps(versions(), indent=2))
    elif args.command == 'plan':
        plan()
    else:
        require(args.package and args.directory and args.directory.is_absolute(), 'Package and absolute artifact directory required')
        globals()[args.command](args.package, args.directory)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, KeyError, ValueError, urllib.error.URLError, subprocess.CalledProcessError) as exc:
        # CalledProcessError includes command arguments, which may contain authentication data.
        print('Release failed: ' + ('external command failed; see preceding output' if isinstance(exc, subprocess.CalledProcessError) else str(exc)), file=sys.stderr)
        sys.exit(1)
