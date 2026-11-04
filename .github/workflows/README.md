# CI notes

The why behind the workflows in this folder, and everything about them that
can change without the workflow files changing: dates, observations,
vendor behaviour, owner settings, other files. The `.yml` files keep only
comments about their own lines. GitHub runs only `.yml`/`.yaml` files here,
and no workflow's `paths` match this file, so editing it triggers nothing.
Contracts and conventions are in [CLAUDE.md](../../CLAUDE.md); the pinned
tool images are described in [tool-images/README.md](../../tool-images/README.md).

| Workflow | Runs on | Does |
| --- | --- | --- |
| `image-<name>.yml` | PRs and pushes to main touching the image (paths below) | `_build-image.yml` for that image: verify, and on main also publish |
| `build-image-branch.yml` | dispatch only | `_build-image.yml` for one image or all, at any ref: test tags |
| `_build-image.yml` | called | lint, build, smoke test (verify); push (publish) |
| `_discover-images.yml` | called | the image folders as a JSON list |
| `image-scan.yml` | Fridays 19:30 Vienna; dispatch; PRs touching it or the scanner pin | CVE scan of every published image |
| `shared-sync.yml` | PRs and pushes to main touching `shared/` or `images/` | synced copies match `shared/`; offline tests |

## Image builds (`_build-image.yml`)

- **Verify runs on every trigger, pull requests included.** It lints the
  Dockerfile against the contract, builds both platforms, loads amd64 and
  smoke-tests it with a read-only root. So a base-image bump PR is proven
  before merge, not first by the publish after it.
- **BuildKit** runs from the digest pin in `tool-images/buildkit/`, not
  setup-buildx's floating default. **No QEMU**: Dockerfiles are COPY-only
  (the lint rejects `RUN`), so arm64 builds need no emulation, and a `RUN`
  fails loudly in the lint instead of silently depending on QEMU.
