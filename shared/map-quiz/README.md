# map-quiz engine

A map quiz as a static page: an inline SVG map, a question card, round
after round of "find this region". One engine for several images
(`images/europe-quiz`, `images/vienna-districts`,
`images/south-america-quiz`, `images/east-asia-quiz`, `images/japan-quiz`:
grouped rounds, `images/world-quiz`: Fuller's net, rounds with and
without the small states); each image brings its own data, texts and
map, the engine stays the same.

```
shared/map-quiz/
  site/             the engine: synced into each map image's site/
    main.js           map view (zoom, pan), input, HUD, persistence
    quiz.js           the rules (no DOM)
    contract.js       config checks (no DOM): main.js at start, node tests
    wheel.js          mouse wheel or trackpad? (no DOM)
    theme.js          light/dark, a classic script in <head>
    style.css         layout, theme tokens
    wiki.js           Wikipedia article URLs for config.js (no DOM; a
                      helper, main.js doesn't load it)
  tools/            not synced, not shipped
    mapgen/           generator core (Python 3.9+, stdlib), see below
    mapgen_test.py    python3 -I shared/map-quiz/tools/mapgen_test.py
    wikicheck.py      checks the data's Wikipedia titles online, by hand
                      only (never a build or CI), see below
    wikicheck_test.py python3 -I shared/map-quiz/tools/wikicheck_test.py
                      (offline, canned answers; by hand, not in CI)
    quiz.test.mjs     node shared/map-quiz/tools/quiz.test.mjs (rules)
    contract.test.mjs node shared/map-quiz/tools/contract.test.mjs
    wheel.test.mjs    node shared/map-quiz/tools/wheel.test.mjs
                      (+ wheel-fixture.json: recorded wheel events)
    wiki.test.mjs     node shared/map-quiz/tools/wiki.test.mjs
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
| `main.js`, `quiz.js`, `contract.js`, `wheel.js`, `theme.js`, `style.css`, `wiki.js` | synced | the engine: don't edit there (`wiki.js` only loads where `config.js` imports it) |

### index.html

- `<html lang="…" data-quiz="<image folder name>">`. `data-quiz`
  namespaces localStorage: `phw-<name>` (quiz state), `phw-<name>-theme`
  (theme override), so two map images on one origin keep apart. Without
  it the engine doesn't start, and `sync.py` (`require` in
  `shared/sync.json`) fails for an image listed for the engine.
- In `<head>`: `style.css` (then the image's own stylesheet, if any),
  then `<script src="theme.js"></script>` (classic, after the
  stylesheets: no flash of the other theme), `<script type="module"
  src="main.js"></script>`, and a `<meta name="theme-color">`.
- The element ids the engine uses: `map`, `card` (with a `.swatch`),
  `round`, `progress`, `correct`, `misses`, `prompt`, `prompt-kind`,
  `prompt-text`, `toast`, `controls`, `reset` (with `.btn-text`), `theme`
  (with `.icon-moon`, `.icon-sun`), `zoom-out`, `zoom-fit`, `zoom-in`,
  `label`, `safe` (main.js adds `attribution`, `prompt-sub`,
  `round-picker`, and `prompt-link` with `prompt-live` when the config
  asks for them). Start from europe-quiz's `index.html` and translate its
  text: title, description, `aria-label`s, the `sr-only` help paragraph,
  `noscript`, "Reset?". The engine overwrites the round label, prompt and
  the reset/theme button labels from the config once it runs. Keep the
  armed reset's word ("Reset?", `.btn-text`) short: on a 320 px screen
  about 40 px fit beside the zoom buttons (vienna-districts: "Echt?";
  europe's "Reset?" is 3 px over there, so the button groups touch).

### config.js

An ES module beside the data module; its default export:

```js
import { MAP, DISTRICTS } from './districts.js'; // generated
import { wikipediaUrl } from './wiki.js';         // optional, for rounds[].link

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
      link: (d) => wikipediaUrl('de', d.wiki), // optional: the prompt links there
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
    intro: { mouse: 'Klicke …', touch: 'Tippe …' }, // toast on every load, until the first interaction
    newGame: 'Neues Spiel …',                       // toast after a reset
    reset: 'Quiz zurücksetzen',                     // reset button label …
    resetArmed: 'Wirklich zurücksetzen? …',         // … while armed (3 s)
    mapError: 'Die Karte konnte nicht geladen werden …',
    // theme button: other = the theme a press switches to ('light' | 'dark'),
    // override = an override is stored (a press goes back to the system's)
    theme: (other, override) => ({ label: '…', title: '…' }),
    roundPicker: 'Runde wählen (beginnt von vorn)', // with roundPicker: its name and tooltip
    link: (asked) => `${asked} auf Wikipedia (neuer Tab)`, // with rounds[].link: its name and tooltip
  },
  attribution: 'Datenquelle: Stadt Wien – data.wien.gv.at', // optional
  view: { maxScale: 6, besideHud: true, panToCentre: true }, // optional, see below
  blockingOverlays: ['water'],           // optional, see below
  carryColours: true,                    // optional, see below
  roundPicker: true,                     // optional, see below
};
```

A round may also ask for groups of pieces instead of single ones
(optional fields, all per round; a Japan-like example):

```js
import { MAP, PIECES, ISLANDS, PREFECTURES } from './japan.js'; // generated

