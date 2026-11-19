"""Select affected client packages from a complete Git change range."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
KEYS = ('sdk-js', 'mcp-server', 'python', 'go', 'java', 'dotnet', 'php', 'ruby')
SHA = re.compile(r'[a-f0-9]{40}\Z')
DIRECTORIES = {key if key in KEYS[:2] else 'sdk-' + key: key for key in KEYS}


def select_paths(paths):
    verify, publish = set(), set()
    for path in paths:
        top = path.split('/', 1)[0]
        if top in DIRECTORIES:
            affected = {DIRECTORIES[top]}
            if top == 'sdk-js':
                affected.add('mcp-server')
            verify.update(affected)
            publish.update(affected)
        elif top == 'smithery':
            verify.add('mcp-server')
            publish.add('mcp-server')
        elif path in ('scripts/release/changes.py', 'scripts/release/gate.py',
                      'scripts/release/test_changes.py', '.github/workflows/verify.yml'):
            verify.update(KEYS)
        elif path.startswith(('scripts/release/', '.github/actions/release-')) or path in (
                '.github/workflows/publish.yml', '.github/workflows/release-check.yml',
                '.github/workflows/mcp-release.yml'):
            # The always-required release-tools job covers this machinery.
            continue
        elif top in ('guides', 'skills') or path in ('README.md', 'CONTRIBUTING.md', 'SECURITY.md',
                                                   'AGENTS.md', 'LICENSE', '.gitignore', '.github/CODEOWNERS'):
            continue
        else:
            # Shared contracts/build tools and unknown inputs are conservative.
            verify.update(KEYS)
    return {'packages': [key for key in KEYS if key in verify],
            'publish': [key for key in KEYS if key in publish]}


def git(*args, root=ROOT):
    return subprocess.check_output(['git', *args], cwd=root)


def selection(base, head, *, root=ROOT):
    if not SHA.fullmatch(base) or not SHA.fullmatch(head):
        raise ValueError('Expected full Git commit IDs')
    git('cat-file', '-e', head + '^{commit}', root=root)
    if base == '0' * 40:
        paths = git('ls-tree', '-r', '--name-only', '-z', head, root=root)
    else:
        try:
            git('cat-file', '-e', base + '^{commit}', root=root)
        except subprocess.CalledProcessError:
            return {'schema': 1, 'base': base, 'head': head, 'fallback': True,
                    'packages': list(KEYS), 'publish': list(KEYS)}
        # Disabling rename detection selects both the removed and added path.
        paths = git('diff', '--name-only', '--no-renames', '-z', base, head, '--', root=root)
    names = paths.decode('utf-8', errors='surrogateescape').rstrip('\0').split('\0') if paths else []
    return {'schema': 1, 'base': base, 'head': head, 'fallback': False, **select_paths(names)}


def from_event(event_name, event, sha, *, root=ROOT):
    if event_name == 'pull_request':
        pr = event['pull_request']
        if pr['base']['ref'] != 'main':
            raise ValueError('Only pull requests targeting main are supported')
        base, head = pr['base']['sha'], pr['head']['sha']
        if not SHA.fullmatch(base) or not SHA.fullmatch(head):
            raise ValueError('Expected full pull-request commit IDs')
        base = git('merge-base', base, head, root=root).decode().strip()
    elif event_name == 'push' and event['ref'] == 'refs/heads/main' and event['after'] == sha:
        base, head = event['before'], sha
    else:
        raise ValueError('Expected a main push or pull request')
    return selection(base, head, root=root)


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    result = from_event(os.environ['GITHUB_EVENT_NAME'], event, os.environ['GITHUB_SHA'])
    Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        for name in ('packages', 'publish'):
            output.write(name + '=' + json.dumps(result[name], separators=(',', ':')) + '\n')
    print('Verify: ' + (', '.join(result['packages']) or 'common checks only'))
    print('Release candidates: ' + (', '.join(result['publish']) or 'none'))


if __name__ == '__main__':
    main()
