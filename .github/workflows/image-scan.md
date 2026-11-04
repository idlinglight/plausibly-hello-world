# `image-scan.yml`

CVE scan of every published image. Editing this file triggers nothing; see
[README.md](README.md).

## What and when

- **Why**: base images never get Dependabot alerts (they're not in the
  dependency graph). The scan closes that gap: every image's `:latest`, one
  matrix job each, failing on **fixable** HIGH/CRITICAL findings and
  listing ignored ones with their rule's reason. A failed scheduled run
  notifies the repository owner, as their notification settings say: that
  is the alert (CLAUDE.md, "Who hears about a failed scheduled scan").
- **Schedule**: Fridays 19:30 Europe/Vienna (`timezone` on `schedule`, per
  GitHub's docs as of 2026-10-29; DST-safe). That is 30 min after
  Dependabot's weekly run (19:00), so a fix-carrying bump PR is usually
  already open when the scan reports.
- **Dispatch**: `-f tag=<tag>` scans that tag of every image (default
  `latest`).
- **On a PR** (this file, the scanner pin, its rules): `scanner-age` first,
  then the scan of `:latest`, falling back to `sha-<PR head short7>` (make
  one with `build-image-branch.yml`), so a scanner bump is tested against
  the real images before merge.
- **Not published yet** (a new folder, before its first main build): that
  image's job warns and passes.

## When it fails

Merge the pending Dependabot digest bump, else bump the digest by hand. If
the summary says the upstream tag still points at the pinned digest, the
fix waits on nginxinc rebuilding: a digest bump can't help yet, and `RUN apk
upgrade` isn't allowed (COPY-only). Accepted risks become narrow, reasoned
ignore rules (`tool-images/grype/grype.yaml`, analysis in
`tool-images/README.md`); every ignored match is listed in the summary with
its reason.

## Scanner choice and isolation

- **Grype** as a digest-pinned container from a plain `docker run`, not
  trivy-action / setup-trivy and not anchore/scan-action. In March 2026,
  aquasecurity's release credentials were stolen (again, after an
  incomplete rotation): 76 of 77 trivy-action tags and all setup-trivy tags
  were force-pushed to an infostealer, plus malicious trivy v0.69.4
  binaries and images and Docker Hub 0.69.5/0.69.6 (GHSA-69fq-xp46-6x23,
  CVE-2026-33634). Only SHA and digest pins were safe. Scanner actions
  aren't on the repository's Actions allowlist anyway. Grype/Anchore: no
  known incident as of 2026-10-29.
- **Isolation**: the only action in the scan job is `actions/checkout`. The
  image is pulled on the host and handed to the scanner as a read-only
  tarball; the scanner container gets its config (read-only), a DB cache
  folder and network for the DB download: no credentials, no docker
  socket, no workspace.
- **Only linux/amd64** is scanned: arm64 is built from the same base index
  digest, i.e. the same Alpine package set. The amd64 manifest (not the
  index) is pulled, so `docker save` works with the classic and the
  containerd image store.

## Permissions and pulls

The scan jobs are read-only. The phw-* packages are public. Were one
private, `packages: read` would still do: packages this repository's
workflows publish are linked to it (OCI source label) and grant it read
access. Observed 2026-10-29: for a package that doesn't exist yet, GHCR
still issues a pull token and answers the manifest with 404
`MANIFEST_UNKNOWN`. So the job treats a refused token as an access problem
and fails, and a 404 as "not published yet": a warning, and the job passes.

## `scanner-age`

On PRs touching the scan or the scanner pin, the pinned grype must be at
least 3 days old: both its GitHub release and the pinned digest's build
(the linux/amd64 config's `created`), so a re-pushed old tag is held too.
The scan matrix waits for it, so a scanner too new to pin never runs. It
says when to re-run.

Why a check of its own: Dependabot's cooldown can't see release dates on
ghcr.io ("No verified registry publication date source for ghcr.io;
skipping cooldown", observed 2026-11-04). Only grype is checked: the one
pin on ghcr.io; the docker.io pins have Dependabot's cooldown. Generalize
when a second ghcr.io pin appears.

The job is isolated: it runs only on PRs that change the scan or the
scanner pin, and checks the pin on that PR's branch, so other PRs never
wait on it (main's pin passed when it was merged).
