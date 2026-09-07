"""Import verified pytest-codspeed walltime results and publish ASV charts."""

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

from asv import util
from asv.commands.publish import Publish
from asv.config import Config
from asv.results import Results
from asv.runner import BenchmarkResult

PYTHON = "3.14.7"
# The first main-branch commit containing the modern, correctness-checked suite.
START_COMMIT = "226d2deab92f21fd6696d94b37d8824cc414003e"


def git(source: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]


def read_records(root: Path) -> list[dict]:
    return [
        json.loads(path.read_text())
        for path in sorted((root / "records").glob("*.json"))
    ]


def pending_targets(
    source: Path,
    records: list[dict],
    machine: str,
    *,
    start_commit: str = START_COMMIT,
    include_stress: bool = False,
    max_releases: int = 5,
) -> list[tuple[str, bool]]:
    """Catch up oldest unmeasured stable tags, then sample current main."""
    completed = {
        (record["environment"]["source_revision"], record["include_stress"])
        for record in records
        if record["environment"]["python"].split()[0] == PYTHON
        and record["environment"]["runner"]["RUNNER_NAME"] == machine
        and "harness_revision" not in record["environment"]
    }

    def missing(commit: str, stress: bool) -> bool:
        return (commit, True) not in completed and (
            stress or (commit, False) not in completed
        )

    tags = []
    for tag in git(source, "tag", "--list").splitlines():
        if not re.fullmatch(r"\d+\.\d+\.\d+", tag):
            continue
        commit = git(source, "rev-parse", f"refs/tags/{tag}^{{commit}}")
        descendant = subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "merge-base",
                "--is-ancestor",
                start_commit,
                commit,
            ],
            check=False,
        )
        if descendant.returncode not in (0, 1):
            raise RuntimeError(f"Cannot determine release ancestry for {tag}")
        if descendant.returncode == 0 and missing(commit, True):
            tags.append(tag)
    targets = []
    selected_commits = set()
    for tag in sorted(tags, key=lambda tag: tuple(map(int, tag.split(".")))):
        commit = git(source, "rev-parse", f"refs/tags/{tag}^{{commit}}")
        if commit not in selected_commits and len(targets) < max_releases:
            targets.append((tag, True))
            selected_commits.add(commit)
    main = git(source, "rev-parse", "main^{commit}")
    if main not in selected_commits and missing(main, include_stress):
        targets.append(("main", include_stress))
    return targets


