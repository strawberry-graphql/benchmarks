# Strawberry performance reporting

[**speed.strawberry.rocks**](https://speed.strawberry.rocks/) keeps ASV charts for
Strawberry's native elapsed times, including future stable releases. The old
benchmark history is reset; new results start with the modern suite merged on
September 7, 2026. Earlier data is available in Git history.

## One measurement suite, retained charts

Workloads and correctness assertions live in
[strawberry/tests/benchmarks](https://github.com/strawberry-graphql/strawberry/tree/main/tests/benchmarks).
We run that pytest-codspeed suite in native walltime mode and import its median
nanoseconds as seconds per callback. ASV 0.6.6 publishes the static charts; it does
not build Strawberry or run a second timing harness. CPU simulation and memory
checks continue in Strawberry's CodSpeed integration.

Only clean, matching source revisions with a complete set of passing measured
tests are imported. Missing, skipped, unsuccessful and non-finite measurements are
rejected. Benchmark medians are not request p95/p99 latency. The raw export has
aggregate statistics, so the importer does not invent samples or confidence
intervals.

Chart series separate workload hashes, Python builds, dependencies, runner, CPU
and operating system. Strawberry's own package version is excluded from the
dependency identity so successive releases can share a series. Environment
records retain the full dependency list, source revision and lockfile hash.
A changed workload or environment starts a separate baseline.

## Automatic release coverage

`.github/workflows/asv.yml`, named **Native benchmarks**, runs daily on the
existing dedicated `self-hosted, macOS, ARM64` runner. It discovers stable
`MAJOR.MINOR.PATCH` tags descended from the benchmark modernization commit and
measures unrecorded releases, oldest first, up to five per run. Any backlog is
picked up on subsequent runs. Prereleases and the obsolete historical releases
are excluded. It then measures main if needed. Unsuccessful revisions stay pending.
Release runs always include stress sizes; main includes them on Sundays or on
request. A release whose commit already has full measurements reuses those
measurements and gains its release label during publication.

Python **3.14.7** is pinned, matching the CPU and memory jobs and the latest
stable Python as of September 7, 2026. Each source revision installs its locked
dependencies. Runs are serial, with a global concurrency group and a 45-minute
job timeout. Use an otherwise idle runner. Measurements are advisory; no
regression threshold is enforced.

A manual dispatch with an empty `strawberry_ref` runs the same catch-up logic.
To remeasure a specific merged revision, supply its ref and select stress sizes
if needed. Only merged commits containing the modern suite are accepted. Never
add pull-request triggers to this persistent runner.

## Retained data and publication

- `results/`: ASV timing history, benchmark catalog and machine information.
- `records/`: source, workload and environment provenance for each run identity.
- `html/`: generated ASV dashboard, graphs, metadata and the methodology page.
- `site/about.html`: editable methodology, CPU/memory links and live workflow status.

After measurement, the workflow regenerates ASV charts from all retained results.
On this repository's **main branch only**, it commits results, records and the
generated site. The existing Vercel deployment serves `html/` at the existing
domain. Branch validation uploads artifacts without changing production. No DNS
or hosting migration is required. Successful measurements are retained even if
another revision is unsuccessful, and the job still reports that error.

Raw CodSpeed JSON and JUnit diagnostics are attached to each workflow run for
90 days. Normalized timing history and environment records are retained in Git.
Old results cannot be recreated by the new workflow because its release cutoff
excludes them. The first new data point is a baseline; trends appear as further
commits and releases are measured.

## Local development

```sh
uv sync --locked
uv run pytest
node tests/test_site.cjs
# A full Strawberry clone with main and release tags is needed to publish:
uv run python -m scripts.dashboard publish --source /path/to/strawberry
python3 -m http.server 8765 --directory html --bind 127.0.0.1
```

The tests exercise release catch-up, invalid-result rejection, environment separation
and real ASV publication with two commits. Test fixtures are never published as
production measurements. The methodology page handles unavailable or stale
GitHub status explicitly; a successful workflow is not a performance improvement.
