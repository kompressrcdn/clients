import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import release as r


class VerifiedSelectionTests(unittest.TestCase):
    def setUp(self):
        self.sha = 'a' * 40
        self.checked = {'id': 42, 'run_attempt': 2}
        self.expected = {'schema': 1, 'base': 'b' * 40, 'head': self.sha, 'fallback': False,
                         'packages': ['python'], 'publish': ['python']}

    def archive(self, value, name='selection.json'):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr(name, json.dumps(value))
        return buffer.getvalue()

    def artifacts(self):
        return {'artifacts': [{'id': 8, 'name': 'client-selection-1', 'expired': False},
                              {'id': 9, 'name': 'client-selection-2', 'expired': False}]}

    def test_selection_comes_from_the_exact_successful_run_attempt_and_git_diff(self):
        with patch.object(r, 'github', return_value=self.artifacts()) as github, \
                patch.object(r.subprocess, 'check_output', return_value=self.archive(self.expected)) as download, \
                patch.object(r.changes, 'selection', return_value=self.expected) as recompute:
            self.assertEqual(r.verified_selection(self.checked, self.sha), {'python'})
        self.assertIn('actions/runs/42/artifacts', github.call_args.args[0])
        self.assertIn('repos/kompressrcdn/clients/actions/artifacts/9/zip', download.call_args.args[0])
        recompute.assert_called_once_with('b' * 40, self.sha, root=r.ROOT)

    def test_failed_job_rerun_reuses_successful_earlier_selection(self):
        artifacts = {'artifacts': [self.artifacts()['artifacts'][0]]}
        with patch.object(r, 'github', return_value=artifacts), \
                patch.object(r.subprocess, 'check_output', return_value=self.archive(self.expected)) as download, \
                patch.object(r.changes, 'selection', return_value=self.expected):
            self.assertEqual(r.verified_selection(self.checked, self.sha), {'python'})
            self.assertIn('repos/kompressrcdn/clients/actions/artifacts/8/zip', download.call_args.args[0])

    def test_selection_from_a_future_attempt_is_not_used(self):
        artifact = {'id': 10, 'name': 'client-selection-3', 'expired': False}
        with patch.object(r, 'github', return_value={'artifacts': [artifact]}), self.assertRaisesRegex(RuntimeError, 'Missing current'):
            r.verified_selection(self.checked, self.sha)

    def test_missing_expired_or_duplicate_artifacts_fail(self):
        current = self.artifacts()['artifacts'][1]
        for values in ([], [{**current, 'expired': True}], [current, current]):
            with self.subTest(values=values), patch.object(r, 'github', return_value={'artifacts': values}), self.assertRaisesRegex(RuntimeError, 'Missing current'):
                r.verified_selection(self.checked, self.sha)

    def test_cross_commit_and_modified_package_selection_fail(self):
        for field, value in (('head', 'c' * 40), ('publish', ['ruby']), ('packages', []), ('schema', 2)):
            altered = {**self.expected, field: value}
            with self.subTest(field=field), patch.object(r, 'github', return_value=self.artifacts()), \
                    patch.object(r.subprocess, 'check_output', return_value=self.archive(altered)), \
                    patch.object(r.changes, 'selection', return_value=self.expected), self.assertRaises(RuntimeError):
                r.verified_selection(self.checked, self.sha)

    def test_archive_cannot_select_an_unexpected_filename(self):
        with patch.object(r, 'github', return_value=self.artifacts()), \
                patch.object(r.subprocess, 'check_output', return_value=self.archive(self.expected, '../selection.json')), \
                self.assertRaisesRegex(RuntimeError, 'Unexpected'):
            r.verified_selection(self.checked, self.sha)

    def test_manual_explicit_recovery_supports_old_runs_without_selection_artifacts(self):
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch'}), patch.object(r, 'verified_selection') as selection:
            self.assertEqual(r.selected_packages({}, self.sha, {'inputs': {'packages': 'python,sdk-js'}}), {'python', 'sdk-js'})
            selection.assert_not_called()
            for invalid in ('python,unknown', 'python,'):
                with self.assertRaisesRegex(RuntimeError, 'Unknown recovery'):
                    r.selected_packages({}, self.sha, {'inputs': {'packages': invalid}})

    def test_automatic_event_cannot_override_its_verified_package_selection(self):
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_run'}), patch.object(r, 'verified_selection', return_value={'python'}) as selection:
            self.assertEqual(r.selected_packages(self.checked, self.sha, {'inputs': {'packages': 'ruby'}}), {'python'})
            selection.assert_called_once_with(self.checked, self.sha)

    def test_selection_artifact_lookup_paginates(self):
        unrelated = [{'id': i + 100, 'name': 'other-' + str(i), 'expired': False} for i in range(100)]
        with patch.object(r, 'github', side_effect=[{'artifacts': unrelated}, self.artifacts()]) as github, \
                patch.object(r.subprocess, 'check_output', return_value=self.archive(self.expected)), \
                patch.object(r.changes, 'selection', return_value=self.expected):
            self.assertEqual(r.verified_selection(self.checked, self.sha), {'python'})
            self.assertEqual(github.call_count, 2)


