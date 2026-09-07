import subprocess

import pytest

from scripts.dashboard import git


@pytest.fixture
def source(tmp_path):
    source = tmp_path / "source"
    subprocess.run(["git", "init", "-q", "-b", "main", str(source)], check=True)
    git(source, "config", "user.name", "Benchmark tests")
    git(source, "config", "user.email", "benchmarks@example.com")
    git(source, "config", "commit.gpgSign", "false")
    git(source, "config", "tag.gpgSign", "false")
    return source
