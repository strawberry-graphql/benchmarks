"""Run a fixed benchmark harness against an explicitly selected source checkout."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    source, harness, artifact = (
        path.resolve() for path in (args.source, args.harness, args.artifact)
    )
    if git(source, "status", "--porcelain") or git(harness, "status", "--porcelain"):
        raise ValueError("Historical source and benchmark harness must both be clean")

    # Import the target before pytest adds the harness to sys.path. Child-process
    # benchmarks also import the target because their cwd and PYTHONPATH point here.
    os.chdir(source)
    os.environ["PYTHONPATH"] = str(source)
    sys.path.insert(0, str(source))
    import strawberry

    imported = Path(strawberry.__file__).resolve()
    if imported != source / "strawberry" / "__init__.py":
        raise ValueError(f"Wrong Strawberry source imported: {imported}")
    sys.path.insert(0, str(harness))
    from tests.benchmarks.metadata import write_metadata

    write_metadata(artifact / "environment.json", "walltime")
    environment = json.loads((artifact / "environment.json").read_text())
    environment.update(
        source_revision=git(source, "rev-parse", "HEAD"),
        source_version=tomllib.loads((source / "pyproject.toml").read_text())[
            "project"
        ]["version"],
        source_import_path=str(imported),
        harness_revision=git(harness, "rev-parse", "HEAD"),
        measurement_profile="fixed-harness-v1",
        excluded_benchmarks=["test_http.py: historical JSON wire format differs"],
        dependency_policy="Installed from the fixed harness lockfile; Strawberry imports from the target checkout",
    )
    environment["harness_suite_sha256"] = environment["suite_sha256"]
    environment["suite_sha256"] = hashlib.sha256(
        (environment["suite_sha256"] + "\0exclude=test_http.py").encode()
    ).hexdigest()
    (artifact / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")

    import pytest

    options = [
        str(harness / "tests" / "benchmarks"),
        "-c",
        str(harness / "pyproject.toml"),
        f"--rootdir={harness}",
        "-p",
        "no:codeflash-benchmark",
        "-q",
        f"--junitxml={artifact / 'results.xml'}",
        "-o",
        "junit_family=legacy",
        f"--ignore={harness / 'tests' / 'benchmarks' / 'test_http.py'}",
    ]
    if not args.validate_only:
        options += [
            "--codspeed",
            "--codspeed-mode",
            "walltime",
            "--codspeed-warmup-time",
            "0.1",
            "--codspeed-max-time",
            "1",
            "--codspeed-max-rounds",
            "30",
        ]
    outcome = pytest.main(options)
    if git(source, "status", "--porcelain") or git(harness, "status", "--porcelain"):
        raise ValueError("Benchmark execution modified a source checkout")
    raise SystemExit(outcome)


if __name__ == "__main__":
    main()
