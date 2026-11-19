from pathlib import Path
import subprocess
import tempfile
import unittest

import changes
import gate


class SelectionTests(unittest.TestCase):
    def test_each_package_selects_its_supported_matrix_and_release(self):
        for directory, key in changes.DIRECTORIES.items():
            expected = ['sdk-js', 'mcp-server'] if key == 'sdk-js' else [key]
            with self.subTest(key=key):
                self.assertEqual(changes.select_paths([directory + '/src/file']),
                                 {'packages': expected, 'publish': expected})

    def test_mcp_and_bundle_changes_do_not_require_sdk_tests(self):
        for path in ('mcp-server/src/tools/upload.ts', 'smithery/manifest.json'):
            self.assertEqual(changes.select_paths([path])['packages'], ['mcp-server'])

    def test_shared_and_unknown_inputs_verify_all_without_releasing_unchanged_packages(self):
        for path in ('contracts/kompressr-api.yaml', 'scripts/verify.mjs', '.github/workflows/verify.yml',
                     'scripts/release/changes.py', 'scripts/release/gate.py', 'new-build-config.json'):
            with self.subTest(path=path):
                self.assertEqual(changes.select_paths([path]), {'packages': list(changes.KEYS), 'publish': []})

    def test_root_docs_and_release_tools_need_only_common_checks(self):
        for path in ('README.md', 'guides/private-upload.md', 'skills/kompressr/SKILL.md',
                     'scripts/release/release.py', 'scripts/release/test_release.py',
                     '.github/workflows/publish.yml', '.github/actions/release-publish/action.yml'):
            with self.subTest(path=path):
                self.assertEqual(changes.select_paths([path]), {'packages': [], 'publish': []})

    def test_package_documentation_is_still_part_of_the_distribution(self):
        self.assertEqual(changes.select_paths(['sdk-python/README.md'])['packages'], ['python'])

    def test_empty_changes_and_duplicate_paths(self):
        self.assertEqual(changes.select_paths([]), {'packages': [], 'publish': []})
        self.assertEqual(changes.select_paths(['sdk-go/go.mod'] * 2)['packages'], ['go'])


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.com')
        self.git('config', 'user.name', 'Fixture')
        self.base = self.commit('README.md', 'initial')

    def git(self, *args):
        return changes.git(*args, root=self.root).decode().strip()

    def commit(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self.git('add', '--', name)
        self.git('commit', '-qm', 'Fixture change')
        return self.git('rev-parse', 'HEAD')

    def test_push_includes_every_commit_in_the_event_range(self):
        self.commit('sdk-python/client.py', 'python')
        head = self.commit('sdk-go/client.go', 'go')
        event = {'ref': 'refs/heads/main', 'before': self.base, 'after': head}
        self.assertEqual(changes.from_event('push', event, head, root=self.root)['packages'], ['python', 'go'])

    def test_pr_uses_merge_base_and_excludes_unrelated_base_branch_changes(self):
        self.git('checkout', '-qb', 'feature')
        head = self.commit('sdk-python/client.py', 'python')
        self.git('checkout', '-q', 'main')
        base_tip = self.commit('sdk-go/client.go', 'go')
        event = {'pull_request': {'base': {'ref': 'main', 'sha': base_tip}, 'head': {'sha': head}}}
        result = changes.from_event('pull_request', event, base_tip, root=self.root)
        self.assertEqual(result['base'], self.base)
        self.assertEqual(result['packages'], ['python'])

    def test_rename_between_packages_selects_both(self):
        base = self.commit('sdk-python/example.txt', 'same bytes')
        (self.root / 'sdk-go').mkdir()
        self.git('mv', 'sdk-python/example.txt', 'sdk-go/example.txt')
        self.git('commit', '-qm', 'Rename')
        self.assertEqual(changes.selection(base, self.git('rev-parse', 'HEAD'), root=self.root)['packages'], ['python', 'go'])

    def test_deleted_package_file_is_selected(self):
        base = self.commit('sdk-ruby/example.rb', 'example')
        self.git('rm', '-q', 'sdk-ruby/example.rb')
        self.git('commit', '-qm', 'Delete')
        self.assertEqual(changes.selection(base, self.git('rev-parse', 'HEAD'), root=self.root)['packages'], ['ruby'])

    def test_missing_history_is_conservative_and_invalid_head_fails(self):
        result = changes.selection('a' * 40, self.base, root=self.root)
        self.assertTrue(result['fallback'])
        self.assertEqual(result['packages'], list(changes.KEYS))
        with self.assertRaises(subprocess.CalledProcessError):
            changes.selection(self.base, 'b' * 40, root=self.root)

    def test_first_push_inspects_tracked_files(self):
        head = self.commit('sdk-java/pom.xml', 'fixture')
        self.assertEqual(changes.selection('0' * 40, head, root=self.root)['packages'], ['java'])

    def test_wrong_push_identity_and_branch_fail(self):
        for event in ({'ref': 'refs/heads/feature', 'before': self.base, 'after': self.base},
                      {'ref': 'refs/heads/main', 'before': self.base, 'after': 'a' * 40}):
            with self.assertRaises(ValueError):
                changes.from_event('push', event, self.base, root=self.root)
        with self.assertRaises(ValueError):
            changes.selection('--help', self.base, root=self.root)


class GateTests(unittest.TestCase):
    def results(self):
        return {name: {'result': 'success' if name in ('changes', 'release-tools', 'python') else 'skipped'}
                for name in gate.JOBS}

    def test_unaffected_packages_can_be_skipped(self):
        gate.check(self.results(), ['python'])

    def test_selected_failures_cancellations_and_unexpected_skips_fail(self):
        for job in ('changes', 'release-tools', 'python'):
            for status in ('failure', 'cancelled', 'skipped'):
                with self.subTest(job=job, status=status), self.assertRaises(ValueError):
                    results = self.results()
                    results[job]['result'] = status
                    gate.check(results, ['python'])

    def test_missing_jobs_and_invalid_selection_fail(self):
        results = self.results()
        del results['python']
        with self.assertRaises(ValueError):
            gate.check(results, ['python'])
        for selected in (['unknown'], ['python', 'python'], 'python'):
            with self.assertRaises(ValueError):
                gate.check(self.results(), selected)

    def test_docs_only_and_all_packages(self):
        results = {name: {'result': 'success' if name in ('changes', 'release-tools') else 'skipped'} for name in gate.JOBS}
        gate.check(results, [])
        gate.check({name: {'result': 'success'} for name in gate.JOBS}, list(changes.KEYS))

    def test_js_and_mcp_share_the_node_matrix(self):
        for selected in (['sdk-js'], ['mcp-server'], ['sdk-js', 'mcp-server']):
            results = {name: {'result': 'success' if name in ('changes', 'release-tools', 'verify') else 'skipped'} for name in gate.JOBS}
            gate.check(results, selected)


if __name__ == '__main__':
    unittest.main()
