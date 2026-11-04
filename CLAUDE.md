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
  entrypoint/         optional: startup scripts → /docker-entrypoint.d/
                      (run before nginx; glyph-rain)
  tools/              optional, not shipped (not in the image's CI paths):
                      offline generators for data in site/ (outputs
                      committed: europe-quiz's map), node tests (CI),
                      hand-run online checkers (wiki_titles.py: never run
                      by a build, a test or CI)
shared/               files several images use: one source, synced copies
  sync.py             writes the copies into images/; --check (CI) fails on drift
  sync.json           which source goes to which images (+ files they must have)
  sync-manifest.json  written by sync.py: every copy, its source, sha256
  nginx.conf          → every images/*/nginx.conf
  map-quiz/           the map-quiz engine (README.md: config contract)
    site/               → site/ of each map image (engine JS/CSS)
    tools/              generator core (mapgen), engine tests; wikicheck.py
                        (hand-run online title checker, never run by a
                        build, a test or CI); not synced
tool-images/          pin holders for images CI runs from run: steps, never
  README.md           built (Dependabot bumps the FROM lines); the notes,
  buildkit/           incl. each scan ignore rule's analysis
  grype/              (+ grype.yaml: scan ignore rules)
.github/
  dependabot.yml      (+ dependabot.md: its notes)
  workflows/          each <workflow>.yml has its notes in <workflow>.md beside
    README.md               it (they trigger nothing); README.md: the index
    _build-image.yml        reusable: contract lint, verify, publish (publish-skip)
    _discover-images.yml    reusable: lists images/*/ (shared name rule)
    image-<name>.yml        thin caller per image (paths-filtered; notes: _build-image.md)
    build-image-branch.yml  on demand: one image or all, at any ref (sha- tags)
    image-scan.yml          weekly CVE scan of every :latest; scanner-age on PRs
    checks.yml              synced copies match shared/; every unit test
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
- **Startup scripts** (optional): `entrypoint/*.sh` →
  `/docker-entrypoint.d/` (`COPY --chmod=0755`); the base image's
  entrypoint runs them as uid 101 before nginx starts. They write only
  under `/tmp` (a result is served through a symlink in `site/`, so the
  shared `nginx.conf` stays as it is) and never fail: the entrypoint runs
  them under `set -e`, a failing script would stop the container. A
  deployment that overrides the container's command skips them.
- **Published as** `ghcr.io/idlinglight/phw-<name>` (public), `<name>` =
  the folder name, tags `sha-<short7>` and `latest` (only when the commit is
  still main's head at publish time), `linux/amd64` + `linux/arm64`. A push
  to main publishes an image only when its fingerprint changed: the shipped
  files of `images/<name>/` without `tools/`, the platforms, the BuildKit
  and `docker/*` action pins (annotation `com.github.idlinglight.phw.content`),
  compared with `latest`'s. So `latest` and its `/version.txt` name the last
  commit that changed the image or its build tools. A dispatch always
  publishes. Flat and `phw-`-prefixed on purpose: GitHub's package list
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

- The base image's own `/etc/nginx/nginx.conf` puts the pid file and all
  temp paths under `/tmp` (so a read-only root works given a writable
  `/tmp`) and logs at http level to `/var/log/nginx/access.log` (a symlink
  to stdout) in its `main` format; `shared/nginx.conf` replaces that log at
  server level with the JSON one, same file. Re-check both after a base
  image line change (a new nginx stable line).
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
  Links the player follows to other sites are fine (no request of the
  page): `target="_blank"`, `rel="noopener noreferrer"`, nothing
  prefetched or embedded from there.
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
`checks.yml`) fails on any missing, differing or stale copy, an
outdated manifest or a missing required file, and names what to edit.
Commit sources, copies and manifest together. Dockerfiles are never
synced (Dependabot bumps them per folder).

### Map-quiz engine

`shared/map-quiz/`: a map quiz on an inline SVG map, shared by the map
images (now `europe-quiz`, `vienna-districts`, `japan-quiz`, `world-quiz`,
`south-america-quiz`, `east-asia-quiz`). Its `README.md` has the contracts and the
behaviour (rounds, colours, rings, zoom/pan input, wheel classification,
layouts, theme, `?seed`, `<html data-*>`, storage). The engine files
(`main.js`, `quiz.js`, `contract.js`, `wheel.js`, `theme.js`, `style.css`,
`wiki.js`: Wikipedia URLs for a config, loaded only where one imports it)
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
(projections incl. already-projected input and Fuller's icosahedral net, clipping, shared borders,
simplification, optionally of the region borders too, boundary lines
between groups of regions for line overlays, SVG, `--check`). Adding a map image: folder + `config.js`
+ data adapter (+ `tools/data.test.mjs`), its name in the map-quiz rule
of `shared/sync.json` and `python3 shared/sync.py`, then "Adding an
image" below (caller workflow, README row). Engine changes go to
`shared/map-quiz/site/` and reach all map images by the sync.
Opt-in per image: `roundPicker: true` (+ `text.roundPicker`) turns the
card's round label into a native list of the rounds; picking one starts
a fresh round of it (next round index of that kind, blank map, counters
kept; on in world-quiz). `view.panToCentre: true` lets any point of
the full view be panned to the centre of the free area at every zoom (for
a one-handed pinch about the centre; on in world-quiz). `rounds[].link`
(+ `text.link`, the link's name) makes the asked name on the card a link
to a page about it, opened in a new tab: marked by an icon after it,
underlined only on hover and keyboard focus (https only, no prefetch, the
live region moves to an sr-only copy; on in world-quiz and japan-quiz:
the English Wikipedia article, a capital round's the capital's).

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
  Earth has them. A shaded relief (`site/relief.png`, owner's pick over
  elevation bands) lies over the pieces as `<image id="relief">`, first
  in `#overlays` (never hit), plain alpha, no blend mode (`japan.css`).
  Data: Natural Earth v5.1.2 (public domain) admin-1 10m, admin-0 50m
  (context land) and lakes 10m, and NOAA ETOPO 2022 (30" ERDDAP subset,
  free to use, no warranty), all sha256-pinned, not committed;
  `tools/build_map.py` (adapter over mapgen: fix-ups with expected
  counts and point checks, the piece split, LAEA 35°N 135°E, line
  overlays from `mapgen.boundary_lines`, the hillshade with the inverse
  projection) and `tools/prefectures.json` (the single source of truth:
  names, kanji, kana, capitals, regions, islands; every kana checked
  against its Hepburn name) give `site/map.svg`, `site/japan.js` and
  `site/relief.png`; fix-ups, pins and relief parameters in
  `tools/README.md`. English Wikipedia titles for the card's link
  (`wiki` on every answer, `capital_wiki` on the 18 asked capitals) live
  in `prefectures.json` too, checked by hand online with
  `tools/wiki_titles.py` (shared `wikicheck.py`). Checks: `node
  tools/data.test.mjs`. Favicon rasters exported once from `favicon.svg`
  as for europe-quiz.
- **world-quiz**: a map-quiz image (engine above) of the world on
  Buckminster Fuller's Dymaxion (Airocean) projection (title "World Quiz";
  "Dymaxion" only descriptively): `mapgen.Polyhedral("fuller")`, Gray's
  exact transform on Fuller's net, polygons clipped per net piece. 197
  entries (owner, 2026-11-02): the 193 UN members, Vatican City, Kosovo,
  Taiwan, and Greenland ("Greenland (Denmark)", `of`); Russia clickable;
  Palestine, Western Sahara, the Siachen Glacier, Antarctica and every
  dependency or territory are context land; overseas parts Natural Earth
  files under a state answer that state. Border view as europe-quiz (EU
  official view): Crimea, Northern Cyprus, Somaliland, Åland, Hong Kong,
  Macao merged; the Golan Heights (→ Syria) and Western Sahara (out of
  Morocco) cut along lon/lat lines (`mapgen.cut_cells`), Ceuta and
  Melilla (→ Spain) clipped by small boxes (`mapgen.clip_box`); the cuts'
  new vertices go into the neighbours, no T-junction anywhere
  (`mapgen.t_junctions`, asserted); 68 point checks, 9 empty boxes, the
  context list asserted (tools/README.md). Rounds (`<html data-round>`):
  `countries` and `capitals` without the 36 small states (inert there;
  `small: true`, checked by the build against its rule on the map as
  drawn: under 1,000 km², or no land border and under 30,000 km²; Cyprus
  is one), then `all-countries` and `all-capitals` with them, ringed;
  Brunei, Kosovo, Luxembourg, Montenegro and Qatar (largest drawn shape
  under 4 units) have rings in every round. Israel's capital: Jerusalem
  (owner). `carryColours: false`,
  `roundPicker: true`, `view`: `maxScale` 60, `besideHud`, `panToCentre` (any part of the net
  can be dragged to the middle, also at the full view). Far parts cut
  off by the net and under 1 % of their state (NZ's Chathams and
  Tokelau, a Fiji islet) are dropped, asserted. map.svg starts with
  `<path id="net">` (the sea) and `<path id="folds">`; `world.css`
  colours outside the net as the page. Data: Natural Earth 50m admin-0
  v5.1.2 (public domain), the file europe-quiz pins; `tools/build_map.py`
  and `tools/countries.json` (the single source of truth: names,
  capitals, flags, curated marker points, English Wikipedia titles
  `wiki` and `capital_wiki` on all 197, checked by hand online with
  `tools/wiki_titles.py`) give `site/map.svg` and `site/countries.js`.
  Checks: `node tools/data.test.mjs`. Favicon rasters exported once from
  `favicon.svg` as for europe-quiz.
- **south-america-quiz**: a map-quiz image (engine above), English UI,
  rounds like europe-quiz (`countries`, `capitals`). 13 quiz entries: the
  12 sovereign states plus French Guiana, shown as "French Guiana
  (France)" (`of` in the data); the Falkland Islands are context land
  (owner's call, 2026-11-02; membership is the `"quiz"` field in
  `tools/countries.json`, the steps of a flip in `tools/README.md`).
  Bolivia's capital is asked
  as "Sucre / La Paz" (constitutional capital first). Border view:
  Natural Earth's default (as administered: Essequibo and the New River
  Triangle in Guyana, the Litani–Marouini area in French Guiana; the
  Southern Patagonian Ice Field line as drawn), point-checked. No rings
  (French Guiana is ~23 px on a phone); `config.view`: `maxScale` 6,
  `besideHud` (else the landscape card covers the tip of north-east
  Brazil on small phones). LAEA 20°S 60°W; the Galápagos are a remote
  part: drawn at their real position beside the window as part of
  Ecuador (seen on desktops and in landscape), not counted for it, which
  would cost 18 % of the map's size on portrait phones; Easter Island is
  left out (a speck in the faded band that would still take clicks);
  extent 60 % / 20 % (a tall continent). Data: `tools/build_map.py`
  (adapter over mapgen: French Guiana split out of `FRA`, deterministic,
  `--check`) turns Natural Earth 50m v5.1.2 (the file europe-quiz pins) and
  `tools/countries.json` (the single source of truth) into `site/map.svg`
  and `site/countries.js`; details in `tools/README.md`. Checks: `node
  tools/data.test.mjs`. Favicon rasters exported once from `favicon.svg`
  as for europe-quiz.
- **east-asia-quiz**: a map-quiz image (engine above), built like
  europe-quiz. 18 quiz countries: the UN geoscheme's Eastern and
  South-eastern Asia plus Palau; Taiwan its own country, Hong Kong and
  Macao merged into China (owner's calls); all other land in the extent
  is muted, non-interactive context (from Sweden to Alaska and New
  Zealand; picked by projected bounding box, asserted by
  `CONTEXT_CHECKS`; Natural Earth's cut at 180° stitched so no line shows
  through Chukotka), faded out around the window. Otherwise
  Natural Earth's default layer (Aksai Chin with China, Arunachal Pradesh
  with India, the Kurils Russian context land); the South China Sea's
  reefs and islets aren't in the 50m file, and the build stops if a source
  has them (`EMPTY`: handle them as context land on purpose). Names and
  capitals in English per the EU Interinstitutional Style Guide, plain
  ASCII (Myanmar for its Myanmar/Burma, Tokyo; Taiwan, Taipei by their
  common names); Indonesia's capital is Jakarta until the presidential
  decree moving it to Nusantara (source, re-check note in
  `tools/README.md`). Rounds as europe-quiz (`countries`, `capitals`).
  Rings for Singapore, Palau, Brunei and Timor-Leste (its ring shows on
  phones only); Palau's Tobi is dropped (it would size Palau's ring to
  hide). `config.view`: `besideHud` (Japan reaches the top-right corner),
  default `maxScale`. LAEA 20°N 110°E, no remote parts. Data:
  `tools/build_map.py` (adapter over mapgen) and `tools/countries.json`
  (codes, names, capitals, marker points) turn the Natural Earth 50m
  file europe-quiz pins into `site/map.svg` and `site/countries.js`;
  fix-ups, point checks and choices in `tools/README.md`. Checks: `node
  tools/data.test.mjs`. Favicon rasters exported once from `favicon.svg`
  as for europe-quiz.