class SelectedPlanTests(unittest.TestCase):
    def run_plan(self, selection, *, enabled="python,go", inputs=None):
        with tempfile.TemporaryDirectory() as temporary:
            event = Path(temporary) / 'event.json'
            r.write_json(event, {'workflow_run': {'id': 42}} if inputs is None else {'inputs': inputs})
            sha = 'a' * 40
            checked = {'repository': {'full_name': r.REPO}, 'head_repository': {'full_name': r.REPO},
                       'path': '.github/workflows/verify.yml', 'event': 'push', 'head_branch': 'main',
                       'head_sha': sha, 'status': 'completed', 'conclusion': 'success', 'id': 42}
            env = {'GITHUB_EVENT_PATH': str(event), 'GITHUB_REPOSITORY': r.REPO,
                   'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_run' if inputs is None else 'workflow_dispatch',
                   'GITHUB_SHA': sha, 'RELEASE_PACKAGES': enabled}
            with patch.dict(os.environ, env), patch.object(r, 'repository_controls'), \
                    patch.object(r, 'github', return_value=checked if inputs is None else {'workflow_runs': [checked]}), patch.object(r, 'run', return_value=sha), \
                    patch.object(r, 'versions', return_value={'python': '0.2.0', 'go': '0.2.0'}), \
                    patch.object(r, 'selected_packages', return_value=selection), \
                    patch.object(r, 'release', return_value=None) as release, \
                    patch.object(r, 'registry', return_value=None) as registry, patch.object(r, 'output') as output:
                r.plan()
            return release, registry, dict(call.args for call in output.call_args_list)

    def test_unchanged_unpublished_package_is_not_automatically_released(self):
        release, registry, outputs = self.run_plan({'python'})
        release.assert_called_once_with('python', '0.2.0')
        registry.assert_called_once_with('python', '0.2.0')
        self.assertEqual(outputs['packages'], ['python'])
        self.assertEqual(outputs['builds'], ['python'])

    def test_automatic_selection_respects_disabled_packages(self):
        release, registry, outputs = self.run_plan({'python', 'go'}, enabled='python')
        self.assertEqual(outputs['packages'], ['python'])
        registry.assert_called_once_with('python', '0.2.0')

    def test_explicit_manual_selection_cannot_enable_a_disabled_package(self):
        with self.assertRaisesRegex(RuntimeError, 'disabled by RELEASE_PACKAGES'):
            self.run_plan({'go'}, enabled='python', inputs={'packages': 'go'})

    def test_default_manual_selection_intersects_the_enabled_packages(self):
        _, registry, outputs = self.run_plan({'python', 'go'}, enabled='python', inputs={})
        self.assertEqual(outputs['packages'], ['python'])
        registry.assert_called_once_with('python', '0.2.0')

    def test_workflow_only_change_does_not_touch_existing_partial_releases(self):
        release, registry, outputs = self.run_plan(set())
        release.assert_not_called()
        registry.assert_not_called()
        self.assertEqual(outputs['packages'], [])
        self.assertEqual(outputs['builds'], [])


if __name__ == '__main__':
    unittest.main()
