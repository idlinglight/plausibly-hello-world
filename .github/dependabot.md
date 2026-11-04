# `dependabot.yml`

Notes for the Dependabot configuration beside this file. Editing this file
triggers nothing: Dependabot only reacts to `dependabot.yml`. Policy:
CLAUDE.md, "Supply-chain policy". Workflow notes:
[workflows/README.md](workflows/README.md).

- **Switch**: the file's presence on main turns version updates on; no
  settings toggle is involved. Editing it starts an off-schedule run of
  every ecosystem.
- **Deliberately off** (repository settings, verified 2026-10-29):
  Dependabot **alerts** (here they could only ever fire for the pinned
  actions: no package manifests) and **security-update PRs** (they ignore
  the cooldown and bump straight to the newest version, which
  systematically breaks the 3-day rule). Base images never get alerts at
  all; the weekly scan covers that (`workflows/image-scan.md`).
- **Cooldown** is supported for github-actions (default-days only, no
  semver-*-days; GitHub's docs re-checked 2026-10-29). For docker it works
  where the registry gives publication dates: docker.io yes, ghcr.io no
  (the grype pin; `scanner-age` in `workflows/image-scan.md`).
- **One PR per dependency**: the docker updates are grouped by dependency
  name, so a base-digest bump for every image folder arrives as one PR,
  while nginx, BuildKit and grype stay separate PRs. github-actions has no
  groups: one PR per action.
- **`.github/` is out of reach** for every ecosystem but github-actions:
  creating a PR that changes files under `.github/` fails with 400 "The
  request contains invalid or unauthorized changes"
  ([dependabot-core#15237](https://github.com/dependabot/dependabot-core/issues/15237);
  first seen here 2026-11-04 with the grype bump). The web UI calls it
  "Dependabot can't update vulnerable dependencies without a pinned
  version", which says nothing about the cause. That's why the tool-image
  pins live in `tool-images/` at the root.

## Reviewing bump PRs

- **`images/*` base digests**: the image's PR run builds both platforms and
  smoke-tests the contract before merge; green means the new base works.
  The merge publishes `sha-<short7>` and `latest`.
- **`tool-images/buildkit`**: in every caller's paths and in the
  fingerprint, so every image is re-verified on the PR and republished on
  merge.
- **`tool-images/grype`**: runs `scanner-age`, then the scan on the PR.
- **github-actions**: the repository's Actions allowlist is `actions/*` plus
  five `docker/*` actions (owner setting, SHA pinning enforced), so a bump
  can't bring in anything else. Bumps in `_build-image.yml` re-verify
  every image on the PR, but `docker/login-action` and
  `docker/metadata-action` only run in publish: prove them before merge by
  publishing one image from the PR's branch:
  `gh workflow run build-image-branch.yml --ref <branch> -f image=snake`.
  The merge then republishes every image (the `docker/*` pins are in the
  fingerprint); an `actions/checkout` bump republishes none.
