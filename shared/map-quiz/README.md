# map-quiz engine

A map quiz as a static page: an inline SVG map, a question card, round
after round of "find this region". One engine for several images
(`images/europe-quiz`, more to come); each image brings its own data,
texts and map, the engine stays the same.

```
shared/map-quiz/
  site/             the engine: synced into each map image's site/
    main.js           map view (zoom, pan), input, HUD, persistence
    quiz.js           the rules (no DOM)
    contract.js       config checks (no DOM): main.js at start, node tests
    wheel.js          mouse wheel or trackpad? (no DOM)
    theme.js          light/dark, a classic script in <head>
    style.css         layout, theme tokens
  tools/            not synced, not shipped
    mapgen/           generator core (Python 3.9+, stdlib), see below
    mapgen_test.py    python3 -I shared/map-quiz/tools/mapgen_test.py
    quiz.test.mjs     node shared/map-quiz/tools/quiz.test.mjs (rules)
    contract.test.mjs node shared/map-quiz/tools/contract.test.mjs
    wheel.test.mjs    node shared/map-quiz/tools/wheel.test.mjs
                      (+ wheel-fixture.json: recorded wheel events)
```

The engine files reach an image as byte-identical copies
(`python3 shared/sync.py`, rules in `shared/sync.json`; CI's
`shared-sync.yml` fails on drift). Edit them here, never in an image,
and commit the source together with the updated copies. Each image's
behaviour is its own `site/config.js` + `site/index.html` + generated
data.

## A map image's site/

| File | Whose | What |
| --- | --- | --- |
| `index.html` | image | static text and `lang`; contract below |
| `config.js` | image | data and texts for the engine; contract below |
| data module (e.g. `countries.js`) | generated | `MAP` + the region list, by the image's `tools/build_map.py` |
| `map.svg` | generated | the map, layout below |
| favicons | image | `favicon.svg`, `favicon.ico`, `apple-touch-icon.png` |
| own stylesheet (optional) | image | token overrides, linked after `style.css` |
| `main.js`, `quiz.js`, `contract.js`, `wheel.js`, `theme.js`, `style.css` | synced | the engine: don't edit there |

### index.html

- `<html lang="…" data-quiz="<image folder name>">`. `data-quiz`
  namespaces localStorage: `phw-<name>` (quiz state), `phw-<name>-theme`
  (theme override), so two map images on one origin keep apart.
