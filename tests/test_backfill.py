import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.backfill import completed_history, history_commits
from scripts.dashboard import START_COMMIT, git, pending_targets
from tests.test_dashboard import commit, record


def test_exact_mainline_window_is_frozen_and_complete(source):
    revisions = [commit(source) for _ in range(102)]
    selected = history_commits(source, revisions[-1], 100)
    assert selected == revisions[2:]
    commit(source)
    assert history_commits(source, revisions[-1], 100) == selected
    with pytest.raises(ValueError, match="full clone"):
        history_commits(source, revisions[0], 100)
    for count in (0, 101):
        with pytest.raises(ValueError, match="between"):
            history_commits(source, "main", count)


def test_history_resume_does_not_replace_release_measurements(source):
    revision = commit(source, "1.0.0")
    historical = record(revision)
    historical["environment"].update(
        harness_revision=START_COMMIT, measurement_profile="fixed-harness-v1"
    )
    assert completed_history([historical], "test-runner") == {revision}
    assert completed_history([record(revision)], "test-runner") == set()
    assert completed_history([historical], "other-runner") == set()
    assert pending_targets(
        source, [historical], "test-runner", start_commit=revision
    ) == [("1.0.0", True)]
    historical["include_stress"] = False
    assert completed_history([historical]) == set()


def test_fixed_harness_imports_old_source_in_parent_and_child(tmp_path, source):
    (source / "strawberry").mkdir()
    (source / "strawberry" / "__init__.py").write_text("VALUE = 'old'\n")
    (source / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    git(source, "add", ".")
    source_revision = commit(source)
    harness = tmp_path / "harness"
    subprocess.run(["git", "clone", "-q", str(source), str(harness)], check=True)
    git(harness, "config", "user.name", "Harness tests")
    git(harness, "config", "user.email", "benchmarks@example.com")
    git(harness, "config", "commit.gpgSign", "false")
    (harness / "strawberry" / "__init__.py").write_text("VALUE = 'new'\n")
    tests = harness / "tests" / "benchmarks"
    tests.mkdir(parents=True)
    (harness / "tests" / "__init__.py").touch()
    (tests / "__init__.py").touch()
    (harness / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (tests / "metadata.py").write_text("""import json
def write_metadata(path, instrument):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"suite_sha256": "a" * 64, "instrument": instrument}))
""")
    (tests / "test_source.py").write_text("""import subprocess
import sys
import strawberry
def test_source():
    assert strawberry.VALUE == "old"
    child = subprocess.check_output([sys.executable, "-c", "import strawberry; print(strawberry.VALUE)"], text=True)
    assert child.strip() == "old"
""")
    git(harness, "add", ".")
    harness_revision = commit(harness)
    # Ignore only Python-generated cache files in the test source fixture.
    (source / ".git" / "info" / "exclude").write_text("__pycache__/\n")
    artifact = tmp_path / "artifact"
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "scripts" / "history_benchmark.py"),
            "--source",
            str(source),
            "--harness",
            str(harness),
            "--artifact",
            str(artifact),
            "--validate-only",
        ],
        check=True,
    )
    environment = json.loads((artifact / "environment.json").read_text())
    assert environment["source_revision"] == source_revision
    assert environment["harness_revision"] == harness_revision
    assert environment["source_import_path"] == str(
        source / "strawberry" / "__init__.py"
    )
    assert environment["source_version"] == "1.0.0"
