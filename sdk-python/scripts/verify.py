"""Build, inspect and test source plus a fresh installed wheel; never publish."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=ROOT, env=None):
    print('+ ' + ' '.join(str(x) for x in args), flush=True)
    subprocess.run([str(x) for x in args], check=True, cwd=cwd, env=env)


def inspect_file(name, data):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or any(p in ('.git', '.venv', '__pycache__', 'node_modules') for p in path.parts):
        raise RuntimeError(f'Unexpected archive path: {name}')
    if path.name.startswith('.env') or path.suffix in ('.pyc', '.pem', '.key'):
        raise RuntimeError(f'Unexpected archive file: {name}')
    text = data.decode('utf-8')
    # Distribution content must be text, public-safe and independent of a checkout.
    forbidden = [r'/(?:home|Users)/[^/\s]+/', r'-----BEGIN [A-Z ]*PRIVATE KEY-----', r'AKIA[A-Z0-9]{16}', r'gh[pousr]_[A-Za-z0-9]{30,}']
    if any(re.search(pattern, text) for pattern in forbidden):
        raise RuntimeError(f'Private credential or machine path in archive: {name}')


def inspect_archive(artifact):
    names = []
    if artifact.suffix == '.whl':
        with zipfile.ZipFile(artifact) as archive:
            for item in archive.infolist():
                if item.is_dir():
                    continue
                if item.file_size > 2 * 1024 * 1024:
                    raise RuntimeError(f'Unexpected large archive member: {item.filename}')
                names.append(item.filename)
                inspect_file(item.filename, archive.read(item))
        if 'kompressr/py.typed' not in names or not any(n.endswith('/licenses/LICENSE') for n in names):
            raise RuntimeError('Wheel is missing typing marker or license.')
        if any(n.startswith(('tests/', 'examples/', 'scripts/')) for n in names):
            raise RuntimeError('Wheel unexpectedly contains development files.')
    else:
        with tarfile.open(artifact, 'r:gz') as archive:
            for item in archive:
                if not item.isfile():
                    if not item.isdir():
                        raise RuntimeError(f'Unsupported archive member: {item.name}')
                    continue
                names.append(item.name)
                content = archive.extractfile(item)
                assert content is not None
                inspect_file(item.name, content.read())
        required = ('README.md', 'API.md', 'PARITY.md', 'PUBLISHING.md', 'tests/test_sdk.py', 'tests/file-lifecycle.json')
        for relative in required:
            if not any(n.endswith('/' + relative) for n in names):
                raise RuntimeError(f'Source distribution missing {relative}')
    print(f'Inspected {len(names)} public text members in {artifact.name}', flush=True)


def main():
    manifest = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    version = manifest['project']['version']
    from kompressr import __version__
    if __version__ != version:
        raise RuntimeError('Package and manifest versions disagree.')
    shared_fixture = ROOT.parent / 'contracts' / 'fixtures' / 'file-lifecycle.json'
    if shared_fixture.exists() and shared_fixture.read_bytes() != (ROOT / 'tests' / 'file-lifecycle.json').read_bytes():
        raise RuntimeError('Package lifecycle fixture differs from the shared contract fixture.')
    run(sys.executable, '-m', 'mypy', 'src/kompressr')
    run(sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v')
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    # Build in an empty destination; only replace this version's two owned artifacts.
    with tempfile.TemporaryDirectory(prefix='kompressr-python-verify-') as temporary:
        temp = Path(temporary)
        run(sys.executable, '-m', 'build', '--outdir', temp / 'dist')
        artifacts = sorted((temp / 'dist').iterdir())
        if len(artifacts) != 2:
            raise RuntimeError('Expected exactly one wheel and one source distribution.')
        for artifact in artifacts:
            inspect_archive(artifact)
        run(sys.executable, '-m', 'twine', 'check', '--strict', *artifacts)
        wheel = next(p for p in artifacts if p.suffix == '.whl')
        consumer = temp / 'consumer'
        consumer.mkdir()
        environment = temp / 'venv'
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        run(python, '-m', 'pip', 'install', wheel, cwd=consumer)
        shutil.copytree(ROOT / 'tests', consumer / 'tests', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / 'examples', consumer / 'examples', ignore=shutil.ignore_patterns('__pycache__'))
        clean_env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
        clean_env['PYTHONNOUSERSITE'] = '1'
        run(python, '-c', 'import kompressr; from pathlib import Path; assert "site-packages" in str(Path(kompressr.__file__)); print("Installed wheel:", kompressr.__version__)', cwd=consumer, env=clean_env)
        # Test-only certificate generation; the wheel itself needs no cryptography.
        run(python, '-m', 'pip', 'install', 'cryptography>=45,<51', cwd=consumer, env=clean_env)
        run(python, '-m', 'unittest', 'discover', '-s', 'tests', '-v', cwd=consumer, env=clean_env)
        (consumer / 'typed_consumer.py').write_text('''from kompressr import AsyncKompressrClient, KompressrClient, UploadAccepted, UploadAsset

def sync(files: KompressrClient) -> UploadAsset:
    accepted: UploadAccepted = files.upload_bytes(b"example", "example.png")
    return files.wait_until_ready(accepted["id"])

async def asynchronous(files: AsyncKompressrClient) -> UploadAsset:
    accepted = await files.upload_bytes(b"example", "example.png")
    return await files.wait_until_ready(accepted["id"])
''')
        run(sys.executable, '-m', 'mypy', '--strict', '--python-executable', python, consumer / 'typed_consumer.py', cwd=consumer, env=clean_env)
        for artifact in artifacts:
            destination = dist / artifact.name
            shutil.copy2(artifact, destination)
            print(f'{destination.name} sha256={hashlib.sha256(destination.read_bytes()).hexdigest()}', flush=True)
    print('Python SDK source, distributions and installed consumer verified. No live API requests or publication performed.')


if __name__ == '__main__':
    main()
