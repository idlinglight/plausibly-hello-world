# germany-quiz tools

Offline generator for the map data. Not part of the image (the Dockerfile
copies `site/` only); its outputs are committed:

- `site/map.svg`: `<path id="land">` (all context land, merged), the
  context land's relief (`<image id="relief-context"
  href="relief-context.png">`), one `<path>` per Land inside
  `<g id="states">`, and in `<g id="overlays">` the Länder's relief
  (`<image id="relief" href="relief.png">`, first) and the lakes
  (`lakes`, water). No
  styling in the file: the engine's `style.css` (and the image's
  `germany.css`) does that.
- `site/states.js`: the map's window/extent (`MAP`) and the 16 Länder
  (`STATES`) with their names, capitals, Wikipedia titles and Bremen's
  ring. `site/config.js` (hand-written) hands them and the German texts
  to the shared map-quiz engine.
- `site/relief.png`, `site/relief-context.png`: the shaded relief (below,
  "Relief").

The first two carry a "generated, don't edit" header. Edit `states.json`
(names, capitals, Wikipedia titles, a point inside each Land: the single
source of truth) or `build_map.py`, then regenerate.

`build_map.py` is this image's adapter: Natural Earth, the checks, the
window, the context land, the lakes, the quiz data and the relief's
parameters. The geometry (projection, clipping, shared borders,
simplification, SVG writing, `--check`) and the relief shading
(`mapgen.shaded_relief`) are the shared core in
`shared/map-quiz/tools/mapgen` (`shared/map-quiz/README.md`), which the
script imports from there.

## Regenerate

```sh
mkdir -p /tmp/ne && for f in ne_10m_admin_1_states_provinces ne_10m_lakes; do
  curl -fsSL -o /tmp/ne/$f.geojson \
    https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/$f.geojson
done
# ETOPO 2022 subset (158 MB, about 2.5 min; ERDDAP answers 503 now and then, hence the retries)
curl -fsS --retry 8 --retry-delay 30 --retry-all-errors -o /tmp/ne/etopo_2022_15s_germany.asc \
  'https://coastwatch.pfeg.noaa.gov/erddap/griddap/ETOPO_2022_v1_15s.esriAscii?z%5B(44.75):1:(57.25)%5D%5B(-1.0):1:(22.0)%5D'
python3 -I images/germany-quiz/tools/build_map.py /tmp/ne/ne_10m_admin_1_states_provinces.geojson \
  /tmp/ne/ne_10m_lakes.geojson /tmp/ne/etopo_2022_15s_germany.asc
python3 -I images/germany-quiz/tools/build_map.py /tmp/ne/ne_10m_admin_1_states_provinces.geojson \
  /tmp/ne/ne_10m_lakes.geojson /tmp/ne/etopo_2022_15s_germany.asc --check   # files up to date?
