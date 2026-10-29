# plausibly-hello-world

Container images without much content, used as deploy dummies for practicing
cloud deployments — but nice enough to look at to keep deployed for a while.
Not bound to one idea: each image is a self-contained folder under `images/`.

## Layout

```
images/<name>/        one folder = one image, build context = this folder
  Dockerfile
  nginx.conf          → /etc/nginx/conf.d/default.conf
  site/               → /usr/share/nginx/html/ (static files, no build step)
.github/
  dependabot.yml
  workflows/
    _build-image.yml        reusable: contract lint, verify, publish
    _discover-images.yml    reusable: lists images/*/ (shared name rule)
    image-<name>.yml        thin caller per image (paths-filtered)
    build-image-branch.yml  build-image/** fan-out, all images, no paths filter
    image-scan.yml          weekly CVE scan of every :latest
  tool-images/        pin holders for images used from run: steps — never
    buildkit/           built; they exist so Dependabot bumps the pins
    grype/              (+ grype.yaml: scan ignore rules)
```

## Image contract

Every image under `images/` must satisfy this — CI lints and smoke-tests it,
and deployments can rely on it without per-image knowledge:

- **Base**: `nginxinc/nginx-unprivileged:<stable>-alpine-slim`, digest-pinned
  (`tag@sha256:<index digest>`). Stable channel only (even minor, e.g. 1.30).
- **Runtime**: uid **101** (non-root), listens on **8080** (IPv4), works with a
  read-only root filesystem plus a writable `/tmp` (`docker run --read-only
  --tmpfs /tmp`; k8s: `readOnlyRootFilesystem` + an emptyDir on `/tmp`).
- **Endpoints**: `GET /healthz` → `200 ok` (probe target), `GET /version.txt`
  → the short commit SHA (build arg `GIT_SHA`, default `dev`), `GET /` → the page.
- **Dockerfile**: single stage, COPY-only from the build context — CI rejects
  `RUN` (multi-arch would need QEMU), `ADD`, `ONBUILD`, `COPY --from` and an
  unpinned `# syntax=` (both would pull a second, unpinned image). Static
  files ship as-is — no npm, no bundler, so there's no JS dependency tree.
- **Published as** `ghcr.io/idlinglight/plausibly-hello-world/<name>` (public),
  tags `sha-<short7>` (every build) and `latest` (only when the commit is
  still main's head at publish time), `linux/amd64` + `linux/arm64`.

Local check:

```sh
docker build --build-arg GIT_SHA=dev -t phw-<name> images/<name>
docker run --rm --read-only --tmpfs /tmp -p 8080:8080 phw-<name>
```

### nginx and static-site conventions

- Set `add_header` **only at server level**. A location with any
  `add_header` of its own drops all inherited ones, CSP included. Vary
  per-URI values through a `map` (see `images/gradient-ripple/nginx.conf`,
  `$phw_cache_control`).
- Pages are self-contained so a strict CSP works: no inline `<script>` or
  `style="…"`, no external requests (CDNs, fonts, analytics). Setting styles
  from JS via the CSSOM (`el.style.foo = …`) is fine under `style-src 'self'`;
  `setAttribute('style', …)` is not. Use relative asset paths so an image
  also works behind a path prefix. Ship a favicon (`favicon.svg`,
  `favicon.ico`, `apple-touch-icon.png`) so logs stay free of 404s.
- The CSP sets `frame-ancestors 'none'` (+ `X-Frame-Options: DENY`): pages
  can't be iframed. Loosen per image if embedding is ever wanted.

### Per-image notes

- **gradient-ripple**: `?force=webgl1|rgba8|nogl` (comma-separated) forces
  the lower render tiers, `?seed=<int>` fixes the palette;
  `<html data-renderer>` shows the active path. Favicon raster files were
  exported once from `favicon.svg` by hand — re-export when the SVG changes.

## CI

- **Adding an image**: `images/<name>/` + a copy of `image-gradient-ripple.yml`
  named `image-<name>.yml`, every `gradient-ripple` replaced. The scan, the
  `build-image/**` fan-out and Dependabot find new folders on their own.
- PRs run **verify** (lint, build both platforms, smoke test) — base-image
  and BuildKit bumps are proven before merge. Push to main also publishes.
- Bumps to `docker/login-action` or `docker/metadata-action` only execute in
  publish. Prove them before merge by pushing the PR head to a
  `build-image/<topic>` branch.
- **Weekly scan** (Fri 19:30 Europe/Vienna, after Dependabot): Grype as a
  digest-pinned container, fails on **fixable** HIGH/CRITICAL. If its summary
  says the upstream tag still points at the pinned digest, the fix waits on
  nginxinc rebuilding — a digest bump can't help yet, and `RUN` is not allowed.
- **Ignore rules** live in `.github/tool-images/grype/grype.yaml`: each pinned
  to vulnerability + package + exact installed version (so it stops matching
  on its own), with the reasoning and the owner's decision date. Ignored
  matches are listed in the scan summary. Delete a rule once its version is
  gone from all images. Current: CVE-2026-85091 (zlib 1.3.2-r0, gzFile API
  not reachable from nginx) — delete once the base ships zlib 1.3.2-r1.
- A failed scheduled scan emails whoever last changed the `cron:` line.
  GitHub disables schedules in public repos after **60 days without repo
  activity** — merging the weekly Dependabot PRs keeps it alive; if it was
  disabled anyway, re-enable it in the Actions tab.
- Repo Actions policy (owner-managed): only selected actions — GitHub-owned
  plus `docker/{build-push,login,metadata,setup-buildx,setup-qemu}-action` —
  and SHA pinning enforced. Other tools run as pinned containers from
  `run:` steps; a new action needs the owner to extend the list.

## Supply-chain policy

- Anything newly pinned (actions, base images, tool images) must have been
  published **≥ 3 days** ago — same rule as Dependabot's cooldown.
- Actions are SHA-pinned with a `# vX.Y.Z` comment; images digest-pinned.
- Dependabot version updates: weekly, **Friday 19:00 Europe/Vienna**, 3-day
  cooldown for every ecosystem incl. github-actions (supported now — verified
  2026-10-29; older sister-repo notes saying otherwise are outdated). Docker:
  one PR per dependency across all folders (`group-by: dependency-name`).
- Dependabot alerts and security-update PRs are deliberately off
  (security-update PRs skip the cooldown); base images never get alerts
  anyway — the weekly scan covers that gap.

## Branches

`feature/<YYYY-MM-DD>-<topic>` / `bugfix/...`, squash-merged via PR.

`build-image/**`: `git push origin HEAD:build-image/<topic>` verifies and
publishes `sha-<short7>` of **all** images at that state
(`build-image-branch.yml`, no paths filter); delete the branch afterwards.
The per-image callers deliberately don't listen there: `on.push.paths` on a
new branch is evaluated against that push's own diff, so re-pushing commits
GitHub already has never triggers a paths-filtered workflow. Single image,
any branch, once its caller is on main: `gh workflow run image-<name>.yml
--ref <branch>`.
