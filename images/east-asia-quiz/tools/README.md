# east-asia-quiz tools

Offline generator for the map data. Not part of the image (the Dockerfile
copies `site/` only); its outputs are committed:

- `site/map.svg`: one `<path id="<ADM0_A3>">` per quiz country inside
  `<g id="countries">`, plus `<path id="land">` (all context land, merged).
  No styling in the file: the engine's `style.css` does that.
- `site/countries.js`: names, capitals, projected marker points, and the
  map's window/extent (`MAP`). `site/config.js` (hand-written) hands it
  and the English texts to the shared map-quiz engine.

Both carry a "generated, don't edit" header. Edit `countries.json` (codes,
names, capitals, marker points: the single source of truth) or
`build_map.py`, then regenerate.

`build_map.py` is this image's adapter: Natural Earth, the fix-ups, the
window and the quiz set. The geometry (projection, clipping, shared
borders, simplification, SVG writing, `--check`) is the shared core in
`shared/map-quiz/tools/mapgen` (`shared/map-quiz/README.md`), which the
script imports from there.

## Regenerate

```sh
mkdir -p /tmp/ne && curl -fsSL -o /tmp/ne/ne_50m_admin_0_countries.geojson \
  https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson
python3 -I images/east-asia-quiz/tools/build_map.py /tmp/ne/ne_50m_admin_0_countries.geojson
python3 -I images/east-asia-quiz/tools/build_map.py /tmp/ne/ne_50m_admin_0_countries.geojson --check  # files up to date?
node images/east-asia-quiz/tools/data.test.mjs   # this image's data and config (Node 22.12+)
```

