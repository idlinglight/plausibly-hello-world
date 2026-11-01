# japan-quiz tools

Offline generator for the map data. Not part of the image (the Dockerfile
copies `site/` only); its outputs are committed:

- `site/map.svg`: one `<path>` per map piece inside `<g id="pieces">`,
  `<path id="land">` (all context land, merged), and in
  `<g id="overlays">` the shaded relief (`<image id="relief"
  href="relief.png">`, first), Lake Biwa (`lakes`, water) and four line
  overlays (open paths, stroke only): `coast-main`, `coast-isles`,
  `borders-prefectures`, `borders-regions`. No styling in the file: the
  engine's `style.css` (and the image's `japan.css`) does that.
- `site/japan.js`: the map's window/extent (`MAP`), the pieces (`PIECES`)
  and the answers of the rounds with the pieces each covers and their
  texts: `ISLANDS` (4), `REGIONS` (8), `PREFECTURES` (47).
  `site/config.js` (hand-written) hands them and the English texts to
  the shared map-quiz engine: the rounds' answers, which line overlays
  each round shows, the card's kanji · kana line.
- `site/relief.png`: the shaded relief over the window (below, "Relief").

The first two carry a "generated, don't edit" header. Edit `prefectures.json`
(names, kanji, kana, capitals, regions, islands: the single source of
truth) or `build_map.py`, then regenerate.

`build_map.py` is this image's adapter: Natural Earth, the fix-ups, the
split into pieces, the window, the quiz data and the relief. The geometry (projection,
clipping, shared borders, simplification, boundary lines, SVG writing,
`--check`) is the shared core in `shared/map-quiz/tools/mapgen`
(`shared/map-quiz/README.md`), which the script imports from there.

## Regenerate

```sh
mkdir -p /tmp/ne && for f in ne_10m_admin_1_states_provinces ne_50m_admin_0_countries ne_10m_lakes; do
  curl -fsSL -o /tmp/ne/$f.geojson \
    https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/$f.geojson
done
# ETOPO 2022 subset (59 MB; ERDDAP answers 503 now and then, hence the retries)
curl -fsS --retry 8 --retry-delay 30 --retry-all-errors -o /tmp/ne/etopo_2022_30s_japan.asc \
  'https://coastwatch.pfeg.noaa.gov/erddap/griddap/ETOPO_2022_v1_15s.esriAscii?z%5B(24.0):2:(45.75)%5D%5B(122.75):2:(146.0)%5D'
python3 -I images/japan-quiz/tools/build_map.py /tmp/ne/ne_10m_admin_1_states_provinces.geojson \
  /tmp/ne/ne_50m_admin_0_countries.geojson /tmp/ne/ne_10m_lakes.geojson /tmp/ne/etopo_2022_30s_japan.asc
python3 -I images/japan-quiz/tools/build_map.py /tmp/ne/ne_10m_admin_1_states_provinces.geojson \
  /tmp/ne/ne_50m_admin_0_countries.geojson /tmp/ne/ne_10m_lakes.geojson /tmp/ne/etopo_2022_30s_japan.asc \
  --check   # files up to date?
node images/japan-quiz/tools/data.test.mjs   # this image's data and config (Node 22.12+)
```

