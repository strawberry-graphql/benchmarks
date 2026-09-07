"""Backfill a bounded, resumable batch with one fixed benchmark environment."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.dashboard import PYTHON, START_COMMIT, git, import_run, read_records

BATCH_SIZE = 10


def history_commits(source: Path, end: str, count: int) -> list[str]:
    if not 1 <= count <= 100:
        raise ValueError("History length must be between 1 and 100 commits")
    end = git(source, "rev-parse", f"{end}^{{commit}}")
    subprocess.run(
        ["git", "-C", str(source), "merge-base", "--is-ancestor", end, "main"],
        check=True,
    )
    commits = git(
        source, "rev-list", "--first-parent", f"--max-count={count}", end
    ).splitlines()
    if len(commits) != count:
        raise ValueError("A full clone is required to select the requested history")
    return list(reversed(commits))


def completed_history(records: list[dict], machine: str | None = None) -> set[str]:
    return {
        record["environment"]["source_revision"]
        for record in records
        if record["environment"].get("harness_revision") == START_COMMIT
        and record["environment"].get("measurement_profile") == "fixed-harness-v1"
        and record["environment"]["python"].split()[0] == PYTHON
        and record["include_stress"]
        and (
            machine is None or record["environment"]["runner"]["RUNNER_NAME"] == machine
        )
    }


def run_batch(root: Path, source: Path, end: str, count: int, batch: int) -> None:
    commits = history_commits(source, end, count)
    if not 0 <= batch < (count + BATCH_SIZE - 1) // BATCH_SIZE:
        raise ValueError("Batch is outside the requested commit window")
    selected = commits[batch * BATCH_SIZE : (batch + 1) * BATCH_SIZE]
    completed = completed_history(read_records(root), os.environ["RUNNER_NAME"])
    pending = [commit for commit in selected if commit not in completed]
    print(
        f"Historical batch {batch + 1}: {len(pending)} pending of {len(selected)} commits",
        flush=True,
    )
    if not pending:
        return
    harness = root / "benchmark-harness"
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "worktree",
            "add",
            "--detach",
            str(harness),
            START_COMMIT,
        ],
        check=True,
    )
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    subprocess.run(["uv", "sync", "--locked"], cwd=harness, env=env, check=True)
    python = harness / ".venv" / "bin" / "python"
    failures = []
    for commit in pending:
        artifact = root / "benchmark-artifacts" / f"history-{commit}"
        artifact.mkdir(parents=True, exist_ok=False)
        subprocess.run(
            ["git", "-C", str(source), "checkout", "--detach", commit], check=True
        )
        for path in (source / ".codspeed").glob("results_*.json"):
            path.unlink()
        print(f"Measuring historical commit {commit}", flush=True)
        try:
            subprocess.run(
                [
                    str(python),
                    str(root / "scripts" / "history_benchmark.py"),
                    "--source",
                    str(source),
                    "--harness",
                    str(harness),
                    "--artifact",
                    str(artifact),
                ],
                env=env,
                check=True,
            )
            for path in (source / ".codspeed").glob("results_*.json"):
                shutil.copyfile(path, artifact / path.name)
            import_run(root, source, artifact, ref=commit, include_stress=True)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            print(f"Historical measurement failed for {commit}: {error}", flush=True)
            failures.append(commit)
        finally:
            for path in (source / ".codspeed").glob("results_*.json"):
                shutil.copyfile(path, artifact / path.name)
    if failures:
        raise SystemExit(f"Unsuccessful historical revisions: {', '.join(failures)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "plan", "verify"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--end", default=os.environ.get("HISTORY_REF") or "main")
    parser.add_argument(
        "--count", type=int, default=int(os.environ.get("HISTORY_COMMITS", "100"))
    )
    parser.add_argument(
        "--batch", type=int, default=int(os.environ.get("HISTORY_BATCH", "0"))
    )
    args = parser.parse_args()
    source = args.source.resolve()
    root = Path(__file__).resolve().parents[1]
    commits = history_commits(source, args.end, args.count)
    if args.command == "plan":
        batches = list(range((args.count + BATCH_SIZE - 1) // BATCH_SIZE))
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
            output.write(f"revision={commits[-1]}\nbatches={json.dumps(batches)}\n")
        print(
            json.dumps(
                {
                    "count": len(commits),
                    "oldest": commits[0],
                    "newest": commits[-1],
                    "batches": batches,
                }
            )
        )
    elif args.command == "verify":
        missing = set(commits) - completed_history(read_records(root))
        print(
            f"Historical coverage: {len(commits) - len(missing)}/{len(commits)} commits"
        )
        if missing:
            sys.exit(f"Missing historical measurements: {', '.join(sorted(missing))}")
    else:
        run_batch(root, source, args.end, args.count, args.batch)


if __name__ == "__main__":
    main()