def import_run(
    root: Path, source: Path, artifact: Path, *, ref: str, include_stress: bool
) -> Path:
    environment = json.loads((artifact / "environment.json").read_text())
    raw_paths = list(artifact.glob("results_*.json"))
    if len(raw_paths) != 1:
        raise ValueError("Expected exactly one native result file")
    raw = json.loads(raw_paths[0].read_text())
    commit = git(source, "rev-parse", f"{ref}^{{commit}}")
    if environment["source_revision"] != commit or environment["worktree_dirty"]:
        raise ValueError(
            "Measurements must identify the requested clean source revision"
        )
    if (
        environment["instrument"] != "walltime"
        or raw["instrument"]["type"] != "walltime"
    ):
        raise ValueError("Only native walltime measurements belong in these charts")
    if environment["python"].split()[0] != PYTHON:
        raise ValueError(f"Expected Python {PYTHON}")
    cases = ElementTree.parse(artifact / "results.xml").findall(".//testcase")
    if not cases or any(
        list(case.iter(tag))
        for case in cases
        for tag in ("failure", "error", "skipped")
    ):
        raise ValueError("Every measured benchmark must pass without skips")
    tested = {f"{case.attrib['file']}::{case.attrib['name']}" for case in cases}
    benchmarks = raw["benchmarks"]
    measured = {benchmark["uri"] for benchmark in benchmarks}
    if (
        measured != tested
        or len(measured) != len(benchmarks)
        or len(tested) != len(cases)
    ):
        raise ValueError(
            "Native measurements and passing test cases must match exactly"
        )
    for benchmark in benchmarks:
        if not re.fullmatch(
            r"tests/benchmarks/[\w/]+\.py::[\w.\[\]()-]+", benchmark["uri"]
        ):
            raise ValueError(f"Unsupported benchmark identifier: {benchmark['uri']}")
        median = benchmark["stats"]["median_ns"]
        if type(median) not in (int, float) or not math.isfinite(median) or median <= 0:
            raise ValueError("Native medians must be finite and positive")

    # Exclude Strawberry's own version: each release changes it, not its dependencies.
    dependencies = {
        name: version
        for name, version in environment["dependencies"].items()
        if name.lower().replace("_", "-") != "strawberry-graphql"
    }
    machine = environment["runner"]["RUNNER_NAME"]
    if not machine or not re.fullmatch(r"[\w.-]+", machine) or machine in (".", ".."):
        raise ValueError("A stable runner name is required")
    params = {
        "machine": machine,
        "python": PYTHON,
        "cpu": environment["hardware"]["cpu_model"] or "unknown",
        "arch": environment["machine"],
        "os": environment["platform"],
        "workload": environment["suite_sha256"][:12],
        "dependencies": digest(dependencies),
        "python_build": digest(environment["python"]),
    }
    if "measurement_profile" in environment:
        params["measurement_profile"] = environment["measurement_profile"]
    identity = digest(params)
    date = int(git(source, "show", "-s", "--format=%ct", commit)) * 1000
    result = Results(params, {}, commit, date, PYTHON, f"native-{identity}", {})
    result.load_data(str(root / "results"))
    catalog_path = root / "results" / "benchmarks.json"
    catalog = (
        util.load_json(str(catalog_path), api_version=2)
        if catalog_path.exists()
        else {}
    )
    for benchmark in benchmarks:
        name = (
            benchmark["uri"]
            .removeprefix("tests/benchmarks/")
            .replace(".py::", ".")
            .replace("/", ".")
        )
        definition = {
            "name": name,
            "version": "native-median-v1",
            "type": "time",
            "unit": "seconds",
            "params": [],
            "param_names": [],
            "code": f"# pytest node: {benchmark['uri']}\n# Native median seconds per callback; not request p95/p99.\n# See about.html for methodology and workflow status.",
        }
        catalog[name] = definition
        result.add_result(
            definition,
            BenchmarkResult(
                [benchmark["stats"]["median_ns"] / 1e9], [None], [None], 0, "", None
            ),
            started_at=datetime.fromisoformat(environment["recorded_at"]),
            duration=benchmark["stats"]["total_time"],
        )
    util.write_json(str(catalog_path), catalog, api_version=2)
    util.write_json(
        str(root / "results" / machine / "machine.json"),
        {
            "machine": machine,
            "arch": params["arch"],
            "os": params["os"],
            "cpu": params["cpu"],
            "num_cpu": environment["hardware"]["logical_cpus"],
            "ram": "not recorded",
        },
        api_version=1,
    )
    result.save(str(root / "results"))
    record_path = root / "records" / f"{commit}-{identity}.json"
    previous = json.loads(record_path.read_text()) if record_path.exists() else {}
    record = {
        "environment": environment,
        "ref": ref,
        "include_stress": include_stress or previous.get("include_stress", False),
        "benchmark_count": len(benchmarks),
        "raw_sha256": hashlib.sha256(raw_paths[0].read_bytes()).hexdigest(),
        "measurement": "median native wall-clock seconds per callback",
    }
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    return record_path


def publish(root: Path, source: Path) -> None:
    conf = Config.load(str(root / "asv.conf.json"))
    conf.repo = str(source)
    conf.results_dir = str(root / "results")
    conf.html_dir = str(root / "html")
    Publish.run(conf, pull=False)
    index_path = root / "html" / "index.json"
    index = json.loads(index_path.read_text())
    commits = {
        record["environment"]["source_revision"] for record in read_records(root)
    }
    # Show release labels only for commits with measurements in this fresh history.
    index["tags"] = {
        tag: revision
        for tag, revision in index["tags"].items()
        if index["revision_to_hash"][str(revision)] in commits
    }
    index_path.write_text(json.dumps(index, separators=(",", ":")) + "\n")
    shutil.copyfile(root / "site" / "about.html", root / "html" / "about.html")
    shutil.copytree(root / "records", root / "html" / "metadata", dirs_exist_ok=True)
    if not list((root / "html" / "graphs" / "summary").glob("*.json")):
        raise ValueError("Publication produced no charts")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["import", "publish"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--ref", default="main")
    parser.add_argument("--include-stress", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == "publish":
        publish(root, args.source.resolve())
    else:
        if args.artifact is None:
            parser.error("import requires --artifact")
        import_run(
            root,
            args.source.resolve(),
            args.artifact,
            ref=args.ref,
            include_stress=args.include_stress,
        )