- **glyph-rain**: canvas 2D, dark only: glyphs fall down columns and fade
  (white head, green trail, black ground); a tap starts a column there.
  It shows which of two documented switches, neither of them secret,
  reached the container at its start (meant for checking config and
  secret delivery behind an auth layer; no public instance, so no Live
  link): none → Egyptian hieroglyphs; env `PHW_GLYPHS=music` → musical
  symbols; a regular file `/etc/phw/glyphs` of exactly the bytes `runes`,
  optionally + LF or CRLF (byte-compared with `cmp`; e.g. a secret mounted
  as a file, the volume at `/etc/phw`; links are followed) → runes; both
  → the two mixed. `entrypoint/40-phw-glyphs.sh` (POSIX sh, every start)
  writes `/tmp/phw/glyphs.json` (beside, then moved; a failed write
  removes the old one), served as `/glyphs.json` through the symlink
  `site/glyphs.json`. It holds fixed tokens only (the sets; per switch
  unset/match/other and absent/match/other/unreadable/directory/notfile):
  a switch's value is never written or logged, nothing but a regular file
  is read (a pipe can't block the start), and the page has no URL or
  storage override (the set on screen is the signal). Read once at start:
  a change needs a restart.
  The caption (bottom left) names each set and its switch, plus a note
  for a switch that didn't take or a file that didn't load; `<html
  data-glyphs data-env data-file>` (+ `data-missing`, `data-motion`).
  System fonts only. Checked 2026-11-04: hieroglyphs are default on
  Windows 10+, Apple systems, Android, ChromeOS and Ubuntu 24.04+;
  musical symbols are complete on Windows, Android and Ubuntu, Apple
  systems draw 17, ChromeOS 7; runes U+16A0–16EA everywhere. `render.js`
  drops glyphs a system can't draw (a missing glyph's metrics equal an
  unassigned code point's), keeps upright hieroglyphs (ink aspect
  0.45–1.35), and a set with under 6 drawable glyphs shows digits, said in
  the caption. `?seed=<int>` fixes the rain; `prefers-reduced-motion`: a
  still frame. Rhythm constants at the top of `sim.js`. Checks: `node
  tools/entrypoint.test.mjs` (every switch state under the system's sh; a
  sentinel value never reaches the log or the file), `glyphs.test.mjs`,
  `sim.test.mjs`. Favicon rasters exported once from `favicon.svg` as for
  europe-quiz.

