"""Measure pending releases and main in an owned Strawberry checkout."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from scripts.dashboard import (
    START_COMMIT,
    git,
    import_run,
    pending_targets,
    read_records,
)


def measure(root: Path, source: Path, ref: str, include_stress: bool) -> None:
    commit = git(source, "rev-parse", f"{ref}^{{commit}}")
    # Only merged revisions with the modern suite belong on the public timeline.
    for ancestor, descendant in ((START_COMMIT, commit), (commit, "main")):
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "merge-base",
                "--is-ancestor",
                ancestor,
                descendant,
            ],
            check=True,
        )
    artifact = (
        root
        / "benchmark-artifacts"
        / f"{commit}-{'full' if include_stress else 'daily'}"
    )
    artifact.mkdir(parents=True, exist_ok=False)
    subprocess.run(
        ["git", "-C", str(source), "checkout", "--detach", commit], check=True
    )
    # Avoid importing a previous invocation's native measurements.
    for path in (source / ".codspeed").glob("results_*.json"):
        path.unlink()
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)

    def run(*args: str) -> None:
        subprocess.run(["uv", *args], cwd=source, env=env, check=True)

    run("sync", "--locked")
    run(
        "run",
        "--no-sync",
        "python",
        "-m",
        "tests.benchmarks.metadata",
        str(artifact / "environment.json"),
        "--instrument",
        "walltime",
    )
    try:
        run(
            "run",
            "--no-sync",
            "pytest",
            "tests/benchmarks",
            "--codspeed",
            "--codspeed-mode",
            "walltime",
            "-p",
            "no:codeflash-benchmark",
            "-m",
            "" if include_stress else "not benchmark_stress",
            "--codspeed-warmup-time",
            "0.1",
            "--codspeed-max-time",
            "1",
            "--codspeed-max-rounds",
            "30",
            f"--junitxml={artifact / 'results.xml'}",
            "-o",
            "junit_family=legacy",
        )
    finally:
        # Keep diagnostics even when correctness checks fail; import only on success.
        for path in (source / ".codspeed").glob("results_*.json"):
            shutil.copyfile(path, artifact / path.name)
    import_run(root, source, artifact, ref=commit, include_stress=include_stress)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--ref", default=os.environ.get("STRAWBERRY_REF", ""))
    parser.add_argument(
        "--include-stress",
        action="store_true",
        default=os.environ.get("INCLUDE_STRESS") == "true",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = args.source.resolve()
    targets = (
        [(args.ref, args.include_stress)]
        if args.ref
        else pending_targets(
            source,
            read_records(root),
            os.environ["RUNNER_NAME"],
            include_stress=args.include_stress,
        )
    )
    print(f"Pending measurements: {targets}", flush=True)
    failures = []
    for ref, stress in targets:
        try:
            measure(root, source, ref, stress)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            # Retain other successful releases and retry this revision next time.
            print(f"Measurement failed for {ref}: {error}", flush=True)
            failures.append(ref)
    if failures:
        raise SystemExit(f"Failed revisions: {', '.join(failures)}")


if __name__ == "__main__":
    main()
