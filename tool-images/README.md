# tool-images

Pin holders: one Dockerfile per image that CI runs from a `run:` step,
never built. A workflow reads the `FROM` line, which must be
digest-pinned (the workflow checks).

**Why Dockerfiles**: Dependabot's github-actions ecosystem only sees
`uses:` lines, so an image referenced from a `run:` step would never be
bumped. As a `FROM` line it gets the same weekly docker-ecosystem PRs as
the image folders, with the cooldown where the registry allows it.

**Why here and not under `.github/`**: Dependabot can't open PRs that
change files under `.github/` for any ecosystem but github-actions
(dependabot-core#15237; it failed that way for the grype bump on
2026-11-04). Moved here in #21.

| Folder | Read by | A bump runs |
| --- | --- | --- |
| `buildkit/` | `_build-image.yml` (the buildx docker-container driver's image; also part of each image's fingerprint) | every caller's paths include it: all images are re-verified on the PR and republished on merge |
| `grype/` (+ `grype.yaml`, mounted read-only) | `image-scan.yml` | `scanner-age` first (release and pinned digest at least 3 days old: Dependabot has no cooldown for ghcr.io), then the scan on the PR, against the published images |

Editing this README triggers nothing (no `paths` match it).

## Grype ignore rules (`grype/grype.yaml`)

Each rule names vulnerability + package + exact installed version, so it
stops matching on its own once the package moves; its `reason` is shown in
every scan summary. Delete a rule once its version is gone from all images
(CLAUDE.md, "Ignore rules").

### CVE-2026-85091 (zlib 1.3.2-r0)

Decided by the repository owner on 2026-10-29.

- **The bug** is in zlib's gzFile API: `gz_vacate()`, reached through
  non-blocking `gzwrite`/`gzprintf`.
- **Why it doesn't apply here**: nginx uses only the deflate/inflate stream
  API, and the nginx 1.30.6 binary doesn't import `gzwrite`, so no request
  path reaches the bug. The only other zlib users in the image are
  apk-tools/libapk, which never run.
- **Fix status**: fixed in Alpine 1.3.2-r1. As of 2026-10-29, upstream
  `nginx-unprivileged:1.30-alpine-slim` hadn't been rebuilt with it (still
  the pinned digest). The rule stops matching once a base bump brings
  1.3.2-r1.
- **Sources**: https://security.alpinelinux.org/vuln/CVE-2026-85091,
  https://www.vulncheck.com/advisories/zlib-1.3.1.2-through-1.3.2-heap-buffer-overflow-via-gz-vacate