The engine's own tests (quiz rules, config contract, wheel replay) and
the generator core's live in `shared/map-quiz/tools/`; CI runs them all
(`.github/workflows/shared-sync.yml`), not `build_map.py --check` (its
inputs aren't committed).

Python 3.9+, standard library only (about 10 s). The script verifies its
four inputs and stops on any other file:

| File | Bytes | sha256 |
| --- | --- | --- |
| `ne_10m_admin_1_states_provinces.geojson` | 40 726 851 | `22d0e3ad85eb3e27f17cabf8ba2d50e554fbc27a87796ff891d958185da62fb5` |
| `ne_50m_admin_0_countries.geojson` | 3 083 490 | `3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb` |
| `ne_10m_lakes.geojson` | 5 043 554 | `2d036f53dedec578001c5c30c2959ee7d4eebc1306900fa4367c49929ec8f2d9` |
| `etopo_2022_30s_japan.asc` | 59 353 552 | `f94b68ad855dce74e481030a2f73264534bfbfd89f82743964bf7b6c7735ff3c` |

(The second is the file europe-quiz pins.) Output is deterministic:
re-running gives byte-identical files (`--check` compares without
writing; for `relief.png` it compares the decoded pixel data when the
bytes differ, as another zlib build may compress the same pixels
differently). It prints sizes (raw, gzip -1 as nginx serves it, gzip -9)
and what it moved, dropped and checked.

## Data

[Natural Earth](https://www.naturalearthdata.com/) release v5.1.2
(2022-05-13), GeoJSON from the `nvkelso/natural-earth-vector`
repository. Natural Earth is **public domain**; no attribution required
(it's credited here anyway).

- Prefectures: admin-1 states/provinces, 1:10m, the 47 features with
  `adm0_a3` JPN, matched by `iso_3166_2` (`prefectures.json` `iso`); the
  build checks Natural Earth's `name` against `ne_name`. The borders are
  exact shared edges. Natural Earth's own `region` / `region_cod` fields
  are unreliable for Japan and not used: regions come from
  `prefectures.json`.
- Context land: admin-0 countries, 1:50m, everything except Japan (drawn
  from admin-1) and the Kuril islands (below).
- Lakes: Lake Biwa (`ne_id` 1159115641) from lakes, 1:10m, the only
  Japanese lake in that file (Kasumigaura isn't in it). The build checks
  that it lies inside Shiga; it is drawn as the `lakes` overlay above the
  pieces, see-through: a click on it picks Shiga (not a blocking overlay).

At 1:10m the coast is generalised to steps of roughly 1–2 km: fine up to
about 6 px per map unit (1 unit ≈ 2.2 km), visibly angular at the
engine's default closest zoom of 12 (`config.view.maxScale` is 6). Some
small islands are missing from the source (e.g. Kōzushima, Teuri,
Yagishiri, Awashima, Hateruma). Lakes are not cut out of the prefectures
(Lake Biwa is part of Shiga's shape; the overlay draws the water above
it).

Elevation: [ETOPO 2022](https://www.ncei.noaa.gov/products/etopo-global-relief-model)
v1, NOAA National Centers for Environmental Information (NCEI): a 15"
global relief model of land and sea floor. Cite as: NOAA
National Centers for Environmental Information, 2022: ETOPO 2022 15
Arc-Second Global Relief Model, doi:10.25921/fd45-gt74. A work of the
U.S. government; the dataset's licence note says it "may be used and
redistributed for free but is not intended for legal use, since it may
contain inaccuracies" (no warranty). No attribution required on the page
(credited here). The pinned file is a subset from CoastWatch's ERDDAP
(dataset `ETOPO_2022_v1_15s`): every second cell, i.e. 30" (about
0.9 km north–south, 0.65–0.85 km east–west here), of 24.0–45.75°N,
122.75–146.0°E, as ESRI ASCII
grid (2791 × 2611 cells, cell centres, rows from north to south, values
in metres). ERDDAP writes no timestamp into this format: repeated
downloads (2026-11-01) were byte-identical, so it pins by sha256 like the
Natural Earth files. Not committed (59 MB).

## Fix-ups

Natural Earth files a few islands under the wrong prefecture, and Tōkyō
reaches some 1,850 km into the Pacific (Minami-Torishima).
`build_map.py` (`MOVES`, `DROPS`, `ATTACHED`, `KURILS`) fixes that up;
each rule must match exactly the expected number of parts, and point
checks (`VIEW_CHECKS`, `KURIL_CHECKS`) assert the result on every run:

- **Amami islands → Kagoshima**: Okinawa's parts north of 27.0°N and
  east of 128.3°E (Amami Ōshima, Kakeromajima, Kikaijima, Tokunoshima,
  Okinoerabujima, Yoronjima: 6 parts). Iheyajima and Iōtorishima, just
  west of that line, stay in Okinawa.
- **Nagashima and Shishijima → Kagoshima**: filed under Kumamoto, both
  belong to Nagashima town, Kagoshima.
- **Ogasawara dropped**: Tōkyō's parts south of 29°N (12 parts: the
  Bonin islands and Nishinoshima, about 1,000 km south of Tokyo; the Iwo
  islands, about 1,250 km; Minami-Torishima, about 1,850 km south-east)
  would stretch the map by a whole ocean for a few specks. The Izu
  islands down to Torishima (about 580 km) stay.
- **Specks**: parts below 0.5 km² are dropped: 12 rocks and islets
  (Sumisu-tō, the Kusagaki islands, the smaller Senkaku islets, a few
  nameless ones), a few pixels at most even at the closest zoom.
- **Spits**: the Notsuke and Saroma lagoon spits, which Natural Earth
  draws 1–2 km off Hokkaidō, belong to Hokkaidō's main piece (they are
  sandbars of the main island, not islands).
- **Kuril islands**: not drawn. The Southern Kurils (Northern
  Territories) are neither clickable nor Japanese-administered, and the
  rest of the chain would begin mid-sea without them: Natural Earth's
  RUS parts inside 145–157°E, 43–51°N (14 parts at 1:50m) are left out of
  the context land; Sakhalin and Kamchatka stay.

Not changed: the Senkaku islands stay part of Okinawa as in Natural
Earth (Japan administers them, the same rule that leaves the Kurils out;
Uotsuri-jima and Kuba-jima are above the speck limit, the rest are
specks). Takeshima is not in Natural Earth's JPN features, nor in the
1:50m admin-0 file.

## Pieces

The quiz asks islands, regions and prefectures, so the map is cut into
pieces that each answer is a set of (`japan.js`):

- **Main piece**, id = the prefecture's id (`niigata`): its parts on its
  main island (`prefectures.json` `island`). The main island is the
  connected landmass (parts sharing a border edge; a single shared
  vertex doesn't join) that holds the largest part of each of its
  prefectures; the build checks that the four landmasses hold exactly
  the expected prefectures.
- **`<id>-isles`** (`niigata-isles`): all other parts of the prefecture,
  merged into one piece (17 prefectures, e.g. Sado, Awaji, Oki, Tsushima,
  Gotō, Amakusa, Yakushima, the Izu islands; also the airport islands of
  Kansai and Chūbu Centrair). They lie on none of the four main islands,
  so the islands round leaves them inert.
- **Okinawa** is one piece, `okinawa` (`island` null).

64 pieces in all. Every piece keeps all its islands (`keep_islands`):
none is lost to the grid, which the line overlays need.

## Map geometry

- Projection: Lambert azimuthal equal-area centred on 35°N 135°E, GRS80.
  135°E is Japan's standard meridian and runs through the middle of the
  map, so north is up there; equal-area keeps prefecture sizes
  comparable across the nearly 2,900 km from Hokkaidō to Yonaguni.
- Window (the full view, `0 0 1000 1097`): the bounding box of all
  pieces plus 3 % margin, so Okinawa sits at its real position (no
  inset).
- Extent (the viewBox): the window plus 50 % / 35 % of its width / height
  per side of context land (Korea, China, Russia's Far East, Taiwan), so
  wide and tall screens show map instead of an empty band (the page fades
  it out at the edge).
- Shared borders: vertices snap to a 0.1-unit grid; parts of one piece
  merge by cancelling shared segments; borders become shared arcs, so
  neighbours use identical vertices.
- Simplification: none for pieces. Context-only arcs get Douglas-Peucker
  0.2 units near the window and 1.5 units outside it.
- Line overlays (`mapgen.boundary_lines` on the shared arcs, never
  simplified on their own; each edge in one overlay only): `coast-main` =
  the outline of the main pieces (the four main islands), `coast-isles` =
  the outline of all other pieces, `borders-regions` = the land borders
  between two regions, `borders-prefectures` = the other land borders
  between two prefectures (the rounds that show it show
  `borders-regions` too).
  The four main islands share no land border, so there is no
  `borders-islands` (the build checks it).

## Relief

`site/relief.png` shades the terrain so plains and mountains can be told
apart (Kantō, Nōbi and the Kinki basins flat, the Japan Alps and the
backbone ranges rugged). `build_map.py`, `RELIEF_*`:

- Grid: 2.5 px per map unit (`RELIEF_PPU`; 2500 × 2743 px over the
  window `0 0 1000 1097.2`), about the 30" cells, so it stays sharp at the
  closest zoom (6 px/unit). Each pixel centre goes back to lon/lat by the
  inverse of the map's projection (Snyder's ellipsoidal LAEA, in the
  adapter; a round trip is checked on every run), its elevation is
  bilinear between the ETOPO cell centres; sea values count as 0 m, so
  the coast doesn't shade against the sea floor.
- Shading: Horn's gradient, vertical exaggeration 5 (`RELIEF_Z`), light
  from the top left (azimuth 315°, 45° high). Darkness = 0.8 × how far
  the slope faces away from the light + 0.9 × its steepness, up to black
  at alpha 0.55 (`RELIEF_DARK`); slopes facing the light get white up to
  alpha 0.3 (`RELIEF_LIGHT`); flat land stays transparent. 32 alpha steps
  (`RELIEF_LEVELS`).
- Mask: only on the pieces (Japan's land), from their drawn rings (the
  shared arcs), with exact coverage along 4 scanlines per pixel row, so
  the shading fades out across the coast pixel instead of spilling into
  the sea; context land and sea stay transparent.
- File: an 8-bit palette PNG (transparent, black or white with alpha;
  ~330 KB; decoded 2500 × 2743 × 4 ≈ 27 MB in the browser), no time or
  text chunks. In `map.svg` it is `<image id="relief" href="relief.png">`
  first in `<g id="overlays">`: above the pieces, below Lake Biwa and the
  lines; `#overlays` is never hit, so a tap on a mountain picks the piece
  beneath. `japan.css` draws it with plain alpha (`--relief-opacity`,
  softer in dark mode). No blend mode: the sea is the page background
  outside the inline SVG's own compositing group, so `multiply` would
  have nothing to blend with there and leave a light fringe along the
  coasts.
- Choices (2026-11-01): shaded relief rather than elevation bands
  (contours as tinted overlays; the owner's pick from previews of both);
  2.5 px/unit as the finest that stays around 350 KB (1.5: 115 KB, soft
  at the closest zoom; 3.0: 470 KB).

## Names and readings

`prefectures.json` has every name in Hepburn with macrons (Tōkyō,
Kyōto, Ōsaka, Hyōgo, Kōchi, Ōita; capitals Kōbe, Kōfu, Ōtsu; Honshū,
Kyūshū; Tōhoku, Kantō, Chūbu, Chūgoku) and, for the card's second line,
kanji and hiragana: prefectures without the generic suffix (青森 ·
あおもり, 東京 · とうきょう) but whole where it is part of the name
(北海道 · ほっかいどう), capitals without 市 / 区 (札幌 · さっぽろ, 新宿 ·
しんじゅく), islands (本州 · ほんしゅう) and regions (東北 · とうほく,
関西 · かんさい). Kanji and kana were cross-checked on 2026-11-01 against
Wikidata (Japanese labels, P1814 "name in kana"), the first sentence of
each Japanese Wikipedia article and English Wikipedia's "List of regions
of Japan" (every reading confirmed by at least two of them; that list's
ぎふけん for Gifu is a slip, the other two say ぎふ). The build also
reads every kana back into Hepburn and fails on a mismatch with the
name (long vowels per syllable: おお, おう → ō, うう → ū; お + う across a
morpheme boundary, as in いのうえ, would need an entry in `OU_SPLIT`,
none does today).

Choices the quiz makes: the eight standard regions, Okinawa in Kyūshū.
The region the official division calls Kinki (近畿 · きんき, which
includes Mie) goes by its common name on purpose: Kansai (関西 ·
かんさい), the usual English name and the title of Wikipedia's article;
its extent is Kinki's, Mie included. Tōkyō's capital is Shinjuku (seat
of the metropolitan government), so `capital_differs` marks 18
prefectures (17 + Tōkyō).
