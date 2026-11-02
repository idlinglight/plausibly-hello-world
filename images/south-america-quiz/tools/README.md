# south-america-quiz tools

Offline generator for the map data. Not part of the image (the Dockerfile
copies `site/` only); its outputs are committed:

- `site/map.svg`: one `<path id="<code>">` per quiz entry inside
  `<g id="countries">`, plus `<path id="land">` (all context land, merged).
  No styling in the file: the engine's `style.css` does that.
- `site/countries.js`: names, capitals, the state a territory belongs to
  (`of`), and the map's window/extent (`MAP`). `site/config.js`
  (hand-written) hands it and the English texts to the shared map-quiz
  engine.

Both carry a "generated, don't edit" header. Edit `countries.json` (codes,
names, capitals, which entries are clickable: the single source of truth)
or `build_map.py`, then regenerate.

`build_map.py` is this image's adapter: Natural Earth, French Guiana, the
border view, remote parts, the window and the quiz set. The geometry
(projection, clipping, shared borders, simplification, SVG writing,
`--check`) is the shared core in `shared/map-quiz/tools/mapgen`
(`shared/map-quiz/README.md`), which the script imports from there.

## Regenerate

```sh
mkdir -p /tmp/ne && curl -fsSL -o /tmp/ne/ne_50m_admin_0_countries.geojson \
  https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson
python3 -I images/south-america-quiz/tools/build_map.py /tmp/ne/ne_50m_admin_0_countries.geojson
python3 -I images/south-america-quiz/tools/build_map.py /tmp/ne/ne_50m_admin_0_countries.geojson --check  # files up to date?
node images/south-america-quiz/tools/data.test.mjs   # this image's data and config (Node 22.12+)
```

