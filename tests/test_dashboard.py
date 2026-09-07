import json
import shutil
from pathlib import Path

import pytest

from scripts.dashboard import (
    PYTHON,
    git,
    import_run,
    pending_targets,
    publish,
    read_records,
)


def commit(source, tag=None):
    git(source, "commit", "--allow-empty", "-qm", tag or "main update")
    revision = git(source, "rev-parse", "HEAD")
    if tag:
        git(source, "tag", tag)
    return revision


def record(revision, stress=True, python=PYTHON, machine="test-runner"):
    return {
        "environment": {
            "source_revision": revision,
            "python": python,
            "runner": {"RUNNER_NAME": machine},
        },
        "include_stress": stress,
    }


def test_release_backlog_and_stress_upgrade(source):
    commit(source, "0.1.0")
    start = commit(source)
    commit(source, "0.2.0rc1")
    first = commit(source, "0.2.0")
    second = commit(source, "0.2.1")
    third = commit(source, "0.3.0")
    main = commit(source)
    options = {"start_commit": start, "max_releases": 2}
    assert pending_targets(source, [], "test-runner", **options) == [
        ("0.2.0", True),
        ("0.2.1", True),
        ("main", False),
    ]
    # A daily sample cannot satisfy a release's full-size requirement.
    records = [record(first, False), record(main, False)]
    assert pending_targets(source, records, "test-runner", **options) == [
        ("0.2.0", True),
        ("0.2.1", True),
    ]
    records += [record(first), record(second)]
    assert pending_targets(source, records, "test-runner", **options) == [
        ("0.3.0", True)
    ]
    records.append(record(third))
    assert pending_targets(source, records, "test-runner", **options) == []
    assert pending_targets(
        source, records, "test-runner", include_stress=True, **options
    ) == [("main", True)]


def test_release_at_main_measured_once_and_wrong_environment_not_reused(source):
    start = commit(source)
    main = commit(source, "1.0.0")
    git(source, "tag", "1.0.1")
    options = {"start_commit": start}
    assert pending_targets(source, [], "test-runner", **options) == [("1.0.0", True)]
    assert pending_targets(source, [record(main)], "test-runner", **options) == []
    assert pending_targets(
        source, [record(main, python="3.13.0")], "test-runner", **options
    ) == [("1.0.0", True)]
    assert pending_targets(
        source, [record(main, machine="other")], "test-runner", **options
    ) == [("1.0.0", True)]


@pytest.fixture
def report(tmp_path):
    root = tmp_path / "report"
    (root / "site").mkdir(parents=True)
    (root / "site" / "about.html").write_text("<h1>Methodology</h1>")
    shutil.copyfile(Path(__file__).parents[1] / "asv.conf.json", root / "asv.conf.json")
    return root


def artifact(
    tmp_path,
    revision,
    median=1_000_000,
    version="1.0.0",
    workload="a" * 64,
    dependency="3.2.6",
):
    directory = tmp_path / f"artifact-{revision}-{version}-{median}"
    directory.mkdir()
    environment = {
        "source_revision": revision,
        "worktree_dirty": False,
        "instrument": "walltime",
        "python": f"{PYTHON} (test build)",
        "recorded_at": "2026-09-07T12:00:00+00:00",
        "suite_sha256": workload,
        "lock_sha256": version,
        "machine": "arm64",
        "platform": "testOS",
        "hardware": {"cpu_model": "test CPU", "logical_cpus": 8},
        "dependencies": {"strawberry-graphql": version, "graphql-core": dependency},
        "runner": {"RUNNER_NAME": "test-runner"},
    }
    (directory / "environment.json").write_text(json.dumps(environment))
    (directory / "results_raw.json").write_text(
        json.dumps(
            {
                "instrument": {"type": "walltime"},
                "benchmarks": [
                    {
                        "uri": "tests/benchmarks/test_example.py::test_query[100]",
                        "stats": {"median_ns": median, "total_time": 1.0},
                    }
                ],
            }
        )
    )
    (directory / "results.xml").write_text(
        '<testsuites><testsuite><testcase file="tests/benchmarks/test_example.py" name="test_query[100]"/></testsuite></testsuites>'
    )
    return directory


