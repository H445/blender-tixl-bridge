"""Keep pull-request checks and release gating connected to unit discovery."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def section(text: str, key: str) -> str:
    """Return a simple indentation-delimited YAML mapping section."""
    match = re.search(rf"(?m)^  {re.escape(key)}:\s*$", text)
    if not match:
        return ""
    start = match.end()
    next_section = re.search(r"(?m)^  [A-Za-z0-9_-]+:\s*$", text[start:])
    return text[start:start + next_section.start()] if next_section else text[start:]


class WorkflowConfigurationTest(unittest.TestCase):
    def test_reusable_unit_workflow_covers_pr_push_and_callable_runs(self):
        workflow = (ROOT / ".github" / "workflows" / "unit-tests.yml").read_text(encoding="utf-8")
        triggers = re.search(r"(?ms)^on:\s*\n(.*?)(?=^[A-Za-z][A-Za-z0-9_-]*:|\Z)", workflow)
        self.assertIsNotNone(triggers)
        for event in ("pull_request", "push", "workflow_call"):
            self.assertRegex(triggers.group(1), rf"(?m)^  {event}:\s*$")
        jobs = section(workflow, "unit-tests")
        self.assertIn("runs-on: ${{ matrix.os }}", jobs)
        self.assertRegex(jobs, r"(?m)^        os: \[.*ubuntu-latest.*windows-latest.*\]$")
        self.assertIn("actions/setup-python@v5", jobs)
        self.assertIn("python -m unittest discover", jobs)
        self.assertIn("test_*.py", jobs)

    def test_release_job_waits_for_reusable_unit_workflow(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        unit_job = section(workflow, "unit-tests")
        release_job = section(workflow, "release")
        self.assertIn("uses: ./.github/workflows/unit-tests.yml", unit_job)
        self.assertRegex(release_job, r"(?m)^    needs: unit-tests\s*$")
        self.assertIn("gh release create", release_job)


if __name__ == "__main__":
    unittest.main()