node images/germany-quiz/tools/data.test.mjs    # this image's data and config (Node 22.12+)
node images/germany-quiz/tools/links.test.mjs   # which title each round links
```

The engine's own tests (quiz rules, config contract, wheel replay) and
the generator core's live in `shared/map-quiz/tools/`; CI runs them all
(`.github/workflows/checks.yml`), not `build_map.py --check` (its
inputs aren't committed).

Python 3.9+, standard library only (about 10 s). The script verifies its
three inputs and stops on any other file:

| File | Bytes | sha256 |
| --- | --- | --- |
| `ne_10m_admin_1_states_provinces.geojson` | 40 726 851 | `22d0e3ad85eb3e27f17cabf8ba2d50e554fbc27a87796ff891d958185da62fb5` |
| `ne_10m_lakes.geojson` | 5 043 554 | `2d036f53dedec578001c5c30c2959ee7d4eebc1306900fa4367c49929ec8f2d9` |
| `etopo_2022_15s_germany.asc` | 157 837 395 | `cbda9149d8e8900fa7c283ce3cb5be824053d15701b9892a3dbe278572e124f8` |

(The first two are the files japan-quiz pins.) Output is deterministic:
re-running gives byte-identical files (`--check` compares without
writing; for the PNGs it compares the decoded pixel data when the bytes
differ, as another zlib build may compress the same pixels
differently). It prints sizes (raw, gzip -1 as nginx serves it, gzip -9)
and what it checked.

## Data

[Natural Earth](https://www.naturalearthdata.com/) release v5.1.2
(2022-05-13), GeoJSON from the `nvkelso/natural-earth-vector`
repository. Natural Earth is **public domain**; no attribution required
(it's credited here anyway).

- Länder: admin-1 states/provinces, 1:10m, the 16 features with
  `adm0_a3` DEU, matched by `iso_3166_2` (`states.json` `iso`); the build
  checks Natural Earth's `name` against `ne_name` (Natural Earth's
  `name_de` is the full name for Bremen, "Freie Hansestadt Bremen"; its
  `name` is the short one the quiz uses).
- Context land: every other admin-1 feature of the same file that
  reaches the extent (504 polygons of 1,518 near Germany), merged into one
  shape. Using the same file on both sides keeps the national border one
  line: the Länder and their neighbours share every border vertex; the
  build asserts no T-junction (`mapgen.t_junctions`) among the Länder and
  all context polygons near Germany. Not the 1:50m admin-0 file the other
  map images use for context: its borders don't meet admin-1's.
- Lakes: Natural Earth's 1:10m lakes in Germany (`LAKES`, 13 of them:
  the Bodensee in two features, Müritz, Schweriner See and nine unnamed
  ones, each checked to lie on the Länder it names). Every lake whose
  bounding box lies within Germany's (`LAKE_BOX`) must be listed or
  explicitly ignored (`LAKE_IGNORE`: Lake Geneva, the IJsselmeer,
  Lauwersmeer, Dąbie, all outside Germany), so a changed source can't
  drop one silently. The file has no Chiemsee, Starnberger See or
  Ammersee (too small for 1:10m), so they aren't drawn.

At 1:10m the coast and the borders are generalised to steps of roughly
0.5–2 km: fine at the closest zoom (`config.view.maxScale` 3, about
4.4 px per km). Some details are missing from the source: Hamburg's
Neuwerk and Scharhörn islands, the smaller Halligen, the Vennbahn (the
Belgian railway strip with German enclaves west of it; Natural Earth
draws Mützenich and its neighbours as part of Nordrhein-Westfalen).

Elevation: [ETOPO 2022](https://www.ncei.noaa.gov/products/etopo-global-relief-model)
v1, NOAA National Centers for Environmental Information (NCEI): a 15"
global relief model of land and sea floor. Cite as: NOAA National
Centers for Environmental Information, 2022: ETOPO 2022 15 Arc-Second
Global Relief Model, doi:10.25921/fd45-gt74. A work of the U.S.
government; the dataset's licence note says it "may be used and
redistributed for free but is not intended for legal use, since it may
contain inaccuracies" (no warranty). No attribution required on the page
(credited here). The pinned file is a subset from CoastWatch's ERDDAP
(dataset `ETOPO_2022_v1_15s`): every cell, i.e. the full 15" (about
0.46 km north–south, 0.27–0.33 km east–west here), of 44.75–57.25°N,
1.0°W–22.0°E (the whole extent and a margin), as ESRI ASCII grid (5521 ×
3001 cells, cell centres, rows from north to south, values in metres).
ERDDAP writes no timestamp into this format: two downloads (2026-11-26)
were byte-identical, so it pins by sha256 like the Natural Earth files.
Not committed (158 MB).

## Choices

No geometry is moved, cut or dropped: Natural Earth's Länder are drawn
as they are. Point checks (`states.json` `point`, `VIEW_CHECKS`,
`EMPTY_CHECKS`) assert on every run what the map shows:

- **Bremen** is two parts, the city and Bremerhaven, both in Bremen's
  shape (one `<path>`).
- **Islands**: every Land keeps all its islands (`keep_islands`), down
  to Helgoland and its Düne (0.7 km²).
- **Büsingen am Hochrhein** (a German exclave in Switzerland, 7.6 km²):
  Natural Earth draws it as part of Schaffhausen, so it is Swiss context
  land here. It would be about 3 px across at the closest zoom.
- **Jungholz** and the **Kleinwalsertal** are Austrian and drawn so
  (context land).
- **Bodensee**: its border is undefined (no treaty for the Obersee;
  Austria holds it a condominium, Switzerland a median line). Natural
  Earth splits the lake area along a line through the middle among the
  admin-1 features around it: the Überlinger See and the northern Obersee
  to Baden-Württemberg, a part off Lindau to Bayern, the southern Obersee
  to Thurgau, St. Gallen and Vorarlberg; the Untersee between
  Baden-Württemberg and Thurgau. The lake is drawn as
  water above it (the `lakes` overlay, see-through), so a tap on the
  lake picks what Natural Earth has beneath: Baden-Württemberg or Bayern
  in their part, nothing (context land) in the Swiss and Austrian part.
- **Berlin** is a hole in Brandenburg, as in the source.
- **Usedom** and the Oder: the German part of Usedom is
  Mecklenburg-Vorpommern's, the Polish part context land.

## Map geometry

- Projection: Lambert azimuthal equal-area centred on 51°N 10.5°E,
  GRS80: the middle of Germany, so north is up there; equal-area keeps
  the Länder's sizes comparable.
- Window (the full view, `0 0 1000 1334.7`; 1 unit ≈ 0.68 km): the
  bounding box of all Länder plus 3 % margin.
- Extent (the viewBox): the window plus 50 % of its width per side (wide
  screens and desktops show Benelux, France, Poland and Czechia fading
  out) and 20 % of its height (portrait phones show about that much above
  and below Germany: Denmark, the Alps), `-500 -266.9 2000 1868.5`.
- Shared borders: vertices snap to a 0.1-unit grid; parts of a Land merge
  by cancelling shared segments; borders become shared arcs, so
  neighbours use identical vertices.
- Simplification: none for the Länder. Context-only arcs get
  Douglas-Peucker 0.2 units near the window and 1.5 units outside it.
- Arc crossings: 2, both made by the snapping to the 0.1 grid (the
  tri-point of Baden-Württemberg, Rheinland-Pfalz and France on the Rhine,
  and a stretch of Mecklenburg-Vorpommern's coast by Rügen), each smaller
  than the grid, so nothing shows; a 0.01 grid has none on the Länder but
  a bigger file. The build expects exactly 2 (`CROSSINGS`), so a new one
  stops it.
- Closest zoom: `config.view.maxScale` 3 px per unit (about 4.4 px per km,
  a little closer than japan-quiz's 2.7; the engine's floor is 4× the
  full view, about 2.6 on a 1440 × 900 desktop). `relief.png`
  has 1 px per unit, so it is magnified 3× there (japan-quiz: 2.4×).
- `besideHud`: in landscape the full view fits left of the card and the
  controls (Germany is taller than wide, so this costs little).
- Ring: Bremen only (`RING`). At the full view on phones (0.26–0.37 px per
  unit) Bremen's city part has a bounding box of 13–18 × 9–12 px but is a
  narrow band along the Weser, Bremerhaven 3–4 × 5–8 px: too small to
  tap. The next smallest, Hamburg and Berlin, are compact and 15–24 px
  across, and get none. The marker sits at the centre of the city part's
  bounding box, and its `size` is that part's larger side (48.1 units),
  not the whole state's (97.9: with Bremerhaven, which would hide the
  ring at about half the zoom); the engine hides the ring once that is
  28 px across (from about 0.58 px per unit: shown on a 1280 × 800
  desktop, hidden on 1440 × 900). The ring shows in the states round
  only: the capitals round never asks Bremen, so there it would only
  draw misclicks (and take taps from Niedersachsen around it).
  `config.js` gives that round the states as one-piece answers without
  `marker` / `size` (a grouped round takes its rings from its answers;
  no engine change).

## Relief

The two PNGs shade the terrain so lowlands and uplands can be told apart
(the North German Plain flat; the Harz, the low mountain ranges, the
Black Forest, the Alps along the southern edge rugged). Japan-quiz's
look (`mapgen.shaded_relief`, the same parameters: Horn's gradient,
vertical exaggeration 5, light from the top left at 45°, darkness 0.8 ×
facing away + 0.9 × steepness up to black at alpha 0.55, highlights up to
white at alpha 0.3, 32 alpha steps, sea as 0 m), on ETOPO's full 15"
grid. `build_map.py`, `RELIEF_*`:

- `relief.png`: on the Länder only, over the window, 1 px per map unit
  (`RELIEF_PPU`, 0.68 km per pixel; 1000 × 1335 px, about 340 KB, decoded
  about 5 MB), ending at the coast and at the national border (coverage
  from the drawn rings, as in japan-quiz). First in `<g id="overlays">`:
  above the Länder, below the lakes; `#overlays` is never hit, so a tap
  on a mountain picks the Land beneath.