The engine's own tests (quiz rules, config contract, wheel replay) and
the generator core's live in `shared/map-quiz/tools/`; CI runs them all
(`.github/workflows/shared-sync.yml`), not `build_map.py --check` (its
input isn't committed).

Python 3.9+, standard library only. The script verifies the input's sha256
(`3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb`,
3 083 490 bytes: the file europe-quiz pins) and stops on any other file.
Output is deterministic: re-running gives byte-identical files (`--check`
compares without writing). It prints sizes (raw, gzip -1 as nginx serves
it, gzip -9) and what it merged, dropped and checked.

## Data

[Natural Earth](https://www.naturalearthdata.com/) admin-0 countries,
1:50m, release v5.1.2 (2022-05-13), GeoJSON from the
`nvkelso/natural-earth-vector` repository. Natural Earth is **public
domain**; no attribution required (it's credited here anyway).

1:50m has every quiz country, Singapore and Palau included; the whole
map.svg is about 121 KB (49 KB as served, gzip -1). Singapore is one
coarse polygon (about 5.6 × 2.8 units), Palau one for Babeldaob and its
neighbours. Small islands this scale does not have: Penghu and Matsu
(Taiwan has its main island and Kinmen), the Senkaku islands, the
Liancourt Rocks, Pratas, and every reef and islet of the South China Sea
(the Paracel and Spratly islands, Scarborough Shoal). The build checks
the last (`EMPTY`: no polygon meets the boxes around the Paracels, the
Spratlys, Scarborough Shoal and Pratas, not even with an edge passing
through without a vertex inside), so a source that has them stops
the build until they are handled on purpose: as non-clickable context
land, not assigned to a quiz country. Of the Ogasawara islands only
Hahajima is in the file (a speck about 1,000 km south of Tokyo, inside
the window, drawn as part of Japan); of the Izu islands, Ōshima and
Hachijōjima.

## Fix-ups

`build_map.py` (`MERGES`, `DROPS`) changes two things about what is
whose (the antimeridian stitch, which only joins Natural Earth's cut
parts, is under "Map geometry"); point checks (`VIEW_CHECKS`) assert the
result on every run:

- **Hong Kong and Macao → China**: Natural Earth has them as separate
  features (`HKG`, `MAC`); both merge into `CHN`, the shared borders
  dissolved. Checked: the New Territories, Hong Kong Island, Lantau,
  Macao, Shenzhen.
- **Tobi dropped**: Palau's second polygon is Tobi (Southwest Islands), a
  17 km² blob at this scale for an island of well under 1 km², some
  500 km from the main islands. Kept, it would make Palau's bounding box
  (the ring's `size`) 70 units instead of 6, and the ring would hide at
  every full view.

Everything else is as Natural Earth's default layer (de facto control)
draws it, checked by points:

- Taiwan is its own feature and a quiz country (`TWN`: the main island
  and Kinmen); Xiamen island next to Kinmen is China.
- China–India: Aksai Chin is in China, Arunachal Pradesh (Tawang,
  Itanagar) in India. The Siachen Glacier is its own feature (`KAS`), part
  of the context land like India and Pakistan.
- The Kuril islands (Kunashiri and Iturup checked) and Sakhalin are part
  of Russia, context land. (japan-quiz leaves the Kurils out because
  there they would stretch the window; here they lie inside the drawn
  context anyway.)
- Western New Guinea (Jayapura checked) is Indonesia; Timor-Leste is the
  eastern half of Timor with Oecusse (checked) and Atauro, West Timor
  (Kupang checked) Indonesia.
- Hahajima (Ogasawara) is Japan; Tobi has no land left.

Context land (one merged, non-interactive path): every other polygon
that reaches the extent (below), from Sweden, the Baltic states and
Moscow in the north-west, Türkiye and Arabia in the west, Russia incl.
the Kuril islands and Chukotka across 180° to Alaska in the north-east,
to India, Papua New Guinea, Australia and New Zealand; Guam, the
Northern Mariana Islands and Micronesia in the Pacific.

## Names and capitals

English short forms per the EU Interinstitutional Style Guide (as
europe-quiz), plain ASCII: Brunei, Cambodia, China, Indonesia, Japan,
Laos, Malaysia, Mongolia, North Korea, South Korea, Philippines,
Singapore, Thailand, Timor-Leste, Vietnam, Palau. Choices:

- **Myanmar**, not the guide's double name "Myanmar/Burma": the first
  part, the country's own English short name (also Natural Earth's and the
  UN's). Capital **Naypyidaw** (the guide's spelling; also written Nay Pyi
  Taw).
- **Taiwan**, capital **Taipei**: the common English names (the guide's
  country list has no entry for Taiwan).
- **Tokyo** without a macron (an English world-style quiz, unlike
  japan-quiz's Tōkyō); **Ulaanbaatar**.
- **Indonesia: Jakarta.** The capital is moving to Nusantara (Law 3/2022
  on the State Capital), but the transfer takes effect only with a
  presidential decree, which has not been issued as of 2026-11-02. The
  Constitutional Court confirmed on 12 May 2026 (decision
  71/PUU-XXIV/2026) that Jakarta remains the capital until then:
  [Jakarta Globe, 2026-05-13](https://jakartaglobe.id/news/constitutional-court-confirms-jakarta-still-indonesias-capital-not-nusantara).
  Re-check when the decree comes.
- **Malaysia: Kuala Lumpur**, the capital; Putrajaya is the
  administrative centre (seat of government).
- **Palau: Ngerulmud**, the seat of government in Melekeok State since
  2006 (some lists give Melekeok).
- **Singapore**: capital Singapore. Same-name capitals are asked like
  europe-quiz asks Luxembourg or Monaco ("Find the country whose capital
  is Singapore").

## Rings

`countries.json` `marker` (curated points, roughly the middle of the
main land): **Singapore**, **Palau**, **Brunei**, **Timor-Leste**. A ring
shows while its country is under 28 px across: Singapore (5.6 units),
Palau (5.9) and Brunei (20.3) at every full view; Timor-Leste (52.6 units,
long and narrow: about 19 × 8 px on a 390 px phone) on phones only, at
desktop sizes it is tappable as it is and its ring hides. Markered
countries keep every island.

## Map geometry

- Projection: Lambert azimuthal equal-area centred on 20°N 110°E
  (GRS80), the middle of the set: north is up through the middle of the
  window, and areas stay comparable from Mongolia to Timor.
- Window (the full view, `0 0 1000 1068.7`, 1 unit ≈ 7 km): the bounding
  box of all quiz geometry plus 3 % margin. Its edges: China in the west
  (Xinjiang, 74.4°E) and north (53.6°N), Indonesia in the east (the
  border with Papua New Guinea, 141°E) and south (Rote, 10.9°S). Every
  part of every quiz country counts, so nothing is clipped and there are
  no remote parts (at 1:50m nothing is far enough out to need one; a
  source with, say, Minami-Torishima would widen the window: give it a
  `REMOTE` rule then, as europe-quiz has).
- Extent (the viewBox, `-450 -480.9 1900 2030.5`): the window plus 45 %
  of its width and height per side of context, so wide and tall screens
  show map instead of an empty band (the page fades it out at the edge).
  Its corners lie about 100° (great circle) from the projection centre:
  Sweden at the top left, Alaska at the top right, Arabia on the left,
  New Zealand at the bottom right.
- Context selection: a polygon is drawn when its projected bounding box
  overlaps the extent (a lon/lat box can't describe this extent). A
  polygon reaching more than 150° from the centre (`FAR_SIDE`: towards
  the antipode in South America, where the projection wraps around) is
  skipped; the build checks that its nearer vertices all lie outside the
  extent. `CONTEXT_CHECKS` asserts drawn context land at 17 points all
  around it (Sweden, Estonia, Latvia, Lithuania, Moscow, Türkiye, Saudi
  Arabia, Delhi, Kamchatka, Chukotka on both sides of 180°, St. Lawrence
  Island, Alaska, Papua New Guinea, the Northern Territory, Tasmania, New
  Zealand), so a selection that loses land inside the extent fails.
- Antimeridian: Natural Earth cuts Chukotka and Wrangel Island at 180°
  into two polygons each, with different vertices along the cut (one long
  edge on one side, a vertex every 0.24° on the other), which mapgen's
  merge (cancelling identical segments) would leave as a drawn line. The
  adapter moves vertices within 0.0001° of the cut onto it and gives
  every edge along it the other side's vertices; `SEAMS` checks that no
  drawn edge runs along 180° inside either land afterwards.
- Window sides: after the build, the drawn quiz geometry (and the
  markers) must still reach each side of the window where the margin puts
  it (within 0.5 units), so a dropped island can't leave a side set by
  nothing visible.
- Shared borders: vertices snap to a 0.1-unit grid; parts of one country
  merge by cancelling shared segments; borders become shared arcs, so
  neighbours use identical vertices (no slivers or gaps).
- Simplification: none for quiz countries. Context-only arcs get
  Douglas-Peucker 0.2 units near the window and 1.5 units outside it,
  where context is only ever seen small; small context islands outside
  the window are dropped. The report's 19 arc crossings: 18 in context
  land (from that simplification), 1 a kink in Natural Earth's own Taiwan
  outline near Kaohsiung (about 0.1 unit, below a pixel even at the
  closest zoom).

## View options (`site/config.js`)

- `besideHud: true`: Japan reaches the window's top-right corner, where
  the card sits in landscape (on a phone held sideways it would cover
  Hokkaidō and Tōhoku), so the full view fits left of the card and the
  controls.
- `maxScale`: the engine's default (12 px per unit at the closest zoom):
  Singapore about 67 × 34 px there, Palau 25 × 71 px, both tappable as
  shapes.