export default {
  map: MAP,
  items: PIECES,        // the map pieces: one <path id> each
  rounds: [
    { key: 'islands', label: 'Islands', prompt: 'Find',
      answers: ISLANDS,                 // [{ id, pieces: [item ids], marker?, size?, ...own }]
      lines: ['coast-main'],            // line overlays shown in this round
      ask: (a) => a.name, miss: (a) => a.name, done: ({ total }) => `All ${total} islands.` },
    { key: 'prefectures', label: 'Prefectures', prompt: 'Find', answers: PREFECTURES,
      lines: ['coast-main', 'coast-isles', 'borders-prefectures'],
      sub: (p) => `${p.kanji} · ${p.kana}`, subLang: 'ja', // second card line
      ask: (p) => p.name, miss: (p) => p.name, done: ({ total }) => `All ${total}.` },
    { key: 'capitals', label: 'Capitals', prompt: 'Find the prefecture whose capital is',
      answers: PREFECTURES, asked: (p) => p.capital !== p.name, // the others: misclicks only
      ask: (p) => p.capital, miss: (p) => `${p.name} · ${p.capital}`,
      missSub: (p) => p.kanji, subLang: 'ja', done: ({ total }) => `All ${total}.` },
  ],
  // text …
};
```

- **map**: `width`, `height` and the four `extent` numbers finite, sizes
  above 0 (the generated `MAP` is).
- **items**: one per map piece (a region: one `<path>` in map.svg).
  `id`: unique, letters, digits, `_ . -`, not
  starting with a digit, not `land`, `overlays`, `regions`, `markers`,
  `fade*`, and not an element id of `index.html` or another id in
  `map.svg` (ADM0_A3 codes, `d01` … all fine).
  `marker: [x, y]` (map units) + `size` (larger side of the region's
  bounding box, map units) draws a ring for a region too small to tap at
  the full view: a tap inside the drawn ring picks it, one in a wider zone
  only over sea, context land or that region itself; the ring hides once
  the region is 28 px across. Leave markers out for none (no ring layer).
- **rounds**: any number of kinds; rounds cycle through them (from a
  picked one on, with `roundPicker`), each round
  asks every asked answer once in its own shuffled order. Colours: A in
  even rounds, B in odd ones, so the map recolours round by round. Prompts
  must be unique within a round (`checkTexts` tests it). A saved game
  records the round keys: after a change to them (added, removed, renamed,
  reordered) stored games start over, as they do when a round's asked
  answers change, and (with grouped or subset rounds, whose saves carry a
  fingerprint of them) when any round's answers or asked answers change. `done({ total, misses })`: total is the number of
  answers that round asked.
- **rounds[].answers** (optional): the round's answers as groups of items,
  `{ id, pieces: [item ids], marker?, size?, ...own fields }`; `ask`,
  `miss`, `sub` … get the answer object. Without it every item is its own
  answer (and gets the item). Ids unique within the round (same id rules,
  minus the reserved list: answer ids never become element ids, so one
  may equal the id of one of its own pieces, e.g. `niigata` = `niigata` +
  `niigata-isles`, never another answer's piece, and ids may repeat
  across rounds); each piece in at
  most one answer of a round. A piece in no answer of the round is inert
  there: drawn as context land, never hit. An item in no round's answers
  fails the check (make it context land). Rings belong to answers: a
  grouped round takes `marker` / `size` from its answers (size = the
  larger side of the piece the ring sits on, not the whole group).
- **rounds[].asked** (optional): `(answer) => true | false`, which answers
  the round asks (default: all); the others stay clickable as misclicks
  with their label. A round must ask at least one.
- **rounds[].lines** (optional): ids of line overlays (`<path>`s in
  map.svg's `#overlays`, e.g. from `mapgen.boundary_lines`) shown in this
  round; the others are hidden. With `lines` (even `[]`) the round's
  pieces outline themselves in their own fill, so no hairline shows
  between the pieces of a group; the lines draw the outlines that count.
  Unique, not an item's id, not a blocking overlay.
