# europe-quiz tools

Offline generator for the map data. Not part of the image (the Dockerfile
copies `site/` only); its outputs are committed:

- `site/map.svg`: one `<path id="<ADM0_A3>">` per quiz country inside
  `<g id="countries">`, plus `<path id="land">` (all context land, merged).
  No styling in the file: `site/style.css` does that.
- `site/countries.js`: names, capitals, projected marker points, and the
  map's window/extent (`MAP`).

Both carry a "generated, don't edit" header. Edit `countries.json` (codes,
names, capitals, marker points: the single source of truth) or
`build_map.py`, then regenerate.

## Regenerate

```sh
mkdir -p /tmp/ne && curl -fsSL -o /tmp/ne/ne_50m_admin_0_countries.geojson \
  https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson
python3 -I images/europe-quiz/tools/build_map.py /tmp/ne/ne_50m_admin_0_countries.geojson
python3 -I images/europe-quiz/tools/build_map.py /tmp/ne/ne_50m_admin_0_countries.geojson --check  # files up to date?
node images/europe-quiz/tools/quiz.test.mjs   # checks of site/quiz.js (Node 22.12+)
node images/europe-quiz/tools/wheel.test.mjs  # site/wheel.js against recorded wheel events
```

Python 3.9+, standard library only. The script verifies the input's sha256
(`3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb`,
3 083 490 bytes) and stops on any other file. Output is
deterministic: re-running gives byte-identical files (`--check` compares
without writing). It prints sizes (raw, gzip -1 as nginx serves it, gzip -9)
and what it clipped, merged and dropped.

## Data

[Natural Earth](https://www.naturalearthdata.com/) admin-0 countries,
1:50m, release v5.1.2 (2022-05-13), GeoJSON from the
`nvkelso/natural-earth-vector` repository. Natural Earth is **public
domain**; no attribution required (it's credited here anyway).

1:50m has every quiz country, microstates included; the whole map.svg is
about 115 KB (47 KB as served, gzip -1). The Vatican snaps to a 0.2-unit
speck on the 0.1-unit grid (still its own shape, drawn on top of Italy); a
country that vanished entirely would fall back to its outline at a 10x finer
grid. At this scale Natural Earth's Vatican sits 1–2 km west of the real
one, so the marker rings (Vatican, Monaco, San Marino, Liechtenstein,
Andorra, Malta, Luxembourg) use curated points from `countries.json`, not
the polygons.

## Border view

The official EU/Austrian view. Natural Earth's default layer shows de-facto
control, so the generator fixes it up:

- **Crimea → Ukraine**: the default layer puts Crimea in Russia; the RUS
  polygon containing Simferopol moves to UKR.
- **Northern Cyprus → Cyprus**: `CYN` merges into `CYP` (shared border
  dissolved).
- **Åland → Finland**: `ALD` merges into `FIN` (Åland is a separate feature
  in Natural Earth, part of Finland).
- Already as wanted: Kosovo is its own feature (`KOS`), Transnistria is part
  of Moldova.

Natural Earth's 10m German point-of-view file agrees with the result. Point
checks (`VIEW_CHECKS`: Simferopol, Sevastopol, Donetsk, Luhansk, Tiraspol,
Pristina, Kyrenia, Famagusta, Mariehamn, Kaliningrad) assert it on every
run.

Context land (one merged, non-interactive path): Russia incl. Kaliningrad,
North Africa, the Middle East, the Caucasus, the Faroes, the Channel
Islands, the Isle of Man, Greenland, and everything else that isn't one of
the 46 quiz countries.

## Map geometry

- Projection: Lambert azimuthal equal-area with EPSG:3035's parameters
  (centre 52°N 10°E, GRS80), checked against EPSG's reference point.
- Window (the full view, `0 0 1000 859.1`): the bounding box of all quiz
  geometry except remote parts, plus 3 % margin. Remote parts (`REMOTE`):
  Azores, Madeira, Canary Islands, French overseas departments, Caribbean
  Netherlands, Svalbard, Jan Mayen. The script fails if any other quiz
  geometry would fall outside the window, if a country's largest polygon
  matches a remote rule, or if a rule matches nothing.
- Extent (the viewBox): the window plus 30 % / 45 % of its width / height
  per side of context, so wide and tall screens show map instead of an
  empty band (the page fades it out at the edge). Remote parts inside it
  (Svalbard, Canaries, some of the Azores) are drawn as part of their
  country; the rest is clipped.
- Shared borders: vertices snap to a 0.1-unit grid; parts of one country
  merge by cancelling shared segments; borders become shared arcs, so
  neighbours use identical vertices (no slivers or gaps).
- Simplification: none for quiz countries. Context-only arcs get
  Douglas-Peucker 0.2 units near the window and 1.5 units outside it,
  where context is only ever seen small; small context islands outside
  the window are dropped.