def test_publish_keeps_two_releases_in_same_series(source, report, tmp_path):
    commit(source, "0.1.0")
    first = commit(source, "1.0.0")
    second = commit(source, "1.0.1")
    for revision, median, version in (
        (first, 1_000_000, "1.0.0"),
        (second, 2_000_000, "1.0.1"),
    ):
        import_run(
            report,
            source,
            artifact(tmp_path, revision, median, version),
            ref=revision,
            include_stress=True,
        )
    assert len(read_records(report)) == 2
    assert len(list((report / "results" / "test-runner").glob("*-native-*.json"))) == 2
    publish(report, source)
    index = json.loads((report / "html" / "index.json").read_text())
    assert set(index["tags"]) == {"1.0.0", "1.0.1"}
    assert len(index["params"]["dependencies"]) == 1
    series = list(
        (report / "html" / "graphs").glob("**/test_example.test_query[[]100].json")
    )
    # Both a summary graph and the environment's graph retain both real medians.
    assert len(series) == 2
    for path in series:
        points = json.loads(path.read_text())
        assert [point[1] for point in points] == [0.001, 0.002]
    assert (report / "html" / "about.html").read_text() == "<h1>Methodology</h1>"
    assert len(list((report / "html" / "metadata").glob("*.json"))) == 2
    assert (report / "html" / "asv.js").exists()


@pytest.mark.parametrize("change", ["workload", "dependency"])
def test_changed_environment_starts_a_separate_series(source, report, tmp_path, change):
    first = commit(source, "1.0.0")
    second = commit(source, "1.0.1")
    import_run(
        report, source, artifact(tmp_path, first), ref=first, include_stress=True
    )
    options = (
        {"workload": "b" * 64} if change == "workload" else {"dependency": "3.3.0"}
    )
    import_run(
        report,
        source,
        artifact(tmp_path, second, **options),
        ref=second,
        include_stress=True,
    )
    files = list((report / "results" / "test-runner").glob("*-native-*.json"))
    assert len({json.loads(path.read_text())["env_name"] for path in files}) == 2


@pytest.mark.parametrize(
    "invalid",
    [
        "failure",
        "skipped",
        "missing",
        "duplicate",
        "nan",
        "zero",
        "instrument",
        "dirty",
        "revision",
        "python",
    ],
)
def test_invalid_measurements_never_become_points(source, report, tmp_path, invalid):
    revision = commit(source)
    directory = artifact(tmp_path, revision)
    metadata = directory / "environment.json"
    raw_path = directory / "results_raw.json"
    env = json.loads(metadata.read_text())
    raw = json.loads(raw_path.read_text())
    if invalid in ("failure", "skipped"):
        xml = directory / "results.xml"
        xml.write_text(xml.read_text().replace("/>", f"><{invalid}/></testcase>"))
    elif invalid == "missing":
        raw["benchmarks"] = []
    elif invalid == "duplicate":
        raw["benchmarks"] *= 2
    elif invalid in ("nan", "zero"):
        raw["benchmarks"][0]["stats"]["median_ns"] = (
            float("nan") if invalid == "nan" else 0
        )
    elif invalid == "instrument":
        raw["instrument"]["type"] = "simulation"
    elif invalid == "dirty":
        env["worktree_dirty"] = True
    elif invalid == "revision":
        env["source_revision"] = "0" * 40
    elif invalid == "python":
        env["python"] = "3.13.0"
    metadata.write_text(json.dumps(env))
    raw_path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        import_run(report, source, directory, ref=revision, include_stress=True)
    assert not (report / "results").exists()
    assert read_records(report) == []


def test_fixed_harness_preserves_native_results_for_the_same_commit(
    source, report, tmp_path
):
    revision = commit(source)
    native = artifact(tmp_path, revision)
    historical = artifact(tmp_path, revision, median=2_000_000)
    metadata = historical / "environment.json"
    environment = json.loads(metadata.read_text())
    environment.update(
        harness_revision=revision, measurement_profile="fixed-harness-v1"
    )
    metadata.write_text(json.dumps(environment))
    for directory in (native, historical):
        import_run(report, source, directory, ref=revision, include_stress=True)
    assert len(read_records(report)) == 2
    publish(report, source)
    index = json.loads((report / "html" / "index.json").read_text())
    assert set(index["params"]["measurement_profile"]) == {None, "fixed-harness-v1"}
    graphs = list(
        (report / "html" / "graphs").glob("**/test_example.test_query[[]100].json")
    )
    assert len(graphs) == 3  # summary plus two separately selectable profiles
