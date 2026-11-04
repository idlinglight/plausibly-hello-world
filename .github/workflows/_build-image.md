# `_build-image.yml` and the image callers

Notes for `_build-image.yml` (reusable: verify + publish one image folder)
and for the thin callers `image-<name>.yml` that run it. Editing this file
triggers nothing; see [README.md](README.md) for the convention.

## What it does

- **verify** (always, pull requests included): lints the Dockerfile against
  the contract (CLAUDE.md, "Image contract"), builds both platforms, loads
  amd64 and smoke-tests it with a read-only root: `/healthz`,
  `/version.txt` = the short commit SHA, `/` is HTML, the process runs as
  uid 101. So a base-image bump PR is proven before merge, not first by the
  publish after it.
- **publish** (after verify, never on pull requests): multi-arch push to
  `ghcr.io/<owner>/phw-<image>`, tags `sha-<short7>` and `latest` (only
  while the commit is the default branch's head), unless publish-skip says
  nothing changed (below). The pushed platforms are checked afterwards
  (`PLATFORMS`, nothing else).

## Design

- **BuildKit** runs from the digest pin in `tool-images/buildkit/`, not
  setup-buildx's floating default.
- **No QEMU**: Dockerfiles are COPY-only (the lint rejects `RUN`), so arm64
  builds need no emulation, and a `RUN` fails loudly in the lint instead of
  silently depending on QEMU.
- **Permissions**: a called workflow's `GITHUB_TOKEN` is capped by the
  caller job's `permissions:`; it can narrow them, never widen them. So the
  callers (and `build-image-branch.yml`'s jobs) grant the ceiling
  (`contents: read`, `packages: write`), and verify, which runs the
  Dockerfile and the image, narrows itself to `contents: read`.
- **`latest` never moves backwards.** Serialization alone doesn't order
  runs: an older run whose verify finished later would publish last. So
  publishes of an image and ref run one at a time (concurrency group, no
  cancel), and inside that, `latest` is tagged only if the commit is still
  the default branch's head. Whichever run publishes last, a stale one
  skips `latest`. A queued publish superseded by a newer queued one is
  cancelled, and that commit then has no `sha-` tag (rare).
- **Published name** `ghcr.io/<owner>/phw-<folder>`: flat and prefixed
  because GitHub's package list hides a leading `<repo>/` path part, so the
  earlier nested names (until 2026-10-31) showed as bare folder names. The
  same rule is in `image-scan.yml` (step "Resolve tag"); change both
  together.
- **OCI labels** go on each platform's config and, as annotations, on the
  index: GHCR's package page reads the index annotations for multi-arch
  images.
- **Build records**: `DOCKER_BUILD_RECORD_UPLOAD: false` drops
  build-push-action's per-build artifacts (the job summary already shows
  the build).

## Publish-skip (since #22)

A push to main publishes an image only when its fingerprint changed. The
fingerprint is the sha256 of:

- `git ls-files -s` for `images/<image>/` without `tools/`: path, mode and
  blob per file, so the exec bit and symlinks count;
- `PLATFORMS`;
- the BuildKit pin and the pins of the `docker/*` actions in
  `_build-image.yml` (what builds and publishes the image).

It is stored as the annotation and label `com.github.idlinglight.phw.content`.
A push whose fingerprint equals `latest`'s publishes nothing: no new `sha-`
tag, `latest` stays, the job summary and a notice say so. The skip is
decided before BuildKit starts.

- Comments, a caller, other edits of `_build-image.yml`, an
  `actions/checkout` bump: re-verified, nothing republished.
- A BuildKit or `docker/*` action bump: every image is republished on
  merge, so the publish path (login, metadata, push) runs with the new
  versions right away, not first on some later content change.
- `/version.txt` and the `revision` annotation name the last commit that
  changed the fingerprint. A `latest` without the annotation (published
  before #22), or one that can't be read, counts as different; an
  unreadable one also leaves a warning, so a skip that never happens
  doesn't go unnoticed. A new image's first publish warns too (there is no
  `latest` yet): harmless.
- A dispatch (`build-image-branch.yml`) always publishes; on main that is
  the way to force a republish.

## Callers (`image-<name>.yml`)

- One per image, identical but for the name: verify on pull requests,
  verify + publish on pushes to main.
- **Paths**: the image's folder minus `tools/` (generators, their notes and
  node tests: nothing there is shipped; `checks.yml` runs the tests), the
  caller itself, `_build-image.yml` and the BuildKit pin. So a change to
  how images are built re-verifies every image (PR and main); whether main
  then republishes is publish-skip's call. A negation rather than a list of
  shipped folders, so a new shipped folder triggers by default.
- **No `shared/**` path**: a shared change reaches an image only through its
  synced copies, inside its folder.
- **New image**: copy any caller, replace the name (CLAUDE.md, "Adding an
  image").
- **No push trigger for test tags**: `on.push.paths` on a new branch is
  evaluated against that push's own diff, not against main. Verified on
  2026-10-29 with a throwaway probe workflow: a new branch whose commits are
  all already on GitHub (a re-pushed PR head) has an empty diff, so a
  paths-filtered workflow doesn't run; a branch with new commits is diffed
  against the parent of its oldest new commit. Test tags therefore come
  from `build-image-branch.yml`'s dispatch, which has no paths filter.
