# plausibly-hello-world

Container images without much content, used as deploy dummies for practicing
cloud deployments — but nice enough to look at to keep deployed for a while.
Not bound to one idea: each image is a self-contained folder under `images/`.

## Layout

```
images/<name>/        one folder = one image, build context = this folder
  Dockerfile
  nginx.conf          → /etc/nginx/conf.d/default.conf (synced copy)
  site/               → /usr/share/nginx/html/ (static files, no build step)
  tools/              optional: offline generators for data in site/ — not
                      shipped, outputs committed (europe-quiz's map)
shared/               files several images use: one source, synced copies
  sync.py             writes the copies into images/; --check (CI) fails on drift
  sync.json           which source goes to which images (+ files they must have)
  sync-manifest.json  written by sync.py: every copy, its source, sha256
  nginx.conf          → every images/*/nginx.conf
  map-quiz/           the map-quiz engine (README.md: config contract)
    site/               → site/ of each map image (engine JS/CSS)
    tools/              generator core (mapgen), engine tests; not synced
.github/
  dependabot.yml
  workflows/
    _build-image.yml        reusable: contract lint, verify, publish
    _discover-images.yml    reusable: lists images/*/ (shared name rule)
    image-<name>.yml        thin caller per image (paths-filtered)
    build-image-branch.yml  build-image/** fan-out, all images, no paths filter
    image-scan.yml          weekly CVE scan of every :latest
    shared-sync.yml         synced copies match shared/; engine tests
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
- **Published as** `ghcr.io/idlinglight/phw-<name>` (public), `<name>` =
  the folder name, tags `sha-<short7>` (every build) and `latest` (only when
  the commit is still main's head at publish time), `linux/amd64` +
  `linux/arm64`. Flat and `phw-`-prefixed on purpose: GitHub's package list
  hides a leading `<repo>/` path part, so the earlier nested names
  (`…/plausibly-hello-world/<name>`, until 2026-10-31) showed as bare folder
  names. The rule lives in `_build-image.yml` (step "Published name") and
  `image-scan.yml`.

Local check:

```sh
docker build --build-arg GIT_SHA=dev -t phw-<name> images/<name>
docker run --rm --read-only --tmpfs /tmp -p 8080:8080 phw-<name>
```

### nginx and static-site conventions

- Set `add_header` **only at server level**. A location with any
  `add_header` of its own drops all inherited ones, CSP included. Vary
  per-URI values through a `map` (see `shared/nginx.conf`,
  `$phw_cache_control`).
- Pages are self-contained so a strict CSP works: no inline `<script>` or
  `style="…"`, no external requests (CDNs, fonts, analytics). Setting styles
  from JS via the CSSOM (`el.style.foo = …`) is fine under `style-src 'self'`;
  `setAttribute('style', …)` is not. Use relative asset paths so an image
  also works behind a path prefix. Ship a favicon (`favicon.svg`,
  `favicon.ico`, `apple-touch-icon.png`) so logs stay free of 404s. Page
  title: `<Name> · phw` (e.g. `Snake · phw`): name first, as tabs truncate.
- The CSP sets `frame-ancestors 'none'` (+ `X-Frame-Options: DENY`): pages
  can't be iframed. Loosen per image if embedding is ever wanted.
- `nginx.conf` is the same file in every image (JSON access log incl. the
  Host header, security headers, endpoints). Each build context is its own
  folder, so every image holds a byte-identical copy of `shared/nginx.conf`.
  Edit the source, run `python3 shared/sync.py`, commit both; a new image
  gets its copy from the same command.

### Shared files (`shared/`)

A file several images need lives once under `shared/`; `shared/sync.py`
(stdlib Python) copies it byte-identically into each consuming image
folder, and the copies are committed (Dockerfiles stay COPY-only, the
build contexts per folder). `shared/sync.json` says what goes where:
`nginx.conf` to every image, `map-quiz/site/` to an explicit list of map
images, which must also have `data-quiz="<folder>"` in their
`site/index.html` (a rule's `require`). `shared/sync-manifest.json`
(written by the sync, committed) lists every copy with source and sha256:
a copy no rule produces any more (source renamed or removed, image taken
off a rule) is removed by the next sync, unless it was edited since —
then the sync stops until it is deleted, or kept as the image's own file
by deleting its manifest entry. `python3 shared/sync.py --check` (CI:
`shared-sync.yml`) fails on any missing, differing or stale copy, an
outdated manifest or a missing required file, and names what to edit.
Commit sources, copies and manifest together. Dockerfiles are never
synced (Dependabot bumps them per folder).

### Map-quiz engine

`shared/map-quiz/`: a map quiz on an inline SVG map, shared by the map
images (now `europe-quiz`, `vienna-districts`, `japan-quiz`). Its `README.md` has the contracts and the
behaviour (rounds, colours, rings, zoom/pan input, wheel classification,
layouts, theme, `?seed`, `<html data-*>`, storage). The engine files
(`main.js`, `quiz.js`, `contract.js`, `wheel.js`, `theme.js`, `style.css`)
are synced into each map image's `site/`; per image: `index.html` (static
text, `lang`, `<html data-quiz="<name>">`, which namespaces localStorage),
`config.js` (regions from the generated data module, rounds, every UI
text, optional attribution line, view options and overlays that swallow
taps; a round may group the map pieces into answers, e.g. islands or
regions, with pieces in no answer inert that round, ask only a subset,
show its own line overlays and a second card line), the generated data module
and `map.svg`, favicons, optionally an own stylesheet for colours. The
offline generator is `tools/build_map.py` per image, an adapter (inputs,
fix-ups, selection) over the shared core `shared/map-quiz/tools/mapgen`
(projections incl. already-projected input, clipping, shared borders,
simplification, optionally of the region borders too, boundary lines
between groups of regions for line overlays, SVG, `--check`). Adding a map image: folder + `config.js`
+ data adapter (+ `tools/data.test.mjs`), its name in the map-quiz rule
of `shared/sync.json` and `python3 shared/sync.py`, then "Adding an
image" below (caller workflow, README row). Engine changes go to
`shared/map-quiz/site/` and reach all map images by the sync.

### Per-image notes

- **gradient-ripple**: `?force=webgl1|rgba8|nogl` (comma-separated) forces
  the lower render tiers, `?seed=<int>` fixes the palette;
  `<html data-renderer>` shows the active path. Favicon raster files were
  exported once from `favicon.svg` by hand — re-export when the SVG changes.
  Input: a tap makes one impulse, a drag a trail, and a held press keeps
  dipping in place, one dip per ring, so the tap's rings carry on as one
  even sequence (up to a generous cap). Strength and cap sit at the top of
  `main.js`; each renderer sets the rhythm (`holdRhythm`, from its measured
  or drawn ring spacing). In the packed `rgba8` tier the mean water level
  creeps while the sim runs — pre-existing, invisible, reset on parking,
  bounded for holds by that cap (details in `water.js`).
- **snake**: canvas 2D, no WebGL. The board wraps at the edges and is sized
  to the viewport when a round starts; on a resize a person's round keeps
  its board (rescaled), the demo starts over on a fitting one. While nobody
  plays, an autopilot plays a demo (`autopilot.js`); each round picks a
  target length, after which it gets careless and soon crashes, so a round
  lasts a minute or two. Any direction input starts a person's round; 30 s
  without input hands it to the autopilot. `prefers-reduced-motion`: no
  demo, a still board until someone plays, and an abandoned round pauses.
  Growth: a swallowed fruit travels down the body as a bulge
  (`MEAL_SPEED` in `game.js`); the snake grows when it reaches the tail
  (at most once per `GROW_SPACING` steps), and the drawn tail eases into
  it instead of stopping for a step.
  Rendering: the body is drawn along its path (corners stay put between
  steps, no flicker); on death the head bumps into the cell it hit, which
  keeps a coral ring while the round is over (`render.js` header).
  `?seed=<int>` makes fruit and autopilot reproducible; `<html data-mode>`
  (`demo`, `demo-end`, `play`, `paused`, `over`, `idle`) shows the state.
  Best score lives in `localStorage` (per browser, optional).
  `game.js` and `autopilot.js` have no DOM, so they also run under plain
  node. Favicon raster files are exports of `favicon.svg` (`.ico` = one
  32 px PNG inside an ICO; the touch icon without the rounded corners).
- **europe-quiz**: a map-quiz image (engine above; its `site/` engine
  files are synced copies). 46 quiz countries (the UN geoscheme's Europe
  minus Russia, plus Kosovo, Cyprus, Türkiye); all other land is muted,
  non-interactive context, faded out around the window. Border view
  EU/Austrian (Crimea → Ukraine, Northern Cyprus → Cyprus, Kosovo
  separate, Transnistria → Moldova); names and capitals in English per the
  EU Interinstitutional Style Guide. Rounds: every country by name, then
  by capital (`<html data-round>` `countries`, `capitals`); a misclick
  shows the name (+ capital). Rings for Vatican, Monaco, San Marino,
  Liechtenstein, Andorra, Malta and Luxembourg. Texts in `site/config.js`
  and `site/index.html`. Data: `tools/build_map.py` (adapter over mapgen,
  deterministic, `--check`) turns Natural Earth 50m v5.1.2 (public domain,
  sha256-pinned, not committed) and `tools/countries.json` (the single
  source of truth: codes, names, capitals, marker points) into
  `site/map.svg` and `site/countries.js`, committed with a "generated"
  header; fix-ups, window and remote parts in `tools/README.md`. Checks:
  `node tools/data.test.mjs`. Favicon rasters exported once from
  `favicon.svg` with headless Chrome (`.ico` = one 32 px PNG; touch icon
  square).
- **vienna-districts**: a map-quiz image (engine above), German UI. Vienna's
  23 districts (ids `d01` … `d23`); rounds: every district by name, then
  by number ("2. Bezirk"; `<html data-round>` `names`, `numbers`); a
  misclick shows "Name · N.". Plain background, no context land, no rings
  or labels; water (Donau, Neue Donau, Donaukanal, Alte Donau, Wienfluss)
  is a muted, non-interactive overlay: bridge gaps patched in map.svg, a
  thin same-coloured outline in map units (`site/vienna.css`,
  `WATER_STROKE`) for the rest; a click on it does nothing
  (`config.blockingOverlays`, owner's call). Ponds and side features near
  the rivers are cut or left out explicitly (`tools/districts.json`
  `water_cut` / `water_out`), never joined by proximity. The district
  borders are drawn once more above the water (`#borders`, an overlay:
  never hit), the regions without their own outline.
  `config.view`: `maxScale` 6, `besideHud`. Data:
  Stadt Wien open data (CC BY 4.0; the attribution line is on the page),
  district boundaries and Realnutzungskartierung 2024 water, both
  sha256-pinned and not committed (the water file without its
  per-request feature-number column); `tools/build_map.py` (adapter over
  mapgen, native EPSG:31256, simplified shared borders, 0 arc crossings
  asserted, water tidied and its final gaps checked) and
  `tools/districts.json` (names, water seeds, cuts, near water left out) give
  `site/map.svg` and `site/districts.js`. Pins, snapshot date and the
  re-pin procedure in `tools/README.md`. Checks: `node
  tools/data.test.mjs`. Favicon rasters exported once from `favicon.svg`
  as for europe-quiz.