The engine's own tests (quiz rules, config contract, wheel replay) and
the generator core's live in `shared/map-quiz/tools/`; CI runs them all
(`.github/workflows/shared-sync.yml`), not `build_map.py --check` (its
input isn't committed).

Python 3.9+, standard library only. The script verifies the input's sha256
(`3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb`,
3 083 490 bytes: the same file europe-quiz pins) and stops on any other
file. Output is deterministic: re-running gives byte-identical files
(`--check` compares without writing). It prints sizes (raw, gzip -1 as
nginx serves it, gzip -9) and what it clipped, split and dropped.

## Data

[Natural Earth](https://www.naturalearthdata.com/) admin-0 countries,
1:50m, release v5.1.2 (2022-05-13), GeoJSON from the
`nvkelso/natural-earth-vector` repository. Natural Earth is **public
domain**; no attribution required (it's credited here anyway).

map.svg is about 66 KB (27 KB as served, gzip -1). The smallest quiz entry,
French Guiana, is about 23 px across at the full view on a 390 px phone in
portrait (16 px in landscape), so no entry gets a ring.

## Quiz set

`countries.json`: the 12 sovereign states (Argentina, Bolivia, Brazil,
Chile, Colombia, Ecuador, Guyana, Paraguay, Peru, Suriname, Uruguay,
Venezuela) plus **French Guiana**, an overseas region of France: 13
entries. The Falkland Islands are context land. Both are the owner's call
(2026-11-02). Membership is a data switch: `"quiz": false` makes an entry
context land (the Falklands' entry is there with it), `true` or no field
makes it clickable. A clickable Falklands entry would get a ring (its
`marker` is there already: 44 units across, about 16 px on a portrait
phone) and read "Falkland Islands (United Kingdom)". Flipping one means:

1. the field in `countries.json`, then regenerate;
2. `data.test.mjs`: the entry count, the sovereign/territory and
   Falklands-context assertions, the rings check (no rings today; FLK
   carries a marker) and the map.svg `FLK` check;
3. `site/index.html`: the static `0 / 13`, the `<meta name="description">`
   and the screen-reader paragraph ("twelve countries and French Guiana");
4. the README's row and the count in `/CLAUDE.md`'s note on this image.

- **French Guiana**: Natural Earth draws it as a polygon of France (`FRA`);
  the generator moves that polygon (picked by a point inland) into its own
  feature, `GUF` (its ISO 3166-1 code). `"of": "France"` puts the state
  after the name wherever the page names it: "French Guiana (France)" on
  the card and in misclick labels; the capital round asks "Cayenne".
  Martinique and the rest of France stay context land.
- **Names and capitals**: English short forms per the EU Interinstitutional
  Style Guide, diacritics kept (Brasília, Bogotá, Asunción).
- **Bolivia**: Sucre is the constitutional capital, La Paz the seat of
  government. The capital round asks **"Sucre / La Paz"**, the
  constitutional capital first: unique (no other entry has either city),
  and fair to someone who knows only one of the two; a misclick on Bolivia
  shows "Bolivia · Sucre / La Paz".

Context land (one merged, non-interactive path): Central America, the
Caribbean incl. Trinidad and Tobago and the ABC islands, the Falkland
Islands, South Georgia, the Antarctic
Peninsula, West Africa at the far right edge, and everything else that
isn't a quiz entry.

## Border view

Natural Earth's default layer shows de-facto administration; here it is
used as it is (no fix-ups besides the French Guiana split). Point checks
(`VIEW_CHECKS`) assert on every run:

Each point lies well inside the area it tests, at least 10 km from any
border or coast in the file, so vertex noise in a re-pin can't flip it:

- **Essequibo** (claimed by Venezuela) is part of Guyana, as administered:
  points in its north (Cuyuni-Mazaruni) and south (Rupununi) in `GUY`, one
  in Bolívar west of it in `VEN`.
- **New River Triangle** (claimed by Suriname) is part of Guyana, the
  **Litani–Marouini area** (claimed by Suriname) part of French Guiana,
  both as administered (a point in each claim's interior).
- **Southern Patagonian Ice Field**: the Argentina–Chile line as Natural
  Earth draws it, not adjusted: a point east of it and Lago Argentino in
  `ARG`, one west of it and Torres del Paine in `CHL`. 1:50m is coarse
  along the Andes: a town right at the border can land on the other side
  (Villa O'Higgins, Chile, falls 0.8 km inside `ARG`); not fixed, far
  below what the map shows.
- **Falkland Islands**: their own feature (`FLK`), context land; South
  Georgia (`SGS`) and Trinidad (`TTO`) context land too.
- French Guiana's interior is `GUF`, Suriname's `SUR`, the Galápagos
  (Santa Cruz) part of Ecuador.

## Map geometry

- Projection: Lambert azimuthal equal-area centred on 20°S 60°W (GRS80):
  the middle of the continent, so sizes stay comparable from Colombia to
  Tierra del Fuego. The formulas are mapgen's, checked against EPSG:3035's
  reference point on every run.
- Window (the full view, `0 0 1000 1422.3`): the bounding box of all quiz
  geometry except remote parts, plus 3 % margin. Remote parts (`REMOTE`):
  the **Galápagos** (Ecuador). The script fails if any other quiz geometry
  would fall outside the window, if an entry's largest polygon matches a
  remote rule, or if a rule matches nothing. The Juan Fernández Islands
  (Robinson Crusoe; Alejandro Selkirk isn't in the file) lie inside the
  window anyway.
- Galápagos: counting them for the window would make it 22 % wider (6 298
  instead of 5 145 km) and the whole map 18 % smaller on phones in
  portrait, where the width decides the scale. So they lie beside the
  window, at their real position (no inset) and part of Ecuador's shape: on
  screen at the full view on desktops and in landscape (where the height
  decides the scale and the view shows context to the side), off screen on
  phones and tablets in portrait. Panning stops at the window, so they are
  seen, and clickable, only while the zoom leaves room beside it. Making
  the Galápagos count: delete their `REMOTE` line and regenerate.
- **Easter Island** (Chile) is left out (`DROP`, same matching, every rule
  must match): it would lie in the outer, faded band of the extent (about
  x −394), a speck hardly seen that would still take clicks (the fade
  doesn't catch them).
- Not in Natural Earth at 1:50m, so nothing to place: Fernando de Noronha,
  Trindade and Martim Vaz, Sala y Gómez, San Félix and San Ambrosio, San
  Andrés y Providencia, Malpelo, Martín García.
- Extent (the viewBox): the window plus 60 % / 20 % of its width / height
  per side of context: the continent is tall, so wide screens show a lot
  beside it (60 %: about the room beside it on a 16:9 desktop), tall ones
  little above and below it. The page fades the outer half out. LAEA's
  corners reach far (about 31°N 118°W, 32°N 2°E, 46°S 154°W, 43°S 38°E),
  so `PREFILTER`, the lon/lat box that skips polygons early, is
  160°W–40°E, 90°S–36°N.
- Shared borders: vertices snap to a 0.1-unit grid; parts of one entry
  merge by cancelling shared segments; borders become shared arcs, so
  neighbours use identical vertices (no slivers or gaps).
- Simplification: none for quiz entries. Context-only arcs get
  Douglas-Peucker 0.2 units near the window and 1.5 units outside it,
  where context is only ever seen small; small islands below 0.3 units²
  (4 units² for context entirely outside the window) are dropped.
