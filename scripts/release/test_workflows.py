import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class WorkflowTests(unittest.TestCase):
    def test_verification_has_no_ordinary_branch_push_trigger(self):
        text = (ROOT / '.github/workflows/verify.yml').read_text()
        self.assertIn('on:\n  push:\n    branches: [main]\n  pull_request:\n    branches: [main]\n', text)
        self.assertNotIn('pull_request_target', text)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", text)

    def test_each_runtime_matrix_uses_the_affected_package_selection(self):
        text = (ROOT / '.github/workflows/verify.yml').read_text()
        for key in ('python', 'go', 'java', 'dotnet', 'php', 'ruby'):
            self.assertIn(f"if: contains(fromJSON(needs.changes.outputs.packages), '{key}')", text)
        self.assertIn("contains(fromJSON(needs.changes.outputs.packages), 'sdk-js')", text)
        self.assertIn("contains(fromJSON(needs.changes.outputs.packages), 'mcp-server')", text)
        self.assertIn('run: python3 scripts/release/gate.py', text)

    def test_pypi_runs_directly_after_retention_and_before_handoff(self):
        publisher = (ROOT / '.github/actions/release-publish/action.yml').read_text()
        self.assertNotIn('pypa/gh-action-pypi-publish@', publisher)
        workflow = (ROOT / '.github/workflows/publish.yml').read_text()
        python = workflow.split('  python-publish:\n', 1)[1].split('\n  python-consumer:', 1)[0]
        self.assertIn('      - uses: pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086', python)
        self.assertIn("if: steps.publish.outputs.upload == 'true'", python)
        self.assertLess(python.index('uses: ./automation/.github/actions/release-publish'), python.index('uses: pypa/'))
        self.assertLess(python.index('uses: pypa/'), python.index('release.py handoff'))
        self.assertLess(python.index('release.py handoff'), python.index('uses: actions/upload-artifact@'))
        self.assertIn('artifact-id: ${{ steps.consumer-artifact.outputs.artifact-id }}', python)


if __name__ == '__main__':
    unittest.main()