- `relief-context.png`: the context land's, over the whole extent, 0.5 px
  per unit (`RELIEF_CONTEXT_PPU`; 1000 × 935 px, about 230 KB, decoded
  about 4 MB). Clipped at the extent like the land, it fades out with it
  under the page's fade. Drawn between `<path id="land">` and the Länder's
  group, so the Länder's opaque fills cover whatever of it lies under
  them: its pixels are those touching context land, at the coverage of
  all land (`mapgen.shaded_relief`'s `within`), so they are whole up to
  the national border and the Länder cut them off exactly there.
  `germany.css` gives it `pointer-events: none`, like `#land`.
- Border seam (fixed 2026-11-26, review): with both images above the
  Länder, each pixel along the border was covered by two partial-alpha
  pixels of different size (one of each image), lighter than either
  image alone (alpha about 0.47 instead of 0.55 at the darkest), and the
  coarse one also shaded a strip of the Länder: closest-zoom shots on the
  Alps border before and after the change differ by up to about 36 of
  255 grey levels, only along the border; barely visible by eye. Now only relief.png's
  own partial pixel (≤ 3 px at the closest zoom) meets the border, as at
  any coast.
- `germany.css` draws both with plain alpha (`--relief-opacity`, softer
  in dark mode), no blend mode (japan-quiz's reason: nothing to blend
  with over the sea, the page background outside the SVG, so a blend
  would leave a light fringe along the coasts).
- Why two images (2026-11-26): one image over the whole extent costs far
  more than japan-quiz's 330 KB, as almost all of it is land: 2.8 MB at
  1.5 px per unit (about the 15" cells), 1.26 MB at 1, 700 KB at 0.75.
  The Länder alone at 1 px per unit are japan-quiz's size; the context
  land, muted and faded, gets half that density. At the full view the
  difference doesn't show; zoomed in, the context land is softer than the
  Länder.

## Names and capitals

The common short German names (`states.json` `name`): Bayern,
Nordrhein-Westfalen, Baden-Württemberg, Thüringen, Bremen (not "Freie
Hansestadt Bremen"), Hamburg, Berlin, in the usual alphabetical order
(ü sorted as u). Capitals by their common names: München, Hannover,
Düsseldorf, Wiesbaden, Saarbrücken, …. Berlin, Hamburg and Bremen are
city states, their own capitals: the capitals round asks the other 13
(`capital_differs`), and a pick of a city state there is a misclick
whose label is the name alone. Ids are ASCII (`baden-wuerttemberg`,
`thueringen`).

## Wikipedia titles

The card links the asked name to its German Wikipedia article (the links
are built in `site/config.js`). `states.json` holds the titles: `wiki`
on every state, `capital_wiki` on the 13 states whose capital the
capitals round asks (`capital_differs`), and only there. Stored exactly
as the article is titled (spaces, no redirect); `build_map.py` passes
them into `states.js` (`wiki`; `capitalWiki` on those 13 only) and stops
if one is missing, malformed (`mapgen.wiki_title_error`), duplicated, or
a `capital_wiki` sits on a capital that isn't asked; `data.test.mjs`
checks the shape and the special cases below.

Checked on 2026-11-26 against the live German Wikipedia and Wikidata
with `wiki_titles.py`, by hand: it needs the network, so neither the
build nor CI runs it (the shared part is
`shared/map-quiz/tools/wikicheck.py`):

```sh
python3 -I images/germany-quiz/tools/wiki_titles.py /tmp/ne/ne_10m_admin_1_states_provinces.geojson            # check; exit 1 on a failure
python3 -I images/germany-quiz/tools/wiki_titles.py /tmp/ne/ne_10m_admin_1_states_provinces.geojson --suggest  # propose titles from Wikidata
```

Each title must exist, be canonical (Wikipedia neither normalises nor
redirects it), not be a disambiguation page, and belong to the expected
Wikidata item: a state's Natural Earth `wikidataid` (admin-1, matched by
`iso` as the build matches it; all 16 agree), a capital's an item
Wikidata records as a current capital of the state (its P36 or the
city's P1376). Result: 29 of 29 verified (16 states, 13 capitals; all 13
capitals through the state's P36). Special cases:

- **Bremen**: the state's article is "Freie Hansestadt Bremen" (Q1209);
  "Bremen" is the city's. The quiz shows the short name and links the
  state's article.
- **Berlin, Hamburg**: one article each for city and state ("Berlin",
  Q64; "Hamburg", Q1055), the items Natural Earth gives.
- Every other state's article is titled by its short name (Bayern,
  Sachsen, Thüringen, …), every asked capital's by its name (München,
  Hannover, Düsseldorf, …).
