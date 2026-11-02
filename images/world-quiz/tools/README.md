# world-quiz tools

Offline generator for the map data. Not part of the image (the Dockerfile
copies `site/` only); its outputs are committed:

- `site/map.svg`: the net's shape (`<path id="net">`, drawn as the sea)
  and its folds (`<path id="folds">`, open lines), context land (`<path
  id="land">`, merged), then one `<path id="<ADM0_A3>">` per quiz entry
  inside `<g id="countries">`. No styling in the file: the engine's
  `style.css` and this image's `world.css` do that.
- `site/countries.js`: names, capitals, the small-state flag, projected
  marker points and ring sizes, and the map's window (`MAP`).
  `site/config.js` (hand-written) hands them and the English texts to the
  shared map-quiz engine.

Both carry a "generated, don't edit" header. Edit `countries.json` (codes,
names, capitals, flags, marker points: the single source of truth) or
`build_map.py`, then regenerate. `build_map.py` is this image's adapter;
the geometry is the shared core in `shared/map-quiz/tools/mapgen`
(`shared/map-quiz/README.md`, "Generator core: mapgen", and its
polyhedral maps).

## Regenerate

```sh
mkdir -p /tmp/ne && curl -fsSL -o /tmp/ne/ne_50m_admin_0_countries.geojson \
  https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson
python3 -I images/world-quiz/tools/build_map.py /tmp/ne/ne_50m_admin_0_countries.geojson
python3 -I images/world-quiz/tools/build_map.py /tmp/ne/ne_50m_admin_0_countries.geojson --check  # files up to date?
node images/world-quiz/tools/data.test.mjs   # this image's data and config (Node 22.12+)
```