- **japan-quiz**: a map-quiz image (engine above) with grouped answers.
  The map is cut into 64 pieces (`PIECES`): each prefecture's part on its
  main island (id = the prefecture's, e.g. `niigata`) plus, for 17, an
  `<id>-isles` piece; Okinawa is one piece. Rounds (`<html data-round>`):
  `islands` (Honshū, Hokkaidō, Kyūshū, Shikoku; the -isles pieces and
  Okinawa are inert), `regions` (the standard 8, Okinawa in Kyūshū;
  "Kansai" 関西 is the official Kinki 近畿 incl. Mie, named by its common
  name on purpose), `prefectures` (47), `capitals` (only the 18 whose capital's
  name differs, a data flag: Tōkyō → Shinjuku counts); each round shows
  its line overlays (coasts, region and prefecture borders); every round
  starts blank (`carryColours: false`: the rounds cover different pieces,
  carried colours would mix found and not-found). Names in
  Hepburn with macrons; the card's second line has kanji · hiragana
  (`sub`, `lang="ja"`), a misclick the kanji. Lake Biwa is a see-through
  water overlay (a tap picks Shiga). No rings; `config.view`: `maxScale`
  6, `besideHud`. Okinawa at its real position, no inset (owner's call);
  the Kuril islands aren't drawn at all (owner: neither clickable nor
  Japanese-administered), the Senkaku islets stay in Okinawa as Natural
  Earth has them. Data: Natural Earth v5.1.2 (public domain) admin-1 10m,
  admin-0 50m (context land) and lakes 10m, sha256-pinned, not
  committed; `tools/build_map.py` (adapter over mapgen: fix-ups with
  expected counts and point checks, the piece split, LAEA 35°N 135°E,
  line overlays from `mapgen.boundary_lines`) and `tools/prefectures.json`
  (the single source of truth: names, kanji, kana, capitals, regions,
  islands; every kana checked against its Hepburn name) give
  `site/map.svg` and `site/japan.js`; fix-ups and pins in
  `tools/README.md`. Checks: `node tools/data.test.mjs`. Favicon rasters
  exported once from `favicon.svg` as for europe-quiz.

## CI

- **Adding an image**: `images/<name>/` + a copy of `image-gradient-ripple.yml`
  named `image-<name>.yml`, every `gradient-ripple` replaced, and
  `python3 shared/sync.py` for its `nginx.conf` (a map-quiz image: see
  "Map-quiz engine" first). The scan, the `build-image/**` fan-out,
  Dependabot and the sync's `"*"` rule find new folders on their own. The
  first publish creates `phw-<name>` already public and linked to this repo
  (observed 2026-10-31): nothing to set in the package settings. The
  README's "Live" column lists the owner's public instances
  (`<short>.phw.salient.at`); the owner fills it in after deploying, so a
  new image's row leaves it empty until then. Hostnames only there: no
  hosting provider or deploy details in the repo.
- PRs run **verify** (lint, build both platforms, smoke test) — base-image
  and BuildKit bumps are proven before merge. Push to main also publishes.
- **shared-sync.yml** (PRs and main, paths `shared/**`, `images/**`):
  `python3 shared/sync.py --check`, the generator core's unittest, and the
  node tests (`shared/map-quiz/tools/*.test.mjs`,
  `images/*/tools/*.test.mjs`) with the runner's own python3 and node (no
  setup actions; the tests need Node 22.12+, the step checks). The image
  callers need no `shared/**` path: a shared change reaches an image only
  through its synced copies, inside its folder.
