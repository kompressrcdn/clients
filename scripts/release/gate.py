"""Require successful affected-package checks; accept only deliberate skips."""
import json
import os
from changes import KEYS

JOBS = ('changes', 'release-tools', 'verify', 'python', 'go', 'java', 'dotnet', 'php', 'ruby')


def check(results, packages):
    if not isinstance(packages, list) or len(set(packages)) != len(packages) or not set(packages) <= set(KEYS):
        raise ValueError('Invalid affected-package selection')
    if set(results) != set(JOBS):
        raise ValueError('Missing or unexpected verification jobs')
    required = {'changes', 'release-tools'} | (set(packages) - set(KEYS[:2]))
    if set(packages) & set(KEYS[:2]):
        required.add('verify')
    wrong = {job: results[job].get('result') for job in JOBS
             if results[job].get('result') != ('success' if job in required else 'skipped')}
    if wrong:
        raise ValueError('Verification did not pass: ' + str(wrong))


if __name__ == '__main__':
    check(json.loads(os.environ['CHECK_RESULTS']), json.loads(os.environ['EXPECTED_PACKAGES']))
