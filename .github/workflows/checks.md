# `checks.yml`

The repository's offline checks: synced copies and every unit test, in one
job. Editing this file triggers nothing; see [README.md](README.md). Until
#22 the workflow was `shared-sync.yml`, named after its first step from
when it held only the sync check and the engine's tests (#9).

## What runs

| Step | Checks |
| --- | --- |
| `python3 shared/sync.py --check` | every copy of a `shared/` file in the image folders matches its source; no stale copies; the manifest is current; each rule's required files exist |
| `shared/sync_test.py` | `sync.py` itself, on scratch repositories |
| `shared/map-quiz/tools/mapgen_test.py` | the map generator core, on synthetic data (stdlib unittest) |
| `shared/map-quiz/tools/wikicheck_test.py` | the Wikipedia title checker's logic, on canned answers (the network is blocked there; the live check is run by hand) |
| `shared/map-quiz/tools/*.test.mjs` | the engine: quiz rules, the config contract, the wheel replay, Wikipedia URLs |
| `images/*/tools/*.test.mjs` | each image's own checks (map data against its config, links, glyph-rain's startup script, sets and simulation) |

## Triggers

Pull requests and pushes to main that touch `shared/**`, `images/**` or
this workflow. Everything runs every time.

## Why everything runs on any change

- **Cost**: one job of about 10 to 20 s, of which the tests take about 5 s
  (measured 2026-11-04: sync steps 0 s, map generator 1 s, title checker
  0 s, all node tests 3 s). GitHub bills it as one minute. Unlike the image
  builds, it doesn't multiply with the number of images.
- **Coupling**: a test imports the files it checks, and in the map images
  those include the synced engine copies (`site/contract.js`, `wiki.js`,
  …) next to the image's own config and data. So a change under `shared/`
  reaches every map image's tests through the sync, and an image's change
  reaches its own.
- **The alternative costs more than it saves**: running only what applies
  would need one workflow per test family with its own paths (a path
  filter action isn't on the Actions allowlist), more to maintain for
  about 5 s saved. The waste that remains, e.g. the generator tests
  running for a glyph-rain change, is trivial.

## Python and Node

- The runner's own `python3` and `node`, no setup actions: no extra
  download, no extra pin to bump. ubuntu-latest checked on 2026-11-01:
  image 20261026, Node 22.23.4, Python 3.12.3.
- **Node is not pinned**, only checked for a minimum: 22.12, the first
  version that runs these tests as written (ES module syntax in `.js`
  files without a `package.json`). Whatever newer Node the runner image
  ships is used. That is acceptable because Node is only the test harness
  here: the shipped JavaScript runs in browsers, so a Node change can at
  worst break a test, visibly, never an image.
- The tests need nothing but the standard library (no npm, no pip).