- **rounds[].sub**, **subLang**, **missSub** (optional): `sub(answer)` is a
  second, smaller card line under the prompt (e.g. the name in its own
  script), `missSub(answer)` a second part of the misclick label;
  `subLang` (a language tag such as `ja`) tags both. Once any round has
  `sub`, the line is reserved in every round (empty where a round has
  none), so the card keeps its height. System fonts only; an image
  stylesheet can add a `:lang(ja)` font list.
- **rounds[].link** (optional): `(answer) => 'https://…'`, a page about
  the asked answer (e.g. its Wikipedia article; in a capitals round the
  capital's, whatever the round asks): the card's prompt text links there,
  opened in a new tab (Behaviour below). Absolute `https:` URLs without
  whitespace only (`contract.js` `linkError(url)`, the one rule for
  `checkTexts`, which fails on a bad one, and main.js, which links
  nothing else: a bad one, or a `link()` that throws, shows the prompt
  without a link and a console warning, once per answer). For Wikipedia,
  `wiki.js` (synced like the engine, no DOM, loaded only by a config that
  imports it) has `wikipediaUrl(lang, title)`: the article's URL as
  Wikipedia writes them (spaces as `_`, percent-encoded UTF-8 but for
  letters, digits and `- _ . ! ~ * ' ( ) , / :`, so `? # % & +` stay part
  of the title); it throws on a bad language code or no title, so
  `checkTexts` names the answer without one. A round without `link` shows plain
  text. Once any round has `link`, `text.link` is needed: `(asked text) =>
  string`, the link's accessible name and tooltip, e.g. ``(asked) =>
  `${asked} on Wikipedia (opens a new tab)` ``.
- **attribution**: a credit line where it never meets the HUD: under the
  controls in portrait (they move up for it), the bottom-left corner in
  landscape. The full view stays clear of it in both. Fits about 50
  characters on a 320 px phone.
- **carryColours** (default `true`): colours carry over from round to
  round (each round recolours the map). `false`: every round starts
  blank, so coloured means found in this round (e.g. when a round leaves
  some clickable pieces unasked or inert, which would otherwise start the
  next round partly coloured).
- **roundPicker** (default `false`): the card's round label opens a list
  of the rounds (each by its `label`, the current one chosen); picking one
  starts a fresh round of it (Behaviour below), so a player can go
  straight to a later kind instead of finishing every round before it.
  Needs `text.roundPicker` (the list's accessible name and tooltip, e.g.
  'Pick a round (starts it fresh)'), two or more rounds and each `label`
  once. Its chevron costs the card's top row about 9 px; where the row
  then overflows, the card fits it as any other (Behaviour: top row).
- **view.maxScale**: maps are 1000 units wide; at most this many CSS px
  per unit at the closest zoom (default 12, europe; a city map needs
  less), but always at least 4× the full view.
- **view.besideHud**: in landscape, fit the full view left of the card
  and the controls column. Default false: the card covers the full view's
  top-right corner, fine where that is context land (europe: Russia), not
  for a map whose regions reach that corner.
- **view.panToCentre** (default false): the map may be panned until any
  point of the full view sits at the centre of the free area, at every
  zoom, the full view included (by default, at the full view, the map
  moves at most within the free area, so an edge region never reaches the
  centre). For a one-handed
  pinch about the screen's centre, e.g. on a world map: drag the region
  to the centre first. The default range stays a subset; fit (button, `0`)
  returns to the full view.
- **blockingOverlays**: ids of overlays in `map.svg`'s `#overlays` (each a
  `<path>`) whose area swallows clicks and taps like the background: no
  answer, no misclick, no hover on the region beneath. Their outline
  counts too, at its drawn width (`--overlay-stroke`). Left out (europe):
  every overlay is see-through, a click on it picks the region beneath.
  A drawn ring still wins over a blocking overlay; in a ring's wider zone
  the overlay counts as sea. Unique, not an item's id; main.js stops with
  `text.mapError` if one isn't an overlay `<path>`.