- Bumps to `docker/login-action` or `docker/metadata-action` only execute in
  publish. Prove them before merge by pushing the PR head to a
  `build-image/<topic>` branch.
- **Weekly scan** (Friday evening, after Dependabot's run): Grype as a
  digest-pinned container, fails on **fixable** HIGH/CRITICAL. If its summary
  says the upstream tag still points at the pinned digest, the fix waits on
  nginxinc rebuilding — a digest bump can't help yet, and `RUN` is not allowed.
- **Ignore rules** live in `.github/tool-images/grype/grype.yaml`: each pinned
  to vulnerability + package + exact installed version (so it stops matching
  on its own), with the reasoning and the owner's decision date. Ignored
  matches are listed in the scan summary. Delete a rule once its version is
  gone from all images.
- Who hears about a failed scheduled scan: GitHub notifies the account that
  created the workflow or last changed its `cron:` line (or re-enabled it),
  through that account's own notification settings (web and/or email,
  Settings → Notifications → Actions) — nothing is mailed unless enabled
  there. GitHub disables schedules in public repos after **60 days without
  repo activity**; merging the weekly Dependabot PRs keeps it alive, and a
  disabled schedule is re-enabled in the Actions tab.
- The repo's Actions policy is owner-managed (selected actions only, SHA
  pinning enforced). Read the current allow-list with
  `gh api repos/idlinglight/plausibly-hello-world/actions/permissions/selected-actions`
  before adding a `uses:`. Tools outside it run as pinned containers from
  `run:` steps, or the owner extends the list.

## Supply-chain policy

- Anything newly pinned (actions, base images, tool images) must have been
  published **≥ 3 days** ago — same rule as Dependabot's cooldown.
- Actions are SHA-pinned with a `# vX.Y.Z` comment; images digest-pinned.
- Dependabot version updates: weekly, **Friday 19:00 Europe/Vienna**, 3-day
  cooldown for every ecosystem. Details and per-dependency rules live in
  `.github/dependabot.yml`.
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
