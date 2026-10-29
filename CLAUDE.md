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
  workflows/          shared build workflow + one thin caller per image
```

## Image contract

Every image under `images/` must satisfy this — CI smoke-tests it, and
deployments can rely on it without per-image knowledge:

- **Base**: `nginxinc/nginx-unprivileged:<stable>-alpine-slim`, digest-pinned
  (`tag@sha256:<index digest>`). Stable channel only (even minor, e.g. 1.30).
- **Runtime**: non-root (uid 101), listens on **8080** (IPv4), works with a
  read-only root filesystem plus a writable `/tmp` (`docker run --read-only
  --tmpfs /tmp`; k8s: `readOnlyRootFilesystem` + an emptyDir on `/tmp`).
- **Endpoints**: `GET /healthz` → `200 ok` (probe target), `GET /version.txt`
  → the short commit SHA (build arg `GIT_SHA`, default `dev`), `GET /` → the page.
- **Dockerfile**: COPY-only, no `RUN` (multi-arch without QEMU). Static files
  ship as-is — no npm, no bundler, so there's no JS dependency tree to patch.
- **Published as** `ghcr.io/idlinglight/plausibly-hello-world/<name>`, tags
  `sha-<short7>` (every build) and `latest` (main only), `linux/amd64` +
  `linux/arm64`.

Local check:

```sh
docker build --build-arg GIT_SHA=dev -t phw-<name> images/<name>
docker run --rm --read-only --tmpfs /tmp -p 8080:8080 phw-<name>
```

## Supply-chain policy

- Anything newly pinned (actions, base images, scanner versions) must have been
  published **≥ 3 days** ago — same rule as Dependabot's cooldown.
- Actions are SHA-pinned with a `# vX.Y.Z` comment; base images digest-pinned.
- Dependabot version updates: weekly, **Friday 19:00 Europe/Vienna**, 3-day
  cooldown. Dependabot alerts and security-update PRs are deliberately off
  (security-update PRs skip the cooldown); base images never get alerts
  anyway — the weekly image CVE scan covers that gap.

## Branches

`feature/<YYYY-MM-DD>-<topic>` / `bugfix/...`, squash-merged via PR.
`build-image/**` branches: push any state there to get an image built and
pushed without merging (see the workflow comments).