`contract.js`: `checkConfig(config)`, `roundSpecs(config)` (the rounds
as the rules need them: answers, asked ids, the config object per
answer) and `checkTexts(config)` (per round: ask, sub, link and
`text.link` for every asked answer, miss and missSub for every answer,
done; for an image's node test). At start main.js runs `checkConfig`, `roundSpecs` and checks
`data-quiz`; on a failure the page shows
`text.mapError` (or a built-in English line if that text is unusable) in
the toast, sets `data-ready="error"`, and the error names the field in the
console. (A `config.js` that doesn't load at all, a syntax error say,
stops main.js before it runs: the browser console shows it.)

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
  <path id="water" d="…"/>        (clicks go to the region beneath, or nowhere
                                  if config.blockingOverlays names it)
  <path id="coast-main" d="m…"/>  line overlays (open subpaths, rounds[].lines)
</g>
</svg>
```

`#overlays` may also hold an `<image>` (japan-quiz: `<image id="relief"
href="relief.png" …>`, a shaded relief, written by the image's adapter
after `mapgen.map_svg`): drawn in document order with the paths, never
hit (`#overlays` has `pointer-events: none`), never a line or a blocking
overlay (those must be paths), styled by its id in the image's
stylesheet. Its `href` is relative: it resolves against the page, and
`img-src 'self'` allows it.

No styling in the file. Every id once, none of the page's (`index.html`)
nor `markers` / `fade*`: the engine checks when it loads the map. An
overlay a round lists in `lines` gets class `line` (a stroke only, the
region outline's hairline) and is hidden (class `off`) in the rounds that
don't list it. It
finds the regions' group from their shapes (each a `<path>`; class
`regions` is added), draws a fade at the edge of the extent when there is
context around the window (`MAP.extent` starts below 0), and the rings.

### Styling

Tokens on `:root` in `style.css`, each defined three times (light;
`@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`;
`:root[data-theme="dark"]`): `--sea` (page background, also beyond the
drawn extent; a map without sea sets its plain background here, as
vienna-districts does), `--land`, `--land-line`, `--region`, `--region-hover`,
`--border`, `--a` / `--b` (+ `-hover`), `--miss`, `--ring`, panel and text
colours; `--water` (overlay fill and outline, default `--sea`) and
`--overlay-stroke` (overlay outline width in map units, e.g. `1.2px`,
scales with the map; default 0); `--inert` / `--inert-line` (pieces in no
answer of the round, default `--land` / `--land-line`). Classes on
`#card`: `.row-tight`, `.row-wide`, `.row-wrap` (top row, Behaviour). Classes on the
regions: `.inert` (that piece this round), `.seamless` on the group in a
round with `lines`; line overlays: `#overlays .line`, hidden ones `.off`
(e.g. heavier region lines in one round: `[data-round="…"] #borders-…`
in the image's stylesheet). An image overrides them in its own
stylesheet, linked after `style.css`, in the same three places; one
overlay can be styled by its id. `theme.js` copies `--sea` into the
theme-color meta.

## Behaviour

- `map.svg` is fetched and inserted inline (gzip and MIME already covered
  by `nginx.conf`); the viewBox follows a camera, so strokes stay crisp and
  a tap is tested against the real shapes.
- Rounds cycle through `config.rounds`, each asking every asked answer
  once, shuffled (a round never opens with an answer sharing a piece with
  the one that closed the last, unless every answer does). A correct pick
  colours all pieces of the answer (A in even rounds, B in odd ones: the
  map recolours round by round, blank only after a reset); colours are
  per piece, so pieces a round doesn't ask (inert, or not asked) keep
  theirs. With `carryColours: false` the map is cleared as each round
  starts, right after the last answer's pulse begins. A misclick (any other answer of the round: found, not yet, or
  not asked) counts, blinks all its pieces and shows the round's `miss`
  label for 1.5 s. A click on the sea, context land, an inert piece or a
  blocking overlay does nothing. Hover lights every piece of an answer.
  Reset takes two presses (the first arms it for 3 s).
- Round picker (`roundPicker`): the round label is the face of a native
  `<select>`, invisible over it and larger (a 38 px high target inside
  the card, which keeps its size), with a chevron after the label; phones
  show their own picker. Picking a kind starts a fresh round of it at
  once, no confirmation (choosing in a list is deliberate; closing it
  changes nothing, nor does picking the current kind): round r moves on to
  the first round index after r of that kind (`quiz.jumpTo`), so the
  round has that index's colour (A even, B odd) and `?seed` shuffle, and
  the cycle carries on from it. The picked round starts on a blank map,
  whatever `carryColours` says (with an even number of kinds it may have
  the left round's colour, and carried colours would look found); the
  counters (✓ ✗) run on, as from round to round (reset zeroes them); the
  round's misclicks start at 0; it never opens with the answer found last
  (also right after a round ended).
  The misclick label, marks and toasts of the left round go. The save
  format is unchanged (the round index says it all): older saves restore,
  and a picked round survives a reload. Keyboard: Tab reaches it first;
  Space, Enter, F4 or Alt + ↓ open the list, where the browser's own
  popup takes the keys (arrows and Enter choose). On the closed picker
  every other plain key is cancelled, map or no map, so no stray key
  ever leaves a round (letters, Home / End, Page Up / Down and arrows
  would change a closed select at once on Windows); the arrows and
  `+ - 0` still pan and zoom the map. Screen
  readers get a combo box named by `text.roundPicker` (the visible label
  is hidden from them).
- Prompt link (`rounds[].link`): the asked name on the card is a link,
  `target="_blank"`, `rel="noopener noreferrer"` (the page sends no
  referrer anyway), so a lookup opens a new tab and the game tab stays as
  it was: no answer, no counter, nothing saved. Nothing is fetched or
  prefetched from the linked site until the player follows the link (the
  CSP is unchanged: a followed link is no request of the page). The name
  looks as without the link (text colour, no underline at rest); a small
  "opens a new tab" icon after it (a box and an arrow, 13 px, thin lines
  in the text colour) says it is a link. Hover (a mouse) underlines the
  name, keyboard focus too, with a focus ring. A long name shrinks and is
  cut with an ellipsis before the icon, which stays; the card keeps its
  size. Where
  the top row is one line, the round picker's larger target overlaps the
  top 7 px of the prompt line and stays on top there (a near miss opens
  the list, not a tab). Keys:
  Tab reaches the link after the round picker, before the controls;
  Enter follows it; `+ - 0` and the arrows still zoom and pan from it.
  Screen readers: the live region moves from `#prompt` to an sr-only copy
  of the prompt (`#prompt-live`: prompt kind, asked text, the sub-line),
  so each new question is announced as without the link; the link itself
  is named by `text.link`. In a round without `link` the name is plain
  text: no href (not focusable), no icon, hidden from screen readers
  (`#prompt-live` says it).
- Rings (optional, per round's answers): a tap inside the drawn ring
  picks it, a tap in the wider zone around it only over sea, context
  land, an inert piece or that answer itself (never over a neighbour);
  the nearest ring wins. A ring shows the colour all its pieces share.
  Rings shrink at low zoom (phones) and hide once their piece is 28 px
  across; they are rebuilt when a round's ring set differs.
- Toasts under the card: the intro (`text.intro`) shows on every page
  load, also when a saved game resumes (a reload is how to read it
  again), and stays until the first interaction, a press anywhere on the
  page (map or controls), a wheel or pinch, or a key, and then fades; the
  round-end toast fades after 4 s, reset's after 2.5 s; a newer toast
  replaces the one shown.
- Answering needs a pointer (click or tap); keys only zoom and pan. Zoom:
  pinch (touch, trackpad), mouse wheel and ctrl + wheel (at the cursor),
  buttons, `+ - 0` keys. Pan: drag, a trackpad's two-finger scroll, arrow
  keys. A press that moves more than 5–10 px is a pan, never a click. Per
  axis the map keeps covering the free area where it is larger and stays
  inside it where it is smaller; with `view.panToCentre` it may also move
  until any of its points reaches the centre.
- Wheel events are classified per gesture as trackpad or mouse by
  `wheel.js` (DOM-free; rules from real macOS recordings in Safari,
  Chrome, Firefox at 100 % and 125 % zoom: trackpads send whole CSS or
  device pixels, mice fractional steps or lines). `tools/wheel.test.mjs`
  replays those recordings (`tools/wheel-fixture.json`); re-record and
  extend it when a device misbehaves.
- The full view fits the window around all regions, between the card and
  the controls in portrait; context drawn around the window fades out, so
  tall or wide screens show map. Two layouts (`min-aspect-ratio: 4/3` in
  `style.css` and `main.js`); in landscape under 390 px high (phones held
  sideways; under 410 px while the card's top row takes two lines) the
  controls' two groups stand side by side, three buttons high, so they
  stay clear of the card.
- The card's top row (round label, progress, counters) fits the card.
  Where it would overflow (a 320 px phone, a long label, three- or
  four-digit counters, the round picker's chevron), main.js (`fitRow`,
  when the label or a number's length changes, and on a resize) keeps
  the first of these on `#card` that
  makes it fit: `.row-tight` (narrower letter-spacing on the label);
  in landscape `.row-wide` (the card at least 260 px wide: 36vw is 204 px
  on a 568 px screen), alone or with `.row-tight`; `.row-wrap` (the
  counters on a line of their own: the card grows by 20 px, the toast
  moves down with it and the full view is measured around it, after a
  camera animation in flight has ended), with
  `.row-tight` if still needed. Where the row fits, none applies and
  nothing changes. Sized for a world map: a 14-character label,
  `123 / 197` and `✓ 1234 ✗ 123` fit on a 320 px phone held either way.
- Theme follows the OS; the toggle stores the other theme, pressing again
  clears it, and an override that matches the OS is dropped (`theme.js`,
  a classic script in `<head>`: no flash).
- `?seed=<int>` makes the shuffles reproducible (stored state with another
  seed is replaced). State on `<html>`: `data-round` (the round's key),
  `data-progress`, `data-zoom`, `data-wheel`, `data-theme`,
  `data-theme-pref`, `data-ready` (`1`, or `error`). Quiz state lives in
  localStorage (optional: blocked storage just means no resume).

## Generator core: mapgen

Python 3.9+, stdlib only, deterministic (modules: `build` pipeline,
`geometry`, `projection`, `polyhedral` Fuller's net, `lines` boundary
lines, `svg` path text, `output` pins and emit). An image's
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
mb = mapgen.MapBuilder(project, window, region_ids, grid=10)  # + region_tol=0.25 for dense input
for rid, poly in regions:   mb.add_region(rid, poly)   # mapgen.parse_wkt / polys_of
for poly in context:        mb.add_context(poly)       # optional
for poly in water:          mb.add_overlay("water", poly)
res = mb.build(keep_islands=ringed_ids)
assert res.stats["crossings"] == 0  # (raise BuildError) when region arcs are simplified
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
  `keep_islands`), context-only arcs are simplified (`context_tol`,
  `far_tol` beyond `far_gap`), overlays get `overlay_tol` (and drop rings
  below `min_island` too) and stay outside the shared topology. Region
  arcs keep every vertex unless `region_tol` is set (Douglas-Peucker on
  the shared arcs, so neighbours stay gap-free): europe's Natural Earth
  data is coarse enough as it is, city data densified to centimetre
  steps (vienna-districts) is not.
  Simplification can make arcs cross; `res.stats["crossings"]` counts
  them (the report prints it; europe's 5 are all in context land) and an
  adapter that simplifies region arcs should require 0:
  `repair_crossings=True` simplifies the arcs of every crossing again
  with half their tolerance, down to their own points, until none is
  left (`stats["repaired"]`; crossings the snapping itself made stay, a
  finer grid helps there;
  `mapgen.crossing_pairs(arcs)` lists them). `region_tols={rid: tol}`
  gives single regions their own tolerance (an arc takes the smallest of
  its regions'), e.g. finer outlines for small states people zoom in on.
  A region lost to the grid keeps its outline at 10× finer resolution.
- `mapgen.cut_cells(poly, xs, ys)` cuts a polygon (lon/lat or projected)
  along vertical and horizontal lines into `{(i, j): polygon}` cells; the
  cells share their cut vertices exactly, so an adapter can hand a part
  of one feature to another (a border-view fix-up) and the rest still
  merges; the lines run across the whole feature. `mapgen.clip_box(poly,
  box)` → `(inside, outside)` moves only what lies inside a rectangle.
  Either way the new vertices also belong into the neighbours whose border
  they lie on (`mapgen.node_points(polys, points)`), and
  `mapgen.t_junctions({fid: polys})` lists every vertex lying on another
  feature's edge without being one of its vertices (an adapter that cuts
  asserts none: else arcs come out one-sided, with slivers or gaps).
- Line overlays along the region edges (for `rounds[].lines`): the result
  keeps the shared topology it drew the paths from, `res.arcs`
  (simplified arcs, integer points in 1/`res.grid` units) and `res.topo`
  (`{fid: [[arc refs] per ring]}`, `~i` = arc i reversed; a region lost to
  the grid is not in it). `mapgen.boundary_lines(res, group_of,
  inner=True, outer=True)` chains the edges whose two sides fall in
  different groups into polylines, each edge once, deterministic:
  `group_of` maps region ids to any group key; context land, ungrouped
  regions and nothing count as outside. `inner`: edges between two
  groups (borders), `outer`: between a group and the outside (coasts,
  edges against context land or ungrouped regions). Identity grouping
  (`{rid: rid}`) gives every region edge once (vienna-districts'
  `#borders`). `mapgen.lines_d(lines, res.dec)` writes them as open
  subpaths; put that into `res.overlays[oid]` before `map_svg`. A
  grouped region lost to the grid raises BuildError (it has no shared
  edges: leave it ungrouped, or use a finer grid). The lines sit on the
  region edges and are never simplified on their own; a coast shared by
  two line overlays is drawn twice, so emit each edge in one overlay
  where size matters.
- Polyhedral maps (`mapgen.polyhedral`): the sphere on an icosahedron's
  faces, laid out as a net; `AIROCEAN` is Buckminster Fuller's Dymaxion
  net (his 1954 orientation, all 12 vertices in the sea; faces 9 and 16
  split so the continents stay whole), in Robert W. Gray's numbering and
  coordinates (edge 1, x right, y up). Per-face transforms: `"fuller"`
  (Gray's exact equations, 1995; the default), `"gnomonic"`, `"snyder"`
  (Snyder's equal-area polyhedral, 1992). A net can't be projected vertex
  by vertex, so the adapter splits each lon/lat polygon and feeds the
  parts, already planar, to a MapBuilder with `Identity()`:

  ```python
  net = mapgen.Polyhedral("fuller")          # scale=1: unit edges; self_test()
  window = mapgen.Window([p for _, tri in net.outline() for p in tri], 0.01, 1000.0, (0, 0))
  mb = mapgen.MapBuilder(mapgen.Identity(), window, ids, grid=10)
  for rid, polys in features:                 # one feature's polygons together:
      for poly in mapgen.stitch_antimeridian(polys):   # Natural Earth's +-180 seams match up
          for part in net.split(poly):        # clipped per net piece on the sphere
              mb.add_region(rid, part)
  marker = window.to_view(*net(lon, lat))     # a single point
  ```

  `split` clips each ring against the net's pieces (great-circle sides,
  Sutherland-Hodgman on the sphere: every ring must fit in a hemisphere,
  else BuildError) and computes each crossing of a fold once, from the
  edge's end points, so the parts on two pieces that meet in the net share
  those vertices exactly and the builder's dissolve merges them; across a
  cut they stay apart (two rings). `densify` (default 1 degree) adds
  lon/lat-linear points to long segments first. `outline()` gives the
  net's triangles (the sea's shape), `edges()` its folds, cuts and the
  split inside face 9. Sources: Gray's published vertex coordinates and
  net (rwgrayprojects.com), d3-geo-polygon's `geoAirocean` (ISC) as a
  cross-check of the vertices (within 0.25 arc seconds), Philippe
  Rivière's public-domain port of Gray's equations (d3-geo-polygon
  `grayfuller.js`) for the formulas; the tests compare 12 points with
  values from Gray's own procedure.
- Feed polygons in a fixed order: the output depends on it, and the same
  inputs in the same order give byte-identical files. `emit` writes, or
  with `check` compares and returns 1 on a difference, and prints sizes
  (raw, gzip -1 as nginx serves it, gzip -9).

## Wikipedia titles: wikicheck

An image may link the asked names to Wikipedia: its source-of-truth JSON
holds the article titles (`wiki`, `capital_wiki`, …), `build_map.py`
passes them into the data module and fails where one is missing or
malformed (`mapgen.wiki_title_error`: spaces, no `_ # ? |`, no padding),
and `tools/data.test.mjs` checks the same, all offline.
`wikicheck.py` (stdlib) checks the titles against the live Wikipedia and
Wikidata APIs: the page exists, the title is canonical (no redirect), no
disambiguation page, and its Wikidata item is the expected one, or, for
a capital, a current capital of the expected item (P36 / P1376). It is
run by hand through a thin per-image entry point
(`images/<name>/tools/wiki_titles.py <pinned input>`, `--suggest`
proposes titles from Wikidata); world-quiz and japan-quiz have one, each
`tools/README.md` ("Wikipedia titles") the method, date and special
cases.

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
   image anyway; it checks `data-quiz` and updates
   `shared/sync-manifest.json`), commit all of it.
4. The CI caller and the rest of "Adding an image" in `/CLAUDE.md`.

Engine changes happen here and reach every map image through the sync;
check them in each (`node` tests, and the local browser harness where
there is one).