- In `<head>`: `style.css` (then the image's own stylesheet, if any),
  then `<script src="theme.js"></script>` (classic, after the
  stylesheets: no flash of the other theme), `<script type="module"
  src="main.js"></script>`, and a `<meta name="theme-color">`.
- The element ids the engine uses: `map`, `card` (with a `.swatch`),
  `round`, `progress`, `correct`, `misses`, `prompt`, `prompt-kind`,
  `prompt-text`, `toast`, `controls`, `reset` (with `.btn-text`), `theme`
  (with `.icon-moon`, `.icon-sun`), `zoom-out`, `zoom-fit`, `zoom-in`,
  `label`, `safe`. Start from europe-quiz's `index.html` and translate its
  text: title, description, `aria-label`s, the `sr-only` help paragraph,
  `noscript`, "Reset?". The engine overwrites the round label, prompt and
  the reset/theme button labels from the config once it runs.

### config.js

An ES module beside the data module; its default export:

```js
import { MAP, DISTRICTS } from './districts.js'; // generated

export default {
  map: MAP,           // { width, height, extent: [x, y, w, h] } (map units)
  items: DISTRICTS,   // [{ id, marker?, size?, ...own fields }]
  rounds: [           // round r uses rounds[r % rounds.length]
    {
      key: 'names',                 // <html data-round>
      label: 'Namen',               // the card's round label
      prompt: 'Finde',              // screen-reader text before the asked one
      ask: (d) => d.name,           // the asked text (the card's big line)
      miss: (d) => d.name,          // label at a misclick on d
      done: ({ total, misses }) => `Alle ${total} Bezirke gefunden. Jetzt die Nummern.`,
    },
    {
      key: 'numbers', label: 'Nummern', prompt: 'Finde',
      ask: (d) => `${d.number}. Bezirk`,
      miss: (d) => `${d.name} · ${d.number}.`,
      done: ({ total, misses }) => `Alle ${total} Nummern gefunden. Wieder die Namen.`,
    },
  ],
  text: {
    intro: { mouse: 'Klicke …', touch: 'Tippe …' }, // first visit's toast
    newGame: 'Neues Spiel …',                       // toast after a reset
    reset: 'Quiz zurücksetzen',                     // reset button label …
    resetArmed: 'Wirklich zurücksetzen? …',         // … while armed (3 s)
    mapError: 'Die Karte konnte nicht geladen werden …',
    // theme button: other = the theme a press switches to ('light' | 'dark'),
    // override = an override is stored (a press goes back to the system's)
    theme: (other, override) => ({ label: '…', title: '…' }),
  },
  attribution: 'Datenquelle: Stadt Wien – data.wien.gv.at', // optional
  view: { maxScale: 6 }, // optional: CSS px per map unit at the closest zoom (default 12)
};
```

- **items**: one per region. `id`: unique, letters, digits, `_ . -`, not
  starting with a digit, not `land`, `overlays`, `markers`, `fade*`, and
  not an element id of `index.html` (ADM0_A3 codes, `d01` … all fine).
  `marker: [x, y]` (map units) + `size` (larger side of the region's
  bounding box, map units) draws a ring for a region too small to tap at
  the full view: a tap inside the drawn ring picks it, one in a wider zone
  only over sea, context land or that region itself; the ring hides once
  the region is 28 px across. Leave markers out for none (no ring layer).
- **rounds**: any number of kinds; rounds cycle through them, each round
  asks every region once in its own shuffled order. Colours: A in even
  rounds, B in odd ones, so the map recolours round by round. Prompts must
  be unique within a round (`checkTexts` tests it).
- **attribution**: a credit line where it never meets the HUD: under the
  controls in portrait (they move up for it), the bottom-left corner in
  landscape. Fits about 50 characters on a 320 px phone.
- **view.maxScale**: maps are 1000 units wide; at most this many CSS px
  per unit (europe 12; a city map needs less), but always at least 4× the
  full view.

`contract.js`: `checkConfig(config)` (main.js runs it at start: a broken
config throws, naming the field) and `checkTexts(config)` (every ask/miss
text for every item; for an image's node test).

### map.svg

What the engine reads (`mapgen.map_svg` writes exactly this):

```
<svg xmlns="http://www.w3.org/2000/svg" viewBox="<extent>">
<!-- generated header -->
<path id="land" d="…"/>          optional: context land, merged, never hit
<g id="…">                        the regions: one <path id="<item id>"> each
  …                               (europe: id="countries"; mapgen default "regions")
</g>
<g id="overlays">                 optional: drawn above the regions, never hit
  <path id="water" d="…"/>        (clicks go to the region beneath)
</g>
</svg>
```

No styling in the file. The engine finds the regions' group from their
shapes (class `regions` is added), draws a fade at the edge of the extent
when there is context around the window (`MAP.extent` starts below 0),
and the rings.

### Styling

Tokens on `:root` in `style.css`, each defined three times (light;
`@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`;
`:root[data-theme="dark"]`): `--sea` (page background, also beyond the
drawn extent), `--land`, `--land-line`, `--region`, `--region-hover`,
`--border`, `--a` / `--b` (+ `-hover`), `--miss`, `--ring`, panel and text
colours; `--water` (overlay fill and outline, default `--sea`) and
`--overlay-stroke` (overlay outline width in map units, e.g. `1.2px`,
scales with the map; default 0). An image overrides them in its own
stylesheet, linked after `style.css`, in the same three places; one
overlay can be styled by its id. `theme.js` copies `--sea` into the
theme-color meta.

## Behaviour

- `map.svg` is fetched and inserted inline (gzip and MIME already covered
  by `nginx.conf`); the viewBox follows a camera, so strokes stay crisp and
  a tap is tested against the real shapes.
- Rounds cycle through `config.rounds`, each asking every region once,
  shuffled (a round never opens with the region that closed the last). A
  correct pick colours the region (A in even rounds, B in odd ones: the
  map recolours round by round, blank only after a reset); a misclick
  counts, blinks and shows the round's `miss` label for 1.5 s. Reset takes
  two presses (the first arms it for 3 s).
- Rings (optional): a tap inside the drawn ring picks it, a tap in the
  wider zone around it only over sea, context land or that region itself
  (never over a neighbour); the nearest ring wins. Rings shrink at low zoom
  (phones) and hide once their region is 28 px across.
- Answering needs a pointer (click or tap); keys only zoom and pan. Zoom:
  pinch (touch, trackpad), mouse wheel and ctrl + wheel (at the cursor),
  buttons, `+ - 0` keys. Pan: drag, a trackpad's two-finger scroll, arrow
  keys. A press that moves more than 5–10 px is a pan, never a click.
- Wheel events are classified per gesture as trackpad or mouse by
  `wheel.js` (DOM-free; rules from real macOS recordings in Safari,
  Chrome, Firefox at 100 % and 125 % zoom: trackpads send whole CSS or
  device pixels, mice fractional steps or lines). `tools/wheel.test.mjs`
  replays those recordings (`tools/wheel-fixture.json`); re-record and
  extend it when a device misbehaves.
- The full view fits the window around all regions, between the card and
  the controls in portrait; context drawn around the window fades out, so
  tall or wide screens show map. Two layouts (`min-aspect-ratio: 4/3` in
  `style.css` and `main.js`).
- Theme follows the OS; the toggle stores the other theme, pressing again
  clears it, and an override that matches the OS is dropped (`theme.js`,
  a classic script in `<head>`: no flash).
- `?seed=<int>` makes the shuffles reproducible (stored state with another
  seed is replaced). State on `<html>`: `data-round` (the round's key),
  `data-progress`, `data-zoom`, `data-wheel`, `data-theme`,
  `data-theme-pref`, `data-ready` (`1`, or `error`). Quiz state lives in
  localStorage (optional: blocked storage just means no resume).

## Generator core: mapgen

Python 3.9+, stdlib only, deterministic. An image's
`tools/build_map.py` is an adapter: it loads and pins its inputs, applies
its own fix-ups, decides what is a region, context land or an overlay,
and writes its data module; mapgen does the geometry. `python3 -I` keeps
the script's folder off `sys.path`, so the adapter adds the core's:

```python
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "shared", "map-quiz", "tools"))
import mapgen

raw = mapgen.read_pinned(path, SHA256, SIZE, URL)      # BuildError on mismatch
project = mapgen.Identity()       # input already projected (e.g. EPSG:31256), or
# mapgen.epsg3035() / LambertAzimuthalEqualArea(...) / TransverseMercator(lon0, ...)
window = mapgen.Window(points_metres, margin=0.03, width=1000.0, extent=(0, 0))
mb = mapgen.MapBuilder(project, window, region_ids, grid=10)
for rid, poly in regions:   mb.add_region(rid, poly)   # mapgen.parse_wkt / polys_of
for poly in context:        mb.add_context(poly)       # optional
for poly in water:          mb.add_overlay("water", poly)
res = mb.build(keep_islands=ringed_ids)
svg = mapgen.map_svg(res, region_ids, HEAD, group_id="regions")
js = "\n".join([f"// {HEAD}", "", window.map_js(), "", "export const DISTRICTS = [", …, "];", ""])
sys.exit(mapgen.emit({"map.svg": svg, "districts.js": js}, out_dir, check, res.report(region_ids)))
```

- Projections are callables `(lon, lat) -> (easting, northing)` in
  metres, y north; anything with that shape works. `Identity()` passes
  projected coordinates through; `self_test()` checks a projection
  against its reference point (EPSG:3035's; the TM formulas against
  EPSG Guidance Note 7-2's worked example).
- `Window`: the full view is the bounding box of the given points plus
  margin, scaled to `width` units, y down; `extent` = context drawn
  around it per side (fraction of width / height), `(0, 0)` for none.
- `MapBuilder`: regions must lie inside the window (`outside_ok=True` for
  remote parts, which may be clipped at the extent); vertices snap to
  1/`grid`; parts of a region merge, neighbours share border vertices
  (shared arcs), unshared specks below `min_island` are dropped (never for
  `keep_islands`), only context-only arcs are simplified
  (`context_tol`, `far_tol` beyond `far_gap`), overlays get `overlay_tol`
  and stay outside the shared topology. A region lost to the grid keeps
  its outline at 10× finer resolution.
- Feed polygons in a fixed order: the output depends on it, and the same
  inputs in the same order give byte-identical files. `emit` writes, or
  with `check` compares and returns 1 on a difference, and prints sizes
  (raw, gzip -1 as nginx serves it, gzip -9).

## Adding a map image

1. `images/<name>/`: `Dockerfile` (a copy of europe-quiz's), `site/index.html`
   (copy, translate, `data-quiz="<name>"`), `site/config.js`, favicons.
2. `tools/build_map.py` (adapter, above) → `site/<data>.js` +
   `site/map.svg`, committed with a "generated" header; `tools/README.md`
   (data source, licence, pins, fix-ups); `tools/data.test.mjs`:
   `checkTexts(config)` from `../site/contract.js` plus the image's own data
   checks (CI runs every `images/*/tools/*.test.mjs`).
3. Add `<name>` to the map-quiz rule in `shared/sync.json`, run
   `python3 shared/sync.py` (engine files; `nginx.conf` comes to every
   image anyway).
4. The CI caller and the rest of "Adding an image" in `/CLAUDE.md`.

Engine changes happen here and reach every map image through the sync;
check them in each (`node` tests, and the local browser harness where
there is one).
