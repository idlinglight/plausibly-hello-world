# `image-scan.yml`

CVE scan of every published image. Editing this file triggers nothing; see
[README.md](README.md).

## What and when

- **Why**: base images never get Dependabot alerts (they're not in the
  dependency graph). The scan closes that gap: every image's `:latest`, in
  one job, failing on **fixable** HIGH/CRITICAL findings and listing
  ignored ones with their rule's reason. A failed scheduled run
  notifies the repository owner, as their notification settings say: that
  is the alert (CLAUDE.md, "Who hears about a failed scheduled scan").
- **Schedule**: Fridays 19:30 Europe/Vienna (`timezone` on `schedule`, per
  GitHub's docs as of 2026-10-29; DST-safe). That is after Dependabot's
  runs of that day (base images on weekdays at 16:05, the rest Fridays
  19:00; `.github/dependabot.md`), so a fix-carrying bump PR is usually
  already open when the scan reports.
- **Dispatch**: `-f tag=<tag>` scans that tag of every image (default
  `latest`).
- **On a PR** (this file, the scanner pin, its rules): `scanner-age` first,
  then the scan of `:latest`, falling back to `sha-<PR head short7>` (make
  one with `build-image-branch.yml`), so a scanner bump is tested against
  the real images before merge.
- **Not published yet** (a new folder, before its first main build): a
  warning, and the image is listed as skipped; the scan passes.
- **One job, not one per image** (since 2026-11-13): one runner, one
  scanner pull and one DB download instead of one each per image, so every
  image is matched against the same DB. Every image is still scanned: they
  can differ, as each is published on its own. The summary lists a finding
  once, with the images that have it, and the run fails once. An image
  that can't be resolved (a refused token, an unexpected registry answer),
  pulled or scanned doesn't stop the others: it is listed as not scanned
  and fails the run in the report, which also runs after a failed pull or
  scan step. Before, a
  finding in the shared base failed one job per image, and stopping at the
  first failure would have saved nothing: the jobs started together.

## When it fails

Merge the pending Dependabot digest bump, else bump the digest by hand. If
the summary says the upstream tag still points at the pinned digest, the
fix waits on upstream rebuilding: a digest bump can't help yet, and `RUN apk
upgrade` isn't allowed (COPY-only). The hint gives that build's date and
age. If it adds "No upstream build for over N days", see "Base age" below
before waiting. Accepted risks become narrow, reasoned
ignore rules (`tool-images/grype/grype.yaml`, analysis in
`tool-images/README.md`); every ignored match is listed in the summary with
its reason.

A newer upstream digest doesn't have to carry the fix. "Fixable" means
Alpine's package repository has a fixed version. The nginx image has the
packages of the `alpine` image it was built on (observed 2026-11-13), so
the fix reaches it only after Alpine publishes a new image and nginx
rebuilds on that. Seen on 2026-11-13 with zlib 1.4-r0: in Alpine 3.24's
repository since 2026-11-06, in neither upstream's 2026-11-12 build nor
`alpine:3.24`. It was answered with an ignore rule, as the finding didn't
apply.

So when the gate fails and a base tag has a newer digest upstream than the
Dockerfiles pin, the scan pulls that digest (linux/amd64) and scans it
too, with the same rules. The hint then says whether that base would pass
the gate: it has no fixable HIGH/CRITICAL finding (merge the bump), still
has all of the images' ones (a bump wouldn't help), or has some of them or
others of its own (a bump alone wouldn't pass the scan). Findings are
compared by vulnerability and package, not by version: a newer package
revision that is still vulnerable counts as still there. If that base can't be
pulled or scanned, the hint says it wasn't scanned: check by hand before
bumping, `docker run --rm --entrypoint apk <base>@<digest> info -v` lists
its packages. Without a failing gate the newer digest isn't looked at.

## Base age (`base-age`)

On every run, this job reads the base tags from `images/*/Dockerfile`. For
each tag, it looks up the digest the tag points to upstream now and that
build's date (the linux/amd64 config's `created`). It shows them in a
summary table (one row per tag: how many images pin it, and how many of
those are on the current digest). It passes the result to the scan for
its base hint. A build older than `BASE_STALE_DAYS` (14) is a
warning, both here and in the scan's hint. So is a tag that doesn't
resolve. The job never fails the run, and the scan runs whatever its
result. Without the lookup, the hint says "could not resolve".

**Why**: a base can stop getting updates without anything breaking.
Upstream (GitHub `nginx/docker-nginx-unprivileged`) moved its Docker Hub
images from `nginxinc/nginx-unprivileged` to `nginx/nginx-unprivileged` on
2026-10-20, and Docker Hub shows the old name as archived (last push
2026-10-19). The tag we pinned never moved again: Dependabot found nothing
to bump, and the scan's hint kept saying "still the pinned digest", i.e.
"wait". That happened on 2026-10-29 (zlib, answered with an ignore rule
although the fix was most likely already available under the new name) and
on 2026-11-06 (musl). We switched on 2026-11-07 (#26).

**Why 14 days**: upstream rebuilt its images every Monday at 00:00 UTC as
of 2026-11. At the Friday scan, a current tag is about 4 days old, 11 after
one missed build, and 18 after two. 14 tolerates one missed build. With
this check, the archived tag would have been flagged at the 2026-11-06 scan
(18 days), not yet at 2026-10-30 (11).

**On the warning**: look at where upstream's workflows push now (the image
names in its build workflows) and at the repository's status on Docker Hub.
If upstream moved, switch the name: the Dockerfiles, the base lint in
`_build-image.yml`, `dependabot.yml` and CLAUDE.md ("Base"), as in #26. If
upstream only paused (failed builds, a release in progress), wait and keep
an eye on the scan.

**Docker Hub requests**: two manifest requests per base tag per run,
anonymous. The scan pulls from Docker Hub only for the newer-base check
("When it fails"): one anonymous pull per base tag, in runs whose gate
fails.

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
- **Isolation**: the only action in the scan job is `actions/checkout`.
  The scanner runs in containers without credentials, the docker socket
  or the workspace. One downloads the DB (`grype db update`): it has
  network and the DB cache folder, and sees no image. Then one container
  per image scans it: the image is pulled on the host and handed over as
  a read-only tarball, with the config (read-only) and that DB, and
  without network (`--network none`; the scans don't update the DB).
- **Only linux/amd64** is scanned: arm64 is built from the same base index
  digest, i.e. the same Alpine package set. The amd64 manifest (not the
  index) is pulled, so `docker save` works with the classic and the
  containerd image store.

## Permissions and pulls

The scan job is read-only. The phw-* packages are public. Were one
private, `packages: read` would still do: packages this repository's
workflows publish are linked to it (OCI source label) and grant it read
access. Observed 2026-10-29: for a package that doesn't exist yet, GHCR
still issues a pull token and answers the manifest with 404
`MANIFEST_UNKNOWN`. So the job treats a refused token as an access problem
(the run fails), and a 404 as "not published yet": a warning, and the image
is skipped.

## `scanner-age`

On PRs touching the scan or the scanner pin, the pinned grype must be at
least 3 days old: both its GitHub release and the pinned digest's build
(the linux/amd64 config's `created`), so a re-pushed old tag is held too.
The scan waits for it, so a scanner too new to pin never runs. It
says when to re-run.

Why a check of its own: Dependabot's cooldown can't see release dates on
ghcr.io ("No verified registry publication date source for ghcr.io;
skipping cooldown", observed 2026-11-04). Only grype is checked: the one
pin on ghcr.io; the docker.io pins have Dependabot's cooldown. Generalize
when a second ghcr.io pin appears.

The job is isolated: it runs only on PRs that change the scan or the
scanner pin, and checks the pin on that PR's branch, so other PRs never
wait on it (main's pin passed when it was merged).