- **Permissions**: a called workflow's `GITHUB_TOKEN` is capped by the
  caller job's `permissions:`; it can narrow them, never widen them. So the
  callers (and `build-image-branch.yml`'s jobs) grant the ceiling
  (`contents: read`, `packages: write`), and verify, which runs the
  Dockerfile and the image, narrows itself to `contents: read`.
- **`:latest` never moves backwards.** Serialization alone doesn't order
  runs: an older run whose verify finished later would publish last. So
  publishes of an image and ref run one at a time (concurrency group, no
  cancel), and inside that, `latest` is tagged only if the commit is still
  the default branch's head. Whichever run publishes last, a stale one
  skips `latest`. A queued publish superseded by a newer queued one is
  cancelled, and that commit then has no `sha-` tag (rare).
- **Published name** `ghcr.io/<owner>/phw-<folder>`: flat and prefixed
  because GitHub's package list hides a leading `<repo>/` path part, so the
  earlier nested names showed as bare folder names. The same rule is in
  `image-scan.yml` (step "Resolve tag"); change both together.
- **OCI labels** go on each platform's config and, as annotations, on the
  index: GHCR's package page reads the index annotations for multi-arch
  images.
- The pushed platforms are checked after the push (`PLATFORMS`, nothing
  else).
- **Publish-skip** (since #22): a push to main publishes an image only when
  its fingerprint changed: the sha256 of `git ls-files -s` for
  `images/<image>/` without `tools/` (path, mode and blob per file, so the
  exec bit and symlinks count), `PLATFORMS`, the BuildKit pin and the pins
  of the `docker/*` actions in `_build-image.yml`. It is stored as the
  annotation and label `com.github.idlinglight.phw.content`, and a push
  whose fingerprint equals `latest`'s publishes nothing: no new `sha-` tag,
  `latest` stays, the job summary says so (the skip is decided before
  BuildKit starts).
  - Comments, a caller, other edits of `_build-image.yml`, an
    `actions/checkout` bump: re-verified, nothing republished.
  - A BuildKit or `docker/*` action bump: every image is republished on
    merge, so the publish path (login, metadata, push) runs with the new
    versions right away, not first on some later content change.
  - `/version.txt` and the `revision` annotation name the last commit that
    changed the fingerprint. A `latest` without the annotation (published
    before #22), or one that can't be read, counts as different.
  - To republish anyway: dispatch on main (below). A dispatch always
    publishes.

## Callers (`image-<name>.yml`)

- **Paths**: the image's folder minus `tools/` (generators, their notes and
  node tests: nothing there is shipped; shared-sync runs the tests), the
  caller itself, `_build-image.yml` and the BuildKit pin. So a change to how
  images are built re-verifies every image (PR and main); whether main then
  republishes is the fingerprint's call (publish-skip, above). A negation
  rather than a list of shipped folders, so a new shipped folder triggers
  by default.
- **No `shared/**` path**: a shared change reaches an image only through its
  synced copies, inside its folder.
- **New image**: copy any caller, replace the name (CLAUDE.md, "Adding an
  image").
- **Why test tags come from a dispatch, not from pushes**: `on.push.paths`
  on a new branch is evaluated against that push's own diff, not against
  main. Verified on 2026-10-29 with a throwaway probe workflow: a new branch
  whose commits are all already on GitHub (a re-pushed PR head) has an
  empty diff, so a paths-filtered workflow doesn't run; a branch with new
  commits is diffed against the parent of its oldest new commit. A dispatch
  has no paths filter.

## On-demand builds (`build-image-branch.yml`)

```sh
gh workflow run build-image-branch.yml --ref <branch> -f image=<name>   # one image
gh workflow run build-image-branch.yml --ref <branch> -f image=all      # every image
```

- Verifies and publishes `sha-<short7>` at that ref: a PR head, a
  Dependabot branch, a new image whose caller isn't on main yet. One image
  needs no discovery; a bad name fails `_build-image.yml`'s lint step
  before anything is built. `all` is reserved: `_discover-images.yml`
  rejects a folder of that name.
- GitHub offers a dispatch only for workflows on the default branch, but
  the run uses the workflow files **at `--ref`**, so changes to the build
  itself are exercised too. A ref without this workflow's dispatch fails
  with 422 ("does not have workflow_dispatch trigger"): rebase the branch,
  or `@dependabot rebase` a Dependabot PR.
- **On main only to force a republish** (a push to main skips an image
  whose shipped files didn't change; a dispatch never skips): there the
  publish also moves `latest` and queues in the same concurrency groups as
  main's own publishes.
- Before 2026-11-04 (#19, #21) test tags came from pushing to
  `build-image/<topic>`, which built and published every image (about 19
  jobs); the per-image callers had their own dispatch too.

## Scan (`image-scan.yml`)

- **Why**: base images never get Dependabot alerts (they're not in the
  dependency graph). The weekly scan closes that gap: every image's `:latest`,
  one matrix job each, failing on **fixable** HIGH/CRITICAL. A failed
  scheduled run notifies the repository owner, as their notification
  settings say: that is the alert (CLAUDE.md, "Who hears about a failed
  scheduled scan").
- **Schedule**: Fridays 19:30 Europe/Vienna (`timezone` on `schedule`, per
  GitHub's docs as of 2026-10-29; DST-safe). That is 30 min after
  Dependabot's weekly run (19:00), so a fix-carrying bump PR is usually
  already open when the scan reports.
- **When it fails**: merge the pending Dependabot digest bump, else bump
  the digest by hand. If the summary says the upstream tag still points at
  the pinned digest, the fix waits on nginxinc rebuilding: a digest bump
  can't help yet, and `RUN apk upgrade` isn't allowed (COPY-only). Accepted
  risks become narrow, reasoned ignore rules (`tool-images/grype/grype.yaml`,
  analysis in `tool-images/README.md`); every ignored match is listed in
  the summary with its reason.
- **Scanner choice**: Grype as a digest-pinned container from a plain
  `docker run`, not trivy-action / setup-trivy and not anchore/scan-action.
  In March 2026, aquasecurity's release credentials were stolen (again,
  after an incomplete rotation): 76 of 77 trivy-action tags and all
  setup-trivy tags were force-pushed to an infostealer, plus malicious
  trivy v0.69.4 binaries and images and Docker Hub 0.69.5/0.69.6
  (GHSA-69fq-xp46-6x23, CVE-2026-33634). Only SHA and digest pins were
  safe. Scanner actions aren't on the repository's Actions allowlist
  anyway. Grype/Anchore: no known incident as of 2026-10-29.
- **Isolation**: the only action in the scan job is `actions/checkout`. The
  image is pulled on the host and handed to the scanner as a read-only
  tarball; the scanner container gets its config (read-only), a DB cache
  folder and network for the DB download: no credentials, no docker
  socket, no workspace.
- **Only linux/amd64** is scanned: arm64 is built from the same base index
  digest, i.e. the same Alpine package set.
- **Permissions and pulls**: the scan jobs are read-only. The phw-*
  packages are public. Were one private,
  `packages: read` would still do: packages this repository's workflows
  publish are linked to it (OCI source label) and grant it read access.
  Observed 2026-10-29: for a package that doesn't exist yet, GHCR still
  issues a pull token and answers the manifest with 404 `MANIFEST_UNKNOWN`.
  So the job treats a refused token as an access problem and fails, and a
  404 as "not published yet": a warning, and the job passes.
- **On a PR** (this file, the scanner pin, its rules): it scans `:latest`,
  falling back to `sha-<PR head short7>` (make one with the dispatch
  above), so a scanner bump is tested against the real images before
  merge.
- **`scanner-age`** (PRs touching the scan or the scanner pin): the pinned
  grype must be at least 3 days old, both its GitHub release and the
  pinned digest's build (the linux/amd64 config's `created`), so a
  re-pushed old tag is held too. The scan matrix waits for it, so a
  scanner too new to pin never runs. Dependabot's cooldown can't see
  release dates on ghcr.io ("No verified registry publication date source
  for ghcr.io; skipping cooldown", observed 2026-11-04), so this check
  enforces the repository's rule for the scanner. It says when to re-run.
  Only grype is checked: the one pin on ghcr.io; the docker.io pins have
  Dependabot's cooldown.

## Sync and tests (`shared-sync.yml`)

- `python3 shared/sync.py --check`: copies, stale copies, the manifest, each
  rule's required files. Then `sync.py` itself on scratch repositories, the
  map generator core on synthetic data (`mapgen_test.py`), the Wikipedia
  title checker's offline logic on canned answers (`wikicheck_test.py`;
  the network is blocked there, the live check is run by hand), and the
  node tests: `shared/map-quiz/tools/*.test.mjs` (quiz rules, config
  contract, wheel replay) and `images/*/tools/*.test.mjs` (each image's own
  checks).
- Only the runner's own python3 and node, no setup actions. ubuntu-latest
  checked 2026-11-01: image 20261026, Node 22.23.4, Python 3.12.3. The node
  tests need Node 22.12+ (ES modules in `.js` files without a
  `package.json`); the step says so if a runner image ever has less.

## Dependabot (`../dependabot.yml`)

- The file's presence on main turns version updates on; no settings toggle
  is involved. Editing it starts an off-schedule run of every ecosystem.
- **Deliberately off** (repository settings, verified 2026-10-29):
  Dependabot **alerts** (here they could only ever fire for the pinned
  actions: no package manifests) and **security-update PRs** (they ignore
  the cooldown and bump straight to the newest version, which
  systematically breaks the 3-day rule).
- **Cooldown** is supported for github-actions (default-days only, no
  semver-*-days; GitHub's docs re-checked 2026-10-29). For docker it works
  where the registry gives publication dates: docker.io yes, ghcr.io no
  (see `scanner-age` above).
- **`.github/` is out of reach** for every ecosystem but github-actions:
  creating a PR that changes files under `.github/` fails with 400 "The
  request contains invalid or unauthorized changes"
  ([dependabot-core#15237](https://github.com/dependabot/dependabot-core/issues/15237);
  first seen here 2026-11-04 with the grype bump). The web UI calls it
  "Dependabot can't update vulnerable dependencies without a pinned
  version", which says nothing about the cause. That's why the tool-image
  pins live in `tool-images/` at the root.
- **Reviewing bump PRs**:
  - `images/*` base digests: the image's PR run builds both platforms and
    smoke-tests the contract before merge; green means the new base works.
    The merge publishes `sha-<short7>` and `latest`.
  - `tool-images/buildkit`: in every caller's paths and in the
    fingerprint, so every image is re-verified on the PR and republished on
    merge.
  - `tool-images/grype`: runs the scan on the PR (and `scanner-age`).
  - github-actions: the repository's Actions allowlist is `actions/*` plus
    five `docker/*` actions (owner setting, SHA pinning enforced), so a bump
    can't bring in anything else. Bumps in `_build-image.yml` re-verify
    every image on the PR, but `docker/login-action` and
    `docker/metadata-action` only run in publish: prove them before merge
    by publishing one image from the PR's branch:
    `gh workflow run build-image-branch.yml --ref <branch> -f image=snake`.
    The merge then republishes every image (the `docker/*` pins are in the
    fingerprint); an `actions/checkout` bump republishes none.
