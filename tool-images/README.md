# tool-images

Pin holders: one Dockerfile per image that CI runs from a `run:` step,
never built. A workflow reads the `FROM` line, which must be
digest-pinned (the workflow checks).

**Why Dockerfiles**: Dependabot's github-actions ecosystem only sees
`uses:` lines, so an image referenced from a `run:` step would never be
bumped. As a `FROM` line it gets weekly docker-ecosystem PRs, as the
image folders get theirs, with the cooldown where the registry allows it.

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

### CVE-2026-4738 (zlib 1.3.2-r1)

Decided by the repository owner on 2026-11-13.

- **The bug** is out-of-bounds pointer arithmetic in zlib's
  `contrib/infback9` (`inftree9.c`), a decoder for Deflate64. The CVE was
  filed in March 2026 against the copy GDAL bundles (CVSS 4.0 9.4 from the
  reporting CNA; NVD hadn't analysed it as of 2026-11-13). zlib 1.4
  (2026-11-04) lists its fix under this id.
- **Why it doesn't apply here**: `contrib/` isn't part of libz. Alpine
  builds zlib with plain `./configure` and `make`, and the image's
  `libz.so.1.3.2` has no infback9 code (no such string in the file; checked
  in `phw-snake:sha-7700cd6`). The nginx binary imports only `deflate`,
  `deflateEnd`, `deflateInit2_`, `inflate`, `inflateEnd`, `inflateInit2_`
  and `inflateReset`. zlib 1.4's other memory fixes, which have no CVE id,
  are in functions nginx doesn't call (`inflateSync`, `inflatePrime`,
  `deflatePrime`, `inflateGetDictionary`, `inflateBack`,
  `deflateResetKeep`, the `gz*` file functions). The only other zlib users
  in the image are apk-tools/libapk, which never run.
- **Fix status**: fixed in Alpine 1.4-r0, in the 3.24 repository since
  2026-11-06. As of 2026-11-13, no base image had it: upstream's newest
  `nginx/nginx-unprivileged:1.30-alpine-slim` (built 2026-11-12, Alpine
  3.24.4) still shipped 1.3.2-r1, and so did `alpine:3.24`
  (`.github/workflows/image-scan.md`, "When it fails"). The rule stops
  matching once a base bump brings 1.4-r0.
- **Sources**: https://security.alpinelinux.org/vuln/CVE-2026-4738,
  https://www.cve.org/CVERecord?id=CVE-2026-4738,
  https://github.com/OSGeo/gdal/pull/12244,
  https://github.com/madler/zlib/blob/develop/ChangeLog ("Changes in 1.4")

### OpenSSL advisory of 2026-11-10 (libcrypto3, libssl3 3.5.9-r0)

Four CVEs, each with a rule for `libcrypto3` and one for `libssl3` (one
source package, two findings). Decided by the repository owner on
2026-11-20.

- **Severity**: OpenSSL rates all four Low; the scan's High comes from
  the vulnerability database's score.
- **The bugs and why they don't apply here** (imports read with `nm -D`
  from the nginx binary of `phw-snake:sha-5dcdddd`):
  - **CVE-2026-107496**: `CMS_encrypt()` / `CMS_encrypt_ex()` loop
    forever on a recipient certificate whose EC group order is 1. nginx
    imports no `CMS_*` function.
  - **CVE-2026-88823**, **CVE-2026-95692**: AES-GCM-SIV only (a
    zero-length AAD update drops the AAD before it; a wrong IV length is
    read out of bounds or truncated). nginx imports the CBC, CTR, CCM and
    GCM forms of AES (`EVP_aes_*`) and no cipher fetch by name; TLS has
    no AES-GCM-SIV cipher suite.
  - **CVE-2026-95691**: a use-after-free read in OpenSSL's own QUIC
    stack, in the client, on retransmitted CRYPTO frames from a malicious
    server. nginx is a server with its own QUIC implementation; from
    OpenSSL's QUIC side it imports only the TLS callbacks for third-party
    stacks (`SSL_set_quic_tls_*`).
- **Beyond the imports**: the image's configuration has one plain
  `listen 8080` and no TLS, QUIC, proxying, mail or stream, so nginx
  never starts a TLS handshake. The other files linked against OpenSSL
  are `ssl_client` (busybox wget's helper) and `libapk`: neither imports
  CMS, SIV or QUIC functions, and neither runs (the base image's
  `10-listen-on-ipv6-by-default.sh` would call `apk manifest`, but stops
  before it: uid 101 can't write the config; seen in the start log with
  and without a read-only root).
- **Not ignored**: CVE-2026-88822 (Medium in the scan, the same
  advisory, also only OpenSSL's QUIC stack) doesn't fail the scan and
  stays listed.
- **Fix status**: fixed in Alpine 3.5.9-r1, in the 3.24 repository since
  2026-11-18T23:31Z, seven hours after the build of the base we pin. As of
  2026-11-20 no base image had it: `alpine:3.24` (3.24.4, pushed
  2026-11-08) still shipped 3.5.9-r0. The nginx image takes its packages
  as the Alpine image has them (its 2026-11-18 build still has zlib
  1.3.2-r1, with 1.4-r0 in the repository since 2026-11-06), so the fix
  most likely waits for a new `alpine:3.24` image, not just upstream's
  next weekly build. The rules stop matching once a base bump brings
  3.5.9-r1.
- **Sources**: https://openssl-library.org/news/secadv/20261110.txt,
  the CVE records on https://www.cve.org,
  https://security.alpinelinux.org/vuln/CVE-2026-107496 (and the other
  three ids).

### Past rules

Past rules and their analyses are in
this file's git history. The last one, CVE-2026-85091 (zlib 1.3.2-r0,
decided on 2026-10-29), was removed on 2026-11-07. The base image had
moved to `nginx/nginx-unprivileged` and brought 1.3.2-r1. The fix was most
likely available under that name before the rule was written: upstream's
2026-10-26 build would have been on Alpine 3.24.3, which shipped 1.3.2-r1.
That build couldn't be inspected any more. The `nginxinc/` name we pinned
was no longer updated (`.github/workflows/image-scan.md`, "Base age").