## Comments in files that run CI

A comment in a file that triggers CI or ships in an image (workflows,
`dependabot.yml`, tool-image pins, Dockerfiles, `nginx.conf`, everything in
`site/` and `entrypoint/`, engine files) says only what its own lines do
and why, in terms that change only when those lines change. Anything that
can become false through a change elsewhere goes to a note that triggers
nothing, and the comment keeps at most a pointer: another file's behaviour,
which images or workflows exist or use something, dates and observations,
upstream or vendor behaviour, owner settings, policy. The notes:
this file (contracts, conventions, per-image notes); for each workflow a
note named after it beside it (`.github/workflows/<workflow>.md`; the
folder's `README.md` is the index), `.github/dependabot.md`;
`tool-images/README.md` (pins, scan ignore rules); an image's
`tools/README.md` (its data). A workflow's header is its name, at most a
line of purpose, and the pointer to its note: even a summary of its own
jobs would go stale unnoticed when they change. So updating a note never
rebuilds an image, and no comment needs a rebuild to stay true.

## CI

- **Adding an image**: `images/<name>/` + a copy of any caller (they differ
  only in the name, e.g. `image-snake.yml`) named `image-<name>.yml`, every
  `snake` replaced, and
  `python3 shared/sync.py` for its `nginx.conf` (a map-quiz image: see
  "Map-quiz engine" first). The scan, `build-image-branch.yml -f
  image=all`, Dependabot and the sync's `"*"` rule find new folders on their
  own; a test tag works before the caller is on main ("Branches"). The
  first publish creates `phw-<name>` already public and linked to this repo
  (observed 2026-10-31): nothing to set in the package settings. The
  README's "Live" column lists the owner's public instances
  (`<short>.phw.salient.at`); the owner fills it in after deploying, so a
  new image's row leaves it empty until then. Hostnames only there: no
  hosting provider or deploy details in the repo.
- PRs run **verify** (lint, build both platforms, smoke test) — base-image
  and BuildKit bumps are proven before merge. A push to main verifies and
  publishes, but an image only when its fingerprint changed (shipped files,
  platforms, BuildKit and `docker/*` action pins; "Image contract").
- **checks.yml** (PRs and main, paths `shared/**`, `images/**`): every
  offline check in one job, all of them on any change: `sync.py --check`,
  the python unittests (sync script, generator core, the Wikipedia title
  checker's offline logic) and every `*.test.mjs` under
  `shared/map-quiz/tools/` and `images/*/tools/`, with the runner's own
  python3 and node (Node 22.12+ checked, not pinned). Why all at once, the
  couplings, what each step checks: `.github/workflows/checks.md`. A new
  test file there is picked up by its glob; a new kind of test gets a step
  and a line in that note.
- Bumps to `docker/login-action` or `docker/metadata-action` only execute in
  publish. Prove them before merge by publishing one image from the PR's
  branch: `gh workflow run build-image-branch.yml --ref <branch> -f
  image=snake`.
- **Weekly scan** (Friday evening, after Dependabot's run): Grype as a
  digest-pinned container, fails on **fixable** HIGH/CRITICAL. If its summary
  says the upstream tag still points at the pinned digest, the fix waits on
  nginxinc rebuilding — a digest bump can't help yet, and `RUN` is not allowed.
- **Ignore rules** live in `tool-images/grype/grype.yaml`: each pinned
  to vulnerability + package + exact installed version (so it stops matching
  on its own), with a short `reason`; the analysis, sources and the owner's
  decision date per rule are in `tool-images/README.md`. Ignored
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
  published **≥ 3 days** ago — same rule as Dependabot's cooldown. Dependabot
  has no cooldown for images on ghcr.io (the grype pin), so image-scan's
  `scanner-age` job checks the scanner's release and digest build dates on
  every PR that changes the scanner pin or the scan.
- Actions are SHA-pinned with a `# vX.Y.Z` comment; images digest-pinned.
- Dependabot version updates: weekly, **Friday 19:00 Europe/Vienna**, 3-day
  cooldown for every ecosystem. Per-dependency rules: `.github/dependabot.yml`;
  what is off and why, review notes per bump kind: `.github/dependabot.md`.
- Dependabot alerts and security-update PRs are deliberately off
  (security-update PRs skip the cooldown); base images never get alerts
  anyway — the weekly scan covers that gap.

## Branches

`feature/<YYYY-MM-DD>-<topic>` / `bugfix/...`, squash-merged via PR.

Test tags (`sha-<short7>`) of any branch GitHub has, no merge needed:
`gh workflow run build-image-branch.yml --ref <branch> -f image=<name>`
verifies and publishes that one image, `-f image=all` every image. Also for
a new image whose caller isn't on main yet, and for PR heads or Dependabot
branches. On main only to force a republish (a push skips an unchanged
image): there the publish also moves `latest` and queues in main's own
publish groups. The run uses the
workflow files at `--ref`, which therefore needs a version of
`build-image-branch.yml` with the dispatch: rebase an older branch (a
Dependabot PR: `@dependabot rebase`). Details: `.github/workflows/build-image-branch.md`.
