import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile
import release as r


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.sha = 'a' * 40
        self.record = {'schema': 2, 'package': 'sdk-js', 'version': '1.0.2', 'sha': self.sha, 'files': {'sdk.tgz': '0' * 64}}

    def retained(self, key='sdk-js'):
        self.record['package'] = key
        (self.directory / 'sdk.tgz').write_bytes(b'verified package')
        self.record['files']['sdk.tgz'] = r.digest(self.directory / 'sdk.tgz')
        r.write_json(self.directory / 'release.json', self.record)

    def test_manifest_versions_and_flat_mcp_tag(self):
        values = r.versions()
        self.assertEqual(set(values), set(r.KEYS))
        self.assertEqual(r.tag('mcp-server', '2.0.3'), 'mcp-server-v2.0.3')
        self.assertEqual(r.tag('go', '0.2.0'), 'sdk-go/v0.2.0')

    def test_stable_versions_reject_suffixes_and_leading_zeroes(self):
        for invalid in ('1.2.3-beta', '01.2.3', '1.2', 'v1.2.3', '1.2.3\n', '../../1'):
            self.assertIsNone(r.STABLE.fullmatch(invalid))

    def test_only_real_404_is_absent(self):
        for code in (401, 403, 410, 429, 500, 503):
            with self.subTest(code=code), patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError('https://example.com', code, 'failure', {}, None)):
                with self.assertRaises(RuntimeError):
                    r.request('https://example.com', missing=True)
        with patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError('https://example.com', 404, 'missing', {}, None)):
            self.assertIsNone(r.request('https://example.com', missing=True))

    def test_malformed_json_fails_closed(self):
        with patch.object(r, 'request', return_value=b'{'):
            with self.assertRaises(ValueError):
                r.get_json('https://example.com', missing=True)

    def valid_run(self):
        return {'repository': {'full_name': r.REPO}, 'head_repository': {'full_name': r.REPO},
                'path': '.github/workflows/verify.yml', 'event': 'push', 'head_branch': 'main',
                'head_sha': self.sha, 'status': 'completed', 'conclusion': 'success'}

    def test_successful_exact_main_run_required(self):
        good = self.valid_run()
        r.validate_run(good, self.sha)
        for field, value in [('event', 'pull_request'), ('head_branch', 'feature'), ('head_sha', 'b' * 40),
                             ('status', 'in_progress'), ('conclusion', 'failure'), ('path', '.github/workflows/other.yml'),
                             ('head_repository', {'full_name': 'example/fork'}), ('repository', {'full_name': 'example/fork'})]:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                r.validate_run({**good, field: value}, self.sha)

    def test_record_validates_source_and_bytes(self):
        self.retained()
        r.validate_record(self.record, 'sdk-js', '1.0.2', self.sha, self.directory)
        with self.assertRaises(RuntimeError):
            r.validate_record(self.record, 'sdk-js', '1.0.2', 'b' * 40, self.directory)
        (self.directory / 'sdk.tgz').write_bytes(b'changed')
        with self.assertRaises(RuntimeError):
            r.validate_record(self.record, 'sdk-js', '1.0.2', self.sha, self.directory)

    def test_record_rejects_path_traversal_and_empty_assets(self):
        for files in ({'../outside': '0' * 64}, {}, {'release.json': '0' * 64}):
            with self.subTest(files=files), self.assertRaises(RuntimeError):
                r.validate_record({**self.record, 'files': files}, 'sdk-js', '1.0.2', self.sha, self.directory)

    def test_tag_checks_annotated_commit_and_conflict(self):
        with patch.object(r, 'github', side_effect=[{'object': {'type': 'tag', 'sha': 'c' * 40}}, {'object': {'type': 'commit', 'sha': self.sha}}]):
            r.check_tag('go', '1.0.0', self.sha)
        with patch.object(r, 'github', return_value={'object': {'type': 'commit', 'sha': 'b' * 40}}), self.assertRaises(RuntimeError):
            r.check_tag('go', '1.0.0', self.sha)

    def test_partial_pypi_release_only_uploads_missing_files(self):
        record = {'files': {'sdk.whl': 'a' * 64, 'sdk.tar.gz': 'b' * 64, 'SHA256SUMS': 'c' * 64}}
        present = {'urls': [{'filename': 'sdk.whl', 'digests': {'sha256': 'a' * 64}}]}
        with patch.object(r, 'registry', return_value=present):
            self.assertTrue(r.needs_upload('python', '1.0.0', record))
        present['urls'].append({'filename': 'sdk.tar.gz', 'digests': {'sha256': 'b' * 64}})
        with patch.object(r, 'registry', return_value=present):
            self.assertFalse(r.needs_upload('python', '1.0.0', record))
        present['urls'][0]['digests']['sha256'] = 'd' * 64
        with patch.object(r, 'registry', return_value=present), self.assertRaises(RuntimeError):
            r.needs_upload('python', '1.0.0', record)

    def test_existing_registry_version_never_republished(self):
        self.retained()
        with patch.object(r, 'versions', return_value={'sdk-js': '1.0.2'}), patch.object(r, 'run', return_value=self.sha) as run, patch.object(r, 'verify_attestation'), patch.object(r, 'registry', return_value={'version': '1.0.2'}):
            r.publish('sdk-js', self.directory)
            self.assertEqual(run.call_count, 1)  # Only read the checkout SHA.

    def test_retained_retry_never_builds_or_resigns(self):
        self.retained('java')
        with patch.object(r, 'versions', return_value={'java': '1.0.2'}), patch.object(r, 'source_sha', return_value=self.sha), patch.object(r, 'verify_attestation') as verify, patch.object(r, 'sign_java') as sign, patch.object(r, 'build') as build, patch.object(r, 'output') as output:
            r.seal('java', self.directory)
            build.assert_not_called()
            sign.assert_not_called()
            verify.assert_called_once_with(self.directory / 'release.json', sha=self.sha)
            output.assert_called_once_with('fresh', 'false')

    def test_new_build_cannot_claim_another_workflow_commit(self):
        with patch.object(r, 'versions', return_value={'sdk-js': '1.0.2'}), patch.object(r, 'source_sha', return_value=self.sha), patch.dict(os.environ, {'GITHUB_SHA': 'b' * 40}), patch.object(r, 'release', return_value=None), patch.object(r, 'sign_java') as sign:
            with self.assertRaisesRegex(RuntimeError, 'workflow source'):
                r.seal('sdk-js', self.directory)
            sign.assert_not_called()

    def test_incomplete_or_legacy_release_fails_before_artifact_download(self):
        rel = {'assets': [{'name': 'release.json'}]}
        with patch.object(r, 'release', return_value=rel), patch.object(r, 'gh') as gh:
            with self.assertRaisesRegex(RuntimeError, 'authenticated record'):
                r.download('sdk-js', '1.0.2', self.directory)
            gh.assert_not_called()

    def test_replacing_package_and_checksum_cannot_bypass_provenance(self):
        self.retained()
        authenticated_digest = r.digest(self.directory / 'release.json')
        # Model the immutable signed subject digest, not a checksum stored beside the package.
        def check_subject(path, **kwargs):
            r.require(r.digest(path) == authenticated_digest, 'signature subject mismatch')
        with patch.object(r, 'versions', return_value={'sdk-js': '1.0.2'}), patch.object(r, 'source_sha', return_value=self.sha), patch.object(r, 'verify_attestation', side_effect=check_subject), patch.object(r, 'gh') as gh, patch.object(r, 'registry', return_value=None):
            r.authenticated('sdk-js', self.directory)
            (self.directory / 'sdk.tgz').write_bytes(b'substituted package')
            self.record['files']['sdk.tgz'] = r.digest(self.directory / 'sdk.tgz')
            r.write_json(self.directory / 'release.json', self.record)
            for operation in (r.retain, r.publish, r.finish):
                with self.subTest(operation=operation.__name__), self.assertRaisesRegex(RuntimeError, 'signature subject'):
                    operation('sdk-js', self.directory)
            gh.assert_not_called()

    def test_provenance_requires_repo_workflow_main_source_and_hosted_runner(self):
        self.retained()
        (self.directory / 'release.intoto.jsonl').write_text('{}')
        with patch.object(r, 'run') as run:
            r.verify_attestation(self.directory / 'release.json', sha=self.sha)
            args = run.call_args.args
            for flag, value in (('--repo', r.REPO), ('--signer-workflow', r.SIGNER), ('--source-ref', 'refs/heads/main'), ('--source-digest', self.sha), ('--predicate-type', 'https://slsa.dev/provenance/v1')):
                self.assertEqual(args[args.index(flag) + 1], value)
            self.assertIn('--deny-self-hosted-runners', args)

    def test_unsigned_receipt_and_cross_package_receipt_are_rejected(self):
        self.retained()
        r.write_json(self.directory / 'published.json', r.completion(self.record, self.directory))
        with self.assertRaisesRegex(RuntimeError, 'authenticated release record'):
            r.complete(self.directory, self.record)
        r.write_json(self.directory / 'published.json', {**r.completion(self.record, self.directory), 'package': 'ruby'})
        with patch.object(r, 'verify_attestation'), self.assertRaisesRegex(RuntimeError, 'receipt differs'):
            r.complete(self.directory, self.record)

    def test_symlinks_unexpected_files_and_metadata_paths_are_rejected(self):
        self.retained()
        outside = self.directory / 'outside'
        outside.write_bytes(b'verified package')
        (self.directory / 'sdk.tgz').unlink()
        (self.directory / 'sdk.tgz').symlink_to(outside)
        with self.assertRaises(RuntimeError):
            r.validate_record(self.record, 'sdk-js', '1.0.2', self.sha, self.directory)
        (self.directory / 'sdk.tgz').unlink()
        (self.directory / 'sdk.tgz').write_bytes(b'verified package')
        with self.assertRaisesRegex(RuntimeError, 'Unexpected'):
            r.validate_record(self.record, 'sdk-js', '1.0.2', self.sha, self.directory)
        outside.unlink()
        for name in ('.npmrc', '-options', 'release.intoto.jsonl', 'nested/file', '../escape'):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                r.validate_record({**self.record, 'files': {name: 'a' * 64}}, 'sdk-js', '1.0.2', self.sha, self.directory)

    def test_consumers_do_not_inherit_tokens_or_tool_configuration(self):
        import subprocess
        import sys
        with patch.dict(os.environ, {'GH_TOKEN': 'fixture', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'fixture', 'MAVEN_GPG_PRIVATE_KEY': 'fixture', 'NPM_CONFIG_USERCONFIG': '/fixture', 'RUBYOPT': '-rfixture', 'PYTHONPATH': '/fixture', 'RELEASE_SOURCE': str(r.ROOT)}):
            env = r.consumer_environment()
            value = subprocess.check_output([sys.executable, '-c', 'import os,json;print(json.dumps(dict(os.environ)))'], env=env, text=True)
            actual = json.loads(value)
            for name in ('GH_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'MAVEN_GPG_PRIVATE_KEY', 'NPM_CONFIG_USERCONFIG', 'RUBYOPT', 'PYTHONPATH'):
                self.assertNotIn(name, actual)
            self.assertEqual(actual['RELEASE_SOURCE'], str(r.ROOT))

    def test_mcp_dependency_rejects_unpublished_or_different_integrity(self):
        lock = {'packages': {'node_modules/@kompressr/sdk': {'version': '1.0.2', 'integrity': 'sha512-expected'}}}
        for data in (None, {'dist': {'integrity': 'sha512-other'}}):
            with patch.object(r, 'read_json', return_value=lock), patch.object(r, 'registry', return_value=data), self.assertRaises(RuntimeError):
                r.sdk_dependency()

    def test_unknown_central_upload_is_never_repeated(self):
        (self.directory / 'central-upload-started.json').write_text('{}')
        with patch.dict(os.environ, {'MAVEN_CENTRAL_USERNAME': 'fixture', 'MAVEN_CENTRAL_PASSWORD': 'fixture'}), patch.object(r, 'request') as request:
            with self.assertRaisesRegex(RuntimeError, 'outcome is unknown'):
                r.central(self.directory, {'version': '0.1.0', 'sha': self.sha})
            request.assert_not_called()

    def test_retained_central_id_is_polled_without_upload(self):
        r.write_json(self.directory / 'central-deployment.json', {'id': '12345678-1234-1234-1234-123456789abc'})
        with patch.dict(os.environ, {'MAVEN_CENTRAL_USERNAME': 'fixture', 'MAVEN_CENTRAL_PASSWORD': 'fixture'}), patch.object(r, 'get_json', return_value={'deploymentState': 'PUBLISHED'}) as get, patch.object(r, 'gh') as gh:
            r.central(self.directory, {'version': '0.1.0', 'sha': self.sha})
            self.assertIn('/status?id=', get.call_args.args[0])
            gh.assert_not_called()

    def test_nuget_can_become_available_after_fifteen_minutes(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('lib/sdk.dll', b'verified payload')
        package = stream.getvalue()
        (self.directory / 'Kompressr.Sdk.0.1.1.nupkg').write_bytes(package)
        elapsed = 0

        def sleep(seconds):
            nonlocal elapsed
            elapsed += seconds

        def metadata(key, version):
            self.assertEqual((key, version), ('dotnet', '0.1.1'))
            return b'<package/>' if elapsed >= 15 * 60 else None

        with patch.object(r.time, 'sleep', side_effect=sleep), patch.object(r, 'registry', side_effect=metadata), patch.object(r, 'request', return_value=package) as download:
            r.verify_public('dotnet', self.directory, {'version': '0.1.1'})
            self.assertEqual(elapsed, 15 * 60)
            download.assert_called_once_with('https://api.nuget.org/v3-flatcontainer/kompressr.sdk/0.1.1/kompressr.sdk.0.1.1.nupkg')

    def test_nuget_validation_wait_is_bounded(self):
        elapsed = 0

        def sleep(seconds):
            nonlocal elapsed
            elapsed += seconds

        with patch.object(r.time, 'sleep', side_effect=sleep), patch.object(r, 'registry', return_value=None), patch.object(r, 'request') as download:
            with self.assertRaisesRegex(RuntimeError, 'Timed out waiting for dotnet registry metadata; retry the same release'):
                r.verify_public('dotnet', self.directory, {'version': '0.1.1'})
            self.assertGreaterEqual(elapsed, 15 * 60)
            self.assertLessEqual(elapsed, 30 * 60)
            download.assert_not_called()

    def test_nuget_allows_repository_signature_only(self):
        def archive(files):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as z:
                for name, data in files.items():
                    z.writestr(name, data)
            return stream.getvalue()
        original = archive({'lib/sdk.dll': b'sdk', 'package.nuspec': b'meta'})
        signed = archive({'package.nuspec': b'meta', 'lib/sdk.dll': b'sdk', '.signature.p7s': b'signed'})
        r.compare_zip(original, signed)
        with self.assertRaises(RuntimeError):
            r.compare_zip(original, archive({'lib/sdk.dll': b'changed', 'package.nuspec': b'meta'}))

    def mcp_manifest(self):
        return {'name': 'com.kompressr/kompressr', 'version': '2.0.3', 'packages': [
            {'registryType': 'npm', 'registryBaseUrl': 'https://registry.npmjs.org',
             'identifier': '@kompressr/mcp-server', 'version': '2.0.3',
             'transport': {'type': 'stdio'}, 'environmentVariables': [
                 {'name': 'KOMPRESSR_API_KEY', 'format': 'string', 'isRequired': True, 'isSecret': True},
                 {'name': 'KOMPRESSR_PROJECT_ID', 'format': 'string', 'isRequired': False}]},
            {'registryType': 'mcpb', 'identifier': 'https://example.com/server.mcpb',
             'fileSha256': 'a' * 64, 'transport': {'type': 'stdio'}}]}

    def test_mcp_registry_omitted_false_is_already_published(self):
        expected = self.mcp_manifest()
        r.write_json(self.directory / 'server.json', expected)
        actual = copy.deepcopy(expected)
        del actual['packages'][0]['environmentVariables'][1]['isRequired']
        response = {'server': actual}
        with patch.object(r, 'get_json', return_value=response), patch.object(r, 'run') as run:
            self.assertIs(r.mcp_matches(self.directory, {'version': '2.0.3'}), response)
            r.mcp_registry(self.directory, {'version': '2.0.3'})
            run.assert_not_called()
        self.assertNotIn('isRequired', actual['packages'][0]['environmentVariables'][1])
        self.assertEqual(r.read_json(self.directory / 'server.json'), expected)

    def test_mcp_registry_defaults_apply_only_to_schema_input_locations(self):
        expected = self.mcp_manifest()
        package = expected['packages'][0]
        package['packageArguments'] = [{'type': 'named', 'name': '--project', 'isRepeated': False,
            'isRequired': False, 'isSecret': False, 'format': 'string',
            'variables': {'project': {'isRequired': False, 'isSecret': False, 'format': 'string'}}}]
        package['runtimeArguments'] = [{'type': 'positional', 'value': 'run', 'isRepeated': False}]
        package['transport'] = {'type': 'streamable-http', 'url': 'https://example.com/mcp',
            'headers': [{'name': 'X-Project', 'isRequired': False}],
            'variables': {'project': {'isRequired': False}}}
        r.write_json(self.directory / 'server.json', expected)
        actual = copy.deepcopy(expected)
        actual['packages'][0]['packageArguments'] = [{'type': 'named', 'name': '--project', 'variables': {'project': {}}}]
        actual['packages'][0]['runtimeArguments'] = [{'type': 'positional', 'value': 'run'}]
        actual['packages'][0]['transport']['headers'] = [{'name': 'X-Project'}]
        actual['packages'][0]['transport']['variables'] = {'project': {}}
        del actual['packages'][0]['environmentVariables'][1]['format']
        with patch.object(r, 'get_json', return_value={'server': actual}):
            r.mcp_matches(self.directory, {'version': '2.0.3'})
        # An arbitrary package-level false field is not a documented input default.
        actual['packages'][0]['isRequired'] = False
        with patch.object(r, 'get_json', return_value={'server': actual}), self.assertRaisesRegex(RuntimeError, 'metadata differs'):
            r.mcp_matches(self.directory, {'version': '2.0.3'})

    def test_mcp_registry_rejects_meaningful_and_malformed_changes(self):
        expected = self.mcp_manifest()
        r.write_json(self.directory / 'server.json', expected)
        changes = [
            (('name',), 'com.example/server'), (('version',), '2.0.4'),
            (('packages', 0, 'identifier'), '@example/server'),
            (('packages', 0, 'version'), '2.0.4'),
            (('packages', 0, 'registryBaseUrl'), 'https://example.com'),
            (('packages', 0, 'transport', 'type'), 'sse'),
            (('packages', 1, 'identifier'), 'https://example.com/changed.mcpb'),
            (('packages', 1, 'fileSha256'), 'b' * 64),
            (('packages', 0, 'environmentVariables', 0, 'isSecret'), False),
            (('packages', 0, 'environmentVariables', 1, 'format'), 'number'),
        ]
        for value in (True, None, 0, 'false'):
            changes.append((('packages', 0, 'environmentVariables', 1, 'isRequired'), value))
        for path, value in changes:
            actual = copy.deepcopy(expected)
            target = actual
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            with self.subTest(path=path, value=value), patch.object(r, 'get_json', return_value={'server': actual}), self.assertRaisesRegex(RuntimeError, 'metadata differs'):
                r.mcp_matches(self.directory, {'version': '2.0.3'})
        for key in ('isRequired', 'isSecret'):
            actual = copy.deepcopy(expected)
            del actual['packages'][0]['environmentVariables'][0][key]
            with self.subTest(missing=key), patch.object(r, 'get_json', return_value={'server': actual}), self.assertRaisesRegex(RuntimeError, 'metadata differs'):
                r.mcp_matches(self.directory, {'version': '2.0.3'})

    def test_mcp_registry_failure_keeps_release_retryable(self):
        self.retained('mcp-server')
        self.record['version'] = '2.0.3'
        r.write_json(self.directory / 'release.json', self.record)
        with patch.object(r, 'versions', return_value={'mcp-server': '2.0.3'}), patch.object(r, 'run', return_value=self.sha), patch.object(r, 'release', return_value={'draft': True, 'immutable': True}), patch.object(r, 'authenticated', return_value=self.record), patch.object(r, 'complete', return_value=True), patch.object(r, 'download') as download, patch.object(r.Path, 'read_bytes', return_value=b'record'), patch.object(r, 'gh') as gh, patch.object(r, 'mcp_registry', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                r.finish('mcp-server', self.directory)
            gh.assert_called_once()  # Assets must be public before registry admission.
            self.assertFalse((self.directory / 'published.json').exists())

    def test_plan_skips_old_versions_and_resumes_incomplete_release(self):
        event = self.directory / 'event.json'
        r.write_json(event, {'workflow_run': {'id': 42}})
        rels = {'sdk-js': None, 'mcp-server': {'assets': [{'name': 'release.json'}]}, 'python': None}
        with patch.dict(os.environ, {'GITHUB_EVENT_PATH': str(event), 'GITHUB_REPOSITORY': r.REPO, 'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_run', 'GITHUB_SHA': self.sha, 'RELEASE_PACKAGES': 'sdk-js,mcp-server,python'}), patch.object(r, 'repository_controls'), patch.object(r, 'github', return_value=self.valid_run()), patch.object(r, 'run', return_value=self.sha), patch.object(r, 'versions', return_value={'sdk-js': '1.0.2', 'mcp-server': '2.0.3', 'python': '0.2.0'}), patch.object(r, 'release', side_effect=lambda key, version: rels[key]), patch.object(r, 'registry', side_effect=lambda key, version: {} if key == 'sdk-js' else None), patch.object(r, 'download', return_value={'sha': self.sha}), patch.object(r, 'complete', return_value=False), patch.object(r, 'output') as output:
            r.plan()
            result = dict(call.args for call in output.call_args_list)
            self.assertEqual(result['sdk'], 'false')
            self.assertEqual(result['mcp'], 'true')
            self.assertEqual(result['packages'], ['python'])
            self.assertEqual(result['builds'], ['python'])

    def test_npm_retry_cannot_claim_newer_source_provenance(self):
        self.retained()
        with patch.object(r, 'authenticated', return_value=self.record), patch.object(r, 'registry', return_value=None), patch.dict(os.environ, {'GITHUB_SHA': 'b' * 40}), patch.object(r, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'original workflow'):
                r.publish('sdk-js', self.directory)
            run.assert_not_called()

    def test_new_npm_release_cannot_downgrade_latest(self):
        with patch.object(r, 'get_json', return_value={'versions': {'1.0.0': {}, '2.0.0': {}, '3.0.0-beta': {}}}):
            with self.assertRaises(RuntimeError):
                r.npm_version_must_advance('sdk-js', '1.1.0')
            r.npm_version_must_advance('sdk-js', '2.0.1')

    def test_fresh_retention_uploads_record_before_reserving_version(self):
        self.retained()
        calls = []
        with patch.object(r, 'authenticated', return_value=self.record), patch.object(r, 'check_tag', return_value=False), patch.object(r, 'release', return_value=None), patch.object(r, 'registry', return_value=None), patch.object(r, 'gh', side_effect=lambda *a: calls.append(a)), patch.object(r, 'github', side_effect=lambda *a, **kw: calls.append(('reserve', kw['data']))), patch.object(r, 'output'):
            r.retain('sdk-js', self.directory)
        self.assertEqual(calls[0][:2], ('release', 'create'))
        self.assertIn('--draft', calls[0])
        self.assertEqual(calls[-2][-1], str(self.directory / 'release.json'))
        self.assertEqual(calls[-1], ('reserve', {'ref': 'refs/tags/sdk-js/v1.0.2', 'sha': self.sha}))

    def test_new_record_is_derived_from_checked_candidate(self):
        self.retained()
        (self.directory / 'release.json').rename(self.directory / 'candidate.json')
        with patch.object(r, 'versions', return_value={'sdk-js': '1.0.2'}), patch.object(r, 'source_sha', return_value=self.sha), patch.dict(os.environ, {'GITHUB_SHA': self.sha}), patch.object(r, 'release', return_value=None), patch.object(r, 'output') as output:
            r.seal('sdk-js', self.directory)
        record = r.read_json(self.directory / 'release.json')
        self.assertFalse((self.directory / 'candidate.json').exists())
        r.validate_record(record, 'sdk-js', '1.0.2', self.sha, self.directory)
        self.assertIn('SHA256SUMS', record['files'])
        output.assert_called_once_with('fresh', 'true')

    def test_public_immutable_release_is_not_edited_on_retry(self):
        self.retained()
        def download(key, version, directory):
            (directory / 'release.json').write_bytes((self.directory / 'release.json').read_bytes())
        with patch.object(r, 'authenticated', return_value=self.record), patch.object(r, 'complete', return_value=True), patch.object(r, 'download', side_effect=download), patch.object(r, 'release', return_value={'draft': False, 'immutable': True}), patch.object(r, 'gh') as gh:
            r.finish('sdk-js', self.directory)
            gh.assert_not_called()

    def test_mutable_public_release_cannot_finish(self):
        self.retained()
        def download(key, version, directory):
            (directory / 'release.json').write_bytes((self.directory / 'release.json').read_bytes())
        with patch.object(r, 'authenticated', return_value=self.record), patch.object(r, 'complete', return_value=True), patch.object(r, 'download', side_effect=download), patch.object(r, 'release', return_value={'draft': False, 'immutable': False}), patch.object(r, 'gh') as gh:
            with self.assertRaisesRegex(RuntimeError, 'not immutable'):
                r.finish('sdk-js', self.directory)
            gh.assert_not_called()

    def test_partial_completion_signature_is_reused(self):
        self.retained()
        (self.directory / 'published.intoto.jsonl').write_text('signed fixture')
        with patch.object(r, 'authenticated', return_value=self.record), patch.object(r, 'check_tag'), patch.object(r, 'verify_public'), patch.object(r, 'verify_attestation') as signature, patch.object(r, 'output') as output:
            r.receipt('sdk-js', self.directory)
            signature.assert_called_once_with(self.directory / 'published.json')
            output.assert_called_once_with('fresh', 'false')
            self.assertEqual(r.read_json(self.directory / 'published.json'), r.completion(self.record, self.directory))

    def test_missing_repository_controls_block_publication(self):
        tag_rule = {'id': 1, 'target': 'tag', 'enforcement': 'active'}
        protected = {'conditions': {'ref_name': {'include': ['~ALL'], 'exclude': []}},
                     'rules': [{'type': 'update'}, {'type': 'deletion'}]}
        with patch.object(r, 'github', side_effect=[{'protected': True}, [tag_rule], protected]):
            r.repository_controls()
        for answers in ([{'protected': False}], [{'protected': True}, []],
                        [{'protected': True}, [tag_rule], {**protected, 'rules': [{'type': 'deletion'}]}]):
            with self.subTest(answers=answers), patch.object(r, 'github', side_effect=answers), self.assertRaises(RuntimeError):
                r.repository_controls()

    def test_deleted_central_marker_does_not_authorize_reupload(self):
        with patch.dict(os.environ, {'MAVEN_CENTRAL_USERNAME': 'fixture', 'MAVEN_CENTRAL_PASSWORD': 'fixture', 'RELEASE_FRESH': 'false'}), patch.object(r, 'request') as request:
            with self.assertRaisesRegex(RuntimeError, 'outcome is unknown'):
                r.central(self.directory, {'version': '0.1.0', 'sha': self.sha})
            request.assert_not_called()

    def test_reserved_tag_with_missing_record_cannot_start_new_build(self):
        target = self.directory / 'new'
        with patch.object(r, 'versions', return_value={'sdk-js': '1.0.2'}), patch.object(r, 'source_sha', return_value=self.sha), patch.dict(os.environ, {'GITHUB_SHA': self.sha}), patch.object(r, 'release', return_value=None), patch.object(r, 'check_tag', return_value=True), patch.object(r, 'registry') as registry:
            with self.assertRaisesRegex(RuntimeError, 'Tag exists'):
                r.inspect('sdk-js', target)
            registry.assert_not_called()

    def test_required_gate_rejects_failed_skipped_and_cancelled_jobs(self):
        import subprocess
        import sys
        import textwrap
        workflow = (r.CONTROL_ROOT / '.github/workflows/verify.yml').read_text()
        script = textwrap.dedent(workflow.split("python3 - <<'PYTHON'\n", 1)[1].split('          PYTHON\n', 1)[0])
        for result in ('success', 'failure', 'skipped', 'cancelled'):
            env = {**r.consumer_environment(), 'CHECK_RESULTS': json.dumps({'verify': {'result': 'success'}, 'python': {'result': result}})}
            completed = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True)
            self.assertEqual(completed.returncode == 0, result == 'success')

    def test_draft_discovery_paginates_and_reads_the_selected_id(self):
        first = [{'id': i + 1, 'tag_name': f'sdk-python/v9.0.{i}', 'draft': False} for i in range(100)]
        draft = {'id': 101, 'tag_name': 'sdk-java/v0.1.0', 'draft': True, 'assets': []}
        with patch.object(r, 'github', side_effect=[first, [draft], draft]) as api:
            self.assertEqual(r.release('java', '0.1.0'), draft)
        self.assertEqual([call.args[0] for call in api.call_args_list],
                         ['releases?per_page=100&page=1', 'releases?per_page=100&page=2', 'releases/101'])

    def test_release_lookup_rejects_duplicate_tags_and_api_errors(self):
        draft = {'id': 10, 'tag_name': 'sdk-java/v0.1.0', 'draft': True}
        with patch.object(r, 'github', return_value=[draft, {**draft, 'id': 11}]), self.assertRaisesRegex(RuntimeError, 'Multiple releases'):
            r.release('java', '0.1.0')
        with patch.object(r, 'github', side_effect=RuntimeError('HTTP 403')), self.assertRaisesRegex(RuntimeError, '403'):
            r.release('java', '0.1.0')
        with patch.object(r, 'github', return_value=[]):
            self.assertIsNone(r.release('java', '0.1.0'))

    def test_asset_download_uses_id_and_preserves_binary_bytes(self):
        payload = bytes(range(256))
        def transport(command, **kwargs):
            self.assertEqual(command[:3], ['gh', 'api', f'repos/{r.REPO}/releases/assets/42'])
            kwargs['stdout'].write(payload)
        rel = {'assets': [{'name': 'sdk.tgz', 'id': 42}]}
        with patch.object(r.subprocess, 'run', side_effect=transport):
            r.download_asset(rel, 'sdk.tgz', self.directory)
        self.assertEqual((self.directory / 'sdk.tgz').read_bytes(), payload)
        for name, assets in (('../outside', [{'name': '../outside', 'id': 42}]), ('other', rel['assets']),
                             ('sdk.tgz', rel['assets'] * 2)):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                r.download_asset({'assets': assets}, name, self.directory)

    def test_old_sha_recovers_retained_packages_without_building_others(self):
        event = self.directory / 'event.json'
        r.write_json(event, {'inputs': {'sha': self.sha}})
        run = {**self.valid_run(), 'id': 123}
        rels = {'python': {'draft': True, 'assets': [{'name': 'release.json'}]}, 'java': None}
        env = {'GITHUB_EVENT_PATH': str(event), 'GITHUB_REPOSITORY': r.REPO,
               'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_SHA': 'b' * 40, 'RELEASE_PACKAGES': 'python,java'}
        with patch.dict(os.environ, env), patch.object(r, 'repository_controls'), patch.object(r, 'github', return_value={'workflow_runs': [run]}), patch.object(r, 'run', return_value='b' * 40), patch.object(r, 'versions', return_value={'python': '0.1.0', 'java': '0.1.0'}), patch.object(r, 'release', side_effect=lambda k, v: rels[k]), patch.object(r, 'registry', return_value=None), patch.object(r, 'download', return_value={'sha': self.sha}), patch.object(r, 'complete', return_value=False), patch.object(r, 'output') as output:
            r.plan()
        values = dict(call.args for call in output.call_args_list)
        self.assertEqual(values['packages'], ['python'])
        self.assertEqual(values['builds'], [])
        self.assertEqual(values['sha'], self.sha)

    def test_candidate_cannot_be_resigned_when_a_remote_release_exists(self):
        with patch.object(r, 'versions', return_value={'java': '0.1.0'}), patch.object(r, 'source_sha', return_value=self.sha), patch.object(r, 'release', return_value={'draft': True}), patch.object(r, 'sign_java') as sign:
            with self.assertRaisesRegex(RuntimeError, 'Restore the authenticated retained release'):
                r.seal('java', self.directory)
            sign.assert_not_called()

    def test_publisher_retry_restores_signed_files_before_candidate_download(self):
        import shutil
        version = '0.1.0'
        record = {'schema': 2, 'package': 'java', 'version': version, 'sha': self.sha,
                  'files': {'central-bundle.zip': '0' * 64}}
        remote = self.directory / 'remote'
        remote.mkdir()
        (remote / 'central-bundle.zip').write_bytes(b'original signed bundle')
        record['files']['central-bundle.zip'] = r.digest(remote / 'central-bundle.zip')
        r.write_json(remote / 'release.json', record)
        (remote / 'release.intoto.jsonl').write_text('fixture provenance')
        names = sorted(p.name for p in remote.iterdir())
        rel = {'id': 1, 'draft': True, 'tag_name': r.tag('java', version),
               'assets': [{'name': n, 'id': i + 1} for i, n in enumerate(names)]}
        def asset(rel, name, directory):
            shutil.copyfile(remote / name, directory / name)
        retry = self.directory / 'retry'
        with patch.object(r, 'versions', return_value={'java': version}), patch.object(r, 'source_sha', return_value=self.sha), patch.object(r, 'release', return_value=rel), patch.object(r, 'download_asset', side_effect=asset), patch.object(r, 'verify_attestation'), patch.object(r, 'check_tag', return_value=True), patch.object(r, 'output') as output, patch.object(r, 'sign_java') as sign, patch.object(r, 'registry', return_value=None), patch.object(r, 'gh') as write:
            r.inspect('java', retry)
            self.assertIn(('resume', 'true'), [call.args for call in output.call_args_list])
            r.seal('java', retry)
            r.retain('java', retry)
            sign.assert_not_called()
            write.assert_not_called()
            self.assertEqual((retry / 'central-bundle.zip').read_bytes(), b'original signed bundle')

    def test_read_only_consumer_receives_authenticated_handoff_without_draft_access(self):
        import shutil
        self.retained()
        (self.directory / 'release.intoto.jsonl').write_text('fixture provenance')
        (self.directory / 'central-deployment.json').write_text('{"id":"fixture state"}')
        # Use a nested job workspace so handoff stays within this test's temporary tree.
        publisher = self.directory / 'publisher'
        publisher.mkdir()
        for name in ('sdk.tgz', 'release.json', 'release.intoto.jsonl', 'central-deployment.json'):
            shutil.move(self.directory / name, publisher / name)
        with patch.object(r, 'versions', return_value={'sdk-js': '1.0.2'}), patch.object(r, 'source_sha', return_value=self.sha), patch.object(r, 'verify_attestation'), patch.object(r, 'verify_public'), patch.object(r, 'run') as run, patch.object(r, 'release', side_effect=AssertionError('Consumer must not look up drafts')):
            r.handoff('sdk-js', publisher)
            consumer = self.directory / 'consumer-artifacts'
            self.assertFalse((consumer / 'central-deployment.json').exists())
            r.consume('sdk-js', consumer)
            run.assert_called_once()
            (consumer / 'sdk.tgz').write_bytes(b'tampered')
            with self.assertRaises(RuntimeError):
                r.consume('sdk-js', consumer)
            self.assertEqual(run.call_count, 1)

    def test_workflow_permissions_and_job_order(self):
        workflow = (r.CONTROL_ROOT / '.github/workflows/publish.yml').read_text()
        check = (r.CONTROL_ROOT / '.github/workflows/release-check.yml').read_text()
        manual = (r.CONTROL_ROOT / '.github/workflows/mcp-release.yml').read_text()
        self.assertIn("vars.RELEASE_AUTOMATION_ENABLED == 'true'", workflow)
        self.assertIn('needs: [plan, sdk]', workflow)
        self.assertIn('needs: [plan, sdk, mcp-build]', workflow)
        self.assertNotIn('release.py inspect', check)
        self.assertNotIn('release.py download', check)
        self.assertIn('artifact-ids: ${{ inputs.artifact-id }}', check)
        self.assertEqual(workflow.count("needs.plan.outputs.sdk != 'true' || needs.sdk.result == 'success'"), 2)
        self.assertNotIn("needs.sdk.result == 'skipped'", workflow)
        for source in (check, manual):
            for forbidden in ('secrets.', 'id-token:', 'contents: write', 'environment:', 'release create'):
                self.assertNotIn(forbidden, source)
        for key in ('sdk', 'mcp', 'python', 'go', 'java', 'dotnet', 'php', 'ruby'):
            self.assertIn(f'needs: [plan, {key}-consumer]', workflow)
            self.assertIn(f'artifact-id: ${{{{ needs.{key}-build.outputs.artifact-id }}}}', workflow)
            self.assertIn(f'artifact-id: ${{{{ needs.{key}-publish.outputs.artifact-id }}}}', workflow)
        publisher = (r.CONTROL_ROOT / '.github/actions/release-publish/action.yml').read_text()
        self.assertLess(publisher.index('release.py inspect'), publisher.index('actions/download-artifact'))
        self.assertIn("if: steps.restore.outputs.resume == 'false'", publisher)
        self.assertLess(publisher.index('release.py publish'), publisher.index('release.py handoff'))
        for action in ('release-publish', 'release-finish'):
            privileged = (r.CONTROL_ROOT / f'.github/actions/{action}/action.yml').read_text()
            for forbidden in ('build_candidate', 'release.py consume', 'npm run', 'bundle install', 'pip install', 'verify.mjs', 'node_modules'):
                self.assertNotIn(forbidden, privileged)
        for source in (workflow, check, manual):
            self.assertNotIn('pull_request_target', source)
            self.assertNotIn('persist-credentials: true', source)


if __name__ == '__main__':
    unittest.main()
