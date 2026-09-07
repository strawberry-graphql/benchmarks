# Strawberry performance reporting

Current workloads live in
[strawberry/tests/benchmarks](https://github.com/strawberry-graphql/strawberry/tree/main/tests/benchmarks).
This repository owns the public entry point and native measurement workflow.

## Public site

`html/index.html` is the public overview for `speed.strawberry.rocks`. It links to
CPU, native and memory results and reads public GitHub Actions status on load.
Unsuccessful runs, unavailable status, missing successful runs and stale results are shown
explicitly. Dates describe workflow completion, not an inferred speedup. The
native workflow's GitHub commit belongs to this reporting repository; the actual
Strawberry revision is recorded in each measurement artifact.

The obsolete ASV harness, stored runs, generated charts and vendored assets are
removed. Their earlier versions are available in Git history. The public site only
links current measurement sources.

To preview locally:

```sh
python3 -m http.server 8765 --directory html --bind 127.0.0.1
```

Opening the page does not require credentials. If GitHub's public API is
unavailable or rate-limited, the workflow links still work. A successful workflow
is not a claim that performance improved.

## Native measurements

`.github/workflows/asv.yml` (named **Native benchmarks** in Actions) runs only scheduled or maintainer-dispatched code,
on the existing `self-hosted, macOS, ARM64` runner. It checks out Strawberry's main
branch (or an explicitly requested trusted ref), installs its locked environment,
and runs pytest-codspeed in native walltime mode. No new hosting service is needed.
Do not add pull-request triggers to this persistent runner.

The job uses Python 3.14.7, the [latest stable release](https://www.python.org/getit/source/)
as of September 7, 2026, matching the CPU and memory jobs. The exact version is
pinned for reproducibility; Python upgrades start a new baseline. A global
concurrency group serializes runs with a 45-minute job timeout.
Daily runs exclude stress sizes; Sunday/manual stress runs
include them. Within each job, benchmarks run in one process without xdist.
Use an otherwise idle runner and compare matching environment/workload identities.

Artifacts retained for 90 days include native CodSpeed JSON, measurement metadata,
JUnit correctness results, and HTTP response byte counts. Download the artifacts
from the workflow run. These native measurements are advisory; no threshold or
cross-machine comparison is enforced. CPU and memory measurements stay in the
main repository's CodSpeed integration.

## Rollout order

Merge the main repository's benchmark modernization first: the native workflow
requires `tests/benchmarks/metadata.py` and the version-2 workload markers. Before
merging this reporting change, dispatch the native workflow against that merged
revision (or the trusted implementation branch) and verify the job and its
artifacts. Verify the site's overview and measurement links using the existing
static-site deployment pipeline; this change does not change DNS or hosting.

The existing workflow filename, `asv.yml`, is retained so maintainers can dispatch
this branch before merging it. Its new implementation replaces the failing ASV
build/publish cycle with native measurements. The old schedule stays on main
until this reporting change is merged. After merge no ASV publish step can
regenerate the removed results or overwrite the overview.

Run the status checks with `node tests/test_site.cjs`. These use a
small DOM stub and do not replace a visual browser review.