Python 3.9+, standard library only, deterministic (`--check` compares
without writing); about 10 s. The script verifies the input's sha256
(`3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb`,
3 083 490 bytes, the file europe-quiz uses) and stops on any other file.
CI runs the node test and the generator core's tests, not `build_map.py
--check` (its input isn't committed).

## Data

[Natural Earth](https://www.naturalearthdata.com/) admin-0 countries,
1:50m, release v5.1.2 (2022-05-13), GeoJSON from the
`nvkelso/natural-earth-vector` repository: **public domain**.

## Projection

Buckminster Fuller's Dymaxion (Airocean) projection, his 1954
icosahedral version: the globe on the 20 faces of an icosahedron in
Fuller's orientation (all 12 vertices in the sea), each face mapped by
his own transformation in Robert W. Gray's exact equations (1995), laid
out as Fuller's net (faces 9 and 16 split, so the continents stay
whole). `mapgen.Polyhedral("fuller")`: the vertex coordinates and the
net follow Gray's published description (rwgrayprojects.com), checked
against d3-geo-polygon's `geoAirocean` (ISC) and against points from
Gray's own procedure in the mapgen tests; the face formulas follow
Philippe Rivière's public-domain port of Gray's equations. Each
polygon is clipped per net piece on the sphere, so a country that
crosses a fold is one shape, and nothing is cut by the net's outline
(Antarctica stays whole).

Scale: 1 map unit is about 39 km along the faces' edges (43 km
area-equivalent); the window (`0 0 1000 480.7`) is the net plus 0.8 %.
The net keeps Fuller's standard layout: north is not up (Europe points
to the lower right).

## Quiz set

197 entries (owner, 2026-11-02): the 193 UN member states, Vatican City,
Kosovo, Taiwan, and Greenland as its own entry, shown as "Greenland
(Denmark)" (`of`). Overseas parts Natural Earth files under a state stay
with it (French Guiana, Réunion and Mayotte answer France, Bonaire the
Netherlands, Svalbard Norway). Everything else is context land, one
merged grey path (`CONTEXT`, asserted, so another release with new
features stops the build): Antarctica, Palestine, Western Sahara, the
Siachen Glacier, and the dependencies and territories (Puerto Rico, New
Caledonia, the Falkland Islands, French Polynesia, the Faroe Islands,
Guernsey, Jersey, the Isle of Man, Aruba, Curaçao, Sint Maarten, …).

## Border view

The official EU/Austrian view where it differs from Natural Earth's
de-facto default layer (as europe-quiz); everything else as Natural
Earth's default layer draws it. `build_map.py` (`MERGES`, `CUTS`)
changes, and point checks (`VIEW_CHECKS`, 68) assert on every run:

- **Crimea → Ukraine**: the Russia polygon containing Simferopol moves to
  Ukraine. Checked: Simferopol, Sevastopol; Donetsk, Luhansk, Melitopol
  and Kherson are Ukraine in the source already.
- **Northern Cyprus → Cyprus** (merged, border dissolved). Checked:
  Kyrenia, Famagusta, northern Nicosia. The file has no Sovereign Base
  Areas or buffer zone at 1:50m: Akrotiri and Dhekelia are inside
  Cyprus's outline (checked).
- **Somaliland → Somalia** (merged). Checked: Hargeisa, Berbera.
- **Åland → Finland** (merged). Checked: Mariehamn.
- **Hong Kong and Macao → China** (merged, as east-asia-quiz). Checked:
  the New Territories, Macao.
- **Golan Heights → Syria**: the part of Natural Earth's Israel outline
  east of 35.64°E (the Jordan River and Sea of Galilee line, within
  about 2 km at this scale) moves to Syria; it includes the Shebaa Farms.
  Checked: Katzrin, Majdal Shams, Quneitra, the Shebaa Farms → Syria;
  Tiberias, Kiryat Shmona, Beit She'an, Eilat → Israel.
- **Western Sahara**: Natural Earth's Morocco outline reaches south into
  Western Sahara; the part south of 27.6564°N (the parallel at its
  northern border in the file) moves to Western Sahara, context land.
  Checked: Laayoune, Smara, Aousserd → context; Rabat, Tan-Tan, Tétouan,
  Nador → Morocco.
- **Ceuta and Melilla → Spain**: inside Morocco's outline at 1:50m; cut
  out along small lon/lat boxes (`CUTS`). Checked: Ceuta, Melilla.
- **Kosovo** is its own feature and a quiz entry (checked: Pristina;
  Belgrade is Serbia); **Transnistria** is Moldova (Tiraspol, Bender);
  **Abkhazia** and **South Ossetia** are Georgia (Sukhumi, Tskhinvali);
  Stepanakert is Azerbaijan; **Taiwan** is its own quiz entry (Taipei).
- **Kashmir, Aksai Chin, Arunachal Pradesh** as Natural Earth's default
  layer (as east-asia-quiz): Srinagar and Leh India, Muzaffarabad and
  Gilgit Pakistan, Aksai Chin China, Tawang and Itanagar India. The
  **Siachen Glacier** is its own feature (`KAS`): context land.
- **Palestine** (the West Bank and Gaza; Ramallah, Gaza checked) is
  context land. At 1:50m the West Bank outline covers all of Jerusalem.
- Also as the file has them (checked): Baikonur Kazakhstan, Guantánamo
  Bay Cuba (no separate base at 1:50m), Kaliningrad and the Kuril
  Islands (Iturup, Kunashir) Russia, the Hala'ib Triangle Egypt, Bir
  Tawil, Abyei and Kafia Kingi Sudan, the Ilemi Triangle Kenya, the
  Essequibo Guyana, the Falkland Islands context land.
- Not in the file at 1:50m, checked as empty boxes (`EMPTY`): the
  Paracel and Spratly Islands, Scarborough Shoal, Pratas, the Senkaku
  Islands, the Liancourt Rocks, Bajo Nuevo and Serranilla Banks, Abu
  Musa and the Tunbs. Gibraltar has no polygon either. A source that
  has them stops the build until they are decided.

## Names and capitals

English short forms in the style of the EU Interinstitutional Style
Guide, diacritics kept, consistent with europe-quiz, south-america-quiz
and east-asia-quiz (Türkiye, Czechia, Cabo Verde, Côte d'Ivoire,
Eswatini, North Macedonia, Timor-Leste, Myanmar, Congo and Democratic
Republic of the Congo, Vatican City, United States). Choices where a
state has more than one capital, or none:

- **Bolivia: Sucre / La Paz** (constitutional capital / seat of
  government; both asked, as south-america-quiz).
- **South Africa: Pretoria**, the seat of the executive (Cape Town:
  legislature, Bloemfontein: judiciary).
- **Netherlands: Amsterdam**, the constitutional capital (The Hague: seat
  of government), as europe-quiz.
- **Côte d'Ivoire: Yamoussoukro**, the official capital (Abidjan: the
  economic centre and seat of most institutions).
- **Benin: Porto-Novo**, the official capital (Cotonou: seat of
  government).
- **Sri Lanka: Sri Jayewardenepura Kotte**, the official capital and
  seat of parliament (Colombo: the commercial capital).
- **Eswatini: Mbabane**, the administrative capital (Lobamba: royal and
  legislative).
- **Tanzania: Dodoma** (Dar es Salaam: the largest city).
- **Burundi: Gitega**, the political capital since 2019 (Bujumbura: the
  economic capital).
- **Malaysia: Kuala Lumpur** (Putrajaya: seat of government), as
  east-asia-quiz.
- **Nauru: Yaren**, the district with the seat of government (no
  official capital).
- **Kiribati: South Tarawa**.
- **Equatorial Guinea: Ciudad de la Paz**, the capital since Decree-Law
  1/2026 of January 2026 (Malabo before):
  [Financial Afrik, 2026-01-06](https://www.financialafrik.com/en/2026/01/06/equatorial-guinea-officially-changes-its-capital/).
- **Indonesia: Jakarta**, **Myanmar: Naypyidaw**, **Palau: Ngerulmud**,
  **Taiwan: Taipei**, as east-asia-quiz (reasons there).
- **Switzerland: Bern**, **Montenegro: Podgorica**, **Kosovo: Pristina**,
  as europe-quiz. **Yemen: Sanaa**, **Kazakhstan: Astana**.
- **Israel: no capital** (`capital: null`): not asked in the capital
  rounds, still there as a misclick ("Israel").
- Same-name capitals are asked as europe-quiz asks them (Luxembourg,
  Monaco, San Marino, Vatican City, Singapore, Djibouti).

## Small states and rings

The 35 **small states** (`small: true`): land area under 1,000 km², or
no land border and under 30,000 km², both measured on Natural Earth's
geometry (areas on the sphere; a land border = a vertex shared with
another of the file's own features, before the border-view fix-ups).
`build_map.py` computes the rule and stops if a flag disagrees. They are
inert in the countries and capitals rounds (drawn as context, never
hit, no ring) and asked, with rings, in "All countries" and "All
capitals": Andorra, Antigua and Barbuda, Bahamas, Bahrain, Barbados,
Cabo Verde, Comoros, Dominica, Fiji, Grenada, Jamaica, Kiribati,
Liechtenstein, Maldives, Malta, Marshall Islands, Mauritius, Micronesia,
Monaco, Nauru, Palau, Saint Kitts and Nevis, Saint Lucia, Saint Vincent
and the Grenadines, Samoa, San Marino, São Tomé and Príncipe,
Seychelles, Singapore, Solomon Islands, Tonga, Trinidad and Tobago,
Tuvalu, Vanuatu, Vatican City.

**Rings**: every small state, and every state whose largest polygon is
under 4 map units (`RING_SIZE`), so in every round: Brunei, Cyprus,
Kosovo, Luxembourg, Montenegro, Qatar. The build checks that exactly
these have a `marker`. Marker points are curated (on the main island or
near the capital); a ring's `size` is the larger side of the bounding
box of the polygon it sits on (the island, not the archipelago), so it
stays until that island is about 28 px across. `view.maxScale` 60: at
the closest zoom most small states are shapes to tap (Malta about
30 px); Vatican City, Monaco, Nauru, Tuvalu and San Marino keep their
rings even there.

## Far-flung parts

A net cuts the globe open, so a few islands land far from their state on
the map. Rule (`FAR_*`): a polygon whose distance from its state's main
polygon in the net is more than twice its distance on the globe plus
500 km is cut off; cut-off polygons close together form a group; a
group under 1 % of the state's area is dropped. The build asserts what it
drops: New Zealand's Chatham and Pitt Islands and the two Tokelau atolls
(which Natural Earth files under New Zealand), and an islet of Fiji
west of the cut through 180° (around 174.6°E 21.7°S). Kiribati's Gilbert
Islands are cut off from Kiritimati too, but they are a third of its
area: kept, as are all other states' parts.

## Map geometry

- Natural Earth cuts land at 180° (Chukotka, Wrangel Island, Fiji,
  Antarctica): `mapgen.stitch_antimeridian` matches the two sides, so the
  parts merge.
- Vertices snap to a 0.01-unit grid (`GRID` 100, about 430 m). Douglas-
  Peucker on the shared arcs: 0.12 units for states (`REGION_TOL`), 0.01
  for ringed states (`RING_TOL`, people zoom in on them), 0.25 for
  context land; unshared islands under 0.15 units² (about 280 km²) are
  dropped except for ringed states. Arcs in a crossing are simplified
  again with half the tolerance until there are none (`repair_crossings`;
  the build requires 0).
- Sizes: map.svg about 209 KB, 93 KB as served (gzip -1); countries.js
  14 KB. The report prints the figures.
- `<path id="net">` and `<path id="folds">` come first, so the folds show
  over the sea only; `world.css` colours the page outside the net
  (`--sea`, also the theme colour) apart from the sea inside it
  (`--net-sea`).
